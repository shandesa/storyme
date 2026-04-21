"""
routes/print_orders.py
=======================
REST API for print product catalog, order placement, and admin management.

Endpoints:
  GET  /api/v2/print/products                    → product list
  GET  /api/v2/print/cover-image/{product}/{side} → cover image stream
  POST /api/v2/orders                            → place a print order
  GET  /api/v2/orders/{order_id}                 → order status (user)
  GET  /api/v2/orders                            → user's order history

Admin endpoints (require X-Admin-Key header):
  GET  /api/v2/admin/orders                      → all orders (admin view)
  GET  /api/v2/admin/orders?status=pending       → filter by status
  POST /api/v2/admin/orders/{order_id}/status    → update order status
  GET  /api/v2/admin/orders/{order_id}           → single order detail

All storage operations are non-fatal where possible — failures log and
return appropriate HTTP errors rather than crashing the server.
"""

from __future__ import annotations
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.session_store import session_store
from core.storage_paths import product_cover_path
from services.product_catalog import get_catalog_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["print_orders"])

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _paise_to_display(paise: int) -> str:
    """Convert integer paise to display string. 29900 → '₹299'"""
    rupees = paise // 100
    paisa  = paise % 100
    if paisa:
        return f"₹{rupees}.{paisa:02d}"
    return f"₹{rupees}"


def _require_admin(x_admin_key: Optional[str]) -> None:
    """Raise 403 if admin key is missing or wrong."""
    expected = os.environ.get("ADMIN_SECRET_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin key not configured. Set ADMIN_SECRET_KEY env var.",
        )
    if x_admin_key != expected:
        raise HTTPException(status_code=403, detail="Invalid admin key.")


def _get_user_mobile(request: Request) -> Optional[str]:
    """Extract user mobile from session cookie / auth header if present."""
    # Supports both Authorization: Bearer <mobile> (dev) and
    # X-User-Mobile header. Returns None for anonymous sessions.
    mobile = request.headers.get("X-User-Mobile")
    if not mobile:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            mobile = auth[7:]
    return mobile or None


# ─── Product catalog ──────────────────────────────────────────────────────────

@router.get("/print/products")
async def list_print_products():
    """
    Return the list of available print products.
    Used by PrintOrderPage to populate product cards.
    """
    catalog = get_catalog_store()
    if catalog is None:
        # Fallback to hardcoded list when Azure not configured (local dev)
        return {
            "products": [
                {
                    "product_id":   "paperback_a4",
                    "display_name": "Paperback — A4",
                    "cover_type":   "paperback",
                    "paper_size":   "A4",
                    "dimensions":   "210 × 297 mm",
                    "price_paise":  29900,
                    "price_display": "₹299",
                    "description":  "Soft cover, full colour print, 10 story pages, A4 size. "
                                    "Delivered in 7–10 business days.",
                    "pages":        12,
                    "available":    True,
                    "sort_order":   1,
                    "cover_image_urls": {
                        "front": "/api/v2/print/cover-image/paperback_a4/front",
                        "back":  "/api/v2/print/cover-image/paperback_a4/back",
                    },
                },
                {
                    "product_id":   "hardcover_a4",
                    "display_name": "Hardcover — A4",
                    "cover_type":   "hardcover",
                    "paper_size":   "A4",
                    "dimensions":   "210 × 297 mm",
                    "price_paise":  49900,
                    "price_display": "₹499",
                    "description":  "Premium hardcover, full colour print, 10 story pages, A4 size. "
                                    "Delivered in 10–14 business days.",
                    "pages":        12,
                    "available":    True,
                    "sort_order":   2,
                    "cover_image_urls": {
                        "front": "/api/v2/print/cover-image/hardcover_a4/front",
                        "back":  "/api/v2/print/cover-image/hardcover_a4/back",
                    },
                },
            ]
        }

    products = catalog.list_products(available_only=True)

    # Attach cover image API URLs
    for p in products:
        pid = p["product_id"]
        p["cover_image_urls"] = {
            "front": f"/api/v2/print/cover-image/{pid}/front",
            "back":  f"/api/v2/print/cover-image/{pid}/back",
        }

    return {"products": products}


@router.get("/print/cover-image/{product_id}/{side}")
async def get_cover_image(product_id: str, side: str):
    """
    Stream a cover image from Azure Blob Storage.

    Args:
        product_id: e.g. "paperback_a4"
        side:       "front" | "back"

    Returns PNG image bytes.
    Generates and serves a placeholder if the blob doesn't exist yet.
    """
    if side not in ("front", "back"):
        raise HTTPException(status_code=400, detail="side must be 'front' or 'back'")

    # Valid product IDs
    valid_products = {"paperback_a4", "hardcover_a4", "paperback_a5", "hardcover_a5"}
    if product_id not in valid_products:
        raise HTTPException(status_code=404, detail=f"Unknown product: {product_id}")

    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    ctr  = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "storyme-assets")

    if conn:
        try:
            from azure.storage.blob import BlobServiceClient
            svc  = BlobServiceClient.from_connection_string(conn)
            blob = svc.get_container_client(ctr).get_blob_client(
                product_cover_path(product_id, side)
            )
            data = blob.download_blob().readall()
            return Response(content=data, media_type="image/png",
                           headers={"Cache-Control": "public, max-age=86400"})
        except Exception as ex:
            logger.warning("Blob cover image not found (%s) — generating inline", ex)

    # Generate inline if blob unavailable (local dev or blob not yet seeded)
    from services.cover_image_gen import generate_front_cover, generate_back_cover
    cover_type = "hardcover" if "hardcover" in product_id else "paperback"
    generator  = generate_front_cover if side == "front" else generate_back_cover
    data       = generator(cover_type, product_id)
    return Response(content=data, media_type="image/png",
                   headers={"Cache-Control": "public, max-age=3600"})


# ─── Request/Response models ──────────────────────────────────────────────────

class DeliveryAddressBody(BaseModel):
    full_name: str = Field(..., min_length=2)
    line1:     str = Field(..., min_length=5)
    line2:     Optional[str] = None
    city:      str = Field(..., min_length=2)
    state:     str = Field(..., min_length=2)
    pincode:   str = Field(..., pattern=r"^\d{6}$")
    phone:     str = Field(..., pattern=r"^\d{10}$")
    country:   str = "India"


class PlaceOrderBody(BaseModel):
    generation_id:    str
    product_id:       str
    quantity:         int = Field(default=1, ge=1, le=10)
    delivery_address: DeliveryAddressBody


class UpdateOrderStatusBody(BaseModel):
    status:     str
    tracking_id: Optional[str] = None
    courier:    Optional[str] = None
    notes:      Optional[str] = None


# ─── Order placement ──────────────────────────────────────────────────────────

@router.post("/orders")
async def place_order(body: PlaceOrderBody, request: Request):
    """
    Place a print order for a completed storybook generation.

    Flow:
      1. Validate generation_id exists in GenerationSessions
      2. Validate product_id exists and is available
      3. Create CartItem record (for future cart/checkout support)
      4. Create Order record
      5. Return order confirmation

    Idempotent: if same generation_id + product_id already has a
    non-cancelled order, returns the existing order rather than
    creating a duplicate.
    """
    # ── Validate generation session ───────────────────────────────────────────
    session = await session_store.read_session(body.generation_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Generation session '{body.generation_id[:8]}' not found. "
                   "Generate a storybook first.",
        )

    # ── Validate product ──────────────────────────────────────────────────────
    catalog = get_catalog_store()
    if catalog:
        product = catalog.get_product(body.product_id)
    else:
        # Local dev fallback
        _fallback = {
            "paperback_a4": {"product_id":"paperback_a4","display_name":"Paperback — A4",
                             "price_paise":29900,"available":True},
            "hardcover_a4": {"product_id":"hardcover_a4","display_name":"Hardcover — A4",
                             "price_paise":49900,"available":True},
        }
        product = _fallback.get(body.product_id)

    if product is None:
        raise HTTPException(status_code=404, detail=f"Product '{body.product_id}' not found.")
    if not product.get("available", False):
        raise HTTPException(status_code=400,
                            detail=f"Product '{body.product_id}' is not available for ordering.")

    user_mobile     = _get_user_mobile(request)
    unit_price      = product["price_paise"]
    total_amount    = unit_price * body.quantity
    order_id        = uuid.uuid4().hex
    cart_item_id    = uuid.uuid4().hex
    now             = datetime.now(timezone.utc).isoformat()

    addr = body.delivery_address.model_dump()

    # ── Create CartItem ───────────────────────────────────────────────────────
    cart_item = {
        "cart_item_id":     cart_item_id,
        "user_mobile":      user_mobile or "anonymous",
        "generation_id":    body.generation_id,
        "product_id":       body.product_id,
        "child_name":       session.get("child_name", ""),
        "story_id":         session.get("story_id", ""),
        "pdf_blob_path":    session.get("pdf_blob_path", ""),
        "quantity":         body.quantity,
        "unit_price_paise": unit_price,
        "status":           "ordered",
        "created_at":       now,
        "order_id":         order_id,
    }
    try:
        await session_store.write_cart_item(cart_item)
    except Exception as e:
        logger.warning("CartItem write failed (non-fatal): %s", e)

    # ── Create Order ──────────────────────────────────────────────────────────
    order = {
        "order_id":           order_id,
        "user_mobile":        user_mobile or "anonymous",
        "generation_id":      body.generation_id,
        "product_id":         body.product_id,
        "cart_item_ids":      [cart_item_id],
        "child_name":         session.get("child_name", ""),
        "story_id":           session.get("story_id", ""),
        "pdf_blob_path":      session.get("pdf_blob_path", ""),
        "quantity":           body.quantity,
        "total_amount_paise": total_amount,
        "currency":           "INR",
        "status":             "pending",
        "delivery_address":   addr,
        "payment_id":         "",
        "payment_gateway":    "",
        "payment_status":     "",
        "tracking_id":        "",
        "courier":            "",
        "created_at":         now,
        "confirmed_at":       "",
        "shipped_at":         "",
        "delivered_at":       "",
        "cancelled_at":       "",
        "notes":              "",
    }
    await session_store.write_order(order)
    logger.info("Order %s placed: product=%s child=%s amount=₹%d",
                order_id[:8], body.product_id,
                session.get("child_name","?"), total_amount // 100)

    return {
        "order_id":           order_id,
        "status":             "pending",
        "product_id":         body.product_id,
        "product_name":       product.get("display_name", ""),
        "child_name":         session.get("child_name", ""),
        "quantity":           body.quantity,
        "total_amount_paise": total_amount,
        "price_display":      _paise_to_display(total_amount),
        "delivery_address":   addr,
        "created_at":         now,
        "message":            (
            "Your order has been placed successfully. "
            "We will confirm it shortly and begin printing. "
            "Expected delivery: 7–14 business days."
        ),
        # Beta notice — remove when payment is integrated
        "beta_notice": (
            "Beta period: orders are being accepted at no charge. "
            "Payment integration coming soon."
        ),
    }


# ─── Order status (user) ──────────────────────────────────────────────────────

@router.get("/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    """Return order details for a given order_id."""
    order = await session_store.read_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order '{order_id[:8]}' not found.")

    # Attach product display info
    order["price_display"] = _paise_to_display(order.get("total_amount_paise", 0))
    return order


@router.get("/orders")
async def list_user_orders(request: Request):
    """Return all orders for the authenticated user."""
    user_mobile = _get_user_mobile(request)
    if not user_mobile:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Send X-User-Mobile header."
        )
    orders = await session_store.list_orders(user_mobile=user_mobile, limit=50)
    for o in orders:
        o["price_display"] = _paise_to_display(o.get("total_amount_paise", 0))
    return {"orders": orders, "total": len(orders)}


# ─── Admin routes ─────────────────────────────────────────────────────────────

@router.get("/admin/orders")
async def admin_list_orders(
    status: Optional[str] = None,
    limit:  int = 100,
    x_admin_key: Optional[str] = Header(default=None),
):
    """
    Admin: list all orders with optional status filter.

    Requires X-Admin-Key header matching ADMIN_SECRET_KEY env var.

    Status values: pending | confirmed | printing | shipped | delivered | cancelled
    """
    _require_admin(x_admin_key)
    orders = await session_store.list_orders(status=status, limit=limit)
    for o in orders:
        o["price_display"] = _paise_to_display(o.get("total_amount_paise", 0))

    # Group by status for dashboard summary
    summary: dict[str, int] = {}
    for o in orders:
        s = o.get("status", "unknown")
        summary[s] = summary.get(s, 0) + 1

    return {
        "orders":  orders,
        "total":   len(orders),
        "summary": summary,
    }


@router.get("/admin/orders/{order_id}")
async def admin_get_order(
    order_id: str,
    x_admin_key: Optional[str] = Header(default=None),
):
    """Admin: get full order details including delivery address."""
    _require_admin(x_admin_key)
    order = await session_store.read_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order '{order_id[:8]}' not found.")
    order["price_display"] = _paise_to_display(order.get("total_amount_paise", 0))
    return order


@router.post("/admin/orders/{order_id}/status")
async def admin_update_order_status(
    order_id: str,
    body: UpdateOrderStatusBody,
    x_admin_key: Optional[str] = Header(default=None),
):
    """
    Admin: update order status.

    Valid transitions:
      pending → confirmed → printing → shipped → delivered
      Any state → cancelled

    Automatically sets timestamp fields (confirmed_at, shipped_at, etc.).
    """
    _require_admin(x_admin_key)

    valid_statuses = {"pending","confirmed","printing","shipped","delivered","cancelled"}
    if body.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. Must be one of: {sorted(valid_statuses)}"
        )

    order = await session_store.read_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order '{order_id[:8]}' not found.")

    now = datetime.now(timezone.utc).isoformat()

    # Update status and relevant timestamp
    order["status"] = body.status
    if body.status == "confirmed"  and not order.get("confirmed_at"):
        order["confirmed_at"] = now
    if body.status == "shipped"    and not order.get("shipped_at"):
        order["shipped_at"]   = now
    if body.status == "delivered"  and not order.get("delivered_at"):
        order["delivered_at"] = now
    if body.status == "cancelled"  and not order.get("cancelled_at"):
        order["cancelled_at"] = now

    # Update tracking if provided
    if body.tracking_id:
        order["tracking_id"] = body.tracking_id
    if body.courier:
        order["courier"] = body.courier
    if body.notes:
        order["notes"] = body.notes

    await session_store.write_order(order)
    logger.info("Admin: order %s status → %s", order_id[:8], body.status)

    return {
        "order_id":    order_id,
        "status":      body.status,
        "updated_at":  now,
        "tracking_id": order.get("tracking_id", ""),
        "courier":     order.get("courier", ""),
        "message":     f"Order status updated to '{body.status}'.",
    }

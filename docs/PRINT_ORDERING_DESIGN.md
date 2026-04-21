# Offline Printing Feature — Design & Implementation

**Status:** ✅ IMPLEMENTED  
**Branch:** beta  
**Commits:** a4845a9, 927e1a7, aa25e2b, dd7c65e  

---

## What Was Built

Offline print ordering for StoryMe storybooks — paperback and hardcover — with a complete order lifecycle, admin management dashboard, and a data model that supports a future multi-item cart and single-payment checkout.

---

## User Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HOMEPAGE                                    │
│  INPUT → PREVIEWING → PREVIEW → GENERATING                          │
│                                       ↓                             │
│                               PDF auto-downloads                    │
│                               ┌────────────────────────────┐        │
│                               │   COMPLETE STEP            │        │
│                               │                            │        │
│                               │  [🖨 Order a Printed Copy] │        │
│                               │  [⬇ Download PDF Again]   │        │
│                               │  [↩ Create Another Story] │        │
│                               └─────────────┬──────────────┘        │
└─────────────────────────────────────────────┼───────────────────────┘
                                              │ navigate("/print-order",
                                              │   { generationId, childName, storyId })
                                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      PRINT ORDER PAGE (/print-order)                │
│                                                                     │
│  ┌──────────────────────┐  ┌──────────────────────┐                │
│  │   PAPERBACK   ₹299   │  │   HARDCOVER   ₹499   │                │
│  │  [Front cover img]   │  │  [Front cover img]   │                │
│  │  [Back  cover img]   │  │  [Back  cover img]   │                │
│  │  Soft cover · A4     │  │  Premium · A4        │                │
│  │  7–10 business days  │  │  10–14 business days │                │
│  │  ○ Select            │  │  ○ Select (default)  │                │
│  └──────────────────────┘  └──────────────────────┘                │
│                                                                     │
│  ── Delivery Address ──────────────────────────────────────────    │
│  Full Name *          Phone *                                       │
│  Address Line 1 *                                                   │
│  Address Line 2 (optional)                                          │
│  City *       Pincode *        State * (dropdown, 36 states/UTs)    │
│                                                                     │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━                   │
│  Paperback — A4 · Qty 1 · Personalised for Niku    ₹299            │
│  🎉 Beta period — orders at no charge                               │
│  🔒 Secure  🚚 7–14 days  📗 Quality guaranteed                    │
│                                                                     │
│  [🖨 Place Order — ₹299]                                           │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ POST /api/v2/orders
                                   │ → { order_id, status: "pending" }
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│              ORDER STATUS PAGE (/order-status/:orderId)             │
│                                                                     │
│  ✅ Order Placed Successfully!                                       │
│  Personalised storybook for Niku is on its way.                     │
│                                                                     │
│  Order Reference: A1B2C3D4  ← keep for tracking                    │
│                                                                     │
│  Status: ⬤ Order Received                                          │
│  Timeline: [Received] ──── [Confirmed] ──── [Printing] ──── [Shipped] ──── [Delivered]
│                                                                     │
│  Paperback A4 · 1 copy · Personalised for Niku      ₹299           │
│  🎉 Beta: printed & shipped free                                    │
│  🚚 Expected: 7–10 business days                                    │
│                                                                     │
│  Delivery to:  Priya Sharma                                         │
│                12 MG Road, Bengaluru, Karnataka – 560001            │
│                                                                     │
│  [🔄 Create Another Storybook]   [← Back to Home]                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Admin Flow

```
Browser → /admin/orders

┌─────────────────────────────────────────────────────────────────────┐
│                  ADMIN LOGIN (dark theme)                           │
│  🔒 StoryMe Admin  ─  Enter ADMIN_SECRET_KEY                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ POST header X-Admin-Key verified
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  ADMIN DASHBOARD                                    │
│                                                                     │
│  Summary: [3 pending] [2 confirmed] [1 printing] [5 delivered]     │
│  Filter:  [All] [Pending] [Confirmed] [Printing] [Shipped] [Done]  │
│                                                                     │
│  ┌─── A1B2C3D4 ─────── pending ── Niku ─ Paperback ─── ₹299 ──┐   │
│  │ ▼ Expand                                                    │   │
│  │   Address: Priya Sharma, 12 MG Road, Bengaluru 560001       │   │
│  │   Placed: 21 Apr 2026 16:25                                  │   │
│  │   [Mark as Confirmed]  [Cancel Order]                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─── E5F6G7H8 ─────── shipped ── Aryan ─ Hardcover ─── ₹499 ─┐   │
│  │ ▼ Expand                                                    │   │
│  │   Tracking: BD123456789IN via BlueDart                       │   │
│  │   [Mark as Delivered]                                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Data Architecture

### Azure Tables (all in the same Storage Account — no extra subscription)

```
┌─────────────────────────────────────────────────────────────────────┐
│ PrintProducts                                                       │
│   PK = "storyme"   RK = product_id                                  │
│   Seeded at startup (idempotent)                                    │
│                                                                     │
│   paperback_a4  ₹299  available=true   sort=1                       │
│   hardcover_a4  ₹499  available=true   sort=2                       │
│   paperback_a5  ₹249  available=false  sort=3  (Phase 2)            │
│   hardcover_a5  ₹449  available=false  sort=4  (Phase 2)            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ CartItems                                                           │
│   PK = user_mobile_safe   RK = cart_item_id                         │
│   Phase 1: created & immediately linked to an Order                 │
│   Phase 2: accumulate before checkout (multi-item cart)             │
│                                                                     │
│   Fields: cart_item_id, user_mobile, generation_id, product_id,     │
│           child_name, story_id, pdf_blob_path, quantity,            │
│           unit_price_paise, status, created_at, order_id            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ Orders                                                              │
│   PK = user_mobile_safe   RK = ts_orderid                           │
│                                                                     │
│   Fields: order_id, user_mobile, generation_id, product_id,         │
│           cart_item_ids (JSON), child_name, story_id,               │
│           pdf_blob_path, quantity, total_amount_paise,              │
│           status, delivery_address (JSON), payment_id,              │
│           payment_gateway, payment_status, tracking_id, courier,    │
│           created_at, confirmed_at, shipped_at, delivered_at,       │
│           cancelled_at, notes                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Order Status Lifecycle

```
              ┌─────────┐
    Create →  │ PENDING │
              └────┬────┘
                   │ Admin confirms
              ┌────▼─────┐
              │ CONFIRMED │
              └────┬──────┘
                   │ Sent to printer
              ┌────▼────┐
              │ PRINTING │
              └────┬─────┘
                   │ Dispatched
              ┌────▼───┐
              │ SHIPPED │  ← tracking_id + courier set here
              └────┬────┘
                   │ Delivered
              ┌────▼─────┐
              │ DELIVERED │
              └───────────┘

Any status → CANCELLED
```

---

## API Reference

### Public endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v2/print/products` | List available print products |
| `GET` | `/api/v2/print/cover-image/{product_id}/{side}` | Stream cover image (PNG) |
| `POST` | `/api/v2/orders` | Place a print order |
| `GET` | `/api/v2/orders/{order_id}` | Get order status |
| `GET` | `/api/v2/orders` | User's order history (requires X-User-Mobile) |

### Admin endpoints (require `X-Admin-Key` header)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v2/admin/orders` | All orders, optional `?status=` filter |
| `GET` | `/api/v2/admin/orders/{order_id}` | Single order detail |
| `POST` | `/api/v2/admin/orders/{order_id}/status` | Update status + tracking |

### Modified endpoint

| Method | Path | Change |
|---|---|---|
| `POST` | `/api/generate` | Now returns `X-Generation-ID`, `X-Child-Name`, `X-Story-ID` response headers |

---

## Azure Configuration Required

**App Service → Configuration → Application Settings:**

| Setting | Value | Purpose |
|---|---|---|
| `ADMIN_SECRET_KEY` | `your-strong-secret-key` | Admin dashboard authentication |

No other new settings needed. `AZURE_STORAGE_CONNECTION_STRING` (already set) provisions all three new Azure Tables automatically on first write.

---

## Cover Images

Placeholder cover images are generated with Pillow at first startup and uploaded to Azure Blob:

```
products/paperback_a4/front_cover.png   800×1200 px
products/paperback_a4/back_cover.png    800×1200 px
products/hardcover_a4/front_cover.png   800×1200 px
products/hardcover_a4/back_cover.png    800×1200 px
```

To replace with real artwork: overwrite the blob at the same path. No code changes needed.

---

## Future: Multi-Item Cart & Payment (Phase 2)

The current data model already supports this:

```
Phase 2 user flow:
  Add to cart → keep shopping → cart has N items
  Checkout → single payment covers all items → one Order with N cart_item_ids
  Payment webhook → OrderStatus = confirmed
```

**What changes in Phase 2:**
- Frontend: Shopping cart page showing CartItems with `status="pending_order"`
- Frontend: Checkout button → payment gateway (Razorpay/Stripe)
- Backend: `POST /api/v2/cart/add` endpoint
- Backend: `POST /api/v2/checkout` → creates Order, initiates payment
- Backend: Payment webhook handler → updates order status automatically

**What does NOT change:**
- Orders table schema — payment fields already present (`payment_id`, `payment_gateway`, `payment_status`)
- CartItems table schema — already supports multi-item
- Admin dashboard — works unchanged
- Order status lifecycle — unchanged

---

## Files Created / Modified

### Backend
| File | Status | Description |
|---|---|---|
| `backend/core/session_store.py` | Modified | Added write/read/list for CartItems and Orders |
| `backend/core/storage_paths.py` | Modified | Added `product_cover_path()` |
| `backend/services/product_catalog.py` | New | ProductCatalogStore + seed logic |
| `backend/services/cover_image_gen.py` | New | Pillow-based placeholder cover generator |
| `backend/routes/print_orders.py` | New | All print/order/admin endpoints |
| `backend/routes/generate.py` | Modified | X-Generation-ID response header |
| `backend/server.py` | Modified | Router registration, CORS expose_headers, startup seeding |

### Frontend
| File | Status | Description |
|---|---|---|
| `frontend/src/AppRoutes.jsx` | Modified | New routes: /print-order, /order-status/:id, /admin/orders |
| `frontend/src/pages/HomePage.jsx` | Modified | COMPLETE step with print CTA, captures X-Generation-ID |
| `frontend/src/pages/PrintOrderPage.jsx` | New | Product selection + delivery form + order placement |
| `frontend/src/pages/OrderStatusPage.jsx` | New | Order confirmation + status timeline |
| `frontend/src/pages/AdminOrdersPage.jsx` | New | Admin dashboard (dark theme, status updates) |
| `frontend/src/components/PrintProductCard.jsx` | New | Product card with front/back cover display |

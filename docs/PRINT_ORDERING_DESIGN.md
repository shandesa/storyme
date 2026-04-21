# Offline Printing Feature — Design & Implementation Plan

**Date:** 2026-04-21  
**Status:** PENDING APPROVAL  
**Branch:** beta  

---

## 1. Executive Summary

This document covers the complete design for adding offline print ordering to StoryMe — paperback and hardcover options — while laying the groundwork for a future multi-item cart and single-payment checkout. Nothing is implemented until approval is given.

---

## 2. Current State (Baseline)

### User flow today
```
LOGIN → INPUT → PREVIEWING → PREVIEW → GENERATING → COMPLETE
                                                      ↓
                                              PDF auto-downloaded
                                              "Download again" button
                                              "Create Another" button
```

### Backend today
- `POST /api/generate` returns a binary `FileResponse` (PDF blob)
- `generation_id` is created server-side, written to Azure Table, but **never returned to the frontend**
- `Order` model exists in `models/generation.py` but is never written or read
- Azure Table `Orders` was planned in the migration doc but never provisioned

### What is missing
| Gap | Impact |
|---|---|
| `generation_id` not sent to frontend | Cannot reference a session when placing a print order |
| No print product catalog in DB | Nothing to show the user as print options |
| No cover images for products | Cannot show front/back cover previews |
| No `Orders` Azure Table | Cannot persist a print order |
| No cart concept | Cannot support future multi-item checkout |
| No `PrintOrderPage` in frontend | No UI to display print options |

---

## 3. Design Decisions

### 3.1 — Return `generation_id` to the frontend

The generate endpoint currently returns a binary PDF `FileResponse`. We add a response header:

```
X-Generation-ID: abc123def456...
```

The frontend reads this header after the PDF download completes and stores it in React state. This is the tie between a completed generation and any order placed afterward. Zero breaking change — existing PDF download behaviour is unchanged.

### 3.2 — Product Catalog in Azure Table Storage

A new Azure Table `PrintProducts` stores the print options. No separate database needed — same Storage Account as everything else.

```
Table: PrintProducts
PartitionKey = "storyme"          (single partition, < 10 products ever)
RowKey       = product_id         e.g. "paperback_a4", "hardcover_a4"

Columns:
  display_name       string        "Paperback — A4"
  cover_type         string        "paperback" | "hardcover"
  paper_size         string        "A4"
  price_paise        int           29900  (₹299.00)
  front_cover_blob   string        "products/paperback_a4/front_cover.png"
  back_cover_blob    string        "products/paperback_a4/back_cover.png"
  description        string        "Soft cover, full colour, 10 pages, A4"
  available          bool          true
  sort_order         int           1
```

**Seed data (4 products):**

| product_id | Type | Price |
|---|---|---|
| `paperback_a4` | Paperback | ₹299 |
| `paperback_a5` | Paperback | ₹249 |
| `hardcover_a4` | Hardcover | ₹499 |
| `hardcover_a5` | Hardcover | ₹449 |

For MVP: only `paperback_a4` and `hardcover_a4` are `available=true`.

### 3.3 — Cover Images as Blob Placeholders

Placeholder cover images are generated programmatically (Python + Pillow) and uploaded to Azure Blob at startup if not already present. They are not bundled in the git repo.

```
Blob paths:
  products/paperback_a4/front_cover.png    (800×1200 — book-proportioned portrait)
  products/paperback_a4/back_cover.png     (800×1200)
  products/hardcover_a4/front_cover.png    (800×1200)
  products/hardcover_a4/back_cover.png     (800×1200)
```

These are served via a new `GET /api/v2/print/cover-image/{product_id}/{side}` endpoint that streams the blob directly (no public blob URLs needed — keeps storage private).

### 3.4 — Cart Model (built now, used by payment later)

A `CartItems` Azure Table is created now with the correct schema. In this release, the "cart" contains one item at a time (the print option the user selects). When payment is added, the cart becomes multi-item with a checkout endpoint.

```
Table: CartItems
PartitionKey = user_mobile_safe
RowKey       = cart_item_id (UUID hex)

Columns:
  cart_item_id      string     UUID hex
  user_mobile       string     "+919160570733"
  generation_id     string     links to GenerationSession
  product_id        string     "paperback_a4"
  child_name        string     "Niku"
  story_id          string     "forest_of_smiles"
  pdf_blob_path     string     "pdfs/niku/forest_of_smiles/..."
  quantity          int        1
  unit_price_paise  int        29900
  status            string     "pending_order" | "ordered" | "cancelled"
  created_at        string     ISO timestamp
  order_id          string     (set when ordered, empty until then)
```

**Why a cart table even for single-item orders?**  
When payment is added, the user needs to select multiple print products (e.g. paperback + hardcover) before a single checkout. The `CartItems` table makes this trivial — just add multiple rows per user, then create one `Order` referencing all of them.

### 3.5 — Orders Table

```
Table: Orders
PartitionKey = user_mobile_safe
RowKey       = created_at_order_id

Columns:
  order_id              string
  user_mobile           string
  cart_item_ids_json    string     JSON array of cart_item_id
  generation_ids_json   string     JSON array (one per line item)
  total_amount_paise    int        sum of all line items
  currency              string     "INR"
  status                string     "pending"|"confirmed"|"printing"|"shipped"|"delivered"|"cancelled"
  delivery_address_json string     JSON of {full_name, line1, city, state, pincode, phone}
  payment_id            string     (future — razorpay/stripe payment id)
  payment_gateway       string     (future)
  payment_status        string     (future — "paid"|"refunded"|"failed")
  tracking_id           string     (set when shipped)
  courier               string     (set when shipped)
  created_at            string     ISO timestamp
  confirmed_at          string
  shipped_at            string
  delivered_at          string
  cancelled_at          string
  notes                 string
```

**Order status flow:**
```
PENDING → CONFIRMED → PRINTING → SHIPPED → DELIVERED
Any state → CANCELLED
```

---

## 4. New API Endpoints

### 4.1 — Print Products

```
GET /api/v2/print/products
  Returns list of available print products with metadata.
  No auth required (public catalog).
  
  Response:
  {
    "products": [
      {
        "product_id": "paperback_a4",
        "display_name": "Paperback — A4",
        "cover_type": "paperback",
        "paper_size": "A4",
        "price_paise": 29900,
        "price_display": "₹299",
        "description": "Soft cover, full colour, 10 pages",
        "available": true,
        "cover_image_urls": {
          "front": "/api/v2/print/cover-image/paperback_a4/front",
          "back":  "/api/v2/print/cover-image/paperback_a4/back"
        }
      },
      ...
    ]
  }
```

```
GET /api/v2/print/cover-image/{product_id}/{side}
  Streams the cover image blob (front or back).
  side: "front" | "back"
  Returns: image/png binary
```

### 4.2 — Orders

```
POST /api/v2/orders
  Create a print order for a completed generation.
  Body (JSON):
  {
    "generation_id": "abc123...",
    "product_id": "paperback_a4",
    "quantity": 1,
    "delivery_address": {
      "full_name": "Priya Sharma",
      "line1": "12 MG Road",
      "city": "Bengaluru",
      "state": "Karnataka",
      "pincode": "560001",
      "phone": "9160570733"
    }
  }
  
  Response:
  {
    "order_id": "uuid...",
    "status": "pending",
    "total_amount_paise": 29900,
    "price_display": "₹299",
    "message": "Order placed. You will receive a confirmation shortly."
  }
```

```
GET /api/v2/orders/{order_id}
  Get order status by order_id.
  
  Response:
  {
    "order_id": "uuid...",
    "status": "confirmed",
    "product": { ... },
    "delivery_address": { ... },
    "tracking_id": null,
    "courier": null,
    "created_at": "2026-04-21T...",
    "confirmed_at": null
  }
```

```
GET /api/v2/orders
  List all orders for the authenticated user (by session mobile).
  Used by future order history page.
```

### 4.3 — Modified: Generate Endpoint

```
POST /api/generate   (modified)
  Existing behaviour unchanged.
  NEW: Add response header X-Generation-ID: {gen_id}
  This allows frontend to reference the session for ordering.
```

---

## 5. Frontend Changes

### 5.1 — New step machine

```
Current:
  INPUT → PREVIEWING → PREVIEW → GENERATING → COMPLETE

New:
  INPUT → PREVIEWING → PREVIEW → GENERATING → COMPLETE → PRINT_OPTIONS → PRINT_ORDER
                                                 ↑
                                         (PDF downloaded automatically)
                                         Two buttons appear:
                                           [Download PDF again]  [Order a Printed Copy →]
```

### 5.2 — New pages / components

```
frontend/src/pages/
  HomePage.jsx              ← modified (new steps, generation_id state)
  PrintOrderPage.jsx        ← NEW — standalone page for print ordering

frontend/src/components/
  PrintProductCard.jsx      ← NEW — front+back cover display for one product
  OrderStatusBadge.jsx      ← NEW — reusable status chip for order history
```

### 5.3 — PrintOrderPage layout

```
┌─────────────────────────────────────────────┐
│  📚 Order a Printed Copy                    │
│  "Niku and the Forest of Smiles"            │
├─────────────────────────────────────────────┤
│                                             │
│  ┌─────────────────┐  ┌─────────────────┐  │
│  │   PAPERBACK     │  │   HARDCOVER     │  │
│  │   ₹299          │  │   ₹499          │  │
│  │                 │  │                 │  │
│  │  [Front cover]  │  │  [Front cover]  │  │
│  │  [Back  cover]  │  │  [Back  cover]  │  │
│  │                 │  │                 │  │
│  │ ○ Select        │  │ ○ Select        │  │
│  └─────────────────┘  └─────────────────┘  │
│                                             │
│  ── Delivery Details ──────────────────     │
│  [Full name] [Phone]                        │
│  [Address line 1]                           │
│  [City] [State] [Pincode]                   │
│                                             │
│  [Place Order — ₹299]                       │
│                                             │
│  (Payment gateway integration coming soon) │
└─────────────────────────────────────────────┘
```

### 5.4 — Routing

```javascript
// New route in AppRoutes.jsx
<Route path="/print-order" element={<PrintOrderPage />} />
<Route path="/order-status/:orderId" element={<OrderStatusPage />} />  // future
```

State passed between HomePage → PrintOrderPage via React Router `state`:
```javascript
navigate("/print-order", { 
  state: { 
    generationId, 
    childName, 
    storyId, 
    pdfBlobPath 
  } 
})
```

---

## 6. Data Layer Changes

### 6.1 — SessionStore extension

The `SessionStore` ABC gets two new methods:

```python
class SessionStore(ABC):
    # existing
    async def write_session(session_dict)
    async def read_session(generation_id)
    async def list_sessions(...)

    # NEW
    async def write_order(order_dict: dict) -> None
    async def read_order(order_id: str) -> dict | None
    async def list_orders(user_mobile: str, limit: int) -> list[dict]
    
    async def write_cart_item(item_dict: dict) -> None
    async def read_cart_items(user_mobile: str) -> list[dict]
```

### 6.2 — New: ProductCatalogStore

A separate small class (not part of SessionStore ABC — it's read-heavy, write-once):

```python
class ProductCatalogStore:
    async def list_products(available_only=True) -> list[dict]
    async def get_product(product_id: str) -> dict | None
    async def seed_products() -> None     # idempotent, called at startup
    async def get_cover_image(product_id, side) -> bytes
```

### 6.3 — Storage paths (additions to storage_paths.py)

```python
def product_cover_path(product_id: str, side: str) -> str:
    """products/{product_id}/{side}_cover.png"""

def order_pdf_path(order_id: str) -> str:
    """orders/{order_id}/book.pdf"""   # future: per-order PDF copy
```

---

## 7. New Files Created

```
backend/
  routes/print_orders.py       ← GET /api/v2/print/products
                                  GET /api/v2/print/cover-image/{id}/{side}
                                  POST /api/v2/orders
                                  GET /api/v2/orders/{order_id}
                                  GET /api/v2/orders
  services/product_catalog.py  ← ProductCatalogStore + seeding logic
  services/cover_image_gen.py  ← Generates placeholder cover PNGs at startup

frontend/src/
  pages/PrintOrderPage.jsx     ← Full print ordering UI
  components/PrintProductCard.jsx

docs/
  PRINT_ORDERING_DESIGN.md     ← This file
```

---

## 8. Placeholder Cover Image Specification

Generated programmatically by `cover_image_gen.py` at first startup. Stored in Azure Blob.

**Dimensions:** 800 × 1200 px (2:3 portrait — standard book proportion)  
**Format:** PNG

| Product | Front cover | Back cover |
|---|---|---|
| Paperback A4 | Forest green gradient + "Forest of Smiles" title text + StoryMe logo area | Soft cream with barcode placeholder + tagline |
| Hardcover A4 | Deep forest green + gold title emboss simulation | Dark navy with gold borders + tagline |

These are clearly marked as placeholders — they contain the text "COVER ARTWORK COMING SOON" in a tasteful position. When real artwork is commissioned, the blob is simply overwritten at the same path — no code changes needed.

---

## 9. Future-Proofing for Cart + Payment

### How the cart grows

**Phase 1 (this PR):** Single product selection → direct order placement. CartItem is created, immediately linked to an Order. No pending-cart UI.

**Phase 2 (payment):** CartItems accumulate in `CartItems` Azure Table with `status="pending_order"`. A cart UI shows all pending items with a total. Checkout creates one Order referencing all cart_item_ids. Razorpay/Stripe webhook updates `payment_status` and triggers `status="confirmed"`.

**Phase 3 (order history):** `GET /api/v2/orders` feeds an order history page per user. Each order shows all line items, status, and tracking.

The schema and endpoints designed in this PR support all three phases without schema changes.

### OrderStatus enum is already complete

`PENDING → CONFIRMED → PRINTING → SHIPPED → DELIVERED → CANCELLED`

Phase 1 uses PENDING → CONFIRMED (manual admin confirmation via future admin panel).
Phase 2 uses PENDING → CONFIRMED (automated via payment webhook).
Phase 3 adds tracking data at SHIPPED.

---

## 10. What Does NOT Change

- `POST /api/generate` behaviour — PDF is still returned as binary FileResponse
- `POST /api/v2/generate/preview` — unchanged
- `GET /api/v2/stories` — unchanged
- Auth flow — unchanged
- Azure Blob structure for generated pages and PDFs — unchanged
- Face blend pipeline — unchanged
- Evaluator — unchanged

---

## 11. Implementation Order (after approval)

```
Step 1: Backend data layer
  ├── Add write_order / read_order / list_orders to SessionStore ABC + implementations
  ├── Add write_cart_item / read_cart_items to SessionStore
  └── Create ProductCatalogStore + seed 4 products

Step 2: Backend routes
  ├── Add print_orders.py router
  ├── Register router in server.py
  ├── Modify generate.py to return X-Generation-ID header
  └── Add cover_image_gen.py + call at startup

Step 3: storage_paths.py additions
  └── product_cover_path(), order_pdf_path()

Step 4: Frontend — core
  ├── HomePage.jsx — read X-Generation-ID header, add PRINT_OPTIONS step
  └── AppRoutes.jsx — add /print-order route

Step 5: Frontend — PrintOrderPage
  ├── PrintOrderPage.jsx — product cards, delivery form, order placement
  └── PrintProductCard.jsx — cover image display component

Step 6: Commit, push, verify
```

---

## 12. Open Questions (for discussion before implementation)

1. **Price display** — Should prices be shown in the MVP UI even though payment is not wired? Recommendation: yes, with a note "Payment integration coming soon — orders are free during beta."

2. **Delivery address** — Required fields for MVP? Recommendation: all fields required (name, line1, city, state, pincode, phone) since the order needs a real address for printing.

3. **Order confirmation** — After `POST /api/v2/orders`, should the user see an order confirmation screen, or just a success toast? Recommendation: full confirmation screen with order ID for beta.

4. **Real artwork timeline** — The placeholder covers are functional but not beautiful. When will real front/back cover artwork be ready? This does not block implementation.

5. **Admin order management** — Who sees orders and updates their status? For now, orders go into Azure Table and someone checks manually. An admin panel is a future story.

# StoryMe — Payment Integration Design & Roadmap

**Status:** Beta (no real charges)  
**Last Updated:** April 2026  
**Owner:** Engineering

---

## 1. Current State (Beta)

### What is in production today

Every order — digital (PDF) or print — goes through the same `PaymentPage` route. The page shows real prices, a transparent beta-discount breakdown, and records the order on the backend. No card is ever charged.

```
HomePage  →  /payment  →  POST /api/v2/orders/digital  OR  POST /api/v2/orders
                         (payment_status = "beta_bypass", no charge)
           →  /order-status/:id
```

### Why we store real prices during beta

Orders are stored at their real `total_amount_paise` (₹199 for digital, ₹299+ for print). The "beta bypass" is tracked via `payment_status: "beta_bypass"` in the order record. This gives us:

- An accurate audit trail of what was given for free.
- Zero migration cost when payment goes live — existing order records are already correctly priced.
- Meaningful analytics on demand volume at real prices.

### Pricing (current)

| Product | Price | Field |
|---|---|---|
| PDF Download | ₹199 | `PDF_DOWNLOAD_PRICE_PAISE = 19900` |
| Email PDF | ₹199 | `EMAIL_PDF_PRICE_PAISE = 19900` |
| Paperback A4 | ₹299 | catalog / env |
| Hardcover A4 | ₹499 | catalog / env |

---

## 2. Order Type Architecture

### 2.1 Digital orders (`order_type: "pdf_download" | "email_pdf"`)

**Endpoint:** `POST /api/v2/orders/digital`

**Status lifecycle:**

```
order_received  →  payment_pending  →  generating  →  emailed
```

| Status | Meaning |
|---|---|
| `order_received` | Order recorded; awaiting payment confirmation |
| `payment_pending` | Payment initiated but not yet verified |
| `generating` | PDF being assembled/re-generated for delivery |
| `emailed` | PDF sent to user's email address |

For `pdf_download` in beta, the browser download is triggered immediately after `order_received` without going through the full lifecycle. Once payment is live, the flow will be:
1. `order_received` — intent recorded
2. Payment gateway callback → `payment_pending` → `order_received` (confirmed)
3. Signed time-limited download URL returned to frontend

**Order record fields:**
```json
{
  "order_id": "...",
  "order_type": "pdf_download",
  "total_amount_paise": 19900,
  "price_display": "₹199",
  "payment_status": "beta_bypass | payment_pending | paid | failed | refunded",
  "payment_id": "",
  "payment_gateway": "",
  "delivery_email": "",
  "status": "order_received | generating | emailed | cancelled"
}
```

### 2.2 Print orders (`order_type: "print"`)

**Endpoint:** `POST /api/v2/orders`

**Status lifecycle:**

```
pending  →  confirmed  →  printing  →  shipped  →  delivered
```

| Status | Meaning |
|---|---|
| `pending` | Order received; awaiting confirmation |
| `confirmed` | Payment verified; queued for printing |
| `printing` | Book in print queue |
| `shipped` | Dispatched with courier |
| `delivered` | Confirmed delivery |

---

## 3. Razorpay Integration Roadmap

### 3.1 Prerequisites

- Razorpay account (KYC completed)
- `RAZORPAY_KEY_ID` + `RAZORPAY_KEY_SECRET` environment variables
- Backend: `pip install razorpay`
- Frontend: Razorpay checkout script (or `npm install razorpay`)

### 3.2 Backend changes required

**New endpoint:** `POST /api/v2/payments/create-order`
```python
@router.post("/payments/create-order")
async def create_razorpay_order(body: CreatePaymentOrderBody, request: Request):
    """
    Create a Razorpay order. Called by frontend before showing checkout.
    Returns razorpay_order_id which is passed to the Razorpay checkout widget.
    """
    import razorpay
    client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))
    rp_order = client.order.create({
        "amount":   body.amount_paise,    # ₹199 → 19900
        "currency": "INR",
        "receipt":  body.storyme_order_id,
        "notes":    {"order_type": body.order_type, "child_name": body.child_name},
    })
    return {"razorpay_order_id": rp_order["id"], "amount": rp_order["amount"]}
```

**New endpoint:** `POST /api/v2/payments/verify`
```python
@router.post("/payments/verify")
async def verify_razorpay_payment(body: VerifyPaymentBody, request: Request):
    """
    Verify Razorpay signature after successful payment.
    Called by frontend on Razorpay success callback.
    Updates order.payment_status to "paid".
    """
    import razorpay, hmac, hashlib
    generated_signature = hmac.new(
        KEY_SECRET.encode(), 
        f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode(),
        hashlib.sha256
    ).hexdigest()

    if generated_signature != body.razorpay_signature:
        raise HTTPException(status_code=400, detail="Payment signature verification failed")

    # Update order
    order = await session_store.read_order(body.storyme_order_id)
    order["payment_status"] = "paid"
    order["payment_id"]     = body.razorpay_payment_id
    order["payment_gateway"] = "razorpay"
    order["status"]          = "order_received"  # confirmed
    await session_store.write_order(order)

    return {"status": "verified", "payment_id": body.razorpay_payment_id}
```

### 3.3 Frontend changes required (PaymentPage.jsx)

Replace the current `handleConfirmPayment` with a two-step flow:

```javascript
// Step 1: Create Razorpay order
const rpRes = await axios.post(`${API_V2}/payments/create-order`, {
  storyme_order_id: storedOrderId,
  amount_paise:     19900,
  order_type:       orderType,
  child_name:       childName,
});

// Step 2: Open Razorpay checkout widget
const options = {
  key:            process.env.REACT_APP_RAZORPAY_KEY_ID,
  amount:         rpRes.data.amount,
  currency:       "INR",
  name:           "StoryMe",
  description:    `Personalised storybook for ${childName}`,
  order_id:       rpRes.data.razorpay_order_id,
  handler:        async (response) => {
    // Step 3: Verify signature on backend
    await axios.post(`${API_V2}/payments/verify`, {
      razorpay_order_id:   response.razorpay_order_id,
      razorpay_payment_id: response.razorpay_payment_id,
      razorpay_signature:  response.razorpay_signature,
      storyme_order_id:    storedOrderId,
    }, { headers: authHeaders() });

    // Step 4: Trigger download / navigate
    triggerDownloadOrNavigate();
  },
  prefill:        { name: childName, contact: getMobile() },
  theme:          { color: "#6366f1" },   // indigo-500
};
const rzp = new window.Razorpay(options);
rzp.open();
```

### 3.4 Migration checklist

- [ ] Add Razorpay env vars to Azure App Service (KEY_ID, KEY_SECRET)
- [ ] Add REACT_APP_RAZORPAY_KEY_ID to Azure Static Web Apps env
- [ ] Deploy backend endpoints (`/payments/create-order`, `/payments/verify`)
- [ ] Remove beta bypass in `PaymentPage.jsx` — connect to Razorpay
- [ ] Remove `payment_status: "beta_bypass"` default from backend order creation
- [ ] Add Razorpay webhook for payment failure / refund handling
- [ ] Test with Razorpay test mode before going live
- [ ] Remove beta discount breakdown from PaymentPage UI

---

## 4. Email PDF Integration Roadmap

### 4.1 Chosen provider: SendGrid (recommended) or AWS SES

**Decision criteria:**
- SendGrid: simpler API, better deliverability monitoring, free tier (100/day)
- AWS SES: cheaper at scale, requires more setup, native Azure integration via Entra

**Initial recommendation: SendGrid** for the first 10k orders.

### 4.2 Backend changes required

**Install:** `pip install sendgrid`  
**Env var:** `SENDGRID_API_KEY`

**New service:** `services/email_service.py`
```python
import sendgrid
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
import base64, os

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL       = "stories@storyme.app"
FROM_NAME        = "StoryMe"

def send_pdf_email(to_email: str, child_name: str, pdf_bytes: bytes) -> bool:
    """
    Send a personalised storybook PDF to the given email.
    Returns True on success, False on failure.
    """
    sg      = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    encoded = base64.b64encode(pdf_bytes).decode()

    mail = Mail(
        from_email=(FROM_EMAIL, FROM_NAME),
        to_emails=to_email,
        subject=f"Your StoryMe storybook for {child_name} is here! 📚",
        html_content=_email_body_html(child_name),
    )
    attachment = Attachment(
        FileContent(encoded),
        FileName(f"{child_name}_storybook.pdf"),
        FileType("application/pdf"),
        Disposition("attachment"),
    )
    mail.attachment = attachment
    response = sg.send(mail)
    return response.status_code in (200, 201, 202)
```

**Trigger point:** After `POST /api/v2/orders/digital` with `order_type="email_pdf"`, a background task calls `send_pdf_email` and updates `order.status → "emailed"` and `order.emailed_at`.

```python
# In place_digital_order, after write_order:
if body.order_type == "email_pdf" and body.email:
    background_tasks.add_task(
        _deliver_pdf_by_email,
        order_id=order_id,
        email=body.email,
        generation_id=body.generation_id,
    )
```

### 4.3 Email delivery task
```python
async def _deliver_pdf_by_email(order_id: str, email: str, generation_id: str):
    """Background task: fetch PDF from blob, send via SendGrid, update order status."""
    try:
        # Mark generating
        order = await session_store.read_order(order_id)
        order["status"] = "generating"
        await session_store.write_order(order)

        # Fetch PDF bytes from Azure Blob
        pdf_bytes = await _fetch_pdf_from_blob(generation_id)

        # Send email
        success = send_pdf_email(email, order.get("child_name", ""), pdf_bytes)

        # Update status
        order["status"]     = "emailed" if success else "order_received"
        order["emailed_at"] = datetime.now(timezone.utc).isoformat() if success else ""
        await session_store.write_order(order)
    except Exception as e:
        logger.error("Email delivery failed for order %s: %s", order_id[:8], e)
```

### 4.4 Email integration checklist

- [ ] Create SendGrid account; verify `stories@storyme.app` sender domain
- [ ] Add `SENDGRID_API_KEY` to Azure App Service env
- [ ] Add `services/email_service.py`
- [ ] Update `POST /api/v2/orders/digital` to use `BackgroundTasks`
- [ ] Design HTML email template (`_email_body_html`)
- [ ] Test with SendGrid sandbox before enabling production sends

---

## 5. Secure PDF Download (pdf_download flow)

Currently the browser downloads from an in-memory `objectURL` created in `HomePage`. This works for the current session but breaks if the user navigates away or refreshes.

### 5.1 Production approach: signed download URL

**New endpoint:** `GET /api/v2/orders/:orderId/download`
```python
@router.get("/orders/{order_id}/download")
async def get_download_url(order_id: str, request: Request):
    """
    Issue a short-lived (15 min) pre-signed Azure Blob URL for the PDF.
    Requires valid session token. Validates order belongs to authenticated user.
    """
    mobile = require_mobile_from_request(request)
    order  = await session_store.read_order(order_id)
    
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("user_mobile") != mobile:
        raise HTTPException(status_code=403, detail="Not authorised")
    if order.get("payment_status") not in ("paid", "beta_bypass"):
        raise HTTPException(status_code=402, detail="Payment required")

    blob_path = order.get("pdf_blob_path", "")
    url = generate_sas_url(blob_path, expiry_minutes=15)
    return {"download_url": url, "expires_in_seconds": 900}
```

**Frontend:** Navigate to `/order-status/:id`, then offer a "Download Again" button that calls this endpoint.

### 5.2 Download checklist

- [ ] Implement `GET /api/v2/orders/:orderId/download`
- [ ] Add "Download Again" button to `OrderStatusPage` (digital orders only)
- [ ] Remove dependency on `pdfObjectUrl` in `PaymentPage` after payment goes live
- [ ] Set SAS URL expiry to 15 minutes (configurable via env)

---

## 6. Environment Variables Reference

### Backend (Azure App Service)

| Variable | Purpose | Required for |
|---|---|---|
| `RAZORPAY_KEY_ID` | Razorpay API key | Payment |
| `RAZORPAY_KEY_SECRET` | Razorpay API secret | Payment |
| `SENDGRID_API_KEY` | SendGrid email API | Email delivery |
| `ADMIN_SECRET_KEY` | Admin order management | Already present |
| `AZURE_STORAGE_CONNECTION_STRING` | Blob + Table storage | Already present |

### Frontend (Azure Static Web Apps)

| Variable | Purpose | Required for |
|---|---|---|
| `REACT_APP_RAZORPAY_KEY_ID` | Razorpay checkout (public key) | Payment |
| `REACT_APP_BACKEND_URL` | API base URL | Already present |

---

## 7. Testing Strategy

### Beta period
- All orders go through with `payment_status: "beta_bypass"` — no card charged
- Admin can view all orders at `GET /api/v2/admin/orders`
- Order status can be manually updated via `POST /api/v2/admin/orders/:id/status`

### Pre-launch (Razorpay test mode)
1. Set Razorpay keys to test mode (`rzp_test_...`)
2. Use Razorpay test card: `4111 1111 1111 1111`, any future expiry, any CVV
3. Verify signature validation works
4. Test payment failure path
5. Test refund via Razorpay dashboard

### Production
- Enable Razorpay live keys
- Monitor `payment_status` distribution in admin dashboard
- Set up Razorpay webhook for async payment events

---

## 8. Rollout Plan

| Phase | Milestone | Effort |
|---|---|---|
| **Beta (now)** | All orders free; prices displayed; audit trail via `beta_bypass` | ✅ Done |
| **Phase 1** | Razorpay integration for print orders only | ~3 days |
| **Phase 2** | Razorpay integration for digital orders; signed download URLs | ~2 days |
| **Phase 3** | SendGrid email PDF delivery | ~2 days |
| **Phase 4** | Refund flow; payment failure retries | ~2 days |
| **Phase 5** | UPI / PhonePe / Paytm via Razorpay methods | ~1 day |
| **Phase 6** | Subscription model (e.g. 3 books/month for ₹399) | TBD |

---

*This document should be updated after each phase is completed.*

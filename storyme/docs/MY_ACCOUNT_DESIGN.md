# My Account — Feature Design & Implementation

**Status:** 🚧 IN PROGRESS  
**Branch:** `feature_myaccount_beta`  
**Owner:** Engineering  

---

## 1. Overview

The **My Account** feature gives every authenticated StoryMe user a persistent, accessible account panel available on every protected page. It surfaces three core capabilities:

| Capability | What it does |
|---|---|
| **My Orders** | View all past and active print orders with live status |
| **Saved Addresses** | Add, edit, and delete delivery addresses for reuse at checkout |
| **Sign Out** | Securely ends the session from anywhere in the app |

The panel is implemented as a **side-sheet (drawer)** triggered by a user avatar icon in a shared `AppHeader` component that replaces the per-page inline headers previously duplicated across `HomePage`, `PrintOrderPage`, and `OrderStatusPage`.

---

## 2. Design Rationale

### Why a Sheet, not a full page?
- Users are mid-flow (generating a story, reviewing an order) when they need account access.
- A sheet lets them check an order or copy an address without losing their current position.
- No extra route to manage; no back-button confusion.
- The `shadcn/ui` `<Sheet>` component is already in the codebase — zero new dependencies.

### Why a shared `AppHeader`?
The header (`BookOpen + StoryMe + Sparkles + [User Icon]`) was previously copy-pasted into every protected page. Extracting it to `AppHeader.jsx` means:
- Logout existed only in `HomePage` — now it lives inside the Account sheet, accessible everywhere.
- Future header changes (e.g. cart icon, notifications) happen in one file.

### Address storage — new backend table
Saved addresses require persistence across sessions (unlike the current stateless flow). A new `UserAddresses` Azure Table is added (with a `JsonAddressStore` fallback for local dev), following the exact same pattern as `UserStore`.

---

## 3. User Flow

```
ANY PROTECTED PAGE
┌────────────────────────────────────────────────────────────┐
│  📖 StoryMe ✨                          [👤 98765 43210]   │  ← AppHeader
└────────────────────────────────────────────────────────────┘
                                                 │ tap
                                                 ▼
              ┌──────────────────────────────────────────┐
              │  MY ACCOUNT                          [×] │
              │  📱 +91 98765 43210                       │
              │  ─────────────────────────────────────── │
              │  [ My Orders ]  [ Saved Addresses ]       │ ← Tabs
              │  ─────────────────────────────────────── │
              │                                           │
              │  MY ORDERS TAB:                           │
              │  ┌───────────────────────────────────┐   │
              │  │ #A1B2C3D4  Paperback · ₹299       │   │
              │  │ Emma · Forest of Smiles            │   │
              │  │ ● Printing  · 12 Apr 2025          │   │
              │  └───────────────────────────────────┘   │
              │  ┌───────────────────────────────────┐   │
              │  │ #E5F6G7H8  Hardcover · ₹499       │   │
              │  │ Rohan · Forest of Smiles           │   │
              │  │ ✓ Delivered · 02 Mar 2025          │   │
              │  └───────────────────────────────────┘   │
              │                                           │
              │  SAVED ADDRESSES TAB:                     │
              │  ┌───────────────────────────────────┐   │
              │  │ 🏠 Home                     [✏][🗑]│   │
              │  │ Priya Sharma                       │   │
              │  │ 12 MG Road, Bangalore 560001       │   │
              │  └───────────────────────────────────┘   │
              │  [+ Add New Address]                      │
              │  ─────────────────────────────────────── │
              │  [Sign Out]                               │
              └──────────────────────────────────────────┘
```

### Address pre-fill in PrintOrderPage

When the user navigates to `/print-order`, if they have saved addresses, a **"Use saved address"** selector appears above the manual form. Selecting one pre-fills all fields instantly. A **"Save this address"** checkbox (default: on) at the bottom of the form saves newly entered addresses to the book.

---

## 4. Architecture

### 4.1 Frontend — New Files

| File | Purpose |
|---|---|
| `src/components/AppHeader.jsx` | Shared header bar used by all protected pages |
| `src/components/UserAccountSheet.jsx` | Sheet component containing Orders + Addresses tabs + Sign Out |

### 4.2 Frontend — Modified Files

| File | Change |
|---|---|
| `src/pages/HomePage.jsx` | Replace inline header with `<AppHeader />` |
| `src/pages/PrintOrderPage.jsx` | Add `<AppHeader />` + saved address selector + save checkbox |
| `src/pages/OrderStatusPage.jsx` | Add `<AppHeader />` |

### 4.3 Backend — New Files

| File | Purpose |
|---|---|
| `backend/core/address_store.py` | `AddressStore` ABC + `AzureAddressStore` + `JsonAddressStore` |
| `backend/routes/user_profile.py` | REST endpoints for address CRUD |

### 4.4 Backend — Modified Files

| File | Change |
|---|---|
| `backend/server.py` | Register `user_profile_router` |

---

## 5. API Contract

### Address schema

```json
{
  "address_id":  "uuid-hex",
  "label":       "Home",
  "full_name":   "Priya Sharma",
  "line1":       "12 MG Road",
  "line2":       "Near Residency Road",
  "city":        "Bangalore",
  "state":       "Karnataka",
  "pincode":     "560001",
  "phone":       "9876543210",
  "country":     "India",
  "created_at":  "ISO-8601",
  "updated_at":  "ISO-8601"
}
```

All fields match the existing `DeliveryAddressBody` in `print_orders.py` — so a saved address can be passed directly as `delivery_address` in `POST /api/v2/orders` without any transformation.

### Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v2/user/addresses` | JWT | List all saved addresses |
| `POST` | `/api/v2/user/addresses` | JWT | Add a new address |
| `PUT` | `/api/v2/user/addresses/{id}` | JWT | Update an address |
| `DELETE` | `/api/v2/user/addresses/{id}` | JWT | Delete an address |

Auth: `Authorization: Bearer <token>` (same as all other protected endpoints via `require_mobile_from_request`).

---

## 6. Storage — `UserAddresses` Azure Table

```
Table: UserAddresses
  PartitionKey  = safe(mobile)   e.g. "9876543210"
  RowKey        = address_id     e.g. "a1b2c3d4e5f6..."
  label         string
  full_name     string
  line1         string
  line2         string (optional)
  city          string
  state         string
  pincode       string  (6 digits)
  phone         string  (10 digits)
  country       string  default "India"
  created_at    ISO-8601
  updated_at    ISO-8601
```

Local dev fallback: `JsonAddressStore` writes to `backend/data/addresses.json` (gitignored).  
Max addresses per user: **10** (enforced at API level — prevents unbounded table growth).

---

## 7. Component API

### `<AppHeader>`

```jsx
<AppHeader />
// Reads mobile from getMobile() (session)
// Internally renders UserAccountSheet trigger
// No props required
```

### `<UserAccountSheet>`

```jsx
<UserAccountSheet open={bool} onOpenChange={fn} />
// Internal state: activeTab ("orders" | "addresses")
// Fetches orders + addresses lazily on open
```

---

## 8. UX Details

### My Orders
- Sorted by `created_at` descending (newest first).
- Each card shows: order reference (first 8 chars of UUID, uppercased), product name, price, child name, status badge (matches existing `STATUS_CONFIG` from `OrderStatusPage`), and formatted date.
- Tapping a card closes the sheet and navigates to `/order-status/:orderId`.
- Empty state: illustrated empty card with "No orders yet — create your first storybook!" CTA.
- Loading state: skeleton cards.

### Saved Addresses
- Each card: label (Home/Office/Other), full name, line1+line2, city + state + pincode, phone.
- Edit: opens inline form within the sheet (replaces list view for that card).
- Delete: confirmation dialog (`AlertDialog` from shadcn) before deletion.
- Add: "+" button → inline form (same fields as `PrintOrderPage` delivery address).
- Label field: quick-select chips (Home / Office / Other) + custom text input.
- Max 10 addresses enforced — add button is disabled/hidden beyond limit.

### PrintOrderPage Integration
- If user has ≥ 1 saved address → show "Use a saved address" accordion above the manual form.
- Selecting a saved address pre-fills all fields; user can still edit before ordering.
- "Save this address" toggle (default: checked) — on `Place Order`, POSTs to address API.
- If address was pre-filled from saved, toggle becomes "Update saved address" (default: unchecked to avoid noise).

### Sign Out
- Single button at bottom of sheet.
- Calls `clearSession()`, `stopInactivityTimer()`, `stopTokenRefresh()` — same as current `handleLogout`.
- Navigates to `/` with `replace: true`.

---

## 9. Accessibility & Mobile

- Sheet has `aria-label="My Account"`.
- All interactive elements have visible focus rings (Tailwind `focus-visible:ring-2`).
- Tabs use `role="tab"` / `role="tabpanel"` from shadcn `Tabs`.
- Minimum tap target: 44 × 44 px (mobile-first India market).
- Sheet slides from the right on desktop; bottom-sheet behaviour on narrow viewports is handled by shadcn's drawer component.

---

## 10. Open Questions / Future Work

| Item | Notes |
|---|---|
| **Default address** | Mark one address as default so it auto-fills PrintOrderPage without user selection |
| **Edit profile** | Add display name / email to user model |
| **Push notifications** | "Your order was shipped!" — requires FCM integration |
| **Address validation** | Integrate India Post API for pincode → city/state auto-fill |
| **Order cancellation** | "Cancel order" button on pending orders in My Orders tab |

# StoryMe — My Account: Feature Design

**Status:** Implemented (v2.0)  
**Last Updated:** April 2026  
**Owner:** Engineering

---

## 1. Overview

The "My Account" section is the primary self-service hub for StoryMe users. It is accessible from every protected page via the `AppHeader` as a slide-in sheet panel.

### 1.1 Why these features matter for a children's storybook platform

| Feature | User value | Business value |
|---|---|---|
| Display name | Personalised greeting; used in storybook generation | Reduces "who is this account?" confusion |
| Email address | Order receipts; PDF delivery; account recovery | Enables email-based customer communication |
| Password change | Security hygiene | Reduces account takeover risk |
| Account deletion | DPDP / GDPR compliance | Builds trust; legally required |
| Order history | Track print/digital orders | Reduces support load |
| Address book | Faster print checkout | Increases conversion |

---

## 2. UI Structure

### 2.1 Panel layout

```
┌──────────────────────────────────────┐
│  My Account                    [✕]  │  SheetHeader
│                                      │
│  [avatar initials]  Shantanu Kumar   │  Profile header
│                     +91 ●●●●●0733  │
│ ─────────────────────────────────── │
│  [Orders]  [Addresses]  [Profile]   │  TabsList (3 tabs)
│                                      │
│  ┌──────────────────────────────┐   │
│  │  Tab content (scrollable)    │   │
│  └──────────────────────────────┘   │
│                                      │
│  [Sign Out]                          │  Footer (always visible)
└──────────────────────────────────────┘
```

### 2.2 Tab: My Orders (unchanged)

Displays all orders (print + digital) with status badges. Tapping an order navigates to `/order-status/:id`.

### 2.3 Tab: Saved Addresses (unchanged)

Full address CRUD — add, edit, delete. Max 10 addresses. Pre-fills during print checkout.

### 2.4 Tab: Profile (new)

Three sections stacked vertically:

```
── Personal Information ────────────────
  Display Name  [                      ] [Save]
  Email         [                      ] [Save]
  Mobile        +91 9160570733 (cannot change)

── Security ────────────────────────────
  Current Password  [●●●●●●●           ]
  New Password      [●●●●●●●           ]
  Confirm New       [●●●●●●●           ]
  [Change Password]

── Account Information ──────────────────
  Member since: 22 Apr 2026
  Account status: Active

── Danger Zone ─────────────────────────
  [Delete My Account]
  → Opens confirmation dialog
  → User must type "DELETE" to confirm
  → Account is soft-deleted (30-day grace period)
```

---

## 3. Data Model

### 3.1 New user fields (added to user_store)

All fields are optional and additive — existing records without them continue to function via `setdefault` normalization.

| Field | Type | Default | Notes |
|---|---|---|---|
| `display_name` | `str` | `""` | Free text, 2–60 chars |
| `email` | `str` | `""` | Optional; validated format |
| `account_status` | `str` | `"active"` | `active` / `deletion_requested` |
| `deletion_requested_at` | `str` | `""` | ISO-8601 UTC timestamp |

### 3.2 Azure Table storage

All new fields are added to `AzureUserStore.upsert_user` and `_to_dict`. Because Azure Table Storage is schema-less, existing rows without these columns continue to be read without error — missing columns return `None` which is handled by `.get(field, default)`.

---

## 4. API Design

### 4.1 Existing (unchanged)

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/api/auth/register` | None | Now accepts optional `display_name` |
| POST | `/api/auth/login-password` | None | Rejects `deletion_requested` accounts |
| GET | `/api/auth/me` | JWT | Now returns `display_name`, `email`, `account_status` |
| GET | `/api/v2/user/addresses` | JWT | Unchanged |
| POST | `/api/v2/user/addresses` | JWT | Unchanged |
| PUT | `/api/v2/user/addresses/:id` | JWT | Unchanged |
| DELETE | `/api/v2/user/addresses/:id` | JWT | Unchanged |

### 4.2 New profile endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/v2/user/profile` | JWT | Return full profile (no password hash) |
| PUT | `/api/v2/user/profile` | JWT | Update `display_name` and/or `email` |
| POST | `/api/v2/user/password` | JWT | Change password (requires current password) |
| DELETE | `/api/v2/user/account` | JWT | Request account deletion (soft delete) |

### 4.3 Request / Response shapes

#### `GET /api/v2/user/profile`
```json
{
  "mobile":                "9160570733",
  "country_code":          "+91",
  "display_name":          "Shantanu Kumar",
  "email":                 "shantanu@example.com",
  "account_status":        "active",
  "terms_accepted":        true,
  "terms_accepted_at":     "2026-04-25T...",
  "created_at":            "2026-04-22T...",
  "last_login_at":         "2026-04-25T..."
}
```

#### `PUT /api/v2/user/profile`
```json
// Request
{ "display_name": "Shantanu Kumar", "email": "shantanu@example.com" }

// Response
{ "status": "updated", "user": { ...profile } }
```

#### `POST /api/v2/user/password`
```json
// Request
{ "current_password": "old123", "new_password": "new456" }

// Response (success)
{ "status": "password_changed" }

// Response (wrong current)
HTTP 401 — "Current password is incorrect"

// Response (OTP-only user — no password set)
HTTP 400 — "No password set. Log in via OTP to set one."
```

#### `DELETE /api/v2/user/account`
```json
// Request
{ "confirmation": "DELETE", "current_password": "optional_if_set" }

// Response
{ "status": "deletion_requested", "message": "...", "grace_days": 30 }

// On next login attempt (OTP or password):
HTTP 403 — "This account is scheduled for deletion. Contact support to cancel."
```

---

## 5. Account Deletion Design

### 5.1 Soft delete (implemented now)

1. User confirms deletion with text "DELETE"
2. Backend sets `account_status = "deletion_requested"`, `deletion_requested_at = now()`
3. Session is cleared on frontend; user is redirected to login
4. Any subsequent login attempt returns HTTP 403
5. All existing orders remain in the system (for fulfilment of in-flight orders)

### 5.2 Hard delete (future — scheduled job)

A nightly Azure Function / cron job should:
1. Query users where `account_status = "deletion_requested"` AND `deletion_requested_at < 30 days ago`
2. For each: delete addresses, mark orders as orphaned, delete user record
3. Log deletion for DPDP audit trail

### 5.3 Grace period display

After deletion is requested, users who navigate back are told: "Your account is scheduled for deletion. Contact support@storyme.app to cancel within 30 days."

---

## 6. Registration Flow Update

### 6.1 Current flow
```
OTP verified → /register → mobile + password → /terms → /home
```

### 6.2 Updated flow
```
OTP verified → /register → name (optional) + password → /terms → /home
```

The `display_name` field is optional at registration. If empty, the header falls back to the masked mobile number. The user can always set/update it later in Profile.

---

## 7. Security Considerations

### 7.1 Password change
- Requires **current password** verification even when already logged in (re-authentication principle)
- New password minimum: 6 characters (same as registration)
- Password hash updated in-place; all existing sessions remain valid (acceptable for MVP; session invalidation on password change is a Phase 2 hardening)

### 7.2 Account deletion
- Requires typing exact string "DELETE" (prevents accidental deletion)
- For accounts with a password: requires current password (prevents deletion via stolen session)
- For OTP-only accounts: confirmation text alone is sufficient (no password set)
- Soft delete means data is recoverable for 30 days

### 7.3 Email address
- Not verified in this version (no email OTP flow)
- Used for PDF delivery and notifications only
- Email verification via OTP is a Phase 2 feature

### 7.4 What cannot be changed
- **Mobile number** is the login identifier and cannot be changed (immutable primary key)
- **Terms acceptance** cannot be revoked post-acceptance (legal record)

---

## 8. Component Architecture

### 8.1 UserAccountSheet.jsx tabs

```
UserAccountSheet
├── Sheet (shadcn slide-in)
│   ├── SheetHeader (avatar + display_name + masked mobile)
│   ├── Tabs (3 tabs)
│   │   ├── MyOrdersTab       — unchanged
│   │   ├── MyAddressesTab    — unchanged
│   │   └── ProfileTab (new)
│   │       ├── PersonalInfoSection
│   │       │   ├── EditableField (display_name)
│   │       │   └── EditableField (email)
│   │       ├── SecuritySection
│   │       │   └── ChangePasswordForm
│   │       ├── AccountInfoSection
│   │       └── DangerZoneSection
│   │           └── DeleteAccountDialog
│   └── Footer (Sign Out)
```

### 8.2 State management

Profile data is fetched once on `ProfileTab` mount via `GET /api/v2/user/profile` and stored in local component state. Changes are committed field-by-field with individual Save buttons — no global form state. This pattern is consistent with the address book UX.

### 8.3 Header sync

After saving display_name, the sheet header updates immediately via a `onProfileUpdate` callback prop passed down from `UserAccountSheet` → `ProfileTab` → `PersonalInfoSection`.

---

## 9. Accessibility & UX Rules

- Destructive actions (delete) are always in a modal with a required type-to-confirm field
- Sensitive fields (password) use `type="password"` with a show/hide toggle
- Save buttons are per-field (not a single global Save) to reduce the blast radius of errors
- All error states surface as inline text below the field + a toast
- Mobile number is displayed but clearly marked as non-editable (disabled input with a lock icon)
- Account deletion dialog has a 2-second delay on the confirm button to prevent accidental rapid taps

---

## 10. Future Roadmap

| Feature | Priority | Notes |
|---|---|---|
| Email verification (OTP to inbox) | High | Required before using email for PDF delivery |
| Push notification preferences | Medium | `notify_order_updates`, `notify_promotions` toggles |
| My Children profiles | Medium | Save child name + photo for reuse across books |
| Profile photo / avatar | Low | Upload personal avatar for account header |
| Session management | Medium | "Sign out all devices" — invalidate all tokens on password change |
| Account reactivation | High | Admin endpoint to cancel pending deletion within grace period |
| Data export | Medium | DPDP Article 11 — download all personal data as ZIP |
| 2FA (TOTP) | Low | Google Authenticator / Authy for high-security users |

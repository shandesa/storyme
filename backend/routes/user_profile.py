"""
routes/user_profile.py
=======================
User profile endpoints — address book management.

Endpoints:
  GET    /api/v2/user/addresses              → list saved addresses
  POST   /api/v2/user/addresses              → add a new address
  PUT    /api/v2/user/addresses/{address_id} → update an existing address
  DELETE /api/v2/user/addresses/{address_id} → delete an address

All endpoints require a valid JWT session token (Authorization: Bearer <token>).
Mobile is extracted from the validated token — no spoofing possible via headers.

Address schema mirrors DeliveryAddressBody in print_orders.py so a saved
address can be passed directly to POST /api/v2/orders without transformation.
"""

from __future__ import annotations
import logging
from typing import Optional
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.session_tokens import require_mobile_from_request
from core.user_store import (
    get_user, update_user_profile, update_user_password,
    request_account_deletion, verify_password, hash_password, is_hashed,
)
from core.address_store import (
    list_addresses, get_address, upsert_address,
    delete_address, count_addresses, MAX_ADDRESSES_PER_USER,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/user", tags=["user_profile"])


# ─── Request models ───────────────────────────────────────────────────────────

class AddressBody(BaseModel):
    """
    Delivery address — same field set as DeliveryAddressBody in print_orders.py.
    Extra field: optional label (Home / Office / Other / custom).
    """
    label:    str = Field(default="Home", max_length=32)
    full_name: str = Field(..., min_length=2, max_length=100)
    line1:    str = Field(..., min_length=5, max_length=200)
    line2:    Optional[str] = Field(default=None, max_length=200)
    city:     str = Field(..., min_length=2, max_length=100)
    state:    str = Field(..., min_length=2, max_length=100)
    pincode:  str = Field(..., pattern=r"^\d{6}$")
    phone:    str = Field(..., pattern=r"^\d{10}$")
    country:  str = Field(default="India", max_length=50)


# ─── New profile request models ──────────────────────────────────────────────


class UpdateProfileBody(BaseModel):
    """Update display_name and/or email for the authenticated user."""
    display_name: str = Field(default="", max_length=60)
    email:        str = Field(default="", max_length=254)

    @staticmethod
    def _validate_email(email: str) -> str:
        """Basic email format validation."""
        import re
        if not email:
            return ""
        pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, email.strip()):
            raise ValueError(f"Invalid email format: {email!r}")
        return email.strip().lower()

    def model_post_init(self, __context):
        object.__setattr__(self, "email", self._validate_email(self.email or ""))
        object.__setattr__(self, "display_name", (self.display_name or "").strip())


class ChangePasswordBody(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password:     str = Field(..., min_length=6)


class DeleteAccountBody(BaseModel):
    """confirmation must equal exactly 'DELETE' (case-sensitive)."""
    confirmation:     str
    current_password: Optional[str] = None   # required if user has a password set


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/addresses")
async def list_user_addresses(request: Request):
    """
    List all saved addresses for the authenticated user.
    Returns addresses sorted by creation date (oldest first).
    """
    mobile = require_mobile_from_request(request)
    addresses = list_addresses(mobile)
    return {
        "addresses": addresses,
        "total":     len(addresses),
        "max":       MAX_ADDRESSES_PER_USER,
        "can_add":   len(addresses) < MAX_ADDRESSES_PER_USER,
    }


@router.post("/addresses", status_code=201)
async def add_address(body: AddressBody, request: Request):
    """
    Save a new delivery address for the authenticated user.
    Returns 400 if the user already has MAX_ADDRESSES_PER_USER addresses.
    """
    mobile = require_mobile_from_request(request)

    current_count = count_addresses(mobile)
    if current_count >= MAX_ADDRESSES_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Address limit reached ({MAX_ADDRESSES_PER_USER} max). "
                   "Please delete an existing address before adding a new one.",
        )

    address_dict = {
        "address_id": uuid.uuid4().hex,
        "label":      body.label,
        "full_name":  body.full_name.strip(),
        "line1":      body.line1.strip(),
        "line2":      (body.line2 or "").strip() or None,
        "city":       body.city.strip(),
        "state":      body.state.strip(),
        "pincode":    body.pincode.strip(),
        "phone":      body.phone.strip(),
        "country":    body.country or "India",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    saved = upsert_address(mobile, address_dict)
    logger.info("user_profile: added address %s for %s", saved["address_id"][:8], mobile)
    return {"address": saved, "message": "Address saved successfully."}


@router.put("/addresses/{address_id}")
async def update_address(address_id: str, body: AddressBody, request: Request):
    """
    Update an existing saved address.
    Returns 404 if address_id does not belong to the authenticated user.
    """
    mobile = require_mobile_from_request(request)

    existing = get_address(mobile, address_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Address '{address_id[:8]}' not found.",
        )

    updated_dict = {
        "address_id": address_id,
        "label":      body.label,
        "full_name":  body.full_name.strip(),
        "line1":      body.line1.strip(),
        "line2":      (body.line2 or "").strip() or None,
        "city":       body.city.strip(),
        "state":      body.state.strip(),
        "pincode":    body.pincode.strip(),
        "phone":      body.phone.strip(),
        "country":    body.country or "India",
        "created_at": existing.get("created_at", datetime.now(timezone.utc).isoformat()),
    }

    saved = upsert_address(mobile, updated_dict)
    logger.info("user_profile: updated address %s for %s", address_id[:8], mobile)
    return {"address": saved, "message": "Address updated successfully."}


@router.delete("/addresses/{address_id}", status_code=200)
async def remove_address(address_id: str, request: Request):
    """
    Delete a saved address.
    Returns 404 if address_id does not belong to the authenticated user.
    """
    mobile = require_mobile_from_request(request)

    existing = get_address(mobile, address_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Address '{address_id[:8]}' not found.",
        )

    deleted = delete_address(mobile, address_id)
    if not deleted:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete address. Please try again.",
        )

    logger.info("user_profile: deleted address %s for %s", address_id[:8], mobile)
    return {"address_id": address_id, "message": "Address deleted."}


# ─── Profile endpoints ────────────────────────────────────────────────────────


@router.get("/profile")
async def get_profile(request: Request):
    """
    Return the authenticated user's full profile (no password hash).

    Used by ProfileTab in UserAccountSheet to pre-populate form fields.
    """
    mobile = require_mobile_from_request(request)
    user   = get_user(mobile)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    return {
        "mobile":                user.get("mobile", ""),
        "country_code":          user.get("country_code", "+91"),
        "display_name":          user.get("display_name", ""),
        "email":                 user.get("email", ""),
        "account_status":        user.get("account_status", "active"),
        "deletion_requested_at": user.get("deletion_requested_at", ""),
        "terms_accepted":        user.get("terms_accepted", False),
        "created_at":            user.get("created_at", ""),
        "last_login_at":         user.get("last_login_at", ""),
    }


@router.put("/profile")
async def update_profile(body: UpdateProfileBody, request: Request):
    """
    Update display_name and/or email for the authenticated user.

    Both fields are optional — pass only the fields you want to change.
    If display_name is empty, it is cleared (falls back to masked mobile in UI).
    If email is empty, it is cleared.
    """
    mobile = require_mobile_from_request(request)
    user   = update_user_profile(mobile, body.display_name, body.email)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    logger.info("Profile updated for %s: name=%r email=%r", mobile, body.display_name, body.email)
    return {
        "status":       "updated",
        "display_name": user.get("display_name", ""),
        "email":        user.get("email", ""),
    }


@router.post("/password")
async def change_password(body: ChangePasswordBody, request: Request):
    """
    Change the authenticated user's password.

    Requires the current password for re-verification (even if already logged in).
    Returns 400 if no password is set (OTP-only registration; user must set one first).
    Returns 401 if current_password is wrong.
    """
    mobile = require_mobile_from_request(request)
    user   = get_user(mobile)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    stored_hash = user.get("password_hash", "")
    if not stored_hash:
        raise HTTPException(
            status_code=400,
            detail="No password is set on this account. Log in via OTP and set a password from Profile.",
        )

    if not verify_password(body.current_password, stored_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one.")

    new_hash = hash_password(body.new_password)
    updated  = update_user_password(mobile, new_hash)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update password. Please try again.")

    logger.info("Password changed for %s", mobile)
    return {"status": "password_changed"}


@router.delete("/account")
async def delete_account(body: DeleteAccountBody, request: Request):
    """
    Request deletion of the authenticated user's account (soft delete).

    - Sets account_status = "deletion_requested"
    - Sets deletion_requested_at = now()
    - Does NOT delete any data immediately (30-day grace period)
    - Subsequent login attempts will be rejected with HTTP 403

    Requires:
      - confirmation == "DELETE" (exact, case-sensitive)
      - current_password (if user has a password set)
    """
    if body.confirmation != "DELETE":
        raise HTTPException(
            status_code=400,
            detail="Confirmation must be exactly 'DELETE' (case-sensitive).",
        )

    mobile = require_mobile_from_request(request)
    user   = get_user(mobile)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if user.get("account_status") == "deletion_requested":
        raise HTTPException(
            status_code=409,
            detail="Account deletion already requested. Contact support@storyme.app to cancel.",
        )

    stored_hash = user.get("password_hash", "")
    if stored_hash and is_hashed(stored_hash):
        # User registered with a password — require current password verification
        if not body.current_password:
            raise HTTPException(
                status_code=400,
                detail="Current password is required to delete this account.",
            )
        if not verify_password(body.current_password, stored_hash):
            raise HTTPException(status_code=401, detail="Incorrect password.")

    updated = request_account_deletion(mobile)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to process deletion request. Please try again.")

    logger.info("Account deletion requested for %s", mobile)
    return {
        "status":      "deletion_requested",
        "grace_days":  30,
        "message":     (
            "Your account has been scheduled for deletion. "
            "All data will be permanently removed after 30 days. "
            "Contact support@storyme.app to cancel."
        ),
    }

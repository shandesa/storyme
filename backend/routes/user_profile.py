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

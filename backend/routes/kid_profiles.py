"""
routes/kid_profiles.py
=======================
Kid (child) profile management endpoints.

Endpoints:
  GET    /api/v2/kids                        → list profiles for logged-in user
  POST   /api/v2/kids                        → create new profile (multipart)
  GET    /api/v2/kids/{profile_id}           → get single profile
  PUT    /api/v2/kids/{profile_id}           → update name/gender/age/notes
  POST   /api/v2/kids/{profile_id}/photo     → upload/replace profile photo
  DELETE /api/v2/kids/{profile_id}           → delete profile + photo blob
  GET    /api/v2/kids/{profile_id}/photo     → serve profile photo (auth-gated)

Auth: all endpoints require a valid JWT (Authorization: Bearer <token>).
Mobile is extracted from the token — no spoofing possible via URL parameters.
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.session_tokens import require_mobile_from_request
from core.kid_profile_store import (
    list_profiles, get_profile, upsert_profile,
    delete_profile, count_profiles,
    MAX_KID_PROFILES_PER_USER,
)
from core.storage import storage
from core.storage_paths import profile_photo_path, VALID_GENDERS
from core.config import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/kids", tags=["kid_profiles"])


# ─── Request/response models ──────────────────────────────────────────────────

class UpdateProfileBody(BaseModel):
    name:   str           = Field(..., min_length=1, max_length=60)
    gender: str           = Field(..., pattern="^(male|female|neutral)$")
    age:    Optional[int] = Field(default=None, ge=0, le=12)
    notes:  Optional[str] = Field(default=None, max_length=200)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _profile_to_response(profile: dict, mobile: str) -> dict:
    """Convert stored profile dict → API response dict (never exposes blob path)."""
    pid       = profile.get("profile_id", "")
    has_photo = bool(profile.get("photo_blob_path"))
    return {
        "profile_id": pid,
        "name":       profile.get("name", ""),
        "gender":     profile.get("gender", "neutral"),
        "age":        int(profile.get("age", 0) or 0),
        "notes":      profile.get("notes", "") or "",
        "has_photo":  has_photo,
        "photo_url":  f"/api/v2/kids/{pid}/photo" if has_photo else None,
        "created_at": profile.get("created_at", ""),
        "updated_at": profile.get("updated_at", ""),
    }


def _save_photo(mobile: str, profile_id: str, upload: UploadFile) -> str:
    """
    Validate and persist the uploaded photo to permanent blob storage.
    Returns the blob path string.
    Raises HTTPException on validation failure.
    """
    if upload.content_type not in config.ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{upload.content_type}'. "
                   f"Allowed: {', '.join(config.ALLOWED_IMAGE_TYPES)}",
        )
    blob_path = profile_photo_path(mobile, profile_id)
    storage.save_file(upload.file, blob_path)
    logger.info("Kid profile photo saved: %s (profile=%s)", blob_path, profile_id[:8])
    return blob_path


# ─── GET /api/v2/kids ────────────────────────────────────────────────────────

@router.get("")
async def list_kid_profiles(request: Request):
    """
    List all kid profiles for the authenticated user.
    Returns profiles ordered by creation date (oldest first).
    """
    mobile   = require_mobile_from_request(request)
    profiles = list_profiles(mobile)
    return {
        "profiles": [_profile_to_response(p, mobile) for p in profiles],
        "total":    len(profiles),
        "max":      MAX_KID_PROFILES_PER_USER,
        "can_add":  len(profiles) < MAX_KID_PROFILES_PER_USER,
    }


# ─── POST /api/v2/kids ───────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_kid_profile(
    request: Request,
    name:   str                    = Form(...),
    gender: str                    = Form(...),
    age:    Optional[str]          = Form(default=None),
    notes:  Optional[str]          = Form(default=None),
    photo:  Optional[UploadFile]   = File(default=None),
):
    """
    Create a new kid profile for the authenticated user.

    Form fields:
      name    — child's first name (required, 1–60 chars)
      gender  — male | female | neutral (required)
      age     — integer 0–12 (optional)
      notes   — free text up to 200 chars (optional)
      photo   — JPEG/PNG/WEBP image up to 5MB (optional)
    """
    mobile = require_mobile_from_request(request)

    # Validate limit
    if count_profiles(mobile) >= MAX_KID_PROFILES_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Profile limit reached ({MAX_KID_PROFILES_PER_USER} max). "
                   "Please delete an existing profile before adding a new one.",
        )

    # Validate name
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Child's name is required.")
    if len(name) > 60:
        raise HTTPException(status_code=400, detail="Name must be 60 characters or fewer.")

    # Validate gender
    if gender not in VALID_GENDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid gender '{gender}'. Must be one of: {sorted(VALID_GENDERS)}",
        )

    # Validate age
    age_int: Optional[int] = None
    if age is not None and str(age).strip():
        try:
            age_int = int(age)
            if not (0 <= age_int <= 12):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Age must be an integer between 0 and 12.")

    # Validate notes
    notes_str = (notes or "").strip()[:200]

    profile_id     = uuid.uuid4().hex
    photo_blob_path = ""

    # Save photo if provided
    if photo and photo.filename:
        photo_blob_path = _save_photo(mobile, profile_id, photo)

    now     = datetime.now(timezone.utc).isoformat()
    profile = upsert_profile(mobile, {
        "profile_id":      profile_id,
        "user_mobile":     mobile,
        "name":            name,
        "gender":          gender,
        "age":             age_int or 0,
        "notes":           notes_str,
        "photo_blob_path": photo_blob_path,
        "created_at":      now,
    })

    logger.info("Kid profile created: %s for %s name=%r", profile_id[:8], mobile, name)
    return {
        "profile": _profile_to_response(profile, mobile),
        "message": "Profile created successfully.",
    }


# ─── GET /api/v2/kids/{profile_id} ──────────────────────────────────────────

@router.get("/{profile_id}")
async def get_kid_profile(profile_id: str, request: Request):
    """Return a single kid profile by ID."""
    mobile  = require_mobile_from_request(request)
    profile = get_profile(mobile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return {"profile": _profile_to_response(profile, mobile)}


# ─── PUT /api/v2/kids/{profile_id} ──────────────────────────────────────────

@router.put("/{profile_id}")
async def update_kid_profile(
    profile_id: str,
    body:       UpdateProfileBody,
    request:    Request,
):
    """
    Update kid profile metadata (name, gender, age, notes).
    Photo update uses a separate endpoint: POST /api/v2/kids/{id}/photo
    """
    mobile  = require_mobile_from_request(request)
    profile = get_profile(mobile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    updated = upsert_profile(mobile, {
        **profile,
        "name":   body.name.strip(),
        "gender": body.gender,
        "age":    body.age or 0,
        "notes":  (body.notes or "").strip()[:200],
    })
    logger.info("Kid profile updated: %s for %s", profile_id[:8], mobile)
    return {
        "profile": _profile_to_response(updated, mobile),
        "message": "Profile updated successfully.",
    }


# ─── POST /api/v2/kids/{profile_id}/photo ────────────────────────────────────

@router.post("/{profile_id}/photo")
async def update_kid_profile_photo(
    profile_id: str,
    request:    Request,
    photo:      UploadFile = File(...),
):
    """
    Upload or replace the profile photo.
    Overwrites the existing blob at the same path (no version history).
    Existing GeneratedBooks for this profile are NOT invalidated.
    """
    mobile  = require_mobile_from_request(request)
    profile = get_profile(mobile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    blob_path = _save_photo(mobile, profile_id, photo)
    updated   = upsert_profile(mobile, {**profile, "photo_blob_path": blob_path})

    logger.info("Kid profile photo updated: %s for %s", profile_id[:8], mobile)
    return {
        "profile": _profile_to_response(updated, mobile),
        "message": "Photo updated successfully.",
    }


# ─── DELETE /api/v2/kids/{profile_id} ────────────────────────────────────────

@router.delete("/{profile_id}")
async def delete_kid_profile(profile_id: str, request: Request):
    """
    Delete a kid profile.
    - Hard-deletes the KidProfiles table row.
    - Deletes the photo blob from storage (if any).
    - GeneratedBook records are NOT deleted (retained as order history).
    - PDF blobs in storage are NOT deleted (retained per retention policy).
    """
    mobile  = require_mobile_from_request(request)
    profile = get_profile(mobile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    # Delete photo blob first
    blob_path = profile.get("photo_blob_path", "")
    if blob_path:
        try:
            storage.delete_file(blob_path)
            logger.info("Kid profile photo deleted from blob: %s", blob_path)
        except Exception as exc:
            logger.warning("Failed to delete photo blob %s: %s", blob_path, exc)

    # Delete profile record
    ok = delete_profile(mobile, profile_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete profile. Please try again.")

    logger.info("Kid profile deleted: %s for %s", profile_id[:8], mobile)
    return {"profile_id": profile_id, "message": "Profile deleted."}


# ─── GET /api/v2/kids/{profile_id}/photo ─────────────────────────────────────

@router.get("/{profile_id}/photo")
async def serve_kid_profile_photo(profile_id: str, request: Request):
    """
    Serve the kid profile photo as an image response.
    Auth-gated: the authenticated user must own the profile.
    Returns 404 if no photo has been uploaded.
    """
    mobile  = require_mobile_from_request(request)
    profile = get_profile(mobile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    blob_path = profile.get("photo_blob_path", "")
    if not blob_path:
        raise HTTPException(status_code=404, detail="No photo uploaded for this profile.")

    try:
        data = storage.read_file(blob_path)
    except Exception as exc:
        logger.error("Failed to read profile photo %s: %s", blob_path, exc)
        raise HTTPException(status_code=404, detail="Photo not found in storage.")

    return StreamingResponse(
        io.BytesIO(data),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )

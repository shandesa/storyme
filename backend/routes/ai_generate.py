"""
routes/ai_generate.py
======================
AI-based full book generation endpoints (SPEC-004).

POST /api/v2/generate/ai-book      Start AI book generation
GET  /api/v2/ai-book/cache-status  Background page cache status

Auth: JWT required for all endpoints.
Status polling: reuse existing GET /api/v2/generate/status/{id}
"""
from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from core.session_tokens import require_mobile_from_request
from core.config import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2", tags=["ai_generate"])


@router.post("/generate/ai-book")
async def start_ai_book_generation(
    request:    Request,
    name:       str                  = Form(...),
    story_id:   str                  = Form("forest_of_smiles"),
    profile_id: Optional[str]        = Form(default=None),
    image:      Optional[UploadFile] = File(default=None),
    quality:    str                  = Form("medium"),
):
    """
    Start AI-based full book generation (18 pages).

    Either profile_id (uses stored profile photo) or image upload required.
    Returns generation_id immediately; poll /api/v2/generate/status/{id}.
    """
    mobile = require_mobile_from_request(request)

    if quality not in ("medium", "high"):
        raise HTTPException(status_code=400, detail="quality must be 'medium' or 'high'")

    # Lazy import — service raises RuntimeError if OPENAI_API_KEY not set
    try:
        from services.ai_book_service import ai_book_service
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI generation unavailable: {exc}")

    if ai_book_service is None:
        raise HTTPException(
            status_code=503,
            detail="AI generation is not configured. Set OPENAI_API_KEY in environment.",
        )

    child_name = (name or "").strip()
    if not child_name:
        raise HTTPException(status_code=400, detail="Child's name is required.")

    # Resolve user photo
    user_photo_bytes: Optional[bytes] = None

    if profile_id:
        from core.kid_profile_store import get_profile
        profile = get_profile(mobile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Kid profile not found.")
        blob_path = profile.get("photo_blob_path", "")
        if not blob_path:
            raise HTTPException(
                status_code=400,
                detail="This profile has no photo. Add a photo to the profile first.",
            )
        # Use profile name
        child_name = profile.get("name", child_name)
        try:
            from core.storage import storage
            user_photo_bytes = storage.read_file(blob_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read profile photo: {exc}")

    elif image and image.filename:
        if image.content_type not in config.ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: {config.ALLOWED_IMAGE_TYPES}",
            )
        user_photo_bytes = await image.read()

    else:
        raise HTTPException(
            status_code=400,
            detail="Either profile_id (saved profile) or an image upload is required.",
        )

    if not user_photo_bytes:
        raise HTTPException(status_code=400, detail="Could not read user photo.")

    result = await ai_book_service.start_generation(
        user_mobile      = mobile,
        child_name       = child_name,
        story_id         = story_id,
        user_photo_bytes = user_photo_bytes,
        quality          = quality,
    )

    logger.info(
        "AI book generation started: gen_id=%s child=%r story=%s quality=%s",
        result["generation_id"][:8], child_name, story_id, quality,
    )
    return result


@router.get("/ai-book/cache-status")
async def ai_book_cache_status(story_id: str = "forest_of_smiles", request: Request = None):
    """
    Return background page cache status for a story.
    Shows which pages are cached globally and which would trigger a DALL-E call.
    """
    require_mobile_from_request(request)

    try:
        from services.ai_book_service import ai_book_service
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if ai_book_service is None:
        raise HTTPException(status_code=503, detail="AI service not configured.")

    return ai_book_service.get_cache_status(story_id)

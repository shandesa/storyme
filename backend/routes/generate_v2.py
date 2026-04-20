"""V2 Generation API Routes
===========================

POST /api/v2/generate/preview  — upload face photo, get page-1 preview (base64)

Mode vocabulary (aligned with frontend + generate.py):
  "opencv"   → Classic Storybook: face_blend OpenCV pipeline (default)
  "ai"       → AI-Powered Storybook: model-based generation (future)

Legacy values still accepted for backward compatibility:
  "template" → treated as "opencv"
  "dalle"    → treated as "ai"

NOTE: GET /api/v2/stories lives in routes/stories.py (no cv2 dependency).

WHY generation_service IS IMPORTED LAZILY (inside the function):
  generation_service → image_service → cv2 → requires libxcb.so.1, libGL.so.1
  A top-level import would crash the router if native libs are missing.
  Lazy import keeps the router always registered; missing libs → HTTP 503.
"""

import base64
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from core.config import config
from core.storage_paths import GENERATION_MODE_OPENCV, GENERATION_MODE_AI

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["generate_v2"])

# Use config.UPLOADS_DIR — stable path regardless of Azure deployment slot.
# Never use Path(__file__).parent.parent — resolves to /tmp/<hash>/ on Azure.
UPLOAD_DIR = config.UPLOADS_DIR
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

# Accepted mode values from the frontend, plus legacy aliases kept for compat.
# Maps incoming value → internal generation_service mode string ("template"|"dalle").
_MODE_MAP = {
    # Current values (introduced with generation mode selector)
    GENERATION_MODE_OPENCV: "template",   # "opencv" → OpenCV/template pipeline
    GENERATION_MODE_AI:     "dalle",      # "ai"     → DALL-E / AI pipeline

    # Legacy values (generate_v2 previously only accepted these)
    "template": "template",
    "dalle":    "dalle",
}


@router.post("/generate/preview")
async def generate_preview(
    name: str = Form(...),
    image: UploadFile = File(...),
    story_id: str = Form("forest_of_smiles"),
    mode: str = Form(GENERATION_MODE_OPENCV),   # "opencv" | "ai" | "template" | "dalle"
    gender: str = Form("neutral"),               # "neutral" | "male" | "female"
):
    """
    Upload a face photo and receive a page-1 preview as a base64 PNG.

    Stateless — no session is created. The caller can proceed to
    POST /api/generate (v1) to generate the full PDF.

    Args:
        name:     Child's name
        image:    Child's photo (JPG/PNG/WEBP)
        story_id: e.g. "forest_of_smiles"
        mode:     "opencv" (default) | "ai" | "template" | "dalle"
        gender:   "neutral" (default) | "male" | "female"

    Returns:
        { "preview_image": "data:image/png;base64,..." }

    Raises:
        HTTP 503  native image libraries missing (cv2/mediapipe/libxcb)
        HTTP 400  invalid input
        HTTP 500  generation failure
    """
    # ── Lazy import: generation_service needs cv2/mediapipe/libxcb ───────────
    try:
        from services.generation_service import generation_service  # noqa: PLC0415
    except ImportError as lib_err:
        logger.error(
            "generation_service unavailable — native library missing: %s", lib_err,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Image generation is temporarily unavailable — "
                "required native libraries are not installed. "
                f"Missing: {lib_err}"
            ),
        )

    # ── Input validation ──────────────────────────────────────────────────────
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Child's name is required")
    if not image:
        raise HTTPException(status_code=400, detail="Image file is required")
    if image.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {image.content_type!r}. "
                   f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}",
        )

    # ── Mode normalisation ────────────────────────────────────────────────────
    # Accept "opencv"/"ai" (new) and "template"/"dalle" (legacy).
    # Unknown values default to "template" (opencv) rather than rejecting —
    # failing the whole preview for an unknown mode string is too disruptive.
    internal_mode = _MODE_MAP.get(mode.lower().strip(), "template")
    if mode.lower().strip() not in _MODE_MAP:
        logger.warning(
            "Unknown mode %r — defaulting to 'template' (opencv pipeline)", mode,
        )

    # ── Save upload ───────────────────────────────────────────────────────────
    ext = Path(image.filename or "upload.jpg").suffix or ".jpg"
    upload_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    content = await image.read()
    upload_path.write_bytes(content)

    try:
        preview_path = await generation_service.generate_preview_stateless(
            child_name=name.strip(),
            story_id=story_id,
            face_image_path=str(upload_path),
            mode=internal_mode,   # always "template" or "dalle" for generation_service
        )

        with open(preview_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        return {"preview_image": f"data:image/png;base64,{img_b64}"}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Preview generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {str(e)}")
    finally:
        try:
            upload_path.unlink(missing_ok=True)
        except Exception:
            pass

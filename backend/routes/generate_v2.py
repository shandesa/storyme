"""V2 Generation API Routes

POST /api/v2/stories                  — list available stories
POST /api/v2/generate/preview         — upload face photo, get page-1 preview (base64)

Note: The session-based flow (proceed/status/download) is planned for a future
iteration.  The stateless preview endpoint is fully functional for MVP.
"""

import base64
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from services.generation_service import generation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["generate_v2"])

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


@router.get("/stories")
async def list_stories():
    """List all available stories."""
    stories = generation_service.list_stories()
    return {"stories": stories}


@router.post("/generate/preview")
async def generate_preview(
    name: str = Form(...),
    image: UploadFile = File(...),
    story_id: str = Form("forest_of_smiles"),
    mode: str = Form("template"),  # "template" or "dalle"
):
    """
    Upload a face photo and receive a page-1 preview as a base64 PNG.

    This endpoint is fully stateless — no session is created.
    The caller receives the preview immediately and can proceed to call
    POST /api/generate (v1) to generate the full PDF.

    Returns:
        { "preview_image": "data:image/png;base64,..." }
    """
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
    if mode not in ("template", "dalle"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {mode!r}. Expected 'template' or 'dalle'.",
        )

    # Save uploaded file to disk so image_service can read it
    ext = Path(image.filename or "upload.jpg").suffix or ".jpg"
    upload_path = str(UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}")
    content = await image.read()
    with open(upload_path, "wb") as f:
        f.write(content)

    try:
        preview_path = await generation_service.generate_preview_stateless(
            child_name=name.strip(),
            story_id=story_id,
            face_image_path=upload_path,
            mode=mode,
        )

        # Return preview as base64 so the browser can display it without
        # needing a separate authenticated GET request.
        with open(preview_path, "rb") as f:
            img_bytes = f.read()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")

        return {"preview_image": f"data:image/png;base64,{img_b64}"}

    except ValueError as e:
        # Story not found, invalid mode, etc.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Preview generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {str(e)}")
    finally:
        # Always clean up the uploaded temp file
        try:
            Path(upload_path).unlink(missing_ok=True)
        except Exception:
            pass

"""V2 Generation API Routes

POST /api/v2/stories                  — list available stories
POST /api/v2/generate/preview         — upload face photo, get page-1 preview (base64)

Note: The session-based flow (proceed/status/download) is planned for a future
iteration.  The stateless preview endpoint is fully functional for MVP.

Storage notes:
  Uploaded photos are saved to the local filesystem via config.UPLOADS_DIR
  (which is always BACKEND_DIR/uploads regardless of STORAGE_TYPE). This
  gives a stable absolute path that image_service.extract_face() can read
  directly — avoiding the blob-key confusion that arises when passing
  absolute /tmp/... paths to AzureBlobStorage.read_file().

  The preview PNG returned by generation_service is always a local absolute
  path (image_service.compose_page() guarantees this). It is read with
  open() and returned as base64 — no storage abstraction needed.
"""

import base64
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from services.generation_service import generation_service
from core.config import config   # ← use config.UPLOADS_DIR for stable path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["generate_v2"])

# Always use the backend-relative uploads directory (config guarantees it exists).
# DO NOT use Path(__file__).parent.parent — on Azure App Service __file__ resolves
# to a /tmp/... deployment path that changes per deployment slot and is unrelated
# to the stable BACKEND_DIR the storage layer expects.
UPLOAD_DIR = config.UPLOADS_DIR
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

    # ── Save uploaded photo to stable local path ──────────────────────────────
    # Use config.UPLOADS_DIR (= BACKEND_DIR/uploads) so the path is always a
    # real local filesystem path — not a /tmp deployment artifact path.
    # image_service.extract_face() reads this file; on Azure, AzureBlobStorage
    # now handles absolute paths by reading from local FS directly.
    ext = Path(image.filename or "upload.jpg").suffix or ".jpg"
    upload_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    content = await image.read()
    upload_path.write_bytes(content)

    try:
        # generation_service returns an absolute local path to the preview PNG.
        # image_service.compose_page() always writes to local FS and returns
        # the local absolute path — safe to open() directly regardless of
        # STORAGE_TYPE.
        preview_path = await generation_service.generate_preview_stateless(
            child_name=name.strip(),
            story_id=story_id,
            face_image_path=str(upload_path),  # absolute local path
            mode=mode,
        )

        # Read preview bytes from local file and encode as base64
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
        # Clean up the uploaded temp file regardless of outcome
        try:
            upload_path.unlink(missing_ok=True)
        except Exception:
            pass


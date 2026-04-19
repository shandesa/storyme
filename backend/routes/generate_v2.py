"""V2 Generation API Routes
===========================

POST /api/v2/generate/preview  — upload face photo, get page-1 preview (base64)

NOTE: GET /api/v2/stories has been moved to routes/stories.py
--------------------------------------------------------------
It previously lived here and was silently broken whenever native image
libraries (cv2, mediapipe) failed to import. Moving it to stories.py
ensures the story list is ALWAYS available regardless of whether OpenCV
or libxcb is installed.

WHY generation_service IS IMPORTED LAZILY (inside the function, not here)
--------------------------------------------------------------------------
The import chain is:
  generation_service
    → image_service
        → cv2  (OpenCV)   → requires libxcb.so.1, libGL.so.1
        → mediapipe       → requires libxcb.so.1, libglib2.0

These shared libraries are installed by startup.sh via apt-get. If the
Azure portal Startup Command bypasses startup.sh (e.g. calling gunicorn
directly), the libraries are missing and ANY top-level import of
generation_service will raise ImportError.

With a top-level import, that error propagates to server.py which sets
generate_v2_router = None, killing every /api/v2/* endpoint including
the story list — resulting in an empty dropdown in the UI.

With a LAZY import (inside the function body), the router ALWAYS registers
successfully. The /api/v2/generate/preview endpoint returns HTTP 503 with
a clear message if the libs are missing, instead of silently killing the
entire router.
"""

import base64
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from core.config import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["generate_v2"])

# Use config.UPLOADS_DIR (= BACKEND_DIR/uploads) — a stable path that
# exists regardless of the deployment slot or container restart.
# Never use Path(__file__).parent.parent here: on Azure App Service,
# __file__ resolves into the /tmp/<hash>/ extraction directory which
# changes on every deployment.
UPLOAD_DIR = config.UPLOADS_DIR
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


@router.post("/generate/preview")
async def generate_preview(
    name: str = Form(...),
    image: UploadFile = File(...),
    story_id: str = Form("forest_of_smiles"),
    mode: str = Form("template"),
):
    """
    Upload a face photo and receive a page-1 preview as a base64 PNG.

    Stateless — no session is created. The caller can proceed to
    POST /api/generate (v1) to generate the full PDF.

    Returns:
        { "preview_image": "data:image/png;base64,..." }

    Raises:
        HTTP 503 if native image libraries (cv2/mediapipe/libxcb) are not
                 installed on the server. Install them via the Azure portal
                 Startup Command: prepend the apt-get install command.
        HTTP 400 for invalid input.
        HTTP 500 for generation failures.
    """
    # ── Lazy import: generation_service needs cv2/mediapipe/libxcb ───────────
    # If these native libraries are not installed, we return a clear 503
    # instead of crashing the router registration at startup.
    try:
        from services.generation_service import generation_service  # noqa: PLC0415
    except ImportError as lib_err:
        logger.error(
            f"generation_service unavailable — native library missing: {lib_err}. "
            "Install system deps via the Azure portal Startup Command: "
            "apt-get install -y libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 && gunicorn ..."
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Image generation is temporarily unavailable — "
                "required native libraries are not installed on this server instance. "
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
    if mode not in ("template", "dalle"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {mode!r}. Expected 'template' or 'dalle'.",
        )

    # ── Save upload to stable local path ──────────────────────────────────────
    # config.UPLOADS_DIR is always BACKEND_DIR/uploads — a real filesystem
    # path that image_service.extract_face() can open with cv2.imread().
    ext = Path(image.filename or "upload.jpg").suffix or ".jpg"
    upload_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    content = await image.read()
    upload_path.write_bytes(content)

    try:
        # generate_preview_stateless() returns an absolute local path to the
        # composited PNG. image_service.compose_page() always writes locally,
        # so open() is always safe here regardless of STORAGE_TYPE.
        preview_path = await generation_service.generate_preview_stateless(
            child_name=name.strip(),
            story_id=story_id,
            face_image_path=str(upload_path),
            mode=mode,
        )

        with open(preview_path, "rb") as f:
            img_bytes = f.read()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")

        return {"preview_image": f"data:image/png;base64,{img_b64}"}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Preview generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {str(e)}")
    finally:
        try:
            upload_path.unlink(missing_ok=True)
        except Exception:
            pass

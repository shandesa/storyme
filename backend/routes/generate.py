"""Generate Storybook API Route — v1

POST /api/generate
Accepts multipart form with name, image, story_id, mode, gender.
Returns the personalised PDF as a file download.

Generation modes:
  opencv (default) — face_blend pipeline: affine align → colour match → seamlessClone
  ai               — AI model-based image generation (requires OPENAI_API_KEY)

Both modes use the same storage layer, route code, and PDF builder.
Mode selection is stored in the generation session (MongoDB).

Template structure:
  backend/templates/stories/{story_id}/{gender}/templates/scene_XX.png
  backend/templates/stories/{story_id}/{gender}/references/scene_XX.png

Per-page resilience:
  Individual page failures are caught, logged, and skipped.
  The PDF always contains all successfully generated pages.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Optional
import logging
import uuid
import tempfile
import os
import re
from datetime import datetime, timezone

from services.story_service import story_registry, FACE_COORDS, SCENE_FILES
from services.image_service import image_service
from services.pdf_service import PDFService
from services.generation_mode import generate_page
from core.storage import storage
from core.config import config
from core.storage_paths import (
    upload_path as make_upload_path,
    generation_page_path,
    pdf_path as make_pdf_path,
    GENDER_NEUTRAL, VALID_GENDERS,
    GENERATION_MODE_OPENCV, GENERATION_MODE_AI,
)
from models.generation import GenerationMode, Gender

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["generate"])
pdf_service = PDFService(str(config.OUTPUT_DIR))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\-]", "_", name.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:64] or "unknown"


def _resolve_local(path: str) -> str:
    """Return absolute local path for cv2. Downloads blob to temp if non-local."""
    if config.STORAGE_TYPE == "local":
        return storage.get_file_path(path)
    data = storage.read_file(path)
    suffix = Path(path).suffix or ".png"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


def _cleanup_temp(path: str) -> None:
    if config.STORAGE_TYPE != "local":
        try:
            os.unlink(path)
        except Exception:
            pass


# ─── Generate endpoint ────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_storybook(
    name: str = Form(...),
    image: UploadFile = File(...),
    story_id: Optional[str] = Form(None),
    story_index: Optional[int] = Form(None),
    mode: str = Form(GENERATION_MODE_OPENCV),   # "opencv" | "ai"
    gender: str = Form(GENDER_NEUTRAL),           # "male" | "female" | "neutral"
):
    """
    Generate a personalised storybook PDF and return it as a download.

    Inputs:
        name:        Child's name
        image:       Child's photo (JPG/PNG/WEBP, max 5MB)
        story_id:    e.g. "forest_of_smiles"
        mode:        "opencv" (default) | "ai"
        gender:      "neutral" (default) | "male" | "female"
                     Selects which set of illustrated templates to use.

    Returns:
        PDF file download (Content-Disposition: attachment)
    """
    # ── Validation ────────────────────────────────────────────────────────────
    if not name or name.strip() == "":
        raise HTTPException(status_code=400, detail="Child's name is required")
    if not image:
        raise HTTPException(status_code=400, detail="Image file is required")
    if image.content_type not in config.ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(config.ALLOWED_IMAGE_TYPES)}",
        )
    if mode not in (GENERATION_MODE_OPENCV, GENERATION_MODE_AI):
        mode = GENERATION_MODE_OPENCV
    if gender not in VALID_GENDERS:
        gender = GENDER_NEUTRAL

    child_name = name.strip()
    gen_mode   = GenerationMode.OPENCV if mode == GENERATION_MODE_OPENCV else GenerationMode.AI
    gen_id     = uuid.uuid4().hex

    # ── Story selection ───────────────────────────────────────────────────────
    story = None
    if story_id:
        story = story_registry.get_story_by_id(story_id)
        if not story:
            raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")
    elif story_index is not None:
        story = story_registry.get_story_by_index(story_index)
        if not story:
            raise HTTPException(status_code=404, detail=f"Story not found at index {story_index}")
    else:
        story = story_registry.get_story_by_index(0)
        if not story:
            raise HTTPException(status_code=500, detail="No stories available")

    total_pages = len(story.pages)
    logger.info(
        "Generation start: child=%r story=%s mode=%s gender=%s pages=%d gen_id=%s",
        child_name, story.story_id, mode, gender, total_pages, gen_id[:8],
    )

    uploaded_blob_path = None
    local_upload_path  = None
    temp_paths_to_clean = []

    try:
        # ── Save uploaded photo ───────────────────────────────────────────────
        ext = Path(image.filename or "upload.jpg").suffix or ".jpg"
        uploaded_blob_path = make_upload_path(ext, gen_id)
        storage.save_file(image.file, uploaded_blob_path)

        local_upload_path = _resolve_local(uploaded_blob_path)
        if config.STORAGE_TYPE != "local":
            temp_paths_to_clean.append(local_upload_path)

        pages_data   = []
        failed_pages = []

        # ── Generate each page ────────────────────────────────────────────────
        for page in story.pages:
            fp          = page.face_placement
            scene_file  = SCENE_FILES[page.page_number - 1]  # scene_01.png ... scene_10.png
            face_cfg    = FACE_COORDS[scene_file]
            out_local   = str(config.OUTPUT_DIR / f"{gen_id}_{page.page_number:02d}.png")
            page_text   = page.text

            # Template and reference paths (local filesystem, bundled with app)
            template_local  = str(
                config.BACKEND_DIR /
                f"templates/stories/{story.story_id}/{gender}/templates/{scene_file}"
            )
            reference_local = str(
                config.BACKEND_DIR /
                f"templates/stories/{story.story_id}/{gender}/references/{scene_file}"
            )

            # Check template exists; warn clearly if not
            if not Path(template_local).exists():
                logger.warning(
                    "Page %d/%d: template missing at %s — skipping page",
                    page.page_number, total_pages, template_local,
                )
                failed_pages.append(page.page_number)
                continue

            try:
                # ── PRIMARY: generation mode pipeline ─────────────────────────
                result = generate_page(
                    mode=gen_mode,
                    template_path=template_local,
                    reference_path=reference_local,
                    user_face_path=local_upload_path,
                    face_config=face_cfg,
                    output_path=out_local,
                    child_name=child_name,
                    scene_text=page_text,
                )

                if result:
                    logger.info(
                        "Page %d/%d: %s ✓", page.page_number, total_pages, mode,
                    )
                    # Save page image to Azure Blob for evaluator + retrieval
                    page_blob_path = None
                    if config.STORAGE_TYPE in ("azure", "s3"):
                        page_blob_path = generation_page_path(gen_id, page.page_number)
                        try:
                            with open(result, "rb") as pf:
                                storage.save_file(pf, page_blob_path)
                        except Exception as _e:
                            logger.warning("Page %d blob upload failed (non-fatal): %s", page.page_number, _e)
                            page_blob_path = None
                    pages_data.append({
                        "text": page_text,
                        "image_path": result,
                        "blob_path": page_blob_path,
                        "page_number": page.page_number,
                        "scene_file": scene_file,
                    })
                    continue

                # ── FALLBACK: PIL pipeline ────────────────────────────────────
                logger.info(
                    "Page %d/%d: %s returned None — PIL fallback",
                    page.page_number, total_pages, mode,
                )
                face_img = image_service.extract_face(
                    uploaded_blob_path, (fp.width, fp.height), angle=fp.angle,
                )
                name_pos = name_font_size = name_color = None
                if page.name_placement:
                    name_pos = (page.name_placement.x, page.name_placement.y)
                    name_font_size = page.name_placement.font_size
                    name_color = page.name_placement.color
                circle_center = circle_radius = None
                if page.face_circle:
                    circle_center = (page.face_circle.cx, page.face_circle.cy)
                    circle_radius = page.face_circle.radius
                text_regions = None
                if page.name_text_regions:
                    text_regions = [
                        (r.x1, r.y1, r.x2, r.y2, r.line_text) if r.line_text
                        else (r.x1, r.y1, r.x2, r.y2)
                        for r in page.name_text_regions
                    ]
                fallback_out = f"output/{gen_id}_{page.page_number:02d}_fallback.png"
                composed = image_service.compose_page(
                    page.image_path, face_img, (fp.x, fp.y), fallback_out,
                    child_name=child_name,
                    name_position=name_pos,
                    name_font_size=name_font_size or 48,
                    name_color=name_color or (51, 51, 51),
                    face_circle_center=circle_center,
                    face_circle_radius=circle_radius,
                    name_text_regions=text_regions,
                )
                logger.info("Page %d/%d: PIL fallback ✓", page.page_number, total_pages)
                page_blob_path = None
                if config.STORAGE_TYPE in ("azure", "s3"):
                    page_blob_path = generation_page_path(gen_id, page.page_number)
                    try:
                        with open(composed, "rb") as pf:
                            storage.save_file(pf, page_blob_path)
                    except Exception as _e:
                        logger.warning("Page %d blob upload failed (non-fatal): %s", page.page_number, _e)
                        page_blob_path = None
                pages_data.append({
                    "text": page_text,
                    "image_path": composed,
                    "blob_path": page_blob_path,
                    "page_number": page.page_number,
                    "scene_file": scene_file,
                })

            except Exception as page_err:
                failed_pages.append(page.page_number)
                logger.warning(
                    "Page %d/%d FAILED — skipping. Error: %s",
                    page.page_number, total_pages, page_err,
                    exc_info=True,
                )

        # ── Generation summary ────────────────────────────────────────────────
        succeeded = len(pages_data)
        failed    = len(failed_pages)

        if succeeded == 0:
            logger.error(
                "ALL pages failed for %r story=%s — cannot produce PDF",
                child_name, story.story_id,
            )
            raise HTTPException(
                status_code=500,
                detail=f"All {total_pages} pages failed to generate. Please try again.",
            )
        elif failed > 0:
            logger.warning(
                "Partial success: %d/%d pages generated for %r "
                "(failed pages: %s). PDF will have %d pages.",
                succeeded, total_pages, child_name, failed_pages, succeeded,
            )
            if succeeded < total_pages // 2:
                logger.critical(
                    "CRITICAL: majority of pages failed (%d/%d) for %r story=%s",
                    failed, total_pages, child_name, story.story_id,
                )
        else:
            logger.info(
                "All %d/%d pages generated for %r", succeeded, total_pages, child_name,
            )

        # ── Build PDF ─────────────────────────────────────────────────────────
        ts           = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        pdf_filename = f"{_safe_name(child_name)}_{ts}_{gen_id[:8]}.pdf"

        pdf_local = pdf_service.create_storybook_pdf(
            child_name=child_name,
            story_title=story.title,
            pages_data=pages_data,
            output_filename=pdf_filename,
        )
        logger.info(
            "PDF: %s (%d pages, %d bytes)",
            pdf_filename, succeeded, Path(pdf_local).stat().st_size,
        )

        # ── Upload PDF to cloud storage ───────────────────────────────────────
        blob_pdf_path = None
        if config.STORAGE_TYPE in ("azure", "s3"):
            blob_pdf_path = make_pdf_path(child_name, story.story_id, gen_id)
            try:
                with open(pdf_local, "rb") as pf:
                    storage.save_file(pf, blob_pdf_path)
                logger.info("PDF uploaded to %s: %s", config.STORAGE_TYPE, blob_pdf_path)
            except Exception as upload_err:
                logger.warning("PDF upload failed (non-fatal): %s", upload_err)
                blob_pdf_path = None

        # ── Persist GenerationSession via session_store abstraction ─────────────
        # session_store routes to AzureTableSessionStore, MongoSessionStore,
        # or NullSessionStore based on available environment configuration.
        # This is non-fatal — PDF download proceeds even if the write fails.
        try:
            from core.session_store import session_store as _store
            from datetime import datetime, timezone as _tz
            session_dict = {
                "generation_id":   gen_id,
                "child_name":      child_name,
                "story_id":        story.story_id,
                "gender":          gender,
                "generation_mode": str(gen_mode.value if hasattr(gen_mode, "value") else gen_mode),
                "status":          "complete",
                "pdf_blob_path":   blob_pdf_path or "",
                "pdf_filename":    pdf_filename,
                "pages_succeeded": succeeded,
                "pages_failed":    failed,
                "total_pages":     total_pages,
                "completed_at":    datetime.now(_tz.utc).isoformat(),
                "page_results":    [
                    {
                        "page_number": pd["page_number"],
                        "blob_path":   pd.get("blob_path") or "",
                        "succeeded":   True,
                    }
                    for pd in pages_data if "page_number" in pd
                ],
            }
            await _store.write_session(session_dict)
            logger.info("Session %s persisted via %s", gen_id[:8], type(_store).__name__)
        except Exception as db_err:
            logger.warning("Session persist failed (non-fatal): %s", db_err)

        # ── Return PDF as download ────────────────────────────────────────────
        download_name = f"{_safe_name(child_name)}_storybook.pdf"
        return FileResponse(
            path=pdf_local,
            filename=download_name,
            media_type="application/pdf",
            headers={
                "Content-Disposition":  f'attachment; filename="{download_name}"',
                # X-Generation-ID allows the frontend to link this PDF download
                # to the GenerationSession for subsequent print ordering.
                # Exposed via CORS expose_headers in server.py.
                "X-Generation-ID":      gen_id,
                "X-Child-Name":         child_name,
                "X-Story-ID":           story.story_id,
                "Access-Control-Expose-Headers": "X-Generation-ID, X-Child-Name, X-Story-ID",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error generating storybook: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating storybook: {str(e)}")

    finally:
        if uploaded_blob_path:
            try:
                storage.delete_file(uploaded_blob_path)
            except Exception:
                pass
        for tmp in temp_paths_to_clean:
            _cleanup_temp(tmp)

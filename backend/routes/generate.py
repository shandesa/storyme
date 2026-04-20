"""Generate Storybook API Route — v1

POST /api/generate
Accepts multipart form with name, image, optional story_id/story_index.
Returns the personalised PDF as a file download.

This is the primary PDF generation endpoint called by the frontend when
the user clicks "Proceed — Generate Full Book" after reviewing the preview.

Generation pipeline per page:
  PRIMARY  → face_blend_service.process_scene()
             Full playground pipeline: affine align → hull extract →
             LAB colour match → luminance match → seamlessClone
  FALLBACK → image_service PIL pipeline (Haar + paste + oval mask)
             Used when MediaPipe detects no face, or seamlessClone fails.

Partial-failure resilience:
  If individual pages fail (missing template, blend error, etc.) the failure
  is logged with a WARNING and generation continues with remaining pages.
  The PDF is always produced from whatever pages succeeded.
  A CRITICAL log is emitted when < 50% of pages succeeded.

PDF storage:
  The PDF is always returned as a download response.
  When STORAGE_TYPE=azure/s3, a copy is also saved to:
    pdfs/{sanitized_child_name}/{story_id}/{YYYYMMDD_HHMMSS}_{uuid8}.pdf
  This path is deterministic and suitable for later retrieval.
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

from services.story_service import story_registry
from services.image_service import image_service
from services.pdf_service import PDFService
from core.storage import storage
from core.config import config
from services.face_blend_service import process_scene as blend_face_scene

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["generate"])
pdf_service = PDFService(str(config.OUTPUT_DIR))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sanitize_name(name: str) -> str:
    """
    Sanitize a child name / story id for use in a blob storage path.
    Replaces any character that isn't alphanumeric, hyphen, or underscore
    with an underscore, and collapses runs of underscores.
    """
    cleaned = re.sub(r"[^\w\-]", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:64] or "unknown"


def _resolve_local(path: str) -> str:
    """
    Return an absolute local filesystem path usable by cv2.imread().

    For local storage: delegates to storage.get_file_path().
    For Azure/S3: downloads the blob to a temporary file and returns its path.
    The caller is responsible for deleting temp files via _cleanup_temp().
    """
    if config.STORAGE_TYPE == "local":
        return storage.get_file_path(path)
    data = storage.read_file(path)
    suffix = Path(path).suffix or ".png"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


def _cleanup_temp(path: str) -> None:
    """Delete a temp file created by _resolve_local (no-op for local storage)."""
    if config.STORAGE_TYPE != "local":
        try:
            os.unlink(path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# PDF storage path builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_pdf_storage_path(child_name: str, story_id: str, filename: str) -> str:
    """
    Build a structured storage path for the generated PDF.

    Format: pdfs/{child_name}/{story_id}/{filename}
    Example: pdfs/Niku/forest_of_smiles/20260420_162530_a1b2c3d4.pdf

    This path is consistent and can be used for later retrieval by:
      - child name (browse all books for a child)
      - story id  (browse all generations of a story)
    """
    safe_name = _sanitize_name(child_name)
    safe_story = _sanitize_name(story_id)
    return f"pdfs/{safe_name}/{safe_story}/{filename}"


# ─────────────────────────────────────────────────────────────────────────────
# Generate endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_storybook(
    name: str = Form(...),
    image: UploadFile = File(...),
    story_id: Optional[str] = Form(None),
    story_index: Optional[int] = Form(None),
):
    """
    Generate a personalised storybook PDF and return it as a download.

    Called by the frontend when the user clicks "Proceed — Generate Full Book"
    after approving the page-1 preview. Receives the same inputs as the
    preview endpoint (name + photo + story selection).

    Returns:
        PDF file download (Content-Disposition: attachment)

    Partial-failure behaviour:
        Individual page failures are caught, logged as WARNING, and skipped.
        Generation continues with remaining pages. The returned PDF contains
        all successfully generated pages. If zero pages succeed, HTTP 500.
    """
    # ── Input validation ──────────────────────────────────────────────────────
    if not name or name.strip() == "":
        raise HTTPException(status_code=400, detail="Child's name is required")
    if not image:
        raise HTTPException(status_code=400, detail="Image file is required")
    if image.content_type not in config.ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(config.ALLOWED_IMAGE_TYPES)}",
        )

    child_name = name.strip()

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
        "Starting full storybook generation: child=%r story=%s pages=%d",
        child_name, story.story_id, total_pages,
    )

    uploaded_file_path = None
    local_upload_path = None
    temp_paths_to_clean = []

    try:
        # ── Save uploaded photo ───────────────────────────────────────────────
        ext = Path(image.filename or "upload.jpg").suffix or ".jpg"
        uploaded_file_path = f"uploads/{uuid.uuid4()}{ext}"
        storage.save_file(image.file, uploaded_file_path)

        local_upload_path = _resolve_local(uploaded_file_path)
        if config.STORAGE_TYPE != "local":
            temp_paths_to_clean.append(local_upload_path)

        pages_data = []
        failed_pages = []

        # ── Generate each page ────────────────────────────────────────────────
        for page in story.pages:
            fp = page.face_placement
            out_path = f"output/{uuid.uuid4().hex}_{page.page_number}.png"

            try:
                local_template_path = _resolve_local(page.image_path)
                if config.STORAGE_TYPE != "local":
                    temp_paths_to_clean.append(local_template_path)

                local_out_path = str(config.OUTPUT_DIR / Path(out_path).name)

                # ── PRIMARY: playground blend pipeline ────────────────────────
                blended_path = None
                face_config_dict = {
                    "x": fp.x, "y": fp.y,
                    "w": fp.width, "h": fp.height,
                }
                try:
                    blended_path = blend_face_scene(
                        template_path=local_template_path,
                        user_face_path=local_upload_path,
                        face_config=face_config_dict,
                        output_path=local_out_path,
                    )
                    if blended_path:
                        logger.info("Page %d/%d: playground blend ✓", page.page_number, total_pages)
                except Exception as blend_err:
                    logger.warning(
                        "Page %d/%d: playground blend failed (%s) — trying PIL fallback",
                        page.page_number, total_pages, blend_err,
                    )
                    blended_path = None

                # ── FALLBACK: PIL pipeline ────────────────────────────────────
                if blended_path is None:
                    face_img = image_service.extract_face(
                        uploaded_file_path, (fp.width, fp.height), angle=fp.angle,
                    )
                    name_pos = None
                    name_font_size = 48
                    name_color = (51, 51, 51)
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

                    composed = image_service.compose_page(
                        page.image_path, face_img, (fp.x, fp.y), out_path,
                        child_name=child_name,
                        name_position=name_pos,
                        name_font_size=name_font_size,
                        name_color=name_color,
                        face_circle_center=circle_center,
                        face_circle_radius=circle_radius,
                        name_text_regions=text_regions,
                    )
                    logger.info("Page %d/%d: PIL fallback ✓", page.page_number, total_pages)
                    pages_data.append({"text": page.text, "image_path": composed})
                    continue  # skip text-overlay block below

                # ── Text/name overlay on playground blend output ──────────────
                name_pos = None
                name_font_size = 48
                name_color = (51, 51, 51)
                if page.name_placement:
                    name_pos = (page.name_placement.x, page.name_placement.y)
                    name_font_size = page.name_placement.font_size
                    name_color = page.name_placement.color

                text_regions = None
                if page.name_text_regions:
                    text_regions = [
                        (r.x1, r.y1, r.x2, r.y2, r.line_text) if r.line_text
                        else (r.x1, r.y1, r.x2, r.y2)
                        for r in page.name_text_regions
                    ]

                from PIL import Image as PilImage
                dummy_face = PilImage.new("RGBA", (1, 1), (0, 0, 0, 0))
                blended_storage_path = f"output/{Path(blended_path).name}"

                final_path = image_service.compose_page(
                    blended_storage_path, dummy_face, (0, 0), out_path,
                    child_name=child_name,
                    name_position=name_pos,
                    name_font_size=name_font_size,
                    name_color=name_color,
                    face_circle_center=None,
                    face_circle_radius=None,
                    name_text_regions=text_regions,
                )
                pages_data.append({"text": page.text, "image_path": final_path})

            except Exception as page_err:
                # ── Per-page failure: log and continue ────────────────────────
                # A single page failing must NOT abort the entire storybook.
                # We log the error, record the failure, and move on.
                failed_pages.append(page.page_number)
                logger.warning(
                    "Page %d/%d FAILED — skipping this page and continuing. "
                    "Error: %s",
                    page.page_number, total_pages, page_err,
                    exc_info=True,
                )
                continue

        # ── Generation summary logging ────────────────────────────────────────
        succeeded = len(pages_data)
        failed = len(failed_pages)

        if failed == 0:
            logger.info(
                "Generation complete: %d/%d pages generated successfully for %r",
                succeeded, total_pages, child_name,
            )
        elif succeeded == 0:
            logger.error(
                "Generation FAILED: 0/%d pages succeeded for %r story=%s. "
                "All pages failed — cannot produce a PDF.",
                total_pages, child_name, story.story_id,
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"All {total_pages} pages failed to generate. "
                    "Please try again — the server logs contain details."
                ),
            )
        else:
            logger.warning(
                "Partial generation: %d/%d pages succeeded, %d pages FAILED "
                "(pages: %s) for child=%r story=%s. "
                "PDF will contain only the %d successful pages.",
                succeeded, total_pages, failed, failed_pages,
                child_name, story.story_id, succeeded,
            )
            # Emit CRITICAL when majority of pages failed
            if succeeded < total_pages // 2:
                logger.critical(
                    "CRITICAL: Majority of pages failed (%d/%d) for %r. "
                    "Review generate.py and image_service for systematic errors.",
                    failed, total_pages, child_name,
                )

        # ── Build PDF filename with timestamp for storage path ────────────────
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        uid8 = uuid.uuid4().hex[:8]
        pdf_filename = f"{_sanitize_name(child_name)}_{ts}_{uid8}.pdf"

        # ── Generate PDF ──────────────────────────────────────────────────────
        story_title_personalised = story.title.replace("{name}", child_name)
        pdf_path = pdf_service.create_storybook_pdf(
            child_name=child_name,
            story_title=story_title_personalised,
            pages_data=pages_data,
            output_filename=pdf_filename,
        )

        pdf_size = Path(pdf_path).stat().st_size
        logger.info(
            "PDF created: %s (%d bytes, %d/%d pages, child=%r)",
            pdf_filename, pdf_size, succeeded, total_pages, child_name,
        )

        # ── Upload PDF to cloud storage for later retrieval ───────────────────
        # Stored at: pdfs/{child_name}/{story_id}/{timestamp_uuid}.pdf
        # Retrievable by child name and story for future download features.
        if config.STORAGE_TYPE in ("azure", "s3"):
            storage_pdf_path = _build_pdf_storage_path(
                child_name, story.story_id, pdf_filename
            )
            try:
                with open(pdf_path, "rb") as pdf_file:
                    storage.save_file(pdf_file, storage_pdf_path)
                logger.info(
                    "PDF uploaded to %s storage: %s",
                    config.STORAGE_TYPE, storage_pdf_path,
                )
            except Exception as upload_err:
                # Non-fatal: local PDF is the source of truth for this response.
                # Upload failure should not prevent the user from downloading.
                logger.warning(
                    "PDF upload to %s failed (non-fatal, local file intact): %s",
                    config.STORAGE_TYPE, upload_err,
                )

        # ── Return PDF as download ─────────────────────────────────────────────
        download_name = f"{_sanitize_name(child_name)}_storybook.pdf"
        return FileResponse(
            path=pdf_path,
            filename=download_name,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error generating storybook: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating storybook: {str(e)}")

    finally:
        # Clean up uploaded user photo (don't store user photos long-term)
        if uploaded_file_path:
            try:
                storage.delete_file(uploaded_file_path)
            except Exception:
                pass
        # Clean up temp files created for non-local storage backends
        for tmp in temp_paths_to_clean:
            _cleanup_temp(tmp)

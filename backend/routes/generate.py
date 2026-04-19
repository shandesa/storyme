"""Generate Storybook API Route — v1

POST /api/generate
Accepts multipart form with name, image, optional story_id/story_index.
Returns personalized PDF.

Face Blending Pipeline (updated):
  1. PRIMARY  → face_blend_service.process_scene()
               Full playground pipeline: affine align → hull extract →
               LAB colour match → luminance match → seamlessClone
  2. FALLBACK → image_service PIL pipeline (Haar + paste + oval mask)
               Used when MediaPipe detects no face, or seamlessClone fails.

Text/Name Overlay:
  Always handled by image_service after blending (PIL rendering).

Storage:
  Supports local / Azure Blob / S3 via core.storage abstraction.
  Final PDFs uploaded to configured storage backend.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Optional
import logging
import uuid
import tempfile
import os

from services.story_service import story_registry
from services.image_service import image_service
from services.pdf_service import PDFService
from core.storage import storage
from core.config import config

# ── New playground-based face blending ───────────────────────────────────────
# process_scene() is the module-level function ported from
# tests/playground/face_blend.py. It replaces the legacy FaceBlendService.
from services.face_blend_service import process_scene as blend_face_scene

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["generate"])
pdf_service = PDFService(str(config.OUTPUT_DIR))


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: resolve storage path → absolute local path for cv2
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_local(path: str) -> str:
    """
    Convert a storage-relative path to an absolute local filesystem path.

    process_scene() calls cv2.imread() which requires a real filesystem path.
    Azure/S3 storage backends return URLs, so we download to a temp file when
    the configured backend is not local.
    """
    if config.STORAGE_TYPE == 'local':
        return storage.get_file_path(path)
    # Non-local backend: download bytes to a temp file
    data = storage.read_file(path)
    suffix = Path(path).suffix or ".png"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


def _cleanup_temp(path: str) -> None:
    """Remove a temp file created by _resolve_local if storage is non-local."""
    if config.STORAGE_TYPE != 'local':
        try:
            os.unlink(path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# GENERATE ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_storybook(
    name: str = Form(...),
    image: UploadFile = File(...),
    story_id: Optional[str] = Form(None),
    story_index: Optional[int] = Form(None),
):
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

    logger.info(f"Generating storybook for '{name}', story={story.story_id}")

    uploaded_file_path = None
    local_upload_path  = None
    temp_paths_to_clean = []

    try:
        # ── Save uploaded photo ───────────────────────────────────────────────
        ext = Path(image.filename).suffix or ".jpg"
        uploaded_file_path = f"uploads/{uuid.uuid4()}{ext}"
        storage.save_file(image.file, uploaded_file_path)

        # Resolve to a local path for cv2 (downloads blob to temp if non-local)
        local_upload_path = _resolve_local(uploaded_file_path)
        if config.STORAGE_TYPE != 'local':
            temp_paths_to_clean.append(local_upload_path)

        pages_data = []

        for page in story.pages:
            fp = page.face_placement
            out_path = f"output/{uuid.uuid4().hex}_{page.page_number}.png"

            # Resolve template to local path for cv2
            local_template_path = _resolve_local(page.image_path)
            if config.STORAGE_TYPE != 'local':
                temp_paths_to_clean.append(local_template_path)

            local_out_path = str(config.OUTPUT_DIR / Path(out_path).name)

            # ── FACE BLENDING ─────────────────────────────────────────────────
            #
            # PRIMARY: playground pipeline (affine align + colour match + seamlessClone)
            #   face_config maps directly from Page.face_placement (FacePlacement model)
            #   → {x, y, w, h} pixel coordinates in the template
            #
            # FALLBACK: PIL pipeline (Haar cascade + oval mask paste)
            #   Used when MediaPipe finds no face, or seamlessClone errors.
            #
            blended_path = None

            face_config = {
                "x": fp.x,
                "y": fp.y,
                "w": fp.width,
                "h": fp.height,
            }

            try:
                blended_path = blend_face_scene(
                    template_path=local_template_path,
                    user_face_path=local_upload_path,
                    face_config=face_config,
                    output_path=local_out_path,
                )
                if blended_path:
                    logger.info(f"Page {page.page_number}: playground blend ✅")
            except Exception as blend_err:
                logger.warning(
                    f"Page {page.page_number}: playground blend raised {blend_err} — "
                    "falling back to PIL pipeline"
                )
                blended_path = None

            if blended_path is None:
                # ── FALLBACK: PIL pipeline ────────────────────────────────────
                logger.info(f"Page {page.page_number}: using PIL fallback pipeline")

                face_img = image_service.extract_face(
                    uploaded_file_path,
                    (fp.width, fp.height),
                    angle=fp.angle,
                )

                name_pos = None
                name_font_size = 48
                name_color = (51, 51, 51)
                if page.name_placement:
                    name_pos = (page.name_placement.x, page.name_placement.y)
                    name_font_size = page.name_placement.font_size
                    name_color = page.name_placement.color

                circle_center = None
                circle_radius = None
                if page.face_circle:
                    circle_center = (page.face_circle.cx, page.face_circle.cy)
                    circle_radius = page.face_circle.radius

                text_regions = None
                if page.name_text_regions:
                    text_regions = [
                        (r.x1, r.y1, r.x2, r.y2, r.line_text)
                        if r.line_text else (r.x1, r.y1, r.x2, r.y2)
                        for r in page.name_text_regions
                    ]

                composed = image_service.compose_page(
                    page.image_path,
                    face_img,
                    (fp.x, fp.y),
                    out_path,
                    child_name=name,
                    name_position=name_pos,
                    name_font_size=name_font_size,
                    name_color=name_color,
                    face_circle_center=circle_center,
                    face_circle_radius=circle_radius,
                    name_text_regions=text_regions,
                )
                pages_data.append({"text": page.text, "image_path": composed})
                continue   # skip the text-overlay block below

            # ── TEXT / NAME OVERLAY on top of playground blend ────────────────
            # The blended_path is a raw PNG with face composited.
            # Apply child name and story text using the PIL image_service helpers.
            #
            # We re-use compose_page with the blended image AS the template
            # (no face blending since circle_center=None), which only renders
            # the name/text overlay on top.
            #
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
                    (r.x1, r.y1, r.x2, r.y2, r.line_text)
                    if r.line_text else (r.x1, r.y1, r.x2, r.y2)
                    for r in page.name_text_regions
                ]

            # Use a transparent 1×1 face so compose_page skips face compositing
            from PIL import Image as PilImage
            dummy_face = PilImage.new("RGBA", (1, 1), (0, 0, 0, 0))

            # compose_page expects storage-relative path; write blended as output
            blended_storage_path = f"output/{Path(blended_path).name}"

            final_path = image_service.compose_page(
                blended_storage_path,       # blended image is now the "template"
                dummy_face,                  # transparent — no face re-paste
                (0, 0),                      # position irrelevant (1×1 transparent)
                out_path,                    # final output storage path
                child_name=name,
                name_position=name_pos,
                name_font_size=name_font_size,
                name_color=name_color,
                face_circle_center=None,     # no circle inpainting — face already blended
                face_circle_radius=None,
                name_text_regions=text_regions,
            )

            pages_data.append({"text": page.text, "image_path": final_path})

        # ── Generate PDF ──────────────────────────────────────────────────────
        pdf_filename = f"{name.replace(' ', '_')}_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = pdf_service.create_storybook_pdf(
            child_name=name,
            story_title=story.title,
            pages_data=pages_data,
            output_filename=pdf_filename,
        )

        logger.info(f"PDF generated: {pdf_path} ({Path(pdf_path).stat().st_size} bytes)")

        # ── Upload PDF to configured storage (Azure / S3 / local) ────────────
        if config.STORAGE_TYPE in ('azure', 's3'):
            with open(pdf_path, 'rb') as pdf_file:
                storage_pdf_path = f"output/pdfs/{pdf_filename}"
                storage.save_file(pdf_file, storage_pdf_path)
            logger.info(f"PDF uploaded to {config.STORAGE_TYPE} storage: {storage_pdf_path}")

        return FileResponse(
            path=pdf_path,
            filename=pdf_filename,
            media_type="application/pdf",
        )

    except Exception as e:
        logger.error(f"Error generating storybook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating storybook: {str(e)}")

    finally:
        # Clean up uploaded user photo from storage
        if uploaded_file_path:
            try:
                storage.delete_file(uploaded_file_path)
            except Exception:
                pass

        # Clean up any temp files created for non-local storage backends
        for tmp in temp_paths_to_clean:
            _cleanup_temp(tmp)

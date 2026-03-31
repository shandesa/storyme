"""Generate Storybook API Route

POST /api/generate
Accepts multipart form with name, image, optional story_id/story_index.
Returns personalized PDF.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Optional
import logging
import uuid

from services.story_service import story_registry
from services.image_service import image_service
from services.pdf_service import PDFService
from core.storage import storage
from core.config import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["generate"])
pdf_service = PDFService(str(config.OUTPUT_DIR))


@router.post("/generate")
async def generate_storybook(
    name: str = Form(...),
    image: UploadFile = File(...),
    story_id: Optional[str] = Form(None),
    story_index: Optional[int] = Form(None),
):
    if not name or name.strip() == "":
        raise HTTPException(status_code=400, detail="Child's name is required")
    if not image:
        raise HTTPException(status_code=400, detail="Image file is required")
    if image.content_type not in config.ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(config.ALLOWED_IMAGE_TYPES)}",
        )

    # Story selection
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
    try:
        # Save upload
        ext = Path(image.filename).suffix
        uploaded_file_path = f"uploads/{uuid.uuid4()}{ext}"
        storage.save_file(image.file, uploaded_file_path)

        pages_data = []

        for page in story.pages:
            fp = page.face_placement

            # Extract face
            face_img = image_service.extract_face(
                uploaded_file_path,
                (fp.width, fp.height),
                angle=fp.angle,
            )

            out_path = f"output/{uuid.uuid4().hex}_{page.page_number}.png"

            # Name placement
            name_pos = None
            name_font_size = 48
            name_color = (51, 51, 51)
            if page.name_placement:
                name_pos = (page.name_placement.x, page.name_placement.y)
                name_font_size = page.name_placement.font_size
                name_color = page.name_placement.color

            # Face circle (for advanced compositing on illustrated templates)
            circle_center = None
            circle_radius = None
            if page.face_circle:
                circle_center = (page.face_circle.cx, page.face_circle.cy)
                circle_radius = page.face_circle.radius

            # Baked-in {name} text regions (list)
            text_regions = None
            if page.name_text_regions:
                text_regions = [
                    (r.x1, r.y1, r.x2, r.y2, r.line_text) if r.line_text else (r.x1, r.y1, r.x2, r.y2)
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

        # Generate PDF
        pdf_filename = f"{name.replace(' ', '_')}_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = pdf_service.create_storybook_pdf(
            child_name=name,
            story_title=story.title,
            pages_data=pages_data,
            output_filename=pdf_filename,
        )

        logger.info(f"PDF generated: {pdf_path} ({Path(pdf_path).stat().st_size} bytes)")

        return FileResponse(path=pdf_path, filename=pdf_filename, media_type="application/pdf")

    except Exception as e:
        logger.error(f"Error generating storybook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error generating storybook: {str(e)}")

    finally:
        if uploaded_file_path:
            try:
                storage.delete_file(uploaded_file_path)
            except Exception:
                pass

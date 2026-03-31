"""Generate Storybook API Route

Handles storybook generation with support for:
- Story selection by ID or index
- Image upload and processing
- PDF generation
- Storage abstraction for S3 compatibility

POST /api/generate
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

# Initialize PDF service
pdf_service = PDFService(str(config.OUTPUT_DIR))


@router.post("/generate")
async def generate_storybook(
    name: str = Form(...),
    image: UploadFile = File(...),
    story_id: Optional[str] = Form(None),
    story_index: Optional[int] = Form(None)
):
    """Generate personalized storybook PDF.
    
    Args:
        name: Child's name
        image: Uploaded photo of the child
        story_id: Story identifier (e.g., 'forest_of_smiles') - optional
        story_index: Story index (0-based) - optional
    
    Priority:
        - If story_id provided, use it
        - Else if story_index provided, use it
        - Else use default (index 0)
    
    Returns:
        FileResponse with PDF download
    """
    
    # ========================================================================
    # Validation
    # ========================================================================
    if not name or name.strip() == "":
        raise HTTPException(status_code=400, detail="Child's name is required")
    
    if not image:
        raise HTTPException(status_code=400, detail="Image file is required")
    
    # Validate file type
    if image.content_type not in config.ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(config.ALLOWED_IMAGE_TYPES)}"
        )
    
    # ========================================================================
    # Story Selection
    # ========================================================================
    story = None
    
    # Priority 1: story_id
    if story_id:
        story = story_registry.get_story_by_id(story_id)
        if not story:
            raise HTTPException(
                status_code=404,
                detail=f"Story not found: {story_id}"
            )
        logger.info(f"Selected story by ID: {story_id}")
    
    # Priority 2: story_index
    elif story_index is not None:
        story = story_registry.get_story_by_index(story_index)
        if not story:
            raise HTTPException(
                status_code=404,
                detail=f"Story not found at index {story_index}"
            )
        logger.info(f"Selected story by index: {story_index}")
    
    # Default: First story
    else:
        story = story_registry.get_story_by_index(0)
        if not story:
            raise HTTPException(
                status_code=500,
                detail="No stories available"
            )
        logger.info(f"Using default story: {story.story_id}")
    
    uploaded_file_path = None
    
    try:
        # ====================================================================
        # Save Uploaded Image
        # ====================================================================
        file_extension = Path(image.filename).suffix
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        uploaded_file_path = f"uploads/{unique_filename}"
        
        storage.save_file(image.file, uploaded_file_path)
        logger.info(f"Uploaded file saved: {uploaded_file_path}")
        
        # ====================================================================
        # Process Each Page
        # ====================================================================
        pages_data = []
        
        for page in story.pages:
            # Extract and resize face for this page
            face_img = image_service.extract_face(
                uploaded_file_path,
                (page.face_placement.width, page.face_placement.height)
            )
            
            # Compose page (paste face onto template + overlay name)
            output_filename = f"output/{uuid.uuid4().hex}_{page.page_number}.png"
            
            # Calculate name position (for page 1, overlay on the {name} placeholder)
            # Page 1 has text at approximately (384, 460) based on template analysis
            name_position = None
            if page.page_number == 1:
                # Position for overlaying name on "{name}" in the template
                template_width = 1536  # Known from template analysis
                template_height = 1024
                name_position = (int(template_width * 0.25), int(template_height * 0.45))
            
            composed_image_path = image_service.compose_page(
                page.image_path,
                face_img,
                (page.face_placement.x, page.face_placement.y),
                output_filename,
                child_name=name if name_position else None,
                name_position=name_position
            )
            
            pages_data.append({
                'text': page.text,
                'image_path': composed_image_path
            })
        
        # ====================================================================
        # Generate PDF
        # ====================================================================
        pdf_filename = f"{name.replace(' ', '_')}_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = pdf_service.create_storybook_pdf(
            child_name=name,
            story_title=story.title,
            pages_data=pages_data,
            output_filename=pdf_filename
        )
        
        logger.info(f"PDF generated successfully: {pdf_path}")
        
        # Get PDF file size for logging
        pdf_size = Path(pdf_path).stat().st_size
        logger.info(f"PDF size: {pdf_size} bytes ({pdf_size / 1024:.2f} KB)")
        logger.info(f"Story: {story.story_id}, Pages: {len(pages_data)}")
        
        # Return PDF file
        response = FileResponse(
            path=pdf_path,
            filename=pdf_filename,
            media_type='application/pdf'
        )
        
        logger.info(f"Returning PDF: {pdf_filename}")
        return response
    
    except Exception as e:
        logger.error(f"Error generating storybook: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error generating storybook: {str(e)}"
        )
    
    finally:
        # Cleanup uploaded file
        if uploaded_file_path:
            try:
                storage.delete_file(uploaded_file_path)
                logger.debug(f"Cleaned up uploaded file: {uploaded_file_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup uploaded file: {e}")

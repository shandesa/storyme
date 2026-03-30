from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import logging
import uuid

from services.story_service import story_repository
from services.image_service import ImageService
from services.pdf_service import PDFService
from core.storage import save_file, delete_file, ensure_directory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["generate"])

# Initialize services
BACKEND_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BACKEND_DIR / "templates"
UPLOADS_DIR = BACKEND_DIR / "uploads"
OUTPUT_DIR = BACKEND_DIR / "output"

# Ensure directories exist
for directory in [TEMPLATES_DIR, UPLOADS_DIR, OUTPUT_DIR]:
    ensure_directory(str(directory))

image_service = ImageService(str(TEMPLATES_DIR))
pdf_service = PDFService(str(OUTPUT_DIR))


@router.post("/generate")
async def generate_storybook(
    name: str = Form(...),
    image: UploadFile = File(...)
):
    """Generate personalized storybook PDF.
    
    Args:
        name: Child's name
        image: Uploaded photo of the child
    
    Returns:
        FileResponse with PDF download
    """
    
    # Validation
    if not name or name.strip() == "":
        raise HTTPException(status_code=400, detail="Child's name is required")
    
    if not image:
        raise HTTPException(status_code=400, detail="Image file is required")
    
    # Validate file type
    allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
    if image.content_type not in allowed_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Allowed: {', '.join(allowed_types)}"
        )
    
    uploaded_file_path = None
    
    try:
        # Get the story (currently only one story available)
        story = story_repository.get_story("forest_of_smiles")
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")
        
        # Save uploaded image
        file_extension = Path(image.filename).suffix
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        uploaded_file_path = UPLOADS_DIR / unique_filename
        
        save_file(image.file, str(uploaded_file_path))
        logger.info(f"Uploaded file saved: {uploaded_file_path}")
        
        # Process each page
        pages_data = []
        
        for page in story.pages:
            # Extract and resize face for this page
            face_img = image_service.extract_face(
                str(uploaded_file_path),
                (page.face_placement.width, page.face_placement.height)
            )
            
            # Compose page (paste face onto template)
            composed_image_path = image_service.compose_page(
                page.template_filename,
                face_img,
                (page.face_placement.x, page.face_placement.y)
            )
            
            pages_data.append({
                'text': page.text,
                'image_path': composed_image_path
            })
        
        # Generate PDF
        pdf_filename = f"{name.replace(' ', '_')}_{uuid.uuid4().hex[:8]}.pdf"
        pdf_path = pdf_service.create_storybook_pdf(
            child_name=name,
            story_title=story.title,
            pages_data=pages_data,
            output_filename=pdf_filename
        )
        
        logger.info(f"PDF generated successfully: {pdf_path}")
        
        # Return PDF file
        return FileResponse(
            path=pdf_path,
            filename=pdf_filename,
            media_type='application/pdf'
        )
    
    except Exception as e:
        logger.error(f"Error generating storybook: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating storybook: {str(e)}")
    
    finally:
        # Cleanup uploaded file
        if uploaded_file_path and Path(uploaded_file_path).exists():
            delete_file(str(uploaded_file_path))

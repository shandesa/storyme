from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


class ImageService:
    """Handles image processing: face extraction and template composition."""
    
    def __init__(self, templates_dir: str):
        self.templates_dir = Path(templates_dir)
    
    def extract_face(self, image_path: str, target_size: Tuple[int, int]) -> Image.Image:
        """Extract and resize face from uploaded image.
        
        For MVP: Simple center crop and resize.
        Future: Add face detection (OpenCV, etc.)
        
        Args:
            image_path: Path to uploaded image
            target_size: (width, height) for face
        
        Returns:
            Processed face image
        """
        try:
            img = Image.open(image_path)
            
            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Center crop to square
            width, height = img.size
            min_dim = min(width, height)
            
            left = (width - min_dim) // 2
            top = (height - min_dim) // 2
            right = left + min_dim
            bottom = top + min_dim
            
            img = img.crop((left, top, right, bottom))
            
            # Resize to target size with high-quality resampling
            img = img.resize(target_size, Image.Resampling.LANCZOS)
            
            # Apply subtle circular mask (optional enhancement)
            img = self._apply_circular_mask(img)
            
            return img
        
        except Exception as e:
            logger.error(f"Error extracting face: {e}")
            raise
    
    def _apply_circular_mask(self, img: Image.Image) -> Image.Image:
        """Apply circular mask to make face round."""
        size = img.size
        mask = Image.new('L', size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0) + size, fill=255)
        
        # Apply mask
        output = Image.new('RGBA', size, (0, 0, 0, 0))
        output.paste(img, (0, 0))
        output.putalpha(mask)
        
        return output
    
    def compose_page(self, 
                     template_filename: str, 
                     face_img: Image.Image,
                     face_position: Tuple[int, int]) -> str:
        """Paste face onto template and return processed image path.
        
        Args:
            template_filename: Name of template file
            face_img: Processed face image
            face_position: (x, y) position to paste face
        
        Returns:
            Path to composed image
        """
        try:
            template_path = self.templates_dir / template_filename
            
            # Open template
            template = Image.open(template_path)
            
            # Convert template to RGBA if needed
            if template.mode != 'RGBA':
                template = template.convert('RGBA')
            
            # Paste face onto template
            template.paste(face_img, face_position, face_img if face_img.mode == 'RGBA' else None)
            
            # Save to output
            output_path = Path('/app/backend/output') / template_filename
            
            # Convert back to RGB for PDF compatibility
            if template.mode == 'RGBA':
                rgb_template = Image.new('RGB', template.size, (255, 255, 255))
                rgb_template.paste(template, mask=template.split()[3] if len(template.split()) == 4 else None)
                rgb_template.save(output_path, 'PNG')
            else:
                template.save(output_path, 'PNG')
            
            return str(output_path)
        
        except Exception as e:
            logger.error(f"Error composing page: {e}")
            raise

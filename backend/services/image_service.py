"""Image Processing Service

Handles face extraction and template composition using storage abstraction.
All file operations go through the storage layer for S3 compatibility.
"""

from PIL import Image, ImageDraw
from typing import Tuple
import logging
import io

from core.storage import storage

logger = logging.getLogger(__name__)


class ImageService:
    """Handles image processing: face extraction and template composition."""
    
    def extract_face(self, image_path: str, target_size: Tuple[int, int]) -> Image.Image:
        """Extract and resize face from uploaded image.
        
        For MVP: Simple center crop and resize.
        Future: Add face detection (OpenCV, etc.)
        
        Args:
            image_path: Path to uploaded image (uses storage abstraction)
            target_size: (width, height) for face
        
        Returns:
            Processed face image
        """
        try:
            # Read image using storage abstraction
            image_bytes = storage.read_file(image_path)
            img = Image.open(io.BytesIO(image_bytes))
            
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
            
            # Apply subtle circular mask
            img = self._apply_circular_mask(img)
            
            logger.debug(f"Face extracted from {image_path}, size: {target_size}")
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
                     template_path: str, 
                     face_img: Image.Image,
                     face_position: Tuple[int, int],
                     output_path: str) -> str:
        """Paste face onto template and save.
        
        Uses storage abstraction for both reading template and saving output.
        
        Args:
            template_path: Relative path to template (storage-agnostic)
            face_img: Processed face image
            face_position: (x, y) position to paste face
            output_path: Relative path for output (storage-agnostic)
        
        Returns:
            Full path to composed image
        """
        try:
            # Read template using storage abstraction
            template_bytes = storage.read_file(template_path)
            template = Image.open(io.BytesIO(template_bytes))
            
            # Convert template to RGBA if needed
            if template.mode != 'RGBA':
                template = template.convert('RGBA')
            
            # Paste face onto template
            template.paste(face_img, face_position, face_img if face_img.mode == 'RGBA' else None)
            
            # Convert back to RGB for PDF compatibility
            if template.mode == 'RGBA':
                rgb_template = Image.new('RGB', template.size, (255, 255, 255))
                rgb_template.paste(template, mask=template.split()[3] if len(template.split()) == 4 else None)
            else:
                rgb_template = template
            
            # Save using storage abstraction
            img_bytes = io.BytesIO()
            rgb_template.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            
            saved_path = storage.save_file(img_bytes, output_path)
            
            logger.debug(f"Page composed: {template_path} -> {output_path}")
            return saved_path
        
        except Exception as e:
            logger.error(f"Error composing page: {e}")
            raise


# Singleton instance
image_service = ImageService()

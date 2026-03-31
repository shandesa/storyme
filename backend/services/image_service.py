"""Image Processing Service - FIXED

Handles face extraction and template composition using storage abstraction.
Updated to handle templates with pre-rendered text and correct face placement.
"""

from PIL import Image, ImageDraw, ImageFont
from typing import Tuple, Optional
import logging
import io

from core.storage import storage

logger = logging.getLogger(__name__)


class ImageService:
    """Handles image processing: face extraction and template composition."""
    
    def extract_face(self, image_path: str, target_size: Tuple[int, int]) -> Image.Image:
        """Extract and resize face from uploaded image.
        
        Args:
            image_path: Path to uploaded image (uses storage abstraction)
            target_size: (width, height) for face
        
        Returns:
            Processed face image with circular mask
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
            
            # Apply circular mask for smooth blending
            img = self._apply_circular_mask(img)
            
            logger.debug(f"Face extracted: {target_size}")
            return img
        
        except Exception as e:
            logger.error(f"Error extracting face: {e}")
            raise
    
    def _apply_circular_mask(self, img: Image.Image) -> Image.Image:
        """Apply circular mask with feathered edges."""
        size = img.size
        
        # Create mask
        mask = Image.new('L', size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0) + size, fill=255)
        
        # Apply mask
        output = Image.new('RGBA', size, (0, 0, 0, 0))
        output.paste(img, (0, 0))
        output.putalpha(mask)
        
        return output
    
    def compose_page(
        self, 
        template_path: str, 
        face_img: Image.Image,
        face_position: Tuple[int, int],
        output_path: str,
        child_name: Optional[str] = None,
        name_position: Optional[Tuple[int, int]] = None
    ) -> str:
        """Paste face onto template and optionally overlay name.
        
        Args:
            template_path: Relative path to template
            face_img: Processed face image
            face_position: (x, y) position to paste face
            output_path: Relative path for output
            child_name: Optional child's name to overlay
            name_position: Optional (x, y) for name text
        
        Returns:
            Full path to composed image
        """
        try:
            # Read template via storage
            template_bytes = storage.read_file(template_path)
            template = Image.open(io.BytesIO(template_bytes))
            
            # Convert to RGBA for alpha compositing
            if template.mode != 'RGBA':
                template = template.convert('RGBA')
            
            # Paste face onto template (centered in the oval)
            template.paste(face_img, face_position, face_img if face_img.mode == 'RGBA' else None)
            
            # Overlay name if provided (replaces {name} placeholder in template)
            if child_name and name_position:
                self._overlay_name(template, child_name, name_position)
            
            # Convert to RGB for PDF compatibility
            rgb_template = Image.new('RGB', template.size, (255, 255, 255))
            rgb_template.paste(template, mask=template.split()[3] if len(template.split()) == 4 else None)
            
            # Save via storage
            img_bytes = io.BytesIO()
            rgb_template.save(img_bytes, format='PNG', quality=95)
            img_bytes.seek(0)
            
            saved_path = storage.save_file(img_bytes, output_path)
            
            logger.debug(f"Page composed: {template_path} -> {output_path}")
            return saved_path
        
        except Exception as e:
            logger.error(f"Error composing page: {e}")
            raise
    
    def _overlay_name(self, img: Image.Image, name: str, position: Tuple[int, int]):
        """Overlay child's name on template to replace {name} placeholder.
        
        Args:
            img: Template image (modified in place)
            name: Child's name
            position: (x, y) center position for text
        """
        draw = ImageDraw.Draw(img)
        
        # Try to load a nice font
        font_size = 48
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except:
            font = ImageFont.load_default()
        
        # Get text size for centering
        bbox = draw.textbbox((0, 0), name, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Calculate position (center the text)
        x = position[0] - text_width // 2
        y = position[1] - text_height // 2
        
        # Draw white background/outline for readability
        outline_color = (255, 255, 255, 255)
        for offset_x in [-2, -1, 0, 1, 2]:
            for offset_y in [-2, -1, 0, 1, 2]:
                if offset_x != 0 or offset_y != 0:
                    draw.text((x + offset_x, y + offset_y), name, font=font, fill=outline_color)
        
        # Draw name in dark color
        draw.text((x, y), name, font=font, fill=(51, 51, 51, 255))
        
        logger.debug(f"Name '{name}' overlaid at ({x}, {y})")


# Singleton instance
image_service = ImageService()

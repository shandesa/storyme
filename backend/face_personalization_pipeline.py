#!/usr/bin/env python3
"""
Face Personalization Pipeline for StoryMe
Clean, modular, extensible system for face extraction, processing, and template rendering.
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from typing import Tuple, Optional
from pathlib import Path
import logging
from abc import ABC, abstractmethod

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class FaceDetector:
    """Handles face detection using OpenCV with multiple fallback methods."""
    
    def __init__(self, method: str = "dnn"):
        self.method = method
        self._load_detector()
        logger.info(f"FaceDetector initialized with method: {method}")
    
    def _load_detector(self):
        """Load face detection model based on method."""
        if self.method == "dnn":
            model_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.detector = cv2.CascadeClassifier(model_path)
            if self.detector.empty():
                raise RuntimeError("Failed to load Haar Cascade")
            logger.debug("DNN detector loaded successfully")
        else:
            raise ValueError(f"Unknown detection method: {self.method}")
    
    def detect_face(self, image: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect the most prominent face in the image.
        
        Args:
            image: OpenCV image (BGR format)
        
        Returns:
            (x, y, width, height) of face bounding box, or None if no face found
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
            flags=cv2.CASCADE_SCALE_IMAGE
        )
        
        if len(faces) == 0:
            logger.warning("No faces detected")
            return None
        
        largest_face = max(faces, key=lambda f: f[2] * f[3])
        x, y, w, h = largest_face
        logger.debug(f"Face detected: x={x}, y={y}, w={w}, h={h}")
        return (x, y, w, h)


class FaceProcessor:
    """Handles face extraction, cropping, and basic preprocessing."""
    
    def __init__(self, padding_percent: float = 0.20):
        self.padding_percent = padding_percent
        logger.info(f"FaceProcessor initialized with padding: {padding_percent*100}%")
    
    def extract_face(self, image_path: str, output_path: Optional[str] = None) -> Image.Image:
        """
        Extract face from image with padding.
        
        Args:
            image_path: Path to input image
            output_path: Optional path to save extracted face
        
        Returns:
            PIL Image of extracted face (RGBA)
        
        Raises:
            FileNotFoundError: If image doesn't exist
            RuntimeError: If no face detected
        """
        if not Path(image_path).exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        
        img_cv = cv2.imread(image_path)
        if img_cv is None:
            raise RuntimeError(f"Failed to load image: {image_path}")
        
        detector = FaceDetector()
        face_bbox = detector.detect_face(img_cv)
        
        if face_bbox is None:
            raise RuntimeError("No face detected in image")
        
        x, y, w, h = face_bbox
        
        padding_w = int(w * self.padding_percent)
        padding_h = int(h * self.padding_percent)
        
        x1 = max(0, x - padding_w)
        y1 = max(0, y - padding_h)
        x2 = min(img_cv.shape[1], x + w + padding_w)
        y2 = min(img_cv.shape[0], y + h + padding_h)
        
        face_crop = img_cv[y1:y2, x1:x2]
        
        face_rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(face_rgb).convert("RGBA")
        
        logger.info(f"Face extracted: {pil_image.size}")
        
        if output_path:
            pil_image.save(output_path, "PNG")
            logger.info(f"Face saved to: {output_path}")
        
        return pil_image
    
    def preprocess_face(self, face_image: Image.Image) -> Image.Image:
        """
        Preprocess face for better blending into illustrated templates.
        
        Args:
            face_image: PIL Image of face
        
        Returns:
            Preprocessed PIL Image
        """
        logger.debug("Preprocessing face...")
        
        img_cv = cv2.cvtColor(np.array(face_image.convert("RGB")), cv2.COLOR_RGB2BGR)
        
        smoothed = cv2.bilateralFilter(img_cv, d=9, sigmaColor=75, sigmaSpace=75)
        
        lab = cv2.cvtColor(smoothed, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        enhanced = cv2.merge([l, a, b])
        enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
        
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(enhanced, -1, kernel)
        
        rgb = cv2.cvtColor(sharpened, cv2.COLOR_BGR2RGB)
        pil_processed = Image.fromarray(rgb).convert("RGBA")
        
        logger.debug("Face preprocessing complete")
        return pil_processed


class FaceStyler:
    """Handles face stylization with extensible architecture for ML models."""
    
    def __init__(self):
        logger.info("FaceStyler initialized")
    
    def stylize_face(self, face_image: Image.Image, mode: str = "pixar") -> Image.Image:
        """
        Apply stylization to face.
        
        Args:
            face_image: PIL Image to stylize
            mode: Stylization mode ('pixar', 'cartoon', 'none')
        
        Returns:
            Stylized PIL Image
        """
        if mode == "none":
            return face_image
        
        if mode == "pixar":
            return self._pixar_style(face_image)
        elif mode == "cartoon":
            return self._cartoon_style(face_image)
        else:
            logger.warning(f"Unknown mode: {mode}, returning original")
            return face_image
    
    def _pixar_style(self, img: Image.Image) -> Image.Image:
        """Lightweight Pixar-like stylization."""
        logger.debug("Applying Pixar-style processing...")
        
        img_cv = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        
        smooth1 = cv2.bilateralFilter(img_cv, d=9, sigmaColor=90, sigmaSpace=90)
        smooth2 = cv2.bilateralFilter(smooth1, d=7, sigmaColor=90, sigmaSpace=90)
        
        gray = cv2.cvtColor(smooth2, cv2.COLOR_BGR2GRAY)
        edges = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 
                                      cv2.THRESH_BINARY, blockSize=9, C=2)
        edges = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        
        cartoon = cv2.bitwise_and(smooth2, edges)
        
        hsv = cv2.cvtColor(cartoon, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = cv2.multiply(hsv[:, :, 1], 1.2).clip(0, 255).astype(np.uint8)
        saturated = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        
        rgb = cv2.cvtColor(saturated, cv2.COLOR_BGR2RGB)
        pil_result = Image.fromarray(rgb).convert("RGBA")
        
        logger.debug("Pixar-style applied")
        return pil_result
    
    def _cartoon_style(self, img: Image.Image) -> Image.Image:
        """Basic cartoon effect."""
        smoothed = img.filter(ImageFilter.SMOOTH_MORE)
        enhancer = ImageEnhance.Color(smoothed)
        enhanced = enhancer.enhance(1.3)
        return enhanced.convert("RGBA")
    
    def add_ml_stylizer(self, model_name: str, model_function):
        """
        Extensibility hook for ML-based stylization.
        
        Args:
            model_name: Name of the model (e.g., 'stable_diffusion')
            model_function: Function that takes PIL Image and returns styled PIL Image
        """
        setattr(self, f"_{model_name}_style", model_function)
        logger.info(f"ML stylizer registered: {model_name}")


class TemplateRenderer:
    """Handles rendering face onto story template with text."""
    
    def __init__(self):
        self.default_font_size = 48
        logger.info("TemplateRenderer initialized")
    
    def apply_face_and_name(
        self,
        template_path: str,
        face_image: Image.Image,
        name: str,
        face_coords: Tuple[int, int, int, int],
        name_coords: Tuple[int, int],
        output_path: str,
        font_path: Optional[str] = None
    ):
        """
        Composite face onto template and add name text.
        
        Args:
            template_path: Path to template image
            face_image: Processed face (PIL Image)
            name: Child's name to render
            face_coords: (x, y, width, height) for face placement
            name_coords: (x, y) for name placement
            output_path: Where to save final image
            font_path: Optional custom font path
        """
        logger.info(f"Rendering template: {template_path}")
        
        if not Path(template_path).exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        template = Image.open(template_path).convert("RGBA")
        
        x, y, target_w, target_h = face_coords
        
        face_resized = self._resize_with_aspect_ratio(face_image, target_w, target_h)
        
        face_masked = self._apply_circular_mask(face_resized)
        
        face_x = x + (target_w - face_masked.width) // 2
        face_y = y + (target_h - face_masked.height) // 2
        
        template.paste(face_masked, (face_x, face_y), face_masked)
        
        self._draw_name(template, name, name_coords, font_path)
        
        final = template.convert("RGB")
        final.save(output_path, "PNG", quality=95)
        
        logger.info(f"Template rendered successfully: {output_path}")
    
    def _resize_with_aspect_ratio(self, img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """Resize image maintaining aspect ratio."""
        orig_w, orig_h = img.size
        ratio = min(target_w / orig_w, target_h / orig_h)
        new_w = int(orig_w * ratio)
        new_h = int(orig_h * ratio)
        return img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    def _apply_circular_mask(self, img: Image.Image) -> Image.Image:
        """Apply feathered circular mask to image."""
        size = img.size
        mask = Image.new('L', size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0) + size, fill=255)
        
        mask = mask.filter(ImageFilter.GaussianBlur(radius=3))
        
        output = Image.new('RGBA', size, (0, 0, 0, 0))
        output.paste(img, (0, 0))
        output.putalpha(mask)
        
        return output
    
    def _draw_name(self, img: Image.Image, name: str, coords: Tuple[int, int], font_path: Optional[str]):
        """Draw name text on image."""
        draw = ImageDraw.Draw(img)
        
        if font_path and Path(font_path).exists():
            font = ImageFont.truetype(font_path, self.default_font_size)
        else:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 
                                         self.default_font_size)
            except:
                font = ImageFont.load_default()
        
        bbox = draw.textbbox((0, 0), name, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        x, y = coords
        text_x = x - text_w // 2
        text_y = y - text_h // 2
        
        outline_color = (255, 255, 255, 200)
        for offset_x in [-2, 0, 2]:
            for offset_y in [-2, 0, 2]:
                draw.text((text_x + offset_x, text_y + offset_y), name, 
                         font=font, fill=outline_color)
        
        draw.text((text_x, text_y), name, font=font, fill=(51, 51, 51, 255))
        
        logger.debug(f"Name rendered: '{name}' at ({text_x}, {text_y})")


class StoryMePipeline:
    """Complete face personalization pipeline."""
    
    def __init__(self):
        self.processor = FaceProcessor()
        self.styler = FaceStyler()
        self.renderer = TemplateRenderer()
        logger.info("StoryMe Pipeline initialized")
    
    def process(
        self,
        input_image_path: str,
        template_path: str,
        name: str,
        face_coords: Tuple[int, int, int, int],
        name_coords: Tuple[int, int],
        output_path: str,
        stylization_mode: str = "pixar",
        enable_preprocessing: bool = True
    ):
        """
        Complete processing pipeline.
        
        Args:
            input_image_path: Input photo
            template_path: Story page template
            name: Child's name
            face_coords: Where to place face (x, y, w, h)
            name_coords: Where to place name (x, y)
            output_path: Output file path
            stylization_mode: 'pixar', 'cartoon', 'none'
            enable_preprocessing: Whether to preprocess face
        """
        logger.info("="*70)
        logger.info("Starting StoryMe Pipeline")
        logger.info("="*70)
        
        face = self.processor.extract_face(input_image_path)
        logger.info(f"Step 1/4: Face extracted")
        
        if enable_preprocessing:
            face = self.processor.preprocess_face(face)
            logger.info(f"Step 2/4: Face preprocessed")
        else:
            logger.info(f"Step 2/4: Preprocessing skipped")
        
        if stylization_mode != "none":
            face = self.styler.stylize_face(face, mode=stylization_mode)
            logger.info(f"Step 3/4: Face stylized ({stylization_mode})")
        else:
            logger.info(f"Step 3/4: Stylization skipped")
        
        self.renderer.apply_face_and_name(
            template_path=template_path,
            face_image=face,
            name=name,
            face_coords=face_coords,
            name_coords=name_coords,
            output_path=output_path
        )
        logger.info(f"Step 4/4: Template rendered")
        
        logger.info("="*70)
        logger.info(f"Pipeline complete: {output_path}")
        logger.info("="*70)


def main():
    """Test driver code."""
    pipeline = StoryMePipeline()
    
    template = "/app/backend/templates/stories/forest_of_smiles/page1.png"
    input_face = "/tmp/test_child.jpg"
    name = "Emma"
    
    from PIL import Image, ImageDraw
    test_img = Image.new('RGB', (400, 400), color='#FFB6C1')
    draw = ImageDraw.Draw(test_img)
    draw.ellipse([100, 100, 300, 300], fill='#FFF0F5')
    draw.ellipse([150, 150, 200, 200], fill='#000000')
    draw.ellipse([250, 150, 300, 200], fill='#000000')
    test_img.save(input_face, 'JPEG')
    logger.info(f"Test image created: {input_face}")
    
    pipeline.process(
        input_image_path=input_face,
        template_path=template,
        name=name,
        face_coords=(220, 180, 160, 160),
        name_coords=(306, 700),
        output_path="/tmp/output_page1_pipeline.png",
        stylization_mode="pixar",
        enable_preprocessing=True
    )
    
    logger.info("Test completed successfully!")


if __name__ == "__main__":
    main()

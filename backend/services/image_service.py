"""Image Processing Service

Handles face extraction using OpenCV and template composition using PIL.
Integrates real face detection via Haar Cascades for proper face cropping.
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Tuple, Optional
import logging
import io
import tempfile
import os

from core.storage import storage

logger = logging.getLogger(__name__)


class ImageService:
    """Handles image processing: face detection, extraction, and template composition."""

    def __init__(self):
        self._detector = None

    @property
    def detector(self):
        """Lazy-load Haar cascade detector."""
        if self._detector is None:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._detector = cv2.CascadeClassifier(cascade_path)
            if self._detector.empty():
                raise RuntimeError("Failed to load Haar Cascade face detector")
            logger.info("Haar Cascade face detector loaded")
        return self._detector

    def _detect_face_bbox(self, cv_image: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """Detect the largest face in an OpenCV image.

        Returns (x, y, w, h) or None if no face found.
        """
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        if len(faces) == 0:
            return None
        # Pick the largest face
        largest = max(faces, key=lambda f: f[2] * f[3])
        return tuple(largest)

    def extract_face(
        self,
        image_path: str,
        target_size: Tuple[int, int],
        angle: float = 0.0,
    ) -> Image.Image:
        """Detect, crop, rotate and mask the face from an uploaded image.

        Args:
            image_path: Relative path to uploaded image (via storage)
            target_size: (width, height) for final face output
            angle: Rotation angle in degrees (counter-clockwise)

        Returns:
            RGBA PIL Image of the extracted face with circular mask
        """
        # Read image bytes via storage abstraction
        image_bytes = storage.read_file(image_path)

        # Decode with OpenCV for face detection
        np_arr = np.frombuffer(image_bytes, np.uint8)
        cv_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if cv_img is None:
            raise RuntimeError(f"Failed to decode image: {image_path}")

        # Attempt face detection
        bbox = self._detect_face_bbox(cv_img)

        if bbox is not None:
            x, y, w, h = bbox
            # Add padding around detected face (20%)
            pad_w = int(w * 0.20)
            pad_h = int(h * 0.20)
            x1 = max(0, x - pad_w)
            y1 = max(0, y - pad_h)
            x2 = min(cv_img.shape[1], x + w + pad_w)
            y2 = min(cv_img.shape[0], y + h + pad_h)
            face_crop = cv_img[y1:y2, x1:x2]
            logger.info(f"Face detected at ({x},{y},{w},{h}), cropped with padding")
        else:
            # Fallback: center-crop to square (best effort)
            logger.warning("No face detected, falling back to center crop")
            h_img, w_img = cv_img.shape[:2]
            min_dim = min(w_img, h_img)
            cx, cy = w_img // 2, h_img // 2
            half = min_dim // 2
            face_crop = cv_img[cy - half : cy + half, cx - half : cx + half]

        # Convert BGR -> RGB -> PIL
        face_rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
        pil_face = Image.fromarray(face_rgb).convert("RGBA")

        # Resize to target
        pil_face = pil_face.resize(target_size, Image.Resampling.LANCZOS)

        # Rotate if needed
        if angle != 0.0:
            pil_face = pil_face.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)

        # Apply circular mask with feathered edges
        pil_face = self._apply_circular_mask(pil_face)

        return pil_face

    def _apply_circular_mask(self, img: Image.Image) -> Image.Image:
        """Apply a feathered circular mask."""
        size = img.size
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0) + size, fill=255)
        # Feather the edge slightly
        mask = mask.filter(ImageFilter.GaussianBlur(radius=2))

        output = Image.new("RGBA", size, (0, 0, 0, 0))
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
        name_position: Optional[Tuple[int, int]] = None,
        name_font_size: int = 48,
        name_color: Tuple[int, int, int] = (51, 51, 51),
    ) -> str:
        """Paste face onto template and optionally overlay name.

        Args:
            template_path: Relative path to template
            face_img: Processed face image (RGBA)
            face_position: (x, y) position to paste face
            output_path: Relative path for output
            child_name: Optional child's name to overlay
            name_position: Optional (x, y) center for name text
            name_font_size: Font size for the name
            name_color: RGB color tuple for the name

        Returns:
            Full path to composed image
        """
        # Read template via storage
        template_bytes = storage.read_file(template_path)
        template = Image.open(io.BytesIO(template_bytes)).convert("RGBA")

        # Paste face
        template.paste(face_img, face_position, face_img)

        # Overlay name
        if child_name and name_position:
            self._overlay_name(template, child_name, name_position, name_font_size, name_color)

        # Convert to RGB for PDF compatibility
        rgb_out = Image.new("RGB", template.size, (255, 255, 255))
        rgb_out.paste(template, mask=template.split()[3] if len(template.split()) == 4 else None)

        # Save via storage
        img_bytes = io.BytesIO()
        rgb_out.save(img_bytes, format="PNG", quality=95)
        img_bytes.seek(0)

        saved_path = storage.save_file(img_bytes, output_path)
        logger.debug(f"Page composed: {template_path} -> {output_path}")
        return saved_path

    def _overlay_name(
        self,
        img: Image.Image,
        name: str,
        position: Tuple[int, int],
        font_size: int = 48,
        color: Tuple[int, int, int] = (51, 51, 51),
    ):
        """Overlay the child's name centered at position."""
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
            )
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), name, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        x = position[0] - text_w // 2
        y = position[1] - text_h // 2

        # White outline for readability
        outline = (255, 255, 255, 255)
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), name, font=font, fill=outline)

        draw.text((x, y), name, font=font, fill=(*color, 255))
        logger.debug(f"Name '{name}' overlaid at ({x}, {y})")


# Singleton
image_service = ImageService()

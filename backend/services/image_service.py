"""Image Processing Service

Advanced face extraction, template compositing, and text replacement.
Uses OpenCV for face detection and PIL for image manipulation.
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Tuple, Optional, Dict, Any
import logging
import io

from core.storage import storage

FONT_PATHS = [
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load best available bold font."""
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()

logger = logging.getLogger(__name__)


class ImageService:
    """Face detection, extraction, template compositing, and name replacement."""

    def __init__(self):
        self._detector = None

    # ------------------------------------------------------------------
    # Face detection
    # ------------------------------------------------------------------

    @property
    def detector(self):
        if self._detector is None:
            path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._detector = cv2.CascadeClassifier(path)
            if self._detector.empty():
                raise RuntimeError("Failed to load Haar Cascade")
            logger.info("Haar Cascade loaded")
        return self._detector

    def _detect_face(self, cv_img: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """Return (x, y, w, h) of the largest face, or None."""
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )
        if len(faces) == 0:
            # Try more relaxed params
            faces = self.detector.detectMultiScale(
                gray, scaleFactor=1.05, minNeighbors=3, minSize=(20, 20)
            )
        if len(faces) == 0:
            return None
        return tuple(max(faces, key=lambda f: f[2] * f[3]))

    # ------------------------------------------------------------------
    # Face extraction
    # ------------------------------------------------------------------

    def extract_face(
        self,
        image_path: str,
        target_size: Tuple[int, int],
        angle: float = 0.0,
    ) -> Image.Image:
        """Detect, crop, resize, rotate and mask the face.

        Returns RGBA PIL Image ready for compositing.
        """
        image_bytes = storage.read_file(image_path)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        cv_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if cv_img is None:
            raise RuntimeError(f"Failed to decode image: {image_path}")

        bbox = self._detect_face(cv_img)

        if bbox is not None:
            x, y, w, h = bbox
            pad = 0.25  # 25% padding around detected face
            pw, ph = int(w * pad), int(h * pad)
            x1 = max(0, x - pw)
            y1 = max(0, y - ph)
            x2 = min(cv_img.shape[1], x + w + pw)
            y2 = min(cv_img.shape[0], y + h + ph)
            crop = cv_img[y1:y2, x1:x2]
            logger.info(f"Face detected at ({x},{y},{w},{h}), cropped with padding")
        else:
            logger.warning("No face detected, using center crop")
            h_img, w_img = cv_img.shape[:2]
            d = min(w_img, h_img)
            cx, cy = w_img // 2, h_img // 2
            r = d // 2
            crop = cv_img[cy - r : cy + r, cx - r : cx + r]

        face_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(face_rgb).convert("RGBA")
        pil = pil.resize(target_size, Image.Resampling.LANCZOS)

        if angle != 0.0:
            pil = pil.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)

        return pil

    # ------------------------------------------------------------------
    # Template compositing (advanced)
    # ------------------------------------------------------------------

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
        face_circle_center: Optional[Tuple[int, int]] = None,
        face_circle_radius: Optional[int] = None,
        name_text_regions: Optional[list] = None,
    ) -> str:
        """Compose a page: fit face into template circle, blend, replace name.

        Args:
            template_path: Relative path to template
            face_img: Extracted face (RGBA)
            face_position: (x, y) paste position
            output_path: Output relative path
            child_name: Name to overlay
            name_position: (x, y) center for name text
            name_font_size: Font size
            name_color: RGB color for name
            face_circle_center: (cx, cy) of the white circle on template
            face_circle_radius: Radius of the white circle
            name_text_region: (x1, y1, x2, y2) bounding box of baked-in {name} text

        Returns:
            Full saved path
        """
        template_bytes = storage.read_file(template_path)
        template = Image.open(io.BytesIO(template_bytes)).convert("RGBA")

        if face_circle_center and face_circle_radius:
            # Advanced compositing: fit face into the detected circle
            template = self._composite_face_into_circle(
                template, face_img, face_circle_center, face_circle_radius
            )
        else:
            # Simple paste with circular mask
            masked = self._apply_circular_mask(face_img)
            template.paste(masked, face_position, masked)

        # Replace baked-in {name} text in all regions
        if child_name and name_text_regions:
            for region in name_text_regions:
                self._replace_baked_text(template, child_name, region, name_font_size, name_color)
        elif child_name and name_position:
            self._overlay_name(template, child_name, name_position, name_font_size, name_color)

        # Convert to RGB
        rgb = Image.new("RGB", template.size, (255, 255, 255))
        rgb.paste(template, mask=template.split()[3] if len(template.split()) == 4 else None)

        buf = io.BytesIO()
        rgb.save(buf, format="PNG", quality=95)
        buf.seek(0)
        saved = storage.save_file(buf, output_path)
        logger.debug(f"Page composed: {output_path}")
        return saved

    def _composite_face_into_circle(
        self,
        template: Image.Image,
        face: Image.Image,
        center: Tuple[int, int],
        radius: int,
    ) -> Image.Image:
        """Place face inside the white circle and blend edges with surroundings."""
        cx, cy = center
        diameter = radius * 2

        # Resize face to fill the circle (slightly smaller for blending margin)
        face_size = int(diameter * 0.88)
        face_resized = face.resize((face_size, face_size), Image.Resampling.LANCZOS)

        # Create circular alpha mask with feathered edge
        mask = Image.new("L", (face_size, face_size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, face_size, face_size), fill=255)
        # Feather: strong gaussian blur on the mask edge
        mask = mask.filter(ImageFilter.GaussianBlur(radius=6))

        # Prepare face with mask
        face_masked = Image.new("RGBA", (face_size, face_size), (0, 0, 0, 0))
        face_masked.paste(face_resized, (0, 0))
        face_masked.putalpha(mask)

        # Calculate paste position (centered in the circle)
        px = cx - face_size // 2
        py = cy - face_size // 2

        # Step 1: Inpaint the white circle area with surrounding colors FIRST
        template = self._inpaint_white_circle(template, center, radius)

        # Step 2: Paste the face over the inpainted area
        template.paste(face_masked, (px, py), face_masked)

        return template

    def _inpaint_white_circle(
        self,
        template: Image.Image,
        center: Tuple[int, int],
        radius: int,
    ) -> Image.Image:
        """Fill the white circle area with neighboring pixel colors using OpenCV inpainting."""
        cx, cy = center

        cv_img = cv2.cvtColor(np.array(template.convert("RGB")), cv2.COLOR_RGB2BGR)
        h, w = cv_img.shape[:2]

        # Create mask using vectorized numpy operations (fast)
        y_start = max(0, cy - radius)
        y_end = min(h, cy + radius)
        x_start = max(0, cx - radius)
        x_end = min(w, cx + radius)

        # Create coordinate grids for the bounding box
        ys = np.arange(y_start, y_end)
        xs = np.arange(x_start, x_end)
        yy, xx = np.meshgrid(ys, xs, indexing="ij")

        # Distance from center
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

        # Extract the region
        region = cv_img[y_start:y_end, x_start:x_end]

        # Mask: inside circle AND white-ish pixels
        inside_circle = dist <= radius
        is_white = (region[:, :, 2] > 230) & (region[:, :, 1] > 230) & (region[:, :, 0] > 230)
        mask_region = (inside_circle & is_white).astype(np.uint8) * 255

        # Build full-size mask
        inpaint_mask = np.zeros((h, w), dtype=np.uint8)
        inpaint_mask[y_start:y_end, x_start:x_end] = mask_region

        if inpaint_mask.sum() > 0:
            inpainted = cv2.inpaint(cv_img, inpaint_mask, inpaintRadius=12, flags=cv2.INPAINT_TELEA)
            result_rgb = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
            result = Image.fromarray(result_rgb).convert("RGBA")
            if template.mode == "RGBA":
                result.putalpha(template.split()[3])
            return result

        return template

    def _replace_baked_text(
        self,
        img: Image.Image,
        name: str,
        text_region: Tuple[int, int, int, int],
        font_size: int,
        color: Tuple[int, int, int],
    ):
        """Replace baked-in {name} text using inpainting + re-rendering."""
        x1, y1, x2, y2 = text_region
        region_height = y2 - y1

        # Auto-adjust font size based on region height
        # The font renders at roughly 70-80% of the specified size
        auto_font_size = max(int(region_height * 0.85), 12)

        cv_img = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)

        # Create mask for text pixels in the region
        region = cv_img[y1:y2, x1:x2]
        gray_region = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

        # Text is dark (< ~160 luminance) on lighter background
        text_mask_local = (gray_region < 160).astype(np.uint8) * 255

        # Dilate to cover anti-aliased edges
        kernel = np.ones((3, 3), np.uint8)
        text_mask_local = cv2.dilate(text_mask_local, kernel, iterations=1)

        # Full-size mask
        full_mask = np.zeros(cv_img.shape[:2], dtype=np.uint8)
        full_mask[y1:y2, x1:x2] = text_mask_local

        # Inpaint
        inpainted = cv2.inpaint(cv_img, full_mask, inpaintRadius=8, flags=cv2.INPAINT_TELEA)

        # Apply inpainted region back
        result_rgb = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
        img_arr = np.array(img.convert("RGB"))
        margin = 2
        y1m, y2m = max(0, y1 - margin), min(img_arr.shape[0], y2 + margin)
        x1m, x2m = max(0, x1 - margin), min(img_arr.shape[1], x2 + margin)
        img_arr[y1m:y2m, x1m:x2m] = result_rgb[y1m:y2m, x1m:x2m]

        new_img = Image.fromarray(img_arr).convert("RGBA")
        img.paste(new_img)

        # Render the actual name
        draw = ImageDraw.Draw(img)
        font = _load_font(auto_font_size)

        bbox = draw.textbbox((0, 0), name, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        tx = (x1 + x2) // 2 - tw // 2
        ty = (y1 + y2) // 2 - th // 2

        draw.text((tx, ty), name, font=font, fill=(*color, 255))
        logger.debug(f"Replaced '{{name}}' with '{name}' at ({tx},{ty}), size={auto_font_size}")

    # ------------------------------------------------------------------
    # Simple helpers (for placeholder pages)
    # ------------------------------------------------------------------

    def _apply_circular_mask(self, img: Image.Image) -> Image.Image:
        size = img.size
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0) + size, fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=2))
        out = Image.new("RGBA", size, (0, 0, 0, 0))
        out.paste(img, (0, 0))
        out.putalpha(mask)
        return out

    def _overlay_name(
        self,
        img: Image.Image,
        name: str,
        position: Tuple[int, int],
        font_size: int = 48,
        color: Tuple[int, int, int] = (51, 51, 51),
    ):
        draw = ImageDraw.Draw(img)
        try:
            font = _load_font(font_size)
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), name, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = position[0] - tw // 2
        y = position[1] - th // 2

        # White outline
        outline = (255, 255, 255, 255)
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                if dx or dy:
                    draw.text((x + dx, y + dy), name, font=font, fill=outline)
        draw.text((x, y), name, font=font, fill=(*color, 255))


# Singleton
image_service = ImageService()

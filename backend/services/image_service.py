"""Image Processing Service

Face extraction, template compositing, and text replacement.
Uses OpenCV for face detection/inpainting and PIL for rendering.
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Tuple, Optional, List
import logging
import io

from core.storage import storage

FONT_PATHS = [
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


logger = logging.getLogger(__name__)


class ImageService:

    def __init__(self):
        self._detector = None

    @property
    def detector(self):
        if self._detector is None:
            p = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._detector = cv2.CascadeClassifier(p)
        return self._detector

    # ------------------------------------------------------------------
    # Face extraction — tight crop, oval mask, heavy feather
    # ------------------------------------------------------------------

    def extract_face(self, image_path: str, target_size: Tuple[int, int], angle: float = 0.0) -> Image.Image:
        raw = storage.read_file(image_path)
        arr = np.frombuffer(raw, np.uint8)
        cv_img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

        bbox = self._detect_face(cv_img)

        if bbox is not None:
            x, y, w, h = bbox
            # Tight crop — just 10% padding so we get mostly face
            pw = int(w * 0.10)
            ph_top = int(h * 0.15)   # a little more above for forehead
            ph_bot = int(h * 0.05)   # very little below chin
            x1 = max(0, x - pw)
            y1 = max(0, y - ph_top)
            x2 = min(cv_img.shape[1], x + w + pw)
            y2 = min(cv_img.shape[0], y + h + ph_bot)
            crop = cv_img[y1:y2, x1:x2]
            logger.info(f"Face detected ({x},{y},{w},{h}), tight crop applied")
        else:
            logger.warning("No face detected — center crop fallback")
            ih, iw = cv_img.shape[:2]
            d = min(iw, ih)
            cx, cy = iw // 2, ih // 2
            r = d // 2
            crop = cv_img[cy - r:cy + r, cx - r:cx + r]

        face_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(face_rgb).convert("RGBA")
        pil = pil.resize(target_size, Image.Resampling.LANCZOS)

        if angle != 0.0:
            pil = pil.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)

        # Oval mask with heavy feathering
        w_t, h_t = target_size
        mask = Image.new("L", (w_t, h_t), 0)
        draw = ImageDraw.Draw(mask)
        # Slightly smaller oval to avoid any background at edges
        margin = int(min(w_t, h_t) * 0.06)
        draw.ellipse((margin, margin, w_t - margin, h_t - margin), fill=255)
        # Heavy gaussian blur for smooth fade
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(8, int(min(w_t, h_t) * 0.08))))
        pil.putalpha(mask)
        return pil

    def _detect_face(self, cv_img):
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detectMultiScale(gray, 1.1, 5, 0, (30, 30))
        if len(faces) == 0:
            faces = self.detector.detectMultiScale(gray, 1.05, 3, 0, (20, 20))
        if len(faces) == 0:
            return None
        return tuple(max(faces, key=lambda f: f[2] * f[3]))

    # ------------------------------------------------------------------
    # Compose page
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
        tpl_bytes = storage.read_file(template_path)
        template = Image.open(io.BytesIO(tpl_bytes)).convert("RGBA")

        if face_circle_center and face_circle_radius:
            template = self._blend_face_into_circle(
                template, face_img, face_circle_center, face_circle_radius
            )
        else:
            masked = self._simple_oval_mask(face_img)
            template.paste(masked, face_position, masked)

        # Name replacement
        if child_name and name_text_regions:
            for region in name_text_regions:
                self._replace_name_in_line(template, child_name, region, name_font_size, name_color)
        elif child_name and name_position:
            self._overlay_name(template, child_name, name_position, name_font_size, name_color)

        # Save as RGB
        rgb = Image.new("RGB", template.size, (255, 255, 255))
        rgb.paste(template, mask=template.split()[3] if template.mode == "RGBA" else None)
        buf = io.BytesIO()
        rgb.save(buf, format="PNG", quality=95)
        buf.seek(0)
        return storage.save_file(buf, output_path)

    # ------------------------------------------------------------------
    # Advanced face blending
    # ------------------------------------------------------------------

    def _blend_face_into_circle(self, template, face, center, radius):
        """
        1. Inpaint the white circle area with surrounding pixels
        2. Paste face on top with feathered alpha so edges blend
        """
        cx, cy = center

        # Step 1: Inpaint white circle
        template = self._inpaint_white_circle(template, center, radius)

        # Step 2: Resize face to fill ~92% of the circle diameter
        face_diam = int(radius * 2 * 0.92)
        face_resized = face.resize((face_diam, face_diam), Image.Resampling.LANCZOS)

        # The face already has a feathered oval alpha from extract_face
        px = cx - face_diam // 2
        py = cy - face_diam // 2

        template.paste(face_resized, (px, py), face_resized)
        return template

    def _inpaint_white_circle(self, template, center, radius):
        cx, cy = center
        cv_img = cv2.cvtColor(np.array(template.convert("RGB")), cv2.COLOR_RGB2BGR)
        h, w = cv_img.shape[:2]

        ys = np.arange(max(0, cy - radius), min(h, cy + radius))
        xs = np.arange(max(0, cx - radius), min(w, cx + radius))
        yy, xx = np.meshgrid(ys, xs, indexing="ij")
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

        region = cv_img[ys[0]:ys[-1]+1, xs[0]:xs[-1]+1]
        inside = dist <= radius
        is_white = (region[:,:,0] > 225) & (region[:,:,1] > 225) & (region[:,:,2] > 225)
        mask_local = (inside & is_white).astype(np.uint8) * 255

        full_mask = np.zeros((h, w), dtype=np.uint8)
        full_mask[ys[0]:ys[-1]+1, xs[0]:xs[-1]+1] = mask_local

        if full_mask.sum() > 0:
            inpainted = cv2.inpaint(cv_img, full_mask, 12, cv2.INPAINT_TELEA)
            rgb = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
            result = Image.fromarray(rgb).convert("RGBA")
            if template.mode == "RGBA":
                result.putalpha(template.split()[3])
            return result
        return template

    # ------------------------------------------------------------------
    # Name text replacement — full-line inpaint + re-render
    # ------------------------------------------------------------------

    def _replace_name_in_line(self, img, name, region, font_size, color):
        """
        region = (x1, y1, x2, y2, full_line_text)
        If full_line_text is provided (as 5th element), inpaints the entire
        region and re-renders full_line_text with {name} replaced.
        Otherwise, just inpaints {name}-sized area and renders name.
        """
        if len(region) == 5:
            x1, y1, x2, y2, full_text = region
        else:
            x1, y1, x2, y2 = region
            full_text = None

        region_h = y2 - y1
        auto_size = max(int(region_h * 0.72), 10)

        # Step 1: Inpaint the region to remove all text
        cv_img = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        local = cv_img[y1:y2, x1:x2]
        gray_local = cv2.cvtColor(local, cv2.COLOR_BGR2GRAY)
        text_mask = (gray_local < 160).astype(np.uint8) * 255
        kernel = np.ones((3, 3), np.uint8)
        text_mask = cv2.dilate(text_mask, kernel, iterations=1)

        full_mask = np.zeros(cv_img.shape[:2], dtype=np.uint8)
        full_mask[y1:y2, x1:x2] = text_mask

        if full_mask.sum() > 0:
            inpainted = cv2.inpaint(cv_img, full_mask, 6, cv2.INPAINT_TELEA)
            rgb = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
            img_arr = np.array(img.convert("RGB"))
            img_arr[y1:y2, x1:x2] = rgb[y1:y2, x1:x2]
            img.paste(Image.fromarray(img_arr).convert("RGBA"))

        # Step 2: Re-render text
        draw = ImageDraw.Draw(img)
        font = _load_font(auto_size)

        if full_text:
            render_text = full_text.replace("{name}", name)
        else:
            render_text = name

        bbox = draw.textbbox((0, 0), render_text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        # Position: left-aligned at x1, vertically centered
        tx = x1
        ty = (y1 + y2) // 2 - th // 2

        draw.text((tx, ty), render_text, font=font, fill=(*color, 255))

    # ------------------------------------------------------------------
    # Simple helpers for placeholder pages
    # ------------------------------------------------------------------

    def _simple_oval_mask(self, img):
        w, h = img.size
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, w, h), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=3))
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.paste(img, (0, 0))
        out.putalpha(mask)
        return out

    def _overlay_name(self, img, name, position, font_size=48, color=(51, 51, 51)):
        draw = ImageDraw.Draw(img)
        font = _load_font(font_size)
        bbox = draw.textbbox((0, 0), name, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = position[0] - tw // 2
        y = position[1] - th // 2
        # White outline for readability on colored backgrounds
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                if dx or dy:
                    draw.text((x + dx, y + dy), name, font=font, fill=(255, 255, 255, 255))
        draw.text((x, y), name, font=font, fill=(*color, 255))


image_service = ImageService()

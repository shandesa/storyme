"""Face Blending & Text Overlay Service

- Blends a user's face into a DALL-E template using MediaPipe + seamlessClone
- Overlays story text onto the image in the designated text area
"""

import cv2
import numpy as np
import mediapipe as mp
import logging
from pathlib import Path
from typing import Optional, Dict, List
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

mp_face_mesh = mp.solutions.face_mesh

# Try to find a nice font, fallback to default
_FONT_PATH = None
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
for fp in _FONT_CANDIDATES:
    if Path(fp).exists():
        _FONT_PATH = fp
        break


def overlay_text_on_image(
    image_path: str,
    text_lines: List[str],
    text_area: Dict[str, int],
    output_path: str,
) -> str:
    """Overlay story text onto the image in the given text area.

    Uses PIL for nicer text rendering with outline for readability.
    """
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    x = text_area["x"]
    y = text_area["y"]
    w = text_area["w"]
    h = text_area["h"]

    # Combine lines
    full_text = "\n".join(text_lines)

    # Find optimal font size to fit within the text area
    font_size = 28
    font = None
    while font_size >= 14:
        if _FONT_PATH:
            font = ImageFont.truetype(_FONT_PATH, font_size)
        else:
            font = ImageFont.load_default()
            break

        # Wrap text to fit width
        wrapped = _wrap_text(draw, full_text, font, w - 20)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font)
        text_h = bbox[3] - bbox[1]

        if text_h <= h - 10:
            break
        font_size -= 2

    if font is None:
        font = ImageFont.load_default()

    wrapped = _wrap_text(draw, full_text, font, w - 20)

    # Calculate vertical centering
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font)
    text_height = bbox[3] - bbox[1]
    ty = y + (h - text_height) // 2

    # Draw text with dark outline for readability
    outline_color = (30, 30, 30)
    text_color = (255, 255, 255)
    tx = x + 10

    for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2), (-2, 0), (2, 0), (0, -2), (0, 2)]:
        draw.multiline_text((tx + dx, ty + dy), wrapped, font=font, fill=outline_color)
    draw.multiline_text((tx, ty), wrapped, font=font, fill=text_color)

    img.save(output_path)
    logger.info(f"Text overlay saved: {output_path}")
    return output_path


def _wrap_text(draw, text: str, font, max_width: int) -> str:
    """Wrap text to fit within max_width pixels."""
    lines = text.split("\n")
    wrapped_lines = []

    for line in lines:
        words = line.split()
        if not words:
            wrapped_lines.append("")
            continue

        current = words[0]
        for word in words[1:]:
            test = current + " " + word
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current = test
            else:
                wrapped_lines.append(current)
                current = word
        wrapped_lines.append(current)

    return "\n".join(wrapped_lines)


class FaceBlendService:
    """Blends a user's face into a generated storybook template."""

    def __init__(self):
        self._mesh = None

    def _get_mesh(self):
        if self._mesh is None:
            self._mesh = mp_face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=True,
            )
        return self._mesh

    def detect_landmarks(self, image: np.ndarray):
        mesh = self._get_mesh()
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        result = mesh.process(rgb)
        if not result.multi_face_landmarks:
            return None
        h, w = image.shape[:2]
        return np.array(
            [(int(l.x * w), int(l.y * h))
             for l in result.multi_face_landmarks[0].landmark]
        )

    def align_face(self, img: np.ndarray, pts: np.ndarray) -> np.ndarray:
        left_eye, right_eye = pts[33], pts[263]
        dx = float(right_eye[0] - left_eye[0])
        dy = float(right_eye[1] - left_eye[1])
        angle = np.degrees(np.arctan2(dy, dx))
        center = (
            (left_eye[0] + right_eye[0]) / 2,
            (left_eye[1] + right_eye[1]) / 2,
        )
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]))

    def extract_face_crop(self, image: np.ndarray, pts: np.ndarray) -> np.ndarray:
        hull = cv2.convexHull(pts)
        x, y, w, h = cv2.boundingRect(hull)
        pad_top = int(0.35 * h)
        pad_bottom = int(0.15 * h)
        pad_side = int(0.15 * w)
        y_start = max(0, y - pad_top)
        y_end = min(image.shape[0], y + h + pad_bottom)
        x_start = max(0, x - pad_side)
        x_end = min(image.shape[1], x + w + pad_side)
        return image[y_start:y_end, x_start:x_end]

    def blend_face_into_template(
        self,
        template_path: str,
        user_face_path: str,
        face_bbox: Dict[str, int],
        output_path: str,
    ) -> str:
        """Blend user face into template at the given face_bbox coordinates."""
        template = cv2.imread(template_path)
        user_img = cv2.imread(user_face_path)

        if template is None:
            raise FileNotFoundError(f"Template not found: {template_path}")
        if user_img is None:
            raise FileNotFoundError(f"User face not found: {user_face_path}")

        x = face_bbox["x"]
        y = face_bbox["y"]
        w = face_bbox["w"]
        h = face_bbox["h"]

        # Detect face in user photo
        pts = self.detect_landmarks(user_img)
        if pts is None:
            logger.warning("No face detected, using center crop fallback")
            ih, iw = user_img.shape[:2]
            d = min(iw, ih)
            cx, cy = iw // 2, ih // 2
            r = d // 2
            face_crop = user_img[cy - r:cy + r, cx - r:cx + r]
        else:
            aligned = self.align_face(user_img, pts)
            pts2 = self.detect_landmarks(aligned)
            if pts2 is None:
                pts2 = pts
                aligned = user_img
            face_crop = self.extract_face_crop(aligned, pts2)

        # Resize to fit face_bbox (95% fill)
        target_w = max(20, int(w * 0.95))
        target_h = max(20, int(h * 0.95))
        face_resized = cv2.resize(face_crop, (target_w, target_h))

        # Soft elliptical mask
        mask = np.zeros((target_h, target_w), dtype=np.uint8)
        cv2.ellipse(mask, (target_w // 2, target_h // 2),
                     (target_w // 2, target_h // 2), 0, 0, 360, 255, -1)
        mask = cv2.GaussianBlur(mask, (31, 31), 15)

        # Build canvas
        canvas_face = np.zeros_like(template)
        canvas_mask = np.zeros(template.shape[:2], dtype=np.uint8)

        x_off = x + (w - target_w) // 2
        y_off = y + (h - target_h) // 2

        th, tw = template.shape[:2]
        y1, y2 = max(0, y_off), min(th, y_off + target_h)
        x1, x2 = max(0, x_off), min(tw, x_off + target_w)
        fy1, fy2 = y1 - y_off, y1 - y_off + (y2 - y1)
        fx1, fx2 = x1 - x_off, x1 - x_off + (x2 - x1)

        if fy2 > fy1 and fx2 > fx1:
            canvas_face[y1:y2, x1:x2] = face_resized[fy1:fy2, fx1:fx2]
            canvas_mask[y1:y2, x1:x2] = mask[fy1:fy2, fx1:fx2]

        center = (x + w // 2, y + h // 2)

        if canvas_mask.max() == 0:
            logger.error("Empty mask — saving template as-is")
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(output_path, template)
            return output_path

        output = cv2.seamlessClone(
            canvas_face, template, canvas_mask, center, cv2.NORMAL_CLONE
        )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(output_path, output)
        logger.info(f"Blended face saved: {output_path}")
        return output_path


face_blend_service = FaceBlendService()

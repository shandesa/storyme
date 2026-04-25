"""
Face Personalisation Pipeline Service  (CPU-only)

Architecture: MediaPipe FaceMesh → pose warp → expression morph →
              colour match → seamlessClone → text overlay.

No GPU required. All dependencies already in requirements.txt.

GPU upgrade path
────────────────
The two methods marked  # GPU STUB  can be replaced with DECA/EMOCA
inference when an Azure ML GPU compute instance is provisioned.
Input/output contract for each stub:
    in  → np.ndarray  BGR face crop
    out → np.ndarray  same dimensions, same dtype

See docs/FACE_PIPELINE_DESIGN.md §6.3 for the exact replacement code.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ─── MediaPipe ────────────────────────────────────────────────────────────────
_mp_face_mesh = mp.solutions.face_mesh

# ─── Expression landmark delta presets ────────────────────────────────────────
# {landmark_index: (dy_fraction, dx_fraction)}
# dy: negative = move up,  positive = move down
# dx: negative = move left, positive = move right
# Fractions are relative to face bounding-box height / width respectively.
_EXPRESSION_DELTAS: Dict[str, Dict[int, Tuple[float, float]]] = {
    "neutral":    {},
    "smile":      {61: (-0.030,  0.010), 291: (-0.030, -0.010),
                   116: (-0.012, 0.000), 345: (-0.012,  0.000)},
    "joyful":     {61: (-0.050,  0.015), 291: (-0.050, -0.015),
                   116: (-0.022, 0.000), 345: (-0.022,  0.000)},
    "sad":        {61:  ( 0.025,  0.010), 291: ( 0.025, -0.010),
                   105: (-0.012,  0.005), 334: (-0.012, -0.005)},
    "curious":    {105: (-0.010,  0.005), 334: (-0.010, -0.005),
                   70:  (-0.008,  0.000), 300: (-0.008,  0.000),
                   61:  (-0.005,  0.003), 291: (-0.005, -0.003)},
    "determined": {105: ( 0.008,  0.005), 334: ( 0.008, -0.005)},
    "caring":     {61: (-0.020,  0.008), 291: (-0.020, -0.008),
                   116: (-0.008, 0.000), 345: (-0.008,  0.000)},
    "delighted":  {61: (-0.060,  0.020), 291: (-0.060, -0.020),
                   116: (-0.025, 0.000), 345: (-0.025,  0.000),
                   17:  ( 0.020, 0.000)},
    "focused":    {105: ( 0.005,  0.003), 334: ( 0.005, -0.003)},
    "gentle":     {61: (-0.015,  0.005), 291: (-0.015, -0.005),
                   116: (-0.005, 0.000), 345: (-0.005,  0.000)},
    "awed":       {105: (-0.015,  0.005), 334: (-0.015, -0.005),
                   70:  (-0.012,  0.000), 300: (-0.012,  0.000),
                   17:  ( 0.018,  0.000)},
    "welcoming":  {61: (-0.040,  0.015), 291: (-0.040, -0.015),
                   116: (-0.015, 0.000), 345: (-0.015,  0.000)},
    "proud":      {61: (-0.020,  0.008), 291: (-0.020, -0.008),
                   116: (-0.008, 0.000), 345: (-0.008,  0.000)},
}

# ─── Font ─────────────────────────────────────────────────────────────────────
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_FONT_PATH: Optional[str] = next(
    (p for p in _FONT_CANDIDATES if Path(p).exists()), None
)


class FacePipelineService:
    """
    End-to-end face personalisation pipeline (CPU-only).

    Public surface
    ──────────────
    process_character_page(...)  →  output PNG path
    process_text_only_page(...)  →  output PNG path
    """

    def __init__(self) -> None:
        self._face_mesh: Optional[object] = None

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════════════════

    def process_character_page(
        self,
        template_path: str,
        user_face_path: str,
        face_config: Dict[str, int],
        pose: Dict[str, float],
        expression: str,
        story_lines: List[str],
        text_area: Dict[str, int],
        child_name: str,
        output_path: str,
    ) -> str:
        """
        Full pipeline for a page where the child's face should appear.

        Parameters
        ──────────
        template_path : absolute path to the DALL-E / illustrated background PNG
        user_face_path: absolute path to the uploaded child photo
        face_config   : {x, y, w, h} of the blank oval in the template
        pose          : {yaw, pitch, roll} in degrees
        expression    : preset name (see _EXPRESSION_DELTAS)
        story_lines   : list of text lines (may contain {name})
        text_area     : {x, y, w, h} pixel region for text overlay
        child_name    : replaces {name} in story_lines
        output_path   : where to save the result PNG

        Returns
        ───────
        output_path (str)
        """
        template = cv2.imread(template_path)
        if template is None:
            raise FileNotFoundError(f"Template not found: {template_path}")

        user_img = cv2.imread(user_face_path)
        if user_img is None:
            raise FileNotFoundError(f"User face not found: {user_face_path}")

        x, y, w, h = (
            face_config["x"], face_config["y"],
            face_config["w"], face_config["h"],
        )

        # ── Step 1: Extract & roll-align face ─────────────────────────────────
        face_crop, landmarks = self._extract_and_align_face(user_img)
        if face_crop is None:
            logger.warning("Face extraction failed — using centre-crop fallback")
            face_crop = self._centre_crop(user_img)
            landmarks = self._detect_landmarks(face_crop)

        # ── Step 2: Head pose warp  [GPU STUB] ────────────────────────────────
        yaw   = float(pose.get("yaw",   0.0))
        pitch = float(pose.get("pitch", 0.0))
        roll  = float(pose.get("roll",  0.0))

        if abs(yaw) + abs(pitch) + abs(roll) > 1.0:
            face_crop = self._apply_pose_warp(face_crop, yaw, pitch, roll)
            landmarks = self._detect_landmarks(face_crop)

        # ── Step 3: Expression morph  [GPU STUB] ──────────────────────────────
        expr = expression.lower() if expression else "neutral"
        if expr != "neutral" and landmarks is not None:
            face_crop = self._apply_expression_morph(face_crop, landmarks, expr)
            landmarks = self._detect_landmarks(face_crop)

        # ── Step 4: Resize to 92 % of target bbox ─────────────────────────────
        scale    = 0.92
        target_w = max(20, int(w * scale))
        target_h = max(20, int(h * scale))
        face_resized = cv2.resize(face_crop, (target_w, target_h))

        # ── Step 5: Colour & lighting match ───────────────────────────────────
        th, tw = template.shape[:2]
        roi = template[
            max(0, y): min(th, y + h),
            max(0, x): min(tw, x + w),
        ]
        if roi.size > 0:
            face_resized = self._match_colour_and_lighting(face_resized, roi)

        # ── Step 6: Seamless clone ────────────────────────────────────────────
        output = self._blend_face_into_template(
            template, face_resized, x, y, w, h, target_w, target_h
        )

        # ── Step 7: Text overlay ──────────────────────────────────────────────
        output = self._overlay_text(output, story_lines, text_area, child_name)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(output_path, output)
        logger.info("Character page → %s", output_path)
        return output_path

    def process_text_only_page(
        self,
        template_path: str,
        story_lines: List[str],
        text_area: Dict[str, int],
        child_name: str,
        output_path: str,
    ) -> str:
        """Copy template and overlay story text (no face). Used for even pages."""
        template = cv2.imread(template_path)
        if template is None:
            raise FileNotFoundError(f"Template not found: {template_path}")

        output = self._overlay_text(template, story_lines, text_area, child_name)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(output_path, output)
        logger.info("Text-only page → %s", output_path)
        return output_path

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 1  — Face extraction & roll alignment
    # ═══════════════════════════════════════════════════════════════════════════

    def _get_mesh(self):
        if self._face_mesh is None:
            self._face_mesh = _mp_face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.4,
            )
        return self._face_mesh

    def _detect_landmarks(self, image: np.ndarray) -> Optional[np.ndarray]:
        """Return (N, 2) int32 pixel landmarks or None."""
        mesh = self._get_mesh()
        rgb  = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        res  = mesh.process(rgb)
        if not res.multi_face_landmarks:
            return None
        h, w = image.shape[:2]
        return np.array(
            [(int(l.x * w), int(l.y * h))
             for l in res.multi_face_landmarks[0].landmark],
            dtype=np.int32,
        )

    def _extract_and_align_face(
        self, image: np.ndarray
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        1. Detect landmarks.
        2. Align to horizontal eye-line (removes roll).
        3. Convex-hull crop with generous padding.
        Returns (crop, landmarks_in_crop).
        """
        pts = self._detect_landmarks(image)
        if pts is None:
            return None, None

        # ── Remove roll via eye-line alignment ───────────────────────────────
        left_eye  = pts[33].astype(float)
        right_eye = pts[263].astype(float)
        angle = float(np.degrees(np.arctan2(
            right_eye[1] - left_eye[1],
            right_eye[0] - left_eye[0],
        )))
        if abs(angle) > 0.5:
            center = tuple(((left_eye + right_eye) / 2).astype(float))
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            image = cv2.warpAffine(
                image, M, (image.shape[1], image.shape[0]),
                borderMode=cv2.BORDER_REFLECT_101,
            )
            pts_new = self._detect_landmarks(image)
            if pts_new is not None:
                pts = pts_new

        # ── Tight crop with padding ───────────────────────────────────────────
        hull = cv2.convexHull(pts)
        x, y, fw, fh = cv2.boundingRect(hull)

        pad_top    = int(0.40 * fh)
        pad_bottom = int(0.12 * fh)
        pad_side   = int(0.18 * fw)

        ih, iw = image.shape[:2]
        x0 = max(0, x - pad_side)
        y0 = max(0, y - pad_top)
        x1 = min(iw, x + fw + pad_side)
        y1 = min(ih, y + fh + pad_bottom)

        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            return None, None

        pts_crop = self._detect_landmarks(crop)
        return crop, pts_crop

    @staticmethod
    def _centre_crop(image: np.ndarray) -> np.ndarray:
        ih, iw = image.shape[:2]
        d  = min(iw, ih)
        cx, cy = iw // 2, ih // 2
        return image[cy - d//2: cy + d//2, cx - d//2: cx + d//2]

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 2  — Head pose warp  [GPU STUB]
    # ═══════════════════════════════════════════════════════════════════════════

    def _apply_pose_warp(
        self,
        face: np.ndarray,
        yaw: float,
        pitch: float,
        roll: float,
    ) -> np.ndarray:
        """
        Approximate 3-D head rotation with 2-D perspective warps.
        Accurate for |angle| ≤ 20°.  For larger angles use DECA (GPU stub).

        yaw   > 0  face turns right   (left side compressed)
        pitch > 0  face looks down    (bottom compressed)
        roll  > 0  face tilts CW
        """
        h, w   = face.shape[:2]
        result = face.copy()

        # Roll — pure 2-D rotation
        if abs(roll) > 0.5:
            M = cv2.getRotationMatrix2D((w // 2, h // 2), -roll, 1.0)
            result = cv2.warpAffine(result, M, (w, h),
                                    borderMode=cv2.BORDER_REFLECT_101)

        # Yaw — horizontal keystone
        if abs(yaw) > 0.5:
            near  = float(np.cos(np.radians(yaw)))
            delta = w * (1.0 - near) * 0.5
            src   = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
            if yaw > 0:          # compress left edge
                dst = np.float32([[delta, 0], [w, 0], [w, h], [delta, h]])
            else:                # compress right edge
                dst = np.float32([[0, 0], [w - delta, 0], [w - delta, h], [0, h]])
            M = cv2.getPerspectiveTransform(src, dst)
            result = cv2.warpPerspective(result, M, (w, h),
                                         borderMode=cv2.BORDER_REFLECT_101)

        # Pitch — vertical keystone
        if abs(pitch) > 0.5:
            near  = float(np.cos(np.radians(pitch)))
            delta = h * (1.0 - near) * 0.5
            src   = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
            if pitch > 0:        # compress bottom
                dst = np.float32([[0, 0], [w, 0], [w, h - delta], [0, h - delta]])
            else:                # compress top
                dst = np.float32([[0, delta], [w, delta], [w, h], [0, h]])
            M = cv2.getPerspectiveTransform(src, dst)
            result = cv2.warpPerspective(result, M, (w, h),
                                         borderMode=cv2.BORDER_REFLECT_101)

        return result

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 3  — Expression morphing  [GPU STUB]
    # ═══════════════════════════════════════════════════════════════════════════

    def _apply_expression_morph(
        self,
        face: np.ndarray,
        landmarks: np.ndarray,
        expression: str,
    ) -> np.ndarray:
        """
        Morph facial expression by displacing landmark positions and
        applying per-triangle affine warps (Delaunay triangulation).
        For expressions with no defined deltas, returns the original face.
        """
        deltas = _EXPRESSION_DELTAS.get(expression)
        if not deltas:
            return face

        h, w = face.shape[:2]
        src_pts = landmarks.astype(np.float32).copy()
        dst_pts = src_pts.copy()

        # Face bbox for scaling deltas to pixels
        x_min, y_min = src_pts[:, 0].min(), src_pts[:, 1].min()
        x_max, y_max = src_pts[:, 0].max(), src_pts[:, 1].max()
        bw = float(x_max - x_min)
        bh = float(y_max - y_min)

        for idx, (dy_frac, dx_frac) in deltas.items():
            if idx < len(dst_pts):
                dst_pts[idx, 0] = float(np.clip(dst_pts[idx, 0] + dx_frac * bw, 0, w - 1))
                dst_pts[idx, 1] = float(np.clip(dst_pts[idx, 1] + dy_frac * bh, 0, h - 1))

        return self._warp_by_landmarks(face, src_pts, dst_pts, w, h)

    def _warp_by_landmarks(
        self,
        src: np.ndarray,
        src_pts: np.ndarray,
        dst_pts: np.ndarray,
        w: int,
        h: int,
    ) -> np.ndarray:
        """Delaunay triangulation → per-triangle affine warp."""
        output = np.zeros_like(src)

        rect = (0, 0, w, h)
        subdiv = cv2.Subdiv2D(rect)

        for pt in src_pts:
            px, py = float(pt[0]), float(pt[1])
            if 0 < px < w - 1 and 0 < py < h - 1:
                try:
                    subdiv.insert((px, py))
                except cv2.error:
                    pass

        for tri in subdiv.getTriangleList():
            # tri = [x1,y1, x2,y2, x3,y3]
            pts_2d = [(tri[i], tri[i + 1]) for i in (0, 2, 4)]

            src_tri_pts = []
            dst_tri_pts = []
            valid = True
            for px, py in pts_2d:
                dists = np.hypot(src_pts[:, 0] - px, src_pts[:, 1] - py)
                idx   = int(np.argmin(dists))
                if dists[idx] > 2.5:
                    valid = False
                    break
                src_tri_pts.append(src_pts[idx])
                dst_tri_pts.append(dst_pts[idx])

            if not valid:
                continue

            s3 = np.float32(src_tri_pts)
            d3 = np.float32(dst_tri_pts)

            dr  = cv2.boundingRect(d3)
            xr, yr, wr, hr = dr
            if xr < 0 or yr < 0 or xr + wr >= w or yr + hr >= h:
                continue
            if wr <= 0 or hr <= 0:
                continue

            sr = cv2.boundingRect(s3)
            xs, ys, ws, hs = sr
            if xs < 0 or ys < 0 or ws <= 0 or hs <= 0:
                continue

            s3_off = s3 - np.float32([xs, ys])
            d3_off = d3 - np.float32([xr, yr])

            M = cv2.getAffineTransform(s3_off, d3_off)

            src_crop = src[ys: ys + hs, xs: xs + ws]
            if src_crop.size == 0:
                continue

            dst_crop = cv2.warpAffine(src_crop, M, (wr, hr),
                                      flags=cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_REFLECT_101)

            mask = np.zeros((hr, wr), dtype=np.uint8)
            cv2.fillConvexPoly(mask, np.int32(d3_off), 255)

            roi = output[yr: yr + hr, xr: xr + wr]
            roi[mask == 255] = dst_crop[mask == 255]
            output[yr: yr + hr, xr: xr + wr] = roi

        # Fill empty pixels (triangulation gaps) from original
        grey    = cv2.cvtColor(output, cv2.COLOR_BGR2GRAY)
        empty   = (grey == 0).astype(np.uint8) * 255
        output[empty == 255] = src[empty == 255]

        return output

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 4  — Colour & lighting match
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _match_colour_and_lighting(
        face: np.ndarray, roi: np.ndarray
    ) -> np.ndarray:
        """
        Normalise face colour/lighting to match the template ROI.
        Uses LAB colour space; blends 60 % matched + 40 % original to
        prevent over-correction on dark or unusual-lit selfies.
        """
        if face.size == 0 or roi.size == 0:
            return face

        f_lab = cv2.cvtColor(face, cv2.COLOR_BGR2LAB).astype(np.float32)
        r_lab = cv2.cvtColor(roi,  cv2.COLOR_BGR2LAB).astype(np.float32)

        matched = f_lab.copy()
        for ch in range(3):
            s_mean = f_lab[:, :, ch].mean()
            s_std  = f_lab[:, :, ch].std()  + 1e-6
            d_mean = r_lab[:, :, ch].mean()
            d_std  = r_lab[:, :, ch].std()  + 1e-6
            matched[:, :, ch] = (f_lab[:, :, ch] - s_mean) * (d_std / s_std) + d_mean

        blended = 0.60 * matched + 0.40 * f_lab
        blended = np.clip(blended, 0, 255).astype(np.uint8)
        return cv2.cvtColor(blended, cv2.COLOR_LAB2BGR)

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 5  — Seamless clone into template
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _blend_face_into_template(
        template: np.ndarray,
        face: np.ndarray,
        x: int, y: int, w: int, h: int,
        target_w: int, target_h: int,
    ) -> np.ndarray:
        """
        Place face into template using:
          1. Soft Gaussian-feathered elliptical mask
          2. cv2.seamlessClone (NORMAL_CLONE)
          3. Alpha-composite fallback if seamlessClone fails
        """
        th, tw = template.shape[:2]

        # Elliptical mask (44 % × 48 % of crop to avoid ear bleed)
        mask = np.zeros((target_h, target_w), dtype=np.uint8)
        ax = max(1, int(target_w * 0.44))
        ay = max(1, int(target_h * 0.48))
        cv2.ellipse(mask, (target_w // 2, target_h // 2), (ax, ay),
                    0, 0, 360, 255, -1)
        mask = cv2.GaussianBlur(mask, (31, 31), 15)

        # Position (centre face within target bbox)
        x_off = x + (w - target_w) // 2
        y_off = y + (h - target_h) // 2

        canvas_face = np.zeros_like(template)
        canvas_mask = np.zeros((th, tw), dtype=np.uint8)

        y1 = max(0, y_off);            y2 = min(th, y_off + target_h)
        x1 = max(0, x_off);            x2 = min(tw, x_off + target_w)
        fy1 = y1 - y_off;              fy2 = fy1 + (y2 - y1)
        fx1 = x1 - x_off;              fx2 = fx1 + (x2 - x1)

        if fy2 <= fy1 or fx2 <= fx1:
            return template

        canvas_face[y1:y2, x1:x2] = face[fy1:fy2, fx1:fx2]
        canvas_mask[y1:y2, x1:x2] = mask[fy1:fy2, fx1:fx2]

        if canvas_mask.max() == 0:
            return template

        center = (x + w // 2, y + h // 2)

        try:
            return cv2.seamlessClone(
                canvas_face, template, canvas_mask,
                center, cv2.NORMAL_CLONE,
            )
        except cv2.error as exc:
            logger.warning("seamlessClone failed (%s) — alpha fallback", exc)
            alpha  = canvas_mask.astype(np.float32) / 255.0
            alpha3 = np.stack([alpha, alpha, alpha], axis=2)
            return (
                canvas_face.astype(np.float32) * alpha3
                + template.astype(np.float32) * (1.0 - alpha3)
            ).astype(np.uint8)

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 6  — Text overlay
    # ═══════════════════════════════════════════════════════════════════════════

    def _overlay_text(
        self,
        image: np.ndarray,
        story_lines: List[str],
        text_area: Dict[str, int],
        child_name: str,
    ) -> np.ndarray:
        """
        Render story text in the designated area.
        • Replaces {name} with child_name.
        • Auto-sizes font to fill area.
        • Word-wraps to width.
        • White text with dark outline for readability on any background.
        """
        lines = [
            line.replace("{name}", child_name).replace('\\"', '"')
            for line in story_lines
        ]
        full_text = "\n".join(lines)

        pil  = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)

        ta_x = text_area["x"]
        ta_y = text_area["y"]
        ta_w = text_area["w"]
        ta_h = text_area["h"]

        font    = self._fit_font(draw, full_text, ta_w - 24, ta_h - 20)
        wrapped = self._wrap_text(draw, full_text, font, ta_w - 24)

        # Vertical centre
        bbox    = draw.multiline_textbbox((0, 0), wrapped, font=font)
        text_h  = bbox[3] - bbox[1]
        ty      = ta_y + max(0, (ta_h - text_h) // 2)
        tx      = ta_x + 12

        # Dark outline
        for ox, oy in [(-2,-2),(-2,2),(2,-2),(2,2),(-2,0),(2,0),(0,-2),(0,2)]:
            draw.multiline_text((tx + ox, ty + oy), wrapped,
                                font=font, fill=(20, 20, 20))
        draw.multiline_text((tx, ty), wrapped, font=font, fill=(255, 255, 255))

        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    def _fit_font(self, draw, text: str, max_w: int, max_h: int):
        for size in range(32, 11, -2):
            font    = self._load_font(size)
            wrapped = self._wrap_text(draw, text, font, max_w)
            bbox    = draw.multiline_textbbox((0, 0), wrapped, font=font)
            if (bbox[2] - bbox[0]) <= max_w and (bbox[3] - bbox[1]) <= max_h:
                return font
        return self._load_font(12)

    @staticmethod
    def _load_font(size: int):
        if _FONT_PATH:
            try:
                return ImageFont.truetype(_FONT_PATH, size)
            except Exception:
                pass
        return ImageFont.load_default()

    @staticmethod
    def _wrap_text(draw, text: str, font, max_width: int) -> str:
        result = []
        for raw in text.split("\n"):
            words = raw.split()
            if not words:
                result.append("")
                continue
            current = words[0]
            for word in words[1:]:
                test = current + " " + word
                if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
                    current = test
                else:
                    result.append(current)
                    current = word
            result.append(current)
        return "\n".join(result)


# Singleton
face_pipeline_service = FacePipelineService()

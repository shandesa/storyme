"""Face Blending Service — Production Integration
=================================================

Integrates the core logic from tests/playground/face_blend.py into the
StoryMe image generation pipeline.

Pipeline (per scene / page):
  1. Detect MediaPipe FaceMesh landmarks on the user's uploaded photo.
  2. Align the user face to a canonical frontal pose using
     cv2.estimateAffinePartial2D (7-point affine — robust, flip-safe).
  3. Extract the face region using ConvexHull bounding box.
  4. Resize + position the face using per-page face_config coordinates
     (sourced from Page.face_placement: FacePlacement).
  5. Match LAB-space colour statistics to the template ROI.
  6. Match luminance to the template ROI.
  7. Create a Gaussian-feathered elliptical mask.
  8. Blend via cv2.seamlessClone (Poisson blending) for seamless edges.

Text overlay (name, story text) is handled separately by image_service.py.

Reference: tests/playground/face_blend.py
Author: StoryMe Engineering
"""

import cv2
import numpy as np
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple

import mediapipe as mp

logger = logging.getLogger(__name__)

# ─── MediaPipe lazy init ────────────────────────────────────────────────────
_mp_face_mesh = mp.solutions.face_mesh


# ============================================================================
# CANONICAL FRONTAL FACE LANDMARK POSITIONS
# ============================================================================
# 7 landmarks used for affine estimation (same indices as playground).
# These are normalised (0–1) positions for a symmetrical frontal face.
# Scaled at runtime to the detected face crop size.
#
# Indices (MediaPipe 468-point mesh):
#   33  → left eye outer corner
#   263 → right eye outer corner
#   1   → nose tip
#   61  → left mouth corner
#   291 → right mouth corner
#   199 → chin
#   152 → forehead centre
#
CANONICAL_LANDMARK_INDICES = [33, 263, 1, 61, 291, 199, 152]

# Normalised (x, y) positions in [0, 1] space for a 1:1 face crop
CANONICAL_POSITIONS = np.array([
    [0.30, 0.38],   # 33  – left eye
    [0.70, 0.38],   # 263 – right eye
    [0.50, 0.55],   # 1   – nose tip
    [0.35, 0.70],   # 61  – left mouth corner
    [0.65, 0.70],   # 291 – right mouth corner
    [0.50, 0.88],   # 199 – chin
    [0.50, 0.18],   # 152 – forehead
], dtype=np.float32)


# ============================================================================
# MODULE-LEVEL HELPERS  (ported from tests/playground/face_blend.py)
# ============================================================================

def get_landmarks(image: np.ndarray) -> Optional[np.ndarray]:
    """
    Detect 468 MediaPipe FaceMesh landmarks on a BGR image.

    Ported from playground: face_blend.py → get_landmarks()

    Returns:
        np.ndarray of shape (468, 2) with pixel coordinates, or None if
        no face is detected.
    """
    with _mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1) as mesh:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        result = mesh.process(rgb)

        if not result.multi_face_landmarks:
            logger.debug("MediaPipe: no face landmarks detected")
            return None

        h, w = image.shape[:2]
        return np.array(
            [(int(lm.x * w), int(lm.y * h))
             for lm in result.multi_face_landmarks[0].landmark]
        )


def align_face_to_canonical(
    user_img: np.ndarray,
    user_pts: np.ndarray,
    target_size: Tuple[int, int],
) -> np.ndarray:
    """
    Align user face to a canonical frontal pose using affine estimation.

    Adapted from playground: face_blend.py → align_face()
    Key improvement: uses estimateAffinePartial2D (7 landmarks, LMEDS)
    instead of simple eye-rotation — handles head tilt, scale, translation.
    Flip-detection guard prevents mirror artefacts.

    Args:
        user_img:    BGR user photo
        user_pts:    detected landmarks (468, 2)
        target_size: (width, height) of the output canvas

    Returns:
        Warped BGR image of size target_size
    """
    tw, th = target_size

    # Scale canonical positions to target canvas
    canonical_scaled = (CANONICAL_POSITIONS * np.array([tw, th])).astype(np.float32)

    user_kp = np.array(
        [user_pts[i] for i in CANONICAL_LANDMARK_INDICES], dtype=np.float32
    )
    ref_kp = canonical_scaled

    M, _ = cv2.estimateAffinePartial2D(user_kp, ref_kp, method=cv2.LMEDS)

    if M is None:
        logger.warning("Affine estimation failed — returning original image resized")
        return cv2.resize(user_img, (tw, th))

    # Guard: negative determinant means a flip was detected
    if np.linalg.det(M[:2, :2]) < 0:
        logger.warning("Flip detected in affine matrix — skipping alignment")
        return cv2.resize(user_img, (tw, th))

    return cv2.warpAffine(
        user_img, M, (tw, th),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def extract_face_hull(
    warped_img: np.ndarray,
    landmarks: np.ndarray,
) -> Tuple[Optional[np.ndarray], int, int, int, int]:
    """
    Extract the face region from a warped image using ConvexHull bounding box.

    Ported from playground: face_blend.py → process_scene() extraction block.
    Uses the full facial convex hull to capture the complete face outline
    (including hair border) rather than a fixed rectangular crop.

    Returns:
        (face_crop, x, y, w, h) — the cropped face and its source coordinates.
        Returns (None, 0, 0, 0, 0) on failure.
    """
    H, W = warped_img.shape[:2]
    x, y, w, h = cv2.boundingRect(cv2.convexHull(landmarks))

    # Clamp to image bounds
    x = max(0, x)
    y = max(0, y)
    w = min(w, W - x)
    h = min(h, H - y)

    if w <= 0 or h <= 0:
        logger.error("Invalid convex hull bounding box — face extraction failed")
        return None, 0, 0, 0, 0

    face = warped_img[y:y + h, x:x + w]

    if face is None or face.size == 0:
        logger.error("Empty face crop after hull extraction")
        return None, 0, 0, 0, 0

    return face, x, y, w, h


def match_color(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """
    Match LAB-space colour statistics of src to dst.

    Ported directly from playground: face_blend.py → match_color()
    Normalises mean and standard deviation for each LAB channel so the
    user's skin tone matches the illustration palette.

    Args:
        src: BGR source image (face to adjust)
        dst: BGR destination image (template ROI — target palette)

    Returns:
        Colour-matched BGR image (same shape as src)
    """
    src_lab = cv2.cvtColor(src, cv2.COLOR_BGR2LAB).astype(np.float32)
    dst_lab = cv2.cvtColor(dst, cv2.COLOR_BGR2LAB).astype(np.float32)

    for i in range(3):
        s_mean, s_std = src_lab[:, :, i].mean(), src_lab[:, :, i].std()
        d_mean, d_std = dst_lab[:, :, i].mean(), dst_lab[:, :, i].std()
        src_lab[:, :, i] = (
            (src_lab[:, :, i] - s_mean) / (s_std + 1e-6)
        ) * d_std + d_mean

    matched = cv2.cvtColor(
        np.clip(src_lab, 0, 255).astype(np.uint8),
        cv2.COLOR_LAB2BGR,
    )
    return matched


def match_light(face: np.ndarray, roi: np.ndarray) -> np.ndarray:
    """
    Match luminance of face to the template ROI.

    Ported directly from playground: face_blend.py → match_light()
    Adjusts overall brightness and applies a warm-bias correction when the
    template ROI is warm-toned (red channel > blue channel).

    Args:
        face: BGR face crop
        roi:  BGR template region-of-interest at the placement coordinates

    Returns:
        Luminance-adjusted BGR face (same shape as face)
    """
    face = face.astype(np.float32)
    roi  = roi.astype(np.float32)

    ratio = roi.mean() / (face.mean() + 1e-6)
    face *= ratio

    # Warm bias: if the ROI is warm-toned, boost red and green slightly
    if roi[:, :, 2].mean() > roi[:, :, 0].mean():
        face[:, :, 2] *= 1.05   # red channel
        face[:, :, 1] *= 1.02   # green channel

    return np.clip(face, 0, 255).astype(np.uint8)


def create_blend_mask(w: int, h: int) -> np.ndarray:
    """
    Create a Gaussian-feathered elliptical mask for seamless blending.

    Ported from playground: face_blend.py → create_mask()
    Ellipse axes set to 84% width and 100% height for a natural face oval.
    Gaussian blur (kernel=51, sigma=25) provides soft feathering so
    seamlessClone edges are invisible.

    Args:
        w: mask width in pixels
        h: mask height in pixels

    Returns:
        Single-channel uint8 mask (0–255)
    """
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(
        mask,
        (w // 2, h // 2),
        (int(w * 0.42), int(h * 0.50)),
        angle=0, startAngle=0, endAngle=360,
        color=255, thickness=-1,
    )
    return cv2.GaussianBlur(mask, (51, 51), 25)


# ============================================================================
# CORE SCENE PROCESSOR  (primary entry point for generate.py)
# ============================================================================

def process_scene(
    template_path: str,
    user_face_path: str,
    face_config: Dict[str, int],
    output_path: str,
) -> Optional[str]:
    """
    Blend user face into a template page using the full playground pipeline.

    This is the primary entry point called by generate.py for each story page.
    It is a direct port of tests/playground/face_blend.py → process_scene(),
    adapted to work with:
      - Absolute file paths (instead of relative playground dirs)
      - face_config dict sourced from Page.face_placement (FacePlacement model)
      - Output path under the configured storage directory

    Full pipeline steps:
      1. Load template + user image via cv2.imread
      2. Detect MediaPipe landmarks on user photo
      3. Align user face to canonical frontal pose (7-point affine, LMEDS)
      4. Re-detect landmarks on aligned image
      5. Extract face region via ConvexHull bounding box
      6. Resize + position at face_config {x, y, w, h} coordinates
      7. Colour-match to template ROI (LAB space mean/std normalisation)
      8. Luminance-match to template ROI (brightness + warm-bias)
      9. Create Gaussian-feathered elliptical mask
     10. cv2.seamlessClone (Poisson blending) into template
     11. Save output PNG

    Args:
        template_path:  Absolute path to the illustrated template PNG
        user_face_path: Absolute path to the uploaded user photo
        face_config:    Dict with keys x, y, w, h — face placement in template.
                        Sourced from Page.face_placement (FacePlacement model):
                            {"x": fp.x, "y": fp.y, "w": fp.width, "h": fp.height}
        output_path:    Absolute path where the blended output PNG is saved

    Returns:
        output_path string on success.
        None on any failure — caller (generate.py) falls back to PIL pipeline.
    """
    template = cv2.imread(template_path)
    user_img  = cv2.imread(user_face_path)

    if template is None:
        logger.error(f"Template not found: {template_path}")
        return None
    if user_img is None:
        logger.error(f"User face not found: {user_face_path}")
        return None

    th, tw = template.shape[:2]

    # ── Step 1: Landmark detection on original user photo ───────────────────
    user_pts = get_landmarks(user_img)

    if user_pts is None:
        logger.warning("No face detected in user photo — falling back to PIL pipeline")
        return None

    # ── Step 2: Affine-align to canonical pose on a canvas = template size ──
    aligned = align_face_to_canonical(user_img, user_pts, target_size=(tw, th))

    # ── Step 3: Re-detect landmarks on the aligned image ────────────────────
    aligned_pts = get_landmarks(aligned)

    if aligned_pts is None:
        logger.warning("No landmarks on aligned image — using pre-alignment landmarks")
        aligned_pts = user_pts
        aligned = user_img

    # ── Step 4: Extract face via ConvexHull ──────────────────────────────────
    face, fx, fy, fw, fh = extract_face_hull(aligned, aligned_pts)

    if face is None:
        logger.warning("Face hull extraction failed — falling back to PIL pipeline")
        return None

    # ── Step 5: Resize + position using face_config ──────────────────────────
    tx      = face_config["x"]
    ty      = face_config["y"]
    target_w = face_config["w"]
    target_h = face_config["h"]

    if target_w <= 0 or target_h <= 0:
        logger.error(f"Invalid face_config dimensions: w={target_w}, h={target_h}")
        return None

    face = cv2.resize(face, (target_w, target_h))

    # ── Step 6: Colour + luminance match to template ROI ─────────────────────
    roi_y1 = max(0, ty)
    roi_y2 = min(th, ty + target_h)
    roi_x1 = max(0, tx)
    roi_x2 = min(tw, tx + target_w)

    roi = template[roi_y1:roi_y2, roi_x1:roi_x2]

    if roi.size > 0:
        # Resize ROI to match face dimensions if clamped to canvas edge
        if roi.shape[:2] != (target_h, target_w):
            roi_for_match = cv2.resize(roi, (target_w, target_h))
        else:
            roi_for_match = roi

        face = match_color(face, roi_for_match)
        face = match_light(face, roi_for_match)

    # ── Step 7: Build canvas + Gaussian elliptical mask ──────────────────────
    mask = create_blend_mask(target_w, target_h)

    canvas_face = np.zeros_like(template)
    canvas_mask = np.zeros((th, tw), dtype=np.uint8)

    # Clamp placement to canvas bounds
    y1 = max(0, ty)
    y2 = min(th, ty + target_h)
    x1 = max(0, tx)
    x2 = min(tw, tx + target_w)
    fy1 = y1 - ty
    fy2 = fy1 + (y2 - y1)
    fx1 = x1 - tx
    fx2 = fx1 + (x2 - x1)

    if fy2 > fy1 and fx2 > fx1:
        canvas_face[y1:y2, x1:x2] = face[fy1:fy2, fx1:fx2]
        canvas_mask[y1:y2, x1:x2] = mask[fy1:fy2, fx1:fx2]
    else:
        logger.error("Face placement is fully outside template bounds — skipping")
        return None

    if canvas_mask.max() == 0:
        logger.error("Empty blend mask — seamlessClone cannot proceed")
        return None

    # ── Step 8: seamlessClone (Poisson blending) ──────────────────────────────
    center = (tx + target_w // 2, ty + target_h // 2)

    try:
        blended = cv2.seamlessClone(
            canvas_face, template, canvas_mask, center, cv2.NORMAL_CLONE
        )
    except cv2.error as e:
        logger.error(f"seamlessClone failed: {e}")
        return None

    # ── Step 9: Save ──────────────────────────────────────────────────────────
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    success = cv2.imwrite(output_path, blended)
    if not success:
        logger.error(f"cv2.imwrite failed: {output_path}")
        return None

    logger.info(f"✅ Blended scene saved → {output_path}")
    return output_path


# ============================================================================
# LEGACY FaceBlendService CLASS  — PRESERVED FOR REFERENCE
# ============================================================================
# The original FaceBlendService class is retained below in commented form.
# It was the first MediaPipe integration attempt and used:
#   - Eye-angle rotation (cv2.getRotationMatrix2D) for alignment
#   - ConvexHull crop with fixed padding ratios (0.35 top, 0.15 sides/bottom)
#   - No colour or luminance matching
#   - seamlessClone as the final blend step (same as new pipeline)
#
# Production code now calls process_scene() above, which ports the full
# playground pipeline (align → extract → colour match → light match → clone).
#
# To restore the legacy path: replace the process_scene() call in generate.py
# with face_blend_service.blend_face_into_template().
# ─────────────────────────────────────────────────────────────────────────────

class _LegacyFaceBlendService:
    """LEGACY — not used in production. See module docstring."""

    def __init__(self):
        self._mesh = None

    # ── Legacy: lazy mesh init ────────────────────────────────────────────────
    # def _get_mesh(self):
    #     if self._mesh is None:
    #         self._mesh = _mp_face_mesh.FaceMesh(
    #             static_image_mode=True, max_num_faces=1, refine_landmarks=True,
    #         )
    #     return self._mesh

    # ── Legacy: landmark detection (same algorithm, different context manager) ─
    # def detect_landmarks(self, image: np.ndarray):
    #     mesh = self._get_mesh()
    #     rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    #     result = mesh.process(rgb)
    #     if not result.multi_face_landmarks:
    #         return None
    #     h, w = image.shape[:2]
    #     return np.array(
    #         [(int(l.x * w), int(l.y * h))
    #          for l in result.multi_face_landmarks[0].landmark]
    #     )

    # ── Legacy: eye-rotation alignment ───────────────────────────────────────
    # REPLACED BY: align_face_to_canonical() — 7-point affine, handles tilt+scale
    # def align_face(self, img: np.ndarray, pts: np.ndarray) -> np.ndarray:
    #     left_eye, right_eye = pts[33], pts[263]
    #     dx = float(right_eye[0] - left_eye[0])
    #     dy = float(right_eye[1] - left_eye[1])
    #     angle = np.degrees(np.arctan2(dy, dx))
    #     center = (
    #         (left_eye[0] + right_eye[0]) / 2,
    #         (left_eye[1] + right_eye[1]) / 2,
    #     )
    #     M = cv2.getRotationMatrix2D(center, angle, 1.0)
    #     return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]))

    # ── Legacy: hull crop with padding ───────────────────────────────────────
    # REPLACED BY: extract_face_hull() — tighter hull, no fixed padding
    # def extract_face_crop(self, image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    #     hull = cv2.convexHull(pts)
    #     x, y, w, h = cv2.boundingRect(hull)
    #     pad_top    = int(0.35 * h)   # forehead padding
    #     pad_bottom = int(0.15 * h)
    #     pad_side   = int(0.15 * w)
    #     y_start = max(0, y - pad_top)
    #     y_end   = min(image.shape[0], y + h + pad_bottom)
    #     x_start = max(0, x - pad_side)
    #     x_end   = min(image.shape[1], x + w + pad_side)
    #     return image[y_start:y_end, x_start:x_end]

    # ── Legacy: full blend method ─────────────────────────────────────────────
    # REPLACED BY: process_scene() — adds colour match + light match
    # def blend_face_into_template(
    #     self,
    #     template_path: str,
    #     user_face_path: str,
    #     face_bbox: Dict,
    #     output_path: str,
    # ) -> str:
    #     template = cv2.imread(template_path)
    #     user_img  = cv2.imread(user_face_path)
    #     ... (see git history for original full body)


# Singleton — retained so any legacy imports resolve without error
face_blend_service = _LegacyFaceBlendService()

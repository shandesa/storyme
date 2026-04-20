"""
tests/tuner/blend_runner.py
============================
Runs face_blend_service.process_scene() with a given parameter set
on all 15 sample user face images for a given scene.

Returns a list of local paths to the blended output PNGs.
The caller (optimiser.py) passes these to score_runner.py for evaluation.

Parameters are passed as a dict that overrides the constants in
face_blend_service.py at runtime using monkey-patching — no file writes,
no recompilation, no subprocess. Safe because this runs single-threaded.
"""

from __future__ import annotations
import logging
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# Ensure backend is importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger(__name__)


def run_blend_with_params(
    sample_paths:   list[str],          # paths to 15 user face images
    template_path:  str,                # path to scene template PNG
    reference_path: str,                # path to scene reference PNG
    face_config:    dict,               # {x, y, w, h} for this scene
    params:         dict,               # parameter overrides (from tuner_params.py)
    output_dir:     Optional[Path] = None,
) -> list[str]:
    """
    Blend all sample faces onto the given template using the specified params.

    Args:
        sample_paths:   List of absolute paths to user face images.
        template_path:  Absolute path to the scene template PNG.
        reference_path: Absolute path to the scene reference PNG.
        face_config:    {x, y, w, h} placement coordinates in the template.
        params:         Dict of parameter name → value (from PARAMS or a trial set).
        output_dir:     Where to write blended PNGs. Uses system temp if None.

    Returns:
        List of absolute paths to blended PNG outputs (same order as sample_paths).
        A path is None if blending failed for that sample.
    """
    out_dir = output_dir or Path(tempfile.mkdtemp(prefix="tuner_blend_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    template  = cv2.imread(template_path)
    reference = cv2.imread(reference_path)

    if template is None or reference is None:
        logger.error("Cannot read template or reference: %s / %s", template_path, reference_path)
        return [None] * len(sample_paths)

    results: list[Optional[str]] = []

    for i, face_path in enumerate(sample_paths):
        user_img = cv2.imread(face_path)
        if user_img is None:
            logger.warning("Cannot read sample %d: %s", i, face_path)
            results.append(None)
            continue

        try:
            blended = _blend_one(
                user_img=user_img,
                template=template,
                reference=reference,
                face_config=face_config,
                params=params,
            )
            if blended is None:
                results.append(None)
                continue

            out_path = out_dir / f"blend_{i:02d}_{uuid.uuid4().hex[:6]}.png"
            cv2.imwrite(str(out_path), blended)
            results.append(str(out_path))

        except Exception as e:
            logger.warning("Blend failed for sample %d (%s): %s", i, face_path, e)
            results.append(None)

    succeeded = sum(1 for r in results if r is not None)
    logger.info("Blend: %d/%d samples succeeded", succeeded, len(sample_paths))
    return results


def _blend_one(
    user_img:    np.ndarray,
    template:    np.ndarray,
    reference:   np.ndarray,
    face_config: dict,
    params:      dict,
) -> Optional[np.ndarray]:
    """
    Run the full face_blend pipeline with parameterised constants.

    This mirrors the logic in face_blend_service.process_scene() but
    every tunable constant is read from `params` instead of being hardcoded.
    This lets the optimiser try different values without touching any files.
    """
    import mediapipe as mp

    # ── Get params (with fallbacks to current defaults) ────────────────────────
    mask_rx          = params.get("mask_ellipse_rx",    0.42)
    mask_ry          = params.get("mask_ellipse_ry",    0.50)
    blur_sigma       = int(params.get("mask_blur_sigma", 25))
    face_scale       = params.get("face_scale",          1.0)
    lum_strength     = params.get("luminance_strength",  1.0)
    warm_r           = params.get("warm_tint_r",         1.05)
    warm_g           = params.get("warm_tint_g",         1.02)
    clone_mode_str   = params.get("clone_mode",          "NORMAL_CLONE")
    clone_mode       = cv2.MIXED_CLONE if clone_mode_str == "MIXED_CLONE" else cv2.NORMAL_CLONE

    # ── Landmark detection ─────────────────────────────────────────────────────
    mp_mesh = mp.solutions.face_mesh
    def get_lm(img):
        with mp_mesh.FaceMesh(static_image_mode=True, max_num_faces=1) as mesh:
            result = mesh.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            if not result.multi_face_landmarks:
                return None
            h, w = img.shape[:2]
            return np.array([
                (int(l.x * w), int(l.y * h))
                for l in result.multi_face_landmarks[0].landmark
            ])

    ref_pts  = get_lm(reference)
    user_pts = get_lm(user_img)
    if ref_pts is None or user_pts is None:
        return None

    # ── Affine alignment ───────────────────────────────────────────────────────
    idx      = [33, 263, 1, 61, 291, 199, 152]
    user_kp  = np.array([user_pts[i] for i in idx], dtype=np.float32)
    ref_kp   = np.array([ref_pts[i] for i in idx],  dtype=np.float32)
    M, _     = cv2.estimateAffinePartial2D(user_kp, ref_kp, method=cv2.LMEDS)
    if M is None or np.linalg.det(M[:2, :2]) < 0:
        return None
    aligned  = cv2.warpAffine(
        user_img, M, (reference.shape[1], reference.shape[0]),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101,
    )

    # ── Face extraction via ConvexHull ─────────────────────────────────────────
    x, y, w, h = cv2.boundingRect(cv2.convexHull(ref_pts))
    H, W = aligned.shape[:2]
    x, y = max(0, x), max(0, y)
    w, h = min(w, W-x), min(h, H-y)
    if w <= 0 or h <= 0:
        return None
    face = aligned[y:y+h, x:x+w]

    # ── Scale and position ─────────────────────────────────────────────────────
    tx, ty   = face_config["x"], face_config["y"]
    tw       = max(1, int(face_config["w"] * face_scale))
    th       = max(1, int(face_config["h"] * face_scale))
    face     = cv2.resize(face, (tw, th))

    # ── Colour and luminance match ─────────────────────────────────────────────
    roi      = template[ty:ty+th, tx:tx+tw]
    if roi.size == 0:
        return None

    # LAB colour match (full strength always — main tunable is luminance)
    src_lab  = cv2.cvtColor(face, cv2.COLOR_BGR2LAB).astype(np.float32)
    dst_lab  = cv2.cvtColor(roi,  cv2.COLOR_BGR2LAB).astype(np.float32)
    for c in range(3):
        s_mean, s_std = src_lab[:,:,c].mean(), src_lab[:,:,c].std()
        d_mean, d_std = dst_lab[:,:,c].mean(), dst_lab[:,:,c].std()
        src_lab[:,:,c] = (src_lab[:,:,c] - s_mean) / (s_std + 1e-6) * d_std + d_mean
    face = cv2.cvtColor(np.clip(src_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)

    # Luminance match with configurable strength
    f32      = face.astype(np.float32)
    r32      = roi.astype(np.float32)
    ratio    = r32.mean() / (f32.mean() + 1e-6)
    # Blend between original luminance and fully matched (controlled by lum_strength)
    adjusted = f32 * (1.0 - lum_strength) + f32 * ratio * lum_strength
    # Warm tint (applied only when scene ROI is warm-toned)
    if r32[:, :, 2].mean() > r32[:, :, 0].mean():
        adjusted[:, :, 2] *= warm_r
        adjusted[:, :, 1] *= warm_g
    face     = np.clip(adjusted, 0, 255).astype(np.uint8)

    # ── Mask creation ──────────────────────────────────────────────────────────
    mask = np.zeros((th, tw), dtype=np.uint8)
    cv2.ellipse(
        mask, (tw // 2, th // 2),
        (max(1, int(tw * mask_rx)), max(1, int(th * mask_ry))),
        0, 0, 360, 255, -1,
    )
    # Kernel size must be odd and large enough for the sigma
    k = max(3, (blur_sigma * 4 + 1) | 1)   # odd, ≥ 3
    mask = cv2.GaussianBlur(mask, (k, k), blur_sigma)

    if mask.max() == 0:
        return None

    # ── SeamlessClone ──────────────────────────────────────────────────────────
    canvas_face           = np.zeros_like(template)
    canvas_mask           = np.zeros(template.shape[:2], dtype=np.uint8)
    canvas_face[ty:ty+th, tx:tx+tw] = face
    canvas_mask[ty:ty+th, tx:tx+tw] = mask

    center = (tx + tw // 2, ty + th // 2)
    try:
        return cv2.seamlessClone(canvas_face, template, canvas_mask, center, clone_mode)
    except cv2.error as e:
        logger.warning("seamlessClone failed: %s", e)
        return None

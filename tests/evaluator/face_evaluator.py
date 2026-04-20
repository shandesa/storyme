"""
tests/evaluator/face_evaluator.py
===================================
Core face attribute evaluator for StoryMe generated images.

Architecture
------------
FaceEvaluator.evaluate(image_path, scene_meta, face_config)
    → EvaluationResult (composite score + per-attribute breakdown)

Attributes evaluated (all computed locally via OpenCV + MediaPipe):

1. face_detected          — MediaPipe FaceMesh found a face in the ROI
2. gaze_direction         — Left iris centroid vs eye centre → "camera"|"subject"|"ambient"
3. expression             — Eye aspect ratio + mouth curvature → "smile"|"neutral"|"wonder"
4. head_tilt              — Roll angle from eye landmarks (bilateral, degrees)
5. face_coverage          — Detected face bbox area / face_config area
6. lighting_match         — LAB colour similarity: face ROI vs surrounding template area
7. blend_edge_quality     — Sobel gradient variance at face boundary (lower = smoother)

Scoring
-------
Each attribute produces a score in [0, 1].
Composite = weighted sum using SceneMeta weights.
Pass threshold = SceneMeta.passing_score (default 0.72).

All evaluations are deterministic and run entirely locally — no API calls.
The evaluator is safe to run in a loop.
"""

from __future__ import annotations
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np

from tests.evaluator.scene_metadata import SceneMeta

logger = logging.getLogger(__name__)

# MediaPipe landmark indices
# https://developers.google.com/mediapipe/solutions/vision/face_landmarker
_LEFT_EYE   = [33, 160, 158, 133, 153, 144]   # 6-point left eye
_RIGHT_EYE  = [263, 387, 385, 362, 380, 373]  # 6-point right eye
_LEFT_IRIS  = [469, 470, 471, 472]
_RIGHT_IRIS = [474, 475, 476, 477]
_MOUTH_TOP  = 13
_MOUTH_BOT  = 14
_MOUTH_L    = 61
_MOUTH_R    = 291
_NOSE_TIP   = 4


@dataclass
class AttributeScore:
    """Score and diagnostic for a single attribute."""
    name:        str
    score:       float          # 0.0 – 1.0
    raw_value:   float | str    # measured value (angle, ratio, label, etc.)
    expected:    str            # what we expected
    passed:      bool
    note:        str = ""


@dataclass
class EvaluationResult:
    """Full evaluation result for one generated image."""
    image_path:      str
    scene_file:      str
    generation_id:   str
    child_name:      str
    story_id:        str
    composite_score: float              # weighted sum of attribute scores
    passed:          bool               # composite_score >= SceneMeta.passing_score
    attributes:      list[AttributeScore] = field(default_factory=list)
    error:           Optional[str] = None

    def summary(self) -> str:
        status = "✅ PASS" if self.passed else "❌ FAIL"
        lines  = [
            f"{status} [{self.composite_score:.2f}] — "
            f"{self.scene_file} | {self.child_name} | {self.generation_id[:8]}",
        ]
        for a in self.attributes:
            mark = "✓" if a.passed else "✗"
            lines.append(
                f"  {mark} {a.name:<22} score={a.score:.2f}  "
                f"measured={a.raw_value!r}  expected={a.expected}  {a.note}"
            )
        return "\n".join(lines)


class FaceEvaluator:
    """
    Evaluates face attribute quality in a generated scene image.

    Usage:
        evaluator = FaceEvaluator()
        result    = evaluator.evaluate(
            image_path   = "/path/to/generated_page.png",
            scene_meta   = SCENE_METADATA["scene_01.png"],
            face_config  = {"x": 297, "y": 608, "w": 192, "h": 180},
            generation_id = "abc123",
            child_name    = "Niku",
            story_id      = "forest_of_smiles",
        )
        print(result.summary())
    """

    def __init__(self):
        self._mp_face_mesh = mp.solutions.face_mesh
        self._face_mesh    = self._mp_face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,   # enables iris landmarks
            min_detection_confidence=0.4,
        )

    # ─── Public API ───────────────────────────────────────────────────────────

    def evaluate(
        self,
        image_path:    str,
        scene_meta:    SceneMeta,
        face_config:   dict,          # {x, y, w, h} from FACE_COORDS
        generation_id: str = "",
        child_name:    str = "",
        story_id:      str = "",
    ) -> EvaluationResult:
        """
        Evaluate face attributes in one generated image.

        Args:
            image_path:    Absolute path to the PNG file.
            scene_meta:    SceneMeta for this scene (expected attributes).
            face_config:   {x, y, w, h} pixel coords of the face region.
            generation_id: Blob storage generation session ID.
            child_name:    For reporting.
            story_id:      For reporting.

        Returns:
            EvaluationResult with composite score and per-attribute breakdown.
        """
        base_result = EvaluationResult(
            image_path=image_path,
            scene_file=scene_meta.scene_file,
            generation_id=generation_id,
            child_name=child_name,
            story_id=story_id,
            composite_score=0.0,
            passed=False,
        )

        img_bgr = cv2.imread(image_path)
        if img_bgr is None:
            base_result.error = f"Cannot read image: {image_path}"
            return base_result

        H, W = img_bgr.shape[:2]
        fx, fy, fw, fh = (
            face_config["x"], face_config["y"],
            face_config["w"], face_config["h"],
        )

        # Clamp ROI to image bounds
        fx = max(0, fx);  fy = max(0, fy)
        fw = min(fw, W - fx);  fh = min(fh, H - fy)

        # Extract face region of interest
        face_roi_bgr = img_bgr[fy:fy+fh, fx:fx+fw]

        # Run MediaPipe on full image (face context matters for gaze)
        img_rgb      = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        mp_result    = self._face_mesh.process(img_rgb)
        landmarks    = None
        if mp_result.multi_face_landmarks:
            landmarks = mp_result.multi_face_landmarks[0].landmark

        # ── Evaluate each attribute ───────────────────────────────────────────
        attrs: list[AttributeScore] = []

        a_detected = self._eval_face_detected(landmarks)
        attrs.append(a_detected)

        if landmarks:
            attrs.append(self._eval_gaze(landmarks, img_bgr.shape, scene_meta))
            attrs.append(self._eval_expression(landmarks, img_bgr.shape, scene_meta))
            attrs.append(self._eval_head_tilt(landmarks, img_bgr.shape, scene_meta))

        attrs.append(self._eval_face_coverage(face_roi_bgr, fw, fh, scene_meta))
        attrs.append(self._eval_lighting_match(img_bgr, fx, fy, fw, fh, scene_meta))
        attrs.append(self._eval_blend_edge(img_bgr, fx, fy, fw, fh, scene_meta))

        # ── Composite score ───────────────────────────────────────────────────
        weight_map = {
            "face_detected":    scene_meta.weight_face_detected,
            "gaze_direction":   scene_meta.weight_gaze,
            "expression":       scene_meta.weight_expression,
            "head_tilt":        scene_meta.weight_tilt,
            "face_coverage":    scene_meta.weight_coverage,
            "lighting_match":   scene_meta.weight_lighting,
            "blend_edge":       scene_meta.weight_blend_edge,
        }
        total_weight = 0.0
        composite    = 0.0
        for a in attrs:
            w = weight_map.get(a.name, 0.0)
            composite    += a.score * w
            total_weight += w

        if total_weight > 0:
            composite /= total_weight   # normalise (in case some attrs are missing)

        base_result.attributes      = attrs
        base_result.composite_score = round(composite, 4)
        base_result.passed          = composite >= scene_meta.passing_score
        return base_result

    # ─── Individual attribute evaluators ──────────────────────────────────────

    def _eval_face_detected(self, landmarks) -> AttributeScore:
        score  = 1.0 if landmarks else 0.0
        return AttributeScore(
            name="face_detected",
            score=score,
            raw_value=landmarks is not None,
            expected="True",
            passed=landmarks is not None,
            note="MediaPipe FaceMesh detection",
        )

    def _eval_gaze(
        self, landmarks, img_shape: tuple, meta: SceneMeta
    ) -> AttributeScore:
        """
        Estimate gaze direction from iris vs eye centre offset.

        Method:
          - Compute left/right iris centroid (MediaPipe refine_landmarks=True)
          - Compute left/right eye corner midpoint (approximate eye centre)
          - Horizontal offset ratio → classify gaze

        Returns:
          "camera"  — iris near eye centre (looking forward)
          "subject" — iris shifted left/right (looking at another character)
          "ambient" — iris shifted but less strongly (soft gaze)
        """
        H, W = img_shape[:2]

        def pt(idx):
            l = landmarks[idx]
            return np.array([l.x * W, l.y * H])

        # Iris centroids
        left_iris  = np.mean([pt(i) for i in _LEFT_IRIS],  axis=0)
        right_iris = np.mean([pt(i) for i in _RIGHT_IRIS], axis=0)

        # Eye corner midpoints (approximate eye centre)
        left_eye_ctr  = (pt(_LEFT_EYE[0])  + pt(_LEFT_EYE[3]))  / 2
        right_eye_ctr = (pt(_RIGHT_EYE[0]) + pt(_RIGHT_EYE[3])) / 2

        # Eye width (for normalisation)
        left_eye_w  = abs(pt(_LEFT_EYE[0])[0]  - pt(_LEFT_EYE[3])[0])  + 1e-6
        right_eye_w = abs(pt(_RIGHT_EYE[0])[0] - pt(_RIGHT_EYE[3])[0]) + 1e-6

        left_offset  = abs(left_iris[0]  - left_eye_ctr[0])  / left_eye_w
        right_offset = abs(right_iris[0] - right_eye_ctr[0]) / right_eye_w
        avg_offset   = (left_offset + right_offset) / 2

        # Thresholds calibrated from MediaPipe observations:
        # < 0.12 → camera,  0.12–0.25 → ambient,  > 0.25 → subject
        if avg_offset < 0.12:
            detected = "camera"
        elif avg_offset < 0.25:
            detected = "ambient"
        else:
            detected = "subject"

        expected = meta.gaze_direction

        # Score: exact match = 1.0, adjacent categories = 0.5, opposite = 0.0
        _adjacent = {
            ("camera", "ambient"), ("ambient", "camera"),
            ("ambient", "subject"), ("subject", "ambient"),
        }
        if detected == expected:
            score = 1.0
        elif (detected, expected) in _adjacent or (expected, detected) in _adjacent:
            score = 0.5
        else:
            score = 0.0

        return AttributeScore(
            name="gaze_direction",
            score=score,
            raw_value=detected,
            expected=expected,
            passed=score >= 0.5,
            note=f"iris_offset={avg_offset:.3f}",
        )

    def _eval_expression(
        self, landmarks, img_shape: tuple, meta: SceneMeta
    ) -> AttributeScore:
        """
        Classify expression from mouth curvature + eye aspect ratio.

        Mouth curvature:
          Positive (corners up) → smile
          Flat                  → neutral
          Wide + slight open    → wonder

        Eye aspect ratio (EAR):
          High (wide open) → wonder / alert
          Normal           → smile or neutral
        """
        H, W = img_shape[:2]
        def pt(idx):
            l = landmarks[idx]
            return np.array([l.x * W, l.y * H])

        mouth_l = pt(_MOUTH_L)
        mouth_r = pt(_MOUTH_R)
        mouth_t = pt(_MOUTH_TOP)
        mouth_b = pt(_MOUTH_BOT)

        # Corner elevation relative to mouth midline
        mouth_mid_y = (mouth_t[1] + mouth_b[1]) / 2
        corner_elev = mouth_mid_y - (mouth_l[1] + mouth_r[1]) / 2   # positive = corners up
        mouth_w     = abs(mouth_r[0] - mouth_l[0]) + 1e-6
        corner_ratio = corner_elev / mouth_w

        # Mouth openness
        mouth_open_ratio = abs(mouth_b[1] - mouth_t[1]) / mouth_w

        # EAR (left eye)
        p1 = pt(_LEFT_EYE[1]);  p2 = pt(_LEFT_EYE[2])
        p3 = pt(_LEFT_EYE[3]);  p4 = pt(_LEFT_EYE[4])
        p5 = pt(_LEFT_EYE[5]);  p6 = pt(_LEFT_EYE[0])
        ear = (np.linalg.norm(p1-p5) + np.linalg.norm(p2-p4)) / (2 * np.linalg.norm(p3-p6) + 1e-6)

        # Classify
        if corner_ratio > 0.04:
            detected = "smile"
        elif ear > 0.30 and mouth_open_ratio > 0.15:
            detected = "wonder"
        else:
            detected = "neutral"

        expected = meta.expression
        score    = 1.0 if detected == expected else (0.4 if detected != "neutral" else 0.2)

        return AttributeScore(
            name="expression",
            score=score,
            raw_value=detected,
            expected=expected,
            passed=score >= 0.5,
            note=f"corner_ratio={corner_ratio:.3f} ear={ear:.3f}",
        )

    def _eval_head_tilt(
        self, landmarks, img_shape: tuple, meta: SceneMeta
    ) -> AttributeScore:
        """
        Compute head roll angle from eye corner landmarks.
        Roll = atan2(dy, dx) between left and right eye corners.
        """
        H, W = img_shape[:2]
        def pt(idx):
            l = landmarks[idx]
            return np.array([l.x * W, l.y * H])

        left_corner  = pt(_LEFT_EYE[0])
        right_corner = pt(_RIGHT_EYE[3])

        dx   = right_corner[0] - left_corner[0]
        dy   = right_corner[1] - left_corner[1]
        tilt = abs(math.degrees(math.atan2(dy, dx)))

        max_tilt = meta.head_tilt_deg_max
        if tilt <= max_tilt:
            score = 1.0
        elif tilt <= max_tilt * 1.5:
            score = 0.5
        else:
            score = max(0.0, 1.0 - (tilt - max_tilt) / max_tilt)

        return AttributeScore(
            name="head_tilt",
            score=score,
            raw_value=round(tilt, 2),
            expected=f"≤{max_tilt}°",
            passed=tilt <= max_tilt,
            note=f"roll_deg={tilt:.1f}°",
        )

    def _eval_face_coverage(
        self, face_roi_bgr: np.ndarray, fw: int, fh: int, meta: SceneMeta
    ) -> AttributeScore:
        """
        Measure what fraction of the face_config bounding box contains
        skin-tone pixels (detected face).

        Uses HSV skin tone segmentation.
        Score degrades if coverage is too low (face too small) or too high
        (face overflows bounding box).
        """
        if face_roi_bgr.size == 0:
            return AttributeScore("face_coverage", 0.0, 0.0, "0.55–1.10", False, "empty ROI")

        hsv = cv2.cvtColor(face_roi_bgr, cv2.COLOR_BGR2HSV)
        # Broad skin tone range in HSV
        lower = np.array([0,   20, 70], dtype=np.uint8)
        upper = np.array([25, 255, 255], dtype=np.uint8)
        mask  = cv2.inRange(hsv, lower, upper)
        coverage = mask.sum() / (255.0 * fw * fh)

        lo = meta.face_coverage_min
        hi = meta.face_coverage_max

        if lo <= coverage <= hi:
            score = 1.0
        elif coverage < lo:
            score = max(0.0, coverage / lo)
        else:
            score = max(0.0, 1.0 - (coverage - hi) / hi)

        return AttributeScore(
            name="face_coverage",
            score=score,
            raw_value=round(coverage, 3),
            expected=f"{lo:.2f}–{hi:.2f}",
            passed=lo <= coverage <= hi,
            note=f"skin_coverage={coverage:.3f}",
        )

    def _eval_lighting_match(
        self, img_bgr: np.ndarray,
        fx: int, fy: int, fw: int, fh: int,
        meta: SceneMeta,
    ) -> AttributeScore:
        """
        Compare LAB colour statistics of the face ROI vs the surrounding
        template area (a border ring around the face box).

        High similarity → face lighting blends with scene.
        Uses Bhattacharyya distance on LAB histograms.
        """
        H, W = img_bgr.shape[:2]

        face_roi = img_bgr[fy:fy+fh, fx:fx+fw]
        if face_roi.size == 0:
            return AttributeScore("lighting_match", 0.0, 0.0, f"≥{meta.lighting_match_threshold}", False, "empty ROI")

        # Surrounding ring (2× face box, clamped to image)
        margin  = max(fw, fh) // 4
        sx = max(0, fx-margin);  sy = max(0, fy-margin)
        sx2= min(W, fx+fw+margin); sy2= min(H, fy+fh+margin)
        surround_roi = img_bgr[sy:sy2, sx:sx2]

        # Create mask: surround minus face box
        surround_mask = np.ones((sy2-sy, sx2-sx), dtype=np.uint8) * 255
        rx = fx - sx;  ry = fy - sy
        surround_mask[ry:ry+fh, rx:rx+fw] = 0

        face_lab     = cv2.cvtColor(face_roi,     cv2.COLOR_BGR2LAB)
        surround_lab = cv2.cvtColor(surround_roi, cv2.COLOR_BGR2LAB)

        # Compare L-channel (luminance) histograms
        hist_f = cv2.calcHist([face_lab],     [0], None, [64], [0, 256])
        hist_s = cv2.calcHist([surround_lab], [0], surround_mask, [64], [0, 256])
        cv2.normalize(hist_f, hist_f)
        cv2.normalize(hist_s, hist_s)

        similarity = 1.0 - cv2.compareHist(hist_f, hist_s, cv2.HISTCMP_BHATTACHARYYA)
        similarity = max(0.0, similarity)

        threshold = meta.lighting_match_threshold
        score = min(1.0, similarity / threshold) if threshold > 0 else 1.0

        return AttributeScore(
            name="lighting_match",
            score=score,
            raw_value=round(similarity, 3),
            expected=f"≥{threshold}",
            passed=similarity >= threshold,
            note=f"bhattacharyya_sim={similarity:.3f}",
        )

    def _eval_blend_edge(
        self, img_bgr: np.ndarray,
        fx: int, fy: int, fw: int, fh: int,
        meta: SceneMeta,
    ) -> AttributeScore:
        """
        Measure gradient smoothness at the face boundary.

        Method:
          - Extract a thin ring (8px) around the face bbox
          - Compute Sobel gradient magnitude in that ring
          - Normalise by the gradient of the overall image
          - Low ratio = smooth transition = good blend

        Lower variance ratio is better (inverse scoring).
        """
        H, W = img_bgr.shape[:2]
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)

        ring_size = 8
        x1 = max(0, fx-ring_size);  y1 = max(0, fy-ring_size)
        x2 = min(W, fx+fw+ring_size); y2 = min(H, fy+fh+ring_size)

        outer = gray[y1:y2, x1:x2]
        # Mask the inner face region, keep only the ring
        inner_mask = np.zeros_like(outer, dtype=bool)
        rix = fx - x1;  riy = fy - y1
        inner_mask[riy:riy+fh, rix:rix+fw] = True

        sobelx = cv2.Sobel(outer, cv2.CV_32F, 1, 0, ksize=3)
        sobely = cv2.Sobel(outer, cv2.CV_32F, 0, 1, ksize=3)
        mag    = np.sqrt(sobelx**2 + sobely**2)

        ring_pixels = mag[~inner_mask]
        if ring_pixels.size == 0:
            return AttributeScore("blend_edge", 0.5, 0.0, f"≤{meta.blend_edge_quality_min}", True, "ring empty")

        # Normalise by median global gradient
        global_grad = np.median(mag) + 1e-6
        ratio = ring_pixels.mean() / global_grad

        # Lower ratio = smoother blend = better
        max_ratio = meta.blend_edge_quality_min
        score = max(0.0, min(1.0, 1.0 - (ratio - max_ratio) / max_ratio)) if ratio > max_ratio else 1.0

        return AttributeScore(
            name="blend_edge",
            score=score,
            raw_value=round(ratio, 4),
            expected=f"≤{max_ratio}",
            passed=ratio <= max_ratio,
            note=f"edge_ratio={ratio:.4f}",
        )

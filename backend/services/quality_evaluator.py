"""
Face Blend Quality Evaluator

Computes objective image-quality metrics for each blended page.
Generates a structured JSON report designed to be pasted into Claude
for automated pipeline parameter tuning.

Metrics
───────
face_position   — MediaPipe face detect → IoU vs target bbox        (weight 20 %)
edge_quality    — Laplacian variance at face boundary                (weight 25 %)
lighting_delta  — LAB L-channel difference: face vs background       (weight 20 %)
colour_harmony  — Histogram correlation: face vs adjacent area       (weight 20 %)
skin_blend      — RGB mean-delta at inner/outer face boundary ring   (weight 15 %)

Overall = weighted average → graded A/B/C/D
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np

logger = logging.getLogger(__name__)

_mp_face_mesh = mp.solutions.face_mesh

_WEIGHTS: Dict[str, float] = {
    "face_position": 0.20,
    "edge_quality":  0.25,
    "lighting":      0.20,
    "colour_harmony": 0.20,
    "skin_blend":    0.15,
}


class QualityEvaluator:
    """Evaluates a single blended image and aggregates results into a report."""

    def __init__(self) -> None:
        self._mesh: Optional[object] = None

    # ── Public ────────────────────────────────────────────────────────────────

    def evaluate_image(
        self,
        image_path: str,
        face_config: Dict[str, int],
        page_number: int,
        expression: str = "neutral",
    ) -> Dict[str, Any]:
        """Return a single-page evaluation dict."""
        img = cv2.imread(image_path)
        if img is None:
            return {"error": f"Cannot read: {image_path}",
                    "page_number": page_number, "metrics": {}}

        x, y, w, h = (
            face_config["x"], face_config["y"],
            face_config["w"], face_config["h"],
        )
        metrics     = {}
        issues      = []
        suggestions = {}

        # 1 ── Face position
        pos, _ = self._face_position(img, x, y, w, h)
        metrics["face_position_score"] = round(pos, 3)
        if pos < 0.50:
            issues.append("Face significantly misaligned or not detected")
            suggestions["face_scale_factor"] = 0.90
        elif pos < 0.70:
            issues.append("Minor face position offset")
            suggestions["face_scale_factor"] = 0.94

        # 2 ── Edge quality
        eq, lap = self._edge_quality(img, x, y, w, h)
        metrics["edge_quality_score"]      = round(eq, 3)
        metrics["edge_laplacian_variance"] = round(lap, 2)
        metrics["edge_quality_label"]      = (
            "excellent" if eq > 0.80 else
            "good"      if eq > 0.60 else
            "fair"      if eq > 0.40 else "poor"
        )
        if eq < 0.40:
            issues.append("Visible edge artefacts at face boundary")
            suggestions["gaussian_blur_sigma"]  = 22
            suggestions["seamless_clone_mode"]  = "MIXED_CLONE"
        elif eq < 0.60:
            issues.append("Minor edge artefacts")
            suggestions["gaussian_blur_sigma"]  = 17

        # 3 ── Lighting
        ls, ld = self._lighting_consistency(img, x, y, w, h)
        metrics["lighting_consistency_score"] = round(ls, 3)
        metrics["lighting_delta_lab_L"]       = round(ld, 2)
        if ls < 0.60:
            issues.append(f"Lighting mismatch (ΔL={ld:.1f} LAB)")
            suggestions["colour_match_strength"] = 0.80
        elif ls < 0.75:
            suggestions["colour_match_strength"] = 0.65

        # 4 ── Colour harmony
        ch, cc = self._colour_harmony(img, x, y, w, h)
        metrics["colour_harmony_score"]   = round(ch, 3)
        metrics["histogram_correlation"]  = round(cc, 3)
        if ch < 0.55:
            issues.append("Poor colour harmony — face looks pasted in")
            suggestions["colour_match_channels"] = "all"
        elif ch < 0.70:
            issues.append("Moderate colour harmony issue")

        # 5 ── Skin blend at boundary
        sb, sd = self._skin_blend(img, x, y, w, h)
        metrics["skin_blend_score"]     = round(sb, 3)
        metrics["skin_tone_delta_rgb"]  = round(sd, 2)
        if sb < 0.55:
            issues.append("Abrupt skin-tone change at face edge")
            suggestions["feather_radius"] = 35
        elif sb < 0.70:
            suggestions["feather_radius"] = 25
        else:
            suggestions.setdefault("feather_radius", 15)

        # Overall
        overall = (
            _WEIGHTS["face_position"]  * metrics["face_position_score"]
            + _WEIGHTS["edge_quality"] * metrics["edge_quality_score"]
            + _WEIGHTS["lighting"]     * metrics["lighting_consistency_score"]
            + _WEIGHTS["colour_harmony"] * metrics["colour_harmony_score"]
            + _WEIGHTS["skin_blend"]   * metrics["skin_blend_score"]
        )
        metrics["overall_score"] = round(overall, 3)
        metrics["grade"] = (
            "A" if overall > 0.85 else
            "B" if overall > 0.70 else
            "C" if overall > 0.55 else "D"
        )

        return {
            "page_number": page_number,
            "image_path":  image_path,
            "expression":  expression,
            "metrics":     metrics,
            "issues":      issues,
            "suggestions": suggestions,
        }

    def generate_report(
        self,
        story_id: str,
        face_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Build the full quality report.

        face_results  — list of {face_index, pages: [eval_result]}
        """
        all_scores: List[float] = []
        page_map:   Dict[int, Dict] = {}

        for fd in face_results:
            fi = fd["face_index"]
            for ev in fd.get("pages", []):
                s = ev.get("metrics", {}).get("overall_score")
                if s is not None:
                    all_scores.append(s)
                pn = ev["page_number"]
                if pn not in page_map:
                    page_map[pn] = {
                        "page_number": pn,
                        "expression":  ev.get("expression", "neutral"),
                        "by_face":     [],
                    }
                page_map[pn]["by_face"].append({
                    "face_index":  fi,
                    "image_url":   ev.get("image_url", ""),
                    "metrics":     ev.get("metrics", {}),
                    "issues":      ev.get("issues", []),
                    "suggestions": ev.get("suggestions", {}),
                })

        # Aggregate suggestions (mean for numerics, mode for strings)
        raw_sugg: Dict[str, list] = {}
        for fd in face_results:
            for ev in fd.get("pages", []):
                for k, v in ev.get("suggestions", {}).items():
                    raw_sugg.setdefault(k, []).append(v)

        tuning: Dict[str, Any] = {}
        for k, vals in raw_sugg.items():
            if vals and isinstance(vals[0], (int, float)):
                tuning[k] = round(sum(vals) / len(vals), 3)
            elif vals:
                tuning[k] = Counter(vals).most_common(1)[0][0]

        avg = float(np.mean(all_scores)) if all_scores else 0.0

        return {
            "report_meta": {
                "story_id":        story_id,
                "generated_at":    datetime.now(timezone.utc).isoformat(),
                "test_faces_count": len(face_results),
                "pages_evaluated": len(page_map),
            },
            "aggregate": {
                "mean_overall_score": round(avg, 3),
                "grade": (
                    "A" if avg > 0.85 else
                    "B" if avg > 0.70 else
                    "C" if avg > 0.55 else "D"
                ),
                "min_score": round(min(all_scores), 3) if all_scores else 0.0,
                "max_score": round(max(all_scores), 3) if all_scores else 0.0,
            },
            "pages": list(page_map.values()),
            "tuning_recommendations": {
                "face_pipeline_service": tuning,
                "notes": [
                    "Paste the claude_tuning_prompt below into Claude to get "
                    "specific code-level suggestions for face_pipeline_service.py.",
                    "Parameter keys map directly to the constants / arguments in "
                    "backend/services/face_pipeline_service.py.",
                ],
            },
            "claude_tuning_prompt": (
                f"StoryMe face-blend quality report for story '{story_id}'. "
                f"Mean score: {avg:.2f}/1.00. "
                f"Current tunable parameters: {json.dumps(tuning)}. "
                f"Please analyse the per-page metrics in this report and "
                f"suggest specific code changes to improve all scores above 0.80. "
                f"Focus on the face_pipeline_service.py methods: "
                f"_apply_pose_warp, _match_colour_and_lighting, "
                f"_blend_face_into_template (seamlessClone flags, mask size, "
                f"Gaussian sigma), and text overlay positioning."
            ),
        }

    # ── Individual metrics ────────────────────────────────────────────────────

    def _get_mesh(self):
        if self._mesh is None:
            self._mesh = _mp_face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                min_detection_confidence=0.3,
            )
        return self._mesh

    def _face_position(
        self, img: np.ndarray, x: int, y: int, w: int, h: int
    ) -> Tuple[float, Optional[Tuple[int,int,int,int]]]:
        """IoU between detected face hull-bbox and target bbox."""
        mesh = self._get_mesh()
        res  = mesh.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        if not res.multi_face_landmarks:
            return 0.0, None

        ih, iw = img.shape[:2]
        pts = np.array(
            [(int(l.x * iw), int(l.y * ih))
             for l in res.multi_face_landmarks[0].landmark],
            dtype=np.int32,
        )
        dx, dy, dw, dh = cv2.boundingRect(cv2.convexHull(pts))

        ix1, iy1 = max(x, dx),    max(y, dy)
        ix2, iy2 = min(x+w, dx+dw), min(y+h, dy+dh)
        inter = max(0, ix2-ix1) * max(0, iy2-iy1)
        union = w*h + dw*dh - inter
        iou   = inter / union if union > 0 else 0.0
        return float(iou), (dx, dy, dw, dh)

    def _edge_quality(
        self, img: np.ndarray, x: int, y: int, w: int, h: int
    ) -> Tuple[float, float]:
        """
        Lower Laplacian mean at the face-boundary ring → better blend.
        Score mapped to [0,1] via exp(-mean/30).
        """
        ax = max(1, int(w * 0.44))
        ay = max(1, int(h * 0.48))
        cx, cy = x + w // 2, y + h // 2

        mask  = np.zeros(img.shape[:2], dtype=np.uint8)
        cv2.ellipse(mask, (cx, cy), (ax, ay), 0, 0, 360, 255, -1)
        outer = cv2.dilate(mask, np.ones((21, 21), np.uint8))
        ring  = cv2.bitwise_and(outer, cv2.bitwise_not(mask))

        lap_mean = float(np.abs(
            cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F)
        )[ring > 0].mean()) if ring.any() else 0.0

        score = float(np.exp(-lap_mean / 30.0))
        return score, lap_mean

    def _lighting_consistency(
        self, img: np.ndarray, x: int, y: int, w: int, h: int
    ) -> Tuple[float, float]:
        """Compare LAB L-channel of face ROI vs surrounding area."""
        ih, iw = img.shape[:2]
        f = img[max(0,y):min(ih,y+h), max(0,x):min(iw,x+w)]

        bx1 = max(0, x - int(0.3*w));  bx2 = min(iw, x+w + int(0.3*w))
        by1 = max(0, y - int(0.3*h));  by2 = min(ih, y+h + int(0.3*h))
        b   = img[by1:by2, bx1:bx2]

        if f.size == 0 or b.size == 0:
            return 0.5, 0.0

        delta = abs(
            float(cv2.cvtColor(f, cv2.COLOR_BGR2LAB)[:,:,0].mean())
            - float(cv2.cvtColor(b, cv2.COLOR_BGR2LAB)[:,:,0].mean())
        )
        return float(np.exp(-delta / 25.0)), delta

    def _colour_harmony(
        self, img: np.ndarray, x: int, y: int, w: int, h: int
    ) -> Tuple[float, float]:
        """Histogram correlation between face and adjacent area."""
        ih, iw = img.shape[:2]
        face = img[max(0,y):min(ih,y+h), max(0,x):min(iw,x+w)]
        pad  = 60
        adj  = img[max(0,y-pad):min(ih,y+h+pad), max(0,x-pad):min(iw,x+w+pad)]

        if face.size == 0 or adj.size == 0:
            return 0.5, 0.5

        total = 0.0
        for ch in range(3):
            hf = cv2.calcHist([face], [ch], None, [64], [0, 256])
            ha = cv2.calcHist([adj],  [ch], None, [64], [0, 256])
            cv2.normalize(hf, hf)
            cv2.normalize(ha, ha)
            total += cv2.compareHist(hf, ha, cv2.HISTCMP_CORREL)

        corr  = total / 3.0
        score = (corr + 1.0) / 2.0
        return float(score), float(corr)

    def _skin_blend(
        self, img: np.ndarray, x: int, y: int, w: int, h: int
    ) -> Tuple[float, float]:
        """Mean RGB difference at inner/outer face boundary ring."""
        ax = max(1, int(w * 0.44))
        ay = max(1, int(h * 0.48))
        cx, cy = x + w // 2, y + h // 2

        inner = np.zeros(img.shape[:2], dtype=np.uint8)
        cv2.ellipse(inner, (cx, cy), (ax, ay), 0, 0, 360, 255, -1)
        eroded = cv2.erode(inner, np.ones((12, 12), np.uint8))
        inner_ring = cv2.bitwise_and(inner, cv2.bitwise_not(eroded))

        outer_ring = cv2.bitwise_and(
            cv2.dilate(inner, np.ones((12, 12), np.uint8)),
            cv2.bitwise_not(inner),
        )

        ip = img[inner_ring > 0]
        op = img[outer_ring > 0]

        if ip.size == 0 or op.size == 0:
            return 0.5, 0.0

        delta = float(np.linalg.norm(
            ip.mean(axis=0).astype(float) - op.mean(axis=0).astype(float)
        ))
        return float(np.exp(-delta / 40.0)), delta


# Singleton
quality_evaluator = QualityEvaluator()

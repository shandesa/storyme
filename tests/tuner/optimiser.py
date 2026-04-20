"""
tests/tuner/optimiser.py
=========================
Coordinate descent optimiser for face_blend parameters.

For each tunable parameter, tries every candidate value in its search range,
blends all 15 sample images with that value, evaluates the results, and keeps
the value that maximises the mean composite score across all samples.

Repeats for max_rounds or until no parameter improves by more than min_delta.
"""

from __future__ import annotations
import copy
import json
import logging
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.tuner.tuner_params import PARAMS, PARAM_MAP, update_current, current_values
from tests.tuner.blend_runner import run_blend_with_params
from tests.evaluator.face_evaluator import FaceEvaluator
from tests.evaluator.scene_metadata import SCENE_METADATA
from backend.services.story_service import FACE_COORDS

logger = logging.getLogger(__name__)


def score_blends(
    blend_paths: list[Optional[str]],
    scene_file:  str,
    evaluator:   FaceEvaluator,
) -> dict:
    """
    Evaluate all blended images and return mean per-attribute scores.

    Args:
        blend_paths: Paths to blended PNGs (None = blend failed for that sample)
        scene_file:  e.g. "scene_01.png"
        evaluator:   FaceEvaluator instance

    Returns:
        {
            "composite": float,           # mean composite score
            "face_detected": float,       # mean per-attribute
            "gaze_direction": float,
            ... etc
            "n_evaluated": int,           # how many samples scored (not None)
        }
    """
    meta      = SCENE_METADATA.get(scene_file)
    face_cfg  = FACE_COORDS.get(scene_file)
    if meta is None or face_cfg is None:
        return {"composite": 0.0, "n_evaluated": 0}

    scores: list[dict] = []
    for path in blend_paths:
        if path is None:
            continue
        result = evaluator.evaluate(
            image_path=path,
            scene_meta=meta,
            face_config=face_cfg,
        )
        attr_scores = {a.name: a.score for a in result.attributes}
        attr_scores["composite"] = result.composite_score
        scores.append(attr_scores)

    if not scores:
        return {"composite": 0.0, "n_evaluated": 0}

    # Mean across all samples
    all_keys = set(k for s in scores for k in s)
    mean     = {k: sum(s.get(k, 0.0) for s in scores) / len(scores) for k in all_keys}
    mean["n_evaluated"] = len(scores)
    return mean


def run_optimisation(
    sample_paths:   list[str],
    template_path:  str,
    reference_path: str,
    scene_file:     str,
    threshold:      float = 0.80,
    max_rounds:     int   = 10,
    min_delta:      float = 0.005,
    results_dir:    Path  = None,
) -> dict:
    """
    Run coordinate descent optimisation over all tunable parameters.

    Args:
        sample_paths:   Paths to 15 user face images.
        template_path:  Absolute path to scene template PNG.
        reference_path: Absolute path to scene reference PNG.
        scene_file:     e.g. "scene_01.png"
        threshold:      Target composite score (default 0.80).
        max_rounds:     Max full passes over all parameters.
        min_delta:      Stop early if best improvement in a round < this.
        results_dir:    Where to save trial logs.

    Returns:
        {
            "winning_params": dict,       # best parameter values found
            "baseline_score": float,      # score before any tuning
            "final_score": float,         # score after tuning
            "improvement": float,         # final - baseline
            "trials": list[dict],         # full log of every trial
            "rounds_completed": int,
        }
    """
    face_cfg    = FACE_COORDS.get(scene_file)
    if face_cfg is None:
        raise ValueError(f"No face_config for {scene_file}")

    results_dir = results_dir or Path("tests/tuner/results")
    results_dir.mkdir(parents=True, exist_ok=True)

    evaluator   = FaceEvaluator()
    trials:     list[dict] = []
    current     = current_values()   # start from current params

    # ── Baseline ──────────────────────────────────────────────────────────────
    logger.info("─── BASELINE: scoring with current params ───")
    tmp        = Path(tempfile.mkdtemp(prefix="tuner_base_"))
    base_paths = run_blend_with_params(
        sample_paths, template_path, reference_path, face_cfg, current, tmp
    )
    base_scores = score_blends(base_paths, scene_file, evaluator)
    baseline    = base_scores.get("composite", 0.0)
    logger.info("Baseline composite: %.4f  (n=%d)", baseline, base_scores.get("n_evaluated", 0))
    _log_scores("BASELINE", base_scores)
    shutil.rmtree(tmp, ignore_errors=True)

    trials.append({"round": 0, "param": "baseline", "value": None,
                   "scores": base_scores})

    best_params = copy.deepcopy(current)
    best_score  = baseline

    # ── Coordinate descent rounds ─────────────────────────────────────────────
    for rnd in range(1, max_rounds + 1):
        round_best_delta = 0.0
        logger.info("═══ Round %d / %d ═══", rnd, max_rounds)

        for param in PARAMS:
            name        = param.name
            candidates  = param.search

            param_best_val   = best_params.get(name, param.current)
            param_best_score = best_score

            logger.info("  Tuning: %-25s  (affects: %s)", name, ", ".join(param.affects))

            for candidate in candidates:
                trial_params = copy.deepcopy(best_params)
                trial_params[name] = candidate

                tmp = Path(tempfile.mkdtemp(prefix=f"tuner_{name}_"))
                out = run_blend_with_params(
                    sample_paths, template_path, reference_path, face_cfg,
                    trial_params, tmp,
                )
                scores = score_blends(out, scene_file, evaluator)
                score  = scores.get("composite", 0.0)
                shutil.rmtree(tmp, ignore_errors=True)

                logger.info(
                    "    %s=%-8s  composite=%.4f  n=%d",
                    name, str(candidate), score, scores.get("n_evaluated", 0),
                )
                trials.append({
                    "round": rnd, "param": name, "value": candidate, "scores": scores,
                })

                if score > param_best_score:
                    param_best_score = score
                    param_best_val   = candidate

            if param_best_score > best_score:
                delta       = param_best_score - best_score
                best_score  = param_best_score
                best_params[name] = param_best_val
                update_current(name, param_best_val)
                round_best_delta = max(round_best_delta, delta)
                logger.info(
                    "  ✓ %s: %s → %s  (+%.4f composite)",
                    name, param.current, param_best_val, delta,
                )
            else:
                logger.info("  — %s: no improvement (keeping %s)", name, param.current)

        logger.info(
            "Round %d complete.  best_score=%.4f  round_delta=%.4f",
            rnd, best_score, round_best_delta,
        )

        # Early stop if composite already passes threshold
        if best_score >= threshold:
            logger.info("✅ Target threshold %.2f reached — stopping early", threshold)
            break

        # Early stop if round produced negligible improvement
        if round_best_delta < min_delta and rnd > 1:
            logger.info(
                "No meaningful improvement this round (%.4f < %.4f) — stopping",
                round_best_delta, min_delta,
            )
            break

    improvement = best_score - baseline
    result      = {
        "scene_file":       scene_file,
        "baseline_score":   round(baseline, 4),
        "final_score":      round(best_score, 4),
        "improvement":      round(improvement, 4),
        "threshold":        threshold,
        "threshold_met":    best_score >= threshold,
        "rounds_completed": rnd,
        "winning_params":   best_params,
        "trials":           trials,
        "timestamp":        datetime.now(timezone.utc).isoformat(),
    }

    # Save result
    ts          = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    result_path = results_dir / f"tuning_{scene_file.replace('.png','')}_{ts}.json"
    result_path.write_text(json.dumps(result, indent=2))

    # Save winning params separately for apply_params.py
    winning_path = results_dir / "winning_params.json"
    winning_path.write_text(json.dumps(best_params, indent=2))

    logger.info("═" * 60)
    logger.info("TUNING COMPLETE  scene=%s", scene_file)
    logger.info("  Baseline:    %.4f", baseline)
    logger.info("  Final:       %.4f", best_score)
    logger.info("  Improvement: %+.4f", improvement)
    logger.info("  Threshold:   %.2f  %s", threshold, "✅ MET" if result["threshold_met"] else "❌ NOT MET")
    logger.info("  Results:     %s", result_path)

    return result


def _log_scores(label: str, scores: dict) -> None:
    attrs = [k for k in scores if k not in ("composite", "n_evaluated")]
    for a in sorted(attrs):
        v = scores.get(a, 0.0)
        bar   = "█" * int(v * 20)
        space = "░" * (20 - len(bar))
        logger.info("  %-22s  %s%s  %.3f", a, bar, space, v)

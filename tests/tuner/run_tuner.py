"""
tests/tuner/run_tuner.py
=========================
CLI entry point for the face_blend parameter optimiser.

Drop your 15 sample user face images in tests/tuner/samples/ then run:

    # Dry-run — score baseline only, no changes:
    python tests/tuner/run_tuner.py --scene scene_01.png --dry-run

    # Full optimisation, target 0.80 composite:
    python tests/tuner/run_tuner.py --scene scene_01.png

    # Optimise all 10 scenes sequentially:
    python tests/tuner/run_tuner.py --all-scenes

    # After reviewing results, apply winning params:
    python tests/tuner/apply_params.py --apply

Environment:
    No Azure or MongoDB needed — runs entirely locally.
    Requires: opencv-python-headless, mediapipe, numpy (same as backend)
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.tuner.optimiser import run_optimisation
from tests.tuner.tuner_params import PARAMS
from backend.services.story_service import FACE_COORDS, SCENE_FILES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tuner")

SAMPLES_DIR = Path(__file__).parent / "samples"
RESULTS_DIR = Path(__file__).parent / "results"

# Default template/reference paths — from bundled backend assets
TEMPLATES_BASE   = REPO_ROOT / "backend" / "templates" / "stories" / "forest_of_smiles" / "neutral"
TEMPLATE_DIR     = TEMPLATES_BASE / "templates"
REFERENCE_DIR    = TEMPLATES_BASE / "references"


def get_sample_paths() -> list[str]:
    if not SAMPLES_DIR.exists():
        SAMPLES_DIR.mkdir(parents=True)
        logger.error(
            "samples/ directory was empty — created: %s\n"
            "Drop 15 user face JPG/PNG images there and re-run.",
            SAMPLES_DIR,
        )
        sys.exit(1)

    paths = sorted([
        str(f) for f in SAMPLES_DIR.iterdir()
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ])

    if not paths:
        logger.error(
            "No images found in %s\n"
            "Add at least 3 JPG/PNG user face images and re-run.",
            SAMPLES_DIR,
        )
        sys.exit(1)

    logger.info("Samples: found %d images in %s", len(paths), SAMPLES_DIR)
    if len(paths) < 5:
        logger.warning(
            "Only %d samples found — 15 recommended for reliable optimisation.", len(paths)
        )
    return paths


def run_for_scene(
    scene_file:   str,
    sample_paths: list[str],
    threshold:    float,
    max_rounds:   int,
    dry_run:      bool,
) -> dict:
    template_path  = str(TEMPLATE_DIR  / scene_file)
    reference_path = str(REFERENCE_DIR / scene_file)

    if not Path(template_path).exists():
        logger.error("Template not found: %s", template_path)
        return {}
    if not Path(reference_path).exists():
        logger.error("Reference not found: %s", reference_path)
        return {}

    logger.info("═" * 60)
    logger.info("Tuning: %s  (threshold=%.2f  max_rounds=%d)", scene_file, threshold, max_rounds)
    logger.info("  Template:  %s", template_path)
    logger.info("  Reference: %s", reference_path)
    logger.info("  Samples:   %d images", len(sample_paths))
    logger.info("  Params:    %d tunable", len(PARAMS))

    if dry_run:
        # Baseline only — no optimisation
        from tests.tuner.blend_runner import run_blend_with_params
        from tests.tuner.optimiser import score_blends
        from tests.evaluator.face_evaluator import FaceEvaluator
        from tests.tuner.tuner_params import current_values
        import shutil, tempfile

        logger.info("DRY-RUN: scoring baseline only")
        face_cfg = FACE_COORDS.get(scene_file)
        tmp      = Path(tempfile.mkdtemp(prefix="tuner_dry_"))
        paths    = run_blend_with_params(
            sample_paths, template_path, reference_path, face_cfg, current_values(), tmp
        )
        scores   = score_blends(paths, scene_file, FaceEvaluator())
        shutil.rmtree(tmp, ignore_errors=True)

        logger.info("Baseline scores for %s:", scene_file)
        for k, v in sorted(scores.items()):
            if k not in ("n_evaluated",):
                status = "✅" if v >= threshold else "❌"
                logger.info("  %s %-22s  %.4f", status, k, v)

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"baseline_{scene_file.replace('.png','')}.json"
        out.write_text(json.dumps({"scene": scene_file, "scores": scores}, indent=2))
        logger.info("Baseline saved: %s", out)
        return scores

    return run_optimisation(
        sample_paths=sample_paths,
        template_path=template_path,
        reference_path=reference_path,
        scene_file=scene_file,
        threshold=threshold,
        max_rounds=max_rounds,
        results_dir=RESULTS_DIR,
    )


def main():
    p = argparse.ArgumentParser(
        description="Auto-tune face_blend parameters using 15 sample images",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  1. Drop 15 user face JPG/PNG images in tests/tuner/samples/
  2. Run: python tests/tuner/run_tuner.py --scene scene_01.png
  3. Review: tests/tuner/results/tuning_scene_01_*.json
  4. Apply: python tests/tuner/apply_params.py --apply

Examples:
  # Baseline only (no changes):
  python tests/tuner/run_tuner.py --scene scene_01.png --dry-run

  # Optimise one scene, target 0.80:
  python tests/tuner/run_tuner.py --scene scene_01.png --threshold 0.80

  # Optimise all scenes sequentially:
  python tests/tuner/run_tuner.py --all-scenes --max-rounds 5

  # Strict target, more rounds:
  python tests/tuner/run_tuner.py --scene scene_06.png --threshold 0.85 --max-rounds 15
""",
    )
    p.add_argument("--scene",      default=None, help="Scene file e.g. scene_01.png")
    p.add_argument("--all-scenes", action="store_true", help="Optimise all 10 scenes")
    p.add_argument("--threshold",  type=float, default=0.80, help="Target score (default 0.80)")
    p.add_argument("--max-rounds", type=int,   default=10,   help="Max optimisation rounds")
    p.add_argument("--dry-run",    action="store_true",     help="Score baseline only, no changes")
    args = p.parse_args()

    if not args.scene and not args.all_scenes:
        p.error("Specify --scene scene_01.png or --all-scenes")

    sample_paths = get_sample_paths()
    scenes       = SCENE_FILES if args.all_scenes else [args.scene]
    all_results  = {}

    for scene in scenes:
        result = run_for_scene(
            scene_file=scene,
            sample_paths=sample_paths,
            threshold=args.threshold,
            max_rounds=args.max_rounds,
            dry_run=args.dry_run,
        )
        all_results[scene] = result

    # Summary across all scenes
    if args.all_scenes and not args.dry_run:
        logger.info("\n%s", "═" * 60)
        logger.info("FULL SUMMARY")
        logger.info("═" * 60)
        for scene, r in all_results.items():
            if not r:
                continue
            status = "✅" if r.get("threshold_met") else "❌"
            logger.info(
                "%s %-15s  baseline=%.3f → final=%.3f  (+%.3f)  rounds=%d",
                status, scene,
                r.get("baseline_score", 0),
                r.get("final_score", 0),
                r.get("improvement", 0),
                r.get("rounds_completed", 0),
            )
        logger.info("\nRun 'python tests/tuner/apply_params.py --apply' to apply winning params.")


if __name__ == "__main__":
    main()

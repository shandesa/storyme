"""
tests/evaluator/run_evaluator.py
==================================
On-demand image quality evaluation loop for StoryMe generated images.

Reads ALL generated page images from Azure Blob Storage,
evaluates face attribute quality for each, and loops until:
  a) All images pass the quality threshold, OR
  b) Maximum iterations reached (--max-iter), OR
  c) User interrupts (Ctrl+C)

Each iteration downloads fresh images from blob storage so newly
generated storybooks are included automatically.

Usage
-----
# Evaluate all images, run indefinitely until all pass:
python tests/evaluator/run_evaluator.py

# Evaluate a specific story/child, max 5 iterations:
python tests/evaluator/run_evaluator.py \\
  --story forest_of_smiles \\
  --child Niku \\
  --max-iter 5

# Evaluate with verbose per-attribute output:
python tests/evaluator/run_evaluator.py --verbose

# Dry-run with local PNG files (no Azure needed):
python tests/evaluator/run_evaluator.py \\
  --local-dir /path/to/generated/images \\
  --story forest_of_smiles

Environment variables required (unless --local-dir):
  AZURE_STORAGE_CONNECTION_STRING
  AZURE_STORAGE_CONTAINER_NAME  (default: storyme-assets)
  MONGO_URL                     (default: mongodb://localhost:27017)

Output
------
Console: live progress + per-scene results
  reports/eval_YYYYMMDD_HHMMSS.json: full machine-readable report
  reports/eval_YYYYMMDD_HHMMSS.txt:  human-readable summary
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.evaluator.scene_metadata import SCENE_METADATA
from tests.evaluator.face_evaluator  import FaceEvaluator, EvaluationResult
from tests.evaluator.blob_reader     import BlobReader, GeneratedImageRecord
from backend.services.story_service  import FACE_COORDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("evaluator")


# ─── Report ───────────────────────────────────────────────────────────────────

class EvaluationReport:
    """Accumulates results across one evaluation run."""

    def __init__(self):
        self.started_at  = datetime.now(timezone.utc).isoformat()
        self.results:    list[EvaluationResult] = []
        self.errors:     list[str] = []
        self.iterations: int = 0

    def add(self, r: EvaluationResult):
        self.results.append(r)

    # ── Aggregate stats ───────────────────────────────────────────────────────

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def mean_score(self) -> float:
        return sum(r.composite_score for r in self.results) / self.total if self.total else 0.0

    def by_scene(self) -> dict[str, dict]:
        """Aggregate stats grouped by scene_file."""
        agg: dict[str, dict] = {}
        for r in self.results:
            s = r.scene_file
            if s not in agg:
                agg[s] = {"total": 0, "passed": 0, "scores": [], "failures": []}
            agg[s]["total"] += 1
            agg[s]["scores"].append(r.composite_score)
            if r.passed:
                agg[s]["passed"] += 1
            else:
                # Collect which attributes failed most often
                failed_attrs = [a.name for a in r.attributes if not a.passed]
                agg[s]["failures"].extend(failed_attrs)

        for s, v in agg.items():
            v["pass_rate"]  = v["passed"] / v["total"] if v["total"] else 0.0
            v["mean_score"] = sum(v["scores"]) / len(v["scores"]) if v["scores"] else 0.0
            # Rank most-failed attributes
            from collections import Counter
            v["top_failures"] = Counter(v["failures"]).most_common(3)

        return agg

    def all_pass(self) -> bool:
        return self.total > 0 and self.passed == self.total

    # ── Console output ────────────────────────────────────────────────────────

    def print_summary(self, verbose: bool = False):
        sep = "─" * 72
        print(f"\n{sep}")
        print(f"  Iteration {self.iterations}  |  {self.total} images evaluated")
        print(f"  Pass rate:  {self.pass_rate:.1%}  ({self.passed}/{self.total})")
        print(f"  Mean score: {self.mean_score:.3f}")
        print(sep)

        if verbose:
            for r in self.results:
                print(r.summary())
                print()

        print("  Scene breakdown:")
        for scene, stats in sorted(self.by_scene().items()):
            bar   = "█" * int(stats["pass_rate"] * 20)
            space = "░" * (20 - len(bar))
            print(
                f"    {scene:<15}  {bar}{space}  "
                f"{stats['pass_rate']:.0%}  "
                f"score={stats['mean_score']:.2f}"
            )
            if stats["top_failures"]:
                attrs = ", ".join(f"{a}×{n}" for a, n in stats["top_failures"])
                print(f"               failing attrs: {attrs}")

        print(sep)
        if self.all_pass():
            print("  ✅ ALL IMAGES PASS — production quality confirmed")
        else:
            print(f"  ❌ {self.failed} image(s) need improvement")
        print()

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "started_at":   self.started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "iterations":   self.iterations,
            "summary": {
                "total":      self.total,
                "passed":     self.passed,
                "failed":     self.failed,
                "pass_rate":  round(self.pass_rate, 4),
                "mean_score": round(self.mean_score, 4),
            },
            "by_scene": {
                k: {
                    "total":     v["total"],
                    "passed":    v["passed"],
                    "pass_rate": round(v["pass_rate"], 4),
                    "mean_score": round(v["mean_score"], 4),
                    "top_failures": v["top_failures"],
                }
                for k, v in self.by_scene().items()
            },
            "results": [
                {
                    "generation_id":   r.generation_id,
                    "child_name":      r.child_name,
                    "story_id":        r.story_id,
                    "scene_file":      r.scene_file,
                    "composite_score": r.composite_score,
                    "passed":          r.passed,
                    "attributes": [
                        {
                            "name":      a.name,
                            "score":     a.score,
                            "raw_value": str(a.raw_value),
                            "expected":  a.expected,
                            "passed":    a.passed,
                            "note":      a.note,
                        }
                        for a in r.attributes
                    ],
                    "error": r.error,
                }
                for r in self.results
            ],
        }

    def save(self, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        data = self.to_dict()

        json_path = out_dir / f"eval_{ts}.json"
        json_path.write_text(json.dumps(data, indent=2))
        logger.info("Report saved: %s", json_path)

        txt_path = out_dir / f"eval_{ts}.txt"
        lines = [
            f"StoryMe Image Quality Report — {ts}",
            f"Iterations: {self.iterations}",
            f"Total images: {self.total}  Pass: {self.passed}  Fail: {self.failed}",
            f"Mean score: {self.mean_score:.4f}",
            "",
            "=== Per-scene ===",
        ]
        for scene, stats in sorted(data["by_scene"].items()):
            lines.append(
                f"  {scene:<15}  {stats['pass_rate']:.0%}  score={stats['mean_score']:.3f}"
            )
        lines += ["", "=== Failed images ==="]
        for r in data["results"]:
            if not r["passed"]:
                lines.append(
                    f"  [{r['composite_score']:.3f}] {r['scene_file']}  "
                    f"gen={r['generation_id'][:8]}  child={r['child_name']}"
                )
                for a in r["attributes"]:
                    if not a["passed"]:
                        lines.append(
                            f"    ✗ {a['name']:<20} measured={a['raw_value']}  "
                            f"expected={a['expected']}  {a['note']}"
                        )
        txt_path.write_text("\n".join(lines))
        logger.info("Text report saved: %s", txt_path)


# ─── Main evaluation loop ─────────────────────────────────────────────────────

def evaluate_once(
    records:   list[GeneratedImageRecord],
    reader:    BlobReader | None,
    local_dir: Path | None,
    evaluator: FaceEvaluator,
    verbose:   bool,
) -> EvaluationReport:
    """Run one full evaluation pass over all records."""
    report = EvaluationReport()

    for i, rec in enumerate(records, 1):
        local_path = None
        try:
            # Determine local image path
            if local_dir:
                # Scan local directory for matching file
                candidates = list(local_dir.glob(f"*{rec.scene_file}")) + \
                             list(local_dir.glob(f"*page_{rec.page_number:02d}*.png"))
                if not candidates:
                    logger.warning("Local file not found for %s", rec.scene_file)
                    continue
                local_path = str(candidates[0])
                cleanup    = False
            else:
                logger.debug("[%d/%d] Downloading %s...", i, len(records), rec.blob_path)
                local_path = reader.download_to_temp(rec.blob_path)
                cleanup    = True

            meta = SCENE_METADATA.get(rec.scene_file)
            if meta is None:
                logger.warning("No scene metadata for %s — skipping", rec.scene_file)
                continue

            face_cfg = FACE_COORDS.get(rec.scene_file)
            if face_cfg is None:
                logger.warning("No face coords for %s — skipping", rec.scene_file)
                continue

            result = evaluator.evaluate(
                image_path=local_path,
                scene_meta=meta,
                face_config=face_cfg,
                generation_id=rec.generation_id,
                child_name=rec.child_name,
                story_id=rec.story_id,
            )

            report.add(result)

            # Live per-image output
            status = "✅" if result.passed else "❌"
            logger.info(
                "%s [%d/%d] %s | %s | score=%.3f",
                status, i, len(records),
                rec.scene_file, rec.child_name[:12], result.composite_score,
            )
            if verbose:
                print(result.summary())

        except Exception as e:
            logger.error("Evaluation failed for %s: %s", rec.blob_path if rec else "?", e)
            report.errors.append(str(e))
        finally:
            if local_path and cleanup:
                reader.cleanup(local_path)

    return report


def run_loop(args: argparse.Namespace) -> None:
    """Main loop — run until all pass or max iterations reached."""
    evaluator = FaceEvaluator()
    reader    = None

    if args.local_dir:
        local_dir = Path(args.local_dir)
        # Build synthetic records from local files
        records = []
        for f in sorted(local_dir.glob("*.png")):
            scene_file = None
            for sf in SCENE_METADATA:
                if sf.replace(".png", "") in f.stem or f.stem.endswith(sf.replace(".png", "")):
                    scene_file = sf
                    break
            if scene_file is None:
                # Try page number pattern
                import re
                m = re.search(r"page_(\d+)", f.stem)
                if m:
                    pn = int(m.group(1))
                    from backend.services.story_service import SCENE_FILES
                    scene_file = SCENE_FILES[pn-1] if 1 <= pn <= len(SCENE_FILES) else None
            if scene_file:
                from tests.evaluator.blob_reader import GeneratedImageRecord
                records.append(GeneratedImageRecord(
                    generation_id="local",
                    child_name=args.child or "unknown",
                    story_id=args.story or "forest_of_smiles",
                    gender=args.gender or "neutral",
                    generation_mode="opencv",
                    scene_file=scene_file,
                    page_number=int(scene_file.split("_")[1].split(".")[0]),
                    blob_path=str(f),
                ))
        logger.info("Local mode: found %d image files in %s", len(records), local_dir)
    else:
        reader = BlobReader.from_env()
        records = reader.list_generated_images(
            story_id=args.story,
            child_name=args.child,
            gender=args.gender,
            limit=args.limit,
        )
        logger.info("Blob/MongoDB: found %d images to evaluate", len(records))

    if not records:
        logger.error(
            "No images found. "
            "Generate some storybooks first, or use --local-dir for local testing."
        )
        sys.exit(1)

    out_dir     = Path(args.output_dir)
    iteration   = 0
    max_iter    = args.max_iter or float("inf")
    poll_secs   = args.poll_interval

    all_passed  = False

    try:
        while iteration < max_iter:
            iteration += 1
            logger.info(
                "═══ Iteration %d/%s — evaluating %d images ═══",
                iteration, str(args.max_iter) if args.max_iter else "∞", len(records),
            )

            report           = evaluate_once(records, reader, Path(args.local_dir) if args.local_dir else None, evaluator, args.verbose)
            report.iterations = iteration
            report.print_summary(verbose=False)
            report.save(out_dir)

            if report.all_pass():
                all_passed = True
                logger.info("✅ All %d images passed quality threshold. Evaluation complete.", report.passed)
                break

            if iteration >= max_iter:
                logger.info("Max iterations (%d) reached. Stopping.", args.max_iter)
                break

            if args.local_dir:
                # Local mode: no new images will appear, stop after one pass
                logger.info("Local mode: stopping after single iteration.")
                break

            logger.info(
                "%.0f%% pass rate. Waiting %ds before next iteration "
                "(new storybooks generated in the meantime will be included)...",
                report.pass_rate * 100, poll_secs,
            )

            # Re-discover images (new generations may have been created)
            records = reader.list_generated_images(
                story_id=args.story,
                child_name=args.child,
                gender=args.gender,
                limit=args.limit,
            )
            time.sleep(poll_secs)

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")

    # Final summary
    print("\n" + "═" * 72)
    if all_passed:
        print("  ✅ EVALUATION COMPLETE — all images meet production quality threshold")
    else:
        print("  📋 EVALUATION ENDED — some images still below threshold")
        print("     Review reports in:", out_dir)
    print("═" * 72)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="StoryMe image quality evaluator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Evaluate all images in Azure Blob:
  python tests/evaluator/run_evaluator.py

  # Evaluate a specific story/child:
  python tests/evaluator/run_evaluator.py --story forest_of_smiles --child Niku

  # Run max 3 iterations, verbose output:
  python tests/evaluator/run_evaluator.py --max-iter 3 --verbose

  # Test locally (no Azure needed):
  python tests/evaluator/run_evaluator.py --local-dir /tmp/my_generated_pages
""",
    )
    p.add_argument("--story",          default=None,  help="Filter by story_id")
    p.add_argument("--child",          default=None,  help="Filter by child_name")
    p.add_argument("--gender",         default=None,  help="Filter by gender (neutral/male/female)")
    p.add_argument("--max-iter",       type=int, default=None, help="Max evaluation iterations (default: infinite)")
    p.add_argument("--poll-interval",  type=int, default=60,   help="Seconds between iterations (default: 60)")
    p.add_argument("--limit",          type=int, default=500,  help="Max images per iteration (default: 500)")
    p.add_argument("--local-dir",      default=None,  help="Evaluate local PNG files instead of Azure Blob")
    p.add_argument("--output-dir",     default="tests/evaluator/reports", help="Directory for report files")
    p.add_argument("--verbose",        action="store_true", help="Print per-attribute detail for every image")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    run_loop(args)

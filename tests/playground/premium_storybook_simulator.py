#!/usr/bin/env python3
"""
premium_storybook_simulator.py
================================
Local test harness for the AI (DALL-E / gpt-image-1) premium storybook
generation pipeline.

Simulates exactly what the frontend does when it calls
  POST /api/v2/generate/ai-book
by calling ai_book_service._run_sync() directly — no HTTP server needed.

Usage
-----
  python premium_storybook_simulator.py \\
      --name   "Arjun" \\
      --photo  /path/to/kid.jpg \\
      --story  forest_of_smiles \\
      --quality medium \\
      --force  true

Arguments
---------
  --name        (required) Child's first name.  Replaces {name} in story text.
  --photo       (required) Path to the child's photo (JPEG / PNG / WEBP).
  --force       (optional) "true" / "false" — bypass DALL-E cache and force
                full regeneration of all pages.  Equivalent to the force_regen
                checkbox on the frontend.  Default: false.
  --story       (optional) Story ID (e.g. forest_of_smiles).  Default: forest_of_smiles.
  --quality     (optional) "medium" or "high".  Passed to gpt-image-1.  Default: medium.
  --story-file  (optional) Absolute or relative path to a custom story JSON to
                use instead of the default backend/data/stories/<story>.json.
                Use this to iterate on prompts without touching the backend copy.

Output
------
  Page images  → tests/playground/output/<name>/<story>/images/
  PDF          → tests/playground/output/<name>/<story>/pdf/
  Run log      → tests/playground/output/logs/<YYYYMMDD_HHMMSS>.log

API key
-------
  Read from tests/playground/env  (key: OPEN_API_KEY)
  The env file must contain a line like:
    OPEN_API_KEY=sk-proj-...

Notes
-----
  * No production code is modified.  This script monkey-patches only the
    config.OUTPUT_DIR instance attribute before calling the service.
  * AZURE_STORAGE_CONNECTION_STRING is intentionally NOT set, so the JSON
    (local filesystem) stores are used for ai_page_store caching.
  * STORAGE_TYPE is set to "local" so blob upload helpers are no-ops.
  * face_pipeline_service is NOT invoked by the AI book pipeline — DALL-E
    images.edit() provides cartoon character faces directly.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# ─── Resolve paths ────────────────────────────────────────────────────────────

_SCRIPT_DIR   = Path(__file__).resolve().parent          # tests/playground/
_REPO_ROOT    = _SCRIPT_DIR.parent.parent                # storyme/
_BACKEND_DIR  = _REPO_ROOT / "backend"
_ENV_FILE     = _SCRIPT_DIR / "env"
_OUTPUT_ROOT  = _SCRIPT_DIR / "output"
_LOGS_DIR     = _OUTPUT_ROOT / "logs"

# ─── Bootstrap sys.path ───────────────────────────────────────────────────────
# Must happen BEFORE any backend imports so Python can find core.*, services.*

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# ─── Logging setup (file + console) ──────────────────────────────────────────

def _setup_logging(log_path: Path) -> logging.Logger:
    """
    Configure root logger to emit to both the console and a timestamped log
    file.  The file captures everything from DEBUG level upward; the console
    shows INFO and above.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        fmt   = "%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s",
        datefmt = "%Y-%m-%d %H:%M:%S",
    )

    # File handler — full DEBUG trace
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler — INFO only, coloured level names
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)

    return logging.getLogger("simulator")


def _bold(logger: logging.Logger, *lines: str) -> None:
    """
    Emit visually prominent log lines so they stand out in the log file.
    In a plain text file there is no real bold; we use a box of '=' characters
    to guarantee the lines are findable at a glance.
    """
    width = 72
    border = "=" * width
    logger.info(border)
    for line in lines:
        logger.info("  ** %s", line)
    logger.info(border)


# ─── Parse env file ───────────────────────────────────────────────────────────

def _read_env_file(path: Path) -> dict[str, str]:
    """
    Parse a simple KEY=VALUE env file.  Strips quotes, ignores comment lines.
    Returns the key/value pairs found.
    """
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip().strip("'\"")
    return result


# ─── Argument parsing ─────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Local DALL-E premium storybook simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--name",
        required=True,
        help="Child's first name (required).",
    )
    p.add_argument(
        "--photo",
        required=True,
        help="Path to the child's photo — JPEG, PNG, or WEBP (required).",
    )
    p.add_argument(
        "--force",
        default="false",
        choices=["true", "false", "True", "False", "1", "0"],
        help="Force regeneration: bypass DALL-E cache.  Default: false.",
    )
    p.add_argument(
        "--story",
        default="forest_of_smiles",
        help="Story ID.  Default: forest_of_smiles.",
    )
    p.add_argument(
        "--quality",
        default="medium",
        choices=["medium", "high"],
        help="DALL-E image quality.  Default: medium.",
    )
    p.add_argument(
        "--story-file",
        default=None,
        help=(
            "Path to a custom story JSON file.  If given, this file is used "
            "instead of backend/data/stories/<story>.json.  Useful for prompt "
            "iteration without touching the production story files."
        ),
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=2,
        metavar="N",
        help=(
            "Maximum number of character (hero) pages to generate using AI models.  "
            "Range 1-16.  Default: 2.  Use this to validate character consistency "
            "before running the full pipeline."
        ),
    )
    return p.parse_args()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    s = re.sub(r"[^\w\-]", "_", name.strip().lower())
    return re.sub(r"_+", "_", s).strip("_")[:40] or "child"


def _bool_arg(value: str) -> bool:
    return value.lower() in ("true", "1")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    args = _parse_args()

    # ── Timestamp for this run ────────────────────────────────────────────────
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = _LOGS_DIR / f"{ts}.log"

    logger = _setup_logging(log_path)

    logger.info("=" * 72)
    logger.info("  StoryMe — Premium Storybook Simulator")
    logger.info("  Run timestamp : %s", ts)
    logger.info("  Python        : %s", sys.version.split()[0])
    logger.info("=" * 72)

    # ── Validate photo ────────────────────────────────────────────────────────
    photo_path = Path(args.photo).resolve()
    if not photo_path.exists():
        logger.error("Photo file not found: %s", photo_path)
        return 1
    if photo_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        logger.error("Unsupported photo format: %s", photo_path.suffix)
        return 1

    # ── Parse arguments ───────────────────────────────────────────────────────
    child_name   = args.name.strip()
    story_id     = args.story.strip()
    quality      = args.quality
    force_regen  = _bool_arg(args.force)
    custom_story = Path(args.story_file).resolve() if args.story_file else None
    max_ai_pages = max(1, min(16, args.max_pages))

    logger.info("Arguments:")
    logger.info("  child_name  : %s", child_name)
    logger.info("  photo       : %s", photo_path)
    logger.info("  story_id    : %s", story_id)
    logger.info("  quality     : %s", quality)
    logger.info("  force_regen : %s", force_regen)
    logger.info("  max_ai_pages: %d", max_ai_pages)
    logger.info("  story_file  : %s", custom_story or "(default backend story JSON)")
    logger.info("  log         : %s", log_path)

    # ── Resolve story JSON path ───────────────────────────────────────────────
    if custom_story:
        if not custom_story.exists():
            logger.error("Custom story file not found: %s", custom_story)
            return 1
        story_json_path = custom_story
    else:
        # Default path used by ai_book_service._STORY_JSON
        story_json_path = (
            _BACKEND_DIR / "data" / "stories" / "forest_of_smiles_v8_final.json"
        )
        # If the story_id differs from the default we can try to find a match
        if story_id != "forest_of_smiles":
            candidates = sorted(
                (_BACKEND_DIR / "data" / "stories").glob(f"{story_id}*.json")
            )
            if candidates:
                story_json_path = candidates[-1]   # most recent by name sort
                logger.info("Resolved story file: %s", story_json_path)
            else:
                logger.warning(
                    "No story JSON found for story_id '%s'; using default: %s",
                    story_id, story_json_path,
                )

    # Emit bold / prominent markers so these are easy to find in the log file
    _bold(
        logger,
        f"STORY JSON FILE  : {story_json_path}",
        f"PROMPTS SOURCE   : page[N]['prompt']['final_text'] inside the story JSON above",
        f"PHOTO            : {photo_path}",
    )

    # ── Read API key from env file ────────────────────────────────────────────
    env_vars = _read_env_file(_ENV_FILE)
    openai_key = env_vars.get("OPEN_API_KEY", "")
    if not openai_key:
        logger.error(
            "OPEN_API_KEY not found in %s — cannot call DALL-E", _ENV_FILE
        )
        return 1

    # Set env vars BEFORE importing any backend module that reads them
    os.environ["OPENAI_API_KEY"]                 = openai_key
    os.environ["STORAGE_TYPE"]                   = "local"
    # Deliberately NOT setting AZURE_STORAGE_CONNECTION_STRING so that
    # ai_page_store uses JsonAIBackgroundPageStore (local JSON files).
    os.environ.pop("AZURE_STORAGE_CONNECTION_STRING", None)

    logger.info("OPENAI_API_KEY  : %s...%s (from %s)",
                openai_key[:8], openai_key[-4:], _ENV_FILE)
    logger.info("STORAGE_TYPE    : local  (forced for simulator)")

    # ── Prepare output directories ────────────────────────────────────────────
    safe_child   = _safe_name(child_name)
    safe_story   = _safe_name(story_id)
    images_dir   = _OUTPUT_ROOT / safe_child / safe_story / "images"
    pdf_dir      = _OUTPUT_ROOT / safe_child / safe_story / "pdf"
    images_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Images output   : %s", images_dir)
    logger.info("PDF output      : %s", pdf_dir)

    # ── Import backend — AFTER env vars are set ───────────────────────────────
    logger.info("Importing backend services …")
    try:
        from core.config import config                          # noqa: E402
        from services.ai_book_service import AIBookService     # noqa: E402
    except Exception as exc:
        logger.error("Backend import failed: %s", exc, exc_info=True)
        return 1

    # ── Patch config.OUTPUT_DIR so intermediate images land in images_dir ─────
    # Patching the instance attribute shadows the class attribute.  _run_sync
    # reads config.OUTPUT_DIR lazily (inside the function body) so the patch
    # is in effect when it executes.
    original_output_dir     = config.OUTPUT_DIR
    config.OUTPUT_DIR       = images_dir
    config.STORAGE_TYPE     = "local"
    images_dir.mkdir(parents=True, exist_ok=True)

    logger.info("config.OUTPUT_DIR patched → %s  (was: %s)", images_dir, original_output_dir)

    # ── Build a local AIBookService instance ──────────────────────────────────
    # We instantiate directly (instead of using the module singleton) so the
    # OPENAI_API_KEY we just set is picked up fresh.
    try:
        svc = AIBookService()
    except RuntimeError as exc:
        logger.error("AIBookService init failed: %s", exc)
        return 1

    # ── Optionally load a custom story JSON ───────────────────────────────────
    # Pre-populate svc._story_config so _load_story() returns our version
    # without touching ai_book_service._STORY_JSON.
    if custom_story or story_json_path != (
        _BACKEND_DIR / "data" / "stories" / "forest_of_smiles_v8_final.json"
    ):
        try:
            svc._story_config = json.loads(story_json_path.read_text("utf-8"))
            logger.info("Loaded custom story config from: %s", story_json_path)
        except Exception as exc:
            logger.error("Failed to load story JSON: %s", exc)
            return 1
    else:
        logger.info("Using default ai_book_service story JSON loader.")

    # ── Read user photo bytes ─────────────────────────────────────────────────
    user_photo_bytes = photo_path.read_bytes()
    logger.info("Photo loaded: %d bytes from %s", len(user_photo_bytes), photo_path)

    # ── Generate a generation_id for this run ─────────────────────────────────
    gen_id = uuid.uuid4().hex
    seed   = random.randint(0, 2**32 - 1)
    user_mobile = "simulator"

    logger.info("generation_id   : %s", gen_id)
    logger.info("generation_seed : %d", seed)
    logger.info("force_regen     : %s", force_regen)
    logger.info("max_ai_pages    : %d", max_ai_pages)

    _bold(
        logger,
        "PIPELINE STARTING",
        f"  generation_id : {gen_id}",
        f"  child_name    : {child_name}",
        f"  story_id      : {story_id}",
        f"  force_regen   : {force_regen}",
        f"  max_ai_pages  : {max_ai_pages}",
        f"  quality       : {quality}",
        f"  seed          : {seed}",
    )

    # ── Call the synchronous pipeline directly ────────────────────────────────
    # _run_sync is normally executed in an asyncio thread executor.
    # Calling it directly here is safe — it is pure synchronous Python.
    t_start = time.time()
    try:
        result = svc._run_sync(
            gen_id           = gen_id,
            user_mobile      = user_mobile,
            child_name       = child_name,
            story_id         = story_id,
            user_photo_bytes = user_photo_bytes,
            quality          = quality,
            generation_seed  = seed,
            force_regen      = force_regen,
            max_ai_pages     = max_ai_pages,
        )
    except Exception as exc:
        logger.error("_run_sync raised an unhandled exception: %s", exc, exc_info=True)
        return 1
    finally:
        # Restore patched config (non-critical — process exits soon anyway)
        config.OUTPUT_DIR = original_output_dir

    elapsed = time.time() - t_start

    status = result.get("status", "unknown")
    logger.info("Pipeline finished in %.1f s — status: %s", elapsed, status)

    if status != "complete":
        logger.error("Generation did NOT complete.  Result: %s", result)
        return 1

    # ── Move PDF from images_dir to pdf_dir ───────────────────────────────────
    pdf_filename = result.get("pdf_filename", "")
    pdf_source   = images_dir / pdf_filename if pdf_filename else None

    moved_pdf: Path | None = None
    if pdf_source and pdf_source.exists():
        pdf_dest = pdf_dir / pdf_filename
        shutil.move(str(pdf_source), str(pdf_dest))
        moved_pdf = pdf_dest
        logger.info("PDF moved → %s", pdf_dest)
    else:
        # Fallback: scan images_dir for any .pdf
        pdf_candidates = sorted(images_dir.glob("*.pdf"))
        if pdf_candidates:
            pdf_source = pdf_candidates[-1]
            pdf_dest   = pdf_dir / pdf_source.name
            shutil.move(str(pdf_source), str(pdf_dest))
            moved_pdf = pdf_dest
            logger.info("PDF moved (fallback) → %s", pdf_dest)
        else:
            logger.warning("No PDF found to move.  Check images_dir: %s", images_dir)

    # ── Collect generated page images ─────────────────────────────────────────
    page_images = sorted(images_dir.glob(f"{gen_id}_p*.png"))
    logger.info("Page images saved: %d files in %s", len(page_images), images_dir)
    for img in page_images:
        logger.info("  %s  (%d KB)", img.name, img.stat().st_size // 1024)

    # ── Final summary ─────────────────────────────────────────────────────────
    updates = result.get("updates", {})
    _bold(
        logger,
        "GENERATION COMPLETE",
        f"  elapsed        : {elapsed:.1f} s",
        f"  pages_succeeded: {updates.get('pages_succeeded', '?')} / {updates.get('total_pages', '?')}",
        f"  pages_failed   : {updates.get('pages_failed', 0)}",
        f"  PDF            : {moved_pdf or 'not found'}",
        f"  Images dir     : {images_dir}",
        f"  Log file       : {log_path}",
        "",
        "  To iterate on prompts:",
        f"    1. Copy {story_json_path}",
        "    2. Edit page[N]['prompt']['final_text']",
        "    3. Re-run with --story-file /path/to/copy.json --force true",
    )

    logger.info("Simulator done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

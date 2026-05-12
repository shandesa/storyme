#!/usr/bin/env python3
"""
test_replicate_models.py
=========================
Standalone test harness for evaluating InstantID and IP-Adapter FaceID via
Replicate for face-consistent, cartoonized, emotionally expressive storybook
character image generation.

Spec  : SPEC-AI-TEST-001 v1.0
Inherits: tests/playground/scripts/BASE_SPEC.md (SPEC-BASE-001)

Pipeline
--------
  Stage 1 — InstantID  : original face photo  → cartoonized identity image
  Stage 2 — IP-Adapter : Stage 1 output       → final chained styled image
  Stage 3 — Final      : copy of Stage 2 (no additional API call)

Usage
-----
  python tests/playground/scripts/ai/test_replicate_models.py \\
      --name   nikshay \\
      --model  both \\
      --quality medium

  python tests/playground/scripts/ai/test_replicate_models.py \\
      --name   nikshay \\
      --model  instantid \\
      --force  true \\
      --dry-run

Arguments
---------
  --name      (required) Child name; resolves face photo path automatically.
  --photo     (optional) Explicit face photo path override.
  --model     (optional) instantid | both. Default: both.
               NOTE: ip_adapter is disallowed standalone (see §3.1 of spec).
  --quality   (optional) medium | high. Default: medium.
  --force     (optional) true | false. Bypass cache. Default: false.
  --dry-run   (optional) Validate plan, make zero API calls.

Output
------
  Per-page folders:
    tests/playground/output/<name>/model_tests/<timestamp>/page_NN/
      p{NN}_1_instantid.png   ← Stage 1 output
      p{NN}_2_ip_adapter.png  ← Stage 2 output (chained on Stage 1)
      p{NN}_3_final.png       ← copy of Stage 2 (final inspection image)

  Run report:
    tests/playground/output/<name>/model_tests/<timestamp>/report.json

  Log file:
    tests/playground/output/logs/<timestamp>_test_replicate_models.log

Credentials
-----------
  tests/playground/env must contain:
    REPLICATE_KEY=r8_...

Edit the PAGE_CONFIGS block below before each test run.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Path resolution ────────────────────────────────────────────────────────────
# All paths are resolved relative to this script's location so the script works
# regardless of the working directory from which it is called.

_SCRIPT_DIR  = Path(__file__).resolve().parent          # scripts/ai/
_SCRIPTS_DIR = _SCRIPT_DIR.parent                       # scripts/
_PG_DIR      = _SCRIPTS_DIR.parent                      # tests/playground/
_REPO_ROOT   = _PG_DIR.parent.parent                    # storyme/
_ENV_FILE    = _PG_DIR / "env"
_OUTPUT_ROOT = _PG_DIR / "output"
_CACHE_DIR   = _PG_DIR / "cache" / "replicate"
_LOGS_DIR    = _OUTPUT_ROOT / "logs"
_FACES_DIR   = _PG_DIR / "user_face"

# ── Replicate model identifiers (pinned version hashes) ───────────────────────
# Update the hash explicitly when upgrading to a newer model version.

INSTANTID_MODEL = (
    "zedge/instantid:"
    "ba2d5293be8794a05841a6f6eed81e810340142c3c25fab4838ff2b5d9574420"
)

# WHY VERSION HASHES ARE MANDATORY FOR COMMUNITY MODELS:
# Without hash → SDK routes to POST /v1/models/{owner}/{name}/predictions → 404
# With hash    → SDK routes to POST /v1/predictions {"version":"hash"}    → works
# Both models below are is_official: false (community models).
# Confirmed hash values from https://replicate.com/{owner}/{model}/versions
# Never call client.run("owner/model") without ":hash" for community models.

# Stage 2 — InstantID + IP-Adapter SDXL (zsxkib/instant-id-ipadapter-plus-face)
# Hash: https://replicate.com/zsxkib/instant-id-ipadapter-plus-face/versions
# is_official: false → hash is mandatory.
# Latest version: 32402fb5 (created 2024-07-14, 5.7K runs).
# This model combines InstantID (face identity) + IP-Adapter (style/prompt)
# in one SDXL call — better than lucataco/ip-adapter-faceid (SD 1.5, 2023).
# Input: "image" = face reference; "instantid_weight" + "ipadapter_weight".
# Output: 1024×1024 SDXL image matching Stage 1 resolution.
IP_ADAPTER_MODEL = (
    "zsxkib/instant-id-ipadapter-plus-face:"
    "32402fb5c493d883aa6cf098ce3e4cc80f1fe6871f6ae7f632a8dbde01a3d161"
)

# ── InstantID neutral portrait prompt (for once-per-user Stage 1 call) ───────
# Stage 1 runs ONCE per user with this neutral prompt to cartoonize the face.
# Scene prompts are applied in Stage 2 only, not here.
INSTANTID_NEUTRAL_PROMPT = (
    "pixar 3d animation style, children's storybook illustration, "
    "cartoon portrait of a child, soft pastel colors, warm lighting, "
    "smooth render, high detail, clean neutral background, "
    "forward-facing, neutral calm expression"
)

# ── User face cache ───────────────────────────────────────────────────────────
# Keyed by face_hash8 + quality only (not by prompt/expression/page).
# Location: cache/replicate/user_faces/
_USER_FACE_CACHE_SUBDIR = "user_faces"

# ── Backoff constants (from BASE §6) ──────────────────────────────────────────
BACKOFF_MAX_RETRIES = 6    # maximum attempts before giving up on a 429
BACKOFF_BASE_SECS   = 10   # default base wait when no hint in error message
BACKOFF_MAX_SECS    = 120  # hard ceiling per sleep to avoid indefinite blocking

# ── Expression map (from SPEC §5) ─────────────────────────────────────────────
EXPRESSION_MAP = {
    "curious":    "wide curious eyes, slightly open mouth, wondering expression",
    "determined": "determined focused gaze, chin slightly raised, confident expression",
    "caring":     "warm gentle eyes, soft reassuring smile, nurturing expression",
    "gentle":     "quiet peaceful smile, gentle kind eyes, calm serene expression",
    "delighted":  "sparkling eyes, wide bright smile, pure delight, joyful face",
    "welcoming":  "open warm smile, inviting expression, friendly welcoming eyes",
    "joyful":     "big joyful smile, crinkled happy eyes, beaming with happiness",
    "proud":      "satisfied proud expression, standing tall, calm content smile",
    "neutral":    "calm thoughtful expression, neutral peaceful face",
}

# ── Style prefix (from SPEC §7) ───────────────────────────────────────────────
STYLE_PREFIX = (
    "pixar 3d animation style, children's storybook illustration, "
    "soft pastel color palette, warm cinematic lighting, shallow depth of field, "
    "smooth 3d render, emotionally warm, magical atmosphere, "
    "high detail, 8k resolution, masterpiece, best quality, "
    "character on left third of frame, right side intentionally soft and uncluttered"
)

# ── Negative prompt (from SPEC §6) ────────────────────────────────────────────
# Applied to every Replicate call, both models, unconditionally.
NEGATIVE_PROMPT = (
    # Anatomy and quality defects
    "realistic, photograph, photorealistic, "
    "ugly, deformed, mutated, bad anatomy, extra limbs, missing limbs, "
    "fused fingers, too many fingers, long neck, malformed hands, "
    "blurry, out of focus, low quality, low resolution, jpeg artifacts, "
    "noisy, grainy, pixelated, "
    # Overlaid and branded content
    "watermark, text, logo, signature, username, border, frame, "
    # Tone and content safety
    "horror, disturbing, frightening, scary, dark, gloomy, "
    "violence, gore, blood, weapons, "
    "nsfw, adult content, mature, suggestive, "
    "monochrome, grayscale, sepia, oversaturated, overexposed, underexposed, "
    # StoryMe-specific face failure modes observed in prior Replicate test runs
    "blank stare, empty eyes, expressionless face, dead eyes, "
    "wrong skin tone, face mismatch, identity drift, "
    "multiple faces, floating head, disembodied face, "
    "distorted face, asymmetric face, squashed face"
)

# ══════════════════════════════════════════════════════════════════════════════
# TEST CONFIGURATION — edit this block before each run
#
# Rules:
#   - Maximum 30 entries. Script exits at startup if this is exceeded.
#   - page_number must be a unique integer between 1 and 30.
#   - prompt must be a non-empty string describing the scene.
#   - expression must be a key in EXPRESSION_MAP, or omit for "neutral".
#   - angle is optional; include when the scene needs a specific camera framing.
# ══════════════════════════════════════════════════════════════════════════════
PAGE_CONFIGS = [
    {
        "page_number": 1,
        "prompt": (
            "A young boy stands at the edge of a glowing magical jungle, "
            "tall trees swaying gently in warm golden light, "
            "soft morning mist, enchanted forest atmosphere"
        ),
        "expression": "curious",
        "angle": "eye-level, medium wide shot, character facing slightly right",
    },
    {
        "page_number": 3,
        "prompt": (
            "The boy kneels beside a sparkling forest river, "
            "sunlight dancing on the water surface, "
            "colourful butterflies nearby, lush green foliage"
        ),
        "expression": "delighted",
        "angle": "low angle, medium close-up on face and hands",
    },
    # ── add further pages here, up to 30 ──────────────────────────────────────
]
# ══════════════════════════════════════════════════════════════════════════════


# ── Logging setup ──────────────────────────────────────────────────────────────

def _setup_logging(log_path: Path) -> logging.Logger:
    """Configure root logger to emit DEBUG to file and INFO to stdout."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        fmt     = "%(asctime)s  %(levelname)-8s  %(name)-32s  %(message)s",
        datefmt = "%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)

    return logging.getLogger(Path(__file__).stem)


# ── Env file reader ────────────────────────────────────────────────────────────

def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=value env file; ignore blank lines and # comments."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip().strip("'\"")
    return result


# ── Argument parsing ───────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    """Parse and return command-line arguments."""
    p = argparse.ArgumentParser(
        description=(
            "StoryMe AI model test harness — InstantID + IP-Adapter FaceID via Replicate.\n"
            "Spec: SPEC-AI-TEST-001 v1.0"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--name",    required=True,
                   help="Child name (required). Determines face photo path.")
    p.add_argument("--photo",   default=None,
                   help="Explicit face photo path override.")
    p.add_argument("--model",   default="both", choices=["instantid", "both", "ip_adapter"],
                   help="Model to run: instantid | both. Default: both.")
    p.add_argument("--quality", default="medium", choices=["medium", "high"],
                   help="Generation quality: medium (30 steps) | high (50 steps). Default: medium.")
    p.add_argument("--force",   default="false",
                   choices=["true", "false", "True", "False", "1", "0"],
                   help="Bypass cache and regenerate. Default: false.")
    p.add_argument("--dry-run", action="store_true",
                   help="Validate plan and print it; make zero API calls.")
    return p.parse_args()


def _bool_arg(val: str) -> bool:
    """Convert string boolean arg to Python bool."""
    return str(val).lower() in ("true", "1")


# ── Prompt construction ────────────────────────────────────────────────────────

def _build_prompt(page: dict, expression: str) -> str:
    """Assemble the final SDXL prompt for a page from style, scene, expression, angle."""
    expr_desc = EXPRESSION_MAP.get(expression, EXPRESSION_MAP["neutral"])
    parts = [STYLE_PREFIX, page["prompt"], expr_desc]
    if page.get("angle"):
        parts.append(page["angle"])
    return ", ".join(parts)


# ── Image input helper ────────────────────────────────────────────────────────
# NOTE ON IMAGE FORMAT FOR REPLICATE MODELS
#
# Data URI approach (base64 strings) does NOT work for zedge/instantid or
# lucataco/ip-adapter-sdxl-face. These models are built with Cog; their image
# loader calls .read() on the input object. A string (even a valid data URI)
# has no .read() method — the model receives None and crashes with:
#   "Unexpected error processing image None: NoneType has no attribute read"
#
# The prior 401 error (run 164252) was caused by an expired Replicate token,
# NOT by using io.BytesIO. With a valid token, io.BytesIO is the correct
# approach: the Replicate SDK uploads it via /v1/files and passes the URL to
# the model, which can then call .read() on its HTTP response.
#
# Always use _make_image_input(bytes) — never pass raw strings to image fields.

def _make_image_input(image_bytes: bytes) -> "io.BytesIO":
    """Return a fresh BytesIO for a Replicate image input field.

    A fresh BytesIO is required on every call — once the SDK reads it
    the internal pointer is at EOF and reuse returns empty bytes.
    """
    return io.BytesIO(image_bytes)



# ── Cache helpers (BASE §7) ────────────────────────────────────────────────────

def _cache_key(face_bytes: bytes, final_prompt: str, expression: str,
               model: str, quality: str) -> str:
    """Build a content-addressed cache filename."""
    face_hash8   = hashlib.sha256(face_bytes).hexdigest()[:8]
    prompt_hash8 = hashlib.sha256(final_prompt.encode()).hexdigest()[:8]
    return f"{face_hash8}_{prompt_hash8}_{expression}_{model}_{quality}.png"


def _load_cache(cache_dir: Path, key: str) -> Optional[bytes]:
    """Return cached PNG bytes if the file exists and is non-empty, else None."""
    path = cache_dir / key
    try:
        if path.exists() and path.stat().st_size > 0:
            return path.read_bytes()
    except Exception as exc:
        logging.getLogger(Path(__file__).stem).warning(
            "Cache read failed (%s): %s", key, exc
        )
    return None


def _save_cache(cache_dir: Path, key: str, data: bytes,
                log: logging.Logger) -> None:
    """Write PNG bytes to cache; verify non-zero size; log outcome."""
    path = cache_dir / key
    try:
        path.write_bytes(data)
        if path.stat().st_size == 0:
            path.unlink()
            log.error("Cache write produced zero-byte file — deleted: %s", key)
        else:
            log.debug("Cache written: %s (%d KB)", key, len(data) // 1024)
    except Exception as exc:
        log.warning("Cache write failed (%s): %s", key, exc)


# ── Once-per-user InstantID face cache ────────────────────────────────────────

def _user_face_cache_dir(cache_dir: Path) -> Path:
    """Return the user_faces subdirectory, creating it if absent."""
    d = cache_dir / _USER_FACE_CACHE_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _user_face_cache_key(face_bytes: bytes, quality: str) -> str:
    """Cache key for once-per-user InstantID: face_hash8_instantid_{quality}.png."""
    return f"{hashlib.sha256(face_bytes).hexdigest()[:8]}_instantid_{quality}.png"


def _load_user_face_cache(cache_dir: Path, key: str,
                          log: logging.Logger) -> Optional[bytes]:
    """Return cached user-face bytes if present, else None."""
    path = _user_face_cache_dir(cache_dir) / key
    try:
        if path.exists() and path.stat().st_size > 0:
            log.info(
                "InstantID user-face CACHE HIT  — %s (%d KB) "
                "— Stage 1 will be skipped for ALL pages in this run",
                key, path.stat().st_size // 1024,
            )
            return path.read_bytes()
    except Exception as exc:
        log.warning("User-face cache read failed (%s): %s", key, exc)
    return None


def _save_user_face_cache(cache_dir: Path, key: str, data: bytes,
                          log: logging.Logger) -> None:
    """Persist user-face bytes; future runs skip Stage 1 entirely for this face."""
    path = _user_face_cache_dir(cache_dir) / key
    try:
        path.write_bytes(data)
        if path.stat().st_size == 0:
            path.unlink()
            log.error("User-face cache write zero-byte file — deleted: %s", key)
        else:
            log.info(
                "InstantID user-face cached: %s (%d KB) "
                "— Stage 1 will be skipped on future runs with this face",
                key, len(data) // 1024,
            )
    except Exception as exc:
        log.warning("User-face cache write failed (%s): %s", key, exc)


# ── Backoff helpers (BASE §6) ──────────────────────────────────────────────────

def _is_rate_limit(exc: Exception) -> bool:
    """Return True when exc is a Replicate 429 throttle error."""
    msg = str(exc).lower()
    return "429" in msg or "throttled" in msg or "rate limit" in msg


def _parse_retry_after(exc: Exception, attempt: int) -> float:
    """
    Extract recommended wait from Replicate error detail (e.g. 'resets in ~7s').
    Applies exponential multiplier capped at BACKOFF_MAX_SECS.
    """
    base = BACKOFF_BASE_SECS
    match = re.search(r"resets?\s+in\s+~?(\d+)\s*s", str(exc), re.IGNORECASE)
    if match:
        base = int(match.group(1)) + 2   # +2s safety margin
    return min(float(base * (2 ** attempt)), float(BACKOFF_MAX_SECS))


# ── Replicate API call with backoff ───────────────────────────────────────────

def _call_replicate(
    client,
    model_ref: str,
    inputs: dict,
    page_number: int,
    stage_label: str,
    log: logging.Logger,
) -> bytes:
    """
    Call a Replicate model with exponential backoff on 429s.
    Returns PNG bytes on success. Raises on non-429 errors or exhausted retries.
    """
    total_wait = 0.0

    for attempt in range(BACKOFF_MAX_RETRIES):
        try:
            output = client.run(model_ref, input=inputs)
        except Exception as exc:
            if not _is_rate_limit(exc):
                log.error(
                    "%s p%02d — non-rate-limit error on attempt %d: %s",
                    stage_label, page_number, attempt + 1, exc,
                    exc_info=True,
                )
                raise

            # ── 429 rate limit ──────────────────────────────────────────────
            if attempt == BACKOFF_MAX_RETRIES - 1:
                log.error(
                    "%s p%02d — all %d retries exhausted after %.0fs total wait, giving up",
                    stage_label, page_number, BACKOFF_MAX_RETRIES, total_wait,
                )
                raise

            wait = _parse_retry_after(exc, attempt)
            hint_match = re.search(r"resets?\s+in\s+~?(\d+)\s*s", str(exc), re.IGNORECASE)
            hint_secs  = hint_match.group(1) if hint_match else "none"
            log.warning(
                "%s p%02d — 429 throttle on attempt %d/%d, "
                "backing off %.0fs (hint=%ss, base=%ds, multiplier=2^%d)",
                stage_label, page_number, attempt + 1, BACKOFF_MAX_RETRIES,
                wait, hint_secs, BACKOFF_BASE_SECS, attempt,
            )
            total_wait += wait
            time.sleep(wait)
            continue

        # ── Success — resolve output to bytes ─────────────────────────────
        if attempt > 0:
            log.info(
                "%s p%02d — succeeded on attempt %d after %.0fs total wait",
                stage_label, page_number, attempt + 1, total_wait,
            )

        return _resolve_output(output, page_number, stage_label, log)

    # Should never reach here
    raise RuntimeError(f"_call_replicate exhausted for {stage_label} p{page_number:02d}")


def _resolve_output(output, page_number: int, stage_label: str,
                    log: logging.Logger) -> bytes:
    """
    Normalise Replicate output to bytes.

    Handles all known SDK output formats:
      - SDK >= 0.25: list of FileOutput objects with .read()
      - SDK < 0.25 / dict output: {"output_paths": [obj]} where obj has .url
      - Plain URL strings returned by some model versions
    """
    import httpx

    if not output:
        raise RuntimeError(
            f"{stage_label} p{page_number:02d} — Replicate returned empty output. "
            f"output={output!r}"
        )

    log.debug(
        "%s p%02d — raw output type: %s, value preview: %.120s",
        stage_label, page_number, type(output).__name__, repr(output)[:120],
    )

    # ── Format 1: dict with "output_paths" key (older SDK, zedge/instantid) ──
    # Seen in test_replicate_instantid_v2–v5: output["output_paths"][0].url
    if isinstance(output, dict):
        paths = output.get("output_paths") or output.get("output") or []
        if paths:
            item = paths[0]
            url  = getattr(item, "url", None) or str(item)
            log.debug(
                "%s p%02d — dict output format, downloading from: %s",
                stage_label, page_number, str(url)[:80],
            )
            resp = httpx.get(str(url), timeout=120, follow_redirects=True)
            resp.raise_for_status()
            log.debug(
                "%s p%02d — downloaded %d bytes from dict output",
                stage_label, page_number, len(resp.content),
            )
            return resp.content
        raise RuntimeError(
            f"{stage_label} p{page_number:02d} — dict output has no output_paths/output key. "
            f"Keys present: {list(output.keys())}"
        )

    # ── Format 2: list/tuple of items (current SDK >= 0.25) ──────────────────
    item = output[0] if isinstance(output, (list, tuple)) else output

    # Format 2a: FileOutput object with .read() method
    if hasattr(item, "read"):
        log.debug("%s p%02d — FileOutput object, calling .read()", stage_label, page_number)
        data = item.read()
        result = data if isinstance(data, bytes) else b"".join(data)
        log.debug("%s p%02d — FileOutput read: %d bytes", stage_label, page_number, len(result))
        return result

    # Format 2b: object with .url attribute
    url = getattr(item, "url", None)
    if url:
        log.debug(
            "%s p%02d — URL attribute output, downloading from: %s",
            stage_label, page_number, str(url)[:80],
        )
        resp = httpx.get(str(url), timeout=120, follow_redirects=True)
        resp.raise_for_status()
        log.debug(
            "%s p%02d — downloaded %d bytes from URL attribute",
            stage_label, page_number, len(resp.content),
        )
        return resp.content

    # Format 2c: plain URL string
    url_str = str(item)
    if url_str.startswith("http"):
        log.debug(
            "%s p%02d — plain URL string, downloading from: %s",
            stage_label, page_number, url_str[:80],
        )
        resp = httpx.get(url_str, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        log.debug(
            "%s p%02d — downloaded %d bytes from URL string",
            stage_label, page_number, len(resp.content),
        )
        return resp.content

    raise RuntimeError(
        f"{stage_label} p{page_number:02d} — unrecognised output format. "
        f"type={type(item).__name__}, repr={repr(item)[:120]}"
    )


# ── Stage execution ────────────────────────────────────────────────────────────

def _run_stage(
    *,
    client,
    model_ref: str,
    model_name: str,
    face_bytes: bytes,
    final_prompt: str,
    expression: str,
    page_number: int,
    quality: str,
    force: bool,
    cache_dir: Path,
    out_file: Path,
    stage_label: str,
    log: logging.Logger,
) -> Optional[bytes]:
    """
    Cache-aware wrapper for one Replicate stage.

    Returns image bytes on success, None on failure.
    Writes output to both the cache and out_file.
    """
    steps = 30 if quality == "medium" else 50
    key   = _cache_key(face_bytes, final_prompt, expression, model_name, quality)

    # ── Cache lookup ───────────────────────────────────────────────────────
    if force:
        log.info("%s p%02d — CACHE BYPASS (--force true)", stage_label, page_number)
    else:
        cached = _load_cache(cache_dir, key)
        if cached:
            log.info(
                "%s p%02d — CACHE HIT  — %s (%d KB) — skipping API call",
                stage_label, page_number, key, len(cached) // 1024,
            )
            out_file.write_bytes(cached)
            return cached
        log.debug("%s p%02d — CACHE MISS — %s", stage_label, page_number, key)

    # ── Pre-flight validation of image bytes ─────────────────────────────
    if not face_bytes:
        log.error(
            "%s p%02d — face_bytes is empty or None — cannot proceed with API call. "
            "Check that the source image (Stage 1 output or original photo) "
            "was generated successfully before reaching this stage.",
            stage_label, page_number,
        )
        return None

    # Detect and log the image format being sent — helps diagnose format mismatches
    if face_bytes[:3] == b"\xff\xd8\xff":
        img_fmt = "JPEG"
    elif face_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        img_fmt = "PNG"
    elif face_bytes[:4] == b"RIFF" and face_bytes[8:12] == b"WEBP":
        img_fmt = "WEBP"
    else:
        img_fmt = "UNKNOWN"
    log.debug(
        "%s p%02d — image input: %s, %d bytes (%.1f KB)",
        stage_label, page_number, img_fmt, len(face_bytes), len(face_bytes) / 1024,
    )

    # ── API call ───────────────────────────────────────────────────────────
    log.info(
        "%s p%02d — calling Replicate (steps=%d, quality=%s, force=%s, "
        "image_fmt=%s, image_kb=%.1f)",
        stage_label, page_number, steps, quality, force,
        img_fmt, len(face_bytes) / 1024,
    )
    log.debug("%s p%02d — prompt: %.200s", stage_label, page_number, final_prompt)

    # Build model-specific input dict
    if model_name == "instantid":
        inputs = {
# zedge/instantid expects "input_image" (not "image") — verified from
            # working test versions v2/v3/v4/v5 in tests/playground/.
            # "adapter_strength" (not "adapter_strength_ratio") per model schema.
            # io.BytesIO required — Cog image loader calls .read() on the input;
            # strings/data URIs return None and crash the model.
            "input_image":               _make_image_input(face_bytes),
            "prompt":                    final_prompt,
            "negative_prompt":           NEGATIVE_PROMPT,
            "width":                     1024,
            "height":                    1024,
            "num_outputs":               1,
            "num_inference_steps":       steps,
            "guidance_scale":            7.5,
            "identitynet_strength_ratio": 0.85,
            "adapter_strength":          0.80,
            "enable_lcm":                False,
            "enhance_face_region":       True,
        }
    else:  # ip_adapter → zsxkib/instant-id-ipadapter-plus-face (SDXL)
        inputs = {
            # zsxkib/instant-id-ipadapter-plus-face input schema (SDXL):
            #   "image" — face reference (Stage 1 InstantID output when chaining).
            #   Combines InstantID face identity + IP-Adapter style in one model.
            #   "instantid_weight": face structure preservation strength (0.01–2.0).
            #   "ipadapter_weight": text prompt adherence strength (0.01–2.0).
            #   SDXL → 1024×1024 matches Stage 1 output resolution.
            #   io.BytesIO required — Cog image loader calls .read() on the value.
            "image":               _make_image_input(face_bytes),
            "prompt":              final_prompt,
            "negative_prompt":     NEGATIVE_PROMPT,
            "width":               1024,
            "height":              1024,
            "num_inference_steps": steps,
            "guidance_scale":      7.5,
            "instantid_weight":    0.80,
            "ipadapter_weight":    0.70,
        }

    t0 = time.time()
    try:
        result_bytes = _call_replicate(
            client     = client,
            model_ref  = model_ref,
            inputs     = inputs,
            page_number= page_number,
            stage_label= stage_label,
            log        = log,
        )
    except Exception as exc:
        log.error(
            "%s p%02d — FAILED after %.0fms: %s",
            stage_label, page_number, (time.time() - t0) * 1000, exc,
            exc_info=True,
        )
        return None

    gen_ms = int((time.time() - t0) * 1000)
    log.info(
        "%s p%02d — complete (%dms, %dKB)",
        stage_label, page_number, gen_ms, len(result_bytes) // 1024,
    )

    # ── Write to cache and output ──────────────────────────────────────────
    _save_cache(cache_dir, key, result_bytes, log)
    out_file.write_bytes(result_bytes)
    return result_bytes


# ── Page-level pipeline ────────────────────────────────────────────────────────

def _process_page(
    *,
    page: dict,
    client,
    face_bytes: bytes,
    stage1_bytes_precomputed: Optional[bytes],
    run_dir: Path,
    cache_dir: Path,
    quality: str,
    model: str,
    force: bool,
    log: logging.Logger,
) -> dict:
    """
    Execute the pipeline for one page.

    stage1_bytes_precomputed: cartoonized user face from the once-per-user
        InstantID call that ran before the page loop. Shared across ALL pages.
        If None, Stage 1 failed before the page loop.
    """
    pn         = page["page_number"]
    expression = page.get("expression", "neutral")
    prompt     = _build_prompt(page, expression)
    page_dir   = run_dir / f"page_{pn:02d}"
    page_dir.mkdir(parents=True, exist_ok=True)

    log.info("=" * 68)
    log.info(
        "PAGE %02d — expression=%s  angle=%s",
        pn, expression, page.get("angle", "(none)"),
    )
    log.debug("PAGE %02d — full prompt: %s", pn, prompt)

    result: dict = {
        "page_number":  pn,
        "expression":   expression,
        "angle":        page.get("angle", ""),
        "final_prompt": prompt,
        "stage_1_instantid":  {"status": "skipped", "reason": "not selected"},
        "stage_2_ip_adapter": {"status": "skipped", "reason": "not selected"},
        "stage_3_final":      {"status": "skipped", "reason": "not applicable"},
        "page_status":  "skipped",
    }

    stage1_bytes: Optional[bytes] = None
    stage2_bytes: Optional[bytes] = None

    # ── Stage 1 — InstantID (once per user, shared across all pages) ─────────
    # stage1_bytes_precomputed is computed ONCE before the page loop in main().
    # No InstantID API call happens here — just copy bytes to output folder.
    s1_file = page_dir / f"p{pn:02d}_1_instantid.png"

    if stage1_bytes_precomputed is None:
        log.error(
            "Stage 1 InstantID p%02d — stage1_bytes_precomputed is None. "
            "The once-per-user call failed before the page loop. "
            "Stage 2 and Stage 3 will be skipped for this page.",
            pn,
        )
        result["stage_1_instantid"] = {
            "status": "failed",
            "reason": "precomputed user-face bytes unavailable (Stage 1 failed before page loop)",
        }
        result["stage_2_ip_adapter"] = {"status": "skipped", "reason": "stage_1 failed"}
        result["stage_3_final"]      = {"status": "skipped", "reason": "stage_1 failed"}
        result["page_status"] = "failed"
        return result

    stage1_bytes = stage1_bytes_precomputed
    s1_file.write_bytes(stage1_bytes)
    ufc_key = _user_face_cache_key(face_bytes, quality)
    log.info(
        "Stage 1 InstantID p%02d — using shared user-face cartoonization (%dKB), "
        "key=%s — zero API calls here",
        pn, len(stage1_bytes) // 1024, ufc_key,
    )
    result["stage_1_instantid"] = {
        "status":        "success",
        "source":        "precomputed_once_per_user",
        "user_face_key": ufc_key,
        "output_file":   str(s1_file.relative_to(run_dir)),
        "output_kb":     len(stage1_bytes) // 1024,
        "generation_ms": 0,
    }

    # ── Stage 2 — IP-Adapter (chained on Stage 1 output) ──────────────────
    if model == "instantid":
        log.info(
            "Stage 2 IP-Adapter p%02d — skipped (--model instantid selected, no chaining)",
            pn,
        )
        result["stage_2_ip_adapter"] = {
            "status": "skipped",
            "reason": "--model instantid; chaining not requested",
        }
        # Stage 3 = copy of Stage 1
        s3_file = page_dir / f"p{pn:02d}_3_final.png"
        shutil.copy2(s1_file, s3_file)
        log.info(
            "Stage 3 p%02d — final written as copy of Stage 1 (%dKB)",
            pn, len(stage1_bytes) // 1024,
        )
        result["stage_3_final"] = {
            "status":      "success",
            "source":      "stage_1_instantid",
            "output_file": str(s3_file.relative_to(run_dir)),
        }
        result["page_status"] = "success"
        return result

    # model == "both" — run Stage 2 chained on Stage 1 output bytes
    log.info(
        "Stage 2 IP-Adapter p%02d — chaining on InstantID output "
        "(face_bytes = Stage 1 PNG, %d bytes, NOT the original photo)",
        pn, len(stage1_bytes),
    )
    s2_key  = _cache_key(stage1_bytes, prompt, expression, "ip_adapter", quality)
    s2_file = page_dir / f"p{pn:02d}_2_ip_adapter.png"
    t2 = time.time()

    s2_from_cache = not force and (_load_cache(cache_dir, s2_key) is not None)
    stage2_bytes = _run_stage(
        client      = client,
        model_ref   = IP_ADAPTER_MODEL,
        model_name  = "ip_adapter",
        face_bytes  = stage1_bytes,        # ← chained: Stage 1 output
        final_prompt= prompt,
        expression  = expression,
        page_number = pn,
        quality     = quality,
        force       = force,
        cache_dir   = cache_dir,
        out_file    = s2_file,
        stage_label = "Stage 2 IP-Adapter",
        log         = log,
    )
    s2_ms = int((time.time() - t2) * 1000)

    if stage2_bytes is None:
        log.error(
            "Stage 2 IP-Adapter p%02d — FAILED — "
            "Stage 1 output is preserved; Stage 3 (final) will be skipped",
            pn,
        )
        result["stage_2_ip_adapter"] = {
            "status":      "failed",
            "from_cache":  False,
            "cache_key":   s2_key,
            "input_was":   "stage_1_output",
            "generation_ms": s2_ms,
        }
        result["stage_3_final"] = {
            "status": "skipped",
            "reason": "stage_2 failed",
        }
        result["page_status"] = "partial"
        return result

    result["stage_2_ip_adapter"] = {
        "status":        "success",
        "from_cache":    s2_from_cache,
        "cache_key":     s2_key,
        "input_was":     "stage_1_output",
        "output_file":   str(s2_file.relative_to(run_dir)),
        "output_kb":     len(stage2_bytes) // 1024,
        "generation_ms": 0 if s2_from_cache else s2_ms,
    }

    # ── Stage 3 — Final (copy of Stage 2, no API call) ────────────────────
    s3_file = page_dir / f"p{pn:02d}_3_final.png"
    shutil.copy2(s2_file, s3_file)
    log.info(
        "Stage 3 p%02d — final written (copy of IP-Adapter output, %dKB)",
        pn, len(stage2_bytes) // 1024,
    )
    result["stage_3_final"] = {
        "status":      "success",
        "source":      "stage_2_ip_adapter",
        "output_file": str(s3_file.relative_to(run_dir)),
    }
    result["page_status"] = "success"
    return result


# ── Validation ─────────────────────────────────────────────────────────────────

def _validate_page_configs(configs: list, log: logging.Logger) -> bool:
    """
    Validate PAGE_CONFIGS at startup. Logs each check result.
    Returns True if valid (with warnings), False if any hard error found.
    """
    ok = True

    if not configs:
        log.error("PAGE_CONFIGS is empty — nothing to generate")
        return False

    if len(configs) > 30:
        log.error(
            "PAGE_CONFIGS has %d entries — maximum is 30. "
            "Remove %d entries before running.",
            len(configs), len(configs) - 30,
        )
        ok = False

    seen_numbers: set = set()
    for i, page in enumerate(configs):
        pn = page.get("page_number")

        if not isinstance(pn, int) or not (1 <= pn <= 30):
            log.error(
                "PAGE_CONFIGS[%d]: page_number=%r is not an integer in range 1–30",
                i, pn,
            )
            ok = False
            continue

        if pn in seen_numbers:
            log.error(
                "PAGE_CONFIGS[%d]: duplicate page_number=%d — "
                "page_number must be unique across all entries",
                i, pn,
            )
            ok = False
        seen_numbers.add(pn)

        prompt = page.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            log.error("PAGE_CONFIGS[%d] (p%02d): prompt is missing or empty", i, pn)
            ok = False

        expr = page.get("expression")
        if expr is not None and expr not in EXPRESSION_MAP:
            log.warning(
                "PAGE_CONFIGS[%d] (p%02d): unknown expression '%s' — "
                "will be replaced with 'neutral'",
                i, pn, expr,
            )
            page["expression"] = "neutral"

    if ok:
        page_nums = sorted(p["page_number"] for p in configs)
        log.info(
            "Validation passed — %d page(s) configured (page numbers: %s)",
            len(configs), page_nums,
        )
    return ok


# ── Dry-run ────────────────────────────────────────────────────────────────────

def _dry_run(
    *,
    configs: list,
    face_path: Path,
    cache_dir: Path,
    run_dir: Path,
    model: str,
    quality: str,
    force: bool,
    log: logging.Logger,
) -> int:
    """Print the full generation plan without making any API calls. Returns exit code."""
    log.info("=" * 68)
    log.info("DRY-RUN MODE — zero API calls will be made")
    log.info("=" * 68)

    face_bytes = face_path.read_bytes()
    stages_per_page = 2 if model == "both" else 1
    total_calls_if_no_cache = len(configs) * stages_per_page

    log.info("Generation plan:")
    log.info("  model          : %s", model)
    log.info("  quality        : %s (%d steps)", quality, 30 if quality == "medium" else 50)
    log.info("  force          : %s", force)
    log.info("  pages          : %d", len(configs))
    log.info("  stages/page    : %d", stages_per_page)
    log.info("  max API calls  : %d (if all cache misses)", total_calls_if_no_cache)
    log.info("  est. cost      : $%.2f (at $0.02/call, no cache hits)", total_calls_if_no_cache * 0.02)
    log.info("")

    for page in configs:
        pn         = page["page_number"]
        expression = page.get("expression", "neutral")
        prompt     = _build_prompt(page, expression)
        s1_key     = _cache_key(face_bytes, prompt, expression, "instantid", quality)
        s1_cached  = _load_cache(cache_dir, s1_key) is not None

        log.info("  Page %02d | expr=%-10s | angle=%s", pn, expression, page.get("angle", "(none)"))
        log.info("    prompt (first 120 chars): %.120s", prompt)
        log.info("    Stage 1 InstantID  cache_key=%s  cached=%s", s1_key, s1_cached)

        if model == "both":
            # Stage 2 cache key needs Stage 1 bytes — can only check if Stage 1 is cached
            if s1_cached:
                s1_bytes = _load_cache(cache_dir, s1_key)
                s2_key   = _cache_key(s1_bytes, prompt, expression, "ip_adapter", quality)
                s2_cached = _load_cache(cache_dir, s2_key) is not None
                log.info("    Stage 2 IP-Adapter cache_key=%s  cached=%s", s2_key, s2_cached)
            else:
                log.info("    Stage 2 IP-Adapter cache_key=<unknown until Stage 1 runs>  cached=unknown")
        log.info("")

    log.info("Dry-run complete — no files written, no API calls made.")
    return 0


# ── Run header / footer ────────────────────────────────────────────────────────

def _print_header(
    log: logging.Logger,
    run_id: str,
    child_name: str,
    photo_path: Path,
    model: str,
    quality: str,
    force: bool,
    dry_run: bool,
    log_path: Path,
    replicate_key: str,
    cache_dir: Path,
    run_dir: Path,
    page_numbers: list,
) -> None:
    """Log the structured run header block."""
    w = "=" * 68
    log.info(w)
    log.info("  StoryMe — AI Model Test Script")
    log.info("  Script        : %s", Path(__file__).name)
    log.info("  Spec          : SPEC-AI-TEST-001 v1.0")
    log.info("  Run timestamp : %s", run_id)
    log.info("  Python        : %s", sys.version.split()[0])
    log.info(w)
    log.info("Arguments:")
    log.info("  child_name    : %s", child_name)
    log.info("  photo         : %s", photo_path)
    log.info("  model         : %s", model)
    log.info("  quality       : %s", quality)
    log.info("  force         : %s", force)
    log.info("  dry_run       : %s", dry_run)
    log.info("  pages         : %d configured (page numbers: %s)", len(page_numbers), page_numbers)
    log.info("  log           : %s", log_path)
    log.info(w)
    log.info("Credentials:")
    masked = f"{replicate_key[:8]}...{replicate_key[-4:]}" if len(replicate_key) > 12 else "***"
    log.info("  REPLICATE_KEY : %s  (from %s)", masked, _ENV_FILE)
    log.info(w)
    log.info("Directories:")
    log.info("  Face photo    : %s  (%d bytes)", photo_path, photo_path.stat().st_size)
    log.info("  Cache dir     : %s  (%s)",
             cache_dir, "exists" if cache_dir.exists() else "will be created")
    log.info("  Output run    : %s  (%s)",
             run_dir, "exists" if run_dir.exists() else "will be created")
    log.info("  Log file      : %s", log_path)
    log.info(w)


def _print_footer(
    log: logging.Logger,
    elapsed: float,
    pages_requested: int,
    page_results: list,
    run_dir: Path,
    log_path: Path,
) -> None:
    """Log the structured run summary footer block."""
    succeeded = sum(1 for r in page_results if r.get("page_status") == "success")
    partial   = sum(1 for r in page_results if r.get("page_status") == "partial")
    failed    = sum(1 for r in page_results if r.get("page_status") == "failed")
    api_calls = sum(
        (1 if r.get("stage_1_instantid", {}).get("from_cache") is False
              and r.get("stage_1_instantid", {}).get("status") != "skipped" else 0)
        + (1 if r.get("stage_2_ip_adapter", {}).get("from_cache") is False
                and r.get("stage_2_ip_adapter", {}).get("status") == "success" else 0)
        for r in page_results
    )
    cache_hits = sum(
        (1 if r.get("stage_1_instantid", {}).get("from_cache") is True else 0)
        + (1 if r.get("stage_2_ip_adapter", {}).get("from_cache") is True else 0)
        for r in page_results
    )
    w = "=" * 68
    log.info(w)
    log.info("  ** GENERATION COMPLETE")
    log.info("  **   elapsed           : %.1f s", elapsed)
    log.info("  **   pages_requested   : %d", pages_requested)
    log.info("  **   pages_succeeded   : %d", succeeded)
    log.info("  **   pages_partial     : %d  (stage 1 ok, stage 2 failed)", partial)
    log.info("  **   pages_failed      : %d  (stage 1 failed)", failed)
    log.info("  **   api_calls_made    : %d", api_calls)
    log.info("  **   cache_hits        : %d", cache_hits)
    log.info("  **   output_dir        : %s", run_dir)
    log.info("  **   report            : %s", run_dir / "report.json")
    log.info("  **   log               : %s", log_path)
    log.info(w)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    """Entry point. Returns an exit code (0–3) as per BASE §8."""
    run_id  = datetime.now().strftime("%Y%m%d_%H%M%S")
    args    = _parse_args()
    force   = _bool_arg(args.force)
    dry_run = args.dry_run
    model   = args.model.lower()
    quality = args.quality.lower()

    # ── Resolve log path and set up logging first ──────────────────────────
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOGS_DIR / f"{run_id}_{Path(__file__).stem}.log"
    log      = _setup_logging(log_path)

    # ── Disallow --model ip_adapter (SPEC §3.1) ────────────────────────────
    if model == "ip_adapter":
        log.error(
            "The --model ip_adapter flag cannot be used standalone in this script.\n\n"
            "       This script implements a two-stage chained pipeline:\n"
            "         Stage 1 — InstantID  : cartoonizes the face from the original photo\n"
            "         Stage 2 — IP-Adapter : refines identity using Stage 1 output as input\n\n"
            "       IP-Adapter in this script is designed to receive the InstantID output\n"
            "       (a cartoon face) as its face reference — NOT the raw photo directly.\n"
            "       Running IP-Adapter alone would bypass the cartoonization step, defeat\n"
            "       the chaining purpose, and produce results incompatible with what this\n"
            "       test harness is designed to evaluate.\n\n"
            "       Valid --model values: instantid, both\n"
            "         instantid  → Stage 1 only (InstantID output is the final image)\n"
            "         both       → Stage 1 then Stage 2 chained (recommended)\n\n"
            "       If you need to test IP-Adapter with a raw photo as input, create a\n"
            "       separate script: tests/playground/scripts/ai/test_ip_adapter_raw.py"
        )
        return 1

    # ── Resolve and validate face photo path ──────────────────────────────
    child_name = args.name.strip()
    if args.photo:
        photo_path = Path(args.photo).resolve()
    else:
        photo_path = (_FACES_DIR / child_name / f"{child_name}.png").resolve()

    if not photo_path.exists():
        log.error(
            "Face photo not found: %s\n"
            "  Expected location: %s\n"
            "  Override with --photo /absolute/path/to/photo.png",
            photo_path,
            _FACES_DIR / child_name / f"{child_name}.png",
        )
        return 1

    # ── Load credentials ───────────────────────────────────────────────────
    if not _ENV_FILE.exists():
        log.error(
            "Credential file not found: %s\n"
            "  Create this file with the line:\n"
            "    REPLICATE_KEY=r8_...",
            _ENV_FILE,
        )
        return 1

    env_vars      = _read_env_file(_ENV_FILE)
    replicate_key = env_vars.get("REPLICATE_KEY", "")
    if not replicate_key:
        log.error(
            "REPLICATE_KEY is not set or empty in %s\n"
            "  Add the line:  REPLICATE_KEY=r8_...",
            _ENV_FILE,
        )
        return 1

    # ── Resolve output directories ─────────────────────────────────────────
    run_dir = (
        _OUTPUT_ROOT / child_name / "model_tests" / run_id
    ).resolve()

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log.error("Failed to create output directories: %s", exc, exc_info=True)
        return 1

    # ── Validate PAGE_CONFIGS ──────────────────────────────────────────────
    if not _validate_page_configs(PAGE_CONFIGS, log):
        return 1

    page_numbers = sorted(p["page_number"] for p in PAGE_CONFIGS)

    # ── Print run header ───────────────────────────────────────────────────
    _print_header(
        log           = log,
        run_id        = run_id,
        child_name    = child_name,
        photo_path    = photo_path,
        model         = model,
        quality       = quality,
        force         = force,
        dry_run       = dry_run,
        log_path      = log_path,
        replicate_key = replicate_key,
        cache_dir     = _CACHE_DIR,
        run_dir       = run_dir,
        page_numbers  = page_numbers,
    )

    # ── Dry-run exits here ─────────────────────────────────────────────────
    if dry_run:
        face_bytes = photo_path.read_bytes()
        return _dry_run(
            configs   = PAGE_CONFIGS,
            face_path = photo_path,
            cache_dir = _CACHE_DIR,
            run_dir   = run_dir,
            model     = model,
            quality   = quality,
            force     = force,
            log       = log,
        )

    # ── Load face photo ────────────────────────────────────────────────────
    log.info("Loading face photo: %s (%d bytes)", photo_path, photo_path.stat().st_size)
    face_bytes = photo_path.read_bytes()

    # ── Initialise Replicate client ────────────────────────────────────────
    log.info("Initialising Replicate client …")
    try:
        import replicate as _replicate
        client = _replicate.Client(api_token=replicate_key)
    except ImportError:
        log.error(
            "replicate package is not installed.\n"
            "  Run:  pip install replicate"
        )
        return 1
    log.info("Replicate client ready")

    # ── Stage 1: Once-per-user InstantID cartoonization ─────────────────────────
    # InstantID is called ONCE for this user/face/quality combination before
    # the page loop. Result is cached in cache/replicate/user_faces/ and reused
    # for ALL pages. This reduces InstantID billing to 1 call per user per run.
    # Cache invalidation: delete the file from cache/replicate/user_faces/ manually.
    t_start            = time.time()
    page_results       = []
    api_calls          = 0
    cache_hits         = 0
    stage1_precomputed = None

    ufc_key = _user_face_cache_key(face_bytes, quality)
    ufc_dir = _user_face_cache_dir(_CACHE_DIR)

    if model in ("instantid", "both"):
        log.info("=" * 68)
        log.info(
            "STAGE 1 (once-per-user) — InstantID cartoonization "
            "of user face before page loop"
        )
        log.info("  user_face_key : %s", ufc_key)
        log.info("  cache_dir     : %s", ufc_dir)

        if not force:
            stage1_precomputed = _load_user_face_cache(_CACHE_DIR, ufc_key, log)
            if stage1_precomputed:
                cache_hits += 1

        if stage1_precomputed is None:
            log.info(
                "Stage 1 (once-per-user) — CACHE MISS — calling InstantID API "
                "(this is the ONLY InstantID API call for this run)"
            )
            s1_out_file = run_dir / "stage1_user_face.png"
            stage1_precomputed = _run_stage(
                client       = client,
                model_ref    = INSTANTID_MODEL,
                model_name   = "instantid",
                face_bytes   = face_bytes,
                final_prompt = INSTANTID_NEUTRAL_PROMPT,
                expression   = "neutral",
                page_number  = 0,
                quality      = quality,
                force        = force,
                cache_dir    = _CACHE_DIR,
                out_file     = s1_out_file,
                stage_label  = "Stage 1 InstantID (user-face)",
                log          = log,
            )
            if stage1_precomputed:
                api_calls += 1
                _save_user_face_cache(_CACHE_DIR, ufc_key, stage1_precomputed, log)
            else:
                log.error(
                    "Stage 1 (once-per-user) FAILED — InstantID returned no output. "
                    "All pages will fail. Check token, model hash, and input image."
                )
        log.info(
            "Stage 1 complete — %dKB cartoonized face ready for %d page(s)",
            len(stage1_precomputed) // 1024 if stage1_precomputed else 0,
            len(PAGE_CONFIGS),
        )
        log.info("=" * 68)

    # ── Process each page ──────────────────────────────────────────────────
    for page in PAGE_CONFIGS:
        page_result = _process_page(
            page                     = page,
            client                   = client,
            face_bytes               = face_bytes,
            stage1_bytes_precomputed = stage1_precomputed,
            run_dir                  = run_dir,
            cache_dir                = _CACHE_DIR,
            quality                  = quality,
            model                    = model,
            force                    = force,
            log                      = log,
        )
        page_results.append(page_result)

        # Count API calls and cache hits from result
        for stage_key in ("stage_1_instantid", "stage_2_ip_adapter"):
            sr = page_result.get(stage_key, {})
            if sr.get("status") == "success":
                if sr.get("from_cache"):
                    cache_hits += 1
                else:
                    api_calls += 1

    elapsed = time.time() - t_start

    # ── Write report.json ──────────────────────────────────────────────────
    report = {
        "script":                "test_replicate_models.py",
        "spec":                  "SPEC-AI-TEST-001 v1.0",
        "run_id":                run_id,
        "child_name":            child_name,
        "face_photo":            str(photo_path),
        "face_hash":             hashlib.sha256(face_bytes).hexdigest()[:8],
        "model":                 model,
        "quality":               quality,
        "force":                 force,
        "total_pages_requested": len(PAGE_CONFIGS),
        "total_api_calls_made":  api_calls,
        "total_cache_hits":      cache_hits,
        "elapsed_seconds":       round(elapsed, 1),
        "pages":                 page_results,
    }
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Report written: %s", report_path)

    # ── Print run footer ───────────────────────────────────────────────────
    _print_footer(
        log             = log,
        elapsed         = elapsed,
        pages_requested = len(PAGE_CONFIGS),
        page_results    = page_results,
        run_dir         = run_dir,
        log_path        = log_path,
    )

    # ── Determine exit code ────────────────────────────────────────────────
    succeeded = sum(1 for r in page_results if r.get("page_status") == "success")
    failed    = sum(1 for r in page_results if r.get("page_status") == "failed")

    if failed == 0:
        return 0
    if succeeded == 0:
        return 3
    return 2


if __name__ == "__main__":
    sys.exit(main())

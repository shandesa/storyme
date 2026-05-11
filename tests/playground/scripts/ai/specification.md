# AI Model Test Harness — Specification
```
Document ID : SPEC-AI-TEST-001
Version     : 1.0
Inherits    : BASE_SPEC.md (SPEC-BASE-001)
Overrides   : BASE §4 — output path adds model_tests/ sub-level
              BASE §8.6 — ip_adapter disallowed as standalone mode
Adds        : §3 page config, §4 models, §5 pipeline, §6 output,
              §7 negative prompt, §8 SDXL prompt, §9 report schema
Location    : tests/playground/scripts/ai/specification.md
Script      : tests/playground/scripts/ai/test_replicate_models.py
```

---

## §1 — Purpose

`test_replicate_models.py` generates face-consistent, cartoonized, emotionally
expressive storybook character images for **manual quality inspection**.

It tests a two-model chained pipeline:

```
Stage 1 — InstantID      : original face photo  → cartoonized identity image
Stage 2 — IP-Adapter     : Stage 1 output       → final styled chained image
Stage 3 — Final          : copy of Stage 2 output (no additional API call)
```

It is fully decoupled from `ai_book_service.py` and all story JSON. Prompts are
defined directly in the script. Output is inspected manually.

---

## §2 — Dependencies

```
replicate
Pillow
python-dotenv
httpx
```

Credential variable: **`REPLICATE_KEY`** from `tests/playground/env`.
This is intentionally distinct from `REPLICATE_API_TOKEN` used by the main
pipeline to prevent accidental cross-pollution between test and production flows.

---

## §3 — Command-Line Arguments

All base behaviours from `BASE §9` (dry-run) apply.

| Argument      | Type     | Required | Default    | Description                                        |
|---------------|----------|----------|------------|----------------------------------------------------|
| `--name`      | `str`    | ✅       | —          | Child name; resolves face photo path automatically |
| `--photo`     | `str`    | ❌       | Auto       | Explicit face photo path override                  |
| `--model`     | `choice` | ❌       | `both`     | `instantid` or `both` (see §3.1)                   |
| `--quality`   | `choice` | ❌       | `medium`   | `medium` = 30 steps · `high` = 50 steps            |
| `--force`     | `str`    | ❌       | `false`    | `true` bypasses cache for all pages                |
| `--dry-run`   | flag     | ❌       | off        | Validate + print plan, zero API calls              |

**No `--pages` argument.** Page configs live in the script (see §4).

### §3.1 — `--model ip_adapter` Is Disallowed

`--model ip_adapter` is explicitly disallowed and causes an immediate exit
with code 1. The reason is logged verbosely:

```
ERROR  The --model ip_adapter flag cannot be used standalone in this script.

       This script implements a two-stage chained pipeline:
         Stage 1 — InstantID  : cartoonizes the face from the original photo
         Stage 2 — IP-Adapter : refines identity using Stage 1 output as input

       IP-Adapter in this script is designed to receive the InstantID output
       (a cartoon face) as its face reference — NOT the raw photo directly.
       Running IP-Adapter alone would bypass the cartoonization step, defeat
       the chaining purpose, and produce inconsistent results incompatible with
       what this test harness is designed to evaluate.

       Valid --model values: instantid, both
         instantid  → Stage 1 only (InstantID output is the final image)
         both       → Stage 1 then Stage 2 chained (recommended)

       If you need to test IP-Adapter with a raw photo as input, create a
       separate script: tests/playground/scripts/ai/test_ip_adapter_raw.py
```

---

## §4 — In-Script Page Configuration

Pages are defined as a Python list at the top of the script in a clearly marked
`TEST CONFIGURATION` block. The operator edits this block directly before each
test run. Maximum 30 entries.

```python
# ═══════════════════════════════════════════════════════════════════════════════
# TEST CONFIGURATION — edit this block before each run
#
# Rules:
#   - Maximum 30 entries. Script will exit at startup if this is exceeded.
#   - page_number must be a unique integer between 1 and 30.
#   - prompt must be a non-empty string describing the scene.
#   - expression must be a key in EXPRESSION_MAP, or omit entirely for "neutral".
#   - angle is optional; include if the scene requires a specific camera framing.
# ═══════════════════════════════════════════════════════════════════════════════
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
# ═══════════════════════════════════════════════════════════════════════════════
```

### Field Definitions

| Field          | Required | Type          | Description                                        |
|----------------|----------|---------------|----------------------------------------------------|
| `page_number`  | ✅       | `int` 1–30    | Unique identifier; used only for output folder name |
| `prompt`       | ✅       | `str`         | Scene description; core of the SDXL prompt         |
| `expression`   | ❌       | `str`         | Key from `EXPRESSION_MAP`; defaults to `neutral`   |
| `angle`        | ❌       | `str`         | Camera/framing hint appended to SDXL prompt        |

### Startup Validation (before any API call)

```
✓ PAGE_CONFIGS is not empty
✓ len(PAGE_CONFIGS) <= 30
✓ all page_number values are integers in range 1–30
✓ no duplicate page_number values
✓ all prompt values are non-empty strings
✓ expression (if present): key must exist in EXPRESSION_MAP
    if unknown key: log WARNING, replace with "neutral", do NOT abort
```

Log `INFO "Validation passed — {N} pages configured (page numbers: {list})"` on success.

---

## §5 — Expression Map

```python
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
```

---

## §6 — Negative Prompt

Defined as a module-level constant. Applied to every Replicate call, both
models, unconditionally. Never passed as a parameter — always read from this
constant.

```python
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
```

---

## §7 — SDXL Prompt Construction

```python
STYLE_PREFIX = (
    "pixar 3d animation style, children's storybook illustration, "
    "soft pastel color palette, warm cinematic lighting, shallow depth of field, "
    "smooth 3d render, emotionally warm, magical atmosphere, "
    "high detail, 8k resolution, masterpiece, best quality, "
    "character on left third of frame, right side intentionally soft and uncluttered"
)
```

**Assembly rule:**
```python
parts = [STYLE_PREFIX, page["prompt"], EXPRESSION_MAP[expression]]
if page.get("angle"):
    parts.append(page["angle"])
final_prompt = ", ".join(parts)
```

The final assembled prompt is:
- Logged at `DEBUG` with label `PROMPT p{N} {model}: {final_prompt}`
- Stored in full in `report.json`
- Used as input to the cache key hash (`prompt_hash8`)

---

## §8 — Model Pipeline and Chaining

### §8.1 — Overview

```
Stage 1 — InstantID
  Input  : original face photo as base64 data URI
  Output : cartoonized image with face identity preserved  →  FILE 1

Stage 2 — IP-Adapter FaceID  (chained — receives Stage 1 output, NOT original photo)
  Input  : Stage 1 output (FILE 1) as base64 data URI
  Output : final image blending InstantID identity with IP-Adapter style  →  FILE 2

Stage 3 — Final  (no API call)
  Action : copy FILE 2 bytes to FILE 3 slot with _final suffix
  Output : FILE 3  (manual inspection convenience copy)
```

### §8.2 — Why This Chaining Works

InstantID extracts and preserves face identity from the raw photo, rendering it
in Pixar/cartoon style. IP-Adapter FaceID, when given a **cartoon face** as its
reference instead of a raw realistic photo, produces output that is stylistically
coherent with the InstantID cartoon render rather than fighting the photo's
realism. The chained result is more stylistically consistent than either model
run independently.

### §8.3 — Stage 1 — InstantID

```
Model   : zedge/instantid
          version hash: ba2d5293be8794a05841a6f6eed81e810340142c3c25fab4838ff2b5d9574420
          (pinned — update hash explicitly when upgrading)

Input   : base64 data URI of original face photo
          NOT io.BytesIO — bypasses Replicate /v1/files pre-upload step,
          eliminating one extra API call and removing the /v1/files 401
          failure surface observed in run 20260506_164252.

Parameters:
  identitynet_strength_ratio : 0.85
  adapter_strength_ratio     : 0.80
  enhance_face_region        : True
  enable_lcm                 : False
  num_inference_steps        : 30 (medium) / 50 (high)
  guidance_scale             : 7.5
  width                      : 1024
  height                     : 1024
  num_outputs                : 1
  prompt                     : final_prompt (assembled per §7)
  negative_prompt            : NEGATIVE_PROMPT (§6)
```

Log on start  : `INFO  "Stage 1 InstantID  p{N} — calling Replicate (steps={steps}, force={force})"`
Log on success: `INFO  "Stage 1 InstantID  p{N} — complete ({ms}ms, {kb}KB)"`
Log on failure: `ERROR "Stage 1 InstantID  p{N} — FAILED: {exc}"` + full traceback

**On Stage 1 failure:** log `ERROR "Stage 1 failed for p{N} — Stage 2 and Stage 3
will be skipped for this page"`, mark page status `failed`, continue to next page.

### §8.4 — Stage 2 — IP-Adapter FaceID (chained)

```
Model   : lucataco/ip-adapter-sdxl-face
          version hash: 2a23d66a53db3af8fb0898a8af8c817f93bab3702a13a0a3c00e76e4fad27c7d
          (pinned — update hash explicitly when upgrading)

Input   : base64 data URI of FILE 1 (InstantID output from Stage 1)
          NOTE: this is the cartoonized face image, NOT the original photo.
          This is the core of the chaining design.

Parameters:
  ip_adapter_scale     : 0.80
  num_inference_steps  : 30 (medium) / 50 (high)
  guidance_scale       : 7.5
  width                : 1024
  height               : 1024
  num_outputs          : 1
  prompt               : same final_prompt used in Stage 1
  negative_prompt      : NEGATIVE_PROMPT (§6)
```

Log on start  : `INFO  "Stage 2 IP-Adapter p{N} — chaining on InstantID output (steps={steps})"`
Log on success: `INFO  "Stage 2 IP-Adapter p{N} — complete ({ms}ms, {kb}KB)"`
Log on failure: `ERROR "Stage 2 IP-Adapter p{N} — FAILED: {exc}"` + full traceback

**On Stage 2 failure:** mark page status `partial` (FILE 1 is saved, FILE 2 and
FILE 3 absent). Report records accurately.

### §8.5 — Stage 3 — Final

No API call. FILE 2 bytes written to `_3_final.png` slot.

Log: `INFO "Stage 3 p{N} — final written (copy of IP-Adapter output, {kb}KB)"`

### §8.6 — Single-Model Mode: `--model instantid`

| Stage   | Action                     | Output         |
|---------|----------------------------|----------------|
| Stage 1 | InstantID runs normally    | FILE 1         |
| Stage 2 | Skipped                    | absent         |
| Stage 3 | Copy of FILE 1 → FILE 3    | FILE 3         |

Log when skipping Stage 2:
`INFO "Stage 2 skipped — --model instantid selected (no chaining)"`

---

## §9 — Cache Keys for Two-Stage Pipeline

Each stage has its own independent cache entry.

```
Stage 1 cache key:
  face_hash8   = sha256(original_face_photo_bytes)[:8]
  prompt_hash8 = sha256(final_prompt.encode())[:8]
  key = f"{face_hash8}_{prompt_hash8}_{expression}_instantid_{quality}.png"

Stage 2 cache key:
  face_hash8   = sha256(stage_1_output_bytes)[:8]   ← hash of FILE 1, NOT original
  prompt_hash8 = sha256(final_prompt.encode())[:8]  ← same prompt as Stage 1
  key = f"{face_hash8}_{prompt_hash8}_{expression}_ip_adapter_{quality}.png"
```

If `--force true` regenerates Stage 1, FILE 1 bytes change, Stage 2's
`face_hash8` changes, and Stage 2's cache is automatically invalidated.
Consistency is maintained without any manual cache management.

Stage 2 is only looked up or executed if a valid Stage 1 result exists
(from cache or freshly generated). Stage 2 is never attempted with a missing
or failed Stage 1.

---

## §10 — Output Structure

```
[OVERRIDE of BASE §4 output path]

tests/playground/output/<child_name>/model_tests/<YYYYMMDD_HHMMSS>/
├── page_01/
│   ├── p01_1_instantid.png     ← Stage 1 output
│   ├── p01_2_ip_adapter.png    ← Stage 2 output (chained on Stage 1)
│   └── p01_3_final.png         ← copy of Stage 2 (final inspection image)
├── page_03/
│   ├── p03_1_instantid.png
│   ├── p03_2_ip_adapter.png
│   └── p03_3_final.png
└── report.json
```

File naming: `p{page_number:02d}_{slot}_{model}.png`
Folder naming: `page_{page_number:02d}/`

Files not generated (Stage 2 failed, or `--model instantid`) are **absent** —
never created as zero-byte placeholders. Absence is recorded in `report.json`.

---

## §11 — report.json Schema

```json
{
  "script": "test_replicate_models.py",
  "spec": "SPEC-AI-TEST-001 v1.0",
  "run_id": "20260506_170000",
  "child_name": "nikshay",
  "face_photo": "tests/playground/user_face/nikshay/nikshay.png",
  "face_hash": "a1b2c3d4",
  "model": "both",
  "quality": "medium",
  "force": false,
  "total_pages_requested": 2,
  "total_api_calls_made": 3,
  "total_cache_hits": 1,
  "elapsed_seconds": 47.2,
  "pages": [
    {
      "page_number": 1,
      "expression": "curious",
      "angle": "eye-level, medium wide shot",
      "final_prompt": "pixar 3d animation style, ...",
      "stage_1_instantid": {
        "status": "success",
        "from_cache": false,
        "cache_key": "a1b2c3d4_e5f6g7h8_curious_instantid_medium.png",
        "output_file": "page_01/p01_1_instantid.png",
        "output_kb": 187,
        "generation_ms": 21400
      },
      "stage_2_ip_adapter": {
        "status": "success",
        "from_cache": true,
        "cache_key": "f9e0d1c2_e5f6g7h8_curious_ip_adapter_medium.png",
        "input_was": "stage_1_output",
        "output_file": "page_01/p01_2_ip_adapter.png",
        "output_kb": 203,
        "generation_ms": 0
      },
      "stage_3_final": {
        "status": "success",
        "source": "stage_2_ip_adapter",
        "output_file": "page_01/p01_3_final.png"
      },
      "page_status": "success"
    }
  ]
}
```

---

## §12 — Run Header and Footer Logs

**Header** (logged at INFO at startup):
```
========================================================================
  StoryMe — AI Model Test Script
  Script        : test_replicate_models.py
  Spec          : SPEC-AI-TEST-001 v1.0
  Run timestamp : 20260506_170000
  Python        : 3.11.9
========================================================================
Arguments:
  child_name    : nikshay
  photo         : C:\...\user_face\nikshay\nikshay.png
  model         : both
  quality       : medium
  force         : false
  dry_run       : false
  pages         : 2 configured (page numbers: 1, 3)
  log           : C:\...\output\logs\20260506_170000_test_replicate_models.log
========================================================================
Credentials:
  REPLICATE_KEY : r8_IEPn...bUBX  (from C:\...\tests\playground\env)
========================================================================
Directories:
  Face photo    : C:\...\user_face\nikshay\nikshay.png  (87006 bytes)
  Cache dir     : C:\...\cache\replicate\  (exists)
  Output run    : C:\...\model_tests\20260506_170000\  (created)
  Log file      : C:\...\output\logs\20260506_170000_test_replicate_models.log
========================================================================
```

**Footer** (logged at INFO at end):
```
========================================================================
  ** GENERATION COMPLETE
  **   elapsed           : 47.2 s
  **   pages_requested   : 2
  **   pages_succeeded   : 1
  **   pages_partial     : 0   (stage 1 ok, stage 2 failed)
  **   pages_failed      : 1   (stage 1 failed)
  **   api_calls_made    : 3
  **   cache_hits        : 1
  **   output_dir        : C:\...\model_tests\20260506_170000\
  **   report            : C:\...\model_tests\20260506_170000\report.json
  **   log               : C:\...\output\logs\20260506_170000_test_replicate_models.log
========================================================================
```

---

## §13 — Explicit Non-Goals

- No PDF generation
- No story JSON loading
- No DALL-E / OpenAI image generation
- No Azure storage integration
- No background (scene-only) page generation
- No automated quality scoring — inspection is manual
- No frontend, API endpoint, or web interface
- No concurrent/parallel page generation
- No `--model ip_adapter` standalone mode (see §3.1)

# SPEC-004 — AI-Based Full Book Generation (DALL-E gpt-image-1)

**Document ID:** SPEC-004  
**Version:** 1.0  
**Date:** 2026-05-02  
**Status:** Ready for Implementation  
**Branch target:** `beta`  
**Story source:** `backend/data/stories/forest_of_smiles_v8_final.json`

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Key Design Decisions](#2-key-design-decisions)
3. [System Architecture](#3-system-architecture)
4. [Page Classification & Generation Rules](#4-page-classification--generation-rules)
5. [Data Models — Two New Azure Tables](#5-data-models--two-new-azure-tables)
6. [Storage Paths](#6-storage-paths)
7. [AI Image Generation Pipeline](#7-ai-image-generation-pipeline)
8. [Prompt Engineering Strategy](#8-prompt-engineering-strategy)
9. [Character Consistency Mechanism](#9-character-consistency-mechanism)
10. [API Endpoints](#10-api-endpoints)
11. [Caching Architecture](#11-caching-architecture)
12. [Implementation Plan — 7 Steps](#12-implementation-plan--7-steps)
13. [Test Cases](#13-test-cases)
14. [Cost Estimation](#14-cost-estimation)
15. [No-Regression Boundary](#15-no-regression-boundary)
16. [Assumptions & Decisions Log](#16-assumptions--decisions-log)

---

## 1. Problem Statement

The current pipeline generates storybook pages from **pre-rendered DALL-E cached
templates** stored at `cache/dalle/forest_of_smiles/page_NN.png`. These were
generated once and are reused for every user.

The user needs **dynamic AI generation** where:

1. All 16 pages are generated fresh using DALL-E (`gpt-image-1`).
2. The user's uploaded photo is supplied to DALL-E so the character resembles
   them (via prompt engineering — DALL-E cannot do face-swap directly).
3. Non-character pages (background-only) are generated **once globally** and
   shared across all users for the same story — no re-generation per user.
4. Character pages (with face overlay) are generated **per user** because
   the user's appearance is baked into the prompt.
5. All generated images are stored permanently and served from cache.
6. Pages 1 and 16 are **placeholder-reserved** — the generation pipeline runs
   for them but the caller is informed they should be replaced with final artwork.

---

## 2. Key Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Background pages generated **globally** (one per story, shared) | Cost: 7 background pages × $0.04 = $0.28 per story, not per user |
| D2 | Character pages generated **per user generation** | Character appearance is prompt-embedded, so unique per user |
| D3 | **First character page (p01) generated first**, then referenced in all subsequent | DALL-E image-to-image (`gpt-image-1` reference input) ensures consistency |
| D4 | User photo supplied as **prompt reference image** to DALL-E | DALL-E `gpt-image-1` supports image input; face overlay (seamlessClone) still applied afterward |
| D5 | Storage in **two new Azure Tables**: `AIBackgroundPages`, `AICharacterPages` | Separate tables match the different caching lifetimes (global vs per-user) |
| D6 | Local disk + blob storage as dual layer; DB holds blob paths | Restart-safe: blob survives App Service recycling; disk is the hot cache |
| D7 | Pages 1 and 16 are **placeholder-flagged** in the DB and response | Allows caller to swap final artwork without breaking the pipeline |
| D8 | **Non-blocking async generation** — same pattern as existing `generate_async.py` | Consistent with existing architecture |
| D9 | All new code goes in `services/ai_book_service.py` + `routes/ai_generate.py` | Zero changes to existing generation routes |

---

## 3. System Architecture

```
╔══════════════════════════════════════════════════════════════════════════╗
║                    AI Book Generation Pipeline                           ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  POST /api/v2/generate/ai-book                                           ║
║  { profile_id, story_id, generation_mode: "ai" }                        ║
║           │                                                              ║
║           ▼                                                              ║
║  ┌────────────────────────────────────────────────────────────┐          ║
║  │              AIBookService.start_generation()              │          ║
║  │                                                            │          ║
║  │  1. Load story config from forest_of_smiles_v8_final.json  │          ║
║  │  2. Resolve user photo (from kid profile or upload)        │          ║
║  │  3. Build generation plan (16 tasks, classified by type)   │          ║
║  │  4. Return generation_id immediately                       │          ║
║  └────────────────────┬───────────────────────────────────────┘          ║
║                       │ asyncio.create_task()                            ║
║                       ▼                                                  ║
║  ┌────────────────────────────────────────────────────────────┐          ║
║  │           _run_ai_book_async() — background task           │          ║
║  │                                                            │          ║
║  │  ┌─────────────────────────────────────────────────────┐   │          ║
║  │  │  PHASE 1: Background Pages (global cache)           │   │          ║
║  │  │                                                      │   │          ║
║  │  │  For each non-character page (2,4,6,8,10,12,14):    │   │          ║
║  │  │    check AIBackgroundPages table                     │   │          ║
║  │  │    ├─ HIT  → use cached blob path (FREE)            │   │          ║
║  │  │    └─ MISS → generate via DALL-E → save blob        │   │          ║
║  │  │              → insert AIBackgroundPages row         │   │          ║
║  │  └─────────────────────────────────────────────────────┘   │          ║
║  │                                                            │          ║
║  │  ┌─────────────────────────────────────────────────────┐   │          ║
║  │  │  PHASE 2: Character Page 1 (anchor page)            │   │          ║
║  │  │                                                      │   │          ║
║  │  │  Generate p01 using:                                 │   │          ║
║  │  │    • p01 final_text prompt                          │   │          ║
║  │  │    • user_photo (b64 reference image)               │   │          ║
║  │  │  → save to AICharacterPages                         │   │          ║
║  │  │  → p01_image saved as "style anchor"                │   │          ║
║  │  └─────────────────────────────────────────────────────┘   │          ║
║  │                                                            │          ║
║  │  ┌─────────────────────────────────────────────────────┐   │          ║
║  │  │  PHASE 3: Remaining Character Pages (3,5,7..15,16) │   │          ║
║  │  │                                                      │   │          ║
║  │  │  For each character page:                            │   │          ║
║  │  │    Generate using:                                   │   │          ║
║  │  │    • page final_text prompt                          │   │          ║
║  │  │    • user_photo (b64 reference)                     │   │          ║
║  │  │    • p01_image (b64 style anchor)                   │   │          ║
║  │  │  → save to AICharacterPages                         │   │          ║
║  │  └─────────────────────────────────────────────────────┘   │          ║
║  │                                                            │          ║
║  │  PHASE 4: Face overlay (existing face_pipeline_service)    │          ║
║  │  For every character page:                                  │          ║
║  │    → face_pipeline_service.process_character_page()        │          ║
║  │    → seamlessClone user face onto AI-generated template     │          ║
║  │                                                            │          ║
║  │  PHASE 5: PDF assembly (existing pdf_service)              │          ║
║  │    → 16 pages → storybook PDF                              │          ║
║  │    → save to blob + GeneratedBooks table                   │          ║
║  └────────────────────────────────────────────────────────────┘          ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## 4. Page Classification & Generation Rules

Based on `forest_of_smiles_v8_final.json`:

```
Page  │ character_present │ Type            │ Generated by        │ Cache scope
──────┼───────────────────┼─────────────────┼─────────────────────┼────────────
  1   │ true              │ CHARACTER       │ DALL-E (per user)   │ Per-generation
  2   │ false             │ BACKGROUND      │ DALL-E (global)     │ Global (story)
  3   │ true              │ CHARACTER       │ DALL-E (per user)   │ Per-generation
  4   │ false             │ BACKGROUND      │ DALL-E (global)     │ Global (story)
  5   │ true              │ CHARACTER       │ DALL-E (per user)   │ Per-generation
  6   │ false             │ BACKGROUND      │ DALL-E (global)     │ Global (story)
  7   │ true              │ CHARACTER       │ DALL-E (per user)   │ Per-generation
  8   │ false             │ BACKGROUND      │ DALL-E (global)     │ Global (story)
  9   │ true              │ CHARACTER       │ DALL-E (per user)   │ Per-generation
 10   │ false             │ BACKGROUND      │ DALL-E (global)     │ Global (story)
 11   │ true              │ CHARACTER       │ DALL-E (per user)   │ Per-generation
 12   │ false             │ BACKGROUND      │ DALL-E (global)     │ Global (story)
 13   │ true              │ CHARACTER       │ DALL-E (per user)   │ Per-generation
 14   │ false             │ BACKGROUND      │ DALL-E (global)     │ Global (story)
 15   │ true              │ CHARACTER       │ DALL-E (per user)   │ Per-generation
 16   │ true (last even)  │ CHARACTER       │ DALL-E (per user)   │ Per-generation
──────┴───────────────────┴─────────────────┴─────────────────────┴────────────

Background pages: 2, 4, 6, 8, 10, 12, 14  (7 pages — generated ONCE globally)
Character pages:  1, 3, 5, 7, 9, 11, 13, 15, 16  (9 pages — per generation)

Placeholder pages (reserved for final artwork):
  Page 1  = FRONT PLACEHOLDER  (generate + flag, caller replaces later)
  Page 16 = BACK PLACEHOLDER   (generate + flag, caller replaces later)
```

---

## 5. Data Models — Two New Azure Tables

### 5.1 AIBackgroundPages

**Purpose:** Global cache of AI-generated background pages (no character).
Generated once per story, shared across ALL users and all generations.

**Azure Table:** `AIBackgroundPages`  
**PartitionKey:** `story_id`  
**RowKey:** `page_number` (zero-padded string, e.g. `"02"`)

| Field | Type | Description |
|-------|------|-------------|
| `story_id` | string | e.g. `forest_of_smiles` |
| `page_number` | int | 2, 4, 6, 8, 10, 12, 14 |
| `story_version` | string | From JSON `version` field — invalidates cache if story updated |
| `blob_path` | string | `ai-pages/background/{story_id}/v{version}/page_{NN}.png` |
| `prompt_hash` | string | SHA256 of the final_text prompt — invalidates cache if prompt changes |
| `model` | string | `gpt-image-1` |
| `size` | string | `1024x1024` |
| `quality` | string | `medium` |
| `face_bbox` | string (JSON) | `{"x":0,"y":0,"w":0,"h":0}` — empty for background pages |
| `text_area` | string (JSON) | Extracted by GPT-4o vision |
| `generated_at` | ISO string | When generated |
| `generation_ms` | int | API call duration in ms |

**Cache invalidation rule:** If `prompt_hash` changes (story JSON updated), the
row is replaced and a new image is generated. Old blob is NOT deleted (retention).

---

### 5.2 AICharacterPages

**Purpose:** Per-user-generation character pages (with face oval for overlay).
Tied to a specific `generation_id`.

**Azure Table:** `AICharacterPages`  
**PartitionKey:** `generation_id`  
**RowKey:** `page_number` (zero-padded string)

| Field | Type | Description |
|-------|------|-------------|
| `generation_id` | string | UUID hex — ties to GenerationSessions |
| `page_number` | int | 1, 3, 5, 7, 9, 11, 13, 15, 16 |
| `story_id` | string | For lookup / audit |
| `user_mobile` | string | Owner — for access control |
| `blob_path` | string | `ai-pages/character/{gen_id}/page_{NN}.png` |
| `face_bbox` | string (JSON) | `{"x":int,"y":int,"w":int,"h":int}` — from GPT-4o vision |
| `text_area` | string (JSON) | From GPT-4o vision |
| `is_anchor` | bool | True only for page 1 — used as style reference for later pages |
| `is_placeholder` | bool | True for pages 1 and 16 — reserved for final artwork |
| `model` | string | `gpt-image-1` |
| `quality` | string | `medium` |
| `generated_at` | ISO string | When generated |
| `generation_ms` | int | API call duration |

---

## 6. Storage Paths

New blob prefixes (add to `backend/core/storage_paths.py`):

```python
def ai_background_page_path(story_id: str, story_version: str, page_number: int) -> str:
    """
    Global background page — shared across all users.
    Format: ai-pages/background/{story_id}/v{version}/page_{NN}.png
    """
    return f"ai-pages/background/{story_id}/v{story_version}/page_{page_number:02d}.png"


def ai_character_page_path(generation_id: str, page_number: int) -> str:
    """
    Per-generation character page.
    Format: ai-pages/character/{generation_id}/page_{NN}.png
    """
    return f"ai-pages/character/{generation_id}/page_{page_number:02d}.png"


def ai_character_blended_path(generation_id: str, page_number: int) -> str:
    """
    Per-generation character page after face blend (ready for PDF).
    Format: ai-pages/blended/{generation_id}/page_{NN}.png
    """
    return f"ai-pages/blended/{generation_id}/page_{page_number:02d}.png"
```

---

## 7. AI Image Generation Pipeline

### 7.1 DALL-E API Call — Background Page

```python
# No user image input — pure scene generation
response = openai_client.images.generate(
    model     = "gpt-image-1",
    prompt    = page.prompt.final_text,   # full prompt from v8_final.json
    size      = "1024x1024",
    quality   = "medium",
    n         = 1,
)
```

### 7.2 DALL-E API Call — Character Page (with user photo reference)

```python
# Character page — user photo provided as style reference
# gpt-image-1 supports image editing with a reference image
response = openai_client.images.edit(
    model   = "gpt-image-1",
    image   = open(user_photo_path, "rb"),     # user's uploaded photo
    prompt  = page.prompt.final_text,          # full prompt from v8_final.json
    size    = "1024x1024",
    quality = "medium",
    n       = 1,
)
```

### 7.3 Style Anchor — Subsequent Character Pages

```python
# Page 3+ character pages: also supply page 1 (anchor) as reference
# Use images.edit with the anchor image as base for visual consistency
response = openai_client.images.edit(
    model   = "gpt-image-1",
    image   = open(anchor_page_path, "rb"),    # page 01 image as style anchor
    prompt  = (
        page.prompt.final_text
        + "\n\nIMPORTANT: Maintain exact same character appearance, clothing, "
          "art style, color palette, and lighting as the reference image provided. "
          "Same child, same yellow t-shirt, same brown hat, same face oval placeholder."
    ),
    size    = "1024x1024",
    quality = "medium",
    n       = 1,
)
```

### 7.4 Coordinate Extraction (existing GPT-4o logic)

After every character page is generated, the existing `_extract_coordinates()`
method from `DalleService` is called to get `face_bbox` and `text_area`.
These are stored in `AICharacterPages` and passed to `face_pipeline_service`.

---

## 8. Prompt Engineering Strategy

### 8.1 Prompt sources

All prompts come directly from `forest_of_smiles_v8_final.json` → `page.prompt.final_text`.
These are already authored for `gpt-image-1` with:
- Exact face oval specification (uniform #E8C4A0, no features)
- Canvas size 1024×1024 for character pages
- Face anchor position per page (from `face_anchor` field)

No prompt engineering is added by the code — the JSON is the single source of truth.

### 8.2 Character consistency via face_anchor

Each character page in the JSON has a `face_anchor` field:
```json
"face_anchor": {
  "center": [0.4, 0.3],       // normalized center (x, y)
  "size_ratio": [0.17, 0.2],  // face oval size as fraction of image
  "rotation": {"yaw": -5, "pitch": -2, "roll": 0}
}
```

The code converts these to pixel coordinates for `face_pipeline_service`:
```python
def anchor_to_face_config(face_anchor: dict, img_w: int, img_h: int) -> dict:
    cx, cy = face_anchor["center"]
    sw, sh = face_anchor["size_ratio"]
    w = int(sw * img_w)
    h = int(sh * img_h)
    x = int(cx * img_w) - w // 2
    y = int(cy * img_h) - h // 2
    return {"x": x, "y": y, "w": w, "h": h}
```

### 8.3 Prompt hash for cache invalidation

```python
import hashlib
prompt_hash = hashlib.sha256(page.prompt.final_text.encode()).hexdigest()[:16]
```

If the story JSON is updated (new `version` field), the hash changes and the
background page is regenerated.

---

## 9. Character Consistency Mechanism

```
User uploads photo
        │
        ▼
  images.edit(image=user_photo, prompt=page1_prompt)
        │
        ▼
  Page 1 image (style anchor) ────────────────────────────────────┐
        │                                                          │
        ▼                                                          │
  Apply face blend (seamlessClone) → Page 1 blended               │
        │                                                          │
        │                                                          │
  For each subsequent character page (3, 5, 7, 9, 11, 13, 15, 16):│
        │                                                          │
        └──────────────────────────────────────────────────────────┤
                                                                   │
  images.edit(image=page_1_raw, prompt=pageN_prompt + consistency) │
        │                                                          │
        ▼                                                          │
  Page N image                                                     │
        │                                                          │
        ▼                                                          │
  Apply face blend → Page N blended                               │
        │                                                          │
        ▼                                                          │
  Repeat for next character page ◄──────────────────────────────── ┘
```

**Key insight:** We use the **raw (pre-blend) page 1 image** as the anchor,
not the blended version. The raw page has the correct art style, character
design, clothing, and lighting without the user's face distorting the reference.

---

## 10. API Endpoints

### 10.1 New route: `POST /api/v2/generate/ai-book`

```
POST /api/v2/generate/ai-book
Auth: Bearer token required

Body (multipart/form-data):
  name        string  required  — child's name
  story_id    string  optional  — default: forest_of_smiles
  profile_id  string  optional  — use stored profile photo (no upload)
  image       file    optional  — one-time photo upload (required if no profile_id)
  quality     string  optional  — medium|high (default: medium)

Response 200:
{
  "generation_id": "abc123...",
  "status":        "generating",
  "story_id":      "forest_of_smiles",
  "total_pages":   16,
  "estimated_seconds": 180,
  "background_pages_cached": 5,   // how many BG pages already in cache
  "character_pages_to_generate": 9
}
```

### 10.2 Status endpoint (reuse existing)

`GET /api/v2/generate/status/{generation_id}` — already implemented,
no changes needed. The AI book generation writes to the same
`GenerationSessions` table.

### 10.3 Background page cache info: `GET /api/v2/ai-book/cache-status`

```
GET /api/v2/ai-book/cache-status?story_id=forest_of_smiles
Auth: Bearer token required

Response:
{
  "story_id": "forest_of_smiles",
  "background_pages": {
    "total": 7,
    "cached": 5,
    "missing": [8, 10]
  },
  "story_version": "v8_final",
  "estimated_generation_cost_usd": 0.08   // only for missing pages
}
```

---

## 11. Caching Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Cache Lookup Flow                               │
│                                                                     │
│  Background page requested:                                         │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  1. Check in-memory dict (process-level hot cache)           │   │
│  │     key: (story_id, page_number, prompt_hash)                │   │
│  │     hit → return immediately (0ms)                           │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             │ miss                                   │
│                             ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  2. Check AIBackgroundPages Azure Table                      │   │
│  │     query: story_id + page_number + prompt_hash              │   │
│  │     hit → download blob → populate memory cache → return     │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             │ miss                                   │
│                             ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  3. Generate via DALL-E gpt-image-1                          │   │
│  │     → save to blob storage                                   │   │
│  │     → insert AIBackgroundPages row                           │   │
│  │     → populate memory cache                                  │   │
│  │     → return                                                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Character page: ALWAYS generate (per user) — no DB cache lookup   │
└─────────────────────────────────────────────────────────────────────┘
```

**In-memory cache implementation:**

```python
# Module-level — lives for the App Service instance lifetime
_background_page_cache: dict[str, tuple[bytes, dict]] = {}
# key: "{story_id}:{page_number}:{prompt_hash}"
# value: (image_bytes, metadata_dict)
```

---

## 12. Implementation Plan — 7 Steps

### Step 1: New storage paths

**File:** `backend/core/storage_paths.py`  
**Add:** `ai_background_page_path()`, `ai_character_page_path()`, `ai_character_blended_path()`

---

### Step 2: New data stores

**File:** `backend/core/ai_page_store.py` (new)

```
AIBackgroundPageStore (ABC)
├── AzureAIBackgroundPageStore  — Azure Table: AIBackgroundPages
└── JsonAIBackgroundPageStore   — local dev fallback

AICharacterPageStore (ABC)
├── AzureAICharacterPageStore   — Azure Table: AICharacterPages
└── JsonAICharacterPageStore    — local dev fallback

Public functions:
  get_background_page(story_id, page_number, prompt_hash) -> Optional[dict]
  save_background_page(story_id, page_number, data: dict) -> dict
  get_character_page(generation_id, page_number) -> Optional[dict]
  save_character_page(generation_id, page_number, data: dict) -> dict
  list_character_pages(generation_id) -> list[dict]
```

---

### Step 3: AI Book Service

**File:** `backend/services/ai_book_service.py` (new)

```
class AIBookService:
    Methods:
      start_generation(...)     → returns generation_id (async, fires background task)
      _run_generation(...)      → full async pipeline (background)
      _generate_background_page(page, story_version) → (bytes, meta)
      _generate_character_page(page, user_photo, anchor_bytes) → (bytes, meta)
      _load_story_config()      → parses v8_final.json
      _anchor_to_face_config()  → converts face_anchor to pixel coords
      _resolve_user_photo()     → profile blob or uploaded file → bytes

ai_book_service = AIBookService()  # singleton
```

---

### Step 4: New API route

**File:** `backend/routes/ai_generate.py` (new)

```
POST /api/v2/generate/ai-book
GET  /api/v2/ai-book/cache-status
```

---

### Step 5: Wire into server.py

**File:** `backend/server.py`  
**Add:** defensive import + `app.include_router(ai_generate_router)`

---

### Step 6: Frontend — expose AI mode option

**File:** `frontend/src/pages/HomePage.jsx`  
**Change:** Add `"ai_book"` to `GENERATION_MODES` dropdown as  
`{ value: "ai_book", label: "AI Generated (Premium)" }`

Route to `POST /api/v2/generate/ai-book` when this mode is selected.

---

### Step 7: Update documentation

**File:** `docs/specs/README.md` — add SPEC-004 entry

---

## 13. Test Cases

All tests in `backend/tests/test_ai_book_service.py`.

### TC-AI-01: Background page cache hit (no API call)

```python
def test_background_page_returns_cached_without_api_call(mock_openai):
    """Calling generate_background_page twice must not call DALL-E the second time."""
    # Pre-seed the store
    save_background_page("forest_of_smiles", 2, {
        "blob_path": "ai-pages/background/forest_of_smiles/v8_final/page_02.png",
        "prompt_hash": "abc123...",
        "face_bbox": {}, "text_area": {},
    })
    with patch("services.ai_book_service.openai_client") as mock_client:
        result = ai_book_service._get_or_generate_background_page(page_config, "v8_final")
    mock_client.images.generate.assert_not_called()
    assert result is not None
```

### TC-AI-02: Background page generated on first call

```python
def test_background_page_calls_dalle_on_cache_miss(mock_openai):
    """First time a background page is requested, DALL-E must be called."""
    mock_openai.images.generate.return_value = MockDalleResponse(b"fake_image_bytes")
    result = ai_book_service._get_or_generate_background_page(page_config, "v8_final")
    mock_openai.images.generate.assert_called_once()
    assert get_background_page("forest_of_smiles", 2, ANY) is not None  # saved to DB
```

### TC-AI-03: Character page uses user photo

```python
def test_character_page_calls_edit_with_user_photo(mock_openai):
    """Character page generation must call images.edit with user photo."""
    mock_openai.images.edit.return_value = MockDalleResponse(b"char_image_bytes")
    ai_book_service._generate_character_page(page_config, b"user_photo_bytes", anchor_bytes=None)
    call_args = mock_openai.images.edit.call_args
    assert call_args is not None
    assert "image" in call_args.kwargs or len(call_args.args) > 1
```

### TC-AI-04: Pages 3+ supply anchor image

```python
def test_subsequent_character_pages_use_anchor(mock_openai):
    """Pages 3, 5, 7... must pass the page-1 raw image as style anchor."""
    mock_openai.images.edit.return_value = MockDalleResponse(b"page_image")
    anchor_bytes = b"page01_image_bytes"
    ai_book_service._generate_character_page(page3_config, b"user_photo", anchor_bytes)
    call_args = mock_openai.images.edit.call_args
    # Anchor image must appear in the call
    assert anchor_bytes in str(call_args) or call_args.kwargs.get("image") is not None
```

### TC-AI-05: Prompt hash invalidates background cache

```python
def test_prompt_hash_change_triggers_regeneration(mock_openai):
    """If prompt changes (hash mismatch), background page must be regenerated."""
    save_background_page("forest_of_smiles", 2, {"prompt_hash": "OLD_HASH", ...})
    mock_openai.images.generate.return_value = MockDalleResponse(b"new_image")
    # Simulate story JSON update — prompt_hash will differ
    ai_book_service._get_or_generate_background_page(page_config_new_prompt, "v8_final")
    mock_openai.images.generate.assert_called_once()
```

### TC-AI-06: Pages 1 and 16 flagged as placeholders

```python
def test_pages_1_and_16_flagged_as_placeholders():
    """Pages 1 and 16 must have is_placeholder=True in AICharacterPages."""
    # Run generation on mocked DALL-E
    result_pages = [mock for mock in ai_book_service._classify_pages("forest_of_smiles")]
    p1 = next(p for p in result_pages if p.page_number == 1)
    p16 = next(p for p in result_pages if p.page_number == 16)
    assert p1.is_placeholder is True
    assert p16.is_placeholder is True
```

### TC-AI-07: face_anchor to face_config conversion

```python
def test_anchor_to_face_config_correct_pixels():
    """face_anchor normalized coords must convert to correct pixel coords."""
    anchor = {"center": [0.4, 0.3], "size_ratio": [0.17, 0.2]}
    result = anchor_to_face_config(anchor, img_w=1024, img_h=1024)
    assert result["w"] == int(0.17 * 1024)   # 174
    assert result["h"] == int(0.2  * 1024)   # 204
    assert result["x"] == int(0.4 * 1024) - result["w"] // 2  # centred
    assert result["y"] == int(0.3 * 1024) - result["h"] // 2
```

### TC-AI-08: End-to-end generation produces 16 output pages

```python
@pytest.mark.integration
def test_full_generation_produces_16_pages(mock_openai_all, mock_storage):
    """Full AI generation must produce exactly 16 page images + PDF."""
    gen_id = await ai_book_service.start_generation(
        user_mobile="9999000001",
        child_name="TestChild",
        story_id="forest_of_smiles",
        user_photo_bytes=b"fake_photo",
    )
    # Wait for background task
    await asyncio.sleep(0.1)
    pages = list_character_pages(gen_id)
    assert len(pages) == 9   # character pages
    # Background pages saved globally
    for pg in [2, 4, 6, 8, 10, 12, 14]:
        assert get_background_page("forest_of_smiles", pg, ANY) is not None
```

### TC-AI-09: DALL-E failure on single page does not abort generation

```python
def test_single_page_failure_continues_generation(mock_openai):
    """If DALL-E fails for page 5, pages 1,3,7... must still be generated."""
    mock_openai.images.edit.side_effect = [
        MockDalleResponse(b"p1"),      # page 1 OK
        RuntimeError("API timeout"),    # page 3 FAIL
        MockDalleResponse(b"p5"),      # page 5 continues
        ...
    ]
    result = await ai_book_service._run_generation(...)
    assert result["pages_succeeded"] >= 7
    assert result["pages_failed"] == [3]   # only page 3 failed
```

### TC-AI-10: No API call when OPENAI_API_KEY not set

```python
def test_raises_clear_error_when_no_api_key(monkeypatch):
    """AIBookService must raise a clear RuntimeError if OPENAI_API_KEY is absent."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        AIBookService()
```

---

## 14. Cost Estimation

Using `gpt-image-1` at $0.04/image (medium quality):

| Scenario | Images | Cost per run |
|----------|--------|-------------|
| First user (all 16 pages from scratch) | 16 | $0.64 |
| Second user, same story (7 BG cached) | 9 char + 0 BG | $0.36 |
| Nth user (all BG cached) | 9 char pages only | $0.36 |
| Background page re-generation (story updated) | 7 BG pages | $0.28 |

Plus GPT-4o vision for coordinate extraction: ~$0.01 per character page.

**Per-user marginal cost (steady state):** ~$0.37

---

## 15. No-Regression Boundary

The following are **never touched**:

| Component | Protected from change |
|-----------|----------------------|
| `POST /api/generate` (v1) | Completely untouched |
| `POST /api/v2/generate/preview` | Completely untouched |
| `POST /api/v2/generate/async` | Completely untouched |
| `face_pipeline_service.py` | Only called, never modified |
| `pdf_service.py` | Only called, never modified |
| `dalle_service.py` | Existing service preserved as-is |
| `story_json_service.py` | Not modified — v8_final.json loaded directly |
| All existing Azure Tables | No changes to existing schema |
| All existing frontend pages | Only `GENERATION_MODES` dropdown gets new entry |

---

## 16. Assumptions & Decisions Log

| # | Assumption | Impact if wrong |
|---|-----------|----------------|
| A1 | `gpt-image-1` `images.edit()` accepts a user photo and produces character consistency | May need to use `images.generate()` with photo description in prompt instead |
| A2 | Page 1 raw image (before face blend) is a sufficient style anchor | If consistency is still poor, switch to DALL-E's native seed parameter if exposed |
| A3 | `gpt-image-1` `images.edit()` is available for this API key | Fall back to `images.generate()` with descriptive character prompt |
| A4 | Background pages 2,4,6,8,10,12,14 will look consistent across users | True — they use the same prompt with no user input |
| A5 | Face overlay via `seamlessClone` works on AI-generated images (not just DALL-E cached templates) | Process is the same — face_pipeline_service does not care about template source |
| A6 | Pages 1 and 16 placeholder replacement is handled by the caller (future artwork drop-in) | If replacement never happens, the AI-generated versions are still usable |
| A7 | `1024x1024` is used for all pages (both character and background) | v8_final.json specifies `1024x819` for canvas — API call uses 1024×1024 (closest valid size); PDF renders at correct aspect ratio |

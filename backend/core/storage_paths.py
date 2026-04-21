"""
core/storage_paths.py
=====================
Single source of truth for ALL Azure Blob Storage path construction.

Design principles:
  - Every path is built by a named function — no raw string concatenation elsewhere
  - All functions are pure (no I/O) — safe to call at any time
  - Paths are idempotent: same inputs always produce the same path
  - Storage backend is abstracted — callers never know if it's local/Azure/S3

Blob Storage layout (designed for 300 stories: 100 × 3 genders):

  storyme-assets/
  │
  ├── stories/                         ← story assets (fixed, read-only in production)
  │   └── {story_id}/                  e.g. forest_of_smiles
  │       └── {gender}/                male | female | neutral
  │           ├── templates/           illustrated scene PNGs
  │           │   ├── scene_01.png
  │           │   └── scene_10.png
  │           └── references/          reference face images for alignment
  │               ├── scene_01.png
  │               └── scene_10.png
  │
  ├── uploads/                         ← transient user photos (deleted after use)
  │   └── {uuid}.{ext}
  │
  ├── generated/                       ← per-generation outputs
  │   └── {generation_id}/
  │       ├── pages/
  │       │   ├── page_01.png
  │       │   └── page_10.png
  │       └── preview/
  │           └── page_01_preview.png
  │
  └── pdfs/                            ← final PDFs (permanent, retrievable)
      └── {child_name_safe}/
          └── {story_id}/
              └── {YYYYMMDD_HHMMSS}_{uid8}.pdf

Key design decisions:
  1. story_id + gender as path segments → O(1) lookup, no scanning needed
  2. generation_id (UUID) isolates concurrent sessions → no write conflicts
  3. pdfs/{name}/{story} → retrievable by child or story for order history
  4. uploads/ are ephemeral → deleted immediately after use
  5. Face coordinates are stored in MongoDB, not in blob paths
     (coordinates change with template versions; decoupling avoids migrations)
"""

import re
import uuid
from datetime import datetime, timezone


# ─── Constants ────────────────────────────────────────────────────────────────

GENDER_MALE    = "male"
GENDER_FEMALE  = "female"
GENDER_NEUTRAL = "neutral"
VALID_GENDERS  = {GENDER_MALE, GENDER_FEMALE, GENDER_NEUTRAL}

GENERATION_MODE_OPENCV = "opencv"   # face_blend.py pipeline (default, no AI cost)
GENERATION_MODE_AI     = "ai"       # model-based image generation


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe(name: str, max_len: int = 64) -> str:
    """
    Sanitize a name for use as a blob path segment.
    Replaces non-alphanumeric characters with underscores.
    Collapses runs and strips leading/trailing underscores.
    """
    cleaned = re.sub(r"[^\w]", "_", name.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:max_len] or "unknown"


def new_generation_id() -> str:
    """Generate a new unique generation session ID."""
    return uuid.uuid4().hex


# ─── Story asset paths (templates + references) ───────────────────────────────

def story_template_path(story_id: str, gender: str, scene_filename: str) -> str:
    """
    Blob path for a story template image.

    Args:
        story_id:       e.g. "forest_of_smiles"
        gender:         "male" | "female" | "neutral"
        scene_filename: e.g. "scene_01.png"

    Returns:
        e.g. "stories/forest_of_smiles/neutral/templates/scene_01.png"
    """
    if gender not in VALID_GENDERS:
        raise ValueError(f"Invalid gender {gender!r}. Must be one of {VALID_GENDERS}")
    return f"stories/{story_id}/{gender}/templates/{scene_filename}"


def story_reference_path(story_id: str, gender: str, scene_filename: str) -> str:
    """
    Blob path for a story reference image (used for face alignment).

    Returns:
        e.g. "stories/forest_of_smiles/neutral/references/scene_01.png"
    """
    if gender not in VALID_GENDERS:
        raise ValueError(f"Invalid gender {gender!r}. Must be one of {VALID_GENDERS}")
    return f"stories/{story_id}/{gender}/references/{scene_filename}"


def story_template_prefix(story_id: str, gender: str) -> str:
    """
    Blob prefix for listing all templates of a story/gender combo.
    Use with storage.list_prefix() if implemented.
    """
    return f"stories/{story_id}/{gender}/templates/"


def story_reference_prefix(story_id: str, gender: str) -> str:
    """
    Blob prefix for listing all references of a story/gender combo.
    """
    return f"stories/{story_id}/{gender}/references/"


# ─── User upload paths ────────────────────────────────────────────────────────

def upload_path(file_ext: str, upload_id: str | None = None) -> str:
    """
    Temporary path for a user-uploaded photo.
    These are deleted immediately after generation completes.

    Args:
        file_ext:  e.g. ".jpg"
        upload_id: optional UUID hex; generated if not provided

    Returns:
        e.g. "uploads/a1b2c3d4e5f6....jpg"
    """
    uid = upload_id or uuid.uuid4().hex
    return f"uploads/{uid}{file_ext}"


# ─── Generation output paths ──────────────────────────────────────────────────

def generation_page_path(generation_id: str, page_number: int) -> str:
    """
    Blob path for a single generated page image.

    Args:
        generation_id: UUID hex for this generation session
        page_number:   1-based page number

    Returns:
        e.g. "generated/abc123.../pages/page_01.png"
    """
    return f"generated/{generation_id}/pages/page_{page_number:02d}.png"


def generation_preview_path(generation_id: str) -> str:
    """
    Blob path for the page-1 preview image shown before full generation.

    Returns:
        e.g. "generated/abc123.../preview/page_01_preview.png"
    """
    return f"generated/{generation_id}/preview/page_01_preview.png"


def generation_prefix(generation_id: str) -> str:
    """
    Blob prefix for all outputs of a generation session.
    Useful for cleanup after PDF is delivered.
    """
    return f"generated/{generation_id}/"


# ─── PDF paths ────────────────────────────────────────────────────────────────

def pdf_path(child_name: str, story_id: str, generation_id: str) -> str:
    """
    Permanent blob path for the generated PDF.

    Format:
        pdfs/{child_name}/{story_id}/{YYYYMMDD_HHMMSS}_{uid8}.pdf

    Designed for retrieval by:
        - Child name  (all books for Niku)
        - Story id    (all generations of forest_of_smiles)
        - Exact file  (a specific order's PDF)

    Args:
        child_name:    raw child name (will be sanitized)
        story_id:      e.g. "forest_of_smiles"
        generation_id: UUID hex (uid8 used as suffix)

    Returns:
        e.g. "pdfs/niku/forest_of_smiles/20260420_162530_a1b2c3d4.pdf"
    """
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    uid8 = generation_id[:8]
    safe_name  = _safe(child_name)
    safe_story = _safe(story_id)
    return f"pdfs/{safe_name}/{safe_story}/{ts}_{uid8}.pdf"


def pdf_prefix_by_child(child_name: str) -> str:
    """Blob prefix for all PDFs for a given child. For order history listing."""
    return f"pdfs/{_safe(child_name)}/"


def pdf_prefix_by_child_story(child_name: str, story_id: str) -> str:
    """Blob prefix for all PDFs for a child + story combo."""
    return f"pdfs/{_safe(child_name)}/{_safe(story_id)}/"


# ─── Print product paths ──────────────────────────────────────────────────────

def product_cover_path(product_id: str, side: str) -> str:
    """
    Blob path for a print product cover image.

    Args:
        product_id: e.g. "paperback_a4"
        side:       "front" | "back"

    Returns:
        e.g. "products/paperback_a4/front_cover.png"
    """
    if side not in ("front", "back"):
        raise ValueError(f"Invalid side {side!r}. Must be 'front' or 'back'.")
    return f"products/{product_id}/{side}_cover.png"


def product_cover_prefix(product_id: str) -> str:
    """Blob prefix for all cover images of a product."""
    return f"products/{product_id}/"

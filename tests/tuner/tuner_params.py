"""
tests/tuner/tuner_params.py
============================
All tunable parameters in face_blend_service.py.

This is the single source of truth for:
  - current parameter values (must stay in sync with face_blend_service.py)
  - search ranges for coordinate descent optimisation
  - which evaluator attributes each parameter affects

When apply_params.py patches face_blend_service.py, it updates the
CURRENT_PARAMS values here automatically so this file stays in sync.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Param:
    """One tunable parameter."""
    name:        str
    current:     Any               # current value in face_blend_service.py
    search:      list              # candidate values to try
    affects:     list[str]         # evaluator attribute names this influences
    description: str = ""
    units:       str = ""


# ─── All tunable parameters ───────────────────────────────────────────────────
#
# These map directly to constants in face_blend_service.py.
# The optimiser tries each candidate value in `search`, blends 15 samples,
# scores them, and keeps the value that produces the highest mean score.
#
# Search ranges are designed to be:
#   - Broad enough to find meaningful improvements
#   - Narrow enough that trials complete in < 2 hours
#   - Physically sensible (no extreme values that obviously look wrong)

PARAMS: list[Param] = [

    # ── Mask shape ─────────────────────────────────────────────────────────────
    # The elliptical mask that defines the face boundary in the blend.
    # rx = horizontal radius as fraction of face width
    # ry = vertical radius as fraction of face height
    # Too small → face looks like it's inside a tiny oval (face_coverage drops)
    # Too large → hard edge visible at boundary (blend_edge drops)

    Param(
        name="mask_ellipse_rx",
        current=0.42,
        search=[0.35, 0.38, 0.40, 0.42, 0.45, 0.48, 0.50],
        affects=["face_coverage", "blend_edge"],
        description="Horizontal radius of face blend ellipse as fraction of width",
        units="fraction",
    ),

    Param(
        name="mask_ellipse_ry",
        current=0.50,
        search=[0.44, 0.47, 0.50, 0.53, 0.56, 0.58],
        affects=["face_coverage", "blend_edge"],
        description="Vertical radius of face blend ellipse as fraction of height",
        units="fraction",
    ),

    # ── Mask feathering ────────────────────────────────────────────────────────
    # Gaussian blur sigma applied to the ellipse mask.
    # Higher sigma → softer edge → smoother blend but face boundary bleeds outward.
    # Lower sigma → sharper edge → less bleed but harder edge visible.
    # Kernel size is always 51×51 (large enough for any sigma in this range).

    Param(
        name="mask_blur_sigma",
        current=25,
        search=[15, 18, 21, 25, 29, 33, 37],
        affects=["blend_edge"],
        description="Gaussian blur sigma for mask feathering",
        units="pixels",
    ),

    # ── Face scale ─────────────────────────────────────────────────────────────
    # Multiplier applied to the face_config w/h before placing the face.
    # 1.0 = use face_config dimensions exactly.
    # > 1.0 = face slightly larger than allocated area (can look more natural).
    # < 1.0 = face slightly smaller (safer boundaries but may look small).

    Param(
        name="face_scale",
        current=1.0,
        search=[0.88, 0.92, 0.96, 1.00, 1.04, 1.08, 1.12],
        affects=["face_coverage"],
        description="Multiplier on face_config w/h dimensions",
        units="multiplier",
    ),

    # ── Luminance matching strength ────────────────────────────────────────────
    # How strongly the face luminance is matched to the template ROI.
    # 1.0 = full match (face brightness = template brightness).
    # 0.0 = no match (face keeps its original brightness).
    # Partial matching (0.7–0.9) often looks more natural than full (1.0)
    # because it preserves some of the face's own lighting character.

    Param(
        name="luminance_strength",
        current=1.0,
        search=[0.50, 0.65, 0.75, 0.85, 0.92, 1.00],
        affects=["lighting_match"],
        description="Strength of luminance matching to template ROI (0=none, 1=full)",
        units="fraction",
    ),

    # ── Warm tint boosts ───────────────────────────────────────────────────────
    # Applied when the template ROI is warm-toned (red channel > blue channel).
    # These multiply the respective face channels to match the scene warmth.
    # Small adjustments — 1.00 = no boost, 1.10 = 10% boost.

    Param(
        name="warm_tint_r",
        current=1.05,
        search=[1.00, 1.02, 1.04, 1.05, 1.07, 1.09],
        affects=["lighting_match"],
        description="Red channel warm tint multiplier when scene is warm-toned",
        units="multiplier",
    ),

    Param(
        name="warm_tint_g",
        current=1.02,
        search=[1.00, 1.01, 1.02, 1.03, 1.04],
        affects=["lighting_match"],
        description="Green channel warm tint multiplier when scene is warm-toned",
        units="multiplier",
    ),

    # ── Clone mode ─────────────────────────────────────────────────────────────
    # cv2.seamlessClone mode:
    # NORMAL_CLONE  — preserves texture of the source (face) — good for natural skin
    # MIXED_CLONE   — blends textures of source and destination — good for transparency
    # For face blending, NORMAL_CLONE is almost always better but MIXED_CLONE
    # can help when the scene background bleeds through the face boundary.

    Param(
        name="clone_mode",
        current="NORMAL_CLONE",
        search=["NORMAL_CLONE", "MIXED_CLONE"],
        affects=["blend_edge", "lighting_match"],
        description="cv2.seamlessClone mode",
        units="enum",
    ),
]

# Fast lookup by name
PARAM_MAP: dict[str, Param] = {p.name: p for p in PARAMS}


def current_values() -> dict:
    """Return {name: current_value} for all params."""
    return {p.name: p.current for p in PARAMS}


def update_current(name: str, value: Any) -> None:
    """Update the current value of a param (called by optimiser after a win)."""
    if name in PARAM_MAP:
        PARAM_MAP[name].current = value

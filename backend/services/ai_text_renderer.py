"""
services/ai_text_renderer.py
=============================
Renders story text directly onto storybook page images using PIL.

Text is placed in the right-side soft zone that the DALL-E prompts reserve:
  Default zone: x=634, y=65, w=368, h=687  (on 1024×1024 canvas)

Features:
  - Auto-fits font size from 28pt down to 14pt to fill available width
  - Word-wraps to text zone width
  - {name} replaced with child_name before rendering
  - White text with dark outline for readability on any background
  - Horizontal + vertical centering within the text zone
  - Pure function: input bytes → output bytes (stateless)
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ─── Default text zone (right-side soft zone on 1024×1024 canvas) ────────────
# Derived from DALL-E prompt: "Right side reserved for text (clean, softly blurred)"
# x=634 = 62% of 1024.  Zone is 36% wide × 84% tall with top/bottom padding.
DEFAULT_TEXT_ZONE = {"x": 634, "y": 65, "w": 368, "h": 687}

# ─── Font settings ────────────────────────────────────────────────────────────
_FONT_MAX_PT   = 28
_FONT_MIN_PT   = 14
_FONT_STEP_PT  = 2
_LINE_SPACING  = 1.45    # multiplier
_ZONE_PADDING  = 18      # px inside text zone edges
_TEXT_COLOUR   = (255, 255, 255, 240)   # near-white
_OUTLINE_COLOUR = (15, 15, 15, 200)     # near-black
_OUTLINE_OFFSETS = [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, -2), (0, 2), (-2, 0), (2, 0)]

# Font search order — first found is used
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",        # macOS
    "C:/Windows/Fonts/arialbd.ttf",               # Windows
]


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Load a font at the given size; fall back to PIL default if none found."""
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    logger.warning("No TrueType font found — using PIL default (rendering quality reduced)")
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = font.getbbox(test)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_text_on_image(
    image_bytes: bytes,
    story_text: str,
    child_name: str,
    text_zone: Optional[dict] = None,
) -> bytes:
    """
    Render story_text into the text zone on the image.

    Args:
        image_bytes:  Raw PNG/JPEG bytes of the source image
        story_text:   Story text, may contain {name} placeholder
        child_name:   Child's name — replaces {name}
        text_zone:    {"x", "y", "w", "h"} in pixels; defaults to DEFAULT_TEXT_ZONE

    Returns:
        PNG bytes of the image with text rendered in the zone.
    """
    zone = text_zone or DEFAULT_TEXT_ZONE
    text = story_text.replace("{name}", child_name).strip()
    if not text:
        return image_bytes

    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    # Inner zone with padding
    inner_x = zone["x"] + _ZONE_PADDING
    inner_y = zone["y"] + _ZONE_PADDING
    inner_w = zone["w"] - 2 * _ZONE_PADDING
    inner_h = zone["h"] - 2 * _ZONE_PADDING

    # Find the largest font size that fits all text vertically
    chosen_font  = None
    chosen_lines: list[str] = []
    chosen_size  = _FONT_MIN_PT

    for pt in range(_FONT_MAX_PT, _FONT_MIN_PT - 1, -_FONT_STEP_PT):
        font   = _get_font(pt)
        lines  = _wrap_text(text, font, inner_w)
        if not lines:
            continue
        # Measure total height
        sample_bbox = font.getbbox("Ag")
        line_h      = (sample_bbox[3] - sample_bbox[1]) * _LINE_SPACING
        total_h     = line_h * len(lines)
        if total_h <= inner_h:
            chosen_font  = font
            chosen_lines = lines
            chosen_size  = pt
            break

    if chosen_font is None:
        # Fallback: use minimum size regardless
        chosen_font  = _get_font(_FONT_MIN_PT)
        chosen_lines = _wrap_text(text, chosen_font, inner_w)[:4]  # max 4 lines
        if not chosen_lines:
            return image_bytes

    logger.debug(
        "ai_text_renderer: %d lines at %dpt in zone (%d,%d %dx%d)",
        len(chosen_lines), chosen_size, zone["x"], zone["y"], zone["w"], zone["h"],
    )

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    sample_bbox = chosen_font.getbbox("Ag")
    line_h      = (sample_bbox[3] - sample_bbox[1]) * _LINE_SPACING
    total_h     = line_h * len(chosen_lines)

    # Vertical centering within inner zone
    start_y = inner_y + max(0, (inner_h - total_h) / 2)

    for i, line in enumerate(chosen_lines):
        lbbox = chosen_font.getbbox(line)
        lw    = lbbox[2] - lbbox[0]
        # Left-align within inner zone
        x = inner_x
        y = start_y + i * line_h

        # Draw outline (8 directions for thickness)
        for dx, dy in _OUTLINE_OFFSETS:
            draw.text((x + dx, y + dy), line, font=chosen_font, fill=_OUTLINE_COLOUR)

        # Draw main text
        draw.text((x, y), line, font=chosen_font, fill=_TEXT_COLOUR)

    # Composite overlay onto original
    result = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="PNG", optimize=False)
    return buf.getvalue()

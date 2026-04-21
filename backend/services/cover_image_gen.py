"""
services/cover_image_gen.py
============================
Generates placeholder front and back cover images for print products.

Images are created with Pillow at startup if they don't already exist in
Azure Blob Storage. When real artwork is commissioned, the blob is simply
overwritten at the same path — no code changes needed.

Dimensions: 800 × 1200 px (2:3 portrait — standard book proportion)
Format: PNG

Design per cover type:
  Paperback front: Forest green gradient, title text, author area
  Paperback back:  Soft cream, tagline, barcode placeholder, StoryMe logo
  Hardcover front: Deep navy with gold emboss-style title
  Hardcover back:  Dark navy with gold border, description text
"""

from __future__ import annotations
import io
import logging
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

W, H = 800, 1200   # standard book proportion

# ─── Colour palettes ─────────────────────────────────────────────────────────

PALETTES = {
    "paperback": {
        "front_bg_top":    (45,  106,  79),   # forest green #2D6A4F
        "front_bg_bot":    (82,  183, 136),   # forest light #52B788
        "front_title":     (255, 255, 255),
        "front_accent":    (244, 162,  97),   # amber
        "back_bg":         (255, 253, 247),   # warm cream
        "back_text":       (27,  43,  34),    # dark forest
        "back_accent":     (45,  106,  79),
        "spine_bg":        (45,  106,  79),
    },
    "hardcover": {
        "front_bg_top":    (13,  27,  42),    # deep navy #0D1B2A
        "front_bg_bot":    (27,  43,  64),
        "front_title":     (200, 150,  62),   # gold #C8963E
        "front_accent":    (200, 150,  62),
        "back_bg":         (13,  27,  42),
        "back_text":       (200, 150,  62),
        "back_accent":     (200, 150,  62),
        "spine_bg":        (13,  27,  42),
    },
}


def _load_font(size: int):
    """Load a font. Falls back to PIL default if system fonts unavailable."""
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", size)
        except Exception:
            return ImageFont.load_default()


def _load_font_regular(size: int):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", size)
        except Exception:
            return ImageFont.load_default()


def _gradient_rect(draw: ImageDraw.Draw, y0: int, y1: int, c0: tuple, c1: tuple, x0=0, x1=W):
    """Draw a vertical gradient rectangle."""
    for y in range(y0, y1):
        t  = (y - y0) / max(y1 - y0 - 1, 1)
        r  = int(c0[0] + t * (c1[0] - c0[0]))
        g  = int(c0[1] + t * (c1[1] - c0[1]))
        b  = int(c0[2] + t * (c1[2] - c0[2]))
        draw.line([(x0, y), (x1, y)], fill=(r, g, b))


def _wrap_text(draw: ImageDraw.Draw, text: str, font, max_width: int, x: int, y: int,
               fill: tuple, line_spacing: int = 8) -> int:
    """Draw word-wrapped text. Returns the y position after last line."""
    words = text.split()
    lines = []
    line  = ""
    for word in words:
        test = f"{line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            line = test
        else:
            if line: lines.append(line)
            line = word
    if line: lines.append(line)

    cy = y
    for l in lines:
        draw.text((x, cy), l, font=font, fill=fill)
        bbox = draw.textbbox((0, 0), l, font=font)
        cy  += (bbox[3] - bbox[1]) + line_spacing
    return cy


def generate_front_cover(cover_type: str, product_id: str) -> bytes:
    """Generate front cover PNG as bytes."""
    pal  = PALETTES.get(cover_type, PALETTES["paperback"])
    img  = Image.new("RGB", (W, H), pal["front_bg_top"])
    draw = ImageDraw.Draw(img)

    # Background gradient
    _gradient_rect(draw, 0, H, pal["front_bg_top"], pal["front_bg_bot"])

    # Decorative circles (book art style)
    if cover_type == "hardcover":
        # Gold border frame
        draw.rectangle([30, 30, W-30, H-30],   outline=pal["front_accent"], width=3)
        draw.rectangle([40, 40, W-40, H-40],   outline=pal["front_accent"], width=1)
    else:
        # Abstract forest circles
        for r, alpha in [(320, 30), (260, 45), (180, 60)]:
            overlay = Image.new("RGBA", (W, H), (0,0,0,0))
            od      = ImageDraw.Draw(overlay)
            od.ellipse([W//2-r, H//2-r-100, W//2+r, H//2+r-100],
                       fill=(*pal["front_accent"], alpha))
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(img)

    # Leaf / forest icon area (simplified)
    icon_y = 160
    draw.text((W//2, icon_y), "🌿", font=_load_font(72), fill=pal["front_title"],
              anchor="mm" if hasattr(draw, "textbbox") else None)

    # Main title
    f_big   = _load_font(54)
    f_mid   = _load_font(36)
    f_small = _load_font_regular(24)

    title_y = 310
    draw.text((W//2, title_y),     "Forest of Smiles",
              font=f_big, fill=pal["front_title"], anchor="mm")
    draw.text((W//2, title_y+80),  "A Personalised Storybook",
              font=f_small, fill=(*pal["front_title"][:3],), anchor="mm")

    # Divider
    draw.line([(W//2-140, title_y+120), (W//2+140, title_y+120)],
              fill=pal["front_accent"], width=2)

    # Central illustration placeholder
    ph_y1, ph_y2 = title_y + 150, title_y + 530
    ph_x1, ph_x2 = 160, W - 160
    if cover_type == "hardcover":
        draw.rectangle([ph_x1, ph_y1, ph_x2, ph_y2],
                       outline=pal["front_accent"], width=2)
        draw.rectangle([ph_x1+8, ph_y1+8, ph_x2-8, ph_y2-8],
                       outline=(*pal["front_accent"], 100), width=1)
    else:
        draw.rounded_rectangle([ph_x1, ph_y1, ph_x2, ph_y2],
                               radius=20, outline=pal["front_accent"], width=2)

    ph_mid_x = (ph_x1 + ph_x2) // 2
    ph_mid_y = (ph_y1 + ph_y2) // 2
    draw.text((ph_mid_x, ph_mid_y - 30), "COVER ARTWORK",
              font=_load_font(20), fill=pal["front_accent"], anchor="mm")
    draw.text((ph_mid_x, ph_mid_y + 10), "COMING SOON",
              font=_load_font_regular(16), fill=(*pal["front_accent"][:3],), anchor="mm")

    # Subtitle at bottom
    sub_y = ph_y2 + 60
    draw.text((W//2, sub_y), "A story made just for your child",
              font=_load_font_regular(22), fill=pal["front_title"], anchor="mm")

    # StoryMe brand
    draw.text((W//2, H - 80), "StoryMe",
              font=_load_font(32), fill=pal["front_accent"], anchor="mm")
    draw.text((W//2, H - 45), "Personalised Children's Books",
              font=_load_font_regular(16), fill=pal["front_title"], anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generate_back_cover(cover_type: str, product_id: str) -> bytes:
    """Generate back cover PNG as bytes."""
    pal  = PALETTES.get(cover_type, PALETTES["paperback"])
    img  = Image.new("RGB", (W, H), pal["back_bg"])
    draw = ImageDraw.Draw(img)

    if cover_type == "hardcover":
        # Solid dark background with gradient header
        _gradient_rect(draw, 0, H, pal["back_bg"], tuple(max(0, c-10) for c in pal["back_bg"]))
        draw.rectangle([30, 30, W-30, H-30], outline=pal["back_accent"], width=2)
        draw.rectangle([40, 40, W-40, H-40], outline=pal["back_accent"], width=1)
    else:
        # Warm cream with top accent bar
        draw.rectangle([0, 0, W, 10], fill=pal["back_accent"])

    # Tagline
    tag_y = 90
    draw.text((W//2, tag_y), "Every child deserves their own story.",
              font=_load_font(26), fill=pal["back_accent"], anchor="mm")

    # Divider
    draw.line([(80, tag_y+50), (W-80, tag_y+50)], fill=pal["back_accent"], width=1)

    # Description text
    desc = (
        "This personalised storybook was created just for your child. "
        "Their face, their name, their adventure — all in one magical "
        "journey through the Forest of Smiles.\n\n"
        "Each story is unique, printed with love, and made to be treasured "
        "for years to come."
    )
    f_body = _load_font_regular(20)
    cy     = tag_y + 80
    for para in desc.split("\n\n"):
        cy = _wrap_text(draw, para.strip(), f_body, W - 160, 80, cy,
                        pal["back_text"], line_spacing=10)
        cy += 20

    # Story details box
    box_y1, box_y2 = cy + 30, cy + 170
    draw.rectangle([80, box_y1, W-80, box_y2], outline=pal["back_accent"], width=1)
    draw.text((W//2, box_y1+28), "Forest of Smiles",
              font=_load_font(22), fill=pal["back_accent"], anchor="mm")
    draw.text((W//2, box_y1+68), "10 story scenes  ·  Full colour  ·  Pixar-style illustrations",
              font=_load_font_regular(15), fill=pal["back_text"], anchor="mm")
    draw.text((W//2, box_y1+100), "Ages 3–6  ·  Made in India  ·  StoryMe",
              font=_load_font_regular(14), fill=pal["back_text"], anchor="mm")
    draw.text((W//2, box_y1+130), "storyme.in",
              font=_load_font(16), fill=pal["back_accent"], anchor="mm")

    # Barcode placeholder
    bc_y = H - 220
    bc_x = W // 2 - 80
    draw.rectangle([bc_x, bc_y, bc_x+160, bc_y+80], outline=pal["back_text"], width=1)
    # Simulated barcode lines
    for i in range(0, 160, 4):
        lw = 2 if i % 8 == 0 else 1
        draw.line([(bc_x+i, bc_y+8), (bc_x+i, bc_y+60)], fill=pal["back_text"], width=lw)
    draw.text((bc_x+80, bc_y+70), "9 780000 000000",
              font=_load_font_regular(12), fill=pal["back_text"], anchor="mm")

    # StoryMe footer
    draw.line([(80, H-100), (W-80, H-100)], fill=pal["back_accent"], width=1)
    draw.text((W//2, H-75), "StoryMe",
              font=_load_font(24), fill=pal["back_accent"], anchor="mm")
    draw.text((W//2, H-45), "Personalised Children's Books  ·  storyme.in",
              font=_load_font_regular(13), fill=pal["back_text"], anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ─── Upload to Azure Blob ─────────────────────────────────────────────────────

def seed_cover_images() -> None:
    """
    Generate placeholder cover images and upload to Azure Blob if not present.
    Called once at startup. Idempotent — skips blobs that already exist.
    """
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    ctr  = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "storyme-assets")
    if not conn:
        logger.info("cover_image_gen: no Azure connection — skipping cover image seed")
        return

    from azure.storage.blob import BlobServiceClient
    from core.storage_paths import product_cover_path

    svc    = BlobServiceClient.from_connection_string(conn)
    client = svc.get_container_client(ctr)

    for product_id, cover_type in [
        ("paperback_a4", "paperback"),
        ("hardcover_a4", "hardcover"),
        ("paperback_a5", "paperback"),
        ("hardcover_a5", "hardcover"),
    ]:
        for side, generator in [
            ("front", generate_front_cover),
            ("back",  generate_back_cover),
        ]:
            blob_path = product_cover_path(product_id, side)
            blob_c    = client.get_blob_client(blob_path)
            try:
                blob_c.get_blob_properties()
                logger.debug("Cover image already exists: %s", blob_path)
            except Exception:
                # Doesn't exist — generate and upload
                try:
                    data = generator(cover_type, product_id)
                    blob_c.upload_blob(data, overwrite=True)
                    logger.info("Uploaded cover image: %s (%d bytes)", blob_path, len(data))
                except Exception as ex:
                    logger.warning("Failed to upload cover %s: %s", blob_path, ex)

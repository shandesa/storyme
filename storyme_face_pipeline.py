#!/usr/bin/env python3
"""
StoryMe — Face Personalization Pipeline (Standalone)

Takes 3 inputs:
  1. template_path  — path to the illustration template image (PNG/JPG)
  2. face_path      — path to a photo containing the child's face
  3. child_name     — the child's name (replaces {name} on template)

Outputs: result.png in the current directory

Dependencies (pip install):
  pip install opencv-python pillow numpy

Usage:
  python storyme_face_pipeline.py template.png face.jpg "Shan"

What it does, step by step:
  1. FACE DETECTION — Haar Cascade finds the face bounding box
  2. TIGHT CROP    — crops just the face (10% padding), no background
  3. OVAL MASK     — applies a feathered elliptical mask so only face pixels remain
  4. CIRCLE DETECT — scans the template for the white placeholder circle automatically
  5. INPAINTING    — fills the white circle with neighbouring pixels (OpenCV Telea)
  6. COMPOSITING   — pastes the masked face onto the inpainted area; feathered edges blend naturally
  7. NAME REPLACE  — finds text lines containing {name}, inpaints them out, re-renders with actual name
  8. SAVE          — writes result.png
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Tuple, Optional, List
import sys
import os


# ======================================================================
# Font loading — tries common system font paths across OS
# ======================================================================

FONT_SEARCH_PATHS = [
    # Linux
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    # macOS
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/SFNSDisplay.ttf",
    # Windows
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
]


def load_font(size: int):
    for p in FONT_SEARCH_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ======================================================================
# 1. FACE DETECTION & EXTRACTION
# ======================================================================

def detect_face(cv_img: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """Detect the largest face. Returns (x, y, w, h) or None."""
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path)

    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    # Try standard params first
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    if len(faces) == 0:
        # Relax for harder images
        faces = detector.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(20, 20))
    if len(faces) == 0:
        return None

    # Pick largest
    return tuple(max(faces, key=lambda f: f[2] * f[3]))


def extract_face(cv_img: np.ndarray, target_size: Tuple[int, int], angle: float = 0.0) -> Image.Image:
    """
    Detect face → tight crop → resize → feathered oval mask.
    Returns RGBA PIL Image ready for compositing.
    """
    bbox = detect_face(cv_img)

    if bbox is not None:
        x, y, w, h = bbox
        # Tight padding: 10% sides, 15% top (forehead), 5% bottom (chin)
        pw = int(w * 0.10)
        ph_top = int(h * 0.15)
        ph_bot = int(h * 0.05)
        x1 = max(0, x - pw)
        y1 = max(0, y - ph_top)
        x2 = min(cv_img.shape[1], x + w + pw)
        y2 = min(cv_img.shape[0], y + h + ph_bot)
        crop = cv_img[y1:y2, x1:x2]
        print(f"  Face detected at ({x}, {y}, {w}, {h}) — tight crop applied")
    else:
        print("  No face detected — using center square crop as fallback")
        ih, iw = cv_img.shape[:2]
        d = min(iw, ih)
        cx, cy = iw // 2, ih // 2
        r = d // 2
        crop = cv_img[cy - r:cy + r, cx - r:cx + r]

    # Convert BGR→RGB→PIL RGBA
    face_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(face_rgb).convert("RGBA")
    pil = pil.resize(target_size, Image.Resampling.LANCZOS)

    # Rotate if needed (for templates where the character's head is tilted)
    if angle != 0.0:
        pil = pil.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)

    # Feathered oval mask — only face pixels survive, edges fade smoothly
    w_t, h_t = target_size
    mask = Image.new("L", (w_t, h_t), 0)
    draw = ImageDraw.Draw(mask)
    margin = int(min(w_t, h_t) * 0.06)
    draw.ellipse((margin, margin, w_t - margin, h_t - margin), fill=255)
    blur_radius = max(8, int(min(w_t, h_t) * 0.08))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    pil.putalpha(mask)

    return pil


# ======================================================================
# 2. TEMPLATE ANALYSIS — auto-detect white circle
# ======================================================================

def find_white_circle(template_arr: np.ndarray, white_threshold: int = 225) -> Optional[Tuple[int, int, int]]:
    """
    Scan template for the largest white circular region.
    Returns (center_x, center_y, radius) or None.
    """
    h, w = template_arr.shape[:2]

    # Find white pixels
    white = (
        (template_arr[:, :, 0] > white_threshold) &
        (template_arr[:, :, 1] > white_threshold) &
        (template_arr[:, :, 2] > white_threshold)
    ).astype(np.uint8) * 255

    # Find contours of white regions
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Find the most circular large contour
    best = None
    best_score = 0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 500:  # too small
            continue
        perimeter = cv2.arcLength(cnt, True)
        if perimeter == 0:
            continue
        # Circularity score: 4π·area / perimeter²  (1.0 = perfect circle)
        circularity = (4 * np.pi * area) / (perimeter * perimeter)
        if circularity > 0.6 and area > best_score:
            best = cnt
            best_score = area

    if best is None:
        return None

    # Fit minimum enclosing circle
    (cx, cy), radius = cv2.minEnclosingCircle(best)
    cx, cy, radius = int(cx), int(cy), int(radius)
    print(f"  White circle found: center=({cx}, {cy}), radius={radius}")
    return (cx, cy, radius)


# ======================================================================
# 3. INPAINTING — fill white circle with surrounding pixels
# ======================================================================

def inpaint_white_circle(template: Image.Image, cx: int, cy: int, radius: int) -> Image.Image:
    """Replace white pixels inside the circle with neighbouring pixel colours."""
    cv_img = cv2.cvtColor(np.array(template.convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = cv_img.shape[:2]

    ys = np.arange(max(0, cy - radius), min(h, cy + radius))
    xs = np.arange(max(0, cx - radius), min(w, cx + radius))
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

    region = cv_img[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1]
    inside = dist <= radius
    is_white = (region[:, :, 0] > 225) & (region[:, :, 1] > 225) & (region[:, :, 2] > 225)
    mask_local = (inside & is_white).astype(np.uint8) * 255

    full_mask = np.zeros((h, w), dtype=np.uint8)
    full_mask[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1] = mask_local

    white_count = full_mask.sum() // 255
    if white_count > 0:
        print(f"  Inpainting {white_count} white pixels inside circle...")
        inpainted = cv2.inpaint(cv_img, full_mask, 12, cv2.INPAINT_TELEA)
        rgb = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
        result = Image.fromarray(rgb).convert("RGBA")
        return result

    return template.convert("RGBA")


# ======================================================================
# 4. COMPOSITING — paste face onto inpainted template
# ======================================================================

def composite_face(template: Image.Image, face: Image.Image, cx: int, cy: int, radius: int) -> Image.Image:
    """
    1. Inpaint the white circle
    2. Paste the feathered face on top — edges blend with the inpainted background
    """
    # Step 1: fill white circle with surroundings
    template = inpaint_white_circle(template, cx, cy, radius)

    # Step 2: size face to fill 92% of circle diameter
    face_diam = int(radius * 2 * 0.92)
    face_resized = face.resize((face_diam, face_diam), Image.Resampling.LANCZOS)

    px = cx - face_diam // 2
    py = cy - face_diam // 2

    template.paste(face_resized, (px, py), face_resized)
    print(f"  Face composited at ({px}, {py}), diameter={face_diam}")
    return template


# ======================================================================
# 5. NAME TEXT REPLACEMENT
# ======================================================================

def find_text_lines(template_arr: np.ndarray, search_y_range=(0, None), search_x_range=(0, None), lum_threshold=140):
    """
    Find horizontal text lines in a region of the template.
    Returns list of (y_start, y_end, x_start, x_end) for each line.
    """
    h, w = template_arr.shape[:2]
    y_lo = search_y_range[0]
    y_hi = search_y_range[1] if search_y_range[1] else h
    x_lo = search_x_range[0]
    x_hi = search_x_range[1] if search_x_range[1] else w

    gray = 0.299 * template_arr[:, :, 0] + 0.587 * template_arr[:, :, 1] + 0.114 * template_arr[:, :, 2]

    lines = []
    current = None

    for y in range(y_lo, y_hi):
        dark_count = (gray[y, x_lo:x_hi] < lum_threshold).sum()
        if dark_count > 10:
            if current is None:
                current = {"y_start": y, "y_end": y}
            else:
                current["y_end"] = y
        else:
            if current and (current["y_end"] - current["y_start"]) > 6:
                # find x extent
                sub = gray[current["y_start"]:current["y_end"] + 1, x_lo:x_hi]
                dark_cols = np.where(sub.min(axis=0) < lum_threshold)[0]
                if len(dark_cols) > 0:
                    current["x_start"] = int(dark_cols[0]) + x_lo
                    current["x_end"] = int(dark_cols[-1]) + x_lo
                    lines.append(current)
            current = None

    if current and (current["y_end"] - current["y_start"]) > 6:
        sub = gray[current["y_start"]:current["y_end"] + 1, x_lo:x_hi]
        dark_cols = np.where(sub.min(axis=0) < lum_threshold)[0]
        if len(dark_cols) > 0:
            current["x_start"] = int(dark_cols[0]) + x_lo
            current["x_end"] = int(dark_cols[-1]) + x_lo
            lines.append(current)

    return lines


def replace_name_in_line(img: Image.Image, x1, y1, x2, y2, full_text: str, name: str, color=(80, 60, 30)):
    """Inpaint a text line, then re-render it with {name} replaced."""
    region_h = y2 - y1
    auto_size = max(int(region_h * 0.72), 10)

    # Inpaint to remove original text
    cv_img = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    local = cv_img[y1:y2, x1:x2]
    gray_local = cv2.cvtColor(local, cv2.COLOR_BGR2GRAY)
    text_mask = (gray_local < 160).astype(np.uint8) * 255
    kernel = np.ones((3, 3), np.uint8)
    text_mask = cv2.dilate(text_mask, kernel, iterations=1)

    full_mask = np.zeros(cv_img.shape[:2], dtype=np.uint8)
    full_mask[y1:y2, x1:x2] = text_mask

    if full_mask.sum() > 0:
        inpainted = cv2.inpaint(cv_img, full_mask, 6, cv2.INPAINT_TELEA)
        rgb = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
        img_arr = np.array(img.convert("RGB"))
        img_arr[y1:y2, x1:x2] = rgb[y1:y2, x1:x2]
        img.paste(Image.fromarray(img_arr).convert("RGBA"))

    # Re-render with name substituted
    render_text = full_text.replace("{name}", name)
    draw = ImageDraw.Draw(img)
    font = load_font(auto_size)

    bbox = draw.textbbox((0, 0), render_text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = x1
    ty = (y1 + y2) // 2 - th // 2

    draw.text((tx, ty), render_text, font=font, fill=(*color, 255))
    print(f"  Text line replaced: '{render_text}' at ({tx}, {ty}), font_size={auto_size}")


# ======================================================================
# 6. MAIN PIPELINE
# ======================================================================

def process(template_path: str, face_path: str, child_name: str, output_path: str = "result.png",
            text_lines_with_name: Optional[List[dict]] = None,
            text_color: Tuple[int, int, int] = (80, 60, 30)):
    """
    Full pipeline:
      template_path — path to illustration template (PNG/JPG)
      face_path     — path to photo with child's face
      child_name    — replaces {name} in template text
      output_path   — where to save the result (default: result.png)

      text_lines_with_name — optional list of dicts:
          [{"y_start": 110, "y_end": 150, "x_start": 146, "x_end": 676,
            "line_text": "{name} and the Forest of Smiles"}, ...]
          If not provided, the pipeline will auto-detect text lines and
          attempt replacement on any line that might contain {name}.

      text_color — RGB tuple for rendered text (default: dark brown)
    """

    print(f"\n{'='*60}")
    print(f"StoryMe Face Personalization Pipeline")
    print(f"{'='*60}")
    print(f"  Template : {template_path}")
    print(f"  Face     : {face_path}")
    print(f"  Name     : {child_name}")
    print(f"  Output   : {output_path}")
    print()

    # --- Load images ---
    print("[1/6] Loading images...")
    template_cv = cv2.imread(template_path)
    face_cv = cv2.imread(face_path)
    if template_cv is None:
        raise FileNotFoundError(f"Cannot load template: {template_path}")
    if face_cv is None:
        raise FileNotFoundError(f"Cannot load face image: {face_path}")

    template_pil = Image.open(template_path).convert("RGBA")
    th, tw = template_cv.shape[:2]
    print(f"  Template size: {tw}x{th}")
    print(f"  Face image size: {face_cv.shape[1]}x{face_cv.shape[0]}")

    # --- Detect white circle on template ---
    print("\n[2/6] Scanning template for face placeholder circle...")
    circle = find_white_circle(template_cv)

    if circle is None:
        print("  WARNING: No white circle found. Face will be pasted at center.")
        cx, cy = tw // 2, th // 2
        radius = min(tw, th) // 6
    else:
        cx, cy, radius = circle

    # --- Extract face ---
    print("\n[3/6] Detecting and extracting face...")
    target_size = (radius * 2, radius * 2)
    face_pil = extract_face(face_cv, target_size)

    # --- Composite face into template ---
    print("\n[4/6] Compositing face into template (inpaint + blend)...")
    result = composite_face(template_pil, face_pil, cx, cy, radius)

    # --- Replace {name} text ---
    print("\n[5/6] Replacing {name} text...")
    if text_lines_with_name:
        # Use provided line definitions
        for tl in text_lines_with_name:
            replace_name_in_line(
                result,
                tl["x_start"], tl["y_start"], tl["x_end"], tl["y_end"],
                tl["line_text"], child_name, color=text_color
            )
    else:
        # Auto-detect: just overlay name below the face circle as a label
        # For precise text replacement, pass text_lines_with_name explicitly
        print("  No text_lines_with_name provided — overlaying name below face.")
        draw = ImageDraw.Draw(result)
        font = load_font(max(radius // 3, 20))
        bbox = draw.textbbox((0, 0), child_name, font=font)
        tw_text = bbox[2] - bbox[0]
        name_x = cx - tw_text // 2
        name_y = cy + radius + 10
        # White outline for readability
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                if dx or dy:
                    draw.text((name_x + dx, name_y + dy), child_name, font=font, fill=(255, 255, 255, 255))
        draw.text((name_x, name_y), child_name, font=font, fill=(*text_color, 255))
        print(f"  Name '{child_name}' overlaid at ({name_x}, {name_y})")

    # --- Save ---
    print(f"\n[6/6] Saving result...")
    rgb = Image.new("RGB", result.size, (255, 255, 255))
    rgb.paste(result, mask=result.split()[3] if result.mode == "RGBA" else None)
    rgb.save(output_path, quality=95)
    file_size = os.path.getsize(output_path)
    print(f"  Saved: {output_path} ({file_size / 1024:.0f} KB)")

    print(f"\n{'='*60}")
    print(f"Done! Open {output_path} to see the result.")
    print(f"{'='*60}\n")

    return output_path


# ======================================================================
# CLI entry point
# ======================================================================

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("""
Usage:
  python storyme_face_pipeline.py <template_image> <face_image> <child_name> [output_path]

Example:
  python storyme_face_pipeline.py template.png face.jpg "Shan"
  python storyme_face_pipeline.py template.png face.jpg "Shan" output.png

Arguments:
  template_image — The illustration template with a white circle face placeholder
  face_image     — A photo containing the child's face
  child_name     — The name to replace {name} in the template text
  output_path    — (optional) Where to save the result. Default: result.png

Requirements:
  pip install opencv-python pillow numpy

For precise text replacement, use as a library:

  from storyme_face_pipeline import process

  process(
      "template.png", "face.jpg", "Shan",
      text_lines_with_name=[
          {"y_start": 110, "y_end": 150, "x_start": 146, "x_end": 676,
           "line_text": "{name} and the Forest of Smiles"},
          {"y_start": 172, "y_end": 208, "x_start": 197, "x_end": 616,
           "line_text": '"Hello {name}! Welcome to'},
      ],
      text_color=(134, 105, 54),
  )
""")
        sys.exit(1)

    template = sys.argv[1]
    face = sys.argv[2]
    name = sys.argv[3]
    out = sys.argv[4] if len(sys.argv) > 4 else "result.png"

    process(template, face, name, out)

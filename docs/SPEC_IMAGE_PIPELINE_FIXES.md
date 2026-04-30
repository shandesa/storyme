# StoryMe — Image Overlay & PDF Layout Fix Specification

**Version:** 1.0  
**Date:** 2026-04-30  
**Branch target:** `beta`  
**Author:** Based on visual inspection of `niku_20260430_173211_7cce1b11.pdf`

---

## 0. Diagnostic Summary

Three independent bugs were identified from the generated PDF. Each bug has a
separate root cause and a separate fix. They must be fixed independently and
tested independently.

| # | Bug | Root cause file | Severity |
|---|-----|----------------|----------|
| B1 | Face pasted onto wrong region — appears on elephant, background, wrong character | `face_pipeline_service.py` `_extract_and_align_face()` + `_blend_face_into_template()` | Critical |
| B2 | Story text is tiny (6-14px tall), rendered inside the 1024×1024 image area instead of below it | `face_pipeline_service.py` `_overlay_text()` + `_fit_font()` | Critical |
| B3 | Expression is always the user's neutral selfie expression — expression morph has no visible effect | `face_pipeline_service.py` `_apply_expression_morph()` | High |

---

## 1. Bug B1 — Face Placed on Wrong Region

### 1.1 Observed Behaviour

- Page 1: user face blended onto character's face. Size is ~40% too small. Positioned correctly but misaligned vertically (appears in upper-left quadrant of the character's large round head oval).
- Page 5: user face appears on the **elephant's forehead**, not on the child character at all.
- Page 4: user face blended onto character but the character's head is sideways; face is wrongly positioned.
- General: face is always visually "pasted" — it does not blend naturally. Hard edge visible on all pages.

### 1.2 Root Cause Analysis

**Root cause 1 — `_extract_and_align_face()` canvas size mismatch.**

```python
# CURRENT (wrong)
aligned = align_face_to_canonical(user_img, user_pts, target_size=(tw, th))
```

`target_size=(tw, th)` is the **template image size** (1024×1024). The canonical
positions in `face_blend_service.CANONICAL_POSITIONS` are normalised to a
1:1 face bounding box, not a full scene canvas. The face is warped onto a 1024×1024
canvas but only the tiny convex hull region is extracted, so the extracted face crop
is from an incorrectly warped image. The face ends up at arbitrary positions on
the scene.

**Fix:** Warp into a square face-only canvas sized proportionally to the detected
face bounding box, not the full template.

**Root cause 2 — `_blend_face_into_template()` mask too small.**

```python
# CURRENT (wrong)
ax = max(1, int(target_w * 0.44))
ay = max(1, int(target_h * 0.48))
```

The elliptical mask covers only 44%×48% of the face region. This leaves a
visible hard rectangular boundary around the blended face, especially on
Pixar-style illustrated backgrounds where the colour difference is high.

**Root cause 3 — `seamlessClone` center point calculation error.**

```python
# CURRENT (wrong)
center = (x + w // 2, y + h // 2)
```

`x, y, w, h` are the **target placement** coordinates. But `seamlessClone`'s
`center` parameter must be the centre of the **source canvas** where the face
pixels are, not the face_config placement. When the face is smaller than the
config region (scaled by 0.92), the actual pixel centroid is offset from the
config centre, causing the Poisson solve to converge at the wrong position.

### 1.3 Specification — Fix B1

#### B1-F1: Fix `_extract_and_align_face()`

File: `backend/services/face_pipeline_service.py`  
Method: `_extract_and_align_face(self, image: np.ndarray)`

**Current behaviour:** calls `align_face_to_canonical(user_img, user_pts, target_size=(tw, th))`
where `tw, th` is the template size. This is wrong.

**Required behaviour:**
1. Detect landmarks on the original user image.
2. Compute the face bounding box from the convex hull of all 468 landmarks.
3. Add padding: `top = 55%` of face height (for forehead/hair), `sides = 20%`, `bottom = 15%`.
4. Crop to the padded bounding box. This is the `face_canvas`.
5. Re-detect landmarks on `face_canvas`.
6. Return `(face_canvas, landmarks_in_canvas)`.

**Do NOT warp into the template canvas.** The face crop is sized relative to the
face itself. Resizing to `face_config {w, h}` happens in Step 4 of
`process_character_page`, which is correct.

**Pseudocode:**
```python
def _extract_and_align_face(self, image):
    pts = self._detect_landmarks(image)
    if pts is None:
        return None, None

    ih, iw = image.shape[:2]
    hull   = cv2.convexHull(pts)
    x, y, fw, fh = cv2.boundingRect(hull)

    pad_top    = int(fh * 0.55)
    pad_side   = int(fw * 0.20)
    pad_bottom = int(fh * 0.15)

    x0 = max(0, x - pad_side)
    y0 = max(0, y - pad_top)
    x1 = min(iw, x + fw + pad_side)
    y1 = min(ih, y + fh + pad_bottom)

    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        return None, None

    crop_pts = self._detect_landmarks(crop)
    return crop, crop_pts
```

**Roll-alignment (keep existing):** Apply the existing `cv2.getRotationMatrix2D`
roll-alignment to the crop before re-detecting, so the face is level.

---

#### B1-F2: Fix `_blend_face_into_template()` mask axes

File: `backend/services/face_pipeline_service.py`  
Method: `_blend_face_into_template()`

**Required change — mask axes:**
```python
# CHANGE FROM:
ax = max(1, int(target_w * 0.44))
ay = max(1, int(target_h * 0.48))

# CHANGE TO:
ax = max(1, int(target_w * 0.50))   # wider — covers full face width
ay = max(1, int(target_h * 0.55))   # taller — covers chin and forehead
```

**Required change — Gaussian blur radius:**
```python
# CHANGE FROM:
mask = cv2.GaussianBlur(mask, (31, 31), 15)

# CHANGE TO:
mask = cv2.GaussianBlur(mask, (51, 51), 20)   # softer feather
```

---

#### B1-F3: Fix `seamlessClone` center calculation

File: `backend/services/face_pipeline_service.py`  
Method: `_blend_face_into_template()`

**Required change:**
```python
# CHANGE FROM:
center = (x + w // 2, y + h // 2)

# CHANGE TO:
# Center must be the centroid of non-zero mask pixels on the full canvas
nz = cv2.findNonZero(canvas_mask)
if nz is None:
    return template  # guard
cx = int(nz[:, 0, 0].mean())
cy = int(nz[:, 0, 1].mean())
center = (cx, cy)
```

This ensures the Poisson solve is anchored exactly where pixels exist, regardless
of the 0.92 scale factor or clamping to canvas bounds.

---

## 2. Bug B2 — Text Too Small and Wrong Position

### 2.1 Observed Behaviour

- Text appears as tiny 6–16px-high region at the **bottom of the PDF page**
  (rows 534–563 of the 792px page), not inside or below the illustrated image.
- Text is rendering **inside the 1024×1024 template image space** at pixel
  coordinates like `x=610, y=100, w=390, h=800`. At 72dpi, the 1024px-wide
  template maps to ~473px wide on the PDF page. The text at `x=610` is
  **outside the right edge** of the image as rendered.
- The `_fit_font()` method starts at size 32 and tries to fit in `w=390, h=800`
  px in template space. But the actual readability requires the text to be
  rendered in the PDF page coordinate system (letter size, 612×792 points),
  **below** the image, at a large readable font size.

### 2.2 Root Cause Analysis

**Two separate sub-bugs:**

**Sub-bug B2a — Text overlay in wrong coordinate system.**

`face_pipeline_service._overlay_text()` renders text into the 1024×1024 PNG
using `text_area` coordinates like `{x: 610, y: 100, w: 390, h: 800}`. These
are designed for a right-hand side text column on a **landscape layout** (image
left, text right). But the DALL-E templates are 1024×1024 **square** images.
Text at `x=610` is at the right ~40% of the image, but this region contains
scene content (trees, animals), not a clean text column. Result: unreadable tiny
text overlaid on illustrated content.

**Sub-bug B2b — PDF layout puts text below already-text-overlaid image.**

`pdf_service.create_storybook_pdf()` renders the PNG at `6×6 inch` and then
adds a `Paragraph` with `fontSize=14` below it. So the PDF has **two** text
layers: the tiny baked-in text on the PNG, and the 14pt text below. At 72dpi,
14pt text is readable, but the image text is not.

**The correct architecture for text:**
- The 1024×1024 PNG should be a **pure illustration** — no text baked in.
- Story text belongs **exclusively in the PDF layer** via `pdf_service`,
  rendered at a minimum 22pt with proper line spacing.
- `face_pipeline_service._overlay_text()` should be **disabled** — it must not
  write any text onto the image.
- `pdf_service` should render the image filling the full page width and put
  story text in a styled block below, or in a dedicated text area on the page.

### 2.3 Specification — Fix B2

#### B2-F1: Remove text overlay from `face_pipeline_service`

File: `backend/services/face_pipeline_service.py`

**Required change in `process_character_page()`:**
```python
# REMOVE this call entirely:
output = self._overlay_text(output, story_lines, text_area, child_name)

# The output PNG is the pure blended illustration.
# story_lines and text_area are no longer used by this method.
```

**Required change in `process_text_only_page()`:**
```python
# REMOVE this call:
output = self._overlay_text(template, story_lines, text_area, child_name)

# Just save the raw template:
Path(output_path).parent.mkdir(parents=True, exist_ok=True)
cv2.imwrite(output_path, template)
```

**Keep** `_overlay_text`, `_fit_font`, `_wrap_text`, `_load_font` methods —
do not delete them. Mark with `# UNUSED — reserved for future in-image text`.

#### B2-F2: Fix `pdf_service.create_storybook_pdf()` layout

File: `backend/services/pdf_service.py`

**Required layout per page:**
```
┌─────────────────────────────────────────┐
│  [Image — full page width, 5.0 inch]    │  top-aligned
│  1024×1024 PNG → square, full width     │
│                                          │
├─────────────────────────────────────────┤
│  Story text — Helvetica 22pt bold       │  immediately below image
│  Line height: 32pt (1.45×)             │
│  Colour: #1a1a2e (dark navy)           │
│  Left + right margin: 0.5 inch         │
│  Max 2–3 lines. Word-wrapped.           │
└─────────────────────────────────────────┘
```

**Required parameter changes in `ParagraphStyle`:**
```python
story_text_style = ParagraphStyle(
    "StoryText",
    parent=styles["Normal"],
    fontSize=22,          # was 14 — minimum readable for children's book
    leading=32,           # line height 32pt (was 20)
    textColor="#1a1a2e",  # dark navy on white for high contrast
    spaceAfter=12,
    spaceBefore=16,       # breathing room after image
    alignment=TA_LEFT,
    fontName="Helvetica-Bold",   # bold for children's readability
)
```

**Required image size change:**
```python
# CHANGE FROM:
img = RLImage(img_path, width=6 * inch, height=6 * inch)

# CHANGE TO:
# Fill full usable page width (letter = 8.5in, margins 0.5in each side)
usable_width = 7.5 * inch
img = RLImage(img_path, width=usable_width, height=usable_width)
```

**Required: page-break strategy.**  
Each story page (image + text) must fit on a single PDF page. Use
`KeepTogether` to prevent splitting:
```python
from reportlab.platypus import KeepTogether

page_elements = []
if img_path and Path(img_path).exists():
    page_elements.append(RLImage(img_path, width=7.5*inch, height=7.5*inch))
    page_elements.append(Spacer(1, 0.2 * inch))
for line in page_text.split("\n"):
    if line.strip():
        safe = line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        page_elements.append(Paragraph(safe, story_text_style))

content.append(KeepTogether(page_elements))
content.append(PageBreak())
```

**Note:** With 7.5×7.5 inch image on a letter page (8.5×11 inch, margins
0.5 inch = usable 7.5×10 inch), this leaves `10 - 7.5 = 2.5 inches` for text.
At 22pt font + 32pt leading, this fits 2–3 lines comfortably. This is the
correct children's book layout.

---

## 3. Bug B3 — Expression Morph Has No Visible Effect

### 3.1 Observed Behaviour

Every character page shows the exact same facial expression from the user's
selfie photo. Pages configured for `joyful`, `curious`, `awed`, `determined`
etc. all look identical — the expression set in `forest_of_smiles.json` is
not visible in the output.

### 3.2 Root Cause Analysis

**Root cause — `_apply_expression_morph()` uses landmark deltas from the
wrong coordinate space.**

The method computes `bw = x_max - x_min` and `bh = y_max - y_min` from
landmarks detected on the extracted `face_crop` image. The landmark
displacement deltas in `_EXPRESSION_DELTAS` are fractions like `0.030` (3% of
face size). On a face crop of ~170×190px, this is `0.030 × 190 = 5.7px` movement.
The Delaunay warp moves pixels by 5–6px, which is invisible on a soft Pixar-style
illustrated oval at the scale the face appears in the final PDF (~78×87px in PDF space).

Additionally, the Delaunay triangulation warp is applied **after** face extraction
but **before** seamlessClone. The Poisson blending in seamlessClone smooths
the colour gradients and effectively erases the subtle (5px) landmark
displacements.

**Fix strategy:** Increase delta magnitudes. The morph must be noticeable at
the scale it appears (face is ~170px wide in template space, rendered at
~78px in PDF). Deltas must move landmarks by at least 8–15px at face-crop scale
to be perceptible after blending.

### 3.3 Specification — Fix B3

#### B3-F1: Increase expression delta magnitudes

File: `backend/services/face_pipeline_service.py`  
Variable: `_EXPRESSION_DELTAS`

**Required multiplier:** all delta fractions must be multiplied by `2.5×` to
produce visible deformation at the rendered scale.

```python
# Expression delta scale factor — increase all values by this multiplier
# to ensure morphs are visible after seamlessClone at final PDF scale.
_DELTA_SCALE = 2.5

_EXPRESSION_DELTAS: Dict[str, Dict[int, Tuple[float, float]]] = {
    "neutral":    {},
    "smile":      {
        61:  (-0.030 * _DELTA_SCALE,  0.010 * _DELTA_SCALE),
        291: (-0.030 * _DELTA_SCALE, -0.010 * _DELTA_SCALE),
        116: (-0.012 * _DELTA_SCALE,  0.000),
        345: (-0.012 * _DELTA_SCALE,  0.000),
    },
    "joyful":     {
        61:  (-0.050 * _DELTA_SCALE,  0.015 * _DELTA_SCALE),
        291: (-0.050 * _DELTA_SCALE, -0.015 * _DELTA_SCALE),
        116: (-0.022 * _DELTA_SCALE,  0.000),
        345: (-0.022 * _DELTA_SCALE,  0.000),
    },
    # ... apply _DELTA_SCALE to all non-zero values in all presets
}
```

**Apply the same 2.5× scaling to every non-zero delta in every preset.**

#### B3-F2: Apply expression morph before seamlessClone in the correct order

The expression morph must be applied **after** colour/lighting match and
**before** the elliptical mask is created. Verify this order in
`process_character_page`:

```
Step 1: _extract_and_align_face   → face_crop
Step 2: _apply_pose_warp          → face_crop
Step 3: _apply_expression_morph   → face_crop  ← morph goes here
Step 4: resize to target_w × target_h
Step 5: _match_colour_and_lighting
Step 6: _blend_face_into_template (mask + seamlessClone)
```

This order is already correct in the existing code. No reordering needed.
Only the delta magnitudes need to change (B3-F1).

---

## 4. No-Regression Requirements

The following MUST NOT change behaviour:

| Component | Must not change |
|-----------|----------------|
| `backend/routes/generate_async.py` | Any route logic, status, polling |
| `backend/routes/generate.py` | v1 sync endpoint |
| `backend/routes/generate_v2.py` | Preview endpoint |
| `backend/core/session_store.py` | Session read/write/update |
| `backend/core/storage.py` | File save/read |
| `backend/services/story_json_service.py` | JSON loading, template resolution |
| `backend/services/face_blend_service.py` | Untouched |
| `backend/services/generation_mode.py` | Untouched |
| `frontend/` | All frontend files untouched |

---

## 5. Test Cases

All tests live in `backend/tests/test_image_pipeline.py`.

### 5.1 Setup

```python
# backend/tests/test_image_pipeline.py
import pytest, cv2, numpy as np
from pathlib import Path
from unittest.mock import MagicMock
from services.face_pipeline_service import FacePipelineService

TEMPLATES_DIR = Path("backend/cache/dalle/forest_of_smiles")
TEST_FACE_DIR = Path("backend/tests/fixtures/faces")
OUT_DIR       = Path("backend/tests/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Fixture faces — must be committed to the repo in tests/fixtures/faces/
# face_frontal.jpg   : clear frontal face, neutral expression
# face_angled.jpg    : face at ~20° horizontal angle
# face_dark.jpg      : darker skin tone
# face_glasses.jpg   : face with glasses
# face_child.jpg     : child face (age 4–6)

@pytest.fixture
def svc():
    return FacePipelineService()

@pytest.fixture
def page1_template():
    p = TEMPLATES_DIR / "page_01.png"
    assert p.exists(), f"Template missing: {p}"
    return str(p)

@pytest.fixture
def frontal_face():
    p = TEST_FACE_DIR / "face_frontal.jpg"
    assert p.exists(), f"Test face missing: {p}"
    return str(p)
```

### 5.2 Test Cases — Bug B1 (Face Placement)

#### TC-B1-01: Face extracted from correct region

```python
def test_face_extraction_returns_face_not_background(svc, frontal_face):
    """Extracted face crop must contain a face detectable by MediaPipe."""
    import cv2
    img = cv2.imread(frontal_face)
    face_crop, landmarks = svc._extract_and_align_face(img)

    assert face_crop is not None, "Face extraction returned None"
    assert landmarks is not None, "No landmarks in extracted crop"

    # Face crop must be portrait-ish (height >= width * 0.8)
    fh, fw = face_crop.shape[:2]
    assert fh >= fw * 0.8, f"Face crop too wide: {fw}x{fh}"

    # Crop must be much smaller than the original image
    oh, ow = img.shape[:2]
    assert fw < ow * 0.8, "Face crop is nearly full image width — extraction failed"
    assert fh < oh * 0.8, "Face crop is nearly full image height — extraction failed"
```

#### TC-B1-02: Face placed within expected bounding box

```python
def test_face_placed_within_face_config(svc, page1_template, frontal_face):
    """After process_character_page, MediaPipe must detect a face near the
    face_config region on the output image."""
    import mediapipe as mp

    face_config = {"x": 430, "y": 220, "w": 170, "h": 190}
    out = str(OUT_DIR / "tc_b1_02.png")

    svc.process_character_page(
        template_path  = page1_template,
        user_face_path = frontal_face,
        face_config    = face_config,
        pose           = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        expression     = "neutral",
        story_lines    = ["Test line one.", "Test line two."],
        text_area      = {"x": 610, "y": 100, "w": 390, "h": 800},
        child_name     = "TestChild",
        output_path    = out,
    )

    assert Path(out).exists(), "Output PNG not created"
    output = cv2.imread(out)
    assert output is not None

    # Detect face in output
    mp_mesh = mp.solutions.face_mesh
    with mp_mesh.FaceMesh(static_image_mode=True, max_num_faces=1,
                          min_detection_confidence=0.3) as mesh:
        rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
        res = mesh.process(rgb)

    assert res.multi_face_landmarks, "No face detected in output image"

    ih, iw = output.shape[:2]
    lm = res.multi_face_landmarks[0].landmark
    xs = [int(l.x * iw) for l in lm]
    ys = [int(l.y * ih) for l in lm]
    detected_cx = int(np.mean(xs))
    detected_cy = int(np.mean(ys))

    expected_cx = face_config["x"] + face_config["w"] // 2
    expected_cy = face_config["y"] + face_config["h"] // 2

    # Allow ±80px tolerance (face must be in the right neighbourhood)
    TOLERANCE = 80
    assert abs(detected_cx - expected_cx) < TOLERANCE, (
        f"Face centre x={detected_cx} too far from expected x={expected_cx} "
        f"(tolerance ±{TOLERANCE}px)"
    )
    assert abs(detected_cy - expected_cy) < TOLERANCE, (
        f"Face centre y={detected_cy} too far from expected y={expected_cy} "
        f"(tolerance ±{TOLERANCE}px)"
    )
```

#### TC-B1-03: Blend mask produces no hard rectangular edge

```python
def test_no_hard_rectangular_edge_at_face_boundary(svc, page1_template, frontal_face):
    """The face boundary must be soft (no sharp rectangular border).
    Measured by checking that the alpha transition at the boundary is gradual."""
    face_config = {"x": 430, "y": 220, "w": 170, "h": 190}
    out = str(OUT_DIR / "tc_b1_03.png")

    svc.process_character_page(
        template_path=page1_template, user_face_path=frontal_face,
        face_config=face_config, pose={"yaw":0,"pitch":0,"roll":0},
        expression="neutral", story_lines=["Test."],
        text_area={"x":610,"y":100,"w":390,"h":800},
        child_name="TestChild", output_path=out,
    )
    output = cv2.imread(out)

    # Sample a ring around the face_config rectangle
    x, y, w, h = face_config["x"], face_config["y"], face_config["w"], face_config["h"]
    # Load the original template for comparison
    template = cv2.imread(page1_template)
    template_resized = cv2.resize(template, (output.shape[1], output.shape[0]))

    # Compute pixel difference at the boundary ring (2px inside the edge)
    diff = cv2.absdiff(output, template_resized).astype(float)

    # Points along the face_config rectangle border
    border_diffs = []
    for bx in range(x, x + w, 4):
        for by_off in [y, y + h - 1]:
            if 0 <= by_off < output.shape[0] and 0 <= bx < output.shape[1]:
                border_diffs.append(float(diff[by_off, bx].mean()))
    for by in range(y, y + h, 4):
        for bx_off in [x, x + w - 1]:
            if 0 <= by < output.shape[0] and 0 <= bx_off < output.shape[1]:
                border_diffs.append(float(diff[by, bx_off].mean()))

    if border_diffs:
        mean_border_diff = np.mean(border_diffs)
        # A hard rectangular paste produces very high difference at the exact edge.
        # A soft Gaussian-feathered blend produces low diff at the border.
        # Threshold: border diff < 30 on a 0-255 scale.
        assert mean_border_diff < 30, (
            f"Hard edge detected at face boundary — mean border diff={mean_border_diff:.1f} "
            f"(should be < 30 for soft blend)"
        )
```

#### TC-B1-04: Multiple character pages — face always on correct character

```python
@pytest.mark.parametrize("page_num,face_config,expression", [
    (1,  {"x":430,"y":220,"w":170,"h":190}, "curious"),
    (3,  {"x":440,"y":300,"w":150,"h":170}, "determined"),
    (7,  {"x":420,"y":240,"w":170,"h":190}, "joyful"),
    (13, {"x":420,"y":230,"w":170,"h":190}, "awed"),
])
def test_face_on_correct_position_all_char_pages(svc, frontal_face, page_num, face_config, expression):
    """For each character page template, the face must be placed near the
    specified face_config coordinates."""
    import mediapipe as mp

    template = str(TEMPLATES_DIR / f"page_{page_num:02d}.png")
    if not Path(template).exists():
        pytest.skip(f"Template {template} not found")

    out = str(OUT_DIR / f"tc_b1_04_page{page_num}.png")
    svc.process_character_page(
        template_path=template, user_face_path=frontal_face,
        face_config=face_config, pose={"yaw":0,"pitch":0,"roll":0},
        expression=expression, story_lines=["Test."],
        text_area={"x":610,"y":100,"w":390,"h":800},
        child_name="TestChild", output_path=out,
    )
    assert Path(out).exists()

    output = cv2.imread(out)
    mp_mesh = mp.solutions.face_mesh
    with mp_mesh.FaceMesh(static_image_mode=True, max_num_faces=1,
                          min_detection_confidence=0.3) as mesh:
        rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
        res = mesh.process(rgb)

    assert res.multi_face_landmarks, f"No face detected on page {page_num}"
    ih, iw = output.shape[:2]
    lm = res.multi_face_landmarks[0].landmark
    detected_cx = int(np.mean([l.x * iw for l in lm]))
    detected_cy = int(np.mean([l.y * ih for l in lm]))
    expected_cx = face_config["x"] + face_config["w"] // 2
    expected_cy = face_config["y"] + face_config["h"] // 2

    assert abs(detected_cx - expected_cx) < 100, (
        f"Page {page_num}: face x={detected_cx}, expected≈{expected_cx}"
    )
    assert abs(detected_cy - expected_cy) < 100, (
        f"Page {page_num}: face y={detected_cy}, expected≈{expected_cy}"
    )
```

---

### 5.3 Test Cases — Bug B2 (Text)

#### TC-B2-01: Output PNG contains no baked-in text

```python
def test_output_png_has_no_text_overlay(svc, page1_template, frontal_face):
    """After fix B2-F1, the output PNG must be a pure illustration.
    No pixels should match the expected text colour (white #ffffff) in the
    text_area region, beyond what was in the original template."""
    face_config = {"x":430,"y":220,"w":170,"h":190}
    text_area   = {"x":610,"y":100,"w":390,"h":800}
    out = str(OUT_DIR / "tc_b2_01.png")

    svc.process_character_page(
        template_path=page1_template, user_face_path=frontal_face,
        face_config=face_config, pose={"yaw":0,"pitch":0,"roll":0},
        expression="neutral", story_lines=["Niku stepped into the forest."],
        text_area=text_area, child_name="Niku", output_path=out,
    )

    output   = cv2.imread(out)
    template = cv2.imread(page1_template)
    template_r = cv2.resize(template, (output.shape[1], output.shape[0]))

    # Check text_area region for new bright-white pixels
    ta_x, ta_y = text_area["x"], text_area["y"]
    ta_w, ta_h = text_area["w"], text_area["h"]

    h, w = output.shape[:2]
    x1 = min(ta_x, w - 1)
    y1 = min(ta_y, h - 1)
    x2 = min(ta_x + ta_w, w)
    y2 = min(ta_y + ta_h, h)

    if x2 > x1 and y2 > y1:
        out_roi  = output[y1:y2, x1:x2].astype(float)
        tpl_roi  = template_r[y1:y2, x1:x2].astype(float)
        diff     = np.abs(out_roi - tpl_roi).mean()
        assert diff < 5.0, (
            f"text_area region in output differs from template by {diff:.1f} — "
            f"text is being baked into the PNG (should not be)"
        )
```

#### TC-B2-02: PDF story text is minimum 22pt

```python
def test_pdf_story_text_minimum_22pt(tmp_path):
    """The PDF story text style must be at least 22pt for readability."""
    from services.pdf_service import PDFService
    import fitz  # PyMuPDF — pip install pymupdf

    svc    = PDFService(str(tmp_path))
    dummy_img = str(TEMPLATES_DIR / "page_01.png")
    pages_data = [
        {"text": "Niku stepped into a quiet jungle.", "image_path": dummy_img},
        {"text": "A little monkey sat alone on a branch.", "image_path": dummy_img},
    ]
    pdf_path = svc.create_storybook_pdf(
        child_name="Niku", story_title="Test Story",
        pages_data=pages_data, output_filename="test_font.pdf"
    )

    doc = fitz.open(pdf_path)
    # Check page 2 (first story page)
    page = doc[1]
    blocks = page.get_text("dict")["blocks"]
    for block in blocks:
        if block.get("type") == 0:  # text block
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    size = span.get("size", 0)
                    if text and len(text) > 3:
                        assert size >= 22, (
                            f"Text '{text}' has font size {size:.1f}pt — "
                            f"minimum 22pt required for children's book"
                        )
    doc.close()
```

#### TC-B2-03: PDF text fits below image on same page — no overflow

```python
def test_pdf_image_and_text_on_same_page(tmp_path):
    """Image and its story text must land on the same PDF page (no split)."""
    import fitz
    from services.pdf_service import PDFService

    svc = PDFService(str(tmp_path))
    dummy_img = str(TEMPLATES_DIR / "page_01.png")
    pages_data = [
        {"text": "Niku stepped into a quiet jungle, soft and green.", "image_path": dummy_img},
    ]
    pdf_path = svc.create_storybook_pdf(
        child_name="Niku", story_title="Test Story",
        pages_data=pages_data, output_filename="test_layout.pdf"
    )

    doc = fitz.open(pdf_path)
    # PDF should have 2 pages: title + 1 story page
    assert len(doc) == 2, f"Expected 2 PDF pages, got {len(doc)}"

    story_page = doc[1]
    # Check that images exist on this page
    image_list = story_page.get_images()
    assert len(image_list) > 0, "No image on story page"

    # Check that text exists on this page
    text = story_page.get_text()
    assert "Niku" in text, "Story text not found on same page as image"
    doc.close()
```

#### TC-B2-04: PDF image fills 90%+ of page width

```python
def test_pdf_image_uses_full_page_width(tmp_path):
    """Image must fill at least 90% of the usable page width."""
    import fitz
    from services.pdf_service import PDFService

    svc = PDFService(str(tmp_path))
    dummy_img = str(TEMPLATES_DIR / "page_01.png")
    pdf_path = svc.create_storybook_pdf(
        child_name="Niku", story_title="Test",
        pages_data=[{"text": "Line one.", "image_path": dummy_img}],
        output_filename="test_imgwidth.pdf",
    )

    doc = fitz.open(pdf_path)
    page = doc[1]
    page_width = page.rect.width  # in points, letter = 612
    images = page.get_image_rects(page.get_images()[0][0])
    assert images, "No image rect found"
    img_width = images[0].width

    # Image must use ≥90% of page width
    usable = page_width - 72  # margins 0.5in each = 36pt each
    assert img_width >= usable * 0.90, (
        f"Image width {img_width:.0f}pt < 90% of usable {usable:.0f}pt"
    )
    doc.close()
```

---

### 5.4 Test Cases — Bug B3 (Expression)

#### TC-B3-01: Expression morph changes pixel content near mouth/brow

```python
@pytest.mark.parametrize("expression", ["joyful", "awed", "determined", "curious"])
def test_expression_morph_changes_face_pixels(svc, frontal_face, expression):
    """Pixel content in mouth and brow region must differ between neutral
    and the specified expression."""
    # Create a synthetic face-sized canvas for testing morphs in isolation
    img = cv2.imread(frontal_face)
    assert img is not None

    pts_neutral   = svc._detect_landmarks(img)
    if pts_neutral is None:
        pytest.skip("No face detected in test face image")

    # Apply neutral (no change)
    out_neutral = img.copy()

    # Apply expression
    out_expr = svc._apply_expression_morph(img, pts_neutral, expression)

    assert out_expr is not None, f"_apply_expression_morph returned None for {expression}"
    assert out_expr.shape == img.shape, "Output shape changed"

    # Measure difference in lower face region (mouth area — bottom 30% of face bbox)
    ih, iw = img.shape[:2]
    mouth_y_start = int(ih * 0.60)
    neutral_mouth = out_neutral[mouth_y_start:, :].astype(float)
    expr_mouth    = out_expr[mouth_y_start:, :].astype(float)
    mean_diff = np.abs(neutral_mouth - expr_mouth).mean()

    assert mean_diff > 1.5, (
        f"Expression '{expression}' produced negligible change in mouth region "
        f"(mean_diff={mean_diff:.3f}, need > 1.5). "
        f"Increase _DELTA_SCALE or delta values."
    )
```

#### TC-B3-02: Different expressions produce different face crops

```python
@pytest.mark.parametrize("expr_a,expr_b", [
    ("neutral", "joyful"),
    ("curious", "determined"),
    ("awed",    "proud"),
])
def test_two_expressions_produce_different_outputs(svc, frontal_face, page1_template, expr_a, expr_b):
    """Two different expressions must produce measurably different output images."""
    face_config = {"x":430,"y":220,"w":170,"h":190}
    text_area   = {"x":610,"y":100,"w":390,"h":800}

    out_a = str(OUT_DIR / f"tc_b3_02_{expr_a}.png")
    out_b = str(OUT_DIR / f"tc_b3_02_{expr_b}.png")

    for expr, out_path in [(expr_a, out_a), (expr_b, out_b)]:
        svc.process_character_page(
            template_path=page1_template, user_face_path=frontal_face,
            face_config=face_config, pose={"yaw":0,"pitch":0,"roll":0},
            expression=expr, story_lines=["Test."],
            text_area=text_area, child_name="TestChild",
            output_path=out_path,
        )
        assert Path(out_path).exists(), f"Output for {expr} not created"

    img_a = cv2.imread(out_a).astype(float)
    img_b = cv2.imread(out_b).astype(float)

    # Focus diff on face region only
    x, y, w, h = face_config["x"], face_config["y"], face_config["w"], face_config["h"]
    face_a = img_a[y:y+h, x:x+w]
    face_b = img_b[y:y+h, x:x+w]

    mean_diff = np.abs(face_a - face_b).mean()
    assert mean_diff > 2.0, (
        f"Expressions '{expr_a}' and '{expr_b}' produced near-identical face regions "
        f"(mean_diff={mean_diff:.3f}, need > 2.0)"
    )
```

---

### 5.5 Integration Test — End-to-End PDF Quality

#### TC-INT-01: Full 16-page generation produces valid PDF

```python
def test_full_16_page_generation(tmp_path, frontal_face):
    """Generate all 16 pages using face_pipeline_service and build a PDF.
    Validate: 17 PDF pages (title + 16), all images present, text readable."""
    import json, fitz
    from services.face_pipeline_service import FacePipelineService
    from services.story_json_service import story_json_service
    from services.pdf_service import PDFService

    svc     = FacePipelineService()
    story   = story_json_service.get_story("forest_of_smiles")
    pdf_svc = PDFService(str(tmp_path))
    pages_data = []

    for page in story.pages:
        if not page.template_path or not Path(page.template_path).exists():
            pytest.skip(f"Template missing for page {page.page_number}")

        out = str(tmp_path / f"page_{page.page_number:02d}.png")
        ta  = {"x":page.text_area.x,"y":page.text_area.y,
               "w":page.text_area.w,"h":page.text_area.h}

        if page.character_present:
            fc = {"x":page.face_config.x,"y":page.face_config.y,
                  "w":page.face_config.w,"h":page.face_config.h} if page.face_config else \
                 {"x":430,"y":220,"w":170,"h":190}
            hp = {"yaw":page.head_pose.yaw,"pitch":page.head_pose.pitch,
                  "roll":page.head_pose.roll} if page.head_pose else \
                 {"yaw":0,"pitch":0,"roll":0}
            svc.process_character_page(
                template_path=page.template_path, user_face_path=frontal_face,
                face_config=fc, pose=hp, expression=page.expression or "neutral",
                story_lines=page.story_lines, text_area=ta,
                child_name="TestChild", output_path=out,
            )
        else:
            svc.process_text_only_page(
                template_path=page.template_path, story_lines=page.story_lines,
                text_area=ta, child_name="TestChild", output_path=out,
            )

        assert Path(out).exists(), f"Page {page.page_number} output missing"
        pages_data.append({
            "text": " ".join(page.story_lines),
            "image_path": out,
            "page_number": page.page_number,
        })

    pdf_path = pdf_svc.create_storybook_pdf(
        child_name="TestChild",
        story_title=story.title,
        pages_data=pages_data,
        output_filename="integration_test.pdf",
    )
    assert Path(pdf_path).exists()

    doc = fitz.open(pdf_path)
    # Title + 16 story pages = 17 total
    assert len(doc) == 17, f"Expected 17 PDF pages, got {len(doc)}"

    # Check every story page has an image
    for pg_idx in range(1, 17):
        page_obj = doc[pg_idx]
        images = page_obj.get_images()
        assert len(images) > 0, f"Story page {pg_idx} has no image in PDF"

    doc.close()
```

---

## 6. Implementation Order

Implement in this exact order to avoid regressions:

1. **B2-F1** — Remove `_overlay_text()` call from `process_character_page` and
   `process_text_only_page`. **Do not delete the method.**
   - Run TC-B2-01 to validate.

2. **B2-F2** — Update `pdf_service.create_storybook_pdf()` layout.
   - Run TC-B2-02, TC-B2-03, TC-B2-04.

3. **B1-F1** — Rewrite `_extract_and_align_face()` with correct padding.
   - Run TC-B1-01.

4. **B1-F2** — Update mask axes in `_blend_face_into_template()`.
   - (No isolated test; validated by TC-B1-03.)

5. **B1-F3** — Fix `seamlessClone` center calculation.
   - Run TC-B1-02, TC-B1-03, TC-B1-04.

6. **B3-F1** — Scale expression delta magnitudes by 2.5×.
   - Run TC-B3-01, TC-B3-02.

7. **Integration** — Run TC-INT-01 with all fixes in place.

8. **Commit** — Single commit per bug group (3 commits total: B1, B2, B3).

---

## 7. Acceptance Criteria

A fix is accepted when:

| Criterion | How verified |
|-----------|-------------|
| Face is centred on the character's head, not on background or other characters | TC-B1-02 passes with ±80px tolerance |
| Face blend has no hard rectangular edge | TC-B1-03 passes with border_diff < 30 |
| Face appears on correct position across all character pages | TC-B1-04 passes for all 4 pages |
| PNG output contains no baked-in story text | TC-B2-01 passes |
| PDF story text ≥ 22pt | TC-B2-02 passes |
| Image and text on same PDF page | TC-B2-03 passes |
| Image uses ≥90% page width | TC-B2-04 passes |
| Expression morph changes mouth/brow pixels by mean > 1.5 | TC-B3-01 passes |
| Different expressions produce different output | TC-B3-02 passes |
| Full 16-page generation produces valid 17-page PDF | TC-INT-01 passes |

---

## 8. Files Modified Summary

| File | Changes |
|------|---------|
| `backend/services/face_pipeline_service.py` | B1-F1: rewrite `_extract_and_align_face()`; B1-F2/F3: update mask + seamlessClone center; B2-F1: remove `_overlay_text()` calls; B3-F1: scale `_EXPRESSION_DELTAS` by 2.5× |
| `backend/services/pdf_service.py` | B2-F2: font 14→22pt, bold, 7.5-inch image, `KeepTogether` |
| `backend/tests/test_image_pipeline.py` | New file — all test cases above |
| `backend/tests/fixtures/faces/*.jpg` | New test fixture images |

**No other files are touched.**

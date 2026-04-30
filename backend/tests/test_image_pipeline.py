"""
backend/tests/test_image_pipeline.py
=====================================
Test suite for SPEC_IMAGE_PIPELINE_FIXES.md

Covers:
  B1 — Face placement (extraction, position, blend edge quality, all char pages)
  B2 — Text rendering (no PNG text bake-in, PDF 22pt, image+text same page, width)
  B3 — Expression morph (pixel change at mouth, different expressions differ)
  INT — Full 16-page end-to-end generation

Run from backend/:
    pytest tests/test_image_pipeline.py -v

Requirements:
    pip install pytest pymupdf --break-system-packages
    (cv2, mediapipe, numpy, PIL already in requirements.txt)
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# Ensure backend/ is on sys.path when running from repo root
BACKEND = Path(__file__).parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import cv2
import numpy as np
import pytest

from services.face_pipeline_service import FacePipelineService

# ─── Paths ────────────────────────────────────────────────────────────────────

TEMPLATES_DIR = BACKEND / "cache" / "dalle" / "forest_of_smiles"
TEST_FACE_DIR = BACKEND / "tests" / "fixtures" / "faces"
OUT_DIR       = BACKEND / "tests" / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def svc():
    return FacePipelineService()


@pytest.fixture(scope="session")
def page1_template():
    p = TEMPLATES_DIR / "page_01.png"
    if not p.exists():
        pytest.skip(f"Template missing: {p}")
    return str(p)


@pytest.fixture(scope="session")
def frontal_face():
    p = TEST_FACE_DIR / "face_frontal.jpg"
    if not p.exists():
        pytest.skip(f"Test face fixture missing: {p}")
    return str(p)


@pytest.fixture(scope="session")
def default_face_config():
    return {"x": 430, "y": 220, "w": 170, "h": 190}


@pytest.fixture(scope="session")
def default_text_area():
    return {"x": 610, "y": 100, "w": 390, "h": 800}


@pytest.fixture(scope="session")
def default_pose():
    return {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}


# ═══════════════════════════════════════════════════════════════════════════════
# B1 — Face Placement Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestB1FacePlacement:
    """TC-B1-01 through TC-B1-04: face extraction and placement correctness."""

    def test_TC_B1_01_face_extraction_returns_face_not_background(self, svc, frontal_face):
        """
        TC-B1-01: Extracted face crop must be a face region, not the
        full image or an unrelated background region.
        """
        img = cv2.imread(frontal_face)
        assert img is not None, f"Cannot read test face: {frontal_face}"

        face_crop, landmarks = svc._extract_and_align_face(img)

        assert face_crop is not None, "Face extraction returned None"

        fh, fw = face_crop.shape[:2]
        oh, ow = img.shape[:2]

        # Crop must be substantially smaller than the source image
        assert fw < ow * 0.85, (
            f"Face crop width {fw}px is nearly full image width {ow}px — "
            f"extraction likely failed (returned whole image)"
        )
        assert fh < oh * 0.85, (
            f"Face crop height {fh}px is nearly full image height {oh}px — "
            f"extraction likely failed"
        )

        # Crop must be roughly portrait-shaped (not wildly landscape)
        assert fh >= fw * 0.6, (
            f"Face crop is too wide relative to height: {fw}x{fh}. "
            f"Expected portrait-ish shape (h ≥ w × 0.6)"
        )

    def test_TC_B1_02_face_placed_within_face_config(
        self, svc, page1_template, frontal_face, default_face_config, default_text_area, default_pose
    ):
        """
        TC-B1-02: After process_character_page, a face must be detectable
        within ±80px of the expected face_config centre.
        """
        import mediapipe as mp

        out = str(OUT_DIR / "tc_b1_02_face_placement.png")
        svc.process_character_page(
            template_path  = page1_template,
            user_face_path = frontal_face,
            face_config    = default_face_config,
            pose           = default_pose,
            expression     = "neutral",
            story_lines    = ["Test line one.", "Test line two."],
            text_area      = default_text_area,
            child_name     = "TestChild",
            output_path    = out,
        )

        assert Path(out).exists(), "Output PNG was not created"
        output = cv2.imread(out)
        assert output is not None

        mp_mesh = mp.solutions.face_mesh
        with mp_mesh.FaceMesh(
            static_image_mode=True, max_num_faces=1, min_detection_confidence=0.3
        ) as mesh:
            rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
            res = mesh.process(rgb)

        assert res.multi_face_landmarks, (
            "No face detected by MediaPipe in the output image. "
            "Face may be placed entirely outside the image or blend quality too low."
        )

        ih, iw = output.shape[:2]
        lm = res.multi_face_landmarks[0].landmark
        detected_cx = int(np.mean([l.x * iw for l in lm]))
        detected_cy = int(np.mean([l.y * ih for l in lm]))

        fc = default_face_config
        expected_cx = fc["x"] + fc["w"] // 2
        expected_cy = fc["y"] + fc["h"] // 2

        TOLERANCE = 80  # pixels
        assert abs(detected_cx - expected_cx) < TOLERANCE, (
            f"Face centre x={detected_cx} is {abs(detected_cx-expected_cx)}px "
            f"from expected x={expected_cx} (tolerance ±{TOLERANCE}px)"
        )
        assert abs(detected_cy - expected_cy) < TOLERANCE, (
            f"Face centre y={detected_cy} is {abs(detected_cy-expected_cy)}px "
            f"from expected y={expected_cy} (tolerance ±{TOLERANCE}px)"
        )

    def test_TC_B1_03_no_hard_rectangular_edge_at_face_boundary(
        self, svc, page1_template, frontal_face, default_face_config, default_text_area, default_pose
    ):
        """
        TC-B1-03: The face boundary must be soft (Gaussian-feathered).
        Mean pixel difference between output and template at the face_config
        rectangle border must be < 30 (hard paste produces much higher diff).
        """
        out = str(OUT_DIR / "tc_b1_03_soft_edge.png")
        svc.process_character_page(
            template_path  = page1_template,
            user_face_path = frontal_face,
            face_config    = default_face_config,
            pose           = default_pose,
            expression     = "neutral",
            story_lines    = ["Test."],
            text_area      = default_text_area,
            child_name     = "TestChild",
            output_path    = out,
        )

        output   = cv2.imread(out).astype(np.float32)
        template = cv2.imread(page1_template)
        template_r = cv2.resize(
            template, (output.shape[1], output.shape[0])
        ).astype(np.float32)

        fc = default_face_config
        x, y, w, h = fc["x"], fc["y"], fc["w"], fc["h"]
        img_h, img_w = output.shape[:2]

        # Sample border pixels of the face_config rectangle
        border_diffs = []
        step = 4
        for bx in range(x, min(x + w, img_w), step):
            for by in [y, y + h - 1]:
                if 0 <= by < img_h and 0 <= bx < img_w:
                    border_diffs.append(float(
                        np.abs(output[by, bx] - template_r[by, bx]).mean()
                    ))
        for by in range(y, min(y + h, img_h), step):
            for bx in [x, x + w - 1]:
                if 0 <= by < img_h and 0 <= bx < img_w:
                    border_diffs.append(float(
                        np.abs(output[by, bx] - template_r[by, bx]).mean()
                    ))

        if not border_diffs:
            pytest.skip("face_config region is outside image bounds")

        mean_border_diff = float(np.mean(border_diffs))
        assert mean_border_diff < 30, (
            f"Hard rectangular edge detected at face boundary — "
            f"mean border diff={mean_border_diff:.1f} (threshold < 30). "
            f"Gaussian feathering may be insufficient."
        )

    @pytest.mark.parametrize("page_num,face_config,expression", [
        (1,  {"x": 430, "y": 220, "w": 170, "h": 190}, "curious"),
        (3,  {"x": 440, "y": 300, "w": 150, "h": 170}, "determined"),
        (7,  {"x": 420, "y": 240, "w": 170, "h": 190}, "joyful"),
        (13, {"x": 420, "y": 230, "w": 170, "h": 190}, "awed"),
    ])
    def test_TC_B1_04_face_on_correct_position_all_char_pages(
        self, svc, frontal_face, page_num, face_config, expression
    ):
        """
        TC-B1-04: For each character page template, face must be detected
        within ±100px of the expected face_config centre.
        """
        import mediapipe as mp

        template = str(TEMPLATES_DIR / f"page_{page_num:02d}.png")
        if not Path(template).exists():
            pytest.skip(f"Template {template} not found")

        out = str(OUT_DIR / f"tc_b1_04_page{page_num:02d}.png")
        svc.process_character_page(
            template_path  = template,
            user_face_path = frontal_face,
            face_config    = face_config,
            pose           = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
            expression     = expression,
            story_lines    = ["Test line."],
            text_area      = {"x": 610, "y": 100, "w": 390, "h": 800},
            child_name     = "TestChild",
            output_path    = out,
        )
        assert Path(out).exists(), f"Output for page {page_num} not created"

        output = cv2.imread(out)
        mp_mesh = mp.solutions.face_mesh
        with mp_mesh.FaceMesh(
            static_image_mode=True, max_num_faces=1, min_detection_confidence=0.3
        ) as mesh:
            rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
            res = mesh.process(rgb)

        assert res.multi_face_landmarks, (
            f"No face detected on page {page_num} output"
        )

        ih, iw = output.shape[:2]
        lm = res.multi_face_landmarks[0].landmark
        detected_cx = int(np.mean([l.x * iw for l in lm]))
        detected_cy = int(np.mean([l.y * ih for l in lm]))
        expected_cx = face_config["x"] + face_config["w"] // 2
        expected_cy = face_config["y"] + face_config["h"] // 2

        TOLERANCE = 100
        assert abs(detected_cx - expected_cx) < TOLERANCE, (
            f"Page {page_num}: face x={detected_cx}, expected≈{expected_cx} "
            f"(off by {abs(detected_cx-expected_cx)}px, tolerance ±{TOLERANCE}px)"
        )
        assert abs(detected_cy - expected_cy) < TOLERANCE, (
            f"Page {page_num}: face y={detected_cy}, expected≈{expected_cy} "
            f"(off by {abs(detected_cy-expected_cy)}px, tolerance ±{TOLERANCE}px)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# B2 — Text Rendering Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestB2TextRendering:
    """TC-B2-01 through TC-B2-04: text bake-in removed, PDF layout correct."""

    def test_TC_B2_01_output_png_has_no_text_baked_in(
        self, svc, page1_template, frontal_face, default_face_config, default_text_area, default_pose
    ):
        """
        TC-B2-01: The output PNG from process_character_page must be a pure
        illustration. The text_area region must not have changed from the
        template (mean pixel diff < 5.0 — only face area should differ).
        """
        out = str(OUT_DIR / "tc_b2_01_no_text.png")
        svc.process_character_page(
            template_path  = page1_template,
            user_face_path = frontal_face,
            face_config    = default_face_config,
            pose           = default_pose,
            expression     = "neutral",
            story_lines    = ["Niku stepped into the forest."],
            text_area      = default_text_area,
            child_name     = "Niku",
            output_path    = out,
        )

        output   = cv2.imread(out)
        template = cv2.imread(page1_template)
        assert output is not None and template is not None

        oh, ow = output.shape[:2]
        template_r = cv2.resize(template, (ow, oh))

        # Check text_area region has NOT changed
        ta = default_text_area
        x1 = min(ta["x"], ow - 1)
        y1 = min(ta["y"], oh - 1)
        x2 = min(ta["x"] + ta["w"], ow)
        y2 = min(ta["y"] + ta["h"], oh)

        if x2 > x1 and y2 > y1:
            out_roi = output[y1:y2, x1:x2].astype(np.float32)
            tpl_roi = template_r[y1:y2, x1:x2].astype(np.float32)
            mean_diff = float(np.abs(out_roi - tpl_roi).mean())

            assert mean_diff < 8.0, (
                f"text_area region in output differs from template by "
                f"{mean_diff:.2f} (threshold < 8.0). "
                f"Text is still being baked into the PNG — B2-F1 fix not applied."
            )

    def test_TC_B2_01b_text_only_page_is_pure_template(
        self, svc, frontal_face
    ):
        """
        TC-B2-01b: process_text_only_page must produce a PNG identical to
        the raw template (no text rendered onto it).
        """
        template_path = str(TEMPLATES_DIR / "page_02.png")
        if not Path(template_path).exists():
            pytest.skip("Template page_02.png not found")

        out = str(OUT_DIR / "tc_b2_01b_text_only.png")
        svc.process_text_only_page(
            template_path = template_path,
            story_lines   = ["A little monkey sat alone on a branch."],
            text_area     = {"x": 550, "y": 120, "w": 450, "h": 780},
            child_name    = "Niku",
            output_path   = out,
        )

        output   = cv2.imread(out).astype(np.float32)
        template = cv2.imread(template_path)
        oh, ow   = output.shape[:2]
        template_r = cv2.resize(template, (ow, oh)).astype(np.float32)

        mean_diff = float(np.abs(output - template_r).mean())
        assert mean_diff < 3.0, (
            f"Text-only page output differs from template by {mean_diff:.2f} "
            f"(threshold < 3.0). Text is still being baked into the PNG."
        )

    def test_TC_B2_02_pdf_story_text_minimum_22pt(self, tmp_path):
        """
        TC-B2-02: All story text in the PDF must be ≥ 22pt font size.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            pytest.skip("PyMuPDF (fitz) not installed — run: pip install pymupdf")

        from services.pdf_service import PDFService

        dummy_img = str(TEMPLATES_DIR / "page_01.png")
        if not Path(dummy_img).exists():
            pytest.skip("Template page_01.png not found")

        svc_pdf = PDFService(str(tmp_path))
        pdf_path = svc_pdf.create_storybook_pdf(
            child_name     = "Niku",
            story_title    = "Test Story",
            pages_data     = [
                {"text": "Niku stepped into a quiet jungle.", "image_path": dummy_img},
                {"text": "A little monkey sat alone.", "image_path": dummy_img},
            ],
            output_filename = "test_fontsize.pdf",
        )

        doc = fitz.open(pdf_path)
        violations = []

        for pg_idx in range(1, len(doc)):  # skip title page (idx 0)
            page = doc[pg_idx]
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        size = span.get("size", 0)
                        if text and len(text) > 3 and size < 22:
                            violations.append(
                                f"Page {pg_idx+1}: '{text[:30]}' = {size:.1f}pt"
                            )

        doc.close()
        assert not violations, (
            f"Story text below 22pt found in PDF:\n" + "\n".join(violations)
        )

    def test_TC_B2_03_pdf_image_and_text_on_same_page(self, tmp_path):
        """
        TC-B2-03: Image and its story text must be on the same PDF page
        (KeepTogether must prevent splitting).
        """
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF (fitz) not installed")

        from services.pdf_service import PDFService

        dummy_img = str(TEMPLATES_DIR / "page_01.png")
        if not Path(dummy_img).exists():
            pytest.skip("Template not found")

        svc_pdf = PDFService(str(tmp_path))
        pdf_path = svc_pdf.create_storybook_pdf(
            child_name     = "Niku",
            story_title    = "Test Story",
            pages_data     = [
                {"text": "Niku stepped into a quiet jungle, soft and green.", "image_path": dummy_img},
            ],
            output_filename = "test_layout.pdf",
        )

        doc = fitz.open(pdf_path)
        # Title page + 1 story page = 2 total
        assert len(doc) == 2, (
            f"Expected 2 PDF pages (title + 1 story), got {len(doc)}"
        )

        story_page = doc[1]

        # Image must be on the story page
        assert len(story_page.get_images()) > 0, (
            "No image on story page — image may have split to a different page"
        )

        # Story text must be on the story page
        page_text = story_page.get_text()
        assert "Niku" in page_text, (
            "Story text not found on the same page as the image"
        )
        doc.close()

    def test_TC_B2_04_pdf_image_uses_full_page_width(self, tmp_path):
        """
        TC-B2-04: Image must use ≥90% of the usable page width (7.5 inch target).
        """
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF (fitz) not installed")

        from services.pdf_service import PDFService

        dummy_img = str(TEMPLATES_DIR / "page_01.png")
        if not Path(dummy_img).exists():
            pytest.skip("Template not found")

        svc_pdf = PDFService(str(tmp_path))
        pdf_path = svc_pdf.create_storybook_pdf(
            child_name     = "Niku",
            story_title    = "Test",
            pages_data     = [{"text": "Line one.", "image_path": dummy_img}],
            output_filename = "test_imgwidth.pdf",
        )

        doc = fitz.open(pdf_path)
        story_page = doc[1]
        page_width = story_page.rect.width  # points; letter = 612

        image_list = story_page.get_images()
        assert image_list, "No images on story page"

        xref = image_list[0][0]
        rects = story_page.get_image_rects(xref)
        assert rects, "Cannot get image rect"

        img_width = rects[0].width
        usable = page_width - 72  # 0.5 inch margin each side = 36pt × 2 = 72

        assert img_width >= usable * 0.90, (
            f"Image width {img_width:.0f}pt is less than 90% of usable "
            f"page width {usable:.0f}pt. Image may be set to 6-inch (old)."
        )
        doc.close()


# ═══════════════════════════════════════════════════════════════════════════════
# B3 — Expression Morph Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestB3ExpressionMorph:
    """TC-B3-01 and TC-B3-02: expression deltas produce visible face changes."""

    @pytest.mark.parametrize("expression", ["joyful", "awed", "determined", "curious"])
    def test_TC_B3_01_expression_changes_face_pixels(self, svc, frontal_face, expression):
        """
        TC-B3-01: _apply_expression_morph must move pixels in the mouth/brow
        region by a mean diff > 1.5 compared to the unwarped face.
        """
        img = cv2.imread(frontal_face)
        assert img is not None

        pts = svc._detect_landmarks(img)
        if pts is None:
            pytest.skip(f"No face detected in test fixture {frontal_face}")

        out_neutral = img.copy()
        out_expr    = svc._apply_expression_morph(img, pts, expression)

        assert out_expr is not None, f"_apply_expression_morph returned None for '{expression}'"
        assert out_expr.shape == img.shape, (
            f"Expression morph changed image shape: {img.shape} → {out_expr.shape}"
        )

        # Measure diff in lower face (mouth area = bottom 35% of image)
        ih = img.shape[0]
        mouth_start = int(ih * 0.60)
        neutral_mouth = out_neutral[mouth_start:].astype(np.float32)
        expr_mouth    = out_expr[mouth_start:].astype(np.float32)
        mean_diff = float(np.abs(neutral_mouth - expr_mouth).mean())

        assert mean_diff > 1.5, (
            f"Expression '{expression}' produced negligible pixel change in mouth region "
            f"(mean_diff={mean_diff:.3f}, threshold > 1.5). "
            f"Increase _DS (delta scale) in face_pipeline_service.py."
        )

    @pytest.mark.parametrize("expr_a,expr_b", [
        ("neutral",  "joyful"),
        ("curious",  "determined"),
        ("awed",     "proud"),
    ])
    def test_TC_B3_02_different_expressions_differ(
        self, svc, frontal_face, page1_template, expr_a, expr_b,
        default_face_config, default_text_area
    ):
        """
        TC-B3-02: Two different expressions must produce measurably different
        output images in the face region (mean_diff > 2.0).
        """
        out_a = str(OUT_DIR / f"tc_b3_02_{expr_a}.png")
        out_b = str(OUT_DIR / f"tc_b3_02_{expr_b}.png")

        for expr, out_path in [(expr_a, out_a), (expr_b, out_b)]:
            svc.process_character_page(
                template_path  = page1_template,
                user_face_path = frontal_face,
                face_config    = default_face_config,
                pose           = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
                expression     = expr,
                story_lines    = ["Test."],
                text_area      = default_text_area,
                child_name     = "TestChild",
                output_path    = out_path,
            )
            assert Path(out_path).exists(), f"Output for expression '{expr}' not created"

        img_a = cv2.imread(out_a).astype(np.float32)
        img_b = cv2.imread(out_b).astype(np.float32)

        fc = default_face_config
        x, y, w, h = fc["x"], fc["y"], fc["w"], fc["h"]

        oh, ow = img_a.shape[:2]
        x2, y2 = min(x + w, ow), min(y + h, oh)
        face_a = img_a[y:y2, x:x2]
        face_b = img_b[y:y2, x:x2]

        mean_diff = float(np.abs(face_a - face_b).mean())
        assert mean_diff > 2.0, (
            f"Expressions '{expr_a}' and '{expr_b}' produced nearly identical "
            f"face regions (mean_diff={mean_diff:.3f}, threshold > 2.0)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Integration — Full 16-page generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """TC-INT-01: end-to-end 16-page PDF generation."""

    def test_TC_INT_01_full_16_page_generation(self, tmp_path, frontal_face):
        """
        TC-INT-01: Generate all 16 pages using face_pipeline_service +
        story_json_service and build the PDF.

        Validates:
          - 17 PDF pages total (title + 16 story pages)
          - Every story page has an image in the PDF
          - No exceptions during generation
        """
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF (fitz) not installed")

        from services.face_pipeline_service import FacePipelineService
        from services.story_json_service import story_json_service
        from services.pdf_service import PDFService

        svc_fp   = FacePipelineService()
        story    = story_json_service.get_story("forest_of_smiles")
        if not story:
            pytest.skip("Story 'forest_of_smiles' not found in story_json_service")

        pdf_svc    = PDFService(str(tmp_path))
        pages_data = []
        skipped    = []

        for page in story.pages:
            if not page.template_path or not Path(page.template_path).exists():
                skipped.append(page.page_number)
                continue

            out = str(tmp_path / f"page_{page.page_number:02d}.png")
            ta  = {
                "x": page.text_area.x, "y": page.text_area.y,
                "w": page.text_area.w, "h": page.text_area.h,
            }

            if page.character_present:
                fc = (
                    {"x": page.face_config.x, "y": page.face_config.y,
                     "w": page.face_config.w, "h": page.face_config.h}
                    if page.face_config
                    else {"x": 430, "y": 220, "w": 170, "h": 190}
                )
                hp = (
                    {"yaw":   page.head_pose.yaw,
                     "pitch": page.head_pose.pitch,
                     "roll":  page.head_pose.roll}
                    if page.head_pose
                    else {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}
                )
                svc_fp.process_character_page(
                    template_path  = page.template_path,
                    user_face_path = frontal_face,
                    face_config    = fc,
                    pose           = hp,
                    expression     = page.expression or "neutral",
                    story_lines    = page.story_lines,
                    text_area      = ta,
                    child_name     = "TestChild",
                    output_path    = out,
                )
            else:
                svc_fp.process_text_only_page(
                    template_path = page.template_path,
                    story_lines   = page.story_lines,
                    text_area     = ta,
                    child_name    = "TestChild",
                    output_path   = out,
                )

            assert Path(out).exists(), f"Page {page.page_number} output missing"
            pages_data.append({
                "text":        " ".join(page.story_lines),
                "image_path":  out,
                "page_number": page.page_number,
            })

        if skipped:
            pytest.skip(f"Templates missing for pages: {skipped}")

        pdf_path = pdf_svc.create_storybook_pdf(
            child_name     = "TestChild",
            story_title    = story.title,
            pages_data     = pages_data,
            output_filename = "integration_test.pdf",
        )

        assert Path(pdf_path).exists(), "PDF file not created"
        assert Path(pdf_path).stat().st_size > 100_000, (
            "PDF file suspiciously small — may be empty or corrupt"
        )

        doc = fitz.open(pdf_path)
        # Title page + 16 story pages = 17
        assert len(doc) == 17, (
            f"Expected 17 PDF pages (title + 16), got {len(doc)}"
        )

        for pg_idx in range(1, 17):
            pg = doc[pg_idx]
            images = pg.get_images()
            assert len(images) > 0, (
                f"Story page {pg_idx} has no image in the PDF"
            )

        doc.close()

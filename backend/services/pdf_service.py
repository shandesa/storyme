"""PDF Generation Service

Builds a multi-page PDF storybook from generated page images and story text.

B2-FIX (2026-04-30):
  Images now fill full page width (7.5 inch). Story text rendered at 22pt
  Helvetica-Bold immediately below each image. KeepTogether prevents image
  and its text from splitting across pages. Text is no longer baked into the
  PNG by face_pipeline_service — all text lives exclusively in the PDF layer.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
    PageBreak, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from pathlib import Path
from typing import List
import logging

logger = logging.getLogger(__name__)


class PDFService:
    """Builds storybook PDFs from generated page images + story text."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_storybook_pdf(
        self,
        child_name: str,
        story_title: str,
        pages_data: List[dict],
        output_filename: str,
    ) -> str:
        """
        Create a multi-page PDF storybook.

        Layout per story page:
          ┌──────────────────────────────────────────┐
          │  Image — 7.5 inch wide (full page width)  │
          │  1024×1024 PNG, square, top-aligned        │
          ├──────────────────────────────────────────┤
          │  Story text — Helvetica-Bold 22pt          │
          │  Line height 32pt, dark navy #1a1a2e       │
          │  KeepTogether with image — never split     │
          └──────────────────────────────────────────┘

        Args:
            child_name:      Child's name (replaces {name} in story text)
            story_title:     Story title (may contain {name})
            pages_data:      List of dicts: {'text': str, 'image_path': str}
            output_filename: Output PDF filename

        Returns:
            Absolute path to the generated PDF file.
        """
        try:
            pdf_path = self.output_dir / output_filename

            # Letter = 8.5×11 inch. Margins 0.5 inch → usable 7.5×10 inch.
            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=letter,
                rightMargin=36,   # 0.5 inch
                leftMargin=36,
                topMargin=36,
                bottomMargin=36,
            )

            styles = getSampleStyleSheet()

            title_style = ParagraphStyle(
                "StoryTitle",
                parent=styles["Heading1"],
                fontSize=24,
                textColor="#2563eb",
                spaceAfter=30,
                alignment=TA_CENTER,
                fontName="Helvetica-Bold",
            )

            # B2-FIX: 22pt bold, 32pt leading, dark navy — minimum for children's book
            story_text_style = ParagraphStyle(
                "StoryText",
                parent=styles["Normal"],
                fontSize=22,
                leading=32,
                textColor="#1a1a2e",
                spaceAfter=12,
                spaceBefore=16,
                alignment=TA_LEFT,
                fontName="Helvetica-Bold",
            )

            content = []

            # ── Title page ────────────────────────────────────────────────────
            title_text = story_title.replace("{name}", child_name)
            content.append(Paragraph(title_text, title_style))
            content.append(Spacer(1, 0.5 * inch))
            content.append(PageBreak())

            # ── Story pages ───────────────────────────────────────────────────
            # B2-FIX: image fills full usable width (7.5 inch).
            # KeepTogether ensures image + text never split across pages.
            img_side = 7.5 * inch  # 1024×1024 PNG → square at full width

            for i, page_data in enumerate(pages_data, 1):
                page_elements = []

                img_path = page_data.get("image_path", "")
                if img_path and Path(img_path).exists():
                    page_elements.append(
                        RLImage(img_path, width=img_side, height=img_side)
                    )
                    page_elements.append(Spacer(1, 0.15 * inch))
                else:
                    logger.warning(
                        "PDF page %d: image not found at %r — skipping image", i, img_path,
                    )

                raw_text = page_data.get("text", "").replace("{name}", child_name)
                if raw_text.strip():
                    for line in raw_text.split("\n"):
                        if line.strip():
                            safe = (
                                line.replace("&", "&amp;")
                                    .replace("<", "&lt;")
                                    .replace(">", "&gt;")
                            )
                            page_elements.append(Paragraph(safe, story_text_style))

                if page_elements:
                    content.append(KeepTogether(page_elements))
                content.append(PageBreak())

            doc.build(content)

            pdf_size = pdf_path.stat().st_size
            logger.info(
                "PDF created: %s (%d pages, %.1f KB)",
                output_filename, len(pages_data), pdf_size / 1024,
            )
            return str(pdf_path)

        except Exception as e:
            logger.error("Error creating PDF %s: %s", output_filename, e, exc_info=True)
            raise

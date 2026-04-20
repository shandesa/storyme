"""PDF Generation Service

Builds a multi-page PDF storybook from generated page images and story text.

Key fix (2026-04-20):
  {name} is now replaced with the child's name in ALL page text, not just
  the title page. Previously page text showed literal "{name}" in the PDF.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak
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

        Args:
            child_name:      Child's name (used for {name} replacement in text)
            story_title:     Story title — may contain {name} placeholder
            pages_data:      List of dicts: {'text': str, 'image_path': str}
            output_filename: Output PDF filename (e.g. "Niku_storybook.pdf")

        Returns:
            Absolute path to the generated PDF file.

        Note on {name} replacement:
            All {name} occurrences in BOTH title and page text are replaced
            with child_name. This happens here rather than at story-definition
            time so the same story object can be reused for different children.
        """
        try:
            pdf_path = self.output_dir / output_filename

            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=letter,
                rightMargin=50,
                leftMargin=50,
                topMargin=50,
                bottomMargin=50,
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
            page_number_style = ParagraphStyle(
                "PageNumber",
                parent=styles["Normal"],
                fontSize=10,
                textColor="#6b7280",
                spaceAfter=12,
                alignment=TA_CENTER,
            )
            story_text_style = ParagraphStyle(
                "StoryText",
                parent=styles["Normal"],
                fontSize=14,
                leading=20,
                textColor="#1f2937",
                spaceAfter=20,
                alignment=TA_LEFT,
                fontName="Helvetica",
            )

            content = []

            # ── Title page ────────────────────────────────────────────────────
            # Replace {name} in title
            title_text = story_title.replace("{name}", child_name)
            content.append(Paragraph(title_text, title_style))
            content.append(Spacer(1, 0.5 * inch))
            content.append(PageBreak())

            # ── Story pages ───────────────────────────────────────────────────
            for i, page_data in enumerate(pages_data, 1):
                content.append(Paragraph(f"Page {i}", page_number_style))

                # Image
                img_path = page_data.get("image_path", "")
                if img_path and Path(img_path).exists():
                    img = RLImage(img_path, width=6 * inch, height=6 * inch)
                    content.append(img)
                    content.append(Spacer(1, 0.25 * inch))
                else:
                    logger.warning(
                        "PDF page %d: image not found at %r — skipping image",
                        i, img_path,
                    )

                # Story text — replace {name} with the child's actual name
                raw_text = page_data.get("text", "")
                page_text = raw_text.replace("{name}", child_name)

                if page_text:
                    for line in page_text.split("\n"):
                        if line.strip():
                            # Escape XML special chars for ReportLab
                            safe_line = (
                                line.replace("&", "&amp;")
                                    .replace("<", "&lt;")
                                    .replace(">", "&gt;")
                            )
                            content.append(Paragraph(safe_line, story_text_style))

                if i < len(pages_data):
                    content.append(PageBreak())

            doc.build(content)

            pdf_size = pdf_path.stat().st_size
            logger.info(
                "PDF created: %s (%d pages, %d bytes)",
                output_filename, len(pages_data), pdf_size,
            )
            return str(pdf_path)

        except Exception as e:
            logger.error("Error creating PDF %s: %s", output_filename, e, exc_info=True)
            raise

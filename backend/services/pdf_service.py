from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfgen import canvas
from pathlib import Path
from typing import List
import logging

logger = logging.getLogger(__name__)


class PDFService:
    """Handles PDF generation for storybooks."""
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def create_storybook_pdf(self, 
                            child_name: str,
                            story_title: str,
                            pages_data: List[dict],
                            output_filename: str) -> str:
        """Create a multi-page PDF storybook.
        
        Args:
            child_name: Child's name
            story_title: Story title (with {name} placeholder)
            pages_data: List of dicts with 'text', 'image_path'
            output_filename: Output PDF filename
        
        Returns:
            Path to generated PDF
        """
        try:
            pdf_path = self.output_dir / output_filename
            
            # Create PDF document
            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=letter,
                rightMargin=50,
                leftMargin=50,
                topMargin=50,
                bottomMargin=50
            )
            
            # Styles
            styles = getSampleStyleSheet()
            
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor='#2563eb',
                spaceAfter=30,
                alignment=TA_CENTER,
                fontName='Helvetica-Bold'
            )
            
            page_number_style = ParagraphStyle(
                'PageNumber',
                parent=styles['Normal'],
                fontSize=10,
                textColor='#6b7280',
                spaceAfter=12,
                alignment=TA_CENTER
            )
            
            story_text_style = ParagraphStyle(
                'StoryText',
                parent=styles['Normal'],
                fontSize=14,
                leading=20,
                textColor='#1f2937',
                spaceAfter=20,
                alignment=TA_LEFT,
                fontName='Helvetica'
            )
            
            # Build PDF content
            content = []
            
            # Title page
            title_text = story_title.replace('{name}', child_name)
            content.append(Paragraph(title_text, title_style))
            content.append(Spacer(1, 0.5 * inch))
            content.append(PageBreak())
            
            # Story pages
            for i, page_data in enumerate(pages_data, 1):
                # Image (template already contains text and personalized name)
                if page_data.get('image_path') and Path(page_data['image_path']).exists():
                    # Use full page width for the template image
                    img = RLImage(page_data['image_path'], width=7.5*inch, height=5*inch)
                    content.append(img)
                
                # Page break except for last page
                if i < len(pages_data):
                    content.append(PageBreak())
            
            # Build PDF
            doc.build(content)
            
            logger.info(f"PDF created successfully: {pdf_path}")
            return str(pdf_path)
        
        except Exception as e:
            logger.error(f"Error creating PDF: {e}")
            raise

#!/usr/bin/env python3
"""Generate placeholder template images for storybook pages."""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

# Template size (letter size at 72 DPI)
WIDTH = 612
HEIGHT = 792

# Soft, sober color palette
COLORS = [
    '#E0F2FE',  # Light blue
    '#DBEAFE',  # Lighter blue
    '#E0E7FF',  # Light indigo
    '#EDE9FE',  # Light purple
    '#F3E8FF',  # Lighter purple
    '#FCE7F3',  # Light pink
    '#FEF3C7',  # Light yellow
    '#D1FAE5',  # Light green
    '#CCFBF1',  # Light teal
    '#E5E7EB',  # Light gray
]

def create_template(page_num: int, bg_color: str, output_dir: Path):
    """Create a simple placeholder template."""
    
    # Create image with background color
    img = Image.new('RGB', (WIDTH, HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)
    
    # Add decorative border
    border_color = '#9CA3AF'  # Gray
    border_width = 3
    draw.rectangle(
        [(border_width, border_width), (WIDTH - border_width, HEIGHT - border_width)],
        outline=border_color,
        width=border_width
    )
    
    # Add page number indicator at bottom
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except:
        font = ImageFont.load_default()
    
    text = f"Page {page_num}"
    
    # Get text bounding box for centering
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    text_x = (WIDTH - text_width) // 2
    text_y = HEIGHT - 60
    
    draw.text((text_x, text_y), text, fill='#6B7280', font=font)
    
    # Add subtle decorative element (top)
    draw.ellipse([(WIDTH//2 - 30, 30), (WIDTH//2 + 30, 90)], fill='#D1D5DB', outline='#9CA3AF', width=2)
    
    # Save template
    output_path = output_dir / f"page{page_num}.png"
    img.save(output_path, 'PNG')
    print(f"Created: {output_path}")

def main():
    """Generate all template images."""
    templates_dir = Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)
    
    for i in range(1, 11):
        create_template(i, COLORS[i-1], templates_dir)
    
    print(f"\nSuccessfully created 10 template images in {templates_dir}")

if __name__ == "__main__":
    main()

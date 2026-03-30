from typing import List, Dict
from pydantic import BaseModel


class FacePlacement(BaseModel):
    """Defines where to place the child's face on a page template."""
    x: int
    y: int
    width: int
    height: int


class Page(BaseModel):
    """Represents a single page in a story."""
    page_number: int
    text: str
    face_placement: FacePlacement
    template_filename: str  # e.g., "page1.png"


class Story(BaseModel):
    """Represents a complete story with metadata and pages."""
    story_id: str
    title: str
    age_group: str  # e.g., "3-5", "6-8"
    pages: List[Page]
    
    class Config:
        frozen = False

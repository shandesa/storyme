"""Story Data Models

Defines the structure for stories and pages.
Used throughout the application for type safety and validation.
"""

from typing import List, Optional, Tuple
from pydantic import BaseModel, Field


class FacePlacement(BaseModel):
    """Defines where to place the child's face on a page template."""
    x: int = Field(..., description="X coordinate for face placement")
    y: int = Field(..., description="Y coordinate for face placement")
    width: int = Field(..., description="Face width in pixels")
    height: int = Field(..., description="Face height in pixels")
    angle: float = Field(default=0.0, description="Rotation angle in degrees (counter-clockwise)")


class NamePlacement(BaseModel):
    """Defines where to place the child's name text on a page template."""
    x: int = Field(..., description="X center coordinate for name text")
    y: int = Field(..., description="Y center coordinate for name text")
    font_size: int = Field(default=48, description="Font size for the name")
    color: Tuple[int, int, int] = Field(default=(51, 51, 51), description="RGB text color")


class Page(BaseModel):
    """Represents a single page in a story."""
    page_number: int = Field(..., description="Page number (1-indexed)")
    text: str = Field(..., description="Story text for this page")
    face_placement: FacePlacement = Field(..., description="Face placement coordinates")
    image_path: str = Field(..., description="Relative path to template image")
    name_placement: Optional[NamePlacement] = Field(default=None, description="Name text placement")
    
    class Config:
        frozen = False


class Story(BaseModel):
    """Represents a complete story with metadata and pages."""
    story_id: str = Field(..., description="Unique story identifier (snake_case)")
    title: str = Field(..., description="Human-readable story title")
    age_group: str = Field(..., description="Target age group (e.g., '3-6')")
    description: str = Field(default="", description="Story description")
    pages: List[Page] = Field(..., description="List of story pages")
    
    class Config:
        frozen = False
    
    def get_page_count(self) -> int:
        """Get total number of pages in the story."""
        return len(self.pages)


class StoryMetadata(BaseModel):
    """Story metadata without page details (for listing)."""
    story_id: str
    title: str
    age_group: str
    description: str
    page_count: int
    
    @classmethod
    def from_story(cls, story: Story):
        """Create metadata from full story object."""
        return cls(
            story_id=story.story_id,
            title=story.title,
            age_group=story.age_group,
            description=story.description,
            page_count=story.get_page_count()
        )

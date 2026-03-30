"""Story Service with Registry

Manages story metadata and provides access to stories by ID or index.
Uses storage abstraction to load page templates.

Design:
- STORIES registry contains story metadata
- Story pages reference template paths (not absolute paths)
- Storage abstraction handles actual file loading
- Easy to add new stories without code changes
"""

from typing import List, Optional
from models.story import Story, Page, FacePlacement, StoryMetadata
from core.storage import storage
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# STORY REGISTRY
# ============================================================================

class StoryRegistry:
    """Centralized registry for all available stories."""
    
    def __init__(self):
        """Initialize story registry."""
        self._stories: List[Story] = self._initialize_stories()
        logger.info(f"StoryRegistry initialized with {len(self._stories)} stories")
    
    def _initialize_stories(self) -> List[Story]:
        """Initialize all available stories.
        
        Returns:
            List of Story objects
        """
        stories = []
        
        # ========================================================================
        # Story 1: Forest of Smiles
        # ========================================================================
        forest_story = Story(
            story_id="forest_of_smiles",
            title="{name} and the Forest of Smiles",
            age_group="3-6",
            description="A magical adventure where your child meets friendly animals and learns about kindness, peace, and joy.",
            pages=[
                Page(
                    page_number=1,
                    text="One sunny morning, {name} walked into a beautiful forest filled with soft light and gentle sounds.\\n\\nEverything felt magical… as if the forest was waiting just for {name}.",
                    face_placement=FacePlacement(x=220, y=180, width=160, height=160),
                    image_path="templates/stories/forest_of_smiles/page1.png"
                ),
                Page(
                    page_number=2,
                    text="A fluffy rabbit hopped closer and said,\\n\\\"Hello {name}! Welcome to the Forest of Smiles.\\\"\\n\\n{name} blinked… the rabbit could talk!",
                    face_placement=FacePlacement(x=200, y=200, width=150, height=150),
                    image_path="templates/stories/forest_of_smiles/page2.png"
                ),
                Page(
                    page_number=3,
                    text="Above them, birds sang sweet songs.\\n\\\"Sing with us, {name}!\\\" they chirped happily.\\n\\n{name} smiled and listened to the melody.",
                    face_placement=FacePlacement(x=230, y=220, width=140, height=140),
                    image_path="templates/stories/forest_of_smiles/page3.png"
                ),
                Page(
                    page_number=4,
                    text="A big gentle elephant came forward and said,\\n\\\"Kindness makes the forest shine.\\\"\\n\\n{name} touched its trunk and felt happy.",
                    face_placement=FacePlacement(x=210, y=210, width=150, height=150),
                    image_path="templates/stories/forest_of_smiles/page4.png"
                ),
                Page(
                    page_number=5,
                    text="A slow turtle whispered,\\n\\\"Take your time, {name}. Every moment is special.\\\"\\n\\n{name} walked slowly… and noticed tiny flowers.",
                    face_placement=FacePlacement(x=240, y=230, width=140, height=140),
                    image_path="templates/stories/forest_of_smiles/page5.png"
                ),
                Page(
                    page_number=6,
                    text="A monkey swung down laughing,\\n\\\"Let's play, {name}!\\\"\\n\\n{name} giggled and clapped with joy.",
                    face_placement=FacePlacement(x=200, y=190, width=150, height=150),
                    image_path="templates/stories/forest_of_smiles/page6.png"
                ),
                Page(
                    page_number=7,
                    text="A deer stood quietly and said,\\n\\\"Peace lives in your heart, {name}.\\\"\\n\\n{name} took a deep breath and smiled softly.",
                    face_placement=FacePlacement(x=220, y=210, width=150, height=150),
                    image_path="templates/stories/forest_of_smiles/page7.png"
                ),
                Page(
                    page_number=8,
                    text="As evening came, tiny fireflies glowed around {name}.\\n\\\"You bring light wherever you go,\\\" they whispered.\\n\\n{name} felt warm and special.",
                    face_placement=FacePlacement(x=230, y=200, width=140, height=140),
                    image_path="templates/stories/forest_of_smiles/page8.png"
                ),
                Page(
                    page_number=9,
                    text="A big tree spoke gently,\\n\\\"You are kind, brave, and wonderful, {name}.\\\"\\n\\n{name} hugged the tree with love.",
                    face_placement=FacePlacement(x=210, y=220, width=150, height=150),
                    image_path="templates/stories/forest_of_smiles/page9.png"
                ),
                Page(
                    page_number=10,
                    text="As {name} walked home, the forest whispered,\\n\\\"Come back anytime.\\\"\\n\\nAnd {name} knew… the smiles would always stay in the heart.",
                    face_placement=FacePlacement(x=220, y=200, width=150, height=150),
                    image_path="templates/stories/forest_of_smiles/page10.png"
                )
            ]
        )
        
        stories.append(forest_story)
        
        # ========================================================================
        # Future: Add more stories here
        # ========================================================================
        # stories.append(ocean_adventure_story)
        # stories.append(space_journey_story)
        
        return stories
    
    # ========================================================================
    # Access Methods
    # ========================================================================
    
    def get_story_by_id(self, story_id: str) -> Optional[Story]:
        """Get story by its ID.
        
        Args:
            story_id: Story identifier (e.g., 'forest_of_smiles')
        
        Returns:
            Story object or None if not found
        """
        for story in self._stories:
            if story.story_id == story_id:
                logger.debug(f"Story found by ID: {story_id}")
                return story
        
        logger.warning(f"Story not found by ID: {story_id}")
        return None
    
    def get_story_by_index(self, index: int) -> Optional[Story]:
        """Get story by its index position.
        
        Args:
            index: Story index (0-based)
        
        Returns:
            Story object or None if index out of range
        """
        if 0 <= index < len(self._stories):
            logger.debug(f"Story found by index: {index}")
            return self._stories[index]
        
        logger.warning(f"Story not found by index: {index}")
        return None
    
    def list_stories(self) -> List[StoryMetadata]:
        """Get list of all available stories (metadata only).
        
        Returns:
            List of StoryMetadata objects
        """
        metadata_list = [StoryMetadata.from_story(story) for story in self._stories]
        logger.debug(f"Listed {len(metadata_list)} stories")
        return metadata_list
    
    def get_story_count(self) -> int:
        """Get total number of available stories.
        
        Returns:
            Number of stories
        """
        return len(self._stories)
    
    def get_stories_by_age_group(self, age_group: str) -> List[Story]:
        """Get stories filtered by age group.
        
        Args:
            age_group: Age group (e.g., '3-6', '6-8')
        
        Returns:
            List of Story objects
        """
        filtered = [s for s in self._stories if s.age_group == age_group]
        logger.debug(f"Found {len(filtered)} stories for age group: {age_group}")
        return filtered
    
    # ========================================================================
    # Template Path Resolution (uses storage abstraction)
    # ========================================================================
    
    def get_page_template_path(self, story_id: str, page_number: int) -> Optional[str]:
        """Get the full path to a page template using storage abstraction.
        
        Args:
            story_id: Story identifier
            page_number: Page number (1-indexed)
        
        Returns:
            Full path/URL to template or None if not found
        """
        story = self.get_story_by_id(story_id)
        if not story:
            return None
        
        # Find the page
        for page in story.pages:
            if page.page_number == page_number:
                # Use storage abstraction to get full path
                return storage.get_file_path(page.image_path)
        
        return None
    
    def verify_story_templates(self, story_id: str) -> dict:
        """Verify all template files exist for a story.
        
        Args:
            story_id: Story identifier
        
        Returns:
            Dictionary with verification results
        """
        story = self.get_story_by_id(story_id)
        if not story:
            return {'error': f'Story not found: {story_id}'}
        
        results = {
            'story_id': story_id,
            'total_pages': len(story.pages),
            'verified': 0,
            'missing': [],
        }
        
        for page in story.pages:
            if storage.file_exists(page.image_path):
                results['verified'] += 1
            else:
                results['missing'].append({
                    'page': page.page_number,
                    'path': page.image_path
                })
        
        logger.info(f"Template verification for {story_id}: "
                   f"{results['verified']}/{results['total_pages']} found")
        
        return results


# ============================================================================
# Singleton Instance
# ============================================================================

story_registry = StoryRegistry()

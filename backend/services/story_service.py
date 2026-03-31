"""Story Service with Registry

Manages story metadata and provides access to stories by ID or index.
Uses storage abstraction to load page templates.
"""

from typing import List, Optional
from models.story import (
    Story, Page, FacePlacement, NamePlacement,
    StoryMetadata, FaceCircle, NameTextRegion,
)
from core.storage import storage
import logging

logger = logging.getLogger(__name__)


class StoryRegistry:
    """Centralized registry for all available stories."""

    def __init__(self):
        self._stories: List[Story] = self._initialize_stories()
        logger.info(f"StoryRegistry initialized with {len(self._stories)} stories")

    def _initialize_stories(self) -> List[Story]:
        stories = []

        # ================================================================
        # Story 1: Forest of Smiles
        # ================================================================
        # Page 1: 1536x1024 illustrated template with:
        #   - White face circle at center=(985,382), radius=135
        #   - Baked-in "{name}" text at ~(y=186-210, x=270-410)
        #   - Character looking slightly down-left, brown hair, yellow shirt
        #   - Text color: dark brown ~RGB(134, 105, 54)
        #
        # Pages 2-10: 612x792 solid-color backgrounds.
        # ================================================================

        forest_story = Story(
            story_id="forest_of_smiles",
            title="{name} and the Forest of Smiles",
            age_group="3-6",
            description="A magical adventure where your child meets friendly animals and learns about kindness, peace, and joy.",
            pages=[
                Page(
                    page_number=1,
                    text="One sunny morning, {name} walked into a beautiful forest filled with soft light and gentle sounds.\n\nEverything felt magical... as if the forest was waiting just for {name}.",
                    face_placement=FacePlacement(x=850, y=247, width=270, height=270, angle=0.0),
                    image_path="templates/stories/forest_of_smiles/page1.png",
                    face_circle=FaceCircle(cx=985, cy=382, radius=135),
                    name_text_regions=[
                        NameTextRegion(x1=146, y1=110, x2=676, y2=150,
                                       line_text="{name} and the Forest of Smiles"),
                        NameTextRegion(x1=197, y1=172, x2=616, y2=208,
                                       line_text='"Hello {name}! Welcome to'),
                    ],
                    name_placement=NamePlacement(x=335, y=197, font_size=28, color=(134, 105, 54)),
                ),
                Page(
                    page_number=2,
                    text='A fluffy rabbit hopped closer and said,\n"Hello {name}! Welcome to the Forest of Smiles."\n\n{name} blinked... the rabbit could talk!',
                    face_placement=FacePlacement(x=230, y=120, width=120, height=120, angle=0.0),
                    image_path="templates/stories/forest_of_smiles/page2.png",
                    name_placement=NamePlacement(x=306, y=700, font_size=36, color=(51, 51, 51)),
                ),
                Page(
                    page_number=3,
                    text='Above them, birds sang sweet songs.\n"Sing with us, {name}!" they chirped happily.\n\n{name} smiled and listened to the melody.',
                    face_placement=FacePlacement(x=240, y=130, width=120, height=120, angle=0.0),
                    image_path="templates/stories/forest_of_smiles/page3.png",
                    name_placement=NamePlacement(x=306, y=700, font_size=36, color=(51, 51, 51)),
                ),
                Page(
                    page_number=4,
                    text='A big gentle elephant came forward and said,\n"Kindness makes the forest shine."\n\n{name} touched its trunk and felt happy.',
                    face_placement=FacePlacement(x=230, y=120, width=120, height=120, angle=0.0),
                    image_path="templates/stories/forest_of_smiles/page4.png",
                    name_placement=NamePlacement(x=306, y=700, font_size=36, color=(51, 51, 51)),
                ),
                Page(
                    page_number=5,
                    text='A slow turtle whispered,\n"Take your time, {name}. Every moment is special."\n\n{name} walked slowly... and noticed tiny flowers.',
                    face_placement=FacePlacement(x=240, y=130, width=120, height=120, angle=0.0),
                    image_path="templates/stories/forest_of_smiles/page5.png",
                    name_placement=NamePlacement(x=306, y=700, font_size=36, color=(51, 51, 51)),
                ),
                Page(
                    page_number=6,
                    text='A monkey swung down laughing,\n"Let\'s play, {name}!"\n\n{name} giggled and clapped with joy.',
                    face_placement=FacePlacement(x=230, y=120, width=120, height=120, angle=0.0),
                    image_path="templates/stories/forest_of_smiles/page6.png",
                    name_placement=NamePlacement(x=306, y=700, font_size=36, color=(51, 51, 51)),
                ),
                Page(
                    page_number=7,
                    text='A deer stood quietly and said,\n"Peace lives in your heart, {name}."\n\n{name} took a deep breath and smiled softly.',
                    face_placement=FacePlacement(x=240, y=130, width=120, height=120, angle=0.0),
                    image_path="templates/stories/forest_of_smiles/page7.png",
                    name_placement=NamePlacement(x=306, y=700, font_size=36, color=(51, 51, 51)),
                ),
                Page(
                    page_number=8,
                    text='As evening came, tiny fireflies glowed around {name}.\n"You bring light wherever you go," they whispered.\n\n{name} felt warm and special.',
                    face_placement=FacePlacement(x=230, y=120, width=120, height=120, angle=0.0),
                    image_path="templates/stories/forest_of_smiles/page8.png",
                    name_placement=NamePlacement(x=306, y=700, font_size=36, color=(51, 51, 51)),
                ),
                Page(
                    page_number=9,
                    text='A big tree spoke gently,\n"You are kind, brave, and wonderful, {name}."\n\n{name} hugged the tree with love.',
                    face_placement=FacePlacement(x=240, y=130, width=120, height=120, angle=0.0),
                    image_path="templates/stories/forest_of_smiles/page9.png",
                    name_placement=NamePlacement(x=306, y=700, font_size=36, color=(51, 51, 51)),
                ),
                Page(
                    page_number=10,
                    text='As {name} walked home, the forest whispered,\n"Come back anytime."\n\nAnd {name} knew... the smiles would always stay in the heart.',
                    face_placement=FacePlacement(x=230, y=120, width=120, height=120, angle=0.0),
                    image_path="templates/stories/forest_of_smiles/page10.png",
                    name_placement=NamePlacement(x=306, y=700, font_size=36, color=(51, 51, 51)),
                ),
            ],
        )

        stories.append(forest_story)
        return stories

    # ================================================================
    # Access Methods
    # ================================================================

    def get_story_by_id(self, story_id: str) -> Optional[Story]:
        for story in self._stories:
            if story.story_id == story_id:
                return story
        return None

    def get_story_by_index(self, index: int) -> Optional[Story]:
        if 0 <= index < len(self._stories):
            return self._stories[index]
        return None

    def list_stories(self) -> List[StoryMetadata]:
        return [StoryMetadata.from_story(s) for s in self._stories]

    def get_story_count(self) -> int:
        return len(self._stories)

    def get_stories_by_age_group(self, age_group: str) -> List[Story]:
        return [s for s in self._stories if s.age_group == age_group]

    def get_page_template_path(self, story_id: str, page_number: int) -> Optional[str]:
        story = self.get_story_by_id(story_id)
        if not story:
            return None
        for page in story.pages:
            if page.page_number == page_number:
                return storage.get_file_path(page.image_path)
        return None

    def verify_story_templates(self, story_id: str) -> dict:
        story = self.get_story_by_id(story_id)
        if not story:
            return {"error": f"Story not found: {story_id}"}
        results = {
            "story_id": story_id,
            "total_pages": len(story.pages),
            "verified": 0,
            "missing": [],
        }
        for page in story.pages:
            if storage.file_exists(page.image_path):
                results["verified"] += 1
            else:
                results["missing"].append({"page": page.page_number, "path": page.image_path})
        logger.info(
            f"Template verification for {story_id}: "
            f"{results['verified']}/{results['total_pages']} found"
        )
        return results


# Singleton
story_registry = StoryRegistry()

"""Story Service with Registry

Manages story metadata and provides access to stories by ID or index.

Template structure (new, gendered):
  backend/templates/stories/{story_id}/{gender}/templates/scene_XX.png
  backend/templates/stories/{story_id}/{gender}/references/scene_XX.png

Face coordinates sourced from tests/playground/face_blend.py face_config,
which were measured against the actual illustrated scene images.

Gender variants: male | female | neutral (same templates currently,
separate paths so per-gender art can be swapped in without code changes).
"""

from typing import List, Optional, Dict
from pathlib import Path
from models.story import (
    Story, Page, FacePlacement, NamePlacement,
    StoryMetadata, FaceCircle, NameTextRegion,
)
from models.generation import Gender
from core.storage_paths import (
    story_template_path, story_reference_path, GENDER_NEUTRAL,
)
from core.storage import storage
from core.config import config
import logging

logger = logging.getLogger(__name__)

# ─── Face coordinates (from playground/face_blend.py) ─────────────────────────
# These were measured against the actual illustrated scene images.
# Keys are scene filenames (scene_01.png ... scene_10.png).
# Values are pixel coords in the template image: x, y = top-left, w/h = size.
#
# scenes 01-05: portrait orientation (1024 × 1536)
# scenes 06-10: landscape orientation (1536 × 1024)

FACE_COORDS: Dict[str, Dict[str, int]] = {
    "scene_01.png": {"x": 297, "y": 608, "w": 192, "h": 180},
    "scene_02.png": {"x": 280, "y": 848, "w": 220, "h": 185},
    "scene_03.png": {"x": 365, "y": 764, "w": 200, "h": 175},
    "scene_04.png": {"x": 290, "y": 478, "w": 193, "h": 178},
    "scene_05.png": {"x": 180, "y": 524, "w": 173, "h": 158},
    "scene_06.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_07.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_08.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_09.png": {"x": 586, "y": 148, "w": 116, "h": 122},
    "scene_10.png": {"x": 586, "y": 148, "w": 116, "h": 122},
}

# Scene files ordered by page number (1-based)
SCENE_FILES = [f"scene_{i:02d}.png" for i in range(1, 11)]


class StoryRegistry:
    """Centralized registry for all available stories."""

    def __init__(self):
        self._stories: List[Story] = self._initialize_stories()
        logger.info("StoryRegistry initialized with %d stories", len(self._stories))

    def _make_pages(self, story_id: str, gender: str) -> List[Page]:
        """
        Build the page list for a story using the gendered template paths
        and face coordinates from FACE_COORDS.

        Template local path pattern:
          templates/stories/{story_id}/{gender}/templates/scene_XX.png

        This relative path is resolved against config.BACKEND_DIR by
        image_service.compose_page() and verify_story_templates().
        """
        story_texts = _FOREST_OF_SMILES_TEXTS  # per-story text dict

        pages = []
        for i, scene_file in enumerate(SCENE_FILES, start=1):
            coords = FACE_COORDS[scene_file]
            # Relative path from backend/ root — resolved locally by image_service
            template_rel = f"templates/stories/{story_id}/{gender}/templates/{scene_file}"

            # Page 1 has special name text regions baked into the template
            name_text_regions = None
            face_circle = None
            name_placement = None

            if i == 1:
                # Page 1 has a white face circle and baked-in {name} text
                # (These values are for the page1 template which is the illustrated
                # scene_01 from the playground)
                name_text_regions = [
                    NameTextRegion(
                        x1=50, y1=30, x2=700, y2=80,
                        line_text="{name} and the Forest of Smiles",
                    ),
                ]
                name_placement = NamePlacement(
                    x=375, y=55, font_size=32, color=(134, 105, 54),
                )
            else:
                name_placement = NamePlacement(
                    x=512, y=1480, font_size=36, color=(51, 51, 51),
                )

            pages.append(Page(
                page_number=i,
                text=story_texts.get(i, f"Page {i} of the story."),
                face_placement=FacePlacement(
                    x=coords["x"],
                    y=coords["y"],
                    width=coords["w"],
                    height=coords["h"],
                    angle=0.0,
                ),
                image_path=template_rel,
                name_placement=name_placement,
                face_circle=face_circle,
                name_text_regions=name_text_regions,
            ))

        return pages

    def _initialize_stories(self) -> List[Story]:
        stories = []

        # ── Forest of Smiles ──────────────────────────────────────────────────
        # Templates: tests/playground/templates/forrest_of_smiles/scene_01-10.png
        # Copied to:  backend/templates/stories/forest_of_smiles/{gender}/templates/
        # Face coords: FACE_COORDS (measured from actual illustrated scenes)

        forest_story = Story(
            story_id="forest_of_smiles",
            title="{name} and the Forest of Smiles",
            age_group="3-6",
            description=(
                "A magical adventure where your child meets friendly animals "
                "and learns about kindness, peace, and joy."
            ),
            pages=self._make_pages("forest_of_smiles", GENDER_NEUTRAL),
        )
        stories.append(forest_story)

        return stories

    # ─── Access methods ───────────────────────────────────────────────────────

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

    def get_reference_path(
        self, story_id: str, gender: str, scene_filename: str,
    ) -> str:
        """
        Return the local absolute path to a reference image for a given scene.
        Reference images are used by face_blend_service for landmark alignment.
        """
        rel = story_reference_path(story_id, gender, scene_filename)
        return str(config.BACKEND_DIR / rel)

    def verify_story_templates(self, story_id: str) -> dict:
        """
        Verify that all template image files exist for a story.

        Checks local filesystem only — templates are bundled assets shipped
        with the app. They are never in Azure Blob (blob = user uploads + PDFs).
        """
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
            local_path = config.BACKEND_DIR / page.image_path
            if local_path.exists():
                results["verified"] += 1
                logger.debug("Template OK (local): %s", local_path)
            else:
                results["missing"].append({
                    "page": page.page_number,
                    "path": page.image_path,
                    "local_checked": str(local_path),
                })
                logger.warning(
                    "Template MISSING: %s — expected at %s",
                    page.image_path, local_path,
                )

        logger.info(
            "Template verification for %s: %d/%d found locally",
            story_id, results["verified"], results["total_pages"],
        )
        return results


# ─── Story texts ──────────────────────────────────────────────────────────────
# {name} placeholders are replaced with the child's name at render time.

_FOREST_OF_SMILES_TEXTS: Dict[int, str] = {
    1: (
        "One sunny morning, {name} walked into a beautiful forest "
        "filled with soft light and gentle sounds.\n\n"
        "Everything felt magical... as if the forest was waiting just for {name}."
    ),
    2: (
        'A fluffy rabbit hopped closer and said,\n'
        '"Hello {name}! Welcome to the Forest of Smiles."\n\n'
        "{name} blinked... the rabbit could talk!"
    ),
    3: (
        'Above them, birds sang sweet songs.\n'
        '"Sing with us, {name}!" they chirped happily.\n\n'
        "{name} smiled and listened to the melody."
    ),
    4: (
        'A big gentle elephant came forward and said,\n'
        '"Kindness makes the forest shine."\n\n'
        "{name} touched its trunk and felt happy."
    ),
    5: (
        'A slow turtle whispered,\n'
        '"Take your time, {name}. Every moment is special."\n\n'
        "{name} walked slowly... and noticed tiny flowers."
    ),
    6: (
        'A monkey swung down laughing,\n'
        '"Let\'s play, {name}!"\n\n'
        "{name} giggled and clapped with joy."
    ),
    7: (
        'A deer stood quietly and said,\n'
        '"Peace lives in your heart, {name}."\n\n'
        "{name} took a deep breath and smiled softly."
    ),
    8: (
        'As evening came, tiny fireflies glowed around {name}.\n'
        '"You bring light wherever you go," they whispered.\n\n'
        "{name} felt warm and special."
    ),
    9: (
        'A big tree spoke gently,\n'
        '"You are kind, brave, and wonderful, {name}."\n\n'
        "{name} hugged the tree with love."
    ),
    10: (
        'As {name} walked home, the forest whispered,\n'
        '"Come back anytime."\n\n'
        "And {name} knew... the smiles would always stay in the heart."
    ),
}


# Singleton
story_registry = StoryRegistry()

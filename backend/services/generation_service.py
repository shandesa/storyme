"""Generation Service

Stateless story preview generator.

Orchestrates:
  - story_registry  → page metadata & template paths
  - image_service   → face extraction + page compositing

Supports two modes:
  template  (default) — composites face onto pre-designed PNG templates
  dalle               — generates base image via DALL-E (experimental)
"""

import uuid
import logging
from pathlib import Path
from typing import List, Dict, Any

from services.story_service import story_registry
from services.image_service import image_service

logger = logging.getLogger(__name__)

# Temporary blended images live here during preview generation.
BLENDED_DIR = Path("tmp/blended")


class GenerationService:

    # ============================================================
    # PUBLIC: STORY LISTING
    # ============================================================

    def list_stories(self) -> List[Dict[str, Any]]:
        """Return serialisable list of all available stories."""
        return [
            {
                "story_id": s.story_id,
                "title": s.title,
                "description": s.description,
                "age_group": s.age_group,
                "total_pages": len(story_registry.get_story_by_id(s.story_id).pages),
            }
            for s in story_registry.list_stories()
        ]

    # ============================================================
    # PUBLIC ENTRY POINT
    # ============================================================

    async def generate_preview_stateless(
        self,
        child_name: str,
        story_id: str,
        face_image_path: str,
        mode: str = "template",
    ) -> str:
        """
        Stateless preview generator — returns the path to a composited page-1 PNG.

        Modes:
          template  → composites face onto a pre-designed PNG template (production)
          dalle     → generates base image via DALL-E then composites (experimental)
        """
        if mode == "template":
            return await self._generate_preview_from_template(
                child_name, story_id, face_image_path
            )
        elif mode == "dalle":
            return await self._generate_preview_from_dalle(
                child_name, story_id, face_image_path
            )
        else:
            raise ValueError(f"Invalid mode: {mode!r}. Expected 'template' or 'dalle'.")

    # ============================================================
    # TEMPLATE-BASED GENERATION (PRIMARY / PRODUCTION)
    # ============================================================

    async def _generate_preview_from_template(
        self,
        child_name: str,
        story_id: str,
        face_image_path: str,
    ) -> str:
        """
        Uses pre-designed PNG templates + image_service.

        Pipeline:
          1. Load story metadata -> page 1 config
          2. Extract & feather-mask face via image_service
          3. Composite face + name onto template via image_service
          4. Write blended PNG to BLENDED_DIR and return its path
        """
        try:
            story = story_registry.get_story_by_id(story_id)
            if not story:
                raise ValueError(f"Story not found: {story_id!r}")

            page = story.pages[0]
            fp = page.face_placement

            logger.info(
                f"Template preview: story={story_id}, child={child_name!r}, "
                f"template={page.image_path}"
            )

            # 1. Extract face from uploaded photo
            face_img = image_service.extract_face(
                face_image_path,
                (fp.width, fp.height),
                angle=fp.angle,
            )

            # 2. Resolve output path
            BLENDED_DIR.mkdir(parents=True, exist_ok=True)
            out_storage_path = f"tmp/blended/{uuid.uuid4().hex}_preview.png"

            # 3. Build optional compositing params from page metadata
            name_pos = None
            name_font_size = 48
            name_color = (51, 51, 51)
            if page.name_placement:
                name_pos = (page.name_placement.x, page.name_placement.y)
                name_font_size = page.name_placement.font_size
                name_color = page.name_placement.color

            circle_center = None
            circle_radius = None
            if page.face_circle:
                circle_center = (page.face_circle.cx, page.face_circle.cy)
                circle_radius = page.face_circle.radius

            text_regions = None
            if page.name_text_regions:
                text_regions = [
                    (r.x1, r.y1, r.x2, r.y2, r.line_text) if r.line_text
                    else (r.x1, r.y1, r.x2, r.y2)
                    for r in page.name_text_regions
                ]

            # 4. Composite page
            composed_path = image_service.compose_page(
                page.image_path,
                face_img,
                (fp.x, fp.y),
                out_storage_path,
                child_name=child_name,
                name_position=name_pos,
                name_font_size=name_font_size,
                name_color=name_color,
                face_circle_center=circle_center,
                face_circle_radius=circle_radius,
                name_text_regions=text_regions,
            )

            logger.info(f"Template preview generated: {composed_path}")
            return composed_path

        except Exception as e:
            logger.error(f"Template preview failed: {e}", exc_info=True)
            raise

    # ============================================================
    # DALLE-BASED GENERATION (EXPERIMENTAL / FUTURE)
    # ============================================================

    async def _generate_preview_from_dalle(
        self,
        child_name: str,
        story_id: str,
        face_image_path: str,
    ) -> str:
        """
        Generates the base scene via DALL-E then composites the face.
        Requires OPENAI_API_KEY and services.dalle_service.
        Falls back with a clear error if not configured.
        """
        try:
            from services.dalle_service import dalle_service  # lazy import
        except ImportError as exc:
            raise ImportError(
                "DALL-E mode requires services.dalle_service and OPENAI_API_KEY. "
                f"Original error: {exc}"
            ) from exc

        try:
            story = story_registry.get_story_by_id(story_id)
            if not story:
                raise ValueError(f"Story not found: {story_id!r}")

            page = story.pages[0]
            fp = page.face_placement

            prompt = (
                "Pixar-style children's book illustration, soft pastel colors, "
                "warm lighting, cinematic composition, shallow depth of field. "
                f"Scene: {page.text[:120]}"
            )

            template_path, meta = await dalle_service.generate_image(
                prompt=prompt,
                story_id=story_id,
                page_number=page.page_number,
                size=getattr(story, "image_size", "1024x1024"),
            )

            if not template_path:
                raise ValueError("DALL-E did not return a template_path")

            logger.info(f"DALL-E image generated: {template_path}")

            face_img = image_service.extract_face(
                face_image_path,
                (fp.width, fp.height),
                angle=fp.angle,
            )

            BLENDED_DIR.mkdir(parents=True, exist_ok=True)
            out_storage_path = f"tmp/blended/{uuid.uuid4().hex}_dalle_preview.png"

            face_bbox = meta.get("face_bbox") or {}
            circle_center = (
                (face_bbox["cx"], face_bbox["cy"]) if "cx" in face_bbox else None
            )
            circle_radius = face_bbox.get("radius")

            composed_path = image_service.compose_page(
                template_path,
                face_img,
                (fp.x, fp.y),
                out_storage_path,
                child_name=child_name,
                face_circle_center=circle_center,
                face_circle_radius=circle_radius,
            )

            logger.info(f"DALL-E preview generated: {composed_path}")
            return composed_path

        except Exception as e:
            logger.error(f"DALL-E preview failed: {e}", exc_info=True)
            raise


# ── Module-level singleton ─────────────────────────────────────────────────────
# This is what generate_v2.py imports:
#   from services.generation_service import generation_service
#
# BUG HISTORY: This singleton was previously missing, causing:
#   ImportError: cannot import name 'generation_service' from
#   'services.generation_service'
# which silently disabled ALL generation routes at startup.
generation_service = GenerationService()

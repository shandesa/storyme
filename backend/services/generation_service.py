import uuid
import logging
from pathlib import Path

from core.storage import storage
from services.story_service import story_registry

logger = logging.getLogger(__name__)

# Directory for generated outputs
BLENDED_DIR = Path("tmp/blended")


class GenerationService:

    # ============================================================
    # PUBLIC ENTRY POINT
    # ============================================================

    async def generate_preview_stateless(
        self,
        child_name: str,
        story_id: str,
        face_image_path: str,
        mode: str = "template",  # "template" or "dalle"
    ) -> str:
        """
        Stateless preview generator.

        Modes:
        - template → uses predefined templates (current production)
        - dalle    → uses DALL-E generated images (experimental)
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
            raise ValueError(f"Invalid mode: {mode}")

    # ============================================================
    # TEMPLATE-BASED GENERATION (PRIMARY)
    # ============================================================

    async def _generate_preview_from_template(
        self,
        child_name: str,
        story_id: str,
        face_image_path: str,
    ) -> str:
        """
        Uses predefined templates from story_service + storage layer.
        """

        try:
            story = story_registry.get_story_by_id(story_id)
            if not story:
                raise ValueError(f"Story not found: {story_id}")

            page = story.pages[0]

            # ✅ Resolve template path via storage (CRITICAL FIX)
            template_path = storage.get_file_path(page.image_path)

            logger.info(f"Using template: {template_path}")

            # Output path
            BLENDED_DIR.mkdir(parents=True, exist_ok=True)
            output_path = BLENDED_DIR / f"{uuid.uuid4().hex}_preview.png"

            # Process page
            _process_page(
                template_path=template_path,
                user_face_path=face_image_path,
                face_bbox={
                    "x": page.face_placement.x,
                    "y": page.face_placement.y,
                    "width": page.face_placement.width,
                    "height": page.face_placement.height,
                },
                text_area=None,  # template already defines layout
                story_lines=[page.text],
                child_name=child_name,
                output_path=str(output_path),
            )

            logger.info(f"Template preview generated: {output_path}")
            return str(output_path)

        except Exception as e:
            logger.error(f"Template preview failed: {e}", exc_info=True)
            raise

    # ============================================================
    # DALLE-BASED GENERATION (SECONDARY / FUTURE)
    # ============================================================

    async def _generate_preview_from_dalle(
        self,
        child_name: str,
        story_id: str,
        face_image_path: str,
    ) -> str:
        """
        Uses DALL-E to generate base image dynamically.
        """

        try:
            story = _load_story(story_id)
            page = story["pages"][0]

            prompt = _build_prompt(story, page)

            template_path, meta = await dalle_service.generate_image(
                prompt=prompt,
                story_id=story_id,
                page_number=page["page_number"],
                size=story.get("image_size", "1024x1024"),
            )

            if not template_path:
                raise ValueError("DALL-E did not return template_path")

            logger.info(f"DALL-E image generated: {template_path}")

            BLENDED_DIR.mkdir(parents=True, exist_ok=True)
            output_path = BLENDED_DIR / f"{uuid.uuid4().hex}_preview.png"

            _process_page(
                template_path=template_path,
                user_face_path=face_image_path,
                face_bbox=meta.get("face_bbox"),
                text_area=meta.get("text_area"),
                story_lines=page["story_lines"],
                child_name=child_name,
                output_path=str(output_path),
            )

            logger.info(f"DALL-E preview generated: {output_path}")
            return str(output_path)

        except Exception as e:
            logger.error(f"DALL-E preview failed: {e}", exc_info=True)
            raise

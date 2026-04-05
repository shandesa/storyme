"""Generation Orchestrator Service

Manages the full storybook generation lifecycle:
1. Create session
2. Preview (page 1 only)
3. Generate all pages (DALL-E → face blend → text overlay)
4. Create PDF

DALL-E images + coordinates are cached by (story_id, page_number).
Face blending and text overlay are per-session (per-user).
"""

import os
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

from services.dalle_service import dalle_service
from services.face_blend_service import face_blend_service, overlay_text_on_image
from services.pdf_service import PDFService

load_dotenv()

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).parent.parent
DATA_DIR = BACKEND_DIR / "data" / "stories"
CACHE_DIR = BACKEND_DIR / "cache"
BLENDED_DIR = CACHE_DIR / "blended"
PDF_DIR = CACHE_DIR / "pdfs"

for d in [BLENDED_DIR, PDF_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def _load_story(story_id: str) -> dict:
    p = DATA_DIR / f"{story_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Story not found: {story_id}")
    with open(p) as f:
        return json.load(f)


def _build_prompt(story: dict, page: dict) -> str:
    return story["common_prompt_template"] + "\n\n" + page["scene_prompt"]


def _process_page(
    template_path: str,
    user_face_path: str,
    face_bbox: dict,
    text_area: dict,
    story_lines: List[str],
    child_name: str,
    output_path: str,
) -> str:
    """Full page processing: face blend → text overlay."""
    # Step 1: Blend face
    blended_path = output_path.replace(".png", "_blended.png")
    face_blend_service.blend_face_into_template(
        template_path=template_path,
        user_face_path=user_face_path,
        face_bbox=face_bbox,
        output_path=blended_path,
    )

    # Step 2: Overlay text with name substitution
    lines = [line.replace("{name}", child_name) for line in story_lines]
    overlay_text_on_image(
        image_path=blended_path,
        text_lines=lines,
        text_area=text_area,
        output_path=output_path,
    )

    # Clean intermediate file
    if Path(blended_path).exists() and blended_path != output_path:
        Path(blended_path).unlink(missing_ok=True)

    return output_path


class GenerationService:
    def __init__(self):
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "storyme_db")
        self._client = AsyncIOMotorClient(mongo_url)
        self._db = self._client[db_name]
        self._sessions = self._db.generation_sessions
        self._pdf_service = PDFService(str(PDF_DIR))

    def list_stories(self) -> List[dict]:
        stories = []
        for f in DATA_DIR.glob("*.json"):
            with open(f) as fp:
                data = json.load(fp)
            stories.append({
                "story_id": data["story_id"],
                "title": data["title"],
                "total_pages": data["total_pages"],
            })
        return stories

    async def create_session(
        self, child_name: str, story_id: str, face_image_path: str
    ) -> str:
        session_id = uuid.uuid4().hex[:12]
        doc = {
            "session_id": session_id,
            "child_name": child_name,
            "story_id": story_id,
            "face_image_path": face_image_path,
            "status": "created",
            "progress": 0,
            "total_pages": 0,
            "preview_path": None,
            "blended_pages": [],
            "pdf_path": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._sessions.insert_one(doc)
        logger.info(f"Session created: {session_id} for '{child_name}'")
        return session_id

    async def get_session(self, session_id: str) -> Optional[dict]:
        return await self._sessions.find_one(
            {"session_id": session_id}, {"_id": 0}
        )

    async def _update_session(self, session_id: str, updates: dict):
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._sessions.update_one(
            {"session_id": session_id}, {"$set": updates}
        )

    async def generate_preview(self, session_id: str) -> str:
        """Generate page 1 with face + text overlay. Returns image path."""
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        story = _load_story(session["story_id"])
        page = story["pages"][0]
        prompt = _build_prompt(story, page)

        await self._update_session(session_id, {
            "status": "generating_preview",
            "total_pages": story["total_pages"],
        })

        # Generate DALL-E image + extract coordinates
        template_path, meta = await dalle_service.generate_image(
            prompt=prompt,
            story_id=session["story_id"],
            page_number=page["page_number"],
            size=story.get("image_size", "1024x1024"),
        )

        # Process: face blend + text overlay
        output_path = str(BLENDED_DIR / f"{session_id}_page_01.png")
        _process_page(
            template_path=template_path,
            user_face_path=session["face_image_path"],
            face_bbox=meta["face_bbox"],
            text_area=meta["text_area"],
            story_lines=page["story_lines"],
            child_name=session["child_name"],
            output_path=output_path,
        )

        await self._update_session(session_id, {
            "status": "preview_ready",
            "preview_path": output_path,
            "progress": 1,
        })

        logger.info(f"Preview ready for session {session_id}")
        return output_path

    async def generate_all_pages(self, session_id: str):
        """Generate all pages, blend faces, overlay text, create PDF."""
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        story = _load_story(session["story_id"])
        child_name = session["child_name"]
        face_path = session["face_image_path"]
        total = story["total_pages"]

        await self._update_session(session_id, {"status": "generating"})

        blended_pages = []

        # Page 1 is already done (preview)
        preview = session.get("preview_path")
        if preview and Path(preview).exists():
            blended_pages.append({"page_number": 1, "image_path": preview})

        for page in story["pages"]:
            pn = page["page_number"]

            if pn == 1 and blended_pages:
                await self._update_session(session_id, {"progress": 1})
                continue

            prompt = _build_prompt(story, page)

            try:
                # Generate (or get cached) DALL-E image + coordinates
                template_path, meta = await dalle_service.generate_image(
                    prompt=prompt,
                    story_id=session["story_id"],
                    page_number=pn,
                    size=story.get("image_size", "1024x1024"),
                )

                # Process page
                output_path = str(BLENDED_DIR / f"{session_id}_page_{pn:02d}.png")
                _process_page(
                    template_path=template_path,
                    user_face_path=face_path,
                    face_bbox=meta["face_bbox"],
                    text_area=meta["text_area"],
                    story_lines=page["story_lines"],
                    child_name=child_name,
                    output_path=output_path,
                )

                blended_pages.append({"page_number": pn, "image_path": output_path})

                await self._update_session(session_id, {
                    "progress": pn,
                    "blended_pages": blended_pages,
                })

                logger.info(f"Page {pn}/{total} done for session {session_id}")

            except Exception as e:
                logger.error(f"Failed page {pn}: {e}")
                await self._update_session(session_id, {
                    "status": "failed",
                    "error": str(e),
                })
                raise

        blended_pages.sort(key=lambda p: p["page_number"])

        # Generate PDF — images already have text overlaid
        story_title = story["title"].replace("{name}", child_name)
        pages_data = []
        for bp in blended_pages:
            pages_data.append({
                "text": "",  # text is already on the image
                "image_path": bp["image_path"],
            })

        pdf_filename = f"{child_name.replace(' ', '_')}_{session_id}.pdf"
        pdf_path = self._pdf_service.create_storybook_pdf(
            child_name=child_name,
            story_title=story_title,
            pages_data=pages_data,
            output_filename=pdf_filename,
        )

        await self._update_session(session_id, {
            "status": "complete",
            "progress": total,
            "blended_pages": blended_pages,
            "pdf_path": pdf_path,
        })

        logger.info(f"Generation complete for session {session_id}: {pdf_path}")
        return pdf_path

    async def find_existing_pdf(self, child_name: str, story_id: str) -> Optional[dict]:
        doc = await self._sessions.find_one(
            {
                "child_name": child_name,
                "story_id": story_id,
                "status": "complete",
                "pdf_path": {"$ne": None},
            },
            {"_id": 0},
            sort=[("created_at", -1)],
        )
        if doc and doc.get("pdf_path") and Path(doc["pdf_path"]).exists():
            return doc
        return None


generation_service = GenerationService()

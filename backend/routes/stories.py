"""Stories API Routes
=====================

Endpoints for listing and accessing story metadata.

  GET /api/stories           — list all stories (legacy path, kept for compat)
  GET /api/stories/{index}   — get story by index
  GET /api/stories/verify/{story_id} — verify story templates exist
  GET /api/v2/stories        — list all stories (canonical v2 path, used by frontend)

WHY /api/v2/stories LIVES HERE AND NOT IN generate_v2.py
---------------------------------------------------------
generate_v2.py imports generation_service which imports image_service which
imports cv2 (OpenCV). cv2 requires native shared libraries (libxcb.so.1,
libGL.so.1) installed by apt-get in startup.sh.

If those libraries are missing, the entire generate_v2_router fails to load
and server.py sets generate_v2_router = None — silently killing every
/api/v2/* endpoint including the story list, causing an empty dropdown.

This file (stories.py) only imports from story_service and models, which
have NO native library dependencies. The /api/v2/stories endpoint therefore
works unconditionally, even when OpenCV is not installed.
"""

from fastapi import APIRouter, HTTPException
from typing import List
import logging

from models.story import StoryMetadata
from services.story_service import story_registry

logger = logging.getLogger(__name__)

# ── v1 router: /api/stories ───────────────────────────────────────────────────
router = APIRouter(prefix="/api/stories", tags=["stories"])

# ── v2 router: /api/v2/stories ───────────────────────────────────────────────
# Registered separately in server.py as a second include_router call.
# Must NOT have prefix=/api/v2 here because server.py passes it with no prefix
# and the route definition includes the full path. We use a separate router
# object to avoid prefix conflicts with generate_v2_router.
v2_router = APIRouter(prefix="/api/v2", tags=["stories_v2"])


# =============================================================================
# /api/v2/stories  ← used by the frontend (HomePage.jsx: axios.get `${API}/stories`)
# =============================================================================

@v2_router.get("/stories")
async def list_stories_v2():
    """
    List all available stories — canonical endpoint used by the frontend.

    Called by HomePage.jsx:
      axios.get(`${BACKEND_URL}/api/v2/stories`)
      → setStories(res.data.stories || [])

    Returns:
      { "stories": [ { story_id, title, description, age_group, total_pages }, ... ] }

    This endpoint has NO dependency on cv2/OpenCV/mediapipe/libxcb.
    It always returns story metadata regardless of whether native image
    libraries are installed. The frontend dropdown is always populated.
    """
    try:
        stories = [
            {
                "story_id": s.story_id,
                "title": s.title,
                "description": s.description,
                "age_group": s.age_group,
                "total_pages": s.page_count,
            }
            for s in story_registry.list_stories()
        ]
        logger.info(f"v2/stories: returning {len(stories)} stories")
        return {"stories": stories}
    except Exception as e:
        logger.error(f"v2/stories: failed to list stories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error retrieving stories")


# =============================================================================
# /api/stories  ← legacy path, kept for backward compatibility
# =============================================================================

@router.get("", response_model=List[StoryMetadata])
async def list_stories():
    """
    List all available stories (legacy path).

    Returns story metadata without page details.
    Frontend uses /api/v2/stories — this is kept for backward compatibility.
    Has no dependency on native image libraries.
    """
    try:
        stories = story_registry.list_stories()
        logger.info(f"Listed {len(stories)} stories")
        return stories
    except Exception as e:
        logger.error(f"Error listing stories: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving stories")


@router.get("/{index}", response_model=StoryMetadata)
async def get_story_by_index(index: int):
    """Get story metadata by index (0-based)."""
    story = story_registry.get_story_by_index(index)
    if not story:
        raise HTTPException(status_code=404, detail=f"Story not found at index {index}")
    logger.info(f"Retrieved story by index {index}: {story.story_id}")
    return StoryMetadata.from_story(story)


@router.get("/verify/{story_id}")
async def verify_story_templates(story_id: str):
    """
    Verify all template files exist for a story.

    NOTE: This makes network requests to Azure Blob Storage (or local FS)
    to HEAD-check each template. It is informational only — a template
    missing from blob storage does NOT prevent generation because
    image_service.compose_page() reads templates from local FS directly.
    """
    results = story_registry.verify_story_templates(story_id)
    if "error" in results:
        raise HTTPException(status_code=404, detail=results["error"])
    logger.info(
        f"Template verification for {story_id}: "
        f"{results['verified']}/{results['total_pages']}"
    )
    return results

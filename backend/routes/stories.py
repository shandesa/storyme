"""Stories API Routes

Provides endpoints for listing and accessing story metadata.

Endpoints:
- GET /api/stories - List all available stories
- GET /api/stories/{index} - Get story by index
- GET /api/stories/verify/{story_id} - Verify story templates
"""

from fastapi import APIRouter, HTTPException
from typing import List
import logging

from models.story import StoryMetadata
from services.story_service import story_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stories", tags=["stories"])


@router.get("", response_model=List[StoryMetadata])
async def list_stories():
    """Get list of all available stories.
    
    Returns:
        List of story metadata (without full page details)
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
    """Get story metadata by index.
    
    Args:
        index: Story index (0-based)
    
    Returns:
        Story metadata
    """
    story = story_registry.get_story_by_index(index)
    
    if not story:
        raise HTTPException(
            status_code=404,
            detail=f"Story not found at index {index}"
        )
    
    logger.info(f"Retrieved story by index {index}: {story.story_id}")
    return StoryMetadata.from_story(story)


@router.get("/verify/{story_id}")
async def verify_story_templates(story_id: str):
    """Verify all template files exist for a story.
    
    Args:
        story_id: Story identifier
    
    Returns:
        Verification results with missing files if any
    """
    results = story_registry.verify_story_templates(story_id)
    
    if 'error' in results:
        raise HTTPException(status_code=404, detail=results['error'])
    
    logger.info(f"Template verification for {story_id}: "
               f"{results['verified']}/{results['total_pages']}")
    
    return results

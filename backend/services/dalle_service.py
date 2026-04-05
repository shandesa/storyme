"""DALL-E Image Generation Service with coordinate extraction and caching.

For each generated image:
1. Generates the illustration via DALL-E
2. Uses GPT-4o vision to extract face_bbox and text_area coordinates
3. Caches both the image and metadata for reuse
"""

import os
import json
import base64
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "cache" / "dalle"

COORD_EXTRACTION_PROMPT = """You are analyzing a 1024x1024 pixel children's storybook illustration.

The image contains a cartoon child character who has a LARGE, BLANK face — a smooth, uniform skin-colored oval with absolutely NO eyes, nose, or mouth. The oval is the entire face from forehead to chin.

Your task: find the EXACT pixel coordinates of this blank face oval and the best text overlay area.

IMPORTANT for the face oval:
- It is the LARGE smooth skin-colored area on the character's HEAD
- It spans from the character's hairline (top) to their chin (bottom)
- It is NOT a small circle — it is a large oval covering the ENTIRE face
- The width is typically 150-200 pixels and height 170-220 pixels in a 1024x1024 image
- Look for the uniform warm skin tone with NO features inside

IMPORTANT for the text area:
- Find the largest clear area AWAY from the character
- Prefer bottom-right or right side of the image
- The area should have a soft/blurred background suitable for white text
- Must NOT overlap with the character

Return ONLY this JSON (all values are pixel integers):
{
  "face_x": <left edge of the blank face oval>,
  "face_y": <top edge of the blank face oval - at the hairline, NOT above>,
  "face_w": <full width of the blank oval>,
  "face_h": <full height from hairline to chin>,
  "text_x": <left edge of text area>,
  "text_y": <top edge of text area>,
  "text_w": <width of text area>,
  "text_h": <height of text area>
}"""


class DalleService:
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in environment")
        self._client = OpenAI(api_key=api_key)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, story_id: str, page_number: int) -> Path:
        d = CACHE_DIR / story_id
        d.mkdir(parents=True, exist_ok=True)
        return d / f"page_{page_number:02d}.png"

    def _meta_path(self, story_id: str, page_number: int) -> Path:
        d = CACHE_DIR / story_id
        d.mkdir(parents=True, exist_ok=True)
        return d / f"page_{page_number:02d}_meta.json"

    def get_cached(self, story_id: str, page_number: int) -> Optional[Tuple[str, dict]]:
        """Return cached (image_path, metadata) or None."""
        img_path = self._cache_path(story_id, page_number)
        meta_path = self._meta_path(story_id, page_number)
        if img_path.exists() and img_path.stat().st_size > 0 and meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            logger.info(f"Cache HIT: {story_id}/page_{page_number}")
            return str(img_path), meta
        return None

    def _extract_coordinates(self, image_bytes: bytes) -> dict:
        """Use GPT-4o vision to extract face and text coordinates."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        try:
            response = self._client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": COORD_EXTRACTION_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]
                }],
                response_format={"type": "json_object"},
                max_tokens=300,
            )

            raw = response.choices[0].message.content
            coords = json.loads(raw)
            logger.info(f"GPT-4o raw coordinates: {coords}")

            required = ["face_x", "face_y", "face_w", "face_h",
                         "text_x", "text_y", "text_w", "text_h"]
            for k in required:
                if k not in coords or not isinstance(coords[k], (int, float)):
                    raise ValueError(f"Missing or invalid key: {k}")
                coords[k] = int(coords[k])

            face_bbox = {
                "x": coords["face_x"],
                "y": coords["face_y"],
                "w": coords["face_w"],
                "h": coords["face_h"],
            }
            text_area = {
                "x": coords["text_x"],
                "y": coords["text_y"],
                "w": coords["text_w"],
                "h": coords["text_h"],
            }

            # Enforce reasonable face size (15-25% of image)
            # GPT-4o is good at position but can undersize the face
            min_w, min_h = 150, 170
            max_w, max_h = 260, 280
            face_bbox["w"] = max(min_w, min(face_bbox["w"], max_w))
            face_bbox["h"] = max(min_h, min(face_bbox["h"], max_h))

            # Clamp to image bounds (assume 1024x1024)
            face_bbox["x"] = max(0, min(face_bbox["x"], 1024 - face_bbox["w"]))
            face_bbox["y"] = max(0, min(face_bbox["y"], 1024 - face_bbox["h"]))

            logger.info(f"Final face_bbox: {face_bbox}, text_area: {text_area}")
            return {"face_bbox": face_bbox, "text_area": text_area}

        except Exception as e:
            logger.error(f"Coordinate extraction failed: {e}")
            return {
                "face_bbox": {"x": 380, "y": 250, "w": 190, "h": 210},
                "text_area": {"x": 620, "y": 700, "w": 360, "h": 260},
            }

    async def generate_image(
        self,
        prompt: str,
        story_id: str,
        page_number: int,
        size: str = "1024x1024",
        model: str = "gpt-image-1",
        quality: str = "medium",
    ) -> Tuple[str, dict]:
        """Generate image and extract coordinates, or return cached.

        Returns (image_path, metadata_dict) where metadata has face_bbox and text_area.
        """
        cached = self.get_cached(story_id, page_number)
        if cached:
            return cached

        logger.info(f"Generating DALL-E image: {story_id}/page_{page_number} ...")

        try:
            response = self._client.images.generate(
                model=model,
                prompt=prompt,
                size=size,
                n=1,
                quality=quality,
            )

            image_data = response.data[0]
            img_bytes = None

            if hasattr(image_data, "b64_json") and image_data.b64_json:
                img_bytes = base64.b64decode(image_data.b64_json)
            elif hasattr(image_data, "url") and image_data.url:
                import httpx
                resp = httpx.get(image_data.url, timeout=60)
                resp.raise_for_status()
                img_bytes = resp.content
            else:
                raise RuntimeError("No image data in response")

            # Save image
            out_path = self._cache_path(story_id, page_number)
            out_path.write_bytes(img_bytes)
            logger.info(f"Image saved: {out_path} ({len(img_bytes) / 1024:.0f} KB)")

            # Extract coordinates using GPT-4o vision
            meta = self._extract_coordinates(img_bytes)

            # Save metadata
            meta_path = self._meta_path(story_id, page_number)
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
            logger.info(f"Metadata saved: {meta_path}")

            return str(out_path), meta

        except Exception as e:
            logger.error(f"DALL-E generation failed for page {page_number}: {e}")
            raise

    def clear_cache(self, story_id: str):
        d = CACHE_DIR / story_id
        if d.exists():
            for f in d.glob("*"):
                f.unlink()
            logger.info(f"Cache cleared for {story_id}")


dalle_service = DalleService()

"""
Story JSON Config Service

Loads story metadata from  backend/data/stories/*.json.
Resolves template paths (DALL-E cache first, static fallback).
Provides typed PageConfig objects consumed by FacePipelineService.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_BACKEND_DIR   = Path(__file__).parent.parent
_STORIES_DIR   = _BACKEND_DIR / "data" / "stories"
_DALLE_DIR     = _BACKEND_DIR / "cache" / "dalle"
_TEMPLATE_DIR  = _BACKEND_DIR / "templates" / "stories"


# ─── Typed data classes ───────────────────────────────────────────────────────

@dataclass
class HeadPose:
    yaw:   float = 0.0
    pitch: float = 0.0
    roll:  float = 0.0


@dataclass
class TextArea:
    x: int = 550
    y: int = 120
    w: int = 450
    h: int = 780


@dataclass
class FaceConfig:
    x: int = 430
    y: int = 220
    w: int = 170
    h: int = 190


@dataclass
class PageConfig:
    page_number:       int
    character_present: bool
    story_lines:       List[str]
    text_area:         TextArea
    face_config:       Optional[FaceConfig]  = None
    head_pose:         Optional[HeadPose]    = None
    expression:        str                   = "neutral"
    template_path:     Optional[str]         = None


@dataclass
class StoryConfig:
    story_id:    str
    title:       str
    total_pages: int
    pages:       List[PageConfig]

    def character_pages(self) -> List[PageConfig]:
        return [p for p in self.pages if p.character_present]

    def text_only_pages(self) -> List[PageConfig]:
        return [p for p in self.pages if not p.character_present]


# ─── Service ──────────────────────────────────────────────────────────────────

class StoryJsonService:
    """Loads and caches story configs from JSON files."""

    def __init__(self) -> None:
        self._cache: Dict[str, StoryConfig] = {}

    # ── Public ────────────────────────────────────────────────────────────────

    def get_story(self, story_id: str) -> Optional[StoryConfig]:
        if story_id in self._cache:
            return self._cache[story_id]

        path = _STORIES_DIR / f"{story_id}.json"
        if not path.exists():
            logger.warning("Story JSON not found: %s", path)
            return None

        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        config = self._parse(data)
        self._cache[story_id] = config
        logger.info("Loaded story config: %s  (%d pages)", story_id, len(config.pages))
        return config

    def list_stories(self) -> List[str]:
        return sorted(p.stem for p in _STORIES_DIR.glob("*.json"))

    def invalidate(self, story_id: str) -> None:
        """Force re-load on next get_story() call."""
        self._cache.pop(story_id, None)

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse(self, data: dict) -> StoryConfig:
        story_id = data["story_id"]
        pages    = []

        for p in data["pages"]:
            pn    = int(p["page_number"])
            char  = bool(p.get("character_present", False))

            # text_area
            ta_raw = p.get("text_area", {})
            ta     = TextArea(
                x=int(ta_raw.get("x", 550)),
                y=int(ta_raw.get("y", 120)),
                w=int(ta_raw.get("w", 450)),
                h=int(ta_raw.get("h", 780)),
            )

            # face_config
            fc = None
            if char and "face_config" in p:
                fc_r = p["face_config"]
                fc   = FaceConfig(
                    x=int(fc_r["x"]), y=int(fc_r["y"]),
                    w=int(fc_r["w"]), h=int(fc_r["h"]),
                )

            # head_pose
            hp = None
            if char and "head_pose" in p:
                hp_r = p["head_pose"]
                hp   = HeadPose(
                    yaw=float(hp_r.get("yaw",   0.0)),
                    pitch=float(hp_r.get("pitch", 0.0)),
                    roll=float(hp_r.get("roll",   0.0)),
                )

            tpl_path = self._resolve_template(story_id, pn)

            pages.append(PageConfig(
                page_number       = pn,
                character_present = char,
                story_lines       = [str(l) for l in p.get("story_lines", [])],
                text_area         = ta,
                face_config       = fc,
                head_pose         = hp,
                expression        = str(p.get("expression", "neutral")),
                template_path     = tpl_path,
            ))

        return StoryConfig(
            story_id    = story_id,
            title       = data.get("title", story_id),
            total_pages = int(data.get("total_pages", len(pages))),
            pages       = pages,
        )

    @staticmethod
    def _resolve_template(story_id: str, page_number: int) -> Optional[str]:
        """
        Priority 1: cache/dalle/{story_id}/page_{NN:02d}.png
        Priority 2: templates/stories/{story_id}/page{N}.png

        To swap a template image, replace the file at priority-1 path.
        See docs/FACE_PIPELINE_DESIGN.md §3 for full instructions.
        """
        dalle = _DALLE_DIR / story_id / f"page_{page_number:02d}.png"
        if dalle.exists():
            return str(dalle)

        static = _TEMPLATE_DIR / story_id / f"page{page_number}.png"
        if static.exists():
            return str(static)

        logger.warning("No template found: %s page %d", story_id, page_number)
        return None


# Singleton
story_json_service = StoryJsonService()

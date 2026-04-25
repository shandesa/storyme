"""
Generate Storybook API — v3  (face pipeline)
────────────────────────────────────────────
POST /api/v3/generate

Uses FacePipelineService + StoryJsonService instead of the legacy
image_service + story_service approach.

Differences from v1/v2
──────────────────────
• Reads 16-page config from data/stories/*.json (pose, expression, text_area)
• Character pages (odd + page 16): full face extraction → pose warp →
  expression morph → colour match → seamlessClone
• Non-character pages (even 2–14): template copy + text overlay only
• Text rendered by PIL with auto-sizing and word wrap
• No dependency on story_service, image_service, or generation_mode

Template resolution (see docs/FACE_PIPELINE_DESIGN.md §3)
  Priority 1: cache/dalle/{story_id}/page_{NN:02d}.png
  Priority 2: templates/stories/{story_id}/page{N}.png
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.config import config
from core.storage import storage
from core.storage_paths import upload_path as make_upload_path
from services.story_json_service import story_json_service
from services.face_pipeline_service import face_pipeline_service
from services.pdf_service import PDFService

logger     = logging.getLogger(__name__)
router     = APIRouter(prefix="/api/v3", tags=["generate-v3"])
pdf_service = PDFService(str(config.OUTPUT_DIR))


def _safe_name(name: str) -> str:
    s = re.sub(r"[^\w\-]", "_", name.strip().lower())
    return (re.sub(r"_+", "_", s).strip("_") or "child")[:64]


def _resolve_local(blob_path: str) -> tuple[str, bool]:
    """Return (local_path, is_temp). Caller must delete if is_temp."""
    if config.STORAGE_TYPE == "local":
        return storage.get_file_path(blob_path), False
    data   = storage.read_file(blob_path)
    suffix = Path(blob_path).suffix or ".jpg"
    tmp    = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name, True


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_storybook_v3(
    name:     str        = Form(...),
    image:    UploadFile = File(...),
    story_id: Optional[str] = Form("forest_of_smiles"),
):
    """
    Generate a personalised 16-page storybook PDF.

    Form fields
    ───────────
    name      Child's first name  (replaces {name} in story text)
    image     Child's photo       (JPEG / PNG / WEBP, ≤ 5 MB)
    story_id  Story identifier    (default: forest_of_smiles)

    Returns
    ───────
    PDF file  (Content-Disposition: attachment)
    """
    # ── Validation ────────────────────────────────────────────────────────────
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Child's name is required")

    if image.content_type not in config.ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(config.ALLOWED_IMAGE_TYPES)}",
        )

    child_name = name.strip()
    sid        = (story_id or "forest_of_smiles").strip()
    gen_id     = uuid.uuid4().hex

    # ── Load story config ─────────────────────────────────────────────────────
    story = story_json_service.get_story(sid)
    if not story:
        raise HTTPException(status_code=404, detail=f"Story not found: {sid}")

    logger.info(
        "v3 generation start — child=%r story=%s pages=%d id=%s",
        child_name, sid, story.total_pages, gen_id[:8],
    )

    # ── Persist uploaded photo ────────────────────────────────────────────────
    ext                = Path(image.filename or "upload.jpg").suffix or ".jpg"
    blob_path          = make_upload_path(ext, gen_id)
    storage.save_file(image.file, blob_path)

    local_face, is_temp = _resolve_local(blob_path)

    pages_data:   list[dict] = []
    failed_pages: list[int]  = []

    try:
        # ── Process each page ─────────────────────────────────────────────────
        for page in story.pages:
            if not page.template_path:
                logger.warning("Page %d: no template — skipped", page.page_number)
                failed_pages.append(page.page_number)
                continue

            out = str(
                config.OUTPUT_DIR / f"{gen_id}_p{page.page_number:02d}.png"
            )

            ta = {"x": page.text_area.x, "y": page.text_area.y,
                  "w": page.text_area.w, "h": page.text_area.h}

            try:
                if page.character_present:
                    fc = ({"x": page.face_config.x, "y": page.face_config.y,
                           "w": page.face_config.w, "h": page.face_config.h}
                          if page.face_config
                          else {"x": 430, "y": 220, "w": 170, "h": 190})
                    hp = ({"yaw":   page.head_pose.yaw,
                           "pitch": page.head_pose.pitch,
                           "roll":  page.head_pose.roll}
                          if page.head_pose else {"yaw": 0.0, "pitch": 0.0, "roll": 0.0})

                    face_pipeline_service.process_character_page(
                        template_path  = page.template_path,
                        user_face_path = local_face,
                        face_config    = fc,
                        pose           = hp,
                        expression     = page.expression or "neutral",
                        story_lines    = page.story_lines,
                        text_area      = ta,
                        child_name     = child_name,
                        output_path    = out,
                    )
                else:
                    face_pipeline_service.process_text_only_page(
                        template_path = page.template_path,
                        story_lines   = page.story_lines,
                        text_area     = ta,
                        child_name    = child_name,
                        output_path   = out,
                    )

                pages_data.append({
                    "text":       "\n".join(page.story_lines),
                    "image_path": out,
                    "page_number": page.page_number,
                })
                logger.info("Page %d ✓", page.page_number)

            except Exception as exc:
                logger.error("Page %d failed: %s", page.page_number, exc, exc_info=True)
                failed_pages.append(page.page_number)

        if not pages_data:
            raise HTTPException(
                status_code=500,
                detail="All pages failed to generate. Check server logs.",
            )

        if failed_pages:
            logger.warning("Failed pages: %s", failed_pages)

        # ── Build PDF ─────────────────────────────────────────────────────────
        safe    = _safe_name(child_name)
        pdf_out = str(config.OUTPUT_DIR / f"{safe}_{gen_id[:8]}.pdf")
        pdf_service.create_storybook_pdf(pages_data, pdf_out, child_name)

        logger.info("v3 PDF ready — %d pages, %s", len(pages_data), pdf_out)

        return FileResponse(
            pdf_out,
            media_type="application/pdf",
            filename=f"{safe}_storybook.pdf",
            headers={"Content-Disposition":
                     f'attachment; filename="{safe}_storybook.pdf"'},
        )

    finally:
        if is_temp:
            try:
                os.unlink(local_face)
            except Exception:
                pass

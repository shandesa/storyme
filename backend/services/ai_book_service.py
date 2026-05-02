"""
services/ai_book_service.py
============================
AI-based full storybook generation pipeline (SPEC-004).

Generates an 18-page storybook:
  Page 0   — front cover (cover_image_gen.py)
  Pages 1–16 — AI-generated via DALL-E gpt-image-1
  Page 17  — back cover (cover_image_gen.py)

Four phases (run as background asyncio task):
  Phase 0: Cover pages
  Phase 1: Background pages 2,4,6,8,10,12,14 (global cache, generated once)
  Phase 2: Character page 1 (style anchor — user photo as reference)
  Phase 3: Character pages 3,5,7,9,11,13,15,16 (page-1 raw as style anchor)
  Phase 4: PDF assembly (18 pages)

Key decisions from SPEC-004 v2:
  - DALL-E seed per generation_id → character consistency across all 9 char pages
  - STORY_BACKGROUND_SEED = 42_000_000 → consistent background pages globally
  - Story text burned into every image via PIL (ai_text_renderer)
  - Background pages: text+name substitution via PIL, global cache never modified
  - Pages 1 and 16 flagged is_placeholder=True (reserved for final artwork)
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import random
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Fixed seed for globally-cached background pages
STORY_BACKGROUND_SEED = 42_000_000

# Placeholder pages (reserved for final artwork)
PLACEHOLDER_PAGES = {1, 16}

# Consistency prompt suffix appended to pages 3–16
_CONSISTENCY_SUFFIX = """

CONSISTENCY REQUIREMENTS (MANDATORY):
- Maintain EXACT same character as the reference image provided
- Same child: same hair colour, same hair length, same face oval placeholder
- Same clothing: light yellow t-shirt, beige shorts, brown hat with black lace
- Same art style: identical colour palette, lighting temperature, rendering quality
- Same background atmosphere and depth layering as the reference
- Face oval MUST remain featureless: skin tone #E8C4A0, no eyes/nose/mouth
"""

# Story config path
_STORY_JSON = (
    Path(__file__).parent.parent / "data" / "stories" / "forest_of_smiles_v8_final.json"
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _anchor_to_face_config(face_anchor: dict, img_w: int = 1024, img_h: int = 1024) -> dict:
    """Convert normalised face_anchor to pixel face_config for face_pipeline_service."""
    cx, cy = face_anchor.get("center", [0.4, 0.3])
    sw, sh = face_anchor.get("size_ratio", [0.17, 0.2])
    w = int(sw * img_w)
    h = int(sh * img_h)
    x = int(cx * img_w) - w // 2
    y = int(cy * img_h) - h // 2
    return {"x": max(0, x), "y": max(0, y), "w": w, "h": h}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name.strip().lower())[:40] or "child"


# ─── Main service ─────────────────────────────────────────────────────────────

class AIBookService:
    """
    Orchestrates AI-based storybook generation.
    One singleton instance used for all generations.
    """

    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Set it in your environment or .env file."
            )
        from openai import OpenAI
        self._openai = OpenAI(api_key=api_key)
        self._story_config: Optional[dict] = None
        # In-memory hot cache for background page bytes
        # key: "story_id:page_number:prompt_hash"  value: (bytes, text_area_dict)
        self._bg_cache: dict[str, tuple[bytes, dict]] = {}

    def _load_story(self) -> dict:
        if self._story_config is None:
            self._story_config = json.loads(_STORY_JSON.read_text("utf-8"))
        return self._story_config

    # ── Public: start generation (non-blocking) ───────────────────────────────

    async def start_generation(
        self,
        user_mobile: str,
        child_name: str,
        story_id: str,
        user_photo_bytes: bytes,
        quality: str = "medium",
    ) -> dict:
        """
        Begin background AI generation. Returns immediately with generation_id.

        Args:
            user_mobile:      Authenticated user's mobile
            child_name:       Child's name (replaces {name} in story text)
            story_id:         Must be "forest_of_smiles" for now
            user_photo_bytes: Raw bytes of the user's uploaded photo
            quality:          "medium" or "high"

        Returns dict with generation_id, status, estimated_seconds, etc.
        """
        from core.session_store import session_store

        gen_id = uuid.uuid4().hex
        seed   = random.randint(0, 2**32 - 1)
        now    = _now_iso()

        story  = self._load_story()
        pages  = story["pages"]
        bg_pgs = [p["page_number"] for p in pages if not p["character_present"]]
        ch_pgs = [p["page_number"] for p in pages if p["character_present"]]

        # Count already-cached background pages
        from core.ai_page_store import get_background_page
        bg_cached = sum(
            1 for pn in bg_pgs
            if get_background_page(story_id, pn) is not None
        )

        # Write initial session
        session_dict = {
            "generation_id":   gen_id,
            "child_name":      child_name,
            "story_id":        story_id,
            "generation_mode": "ai_book",
            "status":          "generating",
            "pdf_blob_path":   "",
            "pdf_filename":    "",
            "pages_succeeded": 0,
            "pages_failed":    0,
            "total_pages":     18,
            "completed_at":    "",
            "created_at":      now,
        }
        try:
            await session_store.write_session(session_dict)
        except Exception as exc:
            logger.warning("Failed to write initial session %s: %s", gen_id[:8], exc)

        # Fire background task
        asyncio.create_task(
            self._run_ai_book_async(
                gen_id=gen_id,
                user_mobile=user_mobile,
                child_name=child_name,
                story_id=story_id,
                user_photo_bytes=user_photo_bytes,
                quality=quality,
                generation_seed=seed,
            )
        )

        logger.info(
            "AI book generation started: gen_id=%s child=%r seed=%d bg_cached=%d/%d",
            gen_id[:8], child_name, seed, bg_cached, len(bg_pgs),
        )

        return {
            "generation_id":                gen_id,
            "status":                       "generating",
            "story_id":                     story_id,
            "total_pages":                  18,
            "story_pages":                  16,
            "cover_pages":                  2,
            "character_pages":              len(ch_pgs),
            "background_pages":             len(bg_pgs),
            "background_pages_cached":      bg_cached,
            "background_pages_to_generate": len(bg_pgs) - bg_cached,
            "generation_seed":              seed,
            "estimated_seconds":            180,
            "placeholder_pages":            sorted(PLACEHOLDER_PAGES),
        }

    # ── Background async task ─────────────────────────────────────────────────

    async def _run_ai_book_async(
        self,
        gen_id: str,
        user_mobile: str,
        child_name: str,
        story_id: str,
        user_photo_bytes: bytes,
        quality: str,
        generation_seed: int,
    ) -> None:
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                self._run_sync,
                gen_id, user_mobile, child_name, story_id,
                user_photo_bytes, quality, generation_seed,
            )
            updates = result.get("updates", {})
            if updates:
                from core.session_store import session_store
                try:
                    await session_store.update_session(gen_id, updates)
                except Exception as exc:
                    logger.warning("Session update failed %s: %s", gen_id[:8], exc)
        except Exception as exc:
            logger.error("AI book generation CRASHED %s: %s", gen_id[:8], exc, exc_info=True)
            from core.session_store import session_store
            try:
                await session_store.update_session(gen_id, {
                    "status": "failed", "completed_at": _now_iso(),
                })
            except Exception:
                pass

    # ── Synchronous pipeline (runs in thread executor) ────────────────────────

    def _run_sync(
        self,
        gen_id: str,
        user_mobile: str,
        child_name: str,
        story_id: str,
        user_photo_bytes: bytes,
        quality: str,
        generation_seed: int,
    ) -> dict:
        from core.config import config
        from core.storage import storage
        from core.storage_paths import (
            ai_background_page_path, ai_character_raw_path,
            ai_character_final_path, ai_background_final_path, pdf_path,
        )
        from core.ai_page_store import (
            get_background_page, save_background_page,
            save_character_page,
        )
        from services.ai_text_renderer import render_text_on_image, DEFAULT_TEXT_ZONE
        from services.face_pipeline_service import face_pipeline_service
        from services.pdf_service import PDFService
        from services.cover_image_gen import generate_front_cover, generate_back_cover

        story   = self._load_story()
        version = story.get("version", "v8")
        pages   = story["pages"]
        out_dir = config.OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        pages_for_pdf:  list[dict] = []
        pages_succeeded = 0
        pages_failed:   list[int] = []

        # ── Phase 0: Covers ───────────────────────────────────────────────────
        logger.info("━ AI Book Phase 0: covers [gen=%s]", gen_id[:8])
        try:
            front_bytes  = generate_front_cover("paperback", "storyme_default")
            front_local  = str(out_dir / f"{gen_id}_p00.png")
            Path(front_local).write_bytes(front_bytes)
            pages_for_pdf.append({"image_path": front_local, "text": "", "page_number": 0})
            pages_succeeded += 1
        except Exception as exc:
            logger.error("Cover Phase 0 front failed: %s", exc)
            pages_failed.append(0)

        # ── Phase 1: Background pages ─────────────────────────────────────────
        logger.info("━ AI Book Phase 1: background pages [gen=%s]", gen_id[:8])
        bg_page_configs = {p["page_number"]: p for p in pages if not p["character_present"]}

        for pn, page_cfg in sorted(bg_page_configs.items()):
            try:
                prompt_text = page_cfg["prompt"]["final_text"]
                p_hash      = _prompt_hash(prompt_text)
                story_text  = page_cfg.get("story", "")

                # Check 3-tier cache
                img_bytes, text_area = self._get_or_generate_background(
                    story_id, version, pn, prompt_text, p_hash, quality, page_cfg
                )

                # PIL: burn text + substitute child name
                final_bytes = render_text_on_image(img_bytes, story_text, child_name, text_area)

                # Save per-generation final (does NOT overwrite global cache)
                final_local = str(out_dir / f"{gen_id}_p{pn:02d}.png")
                Path(final_local).write_bytes(final_bytes)

                # Upload per-generation copy to blob
                blob_path = ai_background_final_path(gen_id, pn)
                _upload_bytes(storage, final_bytes, blob_path)

                pages_for_pdf.append({
                    "image_path": final_local, "text": "", "page_number": pn,
                })
                pages_succeeded += 1
                logger.info("✅ Phase 1 p%02d complete [gen=%s]", pn, gen_id[:8])

            except Exception as exc:
                logger.error("✗ Phase 1 p%02d failed: %s", pn, exc, exc_info=True)
                pages_failed.append(pn)

        # ── Phase 2: Character page 1 (style anchor) ─────────────────────────
        logger.info("━ AI Book Phase 2: character page 1 anchor [gen=%s]", gen_id[:8])
        page1_raw_bytes: Optional[bytes] = None

        p1_cfg = next(p for p in pages if p["page_number"] == 1)
        try:
            t0      = time.time()
            prompt  = p1_cfg["prompt"]["final_text"]
            raw_bytes = self._dalle_edit(
                image_bytes=user_photo_bytes,
                prompt=prompt,
                quality=quality,
                seed=generation_seed,
            )
            gen_ms = int((time.time() - t0) * 1000)

            # Save raw
            raw_local = str(out_dir / f"{gen_id}_p01_raw.png")
            Path(raw_local).write_bytes(raw_bytes)
            page1_raw_bytes = raw_bytes  # keep in memory as anchor

            # Upload raw
            raw_blob = ai_character_raw_path(gen_id, 1)
            _upload_bytes(storage, raw_bytes, raw_blob)

            # Extract face coords
            face_bbox, text_area = self._extract_coords(raw_bytes)

            # Burn story text onto raw
            story_text    = p1_cfg.get("story", "")
            textd_bytes   = render_text_on_image(raw_bytes, story_text, child_name, text_area)
            textd_local   = str(out_dir / f"{gen_id}_p01_textd.png")
            Path(textd_local).write_bytes(textd_bytes)

            # Face blend
            final_local = str(out_dir / f"{gen_id}_p01_final.png")
            fa          = p1_cfg.get("face_anchor", {})
            pose        = fa.get("rotation", {"yaw": 0, "pitch": 0, "roll": 0})
            fc          = _anchor_to_face_config(fa) if fa else face_bbox

            face_pipeline_service.process_character_page(
                template_path  = textd_local,
                user_face_path = _bytes_to_temp(user_photo_bytes, ".jpg"),
                face_config    = fc,
                pose           = pose,
                expression     = "curious",
                story_lines    = [],      # text already burned in
                text_area      = {"x": 0, "y": 0, "w": 0, "h": 0},
                child_name     = child_name,
                output_path    = final_local,
            )

            # Upload final
            final_blob = ai_character_final_path(gen_id, 1)
            final_bytes = Path(final_local).read_bytes()
            _upload_bytes(storage, final_bytes, final_blob)

            # Save to AICharacterPages
            save_character_page(gen_id, 1, {
                "story_id":       story_id,
                "user_mobile":    user_mobile,
                "blob_path_raw":  raw_blob,
                "blob_path_final": final_blob,
                "face_bbox":      face_bbox,
                "text_area":      text_area,
                "is_anchor":      True,
                "is_placeholder": True,   # page 1 = front story placeholder
                "seed":           generation_seed,
                "model":          "gpt-image-1",
                "quality":        quality,
                "generation_ms":  gen_ms,
            })

            pages_for_pdf.append({
                "image_path": final_local, "text": "", "page_number": 1,
            })
            pages_succeeded += 1
            logger.info("✅ Phase 2 p01 anchor complete [gen=%s]", gen_id[:8])

        except Exception as exc:
            logger.error("✗ Phase 2 p01 FAILED: %s", exc, exc_info=True)
            pages_failed.append(1)

        # ── Phase 3: Character pages 3,5,7,9,11,13,15,16 ─────────────────────
        logger.info("━ AI Book Phase 3: remaining character pages [gen=%s]", gen_id[:8])
        char_remaining = [p for p in pages if p["character_present"] and p["page_number"] != 1]

        # Expression map (one per character page for emotional arc)
        _EXPR = {3:"curious",5:"determined",7:"caring",9:"gentle",
                 11:"delighted",13:"welcoming",15:"joyful",16:"proud"}

        for page_cfg in sorted(char_remaining, key=lambda p: p["page_number"]):
            pn = page_cfg["page_number"]
            try:
                t0     = time.time()
                prompt = page_cfg["prompt"]["final_text"] + _CONSISTENCY_SUFFIX

                # Use page 1 raw as anchor if available; fall back to user photo
                anchor = page1_raw_bytes if page1_raw_bytes is not None else user_photo_bytes

                raw_bytes = self._dalle_edit(
                    image_bytes=anchor,
                    prompt=prompt,
                    quality=quality,
                    seed=generation_seed,
                )
                gen_ms = int((time.time() - t0) * 1000)

                # Save raw
                raw_local = str(out_dir / f"{gen_id}_p{pn:02d}_raw.png")
                Path(raw_local).write_bytes(raw_bytes)
                raw_blob = ai_character_raw_path(gen_id, pn)
                _upload_bytes(storage, raw_bytes, raw_blob)

                face_bbox, text_area = self._extract_coords(raw_bytes)

                # Burn text
                story_text  = page_cfg.get("story", "")
                textd_bytes = render_text_on_image(raw_bytes, story_text, child_name, text_area)
                textd_local = str(out_dir / f"{gen_id}_p{pn:02d}_textd.png")
                Path(textd_local).write_bytes(textd_bytes)

                # Face blend
                final_local = str(out_dir / f"{gen_id}_p{pn:02d}_final.png")
                fa          = page_cfg.get("face_anchor", {})
                pose        = fa.get("rotation", {"yaw": 0, "pitch": 0, "roll": 0})
                fc          = _anchor_to_face_config(fa) if fa else face_bbox

                face_pipeline_service.process_character_page(
                    template_path  = textd_local,
                    user_face_path = _bytes_to_temp(user_photo_bytes, ".jpg"),
                    face_config    = fc,
                    pose           = pose,
                    expression     = _EXPR.get(pn, "gentle"),
                    story_lines    = [],
                    text_area      = {"x": 0, "y": 0, "w": 0, "h": 0},
                    child_name     = child_name,
                    output_path    = final_local,
                )

                final_blob = ai_character_final_path(gen_id, pn)
                final_bytes = Path(final_local).read_bytes()
                _upload_bytes(storage, final_bytes, final_blob)

                save_character_page(gen_id, pn, {
                    "story_id":        story_id,
                    "user_mobile":     user_mobile,
                    "blob_path_raw":   raw_blob,
                    "blob_path_final": final_blob,
                    "face_bbox":       face_bbox,
                    "text_area":       text_area,
                    "is_anchor":       False,
                    "is_placeholder":  pn in PLACEHOLDER_PAGES,
                    "seed":            generation_seed,
                    "model":           "gpt-image-1",
                    "quality":         quality,
                    "generation_ms":   gen_ms,
                })

                pages_for_pdf.append({
                    "image_path": final_local, "text": "", "page_number": pn,
                })
                pages_succeeded += 1
                logger.info("✅ Phase 3 p%02d complete [gen=%s]", pn, gen_id[:8])

            except Exception as exc:
                logger.error("✗ Phase 3 p%02d FAILED: %s", pn, exc, exc_info=True)
                pages_failed.append(pn)

        # ── Phase 0b: Back cover ──────────────────────────────────────────────
        try:
            back_bytes = generate_back_cover("paperback", "storyme_default")
            back_local = str(out_dir / f"{gen_id}_p17.png")
            Path(back_local).write_bytes(back_bytes)
            pages_for_pdf.append({"image_path": back_local, "text": "", "page_number": 17})
            pages_succeeded += 1
        except Exception as exc:
            logger.error("Cover Phase 0b back failed: %s", exc)
            pages_failed.append(17)

        # ── Phase 4: PDF ──────────────────────────────────────────────────────
        logger.info("━ AI Book Phase 4: PDF assembly [gen=%s] %d pages", gen_id[:8], len(pages_for_pdf))
        if not pages_for_pdf:
            updates = {"status": "failed", "completed_at": _now_iso()}
            return {"status": "failed", "updates": updates}

        pages_for_pdf.sort(key=lambda p: p["page_number"])

        ts           = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        pdf_filename = f"{_safe_name(child_name)}_{ts}_{gen_id[:8]}.pdf"
        pdf_svc      = PDFService(str(out_dir))

        try:
            pdf_local = pdf_svc.create_storybook_pdf(
                child_name=child_name,
                story_title=story.get("title", "Storybook").replace("{name}", child_name),
                pages_data=pages_for_pdf,
                output_filename=pdf_filename,
            )
        except Exception as exc:
            logger.error("PDF assembly failed %s: %s", gen_id[:8], exc)
            updates = {"status": "failed", "completed_at": _now_iso()}
            return {"status": "failed", "updates": updates}

        # Upload PDF to blob
        pdf_blob_path = ""
        if config.STORAGE_TYPE in ("azure", "s3"):
            pdf_blob_path = pdf_path(child_name, story_id, gen_id)
            try:
                with open(pdf_local, "rb") as fh:
                    storage.save_file(fh, pdf_blob_path)
            except Exception as exc:
                logger.warning("PDF blob upload failed (non-fatal): %s", exc)

        now = _now_iso()
        updates = {
            "status":          "complete",
            "pdf_blob_path":   pdf_blob_path,
            "pdf_filename":    pdf_filename,
            "pages_succeeded": pages_succeeded,
            "pages_failed":    len(pages_failed),
            "total_pages":     18,
            "completed_at":    now,
        }

        logger.info(
            "━━━ AI BOOK COMPLETE ━━━ gen=%s pages=%d/%d pdf=%s",
            gen_id[:8], pages_succeeded, 18, pdf_filename,
        )
        return {"status": "complete", "updates": updates, "pdf_filename": pdf_filename}

    # ── DALL-E helpers ────────────────────────────────────────────────────────

    def _dalle_edit(
        self,
        image_bytes: bytes,
        prompt: str,
        quality: str,
        seed: int,
    ) -> bytes:
        """Call gpt-image-1 images.edit with the given image bytes as reference."""
        import httpx

        tmp = _bytes_to_temp(image_bytes, ".png")
        try:
            response = self._openai.images.edit(
                model   = "gpt-image-1",
                image   = open(tmp, "rb"),
                prompt  = prompt,
                size    = "1024x1024",
                quality = quality,
                n       = 1,
                seed    = seed,
            )
        finally:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass

        img_data = response.data[0]
        if getattr(img_data, "b64_json", None):
            return base64.b64decode(img_data.b64_json)
        if getattr(img_data, "url", None):
            resp = httpx.get(img_data.url, timeout=60)
            resp.raise_for_status()
            return resp.content
        raise RuntimeError("gpt-image-1 returned no image data")

    def _dalle_generate(
        self,
        prompt: str,
        quality: str,
        seed: int,
    ) -> bytes:
        """Call gpt-image-1 images.generate (for background pages)."""
        import httpx

        response = self._openai.images.generate(
            model   = "gpt-image-1",
            prompt  = prompt,
            size    = "1024x1024",
            quality = quality,
            n       = 1,
            seed    = seed,
        )
        img_data = response.data[0]
        if getattr(img_data, "b64_json", None):
            return base64.b64decode(img_data.b64_json)
        if getattr(img_data, "url", None):
            resp = httpx.get(img_data.url, timeout=60)
            resp.raise_for_status()
            return resp.content
        raise RuntimeError("gpt-image-1 returned no image data")

    def _extract_coords(self, image_bytes: bytes) -> tuple[dict, dict]:
        """
        Use GPT-4o vision to extract face_bbox and text_area from image.
        Falls back to defaults if extraction fails.
        """
        from services.dalle_service import DalleService
        try:
            meta = DalleService._extract_coordinates_static(image_bytes)
            return meta.get("face_bbox", {}), meta.get("text_area", {})
        except Exception as exc:
            logger.warning("Coord extraction failed: %s — using defaults", exc)
        # Default: face at left-centre, text at right zone
        face_bbox = {"x": 322, "y": 164, "w": 174, "h": 163}
        text_area = {"x": 634, "y": 65,  "w": 368, "h": 687}
        return face_bbox, text_area

    def _get_or_generate_background(
        self,
        story_id: str,
        version: str,
        page_number: int,
        prompt_text: str,
        p_hash: str,
        quality: str,
        page_cfg: dict,
    ) -> tuple[bytes, dict]:
        """
        3-tier cache lookup for background pages.
        Returns (image_bytes, text_area_dict).
        """
        from core.ai_page_store import get_background_page, save_background_page
        from core.storage import storage
        from core.storage_paths import ai_background_page_path
        from services.ai_text_renderer import DEFAULT_TEXT_ZONE

        cache_key = f"{story_id}:{page_number}:{p_hash}"

        # Tier 1: in-memory
        if cache_key in self._bg_cache:
            logger.debug("BG cache Tier-1 HIT: %s p%02d", story_id, page_number)
            return self._bg_cache[cache_key]

        # Tier 2: Azure Table
        row = get_background_page(story_id, page_number)
        if row and row.get("prompt_hash") == p_hash and row.get("blob_path"):
            try:
                img_bytes = storage.read_file(row["blob_path"])
                ta_raw    = row.get("text_area", "{}")
                text_area = json.loads(ta_raw) if isinstance(ta_raw, str) else ta_raw
                self._bg_cache[cache_key] = (img_bytes, text_area)
                logger.info("BG cache Tier-2 HIT: %s p%02d", story_id, page_number)
                return img_bytes, text_area
            except Exception as exc:
                logger.warning("Tier-2 blob read failed for p%02d: %s", page_number, exc)

        # Tier 3: DALL-E generate
        logger.info("BG cache MISS — calling DALL-E for %s p%02d", story_id, page_number)
        t0        = time.time()
        img_bytes = self._dalle_generate(prompt_text, quality, STORY_BACKGROUND_SEED)
        gen_ms    = int((time.time() - t0) * 1000)

        # Extract text_area via GPT-4o
        _, text_area = self._extract_coords(img_bytes)
        if not text_area:
            text_area = DEFAULT_TEXT_ZONE.copy()

        # Upload to blob
        blob_path = ai_background_page_path(story_id, version, page_number)
        try:
            storage.save_file(io.BytesIO(img_bytes), blob_path)
        except Exception as exc:
            logger.warning("BG blob upload failed p%02d: %s", page_number, exc)
            blob_path = ""

        # Save to DB
        save_background_page(story_id, page_number, {
            "story_version": version,
            "blob_path":     blob_path,
            "prompt_hash":   p_hash,
            "model":         "gpt-image-1",
            "quality":       quality,
            "seed":          STORY_BACKGROUND_SEED,
            "text_area":     text_area,
            "generation_ms": gen_ms,
        })

        self._bg_cache[cache_key] = (img_bytes, text_area)
        logger.info("BG generated and cached: %s p%02d (%dms)", story_id, page_number, gen_ms)
        return img_bytes, text_area

    # ── Cache status (for API endpoint) ──────────────────────────────────────

    def get_cache_status(self, story_id: str) -> dict:
        from core.ai_page_store import get_background_page
        story  = self._load_story()
        version = story.get("version", "v8")
        pages   = story["pages"]
        bg_nums = [p["page_number"] for p in pages if not p["character_present"]]
        missing = []
        cached  = 0
        for pn in bg_nums:
            row = get_background_page(story_id, pn)
            prompt_hash = _prompt_hash(
                next(p for p in pages if p["page_number"] == pn)["prompt"]["final_text"]
            )
            if row and row.get("prompt_hash") == prompt_hash:
                cached += 1
            else:
                missing.append(pn)
        return {
            "story_id":       story_id,
            "story_version":  version,
            "background_pages": {
                "total":   len(bg_nums),
                "cached":  cached,
                "missing": missing,
            },
            "estimated_cost_usd": round(len(missing) * 0.04, 2),
        }


# ─── Utility helpers ──────────────────────────────────────────────────────────

def _bytes_to_temp(data: bytes, suffix: str = ".png") -> str:
    """Write bytes to a temp file and return the path."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


def _upload_bytes(storage, data: bytes, blob_path: str) -> None:
    """Upload bytes to storage, silently skip if storage is local type."""
    from core.config import config
    if config.STORAGE_TYPE in ("azure", "s3"):
        try:
            storage.save_file(io.BytesIO(data), blob_path)
        except Exception as exc:
            logger.warning("Blob upload failed %s: %s", blob_path, exc)


# ─── Singleton ────────────────────────────────────────────────────────────────

def _create_service() -> Optional[AIBookService]:
    try:
        return AIBookService()
    except RuntimeError as exc:
        logger.warning("AIBookService not available: %s", exc)
        return None

ai_book_service: Optional[AIBookService] = _create_service()

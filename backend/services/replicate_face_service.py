"""
services/replicate_face_service.py
=====================================
Face-consistent storybook image generation via Replicate.
Replaces DALL-E images.edit() for character pages (Phases 2 & 3).

Supports two models (configurable at init):
  instantid   — zedge/instantid
                Best face-identity preservation. Recommended for production.
  ip_adapter  — lucataco/ip-adapter-sdxl-face
                Faster, lower cost, slightly lower identity fidelity.

Design principles:
  - Every character page uses the ORIGINAL user face photo as reference.
    No "page-1-as-anchor" trick needed — InstantID / IP-Adapter maintain
    identity directly from the face reference across all pages.
  - DALL-E backgrounds (Phase 1) are unchanged; only Phases 2 & 3 route here.
  - Thread-safe: all methods are synchronous and stateless, safe to call
    from ai_book_service._run_sync inside an asyncio thread executor.
  - Prompts are auto-converted from DALL-E GPT-4 instruction style to
    Stable Diffusion / SDXL tag style via _build_sdxl_prompt().
"""

from __future__ import annotations

import io
import logging
import re
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ── Model IDs (pinned versions for reproducibility) ───────────────────────────

# InstantID — best face identity preservation
# Source: zedge/instantid on Replicate (tested in test_replicate_instantid_v5.py)
INSTANTID_MODEL = (
    "zedge/instantid:"
    "ba2d5293be8794a05841a6f6eed81e810340142c3c25fab4838ff2b5d9574420"
)

# IP-Adapter FaceID — lighter / faster alternative
# Swap this version hash when a newer version is published on Replicate
IP_ADAPTER_MODEL = (
    "lucataco/ip-adapter-sdxl-face:"
    "2a23d66a53db3af8fb0898a8af8c817f93bab3702a13a0a3c00e76e4fad27c7d"
)


# ── Prompt engineering ────────────────────────────────────────────────────────

# SD/SDXL style prefix — prepended to every character page prompt
_SDXL_STYLE_PREFIX = (
    "pixar 3d animation style, children's storybook illustration, "
    "soft pastel color palette, warm cinematic lighting, shallow depth of field, "
    "smooth 3d render, emotionally warm, magical atmosphere, "
    "high detail, 8k resolution, masterpiece, best quality, "
    "character on left third of frame, right side soft for text"
)

# Negative prompt — applied to all Replicate calls
_SDXL_NEGATIVE = (
    "realistic, photograph, photorealistic, ugly, deformed, bad anatomy, "
    "extra limbs, blurry, low quality, low resolution, watermark, text, "
    "logo, signature, horror, disturbing, nsfw, adult, mature, "
    "dark, violence, gore, monochrome, grayscale, oversaturated"
)

# Per-expression face description injected into the prompt
_EXPRESSION_MAP: dict[str, str] = {
    "curious":    "wide curious eyes, slightly open mouth, wondering expression",
    "determined": "determined focused gaze, chin slightly raised, confident expression",
    "caring":     "warm gentle eyes, soft reassuring smile, nurturing expression",
    "gentle":     "quiet peaceful smile, gentle kind eyes, calm serene expression",
    "delighted":  "sparkling eyes, wide bright smile, pure delight, joyful face",
    "welcoming":  "open warm smile, inviting expression, friendly welcoming eyes",
    "joyful":     "big joyful smile, crinkled happy eyes, beaming with happiness",
    "proud":      "satisfied proud expression, standing tall, calm content smile",
    "neutral":    "calm thoughtful expression, neutral peaceful face",
}


def _build_sdxl_prompt(dalle_prompt: str, expression: str = "neutral") -> str:
    """
    Convert a DALL-E GPT-4 instruction-style prompt into an SDXL tag-based prompt.

    Extracts the SCENE DESCRIPTION block from the DALL-E prompt, strips
    any "no humans" directives (irrelevant for character pages), injects
    the expression descriptor, and wraps in the Pixar style prefix.
    """
    scene = _extract_scene(dalle_prompt)
    expr_tag = _EXPRESSION_MAP.get(expression, _EXPRESSION_MAP["neutral"])

    return (
        f"{_SDXL_STYLE_PREFIX}, "
        f"{scene}, "
        f"young cartoon child, {expr_tag}, "
        f"Pixar cartoon face resembling reference photo, "
        f"same character consistent across pages"
    )


def _extract_scene(dalle_prompt: str) -> str:
    """Extract the scene description paragraph from a DALL-E prompt."""
    if "SCENE DESCRIPTION:" in dalle_prompt:
        after = dalle_prompt.split("SCENE DESCRIPTION:")[1]
        match = re.search(r"\n[A-Z]{3,}[\s\S]*?:", after)
        raw = after[: match.start()].strip() if match else after.strip()
        # Remove "no humans / no children" constraints — irrelevant for char pages
        raw = re.sub(r",?\s*no humans?", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r",?\s*no characters?", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r",?\s*no children", "", raw, flags=re.IGNORECASE)
        return raw.strip(" ,.")

    # Fallback: first non-bullet paragraph of reasonable length
    for line in dalle_prompt.splitlines():
        line = line.strip()
        if len(line) > 25 and not line.startswith("-") and not line.isupper():
            return line[:300]

    return dalle_prompt[:200]


# ── Service class ─────────────────────────────────────────────────────────────

class ReplicateFaceService:
    """
    Generates face-consistent storybook character pages via Replicate.

    One instance is created per AIBookService when engine='replicate'.
    All methods are synchronous and safe to call from a thread executor.
    """

    def __init__(
        self,
        api_token: str,
        primary_model: str = "instantid",
        identitynet_strength: float = 0.85,
        adapter_strength: float = 0.80,
        guidance_scale: float = 7.5,
    ) -> None:
        """
        Args:
            api_token:             Replicate API token (r8_...).
            primary_model:         "instantid" or "ip_adapter".
            identitynet_strength:  InstantID identity net strength (0.0–1.0).
                                   Higher = stronger face match; lower = more
                                   creative freedom.  0.85 is a good default.
            adapter_strength:      IP-Adapter / adapter ratio (0.0–1.0).
            guidance_scale:        CFG guidance scale for SDXL.
        """
        if not api_token:
            raise RuntimeError(
                "REPLICATE_API_TOKEN is not set. "
                "Add REPLICATE_API_TOKEN=r8_... to tests/playground/env"
            )
        try:
            import replicate as _replicate
            self._client = _replicate.Client(api_token=api_token)
        except ImportError as exc:
            raise RuntimeError(
                "replicate package is not installed. "
                "Run: pip install replicate"
            ) from exc

        self._primary_model       = primary_model.lower()
        self._identitynet_strength = identitynet_strength
        self._adapter_strength     = adapter_strength
        self._guidance_scale       = guidance_scale

        logger.info(
            "ReplicateFaceService ready: model=%s id_strength=%.2f adapter_strength=%.2f",
            primary_model, identitynet_strength, adapter_strength,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_character_page(
        self,
        face_bytes: bytes,
        dalle_prompt: str,
        expression: str = "neutral",
        page_number: int = 0,
        quality: str = "medium",
    ) -> bytes:
        """
        Generate a full storybook character page with the child's face.

        Args:
            face_bytes:    Raw bytes of the child's photo (JPEG or PNG).
            dalle_prompt:  The existing story JSON prompt['final_text'].
                           Converted to SDXL format internally.
            expression:    Emotion key — must be a key of _EXPRESSION_MAP.
            page_number:   Page index, used for logging only.
            quality:       "medium" → 30 steps; "high" → 50 steps.

        Returns:
            PNG image bytes (1024×1024).
        """
        sdxl_prompt = _build_sdxl_prompt(dalle_prompt, expression)
        steps = 30 if quality == "medium" else 50

        logger.info(
            "Replicate %s p%02d  expr=%-12s  steps=%d",
            self._primary_model.upper(), page_number, expression, steps,
        )
        logger.debug("SDXL prompt (p%02d): %.200s", page_number, sdxl_prompt)

        if self._primary_model == "instantid":
            return self._run_instantid(face_bytes, sdxl_prompt, steps, page_number)
        else:
            return self._run_ip_adapter(face_bytes, sdxl_prompt, steps, page_number)

    # ── InstantID ─────────────────────────────────────────────────────────────

    def _run_instantid(
        self,
        face_bytes: bytes,
        prompt: str,
        steps: int,
        page_number: int,
    ) -> bytes:
        t0 = time.time()
        try:
            output = self._client.run(
                INSTANTID_MODEL,
                input={
                    "image":                      io.BytesIO(face_bytes),
                    "prompt":                     prompt,
                    "negative_prompt":            _SDXL_NEGATIVE,
                    "width":                      1024,
                    "height":                     1024,
                    "num_outputs":                1,
                    "num_inference_steps":        steps,
                    "guidance_scale":             self._guidance_scale,
                    "identitynet_strength_ratio": self._identitynet_strength,
                    "adapter_strength_ratio":     self._adapter_strength,
                    "enable_lcm":                 False,
                    "enhance_face_region":        True,
                },
            )
        except Exception as exc:
            logger.error("InstantID p%02d FAILED (%dms): %s",
                         page_number, int((time.time() - t0) * 1000), exc)
            raise

        gen_ms = int((time.time() - t0) * 1000)
        logger.info("✅ InstantID p%02d complete (%dms)", page_number, gen_ms)
        return self._resolve_output(output, page_number)

    # ── IP-Adapter FaceID ─────────────────────────────────────────────────────

    def _run_ip_adapter(
        self,
        face_bytes: bytes,
        prompt: str,
        steps: int,
        page_number: int,
    ) -> bytes:
        t0 = time.time()
        try:
            output = self._client.run(
                IP_ADAPTER_MODEL,
                input={
                    "image":                 io.BytesIO(face_bytes),
                    "prompt":                prompt,
                    "negative_prompt":       _SDXL_NEGATIVE,
                    "width":                 1024,
                    "height":                1024,
                    "num_outputs":           1,
                    "num_inference_steps":   steps,
                    "guidance_scale":        self._guidance_scale,
                    "ip_adapter_scale":      self._adapter_strength,
                },
            )
        except Exception as exc:
            logger.error("IP-Adapter p%02d FAILED (%dms): %s",
                         page_number, int((time.time() - t0) * 1000), exc)
            raise

        gen_ms = int((time.time() - t0) * 1000)
        logger.info("✅ IP-Adapter p%02d complete (%dms)", page_number, gen_ms)
        return self._resolve_output(output, page_number)

    # ── Output resolution ─────────────────────────────────────────────────────

    def _resolve_output(self, output, page_number: int) -> bytes:
        """
        Normalise Replicate output — handle both FileOutput objects (SDK >= 0.25)
        and plain URL strings returned by older SDK / some models.
        """
        if not output:
            raise RuntimeError(
                f"Replicate returned empty output for p{page_number:02d}"
            )

        item = output[0] if isinstance(output, (list, tuple)) else output

        # Replicate SDK >= 0.25 returns FileOutput with a .read() method
        if hasattr(item, "read"):
            data = item.read()
            if isinstance(data, bytes):
                return data
            # Some versions return an async iterator — materialise it
            return b"".join(data) if not isinstance(data, bytes) else data

        # URL string (older SDK or direct run)
        url = getattr(item, "url", None) or str(item)
        if not url.startswith("http"):
            raise RuntimeError(
                f"Replicate output for p{page_number:02d} is neither "
                f"FileOutput nor URL: {url!r}"
            )
        logger.debug("Downloading Replicate output p%02d from %s", page_number, url[:80])
        resp = httpx.get(url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        return resp.content

"""
services/generation_mode.py
============================
Abstraction layer for the two image generation modes.

Both modes share the same inputs and produce the same output (a PNG file at
a known local path). Storage API calls, route handling, and PDF generation
are completely unaware of which mode was used.

MODE 1 — opencv (default):
  Uses the face_blend pipeline from tests/playground/face_blend.py.
  Steps: MediaPipe landmarks → 7-point affine align → ConvexHull extract →
         LAB colour match → luminance match → Gaussian mask → seamlessClone.
  Fast (~2-5s/page), no external API cost.

MODE 2 — ai (experimental):
  Sends user face image + scene reference image + story prompt to an AI model
  (configured via OPENAI_API_KEY). The model generates a fully personalised
  scene image. Slower, incurs API cost, potentially higher quality.
  Falls back gracefully to opencv mode if not configured.

Interface contract:
  generate_page(
      mode:            GenerationMode (opencv | ai)
      template_path:   absolute local path to the scene template PNG
      reference_path:  absolute local path to the reference face PNG (for alignment)
      user_face_path:  absolute local path to the uploaded user photo
      face_config:     dict {x, y, w, h} — face placement coordinates in template
      output_path:     absolute local path where the result PNG should be written
      child_name:      str — for AI prompt personalisation
      scene_text:      str — story text for AI prompt
  ) -> str | None
      Returns output_path on success, None on failure (caller falls back).
"""

import logging
from pathlib import Path
from typing import Optional, Dict

from models.generation import GenerationMode

logger = logging.getLogger(__name__)


def generate_page(
    mode: GenerationMode,
    template_path: str,
    reference_path: str,
    user_face_path: str,
    face_config: Dict[str, int],
    output_path: str,
    child_name: str = "",
    scene_text: str = "",
) -> Optional[str]:
    """
    Generate a single story page image using the specified mode.

    Args:
        mode:           GenerationMode.OPENCV or GenerationMode.AI
        template_path:  Local path to the illustrated scene template PNG
        reference_path: Local path to the reference face image (for landmark alignment)
        user_face_path: Local path to the child's uploaded photo
        face_config:    {x, y, w, h} — face placement in template pixels
        output_path:    Where to write the output PNG
        child_name:     Child's name (used in AI prompt)
        scene_text:     Story text for this scene (used in AI prompt)

    Returns:
        output_path string on success.
        None on failure — caller should fall back to PIL pipeline.
    """
    if mode == GenerationMode.AI:
        return _generate_ai(
            template_path=template_path,
            reference_path=reference_path,
            user_face_path=user_face_path,
            face_config=face_config,
            output_path=output_path,
            child_name=child_name,
            scene_text=scene_text,
        )
    # Default: opencv
    return _generate_opencv(
        template_path=template_path,
        reference_path=reference_path,
        user_face_path=user_face_path,
        face_config=face_config,
        output_path=output_path,
    )


# ─── OpenCV mode ──────────────────────────────────────────────────────────────

def _generate_opencv(
    template_path: str,
    reference_path: str,
    user_face_path: str,
    face_config: Dict[str, int],
    output_path: str,
) -> Optional[str]:
    """
    Generate page using the face_blend pipeline (OpenCV + MediaPipe).

    Pipeline (ported from tests/playground/face_blend.py):
      1. Detect MediaPipe FaceMesh landmarks on user photo
      2. Align face to canonical frontal pose (7-point affine, LMEDS, flip-safe)
      3. Re-detect landmarks on aligned image
      4. Extract face region via ConvexHull bounding box
      5. Resize and position at face_config coordinates
      6. Match LAB-space colour statistics to template ROI
      7. Match luminance to template ROI
      8. Create Gaussian-feathered elliptical mask
      9. cv2.seamlessClone into template

    The reference_path is used for landmark-based alignment (the reference
    contains a frontal face at the expected pose so alignment is stable).
    Falls back to using user face directly if reference alignment fails.
    """
    from services.face_blend_service import process_scene

    try:
        result = process_scene(
            template_path=template_path,
            user_face_path=user_face_path,
            face_config=face_config,
            output_path=output_path,
        )
        if result:
            logger.debug("opencv: generated %s", Path(output_path).name)
        return result
    except Exception as e:
        logger.warning("opencv generation failed: %s", e)
        return None


# ─── AI mode ──────────────────────────────────────────────────────────────────

def _generate_ai(
    template_path: str,
    reference_path: str,
    user_face_path: str,
    face_config: Dict[str, int],
    output_path: str,
    child_name: str,
    scene_text: str,
) -> Optional[str]:
    """
    Generate page using an AI image generation model.

    Current implementation:
      Uses DALL-E 3 via OpenAI API. Sends:
        - The scene template as style reference
        - A prompt describing the scene with the child's name
        - (Future: send user face for in-painting when model supports it)

    Falls back gracefully: if OPENAI_API_KEY is not set or the API call
    fails, returns None so the caller falls back to opencv mode.

    TODO: When a face-aware model (e.g. IP-Adapter, InstantID) is
    integrated, the user_face_path and reference_path will be used
    to condition the generated face on the child's actual appearance.
    """
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning(
            "AI generation mode requested but OPENAI_API_KEY is not set. "
            "Falling back to opencv mode."
        )
        return _generate_opencv(
            template_path=template_path,
            reference_path=reference_path,
            user_face_path=user_face_path,
            face_config=face_config,
            output_path=output_path,
        )

    try:
        from openai import OpenAI
        import base64, urllib.request

        client = OpenAI()

        # Build a rich prompt for the scene
        clean_text = scene_text.replace("{name}", child_name)
        prompt = (
            f"Pixar-style children's book illustration, soft pastel colors, "
            f"warm lighting, cinematic composition, shallow depth of field. "
            f"A child named {child_name} is the main character. "
            f"Scene: {clean_text[:200]}. "
            f"The child has a photorealistic face that is warm and friendly. "
            f"Style matches the provided template image."
        )

        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )

        image_url = response.data[0].url
        urllib.request.urlretrieve(image_url, output_path)

        logger.info("AI generation succeeded: %s", Path(output_path).name)
        return output_path

    except Exception as e:
        logger.warning(
            "AI generation failed (%s) — falling back to opencv mode", e
        )
        return _generate_opencv(
            template_path=template_path,
            reference_path=reference_path,
            user_face_path=user_face_path,
            face_config=face_config,
            output_path=output_path,
        )

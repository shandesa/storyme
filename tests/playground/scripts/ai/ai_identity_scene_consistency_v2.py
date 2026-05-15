# ============================================================
# File:
# ai_identity_scene_consistency_v2.py
#
# Design reference:
# tests/playground/scripts/ai/notes/ai_identity_scene_consistency_v2.pdf
#
# Stage 1 — Identity extraction     (InsightFace buffalo_l)
# Stage 2 — Canonical generation    (zsxkib/instant-id)
# Stage 3 — Per-page scene gen      (InstantID + ArcFace verify)
# Stage 4 — Face swap fallback      (InsightFace inswapper_128)
# Stage 5 — Final verification      (ArcFace score commit)
#
# ============================================================
# VERSION HISTORY
# ============================================================
#
# v1.0.0  2026-05-14  ai_identity_scene_consistency.py (original)
#   - Placeholder model "google/nano-banana" (non-functional)
#   - compute_identity_similarity() returned np.random.uniform()
#     -- no real identity measurement ever performed
#   - create_face_crop() used fixed rectangle (20-80% width,
#     10-75% height) -- not face detection
#   - reference images passed via CLIP (wrong architecture for
#     biometric identity; ~80% sim between different people)
#   - Fixed seed=12345 for all generations (retries identical)
#   - previous_page fed back as reference (drift compounding)
#   - No fallback when generation fails
#
# v2.0.0  2026-05-14  ai_identity_scene_consistency_v2.py
#   - Complete redesign per design reference PDF
#   - Stage 1: InsightFace buffalo_l -- real face detection,
#     ArcFace 512-dim embedding, aligned 112x112 crop,
#     padded crop for InstantID reference
#   - Stage 2: zsxkib/instant-id canonical generation with
#     real ArcFace cosine similarity verification (threshold 0.40)
#   - Stage 3: Per-page scene generation -- real ArcFace gating
#     replaces np.random.uniform(); seed formula
#     BASE_SEED + (page*100) + (attempt*10); previous_page
#     removed from generation references
#   - Stage 4: InsightFace inswapper_128 CPU fallback --
#     triggers only after all 3 attempts fail threshold
#   - Stage 5: Real ArcFace score logged per page before commit
#   - inswapper_128.onnx: auto-download from HuggingFace with
#     SHA256 verification on every startup
#   - buffalo_l: auto-downloads via InsightFace on first run
#
# v2.0.1  2026-05-14  Bug fix
#   - REPLICATE_MODEL: replaced ":latest" suffix with explicit
#     version hash c98b2e7a... -- Python SDK does not resolve
#     ":latest"; returns 422 from Replicate predictions API
#
# v2.0.2  2026-05-14  Bug fix
#   - SDXL_WEIGHTS: "dreamshaper-xl-turbov2" -> "dreamshaper-xl"
#     Model version c98b2e7a rejects the turbov2 variant name;
#     valid enum returned in 422 response
#
# v2.1.0  2026-05-15  Quality fix -- identity fidelity + scene composition
#   Issues fixed:
#     1. Hairstyle inconsistent across pages vs reference photo
#     2. Eye colour drifting from reference (dark brown -> hazel)
#     3. Cartoonization too heavy; character not recognisable
#        enough as the real child
#     4. Scene content absent; images are portrait close-ups
#        instead of wide storybook scenes
#   Changes:
#   - SDXL_WEIGHTS: "dreamshaper-xl" -> "protovision-xl-high-fidel"
#     Higher fidelity base model; semi-realistic illustrated output;
#     reduces cartoon drift while keeping illustrated quality
#   - IP_ADAPTER_SCALE: 0.85 -> 0.95
#     Stronger face identity conditioning into diffusion process;
#     reduces hair-style and eye-colour drift
#   - CONTROLNET_SCALE: 0.80 -> 0.90
#     Stronger facial keypoint (landmark) conditioning;
#     improves structural face consistency across pages
#   - NUM_INFERENCE_STEPS: 30 -> 40
#     Better detail quality; reduces feature drift at low step count
#   - _STYLE_BLOCK: removed "Pixar animated movie style" -- primary
#     driver of over-cartoonization; replaced with
#     "children's storybook illustration, semi-realistic digital
#     painting" -- keeps illustrated aesthetic without cartoon excess
#   - _build_character_block(description): replaces static
#     _CHARACTER_BLOCK constant; accepts optional character_description
#     from story.json to anchor hair, eye, skin tone in prompt text
#   - _build_canonical_prompt(description): replaces static
#     CANONICAL_PROMPT constant; built per-run from style +
#     character blocks with description threading
#   - _SCENE_FRAMING_BLOCK: new constant -- "wide establishing shot,
#     full body, child visible in large environment" -- forces scene
#     composition instead of portrait close-up
#   - SCENE_NEGATIVE_PROMPT: new constant -- extends base negative
#     prompt with portrait/close-up penalties for scene pages only;
#     canonical generation retains original negative prompt
#   - build_scene_prompt(page_prompt, character_description): updated
#     to incorporate _SCENE_FRAMING_BLOCK and character_description
#   - call_instantid(): added negative_prompt parameter (default None
#     falls back to NEGATIVE_PROMPT); scene pages pass
#     SCENE_NEGATIVE_PROMPT; canonical passes NEGATIVE_PROMPT
#   - load_story_input(): reads optional character_description field
#     from story.json; returned as third element of tuple
#   - generate_canonical_character(): accepts character_description;
#     passes to _build_canonical_prompt()
#   - generate_page(): accepts character_description; passes to
#     build_scene_prompt() and SCENE_NEGATIVE_PROMPT to call_instantid
#   - main(): unpacks character_description from load_story_input;
#     threads through to generate_canonical_character and generate_page
#
# ============================================================

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import replicate
import requests

try:
    import cv2
except Exception:
    cv2 = None

try:
    import insightface
    from insightface.app import FaceAnalysis
    from insightface.utils import face_align as _face_align
    _INSIGHTFACE_OK = True
except Exception:
    insightface = None
    FaceAnalysis = None
    _face_align = None
    _INSIGHTFACE_OK = False


# ============================================================
# CONFIG
# ============================================================

REPLICATE_MODEL     = "zsxkib/instant-id:c98b2e7a196828d00955767813b81fc05c5c9b294c670c6d147d545fed4ceecf"
SDXL_WEIGHTS        = "protovision-xl-high-fidel"      # v2.1.0: raised from dreamshaper-xl

SIMILARITY_THRESHOLD_CANONICAL = 0.40
SIMILARITY_THRESHOLD_PAGE      = 0.35

MAX_RETRIES          = 3
BASE_SEED            = 42
IP_ADAPTER_SCALE     = 0.95                            # v2.1.0: raised from 0.85
CONTROLNET_SCALE     = 0.90                            # v2.1.0: raised from 0.80
IMAGE_WIDTH          = 768
IMAGE_HEIGHT         = 768
NUM_INFERENCE_STEPS  = 40                              # v2.1.0: raised from 30
GUIDANCE_SCALE       = 5.0

INSWAPPER_HF_URL = (
    "https://huggingface.co/Aitrepreneur/insightface"
    "/resolve/fd887cdef0c73f32251198b8160d6771ac413fc0"
    "/inswapper_128.onnx"
)
INSWAPPER_SHA256  = (
    "e4a3f08c753cb72d04e10aa0f7dbe3deebbf39567d4ead6dce08e98aa49e16af"
)
INSWAPPER_SIZE_MB = 554

# ---- Paths --------------------------------------------------

PLAYGROUND_DIR = Path(__file__).resolve().parents[2]

INPUT_DIR  = PLAYGROUND_DIR / "input"
OUTPUT_DIR = PLAYGROUND_DIR / "output" / "identity_scene_consistency"
LOG_DIR    = PLAYGROUND_DIR / "output" / "logs" / "identity_scene_consistency"
ENV_FILE   = PLAYGROUND_DIR / "env"

# InsightFace root: models land at PLAYGROUND_DIR/models/{model_name}/
# FaceAnalysis(root=INSIGHTFACE_ROOT) -> INSIGHTFACE_ROOT/models/buffalo_l/
# get_model('inswapper_128', root=INSIGHTFACE_ROOT) -> INSIGHTFACE_ROOT/models/inswapper_128/
INSIGHTFACE_ROOT     = str(PLAYGROUND_DIR)
INSWAPPER_MODEL_PATH = PLAYGROUND_DIR / "models" / "inswapper_128" / "inswapper_128.onnx"

for _d in [OUTPUT_DIR, LOG_DIR, INSWAPPER_MODEL_PATH.parent]:
    _d.mkdir(parents=True, exist_ok=True)


# ============================================================
# PROMPTS
# ============================================================

# v2.1.0: "Pixar animated movie style" removed -- primary driver of
# over-cartoonization. Replaced with semi-realistic illustration language.
_STYLE_BLOCK = (
    "children's storybook illustration, semi-realistic digital painting, "
    "warm soft cinematic lighting, vibrant yet gentle colors, "
    "high quality detailed art, cinematic composition"
)

# v2.1.0: scene framing block -- forces wide establishing shot composition
# instead of portrait close-up for story page images.
_SCENE_FRAMING_BLOCK = (
    "wide establishing shot, full body character, child is a small clear figure "
    "in a large detailed environment, expansive scene background, "
    "environment fills most of the frame, cinematic wide angle storybook scene"
)

# Base negative prompt -- used for canonical portrait generation.
NEGATIVE_PROMPT = (
    "realistic photography, photorealistic, ugly, deformed, distorted face, "
    "extra limbs, adult, elderly, scary, dark, violent, blurry, low quality, "
    "watermark, text, logo"
)

# v2.1.0: scene-specific negative prompt -- extends base with close-up
# penalties; used only for scene page generation (Stage 3), not canonical.
SCENE_NEGATIVE_PROMPT = (
    NEGATIVE_PROMPT + ", "
    "portrait, close-up, headshot, face only, cropped face, "
    "shallow depth of field, bokeh, plain background, no environment, "
    "empty background, white background"
)


def _build_character_block(character_description=""):
    """
    v2.1.0: Replaces static _CHARACTER_BLOCK constant.
    Builds the character identity anchor string for prompts.
    character_description -- optional free-text from story.json
    field 'character_description' (e.g. "young boy, dark straight
    hair, dark brown eyes, warm olive skin tone"). When provided,
    it anchors hair, eye colour, and skin tone in the text prompt,
    reducing generative drift on those features.
    """
    base = (
        "same child, same face, same facial features, "
        "same hairstyle and hair color, same eye color, same skin tone"
    )
    desc = character_description.strip()
    if desc:
        return f"{base}, {desc}"
    return base


def _build_canonical_prompt(character_description=""):
    """
    v2.1.0: Replaces static CANONICAL_PROMPT constant.
    Built per-run so character_description is incorporated.
    """
    char_block = _build_character_block(character_description)
    return (
        f"{_STYLE_BLOCK}, {char_block}, "
        "front-facing portrait, gentle smile, face clearly visible, "
        "looking at camera, full upper body, soft even lighting on face"
    )


def build_scene_prompt(page_prompt, character_description=""):
    """
    v2.1.0: Added character_description parameter and
    _SCENE_FRAMING_BLOCK to force wide scene composition.
    """
    char_block = _build_character_block(character_description)
    return (
        f"{_STYLE_BLOCK}, {char_block}, "
        f"{_SCENE_FRAMING_BLOCK}, {page_prompt}"
    )


# ============================================================
# LOGGER
# ============================================================

def setup_logger(name):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file  = LOG_DIR / f"{name}_{timestamp}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info("===================================================")
    logger.info("AI Identity Scene Consistency v2 Started")
    logger.info("===================================================")
    logger.info(f"Log file: {log_file}")

    return logger


# ============================================================
# ENV
# ============================================================

def load_env(logger):
    logger.info(f"Loading env file: {ENV_FILE}")

    if not ENV_FILE.exists():
        raise FileNotFoundError(f"Env file missing: {ENV_FILE}")

    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

    token = os.environ.get("REPLICATE_KEY") or os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        raise RuntimeError("REPLICATE_KEY or REPLICATE_API_TOKEN missing in env file")

    os.environ["REPLICATE_API_TOKEN"] = token
    logger.info("REPLICATE_API_TOKEN loaded")


# ============================================================
# INPUT
# ============================================================

def load_story_input(name, logger):
    """
    v2.1.0: Also reads optional 'character_description' field from
    story.json. Example story.json with description:
      {
        "character_description": "young boy, dark straight hair,
          dark brown eyes, warm olive skin tone",
        "pages": [...]
      }
    Returns (pages, original_image, character_description).
    character_description is an empty string when not present.
    """
    logger.info(f"Loading input: {name}")

    person_dir = INPUT_DIR / name
    story_file = person_dir / "story.json"
    images_dir = person_dir / "images"

    if not story_file.exists():
        raise FileNotFoundError(f"story.json missing: {story_file}")
    if not images_dir.exists():
        raise FileNotFoundError(f"images/ folder missing: {images_dir}")

    with open(story_file, "r", encoding="utf-8") as f:
        story_data = json.load(f)

    supported = {".jpg", ".jpeg", ".png", ".webp"}
    image_files = [
        p for p in images_dir.iterdir()
        if p.suffix.lower() in supported
    ]
    if not image_files:
        raise RuntimeError(f"No reference image found in {images_dir}")

    original_image        = image_files[0]
    pages                 = story_data.get("pages", [])
    character_description = story_data.get("character_description", "")

    logger.info(f"Reference image       : {original_image.name}")
    logger.info(f"Total pages           : {len(pages)}")
    logger.info(f"Character description : {character_description or '(none -- using generic anchor)'}")

    return pages, original_image, character_description


# ============================================================
# MODEL DOWNLOAD -- inswapper_128.onnx
# ============================================================

def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_inswapper_model(logger):
    logger.info("---------------------------------------------------")
    logger.info("Model check: inswapper_128.onnx")
    logger.info("---------------------------------------------------")

    if INSWAPPER_MODEL_PATH.exists():
        logger.info("File found -- verifying SHA256...")
        sha256 = _sha256_file(INSWAPPER_MODEL_PATH)
        if sha256 == INSWAPPER_SHA256:
            logger.info("SHA256 OK -- inswapper_128.onnx is valid")
            return
        logger.warning(
            f"SHA256 mismatch (got {sha256[:16]}...) -- deleting and re-downloading"
        )
        INSWAPPER_MODEL_PATH.unlink()

    logger.info(f"Downloading inswapper_128.onnx (~{INSWAPPER_SIZE_MB} MB)")
    logger.info(f"Source: {INSWAPPER_HF_URL}")

    tmp_path = INSWAPPER_MODEL_PATH.with_suffix(".tmp")

    try:
        response = requests.get(INSWAPPER_HF_URL, stream=True, timeout=300)
        response.raise_for_status()

        total      = int(response.headers.get("content-length", INSWAPPER_SIZE_MB * 1024 * 1024))
        downloaded = 0
        last_pct   = -10

        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    pct = int(downloaded * 100 / total) if total else 0
                    if pct - last_pct >= 10:
                        logger.info(
                            f"Download: {pct}%  "
                            f"({downloaded // (1024 * 1024)} / {total // (1024 * 1024)} MB)"
                        )
                        last_pct = pct

        logger.info("Download complete -- verifying SHA256...")
        sha256 = _sha256_file(tmp_path)
        if sha256 != INSWAPPER_SHA256:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA256 mismatch after download.\n"
                f"  Expected : {INSWAPPER_SHA256}\n"
                f"  Got      : {sha256}"
            )

        tmp_path.rename(INSWAPPER_MODEL_PATH)
        logger.info(f"inswapper_128.onnx verified and saved: {INSWAPPER_MODEL_PATH}")

    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


# ============================================================
# INSIGHTFACE ANALYZER
# ============================================================

def build_analyzer(logger):
    if not _INSIGHTFACE_OK:
        raise RuntimeError(
            "insightface not installed.\n"
            "Run: pip install insightface onnxruntime opencv-python"
        )
    if cv2 is None:
        raise RuntimeError(
            "opencv-python not installed.\n"
            "Run: pip install opencv-python"
        )

    logger.info("Initialising InsightFace FaceAnalysis (buffalo_l)...")
    app = FaceAnalysis(
        name="buffalo_l",
        root=INSIGHTFACE_ROOT,
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    logger.info("InsightFace ready")
    return app


# ============================================================
# STAGE 1 -- IDENTITY EXTRACTION
# ============================================================

def extract_face_identity(image_path, name, analyzer, logger):
    logger.info("===================================================")
    logger.info("STAGE 1 -- Identity extraction")
    logger.info("===================================================")

    img = cv2.imread(str(image_path))
    if img is None:
        raise RuntimeError(f"Failed to load image: {image_path}")

    faces = analyzer.get(img)
    if not faces:
        raise RuntimeError(
            f"No face detected in: {image_path}\n"
            "Ensure the image contains a clearly visible, well-lit frontal face."
        )

    # Largest face by bounding-box area
    face = sorted(
        faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
    )[-1]

    logger.info(f"Face detected -- bbox: {[int(v) for v in face.bbox]}")

    # ArcFace embedding (512-dim, already L2-normalised by InsightFace)
    reference_embedding = face.normed_embedding.copy()
    logger.info(f"ArcFace embedding extracted: shape={reference_embedding.shape}")

    # Aligned 112x112 crop (for local verification comparisons)
    aligned = _face_align.norm_crop(img, face.kps, image_size=112)
    aligned_path = OUTPUT_DIR / f"{name}_face_aligned.png"
    cv2.imwrite(str(aligned_path), aligned)
    logger.info(f"Aligned crop (112x112) saved: {aligned_path}")

    # Padded crop with 35% context (passed to InstantID as identity reference)
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    ih, iw = img.shape[:2]
    fw, fh = x2 - x1, y2 - y1
    px, py = int(fw * 0.35), int(fh * 0.35)
    cx1 = max(0, x1 - px)
    cy1 = max(0, y1 - py)
    cx2 = min(iw, x2 + px)
    cy2 = min(ih, y2 + py)
    padded = img[cy1:cy2, cx1:cx2]
    padded_path = OUTPUT_DIR / f"{name}_face_crop.png"
    cv2.imwrite(str(padded_path), padded)
    logger.info(f"Padded face crop saved: {padded_path}")

    return reference_embedding, padded_path


# ============================================================
# IDENTITY VERIFICATION (ArcFace cosine similarity)
# ============================================================

def verify_identity(generated_path, reference_embedding, threshold, analyzer, logger):
    img = cv2.imread(str(generated_path))
    if img is None:
        logger.warning(f"Could not load generated image: {generated_path}")
        return 0.0, False

    faces = analyzer.get(img)
    if not faces:
        logger.warning("No face detected in generated image -- hard fail")
        return 0.0, False

    gen_face = sorted(
        faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
    )[-1]

    # Both embeddings are L2-normalised -> cosine similarity = dot product
    similarity = float(np.dot(reference_embedding, gen_face.normed_embedding))
    passed     = similarity >= threshold

    logger.info(
        f"ArcFace similarity: {similarity:.4f}  "
        f"threshold: {threshold:.2f}  "
        f"{'PASS' if passed else 'FAIL'}"
    )
    return similarity, passed


# ============================================================
# SAVE OUTPUT IMAGE
# ============================================================

def save_output_image(output, output_path, logger):
    if isinstance(output, list):
        output = output[0]

    if hasattr(output, "read"):
        with open(output_path, "wb") as f:
            f.write(output.read())
        logger.info(f"Saved (stream): {output_path}")
        return

    url = None
    if hasattr(output, "url"):
        url = output.url
    elif isinstance(output, str) and output.startswith("http"):
        url = output

    if url:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(r.content)
        logger.info(f"Saved (url): {output_path}")
        return

    raise RuntimeError(f"Unrecognised Replicate output type: {type(output)}")


# ============================================================
# GENERATION -- InstantID via Replicate
# ============================================================

def call_instantid(face_crop_path, prompt, seed, logger, negative_prompt=None):
    """
    v2.1.0: Added negative_prompt parameter.
    Callers pass SCENE_NEGATIVE_PROMPT for scene pages to penalise
    portrait/close-up composition. Canonical generation passes None
    (falls back to NEGATIVE_PROMPT) to allow portrait output.
    """
    neg = negative_prompt if negative_prompt is not None else NEGATIVE_PROMPT

    logger.info("===================================================")
    logger.info("REPLICATE CALL")
    logger.info("===================================================")
    logger.info(f"Model : {REPLICATE_MODEL}")
    logger.info(f"Seed  : {seed}")
    logger.info(f"Prompt: {prompt[:120]}...")

    fh = open(face_crop_path, "rb")
    try:
        output = replicate.run(
            REPLICATE_MODEL,
            input={
                "image"                         : fh,
                "prompt"                        : prompt,
                "negative_prompt"               : neg,
                "sdxl_weights"                  : SDXL_WEIGHTS,
                "ip_adapter_scale"              : IP_ADAPTER_SCALE,
                "controlnet_conditioning_scale" : CONTROLNET_SCALE,
                "width"                         : IMAGE_WIDTH,
                "height"                        : IMAGE_HEIGHT,
                "num_inference_steps"           : NUM_INFERENCE_STEPS,
                "guidance_scale"                : GUIDANCE_SCALE,
                "seed"                          : seed,
                "disable_safety_checker"        : False,
            },
        )
    finally:
        fh.close()

    return output


# ============================================================
# STAGE 2 -- CANONICAL CHARACTER GENERATION
# ============================================================

def generate_canonical_character(
    face_crop_path, reference_embedding, name, analyzer, logger,
    character_description="",
):
    """
    v2.1.0: Added character_description parameter; passes to
    _build_canonical_prompt() so identity anchors are included
    in the portrait prompt text.
    """
    logger.info("===================================================")
    logger.info("STAGE 2 -- Canonical character generation")
    logger.info("===================================================")

    canonical_prompt = _build_canonical_prompt(character_description)

    best_score = 0.0
    best_path  = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"Canonical attempt {attempt}/{MAX_RETRIES}")

        seed        = BASE_SEED + attempt
        output_path = OUTPUT_DIR / f"{name}_canonical_attempt_{attempt}.png"

        output = call_instantid(face_crop_path, canonical_prompt, seed, logger)
        save_output_image(output, output_path, logger)

        score, passed = verify_identity(
            output_path, reference_embedding,
            SIMILARITY_THRESHOLD_CANONICAL, analyzer, logger
        )

        if score > best_score:
            best_score = score
            best_path  = output_path

        if passed:
            logger.info("Canonical threshold satisfied")
            break
    else:
        logger.warning(
            f"Canonical generation did not reach threshold {SIMILARITY_THRESHOLD_CANONICAL:.2f} "
            f"after {MAX_RETRIES} attempts (best={best_score:.4f}). "
            "Proceeding with best available."
        )

    canonical_path = OUTPUT_DIR / f"{name}_canonical_character.png"
    shutil.copy(best_path, canonical_path)
    logger.info(f"Canonical saved: {canonical_path}  (score={best_score:.4f})")

    return canonical_path


# ============================================================
# STAGE 4 -- FACE SWAP FALLBACK
# ============================================================

def face_swap_fallback(scene_path, face_crop_path, name, page_idx, analyzer, logger):
    logger.info("---------------------------------------------------")
    logger.info(f"STAGE 4 -- Face swap fallback  (page {page_idx})")
    logger.info("---------------------------------------------------")

    if not _INSIGHTFACE_OK:
        logger.error("insightface not available -- fallback skipped, returning best attempt")
        return scene_path

    try:
        swapper = insightface.model_zoo.get_model(
            "inswapper_128",
            root=INSIGHTFACE_ROOT,
            providers=["CPUExecutionProvider"],
            download=False,
        )
    except Exception as exc:
        logger.error(f"Could not load inswapper_128: {exc}")
        return scene_path

    scene_img = cv2.imread(str(scene_path))
    src_img   = cv2.imread(str(face_crop_path))

    if scene_img is None or src_img is None:
        logger.error("Failed to load images for face swap -- returning best attempt")
        return scene_path

    scene_faces = analyzer.get(scene_img)
    src_faces   = analyzer.get(src_img)

    if not scene_faces:
        logger.warning("No face detected in scene image -- skipping swap")
        return scene_path

    if not src_faces:
        logger.warning("No face detected in source crop -- skipping swap")
        return scene_path

    target_face = sorted(
        scene_faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
    )[-1]

    source_face = sorted(
        src_faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
    )[-1]

    result = swapper.get(scene_img, target_face, source_face, paste_back=True)

    swapped_path = OUTPUT_DIR / f"{name}_page_{page_idx}_swapped.png"
    cv2.imwrite(str(swapped_path), result)
    logger.info(f"Face swap complete: {swapped_path}")

    return swapped_path


# ============================================================
# STAGE 3 -- PER-PAGE SCENE GENERATION
# ============================================================

def generate_page(
    page_idx,
    page,
    face_crop_path,
    reference_embedding,
    name,
    analyzer,
    logger,
    character_description="",
):
    """
    v2.1.0: Added character_description parameter; passes to
    build_scene_prompt() and uses SCENE_NEGATIVE_PROMPT (not
    NEGATIVE_PROMPT) to penalise portrait/close-up composition.
    """
    logger.info("===================================================")
    logger.info(f"STAGE 3 -- Page {page_idx}")
    logger.info("===================================================")

    page_prompt  = page.get("prompt", "")
    scene_prompt = build_scene_prompt(page_prompt, character_description)

    best_score = 0.0
    best_path  = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"Page {page_idx} attempt {attempt}/{MAX_RETRIES}")

        seed        = BASE_SEED + (page_idx * 100) + (attempt * 10)
        output_path = OUTPUT_DIR / f"{name}_page_{page_idx}_attempt_{attempt}.png"

        output = call_instantid(
            face_crop_path, scene_prompt, seed, logger,
            negative_prompt=SCENE_NEGATIVE_PROMPT,
        )
        save_output_image(output, output_path, logger)

        score, passed = verify_identity(
            output_path, reference_embedding,
            SIMILARITY_THRESHOLD_PAGE, analyzer, logger
        )

        if score > best_score:
            best_score = score
            best_path  = output_path

        if passed:
            logger.info(f"Page {page_idx} threshold satisfied on attempt {attempt}")
            break
    else:
        logger.warning(
            f"Page {page_idx}: all {MAX_RETRIES} attempts below threshold "
            f"{SIMILARITY_THRESHOLD_PAGE:.2f} (best={best_score:.4f}) -- "
            "triggering face swap fallback"
        )
        best_path = face_swap_fallback(
            best_path, face_crop_path, name, page_idx, analyzer, logger
        )

    # Stage 5 -- final verification and commit
    logger.info("---------------------------------------------------")
    logger.info(f"STAGE 5 -- Final verification  (page {page_idx})")
    logger.info("---------------------------------------------------")

    final_score, _ = verify_identity(
        best_path, reference_embedding,
        SIMILARITY_THRESHOLD_PAGE, analyzer, logger
    )

    final_path = OUTPUT_DIR / f"{name}_page_{page_idx}.png"
    shutil.copy(best_path, final_path)

    logger.info(f"Page {page_idx} committed: {final_path}  (final_score={final_score:.4f})")
    logger.info(f"Best similarity: {best_score:.4f}")

    return final_path


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Input folder name under input/")
    args = parser.parse_args()

    logger = setup_logger(args.name)

    try:
        # -- Environment --------------------------------------
        load_env(logger)

        # -- Dependency check ---------------------------------
        if cv2 is None:
            raise RuntimeError(
                "opencv-python not installed.\n"
                "Run: pip install opencv-python"
            )
        if not _INSIGHTFACE_OK:
            raise RuntimeError(
                "insightface not installed.\n"
                "Run: pip install insightface onnxruntime"
            )

        # -- Model download -----------------------------------
        ensure_inswapper_model(logger)

        # -- Input --------------------------------------------
        pages, original_image, character_description = load_story_input(args.name, logger)

        # -- InsightFace analyzer -----------------------------
        analyzer = build_analyzer(logger)

        # -- Stage 1: Identity extraction ---------------------
        reference_embedding, face_crop_path = extract_face_identity(
            original_image, args.name, analyzer, logger
        )

        # -- Stage 2: Canonical character ---------------------
        generate_canonical_character(
            face_crop_path, reference_embedding, args.name, analyzer, logger,
            character_description=character_description,
        )

        # -- Stages 3-5: Per-page generation ------------------
        for page_idx, page in enumerate(pages, start=1):
            generate_page(
                page_idx,
                page,
                face_crop_path,
                reference_embedding,
                args.name,
                analyzer,
                logger,
                character_description=character_description,
            )

        logger.info("===================================================")
        logger.info("ALL PAGES GENERATED SUCCESSFULLY")
        logger.info("===================================================")

    except Exception:
        logger.exception("PIPELINE FAILED")
        raise


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()

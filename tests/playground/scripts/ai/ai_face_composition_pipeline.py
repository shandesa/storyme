# ============================================================
# File:
# ai_face_composition_pipeline.py
#
# Design reference:
# tests/playground/scripts/ai/notes/ai_identity_scene_consistency_v2.pdf
#
# Purpose:
# Composes a personalised storybook by placing a cartoonised
# version of the user's face into pre-generated scene images
# that contain an oval face placeholder.
#
# Pipeline stages:
#   Phase 0 -- Avatar generation (once per user, cached)
#   Phase 1 -- Manifest + scene loading
#   Phase 2 -- Oval placeholder detection (CPU, deterministic)
#   Phase 3 -- Face pose interpretation (metadata + keyword)
#   Phase 4 -- Styled face generation (GPU via Replicate)
#              + face blending into scene (CPU, seamlessClone)
#   Phase 5 -- Composite validation (ArcFace similarity gate)
#
# ============================================================
# VERSION HISTORY
# ============================================================
#
# v1.0.0  2026-05-15  Initial implementation
#   - Complete pipeline from user photo to composed book pages
#   - Phase 0: InsightFace buffalo_l + InstantID avatar generation
#     with Azure Blob / local file avatar caching
#   - Phase 2: OpenCV LAB color segmentation + ellipse fitting
#     for deterministic oval detection
#   - Phase 3: Dual-source pose: manifest metadata (priority)
#     + scene prompt keyword lookup table (fills missing axes)
#   - Phase 4: GenerationBackend abstraction for model-agnostic
#     face generation; ReplicateInstantIDBackend implementation;
#     2D affine pose warp (pitch/yaw/roll); LAB color matching;
#     cv2.seamlessClone face-into-scene blending
#   - Phase 5: ArcFace cosine similarity gate; fail escalates
#     to logged warning; best attempt always committed
#   - Deterministic seed: sha256(user_id:story_id:page_idx)
#   - Backend swap: subclass GenerationBackend and pass to
#     FaceCompositionPipeline; no other changes needed
#
# ============================================================
# USER CHECKLIST -- THINGS TO DO BEFORE RUNNING
# ============================================================
#
# [1] STORY INPUT FOLDER
#     Create folder: tests/playground/input/{name}/stories/{story_id}/
#     Place scene images in: .../stories/{story_id}/scenes/
#     Scene images must contain an oval placeholder (flat solid
#     colour on the face region -- no texture, no gradient).
#     Scene images must be fully rendered storybook illustrations
#     with the generic child body already present.
#
# [2] MANIFEST FILE
#     Create: .../stories/{story_id}/manifest.json
#     See MANIFEST FORMAT section below for the exact schema.
#     Key fields you must fill:
#       - "oval_color_lab": [L, A, B] -- the LAB colour of the
#         placeholder oval in all scene images. Measure this
#         from any scene image using an image editor or the
#         helper script below. Must be consistent across all
#         pages in the story.
#       - "oval_color_tolerance": integer (default 30) --
#         how much LAB distance is allowed for oval detection.
#         Increase if detection misses the oval; decrease if
#         it detects false positives.
#       - "style_hint": the text style description matching
#         the art style of the scene images. Used as the prompt
#         for face generation so the face matches the scenes.
#       - "face_pose" per page: optional but strongly recommended
#         for correct head orientation. If absent, pose is
#         inferred from the scene_prompt keyword table.
#
# [3] MEASURE OVAL COLOR (one-time per scene set)
#     Run this helper to get the LAB values of the oval:
#       python -c "
#       import cv2, numpy as np
#       img = cv2.imread('path/to/page_01_scene.png')
#       lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
#       # Click on oval pixel in image viewer, note x,y
#       x, y = 300, 200  # replace with actual oval pixel coords
#       print('LAB:', lab[y, x].tolist())
#       "
#
# [4] ENV FILE
#     tests/playground/env must contain:
#       REPLICATE_KEY=r8_...
#     Optionally for Azure avatar caching:
#       AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=...
#       AZURE_AVATAR_CONTAINER=storyme-avatars
#
# [5] DEPENDENCIES
#     pip install insightface onnxruntime opencv-python
#              numpy requests replicate
#     Optional (Azure cache): pip install azure-storage-blob
#                                          azure-data-tables
#
# [6] AZURE BLOB CONTAINER (production only)
#     Create container: storyme-avatars (private access)
#     Same Azure region as App Service to avoid egress charges.
#     In playground mode (no Azure env vars), avatars are cached
#     locally at: tests/playground/cache/{user_id}/
#
# [7] RUN COMMAND
#     python ai_face_composition_pipeline.py \
#       --name nikshay \
#       --story jungle_adventure_v1
#
# ============================================================
# MANIFEST FORMAT
# ============================================================
#
# {story_id}/manifest.json must follow this exact schema:
#
# {
#   "story_id": "jungle_adventure_v1",
#   "style_hint": "children's storybook illustration, semi-realistic
#     digital painting, warm soft cinematic lighting",
#   "oval_color_lab": [85, 128, 128],
#   "oval_color_tolerance": 30,
#   "pages": [
#     {
#       "page_idx": 1,
#       "scene_image": "page_01_scene.png",
#       "scene_prompt": "A child enters a glowing jungle with curiosity",
#       "has_character": true,
#       "face_pose": { "yaw": -8, "pitch": -5, "roll": 0 }
#     },
#     {
#       "page_idx": 2,
#       "scene_image": "page_02_scene.png",
#       "scene_prompt": "Ancient jungle at dusk, fireflies in the air",
#       "has_character": false
#     }
#   ]
# }
#
# face_pose is optional per page. When absent, pose is derived
# from the scene_prompt keyword table (see PoseInterpreter).
# When provided, metadata values take priority over keywords.
# Provide at least "yaw" and "pitch" for best results.
#
# ============================================================

import argparse
import hashlib
import json
import logging
import math
import os
import pickle
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import requests

try:
    import replicate
    _REPLICATE_OK = True
except ImportError:
    replicate = None
    _REPLICATE_OK = False

try:
    import insightface
    from insightface.app import FaceAnalysis
    from insightface.utils import face_align as _face_align
    _INSIGHTFACE_OK = True
except ImportError:
    insightface = None
    FaceAnalysis = None
    _face_align = None
    _INSIGHTFACE_OK = False

try:
    from azure.storage.blob import BlobServiceClient
    _AZURE_BLOB_OK = True
except ImportError:
    BlobServiceClient = None
    _AZURE_BLOB_OK = False


# ============================================================
# CONFIG
# ============================================================

# ---- Replicate model ----------------------------------------
# To switch to a different model: subclass GenerationBackend
# and override generate_face(). No other changes needed.
REPLICATE_MODEL_ID = (
    "zsxkib/instant-id"
    ":c98b2e7a196828d00955767813b81fc05c5c9b294c670c6d147d545fed4ceecf"
)
SDXL_WEIGHTS            = "protovision-xl-high-fidel"

# ---- Generation parameters ----------------------------------
# Avatar (Phase 0): maximum identity lock for reference portrait.
AVATAR_IP_SCALE         = 0.95
AVATAR_CN_SCALE         = 0.90
AVATAR_GUIDANCE         = 5.0
AVATAR_STEPS            = 40

# Face generation (Phase 4 GPU): lower IP scale so the style
# prompt and pose text drive the output alongside identity.
FACE_IP_SCALE           = 0.80
FACE_CN_SCALE           = 0.75
FACE_GUIDANCE           = 6.5
FACE_STEPS              = 35
FACE_IMAGE_SIZE         = 512    # face portrait is square 512x512

# ---- Validation ---------------------------------------------
ARCFACE_THRESHOLD_AVATAR = 0.40  # Phase 0 canonical gate
ARCFACE_THRESHOLD_PAGE   = 0.30  # Phase 5 composite gate
#   Lower than v2 pipeline because cross-domain (real → cartoon
#   → blended into scene) introduces additional similarity loss.

# ---- Blend --------------------------------------------------
# Fraction of LAB color shift to apply (0.0 = no shift, 1.0 = full)
COLOR_MATCH_STRENGTH    = 0.65
SEAM_CLONE_FLAGS        = cv2.NORMAL_CLONE

# ---- Paths --------------------------------------------------
PLAYGROUND_DIR   = Path(__file__).resolve().parents[2]
INPUT_DIR        = PLAYGROUND_DIR / "input"
OUTPUT_DIR       = PLAYGROUND_DIR / "output" / "face_composition"
LOG_DIR          = PLAYGROUND_DIR / "output" / "logs" / "face_composition"
CACHE_DIR        = PLAYGROUND_DIR / "cache"
ENV_FILE         = PLAYGROUND_DIR / "env"
INSIGHTFACE_ROOT = str(PLAYGROUND_DIR)

for _d in [OUTPUT_DIR, LOG_DIR, CACHE_DIR]:
    _d.mkdir(parents=True, exist_ok=True)


# ============================================================
# POSE KEYWORD TABLE
# ============================================================
# Maps scene prompt keywords to default yaw/pitch/roll degrees.
# Metadata in manifest takes priority over these defaults.
# Extend this table as more scene types are added to the story
# repository. Values are in degrees; positive pitch = head down,
# negative pitch = head up; positive yaw = face right.

POSE_KEYWORD_TABLE = [
    # (keyword_list, yaw, pitch, roll)
    (["looking up", "gazing up", "staring up", "glancing upward"],        0, -25,  0),
    (["looking down", "gazing down", "staring down", "looking at floor"], 0,  20,  0),
    (["looking left", "glancing left", "turning left"],                  -22,   0,  0),
    (["looking right", "glancing right", "turning right"],                22,   0,  0),
    (["turning around", "looking back", "glancing back"],                 40,   0,  0),
    (["running", "sprinting"],                                            -8,  -8,  0),
    (["jumping", "leaping"],                                               0, -12,  5),
    (["sitting", "seated", "sitting down"],                                0,  10,  0),
    (["entering", "walking into", "stepping into"],                       -6,  -4,  0),
    (["waving", "waving hand"],                                            8,   0,  0),
    (["smiling", "laughing", "giggling"],                                  0,   0,  0),
    (["surprised", "amazed", "astonished"],                                0, -10,  0),
    (["scared", "afraid", "frightened"],                                   0,  -5,  3),
    (["sleeping", "asleep", "resting"],                                    0,  15,  15),
    (["reading", "reading book"],                                          0,  18,  0),
]

# ============================================================
# NEGATIVE PROMPTS
# ============================================================

AVATAR_NEGATIVE = (
    "realistic photography, photorealistic, ugly, deformed face, "
    "extra limbs, adult, elderly, blurry, watermark, text"
)

FACE_NEGATIVE = (
    "ugly, deformed, distorted, blurry, low quality, extra limbs, "
    "adult face, elderly, watermark, logo, text, body, torso, shoulders, "
    "background scene, plain background, white background"
)


# ============================================================
# EXCEPTIONS
# ============================================================

class OvalNotFoundError(RuntimeError):
    pass

class FaceNotDetectedError(RuntimeError):
    pass

class AvatarGenerationError(RuntimeError):
    pass


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class OvalInfo:
    center:   tuple          # (cx, cy) in scene image pixels
    axes:     tuple          # (half_major, half_minor)
    angle:    float          # rotation of ellipse in degrees
    mask:     np.ndarray     # uint8 mask, 255 inside oval
    ellipse:  tuple          # raw cv2.fitEllipse result


@dataclass
class FacePose:
    yaw_deg:   float = 0.0   # positive = face turns right
    pitch_deg: float = 0.0   # positive = head tilts down
    roll_deg:  float = 0.0   # positive = head tilts right shoulder


@dataclass
class AvatarData:
    avatar_path:    Path
    embedding:      np.ndarray   # ArcFace 512-dim L2-normalised
    face_crop_path: Path


@dataclass
class PageResult:
    page_idx:      int
    output_path:   Path
    arcface_score: float
    passed:        bool
    method:        str       # "cpu" or "gpu"


# ============================================================
# GENERATION BACKEND ABSTRACTION
# ============================================================
# To switch from Replicate to any other backend:
#   1. Subclass GenerationBackend
#   2. Override generate_face()
#   3. Pass your class instance to FaceCompositionPipeline
# Nothing else in the pipeline changes.

class GenerationBackend(ABC):
    """
    Abstract face generation backend.
    Generates a styled face portrait from a reference face image.
    Returns path to the generated face image (PNG, square).
    """

    @abstractmethod
    def generate_face(
        self,
        reference_path: Path,
        prompt: str,
        negative_prompt: str,
        seed: int,
        width: int,
        height: int,
        ip_adapter_scale: float,
        controlnet_scale: float,
        guidance_scale: float,
        num_inference_steps: int,
        output_path: Path,
        logger: logging.Logger,
    ) -> Path:
        raise NotImplementedError

    @abstractmethod
    def generate_avatar(
        self,
        reference_path: Path,
        prompt: str,
        negative_prompt: str,
        seed: int,
        output_path: Path,
        logger: logging.Logger,
    ) -> Path:
        raise NotImplementedError


class ReplicateInstantIDBackend(GenerationBackend):
    """
    Replicate backend using zsxkib/instant-id.
    To swap model: change MODEL_ID and adjust input keys if
    the new model uses different parameter names.
    """

    MODEL_ID  = REPLICATE_MODEL_ID
    SDXL      = SDXL_WEIGHTS

    def _save_output(self, output, output_path: Path, logger: logging.Logger) -> Path:
        if isinstance(output, list):
            output = output[0]
        if hasattr(output, "read"):
            with open(output_path, "wb") as f:
                f.write(output.read())
        elif hasattr(output, "url"):
            r = requests.get(output.url, timeout=120)
            r.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(r.content)
        elif isinstance(output, str) and output.startswith("http"):
            r = requests.get(output, timeout=120)
            r.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(r.content)
        else:
            raise RuntimeError(f"Unrecognised output type: {type(output)}")
        logger.info(f"Saved: {output_path}")
        return output_path

    def generate_avatar(
        self,
        reference_path: Path,
        prompt: str,
        negative_prompt: str,
        seed: int,
        output_path: Path,
        logger: logging.Logger,
    ) -> Path:
        logger.info("===================================================")
        logger.info("BACKEND: generate_avatar (Replicate InstantID)")
        logger.info("===================================================")
        logger.info(f"Model   : {self.MODEL_ID}")
        logger.info(f"SDXL    : {self.SDXL}")
        logger.info(f"Seed    : {seed}")
        logger.info(f"Ref img : {reference_path}")
        logger.info("-- PROMPT --")
        for line in prompt.splitlines():
            logger.info(f"  {line}")
        logger.info("-- NEGATIVE --")
        logger.info(f"  {negative_prompt}")
        logger.info("===================================================")

        with open(reference_path, "rb") as fh:
            output = replicate.run(
                self.MODEL_ID,
                input={
                    "image"                         : fh,
                    "prompt"                        : prompt,
                    "negative_prompt"               : negative_prompt,
                    "sdxl_weights"                  : self.SDXL,
                    "ip_adapter_scale"              : AVATAR_IP_SCALE,
                    "controlnet_conditioning_scale" : AVATAR_CN_SCALE,
                    "width"                         : 512,
                    "height"                        : 512,
                    "num_inference_steps"           : AVATAR_STEPS,
                    "guidance_scale"                : AVATAR_GUIDANCE,
                    "seed"                          : seed,
                    "disable_safety_checker"        : False,
                },
            )
        return self._save_output(output, output_path, logger)

    def generate_face(
        self,
        reference_path: Path,
        prompt: str,
        negative_prompt: str,
        seed: int,
        width: int,
        height: int,
        ip_adapter_scale: float,
        controlnet_scale: float,
        guidance_scale: float,
        num_inference_steps: int,
        output_path: Path,
        logger: logging.Logger,
    ) -> Path:
        logger.info("===================================================")
        logger.info("BACKEND: generate_face (Replicate InstantID)")
        logger.info("===================================================")
        logger.info(f"Model              : {self.MODEL_ID}")
        logger.info(f"SDXL               : {self.SDXL}")
        logger.info(f"Seed               : {seed}")
        logger.info(f"ip_adapter_scale   : {ip_adapter_scale}")
        logger.info(f"controlnet_scale   : {controlnet_scale}")
        logger.info(f"guidance_scale     : {guidance_scale}")
        logger.info(f"num_inference_steps: {num_inference_steps}")
        logger.info(f"Output size        : {width}x{height}")
        logger.info(f"Ref img            : {reference_path}")
        logger.info("-- FULL PROMPT --")
        for line in prompt.splitlines():
            logger.info(f"  {line}")
        logger.info("-- FULL NEGATIVE --")
        for line in negative_prompt.splitlines():
            logger.info(f"  {line}")
        logger.info("===================================================")

        with open(reference_path, "rb") as fh:
            output = replicate.run(
                self.MODEL_ID,
                input={
                    "image"                         : fh,
                    "prompt"                        : prompt,
                    "negative_prompt"               : negative_prompt,
                    "sdxl_weights"                  : self.SDXL,
                    "ip_adapter_scale"              : ip_adapter_scale,
                    "controlnet_conditioning_scale" : controlnet_scale,
                    "width"                         : width,
                    "height"                        : height,
                    "num_inference_steps"           : num_inference_steps,
                    "guidance_scale"                : guidance_scale,
                    "seed"                          : seed,
                    "disable_safety_checker"        : False,
                },
            )
        return self._save_output(output, output_path, logger)


# ============================================================
# AVATAR CACHE
# ============================================================

class AvatarCache:
    """
    Manages avatar storage.
    Playground mode (no Azure env vars): local CACHE_DIR.
    Production mode (Azure env vars present): Azure Blob Storage.
    """

    def __init__(self, logger: logging.Logger):
        self.logger    = logger
        self._conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        self._container = os.environ.get("AZURE_AVATAR_CONTAINER", "storyme-avatars")
        self._use_azure = bool(self._conn_str and _AZURE_BLOB_OK)
        mode = "Azure Blob" if self._use_azure else "local filesystem"
        logger.info(f"AvatarCache mode: {mode}")

    def _local_dir(self, user_id: str) -> Path:
        d = CACHE_DIR / user_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def exists(self, user_id: str) -> bool:
        if self._use_azure:
            try:
                client = BlobServiceClient.from_connection_string(self._conn_str)
                cc = client.get_container_client(self._container)
                cc.get_blob_client(f"{user_id}/avatar.png").get_blob_properties()
                return True
            except Exception:
                return False
        else:
            return (self._local_dir(user_id) / "avatar.png").exists()

    def load(self, user_id: str) -> tuple:
        """Returns (avatar_path, embedding_path) as local Paths."""
        local_dir = self._local_dir(user_id)
        avatar_path    = local_dir / "avatar.png"
        embedding_path = local_dir / "embedding.pkl"
        crop_path      = local_dir / "face_crop.png"

        if self._use_azure:
            client = BlobServiceClient.from_connection_string(self._conn_str)
            cc = client.get_container_client(self._container)
            for blob_name, local_path in [
                (f"{user_id}/avatar.png",    avatar_path),
                (f"{user_id}/embedding.pkl", embedding_path),
                (f"{user_id}/face_crop.png", crop_path),
            ]:
                with open(local_path, "wb") as f:
                    f.write(cc.download_blob(blob_name).readall())
        # local mode: files already in local_dir from prior save

        embedding = pickle.load(open(embedding_path, "rb"))
        return avatar_path, embedding_path, embedding, crop_path

    def save(
        self,
        user_id: str,
        avatar_path: Path,
        embedding: np.ndarray,
        crop_path: Path,
    ):
        local_dir      = self._local_dir(user_id)
        local_avatar   = local_dir / "avatar.png"
        local_emb      = local_dir / "embedding.pkl"
        local_crop     = local_dir / "face_crop.png"

        shutil.copy(avatar_path, local_avatar)
        shutil.copy(crop_path,   local_crop)
        with open(local_emb, "wb") as f:
            pickle.dump(embedding, f)

        if self._use_azure:
            client = BlobServiceClient.from_connection_string(self._conn_str)
            cc = client.get_container_client(self._container)
            for blob_name, local_path in [
                (f"{user_id}/avatar.png",    local_avatar),
                (f"{user_id}/embedding.pkl", local_emb),
                (f"{user_id}/face_crop.png", local_crop),
            ]:
                with open(local_path, "rb") as f:
                    cc.upload_blob(blob_name, f, overwrite=True)
            self.logger.info(f"Avatar saved to Azure Blob: {self._container}/{user_id}/")
        else:
            self.logger.info(f"Avatar saved locally: {local_dir}/")


# ============================================================
# LOGGER
# ============================================================

def setup_logger(name: str, story_id: str) -> logging.Logger:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file  = LOG_DIR / f"{name}_{story_id}_{timestamp}.log"

    logger = logging.getLogger(f"{name}_{story_id}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh  = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    ch  = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info("===================================================")
    logger.info("AI Face Composition Pipeline v1.0.0")
    logger.info("===================================================")
    logger.info(f"User     : {name}")
    logger.info(f"Story    : {story_id}")
    logger.info(f"Log file : {log_file}")
    return logger


# ============================================================
# ENV
# ============================================================

def load_env(logger: logging.Logger):
    logger.info(f"Loading env: {ENV_FILE}")
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
        raise RuntimeError("REPLICATE_KEY missing in env file")
    os.environ["REPLICATE_API_TOKEN"] = token
    logger.info("REPLICATE_API_TOKEN loaded")


# ============================================================
# MANIFEST LOADING
# ============================================================

def load_manifest(story_dir: Path, logger: logging.Logger) -> dict:
    manifest_path = story_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json missing: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    required = ["story_id", "style_hint", "oval_color_lab", "pages"]
    for key in required:
        if key not in data:
            raise ValueError(f"manifest.json missing required field: '{key}'")

    logger.info(f"Manifest loaded: story_id={data['story_id']}")
    logger.info(f"Style hint     : {data['style_hint']}")
    logger.info(f"Oval color LAB : {data['oval_color_lab']}")
    logger.info(f"Tolerance      : {data.get('oval_color_tolerance', 30)}")
    logger.info(f"Total pages    : {len(data['pages'])}")

    char_pages = [p["page_idx"] for p in data["pages"] if p.get("has_character")]
    logger.info(f"Character pages: {char_pages}")
    return data


# ============================================================
# DETERMINISTIC SEED
# ============================================================

def make_seed(user_id: str, story_id: str, page_idx: int) -> int:
    """
    Produces a deterministic, reproducible seed from inputs.
    Same user + same story + same page = same seed = same output.
    """
    raw  = f"{user_id}:{story_id}:{page_idx}"
    hx   = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return int(hx, 16) % (2**31)   # keep within signed int range


# ============================================================
# INSIGHTFACE ANALYZER
# ============================================================

def build_analyzer(logger: logging.Logger) -> "FaceAnalysis":
    if not _INSIGHTFACE_OK:
        raise RuntimeError(
            "insightface not installed.\n"
            "Run: pip install insightface onnxruntime"
        )
    logger.info("Initialising InsightFace buffalo_l...")
    app = FaceAnalysis(
        name="buffalo_l",
        root=INSIGHTFACE_ROOT,
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    logger.info("InsightFace ready")
    return app


def extract_face(
    image_path: Path,
    analyzer: "FaceAnalysis",
    logger: logging.Logger,
) -> tuple:
    """
    Returns (normed_embedding, aligned_112x112_array, padded_crop_path).
    Raises FaceNotDetectedError if no face found.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise RuntimeError(f"Cannot load image: {image_path}")

    faces = analyzer.get(img)
    if not faces:
        raise FaceNotDetectedError(
            f"No face detected in: {image_path}\n"
            "Ensure the photo has a clearly visible, well-lit frontal face."
        )

    face = sorted(
        faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
    )[-1]

    logger.info(f"Face detected -- bbox: {[int(v) for v in face.bbox]}")
    embedding = face.normed_embedding.copy()
    logger.info(f"ArcFace embedding: shape={embedding.shape}")

    aligned = _face_align.norm_crop(img, face.kps, image_size=112)

    # Padded crop for InstantID reference (35% padding)
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    ih, iw = img.shape[:2]
    px = int((x2 - x1) * 0.35)
    py = int((y2 - y1) * 0.35)
    cx1 = max(0, x1 - px); cy1 = max(0, y1 - py)
    cx2 = min(iw, x2 + px); cy2 = min(ih, y2 + py)
    padded = img[cy1:cy2, cx1:cx2]

    return embedding, aligned, padded


def arcface_similarity(
    embedding_ref: np.ndarray,
    image_path: Path,
    analyzer: "FaceAnalysis",
    logger: logging.Logger,
) -> tuple:
    """
    Returns (similarity_float, face_bbox_or_None).
    Both embeddings are L2-normalised -> cosine sim = dot product.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        logger.warning(f"Cannot load image for similarity check: {image_path}")
        return 0.0, None

    faces = analyzer.get(img)
    if not faces:
        logger.warning("No face detected in generated image")
        return 0.0, None

    face = sorted(
        faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
    )[-1]

    bbox = [int(v) for v in face.bbox]
    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    sim  = float(np.dot(embedding_ref, face.normed_embedding))

    logger.info(f"ArcFace -- bbox: {bbox}  area={area}px²  sim={sim:.4f}")
    return sim, bbox


# ============================================================
# PHASE 0: AVATAR GENERATION
# ============================================================

def phase0_generate_avatar(
    user_id: str,
    user_image_path: Path,
    style_hint: str,
    backend: GenerationBackend,
    cache: AvatarCache,
    analyzer: "FaceAnalysis",
    out_dir: Path,
    logger: logging.Logger,
) -> AvatarData:
    """
    Generates and caches a cartoonised avatar from the user photo.
    If cache hit: loads from cache and returns immediately.
    If cache miss: runs InsightFace + InstantID, saves to cache.
    """
    logger.info("===================================================")
    logger.info("PHASE 0 -- Avatar generation")
    logger.info("===================================================")

    if cache.exists(user_id):
        logger.info(f"Cache HIT for user_id={user_id} -- loading avatar")
        avatar_path, emb_path, embedding, crop_path = cache.load(user_id)
        logger.info(f"Avatar loaded from cache: {avatar_path}")
        return AvatarData(
            avatar_path=avatar_path,
            embedding=embedding,
            face_crop_path=crop_path,
        )

    logger.info(f"Cache MISS for user_id={user_id} -- generating avatar")

    # Extract face from user photo
    embedding, aligned, padded_crop = extract_face(user_image_path, analyzer, logger)

    crop_path = out_dir / f"{user_id}_reference_crop.png"
    cv2.imwrite(str(crop_path), padded_crop)
    logger.info(f"Reference crop saved: {crop_path}")

    # Build avatar generation prompt
    avatar_prompt = (
        f"{style_hint}, "
        "same child, same face, same eyes, same skin tone, same hair, "
        "front-facing portrait, gentle smile, face clearly visible, "
        "looking at camera, full upper body, soft even lighting"
    )

    seed = make_seed(user_id, "avatar", 0)
    avatar_out = out_dir / f"{user_id}_avatar.png"

    avatar_path = backend.generate_avatar(
        reference_path=crop_path,
        prompt=avatar_prompt,
        negative_prompt=AVATAR_NEGATIVE,
        seed=seed,
        output_path=avatar_out,
        logger=logger,
    )

    # Validate avatar similarity
    sim, _ = arcface_similarity(embedding, avatar_path, analyzer, logger)
    logger.info(
        f"Avatar ArcFace similarity: {sim:.4f}  "
        f"threshold: {ARCFACE_THRESHOLD_AVATAR:.2f}  "
        f"{'PASS' if sim >= ARCFACE_THRESHOLD_AVATAR else 'WARN -- proceeding'}"
    )

    cache.save(user_id, avatar_path, embedding, crop_path)

    return AvatarData(
        avatar_path=avatar_path,
        embedding=embedding,
        face_crop_path=crop_path,
    )


# ============================================================
# PHASE 2: OVAL DETECTION
# ============================================================

def phase2_detect_oval(
    scene_path: Path,
    oval_color_lab: list,
    tolerance: int,
    logger: logging.Logger,
) -> OvalInfo:
    """
    Detects the face placeholder oval in the scene image.
    Fully deterministic: same image + same color = same result.
    """
    logger.info(f"Phase 2 -- Oval detection: {scene_path.name}")

    img = cv2.imread(str(scene_path))
    if img is None:
        raise RuntimeError(f"Cannot load scene image: {scene_path}")

    h, w = img.shape[:2]

    # Convert to LAB and threshold for oval placeholder color
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lo  = np.array([
        max(0,   oval_color_lab[0] - tolerance),
        max(0,   oval_color_lab[1] - tolerance),
        max(0,   oval_color_lab[2] - tolerance),
    ], dtype=np.uint8)
    hi  = np.array([
        min(255, oval_color_lab[0] + tolerance),
        min(255, oval_color_lab[1] + tolerance),
        min(255, oval_color_lab[2] + tolerance),
    ], dtype=np.uint8)

    mask_raw = cv2.inRange(lab, lo, hi)

    # Morphological cleanup: remove small noise
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask_clean = cv2.morphologyEx(mask_raw, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(
        mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        raise OvalNotFoundError(
            f"No oval placeholder detected in: {scene_path.name}\n"
            f"oval_color_lab={oval_color_lab} tolerance={tolerance}\n"
            "Check USER CHECKLIST item [2] and [3] for color measurement."
        )

    # Largest contour = the oval
    largest = max(contours, key=cv2.contourArea)
    area    = cv2.contourArea(largest)

    if len(largest) < 5:
        raise OvalNotFoundError(
            f"Detected contour too small for ellipse fitting (area={area:.0f}px²).\n"
            "Increase oval_color_tolerance in manifest.json."
        )

    ellipse = cv2.fitEllipse(largest)
    cx, cy  = int(ellipse[0][0]), int(ellipse[0][1])
    ma, mb  = int(ellipse[1][0] / 2), int(ellipse[1][1] / 2)
    angle   = ellipse[2]

    oval_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(oval_mask, ellipse, 255, -1)

    logger.info(
        f"Oval detected -- center=({cx},{cy})  "
        f"axes=({ma},{mb})  angle={angle:.1f}°  "
        f"contour_area={area:.0f}px²"
    )

    return OvalInfo(
        center=(cx, cy),
        axes=(ma, mb),
        angle=angle,
        mask=oval_mask,
        ellipse=ellipse,
    )


# ============================================================
# PHASE 3: POSE INTERPRETATION
# ============================================================

def _pose_from_prompt(prompt_lower: str) -> FacePose:
    """Keyword scan; returns first match or default (0,0,0)."""
    for keywords, yaw, pitch, roll in POSE_KEYWORD_TABLE:
        if any(kw in prompt_lower for kw in keywords):
            return FacePose(yaw_deg=yaw, pitch_deg=pitch, roll_deg=roll)
    return FacePose()


def _pose_to_text(pose: FacePose) -> str:
    """Converts pose to a natural language description for the prompt."""
    parts = []
    if abs(pose.pitch_deg) > 5:
        parts.append("looking upward" if pose.pitch_deg < 0 else "looking slightly downward")
    if abs(pose.yaw_deg) > 8:
        parts.append("face turned slightly right" if pose.yaw_deg > 0 else "face turned slightly left")
    if abs(pose.roll_deg) > 5:
        parts.append("head tilted" + (" right" if pose.roll_deg > 0 else " left"))
    if not parts:
        parts.append("facing forward")
    return ", ".join(parts)


def phase3_interpret_pose(page: dict, logger: logging.Logger) -> FacePose:
    """
    Derives FacePose from:
    1. manifest face_pose metadata (priority per axis)
    2. scene_prompt keyword table (fills missing axes)
    """
    scene_prompt = page.get("scene_prompt", "")
    meta         = page.get("face_pose", {})

    prompt_pose = _pose_from_prompt(scene_prompt.lower())

    # Metadata overrides keyword on a per-axis basis
    yaw   = float(meta.get("yaw",   prompt_pose.yaw_deg))
    pitch = float(meta.get("pitch", prompt_pose.pitch_deg))
    roll  = float(meta.get("roll",  prompt_pose.roll_deg))

    pose = FacePose(yaw_deg=yaw, pitch_deg=pitch, roll_deg=roll)

    logger.info(
        f"Phase 3 -- Pose: yaw={pose.yaw_deg:.1f}°  "
        f"pitch={pose.pitch_deg:.1f}°  roll={pose.roll_deg:.1f}°  "
        f"(meta={'yes' if meta else 'no'}, prompt='{scene_prompt[:60]}')"
    )
    return pose


# ============================================================
# PHASE 4: FACE RENDERING
# ============================================================

def _apply_pose_warp(face_img: np.ndarray, pose: FacePose) -> np.ndarray:
    """
    Applies 2D affine approximation of 3D head pose.
    Roll  -> simple rotation.
    Pitch -> vertical foreshortening (compress height).
    Yaw   -> horizontal perspective warp (compress one side).
    """
    h, w = face_img.shape[:2]

    # Roll
    if abs(pose.roll_deg) > 1.0:
        M = cv2.getRotationMatrix2D((w / 2, h / 2), -pose.roll_deg, 1.0)
        face_img = cv2.warpAffine(
            face_img, M, (w, h),
            flags=cv2.INTER_LANCZOS4,
            borderMode=cv2.BORDER_REFLECT,
        )

    # Pitch: compress face vertically to simulate tilt
    if abs(pose.pitch_deg) > 2.0:
        scale_y = max(0.4, math.cos(math.radians(abs(pose.pitch_deg))))
        new_h   = max(10, int(h * scale_y))
        if pose.pitch_deg > 0:     # head down -- compress from top
            src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
            dst = np.float32([[0, h - new_h], [w, h - new_h], [w, h], [0, h]])
        else:                      # head up -- compress from bottom
            src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
            dst = np.float32([[0, 0], [w, 0], [w, new_h], [0, new_h]])
        M = cv2.getPerspectiveTransform(src, dst)
        face_img = cv2.warpPerspective(face_img, M, (w, h))

    # Yaw: perspective compress one horizontal side
    if abs(pose.yaw_deg) > 2.0:
        compress = max(0.3, math.cos(math.radians(abs(pose.yaw_deg))))
        new_w    = max(10, int(w * compress))
        if pose.yaw_deg > 0:       # face right -- compress left side
            src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
            mg  = w - new_w
            dst = np.float32([[mg, 0], [w, 0], [w, h], [mg, h]])
        else:                      # face left -- compress right side
            src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
            dst = np.float32([[0, 0], [new_w, 0], [new_w, h], [0, h]])
        M = cv2.getPerspectiveTransform(src, dst)
        face_img = cv2.warpPerspective(face_img, M, (w, h))

    return face_img


def _match_colors(
    face_img: np.ndarray,
    scene_img: np.ndarray,
    oval_mask: np.ndarray,
    margin: int = 50,
) -> np.ndarray:
    """
    Shifts face LAB color distribution toward the scene surroundings.
    Samples a ring of pixels outside the oval to get scene lighting.
    """
    kernel    = np.ones((margin, margin), np.uint8)
    dilated   = cv2.dilate(oval_mask, kernel)
    ring_mask = cv2.bitwise_and(dilated, cv2.bitwise_not(oval_mask))

    scene_lab = cv2.cvtColor(scene_img, cv2.COLOR_BGR2LAB).astype(np.float32)
    face_lab  = cv2.cvtColor(face_img,  cv2.COLOR_BGR2LAB).astype(np.float32)

    for ch in range(3):
        scene_vals = scene_lab[:, :, ch][ring_mask > 0]
        # Non-black face pixels only (avoid warped transparent regions)
        face_px    = face_lab[:, :, ch]
        face_vals  = face_px[face_px > 5]

        if len(scene_vals) == 0 or len(face_vals) == 0:
            continue

        shift = (np.mean(scene_vals) - np.mean(face_vals)) * COLOR_MATCH_STRENGTH
        face_lab[:, :, ch] = np.clip(face_lab[:, :, ch] + shift, 0, 255)

    return cv2.cvtColor(face_lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def phase4_render_and_blend(
    scene_path: Path,
    avatar: AvatarData,
    oval: OvalInfo,
    pose: FacePose,
    page: dict,
    style_hint: str,
    backend: GenerationBackend,
    user_id: str,
    story_id: str,
    page_idx: int,
    work_dir: Path,
    logger: logging.Logger,
) -> Path:
    """
    Phase 4: Generate a styled face portrait (GPU) then blend
    into the scene oval (CPU). Returns path to composed image.
    """
    logger.info("===================================================")
    logger.info(f"PHASE 4 -- Face rendering  (page {page_idx})")
    logger.info("===================================================")

    scene_img = cv2.imread(str(scene_path))
    if scene_img is None:
        raise RuntimeError(f"Cannot load scene image: {scene_path}")

    # Oval dimensions for face generation target size
    oval_w = oval.axes[0] * 2 + 40   # minor * 2 + small padding
    oval_h = oval.axes[1] * 2 + 40   # major * 2 + small padding
    face_w = max(FACE_IMAGE_SIZE, oval_w)
    face_h = max(FACE_IMAGE_SIZE, oval_h)

    pose_text = _pose_to_text(pose)
    scene_prompt_text = page.get("scene_prompt", "")

    face_prompt = (
        f"{style_hint}, "
        "same child, same face, same skin tone, same hair, same eyes, "
        f"portrait, {pose_text}, "
        "face and head only, face clearly visible, "
        "natural facial proportions, no body, no background, "
        "soft natural lighting matching the scene"
    )

    logger.info(f"Oval size (w×h)    : {oval_w}×{oval_h}px")
    logger.info(f"Face gen size      : {face_w}×{face_h}px")
    logger.info(f"Pose text          : {pose_text}")
    logger.info(f"Scene prompt       : {scene_prompt_text[:80]}")

    seed = make_seed(user_id, story_id, page_idx)

    # GPU: generate styled face portrait
    face_gen_path = work_dir / f"page_{page_idx:02d}_face_raw.png"
    backend.generate_face(
        reference_path=avatar.avatar_path,
        prompt=face_prompt,
        negative_prompt=FACE_NEGATIVE,
        seed=seed,
        width=face_w,
        height=face_h,
        ip_adapter_scale=FACE_IP_SCALE,
        controlnet_scale=FACE_CN_SCALE,
        guidance_scale=FACE_GUIDANCE,
        num_inference_steps=FACE_STEPS,
        output_path=face_gen_path,
        logger=logger,
    )

    # CPU: warp, color-match, blend into scene
    face_img = cv2.imread(str(face_gen_path))
    if face_img is None:
        raise RuntimeError(f"Failed to load generated face: {face_gen_path}")

    logger.info("CPU blend -- pose warp")
    face_warped = _apply_pose_warp(face_img, pose)

    # Resize to oval bounding box dimensions
    target_w = oval.axes[0] * 2
    target_h = oval.axes[1] * 2
    face_resized = cv2.resize(face_warped, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)

    # Save resized face for debug
    cv2.imwrite(str(work_dir / f"page_{page_idx:02d}_face_resized.png"), face_resized)

    logger.info("CPU blend -- LAB color matching")
    face_colored = _match_colors(face_resized, scene_img, oval.mask)

    # Place face_colored into a scene-sized canvas at oval position
    cx, cy = oval.center
    x1 = cx - oval.axes[0]
    y1 = cy - oval.axes[1]
    x2 = x1 + target_w
    y2 = y1 + target_h

    # Clamp to scene bounds
    x1c = max(0, x1); y1c = max(0, y1)
    x2c = min(scene_img.shape[1], x2); y2c = min(scene_img.shape[0], y2)

    canvas = scene_img.copy()
    src_x1 = x1c - x1; src_y1 = y1c - y1
    src_x2 = src_x1 + (x2c - x1c); src_y2 = src_y1 + (y2c - y1c)
    canvas[y1c:y2c, x1c:x2c] = face_colored[src_y1:src_y2, src_x1:src_x2]

    logger.info("CPU blend -- seamlessClone")
    # Build local mask for seamlessClone (local coords)
    local_mask = np.zeros((y2c - y1c, x2c - x1c), dtype=np.uint8)
    local_ellipse = (
        (oval.axes[0] - src_x1, oval.axes[1] - src_y1),
        (oval.axes[0] * 2 * 0.85, oval.axes[1] * 2 * 0.85),
        oval.angle,
    )
    cv2.ellipse(local_mask, local_ellipse, 255, -1)

    # seamlessClone works on the full scene canvas
    center_clone = (cx, cy)
    local_face_full = np.zeros_like(scene_img)
    local_face_full[y1c:y2c, x1c:x2c] = face_colored[src_y1:src_y2, src_x1:src_x2]
    full_mask = np.zeros(scene_img.shape[:2], dtype=np.uint8)
    full_mask[y1c:y2c, x1c:x2c] = local_mask

    try:
        composed = cv2.seamlessClone(
            local_face_full, scene_img, full_mask,
            center_clone, SEAM_CLONE_FLAGS,
        )
    except cv2.error as e:
        logger.warning(f"seamlessClone failed ({e}) -- using direct paste")
        composed = canvas

    composed_path = work_dir / f"page_{page_idx:02d}_composed.png"
    cv2.imwrite(str(composed_path), composed)
    logger.info(f"Composed image saved: {composed_path}")

    return composed_path


# ============================================================
# PHASE 5: COMPOSITE VALIDATION
# ============================================================

def phase5_validate(
    composed_path: Path,
    avatar: AvatarData,
    page_idx: int,
    final_path: Path,
    analyzer: "FaceAnalysis",
    logger: logging.Logger,
) -> PageResult:
    """
    ArcFace similarity check on the composed page.
    Commits final image regardless; logs warning on fail.
    """
    logger.info("---------------------------------------------------")
    logger.info(f"PHASE 5 -- Validation  (page {page_idx})")
    logger.info("---------------------------------------------------")

    sim, bbox = arcface_similarity(avatar.embedding, composed_path, analyzer, logger)
    passed    = sim >= ARCFACE_THRESHOLD_PAGE

    logger.info(
        f"Final similarity : {sim:.4f}  "
        f"threshold: {ARCFACE_THRESHOLD_PAGE:.2f}  "
        f"{'PASS' if passed else 'FAIL -- committing best attempt'}"
    )

    shutil.copy(composed_path, final_path)
    logger.info(f"Page {page_idx} committed: {final_path}")

    return PageResult(
        page_idx=page_idx,
        output_path=final_path,
        arcface_score=sim,
        passed=passed,
        method="gpu+cpu",
    )


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline(
    name: str,
    story_id: str,
    backend: GenerationBackend,
):
    logger = setup_logger(name, story_id)

    try:
        load_env(logger)

        if not _REPLICATE_OK:
            raise RuntimeError("replicate not installed: pip install replicate")
        if not _INSIGHTFACE_OK:
            raise RuntimeError("insightface not installed: pip install insightface onnxruntime")

        # ── Paths ─────────────────────────────────────────────
        person_dir  = INPUT_DIR / name
        images_dir  = person_dir / "images"
        story_dir   = person_dir / "stories" / story_id
        scenes_dir  = story_dir / "scenes"

        if not images_dir.exists():
            raise FileNotFoundError(f"images/ missing: {images_dir}")
        if not story_dir.exists():
            raise FileNotFoundError(f"Story folder missing: {story_dir}")
        if not scenes_dir.exists():
            raise FileNotFoundError(f"scenes/ missing: {scenes_dir}")

        supported = {".jpg", ".jpeg", ".png", ".webp"}
        user_images = [p for p in images_dir.iterdir() if p.suffix.lower() in supported]
        if not user_images:
            raise RuntimeError(f"No reference image found in {images_dir}")
        user_image = user_images[0]
        logger.info(f"Reference image : {user_image.name}")

        # ── Output dir ────────────────────────────────────────
        work_dir = OUTPUT_DIR / name / story_id
        work_dir.mkdir(parents=True, exist_ok=True)

        # ── Load manifest ─────────────────────────────────────
        manifest          = load_manifest(story_dir, logger)
        pages             = manifest["pages"]
        style_hint        = manifest["style_hint"]
        oval_color_lab    = manifest["oval_color_lab"]
        oval_tolerance    = manifest.get("oval_color_tolerance", 30)

        # ── InsightFace ───────────────────────────────────────
        analyzer = build_analyzer(logger)

        # ── Phase 0: Avatar generation ────────────────────────
        cache  = AvatarCache(logger)
        avatar = phase0_generate_avatar(
            user_id=name,
            user_image_path=user_image,
            style_hint=style_hint,
            backend=backend,
            cache=cache,
            analyzer=analyzer,
            out_dir=work_dir,
            logger=logger,
        )

        # ── Per-page composition ──────────────────────────────
        results   = []
        char_pages = [p for p in pages if p.get("has_character")]
        plain_pages = [p for p in pages if not p.get("has_character")]

        logger.info(f"Pages with character : {[p['page_idx'] for p in char_pages]}")
        logger.info(f"Pages without character: {[p['page_idx'] for p in plain_pages]}")

        # Pass-through pages (no character): copy scene directly
        for page in plain_pages:
            idx        = page["page_idx"]
            scene_path = scenes_dir / page["scene_image"]
            final_path = work_dir / f"page_{idx:02d}_final.png"
            if not scene_path.exists():
                logger.warning(f"Scene image missing: {scene_path} -- skipping page {idx}")
                continue
            shutil.copy(scene_path, final_path)
            logger.info(f"Page {idx} (no character) -- copied: {final_path.name}")
            results.append(PageResult(
                page_idx=idx,
                output_path=final_path,
                arcface_score=0.0,
                passed=True,
                method="passthrough",
            ))

        # Character pages: full pipeline phases 2-5
        for page in char_pages:
            idx        = page["page_idx"]
            scene_path = scenes_dir / page["scene_image"]

            if not scene_path.exists():
                logger.warning(f"Scene image missing: {scene_path} -- skipping page {idx}")
                continue

            logger.info("===================================================")
            logger.info(f"COMPOSING PAGE {idx}  ({page['scene_image']})")
            logger.info("===================================================")

            oval = phase2_detect_oval(scene_path, oval_color_lab, oval_tolerance, logger)
            pose = phase3_interpret_pose(page, logger)

            composed_path = phase4_render_and_blend(
                scene_path=scene_path,
                avatar=avatar,
                oval=oval,
                pose=pose,
                page=page,
                style_hint=style_hint,
                backend=backend,
                user_id=name,
                story_id=story_id,
                page_idx=idx,
                work_dir=work_dir,
                logger=logger,
            )

            final_path = work_dir / f"page_{idx:02d}_final.png"
            result = phase5_validate(
                composed_path, avatar, idx, final_path, analyzer, logger
            )
            results.append(result)

        # ── Summary ───────────────────────────────────────────
        logger.info("===================================================")
        logger.info("PIPELINE COMPLETE -- SUMMARY")
        logger.info("===================================================")
        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed and r.method != "passthrough"]
        logger.info(f"Total pages   : {len(results)}")
        logger.info(f"PASS          : {len(passed)}")
        logger.info(f"FAIL (warned) : {len(failed)}")
        for r in sorted(results, key=lambda x: x.page_idx):
            score_str = f"{r.arcface_score:.4f}" if r.method != "passthrough" else "n/a"
            logger.info(
                f"  Page {r.page_idx:02d}  {r.method:12s}  "
                f"sim={score_str}  {'PASS' if r.passed else 'FAIL'}  "
                f"{r.output_path.name}"
            )

    except Exception:
        logger.exception("PIPELINE FAILED")
        raise


# ============================================================
# ENTRY
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="AI Face Composition Pipeline v1.0.0"
    )
    parser.add_argument(
        "--name",
        required=True,
        help="User folder name under tests/playground/input/"
    )
    parser.add_argument(
        "--story",
        required=True,
        help="Story ID, must match a folder under input/{name}/stories/"
    )
    args = parser.parse_args()

    backend = ReplicateInstantIDBackend()
    run_pipeline(name=args.name, story_id=args.story, backend=backend)


if __name__ == "__main__":
    main()

"""
tests/evaluator/scene_metadata.py
==================================
Per-scene sentiment and expected face attribute targets.

This is the authoritative source for what "correct" looks like for each scene.
The evaluator uses these targets to score generated images.

Structure:
    SCENE_METADATA[scene_file] = SceneMeta(...)

Attribute meanings:
    gaze_direction:
        "camera"   — child looking directly at viewer (intimate, greeting scenes)
        "subject"  — child looking at another character (rabbit, elephant, etc.)
        "ambient"  — soft gaze, looking at environment (nature, fireflies)

    expression:
        "neutral"  — calm, peaceful, serene
        "smile"    — happy, joyful, playful
        "wonder"   — wide-eyed curiosity, awe

    head_tilt_deg_max:
        Maximum acceptable head tilt in degrees (bilateral).
        Exceeding this = unnatural pose. Typical for children: ≤ 15°.

    face_coverage_min / face_coverage_max:
        Expected fraction of the face_config bounding box covered by the
        detected face. Too small = face too far. Too large = face overflows.

    lighting_match_threshold:
        Minimum LAB-space colour similarity between the face ROI and the
        surrounding template ROI. Measures colour/lighting coherence.
        Range 0-1. Production threshold: ≥ 0.70.

    blend_edge_quality_min:
        Gradient smoothness at the face boundary (Sobel variance ratio).
        Lower variance = smoother blend. Production threshold: ≤ 0.30.

    scene_description:
        Human-readable scene summary used for AI-based evaluation prompts.
"""

from dataclasses import dataclass, field
from typing import Literal

GazeDir  = Literal["camera", "subject", "ambient"]
ExprType = Literal["neutral", "smile", "wonder"]


@dataclass
class SceneMeta:
    """Expected face attribute targets for one scene."""
    scene_file:               str
    scene_description:        str       # used in AI evaluation prompt
    gaze_direction:           GazeDir   # expected child gaze
    expression:               ExprType  # expected expression
    head_tilt_deg_max:        float = 15.0   # bilateral tolerance
    face_coverage_min:        float = 0.55   # fraction of bbox
    face_coverage_max:        float = 1.10   # allow slight overflow
    lighting_match_threshold: float = 0.70   # LAB similarity to template ROI
    blend_edge_quality_min:   float = 0.30   # Sobel variance ratio (lower=better)
    # Score weights (must sum to 1.0 across all attributes)
    weight_face_detected:     float = 0.25
    weight_gaze:              float = 0.15
    weight_expression:        float = 0.15
    weight_tilt:              float = 0.15
    weight_coverage:          float = 0.10
    weight_lighting:          float = 0.10
    weight_blend_edge:        float = 0.10

    @property
    def passing_score(self) -> float:
        """Minimum composite score to be considered production-grade."""
        return 0.72   # 72% weighted score required


# ─── Per-scene definitions ────────────────────────────────────────────────────
# Story: Forest of Smiles (forest_of_smiles)
# Templates: scene_01.png … scene_10.png
# Face coordinates from face_blend.py face_config

SCENE_METADATA: dict[str, SceneMeta] = {

    "scene_01.png": SceneMeta(
        scene_file="scene_01.png",
        scene_description=(
            "Child walking into a magical forest at sunrise. "
            "Warm, wonder-filled entry scene. Child looks ahead with curiosity."
        ),
        gaze_direction="ambient",
        expression="wonder",
        head_tilt_deg_max=12.0,   # tight — opening scene needs good posture
        weight_gaze=0.10,
        weight_expression=0.20,   # expression is key for this scene
    ),

    "scene_02.png": SceneMeta(
        scene_file="scene_02.png",
        scene_description=(
            "A fluffy rabbit greets the child. "
            "Child looks at the rabbit with surprise and joy."
        ),
        gaze_direction="subject",  # looking at rabbit
        expression="wonder",
        weight_gaze=0.20,          # gaze direction critical — must look at rabbit
        weight_expression=0.15,
    ),

    "scene_03.png": SceneMeta(
        scene_file="scene_03.png",
        scene_description=(
            "Birds singing above. Child looks up at the birds, smiling."
        ),
        gaze_direction="subject",  # looking up at birds
        expression="smile",
        head_tilt_deg_max=20.0,    # slight upward tilt acceptable
        weight_gaze=0.20,
        weight_expression=0.15,
    ),

    "scene_04.png": SceneMeta(
        scene_file="scene_04.png",
        scene_description=(
            "Gentle elephant. Child reaches out to touch trunk. "
            "Happy, calm expression."
        ),
        gaze_direction="subject",  # looking at elephant
        expression="smile",
        weight_gaze=0.20,
        weight_expression=0.15,
    ),

    "scene_05.png": SceneMeta(
        scene_file="scene_05.png",
        scene_description=(
            "Slow turtle. Child walks slowly noticing tiny flowers. "
            "Peaceful, contemplative. Soft downward gaze."
        ),
        gaze_direction="ambient",
        expression="neutral",
        head_tilt_deg_max=18.0,    # slight downward tilt acceptable
        weight_gaze=0.10,
        weight_expression=0.15,
    ),

    "scene_06.png": SceneMeta(
        scene_file="scene_06.png",
        scene_description=(
            "Monkey swings down. Child laughs and claps. "
            "Joyful, playful — big smile."
        ),
        gaze_direction="subject",  # looking at monkey
        expression="smile",
        weight_gaze=0.20,
        weight_expression=0.20,   # strong smile is core of this scene
    ),

    "scene_07.png": SceneMeta(
        scene_file="scene_07.png",
        scene_description=(
            "Quiet deer. Child takes a deep breath. "
            "Peaceful, serene — calm neutral expression."
        ),
        gaze_direction="subject",  # looking at deer
        expression="neutral",
        weight_gaze=0.15,
        weight_expression=0.15,
    ),

    "scene_08.png": SceneMeta(
        scene_file="scene_08.png",
        scene_description=(
            "Evening fireflies. Child feels warm and special. "
            "Soft ambient gaze, gentle smile."
        ),
        gaze_direction="ambient",
        expression="smile",
        weight_gaze=0.10,
        weight_expression=0.15,
    ),

    "scene_09.png": SceneMeta(
        scene_file="scene_09.png",
        scene_description=(
            "Big tree speaks gently. Child hugs the tree. "
            "Warm, loving. Eyes may be closed or look at tree."
        ),
        gaze_direction="subject",  # looking at / hugging tree
        expression="smile",
        head_tilt_deg_max=20.0,
        weight_gaze=0.15,
        weight_expression=0.15,
    ),

    "scene_10.png": SceneMeta(
        scene_file="scene_10.png",
        scene_description=(
            "Child walks home as forest whispers goodbye. "
            "Closing scene — peaceful, content, ambient soft gaze."
        ),
        gaze_direction="ambient",
        expression="neutral",
        weight_gaze=0.10,
        weight_expression=0.15,
    ),
}

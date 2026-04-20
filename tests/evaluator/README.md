# StoryMe Image Quality Evaluator

Evaluates face attribute quality in generated storybook page images.
Reads from Azure Blob Storage, runs locally, loops until quality threshold met.

## Architecture

```
tests/evaluator/
├── scene_metadata.py     ← Per-scene expected face attributes (source of truth)
├── face_evaluator.py     ← Core evaluation engine (OpenCV + MediaPipe, no API)
├── blob_reader.py        ← Discovers images from Azure Blob + MongoDB
├── run_evaluator.py      ← Main loop (CLI entry point)
├── requirements.txt      ← Python deps for evaluator
└── reports/              ← Generated JSON + text reports (git-ignored)
```

## Attributes Evaluated

| Attribute | Method | Weight |
|---|---|---|
| `face_detected` | MediaPipe FaceMesh detection | 25% |
| `gaze_direction` | Iris centroid vs eye centre offset | 15% |
| `expression` | Mouth curvature + EAR (eye aspect ratio) | 15% |
| `head_tilt` | Roll angle from eye landmark line | 15% |
| `face_coverage` | Skin-tone pixel fraction in face bbox | 10% |
| `lighting_match` | LAB histogram Bhattacharyya similarity | 10% |
| `blend_edge` | Sobel gradient variance at face boundary | 10% |

Weights are per-scene in `scene_metadata.py` — scenes with critical expression
(e.g. scene_06: monkey/laughter) have higher expression weight.

**Passing score: ≥ 0.72 composite** (configurable per scene in SceneMeta).

## Quick Start

```bash
# Install deps
pip install -r tests/evaluator/requirements.txt

# Set env vars
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;..."
export AZURE_STORAGE_CONTAINER_NAME="storyme-assets"
export MONGO_URL="mongodb://..."

# Run evaluator once (all images)
python tests/evaluator/run_evaluator.py --max-iter 1

# Run indefinitely, polling every 5 min for new generations
python tests/evaluator/run_evaluator.py --poll-interval 300

# Filter by story and child
python tests/evaluator/run_evaluator.py --story forest_of_smiles --child Niku --max-iter 3

# Test with local PNG files (no Azure needed)
python tests/evaluator/run_evaluator.py --local-dir /tmp/my_pages --max-iter 1

# Verbose: show per-attribute scores for every image
python tests/evaluator/run_evaluator.py --verbose --max-iter 1
```

## Data Flow

```
Azure Blob (generated/{gen_id}/pages/page_NN.png)
    │
    │  BlobReader.list_generated_images()
    │  ├── MongoDB-first: query generation_sessions collection
    │  └── Blob-scan fallback: list blobs, infer from path pattern
    │
    ▼
GeneratedImageRecord (gen_id, child_name, story_id, scene_file, blob_path)
    │
    │  BlobReader.download_to_temp()
    │
    ▼
Local temp PNG
    │
    │  FaceEvaluator.evaluate(image, scene_meta, face_config)
    │
    ▼
EvaluationResult (composite_score, passed, per-attribute breakdown)
    │
    ▼
EvaluationReport (aggregated, saved to reports/eval_YYYYMMDD.json)
```

## Scene Metadata

Expected attributes per scene are defined in `scene_metadata.py`:

```python
SCENE_METADATA["scene_06.png"] = SceneMeta(
    gaze_direction="subject",   # looking at monkey
    expression="smile",         # joyful, playful
    weight_expression=0.20,     # smile is critical here — higher weight
    ...
)
```

To add a new story: add entries for each scene in SCENE_METADATA and
add face coordinates to `FACE_COORDS` in `backend/services/story_service.py`.

## Prerequisite: Page Images Must Be in Azure Blob

The evaluator only works if `POST /api/generate` has saved page images to blob.
This was added in the same commit as this evaluator. Generate a new storybook
after deploying to populate blob storage with page images.

To verify images are being saved, check Azure Portal →
Storage Account → storyme-assets → Containers → storyme-assets → generated/

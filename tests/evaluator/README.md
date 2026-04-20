# StoryMe — Image Quality Evaluator

> **Does our face blending actually look good?**
> This tool answers that question automatically, for every generated image, across every scene.

---

## The Problem It Solves

When a parent uploads their child's photo and we generate a 10-page storybook, we composite the child's face into 10 different illustrated scenes. Quality can vary — the face might be tilted the wrong way, poorly lit relative to the scene, or the child might be looking in the wrong direction for that scene's mood.

This evaluator reads every generated image stored in Azure Blob, scores it against 7 face quality attributes, and tells you exactly which scenes are failing and why.

---

## How to Run It

### 1. Install dependencies

```bash
pip install -r tests/evaluator/requirements.txt
```

### 2. Set environment variables

```bash
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=..."
export AZURE_STORAGE_CONTAINER_NAME="storyme-assets"
export MONGO_URL="mongodb://..."
```

### 3. Run

```bash
# Evaluate everything once
python tests/evaluator/run_evaluator.py --max-iter 1

# Evaluate and keep looping until everything passes (new storybooks included each round)
python tests/evaluator/run_evaluator.py

# Filter to one story and child, max 5 rounds
python tests/evaluator/run_evaluator.py --story forest_of_smiles --child Niku --max-iter 5

# See per-attribute scores for every image
python tests/evaluator/run_evaluator.py --verbose --max-iter 1

# Test locally without Azure (point at a folder of PNG files)
python tests/evaluator/run_evaluator.py --local-dir /tmp/my_pages --max-iter 1
```

### All flags

| Flag | Default | What it does |
|---|---|---|
| `--story` | all | Filter by story ID e.g. `forest_of_smiles` |
| `--child` | all | Filter by child name e.g. `Niku` |
| `--gender` | all | Filter by gender variant (`neutral` / `male` / `female`) |
| `--max-iter` | infinite | Stop after this many evaluation rounds |
| `--poll-interval` | 60 | Seconds to wait between rounds |
| `--limit` | 500 | Max images to evaluate per round |
| `--local-dir` | — | Use local PNG files instead of Azure |
| `--output-dir` | `tests/evaluator/reports/` | Where to save reports |
| `--verbose` | off | Print per-attribute breakdown for every image |

---

## What It Checks

Every generated page image is scored on **7 attributes**. Each produces a score from **0.0 to 1.0**. The weighted sum of all scores must reach **≥ 0.72** (72%) to pass.

```
┌─────────────────────┬────────┬──────────────────────────────────────────────────────┐
│ Attribute           │ Weight │ What it measures                                     │
├─────────────────────┼────────┼──────────────────────────────────────────────────────┤
│ face_detected       │  25%   │ Did MediaPipe find a face in the scene?              │
│ gaze_direction      │  15%   │ Is the child looking where the scene requires?       │
│ expression          │  15%   │ Does the expression match the scene's mood?          │
│ head_tilt           │  15%   │ Is the head at a natural angle (not tilted oddly)?   │
│ face_coverage       │  10%   │ Does the face fill its designated area properly?     │
│ lighting_match      │  10%   │ Does the face lighting match the scene's lighting?   │
│ blend_edge          │  10%   │ Is the boundary between face and scene smooth?       │
└─────────────────────┴────────┴──────────────────────────────────────────────────────┘
```

> **Note:** Weights shift per scene. A scene where the child is laughing with a monkey weights `expression` at 20% because the smile is the whole point of that scene.

### How each attribute is measured

**face_detected** — Runs MediaPipe FaceMesh on the generated image. If no face is found in the face region, all other attribute scores are skipped.

**gaze_direction** — Measures the horizontal offset of each iris centroid relative to the eye corner midpoint, normalised by eye width. A small offset means looking at the camera; a large offset means looking sideways at a character.
- `camera` — looking directly at the viewer
- `subject` — looking at another character (rabbit, monkey, deer, etc.)
- `ambient` — soft unfocused gaze (nature, fireflies, walking)

**expression** — Measures mouth corner elevation relative to the mouth midline (smile = corners up) and eye aspect ratio (wonder = wide open eyes).
- `smile` — corners elevated > 4% of mouth width
- `wonder` — wide eyes (EAR > 0.30) + open mouth
- `neutral` — everything else

**head_tilt** — The roll angle between left and right eye corners. Natural range for children in illustrations is ≤ 15°. Each scene has its own tolerance (e.g. scene where child looks up at birds allows ≤ 20°).

**face_coverage** — The fraction of the face bounding box filled with skin-tone pixels (HSV colour segmentation). Too little = face placed too small. Too large = face overflows the allocated area.

**lighting_match** — Compares the luminance histogram (LAB L-channel) of the face region to the surrounding template area using Bhattacharyya distance. High similarity = the face was lit to match the scene. Threshold: ≥ 0.70 similarity.

**blend_edge** — Samples a thin 8-pixel ring around the face boundary and measures Sobel gradient magnitude relative to the image average. A smooth blend has low gradient at the boundary (ratio ≤ 0.30). High gradient = visible hard edge.

---

## What "Passing" Looks Like

```
✅ PASS [0.83] — scene_01.png | Niku | gen=a1b2c3d4
  ✓ face_detected       score=1.00  measured=True       expected=True
  ✓ gaze_direction      score=1.00  measured='ambient'  expected=ambient   iris_offset=0.087
  ✓ expression          score=1.00  measured='wonder'   expected=wonder    corner_ratio=0.021 ear=0.312
  ✓ head_tilt           score=1.00  measured=8.4°       expected=≤12°      roll_deg=8.4°
  ✓ face_coverage       score=0.91  measured=0.74       expected=0.55–1.10 skin_coverage=0.741
  ✓ lighting_match      score=0.85  measured=0.79       expected=≥0.70     bhattacharyya_sim=0.791
  ✓ blend_edge          score=0.78  measured=0.23       expected=≤0.30     edge_ratio=0.2311
```

## What "Failing" Looks Like

```
❌ FAIL [0.54] — scene_06.png | Niku | gen=a1b2c3d4
  ✓ face_detected       score=1.00  measured=True       expected=True
  ✗ gaze_direction      score=0.50  measured='ambient'  expected=subject   iris_offset=0.191
  ✗ expression          score=0.40  measured='neutral'  expected=smile     corner_ratio=0.008 ear=0.267
  ✓ head_tilt           score=1.00  measured=11.2°      expected=≤15°
  ✓ face_coverage       score=0.88  measured=0.71       expected=0.55–1.10
  ✗ lighting_match      score=0.61  measured=0.55       expected=≥0.70     bhattacharyya_sim=0.551
  ✓ blend_edge          score=0.82  measured=0.21       expected=≤0.30
```

Here you can see that scene_06 (the monkey/laughter scene) failed because:
- The child was not looking at the monkey (`gaze` = ambient instead of subject)
- The face shows no smile (`expression` = neutral instead of smile)
- The face lighting is cooler than the warm scene (`lighting_match` = 0.55)

---

## Scene-by-Scene Quality Targets

Each scene has defined expectations based on its story moment. These live in `scene_metadata.py`.

| Scene | Story moment | Expected gaze | Expected expression | Key weight |
|---|---|---|---|---|
| scene_01 | Walking into the forest | ambient | wonder | expression 20% |
| scene_02 | Rabbit says hello | subject (rabbit) | wonder | gaze 20% |
| scene_03 | Birds singing above | subject (birds) | smile | gaze 20% |
| scene_04 | Gentle elephant | subject (elephant) | smile | gaze 20% |
| scene_05 | Slow turtle, tiny flowers | ambient | neutral | — |
| scene_06 | Monkey swings down | subject (monkey) | smile | expression 20% |
| scene_07 | Quiet deer | subject (deer) | neutral | — |
| scene_08 | Evening fireflies | ambient | smile | — |
| scene_09 | Child hugs a big tree | subject (tree) | smile | — |
| scene_10 | Walking home | ambient | neutral | — |

---

## Loop Behaviour

```
Round 1: discover 47 images → evaluate → 38 pass (80%) → wait 60s
Round 2: discover 52 images → evaluate → 44 pass (84%) → wait 60s  ← 5 new storybooks added
Round 3: discover 52 images → evaluate → 52 pass (100%) → DONE ✅
```

New storybooks generated while the evaluator is running are automatically included in the next round. The evaluator stops as soon as 100% of all discovered images pass.

---

## Reports

Every round saves two files to `tests/evaluator/reports/`:

**`eval_20260420_162530.json`** — Machine-readable. Contains per-image, per-attribute scores. Good for CI pipelines and trend analysis.

**`eval_20260420_162530.txt`** — Human-readable summary. Contains pass rates per scene and the list of failed images with their failing attributes.

---

## File Structure

```
tests/evaluator/
│
├── README.md              ← You are here
│
├── scene_metadata.py      ← The source of truth for what "correct" looks like per scene.
│                             Edit this file to change quality thresholds or add new scenes.
│
├── face_evaluator.py      ← Core evaluation engine.
│                             Runs entirely locally using OpenCV and MediaPipe.
│                             No external API calls. Safe to run in a loop.
│
├── blob_reader.py         ← Discovers generated images from Azure Blob Storage.
│                             Uses MongoDB to find blob paths efficiently.
│                             Falls back to scanning blob prefixes if MongoDB is unavailable.
│
├── run_evaluator.py       ← The CLI entry point. Orchestrates the evaluation loop.
│
├── requirements.txt       ← Python dependencies (separate from backend).
│
└── reports/               ← Auto-created. Contains JSON + text reports per run.
                              Not committed to git.
```

---

## Adding a New Story

1. Add face coordinates to `FACE_COORDS` in `backend/services/story_service.py`
2. Add one `SceneMeta` entry per scene to `SCENE_METADATA` in `scene_metadata.py` — set the gaze direction, expected expression, and scene description for each scene
3. Add template images to `backend/templates/stories/{story_id}/{gender}/templates/`
4. Generate a storybook and run the evaluator

---

## Prerequisite: Images Must Be in Azure Blob

The evaluator reads images from Azure Blob Storage. Images are saved there automatically when `POST /api/generate` runs (added in commit `817f0c7`). If you are testing an older deployment, no images will be found.

**To verify images exist:** Azure Portal → Storage Account → storyme-assets → Containers → `generated/`

You should see folders named by generation ID, each containing `pages/page_01.png … page_10.png`.

---

*All evaluation is local — no OpenAI, no Vision API, no external services. Just OpenCV and MediaPipe.*

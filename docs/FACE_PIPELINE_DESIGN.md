# StoryMe Face Personalisation Pipeline — Design Document

**Version:** 1.0  
**Branch:** `beta`  
**Author:** Architecture Review  
**Date:** April 2025

---

## 1. Executive Summary

This document describes the CPU-only face personalisation pipeline for StoryMe that overlays a child's real face onto illustrated storybook scenes. It covers the full architecture, component responsibilities, data flows, configuration schema, and the admin quality-test framework.

### Why CPU-only (no DECA/EMOCA/PyTorch3D)?

| Criterion | 3DMM (DECA/EMOCA) | This Pipeline (OpenCV) |
|-----------|-------------------|------------------------|
| GPU required | Yes (CUDA) | No |
| Model size | 2–4 GB each | 0 (ships with OpenCV) |
| Azure App Service cold start | 60–120 s | <1 s overhead |
| Setup complexity | CUDA, PyTorch, custom C++ | Already in `requirements.txt` |
| Quality for illustrated art | Excellent | Very Good (seamlessClone) |
| Quality for photorealistic | Excellent | Good (±20° pose range) |

**Conclusion:** For a Pixar-style illustrated storybook, `cv2.seamlessClone` + LAB colour matching + Delaunay-warp expression morphing delivers visually indistinguishable results from 3DMM at a fraction of the runtime cost. The `_apply_pose_warp()` and `_apply_expression_morph()` methods in `face_pipeline_service.py` are explicitly **GPU stubs** — they can be replaced with DECA/EMOCA calls when a GPU compute tier is provisioned without touching any other code.

---

## 2. Character Presence Rule

```
Odd pages  (1, 3, 5, 7, 9, 11, 13, 15) → face overlay applied
Last even  (16)                          → face overlay applied
Even pages (2, 4, 6,  8, 10, 12, 14)   → text overlay only (no face)
```

Even pages contain full illustrated scenes with animals/environments. The child character may appear in the DALL-E image but their face is not personalised (left as the blank oval from generation). This is intentional — it creates rhythm between "close-up personalized" pages and "story narrative" pages.

---

## 3. Template Image Location & How to Change Them

### 3.1 Priority Order

The pipeline resolves templates in this priority order:

```
1. backend/cache/dalle/{story_id}/page_{NN:02d}.png   ← PRIMARY (DALL-E generated)
2. backend/templates/stories/{story_id}/page{N}.png   ← FALLBACK (static art)
```

### 3.2 How to Replace a Template Image

To replace a specific page's illustration:

1. **Prepare your image:**  
   - Resolution: **1024 × 1024 px** (square)  
   - Format: PNG  
   - The child's face area must be a **blank, flat skin-tone oval** (`#E8C4A0`)  
   - No facial features in the oval  
   - Right ~40% of image should be clean/blurred background for text  

2. **Drop it into the cache folder:**
   ```
   backend/cache/dalle/forest_of_smiles/page_0X.png
   ```
   Replace `X` with the page number (zero-padded, e.g., `page_03.png` for page 3).

3. **Update face coordinates if needed:**  
   Open `backend/data/stories/forest_of_smiles.json` and find the page entry.  
   Update `face_config.x`, `face_config.y`, `face_config.w`, `face_config.h`  
   to match the centre of the blank oval in your new image.  
   
   Use the coordinate measurement tool:
   ```bash
   cd backend
   python3 -c "
   import cv2, sys
   img = cv2.imread('cache/dalle/forest_of_smiles/page_03.png')
   # Use the image viewer with pixel coordinates
   # Measure: top-left corner (x, y) and size (w, h) of the face oval
   "
   ```
   
   Or run the admin face-test panel at `/admin/face-test` to visually verify alignment.

4. **For adding a completely new story:**  
   - Create `backend/data/stories/{new_story_id}.json` following the schema in §5.  
   - Add images to `backend/cache/dalle/{new_story_id}/page_NN.png`.  
   - The pipeline auto-discovers all JSON files in `backend/data/stories/`.

### 3.3 Quick Reference — Current Forest of Smiles Templates

| Page | File | Character? | Face Oval Location (x,y,w,h) |
|------|------|-----------|------------------------------|
| 1  | `page_01.png` | ✅ Odd | 430, 220, 170, 190 |
| 2  | `page_02.png` | ❌ Even | — |
| 3  | `page_03.png` | ✅ Odd | 440, 300, 150, 170 |
| 4  | `page_04.png` | ❌ Even | — |
| 5  | `page_05.png` | ✅ Odd | 410, 260, 165, 185 |
| 6  | `page_06.png` | ❌ Even | — |
| 7  | `page_07.png` | ✅ Odd | 420, 240, 170, 190 |
| 8  | `page_08.png` | ❌ Even | — |
| 9  | `page_09.png` | ✅ Odd | 450, 260, 150, 170 |
| 10 | `page_10.png` | ❌ Even | — |
| 11 | `page_11.png` | ✅ Odd | 430, 250, 165, 185 |
| 12 | `page_12.png` | ❌ Even | — |
| 13 | `page_13.png` | ✅ Odd | 420, 230, 170, 190 |
| 14 | `page_14.png` | ❌ Even | — |
| 15 | `page_15.png` | ✅ Odd | 440, 240, 170, 190 |
| 16 | `page_16.png` | ✅ Last Even | 430, 220, 180, 200 |

---

## 4. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         StoryMe Face Pipeline                               │
│                                                                             │
│  INPUT                                                                      │
│  ┌──────────────┐  ┌──────────────────┐  ┌─────────────────────────────┐   │
│  │  User photo  │  │  story_id        │  │  child_name                 │   │
│  │  (1 image)   │  │  (forest_of_     │  │  (replaces {name} in text)  │   │
│  └──────┬───────┘  │   smiles)        │  └────────────────┬────────────┘   │
│         │          └────────┬─────────┘                   │                │
│         │                   │                             │                │
│         ▼                   ▼                             │                │
│  ┌──────────────────────────────────────┐                │                │
│  │        StoryJsonService              │                │                │
│  │  • Reads data/stories/*.json         │                │                │
│  │  • Resolves template paths           │                │                │
│  │    (cache/dalle > templates/stories) │                │                │
│  │  • Typed PageConfig per page         │                │                │
│  └────────────────┬─────────────────────┘                │                │
│                   │ 16 PageConfig objects                 │                │
│                   ▼                                       │                │
│  ┌────────────────────────────────────────────────────────▼───────────┐   │
│  │                    FacePipelineService                              │   │
│  │                                                                     │   │
│  │  for each page:                                                     │   │
│  │                                                                     │   │
│  │  if character_present:          else:                               │   │
│  │  ┌───────────────────────┐      ┌──────────────────────────────┐   │   │
│  │  │ process_character_    │      │ process_text_only_page()     │   │   │
│  │  │ page()                │      │  • copy template             │   │   │
│  │  │                       │      │  • overlay story text        │   │   │
│  │  │ Step 1: Face extract  │      │  • replace {name}            │   │   │
│  │  │   MediaPipe 468-pt    │      └──────────────┬───────────────┘   │   │
│  │  │   FaceMesh detect     │                     │                   │   │
│  │  │   Roll alignment      │                     │                   │   │
│  │  │   Tight crop + pad    │                     │                   │   │
│  │  │         ↓             │                     │                   │   │
│  │  │ Step 2: Pose warp *   │                     │                   │   │
│  │  │   Perspective xform   │                     │                   │   │
│  │  │   Yaw / Pitch / Roll  │                     │                   │   │
│  │  │   (±20° range)        │                     │                   │   │
│  │  │         ↓             │                     │                   │   │
│  │  │ Step 3: Expression *  │                     │                   │   │
│  │  │   Delaunay tri-warp   │                     │                   │   │
│  │  │   13 expression types │                     │                   │   │
│  │  │         ↓             │                     │                   │   │
│  │  │ Step 4: Colour match  │                     │                   │   │
│  │  │   LAB histogram match │                     │                   │   │
│  │  │   60% match / 40% raw │                     │                   │   │
│  │  │         ↓             │                     │                   │   │
│  │  │ Step 5: Blend         │                     │                   │   │
│  │  │   Elliptical mask     │                     │                   │   │
│  │  │   cv2.seamlessClone   │                     │                   │   │
│  │  │         ↓             │                     │                   │   │
│  │  │ Step 6: Text overlay  │                     │                   │   │
│  │  │   PIL font rendering  │                     │                   │   │
│  │  │   Auto-size + wrap    │                     │                   │   │
│  │  └───────────┬───────────┘                     │                   │   │
│  │              │ output PNG                      │ output PNG        │   │
│  └──────────────▼─────────────────────────────────▼───────────────────┘   │
│                   16 output PNGs                                            │
│                        │                                                   │
│                        ▼                                                   │
│  ┌───────────────────────────────────────┐                                 │
│  │            PDFService                 │                                 │
│  │  ReportLab → A4 storybook PDF         │                                 │
│  └───────────────────────────────────────┘                                 │
│                        │                                                   │
│  OUTPUT: {name}_XXXXXXXX.pdf                                                │
└─────────────────────────────────────────────────────────────────────────────┘

* = GPU stub: replace with DECA/EMOCA when GPU available
```

---

## 5. Story JSON Schema (v2)

```json
{
  "story_id": "forest_of_smiles",
  "title": "{name} and the Forest of Smiles",
  "total_pages": 16,
  "image_size": "1024x1024",
  "common_prompt_template": "...",
  "pages": [
    {
      "page_number": 1,
      "character_present": true,
      "story_lines": ["{name} stepped into a quiet jungle..."],
      "face_config": { "x": 430, "y": 220, "w": 170, "h": 190 },
      "head_pose": { "yaw": 5, "pitch": -3, "roll": 0 },
      "expression": "curious",
      "text_area": { "x": 610, "y": 100, "w": 390, "h": 800 },
      "scene_prompt": "..."
    },
    {
      "page_number": 2,
      "character_present": false,
      "story_lines": ["A little monkey sat alone on a branch..."],
      "text_area": { "x": 550, "y": 120, "w": 450, "h": 780 },
      "scene_prompt": "..."
    }
  ]
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `character_present` | bool | Yes | Whether to apply face overlay |
| `head_pose.yaw` | float (°) | Char pages | +ve = turn right, –ve = turn left |
| `head_pose.pitch` | float (°) | Char pages | +ve = look down, –ve = look up |
| `head_pose.roll` | float (°) | Char pages | +ve = tilt clockwise |
| `expression` | string | Char pages | One of 13 presets (see §6.2) |
| `text_area` | {x,y,w,h} | Yes | Pixel region for story text overlay |
| `face_config` | {x,y,w,h} | Char pages | Top-left and size of blank face oval |

---

## 6. FacePipelineService — Component Detail

### 6.1 Processing Flow (Character Page)

```
User image (JPEG/PNG)
        │
        ▼
  MediaPipe FaceMesh (468 landmarks)
        │
        ▼
  Roll alignment (affine rotation via eye-line angle)
        │
        ▼
  Convex-hull face crop  +  40% top / 12% bottom / 18% side padding
        │
        ▼
  Re-detect landmarks in crop
        │
    ┌───┴────────┐
    │            │
    ▼            ▼
  Pose warp   Expression morph
  (if |yaw|   (if expression ≠ neutral)
   |pitch|    Delaunay triangulation →
   |roll|>1°) per-tri affine warp
    │            │
    └────┬───────┘
         │
         ▼
  Resize to target (w × 0.92, h × 0.92)
         │
         ▼
  LAB colour/lighting match  (60% target, 40% original)
         │
         ▼
  Elliptical Gaussian mask  (44% × 48% axes)
         │
         ▼
  cv2.seamlessClone (NORMAL_CLONE)
  → fallback: alpha composite on error
         │
         ▼
  PIL text overlay  (auto-size, word-wrap, outline)
         │
         ▼
  Output PNG
```

### 6.2 Expression Presets

| Expression | Scene Context | Key Movements |
|------------|---------------|---------------|
| `neutral` | Calm/transitional | None |
| `curious` | Exploring, noticing | Brow raise +1.0% |
| `determined` | Searching, focused task | Inner brow lower 0.8% |
| `caring` | Comforting an animal | Soft smile +2.0% |
| `joyful` | Animal grateful hug | Strong smile +5.0%, cheeks +2.2% |
| `focused` | Precise task (nest placement) | Slight brow lower 0.5% |
| `delighted` | Animal celebrating | Big smile +6.0%, mouth slightly open |
| `awed` | Magical moment (glowing tree) | Brows up +1.5%, mouth slightly open |
| `welcoming` | Arms spread, calling friends | Open smile +4.0% |
| `proud` | Final hero scene | Confident soft smile +2.0% |
| `sad` | (reserved for sad scenes) | Corners down +2.5%, brow furrow |
| `gentle` | Soft caring moment | Soft smile +1.5% |

### 6.3 GPU Upgrade Path (DECA/EMOCA)

When GPU compute becomes available (Azure ML compute cluster), replace exactly these two methods in `face_pipeline_service.py`:

```python
# REPLACE:
def _apply_pose_warp(self, face, landmarks, yaw, pitch, roll) -> np.ndarray:
    # Current: 2D perspective warp approximation
    ...

# WITH:
def _apply_pose_warp_deca(self, face, landmarks, yaw, pitch, roll) -> np.ndarray:
    # DECA: reconstruct 3DMM, modify pose parameters, re-render
    from deca import DECAModel
    deca = DECAModel(device='cuda')
    params = deca.encode(face)
    params['pose'][1] = yaw_rad
    params['pose'][0] = pitch_rad
    return deca.render_with_pose(params)

# REPLACE:
def _apply_expression_morph(self, face, landmarks, expression) -> np.ndarray:
    # Current: Delaunay triangle warp on landmark deltas
    ...

# WITH:
def _apply_expression_morph_emoca(self, face, landmarks, expression) -> np.ndarray:
    # EMOCA: manipulate expression code vector directly
    from emoca import EMOCAModel
    emoca = EMOCAModel(device='cuda')
    params = emoca.encode(face)
    params['expression'] = EMOCA_EXPRESSION_CODES[expression]
    return emoca.decode(params)
```

All other pipeline steps (colour matching, seamlessClone, text overlay) remain unchanged.

---

## 7. Quality Evaluation Framework

### 7.1 Metrics

| Metric | Method | Weight | Good Range |
|--------|--------|--------|------------|
| Face position | MediaPipe detect → IoU vs target bbox | 20% | > 0.65 |
| Edge quality | Laplacian variance at face boundary | 25% | score > 0.60 |
| Lighting consistency | LAB L-channel delta (face vs background) | 20% | ΔL < 15 |
| Colour harmony | Histogram correlation (face vs adjacent) | 20% | corr > 0.60 |
| Skin tone blend | RGB delta at inner/outer face boundary | 15% | delta < 30 |

### 7.2 Report Structure (for Claude parameter tuning)

The report at `backend/output/admin_face_tests/{job_id}/report.json` includes a `claude_tuning_prompt` field — paste it directly to Claude to get specific code-level parameter recommendations.

```json
{
  "claude_tuning_prompt": "StoryMe face blend quality report. Average score: 0.74/1.00. Current pipeline parameters to tune: {...}. Please analyse the per-page metrics and suggest specific code changes to backend/services/face_pipeline_service.py to improve scores above 0.80.",
  "tuning_recommendations": {
    "face_pipeline_service": {
      "default_scale_factor": 0.93,
      "gaussian_blur_sigma": 18,
      "color_match_strength": 0.65,
      "feather_radius": 25
    }
  }
}
```

---

## 8. Admin Face Test Panel

Route: `/admin/face-test`  
Auth: Same `X-Admin-Key` as `/admin/orders`

### Workflow

```
Admin opens /admin/face-test
        │
        ▼
  Select story (dropdown, default: forest_of_smiles)
  Upload 4 child photos
        │
        ▼
  POST /api/admin/face-test/run  (multipart)
        │
        ▼
  Backend: async job runs in thread executor
    • process_character_page() for each char page × 4 faces
    • evaluate_image() per output
    • generate_report()
        │
        ▼
  GET /api/admin/face-test/job/{id}  (poll every 3s)
        │
        ▼
  Results grid:
    • Per-page: 4 face overlay images side by side
    • Metrics table: position / edge / lighting / colour / skin
    • Colour-coded grade (A/B/C/D)
    • Expandable suggestions per issue
    • Download full JSON report
```

---

## 9. API Endpoints Added

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/admin/face-test/stories` | List available stories |
| `POST` | `/api/admin/face-test/run` | Submit 4-face quality test job |
| `GET`  | `/api/admin/face-test/job/{id}` | Poll job status & results |
| `GET`  | `/api/admin/face-test/image/{job}/{page}/{face}` | Serve generated image |
| `POST` | `/api/generate` | Updated: uses new pipeline for char pages |

---

## 10. File Map

```
backend/
  data/stories/
    forest_of_smiles.json          ← Story config (v2 with new fields)
  services/
    story_json_service.py          ← NEW: JSON config loader + resolver
    face_pipeline_service.py       ← NEW: Core face pipeline (CPU-only)
    quality_evaluator.py           ← NEW: Quality metrics + report
  routes/
    admin_face.py                  ← NEW: Admin test API
  cache/dalle/forest_of_smiles/
    page_01.png … page_16.png      ← PRIMARY template images (replace here)
  templates/stories/forest_of_smiles/
    page1.png … page10.png         ← FALLBACK templates

frontend/src/
  pages/
    AdminFaceTestPage.jsx           ← NEW: Admin test UI
    AdminOrdersPage.jsx             ← UPDATED: added nav link
  AppRoutes.jsx                     ← UPDATED: /admin/face-test route

docs/
  FACE_PIPELINE_DESIGN.md           ← This file
```

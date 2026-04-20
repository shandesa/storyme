# Face Blend Auto-Tuner

> Automatically improve how well a child's face blends into each story scene —
> without touching the core algorithm by hand.

---

## What it does

The face blend pipeline has 8 numeric constants (mask size, blur strength,
lighting intensity, etc.) that control how a child's face is composited into
an illustrated scene. Tweaking these manually is trial-and-error.

This tool does it systematically. You provide **15 sample user face images**.
The tuner blends each one onto the target scene, scores the result using the
quality evaluator, tries different values for each constant, and keeps whatever
produces the best score. When it's done, it patches `face_blend_service.py` with
the winning values.

**No model training. No AI. No guessing.** Pure parameter optimisation — fast,
transparent, and fully reversible.

---

## Before you start

### 1 — Install dependencies

```bash
pip install opencv-python-headless mediapipe numpy
```

These are the same libraries the backend already uses.

### 2 — Drop your sample images

Put 15 user face photos (JPG or PNG) into:

```
tests/tuner/samples/
    user_01.jpg
    user_02.jpg
    ...
    user_15.jpg
```

**Why 15?** Fewer samples risk over-fitting to one face shape or skin tone.
15 gives enough diversity (different head poses, lighting, complexions) that
the winning parameters work well across all users — not just one.

Minimum viable: 5 images. Below 5 the tool warns you. Below 3 it stops.

---

## The four steps

```
Step 1: Baseline    — see current scores before any changes
Step 2: Optimise    — let the tuner find better parameter values
Step 3: Review      — read the results, decide if they look right
Step 4: Apply       — patch face_blend_service.py with winning values
```

---

## Step 1 — Baseline (always run this first)

```bash
python tests/tuner/run_tuner.py --scene scene_01.png --dry-run
```

This blends your 15 samples onto `scene_01.png` using the **current parameters**,
scores each result, and prints a report. **Nothing is changed.**

Sample output:

```
10:32:14  INFO      ═══ Baseline: scene_01.png ═══
10:32:14  INFO        ✅ face_detected       ████████████████████  0.933
10:32:14  INFO        ❌ lighting_match      ██████████████░░░░░░  0.694
10:32:14  INFO        ❌ blend_edge          █████████████░░░░░░░  0.661
10:32:14  INFO        ✅ face_coverage       ████████████████░░░░  0.801
10:32:14  INFO        ✅ head_tilt           ████████████████████  0.912
10:32:14  INFO        ✅ gaze_direction      ████████████████░░░░  0.800
10:32:14  INFO        ✅ expression          ███████████████░░░░░  0.783
10:32:14  INFO        composite:  0.769   threshold: 0.80  ❌ NOT MET
```

This tells you exactly which attributes are failing (`lighting_match`, `blend_edge`)
before you spend any time optimising.

---

## Step 2 — Optimise

### One scene

```bash
python tests/tuner/run_tuner.py --scene scene_01.png
```

### One scene, stricter target

```bash
python tests/tuner/run_tuner.py --scene scene_01.png --threshold 0.85
```

### All 10 scenes in sequence

```bash
python tests/tuner/run_tuner.py --all-scenes
```

### All scenes, more rounds, strict target

```bash
python tests/tuner/run_tuner.py --all-scenes --threshold 0.85 --max-rounds 15
```

**How long does it take?**

| Samples | Params | Candidates each | One scene |
|---|---|---|---|
| 15 | 8 | 5–7 | ~45–90 min |
| 5 | 8 | 5–7 | ~15–30 min |

The tuner prints live progress as it runs. You can leave it and come back.

---

## Step 3 — Review results

After optimisation, two files are written:

```
tests/tuner/results/
    tuning_scene_01_20260420_163045.json    ← full trial log
    winning_params.json                     ← params to apply
```

**`winning_params.json`** looks like:

```json
{
  "mask_ellipse_rx":   0.45,
  "mask_ellipse_ry":   0.53,
  "mask_blur_sigma":   29,
  "face_scale":        1.04,
  "luminance_strength": 0.85,
  "warm_tint_r":       1.04,
  "warm_tint_g":       1.01,
  "clone_mode":        "MIXED_CLONE"
}
```

**Before applying, check the trial log** to confirm the improvement is real:

```bash
python -c "
import json
d = json.load(open('tests/tuner/results/winning_params.json'))
print('Winning params:', json.dumps(d, indent=2))
"
```

Or look at the `.json` trial log to see every candidate tried and its score.

---

## Step 4 — Apply

### Dry-run first (shows what will change, no writes)

```bash
python tests/tuner/apply_params.py
```

Output:

```
Parameters to patch:
  mask_ellipse_rx: → 0.45
  mask_blur_sigma: → 29
  warm_tint_r:     → 1.04
  clone_mode:      → MIXED_CLONE

Diff:
Line 265:
  - (int(w * 0.42), int(h * 0.50)),
  + (int(w * 0.45), int(h * 0.53)),

DRY RUN — no files written. Run with --apply to patch.
```

### Actually apply

```bash
python tests/tuner/apply_params.py --apply
```

A backup of `face_blend_service.py` is written to `face_blend_service.py.tuner_backup`
before any changes. To undo, just copy the backup back.

### Apply from a custom params file

```bash
python tests/tuner/apply_params.py --apply --params-file /path/to/my_params.json
```

---

## Step 5 — Verify in the real app

```bash
# Generate a storybook in the app (any child, any story)
# Then run the evaluator:
python tests/evaluator/run_evaluator.py --max-iter 1 --verbose
```

The evaluator scores real generated images from Azure Blob. If the tuner did
its job, the scores should be higher than the baseline you recorded in Step 1.

---

## All flags reference

### `run_tuner.py`

```
python tests/tuner/run_tuner.py [options]

Options:
  --scene SCENE       Scene file to tune, e.g. scene_01.png
                      Required unless --all-scenes is used.

  --all-scenes        Tune all 10 scenes sequentially.
                      Takes longer but produces a complete set of winning params.

  --threshold FLOAT   Target composite score to reach. Default: 0.80
                      Range: 0.0–1.0 (higher = stricter)
                      The optimiser stops early when this is reached.

  --max-rounds INT    Maximum number of full passes over all parameters.
                      Default: 10. More rounds = more thorough but slower.

  --dry-run           Only score the baseline. No optimisation. No changes.
                      Use this first to see where you currently stand.

Examples:
  python tests/tuner/run_tuner.py --scene scene_01.png --dry-run
  python tests/tuner/run_tuner.py --scene scene_06.png --threshold 0.85
  python tests/tuner/run_tuner.py --all-scenes --max-rounds 5
```

### `apply_params.py`

```
python tests/tuner/apply_params.py [options]

Options:
  --apply             Actually patch face_blend_service.py.
                      Without this flag, the command is always a dry-run.

  --params-file PATH  Path to winning_params.json.
                      Default: tests/tuner/results/winning_params.json

Examples:
  python tests/tuner/apply_params.py                       # dry-run (safe)
  python tests/tuner/apply_params.py --apply               # patch the file
  python tests/tuner/apply_params.py --apply --params-file custom.json
```

---

## What parameters are tuned

| Parameter | What it controls | Affects |
|---|---|---|
| `mask_ellipse_rx` | How wide the face oval is | face_coverage, blend_edge |
| `mask_ellipse_ry` | How tall the face oval is | face_coverage, blend_edge |
| `mask_blur_sigma` | How soft/feathered the oval edge is | blend_edge |
| `face_scale` | How large the face is placed relative to its target area | face_coverage |
| `luminance_strength` | How strongly the face brightness matches the scene | lighting_match |
| `warm_tint_r` | Red channel warmth boost in warm-lit scenes | lighting_match |
| `warm_tint_g` | Green channel warmth boost in warm-lit scenes | lighting_match |
| `clone_mode` | `NORMAL_CLONE` vs `MIXED_CLONE` in seamlessClone | blend_edge, lighting_match |

The algorithm itself — affine alignment, ConvexHull extraction, Poisson blending — is not touched. Only these 8 constants change.

---

## Run it with Claude Code

If you have Claude Code installed (`claude` CLI), you can hand the entire workflow to it:

```bash
claude --dangerously-skip-permissions \
  "Run tests/tuner/run_tuner.py --scene scene_01.png --threshold 0.80.
   Once done, apply the winning params and show me before/after scores."
```

Claude Code will run the blend, read the scores, iterate rounds, apply the patch,
and verify — telling you what changed and why.

---

## Output files

```
tests/tuner/
├── samples/                          ← your input images go here
│   ├── user_01.jpg
│   └── user_15.jpg
│
└── results/                          ← all output goes here
    ├── baseline_scene_01.json        ← scores before tuning (from --dry-run)
    ├── tuning_scene_01_162530.json   ← full trial log (every candidate tried)
    └── winning_params.json           ← params to pass to apply_params.py
```

---

## Frequently asked questions

**What if the score doesn't reach my threshold?**
The optimiser stops when it can't improve further. If the final score is still
below your threshold, the parameters alone can't fix it — the alignment algorithm
or blend method itself may need changing. That's a code change, not a parameter
change. Check the trial log to see where the ceiling was.

**Can I undo an apply?**
Yes. `apply_params.py --apply` writes a backup at
`backend/services/face_blend_service.py.tuner_backup` before touching anything.
Restore it with:
```bash
cp backend/services/face_blend_service.py.tuner_backup \
   backend/services/face_blend_service.py
```

**Do I need Azure or MongoDB to run the tuner?**
No. The tuner runs entirely locally. It only needs your sample images and the
template/reference files bundled with the app (`backend/templates/...`).

**How is this different from the evaluator?**
The **evaluator** (`tests/evaluator/`) reads images already generated by the live
app and scores them. The **tuner** (`tests/tuner/`) generates its own test images
using your sample faces and optimises the parameters that produced them.
They share the same scoring engine but serve different purposes.

**Should I run the tuner before or after deploy?**
Before. Tune locally, verify the scores, apply the params, then deploy. The
evaluator can confirm the improvement in the live app after deployment.

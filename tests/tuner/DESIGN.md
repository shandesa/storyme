# Auto-Tuner: Automatic face_blend Parameter Optimisation

## Honest Assessment First

Before describing what can be built, it is important to be precise about what kind
of "correction" is possible automatically vs what requires a human engineer.

### Three levels of correction — only one is fully automatable

```
Level 1: Parameter tuning         ← FULLY AUTOMATABLE (this is what we build)
Level 2: Algorithm changes        ← Claude Code can draft + test, human reviews
Level 3: Architectural redesign   ← Human judgment required
```

**Level 1 — Parameter tuning (automatable)**
The face_blend pipeline has ~8 numeric constants. Each maps directly to one or
more evaluator attributes. These can be optimised automatically using the 15
sample images as a dataset and the evaluator as the objective function.

```
Parameter                 → Attribute it affects
─────────────────────────   ──────────────────────
mask_ellipse_rx (0.42)    → blend_edge, face_coverage
mask_ellipse_ry (0.50)    → blend_edge, face_coverage
mask_blur_sigma (25)      → blend_edge
color_match_strength      → lighting_match
luminance_scale_ratio     → lighting_match
warm_tint_r_boost (1.05)  → lighting_match
warm_tint_g_boost (1.02)  → lighting_match
scale_factor (1.1)        → face_coverage
clone_mode (NORMAL/MIXED) → blend_edge
```

**Level 2 — Algorithm changes (Claude Code assisted)**
If a score like `head_tilt` is consistently low, the 7-point affine alignment
landmark set or the canonical positions may need changing. Claude Code can propose
a code change, test it against the 15 samples, evaluate, and iterate.

**Level 3 — Architecture (human)**
If seamlessClone itself is the wrong algorithm for a scene type (e.g. very
high-contrast backgrounds), switching to alpha blending or Laplacian pyramid
blending is a judgment call.

---

## What the 15 Samples Enable

With 15 different user faces blended onto the same template:
- You get a statistically meaningful mean score per parameter setting
- You can detect whether a parameter change improves quality *in general*
  (not just for one face)
- You can run coordinate descent optimisation (adjust one parameter at a time,
  keep if score improves, discard if not)
- 15 samples is enough for this — it covers diversity in face shape, skin tone,
  head pose, and lighting

---

## System Design

```
tests/
└── tuner/
    ├── samples/                      ← you drop your 15 user face images here
    │   ├── user_01.jpg
    │   ├── user_02.jpg
    │   └── ... (15 total)
    │
    ├── tuner_params.py               ← PARAMS dict: all tunable values + ranges
    ├── blend_runner.py               ← runs face_blend with a given PARAMS dict
    ├── score_runner.py               ← runs evaluator on blend output, returns scores
    ├── optimiser.py                  ← coordinate descent loop
    ├── apply_params.py               ← writes winning params back to face_blend_service.py
    └── run_tuner.py                  ← CLI entry point (orchestrates the whole loop)
```

### Data flow

```
15 user face images
        │
        ▼
blend_runner.py (runs face_blend_service.process_scene with current PARAMS)
        │
        ▼
15 blended PNG outputs (temp files)
        │
        ▼
score_runner.py (runs FaceEvaluator on each output, returns mean per-attribute score)
        │
        ▼
optimiser.py (coordinate descent: adjust one param, re-blend, re-score, keep/discard)
        │  (repeats until no improvement or max_rounds reached)
        ▼
apply_params.py (patches face_blend_service.py with winning param values)
        │
        ▼
tests/tuner/results/tuning_{ts}.json (full log of every trial)
```

---

## The Optimiser — Coordinate Descent

Coordinate descent is the right algorithm here:
- No gradients needed (the evaluator is not differentiable)
- Each step is interpretable ("increasing mask sigma from 25→31 improved blend_edge by 0.09")
- Fast enough (15 images × ~3s/image × ~50 trials = ~37 minutes total)
- Converges well on 8-dimensional parameter spaces

Algorithm:
```
for each parameter p in PARAMS:
    for each candidate value v in p.search_range:
        blend all 15 samples with v substituted for p
        evaluate all 15 outputs
        compute mean composite score
    keep v that produced highest mean score
    update PARAMS[p] = best_v
repeat for max_rounds or until no improvement > min_delta
```

---

## Parameters and Search Ranges

```python
PARAMS = {
    # Mask shape — affects face_coverage and blend_edge
    "mask_ellipse_rx": {
        "current": 0.42,
        "search": [0.35, 0.38, 0.42, 0.45, 0.48],
        "affects": ["face_coverage", "blend_edge"],
    },
    "mask_ellipse_ry": {
        "current": 0.50,
        "search": [0.44, 0.47, 0.50, 0.53, 0.56],
        "affects": ["face_coverage", "blend_edge"],
    },
    # Mask feathering — affects blend_edge
    "mask_blur_sigma": {
        "current": 25,
        "search": [15, 20, 25, 31, 37],
        "affects": ["blend_edge"],
    },
    # Scale of extracted face relative to face_config dimensions
    "face_scale": {
        "current": 1.0,
        "search": [0.90, 0.95, 1.00, 1.05, 1.10],
        "affects": ["face_coverage"],
    },
    # Luminance matching strength (0=none, 1=full)
    "luminance_strength": {
        "current": 1.0,
        "search": [0.5, 0.7, 0.85, 1.0],
        "affects": ["lighting_match"],
    },
    # Warm tint red channel boost
    "warm_tint_r": {
        "current": 1.05,
        "search": [1.00, 1.02, 1.05, 1.08],
        "affects": ["lighting_match"],
    },
    # Warm tint green channel boost
    "warm_tint_g": {
        "current": 1.02,
        "search": [1.00, 1.01, 1.02, 1.04],
        "affects": ["lighting_match"],
    },
    # Clone mode
    "clone_mode": {
        "current": "NORMAL_CLONE",
        "search": ["NORMAL_CLONE", "MIXED_CLONE"],
        "affects": ["blend_edge", "lighting_match"],
    },
}
```

---

## What Claude Code Can Do With This

Claude Code (the CLI tool — `claude` command) is well-suited to run this as an
agentic loop because it can:

1. Run `blend_runner.py` on 15 samples with current params
2. Run `score_runner.py` and read the JSON scores
3. Identify which attributes are below threshold (< 0.80)
4. Call `optimiser.py` with a targeted search focused on those attributes
5. Read the winning params from the result JSON
6. Call `apply_params.py` to patch `face_blend_service.py`
7. Run the evaluator again to confirm improvement
8. Repeat until all attributes meet threshold or max iterations reached

This is the exact workflow Claude Code is designed for — read files, run scripts,
interpret output, make targeted code changes, verify.

**To run with Claude Code:**
```bash
claude --dangerously-skip-permissions \
  "Run tests/tuner/run_tuner.py with the 15 samples in tests/tuner/samples/.
   Target threshold 0.80 for all attributes.
   Apply winning params to face_blend_service.py.
   Show me the before/after scores."
```

---

## What Requires Human Review

Even with full automation, the following decisions need a human:
1. **Do the 15 samples look good visually?** Scores can be gamed — a face
   that scores 0.90 might still look wrong to a parent.
2. **Is the winning param physically sensible?** If the optimiser sets
   `mask_ellipse_rx=0.35` (very narrow), it might score well on blend_edge
   but look unnaturally pinched.
3. **Level 2 changes (algorithm code).** If coordinate descent maxes out and
   the score plateau is still below 0.80, the pipeline needs code changes —
   which Claude Code drafts and a human reviews before merging.

---

## Recommended Workflow

```
Phase 1: Baseline (30 min)
  Drop 15 sample images in tests/tuner/samples/
  Run: python tests/tuner/run_tuner.py --dry-run
  Read: tests/tuner/results/baseline.json
  See which attributes are below 0.80

Phase 2: Auto-tune (30–90 min depending on sample count)
  Run: python tests/tuner/run_tuner.py --max-rounds 10 --threshold 0.80
  The optimiser adjusts params, re-blends, re-scores, repeats
  When done: tests/tuner/results/tuning_{ts}.json shows every trial

Phase 3: Review and apply (5 min)
  Look at: tests/tuner/results/winning_params.json
  Check the before/after score comparison
  If satisfied: python tests/tuner/apply_params.py --auto-apply
  This patches face_blend_service.py in-place

Phase 4: Verify
  Generate a storybook in the app
  Run the evaluator: python tests/evaluator/run_evaluator.py --max-iter 1
  Confirm real-world scores match tuner predictions
```

# Image Generation Prompt — Forest of Smiles, Page 1 (Reference Template)

**Story:** Forest of Smiles  
**Page:** 1 of 10 — "Walking into the Forest"  
**Canvas:** 1024 × 1024 px, square  
**Purpose:** Reference character template for face compositing. All other scene prompts must match the character specification defined here.

---

## Primary Prompt (DALL-E 3 / GPT-Image)

```
Pixar-style children's book illustration, 1024x1024 square canvas, 
soft pastel color palette, warm golden sunrise forest scene.

A gender-neutral young child (approximately age 4–5) stands centered 
in the lower two-thirds of the image, facing slightly toward the viewer 
at a gentle three-quarter angle. The character is a single illustrated 
figure with no real photographic face — the face area is a smooth, 
featureless uniform skin-toned oval with absolutely no eyes, no nose, 
no mouth, no eyebrows, no eyelashes, and no facial details of any kind. 
The face is a perfectly smooth, matte, skin-colored ellipse — like an 
unfinished mannequin or a face-shaped placeholder. This blank oval is 
critical and must be exact.

CHARACTER ANATOMY — FIXED SPECIFICATIONS:
- Total character height occupies approximately 70% of canvas height 
  (roughly 720px tall within the 1024px canvas)
- Character is horizontally centered at x=512px
- Character bounding box: x=322 to x=702, y=100 to y=820

HEAD AND FACE:
- Head is proportionally large in Pixar style (approximately 1/3 of 
  total body height)
- HEAD CENTER: x=512, y=265px from top
- BLANK FACE OVAL CENTER: exactly at pixel coordinates x=512, y=285
- BLANK FACE OVAL SIZE: 164px wide × 190px tall (horizontal radius 82px, 
  vertical radius 95px)
- BLANK FACE OVAL TOP-LEFT CORNER: approximately x=430, y=190
- BLANK FACE OVAL BOTTOM-RIGHT CORNER: approximately x=594, y=380
- The blank face oval occupies 16% of canvas width and 18.6% of canvas height
- Face oval color: uniform smooth matte peach-beige (#F5D5B8), 
  zero texture variation, zero shadow detail within the oval itself
- Face oval boundary: soft 3–4px feathered edge blending into the 
  surrounding skin/head area — no hard sharp edge

HAT — FIXED SPECIFICATIONS:
- A wide-brimmed soft adventurer hat (similar to a safari or explorer hat)
- Material: warm golden-tan woven straw/felt, Pixar stylized texture
- Hat brim top edge: y=110px from top of canvas
- Hat brim extends: approximately 360px wide, centered at x=512
  (from x=152 to x=872 for the brim tips)
- Hat crown height: approximately 70px (crown top y=110, brim junction y=180)
- Hat brim is gently curved downward at the sides, slightly upturned at back
- Hat color: warm golden tan (#C8963E), soft highlight on top crown
- A small decorative green leaf or sprig tucked into the hat band on 
  the left side (character's right)
- The hat is worn squarely on the head — not tilted — brim parallel to 
  the ground plane
- Hat sits above and around the blank face oval, framing it from above 
  and sides without covering the face oval

NECK AND BODY:
- Neck: visible, short and rounded (Pixar child style), y=400 to y=420
- Torso: y=410 to y=620, center x=512
- Clothing: a simple short-sleeve t-shirt in warm sunny yellow (#F4D03F), 
  slightly oversized, soft folds at the sides
- Shorts or a simple skirt in earthy sage green (#7DAB5A), knee-length
- Clothing has no logos, no text, no complex patterns — solid color with 
  minimal Pixar-style shading folds
- Shoes: small rounded adventure boots in warm brown (#8B5E3C), 
  simple lace-up style

POSE:
- Both feet on the ground, weight slightly on the left foot (character's left)
- Left arm hanging naturally at side, slightly forward suggesting a walking step
- Right arm slightly raised, open hand, as if reaching toward the forest 
  with wonder and curiosity
- Body is upright, posture is open and welcoming, not stiff
- The character's orientation is 15–20 degrees rotated from front-facing 
  toward the viewer's left — a gentle three-quarter angle

SCENE ENVIRONMENT — PAGE 1 (FIXED):
- Location: entrance to a magical softly lit forest at golden sunrise
- Time of day: early morning, approximately 7am warm golden-hour light
- Lighting direction: soft diffused light coming from upper-left of canvas, 
  casting a very subtle warm shadow to the lower-right of the character
- Background (behind character): a lush green forest path stretching into 
  a warm golden-lit clearing in the distance, soft bokeh blur on far trees
- Foreground (in front of character at bottom of canvas): a few small 
  colorful wildflowers and soft green grass, very gently rendered
- Trees frame the left and right edges of the canvas at medium blur
- The path is a soft dirt trail with dappled light patches
- Atmosphere: magical, warm, inviting, dreamy — like the forest is 
  welcoming the child
- Light beams (god rays) subtly visible in the background behind the 
  character, golden and soft
- Color temperature: warm (#FFE8C2 tones in the light), cool forest greens 
  (#4A7C59) in the shadows

STYLE SPECIFICATIONS:
- Pixar Animation Studios render quality — smooth subsurface scattering 
  on character surfaces
- Soft rim lighting on character edges to separate from background
- Shallow depth of field: character is sharp, foreground slightly soft, 
  background at 40–50% blur (bokeh)
- Color palette is cohesive: warm yellows, forest greens, golden tans, 
  soft sky blues
- Illustration style: cinematic children's book, NOT flat 2D, 
  NOT photorealistic — stylized 3D render
- Line quality: no visible outlines — shading defines form (Pixar style)
- Shadows: soft diffuse, no harsh drop shadows
- Mood: magical, safe, warm, joyful, wonder-filled

CRITICAL CONSTRAINTS (must be exact in every scene):
- Blank face oval: ALWAYS at x=512, y=285 center, 164×190px, 
  completely featureless smooth matte skin tone — no exceptions
- Hat: ALWAYS the same golden tan wide-brimmed adventurer hat, 
  same size, same position relative to the face oval
- Character proportions: ALWAYS the same — 380px wide, 720px tall, 
  centered at x=512
- Clothing: ALWAYS yellow t-shirt + sage green shorts/skirt + brown boots
- Pixar style: ALWAYS consistent render quality across all 10 scenes
- Background and scene environment CHANGE per scene, 
  character anatomy NEVER changes
```

---

## Negative Prompt (Stable Diffusion / ComfyUI)

```
facial features, eyes, nose, mouth, eyebrows, eyelashes, pupils, iris, 
lips, teeth, smile, frown, expression, wrinkles, freckles, dimples, 
any face detail, photorealistic face, realistic skin texture on face,
multiple characters, extra limbs, deformed hands, 
ugly, blurry character, low quality, grainy, 
horror, dark, scary, violent, sad, angry, 
adult proportions, realistic proportions, anime style, cartoon flat 2D,
text, watermark, signature, logo, brand, letters, numbers on clothing,
dark background, night scene, indoor scene
```

---

## Character Specification Card (for consistency across all 10 scenes)

| Property | Specification |
|---|---|
| Canvas size | 1024 × 1024 px |
| Character center X | 512 px |
| Character height | ~720 px (y=100 to y=820) |
| Blank face center | (512, 285) |
| Blank face size | 164 × 190 px |
| Blank face top-left | (430, 190) |
| Blank face bottom-right | (594, 380) |
| Face color | Matte #F5D5B8, zero texture |
| Hat style | Wide-brim adventurer/safari |
| Hat color | Golden tan #C8963E |
| Hat brim Y | y=110 to y=195 |
| Hat brim width | ~360 px centered at x=512 |
| Shirt color | Sunny yellow #F4D03F |
| Shorts/skirt color | Sage green #7DAB5A |
| Boots color | Warm brown #8B5E3C |
| Style | Pixar 3D render, soft lighting |
| Depth of field | Character sharp, BG 40–50% blur |

---

## Consistency Anchor Sentence (add to every scene prompt)

Append this to all 10 scene prompts to enforce character consistency:

```
The gender-neutral child character must be identical to the reference: 
same golden tan wide-brimmed hat (brim top at y=110, 360px wide), same 
yellow t-shirt and sage green shorts, same warm brown boots, same blank 
featureless smooth matte peach-beige face oval centered at pixel (512,285) 
measuring exactly 164px wide and 190px tall, same Pixar 3D render style, 
same character proportions and bounding box.
```

---

## Per-Scene Variables (what changes, page by page)

Only these elements should vary between scenes. Everything else is locked:

| Scene | Background | Lighting | Character Pose | Foreground |
|---|---|---|---|---|
| 01 | Forest entrance, golden sunrise, bokeh trees | Warm upper-left golden hour | Walking, right arm reaching forward | Wildflowers, grass path |
| 02 | Forest floor, dappled light | Warm dappled from tree canopy | Crouching slightly, facing rabbit | Small white rabbit on path |
| 03 | Forest canopy looking up, bright sky | Bright warm overhead, soft | Head tilted slightly upward, arms out | Colorful birds on branches |
| 04 | Deep forest clearing | Soft warm diffuse | Standing beside elephant, hand on trunk | Large gentle gray elephant |
| 05 | Forest floor, mossy ground | Calm cool-green ambient | Walking slowly, looking down | Small turtle, tiny flowers |
| 06 | Forest mid-canopy, warm green | Playful dappled light | Arms raised, mid-laugh | Monkey hanging from branch above |
| 07 | Quiet forest glade, evening | Soft blue-gold transition light | Standing still, hands folded | Elegant deer standing close |
| 08 | Forest at dusk, fireflies | Warm ambient with blue sky | Arms slightly out, looking up | Dozens of glowing fireflies |
| 09 | Ancient large tree, warm | Warm wrap-around tree-glow | Hugging large tree trunk | Massive textured tree trunk |
| 10 | Forest edge, path home, dusk | Golden farewell light | Walking away, head slightly back | Forest receding into distance |

---

## Notes for AI Model Integration

**For DALL-E 3 via API:**
The full primary prompt above is used directly. DALL-E 3 does not support 
negative prompts — all constraints are expressed positively in the main prompt.
The phrase "featureless smooth matte peach-beige oval with absolutely no eyes, 
no nose, no mouth" should be emphasized by repeating it in each scene prompt.

**For Stable Diffusion / SDXL:**
Use the primary prompt as positive, the negative prompt block as cfg_negative.
Add `--cfg 8.5 --steps 40 --sampler dpm++_2m_karras` for deterministic results.
Use the same seed across all 10 scenes for maximum character consistency.
Seed recommendation: use a fixed seed (e.g. `seed=42`) and save it.

**For Midjourney:**
Append `--style raw --stylize 750 --ar 1:1 --v 6` to the main prompt.
Save the job seed from scene 01 and use `--seed {seed}` on all subsequent scenes.

**Consistency verification:**
After generation, run the evaluator on each image:
```
python tests/evaluator/run_evaluator.py --local-dir /path/to/generated --dry-run
```
The `face_detected` score should be 0 (blank face — no MediaPipe face found).
The `face_coverage` score measures whether the blank oval fills the expected area.

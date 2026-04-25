# Render Schema (Rendering Layer)

## Purpose
Defines HOW the story is rendered into images.
Consumes story JSON and converts into model-ready configuration.

---

## Structure

```json
{
  "canvas": {},
  "lighting": {},
  "camera": {},
  "consistency": {},
  "overlay_contract": {},
  "face_anchor": {}
}
```

---

## Key Sections

### Canvas
- Resolution
- Aspect ratio

### Lighting
- Key light direction
- Fill light
- Temperature

### Camera
- Angle (eye-level, top, low)
- Lens (35mm, 50mm)
- Depth of field

### Consistency
- character_id
- style_id
- camera_lock
- lighting_lock

### Overlay Contract
- face_required
- occlusion_allowed
- blend_mode
- color_match

### Face Anchor
- Position
- Size
- Rotation constraints

---

## Notes
- Derived from story schema
- Model-specific adjustments allowed
- Ensures visual consistency across pages

# Story JSON Schema (Story Intent Layer)

## Purpose
Defines WHAT the story wants (not how to render it).
This schema is model-agnostic and drives emotion, character behavior, and narrative.

---

## Top-Level Structure

```json
{
  "version": "v1",
  "story_id": "string",
  "title": "string",
  "global": {},
  "pages": []
}
```

---

## Global

```json
"global": {
  "character_id": "string",
  "style": "pixar_soft",
  "age_group": "4-6",
  "gender": "male"
}
```

---

## Page Structure

```json
{
  "page_number": 1,

  "narrative": {
    "scene": "string",
    "summary": "string"
  },

  "character": {
    "present": true,

    "emotion": {
      "type": "happy | curious | sad | excited | scared | calm | determined",
      "intensity": 0.0
    },

    "expression_rules": {
      "dynamic": true,
      "not_from_input_image": true,
      "scene_driven": true
    },

    "body_language": {
      "posture": "string",
      "gesture": "string"
    },

    "head_pose": {
      "yaw": -5,
      "pitch": -2,
      "roll": 0
    },

    "accessories": []
  },

  "environment": {
    "mood": "string",
    "lighting": "string",
    "elements": []
  },

  "text": {
    "content": "string",
    "name_visible": true
  }
}
```

---

## Notes
- No prompt strings allowed
- No rendering-specific constraints
- Emotion drives expression (not input image)
- This feeds the rendering pipeline

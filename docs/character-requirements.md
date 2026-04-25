# StoryMe Character System Requirements

## 1. Objective
Define how user-based characters are generated, controlled, and rendered across story scenes while preserving identity and enabling expressive storytelling.

---

## 2. Core Principles

### 2.1 Identity Preservation
- Character must strongly resemble the uploaded user images (front, left, right).
- Stylization: Pixar-style / cartoonized but identity-consistent.
- Facial structure, hairstyle, skin tone should remain consistent across scenes.

### 2.2 Non-Static Expressions
- Expressions must NOT be:
  - Static
  - Direct copies of uploaded images
- Expressions must be dynamically generated based on story context.

### 2.3 Story-Driven Expression Engine
- Expressions controlled via `story.json`.
- Scene-level tags define emotional state.

#### Example:
```
{
  "scene_id": "forest_entry",
  "emotion": "curious",
  "intensity": 0.6
}
```

Supported emotions:
- happy
- curious
- surprised
- scared
- determined
- sad
- excited
- calm

### 2.4 Facial Behavior Rules
- Eyes, eyebrows, and mouth must adapt to emotion.
- Subtle micro-expressions preferred over exaggerated distortion.
- Avoid uncanny or hyper-real outputs.

---

## 3. Head Pose Constraints

Character may slightly vary orientation:
- Yaw: ±10°
- Pitch: ±8°
- Roll: ±5°

Rules:
- No extreme rotations
- Maintain recognizability
- Adjust only for scene realism

---

## 4. Body Language System

Body posture must align with emotion:

| Emotion     | Body Language |
|------------|--------------|
| Happy      | Open posture, relaxed shoulders |
| Curious    | Slight lean forward |
| Scared     | Slight backward tilt, tense arms |
| Confident  | Upright posture |
| Sad        | Drooped shoulders |

---

## 5. Accessories System

Optional scene-driven accessories:
- Hat
- Helmet
- Sunglasses

Rules:
- Must not obstruct identity
- Should align with story context

Example:
```
"accessories": ["hat"]
```

---

## 6. Character Rendering Rules

- Maintain consistent face anchor positioning
- Preserve proportions across pages
- Avoid identity drift across scenes

---

## 7. Text Rendering Requirements

### 7.1 Character Name
- Must appear clearly in story
- Readable font
- No overlap with face or key visuals

### 7.2 Book Title Format
Format:
```
<Username> and the <Story Name>
```

Example:
```
Nikshay and the Forest of Smiles
```

---

## 8. Scene Control Contract (JSON)

Each scene must support:

```
{
  "scene_id": "string",
  "emotion": "string",
  "intensity": 0-1,
  "head_pose": {
    "yaw": number,
    "pitch": number,
    "roll": number
  },
  "accessories": [],
  "body_language": "string"
}
```

---

## 9. Future Enhancements

- Expression blending (multi-emotion scenes)
- Gesture animation
- Voice + expression sync

---

## 10. Directory Placement

Recommended:
```
/docs/character-requirements.md
```

Related future structure:
```
/docs
  /character
    expression-system.md
    pose-guidelines.md
    accessories.md
  /story
    story-json-schema.md
```

---

## 11. Summary

This system ensures:
- Strong identity retention
- Emotion-driven storytelling
- Controlled variability
- Scalable architecture for StoryMe

---

# Prompt Builder

## Purpose
Transforms story JSON + render schema into final prompts for image generation models.

---

## Inputs
- Story JSON (intent layer)
- Render Schema (render layer)
- Character embeddings (face inputs)

---

## Output
- Final prompt string
- Negative prompt (optional)
- Model parameters

---

## Pipeline

1. Read story page
2. Extract:
   - scene
   - emotion
   - body language
   - environment
3. Map to visual tokens
4. Merge with render schema
5. Inject character identity
6. Generate final prompt

---

## Example Mapping

| Story Field | Prompt Contribution |
|------------|--------------------|
| emotion=happy | smiling expression |
| mood=magical | glowing particles |
| posture=lean_forward | slight forward body tilt |

---

## Rules
- Never copy input face expression
- Always use scene-driven emotion
- Maintain identity consistency
- Keep prompts deterministic when required

---

## Future
- Multi-character support
- Animation prompts
- Voice sync

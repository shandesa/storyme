# StoryMe — Specification Index

This directory contains all feature and fix specifications for StoryMe.
Each spec is numbered sequentially. Specs describe the **what** and **why**;
implementation commits reference the spec number.

---

## Specs

| ID | Title | Status | Branch |
|----|-------|--------|--------|
| [SPEC-002](SPEC-002-image-pipeline-fixes.md) | Image Pipeline Fixes — face overlay, text layout, expression morph | ✅ Implemented | `beta` |
| [SPEC-003](SPEC-003-kid-profiles-and-pdf-persistence.md) | Kid Profiles & PDF Persistence — per-child profiles, resume download after logout | ✅ Implemented | `beta` |
| [SPEC-004](SPEC-004-ai-book-generation.md) | AI-Based Full Book Generation — DALL-E gpt-image-1, global background cache, per-user character pages | 📋 Ready for implementation | `beta` |

---

## Spec Status Key

| Symbol | Meaning |
|--------|---------|
| 📋 | Ready for implementation — approved, awaiting dev |
| 🔨 | In progress |
| ✅ | Implemented and tested |
| 🗄️ | Superseded by a newer spec |

---

## Conventions

- Specs are numbered SPEC-NNN starting at 001.
- Each spec covers one feature area (not individual commits).
- Test cases in the spec are the acceptance criteria for the implementation.
- All specs assume the `beta` branch as the base unless stated otherwise.
- No implementation work is done without a corresponding spec entry.

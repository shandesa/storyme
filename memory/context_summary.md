# StoryMe - Context Summary

## Last Updated: 2026-03-31

## Project Overview
StoryMe is a web application that allows parents to upload a child's photo and enter their name to generate a personalized 10-page storybook PDF. The child's face is detected and cropped using OpenCV Haar Cascades, then composited onto illustrated story templates with inpainting to blend edges. The child's name replaces baked-in `{name}` text on templates.

## Architecture
- **Frontend**: React + Shadcn UI (port 3000)
- **Backend**: FastAPI + PIL/OpenCV (port 8001, routes prefixed with /api)
- **Database**: MongoDB (status checks only, not used for story generation)
- **Storage**: Local filesystem with abstraction layer for future S3 support
- **PDF Generation**: ReportLab

## Current Story: "Forest of Smiles"
- 10 pages, targeting ages 3-6
- Page 1: High-res 1536x1024 illustrated template with:
  - White face circle at center=(985,382), radius=135
  - Header `{name}` text at (146,118)-(259,147)
  - Main text `{name}` at (277,185)-(394,210)
  - Character: brown hair, yellow shirt, slightly down-left orientation
  - Text color: dark brown RGB(134,105,54)
- Pages 2-10: Solid color 612x792 placeholder backgrounds (need real templates)

## Key API Endpoints
- `POST /api/generate`: Accepts multipart form with `name`, `image`, optional `story_id`/`story_index`. Returns PDF.
- `GET /api/stories`: List available stories

## Key Files
- `/app/backend/services/image_service.py`: OpenCV face detection + inpainting + PIL composition + name text replacement
- `/app/backend/services/story_service.py`: Story registry with face/name coordinates per page
- `/app/backend/services/pdf_service.py`: ReportLab PDF generation
- `/app/backend/routes/generate.py`: Main generation API endpoint
- `/app/backend/models/story.py`: Pydantic models (FacePlacement, NamePlacement, FaceCircle, NameTextRegion, Page, Story)
- `/app/backend/core/storage.py`: Storage abstraction (Local + S3 stub)
- `/app/backend/core/config.py`: Configuration management
- `/app/frontend/src/App.js`: React frontend with form, upload, and download
- `/app/prompts/face_personalization_prompt.md`: Reusable face personalization pipeline prompt

## Completed Work

### Session 1 (Previous Agent)
- FastAPI and React project initialization with Shadcn UI
- Basic MVP PDF generation with ReportLab
- Playwright E2E integration tests & Python backend tests
- Refactoring to Clean Architecture with storage abstraction
- Creation of face_personalization_pipeline.py (reference)
- Fix for Microsoft Edge download issue
- Repository documentation/READMEs

### Session 2 (2026-03-31)
- Integrated OpenCV Haar Cascade face detection into image_service.py
- Added `angle` field to FacePlacement model for face rotation support
- Added `NamePlacement`, `FaceCircle`, `NameTextRegion` models
- OpenCV inpainting to fill white face circle with neighboring pixels
- Advanced face compositing: tight face crop (10% padding), feathered oval mask (8% blur), 92% circle fill
- Full-line text replacement: inpaints entire text line, re-renders with {name} replaced
- Auto font sizing based on line height for natural text matching
- Saved reusable face personalization prompt to `/app/prompts/`
- All tests passing

## Image Input Recommendations
For best results, users should upload:
- **Clear, front-facing photo** of the child's face
- Good lighting, minimal shadows
- Face should be reasonably centered and take up at least 20% of the image
- Supported formats: JPG, PNG, WEBP (max 5MB)
- Both portrait and landscape orientations work (OpenCV detects faces in any orientation)
- Fallback: if no face is detected, center-crops the image

## Testing Status (2026-03-31)
- Backend: 100% (iteration_2: 15/15, iteration_3: 8/8 tests passed)
- Frontend: 100% (all UI flows working)
- Test reports: `/app/test_reports/iteration_2.json`, `/app/test_reports/iteration_3.json`

## Known Limitations
- Pages 2-10 are solid-color placeholder backgrounds (not real illustrated templates)
- Lower text block on page 1 may have additional `{name}` occurrence not yet handled
- Face detection needs a real photo; falls back to center-crop for synthetic images
- S3 storage is stubbed
- No ML-based stylization yet

## Pending Tasks
- P1: Check if lower text block on page 1 has `{name}` to replace
- P2: Replace placeholder templates (pages 2-10) with real illustrations
- P2: Implement actual S3 storage
- P2: Add ML-based face stylization (Pixar-like cartoon effect)

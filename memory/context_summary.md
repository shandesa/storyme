# StoryMe - Context Summary

## Last Updated: 2026-03-31

## Project Overview
StoryMe is a web application that allows parents to upload a child's photo and enter their name to generate a personalized 10-page storybook PDF. The child's face is detected and cropped using OpenCV Haar Cascades, then composited onto illustrated story templates. The child's name is overlaid on each page.

## Architecture
- **Frontend**: React + Shadcn UI (port 3000)
- **Backend**: FastAPI + PIL/OpenCV (port 8001, routes prefixed with /api)
- **Database**: MongoDB (used for status checks, not for story generation)
- **Storage**: Local filesystem with abstraction layer for future S3 support
- **PDF Generation**: ReportLab

## Current Story: "Forest of Smiles"
- 10 pages, targeting ages 3-6
- Page 1: High-res 1536x1024 illustrated template
- Pages 2-10: Solid color 612x792 placeholder backgrounds (need real templates)
- Each page has face placement coordinates and name placement coordinates

## Key API Endpoints
- `POST /api/generate`: Accepts multipart form with `name`, `image`, optional `story_id`/`story_index`. Returns PDF.
- `GET /api/stories`: List available stories

## Key Files
- `/app/backend/services/image_service.py`: OpenCV face detection + PIL composition
- `/app/backend/services/story_service.py`: Story registry with face/name coordinates per page
- `/app/backend/services/pdf_service.py`: ReportLab PDF generation
- `/app/backend/routes/generate.py`: Main generation API endpoint
- `/app/backend/models/story.py`: Pydantic models (FacePlacement, NamePlacement, Page, Story)
- `/app/backend/face_personalization_pipeline.py`: Standalone pipeline (reference, not wired into API)
- `/app/backend/core/storage.py`: Storage abstraction (Local + S3 stub)
- `/app/backend/core/config.py`: Configuration management
- `/app/frontend/src/App.js`: React frontend with form, upload, and download

## Completed Work

### Session 1 (Previous Agent)
- FastAPI and React project initialization with Shadcn UI
- Basic MVP PDF generation with ReportLab
- Playwright E2E integration tests & Python backend tests
- Refactoring to Clean Architecture with storage abstraction
- Creation of face_personalization_pipeline.py (unintegrated)
- Fix for Microsoft Edge download issue
- Repository documentation/READMEs

### Session 2 (Current Agent - 2026-03-31)
- Integrated OpenCV Haar Cascade face detection into image_service.py
- Added `angle` field to FacePlacement model for face rotation support
- Added `NamePlacement` model with per-page name coordinates, font_size, and color
- Updated story_service.py with proper coordinates for all 10 pages
- Updated generate.py to use name/face placements from the story registry
- Removed hardcoded name position logic from generate.py
- Verified API returns valid PDF (5MB, all 10 pages)

## Known Limitations
- Pages 2-10 are solid-color placeholder backgrounds (not real illustrated templates)
- Face detection needs a real photo to work; falls back to center-crop for synthetic/non-face images
- S3 storage is stubbed (not implemented)
- No ML-based stylization yet (Pixar-like effect exists in pipeline but not integrated)

## Pending Tasks
- P0: Test with real face photos to verify detection accuracy
- P0: Verify face position and name text rendering on all 10 pages visually
- P2: Replace placeholder templates (pages 2-10) with real illustrations
- P2: Implement actual S3 storage
- P2: Add ML-based face stylization

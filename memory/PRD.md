# StoryMe - Product Requirements Document

## Original Problem Statement
Build "StoryMe", a simple but well-structured MVP web application that allows a parent to upload a child's photo and enter their name to generate a personalized 10-page storybook (PDF). The app requires a FastAPI backend and a React frontend. The system needs to map the child's face and name onto predefined illustration templates.

## User Personas
- **Parent**: Uploads child's photo, enters name, downloads personalized PDF storybook

## Core Requirements
1. Upload child's photo (JPG/PNG/WEBP, max 5MB)
2. Enter child's name
3. Generate 10-page personalized storybook PDF
4. Face detection and extraction using OpenCV Haar Cascades
5. Face composited onto story template pages inside white circle placeholder
6. White circle area inpainted with neighboring pixels for seamless blending
7. Baked-in `{name}` text on templates replaced with actual child's name
8. PDF download with all 10 pages

## Architecture
- Frontend: React + Shadcn UI
- Backend: FastAPI + PIL/OpenCV + ReportLab
- Storage: Local filesystem (S3 abstraction ready)
- No auth required

## What's Been Implemented
- [x] React frontend with upload form and PDF download (Session 1)
- [x] FastAPI backend with clean architecture (Session 1)
- [x] Storage abstraction layer (Local + S3 stub) (Session 1)
- [x] Story registry with page coordinates (Session 1, updated Session 2)
- [x] OpenCV face detection integrated into image_service.py (Session 2)
- [x] Face rotation support via angle field (Session 2)
- [x] OpenCV inpainting for white circle blending (Session 2)
- [x] Advanced face compositing: sized to 88% circle, feathered mask (Session 2)
- [x] Multiple NameTextRegion support per page (Session 2)
- [x] Inpainting-based {name} text replacement with auto-sized font (Session 2)
- [x] Reusable face personalization prompt saved (Session 2)
- [x] Full test coverage (backend + frontend, 3 iterations) (Session 2)

## Backlog
- P1: Verify lower text block on page 1 for additional {name} occurrences
- P2: Replace placeholder templates (pages 2-10) with real illustrations
- P2: Implement S3 storage backend
- P2: ML-based face stylization (Pixar-like cartoon effect)
- P2: Add more story themes beyond "Forest of Smiles"

# SPEC-004 — AI-Based Full Book Generation (DALL-E gpt-image-1)

**Document ID:** SPEC-004  
**Version:** 2.0  
**Date:** 2026-05-02  
**Status:** Implemented  

## Changes v1→v2: 18-page structure; DALL-E seed; in-image PIL text; name substitution on BG pages.

## Book: 18 pages
- Page 0: front cover (cover_image_gen.py placeholder)
- Pages 1-16: story pages from forest_of_smiles_v8_final.json
  - Character (face overlay): 1,3,5,7,9,11,13,15,16
  - Background (global cache): 2,4,6,8,10,12,14
  - Placeholders: 1, 16 (reserved for final artwork)
- Page 17: back cover (cover_image_gen.py placeholder)

## Phases
- Phase 0: cover_image_gen.generate_front/back_cover()
- Phase 1: BG pages — check AIBackgroundPages (prompt_hash), DALL-E gen if miss, PIL text+name
- Phase 2: Char p01 — images.edit(user_photo, seed=S) → GPT-4o coords → PIL text → face blend
- Phase 3: Char p3-16 — images.edit(page_1_raw, seed=S) → GPT-4o coords → PIL text → face blend
- Phase 4: PDF 18 pages → upload → GeneratedBook

## Seed
- Character pages: random 32-bit per generation_id (same seed all 9 pages)
- Background pages: STORY_BACKGROUND_SEED=42_000_000 (fixed, ensures BG consistency)

## Text rendering (ai_text_renderer.py)
- Right-side zone: x=634, y=65, w=368, h=687 (or GPT-4o extracted text_area)
- PIL: white 28pt bold, dark outline, auto-size down to 14pt
- {name} replaced with child_name before render
- BG pages: render on cached image copy (global cache never modified)
- Char pages: render AFTER face blend; face_pipeline called with story_lines=[]

## Azure Tables
- AIBackgroundPages: PK=story_id, RK=page_number — global, generated once
- AICharacterPages:  PK=generation_id, RK=page_number — per generation

## Storage paths (added to storage_paths.py)
- ai-pages/background/{story_id}/v{version}/page_{NN}.png
- ai-pages/character/{gen_id}/page_{NN}_raw.png
- ai-pages/character/{gen_id}/page_{NN}_final.png
- ai-pages/background-final/{gen_id}/page_{NN}.png

## API
- POST /api/v2/generate/ai-book (new)
- GET  /api/v2/ai-book/cache-status (new)
- Status/download: reuses existing /api/v2/generate/status|download

## Cost: ~$0.45/user (9 char × $0.04 + 9 × $0.01 GPT-4o vision)

## Files
- backend/core/storage_paths.py — modified (4 path functions)
- backend/core/ai_page_store.py — NEW
- backend/services/ai_text_renderer.py — NEW
- backend/services/ai_book_service.py — NEW
- backend/routes/ai_generate.py — NEW
- backend/server.py — modified (router registered)
- frontend/src/pages/HomePage.jsx — modified (AI Book mode)

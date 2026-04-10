"""V2 Generation API Routes

POST /api/v2/stories         — list available stories
POST /api/v2/generate/preview — upload face, generate page 1 preview
POST /api/v2/generate/proceed/{session_id} — generate all + PDF
GET  /api/v2/generate/status/{session_id}  — poll progress
GET  /api/v2/generate/download/{session_id} — download PDF
GET  /api/v2/generate/preview-image/{session_id} — preview image
"""

import os
import uuid
import base64
import logging
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse

from services.generation_service import generation_service
from core.storage import storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["generate_v2"])

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Background tasks tracking
_background_tasks = {}


@router.get("/stories")
async def list_stories():
    """List all available stories."""
    stories = generation_service.list_stories()
    return {"stories": stories}


@router.post("/generate/preview")
async def generate_preview(
    name: str = Form(...),
    image: UploadFile = File(...),
    story_id: str = Form("forest_of_smiles"),
):
    """Upload face photo and generate a preview of page 1."""
    if not name or not name.strip():
        raise HTTPException(400, "Child's name is required")
    if not image:
        raise HTTPException(400, "Image file is required")

    allowed = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
    if image.content_type not in allowed:
        raise HTTPException(400, f"Invalid file type: {image.content_type}")

    # Save uploaded file
    ext = Path(image.filename).suffix or ".jpg"
    upload_path = str(UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}")
    content = await image.read()
    with open(upload_path, "wb") as f:
        f.write(content)

    # Stateless preview generation (NO Mongo)
    preview_path = await generation_service.generate_preview_stateless(
        child_name=name.strip(),
        story_id=story_id,
        face_image_path=upload_path,
    )
    # Generate preview (page 1) — this is synchronous since user waits
    try:
        preview_path = await generation_service.generate_preview(session_id)

        # Return preview as base64 for display
        with open(preview_path, "rb") as f:
            img_bytes = f.read()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")

        return {
            "preview_image": f"data:image/png;base64,{img_b64}",

    except Exception as e:
        logger.error(f"Preview generation failed: {e}", exc_info=True)
        raise HTTPException(500, f"Preview generation failed: {str(e)}")


async def _run_generation(session_id: str):
    """Background task to generate all pages."""
    try:
        await generation_service.generate_all_pages(session_id)
    except Exception as e:
        logger.error(f"Background generation failed for {session_id}: {e}")


@router.post("/generate/proceed/{session_id}")
async def proceed_generation(session_id: str, background_tasks: BackgroundTasks):
    """Start generating all remaining pages in background."""
    session = await generation_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session["status"] not in ("preview_ready", "failed"):
        raise HTTPException(400, f"Cannot proceed from status: {session['status']}")

    # Start background generation
    background_tasks.add_task(_run_generation, session_id)

    return {
        "session_id": session_id,
        "status": "generating",
        "message": "Generation started. Poll /status for progress.",
    }


@router.get("/generate/status/{session_id}")
async def get_status(session_id: str):
    """Get generation progress."""
    session = await generation_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    return {
        "session_id": session_id,
        "status": session["status"],
        "progress": session.get("progress", 0),
        "total_pages": session.get("total_pages", 0),
        "pdf_ready": session["status"] == "complete" and session.get("pdf_path") is not None,
        "error": session.get("error"),
    }


@router.get("/generate/download/{session_id}")
async def download_pdf(session_id: str):
    """Download the generated PDF."""
    session = await generation_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session["status"] != "complete" or not session.get("pdf_path"):
        raise HTTPException(400, "PDF not ready yet")

    pdf_path = session["pdf_path"]
    if not Path(pdf_path).exists():
        raise HTTPException(404, "PDF file not found on disk")

    filename = f"{session['child_name'].replace(' ', '_')}_storybook.pdf"
    return FileResponse(
        path=pdf_path,
        filename=filename,
        media_type="application/pdf",
    )


@router.get("/generate/preview-image/{session_id}")
async def get_preview_image(session_id: str):
    """Get the preview image for a session."""
    session = await generation_service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if not session.get("preview_path"):
        raise HTTPException(400, "Preview not ready")

    preview_path = session["preview_path"]
    if not Path(preview_path).exists():
        raise HTTPException(404, "Preview image not found")

    return FileResponse(path=preview_path, media_type="image/png")

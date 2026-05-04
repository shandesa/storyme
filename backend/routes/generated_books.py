"""
routes/generated_books.py
==========================
Generated book retrieval and download-tracking endpoints.

Endpoints:
  GET  /api/v2/books/pending-downloads           → resume banner: undownloaded PDFs
  GET  /api/v2/books/{book_id}/download          → download PDF + increment counter
  POST /api/v2/books/{book_id}/downloaded        → explicit download acknowledgement

Auth: all endpoints require a valid JWT.
"""

from __future__ import annotations

import io
import logging
import tempfile
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse

from core.session_tokens import require_mobile_from_request
from core.generated_book_store import (
    get_book, list_pending_downloads, increment_download_count,
)
from core.kid_profile_store import get_profile
from core.storage import storage
from core.config import config
from services.story_json_service import story_json_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/books", tags=["generated_books"])


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _resolve_pdf(pdf_blob_path: str, pdf_filename: str) -> str:
    """
    Return a local filesystem path to the PDF.
    For local storage: path is directly on disk.
    For Azure: download blob to a temp file and return its path.
    Raises FileNotFoundError if the blob is not found.
    """
    if config.STORAGE_TYPE == "local":
        local = storage.get_file_path(pdf_blob_path)
        if not Path(local).exists():
            raise FileNotFoundError(f"PDF not on disk: {local}")
        return local

    # Azure / remote — download to temp file
    data = storage.read_file(pdf_blob_path)
    suffix = Path(pdf_filename or "storybook.pdf").suffix or ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


def _book_to_pending_response(book: dict, mobile: str) -> dict:
    """Build the pending-download response object for a single book."""
    profile_name = ""
    profile_id   = book.get("profile_id", "")
    if profile_id:
        profile = get_profile(mobile, profile_id)
        if profile:
            profile_name = profile.get("name", "")

    story_id    = book.get("story_id", "")
    story_title = book.get("child_name", "")
    try:
        story = story_json_service.get_story(story_id)
        if story:
            story_title = story.title.replace("{name}", book.get("child_name", ""))
    except Exception:
        pass

    book_id = book.get("book_id", "")
    return {
        "book_id":      book_id,
        "profile_id":   profile_id,
        "profile_name": profile_name,
        "story_id":     story_id,
        "story_title":  story_title,
        "child_name":   book.get("child_name", ""),
        "completed_at": book.get("completed_at", ""),
        "download_url": f"/api/v2/books/{book_id}/download",
    }


# ─── GET /api/v2/books/pending-downloads ─────────────────────────────────────

@router.get("/pending-downloads")
async def pending_downloads(request: Request):
    """
    Return books that are complete but have never been downloaded.
    Used by the home page to show the Resume Banner on login.
    Returns at most 10 results, ordered by completion time (newest first).
    """
    mobile = require_mobile_from_request(request)
    books  = list_pending_downloads(mobile)
    return {
        "books": [_book_to_pending_response(b, mobile) for b in books],
        "count": len(books),
    }


# ─── GET /api/v2/books/{book_id}/download ────────────────────────────────────

@router.get("/{book_id}/download")
async def download_book(book_id: str, request: Request):
    """
    Download the generated PDF for a book.
    Serves the file as application/pdf with Content-Disposition: attachment.
    Increments download_count after serving.
    """
    mobile = require_mobile_from_request(request)
    book   = get_book(mobile, book_id)

    if not book:
        raise HTTPException(status_code=404, detail="Book not found.")
    if book.get("status") != "complete":
        raise HTTPException(
            status_code=409,
            detail=f"PDF not ready yet (status={book.get('status', 'unknown')}). "
                   "Please wait for generation to complete.",
        )

    pdf_blob_path = book.get("pdf_blob_path", "")
    pdf_filename  = book.get("pdf_filename", "") or "storybook.pdf"

    if not pdf_blob_path:
        raise HTTPException(
            status_code=409,
            detail="PDF blob path is empty — generation may have failed to upload.",
        )

    # Resolve to local path
    is_temp = False
    try:
        local_path = _resolve_pdf(pdf_blob_path, pdf_filename)
        # If _resolve_pdf downloaded to a temp file, mark for cleanup
        is_temp = (config.STORAGE_TYPE != "local")
    except (FileNotFoundError, Exception) as exc:
        logger.error("download_book: cannot resolve PDF %s: %s", pdf_blob_path, exc)
        raise HTTPException(status_code=404, detail="PDF file not found in storage.")

    # Increment download counter
    increment_download_count(mobile, book_id)

    child_name = book.get("child_name", "child")
    safe_name  = child_name.lower().replace(" ", "_")
    download_filename = pdf_filename or f"{safe_name}_storybook.pdf"

    logger.info(
        "Book download: book_id=%s user=%s file=%s",
        book_id[:8], mobile, download_filename,
    )

    if is_temp:
        # Read into memory and delete temp file
        data = Path(local_path).read_bytes()
        try:
            os.unlink(local_path)
        except Exception:
            pass
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{download_filename}"',
                "Content-Length": str(len(data)),
            },
        )

    return FileResponse(
        path=local_path,
        media_type="application/pdf",
        filename=download_filename,
        headers={"Content-Disposition": f'attachment; filename="{download_filename}"'},
    )


# ─── POST /api/v2/books/{book_id}/downloaded ─────────────────────────────────

@router.post("/{book_id}/downloaded")
async def acknowledge_download(book_id: str, request: Request):
    """
    Frontend calls this after a successful download initiation to ensure
    the download_count is incremented even if the GET /download route's
    increment failed (e.g. network error mid-stream).
    Idempotent — safe to call multiple times.
    """
    mobile = require_mobile_from_request(request)
    book   = get_book(mobile, book_id)

    if not book:
        raise HTTPException(status_code=404, detail="Book not found.")

    ok = increment_download_count(mobile, book_id)
    if not ok:
        logger.warning("acknowledge_download: increment failed for book %s", book_id[:8])

    updated = get_book(mobile, book_id)
    return {
        "book_id":        book_id,
        "download_count": updated.get("download_count", 1) if updated else 1,
    }

"""
routes/generate_async.py
=========================
Background PDF generation API — lets the frontend start a generation job
immediately after preview approval and poll for completion, so the user can
browse fulfilment options while the PDF is being produced.

Endpoints:
    POST /api/v2/generate/async                 Start background generation
    GET  /api/v2/generate/status/{gen_id}       Poll job status
    GET  /api/v2/generate/download/{gen_id}     Download completed PDF
    POST /api/v2/generate/email/{gen_id}        Send completed PDF to email

IMPORTANT — no regression:
    The existing synchronous /api/generate (v1) and /api/v2/generate/preview
    endpoints are NOT modified. This file adds new endpoints only.

Generation lifecycle (recorded in GenerationSessions table):
    queued → generating → complete | failed
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.config import config
from core.session_store import session_store
from core.session_tokens import get_mobile_from_request
from core.storage import storage
from core.storage_paths import upload_path as make_upload_path, pdf_path as make_pdf_path
from core.kid_profile_store import get_profile as get_kid_profile
from core.generated_book_store import upsert_book, find_book

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["generate_async"])

# Generation times out if still "generating" after this many seconds
_GENERATION_TIMEOUT_SECONDS = 900   # 15 minutes

# ─── In-memory job tracker (per-process, survives server restart via session_store) ──
_active_jobs: dict[str, dict] = {}


def _safe_name(s: str) -> str:
    s = re.sub(r"[^\w\-]", "_", s.strip().lower())
    return re.sub(r"_+", "_", s).strip("_")[:64] or "child"


# ─── POST /api/v2/generate/async ─────────────────────────────────────────────

@router.post("/generate/async")
async def start_async_generation(
    request:    Request,
    name:       str                  = Form(...),
    image:      Optional[UploadFile] = File(default=None),
    story_id:   str                  = Form("forest_of_smiles"),
    mode:       str                  = Form("opencv"),
    gender:     str                  = Form("neutral"),
    profile_id: Optional[str]        = Form(default=None),
):
    """
    Start a background PDF generation job.

    Returns immediately with a generation_id. The client should poll
    GET /api/v2/generate/status/{generation_id} until status = "complete".

    Either profile_id OR image must be provided (not both required):
      - profile_id: use the kid profile's stored photo (no re-upload needed)
      - image:      legacy ad-hoc upload (unchanged behaviour)
    """
    # Extract user mobile (optional — anonymous generation still allowed)
    user_mobile = get_mobile_from_request(request)

    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Child's name is required")

    child_name = name.strip()
    gen_id     = uuid.uuid4().hex
    now        = datetime.now(timezone.utc).isoformat()

    if profile_id and user_mobile:
        # ── Profile-based generation: use stored photo, no re-upload ──────────
        profile = get_kid_profile(user_mobile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Kid profile not found.")
        if not profile.get("photo_blob_path"):
            raise HTTPException(
                status_code=400,
                detail="This profile has no photo. Please add a photo to the profile first.",
            )
        # Use profile's name and gender (override form values)
        child_name = profile["name"]
        gender     = profile.get("gender", gender)
        local_image_path = _resolve_local_path(profile["photo_blob_path"])
        logger.info(
            "Async generation (profile): gen_id=%s profile=%s child=%r",
            gen_id[:8], profile_id[:8], child_name,
        )

    elif image and image.filename:
        # ── Legacy ad-hoc upload ─────────────────────────────────────────────
        if image.content_type not in config.ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: {', '.join(config.ALLOWED_IMAGE_TYPES)}",
            )
        ext              = Path(image.filename or "upload.jpg").suffix or ".jpg"
        uploaded_path    = make_upload_path(ext, gen_id)
        storage.save_file(image.file, uploaded_path)
        local_image_path = _resolve_local_path(uploaded_path)
        logger.info(
            "Async generation (upload): gen_id=%s child=%r",
            gen_id[:8], child_name,
        )

    else:
        raise HTTPException(
            status_code=400,
            detail="Either profile_id (for a saved profile) or an image upload is required.",
        )

    # Write initial session — status "generating"
    session_dict = {
        "generation_id":  gen_id,
        "child_name":     child_name,
        "story_id":       story_id,
        "gender":         gender,
        "generation_mode": mode,
        "status":         "generating",
        "pdf_blob_path":  "",
        "pdf_filename":   "",
        "pages_succeeded": 0,
        "pages_failed":   0,
        "total_pages":    0,
        "completed_at":   "",
        "created_at":     now,
        "page_results":   [],
    }
    try:
        await session_store.write_session(session_dict)
    except Exception as e:
        logger.warning("Failed to write initial session for %s: %s", gen_id[:8], e)

    # Track in-memory
    _active_jobs[gen_id] = {
        "status":      "generating",
        "started_at":  now,
        "child_name":  child_name,
        "story_id":    story_id,
        "profile_id":  profile_id or "",
        "user_mobile": user_mobile or "",
    }

    # Fire background task
    asyncio.create_task(
        _run_generation_task(
            gen_id=gen_id,
            child_name=child_name,
            local_image_path=local_image_path,
            story_id=story_id,
            mode=mode,
            gender=gender,
            profile_id=profile_id or "",
            user_mobile=user_mobile or "",
        )
    )

    logger.info(
        "Async generation started: gen_id=%s child=%r story=%s mode=%s gender=%s",
        gen_id[:8], child_name, story_id, mode, gender,
    )

    return {
        "generation_id":        gen_id,
        "status":               "generating",
        "child_name":           child_name,
        "story_id":             story_id,
        "estimated_seconds":    75,
    }


# ─── GET /api/v2/generate/status/{gen_id} ─────────────────────────────────────

@router.get("/generate/status/{generation_id}")
async def get_generation_status(generation_id: str):
    """
    Poll generation status.

    Returns:
        {
            generation_id, status, child_name, story_id,
            total_pages, pages_succeeded, pdf_blob_path,
            elapsed_seconds, timed_out
        }

    status values: "generating" | "complete" | "failed"
    """
    # Check in-memory first (fastest path while job is running)
    mem = _active_jobs.get(generation_id)

    session = None
    try:
        session = await session_store.read_session(generation_id)
    except Exception as e:
        logger.warning("Status read_session %s: %s", generation_id[:8], e)

    if not session and not mem:
        raise HTTPException(
            status_code=404,
            detail=f"Generation session '{generation_id[:8]}' not found.",
        )

    status = (session or {}).get("status") or (mem or {}).get("status", "generating")

    # Detect stuck jobs (server restart / crash during generation)
    timed_out = False
    created_at_str = (session or {}).get("created_at", "") or (mem or {}).get("started_at", "")
    if status == "generating" and created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - created_at).total_seconds()
            if age > _GENERATION_TIMEOUT_SECONDS:
                status    = "failed"
                timed_out = True
                # Update session so future polls don't recalculate
                await session_store.update_session(generation_id, {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
        except Exception:
            pass

    return {
        "generation_id":   generation_id,
        "status":          status,
        "child_name":      (session or {}).get("child_name")    or (mem or {}).get("child_name", ""),
        "story_id":        (session or {}).get("story_id")      or (mem or {}).get("story_id", ""),
        "total_pages":     int((session or {}).get("total_pages", 0)),
        "pages_succeeded": int((session or {}).get("pages_succeeded", 0)),
        "pdf_blob_path":   (session or {}).get("pdf_blob_path", ""),
        "pdf_filename":    (session or {}).get("pdf_filename", ""),
        "timed_out":       timed_out,
    }


# ─── GET /api/v2/generate/download/{gen_id} ───────────────────────────────────

@router.get("/generate/download/{generation_id}")
async def download_generated_pdf(generation_id: str):
    """
    Download the completed PDF for a generation session.

    Returns a FileResponse (application/pdf).
    Only available when status = "complete".
    """
    session = None
    try:
        session = await session_store.read_session(generation_id)
    except Exception as e:
        logger.warning("download read_session %s: %s", generation_id[:8], e)

    if not session:
        raise HTTPException(status_code=404, detail="Generation session not found.")

    if session.get("status") != "complete":
        raise HTTPException(
            status_code=409,
            detail=f"PDF not ready yet (status={session.get('status', 'unknown')}). "
                   "Poll /api/v2/generate/status until status=complete.",
        )

    pdf_path = _find_pdf(session)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF file not found on server.")

    child_name = session.get("child_name", "child")
    filename   = session.get("pdf_filename") or f"{_safe_name(child_name)}_storybook.pdf"

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── POST /api/v2/generate/email/{gen_id} ─────────────────────────────────────

class SendEmailBody(BaseModel):
    email:    str
    order_id: Optional[str] = None


@router.post("/generate/email/{generation_id}")
async def send_generated_pdf_email(generation_id: str, body: SendEmailBody):
    """
    Send the completed PDF to an email address.

    If the generation is still in progress, this endpoint queues the email
    to be sent once the PDF is ready (polls internally for up to 10 minutes).

    Body:
        { "email": "user@example.com", "order_id": "optional" }
    """
    if not body.email or "@" not in body.email:
        raise HTTPException(status_code=400, detail="A valid email address is required.")

    session = None
    try:
        session = await session_store.read_session(generation_id)
    except Exception as e:
        logger.warning("email read_session %s: %s", generation_id[:8], e)

    if not session:
        raise HTTPException(status_code=404, detail="Generation session not found.")

    status = session.get("status", "generating")

    if status == "failed":
        raise HTTPException(status_code=409, detail="PDF generation failed — cannot send email.")

    # Fire-and-forget: wait for completion then email
    asyncio.create_task(
        _wait_and_send_email(
            generation_id=generation_id,
            email=body.email,
            order_id=body.order_id,
        )
    )

    return {
        "accepted":       True,
        "generation_id":  generation_id,
        "email":          body.email,
        "message": (
            "Email queued. If your PDF is still generating it will be "
            "sent automatically when complete (usually within 2 minutes)."
        ),
    }


# ─── Background task helpers ──────────────────────────────────────────────────

async def _run_generation_task(
    gen_id: str,
    child_name: str,
    local_image_path: str,
    story_id: str,
    mode: str,
    gender: str,
    profile_id: str = "",
    user_mobile: str = "",
) -> None:
    """Async wrapper — runs synchronous generation in thread executor."""
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            _generate_sync,
            gen_id, child_name, local_image_path, story_id, mode, gender,
        )
        # ── Write session from async context (thread cannot call async code) ──
        updates = result.get("updates")
        if updates:
            try:
                await session_store.update_session(gen_id, updates)
            except Exception as _se:
                logger.warning("Session update failed for %s: %s", gen_id[:8], _se)

        # ── Save GeneratedBook record if profile-based generation ─────────────
        if profile_id and user_mobile and result.get("status") == "complete":
            try:
                now_iso  = datetime.now(timezone.utc).isoformat()
                existing = find_book(user_mobile, profile_id, story_id)
                book_id  = existing["book_id"] if existing else uuid.uuid4().hex
                book_upd = updates or {}
                upsert_book(user_mobile, {
                    "book_id":             book_id,
                    "user_mobile":         user_mobile,
                    "profile_id":          profile_id,
                    "story_id":            story_id,
                    "generation_id":       gen_id,
                    "child_name":          child_name,
                    "pdf_blob_path":       book_upd.get("pdf_blob_path", ""),
                    "pdf_filename":        book_upd.get("pdf_filename", ""),
                    "status":              "complete",
                    "download_count":      0,
                    "first_downloaded_at": "",
                    "created_at":          existing["created_at"] if existing else now_iso,
                    "completed_at":        now_iso,
                })
                logger.info(
                    "GeneratedBook saved: book_id=%s profile=%s story=%s",
                    book_id[:8], profile_id[:8], story_id,
                )
            except Exception as _be:
                logger.error("Failed to save GeneratedBook for %s: %s", gen_id[:8], _be)

        if gen_id in _active_jobs:
            _active_jobs[gen_id]["status"] = result["status"]
        logger.info(
            "Async generation done: gen_id=%s status=%s pages=%d/%d",
            gen_id[:8], result["status"],
            result.get("pages_succeeded", 0), result.get("total_pages", 0),
        )
    except Exception as e:
        logger.error("Async generation CRASHED gen_id=%s: %s", gen_id[:8], e, exc_info=True)
        if gen_id in _active_jobs:
            _active_jobs[gen_id]["status"] = "failed"
        try:
            await session_store.update_session(gen_id, {
                "status": "failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass


def _generate_sync(
    gen_id: str,
    child_name: str,
    local_image_path: str,
    story_id: str,
    mode: str,
    gender: str,
) -> dict:
    """
    Synchronous generation using face_pipeline_service (yesterday's changes).

    Pipeline per page:
      Character pages  → FacePipelineService.process_character_page()
        Steps: MediaPipe align → roll correction → pose warp → expression morph
               → LAB colour match → seamlessClone → PIL text overlay
      Text-only pages  → FacePipelineService.process_text_only_page()
        Steps: copy template → PIL text overlay

    Config source: data/stories/{story_id}.json via StoryJsonService
    Template source: cache/dalle/{story_id}/page_NN.png (DALL-E cached art)
    """
    import re as _re
    from pathlib import Path as _Path
    from datetime import datetime as _dt, timezone as _tz

    # ── Startup banner ────────────────────────────────────────────────────
    logger.info(
        "━━━ ASYNC GENERATION START [face_pipeline_service] ━━━ "
        "gen_id=%s | child=%r | story=%s | mode=%s | gender=%s",
        gen_id[:8], child_name, story_id, mode, gender,
    )

    # ── Imports ───────────────────────────────────────────────────────────
    try:
        from services.story_json_service import story_json_service
        from services.face_pipeline_service import face_pipeline_service
        from services.pdf_service import PDFService
        logger.debug("Async gen [pipeline]: all imports OK — using face_pipeline_service")
    except Exception as e:
        logger.error(
            "✗ Async gen IMPORT FAILURE — face_pipeline_service unavailable: %s", e,
            exc_info=True,
        )
        return {
            "status": "failed",
            "error": f"face_pipeline_service import failed: {e}",
            "updates": {
                "status": "failed",
                "completed_at": _dt.now(_tz.utc).isoformat(),
            },
        }

    # ── Load story config from JSON ────────────────────────────────────────
    story = story_json_service.get_story(story_id)
    if not story:
        logger.error("✗ Async gen: story '%s' not found in story_json_service", story_id)
        return {
            "status": "failed",
            "error": f"Story '{story_id}' not found",
            "updates": {
                "status": "failed",
                "completed_at": _dt.now(_tz.utc).isoformat(),
            },
        }

    pdf_svc     = PDFService(str(config.OUTPUT_DIR))
    total_pages = story.total_pages
    char_pages  = len(story.character_pages())
    text_pages  = len(story.text_only_pages())

    logger.info(
        "Async gen: story loaded — title=%r total=%d char=%d text-only=%d",
        story.title, total_pages, char_pages, text_pages,
    )

    pages_data:   list = []
    failed_pages: list = []

    # ── Process each page ─────────────────────────────────────────────────
    for page in story.pages:
        out_local = str(config.OUTPUT_DIR / f"{gen_id}_p{page.page_number:02d}.png")

        if not page.template_path:
            logger.error(
                "✗ Page %d: NO TEMPLATE PATH resolved "
                "(missing from cache/dalle and templates/stories)",
                page.page_number,
            )
            failed_pages.append(page.page_number)
            continue

        if not _Path(page.template_path).exists():
            logger.error(
                "✗ Page %d: template file MISSING on disk: %s",
                page.page_number, page.template_path,
            )
            failed_pages.append(page.page_number)
            continue

        ta = {
            "x": page.text_area.x, "y": page.text_area.y,
            "w": page.text_area.w, "h": page.text_area.h,
        }

        try:
            if page.character_present:
                fc = {
                    "x": page.face_config.x, "y": page.face_config.y,
                    "w": page.face_config.w, "h": page.face_config.h,
                } if page.face_config else {"x": 430, "y": 220, "w": 170, "h": 190}

                hp = {
                    "yaw":   page.head_pose.yaw,
                    "pitch": page.head_pose.pitch,
                    "roll":  page.head_pose.roll,
                } if page.head_pose else {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}

                logger.info(
                    "▶ Page %d/%d [CHARACTER] | template=%s | "
                    "face_config=%s | pose=%s | expression=%s | lines=%d",
                    page.page_number, total_pages,
                    _Path(page.template_path).name,
                    fc, hp, page.expression, len(page.story_lines),
                )

                face_pipeline_service.process_character_page(
                    template_path  = page.template_path,
                    user_face_path = local_image_path,
                    face_config    = fc,
                    pose           = hp,
                    expression     = page.expression or "neutral",
                    story_lines    = page.story_lines,
                    text_area      = ta,
                    child_name     = child_name,
                    output_path    = out_local,
                )
                logger.info(
                    "✅ Page %d: face_pipeline_service.process_character_page DONE → %s",
                    page.page_number, _Path(out_local).name,
                )

            else:
                logger.info(
                    "▶ Page %d/%d [TEXT-ONLY] | template=%s | lines=%d",
                    page.page_number, total_pages,
                    _Path(page.template_path).name, len(page.story_lines),
                )

                face_pipeline_service.process_text_only_page(
                    template_path = page.template_path,
                    story_lines   = page.story_lines,
                    text_area     = ta,
                    child_name    = child_name,
                    output_path   = out_local,
                )
                logger.info(
                    "✅ Page %d: face_pipeline_service.process_text_only_page DONE → %s",
                    page.page_number, _Path(out_local).name,
                )

            pages_data.append({
                "text":        " ".join(page.story_lines),
                "image_path":  out_local,
                "page_number": page.page_number,
            })

        except Exception as pe:
            logger.error(
                "✗ Page %d EXCEPTION in face_pipeline_service: %s",
                page.page_number, pe, exc_info=True,
            )
            failed_pages.append(page.page_number)

    succeeded = len(pages_data)
    logger.info(
        "━━━ PAGE SUMMARY ━━━ gen_id=%s succeeded=%d failed=%d total=%d failed_pages=%s",
        gen_id[:8], succeeded, len(failed_pages), total_pages, failed_pages,
    )
    if succeeded == 0:
        # Do NOT call async code here — we are in a thread executor.
        return {
            "status": "failed",
            "error": "All pages failed",
            "updates": {
                "status": "failed",
                "completed_at": _dt.now(_tz.utc).isoformat(),
            },
        }

    # ── Build PDF ──────────────────────────────────────────────────────────
    logger.info("Async gen: building PDF with %d pages for %r", succeeded, child_name)
    ts           = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
    safe_n       = _re.sub(r"[^\w\-]", "_", child_name.strip().lower())[:32]
    pdf_filename = f"{safe_n}_{ts}_{gen_id[:8]}.pdf"

    pdf_local = pdf_svc.create_storybook_pdf(
        child_name=child_name,
        story_title=story.title,
        pages_data=pages_data,
        output_filename=pdf_filename,
    )

    # ── Upload PDF to blob storage ─────────────────────────────────────────
    blob_pdf_path = None
    if config.STORAGE_TYPE in ("azure", "s3"):
        blob_pdf_path = make_pdf_path(child_name, story.story_id, gen_id)
        try:
            with open(pdf_local, "rb") as fh:
                storage.save_file(fh, blob_pdf_path)
            logger.info("Async gen: PDF uploaded to %s: %s", config.STORAGE_TYPE, blob_pdf_path)
        except Exception as ue:
            logger.warning("Async gen: PDF blob upload failed (non-fatal): %s", ue)
            blob_pdf_path = None

    # ── Update session to complete ─────────────────────────────────────────
    updates = {
        "status":          "complete",
        "pdf_blob_path":   blob_pdf_path or "",
        "pdf_filename":    pdf_filename,
        "pages_succeeded": succeeded,
        "pages_failed":    len(failed_pages),
        "total_pages":     total_pages,
        "completed_at":    _dt.now(_tz.utc).isoformat(),
    }
    # Do NOT call async code here — we are in a thread executor.
    # Return updates dict; _run_generation_task (async) writes to session_store.
    logger.info(
        "━━━ ASYNC GENERATION COMPLETE ━━━ gen_id=%s | pages=%d/%d | pdf=%s | blob=%s",
        gen_id[:8], succeeded, total_pages, pdf_filename, blob_pdf_path or "local-only",
    )
    return {
        "status":          "complete",
        "pages_succeeded": succeeded,
        "total_pages":     total_pages,
        "pdf_filename":    pdf_filename,
        "updates":         updates,
    }


async def _wait_and_send_email(
    generation_id: str,
    email: str,
    order_id: Optional[str],
) -> None:
    """Poll until generation complete, then send PDF email."""
    from services.email_service import email_service

    # Poll up to 10 minutes (600s / 5s interval = 120 attempts)
    for _ in range(120):
        try:
            session = await session_store.read_session(generation_id)
            if not session:
                await asyncio.sleep(5)
                continue
            status = session.get("status", "generating")
            if status == "complete":
                pdf_path = _find_pdf(session)
                if pdf_path:
                    child_name = session.get("child_name", "Your Child")
                    await email_service.send_pdf_email(
                        to=email,
                        child_name=child_name,
                        pdf_path=pdf_path,
                        order_id=order_id,
                    )
                else:
                    logger.error("_wait_and_send_email: PDF not found for gen %s", generation_id[:8])
                return
            if status == "failed":
                logger.error("_wait_and_send_email: generation %s failed — no email sent", generation_id[:8])
                return
        except Exception as e:
            logger.warning("_wait_and_send_email poll error: %s", e)
        await asyncio.sleep(5)

    logger.error("_wait_and_send_email: generation %s timed out — no email sent", generation_id[:8])


# ─── Path resolution helpers ──────────────────────────────────────────────────

def _resolve_local_path(blob_path: str) -> str:
    """Return a local filesystem path for the uploaded file."""
    if config.STORAGE_TYPE == "local":
        return storage.get_file_path(blob_path)
    import tempfile
    data   = storage.read_file(blob_path)
    suffix = Path(blob_path).suffix or ".jpg"
    tmp    = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


def _find_pdf(session: dict) -> Optional[str]:
    """
    Return a local filesystem path to the PDF, trying blob_path first,
    then OUTPUT_DIR fallback by filename.
    """
    blob_path = session.get("pdf_blob_path", "")
    filename  = session.get("pdf_filename",  "")

    if blob_path:
        try:
            if config.STORAGE_TYPE == "local":
                local = storage.get_file_path(blob_path)
                if Path(local).exists():
                    return local
            else:
                data   = storage.read_file(blob_path)
                suffix = Path(blob_path).suffix or ".pdf"
                import tempfile
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.write(data)
                tmp.close()
                return tmp.name
        except Exception as e:
            logger.warning("_find_pdf blob read failed: %s", e)

    if filename:
        local = config.OUTPUT_DIR / filename
        if local.exists():
            return str(local)

    return None

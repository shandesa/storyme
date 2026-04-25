"""
Admin Face Quality Test API
───────────────────────────
POST /api/admin/face-test/run           Submit 4-face test job
GET  /api/admin/face-test/job/{id}      Poll status + results
GET  /api/admin/face-test/image/{job}/{page}/{face}  Serve blended PNG
GET  /api/admin/face-test/stories       List available stories

Auth: X-Admin-Key header (same key as /api/v2/admin/orders).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from services.story_json_service import story_json_service
from services.face_pipeline_service import face_pipeline_service
from services.quality_evaluator import quality_evaluator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-face"])

_ADMIN_KEY = os.environ.get("ADMIN_SECRET_KEY", "")
_JOBS_DIR  = Path(__file__).parent.parent / "output" / "admin_face_tests"
_JOBS_DIR.mkdir(parents=True, exist_ok=True)

# ── In-memory job store (MVP; replace with DB for multi-worker prod) ──────────
_jobs: dict = {}


def _auth(key: Optional[str]) -> None:
    if _ADMIN_KEY and key != _ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")


# ─── List stories ─────────────────────────────────────────────────────────────

@router.get("/face-test/stories")
async def list_stories(x_admin_key: Optional[str] = Header(None)):
    _auth(x_admin_key)
    return {"stories": story_json_service.list_stories()}


# ─── Submit test job ──────────────────────────────────────────────────────────

@router.post("/face-test/run")
async def run_face_test(
    story_id:     str        = Form("forest_of_smiles"),
    face_1:       UploadFile = File(...),
    face_2:       UploadFile = File(...),
    face_3:       UploadFile = File(...),
    face_4:       UploadFile = File(...),
    x_admin_key:  Optional[str] = Header(None),
):
    _auth(x_admin_key)

    story = story_json_service.get_story(story_id)
    if not story:
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}")

    job_id  = uuid.uuid4().hex
    job_dir = _JOBS_DIR / job_id
    job_dir.mkdir(parents=True)

    # Persist uploaded faces
    face_paths: list[str] = []
    for i, upload in enumerate([face_1, face_2, face_3, face_4]):
        ext = Path(upload.filename or "photo.jpg").suffix or ".jpg"
        p   = job_dir / f"face_{i}{ext}"
        p.write_bytes(await upload.read())
        face_paths.append(str(p))

    char_pages = story.character_pages()
    _jobs[job_id] = {
        "job_id":   job_id,
        "status":   "running",
        "story_id": story_id,
        "progress": 0,
        "total":    len(char_pages) * 4,
        "results":  None,
        "error":    None,
    }

    asyncio.create_task(_run_async(job_id, story_id, face_paths, job_dir))
    return {"job_id": job_id, "status": "running", "total_steps": len(char_pages) * 4}


# ─── Job status ───────────────────────────────────────────────────────────────

@router.get("/face-test/job/{job_id}")
async def get_job(job_id: str, x_admin_key: Optional[str] = Header(None)):
    _auth(x_admin_key)

    if job_id in _jobs:
        return _jobs[job_id]

    # Try loading from disk (survives restart)
    rp = _JOBS_DIR / job_id / "report.json"
    if rp.exists():
        return {"job_id": job_id, "status": "done",
                "results": json.loads(rp.read_text())}

    raise HTTPException(status_code=404, detail="Job not found")


# ─── Serve blended images ─────────────────────────────────────────────────────

@router.get("/face-test/image/{job_id}/{page_num}/{face_idx}")
async def get_image(
    job_id:   str,
    page_num: int,
    face_idx: int,
    x_admin_key: Optional[str] = Header(None),
):
    _auth(x_admin_key)
    p = _JOBS_DIR / job_id / f"page_{page_num:02d}_face_{face_idx}.png"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(p), media_type="image/png")


# ─── Background runner ────────────────────────────────────────────────────────

async def _run_async(job_id: str, story_id: str, faces: list, job_dir: Path):
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _run_sync, job_id, story_id, faces, job_dir)
        if job_id in _jobs:
            _jobs[job_id]["status"] = "done"
    except Exception as exc:
        logger.error("Face test job %s failed: %s", job_id, exc, exc_info=True)
        if job_id in _jobs:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"]  = str(exc)


def _run_sync(job_id: str, story_id: str, face_paths: list, job_dir: Path):
    story       = story_json_service.get_story(story_id)
    char_pages  = story.character_pages()
    face_results = []

    done  = 0
    total = len(char_pages) * len(face_paths)

    for fi, face_path in enumerate(face_paths):
        page_evals = []

        for page in char_pages:
            if not page.template_path:
                logger.warning("No template for page %d — skipped", page.page_number)
                continue

            out = str(job_dir / f"page_{page.page_number:02d}_face_{fi}.png")
            fc  = ({"x": page.face_config.x, "y": page.face_config.y,
                    "w": page.face_config.w, "h": page.face_config.h}
                   if page.face_config else {"x": 430, "y": 220, "w": 170, "h": 190})
            hp  = ({"yaw": page.head_pose.yaw, "pitch": page.head_pose.pitch,
                    "roll": page.head_pose.roll}
                   if page.head_pose else {"yaw": 0.0, "pitch": 0.0, "roll": 0.0})

            try:
                face_pipeline_service.process_character_page(
                    template_path  = page.template_path,
                    user_face_path = face_path,
                    face_config    = fc,
                    pose           = hp,
                    expression     = page.expression or "neutral",
                    story_lines    = page.story_lines,
                    text_area      = {"x": page.text_area.x, "y": page.text_area.y,
                                      "w": page.text_area.w, "h": page.text_area.h},
                    child_name     = "TestChild",
                    output_path    = out,
                )
                ev = quality_evaluator.evaluate_image(
                    image_path  = out,
                    face_config = fc,
                    page_number = page.page_number,
                    expression  = page.expression or "neutral",
                )
            except Exception as exc:
                logger.error("Page %d face %d: %s", page.page_number, fi, exc)
                ev = {"page_number": page.page_number, "error": str(exc),
                      "metrics": {}, "issues": [str(exc)], "suggestions": {}}

            ev["image_url"] = (
                f"/api/admin/face-test/image/{job_id}/{page.page_number}/{fi}"
            )
            page_evals.append(ev)

            done += 1
            if job_id in _jobs:
                _jobs[job_id]["progress"] = done
                _jobs[job_id]["total"]    = total

        face_results.append({"face_index": fi, "face_path": face_path, "pages": page_evals})

    report = quality_evaluator.generate_report(story_id, face_results)
    (job_dir / "report.json").write_text(json.dumps(report, indent=2))

    if job_id in _jobs:
        _jobs[job_id]["results"] = report

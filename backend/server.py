"""StoryMe API — Main Application Entry Point
=============================================

STARTUP ORDER (critical):
  1. _install_system_deps  ← MUST be first: installs libgl1, libxcb1, etc.
  2. All other imports     ← cv2/mediapipe will only succeed after step 1
  3. FastAPI app creation
  4. Route registration
  5. ASGI startup event

Do NOT move the _install_system_deps import below any cv2/mediapipe import.
"""

# ── Step 1: Install system dependencies BEFORE any cv2/mediapipe import ───────
# This module runs apt-get at import time to ensure libGL.so.1, libxcb.so.1,
# etc. are present. It is idempotent (skips if already installed) and
# survives any Azure portal Startup Command configuration.
import _install_system_deps  # noqa: F401  (side-effect import, result unused)

# ── Step 2: Standard library ──────────────────────────────────────────────────
import os
import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import List

# ── Step 3: Third-party (no native lib deps) ──────────────────────────────────
from fastapi import FastAPI, APIRouter
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ConfigDict

# ── Step 4: Internal — core config ───────────────────────────────────────────
from core.config import config

# ── Step 5: Routes that never depend on cv2/mediapipe ─────────────────────────
from health_check import router as health_router
from routes.stories import router as stories_router, v2_router as stories_v2_router
from routes.review import router as review_router
from routes.auth import router as auth_router
from routes.print_orders import router as print_orders_router
from routes.user_profile import router as user_profile_router

# ── Admin face quality test (cv2/mediapipe — wrapped defensively) ─────────────
try:
    from routes.admin_face import router as admin_face_router
except Exception as _e:
    admin_face_router = None  # type: ignore[assignment]
    import logging as _log
    _log.warning("admin_face router unavailable: %s", _e)

# ── Step 6: Routes that NEED cv2/mediapipe — wrapped in try/except ────────────
# generate and generate_v2 depend on native libs (cv2, mediapipe, libxcb, libGL).
# _install_system_deps (step 1) installs those libs first, but we still wrap
# these imports defensively so a failure disables only the generation routes
# rather than crashing the entire server.
#
# If import fails here AFTER step 1 ran, it means apt-get itself failed
# (network issue, permission, etc.) — the warning in the startup log will say so.

_generate_v1_import_error: Exception | None = None
try:
    from routes.generate import router as generate_router
except Exception as _e:
    generate_router = None      # type: ignore[assignment]
    _generate_v1_import_error = _e

_generate_v2_import_error: Exception | None = None
try:
    from routes.generate_v2 import router as generate_v2_router
except Exception as _e:
    generate_v2_router = None   # type: ignore[assignment]
    _generate_v2_import_error = _e

_generate_v3_import_error: Exception | None = None
try:
    from routes.generate_v3 import router as generate_v3_router
except Exception as _e:
    generate_v3_router = None   # type: ignore[assignment]
    _generate_v3_import_error = _e

_generate_async_import_error: Exception | None = None
try:
    from routes.generate_async import router as generate_async_router
except Exception as _e:
    generate_async_router = None  # type: ignore[assignment]
    _generate_async_import_error = _e

# ─────────────────────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB — lazy connection (Motor connects on first use, not at import time)
mongo_url = os.environ.get('MONGO_URL', config.MONGO_URL)
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', config.DB_NAME)]

# ─── FastAPI application ──────────────────────────────────────────────────────
app = FastAPI(
    title="StoryMe API",
    description="Production-ready storybook generation API with storage abstraction",
    version="2.0.0",
)

# ─── CORS middleware ──────────────────────────────────────────────────────────
# MUST be added BEFORE any app.mount() call so it wraps the full ASGI app.
#
# allow_credentials=False: the auth API returns JSON tokens, not cookies.
# With allow_credentials=False, allow_origins=["*"] is valid per the CORS spec.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Generation-ID", "X-Child-Name", "X-Story-ID"],
)

# ─── Legacy /api router ───────────────────────────────────────────────────────
api_router = APIRouter(prefix="/api")


# ─── MongoDB status check (legacy endpoint) ───────────────────────────────────
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


@api_router.get("/")
async def root():
    return {"message": "StoryMe API is running"}


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    await db.status_checks.insert_one(doc)
    return status_obj


@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    return status_checks


# ─── Health check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """
    Health probe endpoint.
    Returns HTTP 200 with system status. Used by:
      - Azure App Service liveness probe
      - Frontend warmup poller (warmup.js)
    """
    try:
        await db.command("ping")
        mongo_status = "up"
    except Exception as e:
        mongo_status = f"unavailable: {e}"

    from core.session_store import session_store as _ss
    session_store_type = type(_ss).__name__

    return {
        "status": "healthy",
        "service": "storyme-backend",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system_deps_installed": _install_system_deps._deps_ok,
        "generation_v1_available": generate_router is not None,
        "generation_v2_available": generate_v2_router is not None,
        "session_store": session_store_type,
        "dependencies": {
            "mongodb": mongo_status,
        },
    }


# ─── Register routers ─────────────────────────────────────────────────────────
#
# Registration order:
#   1. api_router        /api/         legacy root + MongoDB status
#   2. stories_router    /api/stories  story list (v1, no cv2 dep)
#   3. stories_v2_router /api/v2/stories  story list (v2, no cv2 dep, used by frontend)
#   4. review_router     /api/review
#   5. auth_router       /api/auth/*
#   6. health_router     /health
#   7. generate_router   /api/generate    (conditional — needs cv2/mediapipe)
#   8. generate_v2_router /api/v2/*       (conditional — needs cv2/mediapipe)
#
# stories_router and stories_v2_router are ALWAYS registered regardless of
# whether cv2/mediapipe imported successfully. This guarantees the frontend
# story dropdown is always populated.

app.include_router(api_router)           # /api/
app.include_router(stories_router)       # /api/stories
app.include_router(stories_v2_router)    # /api/v2/stories ← always available
app.include_router(review_router)        # /api/review
app.include_router(auth_router)          # /api/auth/*
app.include_router(health_router)        # /health
app.include_router(print_orders_router)  # /api/v2/print/* and /api/v2/orders/* and /api/v2/admin/*
app.include_router(user_profile_router)  # /api/v2/user/addresses
if admin_face_router is not None:
    app.include_router(admin_face_router)    # /api/admin/face-test/*

if generate_router is not None:
    app.include_router(generate_router)       # /api/generate  (v1)
if generate_v2_router is not None:
    app.include_router(generate_v2_router)    # /api/v2/*      (v2)
if generate_v3_router is not None:
    app.include_router(generate_v3_router)    # /api/v3/generate  (v3 face pipeline)
if generate_async_router is not None:
    app.include_router(generate_async_router)  # /api/v2/generate/async|status|download

# ─── Static files (MUST come after CORS middleware) ───────────────────────────
static_dir = ROOT_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


# ─── Startup event ────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("=" * 70)
    logger.info("StoryMe API Starting")
    logger.info("=" * 70)
    logger.info("Storage Type:           %s", config.STORAGE_TYPE)
    logger.info("CORS Origins:           %s", config.CORS_ORIGINS)
    logger.info("System deps installed:  %s", _install_system_deps._deps_ok)
    logger.info("Generation v1 active:   %s", generate_router is not None)
    logger.info("Generation v2 active:   %s", generate_v2_router is not None)

    if _generate_v1_import_error:
        logger.warning(
            "Story generation v1 (/api/generate) DISABLED — %s",
            _generate_v1_import_error,
        )
    if _generate_v2_import_error:
        logger.warning(
            "Story generation v2 (/api/v2/generate/*) DISABLED — %s",
            _generate_v2_import_error,
        )

    from services.story_service import story_registry
    logger.info("Stories Loaded: %d", story_registry.get_story_count())

    # Template verification is informational only — a template missing from
    # Azure Blob Storage does NOT prevent generation because image_service
    # reads templates directly from local disk (bundled with the app).
    for story_meta in story_registry.list_stories():
        try:
            v = story_registry.verify_story_templates(story_meta.story_id)
            logger.info(
                "%s: %d/%d templates found in storage",
                story_meta.story_id, v["verified"], v["total_pages"],
            )
        except Exception as e:
            logger.warning("Template verification failed for %s: %s", story_meta.story_id, e)

    logger.info("=" * 70)

    # Seed print products and placeholder cover images
    try:
        from services.product_catalog import get_catalog_store
        cat = get_catalog_store()
        if cat:
            cat.seed_products()
            logger.info("PrintProducts: catalog seeded")
    except Exception as _e:
        logger.warning("PrintProducts seed failed (non-fatal): %s", _e)

    try:
        from services.cover_image_gen import seed_cover_images
        seed_cover_images()
    except Exception as _e:
        logger.warning("Cover image seed failed (non-fatal): %s", _e)


# ─── Shutdown event ───────────────────────────────────────────────────────────
@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

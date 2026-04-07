from fastapi import FastAPI, APIRouter
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List
import uuid
from datetime import datetime, timezone

# Import core configuration
from core.config import config

# Import routes
from routes.generate import router as generate_router
from routes.stories import router as stories_router
from routes.review import router as review_router
from routes.generate_v2 import router as generate_v2_router
from routes.auth import router as auth_router

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection (lazy — Motor connects on first use, not at startup)
mongo_url = os.environ.get('MONGO_URL', config.MONGO_URL)
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', config.DB_NAME)]

# ─── Create the main FastAPI app ──────────────────────────────────────────────
app = FastAPI(
    title="StoryMe API",
    description="Production-ready storybook generation API with storage abstraction",
    version="2.0.0"
)

# ─── CORS middleware ──────────────────────────────────────────────────────────
# MUST be added before any app.mount() call so it wraps the full ASGI app.
#
# allow_credentials=False because the frontend uses credentials:"omit".
# The auth API returns JSON tokens — it does not set or read cookies.
# With allow_credentials=False, allow_origins=["*"] is valid per the CORS spec
# and browsers will accept it without restriction.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,   # defaults to ["*"] — see core/config.py
    allow_credentials=False,              # no session cookies used
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Legacy /api prefix router ────────────────────────────────────────────────
api_router = APIRouter(prefix="/api")


# ─── Models (status check — legacy MongoDB endpoint) ─────────────────────────
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
    """Lightweight liveness probe — use this to verify the backend is running."""
    return {"status": "ok", "version": "2.0.0"}


# ─── Register routers ─────────────────────────────────────────────────────────
app.include_router(api_router)          # /api/  (legacy)
app.include_router(generate_router)     # /api/generate
app.include_router(stories_router)      # /api/stories
app.include_router(review_router)       # /api/review
app.include_router(generate_v2_router)  # /api/v2/*
app.include_router(auth_router)         # /api/auth/*

# ─── Static files (must come after CORS middleware registration) ──────────────
static_dir = ROOT_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup_event():
    logger.info("=" * 70)
    logger.info("StoryMe API Starting")
    logger.info("=" * 70)
    logger.info(f"Storage Type: {config.STORAGE_TYPE}")
    logger.info(f"CORS Origins: {config.CORS_ORIGINS}")

    from services.story_service import story_registry
    logger.info(f"Stories Loaded: {story_registry.get_story_count()}")

    for story_meta in story_registry.list_stories():
        verification = story_registry.verify_story_templates(story_meta.story_id)
        logger.info(
            f"  - {story_meta.story_id}: "
            f"{verification['verified']}/{verification['total_pages']} templates"
        )

    logger.info("=" * 70)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

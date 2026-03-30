from fastapi import FastAPI, APIRouter
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

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', config.MONGO_URL)
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', config.DB_NAME)]

# Create the main app
app = FastAPI(
    title="StoryMe API",
    description="Production-ready storybook generation API with storage abstraction",
    version="2.0.0"
)

# Create a router with the /api prefix for legacy endpoints
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks

# Include routers
app.include_router(api_router)  # Legacy /api endpoints
app.include_router(generate_router)  # /api/generate
app.include_router(stories_router)  # /api/stories

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Log startup information
@app.on_event("startup")
async def startup_event():
    logger.info("="*70)
    logger.info("StoryMe API Starting")
    logger.info("="*70)
    logger.info(f"Storage Type: {config.STORAGE_TYPE}")
    logger.info(f"Storage Info: {config.get_storage_info()}")
    
    # Import and log story registry info
    from services.story_service import story_registry
    logger.info(f"Stories Loaded: {story_registry.get_story_count()}")
    
    # Verify templates for all stories
    for story_meta in story_registry.list_stories():
        verification = story_registry.verify_story_templates(story_meta.story_id)
        logger.info(f"  - {story_meta.story_id}: {verification['verified']}/{verification['total_pages']} templates found")
    
    logger.info("="*70)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
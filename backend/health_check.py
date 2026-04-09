from fastapi import APIRouter
from datetime import datetime, timezone
import os

router = APIRouter()

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "storyme-backend",
        "version": "2.0.0",
        "environment": os.getenv("ENV", "unknown")
    }

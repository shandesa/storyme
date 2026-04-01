"""Review route - serves pipeline output images for user review."""

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path

router = APIRouter(prefix="/api", tags=["review"])

STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("/review")
async def review_page():
    html_path = STATIC_DIR / "review.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>No review page found</h1>", status_code=404)


@router.get("/review/image/{filename}")
async def review_image(filename: str):
    file_path = STATIC_DIR / filename
    if file_path.exists() and file_path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        media = "image/png" if file_path.suffix == ".png" else "image/jpeg"
        return FileResponse(path=str(file_path), media_type=media)
    return HTMLResponse(content="Not found", status_code=404)

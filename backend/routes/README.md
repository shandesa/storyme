# Backend Routes - API Layer

## Purpose

The `routes/` directory contains FastAPI route handlers that expose the application's functionality as REST API endpoints. Routes handle HTTP concerns (request validation, response formatting, error handling) and delegate business logic to services.

## Placement in Architecture

```
HTTP Request
     ↓
┌─────────────────────────────┐
│    ROUTES (API Layer)      │  ← YOU ARE HERE
│  - Validate requests       │
│  - Call services           │
│  - Format responses        │
└───────────┬─────────────────┘
           │
           ↓
┌───────────┴─────────────────┐
│   Services (Business)      │
└─────────────────────────────┘
```

**Routes are thin HTTP wrappers**:
- No business logic
- Validate input
- Call services
- Return responses

## Files

### 1. `stories.py` - Story Management Endpoints
### 2. `generate.py` - PDF Generation Endpoint

---

## 1. Stories Routes

**File**: `stories.py`

**Purpose**: Provide API access to story catalog and metadata.

### Endpoints

#### GET /api/stories

**Purpose**: List all available stories (metadata only).

```python
@router.get("", response_model=List[StoryMetadata])
async def list_stories():
    """Get list of all stories without full page details."""
    return story_registry.list_stories()
```

**Response**:
```json
[
  {
    "story_id": "forest_of_smiles",
    "title": "{name} and the Forest of Smiles",
    "age_group": "3-6",
    "description": "A magical adventure...",
    "page_count": 10
  }
]
```

**Usage**:
```bash
curl http://localhost:8001/api/stories
```

---

#### GET /api/stories/{index}

**Purpose**: Get story metadata by index position.

```python
@router.get("/{index}", response_model=StoryMetadata)
async def get_story_by_index(index: int):
    """Get story at specific index (0-based)."""
    story = story_registry.get_story_by_index(index)
    if not story:
        raise HTTPException(status_code=404, detail=f"Story not found at index {index}")
    return StoryMetadata.from_story(story)
```

**Response**:
```json
{
  "story_id": "forest_of_smiles",
  "title": "{name} and the Forest of Smiles",
  "age_group": "3-6",
  "description": "A magical adventure...",
  "page_count": 10
}
```

**Usage**:
```bash
curl http://localhost:8001/api/stories/0
```

---

#### GET /api/stories/verify/{story_id}

**Purpose**: Verify all template files exist for a story.

```python
@router.get("/verify/{story_id}")
async def verify_story_templates(story_id: str):
    """Check if all template files are present."""
    results = story_registry.verify_story_templates(story_id)
    if 'error' in results:
        raise HTTPException(status_code=404, detail=results['error'])
    return results
```

**Response (Success)**:
```json
{
  "story_id": "forest_of_smiles",
  "total_pages": 10,
  "verified": 10,
  "missing": []
}
```

**Response (Missing Templates)**:
```json
{
  "story_id": "forest_of_smiles",
  "total_pages": 10,
  "verified": 8,
  "missing": [
    {"page": 9, "path": "templates/stories/forest_of_smiles/page9.png"},
    {"page": 10, "path": "templates/stories/forest_of_smiles/page10.png"}
  ]
}
```

**Usage**:
```bash
curl http://localhost:8001/api/stories/verify/forest_of_smiles
```

---

## 2. Generate Route

**File**: `generate.py`

**Purpose**: Handle storybook PDF generation requests.

### Endpoint

#### POST /api/generate

**Purpose**: Generate personalized storybook PDF.

```python
@router.post("/generate")
async def generate_storybook(
    name: str = Form(...),
    image: UploadFile = File(...),
    story_id: Optional[str] = Form(None),
    story_index: Optional[int] = Form(None)
):
    """Generate personalized PDF storybook."""
    # Validation
    # Story selection
    # Image processing
    # PDF generation
    # Return file
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | string | Yes | Child's name |
| image | file | Yes | Photo (JPG/PNG/WEBP, max 5MB) |
| story_id | string | No | Story identifier (e.g., "forest_of_smiles") |
| story_index | integer | No | Story index (0-based) |

**Selection Priority**:
1. If `story_id` provided → use it
2. Else if `story_index` provided → use it
3. Else → use default (index 0)

**Request Example (curl)**:
```bash
curl -X POST "http://localhost:8001/api/generate" \
  -F "name=Emma" \
  -F "image=@photo.jpg" \
  -F "story_id=forest_of_smiles" \
  -o emma_storybook.pdf
```

**Request Example (JavaScript)**:
```javascript
const formData = new FormData();
formData.append('name', 'Emma');
formData.append('image', fileInput.files[0]);
formData.append('story_id', 'forest_of_smiles');

const response = await fetch('/api/generate', {
  method: 'POST',
  body: formData
});

const blob = await response.blob();
// Trigger download
```

**Response**:
- Content-Type: `application/pdf`
- Content-Disposition: `attachment; filename="{name}_{id}.pdf"`
- Body: PDF file binary

---

## Request Validation

### Input Validation

**Automatic (FastAPI)**:
```python
name: str = Form(...)  # Required, must be string
story_index: Optional[int] = Form(None)  # Optional, must be int if provided
```

**Manual**:
```python
# Name validation
if not name or name.strip() == "":
    raise HTTPException(status_code=400, detail="Child's name is required")

# File type validation
if image.content_type not in config.ALLOWED_IMAGE_TYPES:
    raise HTTPException(status_code=400, detail="Invalid file type")
```

### Error Responses

**400 Bad Request**:
```json
{
  "detail": "Invalid file type. Allowed: image/jpeg, image/png, image/webp"
}
```

**404 Not Found**:
```json
{
  "detail": "Story not found: ocean_adventure"
}
```

**422 Unprocessable Entity**:
```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

**500 Internal Server Error**:
```json
{
  "detail": "Error generating storybook: {error_message}"
}
```

---

## Complete Generation Flow

### Step-by-Step

```python
@router.post("/generate")
async def generate_storybook(...):
    # 1. Validate inputs
    if not name.strip():
        raise HTTPException(400, "Name required")
    
    # 2. Select story
    story = story_registry.get_story_by_id(story_id or "forest_of_smiles")
    if not story:
        raise HTTPException(404, "Story not found")
    
    # 3. Save uploaded image
    uploaded_path = f"uploads/{uuid.uuid4()}.jpg"
    storage.save_file(image.file, uploaded_path)
    
    try:
        # 4. Process each page
        pages_data = []
        for page in story.pages:
            # Extract face
            face = image_service.extract_face(
                uploaded_path,
                (page.face_placement.width, page.face_placement.height)
            )
            
            # Compose onto template
            composed = image_service.compose_page(
                page.image_path,
                face,
                (page.face_placement.x, page.face_placement.y),
                f"output/{uuid.uuid4()}.png"
            )
            
            pages_data.append({
                'text': page.text,
                'image_path': composed
            })
        
        # 5. Generate PDF
        pdf_path = pdf_service.create_storybook_pdf(
            child_name=name,
            story_title=story.title,
            pages_data=pages_data,
            output_filename=f"{name}_{uuid.uuid4().hex[:8]}.pdf"
        )
        
        # 6. Return file
        return FileResponse(
            path=pdf_path,
            filename=f"{name}_storybook.pdf",
            media_type='application/pdf'
        )
    
    finally:
        # 7. Cleanup uploaded file
        storage.delete_file(uploaded_path)
```

---

## Design Patterns

### 1. Thin Controllers

**Routes do NOT contain business logic**:

```python
# ❌ BAD - Business logic in route
@router.post("/generate")
async def generate(...):
    img = Image.open(image.file)
    img = img.crop([100, 100, 300, 300])  # Image processing in route!
    # ...

# ✅ GOOD - Delegate to service
@router.post("/generate")
async def generate(...):
    face = image_service.extract_face(...)  # Service handles logic
    # ...
```

### 2. Dependency Injection

**Services as dependencies**:

```python
# At module level
from services.story_service import story_registry
from services.image_service import image_service

# In route
@router.post("/generate")
async def generate(...):
    story = story_registry.get_story_by_id(...)  # Use injected service
```

### 3. Error Handling

**Specific exceptions with context**:

```python
try:
    face = image_service.extract_face(...)
except FileNotFoundError:
    raise HTTPException(404, "Image not found")
except ValueError as e:
    raise HTTPException(400, str(e))
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise HTTPException(500, "Internal server error")
```

---

## Testing Routes

### Unit Tests (pytest)

```python
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

def test_list_stories():
    response = client.get("/api/stories")
    assert response.status_code == 200
    stories = response.json()
    assert len(stories) > 0
    assert "story_id" in stories[0]

def test_generate_missing_name():
    response = client.post("/api/generate", files={"image": ("test.jpg", b"...")})
    assert response.status_code == 422  # Missing name

def test_generate_invalid_file_type():
    response = client.post(
        "/api/generate",
        data={"name": "Test"},
        files={"image": ("test.txt", b"text", "text/plain")}
    )
    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]
```

### Integration Tests

```python
def test_complete_generation_flow():
    # Create test image
    img_bytes = create_test_image()
    
    # Generate PDF
    response = client.post(
        "/api/generate",
        data={"name": "TestChild", "story_id": "forest_of_smiles"},
        files={"image": ("test.jpg", img_bytes, "image/jpeg")}
    )
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert len(response.content) > 10000  # PDF has content
    
    # Validate PDF
    pdf = PdfReader(io.BytesIO(response.content))
    assert len(pdf.pages) == 11  # 1 title + 10 story pages
```

---

## API Documentation

**FastAPI Auto-Generated**:

- **Swagger UI**: http://localhost:8001/docs
- **ReDoc**: http://localhost:8001/redoc

**Features**:
- Interactive API testing
- Request/response schemas
- Parameter documentation
- Example requests

---

## Best Practices

### DO
✅ Use type hints for all parameters
✅ Validate inputs explicitly
✅ Use response models for type safety
✅ Log important operations
✅ Handle errors gracefully
✅ Clean up resources (finally blocks)
✅ Return appropriate HTTP status codes

### DON'T
❌ Put business logic in routes
❌ Hardcode values
❌ Ignore validation errors
❌ Return stack traces to users
❌ Mix sync and async incorrectly
❌ Forget to clean up temporary files

---

## HTTP Status Codes

| Code | Meaning | When to Use |
|------|---------|-------------|
| 200 | OK | Successful request |
| 400 | Bad Request | Invalid input (file type, etc.) |
| 404 | Not Found | Story/resource doesn't exist |
| 422 | Unprocessable Entity | Validation failed (missing fields) |
| 500 | Internal Server Error | Unexpected errors |

---

## Performance Considerations

### File Upload Limits

```python
# In config.py
MAX_UPLOAD_SIZE_MB = 5

# Validation
if image.size > config.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
    raise HTTPException(413, "File too large")
```

### Async Operations

```python
# CPU-bound operations should be async
@router.post("/generate")
async def generate(...):
    # I/O operations
    story = await async_get_story(...)
    
    # CPU-bound (image processing) - consider background task
    face = image_service.extract_face(...)  # Blocks event loop
```

### Background Tasks (Future)

```python
from fastapi import BackgroundTasks

@router.post("/generate")
async def generate(..., background_tasks: BackgroundTasks):
    # Queue for processing
    background_tasks.add_task(process_and_email, ...)
    return {"status": "processing", "job_id": "..."}
```

---

## Security

### Input Validation

```python
# File type whitelist
ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp']

# File size limit
MAX_SIZE = 5 * 1024 * 1024  # 5MB

# Sanitize filename
import uuid
filename = f"{uuid.uuid4()}{Path(image.filename).suffix}"
```

### CORS Configuration

```python
# In server.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Summary

The `routes/` directory provides:
- ✅ Clean HTTP API layer
- ✅ Input validation
- ✅ Error handling
- ✅ Story catalog access
- ✅ PDF generation endpoint
- ✅ Thin controllers (no business logic)

**Key Takeaway**: Routes are the "face" of the application. They handle HTTP concerns and delegate all real work to services, keeping the codebase clean and testable.

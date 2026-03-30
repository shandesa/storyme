# Backend Services - Business Logic Layer

## Purpose

The `services/` directory contains the core business logic of the application. Services orchestrate operations, implement algorithms, and coordinate between different components while remaining independent of HTTP concerns and storage details.

## Placement in Architecture

```
Application
    │
    ├── Routes (HTTP)  ──────┐
    │                        │
    ├── SERVICES (Logic) ◄───┘  ← YOU ARE HERE
    │       │
    │       ├──► Models (Data)
    │       └──► Storage (Files)
    │
    └── Core (Infrastructure)
```

**Services are the heart of the application**:
- Routes call services (not the other way)
- Services use storage abstraction (not direct file I/O)
- Services operate on models (type-safe data)

## Files

### 1. `story_service.py` - Story Registry & Management
### 2. `image_service.py` - Face Extraction & Composition  
### 3. `pdf_service.py` - PDF Generation

---

## 1. Story Service

**File**: `story_service.py`

**Purpose**: Centralized registry for all available stories with intelligent access methods.

### Architecture

```python
StoryRegistry
    ├── Story Database (in-memory)
    ├── Access Methods (by ID, index, age)
    ├── Template Verification
    └── Storage Integration
```

### Key Components

#### StoryRegistry Class

**Responsibilities**:
- Maintain story catalog
- Provide multiple access patterns
- Verify template files exist
- Resolve template paths via storage

**Methods**:
```python
get_story_by_id(story_id: str) -> Optional[Story]
get_story_by_index(index: int) -> Optional[Story]
list_stories() -> List[StoryMetadata]
get_story_count() -> int
get_stories_by_age_group(age_group: str) -> List[Story]
verify_story_templates(story_id: str) -> dict
```

### Usage Examples

#### Access Stories

```python
from services.story_service import story_registry

# By ID (recommended)
story = story_registry.get_story_by_id("forest_of_smiles")
if story:
    print(f"Found: {story.title}")

# By index (for selection UI)
story = story_registry.get_story_by_index(0)  # First story

# List all (for API)
stories = story_registry.list_stories()  # Returns metadata only
for meta in stories:
    print(f"{meta.story_id}: {meta.page_count} pages")

# By age group (future filtering)
stories_3_6 = story_registry.get_stories_by_age_group("3-6")
```

#### Verify Templates

```python
# Check all templates exist
result = story_registry.verify_story_templates("forest_of_smiles")

if result['missing']:
    print(f"Missing {len(result['missing'])} templates:")
    for missing in result['missing']:
        print(f"  Page {missing['page']}: {missing['path']}")
else:
    print(f"All {result['total_pages']} templates found!")
```

### Adding New Stories

**Step 1**: Create template images
```bash
mkdir -p templates/stories/ocean_adventure
# Add page1.png through page10.png
```

**Step 2**: Add to registry in `_initialize_stories()`
```python
ocean_story = Story(
    story_id="ocean_adventure",
    title="{name}'s Ocean Adventure",
    age_group="3-6",
    description="Underwater journey with sea creatures",
    pages=[
        Page(
            page_number=1,
            text="{name} dove into the crystal blue ocean...",
            face_placement=FacePlacement(x=200, y=150, width=160, height=160),
            image_path="templates/stories/ocean_adventure/page1.png"
        ),
        # ... 9 more pages
    ]
)

stories.append(ocean_story)
```

**Step 3**: Verify
```bash
curl http://localhost:8001/api/stories/verify/ocean_adventure
```

**No other code changes needed!**

### Design Benefits

✅ **Centralized**: One place for all story data
✅ **Flexible**: Multiple access patterns
✅ **Validated**: Template verification
✅ **Extensible**: Easy to add stories
✅ **Storage-agnostic**: Works with local/S3

---

## 2. Image Service

**File**: `image_service.py`

**Purpose**: Handle face extraction and template composition using storage abstraction.

### Architecture

```python
ImageService
    ├── extract_face()        # Face cropping & resizing
    ├── _apply_circular_mask() # Circular face mask
    └── compose_page()        # Face + template composition
         │
         └──► Storage (read templates, save output)
```

### Key Methods

#### extract_face()

**Purpose**: Extract and resize face from uploaded image.

```python
def extract_face(self, image_path: str, target_size: Tuple[int, int]) -> Image.Image:
    """
    Extract face with center crop and resize.
    
    Future: Add face detection (OpenCV, ML models)
    """
    # Read via storage abstraction
    image_bytes = storage.read_file(image_path)
    img = Image.open(io.BytesIO(image_bytes))
    
    # Center crop to square
    # Resize to target size
    # Apply circular mask
    
    return processed_face
```

**Current**: Simple center crop
**Future**: Face detection with OpenCV/ML

#### compose_page()

**Purpose**: Paste face onto template and save result.

```python
def compose_page(
    self,
    template_path: str,      # Relative path
    face_img: Image.Image,
    face_position: Tuple[int, int],
    output_path: str         # Relative path
) -> str:
    """
    Compose face onto template using storage abstraction.
    """
    # Read template via storage
    template_bytes = storage.read_file(template_path)
    template = Image.open(io.BytesIO(template_bytes))
    
    # Paste face
    template.paste(face_img, face_position, face_img)
    
    # Save via storage
    img_bytes = io.BytesIO()
    template.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    return storage.save_file(img_bytes, output_path)
```

### Storage Integration

**Key Point**: No direct file I/O!

```python
# ❌ DON'T
with open("/app/backend/templates/page1.png", 'rb') as f:
    template = Image.open(f)

# ✅ DO
from core.storage import storage
template_bytes = storage.read_file("templates/stories/forest_of_smiles/page1.png")
template = Image.open(io.BytesIO(template_bytes))
```

**Why?** Storage abstraction handles:
- Local filesystem paths
- S3 URLs and authentication
- Future: CDN, Google Cloud, Azure

### Usage Example

```python
from services.image_service import image_service

# Extract face
face_img = image_service.extract_face(
    "uploads/photo.jpg",
    target_size=(160, 160)
)

# Compose onto template
output_path = image_service.compose_page(
    template_path="templates/stories/forest_of_smiles/page1.png",
    face_img=face_img,
    face_position=(220, 180),
    output_path="output/page1_composed.png"
)

print(f"Saved to: {output_path}")
```

---

## 3. PDF Service

**File**: `pdf_service.py`

**Purpose**: Generate multi-page PDFs with personalized story text and images.

### Architecture

```python
PDFService
    └── create_storybook_pdf()
         ├── Title Page
         ├── Story Pages (with images + text)
         └── Personalization ({name} replacement)
```

### Key Method

```python
def create_storybook_pdf(
    self,
    child_name: str,
    story_title: str,
    pages_data: List[dict],    # [{'text': '...', 'image_path': '...'}]
    output_filename: str
) -> str:
    """
    Create personalized PDF storybook.
    
    Returns: Full path to generated PDF
    """
    # Create PDF with ReportLab
    # Add title page
    # Add story pages with images and text
    # Replace {name} with child_name
    # Save to output directory
    
    return pdf_path
```

### Usage Example

```python
from services.pdf_service import PDFService

pdf_service = PDFService("/app/backend/output")

pages_data = [
    {'text': 'Page 1 text...', 'image_path': '/app/backend/output/page1.png'},
    {'text': 'Page 2 text...', 'image_path': '/app/backend/output/page2.png'},
    # ... 10 pages total
]

pdf_path = pdf_service.create_storybook_pdf(
    child_name="Emma",
    story_title="{name} and the Forest of Smiles",
    pages_data=pages_data,
    output_filename="Emma_storybook.pdf"
)

print(f"PDF created: {pdf_path}")
```

---

## Service Orchestration

### Complete Flow

**In `routes/generate.py`**:

```python
# 1. Get story
story = story_registry.get_story_by_id("forest_of_smiles")

# 2. Save uploaded image
storage.save_file(image.file, "uploads/photo.jpg")

# 3. Process each page
pages_data = []
for page in story.pages:
    # Extract face
    face_img = image_service.extract_face(
        "uploads/photo.jpg",
        (page.face_placement.width, page.face_placement.height)
    )
    
    # Compose page
    composed_path = image_service.compose_page(
        page.image_path,
        face_img,
        (page.face_placement.x, page.face_placement.y),
        f"output/page{page.page_number}.png"
    )
    
    pages_data.append({
        'text': page.text,
        'image_path': composed_path
    })

# 4. Generate PDF
pdf_path = pdf_service.create_storybook_pdf(
    child_name=name,
    story_title=story.title,
    pages_data=pages_data,
    output_filename=f"{name}_storybook.pdf"
)

# 5. Return PDF
return FileResponse(pdf_path, filename=...)
```

---

## Design Principles

### 1. Separation of Concerns

**Each service has ONE job**:
- `story_service`: Story catalog management
- `image_service`: Image processing
- `pdf_service`: PDF generation

### 2. Storage Abstraction

**Never hardcode paths**:
```python
# ❌ BAD
template = Image.open("/app/backend/templates/page1.png")

# ✅ GOOD
template_bytes = storage.read_file("templates/stories/forest_of_smiles/page1.png")
template = Image.open(io.BytesIO(template_bytes))
```

### 3. Dependency Injection

**Services are singletons**:
```python
# In service files
image_service = ImageService()

# In routes
from services.image_service import image_service
face = image_service.extract_face(...)
```

### 4. Error Handling

**Services raise descriptive errors**:
```python
if not story:
    raise ValueError(f"Story not found: {story_id}")

if not storage.file_exists(template_path):
    raise FileNotFoundError(f"Template missing: {template_path}")
```

---

## Testing Services

### Unit Tests

```python
def test_story_registry():
    story = story_registry.get_story_by_id("forest_of_smiles")
    assert story is not None
    assert story.story_id == "forest_of_smiles"
    assert story.get_page_count() == 10

def test_image_service_with_mock_storage():
    # Mock storage
    storage.read_file = lambda path: mock_image_bytes
    
    face = image_service.extract_face("test.jpg", (100, 100))
    assert face.size == (100, 100)
```

### Integration Tests

```python
def test_complete_generation_flow():
    # Upload image
    storage.save_file(test_image, "uploads/test.jpg")
    
    # Get story
    story = story_registry.get_story_by_id("forest_of_smiles")
    
    # Process pages
    for page in story.pages:
        face = image_service.extract_face("uploads/test.jpg", ...)
        composed = image_service.compose_page(...)
    
    # Generate PDF
    pdf_path = pdf_service.create_storybook_pdf(...)
    
    # Verify
    assert Path(pdf_path).exists()
    assert Path(pdf_path).stat().st_size > 10000  # At least 10KB
```

---

## Future Enhancements

### Story Service
- Database storage for user-generated stories
- Story versioning
- Multi-language support
- A/B testing for story variations

### Image Service
- Face detection with OpenCV
- ML-based face enhancement
- Background removal
- Multiple face support
- Batch processing

### PDF Service
- Custom page layouts
- Font selection
- Color themes
- Interactive PDFs
- Compression options

---

## Best Practices

### DO
✅ Use storage abstraction for all file operations
✅ Log important operations
✅ Raise descriptive exceptions
✅ Keep services focused (single responsibility)
✅ Use dependency injection
✅ Return consistent types

### DON'T
❌ Access HTTP request/response in services
❌ Hardcode file paths
❌ Mix business logic with infrastructure
❌ Create circular dependencies
❌ Ignore errors silently

---

## Dependencies

```txt
Pillow>=10.0.0          # Image processing
reportlab>=4.0.0        # PDF generation
```

---

## Summary

The `services/` directory provides:
- ✅ Core business logic
- ✅ Story catalog management
- ✅ Image processing pipeline
- ✅ PDF generation
- ✅ Storage-agnostic operations
- ✅ Clean, testable architecture

**Key Takeaway**: Services are the "brain" of the application. They implement all the interesting functionality while remaining independent of HTTP concerns and storage details.

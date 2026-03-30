# Backend Models - Data Layer

## Purpose

The `models/` directory defines the data structures and schemas used throughout the backend application. These models provide type safety, validation, and a clear contract for data exchange between layers.

## Placement in Architecture

```
Application
    │
    ├── Routes (HTTP) ──┐
    │                   │
    ├── Services ───────┼──► MODELS (Data Structures)  ← YOU ARE HERE
    │                   │
    └── Storage ────────┘
```

Models are used by **all layers** for:
- Request/response validation
- Service method parameters
- Database schema (future)
- Type hints and IDE support

## Files

### `story.py` - Story Domain Models

**Purpose**: Define the structure of stories, pages, and face placement data.

---

## Model Definitions

### 1. FacePlacement

**Purpose**: Specifies exact coordinates for placing a child's face on a template.

```python
class FacePlacement(BaseModel):
    x: int              # X coordinate (pixels from left)
    y: int              # Y coordinate (pixels from top)
    width: int          # Face width in pixels
    height: int         # Face height in pixels
```

**Usage**:
```python
face_placement = FacePlacement(x=220, y=180, width=160, height=160)

# Access coordinates
print(f"Place face at ({face_placement.x}, {face_placement.y})")
print(f"Size: {face_placement.width}x{face_placement.height}")
```

**Why Separate Model?**
- Reusable across multiple pages
- Type-safe coordinate access
- Easy to validate ranges
- Clear intent in code

---

### 2. Page

**Purpose**: Represents a single page in a storybook.

```python
class Page(BaseModel):
    page_number: int              # 1-indexed page number
    text: str                     # Story text with {name} placeholder
    face_placement: FacePlacement # Where to place face
    image_path: str              # Relative path to template
```

**Example**:
```python
page = Page(
    page_number=1,
    text="One sunny morning, {name} walked into a forest...",
    face_placement=FacePlacement(x=220, y=180, width=160, height=160),
    image_path="templates/stories/forest_of_smiles/page1.png"
)

# Personalize text
personalized = page.text.replace("{name}", "Emma")
```

**Design Notes**:
- `page_number`: 1-indexed for human readability
- `text`: Contains `{name}` placeholder for personalization
- `image_path`: Relative path (storage abstraction resolves full path)
- `face_placement`: Nested model for coordinate data

---

### 3. Story

**Purpose**: Complete story with metadata and all pages.

```python
class Story(BaseModel):
    story_id: str         # Unique identifier (snake_case)
    title: str            # Human-readable title with {name}
    age_group: str        # Target age (e.g., "3-6", "6-8")
    description: str      # Story description
    pages: List[Page]     # All story pages
    
    def get_page_count(self) -> int:
        return len(self.pages)
```

**Example**:
```python
story = Story(
    story_id="forest_of_smiles",
    title="{name} and the Forest of Smiles",
    age_group="3-6",
    description="A magical adventure...",
    pages=[page1, page2, ...]  # List of 10 pages
)

print(f"Story: {story.story_id}")
print(f"Pages: {story.get_page_count()}")
print(f"Age: {story.age_group}")
```

**Naming Convention**:
- `story_id`: snake_case (e.g., `forest_of_smiles`, `ocean_adventure`)
- Used in URLs: `/api/stories/verify/forest_of_smiles`
- Used in directories: `templates/stories/forest_of_smiles/`

---

### 4. StoryMetadata

**Purpose**: Lightweight story information without full page details.

```python
class StoryMetadata(BaseModel):
    story_id: str
    title: str
    age_group: str
    description: str
    page_count: int
    
    @classmethod
    def from_story(cls, story: Story):
        return cls(
            story_id=story.story_id,
            title=story.title,
            age_group=story.age_group,
            description=story.description,
            page_count=story.get_page_count()
        )
```

**Why Separate Metadata?**
- Lighter API responses
- List stories without loading all page data
- Faster serialization
- Clear separation of concerns

**Usage**:
```python
# Full story (internal use)
story = story_registry.get_story_by_id("forest_of_smiles")

# Metadata only (API response)
metadata = StoryMetadata.from_story(story)
return metadata  # Only essential info, no page details
```

---

## Capabilities

### 1. Validation

**Pydantic Automatic Validation**:
```python
# Valid
page = Page(
    page_number=1,
    text="Story text",
    face_placement=FacePlacement(x=100, y=100, width=150, height=150),
    image_path="templates/page1.png"
)

# Invalid - raises ValidationError
page = Page(
    page_number="one",  # TypeError: expected int
    text=123,           # TypeError: expected str
)
```

### 2. Serialization

**JSON Conversion**:
```python
# To JSON
story_dict = story.model_dump()
story_json = story.model_dump_json()

# From JSON
story = Story.model_validate(data)
story = Story.model_validate_json(json_string)
```

### 3. Type Safety

**IDE Support**:
```python
def process_story(story: Story):
    # IDE knows story.pages is List[Page]
    for page in story.pages:
        # IDE autocompletes: page.page_number, page.text, etc.
        print(page.page_number)
```

### 4. Immutability (Optional)

```python
class Story(BaseModel):
    class Config:
        frozen = True  # Make immutable

# story.story_id = "new_id"  # Raises error if frozen
```

---

## Design Principles

### 1. Single Source of Truth

**All story data flows through these models**:
- Services receive/return these models
- Routes validate against these models
- Storage reads/writes using these structures

### 2. Clear Contracts

**Models define API contracts**:
```python
@router.get("/stories", response_model=List[StoryMetadata])
def list_stories():
    # Return type enforced by Pydantic
    return story_registry.list_stories()
```

### 3. Separation of Concerns

**Models = Data Only**:
- ✅ Data structure
- ✅ Validation rules
- ✅ Serialization
- ❌ Business logic
- ❌ Database operations
- ❌ File I/O

---
## Usage Patterns

### Creating Stories

```python
# In story_service.py
forest_story = Story(
    story_id="forest_of_smiles",
    title="{name} and the Forest of Smiles",
    age_group="3-6",
    description="A magical adventure...",
    pages=[
        Page(
            page_number=1,
            text="One sunny morning, {name}...",
            face_placement=FacePlacement(x=220, y=180, width=160, height=160),
            image_path="templates/stories/forest_of_smiles/page1.png"
        ),
        # ... 9 more pages
    ]
)
```

### Accessing Story Data

```python
# Get story
story = story_registry.get_story_by_id("forest_of_smiles")

# Iterate pages
for page in story.pages:
    print(f"Page {page.page_number}: {page.text[:50]}...")
    print(f"  Template: {page.image_path}")
    print(f"  Face at: ({page.face_placement.x}, {page.face_placement.y})")
```

### Personalization

```python
def personalize_story(story: Story, child_name: str) -> Story:
    """Create personalized copy of story."""
    personalized_pages = []
    
    for page in story.pages:
        personalized_page = page.model_copy()
        personalized_page.text = page.text.replace("{name}", child_name)
        personalized_pages.append(personalized_page)
    
    return story.model_copy(update={"pages": personalized_pages})
```

---

## Validation Examples

### Field Validation

```python
from pydantic import Field, validator

class Page(BaseModel):
    page_number: int = Field(ge=1, le=100)  # Between 1 and 100
    text: str = Field(min_length=1)         # Non-empty
    
    @validator('text')
    def text_must_contain_placeholder(cls, v):
        if '{name}' not in v:
            raise ValueError('Text must contain {name} placeholder')
        return v
```

### Custom Validation

```python
class Story(BaseModel):
    pages: List[Page]
    
    @validator('pages')
    def validate_page_numbers(cls, pages):
        # Check sequential page numbers
        expected = 1
        for page in pages:
            if page.page_number != expected:
                raise ValueError(f"Page numbers must be sequential")
            expected += 1
        return pages
```

---

## API Integration

### Request Models

```python
# routes/generate.py
@router.post("/generate")
async def generate(
    name: str = Form(...),
    story_id: Optional[str] = Form(None)
):
    # Validation happens automatically
    story = story_registry.get_story_by_id(story_id)
    # story is validated Story object
```

### Response Models

```python
@router.get("/stories", response_model=List[StoryMetadata])
async def list_stories():
    # FastAPI serializes using StoryMetadata schema
    return story_registry.list_stories()
```

---

## Testing Models

### Unit Tests

```python
def test_face_placement():
    placement = FacePlacement(x=100, y=200, width=150, height=150)
    assert placement.x == 100
    assert placement.width == 150

def test_story_page_count():
    story = Story(
        story_id="test",
        title="Test Story",
        age_group="3-6",
        description="Test",
        pages=[page1, page2]
    )
    assert story.get_page_count() == 2

def test_metadata_from_story():
    metadata = StoryMetadata.from_story(story)
    assert metadata.story_id == story.story_id
    assert metadata.page_count == len(story.pages)
```

---

## Future Extensions

### Database Integration

```python
# When adding MongoDB
from motor.motor_asyncio import AsyncIOMotorCollection

class Story(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    # ... other fields
    
    class Config:
        populate_by_name = True

# Store in MongoDB
await stories_collection.insert_one(story.model_dump(by_alias=True))
```

### Additional Models

```python
# Future: User model
class User(BaseModel):
    user_id: str
    email: str
    created_at: datetime
    purchased_stories: List[str]  # Story IDs

# Future: Generation request
class GenerationRequest(BaseModel):
    user_id: str
    story_id: str
    child_name: str
    image_url: str
```

---

## Best Practices

### DO
✅ Use Pydantic models for all data structures
✅ Add Field validators for business rules
✅ Use type hints everywhere
✅ Keep models simple (data only)
✅ Use nested models for complex data
✅ Add docstrings for complex models

### DON'T
❌ Add business logic to models
❌ Access database from models
❌ Mix validation and transformation
❌ Use mutable default values
❌ Ignore Pydantic validation errors

---

## Dependencies

```txt
pydantic>=2.6.0    # Data validation
```

---

## Summary

The `models/` directory provides:
- ✅ Type-safe data structures
- ✅ Automatic validation
- ✅ JSON serialization
- ✅ Clear API contracts
- ✅ Foundation for database schema

**Key Takeaway**: Models are the "language" the entire application speaks. Every layer uses these models to communicate, ensuring type safety and validation throughout.

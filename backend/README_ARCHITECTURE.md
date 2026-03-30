# StoryMe Backend - Production Architecture

## Overview

Production-ready FastAPI backend with **clean architecture** and **storage abstraction** that supports seamless migration between local filesystem and Amazon S3 without changing business logic.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        API Routes                            │
│  /api/generate  │  /api/stories  │  /api/stories/{index}   │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│                     Services Layer                           │
│   StoryRegistry  │  ImageService  │  PDFService             │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│                  Storage Abstraction                         │
│           LocalStorage  ◄───►  S3Storage                     │
└─────────────────────────────────────────────────────────────┘
```

## Project Structure

```
backend/
├── server.py                      # FastAPI application
├── .env                          # Environment configuration
├── .env.example                  # Configuration template
├── requirements.txt              # Python dependencies
│
├── core/                         # Core Infrastructure
│   ├── config.py                # Centralized configuration
│   └── storage.py               # Storage abstraction layer
│
├── models/                       # Data Models
│   └── story.py                 # Story, Page, FacePlacement, StoryMetadata
│
├── services/                     # Business Logic
│   ├── story_service.py         # Story registry & access
│   ├── image_service.py         # Image processing
│   └── pdf_service.py           # PDF generation
│
├── routes/                       # API Routes
│   ├── generate.py              # POST /api/generate
│   └── stories.py               # GET /api/stories/*
│
├── templates/                    # Story Templates
│   └── stories/
│       └── forest_of_smiles/
│           ├── page1.png
│           ├── page2.png
│           └── ... (page3-10.png)
│
├── uploads/                      # Temporary uploads (auto-cleanup)
└── output/                       # Generated PDFs
```

## Key Features

### 1. Storage Abstraction

**Interface-Based Design:**
```python
class StorageInterface(ABC):
    def get_file_path(self, path: str) -> str
    def read_file(self, path: str) -> bytes
    def save_file(self, file: BinaryIO, path: str) -> str
    def delete_file(self, path: str) -> bool
    def file_exists(self, path: str) -> bool
```

**Implementations:**
- **LocalStorage** - Filesystem storage (default)
- **S3Storage** - Amazon S3 storage (requires boto3)

**Switching Storage:**
```bash
# Local filesystem (default)
STORAGE_TYPE=local

# Amazon S3
STORAGE_TYPE=s3
S3_BUCKET_NAME=your-bucket
S3_REGION=us-east-1
```

### 2. Story Registry

**Centralized Story Management:**
```python
# Access by ID
story = story_registry.get_story_by_id("forest_of_smiles")

# Access by index
story = story_registry.get_story_by_index(0)

# List all stories
stories = story_registry.list_stories()

# Filter by age group
stories = story_registry.get_stories_by_age_group("3-6")
```

**Adding New Stories:**
```python
# In services/story_service.py -> _initialize_stories()

new_story = Story(
    story_id="ocean_adventure",  # snake_case
    title="{name}'s Ocean Adventure",
    age_group="3-6",
    description="Underwater journey with sea creatures",
    pages=[...]  # 10 pages with face placements
)

stories.append(new_story)
```

### 3. API Endpoints

#### List All Stories
```bash
GET /api/stories

Response:
[
  {
    "story_id": "forest_of_smiles",
    "title": "{name} and the Forest of Smiles",
    "age_group": "3-6",
    "description": "...",
    "page_count": 10
  }
]
```

#### Get Story by Index
```bash
GET /api/stories/0

Response:
{
  "story_id": "forest_of_smiles",
  "title": "{name} and the Forest of Smiles",
  ...
}
```

#### Verify Story Templates
```bash
GET /api/stories/verify/forest_of_smiles

Response:
{
  "story_id": "forest_of_smiles",
  "total_pages": 10,
  "verified": 10,
  "missing": []
}
```

#### Generate Storybook
```bash
POST /api/generate

Form Data:
- name: "Emma"
- image: <file>
- story_id: "forest_of_smiles"  (optional)
- story_index: 0                 (optional)

Priority:
1. story_id (if provided)
2. story_index (if provided)
3. Default: first story (index 0)
```

## Configuration

### Environment Variables

**`.env` file:**
```bash
# Storage Configuration
STORAGE_TYPE=local              # or 's3'

# S3 Configuration (if STORAGE_TYPE=s3)
S3_BUCKET_NAME=your-bucket-name
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret

# Database
MONGO_URL=mongodb://localhost:27017
DB_NAME=storyme_db

# Application
MAX_UPLOAD_SIZE_MB=5
LOG_LEVEL=INFO                  # DEBUG, INFO, WARNING, ERROR
CORS_ORIGINS=*
```

### Storage Migration Path

**Step 1: Local (Default)**
```bash
STORAGE_TYPE=local
```
Files stored in `/app/backend/templates`, `/app/backend/uploads`, `/app/backend/output`

**Step 2: Migrate to S3**
```bash
# Install boto3
pip install boto3

# Update .env
STORAGE_TYPE=s3
S3_BUCKET_NAME=storyme-prod
S3_REGION=us-east-1

# Upload templates to S3
aws s3 sync templates/ s3://storyme-prod/templates/

# Restart application - no code changes needed!
```

## Running the Application

### Development
```bash
cd /app/backend
uvicorn server:app --reload --host 0.0.0.0 --port 8001
```

### Production
```bash
# Using supervisor (already configured)
sudo supervisorctl restart backend

# Check logs
tail -f /var/log/supervisor/backend.*.log
```

### Startup Verification

On startup, the server logs:
```
======================================================================
StoryMe API Starting
======================================================================
Storage Type: local
Storage Info: {'type': 'local', 'templates_dir': '/app/backend/templates', ...}
Stories Loaded: 1
  - forest_of_smiles: 10/10 templates found
======================================================================
```

## Testing

### Test Story Endpoints
```bash
# List stories
curl http://localhost:8001/api/stories

# Get story by index
curl http://localhost:8001/api/stories/0

# Verify templates
curl http://localhost:8001/api/stories/verify/forest_of_smiles
```

### Test PDF Generation
```bash
curl -X POST http://localhost:8001/api/generate \
  -F "name=TestChild" \
  -F "image=@/path/to/photo.jpg" \
  -F "story_id=forest_of_smiles" \
  -o storybook.pdf
```

## Design Principles

### 1. Clean Architecture
- **Routes** handle HTTP concerns only
- **Services** contain business logic
- **Storage** handles file operations
- **Models** define data structures

### 2. Dependency Inversion
- Services depend on `StorageInterface`, not concrete implementations
- Easy to add new storage backends (Google Cloud, Azure, etc.)

### 3. Single Responsibility
- Each service has one clear purpose
- Storage abstraction isolates infrastructure concerns
- Story registry separates data from logic

### 4. Extensibility
- Add new stories without code changes
- Switch storage backends via configuration
- Add new endpoints without touching existing code

## Future Enhancements

### Easy to Add:
1. **More Stories** - Add to `story_service.py`
2. **Age-Based Filtering** - Already implemented
3. **CDN URLs** - Update storage abstraction
4. **Caching** - Add Redis layer
5. **Database** - Store user-generated content
6. **Payment Integration** - New service layer
7. **Multi-language** - Add translation service

### Storage Backends:
- ✅ Local Filesystem
- ✅ Amazon S3
- 🔄 Google Cloud Storage (extend `StorageInterface`)
- 🔄 Azure Blob Storage (extend `StorageInterface`)

## Troubleshooting

### Template Not Found
```bash
# Verify templates exist
GET /api/stories/verify/forest_of_smiles

# Check storage configuration
echo $STORAGE_TYPE

# For S3: verify bucket access
aws s3 ls s3://your-bucket/templates/stories/forest_of_smiles/
```

### Storage Errors
```bash
# Check logs
tail -f /var/log/supervisor/backend.err.log | grep -i storage

# Verify permissions (local)
ls -la /app/backend/templates/stories/

# Verify S3 credentials
aws s3 ls s3://your-bucket/
```

## Dependencies

```txt
fastapi==0.110.1
uvicorn==0.25.0
python-multipart>=0.0.9
Pillow>=10.0.0
reportlab>=4.0.0
motor==3.3.1
pydantic>=2.6.4
python-dotenv>=1.0.1

# Optional (for S3)
boto3>=1.34.0
```

## API Documentation

Access interactive API docs:
- **Swagger UI**: http://localhost:8001/docs
- **ReDoc**: http://localhost:8001/redoc

## License

MIT

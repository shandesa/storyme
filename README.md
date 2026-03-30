# StoryMe - Personalized Storybook Generator

## Project Overview

StoryMe is an MVP web application that generates personalized PDF storybooks for children. Parents upload a child's photo and enter their name, and the app creates a custom 10-page storybook with the child's face inserted into each page.

## Repository Structure

```
/app/
├── backend/                          # FastAPI Backend
│   ├── server.py                     # Main FastAPI application
│   ├── requirements.txt              # Python dependencies
│   ├── .env                          # Environment variables
│   │
│   ├── models/                       # Data Models
│   │   ├── __init__.py
│   │   └── story.py                  # Story, Page, FacePlacement models
│   │
│   ├── services/                     # Business Logic Layer
│   │   ├── __init__.py
│   │   ├── story_service.py          # StoryRepository (manage stories)
│   │   ├── image_service.py          # ImageService (face extraction, composition)
│   │   └── pdf_service.py            # PDFService (PDF generation)
│   │
│   ├── routes/                       # API Routes
│   │   ├── __init__.py
│   │   └── generate.py               # POST /api/generate endpoint
│   │
│   ├── core/                         # Core Utilities
│   │   ├── __init__.py
│   │   └── storage.py                # File operations (save, delete)
│   │
│   ├── templates/                    # Story Page Templates
│   │   ├── page1.png                 # Template for page 1
│   │   ├── page2.png                 # Template for page 2
│   │   └── ... (page3-10.png)
│   │
│   ├── uploads/                      # Temporary uploaded images
│   ├── output/                       # Generated PDFs and processed images
│   └── create_templates.py           # Script to generate placeholder templates
│
├── frontend/                         # React Frontend
│   ├── package.json                  # Node dependencies
│   ├── .env                          # Frontend environment variables
│   ├── public/
│   │   └── index.html                # HTML template (updated title)
│   └── src/
│       ├── index.js                  # Entry point with Toaster
│       ├── App.js                    # Main component with upload form
│       ├── App.css                   # Styles
│       ├── index.css                 # Global styles
│       └── components/ui/            # Shadcn UI components
│           ├── button.jsx
│           ├── card.jsx
│           ├── input.jsx
│           ├── label.jsx
│           └── sonner.jsx            # Toast notifications
│
├── tests/                            # Comprehensive Test Suite
│   ├── README.md                     # Test documentation
│   ├── config.py                     # Centralized test configuration
│   │
│   ├── backend/                      # Backend API Tests
│   │   └── test_api_storybook_generation.py  # 9 comprehensive tests
│   │
│   ├── integration/                  # End-to-End Tests
│   │   └── test_frontend_download.py # Full download flow test
│   │
│   ├── test_data/                    # Test input files
│   │   └── test_upload.jpg           # Generated test images
│   │
│   └── test_output/                  # Test result PDFs
│       ├── Emma_test.pdf
│       ├── Liam_test.pdf
│       └── IntegrationTest_integration_test.pdf
│
└── README.md                         # This file
```

## Architecture Highlights

### Extensible Story System

The app is designed to easily support 50+ stories grouped by age:

```python
# backend/services/story_service.py
class StoryRepository:
    def _initialize_stories(self):
        stories = {}
        
        # Story 1: Forest of Smiles (Age 3-6)
        stories['forest_of_smiles'] = Story(...)
        
        # Easy to add more:
        # stories['ocean_adventure'] = Story(...)
        # stories['space_journey'] = Story(...)
        
        return stories
    
    def get_stories_by_age_group(self, age_group: str):
        return [s for s in self._stories.values() if s.age_group == age_group]
```

### Clean Separation of Concerns

```
API Route → Service Layer → Core Layer
    ↓           ↓              ↓
generate.py → image_service → storage.py
              pdf_service
              story_service
```

- **Routes**: Handle HTTP requests/responses only
- **Services**: Business logic (face extraction, PDF creation)
- **Core**: Reusable utilities (file operations)
- **Models**: Data structures (Story, Page, FacePlacement)

## Key Features

### 1. Story: "The Forest of Smiles"

- 10 pages of magical adventure
- Child meets friendly animals (rabbit, elephant, deer, etc.)
- Teaches kindness, peace, and joy
- Each page has specific face placement coordinates

### 2. Image Processing

- **Face Extraction**: Center crop and resize with high-quality resampling
- **Circular Mask**: Applies circular mask for professional look
- **Template Composition**: Pastes face at precise coordinates per page

### 3. PDF Generation

- **Multi-page PDF**: Title page + 10 story pages
- **Personalization**: Child's name throughout story
- **Professional Layout**: Proper spacing, fonts, images

### 4. Clean UI

- Simple, accessible interface
- Sober color scheme (light blue, black)
- Real-time image preview
- Loading states
- Toast notifications

## Configuration

### Backend Environment Variables

```bash
# /app/backend/.env
MONGO_URL="mongodb://localhost:27017"
DB_NAME="test_database"
CORS_ORIGINS="*"
```

### Frontend Environment Variables

```bash
# /app/frontend/.env
REACT_APP_BACKEND_URL=https://tale-forge-66.preview.emergentagent.com
```

## Running the Application

### Backend

```bash
# Backend runs on 0.0.0.0:8001 (managed by supervisor)
sudo supervisorctl status backend
sudo supervisorctl restart backend

# View logs
tail -f /var/log/supervisor/backend.*.log
```

### Frontend

```bash
# Frontend runs on port 3000 (managed by supervisor)
sudo supervisorctl status frontend
sudo supervisorctl restart frontend

# View logs
tail -f /var/log/supervisor/frontend.*.log
```

### Access the App

- Frontend: https://tale-forge-66.preview.emergentagent.com
- Backend API: https://tale-forge-66.preview.emergentagent.com/api

## API Documentation

### POST /api/generate

Generate personalized storybook PDF.

**Request:**
```bash
curl -X POST "https://tale-forge-66.preview.emergentagent.com/api/generate" \
  -F "name=Emma" \
  -F "image=@child_photo.jpg" \
  -o storybook.pdf
```

**Form Data:**
- `name` (string, required): Child's name
- `image` (file, required): Child's photo (JPEG, PNG, or WEBP, max 5MB)

**Response:**
- Content-Type: `application/pdf`
- Content-Disposition: `attachment; filename="{name}_{id}.pdf"`

**Validation:**
- Returns 400 for invalid file type
- Returns 422 for missing name or image

## Testing

Comprehensive test suite with **10 total tests** (9 backend + 1 integration).

### Backend Tests (9 tests - 100% pass rate)

```bash
cd /app/tests/backend
python test_api_storybook_generation.py
```

**Tests:**
1. API Connectivity
2. Missing Name Validation
3. Missing Image Validation
4. Invalid File Type
5. Successful PDF Generation
6. **PDF Page Count (CONFIGURABLE - validates 10 story pages)**
7. PDF Name Personalization
8. Multiple Names Batch
9. Download Headers

### Integration Tests (1 test)

```bash
cd /app/tests/integration
python test_frontend_download.py
```

**Tests:**
1. Complete End-to-End Download Flow
   - UI interaction
   - Form submission
   - Actual PDF download
   - PDF validation (page count, content)

### Configurable Page Count

Expected page count is configurable in `/app/tests/config.py`:

```python
EXPECTED_STORY_PAGES = 10  # Change this number
EXPECTED_TOTAL_PDF_PAGES = EXPECTED_STORY_PAGES + 1  # Auto-calculated
```

Tests will validate PDFs have exactly this many pages.

## Dependencies

### Backend

```txt
fastapi==0.110.1
uvicorn==0.25.0
motor==3.3.1
pydantic>=2.6.4
python-multipart>=0.0.9
Pillow (latest)
reportlab (latest)
```

### Frontend

```json
{
  "axios": "^1.8.4",
  "react": "^19.0.0",
  "react-router-dom": "^7.5.1",
  "lucide-react": "^0.507.0",
  "sonner": "^2.0.3",
  "@radix-ui/*": "latest"
}
```

### Testing

```txt
requests
pypdf
Pillow
playwright
```

## Future Enhancements

### Easy to Add

1. **More Stories**: Add to `StoryRepository._initialize_stories()`
2. **Age Group Selection**: UI dropdown to select age-appropriate stories
3. **Advanced Face Detection**: OpenCV/AI for better face extraction
4. **Story Templates**: Allow users to upload custom templates
5. **Email Delivery**: Send PDF via email instead of download
6. **Payment Integration**: Charge for premium stories
7. **Multi-language Support**: Translate stories to different languages

### Code is Ready For

- **S3 Storage**: Replace `core/storage.py` with S3 client
- **Multiple Stories**: Already structured with `StoryRepository`
- **Age Filtering**: Method already exists: `get_stories_by_age_group()`
- **Dynamic Templates**: Template path is configurable per page

## Technology Stack

- **Backend**: Python 3.11, FastAPI, Pillow, ReportLab
- **Frontend**: React 19, Shadcn/UI, Tailwind CSS
- **Database**: MongoDB (for future features)
- **Testing**: Requests, PyPDF, Playwright
- **Deployment**: Supervisor, Kubernetes ingress

## Development Notes

### Hot Reload

- Both frontend and backend have hot reload enabled
- Changes to code auto-restart services
- Only restart manually after `.env` or dependency changes

### URL Configuration

- Backend binds to `0.0.0.0:8001`
- Frontend uses `REACT_APP_BACKEND_URL` for API calls
- All API routes prefixed with `/api`
- Kubernetes ingress routes `/api/*` → backend:8001

### File Structure Best Practices

- ✓ Business logic in services (not routes)
- ✓ Reusable utilities in core
- ✓ Models define data structures
- ✓ Routes handle HTTP only
- ✓ Configurable via environment variables

## License

MIT

## Support

For issues or questions, check:
1. Test logs in `/app/tests/test_output/`
2. Backend logs: `/var/log/supervisor/backend.*.log`
3. Frontend logs: `/var/log/supervisor/frontend.*.log`

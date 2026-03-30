# StoryMe Repository Structure

## Complete Directory Tree

```
/app/
├── backend/                                    # FastAPI Backend Service
│   ├── server.py                              # Main FastAPI application entry point
│   ├── requirements.txt                       # Python dependencies
│   ├── .env                                   # Environment variables (MONGO_URL, DB_NAME)
│   ├── create_templates.py                   # Script to generate placeholder templates
│   │
│   ├── models/                                # Data Models
│   │   ├── __init__.py
│   │   └── story.py                          # Story, Page, FacePlacement models
│   │
│   ├── services/                              # Business Logic Layer
│   │   ├── __init__.py
│   │   ├── story_service.py                  # StoryRepository - manages available stories
│   │   ├── image_service.py                  # ImageService - face extraction & composition
│   │   └── pdf_service.py                    # PDFService - PDF generation with ReportLab
│   │
│   ├── routes/                                # API Routes
│   │   ├── __init__.py
│   │   └── generate.py                       # POST /api/generate endpoint
│   │
│   ├── core/                                  # Core Utilities
│   │   ├── __init__.py
│   │   └── storage.py                        # File operations (save_file, delete_file)
│   │
│   ├── templates/                             # Story Page Templates (10 images)
│   │   ├── page1.png                         # Light blue background with decorative elements
│   │   ├── page2.png                         # Lighter blue
│   │   ├── page3.png                         # Light indigo
│   │   ├── page4.png                         # Light purple
│   │   ├── page5.png                         # Lighter purple
│   │   ├── page6.png                         # Light pink
│   │   ├── page7.png                         # Light yellow
│   │   ├── page8.png                         # Light green
│   │   ├── page9.png                         # Light teal
│   │   └── page10.png                        # Light gray
│   │
│   ├── uploads/                               # Temporary storage for uploaded images
│   │   └── (auto-cleaned after processing)
│   │
│   └── output/                                # Generated PDFs and processed images
│       └── (PDFs and composed page images)
│
├── frontend/                                   # React Frontend Application
│   ├── package.json                           # Node.js dependencies
│   ├── .env                                   # Frontend env vars (REACT_APP_BACKEND_URL)
│   ├── tailwind.config.js                     # Tailwind CSS configuration
│   ├── postcss.config.js                      # PostCSS configuration
│   │
│   ├── public/
│   │   └── index.html                        # HTML template (title: "StoryMe")
│   │
│   └── src/
│       ├── index.js                          # Entry point with Toaster component
│       ├── App.js                            # Main component - upload form & logic
│       ├── App.css                           # Component-specific styles
│       ├── index.css                         # Global Tailwind styles
│       │
│       └── components/ui/                    # Shadcn UI Components
│           ├── button.jsx                    # Button component
│           ├── card.jsx                      # Card, CardHeader, CardContent
│           ├── input.jsx                     # Input field
│           ├── label.jsx                     # Label component
│           └── sonner.jsx                    # Toast notifications
│
├── tests/                                      # Comprehensive Test Suite
│   ├── README.md                              # Complete test documentation
│   ├── config.py                              # Centralized test configuration
│   │                                          # - EXPECTED_STORY_PAGES = 10 (configurable)
│   │                                          # - API_BASE_URL, FRONTEND_URL
│   │                                          # - Validation thresholds
│   ├── run_all_tests.sh                       # Script to run all tests
│   │
│   ├── backend/                               # Backend API Tests
│   │   └── test_api_storybook_generation.py  # 9 comprehensive tests:
│   │                                          # 1. API Connectivity
│   │                                          # 2. Missing Name Validation
│   │                                          # 3. Missing Image Validation
│   │                                          # 4. Invalid File Type
│   │                                          # 5. Successful PDF Generation
│   │                                          # 6. PDF Page Count (CONFIGURABLE)
│   │                                          # 7. PDF Name Personalization
│   │                                          # 8. Multiple Names Batch
│   │                                          # 9. Download Headers
│   │
│   ├── integration/                           # Frontend E2E Tests
│   │   └── test_frontend_download.py         # Complete download flow test:
│   │                                          # - Browser automation with Playwright
│   │                                          # - Form interaction
│   │                                          # - Actual PDF download
│   │                                          # - PDF validation (pages, content)
│   │
│   ├── test_data/                             # Test Input Files
│   │   └── test_upload.jpg                   # Auto-generated test images
│   │
│   └── test_output/                           # Test Result PDFs
│       ├── Emma_test.pdf                     # Sample generated PDFs
│       ├── Liam_test.pdf
│       ├── TestChild_test.pdf
│       └── IntegrationTest_integration_test.pdf
│
├── README.md                                   # Main project documentation
└── REPOSITORY_STRUCTURE.md                    # This file
```

## File Count Summary

- **Total Backend Files**: 13 Python files + 10 templates
- **Total Frontend Files**: 7 JS/JSX files + 5+ UI components
- **Total Test Files**: 3 test files (10 total tests)
- **Documentation**: 4 markdown files

## Key Configuration Files

### Backend Configuration
- `/app/backend/.env` - MongoDB URL, DB name, CORS
- `/app/backend/requirements.txt` - Python dependencies (25+ packages)

### Frontend Configuration
- `/app/frontend/.env` - Backend API URL
- `/app/frontend/package.json` - React dependencies (56 packages)

### Test Configuration
- `/app/tests/config.py` - **All test parameters (including page count)**

## Service Ports

- **Backend**: Internal port 8001 (mapped via Kubernetes ingress)
- **Frontend**: Internal port 3000 (mapped via Kubernetes ingress)
- **External URL**: https://tale-forge-66.preview.emergentagent.com

## Important Paths

### Backend
- Templates: `/app/backend/templates/page{1-10}.png`
- Output: `/app/backend/output/`
- Uploads: `/app/backend/uploads/` (temporary)

### Tests
- Configuration: `/app/tests/config.py`
- Test Data: `/app/tests/test_data/`
- Test Output: `/app/tests/test_output/`

## Logs Location

- Backend: `/var/log/supervisor/backend.err.log` and `.out.log`
- Frontend: `/var/log/supervisor/frontend.err.log` and `.out.log`

## Quick Commands

### Run Tests
```bash
# All tests (10 total)
/app/tests/run_all_tests.sh

# Backend only (9 tests)
cd /app/tests/backend && python test_api_storybook_generation.py

# Integration only (1 test)
cd /app/tests/integration && python test_frontend_download.py
```

### View Logs
```bash
# Backend
tail -f /var/log/supervisor/backend.*.log

# Frontend
tail -f /var/log/supervisor/frontend.*.log
```

### Restart Services
```bash
sudo supervisorctl restart backend
sudo supervisorctl restart frontend
```

## Architecture Flow

```
User Browser
    ↓
Frontend (React) - Upload form
    ↓ (REACT_APP_BACKEND_URL/api/generate)
API Route (routes/generate.py)
    ↓
Services Layer:
    - StoryService → Get story data
    - ImageService → Process face & compose templates
    - PDFService → Generate PDF
    ↓
Core Layer (storage.py)
    ↓
File System (uploads/, output/, templates/)
    ↓
PDF returned to user
```

## Test Coverage

### Backend Tests (9 tests)
- ✓ API validation (3 tests)
- ✓ File type validation (1 test)
- ✓ PDF generation (2 tests)
- ✓ **Page count validation (1 test - CONFIGURABLE)**
- ✓ Personalization (1 test)
- ✓ Batch testing (1 test)

### Integration Tests (1 test)
- ✓ Complete E2E flow with actual browser download

**Total: 10 tests, 100% pass rate**

## Extension Points

To add new stories:
1. Edit `/app/backend/services/story_service.py`
2. Add new Story object in `_initialize_stories()`
3. Create 10 new template images in `/app/backend/templates/`
4. Update frontend to show story selection (future)

To change page count:
1. Edit `/app/tests/config.py` → `EXPECTED_STORY_PAGES`
2. Update story in `story_service.py` with new pages
3. Create additional template images
4. Tests will automatically validate new count

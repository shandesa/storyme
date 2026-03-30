"""Test Configuration

Centralized configuration for all tests.
Makes it easy to update test parameters in one place.
"""

import os
from pathlib import Path

# ============================================================================
# DIRECTORY PATHS
# ============================================================================
BASE_DIR = Path(__file__).parent.parent
BACKEND_DIR = BASE_DIR / "backend"
FRONTEND_DIR = BASE_DIR / "frontend"
TESTS_DIR = BASE_DIR / "tests"
TEST_DATA_DIR = TESTS_DIR / "test_data"
TEST_OUTPUT_DIR = TESTS_DIR / "test_output"

# Ensure test directories exist
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# API CONFIGURATION
# ============================================================================
# Backend API base URL (external URL for end-to-end testing)
BACKEND_URL = os.getenv(
    'REACT_APP_BACKEND_URL',
    'https://tale-forge-66.preview.emergentagent.com'
)
API_BASE_URL = f"{BACKEND_URL}/api"

# API endpoints
API_ENDPOINTS = {
    'root': '/',
    'status_post': '/status',
    'status_get': '/status',
    'generate': '/generate',
}

# ============================================================================
# STORY CONFIGURATION
# ============================================================================
# Expected number of story pages (configurable)
EXPECTED_STORY_PAGES = 10

# Expected total PDF pages (title page + story pages)
EXPECTED_TOTAL_PDF_PAGES = EXPECTED_STORY_PAGES + 1

# Story metadata
STORY_CONFIG = {
    'story_id': 'forest_of_smiles',
    'title_template': '{name} and the Forest of Smiles',
    'age_group': '3-6',
    'expected_pages': EXPECTED_STORY_PAGES,
}

# ============================================================================
# FILE UPLOAD CONFIGURATION
# ============================================================================
# Allowed image types
ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']

# Maximum file size (5MB)
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Test image dimensions
TEST_IMAGE_SIZE = (400, 400)

# ============================================================================
# TEST DATA
# ============================================================================
TEST_CHILD_NAMES = [
    'Emma',
    'Liam',
    'Test Child',
    'अर्जुन',  # Unicode test
]

# ============================================================================
# VALIDATION THRESHOLDS
# ============================================================================
# PDF file size expectations (in KB)
MIN_PDF_SIZE_KB = 50  # Minimum expected PDF size
MAX_PDF_SIZE_KB = 5000  # Maximum expected PDF size

# API response timeout (seconds)
API_TIMEOUT = 30

# ============================================================================
# BROWSER TEST CONFIGURATION (for frontend tests)
# ============================================================================
FRONTEND_URL = BACKEND_URL  # Same base URL
BROWSER_TIMEOUT = 10000  # milliseconds

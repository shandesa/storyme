# StoryMe Test Suite

## Overview

Comprehensive test suite for the StoryMe personalized storybook generator application.

## Test Structure

```
tests/
├── config.py                           # Centralized test configuration
├── backend/
│   └── test_api_storybook_generation.py   # Backend API tests (9 tests)
├── integration/
│   └── test_frontend_download.py          # Frontend E2E tests (1 test)
├── test_data/                          # Test images and input data
└── test_output/                        # Generated PDFs for validation
```

## Configuration

All test parameters are configurable in `config.py`:

- **EXPECTED_STORY_PAGES**: Number of story pages (default: 10)
- **EXPECTED_TOTAL_PDF_PAGES**: Total PDF pages including title (default: 11)
- **API_BASE_URL**: Backend API endpoint
- **FRONTEND_URL**: Frontend application URL
- **Test data**: Child names, image sizes, validation thresholds

## Backend Tests

### Running Backend Tests

```bash
cd /app/tests/backend
python test_api_storybook_generation.py
```

### Test Coverage

| Test # | Test Name | Description |
|--------|-----------|-------------|
| 1 | API Connectivity | Verifies API is accessible |
| 2 | Missing Name Validation | Validates name is required |
| 3 | Missing Image Validation | Validates image is required |
| 4 | Invalid File Type | Rejects non-image files |
| 5 | Successful PDF Generation | Generates PDF with valid inputs |
| 6 | **PDF Page Count (CONFIGURABLE)** | **Validates exactly 10 story pages + 1 title page** |
| 7 | PDF Name Personalization | Verifies child's name in PDF |
| 8 | Multiple Names Batch | Tests with various names including Unicode |
| 9 | Download Headers | Validates HTTP headers for download |

### Test Results

```
Total Tests: 9
✓ Passed: 9
✗ Failed: 0
Success Rate: 100.0%
```

## Integration Tests

### Running Integration Tests

```bash
cd /app/tests/integration
python test_frontend_download.py
```

### What It Tests

1. **Application Loading**: Frontend loads correctly
2. **UI Elements**: All form elements present
3. **Form Interaction**: Name input and file upload work
4. **Image Preview**: Uploaded image displays correctly
5. **PDF Generation**: Button triggers API call
6. **Actual Download**: PDF file is downloaded to browser
7. **PDF Validation**: 
   - File exists and has correct size
   - Contains exactly 11 pages (configurable)
   - Child's name appears in title and story

### Test Results

```
Download Flow Summary:
  • Application loaded: ✓
  • Form filled: ✓
  • Image uploaded: ✓
  • PDF generated: ✓
  • PDF downloaded: ✓
  • PDF validated: ✓
  • Page count (11): ✓
  • Personalization: ✓
```

## Configurable Page Count

### How to Change Expected Page Count

1. Open `tests/config.py`
2. Modify `EXPECTED_STORY_PAGES`:

```python
# Change from 10 to any number
EXPECTED_STORY_PAGES = 15  # Now expects 15 story pages
```

3. Run tests again - they will validate against new count

### Where Page Count is Validated

- **Backend Test #6**: Validates PDF has `EXPECTED_TOTAL_PDF_PAGES` (title + story pages)
- **Integration Test**: Validates downloaded PDF has correct page count

## Test Output

All generated PDFs are saved to `/app/tests/test_output/` for manual inspection:

- `Emma_test.pdf`
- `Liam_test.pdf`
- `IntegrationTest_integration_test.pdf`
- etc.

## Dependencies

```bash
pip install requests pypdf pillow playwright
playwright install chromium
```

## Running All Tests

```bash
# Backend tests
cd /app/tests/backend
python test_api_storybook_generation.py

# Integration tests
cd /app/tests/integration
python test_frontend_download.py
```

## Test Comments Structure

All tests include extensive comments:

- **File-level docstring**: Explains purpose and test flow
- **Class-level docstring**: Describes test suite
- **Function-level docstring**: Details what each test validates
- **Inline comments**: Mark important steps and validations
- **Separation markers**: `===` lines separate test sections
- **Print statements**: Real-time progress with ✓ symbols

## Understanding Test Output

Tests print structured, human-readable output:

```
======================================================================
TEST 6: PDF Page Count Validation (CONFIGURABLE)
======================================================================
Configuration:
  - Expected Story Pages: 10
  - Expected Total Pages: 11 (1 title + 10 story)

PDF Analysis:
  ✓ PDF is valid: True
  ✓ Total pages: 11
  ✓ File size: 151.33 KB

✓ SUCCESS: PDF has exactly 11 pages as configured!
```

## Troubleshooting

### Backend Tests Failing

- Check `API_BASE_URL` in `config.py`
- Verify backend is running: `sudo supervisorctl status backend`
- Check backend logs: `tail -f /var/log/supervisor/backend.*.log`

### Frontend Tests Failing

- Check `FRONTEND_URL` in `config.py`
- Verify frontend is running: `sudo supervisorctl status frontend`
- Review error screenshot: `/app/tests/test_output/error_screenshot.png`

### Download Not Working

- Integration test proves download works programmatically
- Browser cache issues: Try incognito mode or clear cache
- Check browser console for JavaScript errors

## CI/CD Integration

To run tests in CI/CD pipeline:

```bash
#!/bin/bash
set -e

# Backend tests
cd /app/tests/backend
python test_api_storybook_generation.py

# Integration tests
cd /app/tests/integration
python test_frontend_download.py

echo "All tests passed!"
```

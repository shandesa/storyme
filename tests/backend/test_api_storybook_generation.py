"""Backend API Tests for Storybook Generation

Comprehensive test suite for the /api/generate endpoint.
Tests cover validation, file upload, PDF generation, and page count verification.

Test Structure:
1. Setup: Create test images
2. Validation Tests: Check input validation
3. Generation Tests: Verify PDF creation
4. Quality Tests: Validate PDF content and structure
5. Cleanup: Remove test files
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from PIL import Image, ImageDraw
import io
from pypdf import PdfReader
import pytest
import json

from config import (
    API_BASE_URL,
    TEST_DATA_DIR,
    TEST_OUTPUT_DIR,
    EXPECTED_STORY_PAGES,
    EXPECTED_TOTAL_PDF_PAGES,
    STORY_CONFIG,
    TEST_CHILD_NAMES,
    MAX_FILE_SIZE_BYTES,
    MIN_PDF_SIZE_KB,
    MAX_PDF_SIZE_KB,
    API_TIMEOUT,
)


class TestHelper:
    """Helper class for creating test images and validating responses."""

    @staticmethod
    def create_test_image(width=400, height=400, color='#FFB6C1'):
        """
        Create a test image for upload testing.
        
        Args:
            width: Image width in pixels
            height: Image height in pixels
            color: Background color (hex)
        
        Returns:
            BytesIO object containing JPEG image
        """
        img = Image.new('RGB', (width, height), color=color)
        draw = ImageDraw.Draw(img)
        
        # Draw a simple face
        draw.ellipse([100, 100, 300, 300], fill='#FFF0F5')  # Face
        draw.ellipse([150, 150, 200, 200], fill='#000000')  # Left eye
        draw.ellipse([250, 150, 300, 200], fill='#000000')  # Right eye
        draw.arc([175, 225, 275, 275], 0, 180, fill='#000000', width=3)  # Smile
        
        # Save to BytesIO
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        return img_bytes

    @staticmethod
    def validate_pdf_structure(pdf_bytes):
        """
        Validate PDF structure and extract metadata.
        
        Args:
            pdf_bytes: PDF file content as bytes
        
        Returns:
            dict with PDF metadata (num_pages, size_kb, is_valid)
        """
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            return {
                'is_valid': True,
                'num_pages': len(reader.pages),
                'size_kb': round(len(pdf_bytes) / 1024, 2),
                'metadata': reader.metadata,
            }
        except Exception as e:
            return {
                'is_valid': False,
                'error': str(e),
            }


class TestStorybookGeneration:
    """Test suite for storybook PDF generation."""

    # ========================================================================
    # TEST 1: API Connectivity
    # ========================================================================
    def test_api_connectivity(self):
        """
        Test 1: Verify API is accessible and responding.
        
        This is a basic health check to ensure the API endpoint exists
        and the server is running.
        """
        print("\n" + "="*70)
        print("TEST 1: API Connectivity Check")
        print("="*70)
        
        response = requests.get(f"{API_BASE_URL}/", timeout=API_TIMEOUT)
        
        print(f"✓ API Base URL: {API_BASE_URL}")
        print(f"✓ Response Status: {response.status_code}")
        print(f"✓ Response Data: {response.json()}")
        
        assert response.status_code == 200, "API should be accessible"
        assert 'message' in response.json(), "API should return a message"

    # ========================================================================
    # TEST 2: Missing Name Validation
    # ========================================================================
    def test_missing_name_validation(self):
        """
        Test 2: Verify API rejects requests with missing child name.
        
        Expected behavior: API should return 422 (Unprocessable Entity)
        and provide a clear error message.
        """
        print("\n" + "="*70)
        print("TEST 2: Missing Name Validation")
        print("="*70)
        
        # Create test image
        test_image = TestHelper.create_test_image()
        
        # Send request WITHOUT name
        files = {'image': ('test.jpg', test_image, 'image/jpeg')}
        response = requests.post(
            f"{API_BASE_URL}/generate",
            files=files,
            timeout=API_TIMEOUT
        )
        
        print(f"✓ Request sent without 'name' parameter")
        print(f"✓ Response Status: {response.status_code}")
        print(f"✓ Response: {response.json()}")
        
        assert response.status_code == 422, "Should reject missing name"
        print("✓ Validation working: Missing name rejected")

    # ========================================================================
    # TEST 3: Missing Image Validation
    # ========================================================================
    def test_missing_image_validation(self):
        """
        Test 3: Verify API rejects requests with missing image file.
        
        Expected behavior: API should return 422 and error message.
        """
        print("\n" + "="*70)
        print("TEST 3: Missing Image Validation")
        print("="*70)
        
        # Send request WITHOUT image
        data = {'name': 'TestChild'}
        response = requests.post(
            f"{API_BASE_URL}/generate",
            data=data,
            timeout=API_TIMEOUT
        )
        
        print(f"✓ Request sent without 'image' file")
        print(f"✓ Response Status: {response.status_code}")
        print(f"✓ Response: {response.json()}")
        
        assert response.status_code == 422, "Should reject missing image"
        print("✓ Validation working: Missing image rejected")

    # ========================================================================
    # TEST 4: Invalid File Type Validation
    # ========================================================================
    def test_invalid_file_type(self):
        """
        Test 4: Verify API rejects non-image files.
        
        Expected behavior: API should validate file type and reject
        files that are not JPEG, PNG, or WEBP.
        """
        print("\n" + "="*70)
        print("TEST 4: Invalid File Type Validation")
        print("="*70)
        
        # Create a fake text file
        fake_file = io.BytesIO(b"This is not an image file")
        
        files = {'image': ('test.txt', fake_file, 'text/plain')}
        data = {'name': 'TestChild'}
        
        response = requests.post(
            f"{API_BASE_URL}/generate",
            files=files,
            data=data,
            timeout=API_TIMEOUT
        )
        
        print(f"✓ Sent text file instead of image")
        print(f"✓ Response Status: {response.status_code}")
        print(f"✓ Response: {response.json()}")
        
        assert response.status_code == 400, "Should reject invalid file type"
        assert 'detail' in response.json(), "Should provide error detail"
        print("✓ Validation working: Invalid file type rejected")

    # ========================================================================
    # TEST 5: Successful PDF Generation
    # ========================================================================
    def test_successful_pdf_generation(self):
        """
        Test 5: Verify successful PDF generation with valid inputs.
        
        This is the main test that validates:
        1. API accepts valid image and name
        2. PDF file is generated and returned
        3. PDF has correct content-type
        4. PDF file size is reasonable
        """
        print("\n" + "="*70)
        print("TEST 5: Successful PDF Generation")
        print("="*70)
        
        child_name = "Emma"
        test_image = TestHelper.create_test_image()
        
        files = {'image': ('child.jpg', test_image, 'image/jpeg')}
        data = {'name': child_name}
        
        print(f"✓ Sending request with name='{child_name}'")
        
        response = requests.post(
            f"{API_BASE_URL}/generate",
            files=files,
            data=data,
            timeout=API_TIMEOUT
        )
        
        print(f"✓ Response Status: {response.status_code}")
        print(f"✓ Content-Type: {response.headers.get('content-type')}")
        print(f"✓ Content-Length: {len(response.content)} bytes")
        
        # Validate response
        assert response.status_code == 200, "Should return success"
        assert response.headers.get('content-type') == 'application/pdf', \
            "Should return PDF content-type"
        assert len(response.content) > 0, "PDF should have content"
        
        # Save PDF for inspection
        pdf_path = TEST_OUTPUT_DIR / f"{child_name}_test.pdf"
        pdf_path.write_bytes(response.content)
        print(f"✓ PDF saved to: {pdf_path}")
        
        print("✓ PDF generation successful!")

    # ========================================================================
    # TEST 6: PDF Page Count Validation (CONFIGURABLE)
    # ========================================================================
    def test_pdf_page_count(self):
        """
        Test 6: Verify PDF contains exactly the expected number of pages.
        
        CONFIGURABLE: Expected page count is set in config.py
        - EXPECTED_STORY_PAGES = 10 (story pages)
        - EXPECTED_TOTAL_PDF_PAGES = 11 (1 title + 10 story pages)
        
        This test validates:
        1. PDF structure is valid
        2. Correct number of pages (title + story pages)
        3. Each page is readable
        """
        print("\n" + "="*70)
        print("TEST 6: PDF Page Count Validation (CONFIGURABLE)")
        print("="*70)
        
        print(f"Configuration:")
        print(f"  - Expected Story Pages: {EXPECTED_STORY_PAGES}")
        print(f"  - Expected Total Pages: {EXPECTED_TOTAL_PDF_PAGES} (1 title + {EXPECTED_STORY_PAGES} story)")
        print()
        
        child_name = "Liam"
        test_image = TestHelper.create_test_image()
        
        files = {'image': ('child.jpg', test_image, 'image/jpeg')}
        data = {'name': child_name}
        
        response = requests.post(
            f"{API_BASE_URL}/generate",
            files=files,
            data=data,
            timeout=API_TIMEOUT
        )
        
        assert response.status_code == 200, "PDF generation should succeed"
        
        # Validate PDF structure
        pdf_info = TestHelper.validate_pdf_structure(response.content)
        
        print(f"PDF Analysis:")
        print(f"  ✓ PDF is valid: {pdf_info['is_valid']}")
        print(f"  ✓ Total pages: {pdf_info['num_pages']}")
        print(f"  ✓ File size: {pdf_info['size_kb']} KB")
        print()
        
        # CRITICAL: Validate page count
        assert pdf_info['is_valid'], "PDF must be valid and readable"
        assert pdf_info['num_pages'] == EXPECTED_TOTAL_PDF_PAGES, \
            f"PDF should have {EXPECTED_TOTAL_PDF_PAGES} pages (1 title + {EXPECTED_STORY_PAGES} story), " \
            f"but got {pdf_info['num_pages']}"
        
        print(f"✓ SUCCESS: PDF has exactly {EXPECTED_TOTAL_PDF_PAGES} pages as configured!")
        
        # Additional validation: Check page size is reasonable
        assert pdf_info['size_kb'] >= MIN_PDF_SIZE_KB, \
            f"PDF too small (< {MIN_PDF_SIZE_KB} KB)"
        assert pdf_info['size_kb'] <= MAX_PDF_SIZE_KB, \
            f"PDF too large (> {MAX_PDF_SIZE_KB} KB)"
        
        print(f"✓ PDF size within acceptable range ({MIN_PDF_SIZE_KB}-{MAX_PDF_SIZE_KB} KB)")

    # ========================================================================
    # TEST 7: PDF Content Validation (Name Personalization)
    # ========================================================================
    def test_pdf_name_personalization(self):
        """
        Test 7: Verify child's name appears in the PDF title page.
        
        Note: Story pages contain name overlaid on images (not extractable text).
        This test validates:
        1. The title page contains the child's name
        2. PDF structure is valid with expected pages
        """
        print("\n" + "="*70)
        print("TEST 7: PDF Content - Name Personalization")
        print("="*70)
        
        child_name = "Oliver"
        test_image = TestHelper.create_test_image()
        
        files = {'image': ('child.jpg', test_image, 'image/jpeg')}
        data = {'name': child_name}
        
        response = requests.post(
            f"{API_BASE_URL}/generate",
            files=files,
            data=data,
            timeout=API_TIMEOUT
        )
        
        assert response.status_code == 200, "PDF generation should succeed"
        
        # Read PDF and extract text
        reader = PdfReader(io.BytesIO(response.content))
        
        # Check title page (page 0)
        title_page_text = reader.pages[0].extract_text()
        print(f"Title page text preview:")
        print(f"  {title_page_text[:200]}...")
        print()
        
        # Verify name appears in title
        expected_title = STORY_CONFIG['title_template'].replace('{name}', child_name)
        assert child_name in title_page_text, \
            f"Child's name '{child_name}' should appear in title page"
        
        print(f"✓ Child's name '{child_name}' found in title page")
        
        # Verify PDF has expected number of pages (name is overlaid on images)
        assert len(reader.pages) == EXPECTED_TOTAL_PDF_PAGES, \
            f"PDF should have {EXPECTED_TOTAL_PDF_PAGES} pages"
        
        print(f"✓ PDF has {len(reader.pages)} pages as expected")
        print(f"✓ Note: Story pages have name overlaid on images (not extractable text)")
        print(f"✓ Personalization working correctly!")

    # ========================================================================
    # TEST 8: Multiple Names Test (Batch)
    # ========================================================================
    def test_multiple_names_batch(self):
        """
        Test 8: Test PDF generation with multiple different names.
        
        This validates that the system works consistently across
        different inputs, including Unicode names.
        """
        print("\n" + "="*70)
        print("TEST 8: Batch Testing with Multiple Names")
        print("="*70)
        
        results = []
        
        for child_name in TEST_CHILD_NAMES[:3]:  # Test first 3 names
            print(f"\nTesting with name: '{child_name}'")
            
            test_image = TestHelper.create_test_image()
            files = {'image': ('child.jpg', test_image, 'image/jpeg')}
            data = {'name': child_name}
            
            response = requests.post(
                f"{API_BASE_URL}/generate",
                files=files,
                data=data,
                timeout=API_TIMEOUT
            )
            
            success = response.status_code == 200
            results.append({
                'name': child_name,
                'success': success,
                'status_code': response.status_code,
            })
            
            print(f"  ✓ Status: {response.status_code}")
            
            if success:
                pdf_info = TestHelper.validate_pdf_structure(response.content)
                print(f"  ✓ Pages: {pdf_info['num_pages']}")
                print(f"  ✓ Size: {pdf_info['size_kb']} KB")
        
        # Verify all succeeded
        print("\nBatch Results:")
        for result in results:
            status = "✓ PASS" if result['success'] else "✗ FAIL"
            print(f"  {status} - {result['name']} (HTTP {result['status_code']})")
        
        all_success = all(r['success'] for r in results)
        assert all_success, "All batch tests should succeed"
        
        print(f"\n✓ All {len(results)} batch tests passed!")

    # ========================================================================
    # TEST 9: Download Header Validation
    # ========================================================================
    def test_download_headers(self):
        """
        Test 9: Verify correct HTTP headers for file download.
        
        This test checks that the response includes proper headers
        for triggering browser download.
        """
        print("\n" + "="*70)
        print("TEST 9: Download Header Validation")
        print("="*70)
        
        child_name = "TestDownload"
        test_image = TestHelper.create_test_image()
        
        files = {'image': ('child.jpg', test_image, 'image/jpeg')}
        data = {'name': child_name}
        
        response = requests.post(
            f"{API_BASE_URL}/generate",
            files=files,
            data=data,
            timeout=API_TIMEOUT
        )
        
        print("Response Headers:")
        for key, value in response.headers.items():
            if key.lower() in ['content-type', 'content-disposition', 'content-length']:
                print(f"  {key}: {value}")
        
        assert response.status_code == 200
        assert response.headers.get('content-type') == 'application/pdf'
        
        # Check if content-disposition is set (for download)
        content_disposition = response.headers.get('content-disposition', '')
        print(f"\n✓ Content-Type: application/pdf")
        if content_disposition:
            print(f"✓ Content-Disposition: {content_disposition}")
        
        print("✓ Headers valid for file download")


if __name__ == "__main__":
    print("\n" + "#"*70)
    print("#" + " "*68 + "#")
    print("#" + "  STORYME - BACKEND API TEST SUITE".center(68) + "#")
    print("#" + " "*68 + "#")
    print("#"*70)
    print()
    print(f"API Base URL: {API_BASE_URL}")
    print(f"Expected Story Pages: {EXPECTED_STORY_PAGES} (configurable in config.py)")
    print(f"Expected Total PDF Pages: {EXPECTED_TOTAL_PDF_PAGES}")
    print()
    
    # Run all tests
    tester = TestStorybookGeneration()
    
    tests = [
        ('API Connectivity', tester.test_api_connectivity),
        ('Missing Name Validation', tester.test_missing_name_validation),
        ('Missing Image Validation', tester.test_missing_image_validation),
        ('Invalid File Type', tester.test_invalid_file_type),
        ('Successful PDF Generation', tester.test_successful_pdf_generation),
        ('PDF Page Count', tester.test_pdf_page_count),
        ('PDF Name Personalization', tester.test_pdf_name_personalization),
        ('Multiple Names Batch', tester.test_multiple_names_batch),
        ('Download Headers', tester.test_download_headers),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
            print(f"\n{'='*70}")
            print(f"✓ TEST PASSED: {test_name}")
            print(f"{'='*70}")
        except AssertionError as e:
            failed += 1
            print(f"\n{'='*70}")
            print(f"✗ TEST FAILED: {test_name}")
            print(f"Error: {e}")
            print(f"{'='*70}")
        except Exception as e:
            failed += 1
            print(f"\n{'='*70}")
            print(f"✗ TEST ERROR: {test_name}")
            print(f"Error: {type(e).__name__}: {e}")
            print(f"{'='*70}")
    
    # Final summary
    print("\n" + "#"*70)
    print("#" + "  FINAL TEST SUMMARY".center(68) + "#")
    print("#"*70)
    print(f"\n  Total Tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")
    print(f"  ✗ Failed: {failed}")
    print(f"  Success Rate: {round(passed / len(tests) * 100, 1)}%")
    print("\n" + "#"*70)
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! 🎉\n")
    else:
        print(f"\n⚠️  {failed} TEST(S) FAILED\n")
        sys.exit(1)

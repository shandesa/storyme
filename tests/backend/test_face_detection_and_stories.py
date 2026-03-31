"""Face Detection and Stories API Tests

Tests for:
1. OpenCV Haar Cascade face detection in image_service.py
2. Fallback to center-crop when no face detected
3. GET /api/stories endpoint
4. Story verification endpoint
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from PIL import Image, ImageDraw
import io
import pytest
import numpy as np

from config import (
    API_BASE_URL,
    TEST_OUTPUT_DIR,
    API_TIMEOUT,
)


class TestFaceDetection:
    """Tests for face detection functionality."""

    @staticmethod
    def create_realistic_face_image():
        """Create an image with a more realistic face pattern for Haar Cascade detection."""
        img = Image.new('RGB', (400, 400), color='#E8D4C4')  # Skin-like background
        draw = ImageDraw.Draw(img)
        
        # Face oval (skin tone)
        draw.ellipse([100, 50, 300, 350], fill='#F5DEB3')
        
        # Eyes (dark circles with white)
        # Left eye
        draw.ellipse([140, 140, 190, 180], fill='#FFFFFF')  # White
        draw.ellipse([155, 150, 175, 170], fill='#4A3728')  # Iris
        draw.ellipse([160, 155, 170, 165], fill='#000000')  # Pupil
        
        # Right eye
        draw.ellipse([210, 140, 260, 180], fill='#FFFFFF')  # White
        draw.ellipse([225, 150, 245, 170], fill='#4A3728')  # Iris
        draw.ellipse([230, 155, 240, 165], fill='#000000')  # Pupil
        
        # Eyebrows
        draw.arc([135, 120, 195, 150], 180, 360, fill='#3D2314', width=3)
        draw.arc([205, 120, 265, 150], 180, 360, fill='#3D2314', width=3)
        
        # Nose
        draw.line([(200, 180), (200, 240)], fill='#D4A574', width=2)
        draw.arc([180, 230, 220, 260], 0, 180, fill='#D4A574', width=2)
        
        # Mouth
        draw.arc([160, 270, 240, 320], 0, 180, fill='#CC6666', width=3)
        
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG', quality=95)
        img_bytes.seek(0)
        return img_bytes

    @staticmethod
    def create_no_face_image():
        """Create an image without any face-like features."""
        img = Image.new('RGB', (400, 400), color='#87CEEB')  # Sky blue
        draw = ImageDraw.Draw(img)
        
        # Draw some random shapes (no face)
        draw.rectangle([50, 50, 150, 150], fill='#228B22')  # Green square
        draw.ellipse([200, 200, 350, 350], fill='#FFD700')  # Yellow circle
        draw.polygon([(200, 50), (250, 150), (150, 150)], fill='#FF6347')  # Red triangle
        
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        return img_bytes

    def test_pdf_generation_with_face_image(self):
        """
        Test PDF generation with an image containing face-like features.
        
        The Haar Cascade should attempt face detection.
        Even if it falls back to center-crop, PDF should be generated.
        """
        print("\n" + "="*70)
        print("TEST: PDF Generation with Face-like Image")
        print("="*70)
        
        test_image = self.create_realistic_face_image()
        files = {'image': ('face.jpg', test_image, 'image/jpeg')}
        data = {'name': 'FaceTest'}
        
        response = requests.post(
            f"{API_BASE_URL}/generate",
            files=files,
            data=data,
            timeout=API_TIMEOUT
        )
        
        print(f"Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type')}")
        print(f"Content-Length: {len(response.content)} bytes")
        
        assert response.status_code == 200, "PDF generation should succeed"
        assert response.headers.get('content-type') == 'application/pdf'
        assert len(response.content) > 50000, "PDF should have substantial content"
        
        # Save for manual inspection
        pdf_path = TEST_OUTPUT_DIR / "face_detection_test.pdf"
        pdf_path.write_bytes(response.content)
        print(f"✓ PDF saved to: {pdf_path}")
        print("✓ Face detection test PASSED")

    def test_pdf_generation_with_no_face_image(self):
        """
        Test PDF generation with an image without face features.
        
        Should fall back to center-crop and still generate valid PDF.
        """
        print("\n" + "="*70)
        print("TEST: PDF Generation with No-Face Image (Fallback)")
        print("="*70)
        
        test_image = self.create_no_face_image()
        files = {'image': ('noface.jpg', test_image, 'image/jpeg')}
        data = {'name': 'NoFaceTest'}
        
        response = requests.post(
            f"{API_BASE_URL}/generate",
            files=files,
            data=data,
            timeout=API_TIMEOUT
        )
        
        print(f"Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type')}")
        print(f"Content-Length: {len(response.content)} bytes")
        
        assert response.status_code == 200, "PDF generation should succeed with fallback"
        assert response.headers.get('content-type') == 'application/pdf'
        
        # Save for manual inspection
        pdf_path = TEST_OUTPUT_DIR / "no_face_fallback_test.pdf"
        pdf_path.write_bytes(response.content)
        print(f"✓ PDF saved to: {pdf_path}")
        print("✓ Center-crop fallback test PASSED")


class TestStoriesAPI:
    """Tests for the /api/stories endpoint."""

    def test_list_stories(self):
        """
        Test GET /api/stories returns available stories.
        """
        print("\n" + "="*70)
        print("TEST: GET /api/stories - List Stories")
        print("="*70)
        
        response = requests.get(f"{API_BASE_URL}/stories", timeout=API_TIMEOUT)
        
        print(f"Status: {response.status_code}")
        
        assert response.status_code == 200, "Stories endpoint should return 200"
        
        stories = response.json()
        print(f"Stories count: {len(stories)}")
        
        assert isinstance(stories, list), "Response should be a list"
        assert len(stories) >= 1, "Should have at least one story"
        
        # Validate story structure
        story = stories[0]
        required_fields = ['story_id', 'title', 'age_group', 'description', 'page_count']
        for field in required_fields:
            assert field in story, f"Story should have '{field}' field"
            print(f"  ✓ {field}: {story[field]}")
        
        # Validate forest_of_smiles story
        assert story['story_id'] == 'forest_of_smiles'
        assert story['page_count'] == 10
        
        print("✓ Stories list test PASSED")

    def test_get_story_by_index(self):
        """
        Test GET /api/stories/{index} returns story by index.
        """
        print("\n" + "="*70)
        print("TEST: GET /api/stories/0 - Get Story by Index")
        print("="*70)
        
        response = requests.get(f"{API_BASE_URL}/stories/0", timeout=API_TIMEOUT)
        
        print(f"Status: {response.status_code}")
        
        assert response.status_code == 200, "Should return story at index 0"
        
        story = response.json()
        print(f"Story ID: {story['story_id']}")
        print(f"Title: {story['title']}")
        print(f"Page Count: {story['page_count']}")
        
        assert story['story_id'] == 'forest_of_smiles'
        print("✓ Get story by index test PASSED")

    def test_get_story_invalid_index(self):
        """
        Test GET /api/stories/{index} with invalid index returns 404.
        """
        print("\n" + "="*70)
        print("TEST: GET /api/stories/999 - Invalid Index")
        print("="*70)
        
        response = requests.get(f"{API_BASE_URL}/stories/999", timeout=API_TIMEOUT)
        
        print(f"Status: {response.status_code}")
        
        assert response.status_code == 404, "Should return 404 for invalid index"
        print("✓ Invalid index test PASSED")

    def test_verify_story_templates(self):
        """
        Test GET /api/stories/verify/{story_id} verifies templates exist.
        """
        print("\n" + "="*70)
        print("TEST: GET /api/stories/verify/forest_of_smiles")
        print("="*70)
        
        response = requests.get(
            f"{API_BASE_URL}/stories/verify/forest_of_smiles",
            timeout=API_TIMEOUT
        )
        
        print(f"Status: {response.status_code}")
        
        assert response.status_code == 200, "Should verify story templates"
        
        result = response.json()
        print(f"Story ID: {result['story_id']}")
        print(f"Total Pages: {result['total_pages']}")
        print(f"Verified: {result['verified']}")
        print(f"Missing: {result['missing']}")
        
        assert result['verified'] == result['total_pages'], "All templates should exist"
        assert len(result['missing']) == 0, "No templates should be missing"
        
        print("✓ Template verification test PASSED")


if __name__ == "__main__":
    print("\n" + "#"*70)
    print("#" + " FACE DETECTION & STORIES API TESTS ".center(68) + "#")
    print("#"*70)
    
    # Run face detection tests
    face_tester = TestFaceDetection()
    face_tester.test_pdf_generation_with_face_image()
    face_tester.test_pdf_generation_with_no_face_image()
    
    # Run stories API tests
    stories_tester = TestStoriesAPI()
    stories_tester.test_list_stories()
    stories_tester.test_get_story_by_index()
    stories_tester.test_get_story_invalid_index()
    stories_tester.test_verify_story_templates()
    
    print("\n" + "#"*70)
    print("#" + " ALL TESTS PASSED ".center(68) + "#")
    print("#"*70)

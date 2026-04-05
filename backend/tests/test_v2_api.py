"""
V2 API Tests for StoryMe App
Tests the new V2 generation workflow:
- GET /api/v2/stories - list available stories
- POST /api/v2/generate/preview - upload face, generate page 1 preview
- POST /api/v2/generate/proceed/{session_id} - start full generation
- GET /api/v2/generate/status/{session_id} - poll progress
- GET /api/v2/generate/download/{session_id} - download PDF
"""

import pytest
import requests
import os
import time
from pathlib import Path

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
API_V2 = f"{BASE_URL}/api/v2"
TEST_PHOTO_PATH = "/tmp/user_test_photo.jpg"


class TestStoriesEndpoint:
    """Test GET /api/v2/stories endpoint"""
    
    def test_list_stories_returns_200(self):
        """Stories endpoint should return 200"""
        response = requests.get(f"{API_V2}/stories")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ GET /api/v2/stories returns 200")
    
    def test_list_stories_returns_stories_array(self):
        """Stories endpoint should return stories array"""
        response = requests.get(f"{API_V2}/stories")
        data = response.json()
        assert "stories" in data, "Response should contain 'stories' key"
        assert isinstance(data["stories"], list), "Stories should be a list"
        print(f"✓ Stories endpoint returns {len(data['stories'])} stories")
    
    def test_forest_of_smiles_story_exists(self):
        """Forest of Smiles story should be available"""
        response = requests.get(f"{API_V2}/stories")
        data = response.json()
        story_ids = [s["story_id"] for s in data["stories"]]
        assert "forest_of_smiles" in story_ids, "forest_of_smiles story should exist"
        
        # Verify story structure
        forest_story = next(s for s in data["stories"] if s["story_id"] == "forest_of_smiles")
        assert "title" in forest_story, "Story should have title"
        assert "total_pages" in forest_story, "Story should have total_pages"
        assert forest_story["total_pages"] == 16, f"Expected 16 pages, got {forest_story['total_pages']}"
        print(f"✓ Forest of Smiles story found with {forest_story['total_pages']} pages")


class TestPreviewEndpoint:
    """Test POST /api/v2/generate/preview endpoint"""
    
    def test_preview_missing_name_returns_422(self):
        """Preview without name should return 422"""
        with open(TEST_PHOTO_PATH, "rb") as f:
            response = requests.post(
                f"{API_V2}/generate/preview",
                files={"image": ("test.jpg", f, "image/jpeg")},
                data={"story_id": "forest_of_smiles"}
            )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print("✓ Preview without name returns 422")
    
    def test_preview_missing_image_returns_422(self):
        """Preview without image should return 422"""
        response = requests.post(
            f"{API_V2}/generate/preview",
            data={"name": "TestChild", "story_id": "forest_of_smiles"}
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print("✓ Preview without image returns 422")
    
    def test_preview_empty_name_returns_400(self):
        """Preview with empty name should return 400"""
        with open(TEST_PHOTO_PATH, "rb") as f:
            response = requests.post(
                f"{API_V2}/generate/preview",
                files={"image": ("test.jpg", f, "image/jpeg")},
                data={"name": "   ", "story_id": "forest_of_smiles"}
            )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("✓ Preview with empty name returns 400")
    
    def test_preview_invalid_file_type_returns_400(self):
        """Preview with invalid file type should return 400"""
        response = requests.post(
            f"{API_V2}/generate/preview",
            files={"image": ("test.txt", b"not an image", "text/plain")},
            data={"name": "TestChild", "story_id": "forest_of_smiles"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("✓ Preview with invalid file type returns 400")
    
    def test_preview_success_returns_session_and_image(self):
        """Preview with valid inputs should return session_id and preview_image"""
        with open(TEST_PHOTO_PATH, "rb") as f:
            start_time = time.time()
            response = requests.post(
                f"{API_V2}/generate/preview",
                files={"image": ("test.jpg", f, "image/jpeg")},
                data={"name": "TestChild", "story_id": "forest_of_smiles"},
                timeout=120
            )
            elapsed = time.time() - start_time
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "session_id" in data, "Response should contain session_id"
        assert "preview_image" in data, "Response should contain preview_image"
        assert data["preview_image"].startswith("data:image/png;base64,"), "Preview should be base64 PNG"
        
        # Verify caching - should be fast since images are cached
        print(f"✓ Preview generated in {elapsed:.2f}s with session_id: {data['session_id']}")
        
        # Store session_id for subsequent tests
        return data["session_id"]


class TestFullGenerationWorkflow:
    """Test the complete generation workflow: preview -> proceed -> status -> download"""
    
    @pytest.fixture(scope="class")
    def session_data(self):
        """Create a preview session for testing"""
        with open(TEST_PHOTO_PATH, "rb") as f:
            response = requests.post(
                f"{API_V2}/generate/preview",
                files={"image": ("test.jpg", f, "image/jpeg")},
                data={"name": "TEST_WorkflowChild", "story_id": "forest_of_smiles"},
                timeout=120
            )
        
        assert response.status_code == 200, f"Preview failed: {response.text}"
        return response.json()
    
    def test_status_after_preview(self, session_data):
        """Status should show preview_ready after preview generation"""
        session_id = session_data["session_id"]
        response = requests.get(f"{API_V2}/generate/status/{session_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["status"] == "preview_ready", f"Expected preview_ready, got {data['status']}"
        assert data["progress"] == 1, f"Expected progress 1, got {data['progress']}"
        assert data["total_pages"] == 16, f"Expected 16 pages, got {data['total_pages']}"
        print(f"✓ Status after preview: {data['status']}, progress: {data['progress']}/{data['total_pages']}")
    
    def test_proceed_starts_generation(self, session_data):
        """Proceed should start background generation"""
        session_id = session_data["session_id"]
        response = requests.post(f"{API_V2}/generate/proceed/{session_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["status"] == "generating", f"Expected generating, got {data['status']}"
        print(f"✓ Proceed started generation for session: {session_id}")
    
    def test_status_shows_progress(self, session_data):
        """Status should show progress during generation"""
        session_id = session_data["session_id"]
        
        # Wait a bit for generation to start
        time.sleep(5)
        
        response = requests.get(f"{API_V2}/generate/status/{session_id}")
        assert response.status_code == 200
        data = response.json()
        
        # Status should be generating or complete
        assert data["status"] in ["generating", "complete"], f"Unexpected status: {data['status']}"
        print(f"✓ Status during generation: {data['status']}, progress: {data['progress']}/{data['total_pages']}")
    
    def test_wait_for_completion(self, session_data):
        """Wait for generation to complete (max 60 seconds)"""
        session_id = session_data["session_id"]
        
        max_wait = 60
        poll_interval = 4
        elapsed = 0
        
        while elapsed < max_wait:
            response = requests.get(f"{API_V2}/generate/status/{session_id}")
            assert response.status_code == 200
            data = response.json()
            
            if data["status"] == "complete" and data.get("pdf_ready"):
                print(f"✓ Generation completed in {elapsed}s, progress: {data['progress']}/{data['total_pages']}")
                return data
            
            if data["status"] == "failed":
                pytest.fail(f"Generation failed: {data.get('error')}")
            
            print(f"  Progress: {data['progress']}/{data['total_pages']} ({data['status']})")
            time.sleep(poll_interval)
            elapsed += poll_interval
        
        pytest.fail(f"Generation did not complete within {max_wait}s")
    
    def test_download_pdf(self, session_data):
        """Download should return valid PDF file"""
        session_id = session_data["session_id"]
        
        # First ensure generation is complete
        max_wait = 60
        poll_interval = 4
        elapsed = 0
        
        while elapsed < max_wait:
            status_response = requests.get(f"{API_V2}/generate/status/{session_id}")
            status_data = status_response.json()
            if status_data["status"] == "complete" and status_data.get("pdf_ready"):
                break
            time.sleep(poll_interval)
            elapsed += poll_interval
        
        # Now download
        response = requests.get(f"{API_V2}/generate/download/{session_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert response.headers.get("content-type") == "application/pdf", "Should return PDF"
        
        # Verify PDF content
        content = response.content
        assert len(content) > 100000, f"PDF too small: {len(content)} bytes"
        assert content[:4] == b"%PDF", "Content should start with PDF header"
        
        print(f"✓ Downloaded PDF: {len(content) / 1024 / 1024:.2f} MB")


class TestStatusEndpoint:
    """Test GET /api/v2/generate/status/{session_id} endpoint"""
    
    def test_status_invalid_session_returns_404(self):
        """Status with invalid session should return 404"""
        response = requests.get(f"{API_V2}/generate/status/invalid_session_id")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Status with invalid session returns 404")


class TestDownloadEndpoint:
    """Test GET /api/v2/generate/download/{session_id} endpoint"""
    
    def test_download_invalid_session_returns_404(self):
        """Download with invalid session should return 404"""
        response = requests.get(f"{API_V2}/generate/download/invalid_session_id")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Download with invalid session returns 404")


class TestProceedEndpoint:
    """Test POST /api/v2/generate/proceed/{session_id} endpoint"""
    
    def test_proceed_invalid_session_returns_404(self):
        """Proceed with invalid session should return 404"""
        response = requests.post(f"{API_V2}/generate/proceed/invalid_session_id")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Proceed with invalid session returns 404")


class TestImageCaching:
    """Test that DALL-E image caching works (second preview should be fast)"""
    
    def test_second_preview_is_fast(self):
        """Second preview request should be instant due to caching"""
        # First request
        with open(TEST_PHOTO_PATH, "rb") as f:
            start1 = time.time()
            response1 = requests.post(
                f"{API_V2}/generate/preview",
                files={"image": ("test.jpg", f, "image/jpeg")},
                data={"name": "TEST_CacheTest1", "story_id": "forest_of_smiles"},
                timeout=120
            )
            elapsed1 = time.time() - start1
        
        assert response1.status_code == 200, f"First preview failed: {response1.text}"
        
        # Second request (should use cached DALL-E image)
        with open(TEST_PHOTO_PATH, "rb") as f:
            start2 = time.time()
            response2 = requests.post(
                f"{API_V2}/generate/preview",
                files={"image": ("test.jpg", f, "image/jpeg")},
                data={"name": "TEST_CacheTest2", "story_id": "forest_of_smiles"},
                timeout=120
            )
            elapsed2 = time.time() - start2
        
        assert response2.status_code == 200, f"Second preview failed: {response2.text}"
        
        print(f"✓ First preview: {elapsed1:.2f}s, Second preview: {elapsed2:.2f}s")
        
        # Both should be fast since DALL-E images are pre-cached
        # The main work is face blending which should be < 5s
        assert elapsed2 < 10, f"Second preview too slow: {elapsed2:.2f}s (expected < 10s)"


class TestPDFRedownload:
    """Test that completed session allows re-download without regeneration"""
    
    @pytest.fixture(scope="class")
    def completed_session(self):
        """Create and complete a generation session"""
        # Create preview
        with open(TEST_PHOTO_PATH, "rb") as f:
            preview_response = requests.post(
                f"{API_V2}/generate/preview",
                files={"image": ("test.jpg", f, "image/jpeg")},
                data={"name": "TEST_RedownloadChild", "story_id": "forest_of_smiles"},
                timeout=120
            )
        
        assert preview_response.status_code == 200
        session_id = preview_response.json()["session_id"]
        
        # Start generation
        proceed_response = requests.post(f"{API_V2}/generate/proceed/{session_id}")
        assert proceed_response.status_code == 200
        
        # Wait for completion
        max_wait = 90
        poll_interval = 4
        elapsed = 0
        
        while elapsed < max_wait:
            status_response = requests.get(f"{API_V2}/generate/status/{session_id}")
            status_data = status_response.json()
            if status_data["status"] == "complete" and status_data.get("pdf_ready"):
                return session_id
            if status_data["status"] == "failed":
                pytest.fail(f"Generation failed: {status_data.get('error')}")
            time.sleep(poll_interval)
            elapsed += poll_interval
        
        pytest.fail(f"Generation did not complete within {max_wait}s")
    
    def test_redownload_without_regeneration(self, completed_session):
        """Re-download should be instant without regeneration"""
        session_id = completed_session
        
        # First download
        start1 = time.time()
        response1 = requests.get(f"{API_V2}/generate/download/{session_id}")
        elapsed1 = time.time() - start1
        
        assert response1.status_code == 200
        size1 = len(response1.content)
        
        # Second download (should be instant)
        start2 = time.time()
        response2 = requests.get(f"{API_V2}/generate/download/{session_id}")
        elapsed2 = time.time() - start2
        
        assert response2.status_code == 200
        size2 = len(response2.content)
        
        # Verify same PDF
        assert size1 == size2, f"PDF sizes differ: {size1} vs {size2}"
        
        # Re-download should be fast (just file serving)
        assert elapsed2 < 5, f"Re-download too slow: {elapsed2:.2f}s"
        
        print(f"✓ First download: {elapsed1:.2f}s ({size1/1024/1024:.2f}MB), Re-download: {elapsed2:.2f}s")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

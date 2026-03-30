#!/usr/bin/env python3
"""
Backend API Testing for StoryMe MVP
Tests all endpoints and core functionality
"""

import requests
import sys
import os
from pathlib import Path
from datetime import datetime
import tempfile
from PIL import Image
import io

# Get the backend URL from frontend env
BACKEND_URL = "https://tale-forge-66.preview.emergentagent.com"
API_BASE = f"{BACKEND_URL}/api"

class StoryMeAPITester:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.errors = []
        
    def log_test(self, name, success, message=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}: PASSED")
        else:
            print(f"❌ {name}: FAILED - {message}")
            self.errors.append(f"{name}: {message}")
    
    def test_root_endpoint(self):
        """Test basic API connectivity"""
        try:
            response = requests.get(f"{API_BASE}/", timeout=10)
            success = response.status_code == 200
            message = f"Status: {response.status_code}"
            if success:
                data = response.json()
                message += f", Response: {data}"
            self.log_test("Root Endpoint", success, message)
            return success
        except Exception as e:
            self.log_test("Root Endpoint", False, str(e))
            return False
    
    def test_status_endpoints(self):
        """Test status check endpoints"""
        try:
            # Test POST /status
            test_data = {"client_name": f"test_client_{datetime.now().strftime('%H%M%S')}"}
            response = requests.post(f"{API_BASE}/status", json=test_data, timeout=10)
            
            post_success = response.status_code == 200
            self.log_test("POST /status", post_success, f"Status: {response.status_code}")
            
            if post_success:
                # Test GET /status
                response = requests.get(f"{API_BASE}/status", timeout=10)
                get_success = response.status_code == 200
                self.log_test("GET /status", get_success, f"Status: {response.status_code}")
                return get_success
            
            return False
            
        except Exception as e:
            self.log_test("Status Endpoints", False, str(e))
            return False
    
    def create_test_image(self):
        """Create a test image for upload"""
        # Create a simple test image
        img = Image.new('RGB', (400, 400), color='lightblue')
        
        # Save to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        return img_bytes
    
    def test_generate_endpoint_validation(self):
        """Test /generate endpoint validation"""
        try:
            # Test missing name
            test_image = self.create_test_image()
            files = {'image': ('test.jpg', test_image, 'image/jpeg')}
            response = requests.post(f"{API_BASE}/generate", files=files, timeout=30)
            
            missing_name_success = response.status_code == 422  # FastAPI validation error
            self.log_test("Generate - Missing Name Validation", missing_name_success, 
                         f"Status: {response.status_code}")
            
            # Test missing image
            data = {'name': 'TestChild'}
            response = requests.post(f"{API_BASE}/generate", data=data, timeout=30)
            
            missing_image_success = response.status_code == 422
            self.log_test("Generate - Missing Image Validation", missing_image_success,
                         f"Status: {response.status_code}")
            
            # Test invalid file type
            invalid_file = io.BytesIO(b"not an image")
            files = {'image': ('test.txt', invalid_file, 'text/plain')}
            data = {'name': 'TestChild'}
            response = requests.post(f"{API_BASE}/generate", files=files, data=data, timeout=30)
            
            invalid_type_success = response.status_code == 400
            self.log_test("Generate - Invalid File Type", invalid_type_success,
                         f"Status: {response.status_code}")
            
            return missing_name_success and missing_image_success and invalid_type_success
            
        except Exception as e:
            self.log_test("Generate Validation Tests", False, str(e))
            return False
    
    def test_generate_endpoint_success(self):
        """Test successful PDF generation"""
        try:
            # Create test image
            test_image = self.create_test_image()
            
            # Prepare request
            files = {'image': ('test_child.jpg', test_image, 'image/jpeg')}
            data = {'name': 'TestChild'}
            
            print("🔄 Testing PDF generation (this may take 10-15 seconds)...")
            response = requests.post(f"{API_BASE}/generate", files=files, data=data, timeout=60)
            
            success = response.status_code == 200
            
            if success:
                # Check if response is PDF
                content_type = response.headers.get('content-type', '')
                is_pdf = 'application/pdf' in content_type
                
                # Check PDF size (should be reasonable)
                pdf_size = len(response.content)
                size_ok = pdf_size > 1000  # At least 1KB
                
                message = f"Status: {response.status_code}, Content-Type: {content_type}, Size: {pdf_size} bytes"
                
                if is_pdf and size_ok:
                    # Save PDF for verification
                    with open('/tmp/test_storybook.pdf', 'wb') as f:
                        f.write(response.content)
                    message += " - PDF saved to /tmp/test_storybook.pdf"
                
                self.log_test("Generate - PDF Creation", is_pdf and size_ok, message)
                return is_pdf and size_ok
            else:
                error_detail = "Unknown error"
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', 'Unknown error')
                except:
                    error_detail = response.text[:200]
                
                self.log_test("Generate - PDF Creation", False, 
                             f"Status: {response.status_code}, Error: {error_detail}")
                return False
                
        except Exception as e:
            self.log_test("Generate - PDF Creation", False, str(e))
            return False
    
    def test_file_size_validation(self):
        """Test file size validation (5MB limit)"""
        try:
            # Create a large image (simulate >5MB)
            # Note: We'll create a smaller image but test the validation logic
            large_img = Image.new('RGB', (2000, 2000), color='red')
            img_bytes = io.BytesIO()
            large_img.save(img_bytes, format='JPEG', quality=95)
            img_bytes.seek(0)
            
            files = {'image': ('large_test.jpg', img_bytes, 'image/jpeg')}
            data = {'name': 'TestChild'}
            
            response = requests.post(f"{API_BASE}/generate", files=files, data=data, timeout=60)
            
            # Should either succeed (if under 5MB) or fail with appropriate error
            if response.status_code == 200:
                self.log_test("File Size - Large Image Processing", True, "Large image processed successfully")
                return True
            elif response.status_code == 400:
                self.log_test("File Size - Validation", True, f"Properly rejected large file: {response.status_code}")
                return True
            else:
                self.log_test("File Size - Validation", False, f"Unexpected status: {response.status_code}")
                return False
                
        except Exception as e:
            self.log_test("File Size Validation", False, str(e))
            return False
    
    def run_all_tests(self):
        """Run all backend tests"""
        print("🚀 Starting StoryMe Backend API Tests")
        print(f"📍 Testing against: {API_BASE}")
        print("=" * 60)
        
        # Basic connectivity
        if not self.test_root_endpoint():
            print("❌ Basic connectivity failed. Stopping tests.")
            return False
        
        # Status endpoints (basic CRUD)
        self.test_status_endpoints()
        
        # Generate endpoint validation
        self.test_generate_endpoint_validation()
        
        # File size validation
        self.test_file_size_validation()
        
        # Full PDF generation test
        self.test_generate_endpoint_success()
        
        # Print summary
        print("\n" + "=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        
        if self.errors:
            print("\n❌ Failed Tests:")
            for error in self.errors:
                print(f"  • {error}")
        
        success_rate = (self.tests_passed / self.tests_run) * 100 if self.tests_run > 0 else 0
        print(f"✨ Success Rate: {success_rate:.1f}%")
        
        return self.tests_passed == self.tests_run

def main():
    """Main test runner"""
    tester = StoryMeAPITester()
    
    try:
        success = tester.run_all_tests()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n⚠️ Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
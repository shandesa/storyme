#!/usr/bin/env python3
"""Production Architecture Test Script

Tests the new storage abstraction and story selection features.
"""

import sys
import requests
from pathlib import Path

# Configuration
API_BASE_URL = "https://tale-forge-66.preview.emergentagent.com/api"

def test_list_stories():
    """Test GET /api/stories"""
    print("\n" + "="*70)
    print("TEST 1: List All Stories")
    print("="*70)
    
    response = requests.get(f"{API_BASE_URL}/stories")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    stories = response.json()
    print(f"✓ Found {len(stories)} story(ies)")
    
    for story in stories:
        print(f"  - {story['story_id']}: {story['title']}")
        print(f"    Age: {story['age_group']}, Pages: {story['page_count']}")
    
    assert len(stories) > 0, "No stories found"
    print("\n✓ TEST PASSED")
    return stories[0]

def test_get_story_by_index():
    """Test GET /api/stories/{index}"""
    print("\n" + "="*70)
    print("TEST 2: Get Story by Index")
    print("="*70)
    
    response = requests.get(f"{API_BASE_URL}/stories/0")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    story = response.json()
    print(f"✓ Retrieved: {story['story_id']}")
    print(f"  Title: {story['title']}")
    print(f"  Pages: {story['page_count']}")
    
    print("\n✓ TEST PASSED")
    return story

def test_verify_templates(story_id):
    """Test GET /api/stories/verify/{story_id}"""
    print("\n" + "="*70)
    print("TEST 3: Verify Story Templates")
    print("="*70)
    
    response = requests.get(f"{API_BASE_URL}/stories/verify/{story_id}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    result = response.json()
    print(f"✓ Story: {result['story_id']}")
    print(f"  Verified: {result['verified']}/{result['total_pages']}")
    
    if result['missing']:
        print(f"  ⚠ Missing: {len(result['missing'])} template(s)")
        for missing in result['missing']:
            print(f"    - Page {missing['page']}: {missing['path']}")
    else:
        print(f"  ✓ All templates found")
    
    assert result['verified'] == result['total_pages'], "Missing templates"
    print("\n✓ TEST PASSED")

def test_generate_with_story_id(story_id):
    """Test POST /api/generate with story_id"""
    print("\n" + "="*70)
    print("TEST 4: Generate PDF with story_id")
    print("="*70)
    
    # Create test image
    from PIL import Image, ImageDraw
    import io
    import tempfile
    
    img = Image.new('RGB', (400, 400), color='#FFB6C1')
    draw = ImageDraw.Draw(img)
    draw.ellipse([100, 100, 300, 300], fill='#FFF0F5')
    draw.ellipse([150, 150, 200, 200], fill='#000000')
    draw.ellipse([250, 150, 300, 200], fill='#000000')
    
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
        img.save(tmp, 'JPEG')
        tmp_path = tmp.name
    
    print(f"✓ Test image created: {tmp_path}")
    
    # Send request
    with open(tmp_path, 'rb') as f:
        files = {'image': ('test.jpg', f, 'image/jpeg')}
        data = {
            'name': 'ArchitectureTest',
            'story_id': story_id
        }
        
        response = requests.post(f"{API_BASE_URL}/generate", files=files, data=data)
    
    print(f"  Response: {response.status_code}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert response.headers['content-type'] == 'application/pdf'
    
    # Validate PDF
    from pypdf import PdfReader
    pdf = PdfReader(io.BytesIO(response.content))
    
    print(f"✓ PDF generated")
    print(f"  Pages: {len(pdf.pages)}")
    print(f"  Size: {len(response.content) / 1024:.2f} KB")
    
    # Cleanup
    Path(tmp_path).unlink()
    
    print("\n✓ TEST PASSED")

def test_generate_with_story_index():
    """Test POST /api/generate with story_index"""
    print("\n" + "="*70)
    print("TEST 5: Generate PDF with story_index")
    print("="*70)
    
    from PIL import Image, ImageDraw
    import io
    import tempfile
    
    img = Image.new('RGB', (400, 400), color='#FFDAB9')
    draw = ImageDraw.Draw(img)
    draw.ellipse([100, 100, 300, 300], fill='#FFF0F5')
    
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
        img.save(tmp, 'JPEG')
        tmp_path = tmp.name
    
    with open(tmp_path, 'rb') as f:
        files = {'image': ('test.jpg', f, 'image/jpeg')}
        data = {
            'name': 'IndexTest',
            'story_index': '0'  # Pass as string (form data)
        }
        
        response = requests.post(f"{API_BASE_URL}/generate", files=files, data=data)
    
    assert response.status_code == 200
    print(f"✓ PDF generated using story_index=0")
    
    Path(tmp_path).unlink()
    print("\n✓ TEST PASSED")

def test_storage_abstraction():
    """Test storage abstraction (local)"""
    print("\n" + "="*70)
    print("TEST 6: Storage Abstraction")
    print("="*70)
    
    # Import storage
    sys.path.insert(0, '/app/backend')
    from core.storage import storage
    from core.config import config
    
    print(f"✓ Storage Type: {config.STORAGE_TYPE}")
    print(f"  Class: {storage.__class__.__name__}")
    
    # Test file exists
    test_path = "templates/stories/forest_of_smiles/page1.png"
    exists = storage.file_exists(test_path)
    print(f"✓ File exists check: {exists}")
    assert exists, f"Template not found: {test_path}"
    
    # Test get file path
    full_path = storage.get_file_path(test_path)
    print(f"✓ Full path: {full_path}")
    
    print("\n✓ TEST PASSED")

def main():
    """Run all tests"""
    print("\n" + "#"*70)
    print("#" + " "*68 + "#")
    print("#" + "  PRODUCTION ARCHITECTURE TEST SUITE".center(68) + "#")
    print("#" + " "*68 + "#")
    print("#"*70)
    
    try:
        # Test story endpoints
        first_story = test_list_stories()
        story = test_get_story_by_index()
        test_verify_templates(story['story_id'])
        
        # Test PDF generation
        test_generate_with_story_id(story['story_id'])
        test_generate_with_story_index()
        
        # Test storage abstraction
        test_storage_abstraction()
        
        # Summary
        print("\n" + "#"*70)
        print("#" + "  FINAL RESULT: ALL TESTS PASSED ✓".center(68) + "#")
        print("#"*70)
        print("\n🎉 Production architecture working perfectly! 🎉\n")
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())

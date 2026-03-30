"""Frontend Integration Test - PDF Download Verification

This test uses Playwright to simulate actual user interaction with the browser
and verifies that the PDF download actually works.

Test Flow:
1. Open the StoryMe application in browser
2. Fill in child's name
3. Upload a test image
4. Click "Generate Storybook" button
5. Wait for generation to complete
6. Verify PDF file is actually downloaded
7. Validate downloaded PDF (size, page count)

This is the most important test as it validates the entire end-to-end flow
from the user's perspective.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import time
from playwright.async_api import async_playwright, expect
from PIL import Image, ImageDraw
from pypdf import PdfReader

from config import (
    FRONTEND_URL,
    TEST_DATA_DIR,
    TEST_OUTPUT_DIR,
    EXPECTED_TOTAL_PDF_PAGES,
    BROWSER_TIMEOUT,
)


class TestFrontendDownload:
    """Test suite for frontend PDF download functionality."""

    @staticmethod
    def create_test_image(path):
        """
        Create a test image file for upload testing.
        
        Args:
            path: Path where to save the image
        
        Returns:
            Path to created image
        """
        img = Image.new('RGB', (400, 400), color='#FFB6C1')
        draw = ImageDraw.Draw(img)
        
        # Draw a simple smiley face
        draw.ellipse([100, 100, 300, 300], fill='#FFF0F5')  # Face
        draw.ellipse([150, 150, 200, 200], fill='#000000')  # Left eye
        draw.ellipse([250, 150, 300, 200], fill='#000000')  # Right eye
        draw.arc([175, 225, 275, 275], 0, 180, fill='#000000', width=3)  # Smile
        
        img.save(path, 'JPEG')
        return path

    async def test_complete_download_flow(self):
        """
        TEST: Complete End-to-End Download Flow
        
        This is the most comprehensive test that simulates a real user:
        1. Opens the app
        2. Enters child's name
        3. Uploads photo
        4. Generates storybook
        5. Downloads PDF
        6. Validates PDF content
        
        This test MUST pass for the app to be considered functional.
        """
        print("\n" + "="*70)
        print("INTEGRATION TEST: Complete PDF Download Flow")
        print("="*70)
        
        # Prepare test data
        child_name = "IntegrationTest"
        test_image_path = TEST_DATA_DIR / "test_upload.jpg"
        self.create_test_image(test_image_path)
        print(f"✓ Test image created: {test_image_path}")
        
        async with async_playwright() as p:
            # Launch browser with download path
            browser = await p.chromium.launch(headless=True)
            
            # Create context with download directory
            context = await browser.new_context(
                accept_downloads=True,
            )
            
            page = await context.new_page()
            
            try:
                # ============================================================
                # STEP 1: Navigate to Application
                # ============================================================
                print(f"\nStep 1: Loading application at {FRONTEND_URL}")
                await page.goto(FRONTEND_URL, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)
                print("✓ Application loaded successfully")
                
                # ============================================================
                # STEP 2: Verify UI Elements Exist
                # ============================================================
                print("\nStep 2: Verifying UI elements...")
                
                # Check for form card
                await expect(page.locator('[data-testid="story-generation-card"]')).to_be_visible()
                print("✓ Story generation card found")
                
                # Check for name input
                name_input = page.locator('[data-testid="child-name-input"]')
                await expect(name_input).to_be_visible()
                print("✓ Name input field found")
                
                # Check for upload input
                upload_input = page.locator('[data-testid="photo-upload-input"]')
                await expect(upload_input).to_be_attached()
                print("✓ Photo upload input found")
                
                # Check for generate button
                generate_button = page.locator('[data-testid="generate-story-button"]')
                await expect(generate_button).to_be_visible()
                print("✓ Generate button found")
                
                # ============================================================
                # STEP 3: Fill in Child's Name
                # ============================================================
                print(f"\nStep 3: Entering child's name: '{child_name}'")
                await name_input.fill(child_name)
                await page.wait_for_timeout(500)
                
                # Verify name was entered
                input_value = await name_input.input_value()
                assert input_value == child_name, f"Name not entered correctly: {input_value}"
                print(f"✓ Name entered successfully: {input_value}")
                
                # ============================================================
                # STEP 4: Upload Test Image
                # ============================================================
                print(f"\nStep 4: Uploading test image...")
                await upload_input.set_input_files(str(test_image_path))
                await page.wait_for_timeout(1000)
                
                # Wait for preview to appear
                try:
                    await expect(page.locator('[data-testid="image-preview"]')).to_be_visible(timeout=5000)
                    print("✓ Image uploaded and preview displayed")
                except:
                    print("⚠ Image preview not found (may still work)")
                
                # ============================================================
                # STEP 5: Click Generate Button and Monitor Download
                # ============================================================
                print("\nStep 5: Clicking 'Generate Storybook' button...")
                
                # Set up download promise BEFORE clicking
                async with page.expect_download(timeout=60000) as download_info:
                    await generate_button.click()
                    print("✓ Generate button clicked")
                    
                    # Wait for loading state
                    await page.wait_for_timeout(2000)
                    
                    # Check for loading state
                    button_text = await generate_button.inner_text()
                    print(f"  Button text: {button_text}")
                    
                    # Wait for download to start
                    print("  Waiting for PDF download to start...")
                
                download = await download_info.value
                print("✓ Download started!")
                
                # ============================================================
                # STEP 6: Save and Validate Downloaded PDF
                # ============================================================
                print("\nStep 6: Saving and validating downloaded PDF...")
                
                # Get download details
                download_path = TEST_OUTPUT_DIR / f"{child_name}_integration_test.pdf"
                await download.save_as(download_path)
                print(f"✓ PDF saved to: {download_path}")
                
                # Validate file exists
                assert download_path.exists(), "Downloaded file doesn't exist"
                file_size_kb = download_path.stat().st_size / 1024
                print(f"✓ File size: {file_size_kb:.2f} KB")
                
                # ============================================================
                # STEP 7: Validate PDF Structure
                # ============================================================
                print("\nStep 7: Validating PDF structure...")
                
                # Read and validate PDF
                with open(download_path, 'rb') as f:
                    reader = PdfReader(f)
                    num_pages = len(reader.pages)
                    
                    print(f"✓ PDF is valid and readable")
                    print(f"✓ Number of pages: {num_pages}")
                    
                    # CRITICAL: Validate page count
                    assert num_pages == EXPECTED_TOTAL_PDF_PAGES, \
                        f"Expected {EXPECTED_TOTAL_PDF_PAGES} pages, got {num_pages}"
                    print(f"✓ Page count correct: {EXPECTED_TOTAL_PDF_PAGES} pages")
                    
                    # Extract and validate title
                    title_text = reader.pages[0].extract_text()
                    assert child_name in title_text, \
                        f"Child's name '{child_name}' not found in PDF title"
                    print(f"✓ Child's name '{child_name}' found in PDF title")
                    
                    # Check story pages
                    story_text = reader.pages[1].extract_text()
                    assert child_name in story_text, \
                        f"Child's name '{child_name}' not found in story"
                    print(f"✓ Child's name '{child_name}' found in story text")
                
                # ============================================================
                # SUCCESS!
                # ============================================================
                print("\n" + "="*70)
                print("✓ ✓ ✓  ALL INTEGRATION TESTS PASSED!  ✓ ✓ ✓")
                print("="*70)
                print("\nDownload Flow Summary:")
                print(f"  • Application loaded: ✓")
                print(f"  • Form filled: ✓")
                print(f"  • Image uploaded: ✓")
                print(f"  • PDF generated: ✓")
                print(f"  • PDF downloaded: ✓")
                print(f"  • PDF validated: ✓")
                print(f"  • Page count ({EXPECTED_TOTAL_PDF_PAGES}): ✓")
                print(f"  • Personalization: ✓")
                print("\n🎉 End-to-end download working perfectly! 🎉\n")
                
                return True
                
            except Exception as e:
                print("\n" + "="*70)
                print("✗ INTEGRATION TEST FAILED")
                print("="*70)
                print(f"Error: {type(e).__name__}: {e}")
                
                # Take screenshot for debugging
                screenshot_path = TEST_OUTPUT_DIR / "error_screenshot.png"
                await page.screenshot(path=str(screenshot_path))
                print(f"\nScreenshot saved to: {screenshot_path}")
                
                raise
                
            finally:
                await browser.close()


async def run_tests():
    """Run all integration tests."""
    print("\n" + "#"*70)
    print("#" + " "*68 + "#")
    print("#" + "  STORYME - FRONTEND INTEGRATION TEST SUITE".center(68) + "#")
    print("#" + " "*68 + "#")
    print("#"*70)
    print()
    print(f"Frontend URL: {FRONTEND_URL}")
    print(f"Expected Total PDF Pages: {EXPECTED_TOTAL_PDF_PAGES}")
    print()
    
    tester = TestFrontendDownload()
    
    try:
        await tester.test_complete_download_flow()
        print("\n" + "#"*70)
        print("#" + "  FINAL RESULT: ALL TESTS PASSED ✓".center(68) + "#")
        print("#"*70 + "\n")
        return 0
    except Exception as e:
        print("\n" + "#"*70)
        print("#" + "  FINAL RESULT: TESTS FAILED ✗".center(68) + "#")
        print("#"*70)
        print(f"\nError Details: {e}\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_tests())
    sys.exit(exit_code)

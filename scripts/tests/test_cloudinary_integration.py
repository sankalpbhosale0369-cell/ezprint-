"""
Cloudinary Integration Verification Script

This script verifies that the Cloudinary integration is working correctly
by testing both backend upload and desktop download functionality.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def test_cloudinary_upload():
    """Test Cloudinary upload functionality"""
    print("\n" + "="*60)
    print("TEST 1: Cloudinary Upload")
    print("="*60)
    
    try:
        from shared.cloudinary_helper import upload_file_to_cloudinary
        
        # Create a test file
        test_content = b"This is a test file for Cloudinary upload verification."
        test_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False)
        test_file.write(test_content)
        test_file.close()
        
        print(f"Created test file: {test_file.name}")
        
        # Upload to Cloudinary
        shop_id = "test_shop"
        filename = "test_upload.txt"
        
        print(f"  Uploading to Cloudinary...")
        cloudinary_url = upload_file_to_cloudinary(test_file.name, shop_id, filename)
        
        print(f"Upload successful!")
        print(f"  Cloudinary URL: {cloudinary_url}")
        
        # Verify URL format
        if cloudinary_url.startswith('https://res.cloudinary.com/'):
            print(f"URL format is correct")
        else:
            print(f"URL format is incorrect")
            return False
        
        # Clean up
        os.remove(test_file.name)
        print(f"Test file cleaned up")
        
        return True, cloudinary_url
        
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False, None

def test_desktop_download(cloudinary_url):
    """Test desktop download functionality"""
    print("\n" + "="*60)
    print("TEST 2: Desktop Download")
    print("="*60)
    
    try:
        from shopkeeper_app.printer_manager import PrinterManager
        
        # Create printer manager instance
        print("  Creating PrinterManager instance...")
        pm = PrinterManager()
        
        print(f"PrinterManager created")
        
        # Test _ensure_local_file with Cloudinary URL
        print(f"  Testing download from: {cloudinary_url}")
        local_path = pm._ensure_local_file(cloudinary_url)
        
        print(f"Download successful!")
        print(f"  Local path: {local_path}")
        
        # Verify file exists
        if os.path.exists(local_path):
            print(f"File exists at local path")
            file_size = os.path.getsize(local_path)
            print(f"  File size: {file_size} bytes")
        else:
            print(f"File does not exist at local path")
            return False
        
        # Test with local file path (backward compatibility)
        print("\n  Testing backward compatibility with local path...")
        local_test_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False)
        local_test_file.write(b"Local file test")
        local_test_file.close()
        
        result_path = pm._ensure_local_file(local_test_file.name)
        
        if result_path == local_test_file.name:
            print(f"Local file path returned unchanged (backward compatible)")
        else:
            print(f"Local file path was modified")
            return False
        
        # Clean up
        os.remove(local_test_file.name)
        print(f"Test files cleaned up")
        
        return True
        
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_url_detection():
    """Test URL detection logic"""
    print("\n" + "="*60)
    print("TEST 3: URL Detection")
    print("="*60)
    
    try:
        from urllib.parse import urlparse
        
        test_cases = [
            ("https://res.cloudinary.com/test/file.pdf", True, "HTTPS URL"),
            ("http://example.com/file.pdf", True, "HTTP URL"),
            ("C:\\Users\\test\\file.pdf", False, "Windows local path"),
            ("/home/user/file.pdf", False, "Unix local path"),
            ("file.pdf", False, "Relative path"),
        ]
        
        all_passed = True
        for test_path, expected_is_url, description in test_cases:
            parsed = urlparse(test_path)
            is_url = parsed.scheme in ['http', 'https']
            
            if is_url == expected_is_url:
                print(f"SUCCESS {description}: {test_path}")
                print(f"  Detected as: {'URL' if is_url else 'Local path'}")
            else:
                print(f"FAILURE {description}: {test_path}")
                print(f"  Expected: {'URL' if expected_is_url else 'Local path'}")
                print(f"  Got: {'URL' if is_url else 'Local path'}")
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all verification tests"""
    print("\n" + "="*60)
    print("CLOUDINARY INTEGRATION VERIFICATION")
    print("="*60)
    
    results = []
    
    # Test 1: Cloudinary Upload
    upload_result, cloudinary_url = test_cloudinary_upload()
    results.append(("Cloudinary Upload", upload_result))
    
    # Test 2: Desktop Download (only if upload succeeded)
    if upload_result and cloudinary_url:
        download_result = test_desktop_download(cloudinary_url)
        results.append(("Desktop Download", download_result))
    else:
        print("\n⚠ Skipping desktop download test (upload failed)")
        results.append(("Desktop Download", False))
    
    # Test 3: URL Detection
    detection_result = test_url_detection()
    results.append(("URL Detection", detection_result))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for test_name, passed in results:
        status = "PASSED" if passed else "FAILED"
        print(f"{test_name}: {status}")
    
    all_passed = all(result[1] for result in results)
    
    print("\n" + "="*60)
    if all_passed:
        print("ALL TESTS PASSED - Integration is working correctly!")
    else:
        print("SOME TESTS FAILED - Please review the errors above")
    print("="*60 + "\n")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

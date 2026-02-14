
import os
import sys
from shared.file_processor import get_page_count, classify_color_pages, normalize_document_for_preview, create_preview_image
from shared.cloudinary_helper import upload_file_to_cloudinary
import tempfile
import pathlib

def test_file_processor_with_url():
    print("--- Testing File Processor with Cloudinary URL ---")
    
    # 1. Create a dummy PDF
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False) as f:
        # Simple PDF content is hard to craft manually, but we can just use a small valid-ish PDF header 
        # Or better, just use an existing small file if available or create a text file and normalize it.
        # Let's create a text file as it's easier to verify normalization too.
        pass
    
    temp_txt = tempfile.mktemp(suffix='.txt')
    with open(temp_txt, 'w') as f:
        f.write("This is a test document for Cloudinary URL processing.")
    
    try:
        # 2. Upload to Cloudinary to get a URL
        print(f"Uploading {temp_txt} to Cloudinary...")
        url = upload_file_to_cloudinary(temp_txt, "test_shop", "test_file.txt")
        print(f"Cloudinary URL: {url}")
        
        # 3. Test get_page_count with URL
        print("\nTesting get_page_count(url, 'txt')...")
        count = get_page_count(url, 'txt')
        print(f"Page Count Result: {count}")
        
        # 4. Test normalize_document_for_preview with URL
        print("\nTesting normalize_document_for_preview(url, 'txt')...")
        norm_path = normalize_document_for_preview(url, 'txt')
        print(f"Normalized Path: {norm_path}")
        if os.path.exists(norm_path) and norm_path.endswith('.pdf'):
            print("SUCCESS: Normalized to PDF locally from URL")
        else:
            print("FAILURE: Normalization failed or path invalid")

        # 5. Test create_preview_image with URL
        print("\nTesting create_preview_image(url, 'txt')...")
        preview_path = create_preview_image(url, 'txt')
        print(f"Preview Path: {preview_path}")
        if preview_path and os.path.exists(preview_path):
            print("SUCCESS: Preview image created from URL")
        else:
            print("FAILURE: Preview creation failed")

    except Exception as e:
        print(f"ERROR during testing: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(temp_txt):
            os.remove(temp_txt)

if __name__ == "__main__":
    test_file_processor_with_url()

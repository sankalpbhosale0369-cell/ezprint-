"""
Upload Release to Distribution Server
Template for uploading built releases to your SaaS platform

Configure this script with your distribution server details
"""

import os
import requests
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Configuration (use environment variables in production)
UPLOAD_URL = os.environ.get('RELEASE_UPLOAD_URL', 'https://api.ezprint.com/releases/upload')
API_KEY = os.environ.get('RELEASE_API_KEY', '')

def upload_release(version, file_path, channel='stable'):
    """
    Upload release to distribution server

    Args:
        version (str): Version number (e.g., "1.0.0")
        file_path (Path): Path to release file
        channel (str): Release channel (stable, beta, dev)
    """
    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}")
        return False

    if not API_KEY:
        print("ERROR: RELEASE_API_KEY not set")
        print("Set environment variable: RELEASE_API_KEY=your_api_key")
        return False

    print("="*60)
    print(f"  Uploading Release v{version}")
    print("="*60)
    print()
    print(f"File: {file_path.name}")
    print(f"Size: {file_path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"Channel: {channel}")
    print(f"Server: {UPLOAD_URL}")
    print()

    try:
        with open(file_path, 'rb') as f:
            files = {'file': (file_path.name, f, 'application/octet-stream')}
            data = {
                'version': version,
                'channel': channel,
                'platform': 'windows'
            }
            headers = {
                'Authorization': f'Bearer {API_KEY}'
            }

            print("Uploading...")
            response = requests.post(
                UPLOAD_URL,
                files=files,
                data=data,
                headers=headers,
                timeout=300  # 5 minutes
            )

            if response.status_code == 200:
                result = response.json()
                print("✓ Upload successful!")
                print(f"  Download URL: {result.get('download_url', 'N/A')}")
                print(f"  Release ID: {result.get('release_id', 'N/A')}")
                return True
            else:
                print(f"✗ Upload failed: HTTP {response.status_code}")
                print(response.text)
                return False

    except Exception as e:
        print(f"✗ Upload error: {e}")
        return False


def main():
    """Main upload process"""
    from shared import version

    # Release file
    release_zip = PROJECT_ROOT / 'build' / 'output' / f'EzPrintAgent_v{version.VERSION}_Windows.zip'

    if not release_zip.exists():
        print("ERROR: Release package not found!")
        print("Build the release first: python build/scripts/build_windows.py")
        return

    # Upload
    success = upload_release(
        version=version.VERSION,
        file_path=release_zip,
        channel=version.CHANNEL
    )

    if success:
        print()
        print("="*60)
        print("  Upload Complete!")
        print("="*60)
        print()
        print("Next steps:")
        print("1. Update version API endpoint with new release metadata")
        print("2. Test auto-update on a client")
        print("3. Announce release to users")
    else:
        print()
        print("="*60)
        print("  Upload Failed")
        print("="*60)


if __name__ == "__main__":
    main()

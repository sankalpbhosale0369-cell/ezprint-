"""
Code Signing Template for EzPrint Agent
Signs the executable with a digital certificate to avoid antivirus false positives

PREREQUISITES:
1. Obtain a code signing certificate from:
   - DigiCert: https://www.digicert.com/signing/code-signing-certificates
   - Sectigo: https://sectigo.com/ssl-certificates-tls/code-signing
   - SSL.com: https://www.ssl.com/certificates/code-signing/
   Cost: $200-400/year

2. Install Windows SDK for signtool.exe:
   - Download: https://developer.microsoft.com/en-us/windows/downloads/windows-sdk/
   - Or use Visual Studio installer

3. Import certificate to Windows Certificate Store
   - Or use .pfx file directly
"""

import os
import subprocess
from pathlib import Path

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent.parent
EXE_PATH = PROJECT_ROOT / 'build' / 'output' / 'dist' / 'EzPrintAgent.exe'

# Certificate configuration
CERTIFICATE_PATH = os.environ.get('CODE_SIGN_CERT_PATH', '')  # Path to .pfx file
CERTIFICATE_PASSWORD = os.environ.get('CODE_SIGN_CERT_PASSWORD', '')  # Certificate password
TIMESTAMP_URL = 'http://timestamp.digicert.com'  # Timestamp server

# SignTool.exe locations (check these paths)
SIGNTOOL_PATHS = [
    r"C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe",
    r"C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe",
    r"C:\Program Files\Microsoft SDKs\Windows\v7.1\Bin\signtool.exe",
]


def find_signtool():
    """Find signtool.exe on the system"""
    for path in SIGNTOOL_PATHS:
        if os.path.exists(path):
            return path

    print("ERROR: signtool.exe not found!")
    print("Please install Windows SDK or Visual Studio")
    print("Or set the path manually in SIGNTOOL_PATHS")
    return None


def sign_executable():
    """Sign the executable with digital certificate"""
    if not EXE_PATH.exists():
        print(f"ERROR: Executable not found: {EXE_PATH}")
        print("Build the executable first using build_windows.py")
        return False

    signtool = find_signtool()
    if not signtool:
        return False

    if not CERTIFICATE_PATH or not os.path.exists(CERTIFICATE_PATH):
        print("ERROR: Certificate file not found!")
        print(f"Set CODE_SIGN_CERT_PATH environment variable")
        print(f"Current value: {CERTIFICATE_PATH or 'Not set'}")
        return False

    print("="*60)
    print("  Code Signing EzPrint Agent")
    print("="*60)
    print()
    print(f"Executable: {EXE_PATH}")
    print(f"Certificate: {CERTIFICATE_PATH}")
    print(f"Timestamp: {TIMESTAMP_URL}")
    print()

    # Sign command
    cmd = [
        signtool,
        'sign',
        '/f', CERTIFICATE_PATH,  # Certificate file
        '/p', CERTIFICATE_PASSWORD,  # Password
        '/tr', TIMESTAMP_URL,  # Timestamp server
        '/td', 'SHA256',  # Timestamp digest algorithm
        '/fd', 'SHA256',  # File digest algorithm
        '/v',  # Verbose
        str(EXE_PATH)
    ]

    try:
        print("Signing executable...")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print("✓ Executable signed successfully!")
            print()
            print("Signature details:")
            print(result.stdout)
            return True
        else:
            print("✗ Signing failed!")
            print(result.stderr)
            return False

    except Exception as e:
        print(f"✗ Error during signing: {e}")
        return False


def verify_signature():
    """Verify the executable signature"""
    signtool = find_signtool()
    if not signtool:
        return False

    print()
    print("Verifying signature...")

    cmd = [signtool, 'verify', '/pa', '/v', str(EXE_PATH)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ Signature verified successfully!")
            print(result.stdout)
            return True
        else:
            print("✗ Signature verification failed!")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"✗ Error verifying signature: {e}")
        return False


def main():
    """Main signing process"""
    print()
    print("="*60)
    print("  EzPrint Agent - Code Signing")
    print("="*60)
    print()

    if not CERTIFICATE_PATH:
        print("⚠ SETUP REQUIRED")
        print()
        print("To sign the executable, you need:")
        print("1. A code signing certificate (.pfx file)")
        print("2. Set environment variables:")
        print("   set CODE_SIGN_CERT_PATH=C:\\path\\to\\certificate.pfx")
        print("   set CODE_SIGN_CERT_PASSWORD=your_password")
        print()
        print("Then run this script again")
        print()
        return

    if sign_executable():
        verify_signature()
        print()
        print("="*60)
        print("  Signing Complete!")
        print("="*60)
    else:
        print()
        print("="*60)
        print("  Signing Failed")
        print("="*60)


if __name__ == "__main__":
    main()

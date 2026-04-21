"""
EzPrint Agent - Windows Build Script
Automates the complete build process from source to installer
"""
import os
import sys
import shutil
import subprocess
import hashlib
import zipfile
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import version info
from shared import version

# Color output for terminal
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(msg):
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}  {msg}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}\n")

def print_success(msg):
    print(f"{Colors.GREEN}✓ {msg}{Colors.ENDC}")

def print_error(msg):
    print(f"{Colors.FAIL}✗ {msg}{Colors.ENDC}")

def print_warning(msg):
    print(f"{Colors.WARNING}⚠ {msg}{Colors.ENDC}")

def print_info(msg):
    print(f"{Colors.CYAN}ℹ {msg}{Colors.ENDC}")


class BuildManager:
    """Manages the build process"""

    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.build_dir = self.project_root / 'build'
        self.output_dir = self.build_dir / 'output'
        self.dist_dir = self.output_dir / 'dist'
        self.release_dir = self.output_dir / 'release'
        self.spec_file = self.build_dir / 'config' / 'ezprint_agent.spec'

        self.version = version.VERSION
        self.build_date = datetime.now().strftime('%Y-%m-%d')

    def clean_build(self):
        """Clean previous build artifacts"""
        print_header("Cleaning Previous Builds")

        dirs_to_clean = [
            self.output_dir / 'dist',
            self.output_dir / 'build',
            self.output_dir / 'release',
        ]

        for dir_path in dirs_to_clean:
            if dir_path.exists():
                print_info(f"Removing {dir_path}")
                shutil.rmtree(dir_path, ignore_errors=True)

        # Recreate directories
        self.dist_dir.mkdir(parents=True, exist_ok=True)
        self.release_dir.mkdir(parents=True, exist_ok=True)

        print_success("Build directories cleaned")

    def check_dependencies(self):
        """Check if all required tools are installed"""
        print_header("Checking Dependencies")

        dependencies = {
            'python': ['python', '--version'],
            'pyinstaller': ['pyinstaller', '--version'],
        }

        all_ok = True
        for name, cmd in dependencies.items():
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    version_output = result.stdout.strip() or result.stderr.strip()
                    print_success(f"{name}: {version_output}")
                else:
                    print_error(f"{name}: Not found")
                    all_ok = False
            except FileNotFoundError:
                print_error(f"{name}: Not found")
                all_ok = False
            except Exception as e:
                print_warning(f"{name}: Check failed ({e})")

        if not all_ok:
            print_error("Some dependencies are missing!")
            print_info("Install missing dependencies:")
            print_info("  pip install -r requirements.txt")
            return False

        print_success("All dependencies OK")
        return True

    def validate_environment(self):
        """Validate the build environment"""
        print_header("Validating Environment")

        checks = [
            (self.spec_file.exists(), f"Spec file exists: {self.spec_file}"),
            ((self.project_root / 'shopkeeper_app' / 'main.py').exists(), "Entry point exists"),
            ((self.project_root / 'assets' / 'icons' / 'ezprint.ico').exists(), "Icon file exists"),
            ((self.project_root / 'requirements.txt').exists(), "Requirements file exists"),
        ]

        all_ok = True
        for check, msg in checks:
            if check:
                print_success(msg)
            else:
                print_error(msg)
                all_ok = False

        if not all_ok:
            print_error("Environment validation failed!")
            return False

        print_success("Environment validation passed")
        return True

    def build_exe(self):
        """Build the executable using PyInstaller"""
        print_header(f"Building EzPrintAgent v{self.version}")

        print_info(f"Spec file: {self.spec_file}")
        print_info(f"Output directory: {self.dist_dir}")

        # Build command
        cmd = [
            'pyinstaller',
            '--clean',  # Clean PyInstaller cache
            '--noconfirm',  # Don't ask for confirmation
            '--distpath', str(self.dist_dir),
            '--workpath', str(self.output_dir / 'build'),
            str(self.spec_file)
        ]

        print_info(f"Running: {' '.join(cmd)}")

        try:
            # Run PyInstaller
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=600  # 10 minutes timeout
            )

            # Check if successful
            exe_path = self.dist_dir / 'EzPrintAgent.exe'

            if result.returncode == 0 and exe_path.exists():
                size_mb = exe_path.stat().st_size / 1024 / 1024
                print_success(f"Build successful! ({size_mb:.2f} MB)")
                print_info(f"Executable: {exe_path}")
                return True
            else:
                print_error("Build failed!")
                if result.stderr:
                    print_error(f"Error output:\n{result.stderr}")
                if result.stdout:
                    print_info(f"Build output:\n{result.stdout}")
                return False

        except subprocess.TimeoutExpired:
            print_error("Build timed out after 10 minutes!")
            return False
        except Exception as e:
            print_error(f"Build error: {e}")
            return False

    def calculate_checksum(self, file_path):
        """Calculate SHA256 checksum of file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def create_installer(self):
        """Create NSIS installer (if NSIS is available)"""
        print_header("Creating Installer")

        # Check if NSIS is installed
        nsis_paths = [
            r"C:\Program Files (x86)\NSIS\makensis.exe",
            r"C:\Program Files\NSIS\makensis.exe",
        ]

        nsis_exe = None
        for path in nsis_paths:
            if os.path.exists(path):
                nsis_exe = path
                break

        if not nsis_exe:
            print_warning("NSIS not found. Skipping installer creation.")
            print_info("Download NSIS from: https://nsis.sourceforge.io/")
            print_info("You can create the installer manually later.")
            return False

        nsi_script = self.build_dir / 'config' / 'installer.nsi'
        if not nsi_script.exists():
            print_warning(f"Installer script not found: {nsi_script}")
            print_info("Installer creation skipped.")
            return False

        try:
            print_info(f"Running NSIS: {nsis_exe}")
            result = subprocess.run(
                [nsis_exe, str(nsi_script)],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes
            )

            if result.returncode == 0:
                print_success("Installer created successfully")
                return True
            else:
                print_error(f"Installer creation failed: {result.stderr}")
                return False

        except Exception as e:
            print_error(f"Installer creation error: {e}")
            return False

    def package_release(self):
        """Create final release package"""
        print_header("Packaging Release")

        exe_path = self.dist_dir / 'EzPrintAgent.exe'
        if not exe_path.exists():
            print_error("Executable not found! Build may have failed.")
            return False

        # Copy exe to release directory
        release_exe = self.release_dir / f'EzPrintAgent_v{self.version}.exe'
        shutil.copy2(exe_path, release_exe)
        print_success(f"Copied: {release_exe.name}")

        # Calculate checksum
        checksum = self.calculate_checksum(release_exe)
        checksum_file = self.release_dir / 'checksums.txt'
        with open(checksum_file, 'w') as f:
            f.write(f"SHA256 ({release_exe.name}) = {checksum}\n")
        print_success(f"Checksum: {checksum[:16]}...")

        # Create README
        readme = self.release_dir / 'README.txt'
        with open(readme, 'w') as f:
            f.write(f"""
EzPrint Agent v{self.version}
{'='*60}

INSTALLATION:
1. Run Ez PrintAgent_v{self.version}.exe
2. Follow the installation wizard
3. Launch EzPrint Agent from desktop or start menu
4. Login with your shop credentials

SYSTEM REQUIREMENTS:
- Windows 10 or later (64-bit)
- 4GB RAM minimum
- Internet connection
- Local printer access

FEATURES:
- Print shop management
- Local printer control
- Real-time job notifications
- File format support: PDF, DOCX, images
- S3 cloud storage support
- Auto-update mechanism

SUPPORT:
- Documentation: https://docs.ezprint.com
- Email: support@ezprint.com
- Website: https://ezprint.com

BUILD INFORMATION:
- Version: {self.version}
- Build Date: {self.build_date}
- Channel: {version.CHANNEL}
- SHA256: {checksum}

{'='*60}
Copyright © {datetime.now().year} EzPrint. All rights reserved.
            """)
        print_success(f"Created: {readme.name}")

        # Create release notes
        release_notes = self.release_dir / 'RELEASE_NOTES.txt'
        with open(release_notes, 'w') as f:
            f.write(f"""
EzPrint Agent v{self.version} - Release Notes
{'='*60}

RELEASE DATE: {self.build_date}

NEW FEATURES:
- Windows executable packaging with PyInstaller
- S3-compatible storage support (MinIO, Cloudflare R2, AWS S3)
- Automatic update mechanism
- Enhanced file processing pipeline
- Improved error handling

IMPROVEMENTS:
- Optimized executable size with UPX compression
- Better printer detection and management
- Enhanced logging and diagnostics
- Modern UI with PyQt5

BUG FIXES:
- Fixed file upload issues
- Resolved printer connectivity problems
- Improved stability and performance

KNOWN ISSUES:
- First launch may be slower (unpacking)
- Antivirus may flag executable (false positive)

UPGRADE NOTES:
- Automatic updates will be available after installation
- Previous settings and data will be preserved

{'='*60}
            """)
        print_success(f"Created: {release_notes.name}")

        # Create ZIP archive
        zip_name = f'EzPrintAgent_v{self.version}_Windows.zip'
        zip_path = self.output_dir / zip_name
        print_info(f"Creating ZIP archive: {zip_name}")

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in self.release_dir.glob('*'):
                zipf.write(file, file.name)

        zip_size_mb = zip_path.stat().st_size / 1024 / 1024
        print_success(f"Release package created: {zip_name} ({zip_size_mb:.2f} MB)")

        return True

    def print_summary(self):
        """Print build summary"""
        print_header("Build Summary")

        print(f"{Colors.BOLD}Version:{Colors.ENDC} {version.VERSION}")
        print(f"{Colors.BOLD}Build Date:{Colors.ENDC} {self.build_date}")
        print(f"{Colors.BOLD}Channel:{Colors.ENDC} {version.CHANNEL}")

        exe_path = self.dist_dir / 'EzPrintAgent.exe'
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / 1024 / 1024
            print(f"{Colors.BOLD}Executable Size:{Colors.ENDC} {size_mb:.2f} MB")

        print(f"\n{Colors.BOLD}Output Files:{Colors.ENDC}")
        print(f"  • Executable: {self.dist_dir / 'EzPrintAgent.exe'}")

        zip_name = f'EzPrintAgent_v{self.version}_Windows.zip'
        zip_path = self.output_dir / zip_name
        if zip_path.exists():
            print(f"  • Release Package: {zip_path}")

        print(f"\n{Colors.BOLD}Next Steps:{Colors.ENDC}")
        print("  1. Test the executable on a clean Windows machine")
        print("  2. Run build/scripts/sign_exe.py to code sign (if certificate available)")
        print("  3. Upload to distribution server using build/scripts/upload_release.py")
        print("  4. Update version API endpoint with new release info")


def main():
    """Main build process"""
    print(f"{Colors.BOLD}{Colors.BLUE}")
    print("  ╔═══════════════════════════════════════════════════╗")
    print("  ║    EzPrint Agent - Windows Build Script          ║")
    print("  ╚═══════════════════════════════════════════════════╝")
    print(f"{Colors.ENDC}\n")

    builder = BuildManager()

    try:
        # Step 1: Clean previous builds
        builder.clean_build()

        # Step 2: Check dependencies
        if not builder.check_dependencies():
            sys.exit(1)

        # Step 3: Validate environment
        if not builder.validate_environment():
            sys.exit(1)

        # Step 4: Build executable
        if not builder.build_exe():
            sys.exit(1)

        # Step 5: Create installer (optional)
        builder.create_installer()

        # Step 6: Package release
        if not builder.package_release():
            sys.exit(1)

        # Step 7: Print summary
        builder.print_summary()

        print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.GREEN}  ✓ BUILD COMPLETE!{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.ENDC}\n")

    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Build cancelled by user{Colors.ENDC}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.FAIL}Build failed: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

# EzPrint Agent - Build System Documentation

## Overview

This directory contains the complete build system for packaging EzPrint Agent as a standalone Windows executable with installer.

## Directory Structure

```
build/
├── config/                     # Build configurations
│   ├── ezprint_agent.spec     # PyInstaller specification
│   ├── installer.nsi          # NSIS installer script
│   ├── version_info.txt       # Windows version resource
│   └── build_config.json      # Build settings
│
├── scripts/                    # Build automation
│   ├── build_windows.py       # Main build script ⭐
│   ├── clean.py               # Cleanup script
│   ├── sign_exe.py            # Code signing
│   └── upload_release.py      # Release distribution
│
├── assets/                     # Installer resources
│   ├── license.txt            # EULA
│   ├── installer_banner.bmp   # Installer graphics (create)
│   └── installer_icon.ico     # Installer icon (use existing)
│
└── output/                     # Build outputs (gitignored)
    ├── dist/                  # Compiled executables
    ├── build/                 # PyInstaller temp files
    └── release/               # Final release packages
```

## Prerequisites

### Required Software

1. **Python 3.8+**
   ```bash
   python --version
   ```

2. **PyInstaller 5.13+**
   ```bash
   pip install pyinstaller
   ```

3. **All project dependencies**
   ```bash
   pip install -r requirements.txt
   ```

### Optional (for installer creation)

4. **NSIS (Nullsoft Scriptable Install System)**
   - Download: https://nsis.sourceforge.io/
   - Install to default location: `C:\Program Files (x86)\NSIS\`

5. **Code Signing Certificate** (recommended for production)
   - Purchase from DigiCert, Sectigo, or SSL.com
   - Cost: $200-400/year
   - Prevents antivirus false positives

## Quick Start

### Build Executable

```bash
# From project root
python build/scripts/build_windows.py
```

This single command will:
1. ✓ Clean previous builds
2. ✓ Check dependencies
3. ✓ Validate environment
4. ✓ Build EzPrintAgent.exe with PyInstaller
5. ✓ Create installer (if NSIS available)
6. ✓ Package release with README and checksums
7. ✓ Create ZIP distribution

### Output

After successful build:
```
build/output/
├── dist/
│   └── EzPrintAgent.exe           # Standalone executable (~80-120 MB)
│
└── release/
    ├── EzPrintAgent_v1.0.0.exe    # Copy of executable
    ├── README.txt                  # Installation instructions
    ├── RELEASE_NOTES.txt          # Version changelog
    └── checksums.txt              # SHA256 checksums

# ZIP package
build/output/EzPrintAgent_v1.0.0_Windows.zip  # Ready for distribution
```

## Build Commands

### Clean Build Artifacts

```bash
python build/scripts/clean.py
```

Removes:
- build/output/dist/
- build/output/build/
- build/output/release/
- Python cache files (__pycache__)

### Manual PyInstaller Build

```bash
# From project root
pyinstaller build/config/ezprint_agent.spec
```

### Code Signing (Optional but Recommended)

```bash
# Set environment variables
set CODE_SIGN_CERT_PATH=C:\path\to\certificate.pfx
set CODE_SIGN_CERT_PASSWORD=your_password

# Sign the executable
python build/scripts/sign_exe.py
```

### Upload Release (For SaaS deployment)

```bash
# Set API key
set RELEASE_API_KEY=your_api_key

# Upload to distribution server
python build/scripts/upload_release.py
```

## Configuration

### Version Management

Edit `shared/version.py`:
```python
VERSION = "1.0.0"           # Semantic version
BUILD_DATE = "2024-04-08"   # Build date
CHANNEL = "stable"          # stable, beta, dev
```

### PyInstaller Options

Edit `build/config/ezprint_agent.spec`:
- **Hidden imports**: Add missing modules
- **Data files**: Include additional resources
- **Excludes**: Remove unused packages
- **UPX compression**: Enable/disable compression
- **Console mode**: Show/hide console window

### Build Settings

Edit `build/config/build_config.json`:
```json
{
  "app_name": "EzPrint Agent",
  "version": "1.0.0",
  "channel": "stable",
  "compress_with_upx": true,
  "create_installer": true,
  "sign_executable": false
}
```

## Troubleshooting

### Issue: Missing Module Errors

**Problem**: `ModuleNotFoundError: No module named 'xyz'`

**Solution**: Add to `hiddenimports` in ezprint_agent.spec:
```python
hiddenimports = [
    'xyz',  # Add missing module here
    # ...
]
```

### Issue: Large Executable Size

**Current**: ~80-120 MB
**Optimization**:

1. Enable UPX compression (already enabled)
2. Add unused packages to `excludes`:
   ```python
   excludes = [
       'matplotlib',
       'pandas',
       # Add more here
   ]
   ```
3. Switch to onedir mode (faster startup but multiple files)

### Issue: Antivirus False Positive

**Problem**: Windows Defender flags .exe as malware

**Solutions**:
1. **Code sign the executable** (best solution)
   - Provides digital signature verification
   - Builds trust over time

2. **Submit to Microsoft**
   - https://www.microsoft.com/en-us/wdsi/filesubmission

3. **Add to exclusions** (temporary)
   - Windows Security → Virus & threat protection → Exclusions

### Issue: DLL Missing Errors

**Problem**: `DLL not found` errors on target machine

**Solution**: Add DLLs to `binaries` in spec file:
```python
binaries = [
    ('C:\\Windows\\System32\\vcruntime140.dll', '.'),
]
```

### Issue: PyQt5 Import Errors

**Problem**: `ImportError: DLL load failed while importing QtCore`

**Solution**: Ensure all PyQt5 modules in hiddenimports:
```python
hiddenimports = [
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtPrintSupport',
]
```

### Issue: Slow First Startup

**Problem**: First run takes 10-20 seconds

**Reason**: Single-file executable unpacks to temp directory

**Solutions**:
1. This is normal for onefile mode
2. Switch to onedir mode for instant startup (but multiple files)
3. Inform users that first launch is slower

## Performance Optimization

### Current Configuration

- **Mode**: Single-file executable (onefile=True)
- **Compression**: UPX enabled
- **Size**: 80-120 MB
- **Startup**: 2-5 seconds (first run slower)

### Alternative: One-Folder Mode

Edit spec file:
```python
# Remove these from EXE()
exe = EXE(
    pyz,
    a.scripts,
    # Remove a.binaries, a.zipfiles, a.datas
    # ...
)

# Add COLLECT section
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='EzPrintAgent'
)
```

**Result**:
- Multiple files in folder
- Instant startup
- Easier to debug

## CI/CD Integration

### GitHub Actions Example

Create `.github/workflows/build-windows.yml`:

```yaml
name: Build Windows Installer

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: windows-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'

    - name: Install dependencies
      run: pip install -r requirements.txt

    - name: Build executable
      run: python build/scripts/build_windows.py

    - name: Create Release
      uses: softprops/action-gh-release@v1
      with:
        files: build/output/EzPrintAgent_*_Windows.zip
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Release Checklist

Before releasing a new version:

- [ ] Update version in `shared/version.py`
- [ ] Update RELEASE_NOTES.txt
- [ ] Test on clean Windows 10/11 VM
- [ ] Run full test suite
- [ ] Build executable: `python build/scripts/build_windows.py`
- [ ] Code sign (if certificate available)
- [ ] Test executable on different machines
- [ ] Upload to distribution server
- [ ] Update version API endpoint
- [ ] Create GitHub release
- [ ] Announce to users

## Support

For build issues:
- Check TESTING.md for test procedures
- Review PyInstaller documentation: https://pyinstaller.org/
- Check project issues on GitHub
- Contact: dev@ezprint.com

## License

Copyright (c) 2024 EzPrint. All rights reserved.

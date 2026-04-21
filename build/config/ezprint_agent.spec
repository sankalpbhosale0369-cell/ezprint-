# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification file for EzPrint Agent
Builds a standalone Windows executable with all dependencies bundled
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

# Get project root directory
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(SPEC))))

block_cipher = None

# ======================================================================
# DATA FILES TO INCLUDE
# ======================================================================
datas = [
    # Application icon
    (os.path.join(project_root, 'assets/icons/ezprint.ico'), 'assets/icons'),

    # Configuration files (optional - can be external too)
    # (os.path.join(project_root, 'shared/config.py'), 'shared'),
]

# ======================================================================
# HIDDEN IMPORTS
# PyInstaller may miss these imports - explicitly include them
# ======================================================================
hiddenimports = [
    # PyQt5 modules
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtWebEngineWidgets',  # For charts (if used)
    'PyQt5.QtPrintSupport',

    # Database — deprecated in the SaaS client; the FastAPI backend owns
    # all persistence. Left here as a safety net in case an unpurged code
    # path still imports SQLAlchemy; strip once dashboard.py is fully DB-free.
    'sqlalchemy',
    'sqlalchemy.orm',

    # File Processing
    'PyPDF2',
    'docx',
    'python_docx',
    'reportlab',
    'reportlab.pdfgen',
    'reportlab.lib',
    'PIL',
    'PIL.Image',
    'PIL._imaging',

    # PDF Processing
    'fitz',  # PyMuPDF
    '_fitz',

    # Windows Printing
    'win32print',
    'win32api',
    'win32con',
    'win32gui',
    'win32com',
    'pywintypes',
    'pythoncom',

    # Networking — new SaaS backend talks FastAPI + native WebSocket.
    # The legacy Flask-SocketIO path has been removed.
    'socket',
    'websocket',  # websocket-client (sync, used by ws_client.py)
    'websocket._app',
    'requests',
    'urllib3',
    'httpx',
    'h11',
    'certifi',
    'anyio',
    'idna',

    # Utilities
    'qrcode',
    'cryptography',
    'bcrypt',
    '_cffi_backend',
    'dotenv',
    'python_dotenv',

    # JSON/Data
    'json',
    'uuid',
    'datetime',
    'pathlib',
    'tempfile',
    'io',
]

# ======================================================================
# BINARIES TO INCLUDE
# ======================================================================
binaries = []

# Add PyMuPDF DLLs if needed
try:
    binaries += collect_dynamic_libs('fitz')
except:
    pass

# ======================================================================
# MODULES TO EXCLUDE (reduce size)
# ======================================================================
excludes = [
    # Unused testing frameworks
    'pytest',
    'unittest',
    'nose',

    # Unused data science libraries
    'matplotlib',
    'numpy',
    'pandas',
    'scipy',
    'sklearn',

    # Unused GUI frameworks
    'tkinter',
    'wx',
    'gtk',

    # Unused development tools
    'IPython',
    'jupyter',
    'notebook',
    '_pytest',

    # Other unused
    'setuptools',
    'pip',
    'wheel',
]

# ======================================================================
# ANALYSIS PHASE
# ======================================================================
a = Analysis(
    # Entry point script
    [os.path.join(project_root, 'shopkeeper_app/main.py')],

    pathex=[project_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[os.path.join(project_root, 'build/hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ======================================================================
# PYZ (Python ZIP archive)
# ======================================================================
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

# ======================================================================
# EXE (Executable)
# ======================================================================
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='EzPrintAgent',
    debug=False,  # Set to True for debugging
    bootloader_ignore_signals=False,
    strip=False,  # Don't strip symbols (helps with debugging)
    upx=True,  # Compress with UPX (reduces size)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Windowed application (no console)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,

    # Windows-specific options
    icon=os.path.join(project_root, 'assets/icons/ezprint.ico'),
    version=os.path.join(project_root, 'build/config/version_info.txt'),
    uac_admin=False,  # Don't require admin privileges
    uac_uiaccess=False,
)

# ======================================================================
# NOTES & TROUBLESHOOTING
# ======================================================================
"""
BUILD COMMAND:
    pyinstaller build/config/ezprint_agent.spec

OUTPUT:
    build/output/dist/EzPrintAgent.exe

COMMON ISSUES:

1. Missing imports:
   - Add to hiddenimports list above
   - Check logs for "ModuleNotFoundError"

2. Large file size:
   - Enable UPX compression (upx=True)
   - Add more modules to excludes list
   - Use --noupx if UPX causes issues

3. Antivirus false positives:
   - Code sign the executable
   - Submit to Microsoft for analysis

4. DLL errors:
   - Check binaries list
   - May need to manually copy DLLs

5. PyQt5 errors:
   - Ensure all PyQt5.Qt* modules are in hiddenimports
   - Check Qt plugins are included

6. Database errors:
   - Check SQLAlchemy and psycopg2 imports
   - May need to include database drivers separately

OPTIMIZATION:
- Current spec creates single-file exe (~80-120 MB)
- First run is slower (unpacks to temp)
- Can switch to onedir mode for faster startup

To build one-folder instead:
- Remove all items from EXE() after pyz
- Add COLLECT() section:

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='EzPrintAgent'
    )
"""

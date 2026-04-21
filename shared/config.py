"""Configuration for the EzPrint Windows shopkeeper agent.

Everything Flask / Socket.IO / Cloudinary / SMTP related has moved to
``ezprint-backend`` (FastAPI). This file now carries only the settings the
Windows .exe actually reads — backend URLs, auto-update endpoints, local
printing knobs, and a few legacy file-processing defaults.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# When running as a PyInstaller frozen exe, __file__ resolves inside the
# temp extraction dir (_MEIPASS), not next to the .exe. Load .env from the
# exe's directory first, then fall back to the repo root for dev.
if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).parent
    _env_candidates = [_exe_dir / ".env", BASE_DIR / ".env"]
else:
    _env_candidates = [BASE_DIR / ".env"]

for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path)
        break


# ── Agent → ezprint-backend (FastAPI) ─────────────────────────────────────────
# The .exe talks to this host for all REST + WebSocket calls. Defaults to the
# dev docker-compose (http://localhost:8000). In production set
# ``EZPRINT_API_BASE_URL`` to the public HTTPS API; the WS URL is derived
# automatically (http → ws, https → wss).
EZPRINT_API_BASE_URL = os.environ.get(
    "EZPRINT_API_BASE_URL", "http://localhost:8000"
).rstrip("/")


def _derive_ws_url(http_base: str) -> str:
    if http_base.startswith("https://"):
        return "wss://" + http_base[len("https://"):] + "/ws/agent"
    if http_base.startswith("http://"):
        return "ws://" + http_base[len("http://"):] + "/ws/agent"
    return http_base + "/ws/agent"


EZPRINT_WS_URL = os.environ.get("EZPRINT_WS_URL", _derive_ws_url(EZPRINT_API_BASE_URL))

# Back-compat alias: some older agent modules still import EZPRINT_BASE_URL.
EZPRINT_BASE_URL = EZPRINT_API_BASE_URL

# Licensing gate — disabled by default on the new SaaS backend; the
# subscription/licensing service is a future deliverable.
EZPRINT_LICENSE_ENABLED = os.environ.get(
    "EZPRINT_LICENSE_ENABLED", "false"
).lower() == "true"


# ── Local database (shrinking, legacy only) ───────────────────────────────────
# ``shared.database`` still drives a handful of dashboard code paths on the
# client. New code must NOT add DB calls here — read/write through the API
# instead. The backend owns the real Postgres.
#
# The DB file location is resolved to a stable absolute path so the
# PyInstaller-packaged exe doesn't create it in an unwritable install dir
# (e.g. C:\Program Files\EzPrint) or lose it between runs when CWD changes.
def _default_sqlite_url() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home())
        data_dir = Path(base) / "EzPrint"
    elif sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support" / "EzPrint"
    else:
        data_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "EzPrint"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        data_dir = BASE_DIR

    db_path = data_dir / "ezprint_local.db"

    # One-shot migration: older builds wrote `fallback.db` next to the CWD
    # (or the exe). If the new AppData file does not exist yet but an old
    # one does, move it over so activated printers / history are preserved.
    if not db_path.exists():
        legacy_candidates = [
            Path.cwd() / "fallback.db",
            BASE_DIR / "fallback.db",
        ]
        if getattr(sys, "frozen", False):
            legacy_candidates.insert(0, Path(sys.executable).parent / "fallback.db")
        for legacy in legacy_candidates:
            try:
                if legacy.exists() and legacy.resolve() != db_path.resolve():
                    import shutil
                    shutil.copy2(str(legacy), str(db_path))
                    break
            except Exception:
                continue

    return f"sqlite:///{db_path.as_posix()}"


DATABASE_URL = os.environ.get("DATABASE_URL", _default_sqlite_url())


# ── File handling (local preview / n-up PDF generation) ───────────────────────
UPLOAD_FOLDER = BASE_DIR / "uploads"
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # bytes
ALLOWED_EXTENSIONS = set(
    os.environ.get(
        "ALLOWED_EXTENSIONS",
        "pdf,docx,doc,ppt,pptx,png,jpg,jpeg,gif,bmp,tiff",
    ).split(",")
)


# ── Printing ──────────────────────────────────────────────────────────────────
DEFAULT_PRINTER: str | None = None
PRINT_TIMEOUT = 30  # seconds
PRINT_CONFIRMATION_TIMEOUT_SECS = int(
    os.environ.get("PRINT_CONFIRMATION_TIMEOUT_SECS", "180")
)
SEND_RETRY_ATTEMPTS = int(os.environ.get("SEND_RETRY_ATTEMPTS", "3"))
SEND_RETRY_BASE_DELAY_SECS = float(os.environ.get("SEND_RETRY_BASE_DELAY_SECS", "1"))

# Discovery / scanning limits
NETWORK_SCAN_MAX_IP = int(os.environ.get("NETWORK_SCAN_MAX_IP", "50"))
NETWORK_SCAN_MAX_THREADS = int(os.environ.get("NETWORK_SCAN_MAX_THREADS", "20"))

# Ghostscript: absolute path, optionally discovered at startup.
GHOSTSCRIPT_EXE = os.environ.get("GHOSTSCRIPT_EXE")


# ── QR code generation ────────────────────────────────────────────────────────
QR_CODE_SIZE = 10
QR_CODE_BORDER = 4


# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "logs" / "ezprint.log"


# ── Auto-update channel (agent only) ──────────────────────────────────────────
UPDATE_CHECK_URL = os.environ.get(
    "UPDATE_CHECK_URL", "https://api.ezprint.com/agent/version"
)
UPDATE_DOWNLOAD_URL = os.environ.get(
    "UPDATE_DOWNLOAD_URL", "https://api.ezprint.com/agent/download"
)
UPDATE_CHANNEL = os.environ.get("UPDATE_CHANNEL", "stable")  # stable | beta | dev
AUTO_UPDATE_ENABLED = os.environ.get("AUTO_UPDATE_ENABLED", "true").lower() == "true"
SHOP_API_TOKEN = os.environ.get("SHOP_API_TOKEN")


# ── Side effects: create directories the agent writes into ────────────────────
UPLOAD_FOLDER.mkdir(exist_ok=True)
(BASE_DIR / "logs").mkdir(exist_ok=True)

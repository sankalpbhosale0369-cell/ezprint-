"""
EzPrint Licensing Module
========================
Self-contained license verification for the EzPrint desktop application.

Responsibilities:
    1. Generate a stable, unique device_id for this Windows machine
    2. Call the backend /api/license/check endpoint
    3. Return a clear allow/block decision to main.py
    4. Show appropriate UI dialogs for expired/blocked licenses
    5. Never crash the app — always fail open on server errors
    6. Cache the last known license status locally for offline use

Usage in main.py:
    from shopkeeper_app.licensing import verify_startup_license
    if not verify_startup_license():
        sys.exit(0)
"""

import hashlib
import json
import logging
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# winreg is Windows-only; guard import for portability
try:
    import winreg
except ImportError:
    winreg = None

import requests

# Add parent directory to path for shared imports (mirrors api_client.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.config import EZPRINT_BASE_URL

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache for device_id (computed once, reused forever)
# ---------------------------------------------------------------------------
_cached_device_id: str | None = None

# ---------------------------------------------------------------------------
# Cache file location: %APPDATA%/EzPrint/license_cache.json
# ---------------------------------------------------------------------------
_CACHE_DIR = Path(os.environ.get("APPDATA", Path.home())) / "EzPrint"
_CACHE_FILE = _CACHE_DIR / "license_cache.json"

# Cache validity period in hours
_CACHE_MAX_AGE_HOURS = 24

# Network timeout for license check (seconds)
_LICENSE_CHECK_TIMEOUT = 8


# ═══════════════════════════════════════════════════════════════════════════
# FUNCTION 1: get_device_id
# ═══════════════════════════════════════════════════════════════════════════

def get_device_id() -> str:
    """
    Generate a stable, unique device identifier for this Windows machine.

    Strategy:
        Primary — SHA-256(MachineGuid + MAC address)
        Fallback — SHA-256(hostname + MAC address)

    The result is cached in a module-level variable after the first call
    so the value never changes during one process lifetime.

    Returns:
        64-character lowercase hex string (SHA-256 digest).
        Never raises — returns a fallback ID on any error.
    """
    global _cached_device_id

    if _cached_device_id is not None:
        return _cached_device_id

    try:
        machine_guid = None

        # --- Step 1: read Windows MachineGuid from the registry ---
        if winreg is not None:
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Cryptography",
                )
                machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                winreg.CloseKey(key)
            except Exception as e:
                logger.debug(f"Could not read MachineGuid from registry: {e}")

        # --- Step 2: get MAC address ---
        mac = str(uuid.getnode())

        # --- Step 3: combine & hash ---
        if machine_guid:
            raw = f"{machine_guid}_{mac}"
        else:
            # Fallback: hostname + MAC (VMs, Wine, non-Windows)
            raw = f"{platform.node()}_{mac}"

        device_id = hashlib.sha256(raw.encode()).hexdigest()

        _cached_device_id = device_id
        logger.debug(f"Device ID generated: {device_id[:8]}…")
        return device_id

    except Exception as e:
        # Absolute last resort — should never happen, but we never crash.
        logger.error(f"Unexpected error generating device ID: {e}")
        fallback = hashlib.sha256(
            f"{platform.node()}_{uuid.getnode()}".encode()
        ).hexdigest()
        _cached_device_id = fallback
        logger.debug(f"Device ID fallback generated: {fallback[:8]}…")
        return fallback


# ═══════════════════════════════════════════════════════════════════════════
# FUNCTION 2: check_license
# ═══════════════════════════════════════════════════════════════════════════

def check_license(email: str | None = None) -> dict:
    """
    Verify the current license status with the backend.

    Calls POST /api/license/check with the device_id (and optional email).
    On success the response is cached locally for offline use.
    On network failure the cached response is returned if fresh enough.
    If no cache is available the function fails OPEN (allows the app).

    Args:
        email: Optional user email to attach to the license check.

    Returns:
        dict with at least ``status``, ``days_remaining``, ``message`` keys.
        Never raises an exception.
    """
    device_id = get_device_id()
    payload = {"device_id": device_id, "email": email}

    # ------------------------------------------------------------------
    # 1. Try a fresh check against the server
    # ------------------------------------------------------------------
    try:
        url = f"{EZPRINT_BASE_URL}/api/license/check"
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=_LICENSE_CHECK_TIMEOUT,
        )

        if response.status_code == 200:
            data = response.json()
            # Normalise: the backend may wrap in {"success": true, "data": {…}}
            if "data" in data and isinstance(data["data"], dict):
                result = data["data"]
            else:
                result = data

            # Ensure minimum keys exist
            result.setdefault("status", "active")
            result.setdefault("days_remaining", None)
            result.setdefault("message", "")

            logger.info(
                f"License check result: status={result['status']}, "
                f"days={result.get('days_remaining')}"
            )
            save_license_cache(result)
            return result

        # Non-200 but server was reachable — treat as server error
        logger.warning(
            f"License server returned HTTP {response.status_code}; "
            f"falling back to cache"
        )

    except requests.exceptions.Timeout:
        logger.warning("License server request timed out; falling back to cache")
    except requests.exceptions.ConnectionError:
        logger.warning("License server unreachable; falling back to cache")
    except Exception as e:
        logger.error(f"Unexpected error in license check: {e}")

    # ------------------------------------------------------------------
    # 2. Server unavailable — try cached response
    # ------------------------------------------------------------------
    cached = get_cached_license()
    if cached is not None:
        return cached

    # ------------------------------------------------------------------
    # 3. No cache — FAIL OPEN
    # ------------------------------------------------------------------
    logger.warning(
        "License server unreachable, no cache available — fail-open (allowing app)"
    )
    return {
        "status": "active",
        "days_remaining": None,
        "message": "Offline mode",
    }


# ═══════════════════════════════════════════════════════════════════════════
# FUNCTION 3: get_cached_license
# ═══════════════════════════════════════════════════════════════════════════

def get_cached_license() -> dict | None:
    """
    Read the locally cached license response.

    Cache location: ``%APPDATA%/EzPrint/license_cache.json``

    Returns:
        The cached dict if the file exists, is valid JSON, and was written
        less than 24 hours ago.  Returns ``None`` otherwise.
    """
    try:
        if not _CACHE_FILE.exists():
            return None

        with open(_CACHE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        # Validate timestamp
        cached_at_str = data.get("cached_at")
        if not cached_at_str:
            return None

        cached_at = datetime.fromisoformat(cached_at_str.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - cached_at
        age_hours = age.total_seconds() / 3600

        if age_hours >= _CACHE_MAX_AGE_HOURS:
            logger.info(
                f"Cached license expired (age: {age_hours:.1f}h > "
                f"{_CACHE_MAX_AGE_HOURS}h); ignoring cache"
            )
            return None

        logger.info(f"Using cached license (age: {age_hours:.1f}h)")
        return data

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning(f"License cache corrupted, ignoring: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading license cache: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# FUNCTION 4: save_license_cache
# ═══════════════════════════════════════════════════════════════════════════

def save_license_cache(response: dict) -> None:
    """
    Persist the license server response to a local JSON file.

    Adds a ``cached_at`` UTC timestamp and the current ``device_id``
    before writing.  Silently fails on any I/O error.

    Args:
        response: The license response dict to cache.
    """
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

        cache_data = {
            "cached_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "device_id": get_device_id(),
        }
        # Merge response keys (status, days_remaining, message, trial_end …)
        cache_data.update(response)

        with open(_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(cache_data, fh, indent=2)

        logger.debug("License cache saved successfully")

    except Exception as e:
        # Read-only filesystem, permissions, disk full — silently continue
        logger.warning(f"Could not save license cache: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# FUNCTION 5: verify_startup_license
# ═══════════════════════════════════════════════════════════════════════════

def verify_startup_license(email: str | None = None) -> bool:
    """
    Top-level license gate called from ``main.py`` at startup.

    Checks the license status and shows the appropriate dialog
    when the user needs to be informed.

    Args:
        email: Optional user email for the license check.

    Returns:
        ``True``  — allow the application to continue.
        ``False`` — block the application (main.py should exit).
        Always returns ``True`` on unexpected errors (fail-open).
    """
    try:
        result = check_license(email)
        status = result.get("status", "").lower()
        days_remaining = result.get("days_remaining")

        if status == "active":
            return True

        if status == "trial":
            show_trial_dialog(days_remaining)
            return True  # trial users may continue

        if status == "expired":
            show_expired_dialog()
            return False  # block

        if status == "blocked":
            show_blocked_dialog()
            return False  # block

        # Unknown / missing status — fail-open
        logger.warning(
            f"Unrecognised license status '{status}'; allowing app (fail-open)"
        )
        return True

    except Exception as e:
        logger.error(f"Unexpected error in verify_startup_license: {e}")
        return True  # fail-open


# ═══════════════════════════════════════════════════════════════════════════
# FUNCTION 6: show_trial_dialog
# ═══════════════════════════════════════════════════════════════════════════

def show_trial_dialog(days_remaining: int | None) -> None:
    """
    Display a friendly trial-expiry reminder.

    Only shown during the last 7 days of the trial.  If ``days_remaining``
    is ``None`` or greater than 7 the dialog is suppressed silently.
    """
    try:
        # Suppress for None or > 7 days remaining
        if days_remaining is None or days_remaining > 7:
            return

        from PyQt5.QtWidgets import QMessageBox

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("EzPrint Trial")
        msg.setText(
            f"Welcome! You have {days_remaining} day"
            f"{'s' if days_remaining != 1 else ''} remaining in your "
            f"free trial.\n\nContact us to activate your license."
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    except Exception as e:
        logger.error(f"Error showing trial dialog: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# FUNCTION 7: show_expired_dialog
# ═══════════════════════════════════════════════════════════════════════════

def show_expired_dialog() -> None:
    """
    Inform the user that their free trial has expired.
    """
    try:
        from PyQt5.QtWidgets import QMessageBox

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Trial Expired")
        msg.setText(
            "Your 15-day free trial has expired.\n\n"
            "Please contact us to activate your license.\n\n"
            "Email: support@ezprint.in"
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    except Exception as e:
        logger.error(f"Error showing expired dialog: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# FUNCTION 8: show_blocked_dialog
# ═══════════════════════════════════════════════════════════════════════════

def show_blocked_dialog() -> None:
    """
    Inform the user that their access has been blocked.
    """
    try:
        from PyQt5.QtWidgets import QMessageBox

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Access Blocked")
        msg.setText(
            "Your access has been blocked.\n\n"
            "Please contact support.\n\n"
            "Email: support@ezprint.in"
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    except Exception as e:
        logger.error(f"Error showing blocked dialog: {e}")

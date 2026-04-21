"""Authentication manager for the shopkeeper desktop app.

Thin facade over `ApiClient` that preserves the historical tuple return
shapes (`(success, message, data)`) so `dashboard.py` and `main.py` keep
working without downstream edits. No local DB, no SMTP — the old fallback
paths are removed now that the FastAPI backend is the source of truth.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shopkeeper_app.api_client import ApiClient  # noqa: E402

logger = logging.getLogger(__name__)

SESSION_DIR = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~/.ezprint"),
    "EzPrint",
)
SESSION_FILE = os.path.join(SESSION_DIR, "session.json")
SESSION_MAX_AGE_DAYS = 15


# --------------------------------------------------------------------- shared
def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _shopkeeper_payload(
    info: Dict[str, Any],
    access_token: Optional[str],
    refresh_token: Optional[str] = None,
    agent_token: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the dict shape the existing GUI expects."""
    return {
        "tenant_id": tenant_id or info.get("tenant_id"),
        "shop_id": info.get("shop_id"),
        "username": info.get("username"),
        "shop_name": info.get("shop_name"),
        "shop_address": info.get("shop_address"),
        "contact_number": info.get("contact_number"),
        "shopkeeper_name": info.get("shopkeeper_name"),
        "email": info.get("email"),
        "qr_code_path": info.get("qr_code_path"),
        "slug": info.get("slug"),
        # `session_token` kept for backwards-compat with old call sites.
        "session_token": access_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "agent_token": agent_token,
    }


# --------------------------------------------------------- session persistence
def save_session(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(SESSION_DIR, exist_ok=True)
        payload = {
            "shopkeeper_data": data,
            "timestamp": _now_iso(),
        }
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        logger.exception("save_session failed")


def load_session() -> Optional[Dict[str, Any]]:
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        ts = datetime.fromisoformat(payload.get("timestamp"))
        if datetime.utcnow() - ts > timedelta(days=SESSION_MAX_AGE_DAYS):
            clear_session()
            return None
        return payload.get("shopkeeper_data")
    except Exception:
        logger.exception("load_session failed; clearing")
        clear_session()
        return None


def clear_session() -> None:
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        logger.exception("clear_session failed")


# ================================================================ AuthManager
class AuthManager:
    """Keeps the original class name and method shapes; delegates to ApiClient."""

    _NOT_AVAILABLE = "This feature is temporarily unavailable in the SaaS release."

    def __init__(self, api_client: Optional[ApiClient] = None) -> None:
        self.api_client = api_client or ApiClient()

    # ---------------------------------------------------------------- login
    def login_shopkeeper(
        self, username: str, password: str
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        ok, data, err = self.api_client.login(username, password)
        if not ok or not data:
            return False, err or "Invalid credentials", None

        # Enrich with the full shop profile (address, QR path, etc.).
        info_ok, info, _info_err = self.api_client.get_shop_info()
        if not info_ok or not info:
            info = {
                "shop_id": data.get("shop_id"),
                "shop_name": data.get("shop_name"),
                "shopkeeper_name": data.get("shopkeeper_name"),
                "username": data.get("username"),
                "email": data.get("email"),
                "tenant_id": data.get("tenant_id"),
            }

        shopkeeper_data = _shopkeeper_payload(
            info,
            access_token=self.api_client.access_token,
            refresh_token=self.api_client.refresh_token_value,
            agent_token=self.api_client.agent_token,
            tenant_id=self.api_client.tenant_id,
        )
        try:
            save_session(shopkeeper_data)
        except Exception:
            logger.exception("session persistence failed (ignored)")

        return True, "Login successful", shopkeeper_data

    def resume_session(self) -> Optional[Dict[str, Any]]:
        """Hydrate the ApiClient from a saved session; returns the dict if alive."""
        stored = load_session()
        if not stored:
            return None
        access = stored.get("access_token") or stored.get("session_token")
        refresh = stored.get("refresh_token")
        tenant_id = stored.get("tenant_id")
        if not access or not refresh or not tenant_id:
            clear_session()
            return None

        self.api_client.set_access_token(access, refresh_token=refresh, expires_in=300)
        self.api_client.tenant_id = tenant_id
        self.api_client.shop_id = stored.get("shop_id")
        self.api_client.shop_name = stored.get("shop_name")
        self.api_client.username = stored.get("username")

        # Access may be stale; force a refresh so subsequent REST calls succeed.
        if not self.api_client.refresh_access():
            clear_session()
            return None
        # Agent token always re-minted on resume.
        self.api_client.mint_agent_token()

        # Pull the latest profile so stale address/QR get refreshed on disk.
        _ok, info, _err = self.api_client.get_shop_info()
        info = info or {}
        fresh = _shopkeeper_payload(
            info,
            access_token=self.api_client.access_token,
            refresh_token=self.api_client.refresh_token_value,
            agent_token=self.api_client.agent_token,
            tenant_id=self.api_client.tenant_id,
        )
        save_session(fresh)
        return fresh

    # --------------------------------------------------------------- logout
    def logout_shopkeeper(self, shop_id: Optional[str] = None) -> Tuple[bool, str]:
        try:
            self.api_client.logout()
        except Exception:
            logger.exception("api logout failed (ignored)")
        clear_session()
        return True, "Logged out successfully"

    # ------------------------------------------------------------ shop info
    def get_shopkeeper_by_id(self, shop_id: str) -> Optional[Dict[str, Any]]:
        ok, data, _err = self.api_client.get_shop_info()
        if not ok or not data:
            return None
        return _shopkeeper_payload(
            data,
            access_token=self.api_client.access_token,
            refresh_token=self.api_client.refresh_token_value,
            agent_token=self.api_client.agent_token,
            tenant_id=self.api_client.tenant_id,
        )

    def update_shop_info(
        self,
        shop_id: Optional[str] = None,
        shop_name: Optional[str] = None,
        shop_address: Optional[str] = None,
        contact_number: Optional[str] = None,
        email: Optional[str] = None,
        shopkeeper_name: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        fields = {
            k: v
            for k, v in {
                "shop_name": shop_name,
                "shop_address": shop_address,
                "contact_number": contact_number,
                "email": email,
                "shopkeeper_name": shopkeeper_name,
            }.items()
            if v is not None
        }
        if not fields:
            return False, "No fields to update", None
        ok, data, err = self.api_client.update_shop_info(**fields)
        if not ok or not data:
            return False, err or "Update failed", None
        return True, "Shop information updated successfully", _shopkeeper_payload(
            data,
            access_token=self.api_client.access_token,
            refresh_token=self.api_client.refresh_token_value,
            agent_token=self.api_client.agent_token,
            tenant_id=self.api_client.tenant_id,
        )

    # --------------------------------------- deprecated / not-yet-available
    def register_shopkeeper(
        self,
        username: str,
        email: str,
        password: str,
        shop_name: str,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        # Registration is done via the `admin/tenants` endpoint (operator-only)
        # in the SaaS backend. Surface a clear message to any UI that still
        # calls this.
        return False, self._NOT_AVAILABLE, None

    def send_otp_email(self, username: str) -> Tuple[bool, str]:
        return False, self._NOT_AVAILABLE

    def verify_otp(self, username: str, otp: str) -> Tuple[bool, str]:
        return False, self._NOT_AVAILABLE

    def reset_password(self, username: str, new_password: str) -> Tuple[bool, str]:
        return False, self._NOT_AVAILABLE

    # ---------------------------------------------------------------- misc
    def close(self) -> None:
        # Kept for API symmetry with the old DB-backed implementation.
        return None

"""API client for the Windows shopkeeper agent.

Targets the FastAPI ezprint-backend at `/api/v1/*`. The agent holds two
tokens at the same time:

    - access / refresh   -> used for every shopkeeper REST call
    - agent              -> used for /ws/agent and /jobs/{id}/file-url

Call sites use the historical `(success, data, error_message)` tuple shape
so the rewrite doesn't ripple into dashboard.py / auth.py / printer_manager.py.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import EZPRINT_API_BASE_URL  # noqa: E402

logger = logging.getLogger(__name__)

ApiResult = Tuple[bool, Optional[Any], Optional[str]]


class ApiClient:
    """Thin HTTP client over the new FastAPI backend."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        session_token: Optional[str] = None,  # legacy kwarg; accepts access JWT.
    ) -> None:
        self.base_url = (base_url or EZPRINT_API_BASE_URL).rstrip("/")
        self.timeout = 10

        # Shopkeeper session (set on login/refresh)
        self.access_token: Optional[str] = None
        self.refresh_token_value: Optional[str] = None
        self.access_expires_at: Optional[datetime] = None

        # Separately-issued agent token (for WS + presigned file-url calls).
        self.agent_token: Optional[str] = None
        self.agent_expires_at: Optional[datetime] = None

        # Identity echoed back from the server on login, cached for convenience.
        self.tenant_id: Optional[str] = None
        self.shop_id: Optional[str] = None
        self.shop_slug: Optional[str] = None
        self.shop_name: Optional[str] = None
        self.username: Optional[str] = None

        if session_token:
            # Legacy: callers used to hand us an access JWT directly.
            self.set_access_token(session_token, expires_in=3600)

        logger.info("ApiClient initialized with base_url: %s", self.base_url)

    # ---------------------------------------------------------- legacy alias
    def set_session_token(
        self,
        token: str,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
    ) -> None:
        """Backward-compat alias used by the old shopkeeper dashboard."""
        self.set_access_token(token, refresh_token=refresh_token, expires_in=expires_in)

    # --------------------------------------------------------------- session
    def set_access_token(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
    ) -> None:
        self.access_token = access_token
        if refresh_token is not None:
            self.refresh_token_value = refresh_token
        if expires_in:
            # 60s buffer so callers don't race the clock.
            self.access_expires_at = datetime.utcnow() + timedelta(
                seconds=max(60, expires_in) - 60
            )
        else:
            self.access_expires_at = None

    def set_agent_token(self, token: str, expires_in: Optional[int] = None) -> None:
        self.agent_token = token
        if expires_in:
            self.agent_expires_at = datetime.utcnow() + timedelta(
                seconds=max(60, expires_in) - 60
            )
        else:
            self.agent_expires_at = None

    def clear_session(self) -> None:
        self.access_token = None
        self.refresh_token_value = None
        self.access_expires_at = None
        self.agent_token = None
        self.agent_expires_at = None
        self.tenant_id = None
        self.shop_id = None
        self.shop_slug = None
        self.shop_name = None
        self.username = None

    @property
    def is_authenticated(self) -> bool:
        return bool(self.access_token)

    @property
    def has_agent_token(self) -> bool:
        return bool(self.agent_token)

    # ------------------------------------------------------------- transport
    def _access_headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        return h

    def _agent_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.agent_token}" if self.agent_token else "",
        }

    def _access_needs_refresh(self) -> bool:
        return (
            self.access_expires_at is not None
            and datetime.utcnow() >= self.access_expires_at
        )

    def _agent_needs_mint(self) -> bool:
        if not self.agent_token:
            return True
        if self.agent_expires_at and datetime.utcnow() >= self.agent_expires_at:
            return True
        return False

    def _request(
        self,
        method: str,
        path: str,
        *,
        use_agent: bool = False,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        retry_on_401: bool = True,
    ) -> ApiResult:
        url = f"{self.base_url}{path}"

        # Proactively refresh if the relevant token is about to expire.
        if use_agent:
            if self._agent_needs_mint() and self.access_token:
                self.mint_agent_token()
            headers = self._agent_headers()
        else:
            if self._access_needs_refresh():
                self.refresh_access()
            headers = self._access_headers()

        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            return False, None, "API request timeout"
        except requests.exceptions.ConnectionError:
            return False, None, "Cannot reach backend API"
        except Exception as exc:
            logger.exception("api_request_error %s %s", method, url)
            return False, None, f"API request error: {exc}"

        if resp.status_code == 401 and retry_on_401:
            # Token expired between proactive refresh and the actual call,
            # or the server rotated secrets. Try once more.
            if use_agent and self.access_token:
                if self.mint_agent_token():
                    return self._request(
                        method, path,
                        use_agent=True, params=params, json=json,
                        retry_on_401=False,
                    )
            elif self.refresh_token_value:
                if self.refresh_access():
                    return self._request(
                        method, path,
                        use_agent=False, params=params, json=json,
                        retry_on_401=False,
                    )

        if 200 <= resp.status_code < 300:
            if resp.status_code == 204 or not resp.content:
                return True, None, None
            try:
                return True, resp.json(), None
            except ValueError:
                return True, resp.text, None

        try:
            body = resp.json()
            msg = body.get("detail") or body.get("message") or f"HTTP {resp.status_code}"
        except Exception:
            msg = f"HTTP {resp.status_code}"
        logger.warning("api_non_2xx %s %s -> %s %s", method, path, resp.status_code, msg)
        return False, None, msg

    # =============================================================== auth
    def login(self, username: str, password: str) -> ApiResult:
        ok, data, err = self._request(
            "POST", "/api/v1/auth/login",
            json={"username": username, "password": password},
            retry_on_401=False,
        )
        if not ok or not data:
            return ok, data, err

        self.set_access_token(
            data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=3600,  # backend default jwt_access_ttl_minutes=60
        )
        self.tenant_id = data.get("tenant_id")
        self.shop_id = data.get("shop_id")
        self.shop_name = data.get("shop_name")
        self.username = data.get("username")

        # Mint the agent token right away so WS can connect and the printer
        # manager can fetch presigned URLs.
        self.mint_agent_token()
        logger.info("login ok user=%s tenant=%s", self.username, self.tenant_id)
        return True, data, None

    def refresh_access(self) -> bool:
        if not self.refresh_token_value:
            return False
        ok, data, _err = self._request(
            "POST", "/api/v1/auth/refresh",
            json={"refresh_token": self.refresh_token_value},
            retry_on_401=False,
        )
        if ok and data and data.get("access_token"):
            self.set_access_token(
                data["access_token"],
                refresh_token=self.refresh_token_value,
                expires_in=3600,
            )
            return True
        return False

    def mint_agent_token(self) -> bool:
        if not self.access_token:
            return False
        ok, data, _err = self._request(
            "POST", "/api/v1/auth/agent/from-session",
            retry_on_401=False,
        )
        if ok and data and data.get("access_token"):
            self.set_agent_token(
                data["access_token"],
                expires_in=data.get("expires_in"),
            )
            if not self.tenant_id:
                self.tenant_id = data.get("tenant_id")
            logger.info("agent token minted tenant=%s", self.tenant_id)
            return True
        return False

    def logout(self) -> ApiResult:
        ok, data, err = self._request("POST", "/api/v1/auth/logout", retry_on_401=False)
        self.clear_session()
        return ok, data, err

    # =========================================================== dashboard
    def get_dashboard(self, period: str = "today", recent_limit: int = 10) -> ApiResult:
        return self._request(
            "GET", "/api/v1/dashboard",
            params={"period": period, "recent_limit": recent_limit},
        )

    # ================================================================ jobs
    def list_jobs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ApiResult:
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        return self._request("GET", "/api/v1/jobs", params=params)

    def get_job(self, job_id: str) -> ApiResult:
        return self._request("GET", f"/api/v1/jobs/{job_id}")

    def get_job_file_url(self, job_id: str, expires_in: int = 1800) -> ApiResult:
        """Agent-only. Returns a short-lived presigned GET URL."""
        return self._request(
            "GET", f"/api/v1/jobs/{job_id}/file-url",
            use_agent=True,
            params={"expires_in": expires_in},
        )

    def download_job_file(
        self,
        job_id: str,
        output_path: str,
        progress_callback=None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Resolve a presigned URL then stream the file to `output_path`."""
        ok, data, err = self.get_job_file_url(job_id)
        if not ok or not data or not data.get("url"):
            return False, None, err or "No download URL"
        url = data["url"]
        try:
            with requests.get(url, stream=True, timeout=60) as r:
                if r.status_code != 200:
                    return False, None, f"HTTP {r.status_code} fetching presigned URL"
                total = int(r.headers.get("Content-Length", 0))
                downloaded = 0
                with open(output_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total:
                            progress_callback(downloaded, total)
            return True, output_path, None
        except requests.exceptions.Timeout:
            return False, None, "File download timeout"
        except requests.exceptions.ConnectionError:
            return False, None, "Cannot reach object storage"
        except Exception as exc:
            logger.exception("download_job_file failed job=%s", job_id)
            return False, None, str(exc)

    def update_job_status(
        self,
        job_id: str,
        status: str,
        *,
        error_message: Optional[str] = None,
        printer_name: Optional[str] = None,
        printed_pages: Optional[int] = None,
    ) -> ApiResult:
        payload: Dict[str, Any] = {"status": status}
        if error_message is not None:
            payload["error_message"] = error_message
        if printer_name is not None:
            payload["printer_name"] = printer_name
        if printed_pages is not None:
            payload["printed_pages"] = printed_pages
        return self._request("PATCH", f"/api/v1/jobs/{job_id}/status", json=payload)

    # =============================================================== shops
    def _tenant_path(self, tail: str) -> str:
        return f"/api/v1/shops/{self.tenant_id}{tail}"

    def get_shop_info(self) -> ApiResult:
        if not self.tenant_id:
            return False, None, "Not logged in"
        return self._request("GET", self._tenant_path("/info"))

    def update_shop_info(self, **fields: Any) -> ApiResult:
        if not self.tenant_id:
            return False, None, "Not logged in"
        return self._request("PUT", self._tenant_path("/info"), json=fields)

    def get_pricing(self) -> ApiResult:
        if not self.tenant_id:
            return False, None, "Not logged in"
        return self._request("GET", self._tenant_path("/pricing"))

    def update_pricing(self, pricing: Dict[str, float]) -> ApiResult:
        if not self.tenant_id:
            return False, None, "Not logged in"
        return self._request("PUT", self._tenant_path("/pricing"), json=pricing)

    # ============================================================ printers
    def list_printers(self) -> ApiResult:
        return self._request("GET", "/api/v1/printers")

    def register_printer(
        self,
        printer_id: str,
        printer_name: str,
        *,
        is_default: bool = False,
        supports_color: bool = False,
        supports_duplex: bool = False,
    ) -> ApiResult:
        return self._request(
            "POST", "/api/v1/printers",
            json={
                "printer_id": printer_id,
                "printer_name": printer_name,
                "is_default": is_default,
                "capabilities": {
                    "supports_color": supports_color,
                    "supports_duplex": supports_duplex,
                },
            },
        )

    def delete_printer(self, printer_id: str) -> ApiResult:
        return self._request("DELETE", f"/api/v1/printers/{printer_id}")

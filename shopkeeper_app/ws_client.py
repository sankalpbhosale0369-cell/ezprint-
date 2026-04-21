"""Native WebSocket client for the Windows shopkeeper agent.

Connects to `ws[s]://.../ws/agent?token=<agent JWT>` on the FastAPI
backend and exposes inbound events as Qt signals. Replaces the old
`shopkeeper_app/socketio_client.py` + `shared/thread_safe_socketio_client.py`.

Runs the I/O loop on a daemon thread; emits Qt signals so UI slots run on
the main thread. Reconnect strategy: exponential backoff (1s -> 30s),
infinite retries; on a 1008 close (auth failure) we re-mint the agent
token through `ApiClient` before the next attempt.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

try:
    from websocket import WebSocketApp, WebSocketException  # websocket-client package
except ImportError:  # pragma: no cover - surfaced at runtime on stripped builds
    WebSocketApp = None  # type: ignore[assignment]
    WebSocketException = Exception  # type: ignore[assignment, misc]

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import EZPRINT_WS_URL  # noqa: E402

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- signals
# We build a tiny Qt signal bridge but keep all pure-Python logic callable
# without Qt. Unit tests use `WsClient._dispatch(...)` directly.
try:
    from PyQt5.QtCore import QObject, pyqtSignal

    class _Signals(QObject):
        connected = pyqtSignal(str)        # tenant_id
        disconnected = pyqtSignal(str)     # reason
        new_job = pyqtSignal(dict)
        job_status = pyqtSignal(dict)
        raw_event = pyqtSignal(dict)

except ImportError:  # pragma: no cover
    # Allow importing the module in headless test environments.
    class _StubSignal:
        def __init__(self) -> None:
            self._slots: List[Callable[..., None]] = []

        def connect(self, slot: Callable[..., None]) -> None:
            self._slots.append(slot)

        def emit(self, *args: Any) -> None:
            for s in self._slots:
                try:
                    s(*args)
                except Exception:
                    logger.exception("stub signal slot failed")

    class _Signals:  # type: ignore[no-redef]
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.connected = _StubSignal()
            self.disconnected = _StubSignal()
            self.new_job = _StubSignal()
            self.job_status = _StubSignal()
            self.raw_event = _StubSignal()


# ----------------------------------------------------------------- constants
MIN_BACKOFF_SECS = 1.0
MAX_BACKOFF_SECS = 30.0
PING_INTERVAL_SECS = 30
CLOSE_CODE_POLICY_VIOLATION = 1008


class WsClient:
    """Thread-safe WebSocket agent.

    Parameters
    ----------
    api_client:
        A logged-in `ApiClient` instance. Provides `agent_token` and the
        `mint_agent_token()` helper used to recover from auth failures.
    url:
        Override for the WebSocket URL (default from `shared.config.EZPRINT_WS_URL`).
    """

    def __init__(self, api_client: Any, url: Optional[str] = None) -> None:
        self.api_client = api_client
        self.url = (url or EZPRINT_WS_URL).rstrip("/")

        self.signals = _Signals()
        self.new_job = self.signals.new_job
        self.job_status = self.signals.job_status
        self.connected = self.signals.connected
        self.disconnected = self.signals.disconnected
        self.raw_event = self.signals.raw_event

        self._ws: Optional[WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._ping_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._is_connected = False
        self._backoff = MIN_BACKOFF_SECS

    # ------------------------------------------------------------- lifecycle
    def is_connected(self) -> bool:
        """Callable (historical dashboard usage) that also works as a truthy check."""
        return self._is_connected

    def start(self) -> None:
        """Spawn the background reconnect loop. Safe to call more than once."""
        if WebSocketApp is None:
            raise RuntimeError(
                "websocket-client is not installed. "
                "Add it to the client requirements."
            )
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="ezprint-ws", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the loop to exit and close the socket."""
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None

    # -------------------------------------------------------------- sending
    def _send(self, type_: str, data: Optional[Dict[str, Any]] = None) -> bool:
        ws = self._ws
        if ws is None or not self._is_connected:
            return False
        try:
            ws.send(json.dumps({"type": type_, "data": data or {}}))
            return True
        except Exception:
            logger.exception("ws send failed type=%s", type_)
            return False

    def report_print_started(self, job_id: str) -> bool:
        return self._send("print_started", {"job_id": job_id})

    def report_print_completed(self, job_id: str) -> bool:
        return self._send("print_completed", {"job_id": job_id})

    def report_print_failed(self, job_id: str, error_message: Optional[str] = None) -> bool:
        payload: Dict[str, Any] = {"job_id": job_id}
        if error_message:
            payload["error_message"] = error_message
        return self._send("print_failed", payload)

    def send_printer_heartbeat(self, printers: List[Dict[str, Any]]) -> bool:
        """`printers` items: {printer_id, is_online?}"""
        return self._send("printer_heartbeat", {"printers": printers})

    # ------------------------------------------------------------- receiving
    def _dispatch(self, message: Dict[str, Any]) -> None:
        """Pure-Python, testable message router."""
        kind = message.get("type")
        data = message.get("data") or {}
        try:
            if kind == "registered":
                self._is_connected = True
                self._backoff = MIN_BACKOFF_SECS
                tenant_id = message.get("tenant_id") or data.get("tenant_id") or ""
                self.connected.emit(str(tenant_id))
            elif kind == "new_job":
                self.new_job.emit(data)
            elif kind == "job_status":
                self.job_status.emit(data)
            elif kind == "pong":
                pass  # keepalive
            else:
                logger.debug("ws unknown type=%s", kind)
            self.raw_event.emit(message)
        except Exception:
            logger.exception("ws dispatch failed type=%s", kind)

    def _on_message(self, _ws: Any, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("ws non-json frame: %s", raw[:120])
            return
        if not isinstance(message, dict):
            return
        self._dispatch(message)

    def _on_error(self, _ws: Any, error: Any) -> None:
        logger.info("ws error: %s", error)

    def _on_close(self, _ws: Any, code: Optional[int], reason: Optional[str]) -> None:
        was_connected = self._is_connected
        self._is_connected = False
        reason_str = f"{code} {reason}" if code is not None else (reason or "closed")
        logger.info("ws closed: %s", reason_str)
        if was_connected:
            self.disconnected.emit(reason_str)
        if code == CLOSE_CODE_POLICY_VIOLATION:
            # Auth failure -> try to re-mint before the next attempt.
            try:
                self.api_client.mint_agent_token()
            except Exception:
                logger.exception("post-1008 mint_agent_token failed")

    def _on_open(self, _ws: Any) -> None:
        logger.info("ws tcp connected; awaiting 'registered'")

    # ---------------------------------------------------------------- loop
    def _connect_url(self) -> Optional[str]:
        token = getattr(self.api_client, "agent_token", None)
        if not token and hasattr(self.api_client, "mint_agent_token"):
            try:
                self.api_client.mint_agent_token()
                token = getattr(self.api_client, "agent_token", None)
            except Exception:
                logger.exception("mint_agent_token before connect failed")
        if not token:
            return None
        sep = "&" if "?" in self.url else "?"
        return f"{self.url}{sep}token={token}"

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            connect_url = self._connect_url()
            if not connect_url:
                logger.info("ws: no agent token, retrying in %.1fs", self._backoff)
                if self._stop.wait(self._backoff):
                    return
                self._backoff = min(self._backoff * 2, MAX_BACKOFF_SECS)
                continue

            logger.info("ws connecting: %s", self.url)
            try:
                self._ws = WebSocketApp(
                    connect_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                # Blocks until socket closes. ping_interval/timeout gives us
                # dead-peer detection in addition to our own `ping` events.
                self._ws.run_forever(ping_interval=PING_INTERVAL_SECS, ping_timeout=10)
            except WebSocketException:
                logger.exception("ws run_forever raised")
            except Exception:
                logger.exception("ws loop crashed")
            finally:
                self._ws = None
                self._is_connected = False

            if self._stop.is_set():
                return

            logger.info("ws reconnect in %.1fs", self._backoff)
            if self._stop.wait(self._backoff):
                return
            self._backoff = min(self._backoff * 2, MAX_BACKOFF_SECS)

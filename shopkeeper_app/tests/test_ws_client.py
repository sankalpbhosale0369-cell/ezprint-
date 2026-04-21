"""Unit tests for shopkeeper_app.ws_client.WsClient.

We can't spin up a real WebSocket without pulling in the Qt event loop,
so these tests exercise the pure-Python `_dispatch` path (which emits the
Qt signals) and confirm outbound `_send(...)` calls hit the underlying
WebSocketApp exactly once with well-formed JSON.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shopkeeper_app.ws_client import WsClient  # noqa: E402


class _FakeApiClient:
    def __init__(self, token: str = "G1") -> None:
        self.agent_token = token

    def mint_agent_token(self) -> bool:
        return bool(self.agent_token)


class TestWsClient(unittest.TestCase):
    def setUp(self) -> None:
        self.client = WsClient(_FakeApiClient(), url="ws://backend.test/ws/agent")
        self.client._ws = MagicMock()
        self.client._is_connected = True

    # ---------------------------------------------------------- dispatch
    def test_dispatch_registered_fires_connected_signal(self) -> None:
        seen = []
        self.client.connected.connect(lambda tid: seen.append(tid))
        self.client._is_connected = False  # simulate pre-registered state
        self.client._dispatch({"type": "registered", "tenant_id": "tid-1"})
        self.assertEqual(seen, ["tid-1"])
        self.assertTrue(self.client.is_connected())

    def test_dispatch_new_job_fires_signal_with_payload(self) -> None:
        seen = []
        self.client.new_job.connect(seen.append)
        self.client._dispatch({
            "type": "new_job",
            "data": {"job_id": "j1", "download_url": "https://x"},
        })
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["job_id"], "j1")

    def test_dispatch_job_status_fires_signal(self) -> None:
        seen = []
        self.client.job_status.connect(seen.append)
        self.client._dispatch({
            "type": "job_status",
            "data": {"job_id": "j1", "status": "Completed"},
        })
        self.assertEqual(seen[0]["status"], "Completed")

    def test_dispatch_unknown_type_does_not_explode(self) -> None:
        self.client._dispatch({"type": "surprise", "data": {}})

    # ---------------------------------------------------------- outbound
    def test_report_print_started_sends_frame(self) -> None:
        self.client.report_print_started("j1")
        self.client._ws.send.assert_called_once()
        payload = json.loads(self.client._ws.send.call_args[0][0])
        self.assertEqual(payload, {"type": "print_started", "data": {"job_id": "j1"}})

    def test_report_print_failed_includes_error_message(self) -> None:
        self.client.report_print_failed("j1", "paper jam")
        payload = json.loads(self.client._ws.send.call_args[0][0])
        self.assertEqual(payload["type"], "print_failed")
        self.assertEqual(payload["data"], {"job_id": "j1", "error_message": "paper jam"})

    def test_heartbeat_sends_printer_list(self) -> None:
        self.client.send_printer_heartbeat([{"printer_id": "HP", "is_online": True}])
        payload = json.loads(self.client._ws.send.call_args[0][0])
        self.assertEqual(payload["type"], "printer_heartbeat")
        self.assertEqual(payload["data"]["printers"][0]["printer_id"], "HP")

    def test_send_returns_false_when_disconnected(self) -> None:
        self.client._is_connected = False
        self.assertFalse(self.client.report_print_completed("j1"))


if __name__ == "__main__":
    unittest.main()

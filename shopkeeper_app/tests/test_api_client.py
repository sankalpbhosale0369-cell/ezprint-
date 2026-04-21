"""Unit tests for shopkeeper_app.api_client.ApiClient.

These tests patch `requests.request` so they run offline. They focus on
behaviour that's easy to regress: login happy-path, access-token auto
refresh on 401, agent-token minting, PATCH status routing, and the
`file-url` 410 (asset cleaned up) path.
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shopkeeper_app.api_client import ApiClient  # noqa: E402


def _mock_response(status_code: int, json_payload=None, content: bytes = b""):
    r = MagicMock()
    r.status_code = status_code
    r.content = content or (b"{}" if json_payload is None else b"{}")
    r.json.return_value = json_payload if json_payload is not None else {}
    r.text = ""
    r.headers = {}
    return r


class TestApiClient(unittest.TestCase):
    def setUp(self) -> None:
        self.client = ApiClient(base_url="http://backend.test")

    def test_login_sets_tokens_and_mints_agent(self) -> None:
        responses = [
            _mock_response(200, {
                "access_token": "A1",
                "refresh_token": "R1",
                "tenant_id": "tid-1",
                "shop_id": "shop-1",
                "shop_name": "Test Shop",
                "username": "alice",
                "email": "a@b.c",
            }),
            _mock_response(200, {
                "access_token": "G1",
                "tenant_id": "tid-1",
                "expires_in": 3600,
            }),
        ]
        with patch("shopkeeper_app.api_client.requests.request", side_effect=responses):
            ok, data, err = self.client.login("alice", "secret")
        self.assertTrue(ok, err)
        self.assertEqual(self.client.access_token, "A1")
        self.assertEqual(self.client.refresh_token_value, "R1")
        self.assertEqual(self.client.agent_token, "G1")
        self.assertEqual(self.client.tenant_id, "tid-1")

    def test_update_status_retries_after_401(self) -> None:
        self.client.set_access_token("expired", refresh_token="R1", expires_in=3600)
        call_log = []

        def fake_request(method, url, **kwargs):
            call_log.append((method, url))
            # First PATCH -> 401, then refresh returns new access, then PATCH -> 200.
            if url.endswith("/api/v1/jobs/j1/status"):
                if len([c for c in call_log if c[1].endswith("/status")]) == 1:
                    return _mock_response(401, {"detail": "expired"})
                return _mock_response(200, {"job_id": "j1", "status": "Completed"})
            if url.endswith("/api/v1/auth/refresh"):
                return _mock_response(200, {"access_token": "A2"})
            raise AssertionError(f"unexpected URL {url}")

        with patch("shopkeeper_app.api_client.requests.request", side_effect=fake_request):
            ok, data, err = self.client.update_job_status("j1", "Completed")

        self.assertTrue(ok, err)
        self.assertEqual(self.client.access_token, "A2")
        self.assertEqual(
            [c[1].rsplit("/", 3)[-3:] for c in call_log],
            [
                ["jobs", "j1", "status"],
                ["v1", "auth", "refresh"],
                ["jobs", "j1", "status"],
            ],
        )

    def test_file_url_returns_gone_after_cleanup(self) -> None:
        self.client.set_agent_token("G1", expires_in=3600)
        with patch("shopkeeper_app.api_client.requests.request",
                   return_value=_mock_response(410, {"detail": "asset removed"})):
            ok, _data, err = self.client.get_job_file_url("j1")
        self.assertFalse(ok)
        self.assertIn("asset", (err or ""))

    def test_mint_agent_token_uses_access_header(self) -> None:
        self.client.set_access_token("A1", refresh_token="R1", expires_in=3600)
        captured = {}

        def fake_request(method, url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return _mock_response(200, {
                "access_token": "AGENT-NEW",
                "tenant_id": "tid-1",
                "expires_in": 3600,
            })

        with patch("shopkeeper_app.api_client.requests.request", side_effect=fake_request):
            self.assertTrue(self.client.mint_agent_token())

        self.assertEqual(captured["headers"].get("Authorization"), "Bearer A1")
        self.assertEqual(self.client.agent_token, "AGENT-NEW")


if __name__ == "__main__":
    unittest.main()

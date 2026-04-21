"""End-to-end smoke test for a running ezprint-backend stack.

Assumes two tenants have already been created (via scripts/create_tenant.py).

    python -m scripts.smoke_test \
        --api http://localhost:8000 \
        --slug demo-shop \
        --username demo --password change-me \
        --agent-token <provisioning token>

Flow:
    1. shop login
    2. customer upload-token
    3. create job -> presigned PUT
    4. PUT dummy file to MinIO via presigned URL
    5. finalize -> gets classified + priced
    6. agent exchange + agent session
    7. agent file-url + GET the file back
    8. agent status update to Completed
"""
from __future__ import annotations

import argparse
import io
import json
import sys

import httpx


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--slug", required=True)
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--agent-token", required=True)
    args = p.parse_args()

    client = httpx.Client(base_url=args.api, timeout=30)

    # 1. shopkeeper login
    r = client.post("/api/v1/auth/login", json={"username": args.username, "password": args.password})
    r.raise_for_status()
    shop_login = r.json()
    print("shop login ok:", shop_login["tenant_id"])

    # 2. customer upload token
    r = client.get(f"/api/v1/auth/upload/{args.slug}")
    r.raise_for_status()
    upload_info = r.json()
    print("upload token ok:", upload_info["expires_in"], "seconds")
    upload_headers = {"Authorization": f"Bearer {upload_info['upload_token']}"}

    # 3. create job
    r = client.post(
        "/api/v1/jobs",
        headers=upload_headers,
        json={
            "filename": "hello.txt",
            "file_type": "txt",
            "file_size": 13,
            "copies": 1,
            "color_mode": "Black & White",
            "print_side": "Single",
        },
    )
    r.raise_for_status()
    job = r.json()
    print("job created:", job["job_id"])

    # 4. PUT file via presigned URL
    put_resp = httpx.put(job["upload_url"], content=b"hello, world!", timeout=30)
    put_resp.raise_for_status()
    print("uploaded via presigned URL")

    # 5. finalize
    r = client.post(f"/api/v1/jobs/{job['job_id']}/finalize", headers=upload_headers)
    r.raise_for_status()
    print("finalize ok:", r.json())

    # 6. agent session
    r = client.post("/api/v1/auth/agent/session", json={"provisioning_token": args.agent_token})
    r.raise_for_status()
    agent_info = r.json()
    agent_headers = {"Authorization": f"Bearer {agent_info['access_token']}"}
    print("agent session ok:", agent_info["tenant_id"])

    # 7. agent file-url
    r = client.get(f"/api/v1/jobs/{job['job_id']}/file-url", headers=agent_headers)
    r.raise_for_status()
    file_url = r.json()["url"]
    dl = httpx.get(file_url, timeout=30)
    dl.raise_for_status()
    print("agent downloaded:", len(dl.content), "bytes")

    # 8. agent status updates: Queued -> Printing -> Completed
    for next_status in ("Printing", "Completed"):
        r = client.patch(
            f"/api/v1/jobs/{job['job_id']}/status",
            headers=agent_headers,
            json={"status": next_status},
        )
        r.raise_for_status()
        print("status updated:", r.json()["status"])

    # 9. verify immediate cleanup — file-url must now return 410 Gone
    r = client.get(f"/api/v1/jobs/{job['job_id']}/file-url", headers=agent_headers)
    assert r.status_code == 410, f"expected 410 after cleanup, got {r.status_code}: {r.text}"
    print("assets cleaned up (file-url -> 410 as expected)")

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPStatusError as exc:
        print("HTTP error:", exc.response.status_code, exc.response.text, file=sys.stderr)
        raise SystemExit(1)

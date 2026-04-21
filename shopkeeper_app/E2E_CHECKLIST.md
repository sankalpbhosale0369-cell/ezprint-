# Shopkeeper agent E2E checklist

Exercises the refactored desktop agent (`shopkeeper_app`) against a local
`ezprint-backend` stack. The goal is to confirm that the client talks to
the new backend over HTTPS + WebSocket only — no Postgres / Cloudinary /
Socket.IO left in the loop.

## 0. Prerequisites

- Docker Desktop running
- `uv` installed (`pipx install uv` if missing)
- Windows box (or a second shell with `PyQt5` installed) for the agent GUI
- A copy of `ezprint-backend/.env.example` saved as `.env` with sensible
  dev values (see repo root for defaults)

## 1. Bring the backend up

```bash
cd ezprint-backend
docker compose up -d --build
docker compose ps                       # api, worker, postgres, redis, minio healthy
curl -fsS http://localhost:8000/healthz # {"status":"ok"}
```

Seed a shop + shopkeeper the first time:

```bash
docker compose exec api python -m app.scripts.seed_demo
# note the printed shopkeeper username + password
```

## 2. Smoke-test the HTTP surface

```bash
# Login → access + refresh tokens
curl -sS -X POST http://localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"demo","password":"demo"}' | tee /tmp/login.json

ACCESS=$(jq -r .access_token /tmp/login.json)

# Mint an agent token (what the desktop .exe does on startup)
curl -sS -X POST http://localhost:8000/api/v1/auth/agent/from-session \
  -H "authorization: Bearer $ACCESS" | jq .

# Dashboard KPIs
curl -sS "http://localhost:8000/api/v1/dashboard?period=today" \
  -H "authorization: Bearer $ACCESS" | jq .
```

All three should return 200. If `/agent/from-session` 401s, the access
token was not minted with `typ=access` — check `app/api/v1/auth.py`.

## 3. Run the agent locally (no PyInstaller)

```bash
cd shopkeeper_app
uv venv
uv pip install -r requirements-client.txt
export EZPRINT_API_BASE_URL=http://localhost:8000
# EZPRINT_WS_URL is auto-derived to ws://localhost:8000/ws/agent
python main.py
```

Walk through the following in the GUI:

- [ ] **Login tab** — sign in with the seeded shopkeeper. Auth should
      succeed without hitting any local database.
- [ ] **Dashboard tab** — KPI tiles populate from
      `GET /api/v1/dashboard?period=today` and `period=month`. The
      "Recent jobs" table mirrors the API response.
- [ ] **Printers tab** — local Windows printers are discovered and
      POSTed to `/api/v1/printers`. Deleting a printer row issues a
      DELETE and removes it from the server list (`GET /api/v1/printers`).
- [ ] **Pricing tab** — load/save round-trip via
      `GET/PUT /api/v1/shops/{tenant_id}/pricing`. Old `ShopPricing`
      SQLAlchemy path must **not** be used.

Tail the backend log in another shell: `docker compose logs -f api`.
You should see a WebSocket upgrade to `/ws/agent?token=...` shortly
after login and periodic `printer_heartbeat` frames.

## 4. End-to-end print job

1. Open the customer upload page (`/u/{shop_slug}` served by the web
   interface or direct API calls — out of scope for the agent repo).
2. Upload a small PDF. The customer flow creates a job, finalizes it,
   and the backend publishes `new_job` on Redis.
3. In the agent GUI:
   - [ ] A toast / list row appears within a second or two — confirms
         the WS push arrived.
   - [ ] The agent fetches the file via
         `GET /api/v1/jobs/{id}/file-url` (presigned MinIO URL) and
         downloads it locally.
   - [ ] Print is dispatched to the selected Windows printer.
   - [ ] Status transitions: `Queued → Printing → Completed` arrive in
         the dashboard (WS `job_status` events) without a page refresh.
4. Confirm server-side cleanup: the MinIO object under
   `tenants/{tenant_id}/jobs/{job_id}/...` is deleted within the
   configured TTL (see `worker` container logs).

## 5. Failure paths worth trying

- [ ] **Expired access token** — manually set
      `self.client._access_expiry_ts` to a past time (debug build) or
      wait it out; the next HTTP call should transparently refresh.
- [ ] **Backend restart** — `docker compose restart api`. The WS
      client should reconnect within ~10 s (exponential backoff).
- [ ] **Invalid agent token** — delete `session.json` mid-run; WS
      should close with `1008`, the client re-mints via
      `/auth/agent/from-session`, and reconnects.
- [ ] **Cleaned-up asset** — request `file-url` for an old completed
      job; expect HTTP 410 and a user-facing "file no longer available"
      toast rather than a crash.

## 6. Tests

```bash
ezprint-backend/.venv/bin/python -m pytest shopkeeper_app/tests -q
# 12 passed
```

If any of the above fail, capture:

- `docker compose logs api` around the timestamp,
- the agent stderr (or the log file in `%APPDATA%/EzPrint/`),
- the failing request in browser devtools / `curl -v`,

and file against the relevant plan item before continuing.

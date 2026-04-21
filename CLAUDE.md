# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EzPrint is a SaaS printing platform that lets customers upload documents and have
them printed at local print shops. The codebase is now split into two services:

1. **`ezprint-backend/`** — FastAPI (Uvicorn) + PostgreSQL + Redis + MinIO.
   Single source of truth for shops, jobs, pricing, files, auth. Multi-tenant.
2. **`shopkeeper_app/`** — PyQt5 Windows desktop agent. Talks to the backend
   over HTTPS (`/api/v1/*`) and a native WebSocket (`/ws/agent`). Owns local
   printer discovery and Windows print jobs.

Supporting code lives in `shared/` (file processing, auto-update, Windows
printing helpers) and is consumed by the desktop agent only.

The legacy Flask app (`web_interface/`), Flask-SocketIO, eventlet,
Cloudinary, and the root Dockerfile/`start.py` entry point have been
removed — everything they did now lives inside `ezprint-backend/`.

## Architecture

### Services

- **Backend** (`ezprint-backend/`)
  - FastAPI + Uvicorn, SQLAlchemy 2.x + Alembic, Postgres
  - Redis pub/sub drives WebSocket fan-out to agents
  - MinIO (S3-compatible) stores customer uploads; presigned URLs handed to the agent
  - Docker Compose spins up the full stack (`docker compose up` in
    `ezprint-backend/`); see `ezprint-backend/README.md`
- **Agent** (`shopkeeper_app/`)
  - `api_client.py` — `requests`-backed REST client, handles access/refresh/agent
    tokens with automatic refresh on 401
  - `ws_client.py` — `websocket-client` background thread bridged into Qt signals
  - `printer_manager.py` — Windows printing; downloads job files via presigned URLs
  - `dashboard.py` — PyQt5 UI. Data layer is now API-only; a small amount of
    legacy SQLite (`shared/database.py`) is still used for historical job views
    and is being phased out
- **Shared** (`shared/`) — file processing, auto-update, Windows print helpers

### Auth

Three JWT types, all minted by the backend:

- `access` / `refresh` — shopkeeper UI calls REST endpoints as a user
- `agent` — the .exe uses this for `/ws/agent` and `GET /jobs/{id}/file-url`

After login, the client calls `POST /api/v1/auth/agent/from-session` with the
access token to mint an agent JWT (no provisioning token needed).

## Development Commands

### Backend

```bash
cd ezprint-backend
docker compose up -d --build        # Postgres + Redis + MinIO + api + worker
docker compose logs -f api          # follow API logs
curl -fsS http://localhost:8000/healthz

# One-time seed (demo shop + shopkeeper)
docker compose exec api python -m app.scripts.seed_demo
```

### Agent (from a dev box)

```bash
cd shopkeeper_app
uv venv && uv pip install -r requirements-client.txt
export EZPRINT_API_BASE_URL=http://localhost:8000
python main.py
```

`EZPRINT_WS_URL` is derived automatically from the API base URL. The
desktop agent expects the backend to be reachable.

### Tests

```bash
ezprint-backend/.venv/bin/python -m pytest shopkeeper_app/tests -q   # client unit tests
cd ezprint-backend && pytest -q                                       # backend suite
```

### Manual E2E

See `shopkeeper_app/E2E_CHECKLIST.md` for a step-by-step walkthrough
against the local docker compose stack.

## Environment Configuration

The root `shared/config.py` is now **agent-only** and reads:

```bash
EZPRINT_API_BASE_URL=http://localhost:8000   # FastAPI backend (required in prod)
EZPRINT_WS_URL=ws://localhost:8000/ws/agent  # optional override; auto-derived
EZPRINT_LICENSE_ENABLED=false                # licensing feature flag
DATABASE_URL=sqlite:///fallback.db           # local legacy cache (shrinking)
UPDATE_CHECK_URL / UPDATE_DOWNLOAD_URL       # auto-update channel for the .exe
SHOP_API_TOKEN                               # optional Bearer for update server
GHOSTSCRIPT_EXE                              # absolute path for PDF→PS (optional)
```

Backend configuration (`ezprint-backend/.env`) is separate — see
`ezprint-backend/.env.example`.

## Critical Patterns

### 1. Data access

- The agent **must** go through `ApiClient` for anything tenant-scoped
  (jobs, pricing, shop info, printers, dashboard KPIs). No new DB calls
  should be added to `shared/database.py`; treat it as a legacy cache
  that will be deleted once `dashboard.py` is fully migrated.
- The backend owns all multi-tenant queries and enforces tenant isolation
  via `require_shopkeeper` / `require_shopkeeper_or_agent` dependencies.

### 2. File pipeline

Customer upload flow (backend-owned):

1. Customer `POST /api/v1/jobs` → backend creates job in `AwaitingUpload`
2. Client uploads file directly to MinIO via presigned PUT
3. Customer `POST /api/v1/jobs/{id}/finalize` → backend flips to `Queued`
4. Backend publishes `new_job` on Redis → WebSocket fan-out
5. Agent receives `new_job`, calls `GET /api/v1/jobs/{id}/file-url` for a
   presigned GET, downloads to temp, prints
6. Agent reports `print_started` / `print_completed` / `print_failed`
   over WS (REST PATCH fallback); state machine enforces valid transitions
7. On terminal state the backend deletes the MinIO object; subsequent
   `file-url` requests return `410 Gone`

### 3. Real-time communication

- **Transport**: native WebSocket at `/ws/agent?token=<agent_jwt>`
- **Frames** (JSON): inbound `registered`, `new_job`, `job_status`, `pong`;
  outbound `ping`, `printer_heartbeat`, `print_started`, `print_completed`,
  `print_failed`
- **Fan-out**: backend subscribes to Redis, pushes per-tenant messages
- **Reconnect**: exponential backoff on the client; re-mint agent token on
  `1008` close

### 4. Job state machine

```
AwaitingUpload → Queued → Printing → Completed
                                   → Failed
                         → Cancelled
```

Only legal transitions are accepted. On any terminal state, the
cleanup worker (`ezprint-backend/app/workers/cleanup.py`) removes the
MinIO object.

### 5. Error handling

- Backend: FastAPI exception handlers map domain errors to HTTP codes
- Agent: `shared/global_error_handler.py` provides `safe_execute`,
  `safe_ui_action`, and `safe_database_action` decorators; all failures
  log to `logs/ezprint.log`

## Common Pitfalls

1. **Tokens**: three of them live in-process. Don't send the agent token
   to `/api/v1/*` routes that expect `access` — the server will 401.
2. **Presigned URLs expire** (default 15 min). Re-request on failure.
3. **Tenant isolation**: every backend query must be filtered by
   `principal.tenant_id`; never trust client-supplied `tenant_id`.
4. **Do not add SocketIO/Flask/eventlet deps.** The project is FastAPI +
   native WebSocket only.
5. **Windows printing**: `pywin32` is a no-op on macOS/Linux — guard with
   `sys.platform.startswith('win')`.
6. **Legacy DB**: if you see `SessionLocal` or `PrintJob` imports in
   `dashboard.py`, they are on the removal list; do not extend them.
7. **ApiClient API surface** (agent-side):
   - Access token: `api_client.access_token` (not `session_token`)
   - Refresh: `api_client.refresh_access()` returns `bool` (not `refresh_token()`)
   - Agent token: `api_client.agent_token` (public attribute, not `_agent_token`)
   - WsClient has `report_print_started/completed/failed(job_id)` — there is NO
     `report_job_status()` method. Map backend statuses before calling.
8. **Local SQLite upsert**: when a `new_job` WS event arrives, the job only
   exists on the backend. Upsert it into local `PrintJob` before calling
   `load_print_jobs()` or `check_and_print_pending_jobs()`. Same applies to
   `job_status` events — update local DB status so the next poll doesn't revert.
9. **WS signal wiring**: connect only `ws_client.raw_event` to the translate
   handler. Do NOT also connect `ws_client.new_job` / `ws_client.job_status`
   directly — that double-fires every event.
10. **GDI fallback receives pre-processed PDF**: when
    `_print_to_network_printer_gdi_fallback` is called from
    `_print_to_network_printer`, `file_path` is already the nup/page-range PDF
    produced by `generate_final_print_pdf`. Do NOT call it again inside the
    fallback — that double-processes layout and page ranges.

## Key Files Reference

**Backend** (`ezprint-backend/`)

- `app/api/v1/auth.py` — login, refresh, agent-token minting
- `app/api/v1/jobs.py` — create/finalize/list/status + `file-url`
- `app/api/v1/dashboard.py` — KPIs + recent jobs
- `app/api/v1/shops.py` / `printers.py` — shop info, pricing, printer registry
- `app/workers/cleanup.py` — terminal-state MinIO cleanup worker
- `app/tenancy/deps.py` — `require_shopkeeper`, `require_shopkeeper_or_agent`

**Agent** (`shopkeeper_app/`)

- `api_client.py` — REST client (access/refresh/agent tokens); `refresh_access()` + `mint_agent_token()` for token renewal
- `ws_client.py` — native WebSocket client with Qt signal bridge; `report_print_started/completed/failed(job_id)`
- `auth.py` — API facade; `resume_session()` refreshes tokens + mints agent JWT on startup; persists `session.json`
- `dashboard.py` — PyQt5 UI; `_sync_jobs_from_api()` polls backend; `_poll_and_sync()` drives fallback timer; `refresh_session_token()` renews all three JWTs every 30 min
- `printer_manager.py` — Windows print dispatch, heartbeats; `_ensure_local_file(path, job_id)` downloads via presigned URL
- `tests/` — unit tests for `api_client` and `ws_client`
- `E2E_CHECKLIST.md` — manual verification steps

**Shared**

- `shared/config.py` — agent config only (URLs, auto-update, printing knobs)
- `shared/file_processor.py` — PDF/n-up generation, color classification
- `shared/auto_updater.py` — agent update channel
- `shared/database.py` — shrinking legacy local cache

## Documentation

- `ezprint-backend/README.md` — backend service overview
- `shopkeeper_app/E2E_CHECKLIST.md` — end-to-end verification
- `build/README.md` + `build/TESTING.md` — PyInstaller packaging and QA

# EzPrint — SaaS printing platform

EzPrint lets customers upload documents from their phone or laptop and pick
them up printed at a local print shop. The platform is split into two
independently-deployable services:

- **`ezprint-backend/`** — FastAPI + Postgres + Redis + MinIO. Hosts the
  customer upload flow, multi-tenant shop data, authentication, and the
  real-time WebSocket that fans jobs out to print shops. Runs as Docker
  Compose (local / single VM) or a managed stack in production.
- **`shopkeeper_app/`** — PyQt5 Windows desktop agent (`EzPrintAgent.exe`).
  Connects to the backend over HTTPS + WebSocket, watches for jobs, pulls
  files via presigned URLs, and drives local printers through `pywin32`.

Supporting code lives in `shared/` (file processing, auto-update, printing
helpers) and is consumed by the desktop agent.

> The legacy Flask + Socket.IO + Cloudinary stack (`web_interface/`,
> `Dockerfile`, `start.py`, etc.) has been removed. Everything it did now
> lives inside `ezprint-backend/`.

## Repository layout

```
ezprint-backend/          FastAPI service (Docker Compose: api, worker, postgres, redis, minio)
  app/                    routers, schemas, workers, tenancy helpers
  docker/                 Dockerfile + MinIO init
  docker-compose.yml      dev stack
  docker-compose.prod.yml prod stack with Caddy + TLS

shopkeeper_app/           Windows desktop agent (PyQt5)
  api_client.py           requests-based REST client (access/refresh/agent JWTs)
  ws_client.py            websocket-client + Qt signal bridge
  auth.py                 API facade, persists session.json
  dashboard.py            main UI (KPIs, jobs, pricing, printers)
  printer_manager.py      Windows print dispatch + heartbeats
  tests/                  unit tests (mock-based)
  requirements-client.txt runtime deps for PyInstaller
  E2E_CHECKLIST.md        manual verification against the dev stack

shared/                   agent-only helpers (file processing, auto-update, printing)
build/                    PyInstaller spec, NSIS installer, CI scripts
```

## Quick start

### 1. Bring up the backend

```bash
cd ezprint-backend
cp .env.example .env         # edit as needed
docker compose up -d --build
curl -fsS http://localhost:8000/healthz   # {"status":"ok"}
docker compose exec api python -m app.scripts.seed_demo
```

### 2. Run the desktop agent against it

```bash
cd shopkeeper_app
uv venv && uv pip install -r requirements-client.txt
export EZPRINT_API_BASE_URL=http://localhost:8000
python main.py                 # log in with the demo shopkeeper
```

`EZPRINT_WS_URL` is derived automatically (`http://…` → `ws://…/ws/agent`,
`https://…` → `wss://…/ws/agent`). Set it explicitly only if you want the
agent to talk to a host different from `EZPRINT_API_BASE_URL`.

### 3. End-to-end walkthrough

Follow `shopkeeper_app/E2E_CHECKLIST.md` — it covers login, dashboard,
printer registration, a real customer upload, WebSocket-driven status
transitions, and failure paths (expired tokens, cleaned-up assets).

## Tests

```bash
# Agent unit tests (mocks only, no network)
ezprint-backend/.venv/bin/python -m pytest shopkeeper_app/tests -q

# Backend suite
cd ezprint-backend && pytest -q
```

## Configuration

- **Backend**: `ezprint-backend/.env` (database URL, JWT secrets, MinIO creds,
  Redis URL). See `ezprint-backend/.env.example`.
- **Agent**: `shared/config.py` reads a handful of env vars — the important
  ones are `EZPRINT_API_BASE_URL`, `EZPRINT_WS_URL`, `EZPRINT_LICENSE_ENABLED`,
  and the auto-update channel settings.

## Building the Windows agent

```bash
cd build
python scripts/build_windows.py         # PyInstaller one-file build
# → build/output/release/EzPrintAgent-<version>.exe + NSIS installer
```

See `build/README.md` for prerequisites (NSIS, signing tools) and
`build/TESTING.md` for the QA checklist.

## License

Proprietary — © EzPrint. See `build/assets/license.txt`.

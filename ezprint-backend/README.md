# ezprint-backend

Single unified backend for the EzPrint SaaS: serves the customer web uploader, a future mobile app, and the Windows shopkeeper printing agent from one API.

- **HTTP REST** under `/api/v1/*` — auth, jobs, printers, shops, admin
- **WebSocket** at `/ws/agent` — persistent channel the Windows agent opens on startup (push side is NAT-safe)
- **MinIO** is the single storage bucket with strict per-tenant prefixing (`tenants/{tenant_id}/...`)
- **Multi-tenant** from day one — every row carries `tenant_id`, resolved from auth context

## Stack

| | |
| --- | --- |
| API | FastAPI 0.110 + Uvicorn |
| DB | Postgres 16 (SQLAlchemy 2.x, Alembic migrations) |
| Bus | Redis 7 (pub/sub fanout for WS push) |
| Storage | MinIO (S3-compatible) |
| TLS | Caddy (prod overlay) |

## Quick start (local)

```bash
cp .env.example .env
docker compose up -d --build

# create a tenant + first shopkeeper + agent provisioning token
docker compose exec api python -m scripts.create_tenant \
    --slug demo-shop --name "Demo Print Shop" \
    --username demo --email demo@example.com --password 'change-me'
```

The output prints a one-time `agent_provisioning_token` — save it; it is shown once.

Then run the end-to-end smoke test (requires `httpx`):

```bash
python -m scripts.smoke_test \
    --api http://localhost:8000 \
    --slug demo-shop \
    --username demo --password change-me \
    --agent-token <provisioning-token>
```

## Running in production (single VM)

1. Point DNS for `api.example.com` and `s3.example.com` at the VM.
2. Edit `.env`: set `ENV=prod`, `API_DOMAIN`, `S3_DOMAIN`, `ACME_EMAIL`, `PUBLIC_BASE_URL`, and `S3_PUBLIC_ENDPOINT=https://s3.example.com`. Use strong random values for `JWT_SECRET`, `MINIO_ROOT_PASSWORD`, `S3_SECRET_KEY`, `POSTGRES_PASSWORD`.
3. Deploy:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   ```
   Caddy obtains Let's Encrypt certs automatically. Postgres/Redis/MinIO host ports are removed; everything reaches the outside world through Caddy on 443.

## Migrations

Migrations run automatically on boot via `docker/entrypoint.sh` (`alembic upgrade head`). To author a new migration locally:

```bash
docker compose exec api alembic revision --autogenerate -m "describe change"
```

## API overview

See `app/api/v1/*.py` for the source of truth; headlines:

- `POST /api/v1/auth/login` — shopkeeper login (access + refresh tokens)
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/agent/session` — exchange provisioning token for short-lived agent JWT
- `GET  /api/v1/auth/upload/{shop_slug}` — mint a customer upload token (anonymous)
- `POST /api/v1/jobs` — create a job (customer) → returns presigned MinIO PUT URL
- `POST /api/v1/jobs/{id}/finalize` — classify + price + push event to the agent
- `GET  /api/v1/jobs` — list (shopkeeper/agent)
- `GET  /api/v1/jobs/{id}/file-url` — agent fetches presigned GET URL
- `PATCH /api/v1/jobs/{id}/status` — Printing / Completed / Failed
- `GET/POST/DELETE /api/v1/printers` — printer registry
- `GET/PUT /api/v1/shops/{tenant_id}/info`
- `GET/PUT /api/v1/shops/{tenant_id}/pricing`
- `POST /api/v1/admin/tenants` — (admin) create tenant + first shopkeeper + provisioning token
- `WS   /ws/agent?token=<agent jwt>` — persistent push channel

## Data model

One `tenants` row per shop. Every other table (`shopkeepers`, `print_jobs`, `printers`, `shop_pricing`, `licenses`, `system_logs`, `agent_tokens`) has a `tenant_id` FK with an index. Application code MUST filter by the tenant in the auth principal, never by request body.

## MinIO layout

```
ezprint/
  tenants/{tenant_id}/
    jobs/{job_id}/
      original/{filename}
      print/{job_id}.pdf
      previews/page-{n}.jpg
  _system/
    qr/{tenant_id}.png
```

`app/services/storage.py` enforces at runtime that every generated key begins with the caller's tenant prefix. Cross-tenant operations raise `TenantScopeViolation`.

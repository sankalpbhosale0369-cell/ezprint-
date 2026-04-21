# EzPrint Azure Deployment

## Infrastructure

| Field | Value |
|-------|-------|
| VM Name | `ezprint-vm` |
| Resource Group | `ezprint-rg2` |
| Location | `westus2` |
| Size | Standard_D2as_v5 (2 vCPU, 8 GB RAM, AMD EPYC) |
| OS | Ubuntu 24.04 LTS |
| OS Disk | 128 GB StandardSSD_LRS |
| Public IP | `20.3.74.49` |
| FQDN | `ezprint-447a0aad.westus2.cloudapp.azure.com` |
| Open Ports | 22 (SSH), 80 (HTTP), 443 (HTTPS) |
| SSH Key | `~/.ssh/id_rsa` (local) |
| SSH User | `azureuser` |

```bash
ssh azureuser@ezprint-447a0aad.westus2.cloudapp.azure.com
```

---

## Live URLs

| Endpoint | URL |
|----------|-----|
| API health check | `https://ezprint-447a0aad.westus2.cloudapp.azure.com/healthz` |
| Customer upload page | `https://ezprint-447a0aad.westus2.cloudapp.azure.com/shop/test-shop` |
| API docs (OpenAPI) | `https://ezprint-447a0aad.westus2.cloudapp.azure.com/docs` |
| MinIO (via Caddy) | `https://ezprint-447a0aad.westus2.cloudapp.azure.com/s3/` |

---

## Stack

All services run via Docker Compose on the VM:

```bash
cd ~/EzPrint/ezprint-backend
sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.azure.yml \
  up -d
```

| Service | Image | Status |
|---------|-------|--------|
| `api` | `ezprint-backend:latest` | healthy |
| `worker` | `ezprint-backend:latest` | up |
| `postgres` | `postgres:16-alpine` | healthy |
| `redis` | `redis:7-alpine` | healthy |
| `minio` | `minio/minio:latest` | healthy |
| `caddy` | `caddy:2-alpine` | up (TLS via Let's Encrypt) |

### Useful commands

```bash
# View logs
sudo docker compose logs -f api
sudo docker compose logs -f worker

# Restart a service
sudo docker compose restart api

# Full redeploy after code change
cd ~/EzPrint && git pull
cd ezprint-backend
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.azure.yml up -d --build
```

---

## MinIO / S3 Fix

The ngrok-era bug was `S3_PUBLIC_ENDPOINT=http://localhost:9000` — presigned URLs pointed to localhost so the Windows agent couldn't download files. Fixed by:

- `S3_ENDPOINT=http://minio:9000` — internal docker network (unchanged)
- `S3_PUBLIC_ENDPOINT=https://ezprint-447a0aad.westus2.cloudapp.azure.com/s3` — public, routed through Caddy

`Caddyfile.azure` routes `/s3/*` → `minio:9000` using `handle_path` (strips the `/s3` prefix). Because SigV4 signs the CanonicalURI as-issued, we can't naively sign against `https://HOST/s3/...` — MinIO would recompute the signature over `/ezprint/...` (post-strip) and reject it with 403.

Instead, `StorageService` in [`ezprint-backend/app/services/storage.py`](ezprint-backend/app/services/storage.py):

1. Splits `S3_PUBLIC_ENDPOINT=https://HOST/s3` into bare host (`https://HOST`) and path prefix (`/s3`).
2. Builds the public boto3 client against the **bare host**, so SigV4 signs the CanonicalURI that MinIO will actually see after Caddy strips `/s3`.
3. After boto3 returns the presigned URL, injects the `/s3` prefix back into the URL path (query string / signature untouched).

Result:
```
https://ezprint-447a0aad.westus2.cloudapp.azure.com/s3/ezprint/tenants/.../...?X-Amz-Signature=...
```
The Windows agent hits `…/s3/…`, Caddy strips `/s3`, MinIO recomputes the signature over `/ezprint/…` — which is exactly what boto3 signed — and serves the object. ✓

Subdomain-based deploys (stock `Caddyfile` with an `S3_DOMAIN`) set `S3_PUBLIC_ENDPOINT=https://s3.HOST` — no path, prefix is empty, and the helper is a no-op.

---

## Backend .env (on VM at `~/EzPrint/ezprint-backend/.env`)

```env
ENV=prod
API_DOMAIN=ezprint-447a0aad.westus2.cloudapp.azure.com
ACME_EMAIL=pranavprajapati586@gmail.com
PUBLIC_BASE_URL=https://ezprint-447a0aad.westus2.cloudapp.azure.com

JWT_ALG=HS256
JWT_ACCESS_TTL_MINUTES=60
JWT_REFRESH_TTL_DAYS=7
AGENT_SESSION_TTL_HOURS=24
UPLOAD_TOKEN_TTL_MINUTES=30

POSTGRES_USER=ezprint
POSTGRES_DB=ezprint
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

REDIS_URL=redis://redis:6379/0

S3_ENDPOINT=http://minio:9000
S3_PUBLIC_ENDPOINT=https://ezprint-447a0aad.westus2.cloudapp.azure.com/s3
S3_ACCESS_KEY=minio_ezprint
S3_BUCKET_NAME=ezprint
S3_REGION=us-east-1
MINIO_ROOT_USER=minioadmin

S3_DOMAIN=
CORS_ALLOW_ORIGINS=["*"]
```

> Secrets (JWT_SECRET, POSTGRES_PASSWORD, S3_SECRET_KEY, MINIO_ROOT_PASSWORD) are set on the server only — not stored here.

---

## Windows Agent Configuration

Set this in the agent's `.env` before launching `EzPrintAgent.exe`:

```env
EZPRINT_API_BASE_URL=https://ezprint-447a0aad.westus2.cloudapp.azure.com
```

WebSocket URL is auto-derived as `wss://ezprint-447a0aad.westus2.cloudapp.azure.com/ws/agent`.

---

## Test Shopkeeper Account

| Field | Value |
|-------|-------|
| Email | `test@ezprint.com` |
| Password | `password123` |
| Shop name | `Test Print Shop` |
| Shop slug | `test-shop` |
| Tenant ID | `a74f81e2-dc61-4146-b173-34e282f5f4ca` |

### Create a new tenant (admin API)

```bash
# X-Admin-Token = JWT_SECRET value from .env
curl -s https://ezprint-447a0aad.westus2.cloudapp.azure.com/api/v1/admin/tenants \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: <JWT_SECRET>" \
  -d '{
    "slug": "my-shop",
    "shop_name": "My Print Shop",
    "shopkeeper_name": "Owner Name",
    "username": "myuser",
    "email": "owner@example.com",
    "password": "strongpassword"
  }'
```

---

## GitHub Actions — EXE Build

Workflow: `.github/workflows/build-exe.yml`

Triggers on:
- Any `v*` tag push (e.g. `git tag v1.2.0 && git push origin v1.2.0`)
- Manual dispatch from the GitHub Actions UI

Artifact: `EzPrintAgent-Windows` → `EzPrintAgent.exe` (retained 30 days)

Latest build triggered by tag: `v1.1.0`

---

## Re-deploy After Code Changes

```bash
# On local machine — commit, push, tag
git add .
git commit -m "your message"
git push origin feature/saas-migration

# SSH into VM and pull
ssh azureuser@ezprint-447a0aad.westus2.cloudapp.azure.com
cd ~/EzPrint && git pull
cd ezprint-backend
sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.azure.yml \
  up -d --build

# Trigger new EXE build (bump version as needed)
git tag v1.2.0 && git push origin v1.2.0
```

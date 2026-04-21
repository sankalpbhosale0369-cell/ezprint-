#!/usr/bin/env bash
set -euo pipefail

CMD="${1:-api}"

case "$CMD" in
  api)
    echo "[entrypoint] Running migrations..."
    alembic upgrade head
    echo "[entrypoint] Starting API on :8000"
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
    ;;
  worker)
    echo "[entrypoint] Starting background worker"
    exec python -m app.workers.cleanup
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    echo "[entrypoint] Exec: $*"
    exec "$@"
    ;;
esac

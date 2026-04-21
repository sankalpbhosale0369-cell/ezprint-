"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.services.notifier import notifier
from app.services.storage import storage
from app.ws.agent import ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    import logging
    log = logging.getLogger(__name__)

    # Guardrail: presigned GET/PUT URLs are signed against `s3_public_endpoint`.
    # If the public base URL is a real host but the S3 public endpoint is
    # still `localhost`, every download from a remote client will fail with
    # "Max retries exceeded ... localhost:9000". Log a very loud warning so
    # the operator notices in dev logs; we don't hard-fail because local
    # developers legitimately run everything on localhost.
    try:
        pub = (settings.public_base_url or "").lower()
        s3_pub = (settings.s3_public_endpoint or "").lower()
        if ("localhost" in s3_pub or "127.0.0.1" in s3_pub) and \
           ("localhost" not in pub and "127.0.0.1" not in pub):
            log.error(
                "MISCONFIGURATION: S3_PUBLIC_ENDPOINT=%s points to localhost but "
                "PUBLIC_BASE_URL=%s is a public host. Remote agents/customers "
                "will NOT be able to download files via presigned URLs. "
                "Set S3_PUBLIC_ENDPOINT to a publicly reachable MinIO/S3 URL "
                "(e.g. https://%s-s3 or the S3_DOMAIN you proxy through Caddy).",
                settings.s3_public_endpoint, settings.public_base_url, settings.env,
            )
    except Exception:  # noqa: BLE001
        pass

    # Log the resolved boto3 public endpoint + any path prefix we will inject
    # into presigned URLs, so a misconfigured single-host deploy (e.g. wrong
    # `/s3` stripping behind Caddy) is easy to spot in `docker compose logs`.
    try:
        log.info(
            "storage public endpoint: boto3_endpoint=%s url_prefix=%r (raw=%s)",
            getattr(storage, "_public_endpoint", None),
            getattr(storage, "_public_url_prefix", ""),
            settings.s3_public_endpoint,
        )
    except Exception:  # noqa: BLE001
        pass

    # Fail fast if MinIO is unreachable / bucket missing in prod-style env.
    try:
        storage.ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        # Don't crash the API if storage is slow to come up during boot; log loudly.
        log.warning("storage.ensure_bucket failed at boot: %s", exc)
    await notifier.start()
    try:
        yield
    finally:
        await notifier.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="EzPrint Backend",
        version="0.1.0",
        description="Single backend for the EzPrint SaaS: customer uploads + Windows printing agent.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router, prefix="/api/v1")
    app.include_router(ws_router)

    @app.get("/healthz", tags=["system"])
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "ezprint-backend", "env": settings.env})

    _upload_page = os.path.join(os.path.dirname(__file__), "static", "upload.html")

    @app.get("/shop/{slug}", include_in_schema=False)
    def customer_upload_page(slug: str) -> FileResponse:
        """Serve the customer upload SPA. Slug is read by the JS from the URL."""
        return FileResponse(_upload_page, media_type="text/html")

    return app


app = create_app()

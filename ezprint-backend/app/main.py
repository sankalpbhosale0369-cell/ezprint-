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
    # Fail fast if MinIO is unreachable / bucket missing in prod-style env.
    try:
        storage.ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        # Don't crash the API if storage is slow to come up during boot; log loudly.
        import logging
        logging.getLogger(__name__).warning("storage.ensure_bucket failed at boot: %s", exc)
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

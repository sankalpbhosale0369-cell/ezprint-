"""Persistent WebSocket channel for the Windows shopkeeper agent.

The agent opens this connection on startup (the backend can't reach the
agent behind NAT). We:

    - validate the agent's JWT from the `token` query param
    - subscribe to Redis pub/sub for that tenant via `notifier`
    - relay new_job / job_cancelled / reconnect_required events downstream
    - accept heartbeat / print_* events coming back up, updating DB state

See plan section 2.2-2.5 for the event vocabulary.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.core.security import decode_token
from app.db import models
from app.db.session import SessionLocal
from app.services.jobs import transition
from app.services.notifier import notifier

logger = logging.getLogger(__name__)

ws_router = APIRouter()


def _utcnow() -> datetime:
    return datetime.utcnow()


async def _handle_heartbeat(tenant_id: str, data: dict) -> None:
    """Update is_online / last_heartbeat on all printers the agent reports."""
    printers = data.get("printers") or []
    if not printers:
        return
    db = SessionLocal()
    try:
        for p in printers:
            pid = p.get("printer_id")
            if not pid:
                continue
            row = db.scalars(
                select(models.Printer).where(
                    models.Printer.tenant_id == tenant_id,
                    models.Printer.printer_id == pid,
                )
            ).first()
            if not row:
                continue
            row.is_online = bool(p.get("is_online", True))
            row.last_heartbeat = _utcnow()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("heartbeat DB update failed (tenant=%s)", tenant_id)
    finally:
        db.close()


_WS_STATUS_MAP = {
    "print_started": "Printing",
    "print_completed": "Completed",
    "print_failed": "Failed",
}


async def _handle_print_status(tenant_id: str, kind: str, data: dict) -> None:
    """Delegate agent-reported status changes to the shared state machine.

    This guarantees the REST and WS paths produce identical DB writes,
    pub/sub broadcasts, and immediate MinIO cleanup on terminal states.
    """
    target = _WS_STATUS_MAP.get(kind)
    if not target:
        return
    job_id = data.get("job_id")
    if not job_id:
        return
    db = SessionLocal()
    try:
        job = db.scalars(
            select(models.PrintJob).where(
                models.PrintJob.tenant_id == tenant_id,
                models.PrintJob.job_id == job_id,
            )
        ).first()
        if not job:
            return
        error_message = data.get("error_message") or data.get("error_code")
        try:
            transition(db, job, target, error_message=error_message)
        except HTTPException as exc:
            # Invalid transition from the agent (e.g. duplicate completed).
            # Log and swallow — we never kill the WS for a stale event.
            logger.warning(
                "ignoring invalid agent transition tenant=%s job=%s %s -> %s: %s",
                tenant_id, job_id, job.status, target, exc.detail,
            )
    except Exception:
        db.rollback()
        logger.exception("print status update failed (job=%s)", job_id)
    finally:
        db.close()


@ws_router.websocket("/ws/agent")
async def agent_socket(websocket: WebSocket, token: Optional[str] = Query(default=None)) -> None:
    # Auth happens BEFORE accept so unauthenticated clients get a clean close.
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        claims = decode_token(token, expected_types={"agent"})
    except jwt.PyJWTError as exc:
        logger.info("ws/agent rejected: %s", exc)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    tenant_id = str(claims["tid"])
    await websocket.accept()
    logger.info("agent connected tenant=%s", tenant_id)

    # Forward redis pub/sub events to THIS socket. We use an async queue so
    # the notifier's callback never blocks on a slow client.
    outbound: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)

    async def _on_event(tid: str, event: dict) -> None:
        if tid != tenant_id:
            return
        try:
            outbound.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("agent queue full for tenant=%s; dropping event", tenant_id)

    await notifier.subscribe(tenant_id, _on_event)

    async def _sender() -> None:
        while True:
            event = await outbound.get()
            await websocket.send_text(json.dumps(event, default=str))

    send_task = asyncio.create_task(_sender(), name=f"ws-sender-{tenant_id}")

    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "registered",
                    "tenant_id": tenant_id,
                    "message": "Agent registered successfully",
                    "server_time": _utcnow().isoformat(),
                }
            )
        )

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("agent sent non-json message (tenant=%s)", tenant_id)
                continue

            kind = message.get("type")
            data = message.get("data") or {}

            if kind == "ping":
                await websocket.send_text(
                    json.dumps({"type": "pong", "server_time": _utcnow().isoformat()})
                )
            elif kind == "printer_heartbeat":
                await _handle_heartbeat(tenant_id, data)
            elif kind in {"print_started", "print_completed", "print_failed"}:
                await _handle_print_status(tenant_id, kind, data)
            else:
                logger.debug("agent message ignored kind=%s tenant=%s", kind, tenant_id)

    except WebSocketDisconnect:
        logger.info("agent disconnected tenant=%s", tenant_id)
    except Exception:
        logger.exception("agent socket error tenant=%s", tenant_id)
    finally:
        send_task.cancel()
        try:
            await send_task
        except (asyncio.CancelledError, Exception):
            pass
        await notifier.unsubscribe(tenant_id, _on_event)

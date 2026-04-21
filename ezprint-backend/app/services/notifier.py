"""Redis pub/sub fanout for pushing events to Windows agents.

Any number of `api` containers can be running behind a load balancer. An
agent is connected to whichever container accepted its WebSocket. When the
backend needs to notify a tenant's agent (e.g. a customer just finished an
upload), we publish to the `tenant:{tenant_id}` Redis channel. Every API
instance subscribes to `tenant:*`, and whichever one holds the matching
socket delivers the message.

    publish:  notifier.publish(tenant_id, event_dict)
    subscribe: set inside `ConnectionManager` on agent connect
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Dict, Optional

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict], Awaitable[None]]


class Notifier:
    """Tiny abstraction around Redis pub/sub keyed on `tenant_id`."""

    CHANNEL_PREFIX = "ezprint:tenant:"

    def __init__(self) -> None:
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub = None
        self._listener_task: Optional[asyncio.Task] = None
        self._subscribers: Dict[str, set] = {}  # tenant_id -> set of callbacks
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._redis is not None:
            return
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        # Pattern subscription so we can dynamically route without resubscribing.
        await self._pubsub.psubscribe(f"{self.CHANNEL_PREFIX}*")
        self._listener_task = asyncio.create_task(self._listen(), name="notifier-listener")
        logger.info("notifier started (pattern=%s*)", self.CHANNEL_PREFIX)

    async def stop(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except (asyncio.CancelledError, Exception):
                pass
            self._listener_task = None
        if self._pubsub:
            try:
                await self._pubsub.close()
            except Exception:
                pass
            self._pubsub = None
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None

    async def publish(self, tenant_id: str, event: dict) -> int:
        """Publish an event to all API instances listening for this tenant.

        Returns the number of subscribers Redis delivered to.
        """
        if self._redis is None:
            await self.start()
        channel = f"{self.CHANNEL_PREFIX}{tenant_id}"
        payload = json.dumps(event, default=str)
        return int(await self._redis.publish(channel, payload))  # type: ignore[union-attr]

    async def subscribe(self, tenant_id: str, callback: EventCallback) -> None:
        async with self._lock:
            self._subscribers.setdefault(tenant_id, set()).add(callback)

    async def unsubscribe(self, tenant_id: str, callback: EventCallback) -> None:
        async with self._lock:
            subs = self._subscribers.get(tenant_id)
            if not subs:
                return
            subs.discard(callback)
            if not subs:
                self._subscribers.pop(tenant_id, None)

    async def _listen(self) -> None:
        assert self._pubsub is not None
        logger.info("notifier listener loop running")
        try:
            async for message in self._pubsub.listen():
                if not message or message.get("type") not in {"pmessage", "message"}:
                    continue
                channel = message.get("channel") or ""
                if not channel.startswith(self.CHANNEL_PREFIX):
                    continue
                tenant_id = channel[len(self.CHANNEL_PREFIX):]
                try:
                    event = json.loads(message.get("data") or "{}")
                except json.JSONDecodeError:
                    logger.warning("notifier got non-json message on %s", channel)
                    continue

                callbacks = list(self._subscribers.get(tenant_id, set()))
                for cb in callbacks:
                    try:
                        await cb(tenant_id, event)
                    except Exception:
                        logger.exception("notifier callback failed for tenant=%s", tenant_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("notifier listener crashed")


notifier = Notifier()

"""Realtime fan-out over Redis pub/sub.

Celery workers and the API run in different processes, so a worker cannot write to a
WebSocket directly. Workers publish to Redis; each API process subscribes and relays to the
sockets it holds. This also means the design already works with several API replicas.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from typing import Any

import redis
import redis.asyncio as aioredis
from fastapi import WebSocket

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

CHANNEL = "claims:events"

ROOM_AGENTS = "agents"


def _room_for_user(user_id: uuid.UUID | str) -> str:
    return f"user:{user_id}"


class ConnectionManager:
    """Sockets held by *this* process, grouped into rooms."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def join(self, websocket: WebSocket, rooms: list[str]) -> None:
        async with self._lock:
            for room in rooms:
                self._rooms[room].add(websocket)

    async def leave(self, websocket: WebSocket) -> None:
        async with self._lock:
            for room in list(self._rooms):
                self._rooms[room].discard(websocket)
                if not self._rooms[room]:
                    del self._rooms[room]

    async def send_to_room(self, room: str, message: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._rooms.get(room, ()))

        dead: list[WebSocket] = []
        for socket in targets:
            try:
                await socket.send_json(message)
            except Exception:  # noqa: BLE001 — a closed socket is expected, not exceptional
                dead.append(socket)

        if dead:
            async with self._lock:
                for socket in dead:
                    for room_sockets in self._rooms.values():
                        room_sockets.discard(socket)

    @property
    def connection_count(self) -> int:
        return len({s for sockets in self._rooms.values() for s in sockets})


manager = ConnectionManager()


def publish(event: dict[str, Any], *, rooms: list[str]) -> None:
    """Publish from synchronous code (Celery tasks, request handlers).

    Failure to publish is logged and swallowed: a missed progress frame must never fail the
    claim processing that produced it. The client can still poll `/claims/{id}/status`.
    """
    payload = json.dumps({"rooms": rooms, "event": event}, default=str)
    try:
        client = redis.from_url(settings.redis_url, socket_connect_timeout=0.4)
        try:
            client.publish(CHANNEL, payload)
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 — Redis is optional; polling remains the fallback
        # structlog reserves the keyword `event` for the message; never pass it as a field.
        log.warning("realtime.publish_failed", error=str(exc), event_type=event.get("type"))


def publish_to_user(user_id: uuid.UUID | str, event: dict[str, Any]) -> None:
    publish(event, rooms=[_room_for_user(user_id)])


def publish_to_agents(event: dict[str, Any]) -> None:
    publish(event, rooms=[ROOM_AGENTS])


async def redis_relay() -> None:
    """Background task: relay Redis messages to this process's sockets."""
    while True:
        try:
            client = aioredis.from_url(settings.redis_url)
            pubsub = client.pubsub()
            await pubsub.subscribe(CHANNEL)
            log.info("realtime.relay_started")

            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue

                event = data.get("event", {})
                for room in data.get("rooms", []):
                    await manager.send_to_room(room, event)

        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("realtime.relay_error", error=str(exc))
            await asyncio.sleep(3)

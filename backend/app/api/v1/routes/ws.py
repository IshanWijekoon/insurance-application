"""Authenticated WebSocket for live claim progress and agent alerts."""

from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.enums import UserRole
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.notifications.hub import ROOM_AGENTS, manager
from app.services.auth import AuthService

log = get_logger(__name__)
router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    db = SessionLocal()
    try:
        user = AuthService(db).resolve_access_token(token)
    except Exception:
        await websocket.close(code=4401)
        db.close()
        return
    finally:
        db.close()

    await websocket.accept()
    rooms = [f"user:{user.id}"]
    if user.role in {UserRole.AGENT, UserRole.ADMIN}:
        rooms.append(ROOM_AGENTS)

    await manager.join(websocket, rooms)
    log.info("realtime.connected", user_id=str(user.id), rooms=rooms)
    try:
        while True:
            # Clients may send pings; we do not currently accept commands over the socket.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.leave(websocket)
        log.info("realtime.disconnected", user_id=str(user.id))

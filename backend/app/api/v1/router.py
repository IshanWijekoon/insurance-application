"""Assembles the v1 HTTP surface."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import rate_limit
from app.api.v1.routes import admin, agent, auth, claims, media, notifications, vehicles, ws

api_router = APIRouter(dependencies=[Depends(rate_limit)])
api_router.include_router(auth.router)
api_router.include_router(vehicles.router)
api_router.include_router(claims.router)
api_router.include_router(agent.router)
api_router.include_router(admin.router)
api_router.include_router(notifications.router)
api_router.include_router(media.router)
api_router.include_router(ws.router)

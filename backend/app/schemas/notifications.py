"""In-app notification contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import DeliveryStatus, NotificationChannel
from app.schemas.common import ORMModel


class UnreadCountResponse(BaseModel):
    unread: int


class NotificationResponse(ORMModel):
    id: uuid.UUID
    claim_id: uuid.UUID | None = None
    channel: NotificationChannel
    notification_type: str
    title: str
    body: str
    payload: dict[str, Any] = Field(default_factory=dict)
    is_read: bool
    read_at: datetime | None = None
    delivery_status: DeliveryStatus
    created_at: datetime

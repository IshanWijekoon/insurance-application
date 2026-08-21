"""In-app notification centre."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError
from app.models.ops import Notification
from app.schemas.common import MessageResponse, Page
from app.schemas.notifications import NotificationResponse, UnreadCountResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationResponse])
def list_notifications(
    db: DbSession,
    user: CurrentUser,
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    from app.core.enums import NotificationChannel

    base = select(Notification).where(
        Notification.recipient_user_id == user.id,
        Notification.channel == NotificationChannel.IN_APP,
    )
    if unread_only:
        base = base.where(Notification.is_read.is_(False))

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page[NotificationResponse](
        items=[NotificationResponse.model_validate(n) for n in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
def unread_count(db: DbSession, user: CurrentUser):
    from app.core.enums import NotificationChannel

    n = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.recipient_user_id == user.id,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.is_read.is_(False),
        )
    ) or 0
    return UnreadCountResponse(unread=n)


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(notification_id: uuid.UUID, db: DbSession, user: CurrentUser):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.recipient_user_id != user.id:
        raise NotFoundError("Notification not found.")
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        db.flush()
    return NotificationResponse.model_validate(notification)


@router.post("/read-all", response_model=MessageResponse)
def mark_all_read(db: DbSession, user: CurrentUser):
    from app.core.enums import NotificationChannel

    rows = db.scalars(
        select(Notification).where(
            Notification.recipient_user_id == user.id,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.is_read.is_(False),
        )
    ).all()
    now = datetime.now(UTC)
    for row in rows:
        row.is_read = True
        row.read_at = now
    db.flush()
    return MessageResponse(message=f"{len(rows)} notification(s) marked as read.")

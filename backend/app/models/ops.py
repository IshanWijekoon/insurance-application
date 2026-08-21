"""Operational tables: fraud signals, notifications, AI call logs and the audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from app.db.types import GUID, JSONDoc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AICallStatus,
    AIStage,
    DeliveryStatus,
    NotificationChannel,
    RiskLevel,
)
from app.db.base import Base, Timestamped, UUIDPrimaryKey
from app.db.types import enum_type

if TYPE_CHECKING:
    from app.models.claim import Claim


class FraudSignal(Base, UUIDPrimaryKey, Timestamped):
    """A risk indicator. Never a rejection on its own — always an input to human review."""

    __tablename__ = "fraud_signals"
    __table_args__ = (Index("ix_fraud_signals_claim", "claim_id"),)

    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    signal_code: Mapped[str] = mapped_column(String(60), nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(
        enum_type(RiskLevel), default=RiskLevel.LOW, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONDoc, default=dict, nullable=False)
    detector_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    reviewed_by_agent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    agent_verdict: Mapped[str | None] = mapped_column(String(60))

    claim: Mapped["Claim"] = relationship(back_populates="fraud_signals")


class Notification(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_recipient", "recipient_user_id", "is_read"),
        Index("ix_notifications_claim", "claim_id"),
    )

    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE")
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_type(NotificationChannel), default=NotificationChannel.IN_APP, nullable=False
    )
    notification_type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONDoc, default=dict, nullable=False)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        enum_type(DeliveryStatus), default=DeliveryStatus.PENDING, nullable=False
    )
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIAnalysisLog(Base, UUIDPrimaryKey, Timestamped):
    """One row per AI call.

    Deliberately stores no image bytes and no customer PII — only which model was asked
    what kind of question, how it went, and a truncated excerpt for debugging.
    """

    __tablename__ = "ai_analysis_logs"
    __table_args__ = (
        Index("ix_ai_logs_claim", "claim_id", "created_at"),
        Index("ix_ai_logs_stage_status", "stage", "status"),
    )

    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE")
    )
    stage: Mapped[AIStage] = mapped_column(enum_type(AIStage), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(80))

    status: Mapped[AICallStatus] = mapped_column(enum_type(AICallStatus), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    image_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_message: Mapped[str | None] = mapped_column(Text)
    response_excerpt: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base, UUIDPrimaryKey, Timestamped):
    """Append-only record of every mutation. No update or delete path exists in code."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_actor", "actor_user_id", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_role: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONDoc)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONDoc)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    request_id: Mapped[str | None] = mapped_column(String(64))

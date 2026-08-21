"""Identity: users, sessions, and the customer/agent profiles hanging off them."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import UserRole
from app.db.base import Base, SoftDeletable, Timestamped, UUIDPrimaryKey
from app.db.types import enum_type

if TYPE_CHECKING:
    from app.models.claim import Claim
    from app.models.vehicle import Vehicle


class User(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[UserRole] = mapped_column(enum_type(UserRole), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped["Customer | None"] = relationship(back_populates="user", uselist=False)
    agent: Mapped["Agent | None"] = relationship(back_populates="user", uselist=False)
    sessions: Mapped[list["RefreshSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshSession(Base, UUIDPrimaryKey, Timestamped):
    """One row per issued refresh token. Rotation revokes the old row.

    `family_id` groups tokens descended from a single login. Presenting a token that has
    already been rotated implies replay, and the whole family is revoked.
    """

    __tablename__ = "refresh_sessions"
    __table_args__ = (Index("ix_refresh_sessions_family", "family_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="sessions")


class Customer(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "customers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    national_id: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(String(400))
    city: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(2), default="LK", nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)

    user: Mapped[User] = relationship(back_populates="customer")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="customer")
    claims: Mapped[list["Claim"]] = relationship(
        back_populates="customer", foreign_keys="Claim.customer_id"
    )


class Agent(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "agents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    employee_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    branch: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_concurrent_claims: Mapped[int] = mapped_column(Integer, default=25, nullable=False)

    user: Mapped[User] = relationship(back_populates="agent")
    assigned_claims: Mapped[list["Claim"]] = relationship(
        back_populates="assigned_agent", foreign_keys="Claim.assigned_agent_id"
    )

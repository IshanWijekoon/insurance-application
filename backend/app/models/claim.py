"""Claims, their status history, notes and location."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from app.db.types import GUID, JSONDoc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    ActorType,
    ClaimPriority,
    ClaimStatus,
    LocationSource,
    NoteVisibility,
)
from app.db.base import Base, SoftDeletable, Timestamped, UUIDPrimaryKey
from app.db.types import CONFIDENCE, enum_type

if TYPE_CHECKING:
    from app.models.assessment import DamageAssessment
    from app.models.estimate import RepairEstimate
    from app.models.image import ClaimImage, CustomerDamageReport
    from app.models.market import VehicleValuation
    from app.models.ops import FraudSignal
    from app.models.user import Agent, Customer
    from app.models.vehicle import InsurancePolicy, Vehicle


class Claim(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_status", "status"),
        Index("ix_claims_customer", "customer_id"),
        Index("ix_claims_agent", "assigned_agent_id"),
        Index("ix_claims_created", "created_at"),
    )

    claim_number: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("insurance_policies.id", ondelete="SET NULL")
    )
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("agents.id", ondelete="SET NULL")
    )

    status: Mapped[ClaimStatus] = mapped_column(
        enum_type(ClaimStatus), default=ClaimStatus.DRAFT, nullable=False
    )
    priority: Mapped[ClaimPriority] = mapped_column(
        enum_type(ClaimPriority), default=ClaimPriority.NORMAL, nullable=False
    )

    # Customer-stated context. Treated as reported information, never as confirmed fact.
    accident_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accident_description: Mapped[str | None] = mapped_column(Text)
    customer_vehicle_description: Mapped[str | None] = mapped_column(Text)

    # Vehicle details typed in for this claim, kept separate from the `vehicles` record so a
    # correction made during a claim never silently rewrites the customer's garage.
    stated_make: Mapped[str | None] = mapped_column(String(80))
    stated_model: Mapped[str | None] = mapped_column(String(80))
    stated_variant: Mapped[str | None] = mapped_column(String(80))
    stated_year: Mapped[int | None] = mapped_column()
    stated_color: Mapped[str | None] = mapped_column(String(40))
    stated_registration: Mapped[str | None] = mapped_column(String(32))

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    manual_review_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    manual_review_reasons: Mapped[list[str]] = mapped_column(
        JSONDoc, default=list, nullable=False
    )
    overall_confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)

    pipeline_stage: Mapped[str | None] = mapped_column(String(48))
    pipeline_progress: Mapped[dict[str, Any]] = mapped_column(JSONDoc, default=dict, nullable=False)

    decision_reason: Mapped[str | None] = mapped_column(Text)
    information_request: Mapped[str | None] = mapped_column(Text)

    customer: Mapped["Customer"] = relationship(
        back_populates="claims", foreign_keys=[customer_id]
    )
    vehicle: Mapped["Vehicle | None"] = relationship(back_populates="claims")
    policy: Mapped["InsurancePolicy | None"] = relationship(back_populates="claims")
    assigned_agent: Mapped["Agent | None"] = relationship(
        back_populates="assigned_claims", foreign_keys=[assigned_agent_id]
    )

    images: Mapped[list["ClaimImage"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    damage_report: Mapped["CustomerDamageReport | None"] = relationship(
        back_populates="claim", uselist=False, cascade="all, delete-orphan"
    )
    assessments: Mapped[list["DamageAssessment"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    valuations: Mapped[list["VehicleValuation"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    estimates: Mapped[list["RepairEstimate"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    location: Mapped["ClaimLocation | None"] = relationship(
        back_populates="claim", uselist=False, cascade="all, delete-orphan"
    )
    status_events: Mapped[list["ClaimStatusEvent"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="ClaimStatusEvent.created_at"
    )
    notes: Mapped[list["ClaimNote"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    fraud_signals: Mapped[list["FraudSignal"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )

    @property
    def is_editable_by_customer(self) -> bool:
        return self.status in {ClaimStatus.DRAFT, ClaimStatus.MORE_INFORMATION_REQUIRED}

    @property
    def latest_assessment(self) -> "DamageAssessment | None":
        return max(self.assessments, key=lambda a: a.created_at, default=None)

    @property
    def latest_estimate(self) -> "RepairEstimate | None":
        return max(self.estimates, key=lambda e: e.created_at, default=None)

    @property
    def latest_valuation(self) -> "VehicleValuation | None":
        return max(self.valuations, key=lambda v: v.created_at, default=None)


class ClaimStatusEvent(Base, UUIDPrimaryKey, Timestamped):
    """Append-only status history; the source of the claim timeline."""

    __tablename__ = "claim_status_events"
    __table_args__ = (Index("ix_claim_status_events_claim", "claim_id", "created_at"),)

    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[ClaimStatus | None] = mapped_column(enum_type(ClaimStatus))
    to_status: Mapped[ClaimStatus] = mapped_column(enum_type(ClaimStatus), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_type: Mapped[ActorType] = mapped_column(
        enum_type(ActorType), default=ActorType.SYSTEM, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)

    claim: Mapped[Claim] = relationship(back_populates="status_events")


class ClaimNote(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "claim_notes"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[NoteVisibility] = mapped_column(
        enum_type(NoteVisibility), default=NoteVisibility.INTERNAL, nullable=False
    )

    claim: Mapped[Claim] = relationship(back_populates="notes")


class ClaimLocation(Base, UUIDPrimaryKey, Timestamped):
    """Where the accident happened.

    A row exists only when a location was genuinely obtained. `source` records how, so the
    UI can say "EXIF GPS" or "Customer selected" rather than implying certainty.
    """

    __tablename__ = "claim_locations"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str | None] = mapped_column(String(400))
    city: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[LocationSource] = mapped_column(enum_type(LocationSource), nullable=False)
    accuracy_meters: Mapped[float | None] = mapped_column(Float)
    geocoded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    claim: Mapped[Claim] = relationship(back_populates="location")

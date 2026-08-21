"""AI assessment output: vehicle identification and the damaged parts it found."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from app.db.types import GUID, JSONDoc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DamageSeverity, DamageType, RepairAction
from app.db.base import Base, Timestamped, UUIDPrimaryKey
from app.db.types import CONFIDENCE, enum_type

if TYPE_CHECKING:
    from app.models.claim import Claim
    from app.models.market import PartPriceSource, PartPriceSummary


class DamageAssessment(Base, UUIDPrimaryKey, Timestamped):
    """One AI analysis run over a claim.

    Re-analysis inserts a new row rather than updating; the history of what the model said,
    and when, is part of the audit trail.
    """

    __tablename__ = "damage_assessments"
    __table_args__ = (Index("ix_damage_assessments_claim", "claim_id", "created_at"),)

    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # Vehicle as identified from the images.
    vehicle_make: Mapped[str | None] = mapped_column(String(80))
    vehicle_model: Mapped[str | None] = mapped_column(String(80))
    vehicle_variant: Mapped[str | None] = mapped_column(String(80))
    vehicle_year: Mapped[int | None] = mapped_column(Integer)
    vehicle_year_min: Mapped[int | None] = mapped_column(Integer)
    vehicle_year_max: Mapped[int | None] = mapped_column(Integer)
    vehicle_color: Mapped[str | None] = mapped_column(String(40))
    vehicle_type: Mapped[str | None] = mapped_column(String(40))
    vehicle_confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)

    # Number plate.
    detected_registration: Mapped[str | None] = mapped_column(String(32))
    ocr_confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)
    registration_confirmed_by_customer: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    confirmed_registration: Mapped[str | None] = mapped_column(String(32))

    # Reconciliation with what the customer stated.
    vehicle_conflict: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vehicle_conflict_detail: Mapped[str | None] = mapped_column(Text)

    damage_confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)
    summary_text: Mapped[str | None] = mapped_column(Text)
    stage_confidences: Mapped[dict[str, Any]] = mapped_column(JSONDoc, default=dict, nullable=False)
    notes: Mapped[list[str]] = mapped_column(JSONDoc, default=list, nullable=False)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONDoc, default=dict, nullable=False)

    # Agent corrections live alongside, never on top of, the model output.
    agent_corrected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    agent_corrections: Mapped[dict[str, Any]] = mapped_column(JSONDoc, default=dict, nullable=False)
    corrected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )

    claim: Mapped["Claim"] = relationship(back_populates="assessments")
    damaged_parts: Mapped[list["DamagedPart"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )

    @property
    def effective_registration(self) -> str | None:
        return self.confirmed_registration or self.detected_registration

    @property
    def vehicle_label(self) -> str:
        parts = [str(p) for p in (self.vehicle_make, self.vehicle_model, self.vehicle_year) if p]
        return " ".join(parts) if parts else "Vehicle not identified"


class DamagedPart(Base, UUIDPrimaryKey, Timestamped):
    """A single damaged component.

    The `customer_reported` / `ai_detected` pair is the reconciliation record: a row with
    only one of them set is a disagreement the agent needs to resolve.
    """

    __tablename__ = "damaged_parts"
    __table_args__ = (Index("ix_damaged_parts_assessment", "assessment_id"),)

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("damage_assessments.id", ondelete="CASCADE"), nullable=False
    )
    image_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("claim_images.id", ondelete="SET NULL")
    )

    canonical_part: Mapped[str] = mapped_column(String(48), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    damage_type: Mapped[DamageType] = mapped_column(
        enum_type(DamageType), default=DamageType.UNKNOWN, nullable=False
    )
    severity: Mapped[DamageSeverity] = mapped_column(
        enum_type(DamageSeverity), default=DamageSeverity.LOW, nullable=False
    )
    confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)

    # Normalised 0–1 so overlays survive any display size.
    bounding_box: Mapped[dict[str, float] | None] = mapped_column(JSONDoc)

    recommended_action: Mapped[RepairAction] = mapped_column(
        enum_type(RepairAction), default=RepairAction.INSPECT, nullable=False
    )
    action_rationale: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)

    customer_reported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    agent_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    agent_note: Mapped[str | None] = mapped_column(Text)

    labour_hours: Mapped[float | None] = mapped_column(Float)
    paint_panels: Mapped[float | None] = mapped_column(Float)

    assessment: Mapped[DamageAssessment] = relationship(back_populates="damaged_parts")
    price_sources: Mapped[list["PartPriceSource"]] = relationship(
        back_populates="damaged_part", cascade="all, delete-orphan"
    )
    price_summary: Mapped["PartPriceSummary | None"] = relationship(
        back_populates="damaged_part", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def agreement(self) -> str:
        if self.customer_reported and self.ai_detected:
            return "CONFIRMED_BY_BOTH"
        if self.ai_detected:
            return "AI_ONLY"
        return "CUSTOMER_ONLY"

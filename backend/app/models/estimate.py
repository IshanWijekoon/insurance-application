"""Repair estimates and their per-part derivation."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from app.db.types import GUID, JSONDoc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RepairAction
from app.db.base import Base, Timestamped, UUIDPrimaryKey
from app.db.types import CONFIDENCE, MONEY, RATIO, enum_type

if TYPE_CHECKING:
    from app.models.claim import Claim


class RepairEstimate(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "repair_estimates"
    __table_args__ = (Index("ix_repair_estimates_claim", "claim_id", "created_at"),)

    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )

    estimated_min: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    estimated_max: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="LKR", nullable=False)

    parts_subtotal_min: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    parts_subtotal_max: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    labour_min: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    labour_max: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    paint_min: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    paint_max: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    materials_min: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    materials_max: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)

    confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)
    damage_to_value_ratio: Mapped[Decimal | None] = mapped_column(RATIO)

    # Parts the estimate could not cost. Their absence is stated rather than guessed at,
    # and the estimate is presented as a partial figure.
    unpriced_parts: Mapped[list[str]] = mapped_column(JSONDoc, default=list, nullable=False)
    is_partial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    labour_rate_used: Mapped[float | None] = mapped_column(Float)
    paint_rate_used: Mapped[float | None] = mapped_column(Float)
    calculation_notes: Mapped[str | None] = mapped_column(Text)

    # Agent adjustments sit beside the AI figures; both are displayed.
    superseded_by_agent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    agent_adjusted_min: Mapped[Decimal | None] = mapped_column(MONEY)
    agent_adjusted_max: Mapped[Decimal | None] = mapped_column(MONEY)
    agent_adjustment_reason: Mapped[str | None] = mapped_column(Text)
    adjusted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )

    claim: Mapped["Claim"] = relationship(back_populates="estimates")
    lines: Mapped[list["RepairEstimateLine"]] = relationship(
        back_populates="estimate", cascade="all, delete-orphan"
    )


class RepairEstimateLine(Base, UUIDPrimaryKey, Timestamped):
    """One costed part.

    `basis` is a plain-English derivation ("crack + HIGH severity on a thermoplastic bumper
    ⇒ replace; part range from 3 sources"). It is what the explainability UI expands, and
    it is written by the estimator, not by the model.
    """

    __tablename__ = "repair_estimate_lines"
    __table_args__ = (Index("ix_repair_estimate_lines_estimate", "estimate_id"),)

    estimate_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("repair_estimates.id", ondelete="CASCADE"), nullable=False
    )
    damaged_part_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("damaged_parts.id", ondelete="SET NULL")
    )

    canonical_part: Mapped[str] = mapped_column(String(48), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[RepairAction] = mapped_column(enum_type(RepairAction), nullable=False)

    part_price_min: Mapped[Decimal | None] = mapped_column(MONEY)
    part_price_max: Mapped[Decimal | None] = mapped_column(MONEY)
    part_price_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    labour_hours: Mapped[float | None] = mapped_column(Float)
    labour_rate: Mapped[float | None] = mapped_column(Float)
    labour_min: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    labour_max: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)

    paint_panels: Mapped[float | None] = mapped_column(Float)
    paint_min: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    paint_max: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)

    line_min: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    line_max: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="LKR", nullable=False)

    basis: Mapped[str] = mapped_column(Text, nullable=False)
    price_source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)

    estimate: Mapped[RepairEstimate] = relationship(back_populates="lines")

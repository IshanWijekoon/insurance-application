"""Vehicles and insurance policies.

Only the owning customer is required on a vehicle. Make, model, year and registration are
all nullable because a customer reporting an accident may know none of them — the AI is
expected to fill the gaps from images, and the two sources are then reconciled.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String
from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import PolicyStatus
from app.db.base import Base, SoftDeletable, Timestamped, UUIDPrimaryKey
from app.db.types import MONEY, enum_type

if TYPE_CHECKING:
    from app.models.claim import Claim
    from app.models.user import Customer


class Vehicle(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "vehicles"
    __table_args__ = (
        Index("ix_vehicles_customer", "customer_id"),
        Index("ix_vehicles_registration", "registration_number"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    registration_number: Mapped[str | None] = mapped_column(String(32))
    make: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    variant: Mapped[str | None] = mapped_column(String(80))
    year: Mapped[int | None] = mapped_column(Integer)
    vehicle_type: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(40))
    vin: Mapped[str | None] = mapped_column(String(40))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    customer: Mapped["Customer"] = relationship(back_populates="vehicles")
    policies: Mapped[list["InsurancePolicy"]] = relationship(back_populates="vehicle")
    claims: Mapped[list["Claim"]] = relationship(back_populates="vehicle")

    @property
    def display_name(self) -> str:
        parts = [str(p) for p in (self.make, self.model, self.year) if p]
        return " ".join(parts) if parts else (self.registration_number or "Unspecified vehicle")


class InsurancePolicy(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "insurance_policies"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    policy_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    insurer_name: Mapped[str | None] = mapped_column(String(160))
    policy_type: Mapped[str | None] = mapped_column(String(60))
    coverage_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    deductible: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), default="LKR", nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[PolicyStatus] = mapped_column(
        enum_type(PolicyStatus), default=PolicyStatus.ACTIVE, nullable=False
    )

    vehicle: Mapped[Vehicle] = relationship(back_populates="policies")
    claims: Mapped[list["Claim"]] = relationship(back_populates="policy")

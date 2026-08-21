"""Market research: the source whitelist, vehicle valuations and part prices.

Two invariants hold across this module:

1. Every price row names its source and records when it was retrieved.
2. When nothing usable is found the summary row says ``UNAVAILABLE`` with a reason.
   There is no fallback figure, no average of nothing, no placeholder.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    DataStatus,
    MarketSourceCategory,
    MarketSourceType,
    PartGrade,
)
from app.db.base import Base, Timestamped, UUIDPrimaryKey
from app.db.types import CONFIDENCE, MONEY, enum_type

if TYPE_CHECKING:
    from app.models.assessment import DamagedPart
    from app.models.claim import Claim


class MarketSource(Base, UUIDPrimaryKey, Timestamped):
    """The fetch whitelist. A host that is not enabled here is never contacted."""

    __tablename__ = "market_sources"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(400), nullable=False)
    source_type: Mapped[MarketSourceType] = mapped_column(
        enum_type(MarketSourceType), default=MarketSourceType.SCRAPE, nullable=False
    )
    category: Mapped[MarketSourceCategory] = mapped_column(
        enum_type(MarketSourceCategory), default=MarketSourceCategory.BOTH, nullable=False
    )
    country: Mapped[str] = mapped_column(String(2), default="LK", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="LKR", nullable=False)

    # Weighs this source when aggregating prices and computing price confidence.
    reliability_weight: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    robots_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    robots_allows: Mapped[bool | None] = mapped_column(Boolean)
    requires_api_key: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parser_key: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def is_fetchable(self) -> bool:
        """Enabled, and either an API/dataset or a scrape target robots.txt permits."""
        if not self.is_enabled:
            return False
        if self.source_type in {MarketSourceType.API, MarketSourceType.DATASET}:
            return True
        return self.robots_allows is True


class VehicleValuation(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "vehicle_valuations"
    __table_args__ = (Index("ix_vehicle_valuations_claim", "claim_id", "created_at"),)

    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    make: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    year: Mapped[int | None] = mapped_column(Integer)
    country: Mapped[str] = mapped_column(String(2), default="LK", nullable=False)

    status: Mapped[DataStatus] = mapped_column(
        enum_type(DataStatus), default=DataStatus.UNAVAILABLE, nullable=False
    )
    unavailable_reason: Mapped[str | None] = mapped_column(Text)

    estimated_min: Mapped[Decimal | None] = mapped_column(MONEY)
    estimated_max: Mapped[Decimal | None] = mapped_column(MONEY)
    median_value: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), default="LKR", nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)
    confidence_reason: Mapped[str | None] = mapped_column(Text)
    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    claim: Mapped["Claim"] = relationship(back_populates="valuations")
    sources: Mapped[list["VehicleValuationSource"]] = relationship(
        back_populates="valuation", cascade="all, delete-orphan"
    )


class VehicleValuationSource(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "vehicle_valuation_sources"

    valuation_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("vehicle_valuations.id", ondelete="CASCADE"), nullable=False
    )
    market_source_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("market_sources.id", ondelete="SET NULL")
    )
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    listing_title: Mapped[str | None] = mapped_column(String(400))
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    listing_year: Mapped[int | None] = mapped_column(Integer)
    mileage_km: Mapped[int | None] = mapped_column(Integer)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_excerpt: Mapped[str | None] = mapped_column(Text)

    valuation: Mapped[VehicleValuation] = relationship(back_populates="sources")


class PartPriceSource(Base, UUIDPrimaryKey, Timestamped):
    """One retrieved price for one damaged part. `retrieved_at` is mandatory."""

    __tablename__ = "part_price_sources"
    __table_args__ = (
        Index("ix_part_price_sources_claim", "claim_id"),
        Index("ix_part_price_sources_part", "damaged_part_id"),
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    damaged_part_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("damaged_parts.id", ondelete="CASCADE"), nullable=False
    )
    market_source_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("market_sources.id", ondelete="SET NULL")
    )

    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    product_name: Mapped[str] = mapped_column(String(400), nullable=False)
    canonical_part: Mapped[str] = mapped_column(String(48), nullable=False)

    vehicle_compatibility: Mapped[str | None] = mapped_column(String(200))
    compatibility_confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)
    part_grade: Mapped[PartGrade] = mapped_column(
        enum_type(PartGrade), default=PartGrade.UNKNOWN, nullable=False
    )

    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    availability: Mapped[str | None] = mapped_column(String(60))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_excerpt: Mapped[str | None] = mapped_column(Text)
    excluded_from_summary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(200))

    damaged_part: Mapped["DamagedPart"] = relationship(back_populates="price_sources")


class PartPriceSummary(Base, UUIDPrimaryKey, Timestamped):
    """Aggregate of the price rows for one part, or an explicit statement that none exist."""

    __tablename__ = "part_price_summaries"

    damaged_part_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("damaged_parts.id", ondelete="CASCADE"),
        unique=True, nullable=False,
    )
    status: Mapped[DataStatus] = mapped_column(
        enum_type(DataStatus), default=DataStatus.UNAVAILABLE, nullable=False
    )
    unavailable_reason: Mapped[str | None] = mapped_column(Text)

    price_min: Mapped[Decimal | None] = mapped_column(MONEY)
    price_max: Mapped[Decimal | None] = mapped_column(MONEY)
    price_median: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), default="LKR", nullable=False)

    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dominant_grade: Mapped[PartGrade | None] = mapped_column(enum_type(PartGrade))
    price_confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)
    confidence_reason: Mapped[str | None] = mapped_column(Text)

    damaged_part: Mapped["DamagedPart"] = relationship(back_populates="price_summary")

    @property
    def requires_manual_verification(self) -> bool:
        return self.status is DataStatus.UNAVAILABLE

"""Structured contracts for every AI stage.

No model output is persisted until it validates against one of these. A model that cannot
produce a conforming object is retried, then failed over, then recorded as a skipped stage —
it is never coerced into the database with best-effort parsing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import DamageSeverity, DamageType, RepairAction
from app.core.parts import PARTS_BY_CODE


class StrictModel(BaseModel):
    # Extra keys are dropped rather than rejected: a model adding a field it was not asked
    # for should not invalidate an otherwise-correct assessment.
    model_config = ConfigDict(extra="ignore")


class CustomerInputExtraction(StrictModel):
    """Structured reading of the customer's free-text description.

    Everything here is *reported*, not confirmed. `possible_damage_parts` seeds the
    reconciliation view; it never creates a damaged-part record on its own.
    """

    possible_damage_parts: list[str] = Field(default_factory=list)
    possible_impact_area: str | None = None
    mentioned_location: str | None = None
    mentioned_datetime: str | None = None
    third_party_involved: bool | None = None
    injuries_mentioned: bool | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    notes: list[str] = Field(default_factory=list)

    @field_validator("possible_damage_parts")
    @classmethod
    def known_codes_only(cls, v: list[str]) -> list[str]:
        return [code for code in v if code in PARTS_BY_CODE]


class VehicleIdentification(StrictModel):
    make: str | None = None
    model: str | None = None
    variant: str | None = None
    year_estimate: int | None = None
    year_range: list[int] | None = None
    color: str | None = None
    vehicle_type: str | None = None
    orientation: str | None = None
    vehicle_visible: bool = True
    multiple_vehicles: bool = False
    confidence: float = Field(default=0.0, ge=0, le=1)
    notes: list[str] = Field(default_factory=list)

    @field_validator("year_estimate")
    @classmethod
    def plausible_year(cls, v: int | None) -> int | None:
        # A model guessing "year 20" or "year 3018" is hallucinating; drop it rather than
        # letting it flow into a valuation query.
        return v if v is not None and 1950 <= v <= 2100 else None

    @field_validator("year_range")
    @classmethod
    def plausible_range(cls, v: list[int] | None) -> list[int] | None:
        if not v or len(v) != 2:
            return None
        low, high = sorted(v)
        return [low, high] if 1950 <= low <= high <= 2100 else None


class PlateReading(StrictModel):
    plate_visible: bool = False
    registration_number: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    country_format_guess: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("registration_number")
    @classmethod
    def tidy(cls, v: str | None) -> str | None:
        if not v:
            return None
        cleaned = " ".join(v.upper().split())
        return cleaned if 2 <= len(cleaned) <= 32 else None


class BoundingBox(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class DetectedDamage(StrictModel):
    canonical_part: str
    display_name: str | None = None
    damage_type: DamageType = DamageType.UNKNOWN
    severity: DamageSeverity = DamageSeverity.LOW
    confidence: float = Field(default=0.0, ge=0, le=1)
    bounding_box: BoundingBox | None = None
    recommended_action: RepairAction = RepairAction.INSPECT
    explanation: str | None = None

    @field_validator("canonical_part")
    @classmethod
    def must_be_known(cls, v: str) -> str:
        code = v.strip().upper().replace(" ", "_")
        if code not in PARTS_BY_CODE:
            raise ValueError(f"'{v}' is not a canonical part code.")
        return code


class ImageDamageAnalysis(StrictModel):
    vehicle_visible: bool = True
    multiple_vehicles: bool = False
    quality_sufficient: bool = True
    damages: list[DetectedDamage] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PartNormalization(StrictModel):
    """Maps a scraped product title to a canonical part, or declines to."""

    canonical_part: str | None = None
    part_grade: str | None = None
    vehicle_compatibility: str | None = None
    compatibility_confidence: float = Field(default=0.0, ge=0, le=1)
    is_relevant: bool = False
    notes: list[str] = Field(default_factory=list)

    @field_validator("canonical_part")
    @classmethod
    def known_or_none(cls, v: str | None) -> str | None:
        if not v:
            return None
        code = v.strip().upper().replace(" ", "_")
        return code if code in PARTS_BY_CODE else None


class MarketListingInterpretation(StrictModel):
    price: float | None = None
    currency: str | None = None
    title: str | None = None
    year: int | None = None
    mileage_km: int | None = None
    is_relevant: bool = False
    relevance_reason: str | None = None


class MarketInterpretation(StrictModel):
    listings: list[MarketListingInterpretation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EstimateReasoningItem(StrictModel):
    """The model's judgement calls only.

    It decides repair vs replace and estimates labour hours. It does not multiply, total or
    produce currency amounts — that arithmetic lives in `app/estimation` where it is
    deterministic and unit-tested.
    """

    canonical_part: str
    action: RepairAction = RepairAction.INSPECT
    action_rationale: str | None = None
    labour_hours_estimate: float | None = Field(default=None, ge=0, le=80)
    paint_panels: float | None = Field(default=None, ge=0, le=10)
    confidence: float = Field(default=0.5, ge=0, le=1)

    @field_validator("canonical_part")
    @classmethod
    def must_be_known(cls, v: str) -> str:
        code = v.strip().upper().replace(" ", "_")
        if code not in PARTS_BY_CODE:
            raise ValueError(f"'{v}' is not a canonical part code.")
        return code


class EstimateReasoning(StrictModel):
    items: list[EstimateReasoningItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ClaimSummary(StrictModel):
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)

    @field_validator("summary")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("The summary must not be empty.")
        return v.strip()

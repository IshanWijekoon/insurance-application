"""Claim contracts: creation, evidence, assessment read models and agent actions."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enums import (
    ActorType,
    AnnotationType,
    ClaimPriority,
    ClaimStatus,
    DamageSeverity,
    DamageType,
    ImageRole,
    ImageValidationStatus,
    LocationSource,
    NoteVisibility,
    PartGrade,
    RepairAction,
    RiskLevel,
)
from app.core.parts import PARTS_BY_CODE
from app.schemas.common import MoneyRange, ORMModel

# ── Creation and editing ────────────────────────────────────


class ClaimCreate(BaseModel):
    vehicle_id: uuid.UUID | None = None
    policy_id: uuid.UUID | None = None
    accident_datetime: datetime | None = None
    accident_description: str | None = Field(default=None, max_length=5000)
    customer_vehicle_description: str | None = Field(default=None, max_length=2000)

    stated_make: str | None = Field(default=None, max_length=80)
    stated_model: str | None = Field(default=None, max_length=80)
    stated_variant: str | None = Field(default=None, max_length=80)
    stated_year: int | None = Field(default=None, ge=1900, le=2100)
    stated_color: str | None = Field(default=None, max_length=40)
    stated_registration: str | None = Field(default=None, max_length=32)

    @field_validator("accident_datetime")
    @classmethod
    def not_in_future(cls, v: datetime | None) -> datetime | None:
        if v and v.timestamp() > datetime.now(v.tzinfo).timestamp():
            raise ValueError("The accident cannot be in the future.")
        return v


class ClaimUpdate(ClaimCreate):
    pass


class DamageReportRequest(BaseModel):
    """What the customer believes is damaged. Verified against images, never trusted alone."""

    reported_parts: list[str] = Field(default_factory=list)
    free_text_parts: str | None = Field(default=None, max_length=2000)

    @field_validator("reported_parts")
    @classmethod
    def known_parts_only(cls, v: list[str]) -> list[str]:
        unknown = [p for p in v if p not in PARTS_BY_CODE]
        if unknown:
            raise ValueError(
                "Unknown part codes: " + ", ".join(unknown) + ". Use the free-text field instead."
            )
        return sorted(set(v))


class AnnotationRegion(BaseModel):
    annotation_type: AnnotationType
    label: str = Field(default="customer_selected_damage", max_length=120)
    points: list[list[float]] = Field(min_length=1)
    color: str | None = Field(default=None, max_length=16)
    stroke_width: int = Field(default=3, ge=1, le=40)
    text_content: str | None = Field(default=None, max_length=400)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def shape_matches_type(self) -> "AnnotationRegion":
        needed = {
            AnnotationType.RECTANGLE: 2,
            AnnotationType.CIRCLE: 2,
            AnnotationType.POLYGON: 3,
            AnnotationType.FREEHAND: 2,
            AnnotationType.TEXT: 1,
        }[self.annotation_type]
        if len(self.points) < needed:
            raise ValueError(
                f"{self.annotation_type.value} requires at least {needed} point(s)."
            )
        if any(len(p) != 2 for p in self.points):
            raise ValueError("Each point must be an [x, y] pair in image pixel coordinates.")
        return self


class AnnotationRequest(BaseModel):
    regions: list[AnnotationRegion]
    replace_existing: bool = True


class ImageNoteRequest(BaseModel):
    customer_note: str | None = Field(default=None, max_length=2000)
    image_role: ImageRole | None = None


class LocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    source: LocationSource
    accuracy_meters: float | None = Field(default=None, ge=0)
    address: str | None = Field(default=None, max_length=400)

    @field_validator("source")
    @classmethod
    def client_cannot_claim_exif(cls, v: LocationSource) -> LocationSource:
        # EXIF-derived locations are written by the metadata extractor from the file itself.
        # Accepting EXIF_GPS from the client would let a caller launder an arbitrary point
        # into the record as photo-verified evidence.
        if v is LocationSource.EXIF_GPS:
            raise ValueError("EXIF locations are derived from the image, not submitted.")
        return v


class RegistrationConfirmRequest(BaseModel):
    registration_number: str = Field(min_length=2, max_length=32)

    @field_validator("registration_number")
    @classmethod
    def normalise(cls, v: str) -> str:
        return " ".join(v.upper().split())


# ── Read models ─────────────────────────────────────────────


class ImageMetadataResponse(ORMModel):
    has_exif: bool
    captured_at: datetime | None = None
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    camera_make: str | None = None
    camera_model: str | None = None


class AnnotationResponse(ORMModel):
    id: uuid.UUID
    annotation_type: AnnotationType
    label: str
    points: list[list[float]]
    color: str | None = None
    stroke_width: int
    text_content: str | None = None
    note: str | None = None


class ClaimImageResponse(ORMModel):
    id: uuid.UUID
    image_role: ImageRole
    original_filename: str | None = None
    mime_type: str
    file_size: int
    width: int | None = None
    height: int | None = None
    quality_score: float | None = None
    blur_score: float | None = None
    validation_status: ImageValidationStatus
    validation_errors: list[str]
    customer_note: str | None = None
    created_at: datetime

    url: str | None = None
    annotated_url: str | None = None
    image_metadata: ImageMetadataResponse | None = None
    annotations: list[AnnotationResponse] = Field(default_factory=list)


class DamagedPartResponse(ORMModel):
    id: uuid.UUID
    canonical_part: str
    display_name: str
    damage_type: DamageType
    severity: DamageSeverity
    confidence: float | None = None
    bounding_box: dict[str, float] | None = None
    recommended_action: RepairAction
    action_rationale: str | None = None
    explanation: str | None = None
    customer_reported: bool
    ai_detected: bool
    agent_confirmed: bool | None = None
    agreement: str
    image_id: uuid.UUID | None = None
    price: MoneyRange | None = None


class VehicleIdentificationResponse(BaseModel):
    make: str | None = None
    model: str | None = None
    variant: str | None = None
    year: int | None = None
    color: str | None = None
    vehicle_type: str | None = None
    confidence: float | None = None
    registration_number: str | None = None
    ocr_confidence: float | None = None
    registration_confirmed: bool = False
    conflict_with_customer: bool = False
    conflict_detail: str | None = None


class ReconciliationResponse(BaseModel):
    """Customer-reported vs AI-detected damage, as an explicit diff."""

    customer_reported: list[str]
    ai_detected: list[str]
    confirmed_by_both: list[str]
    ai_only: list[str]
    customer_only: list[str]
    summary: str
    manual_verification_recommended: bool


class AssessmentResponse(BaseModel):
    claim_id: uuid.UUID
    status: ClaimStatus
    generated_at: datetime | None = None
    provider: str | None = None
    model: str | None = None
    vehicle: VehicleIdentificationResponse | None = None
    damaged_parts: list[DamagedPartResponse] = Field(default_factory=list)
    reconciliation: ReconciliationResponse | None = None
    summary_text: str | None = None
    stage_confidences: dict[str, float] = Field(default_factory=dict)
    overall_confidence: float | None = None
    manual_review_required: bool = True
    manual_review_reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    disclaimer: str


class PriceSourceResponse(ORMModel):
    id: uuid.UUID
    source_name: str
    url: str | None = None
    product_name: str
    vehicle_compatibility: str | None = None
    part_grade: PartGrade
    price: Decimal
    currency: str
    availability: str | None = None
    retrieved_at: datetime
    excluded_from_summary: bool
    exclusion_reason: str | None = None


class PartPriceResponse(BaseModel):
    damaged_part_id: uuid.UUID
    canonical_part: str
    display_name: str
    price: MoneyRange
    dominant_grade: PartGrade | None = None
    confidence_reason: str | None = None
    sources: list[PriceSourceResponse] = Field(default_factory=list)


class ValuationSourceResponse(ORMModel):
    source_name: str
    url: str | None = None
    listing_title: str | None = None
    price: Decimal
    currency: str
    listing_year: int | None = None
    mileage_km: int | None = None
    retrieved_at: datetime


class MarketDataResponse(BaseModel):
    claim_id: uuid.UUID
    vehicle_label: str | None = None
    valuation: MoneyRange
    confidence_reason: str | None = None
    sources: list[ValuationSourceResponse] = Field(default_factory=list)


class EstimateLineResponse(ORMModel):
    canonical_part: str
    display_name: str
    action: RepairAction
    part_price_available: bool
    part_price_min: Decimal | None = None
    part_price_max: Decimal | None = None
    labour_hours: float | None = None
    labour_min: Decimal
    labour_max: Decimal
    paint_min: Decimal
    paint_max: Decimal
    line_min: Decimal
    line_max: Decimal
    currency: str
    basis: str
    price_source_count: int
    confidence: float | None = None


class EstimateResponse(BaseModel):
    claim_id: uuid.UUID
    total: MoneyRange
    parts_subtotal_min: Decimal | None = None
    parts_subtotal_max: Decimal | None = None
    labour_min: Decimal | None = None
    labour_max: Decimal | None = None
    paint_min: Decimal | None = None
    paint_max: Decimal | None = None
    materials_min: Decimal | None = None
    materials_max: Decimal | None = None
    lines: list[EstimateLineResponse] = Field(default_factory=list)
    is_partial: bool = False
    unpriced_parts: list[str] = Field(default_factory=list)
    damage_to_value_ratio: float | None = None
    labour_rate_used: float | None = None
    paint_rate_used: float | None = None
    calculation_notes: str | None = None
    agent_adjusted_min: Decimal | None = None
    agent_adjusted_max: Decimal | None = None
    agent_adjustment_reason: str | None = None
    disclaimer: str


class LocationResponse(ORMModel):
    latitude: float
    longitude: float
    address: str | None = None
    city: str | None = None
    country: str | None = None
    source: LocationSource
    accuracy_meters: float | None = None


class FraudSignalResponse(ORMModel):
    signal_code: str
    risk_level: RiskLevel
    description: str
    evidence: dict = Field(default_factory=dict)


class TimelineEvent(BaseModel):
    at: datetime
    kind: str
    actor_type: ActorType | None = None
    actor_name: str | None = None
    title: str
    detail: str | None = None


class ClaimNoteResponse(ORMModel):
    id: uuid.UUID
    body: str
    visibility: NoteVisibility
    created_at: datetime
    author_name: str | None = None


class ClaimSummaryResponse(ORMModel):
    """Row shape for claim lists and the agent queue."""

    id: uuid.UUID
    claim_number: str
    status: ClaimStatus
    priority: ClaimPriority
    vehicle_label: str | None = None
    customer_name: str | None = None
    image_count: int = 0
    damaged_part_count: int = 0
    estimate: MoneyRange | None = None
    location_label: str | None = None
    location_latitude: float | None = None
    location_longitude: float | None = None
    location_source: LocationSource | None = None
    thumbnail_url: str | None = None
    accident_datetime: datetime | None = None
    photo_captured_at: datetime | None = None
    assigned_agent_name: str | None = None
    manual_review_required: bool = True
    overall_confidence: float | None = None
    created_at: datetime
    submitted_at: datetime | None = None


class ClaimDetailResponse(BaseModel):
    id: uuid.UUID
    claim_number: str
    status: ClaimStatus
    priority: ClaimPriority
    created_at: datetime
    submitted_at: datetime | None = None
    ai_completed_at: datetime | None = None

    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    policy_number: str | None = None

    vehicle: dict[str, str | int | None] = Field(default_factory=dict)
    accident_datetime: datetime | None = None
    accident_description: str | None = None
    customer_vehicle_description: str | None = None
    customer_reported_parts: list[str] = Field(default_factory=list)
    customer_free_text_parts: str | None = None

    images: list[ClaimImageResponse] = Field(default_factory=list)
    assessment: AssessmentResponse | None = None
    estimate: EstimateResponse | None = None
    market_data: MarketDataResponse | None = None
    part_prices: list[PartPriceResponse] = Field(default_factory=list)
    location: LocationResponse | None = None
    fraud_signals: list[FraudSignalResponse] = Field(default_factory=list)
    notes: list[ClaimNoteResponse] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)

    manual_review_required: bool = True
    manual_review_reasons: list[str] = Field(default_factory=list)
    pipeline_stage: str | None = None
    pipeline_progress: dict = Field(default_factory=dict)


class ClaimStatusResponse(BaseModel):
    """Polling fallback for the WebSocket progress stream."""

    claim_id: uuid.UUID
    status: ClaimStatus
    pipeline_stage: str | None = None
    progress: dict = Field(default_factory=dict)
    ai_completed_at: datetime | None = None
    manual_review_required: bool = True


# ── Agent actions ───────────────────────────────────────────


class AgentNoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    visibility: NoteVisibility = NoteVisibility.INTERNAL


class AssessmentCorrectionPart(BaseModel):
    damaged_part_id: uuid.UUID
    agent_confirmed: bool | None = None
    damage_type: DamageType | None = None
    severity: DamageSeverity | None = None
    recommended_action: RepairAction | None = None
    agent_note: str | None = Field(default=None, max_length=2000)


class AssessmentCorrectionRequest(BaseModel):
    """Agent corrections. The original AI output is retained and shown alongside."""

    vehicle_make: str | None = Field(default=None, max_length=80)
    vehicle_model: str | None = Field(default=None, max_length=80)
    vehicle_year: int | None = Field(default=None, ge=1900, le=2100)
    registration_number: str | None = Field(default=None, max_length=32)
    parts: list[AssessmentCorrectionPart] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=2000)


class EstimateAdjustmentRequest(BaseModel):
    adjusted_min: Decimal = Field(ge=0)
    adjusted_max: Decimal = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordered(self) -> "EstimateAdjustmentRequest":
        if self.adjusted_max < self.adjusted_min:
            raise ValueError("The maximum must not be below the minimum.")
        return self


class InformationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    requested_items: list[str] = Field(default_factory=list)


class DecisionRequest(BaseModel):
    decision: ClaimStatus
    reason: str = Field(min_length=1, max_length=2000)
    approved_amount: Decimal | None = Field(default=None, ge=0)

    @field_validator("decision")
    @classmethod
    def allowed_decision(cls, v: ClaimStatus) -> ClaimStatus:
        allowed = {ClaimStatus.APPROVED, ClaimStatus.REJECTED, ClaimStatus.AGENT_REVIEW}
        if v not in allowed:
            raise ValueError("Decision must be APPROVED, REJECTED or AGENT_REVIEW.")
        return v


class VerifyRequest(DecisionRequest):
    """Agent confirmation that the claim report was reviewed before a decision."""

    images_reviewed: bool
    cost_reviewed: bool
    location_reviewed: bool
    time_reviewed: bool

    @model_validator(mode="after")
    def approval_requires_full_review(self) -> "VerifyRequest":
        if self.decision is ClaimStatus.APPROVED:
            missing = [
                label
                for ok, label in (
                    (self.images_reviewed, "images"),
                    (self.cost_reviewed, "cost"),
                    (self.location_reviewed, "location"),
                    (self.time_reviewed, "time"),
                )
                if not ok
            ]
            if missing:
                raise ValueError(
                    "Approve only after reviewing " + ", ".join(missing) + "."
                )
        return self


class AgentDashboardResponse(BaseModel):
    total_claims: int
    new_claims: int
    under_review: int
    high_priority: int
    approved: int
    rejected: int
    pending_information: int
    awaiting_manual_review: int

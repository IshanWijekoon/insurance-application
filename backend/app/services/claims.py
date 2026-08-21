"""Claim lifecycle: creation, evidence attachment, submission and status transitions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import (
    ActorType,
    ClaimPriority,
    ClaimStatus,
    ImageValidationStatus,
    NoteVisibility,
    UserRole,
)
from app.core.errors import ConflictError, InvalidClaimStateError, NotFoundError, ValidationError_
from app.core.logging import get_logger
from app.core.parts import part_display_name
from app.models.claim import Claim, ClaimLocation, ClaimNote, ClaimStatusEvent
from app.models.image import ClaimImage, CustomerDamageReport
from app.models.user import Customer, User
from app.models.vehicle import InsurancePolicy, Vehicle
from app.schemas.claim import (
    AssessmentCorrectionRequest,
    ClaimCreate,
    ClaimUpdate,
    DamageReportRequest,
    DecisionRequest,
    EstimateAdjustmentRequest,
    InformationRequest,
    LocationRequest,
)
from app.services import audit

log = get_logger(__name__)

# Which transitions are legal. Anything not listed is rejected, so a claim cannot skip
# from DRAFT straight to APPROVED because of a malformed request.
ALLOWED_TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    ClaimStatus.DRAFT: {ClaimStatus.SUBMITTED},
    ClaimStatus.SUBMITTED: {ClaimStatus.PROCESSING, ClaimStatus.AGENT_REVIEW},
    ClaimStatus.PROCESSING: {ClaimStatus.AI_ANALYZING, ClaimStatus.AGENT_REVIEW},
    ClaimStatus.AI_ANALYZING: {ClaimStatus.MARKET_RESEARCH, ClaimStatus.AGENT_REVIEW},
    ClaimStatus.MARKET_RESEARCH: {ClaimStatus.ESTIMATING, ClaimStatus.AGENT_REVIEW},
    ClaimStatus.ESTIMATING: {ClaimStatus.AI_COMPLETED, ClaimStatus.AGENT_REVIEW},
    ClaimStatus.AI_COMPLETED: {ClaimStatus.AGENT_REVIEW},
    ClaimStatus.AGENT_REVIEW: {
        ClaimStatus.MORE_INFORMATION_REQUIRED,
        ClaimStatus.APPROVED,
        ClaimStatus.REJECTED,
        ClaimStatus.PROCESSING,
    },
    ClaimStatus.MORE_INFORMATION_REQUIRED: {ClaimStatus.SUBMITTED, ClaimStatus.AGENT_REVIEW},
    ClaimStatus.APPROVED: {ClaimStatus.SETTLEMENT_PROCESSING, ClaimStatus.AGENT_REVIEW},
    ClaimStatus.SETTLEMENT_PROCESSING: {ClaimStatus.COMPLETED},
    ClaimStatus.REJECTED: {ClaimStatus.AGENT_REVIEW},
    ClaimStatus.COMPLETED: set(),
}


class ClaimService:
    def __init__(self, db: Session):
        self.db = db

    # ── Numbering ───────────────────────────────────────────

    def generate_claim_number(self) -> str:
        year = datetime.now(UTC).year
        prefix = f"CLM-{year}-"
        count = self.db.scalar(
            select(func.count()).select_from(Claim).where(Claim.claim_number.like(f"{prefix}%"))
        )
        # Collisions are possible under concurrency; the unique index is the real guard and
        # the retry loop resolves the rare clash.
        for offset in range(1, 50):
            candidate = f"{prefix}{(count or 0) + offset:06d}"
            if not self.db.scalar(select(Claim.id).where(Claim.claim_number == candidate)):
                return candidate
        return f"{prefix}{uuid.uuid4().hex[:6].upper()}"

    # ── Retrieval ───────────────────────────────────────────

    def get(self, claim_id: uuid.UUID, *, with_evidence: bool = False) -> Claim:
        query = select(Claim).where(Claim.id == claim_id, Claim.deleted_at.is_(None))
        if with_evidence:
            query = query.options(
                selectinload(Claim.images).selectinload(ClaimImage.image_metadata),
                selectinload(Claim.images).selectinload(ClaimImage.annotations),
                selectinload(Claim.damage_report),
                selectinload(Claim.assessments),
                selectinload(Claim.estimates),
                selectinload(Claim.valuations),
                selectinload(Claim.status_events),
                selectinload(Claim.notes),
                selectinload(Claim.fraud_signals),
                selectinload(Claim.location),
                selectinload(Claim.vehicle),
            )
        claim = self.db.scalar(query)
        if claim is None:
            raise NotFoundError("Claim not found.")
        return claim

    def get_for_user(
        self, claim_id: uuid.UUID, user: User, *, with_evidence: bool = False
    ) -> Claim:
        claim = self.get(claim_id, with_evidence=with_evidence)
        if user.role is UserRole.CUSTOMER:
            customer = self.db.scalar(select(Customer).where(Customer.user_id == user.id))
            if customer is None or claim.customer_id != customer.id:
                # Deliberately a 404: confirming existence would leak that the claim number
                # is real to anyone probing identifiers.
                raise NotFoundError("Claim not found.")
        return claim

    # ── Creation and editing ────────────────────────────────

    def create(self, customer: Customer, payload: ClaimCreate, actor: User) -> Claim:
        vehicle = self._resolve_vehicle(customer, payload.vehicle_id)
        policy = self._resolve_policy(customer, payload.policy_id, vehicle)

        claim = Claim(
            claim_number=self.generate_claim_number(),
            customer_id=customer.id,
            vehicle_id=vehicle.id if vehicle else None,
            policy_id=policy.id if policy else None,
            status=ClaimStatus.DRAFT,
            accident_datetime=payload.accident_datetime,
            accident_description=payload.accident_description,
            customer_vehicle_description=payload.customer_vehicle_description,
            stated_make=payload.stated_make or (vehicle.make if vehicle else None),
            stated_model=payload.stated_model or (vehicle.model if vehicle else None),
            stated_variant=payload.stated_variant or (vehicle.variant if vehicle else None),
            stated_year=payload.stated_year or (vehicle.year if vehicle else None),
            stated_color=payload.stated_color or (vehicle.color if vehicle else None),
            stated_registration=payload.stated_registration
            or (vehicle.registration_number if vehicle else None),
        )
        self.db.add(claim)
        self.db.flush()

        self._add_status_event(claim, None, ClaimStatus.DRAFT, actor, "Claim created.")
        audit.record(
            self.db, action="claim.create", entity_type="claim", entity_id=claim.id,
            actor=actor, after={"claim_number": claim.claim_number},
        )
        return claim

    def update(self, claim: Claim, payload: ClaimUpdate, actor: User) -> Claim:
        if not claim.is_editable_by_customer:
            raise InvalidClaimStateError(
                f"A claim in status {claim.status.value} can no longer be edited."
            )

        before = {
            "accident_description": claim.accident_description,
            "stated_make": claim.stated_make,
            "stated_model": claim.stated_model,
        }

        for field, value in payload.model_dump(exclude_unset=True).items():
            if field in {"vehicle_id", "policy_id"}:
                continue
            setattr(claim, field, value)

        if payload.vehicle_id is not None:
            customer = self.db.get(Customer, claim.customer_id)
            vehicle = self._resolve_vehicle(customer, payload.vehicle_id) if customer else None
            claim.vehicle_id = vehicle.id if vehicle else None

        self.db.flush()
        audit.record(
            self.db, action="claim.update", entity_type="claim", entity_id=claim.id,
            actor=actor, before=before,
            after={"accident_description": claim.accident_description},
        )
        return claim

    def set_damage_report(
        self, claim: Claim, payload: DamageReportRequest, actor: User
    ) -> CustomerDamageReport:
        if not claim.is_editable_by_customer:
            raise InvalidClaimStateError("Damage details can only be edited before submission.")

        report = claim.damage_report
        if report is None:
            report = CustomerDamageReport(claim_id=claim.id)
            self.db.add(report)

        report.reported_parts = payload.reported_parts
        report.free_text_parts = payload.free_text_parts
        self.db.flush()

        audit.record(
            self.db, action="claim.damage_report", entity_type="claim", entity_id=claim.id,
            actor=actor, after={"reported_parts": payload.reported_parts},
        )
        return report

    def set_location(self, claim: Claim, payload: LocationRequest, actor: User) -> ClaimLocation:
        location = claim.location
        if location is None:
            location = ClaimLocation(claim_id=claim.id, latitude=0, longitude=0, source=payload.source)
            self.db.add(location)

        location.latitude = payload.latitude
        location.longitude = payload.longitude
        location.source = payload.source
        location.accuracy_meters = payload.accuracy_meters
        location.address = payload.address
        self.db.flush()

        audit.record(
            self.db, action="claim.location", entity_type="claim", entity_id=claim.id,
            actor=actor, after={"source": payload.source.value},
        )
        return location

    # ── Submission ──────────────────────────────────────────

    def validate_for_submission(self, claim: Claim) -> list[str]:
        """Blocking problems only. Soft gaps become manual-review reasons, not refusals."""
        problems: list[str] = []

        usable = [i for i in claim.images if i.is_usable_for_analysis]
        if not usable:
            problems.append(
                "At least one usable photograph of the vehicle is required."
                if not claim.images
                else "None of the uploaded photographs passed validation. Please retake them."
            )

        rejected = [i for i in claim.images if i.validation_status is ImageValidationStatus.REJECTED]
        if rejected and not usable:
            problems.append(f"{len(rejected)} image(s) were rejected during validation.")

        return problems

    def submit(self, claim: Claim, actor: User) -> Claim:
        if claim.status not in {ClaimStatus.DRAFT, ClaimStatus.MORE_INFORMATION_REQUIRED}:
            raise InvalidClaimStateError(
                f"A claim in status {claim.status.value} cannot be submitted."
            )

        problems = self.validate_for_submission(claim)
        if problems:
            raise ValidationError_("This claim is not ready to submit.", {"issues": "; ".join(problems)})

        claim.submitted_at = datetime.now(UTC)
        claim.priority = self._initial_priority(claim)
        self.transition(claim, ClaimStatus.SUBMITTED, actor, "Claim submitted by customer.")

        audit.record(
            self.db, action="claim.submit", entity_type="claim", entity_id=claim.id,
            actor=actor, after={"images": len(claim.images)},
        )
        return claim

    def _initial_priority(self, claim: Claim) -> ClaimPriority:
        """Pre-analysis priority from what the customer told us.

        Refined later by the pipeline once severity and estimate are known.
        """
        text = " ".join(
            filter(None, [claim.accident_description, claim.customer_vehicle_description])
        ).lower()
        urgent_terms = ("injur", "hospital", "fire", "rollover", "roll over", "total", "fatal")
        if any(term in text for term in urgent_terms):
            return ClaimPriority.URGENT
        return ClaimPriority.NORMAL

    # ── Transitions ─────────────────────────────────────────

    def transition(
        self,
        claim: Claim,
        to_status: ClaimStatus,
        actor: User | None = None,
        note: str | None = None,
        *,
        force: bool = False,
    ) -> Claim:
        from_status = claim.status
        if from_status == to_status:
            return claim

        if not force and to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
            raise InvalidClaimStateError(
                f"Cannot move a claim from {from_status.value} to {to_status.value}."
            )

        claim.status = to_status
        if to_status is ClaimStatus.PROCESSING and claim.ai_started_at is None:
            claim.ai_started_at = datetime.now(UTC)
        if to_status is ClaimStatus.AI_COMPLETED:
            claim.ai_completed_at = datetime.now(UTC)
        if to_status in {ClaimStatus.APPROVED, ClaimStatus.REJECTED}:
            claim.decided_at = datetime.now(UTC)

        self._add_status_event(claim, from_status, to_status, actor, note)
        self.db.flush()
        log.info(
            "claim.transition",
            claim_id=str(claim.id), from_status=from_status.value, to_status=to_status.value,
        )
        return claim

    def _add_status_event(
        self,
        claim: Claim,
        from_status: ClaimStatus | None,
        to_status: ClaimStatus,
        actor: User | None,
        note: str | None,
    ) -> None:
        actor_type = ActorType.SYSTEM
        if actor is not None:
            actor_type = {
                UserRole.CUSTOMER: ActorType.CUSTOMER,
                UserRole.AGENT: ActorType.AGENT,
                UserRole.ADMIN: ActorType.ADMIN,
            }[actor.role]

        self.db.add(
            ClaimStatusEvent(
                claim_id=claim.id,
                from_status=from_status,
                to_status=to_status,
                actor_user_id=actor.id if actor else None,
                actor_type=actor_type,
                note=note,
            )
        )

    def add_note(self, claim: Claim, body: str, visibility, actor: User) -> ClaimNote:
        note = ClaimNote(
            claim_id=claim.id, author_user_id=actor.id, body=body, visibility=visibility
        )
        self.db.add(note)
        self.db.flush()
        audit.record(
            self.db, action="claim.note", entity_type="claim", entity_id=claim.id, actor=actor
        )
        return note

    def set_manual_review(self, claim: Claim, required: bool, reasons: list[str]) -> None:
        claim.manual_review_required = required
        claim.manual_review_reasons = reasons
        if required and reasons:
            claim.priority = self._priority_from_reasons(claim, reasons)
        self.db.flush()

    def _priority_from_reasons(self, claim: Claim, reasons: list[str]) -> ClaimPriority:
        if claim.priority is ClaimPriority.URGENT:
            return ClaimPriority.URGENT
        escalating = ("structural", "fraud", "high risk", "critical")
        if any(term in r.lower() for r in reasons for term in escalating):
            return ClaimPriority.HIGH
        return claim.priority

    # ── Helpers ─────────────────────────────────────────────

    def _resolve_vehicle(self, customer: Customer | None, vehicle_id: uuid.UUID | None) -> Vehicle | None:
        if vehicle_id is None or customer is None:
            return None
        vehicle = self.db.scalar(
            select(Vehicle).where(
                Vehicle.id == vehicle_id,
                Vehicle.customer_id == customer.id,
                Vehicle.deleted_at.is_(None),
            )
        )
        if vehicle is None:
            raise NotFoundError("Vehicle not found in your garage.")
        return vehicle

    def _resolve_policy(
        self, customer: Customer, policy_id: uuid.UUID | None, vehicle: Vehicle | None
    ) -> InsurancePolicy | None:
        if policy_id is None:
            if vehicle is None:
                return None
            return self.db.scalar(
                select(InsurancePolicy).where(
                    InsurancePolicy.vehicle_id == vehicle.id,
                    InsurancePolicy.deleted_at.is_(None),
                )
            )

        policy = self.db.scalar(
            select(InsurancePolicy).where(
                InsurancePolicy.id == policy_id,
                InsurancePolicy.customer_id == customer.id,
                InsurancePolicy.deleted_at.is_(None),
            )
        )
        if policy is None:
            raise NotFoundError("Insurance policy not found.")
        if vehicle and policy.vehicle_id != vehicle.id:
            raise ConflictError("That policy belongs to a different vehicle.")
        return policy

    def reported_part_labels(self, claim: Claim) -> list[str]:
        report = claim.damage_report
        if report is None:
            return []
        return [part_display_name(code) for code in report.all_reported_part_codes]

    # ── Agent actions ───────────────────────────────────────

    def apply_assessment_correction(
        self, claim: Claim, payload: AssessmentCorrectionRequest, actor: User
    ) -> None:
        assessment = claim.latest_assessment
        if assessment is None:
            raise NotFoundError("This claim has not been analysed yet.")

        original = {
            "vehicle_make": assessment.vehicle_make,
            "vehicle_model": assessment.vehicle_model,
            "vehicle_year": assessment.vehicle_year,
            "registration": assessment.detected_registration,
        }
        corrections: dict = dict(assessment.agent_corrections or {})

        if payload.vehicle_make:
            corrections["vehicle_make"] = {"from": assessment.vehicle_make, "to": payload.vehicle_make}
            assessment.vehicle_make = payload.vehicle_make
        if payload.vehicle_model:
            corrections["vehicle_model"] = {"from": assessment.vehicle_model, "to": payload.vehicle_model}
            assessment.vehicle_model = payload.vehicle_model
        if payload.vehicle_year:
            corrections["vehicle_year"] = {"from": assessment.vehicle_year, "to": payload.vehicle_year}
            assessment.vehicle_year = payload.vehicle_year
        if payload.registration_number:
            corrections["registration"] = {
                "from": assessment.detected_registration,
                "to": payload.registration_number,
            }
            assessment.confirmed_registration = payload.registration_number

        by_id = {p.id: p for p in assessment.damaged_parts}
        for part_edit in payload.parts:
            part = by_id.get(part_edit.damaged_part_id)
            if part is None:
                continue
            if part_edit.agent_confirmed is not None:
                part.agent_confirmed = part_edit.agent_confirmed
            if part_edit.damage_type is not None:
                part.damage_type = part_edit.damage_type
            if part_edit.severity is not None:
                part.severity = part_edit.severity
            if part_edit.recommended_action is not None:
                part.recommended_action = part_edit.recommended_action
            if part_edit.agent_note:
                part.agent_note = part_edit.agent_note

        assessment.agent_corrected = True
        assessment.agent_corrections = {**corrections, "reason": payload.reason}
        assessment.corrected_by_user_id = actor.id
        self.db.flush()
        audit.record(
            self.db, action="claim.assessment_correct", entity_type="claim", entity_id=claim.id,
            actor=actor, before=original, after={"reason": payload.reason},
        )

    def adjust_estimate(
        self, claim: Claim, payload: EstimateAdjustmentRequest, actor: User
    ) -> None:
        estimate = claim.latest_estimate
        if estimate is None:
            raise NotFoundError("No repair estimate has been produced for this claim yet.")
        estimate.superseded_by_agent = True
        estimate.agent_adjusted_min = payload.adjusted_min
        estimate.agent_adjusted_max = payload.adjusted_max
        estimate.agent_adjustment_reason = payload.reason
        estimate.adjusted_by_user_id = actor.id
        self.db.flush()
        audit.record(
            self.db, action="claim.estimate_adjust", entity_type="claim", entity_id=claim.id,
            actor=actor, after={"min": str(payload.adjusted_min), "max": str(payload.adjusted_max)},
        )

    def request_information(
        self, claim: Claim, payload: InformationRequest, actor: User
    ) -> Claim:
        items = ", ".join(payload.requested_items) if payload.requested_items else "additional evidence"
        claim.information_request = payload.message
        self.transition(
            claim,
            ClaimStatus.MORE_INFORMATION_REQUIRED,
            actor,
            f"Information requested ({items}): {payload.message}",
        )
        self.add_note(claim, payload.message, NoteVisibility.CUSTOMER_VISIBLE, actor)
        return claim

    def decide(self, claim: Claim, payload: DecisionRequest, actor: User) -> Claim:
        claim.decision_reason = payload.reason
        if payload.decision is ClaimStatus.APPROVED:
            self.transition(claim, ClaimStatus.APPROVED, actor, payload.reason)
        elif payload.decision is ClaimStatus.REJECTED:
            self.transition(claim, ClaimStatus.REJECTED, actor, payload.reason)
        else:
            self.add_note(
                claim,
                f"Further assessment requested: {payload.reason}",
                NoteVisibility.INTERNAL,
                actor,
            )
        return claim

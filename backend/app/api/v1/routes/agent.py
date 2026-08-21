"""Agent queue, dashboard and claim-handling actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import AgentUser, CurrentAgent, CurrentUser, DbSession
from app.core.enums import ClaimPriority, ClaimStatus, NoteVisibility, UserRole
from app.core.errors import NotFoundError, ValidationError_
from app.models.claim import Claim
from app.models.image import ClaimImage
from app.models.user import Agent, Customer
from app.schemas.claim import (
    AgentDashboardResponse,
    AgentNoteRequest,
    AssessmentCorrectionRequest,
    AssessmentResponse,
    ClaimDetailResponse,
    ClaimNoteResponse,
    ClaimSummaryResponse,
    DecisionRequest,
    EstimateAdjustmentRequest,
    EstimateResponse,
    InformationRequest,
    VerifyRequest,
)
from app.schemas.common import MessageResponse, Page
from app.services import audit
from app.services.claims import ClaimService
from app.services.presenters import ClaimPresenter
from app.notifications.service import NotificationService
from app.workers.local import enqueue_claim_pipeline

router = APIRouter(prefix="/agent", tags=["agent"])

_EVIDENCE_OPTIONS = (
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
    selectinload(Claim.customer).selectinload(Customer.user),
    selectinload(Claim.vehicle),
    selectinload(Claim.policy),
    selectinload(Claim.assigned_agent).selectinload(Agent.user),
)


@router.get("/dashboard", response_model=AgentDashboardResponse)
def dashboard(db: DbSession, user: AgentUser):
    counts = dict(
        db.execute(
            select(Claim.status, func.count())
            .where(Claim.deleted_at.is_(None))
            .group_by(Claim.status)
        ).all()
    )
    total = sum(counts.values())
    under_review = counts.get(ClaimStatus.AGENT_REVIEW, 0) + counts.get(
        ClaimStatus.AI_COMPLETED, 0
    )
    new_claims = counts.get(ClaimStatus.SUBMITTED, 0) + counts.get(ClaimStatus.PROCESSING, 0)
    high_priority = db.scalar(
        select(func.count())
        .select_from(Claim)
        .where(
            Claim.deleted_at.is_(None),
            Claim.priority.in_([ClaimPriority.HIGH, ClaimPriority.URGENT]),
            Claim.status.notin_([ClaimStatus.APPROVED, ClaimStatus.REJECTED, ClaimStatus.COMPLETED]),
        )
    ) or 0
    awaiting = db.scalar(
        select(func.count())
        .select_from(Claim)
        .where(
            Claim.deleted_at.is_(None),
            Claim.manual_review_required.is_(True),
            Claim.status == ClaimStatus.AGENT_REVIEW,
        )
    ) or 0
    return AgentDashboardResponse(
        total_claims=total,
        new_claims=new_claims,
        under_review=under_review,
        high_priority=high_priority,
        approved=counts.get(ClaimStatus.APPROVED, 0),
        rejected=counts.get(ClaimStatus.REJECTED, 0),
        pending_information=counts.get(ClaimStatus.MORE_INFORMATION_REQUIRED, 0),
        awaiting_manual_review=awaiting,
    )


@router.get("/claims", response_model=Page[ClaimSummaryResponse])
def list_queue(
    db: DbSession,
    user: AgentUser,
    agent: CurrentAgent,
    claim_status: ClaimStatus | None = Query(None, alias="status"),
    priority: ClaimPriority | None = None,
    mine: bool = False,
    needs_verification: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    base = select(Claim).where(
        Claim.deleted_at.is_(None),
        Claim.status != ClaimStatus.DRAFT,
    )
    if claim_status:
        base = base.where(Claim.status == claim_status)
    if priority:
        base = base.where(Claim.priority == priority)
    if mine:
        if agent is None:
            return Page[ClaimSummaryResponse](items=[], total=0, page=page, page_size=page_size)
        base = base.where(Claim.assigned_agent_id == agent.id)
    if needs_verification:
        base = base.where(
            Claim.status.in_(
                [
                    ClaimStatus.AGENT_REVIEW,
                    ClaimStatus.AI_COMPLETED,
                    ClaimStatus.SUBMITTED,
                    ClaimStatus.PROCESSING,
                    ClaimStatus.AI_ANALYZING,
                    ClaimStatus.MARKET_RESEARCH,
                    ClaimStatus.ESTIMATING,
                ]
            )
        )

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    claims = db.scalars(
        base.options(*_EVIDENCE_OPTIONS)
        .order_by(Claim.priority.desc(), Claim.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    presenter = ClaimPresenter(db)
    return Page[ClaimSummaryResponse](
        items=[presenter.summary(c) for c in claims],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/claims/{claim_id}", response_model=ClaimDetailResponse)
def get_claim(claim_id: uuid.UUID, db: DbSession, user: AgentUser):
    claim = ClaimService(db).get(claim_id, with_evidence=True)
    return ClaimPresenter(db).detail(claim, include_internal=True)


@router.post("/claims/{claim_id}/assign", response_model=ClaimDetailResponse)
def assign_claim(
    claim_id: uuid.UUID, db: DbSession, user: AgentUser, agent: CurrentAgent
):
    service = ClaimService(db)
    claim = service.get(claim_id, with_evidence=True)
    if user.role is UserRole.AGENT:
        if agent is None:
            raise ValidationError_("No agent profile is attached to this account.")
        claim.assigned_agent_id = agent.id
    service.add_note(
        claim,
        f"Claim assigned to {user.full_name}.",
        NoteVisibility.INTERNAL,
        user,
    )
    audit.record(
        db, action="claim.assign", entity_type="claim", entity_id=claim.id, actor=user
    )
    db.flush()
    return ClaimPresenter(db).detail(claim, include_internal=True)


@router.post("/claims/{claim_id}/notes", response_model=ClaimNoteResponse, status_code=status.HTTP_201_CREATED)
def add_note(
    claim_id: uuid.UUID, payload: AgentNoteRequest, db: DbSession, user: AgentUser
):
    service = ClaimService(db)
    claim = service.get(claim_id)
    note = service.add_note(claim, payload.body, payload.visibility, user)
    if payload.visibility is NoteVisibility.CUSTOMER_VISIBLE and claim.customer:
        NotificationService(db).notify_claim_status(
            claim,
            f"Update on claim {claim.claim_number}",
            payload.body,
        )
    return ClaimNoteResponse(
        id=note.id,
        body=note.body,
        visibility=note.visibility,
        created_at=note.created_at,
        author_name=user.full_name,
    )


@router.patch("/claims/{claim_id}/assessment", response_model=AssessmentResponse)
def correct_assessment(
    claim_id: uuid.UUID,
    payload: AssessmentCorrectionRequest,
    db: DbSession,
    user: AgentUser,
):
    service = ClaimService(db)
    claim = service.get(claim_id, with_evidence=True)
    service.apply_assessment_correction(claim, payload, user)
    db.refresh(claim)
    response = ClaimPresenter(db).assessment(claim)
    if response is None:
        raise NotFoundError("This claim has not been analysed yet.")
    return response


@router.patch("/claims/{claim_id}/estimate", response_model=EstimateResponse)
def adjust_estimate(
    claim_id: uuid.UUID,
    payload: EstimateAdjustmentRequest,
    db: DbSession,
    user: AgentUser,
):
    service = ClaimService(db)
    claim = service.get(claim_id, with_evidence=True)
    service.adjust_estimate(claim, payload, user)
    db.refresh(claim)
    response = ClaimPresenter(db).estimate(claim)
    if response is None:
        raise NotFoundError("No repair estimate has been produced for this claim yet.")
    return response


@router.post("/claims/{claim_id}/request-information", response_model=ClaimDetailResponse)
def request_information(
    claim_id: uuid.UUID,
    payload: InformationRequest,
    db: DbSession,
    user: AgentUser,
):
    service = ClaimService(db)
    claim = service.get(claim_id, with_evidence=True)
    service.request_information(claim, payload, user)
    NotificationService(db).notify_claim_status(
        claim,
        f"More information needed for {claim.claim_number}",
        payload.message,
    )
    db.refresh(claim)
    return ClaimPresenter(db).detail(claim, include_internal=True)


@router.post("/claims/{claim_id}/decision", response_model=ClaimDetailResponse)
def decide_claim(
    claim_id: uuid.UUID, payload: DecisionRequest, db: DbSession, user: AgentUser
):
    service = ClaimService(db)
    claim = service.get(claim_id, with_evidence=True)
    service.decide(claim, payload, user)
    verb = {
        ClaimStatus.APPROVED: "approved",
        ClaimStatus.REJECTED: "declined",
        ClaimStatus.AGENT_REVIEW: "returned for further assessment",
    }.get(payload.decision, "updated")
    NotificationService(db).notify_claim_status(
        claim,
        f"Claim {claim.claim_number} {verb}",
        payload.reason,
    )
    db.refresh(claim)
    return ClaimPresenter(db).detail(claim, include_internal=True)


@router.post("/claims/{claim_id}/verify", response_model=ClaimDetailResponse)
def verify_claim(
    claim_id: uuid.UUID, payload: VerifyRequest, db: DbSession, user: AgentUser
):
    """Record that the agent reviewed images, cost, location and time, then decide."""
    service = ClaimService(db)
    claim = service.get(claim_id, with_evidence=True)
    reviewed = [
        label
        for ok, label in (
            (payload.images_reviewed, "images"),
            (payload.cost_reviewed, "cost"),
            (payload.location_reviewed, "location"),
            (payload.time_reviewed, "time"),
        )
        if ok
    ]
    service.add_note(
        claim,
        "Verified report: " + (", ".join(reviewed) or "no items checked") + f". {payload.reason}",
        NoteVisibility.INTERNAL,
        user,
    )
    service.decide(claim, payload, user)
    verb = {
        ClaimStatus.APPROVED: "approved",
        ClaimStatus.REJECTED: "declined",
        ClaimStatus.AGENT_REVIEW: "returned for further assessment",
    }.get(payload.decision, "updated")
    NotificationService(db).notify_claim_status(
        claim,
        f"Claim {claim.claim_number} {verb}",
        payload.reason,
    )
    db.refresh(claim)
    return ClaimPresenter(db).detail(claim, include_internal=True)


@router.post("/claims/{claim_id}/analyze", response_model=MessageResponse)
def reanalyze(claim_id: uuid.UUID, db: DbSession, user: AgentUser):
    service = ClaimService(db)
    claim = service.get(claim_id)

    enqueue_claim_pipeline(str(claim.id), requested_by=user.full_name)
    audit.record(
        db, action="claim.reanalyze", entity_type="claim", entity_id=claim.id, actor=user
    )
    return MessageResponse(message="Re-analysis has been queued.")

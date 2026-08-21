"""Customer-facing claim endpoints: the wizard, evidence, submission and results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import CurrentCustomer, CurrentUser, CustomerUser, DbSession
from app.core.enums import ClaimStatus, ImageRole
from app.core.errors import NotFoundError, PermissionError_, ValidationError_
from app.core.logging import get_logger
from app.core.parts import PARTS
from app.models.claim import Claim
from app.schemas.claim import (
    AnnotationRequest,
    AssessmentResponse,
    ClaimCreate,
    ClaimDetailResponse,
    ClaimImageResponse,
    ClaimStatusResponse,
    ClaimSummaryResponse,
    ClaimUpdate,
    DamageReportRequest,
    EstimateResponse,
    LocationRequest,
    MarketDataResponse,
    PartPriceResponse,
    ReconciliationResponse,
    RegistrationConfirmRequest,
    TimelineEvent,
)
from app.schemas.common import MessageResponse, Page
from app.services.claims import ClaimService
from app.services.images import ImageService
from app.services.presenters import ClaimPresenter
from app.notifications.service import NotificationService
from app.workers.local import enqueue_claim_pipeline

log = get_logger(__name__)
router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("/part-catalog", response_model=list[dict])
def part_catalog():
    """Canonical parts for the damage-selection checkboxes."""
    return [
        {"code": p.code, "display_name": p.display_name, "group": p.group}
        for p in PARTS
        if p.code != "CHASSIS_FRAME"
    ]


@router.post("", response_model=ClaimDetailResponse, status_code=status.HTTP_201_CREATED)
def create_claim(
    payload: ClaimCreate, db: DbSession, user: CustomerUser, customer: CurrentCustomer
):
    claim = ClaimService(db).create(customer, payload, user)
    db.flush()
    return ClaimPresenter(db).detail(claim, include_internal=False)


@router.get("", response_model=Page[ClaimSummaryResponse])
def list_claims(
    db: DbSession,
    customer: CurrentCustomer,
    claim_status: ClaimStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    base = select(Claim).where(Claim.customer_id == customer.id, Claim.deleted_at.is_(None))
    if claim_status:
        base = base.where(Claim.status == claim_status)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    claims = db.scalars(
        base.order_by(Claim.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    presenter = ClaimPresenter(db)
    return Page[ClaimSummaryResponse](
        items=[presenter.summary(c) for c in claims],
        total=total, page=page, page_size=page_size,
    )


@router.get("/{claim_id}", response_model=ClaimDetailResponse)
def get_claim(claim_id: uuid.UUID, db: DbSession, user: CurrentUser):
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    return ClaimPresenter(db).detail(claim, include_internal=False)


@router.patch("/{claim_id}", response_model=ClaimDetailResponse)
def update_claim(claim_id: uuid.UUID, payload: ClaimUpdate, db: DbSession, user: CustomerUser):
    service = ClaimService(db)
    claim = service.get_for_user(claim_id, user, with_evidence=True)
    service.update(claim, payload, user)
    return ClaimPresenter(db).detail(claim, include_internal=False)


# ── Evidence ────────────────────────────────────────────────


@router.post(
    "/{claim_id}/images",
    response_model=list[ClaimImageResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_images(
    claim_id: uuid.UUID,
    db: DbSession,
    user: CustomerUser,
    files: list[UploadFile] = File(...),
    image_role: ImageRole = Form(ImageRole.OTHER),
    customer_note: str | None = Form(None),
):
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    service = ImageService(db)
    presenter = ClaimPresenter(db)

    if not files:
        raise ValidationError_("No file was provided.")

    uploaded = []
    for upload in files:
        data = await upload.read()
        image = service.upload(
            claim,
            data=data,
            filename=upload.filename or "upload.jpg",
            content_type=upload.content_type or "application/octet-stream",
            image_role=image_role,
            customer_note=customer_note,
            actor=user,
        )
        uploaded.append(presenter.image(image))

    # An EXIF fix from any uploaded photo is the most trustworthy location we can get,
    # so it is claimed as soon as one arrives.
    db.refresh(claim)
    service.resolve_location_from_exif(claim)
    return uploaded


@router.delete("/{claim_id}/images/{image_id}", response_model=MessageResponse)
def delete_image(
    claim_id: uuid.UUID, image_id: uuid.UUID, db: DbSession, user: CustomerUser
):
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    ImageService(db).delete(claim, image_id, user)
    return MessageResponse(message="Image removed.")


@router.post("/{claim_id}/images/{image_id}/annotations", response_model=ClaimImageResponse)
def annotate_image(
    claim_id: uuid.UUID,
    image_id: uuid.UUID,
    payload: AnnotationRequest,
    db: DbSession,
    user: CustomerUser,
):
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    image = ImageService(db).annotate(
        claim, image_id, payload.regions, user, replace_existing=payload.replace_existing
    )
    return ClaimPresenter(db).image(image)


@router.post("/{claim_id}/damage-report", response_model=ClaimDetailResponse)
def set_damage_report(
    claim_id: uuid.UUID, payload: DamageReportRequest, db: DbSession, user: CustomerUser
):
    service = ClaimService(db)
    claim = service.get_for_user(claim_id, user, with_evidence=True)
    service.set_damage_report(claim, payload, user)
    db.refresh(claim)
    return ClaimPresenter(db).detail(claim, include_internal=False)


@router.post("/{claim_id}/location", response_model=ClaimDetailResponse)
def set_location(
    claim_id: uuid.UUID, payload: LocationRequest, db: DbSession, user: CustomerUser
):
    service = ClaimService(db)
    claim = service.get_for_user(claim_id, user, with_evidence=True)
    service.set_location(claim, payload, user)
    db.refresh(claim)
    return ClaimPresenter(db).detail(claim, include_internal=False)


@router.post("/{claim_id}/confirm-registration", response_model=AssessmentResponse)
def confirm_registration(
    claim_id: uuid.UUID,
    payload: RegistrationConfirmRequest,
    db: DbSession,
    user: CustomerUser,
):
    """Customer correction of a low-confidence plate read."""
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    assessment = claim.latest_assessment
    if assessment is None:
        raise NotFoundError("No assessment exists for this claim yet.")

    assessment.confirmed_registration = payload.registration_number
    assessment.registration_confirmed_by_customer = True
    db.flush()

    response = ClaimPresenter(db).assessment(claim)
    if response is None:
        raise NotFoundError("No assessment exists for this claim yet.")
    return response


# ── Submission ──────────────────────────────────────────────


@router.post("/{claim_id}/submit", response_model=ClaimStatusResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_claim(claim_id: uuid.UUID, db: DbSession, user: CustomerUser):
    """Persist the submission, then hand the analysis to a background worker.

    The response returns as soon as the claim is durably SUBMITTED. Vision calls and market
    research take tens of seconds and must never sit on the request path.
    """
    service = ClaimService(db)
    claim = service.get_for_user(claim_id, user, with_evidence=True)
    service.submit(claim, user)
    try:
        NotificationService(db).notify_claim_submitted(claim)
    except Exception:
        log.exception("claim.submit_notify_failed", claim_id=str(claim.id))
    db.commit()

    enqueue_claim_pipeline(str(claim.id))

    db.refresh(claim)
    return ClaimPresenter(db).status(claim)


@router.get("/{claim_id}/status", response_model=ClaimStatusResponse)
def claim_status(claim_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Polling fallback for clients whose WebSocket dropped."""
    claim = ClaimService(db).get_for_user(claim_id, user)
    return ClaimPresenter(db).status(claim)


# ── Analysis read models ────────────────────────────────────


@router.get("/{claim_id}/assessment", response_model=AssessmentResponse)
def get_assessment(claim_id: uuid.UUID, db: DbSession, user: CurrentUser):
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    response = ClaimPresenter(db).assessment(claim)
    if response is None:
        raise NotFoundError("This claim has not been analysed yet.")
    return response


@router.get("/{claim_id}/estimate", response_model=EstimateResponse)
def get_estimate(claim_id: uuid.UUID, db: DbSession, user: CurrentUser):
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    response = ClaimPresenter(db).estimate(claim)
    if response is None:
        raise NotFoundError("No repair estimate has been produced for this claim yet.")
    return response


@router.get("/{claim_id}/market-data", response_model=MarketDataResponse)
def get_market_data(claim_id: uuid.UUID, db: DbSession, user: CurrentUser):
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    return ClaimPresenter(db).market_data(claim)


@router.get("/{claim_id}/part-prices", response_model=list[PartPriceResponse])
def get_part_prices(claim_id: uuid.UUID, db: DbSession, user: CurrentUser):
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    return ClaimPresenter(db).part_prices(claim)


@router.get("/{claim_id}/reconciliation", response_model=ReconciliationResponse)
def get_reconciliation(claim_id: uuid.UUID, db: DbSession, user: CurrentUser):
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    assessment = claim.latest_assessment
    if assessment is None:
        raise NotFoundError("This claim has not been analysed yet.")
    return ClaimPresenter(db).reconciliation(assessment)


@router.get("/{claim_id}/timeline", response_model=list[TimelineEvent])
def get_timeline(claim_id: uuid.UUID, db: DbSession, user: CurrentUser):
    claim = ClaimService(db).get_for_user(claim_id, user, with_evidence=True)
    return ClaimPresenter(db).timeline(claim)


@router.post("/{claim_id}/analyze", response_model=MessageResponse)
def analyze_claim(claim_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Agent/admin re-run. Customers cannot trigger this."""
    from app.core.enums import UserRole

    if user.role is UserRole.CUSTOMER:
        raise PermissionError_("Only an insurance agent can re-run analysis.")

    claim = ClaimService(db).get_for_user(claim_id, user)

    enqueue_claim_pipeline(str(claim.id), requested_by=user.full_name)
    return MessageResponse(message="Re-analysis has been queued.")

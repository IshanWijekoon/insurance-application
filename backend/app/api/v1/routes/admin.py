"""Admin: users, market sources, configuration, analytics and audit logs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession
from app.core.config import settings
from app.core.enums import ClaimStatus, UserRole
from app.core.errors import NotFoundError, ValidationError_
from app.models.claim import Claim
from app.models.market import MarketSource
from app.models.ops import AuditLog
from app.models.user import User
from app.schemas.admin import (
    AIConfigResponse,
    AnalyticsResponse,
    AuditLogResponse,
    MarketSourceCreate,
    MarketSourceResponse,
    MarketSourceUpdate,
    PricingConfigResponse,
    StaffCreateRequest,
    UserAdminResponse,
    UserAdminUpdate,
)
from app.schemas.auth import UserProfile
from app.schemas.common import MessageResponse, Page
from app.services import audit
from app.services.auth import AuthService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=Page[UserAdminResponse])
def list_users(
    db: DbSession,
    user: AdminUser,
    role: UserRole | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    base = select(User).where(User.deleted_at.is_(None))
    if role:
        base = base.where(User.role == role)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page[UserAdminResponse](
        items=[UserAdminResponse.model_validate(u) for u in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/users", response_model=UserProfile, status_code=status.HTTP_201_CREATED)
def create_staff(payload: StaffCreateRequest, db: DbSession, user: AdminUser):
    if payload.role is UserRole.CUSTOMER:
        raise ValidationError_("Customers self-register. Provision agents or admins here.")
    created = AuthService(db).create_staff_user(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role,
        employee_code=payload.employee_code,
        branch=payload.branch,
        region=payload.region,
        actor=user,
    )
    return UserProfile.model_validate(created)


@router.patch("/users/{user_id}", response_model=UserAdminResponse)
def update_user(user_id, payload: UserAdminUpdate, db: DbSession, user: AdminUser):
    target = db.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise NotFoundError("User not found.")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(target, field, value)
    db.flush()
    audit.record(
        db, action="user.update", entity_type="user", entity_id=target.id, actor=user, after=data
    )
    return UserAdminResponse.model_validate(target)


@router.get("/market-sources", response_model=list[MarketSourceResponse])
def list_sources(db: DbSession, user: AdminUser):
    sources = db.scalars(select(MarketSource).order_by(MarketSource.name)).all()
    return [MarketSourceResponse.model_validate(s) for s in sources]


@router.post("/market-sources", response_model=MarketSourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(payload: MarketSourceCreate, db: DbSession, user: AdminUser):
    source = MarketSource(**payload.model_dump())
    db.add(source)
    db.flush()
    audit.record(
        db, action="market_source.create", entity_type="market_source", entity_id=source.id,
        actor=user, after={"name": source.name, "base_url": source.base_url},
    )
    return MarketSourceResponse.model_validate(source)


@router.patch("/market-sources/{source_id}", response_model=MarketSourceResponse)
def update_source(source_id, payload: MarketSourceUpdate, db: DbSession, user: AdminUser):
    source = db.get(MarketSource, source_id)
    if source is None:
        raise NotFoundError("Market source not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    db.flush()
    audit.record(
        db, action="market_source.update", entity_type="market_source", entity_id=source.id,
        actor=user,
    )
    return MarketSourceResponse.model_validate(source)


@router.delete("/market-sources/{source_id}", response_model=MessageResponse)
def delete_source(source_id, db: DbSession, user: AdminUser):
    source = db.get(MarketSource, source_id)
    if source is None:
        raise NotFoundError("Market source not found.")
    db.delete(source)
    audit.record(
        db, action="market_source.delete", entity_type="market_source", entity_id=source_id,
        actor=user,
    )
    return MessageResponse(message="Market source removed from the whitelist.")


@router.get("/ai-config", response_model=AIConfigResponse)
def ai_config(user: AdminUser):
    """Keys are never returned — only whether they are configured."""
    return AIConfigResponse(
        ai_provider=settings.ai_provider,
        vision_provider=settings.vision_provider,
        fallback_chain=settings.fallback_chain,
        providers={
            "gemini": {"configured": bool(settings.gemini_api_key), "text_model": settings.gemini_text_model, "vision_model": settings.gemini_vision_model},
            "openrouter": {"configured": bool(settings.openrouter_api_key), "text_model": settings.openrouter_text_model, "vision_model": settings.openrouter_vision_model},
            "deepseek": {"configured": bool(settings.deepseek_api_key), "text_model": settings.deepseek_text_model},
            "mock": {"configured": True, "note": "Local fixtures only. Refused in production."},
        },
        review_thresholds={
            "vehicle": settings.review_min_vehicle,
            "damage": settings.review_min_damage,
            "ocr": settings.review_min_ocr,
            "price": settings.review_min_price,
            "amount": settings.review_amount_threshold,
            "ratio": settings.review_ratio_threshold,
        },
    )


@router.get("/pricing-config", response_model=PricingConfigResponse)
def pricing_config(user: AdminUser):
    return PricingConfigResponse(
        labour_rate_per_hour=settings.labour_rate_per_hour,
        paint_rate_per_panel=settings.paint_rate_per_panel,
        materials_percent_of_parts=settings.materials_percent_of_parts,
        estimate_range_spread=settings.estimate_range_spread,
        currency=settings.market_currency,
        country=settings.market_country,
    )


@router.get("/analytics", response_model=AnalyticsResponse)
def analytics(db: DbSession, user: AdminUser):
    counts = dict(
        db.execute(
            select(Claim.status, func.count())
            .where(Claim.deleted_at.is_(None))
            .group_by(Claim.status)
        ).all()
    )
    total = sum(counts.values())
    week_ago = datetime.now(UTC) - timedelta(days=7)
    recent = db.scalar(
        select(func.count()).select_from(Claim).where(
            Claim.deleted_at.is_(None), Claim.submitted_at >= week_ago
        )
    ) or 0
    avg_conf = db.scalar(
        select(func.avg(Claim.overall_confidence)).where(
            Claim.deleted_at.is_(None), Claim.overall_confidence.is_not(None)
        )
    )
    cycle = db.scalar(
        select(
            func.avg(
                func.extract("epoch", Claim.decided_at) - func.extract("epoch", Claim.submitted_at)
            )
        ).where(Claim.deleted_at.is_(None), Claim.decided_at.is_not(None), Claim.submitted_at.is_not(None))
    )
    return AnalyticsResponse(
        total_claims=total,
        submitted_last_7_days=recent,
        approved=counts.get(ClaimStatus.APPROVED, 0),
        rejected=counts.get(ClaimStatus.REJECTED, 0),
        awaiting_review=counts.get(ClaimStatus.AGENT_REVIEW, 0),
        average_confidence=float(avg_conf) if avg_conf is not None else None,
        cycle_time_hours=(float(cycle) / 3600) if cycle is not None else None,
        by_status={k.value: v for k, v in counts.items()},
    )


@router.get("/audit-logs", response_model=Page[AuditLogResponse])
def audit_logs(
    db: DbSession,
    user: AdminUser,
    action: str | None = None,
    entity_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    base = select(AuditLog)
    if action:
        base = base.where(AuditLog.action == action)
    if entity_type:
        base = base.where(AuditLog.entity_type == entity_type)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page[AuditLogResponse](
        items=[AuditLogResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )

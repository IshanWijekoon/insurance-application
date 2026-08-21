"""Admin and agent operational contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import MarketSourceCategory, MarketSourceType, UserRole
from app.schemas.auth import UserProfile
from app.schemas.common import AppEmail, ORMModel


class StaffCreateRequest(BaseModel):
    email: AppEmail
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)
    role: UserRole
    employee_code: str | None = Field(default=None, max_length=40)
    branch: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)


class UserAdminUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    is_active: bool | None = None
    phone: str | None = Field(default=None, max_length=32)


class UserAdminResponse(UserProfile):
    last_login_at: datetime | None = None


class MarketSourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    base_url: str = Field(min_length=8, max_length=400)
    source_type: MarketSourceType = MarketSourceType.SCRAPE
    category: MarketSourceCategory = MarketSourceCategory.BOTH
    country: str = Field(default="LK", min_length=2, max_length=2)
    currency: str = Field(default="LKR", min_length=3, max_length=3)
    reliability_weight: float = Field(default=0.5, ge=0, le=1)
    is_enabled: bool = True
    rate_limit_per_minute: int = Field(default=10, ge=1, le=120)
    notes: str | None = Field(default=None, max_length=2000)


class MarketSourceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=400)
    source_type: MarketSourceType | None = None
    category: MarketSourceCategory | None = None
    reliability_weight: float | None = Field(default=None, ge=0, le=1)
    is_enabled: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=120)
    notes: str | None = Field(default=None, max_length=2000)


class MarketSourceResponse(ORMModel):
    id: uuid.UUID
    name: str
    base_url: str
    source_type: MarketSourceType
    category: MarketSourceCategory
    country: str
    currency: str
    reliability_weight: float
    is_enabled: bool
    rate_limit_per_minute: int
    robots_checked_at: datetime | None = None
    robots_allows: bool | None = None
    notes: str | None = None
    created_at: datetime


class AIConfigResponse(BaseModel):
    ai_provider: str
    vision_provider: str
    fallback_chain: list[str]
    providers: dict[str, dict[str, Any]]
    review_thresholds: dict[str, float]


class PricingConfigResponse(BaseModel):
    labour_rate_per_hour: float
    paint_rate_per_panel: float
    materials_percent_of_parts: float
    estimate_range_spread: float
    currency: str
    country: str


class AuditLogResponse(ORMModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    actor_role: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    created_at: datetime


class AnalyticsResponse(BaseModel):
    total_claims: int
    submitted_last_7_days: int
    approved: int
    rejected: int
    awaiting_review: int
    average_confidence: float | None = None
    cycle_time_hours: float | None = None
    by_status: dict[str, int]

"""Vehicle and policy contracts.

Everything descriptive is optional by design: a customer may know only the registration,
or only "it's a silver Prius". The AI fills gaps from images and the two are reconciled.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.core.enums import PolicyStatus
from app.schemas.common import ORMModel

_CURRENT_YEAR_CEILING = 2100


class VehicleCreate(BaseModel):
    registration_number: str | None = Field(default=None, max_length=32)
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    variant: str | None = Field(default=None, max_length=80)
    year: int | None = Field(default=None, ge=1900, le=_CURRENT_YEAR_CEILING)
    vehicle_type: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=40)
    vin: str | None = Field(default=None, max_length=40)
    is_primary: bool = False

    @field_validator("registration_number")
    @classmethod
    def normalise_registration(cls, v: str | None) -> str | None:
        return " ".join(v.upper().split()) if v else v


class VehicleUpdate(VehicleCreate):
    pass


class VehicleResponse(ORMModel):
    id: uuid.UUID
    registration_number: str | None = None
    make: str | None = None
    model: str | None = None
    variant: str | None = None
    year: int | None = None
    vehicle_type: str | None = None
    color: str | None = None
    vin: str | None = None
    is_primary: bool
    display_name: str
    created_at: datetime


class PolicyCreate(BaseModel):
    vehicle_id: uuid.UUID
    policy_number: str = Field(min_length=3, max_length=64)
    insurer_name: str | None = Field(default=None, max_length=160)
    policy_type: str | None = Field(default=None, max_length=60)
    coverage_amount: Decimal | None = Field(default=None, ge=0)
    deductible: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="LKR", min_length=3, max_length=3)
    valid_from: date | None = None
    valid_to: date | None = None


class PolicyResponse(ORMModel):
    id: uuid.UUID
    vehicle_id: uuid.UUID
    policy_number: str
    insurer_name: str | None = None
    policy_type: str | None = None
    coverage_amount: Decimal | None = None
    deductible: Decimal | None = None
    currency: str
    valid_from: date | None = None
    valid_to: date | None = None
    status: PolicyStatus

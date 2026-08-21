"""Authentication request/response contracts."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.enums import UserRole
from app.schemas.common import AppEmail, ORMModel

_PHONE = re.compile(r"^\+?[0-9\s\-()]{7,20}$")


class RegisterRequest(BaseModel):
    email: AppEmail
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        checks = (
            (any(c.islower() for c in v), "a lowercase letter"),
            (any(c.isupper() for c in v), "an uppercase letter"),
            (any(c.isdigit() for c in v), "a digit"),
        )
        missing = [label for ok, label in checks if not ok]
        if missing:
            raise ValueError("Password must contain " + ", ".join(missing) + ".")
        return v

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v: str | None) -> str | None:
        if v and not _PHONE.match(v):
            raise ValueError("Phone number format is not recognised.")
        return v


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        email = v.strip().lower()
        if "@" not in email or " " in email:
            raise ValueError("Enter an email address.")
        return email


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: "UserProfile"


class UserProfile(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None = None
    role: UserRole
    is_active: bool
    created_at: datetime


class CustomerProfile(ORMModel):
    id: uuid.UUID
    national_id: str | None = None
    address: str | None = None
    city: str | None = None
    country: str
    preferred_language: str


class AgentProfile(ORMModel):
    id: uuid.UUID
    employee_code: str
    branch: str | None = None
    region: str | None = None
    is_available: bool


class MeResponse(BaseModel):
    user: UserProfile
    customer: CustomerProfile | None = None
    agent: AgentProfile | None = None


class CustomerProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    national_id: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=400)
    city: str | None = Field(default=None, max_length=120)
    preferred_language: str | None = Field(default=None, max_length=8)


TokenResponse.model_rebuild()

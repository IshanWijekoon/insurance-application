"""Shared response primitives."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

T = TypeVar("T")


def _parse_email(value: str) -> str:
    """Accept real addresses plus `.local` demo accounts used in development."""
    raw = value.strip().lower()
    try:
        return validate_email(raw, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        if "@" in raw and raw.endswith(".local") and " " not in raw:
            local, _, domain = raw.partition("@")
            if local and "." in domain:
                return raw
        raise ValueError(str(exc)) from exc


AppEmail = Annotated[str, AfterValidator(_parse_email)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class MoneyRange(BaseModel):
    """An economic value that may or may not have been obtainable.

    The two-state shape is deliberate. A missing price is not zero and not null-with-no-
    explanation — it is an `UNAVAILABLE` status with a reason and a manual-verification
    flag, so no consumer can accidentally render "LKR 0" or silently drop the caveat.
    """

    status: Literal["AVAILABLE", "UNAVAILABLE"]
    min: Decimal | None = None
    max: Decimal | None = None
    median: Decimal | None = None
    currency: str | None = None
    confidence: float | None = None
    reason: str | None = None
    manual_verification_required: bool = False
    source_count: int = 0

    @classmethod
    def available(
        cls,
        minimum: Decimal,
        maximum: Decimal,
        currency: str,
        *,
        median: Decimal | None = None,
        confidence: float | None = None,
        source_count: int = 0,
    ) -> "MoneyRange":
        return cls(
            status="AVAILABLE",
            min=minimum,
            max=maximum,
            median=median,
            currency=currency,
            confidence=confidence,
            source_count=source_count,
        )

    @classmethod
    def unavailable(cls, reason: str) -> "MoneyRange":
        return cls(
            status="UNAVAILABLE",
            reason=reason,
            manual_verification_required=True,
        )


class ConfidenceInfo(BaseModel):
    """Provenance attached to every significant AI result."""

    value: float | None = None
    provider: str | None = None
    model: str | None = None
    computed_at: str | None = None


class MessageResponse(BaseModel):
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, str] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail

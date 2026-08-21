"""Reusable column types."""

from __future__ import annotations

from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import JSON, Enum as SAEnum, Numeric, Uuid
from sqlalchemy.dialects.postgresql import JSONB

MONEY = Numeric(14, 2)
CONFIDENCE = Numeric(4, 3)  # 0.000 – 1.000
RATIO = Numeric(6, 4)

# Portable across PostgreSQL (production) and SQLite (no-Docker local run).
GUID = Uuid(as_uuid=True)
JSONDoc = JSON().with_variant(JSONB(), "postgresql")


def enum_type(enum_cls: type[PyEnum], **kwargs: Any) -> SAEnum:
    """A VARCHAR + CHECK constraint rather than a native PostgreSQL ENUM.

    Native enums require `ALTER TYPE` gymnastics in migrations every time a status or
    damage type is added, and this domain will keep adding them.
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=48,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
        **kwargs,
    )

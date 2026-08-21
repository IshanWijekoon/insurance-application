"""Evidence: uploaded images, their metadata, annotations, and the customer's own report."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from app.db.types import GUID, JSONDoc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AnnotationType, ImageRole, ImageValidationStatus
from app.db.base import Base, Timestamped, UUIDPrimaryKey
from app.db.types import enum_type

if TYPE_CHECKING:
    from app.models.claim import Claim


class ClaimImage(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "claim_images"
    __table_args__ = (
        Index("ix_claim_images_claim", "claim_id"),
        Index("ix_claim_images_sha256", "sha256"),
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(400), unique=True, nullable=False)
    annotated_storage_key: Mapped[str | None] = mapped_column(String(400))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(60), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    # sha256 catches literal re-uploads; the perceptual hash catches the same photo
    # re-encoded, resized or lightly edited across claims.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    perceptual_hash: Mapped[str | None] = mapped_column(String(32))

    image_role: Mapped[ImageRole] = mapped_column(
        enum_type(ImageRole), default=ImageRole.OTHER, nullable=False
    )
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    quality_score: Mapped[float | None] = mapped_column(Float)
    blur_score: Mapped[float | None] = mapped_column(Float)
    brightness_score: Mapped[float | None] = mapped_column(Float)
    validation_status: Mapped[ImageValidationStatus] = mapped_column(
        enum_type(ImageValidationStatus), default=ImageValidationStatus.PENDING, nullable=False
    )
    validation_errors: Mapped[list[str]] = mapped_column(JSONDoc, default=list, nullable=False)

    customer_note: Mapped[str | None] = mapped_column(Text)

    claim: Mapped["Claim"] = relationship(back_populates="images")
    image_metadata: Mapped["ImageMetadata | None"] = relationship(
        back_populates="image", uselist=False, cascade="all, delete-orphan"
    )
    annotations: Mapped[list["ImageAnnotation"]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )

    @property
    def is_usable_for_analysis(self) -> bool:
        return self.validation_status in {
            ImageValidationStatus.VALID,
            ImageValidationStatus.WARNING,
        }


class ImageMetadata(Base, UUIDPrimaryKey, Timestamped):
    """EXIF, when it exists.

    `has_exif` and the nullable capture fields exist so the UI can distinguish
    "photographed at 22:42" from "we do not know when this was photographed". Upload time
    lives on the image row and is never copied into `captured_at`.
    """

    __tablename__ = "image_metadata"

    image_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claim_images.id", ondelete="CASCADE"),
        unique=True, nullable=False,
    )
    has_exif: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gps_latitude: Mapped[float | None] = mapped_column(Float)
    gps_longitude: Mapped[float | None] = mapped_column(Float)
    gps_altitude: Mapped[float | None] = mapped_column(Float)
    camera_make: Mapped[str | None] = mapped_column(String(120))
    camera_model: Mapped[str | None] = mapped_column(String(120))
    software: Mapped[str | None] = mapped_column(String(160))
    orientation: Mapped[int | None] = mapped_column(Integer)
    raw_exif: Mapped[dict[str, Any]] = mapped_column(JSONDoc, default=dict, nullable=False)

    image: Mapped[ClaimImage] = relationship(back_populates="image_metadata")

    @property
    def has_gps(self) -> bool:
        return self.gps_latitude is not None and self.gps_longitude is not None


class ImageAnnotation(Base, UUIDPrimaryKey, Timestamped):
    """A region the customer (or agent) drew on an image.

    `points` are stored in source-image pixel coordinates so annotations survive any
    display scaling; the frontend converts on render.
    """

    __tablename__ = "image_annotations"
    __table_args__ = (Index("ix_image_annotations_image", "image_id"),)

    image_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claim_images.id", ondelete="CASCADE"), nullable=False
    )
    annotation_type: Mapped[AnnotationType] = mapped_column(
        enum_type(AnnotationType), nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), default="customer_selected_damage", nullable=False)
    points: Mapped[list[list[float]]] = mapped_column(JSONDoc, nullable=False)
    color: Mapped[str | None] = mapped_column(String(16))
    stroke_width: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    text_content: Mapped[str | None] = mapped_column(String(400))
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )

    image: Mapped[ClaimImage] = relationship(back_populates="annotations")


class CustomerDamageReport(Base, UUIDPrimaryKey, Timestamped):
    """What the customer believes is damaged.

    Kept strictly separate from AI findings so the two can be compared rather than merged.
    """

    __tablename__ = "customer_damage_reports"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("claims.id", ondelete="CASCADE"),
        unique=True, nullable=False,
    )
    reported_parts: Mapped[list[str]] = mapped_column(JSONDoc, default=list, nullable=False)
    free_text_parts: Mapped[str | None] = mapped_column(Text)

    # Output of the customer-input extraction prompt over the free text.
    structured_extraction: Mapped[dict[str, Any]] = mapped_column(
        JSONDoc, default=dict, nullable=False
    )
    extracted_parts: Mapped[list[str]] = mapped_column(JSONDoc, default=list, nullable=False)
    possible_impact_area: Mapped[str | None] = mapped_column(String(60))
    mentioned_location: Mapped[str | None] = mapped_column(String(200))
    extraction_confidence: Mapped[float | None] = mapped_column(Float)

    claim: Mapped["Claim"] = relationship(back_populates="damage_report")

    @property
    def all_reported_part_codes(self) -> list[str]:
        """Checkbox selections plus anything the extractor recovered from free text."""
        return sorted({*self.reported_parts, *self.extracted_parts})

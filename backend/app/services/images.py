"""Image upload, metadata capture, annotation and the location resolution chain."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import ImageRole, ImageValidationStatus, LocationSource
from app.core.errors import ConflictError, InvalidClaimStateError, NotFoundError, ValidationError_
from app.core.logging import get_logger
from app.media import annotations as annotation_render
from app.media.exif import extract_exif
from app.media.images import inspect_image
from app.media.storage import get_storage
from app.models.claim import Claim, ClaimLocation
from app.models.image import ClaimImage, ImageAnnotation, ImageMetadata
from app.models.user import User
from app.schemas.claim import AnnotationRegion
from app.services import audit

log = get_logger(__name__)


class ImageService:
    def __init__(self, db: Session):
        self.db = db
        self.storage = get_storage()

    def upload(
        self,
        claim: Claim,
        *,
        data: bytes,
        filename: str,
        content_type: str,
        image_role: ImageRole,
        customer_note: str | None,
        actor: User,
    ) -> ClaimImage:
        if not claim.is_editable_by_customer:
            raise InvalidClaimStateError("Images can only be added before the claim is submitted.")

        if len(claim.images) >= settings.max_images_per_claim:
            raise ValidationError_(
                f"A claim can hold at most {settings.max_images_per_claim} images."
            )

        inspection = inspect_image(data, content_type, filename)
        if inspection.is_rejected:
            raise ValidationError_(
                "This image cannot be used.", {"reasons": "; ".join(inspection.errors)}
            )

        duplicate = self.db.scalar(
            select(ClaimImage).where(
                ClaimImage.claim_id == claim.id, ClaimImage.sha256 == inspection.sha256
            )
        )
        if duplicate is not None:
            raise ConflictError("This exact image has already been uploaded to this claim.")

        key = self.storage.build_key(claim.id, filename)
        self.storage.put(key, data, content_type)

        image = ClaimImage(
            claim_id=claim.id,
            storage_key=key,
            original_filename=filename[:255],
            mime_type=content_type,
            file_size=len(data),
            width=inspection.width,
            height=inspection.height,
            sha256=inspection.sha256,
            perceptual_hash=inspection.perceptual_hash,
            image_role=image_role,
            display_order=len(claim.images),
            quality_score=inspection.quality_score,
            blur_score=inspection.blur_score,
            brightness_score=inspection.brightness_score,
            validation_status=inspection.status,
            validation_errors=inspection.all_messages,
            customer_note=customer_note,
        )
        self.db.add(image)
        self.db.flush()

        self._store_metadata(image, data)

        audit.record(
            self.db, action="claim.image_upload", entity_type="claim_image", entity_id=image.id,
            actor=actor,
            after={"claim_id": str(claim.id), "role": image_role.value, "size": len(data)},
        )
        log.info("image.uploaded", image_id=str(image.id), claim_id=str(claim.id))
        return image

    def _store_metadata(self, image: ClaimImage, data: bytes) -> ImageMetadata:
        exif = extract_exif(data)
        metadata = ImageMetadata(
            image_id=image.id,
            has_exif=exif.has_exif,
            captured_at=exif.captured_at,
            gps_latitude=exif.gps_latitude,
            gps_longitude=exif.gps_longitude,
            gps_altitude=exif.gps_altitude,
            camera_make=exif.camera_make,
            camera_model=exif.camera_model,
            software=exif.software,
            orientation=exif.orientation,
            raw_exif=exif.raw,
        )
        self.db.add(metadata)
        self.db.flush()
        return metadata

    def delete(self, claim: Claim, image_id: uuid.UUID, actor: User) -> None:
        if not claim.is_editable_by_customer:
            raise InvalidClaimStateError("Images can only be removed before submission.")

        image = self.db.scalar(
            select(ClaimImage).where(ClaimImage.id == image_id, ClaimImage.claim_id == claim.id)
        )
        if image is None:
            raise NotFoundError("Image not found on this claim.")

        self.storage.delete(image.storage_key)
        if image.annotated_storage_key:
            self.storage.delete(image.annotated_storage_key)

        self.db.delete(image)
        self.db.flush()
        audit.record(
            self.db, action="claim.image_delete", entity_type="claim_image",
            entity_id=image_id, actor=actor,
        )

    def annotate(
        self,
        claim: Claim,
        image_id: uuid.UUID,
        regions: list[AnnotationRegion],
        actor: User,
        *,
        replace_existing: bool = True,
    ) -> ClaimImage:
        image = self.db.scalar(
            select(ClaimImage).where(ClaimImage.id == image_id, ClaimImage.claim_id == claim.id)
        )
        if image is None:
            raise NotFoundError("Image not found on this claim.")
        if not claim.is_editable_by_customer:
            raise InvalidClaimStateError("Annotations can only be changed before submission.")

        if replace_existing:
            for existing in list(image.annotations):
                self.db.delete(existing)
            self.db.flush()

        for region in regions:
            self.db.add(
                ImageAnnotation(
                    image_id=image.id,
                    annotation_type=region.annotation_type,
                    label=region.label,
                    points=[[float(p[0]), float(p[1])] for p in region.points],
                    color=region.color,
                    stroke_width=region.stroke_width,
                    text_content=region.text_content,
                    note=region.note,
                    created_by_user_id=actor.id,
                )
            )
        self.db.flush()
        self.db.refresh(image)

        self._render_overlay(image)

        audit.record(
            self.db, action="claim.image_annotate", entity_type="claim_image",
            entity_id=image.id, actor=actor, after={"regions": len(regions)},
        )
        return image

    def _render_overlay(self, image: ClaimImage) -> None:
        """Re-render the annotated copy from the stored coordinates.

        Rendering server-side (rather than accepting a client-uploaded overlay) keeps the
        annotated image provably derived from the original plus the recorded regions.
        """
        if not image.annotations:
            if image.annotated_storage_key:
                self.storage.delete(image.annotated_storage_key)
                image.annotated_storage_key = None
            return

        try:
            original = self.storage.get(image.storage_key)
            rendered = annotation_render.render_annotated_image(
                original,
                [
                    {
                        "annotation_type": a.annotation_type,
                        "points": a.points,
                        "color": a.color,
                        "stroke_width": a.stroke_width,
                        "text_content": a.text_content,
                        "label": a.label,
                    }
                    for a in image.annotations
                ],
            )
        except Exception as exc:  # noqa: BLE001 — the coordinates are the record of truth
            log.warning("annotation.render_failed", image_id=str(image.id), error=str(exc))
            return

        key = image.annotated_storage_key or self.storage.build_key(
            image.claim_id, image.original_filename or "annotated.jpg", variant="annotated"
        )
        self.storage.put(key, rendered, "image/jpeg")
        image.annotated_storage_key = key
        self.db.flush()

    def resolve_location_from_exif(self, claim: Claim) -> ClaimLocation | None:
        """First link in the location chain: EXIF GPS → device GPS → manual selection.

        Only this method may write `EXIF_GPS`, and only from a tag actually present in an
        uploaded file. A claim with no obtainable location simply has no location row.
        Photo GPS is queried from the database so a just-uploaded image is included even
        when the in-memory `claim.images` collection is stale.
        """
        metadata_rows = self.db.scalars(
            select(ImageMetadata)
            .join(ClaimImage)
            .where(ClaimImage.claim_id == claim.id)
            .order_by(ClaimImage.created_at)
        ).all()
        candidates = [row for row in metadata_rows if row.has_gps]
        if not candidates:
            return claim.location

        source_metadata = candidates[0]
        latitude = source_metadata.gps_latitude
        longitude = source_metadata.gps_longitude
        if latitude is None or longitude is None:
            return claim.location

        if claim.location is None:
            location = ClaimLocation(
                claim_id=claim.id,
                latitude=latitude,
                longitude=longitude,
                source=LocationSource.EXIF_GPS,
            )
            self.db.add(location)
            self.db.flush()
            claim.location = location
            log.info("location.from_exif", claim_id=str(claim.id))
            return location

        if claim.location.source is not LocationSource.EXIF_GPS:
            claim.location.latitude = latitude
            claim.location.longitude = longitude
            claim.location.source = LocationSource.EXIF_GPS
            self.db.flush()
            log.info("location.upgraded_to_exif", claim_id=str(claim.id))
        return claim.location

    def presign(self, image: ClaimImage) -> tuple[str | None, str | None]:
        return (
            self.storage.presigned_url(image.storage_key),
            self.storage.presigned_url(image.annotated_storage_key),
        )

    def usable_images(self, claim: Claim) -> list[ClaimImage]:
        return [
            image
            for image in sorted(claim.images, key=lambda i: i.display_order)
            if image.validation_status is not ImageValidationStatus.REJECTED
        ]

"""Risk and consistency signals.

Every detector answers a narrow, evidence-based question and returns what it observed. None
of them decides anything: a HIGH signal routes a claim to a human with an explanation, and
that is the entire extent of their authority. Nothing here can reject a claim.

Most of these findings have innocent explanations — messaging apps strip EXIF, people
photograph a car the day after an accident, a repeat claimant may simply be unlucky. The
descriptions are written to say what was observed, not to accuse.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import RiskLevel
from app.core.logging import get_logger
from app.media.images import hamming_distance
from app.models.claim import Claim
from app.models.image import ClaimImage
from app.models.ops import FraudSignal

log = get_logger(__name__)

DETECTOR_VERSION = "1.0"

# Perceptual-hash distance below which two photographs are effectively the same image.
_NEAR_DUPLICATE_THRESHOLD = 8


@dataclass
class Signal:
    code: str
    risk_level: RiskLevel
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _duplicate_images_within_claim(claim: Claim) -> list[Signal]:
    signals: list[Signal] = []
    images = [i for i in claim.images if i.perceptual_hash]

    for i, first in enumerate(images):
        for second in images[i + 1 :]:
            distance = hamming_distance(first.perceptual_hash, second.perceptual_hash)
            if distance is not None and distance <= _NEAR_DUPLICATE_THRESHOLD:
                signals.append(
                    Signal(
                        "DUPLICATE_IMAGE_IN_CLAIM",
                        RiskLevel.LOW,
                        f"Two uploaded photographs are visually near-identical "
                        f"({first.original_filename or 'image'} and "
                        f"{second.original_filename or 'image'}). This is usually an "
                        f"accidental double upload rather than anything untoward, but it "
                        f"means the evidence covers less ground than the image count suggests.",
                        {"image_ids": [str(first.id), str(second.id)], "distance": distance},
                    )
                )
    return signals


def _reused_images_across_claims(db: Session, claim: Claim) -> list[Signal]:
    signals: list[Signal] = []

    for image in claim.images:
        matches = db.scalars(
            select(ClaimImage).where(
                ClaimImage.sha256 == image.sha256,
                ClaimImage.claim_id != claim.id,
            )
        ).all()
        if not matches:
            continue

        other_claims = {str(m.claim_id) for m in matches}
        signals.append(
            Signal(
                "IMAGE_REUSED_ACROSS_CLAIMS",
                RiskLevel.HIGH,
                f"A photograph on this claim is byte-identical to one submitted on "
                f"{len(other_claims)} other claim(s). The same image appearing on separate "
                f"claims needs an explanation before the evidence can be relied upon.",
                {"image_id": str(image.id), "other_claim_ids": sorted(other_claims)},
            )
        )
    return signals


def _metadata_consistency(claim: Claim) -> list[Signal]:
    signals: list[Signal] = []
    metadata = [i.image_metadata for i in claim.images if i.image_metadata]

    if metadata and not any(m.has_exif for m in metadata):
        signals.append(
            Signal(
                "NO_EXIF_ON_ANY_IMAGE",
                RiskLevel.LOW,
                "None of the uploaded photographs carry EXIF metadata. Messaging apps and "
                "social platforms strip it routinely, so this is common and not suspicious "
                "on its own — but it does mean capture time and location cannot be verified "
                "from the files.",
                {"image_count": len(metadata)},
            )
        )

    editors = {
        m.software for m in metadata
        if m.software and any(
            tool in m.software.lower()
            for tool in ("photoshop", "gimp", "lightroom", "snapseed", "facetune", "generated")
        )
    }
    if editors:
        signals.append(
            Signal(
                "IMAGE_EDITING_SOFTWARE_DETECTED",
                RiskLevel.MEDIUM,
                f"EXIF on one or more photographs names image-editing software "
                f"({', '.join(sorted(editors))}). Cropping and rotating are ordinary, but the "
                f"images should be checked before their content is treated as unaltered.",
                {"software": sorted(editors)},
            )
        )

    captures = [m.captured_at for m in metadata if m.captured_at]
    if len(captures) >= 2:
        span = max(captures) - min(captures)
        if span > timedelta(days=7):
            signals.append(
                Signal(
                    "CAPTURE_TIMES_WIDELY_SEPARATED",
                    RiskLevel.MEDIUM,
                    f"The photographs were taken {span.days} days apart. Evidence for a "
                    f"single incident would normally be captured together.",
                    {
                        "earliest": min(captures).isoformat(),
                        "latest": max(captures).isoformat(),
                        "span_days": span.days,
                    },
                )
            )

    if claim.accident_datetime and captures:
        earliest = min(captures)
        accident = claim.accident_datetime
        if accident.tzinfo is None:
            accident = accident.replace(tzinfo=UTC)
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=UTC)

        if earliest < accident - timedelta(hours=2):
            signals.append(
                Signal(
                    "PHOTO_PREDATES_ACCIDENT",
                    RiskLevel.HIGH,
                    f"A photograph's EXIF capture time ({earliest.isoformat()}) is earlier "
                    f"than the stated accident time ({accident.isoformat()}). Either the "
                    f"stated time is wrong or the photograph is not of this incident.",
                    {"captured_at": earliest.isoformat(), "accident_at": accident.isoformat()},
                )
            )

    return signals


def _location_consistency(claim: Claim) -> list[Signal]:
    signals: list[Signal] = []
    points = [
        (m.gps_latitude, m.gps_longitude)
        for m in (i.image_metadata for i in claim.images)
        if m and m.has_gps
    ]

    if len(points) >= 2:
        # Rough degree-to-kilometre conversion; precise enough to spot "different city".
        max_km = 0.0
        for i, (lat1, lon1) in enumerate(points):
            for lat2, lon2 in points[i + 1 :]:
                km = (((lat1 - lat2) * 111) ** 2 + ((lon1 - lon2) * 111) ** 2) ** 0.5
                max_km = max(max_km, km)

        if max_km > 50:
            signals.append(
                Signal(
                    "IMAGE_LOCATIONS_INCONSISTENT",
                    RiskLevel.MEDIUM,
                    f"Photographs on this claim carry GPS tags roughly {max_km:.0f} km apart, "
                    f"which is hard to reconcile with a single incident scene.",
                    {"max_separation_km": round(max_km, 1)},
                )
            )
    return signals


def _repeat_claims(db: Session, claim: Claim) -> list[Signal]:
    ninety_days_ago = datetime.now(UTC) - timedelta(days=90)
    count = db.scalar(
        select(func.count())
        .select_from(Claim)
        .where(
            Claim.customer_id == claim.customer_id,
            Claim.id != claim.id,
            Claim.created_at >= ninety_days_ago,
            Claim.deleted_at.is_(None),
        )
    ) or 0

    if count >= 3:
        return [
            Signal(
                "FREQUENT_CLAIMS",
                RiskLevel.MEDIUM,
                f"This customer has filed {count} other claim(s) in the past 90 days. "
                f"Frequency alone proves nothing, but the history is worth reviewing "
                f"alongside this claim.",
                {"claims_in_90_days": count},
            )
        ]
    return []


def _vehicle_conflict(claim: Claim) -> list[Signal]:
    assessment = claim.latest_assessment
    if assessment is None or not assessment.vehicle_conflict:
        return []

    return [
        Signal(
            "VEHICLE_INFORMATION_CONFLICT",
            RiskLevel.MEDIUM,
            assessment.vehicle_conflict_detail
            or "The vehicle identified from the photographs does not match the details the "
            "customer provided.",
            {
                "stated": f"{claim.stated_make or '?'} {claim.stated_model or '?'}",
                "detected": assessment.vehicle_label,
            },
        )
    ]


def _image_quality(claim: Claim) -> list[Signal]:
    poor = [i for i in claim.images if (i.quality_score or 1.0) < 0.35]
    if not poor:
        return []

    return [
        Signal(
            "POOR_IMAGE_QUALITY",
            RiskLevel.LOW,
            f"{len(poor)} of {len(claim.images)} photograph(s) scored poorly for sharpness "
            f"and exposure. Damage detection on those images is correspondingly less reliable.",
            {"image_ids": [str(i.id) for i in poor]},
        )
    ]


def run_all(db: Session, claim: Claim) -> list[FraudSignal]:
    """Run every detector and persist the findings."""
    signals: list[Signal] = []
    for detector in (
        lambda: _duplicate_images_within_claim(claim),
        lambda: _reused_images_across_claims(db, claim),
        lambda: _metadata_consistency(claim),
        lambda: _location_consistency(claim),
        lambda: _repeat_claims(db, claim),
        lambda: _vehicle_conflict(claim),
        lambda: _image_quality(claim),
    ):
        try:
            signals.extend(detector())
        except Exception as exc:  # noqa: BLE001 — one broken detector must not stop the rest
            log.warning("fraud.detector_failed", error=str(exc))

    persisted: list[FraudSignal] = []
    for signal in signals:
        row = FraudSignal(
            claim_id=claim.id,
            signal_code=signal.code,
            risk_level=signal.risk_level,
            description=signal.description,
            evidence=signal.evidence,
            detector_version=DETECTOR_VERSION,
        )
        db.add(row)
        persisted.append(row)

    db.flush()
    log.info("fraud.evaluated", claim_id=str(claim.id), signals=len(persisted))
    return persisted


def overall_risk(signals: list[FraudSignal]) -> RiskLevel:
    if any(s.risk_level is RiskLevel.HIGH for s in signals):
        return RiskLevel.HIGH
    if any(s.risk_level is RiskLevel.MEDIUM for s in signals):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW

"""Background tasks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urljoin

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.enums import ClaimStatus, MarketSourceType
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.claim import Claim
from app.models.image import ClaimImage
from app.models.market import MarketSource

log = get_logger(__name__)


def _load_claim(db, claim_id: uuid.UUID) -> Claim | None:
    return db.scalar(
        select(Claim)
        .where(Claim.id == claim_id, Claim.deleted_at.is_(None))
        .options(
            selectinload(Claim.images).selectinload(ClaimImage.image_metadata),
            selectinload(Claim.images).selectinload(ClaimImage.annotations),
            selectinload(Claim.damage_report),
            selectinload(Claim.assessments),
            selectinload(Claim.estimates),
            selectinload(Claim.valuations),
            selectinload(Claim.fraud_signals),
            selectinload(Claim.location),
            selectinload(Claim.customer),
        )
    )


@shared_task(
    bind=True,
    name="app.workers.tasks.run_claim_pipeline",
    max_retries=2,
    default_retry_delay=60,
)
def run_claim_pipeline(self, claim_id: str) -> dict:
    """Run the full assessment pipeline for one claim.

    The task is idempotent by status: a claim already past analysis is not reprocessed, so
    a redelivered message cannot produce a duplicate assessment.
    """
    from app.ai.pipeline import ClaimAssessmentPipeline

    identifier = uuid.UUID(claim_id)

    with session_scope() as db:
        claim = _load_claim(db, identifier)
        if claim is None:
            log.warning("pipeline.claim_missing", claim_id=claim_id)
            return {"status": "not_found", "claim_id": claim_id}

        if claim.status not in {ClaimStatus.SUBMITTED, ClaimStatus.PROCESSING}:
            log.info(
                "pipeline.skipped_already_processed",
                claim_id=claim_id, status=claim.status.value,
            )
            return {"status": "skipped", "claim_status": claim.status.value}

        try:
            ClaimAssessmentPipeline(db, claim).run()
        except Exception as exc:  # noqa: BLE001
            log.exception("pipeline.task_failed", claim_id=claim_id, error=str(exc))
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc) from exc
            # Out of retries: the claim is handed to a human rather than left in limbo.
            _force_manual_review(db, identifier, str(exc))
            return {"status": "failed_to_manual_review", "claim_id": claim_id}

        return {"status": "completed", "claim_id": claim_id, "claim_status": claim.status.value}


def _force_manual_review(db, claim_id: uuid.UUID, error: str) -> None:
    from app.services.claims import ClaimService

    claim = _load_claim(db, claim_id)
    if claim is None:
        return

    service = ClaimService(db)
    service.set_manual_review(
        claim,
        True,
        [
            "Automated analysis could not be completed after repeated attempts. "
            "This claim requires full manual assessment."
        ],
    )
    service.transition(
        claim, ClaimStatus.AGENT_REVIEW, None, f"Analysis failed: {error[:200]}", force=True
    )
    db.commit()


@shared_task(name="app.workers.tasks.reanalyze_claim")
def reanalyze_claim(claim_id: str, requested_by: str | None = None) -> dict:
    """Agent-triggered re-run. Adds a new assessment; the previous one is retained."""
    from app.ai.pipeline import ClaimAssessmentPipeline
    from app.services.claims import ClaimService

    identifier = uuid.UUID(claim_id)

    with session_scope() as db:
        claim = _load_claim(db, identifier)
        if claim is None:
            return {"status": "not_found"}

        ClaimService(db).transition(
            claim, ClaimStatus.PROCESSING, None,
            f"Re-analysis requested{f' by {requested_by}' if requested_by else ''}.",
            force=True,
        )
        db.commit()

        ClaimAssessmentPipeline(db, claim).run()
        return {"status": "completed", "claim_id": claim_id}


@shared_task(name="app.workers.tasks.retry_failed_notifications")
def retry_failed_notifications() -> dict:
    from app.notifications.service import NotificationService

    with session_scope() as db:
        retried = NotificationService(db).retry_pending()
        return {"retried": retried}


@shared_task(name="app.workers.tasks.refresh_market_source_robots")
def refresh_market_source_robots() -> dict:
    """Re-check robots.txt for every whitelisted scrape target.

    Permission is not a one-time question: a site can add a Disallow at any point, and this
    keeps the stored answer current rather than relying on a check made when the source was
    first added.
    """
    from app.market.fetcher import MarketFetcher

    fetcher = MarketFetcher()
    checked = 0

    with session_scope() as db:
        sources = db.scalars(
            select(MarketSource).where(MarketSource.source_type == MarketSourceType.SCRAPE)
        ).all()

        for source in sources:
            allowed, _ = fetcher.robots.allows(
                urljoin(source.base_url, "/"), settings.scraper_user_agent
            )
            source.robots_allows = allowed
            source.robots_checked_at = datetime.now(UTC)
            checked += 1

        db.commit()

    log.info("market.robots_refreshed", sources=checked)
    return {"checked": checked}

"""Run the claim pipeline without Celery/Redis (no-Docker local development)."""

from __future__ import annotations

import threading
import uuid

from app.core.logging import get_logger

log = get_logger(__name__)


def enqueue_claim_pipeline(claim_id: str, *, requested_by: str | None = None) -> None:
    """Prefer Celery; if Redis is down, run the pipeline on a background thread."""
    if _broker_up():
        from app.workers.tasks import reanalyze_claim, run_claim_pipeline

        if requested_by:
            reanalyze_claim.delay(claim_id, requested_by=requested_by)
        else:
            run_claim_pipeline.delay(claim_id)
        log.info("pipeline.enqueued_celery", claim_id=claim_id)
        return

    thread = threading.Thread(
        target=_run_in_thread,
        args=(claim_id, requested_by),
        daemon=True,
        name=f"claim-pipeline-{claim_id[:8]}",
    )
    thread.start()
    log.info("pipeline.enqueued_thread", claim_id=claim_id)


def _broker_up() -> bool:
    try:
        import redis

        from app.core.config import settings

        redis.from_url(settings.redis_url, socket_connect_timeout=0.4).ping()
        return True
    except Exception:
        return False


def _run_in_thread(claim_id: str, requested_by: str | None) -> None:
    from app.ai.pipeline import ClaimAssessmentPipeline
    from app.core.enums import ClaimStatus
    from app.db.session import session_scope
    from app.services.claims import ClaimService
    from app.workers.tasks import _load_claim

    identifier = uuid.UUID(claim_id)
    try:
        with session_scope() as db:
            claim = _load_claim(db, identifier)
            if claim is None:
                return
            if requested_by:
                ClaimService(db).transition(
                    claim,
                    ClaimStatus.PROCESSING,
                    None,
                    f"Re-analysis requested by {requested_by}.",
                    force=True,
                )
                db.commit()
                claim = _load_claim(db, identifier)
            if claim is None:
                return
            ClaimAssessmentPipeline(db, claim).run()
    except Exception:
        log.exception("pipeline.thread_failed", claim_id=claim_id)

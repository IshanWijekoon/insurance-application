"""Celery application."""

from __future__ import annotations

from celery import Celery
from celery.signals import setup_logging

from app.core.config import settings
from app.core.logging import configure_logging

celery_app = Celery(
    "ai_motor_claims",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Claim analysis makes several provider round trips plus market fetches; the ceiling is
    # generous but finite so a wedged task cannot hold a worker slot indefinitely.
    task_time_limit=15 * 60,
    task_soft_time_limit=13 * 60,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    broker_connection_retry_on_startup=True,
    task_default_retry_delay=30,
    task_max_retries=3,
    beat_schedule={
        "retry-failed-notifications": {
            "task": "app.workers.tasks.retry_failed_notifications",
            "schedule": 300.0,
        },
        "refresh-robots-permissions": {
            "task": "app.workers.tasks.refresh_market_source_robots",
            "schedule": 24 * 3600.0,
        },
    },
)


@setup_logging.connect
def _configure(**_: object) -> None:
    configure_logging()

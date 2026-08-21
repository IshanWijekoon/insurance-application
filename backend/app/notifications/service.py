"""Notification composition and multi-channel delivery.

Every notification is persisted first, then delivered. If email or SMS is down the record
still exists, still shows in the in-app centre, and can be retried — a delivery failure
never means an agent silently never hears about a claim.
"""

from __future__ import annotations

import smtplib
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.enums import DeliveryStatus, NotificationChannel, UserRole
from app.core.logging import get_logger
from app.models.claim import Claim
from app.models.ops import Notification
from app.models.user import Agent, User
from app.notifications import hub

log = get_logger(__name__)

MAX_DELIVERY_ATTEMPTS = 3


class NotificationService:
    def __init__(self, db: Session):
        self.db = db

    # ── Creation ────────────────────────────────────────────

    def create(
        self,
        *,
        recipient: User,
        notification_type: str,
        title: str,
        body: str,
        claim_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
        channels: list[NotificationChannel] | None = None,
    ) -> list[Notification]:
        channels = channels or [NotificationChannel.IN_APP, NotificationChannel.WEBSOCKET]
        created: list[Notification] = []

        for channel in channels:
            notification = Notification(
                recipient_user_id=recipient.id,
                claim_id=claim_id,
                channel=channel,
                notification_type=notification_type,
                title=title,
                body=body,
                payload=payload or {},
            )
            self.db.add(notification)
            created.append(notification)

        self.db.flush()

        for notification in created:
            self._deliver(notification, recipient)

        return created

    def _deliver(self, notification: Notification, recipient: User) -> None:
        notification.delivery_attempts += 1
        try:
            if notification.channel is NotificationChannel.IN_APP:
                pass  # persistence is the delivery
            elif notification.channel is NotificationChannel.WEBSOCKET:
                hub.publish_to_user(
                    recipient.id,
                    {
                        "type": "notification",
                        "id": str(notification.id),
                        "notification_type": notification.notification_type,
                        "title": notification.title,
                        "body": notification.body,
                        "claim_id": str(notification.claim_id) if notification.claim_id else None,
                        "payload": notification.payload,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                )
            elif notification.channel is NotificationChannel.EMAIL:
                self._send_email(recipient.email, notification.title, notification.body)
            elif notification.channel is NotificationChannel.SMS:
                self._send_sms(recipient.phone, notification.body)

            notification.delivery_status = DeliveryStatus.SENT
            notification.sent_at = datetime.now(UTC)
            notification.last_error = None
        except Exception as exc:  # noqa: BLE001 — delivery is best-effort by design
            notification.last_error = str(exc)[:500]
            notification.delivery_status = (
                DeliveryStatus.RETRYING
                if notification.delivery_attempts < MAX_DELIVERY_ATTEMPTS
                else DeliveryStatus.FAILED
            )
            log.warning(
                "notification.delivery_failed",
                channel=notification.channel.value,
                attempt=notification.delivery_attempts,
                error=str(exc),
            )

        self.db.flush()

    def retry_pending(self, limit: int = 50) -> int:
        """Re-attempt deliveries that failed but have attempts remaining."""
        pending = self.db.scalars(
            select(Notification)
            .where(
                Notification.delivery_status == DeliveryStatus.RETRYING,
                Notification.delivery_attempts < MAX_DELIVERY_ATTEMPTS,
            )
            .limit(limit)
        ).all()

        for notification in pending:
            recipient = self.db.get(User, notification.recipient_user_id)
            if recipient is not None:
                self._deliver(notification, recipient)

        return len(pending)

    # ── Channels ────────────────────────────────────────────

    def _send_email(self, to_address: str, subject: str, body: str) -> None:
        if not settings.email_enabled:
            raise RuntimeError("Email delivery is disabled (EMAIL_ENABLED=false).")
        if not settings.smtp_host:
            raise RuntimeError("SMTP_HOST is not configured.")

        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = to_address
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)

    def _send_sms(self, phone: str | None, body: str) -> None:
        if not settings.sms_enabled:
            raise RuntimeError("SMS delivery is disabled (SMS_ENABLED=false).")
        if not phone:
            raise RuntimeError("The recipient has no phone number on file.")
        # Providers differ enough that a concrete integration belongs behind this method
        # rather than in a half-generic abstraction. Configure SMS_PROVIDER and implement
        # the call here.
        raise NotImplementedError(
            f"No SMS integration is implemented for provider '{settings.sms_provider}'."
        )

    # ── Domain events ───────────────────────────────────────

    def notify_claim_submitted(self, claim: Claim) -> None:
        """Alert agents as soon as a customer submits, so the claim can be watched."""
        location = claim.location
        vehicle = None
        if claim.vehicle:
            vehicle = claim.vehicle.display_name
        else:
            parts = [str(p) for p in (claim.stated_make, claim.stated_model, claim.stated_year) if p]
            vehicle = " ".join(parts) or None
        summary = {
            "vehicle": vehicle,
            "image_count": len(claim.images),
            "location": (
                f"{location.latitude:.5f}, {location.longitude:.5f}"
                if location
                else None
            ),
            "submitted_at": claim.submitted_at.isoformat() if claim.submitted_at else None,
            "estimate": None,
            "customer_reported": None,
            "ai_detected": None,
            "vehicle_value": None,
            "manual_review_reasons": [],
        }
        self._notify_agents(
            claim,
            summary,
            notification_type="claim.submitted",
            title=f"New claim submitted {claim.claim_number}",
        )

    def notify_new_claim(self, claim: Claim, summary_lines: dict[str, Any]) -> None:
        """Alert agents the moment a claim finishes analysis and is ready to verify."""
        self._notify_agents(
            claim,
            summary_lines,
            notification_type="claim.ready",
            title=f"Claim ready to verify {claim.claim_number}",
        )

    def _notify_agents(
        self,
        claim: Claim,
        summary_lines: dict[str, Any],
        *,
        notification_type: str,
        title: str,
    ) -> None:
        recipients = self._agent_recipients(claim)
        body = self._format_agent_alert(claim, summary_lines)

        channels = [NotificationChannel.IN_APP, NotificationChannel.WEBSOCKET]
        if settings.email_enabled:
            channels.append(NotificationChannel.EMAIL)
        if settings.sms_enabled and claim.priority.value in {"HIGH", "URGENT"}:
            channels.append(NotificationChannel.SMS)

        for recipient in recipients:
            self.create(
                recipient=recipient,
                notification_type=notification_type,
                title=title,
                body=body,
                claim_id=claim.id,
                payload=summary_lines,
                channels=channels,
            )

        hub.publish_to_agents(
            {
                "type": notification_type,
                "claim_id": str(claim.id),
                "claim_number": claim.claim_number,
                **summary_lines,
            }
        )

    def notify_claim_status(self, claim: Claim, title: str, body: str) -> None:
        customer_user = claim.customer.user if claim.customer else None
        if customer_user is None:
            return

        channels = [NotificationChannel.IN_APP, NotificationChannel.WEBSOCKET]
        if settings.email_enabled:
            channels.append(NotificationChannel.EMAIL)

        self.create(
            recipient=customer_user,
            notification_type="claim.status",
            title=title,
            body=body,
            claim_id=claim.id,
            payload={"status": claim.status.value},
            channels=channels,
        )

    def _agent_recipients(self, claim: Claim) -> list[User]:
        if claim.assigned_agent_id:
            agent = self.db.scalar(
                select(Agent)
                .options(selectinload(Agent.user))
                .where(Agent.id == claim.assigned_agent_id)
            )
            if agent and agent.user:
                return [agent.user]

        agents = self.db.scalars(
            select(Agent)
            .options(selectinload(Agent.user))
            .where(Agent.is_available.is_(True), Agent.deleted_at.is_(None))
        ).all()
        recipients = [a.user for a in agents if a.user and a.user.is_active]

        if recipients:
            return recipients

        # No agent is available: fall back to admins so the claim is never unwatched.
        admins = self.db.scalars(
            select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
        ).all()
        log.warning("notification.no_agents_available", claim_id=str(claim.id))
        return list(admins)

    @staticmethod
    def _format_agent_alert(claim: Claim, summary: dict[str, Any]) -> str:
        lines = [
            f"Claim: {claim.claim_number}",
            f"Vehicle: {summary.get('vehicle') or 'Not identified'}",
            f"Reported damage: {summary.get('customer_reported') or 'None reported'}",
            f"AI detected: {summary.get('ai_detected') or 'None detected'}",
            f"Estimated damage: {summary.get('estimate') or 'Unavailable — manual verification required'}",
            f"Vehicle value: {summary.get('vehicle_value') or 'Unavailable — manual verification required'}",
            f"Location: {summary.get('location') or 'Not available'}",
            f"Images: {summary.get('image_count', 0)}",
            f"Status: {claim.status.value.replace('_', ' ').title()}",
        ]
        if summary.get("manual_review_reasons"):
            lines.append("")
            lines.append("Manual review required because:")
            lines.extend(f"  - {reason}" for reason in summary["manual_review_reasons"])
        return "\n".join(lines)

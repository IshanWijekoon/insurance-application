"""Registration, login, refresh rotation and logout."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.core.errors import AuthenticationError, ConflictError
from app.core.logging import get_logger
from app.core.security import (
    ACCESS_TOKEN,
    REFRESH_TOKEN,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from app.models.user import Agent, Customer, RefreshSession, User
from app.schemas.auth import RegisterRequest
from app.services import audit

log = get_logger(__name__)


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    # ── Registration ────────────────────────────────────────

    def register_customer(self, payload: RegisterRequest, *, ip: str | None = None) -> User:
        existing = self.db.scalar(select(User).where(User.email == payload.email.lower()))
        if existing:
            raise ConflictError("An account with this email address already exists.")

        user = User(
            email=payload.email.lower(),
            password_hash=hash_password(payload.password),
            full_name=payload.full_name.strip(),
            phone=payload.phone,
            role=UserRole.CUSTOMER,
        )
        self.db.add(user)
        self.db.flush()

        self.db.add(Customer(user_id=user.id))
        self.db.flush()

        audit.record(
            self.db, action="user.register", entity_type="user", entity_id=user.id,
            actor=user, after={"email": user.email, "role": user.role.value}, ip_address=ip,
        )
        log.info("auth.registered", user_id=str(user.id))
        return user

    def create_staff_user(
        self, *, email: str, password: str, full_name: str, role: UserRole,
        employee_code: str | None = None, branch: str | None = None,
        region: str | None = None, actor: User | None = None,
    ) -> User:
        """Agents and admins are provisioned, never self-registered."""
        if self.db.scalar(select(User).where(User.email == email.lower())):
            raise ConflictError("An account with this email address already exists.")

        user = User(
            email=email.lower(),
            password_hash=hash_password(password),
            full_name=full_name.strip(),
            role=role,
        )
        self.db.add(user)
        self.db.flush()

        if role is UserRole.AGENT:
            self.db.add(
                Agent(
                    user_id=user.id,
                    employee_code=employee_code or f"AG-{str(user.id)[:8].upper()}",
                    branch=branch,
                    region=region,
                )
            )
        self.db.flush()

        audit.record(
            self.db, action="user.provision", entity_type="user", entity_id=user.id,
            actor=actor, after={"email": user.email, "role": role.value},
        )
        return user

    # ── Login / tokens ──────────────────────────────────────

    def authenticate(self, email: str, password: str) -> User:
        user = self.db.scalar(select(User).where(User.email == email.lower()))

        # Verify even when the user is missing so a wrong email and a wrong password take
        # comparable time and cannot be distinguished by response latency.
        password_ok = verify_password(
            password,
            user.password_hash if user else "$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "B" * 43,
        )

        if not user or not password_ok:
            raise AuthenticationError("Email address or password is incorrect.")
        if not user.is_active or user.deleted_at is not None:
            raise AuthenticationError("This account has been deactivated.")

        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        user.last_login_at = datetime.now(UTC)
        return user

    def issue_tokens(
        self, user: User, *, user_agent: str | None = None, ip: str | None = None,
        family_id: str | None = None,
    ) -> tuple[str, datetime, str]:
        access_token, access_expires = create_access_token(user.id, user.role.value)
        refresh_token, family, refresh_expires = create_refresh_token(user.id, family_id)

        self.db.add(
            RefreshSession(
                user_id=user.id,
                token_hash=hash_token(refresh_token),
                family_id=family,
                expires_at=refresh_expires,
                user_agent=user_agent[:400] if user_agent else None,
                ip_address=ip,
            )
        )
        self.db.flush()
        return access_token, access_expires, refresh_token

    def rotate_refresh_token(
        self, refresh_token: str, *, user_agent: str | None = None, ip: str | None = None
    ) -> tuple[User, str, datetime, str]:
        try:
            payload = decode_token(refresh_token, REFRESH_TOKEN)
        except TokenError as exc:
            raise AuthenticationError(str(exc)) from exc

        token_hash = hash_token(refresh_token)
        session = self.db.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == token_hash)
        )

        if session is None:
            raise AuthenticationError("This session is no longer valid. Please sign in again.")

        if session.revoked_at is not None:
            # The token was already rotated. Either it leaked or it was replayed; in both
            # cases every descendant of that login is now suspect.
            self._revoke_family(session.family_id)
            log.warning(
                "auth.refresh_reuse_detected",
                user_id=str(session.user_id), family=session.family_id,
            )
            raise AuthenticationError("This session was invalidated. Please sign in again.")

        if session.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
            raise AuthenticationError("This session has expired. Please sign in again.")

        user = self.db.get(User, uuid.UUID(payload["sub"]))
        if user is None or not user.is_active or user.deleted_at is not None:
            raise AuthenticationError("This account is no longer active.")

        session.revoked_at = datetime.now(UTC)
        access_token, access_expires, new_refresh = self.issue_tokens(
            user, user_agent=user_agent, ip=ip, family_id=session.family_id
        )
        return user, access_token, access_expires, new_refresh

    def logout(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        session = self.db.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == hash_token(refresh_token))
        )
        if session and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)

    def _revoke_family(self, family_id: str) -> None:
        sessions = self.db.scalars(
            select(RefreshSession).where(
                RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None)
            )
        ).all()
        now = datetime.now(UTC)
        for session in sessions:
            session.revoked_at = now

    def resolve_access_token(self, token: str) -> User:
        try:
            payload = decode_token(token, ACCESS_TOKEN)
        except TokenError as exc:
            raise AuthenticationError(str(exc)) from exc

        user = self.db.get(User, uuid.UUID(payload["sub"]))
        if user is None or not user.is_active or user.deleted_at is not None:
            raise AuthenticationError("This account is no longer active.")
        return user

"""FastAPI dependencies: database session, current user, role gates, rate limiting."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import UserRole
from app.core.errors import AuthenticationError, PermissionError_, RateLimitError
from app.db.session import get_db
from app.models.user import Agent, Customer, User
from app.services.auth import AuthService

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("A bearer token is required.")
    return AuthService(db).resolve_access_token(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionError_(
                "This action requires the "
                + " or ".join(r.value.lower() for r in roles)
                + " role."
            )
        return user

    return dependency


require_customer = require_roles(UserRole.CUSTOMER)
require_agent = require_roles(UserRole.AGENT, UserRole.ADMIN)
require_admin = require_roles(UserRole.ADMIN)

CustomerUser = Annotated[User, Depends(require_customer)]
AgentUser = Annotated[User, Depends(require_agent)]
AdminUser = Annotated[User, Depends(require_admin)]


def get_current_customer(db: DbSession, user: CustomerUser) -> Customer:
    customer = db.scalar(select(Customer).where(Customer.user_id == user.id))
    if customer is None:
        raise PermissionError_("No customer profile is attached to this account.")
    return customer


def get_current_agent(db: DbSession, user: AgentUser) -> Agent | None:
    """Admins legitimately have no agent row; agent-only data is guarded per endpoint."""
    return db.scalar(select(Agent).where(Agent.user_id == user.id))


CurrentCustomer = Annotated[Customer, Depends(get_current_customer)]
CurrentAgent = Annotated[Agent | None, Depends(get_current_agent)]


class SlidingWindowLimiter:
    """In-process limiter.

    Adequate for a single API container. Behind more than one replica this must move to
    Redis, otherwise the effective limit multiplies by the replica count.
    """

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        hits = [t for t in self._hits.get(key, []) if t > cutoff]

        if len(hits) >= limit:
            retry_in = int(window_seconds - (now - hits[0])) + 1
            raise RateLimitError(
                f"Too many requests. Try again in {retry_in} second(s).",
                {"retry_after": str(retry_in)},
            )

        hits.append(now)
        self._hits[key] = hits

        if len(self._hits) > 10_000:
            self._hits = {
                k: [t for t in v if t > cutoff]
                for k, v in self._hits.items()
                if any(t > cutoff for t in v)
            }


limiter = SlidingWindowLimiter()


def rate_limit(request: Request) -> None:
    limiter.check(f"general:{get_client_ip(request)}", settings.rate_limit_per_minute)


def auth_rate_limit(request: Request) -> None:
    limiter.check(f"auth:{get_client_ip(request)}", settings.auth_rate_limit_per_minute)


def db_session() -> Generator[Session, None, None]:
    yield from get_db()

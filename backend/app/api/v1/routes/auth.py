"""Authentication endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.api.deps import CurrentUser, DbSession, auth_rate_limit, get_client_ip
from app.core.config import settings
from app.core.enums import UserRole
from app.schemas.auth import (
    AgentProfile,
    CustomerProfile,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    TokenResponse,
    UserProfile,
)
from app.schemas.common import MessageResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    # Cross-origin frontend (Railway web → api) needs SameSite=None + Secure.
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        max_age=settings.refresh_token_days * 24 * 3600,
        path=f"{settings.api_v1_prefix}/auth",
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(auth_rate_limit)],
)
def register(payload: RegisterRequest, request: Request, response: Response, db: DbSession):
    """Self-registration creates a customer. Agent and admin accounts are provisioned."""
    service = AuthService(db)
    ip = get_client_ip(request)
    user = service.register_customer(payload, ip=ip)
    access_token, expires_at, refresh_token = service.issue_tokens(
        user, user_agent=request.headers.get("user-agent"), ip=ip
    )
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token,
        expires_at=expires_at,
        user=UserProfile.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(auth_rate_limit)])
def login(payload: LoginRequest, request: Request, response: Response, db: DbSession):
    service = AuthService(db)
    ip = get_client_ip(request)
    user = service.authenticate(payload.email, payload.password)
    access_token, expires_at, refresh_token = service.issue_tokens(
        user, user_agent=request.headers.get("user-agent"), ip=ip
    )
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token,
        expires_at=expires_at,
        user=UserProfile.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(auth_rate_limit)])
def refresh(
    request: Request,
    response: Response,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
):
    service = AuthService(db)
    user, access_token, expires_at, new_refresh = service.rotate_refresh_token(
        refresh_token or "",
        user_agent=request.headers.get("user-agent"),
        ip=get_client_ip(request),
    )
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(
        access_token=access_token,
        expires_at=expires_at,
        user=UserProfile.model_validate(user),
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    response: Response,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
):
    AuthService(db).logout(refresh_token)
    response.delete_cookie(
        REFRESH_COOKIE,
        path=f"{settings.api_v1_prefix}/auth",
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
    )
    return MessageResponse(message="Signed out.")


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser):
    return MeResponse(
        user=UserProfile.model_validate(user),
        customer=(
            CustomerProfile.model_validate(user.customer)
            if user.role is UserRole.CUSTOMER and user.customer
            else None
        ),
        agent=(
            AgentProfile.model_validate(user.agent)
            if user.role in {UserRole.AGENT, UserRole.ADMIN} and user.agent
            else None
        ),
    )

"""Password hashing and JWT issuance/verification."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()

ACCESS_TOKEN = "access"
REFRESH_TOKEN = "refresh"


class TokenError(Exception):
    """Raised when a token is malformed, expired or of the wrong type."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, role: str) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    token = _encode(
        {
            "sub": str(user_id),
            "role": role,
            "type": ACCESS_TOKEN,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": secrets.token_urlsafe(16),
        }
    )
    return token, expires


def create_refresh_token(user_id: uuid.UUID, family_id: str | None = None) -> tuple[str, str, datetime]:
    """Return ``(token, family_id, expires_at)``.

    Refresh tokens are issued in families. Rotation replaces a token within its family;
    presenting an already-rotated token means the token was stolen or replayed, so
    ``AuthService`` revokes the entire family rather than just the one row.
    """
    now = datetime.now(UTC)
    expires = now + timedelta(days=settings.refresh_token_days)
    family = family_id or secrets.token_urlsafe(16)
    token = _encode(
        {
            "sub": str(user_id),
            "type": REFRESH_TOKEN,
            "fam": family,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": secrets.token_urlsafe(16),
        }
    )
    return token, family, expires


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token is invalid") from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token")
    return payload


def hash_token(token: str) -> str:
    """Refresh tokens are stored hashed so a database leak cannot mint sessions."""
    return hashlib.sha256(token.encode()).hexdigest()

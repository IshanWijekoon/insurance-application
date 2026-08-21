"""Application error types and the single JSON error envelope."""

from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    code = "INTERNAL_ERROR"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "An unexpected error occurred."

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or {}


class AuthenticationError(AppError):
    code = "UNAUTHENTICATED"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Authentication is required."


class PermissionError_(AppError):
    code = "FORBIDDEN"
    status_code = status.HTTP_403_FORBIDDEN
    message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND
    message = "The requested resource was not found."


class ConflictError(AppError):
    code = "CONFLICT"
    status_code = status.HTTP_409_CONFLICT
    message = "The request conflicts with the current state."


class ValidationError_(AppError):
    code = "VALIDATION_ERROR"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "The submitted data is not valid."


class RateLimitError(AppError):
    code = "RATE_LIMITED"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Too many requests. Please slow down."


class ProviderUnavailableError(AppError):
    """An external dependency (AI provider, market source, storage) failed.

    This is deliberately distinct from a 500: the claim itself is intact and the work is
    routed to manual review rather than lost.
    """

    code = "PROVIDER_UNAVAILABLE"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "An external service is currently unavailable."


class InvalidClaimStateError(ConflictError):
    code = "INVALID_CLAIM_STATE"
    message = "This action is not allowed for the claim's current status."


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(exc.code, exc.message, exc.details),
    )


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {
        401: "UNAUTHENTICATED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        429: "RATE_LIMITED",
    }.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(status_code=exc.status_code, content=_envelope(code, str(exc.detail)))


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = {
        ".".join(str(p) for p in err["loc"][1:]) or "body": err["msg"] for err in exc.errors()
    }
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_envelope("VALIDATION_ERROR", "The submitted data is not valid.", fields),
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # The message is deliberately generic; the detail is in the structured log.
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope("INTERNAL_ERROR", "An unexpected error occurred."),
    )

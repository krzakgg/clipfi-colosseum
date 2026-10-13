"""RFC 7807 (application/problem+json) error handling.

Defines a small set of API errors that services raise, plus FastAPI exception
handlers that render them as problem+json so the Vue frontend can rely on a
consistent error shape.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

# Base for problem type URIs carrying a stable error code. RFC 7807 `type` is
# THE machine-readable problem identifier (our codes live as its trailing
# token, e.g. .../invalid_credentials — the frontend translates by it);
# errors without a code degrade to a generic per-status type.
_PROBLEM_TYPE_BASE = "https://errors.waggi.local"


class APIError(Exception):
    """Base API error rendered as RFC 7807 problem+json."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    title: str = "Bad Request"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        title: str | None = None,
        type_: str | None = None,
        instance: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        self.detail = detail
        self.code = code
        if status_code is not None:
            self.status_code = status_code
        if title is not None:
            self.title = title
        self.type = type_ or (f"{_PROBLEM_TYPE_BASE}/{code}" if code else f"https://httpstatuses.io/{self.status_code}")
        self.instance = instance
        self.extensions = extensions or {}
        super().__init__(detail or self.title)


class NotFoundError(APIError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Not Found"


class ConflictError(APIError):
    status_code = status.HTTP_409_CONFLICT
    title = "Conflict"


class ForbiddenError(APIError):
    status_code = status.HTTP_403_FORBIDDEN
    title = "Forbidden"


class UnauthorizedError(APIError):
    status_code = status.HTTP_401_UNAUTHORIZED
    title = "Unauthorized"


class ValidationError(APIError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    title = "Validation Error"


def _problem(
    err: APIError,
    request: Request,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": err.type,
        "title": err.title,
        "status": err.status_code,
        "detail": err.detail or err.title,
        "instance": err.instance or str(request.url.path),
    }
    body.update(err.extensions)
    return JSONResponse(status_code=err.status_code, content=body, media_type="application/problem+json")


def install_error_handlers(app: FastAPI) -> None:
    """Register problem+json exception handlers on a FastAPI app."""

    @app.exception_handler(APIError)
    async def _api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return _problem(exc, request)

    @app.exception_handler(Exception)
    async def _unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # Render unexpected errors as a generic 500 problem — never leak internals.
        generic = APIError(
            detail="An unexpected error occurred.",
            code="unexpected_error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Internal Server Error",
            instance=str(request.url.path),
        )
        return _problem(generic, request)


__all__ = [
    "APIError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "UnauthorizedError",
    "ValidationError",
    "install_error_handlers",
]

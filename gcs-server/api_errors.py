"""Shared GCS API error helpers and OpenAPI response metadata."""

from __future__ import annotations

import time
from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError

from schemas import ErrorDetail, ErrorResponse


DEFAULT_ERROR_RESPONSES = {
    401: {"model": ErrorResponse, "description": "Authentication Required"},
    403: {"model": ErrorResponse, "description": "Permission Denied"},
    400: {"model": ErrorResponse, "description": "Bad Request"},
    404: {"model": ErrorResponse, "description": "Not Found"},
    409: {"model": ErrorResponse, "description": "Conflict"},
    422: {"model": ErrorResponse, "description": "Validation Error"},
    500: {"model": ErrorResponse, "description": "Internal Server Error"},
    502: {"model": ErrorResponse, "description": "Bad Gateway"},
    503: {"model": ErrorResponse, "description": "Service Unavailable"},
}


_ERROR_TITLES = {
    401: "Authentication required",
    403: "Permission denied",
    400: "Bad request",
    404: "Not found",
    409: "Conflict",
    422: "Validation error",
    500: "Internal server error",
    502: "Bad gateway",
    503: "Service unavailable",
}


def _error_title(status_code: int) -> str:
    if status_code in _ERROR_TITLES:
        return _ERROR_TITLES[status_code]
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


def build_error_payload(
    request: Request,
    *,
    status_code: int,
    detail: Any = None,
    title: str | None = None,
) -> dict[str, Any]:
    return ErrorResponse(
        error=title or _error_title(status_code),
        detail=detail,
        timestamp=int(time.time() * 1000),
        path=str(request.url.path),
    ).model_dump(exclude_none=True)


def normalize_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for err in exc.errors():
        detail = ErrorDetail(
            loc=list(err.get("loc", [])),
            msg=err.get("msg", "Validation error"),
            type=err.get("type", "value_error"),
        )
        errors.append(detail.model_dump(exclude_none=True))
    return errors

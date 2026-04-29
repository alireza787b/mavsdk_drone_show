"""FastAPI runtime integration for optional MDS auth."""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.security.auth import AUTH_DOCS_URL, SESSION_COOKIE_NAME, build_auth_service


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {
    "/ping",
    "/health",
    "/api/v1/system/health",
    "/api/v1/auth/status",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
}
DOC_PATHS = {"/docs", "/redoc", "/openapi.json"}
MACHINE_ENDPOINTS = {
    ("GET", "/api/v1/origin/bootstrap"),
    ("POST", "/api/v1/fleet/heartbeats"),
    ("POST", "/api/v1/command-reports/execution-start"),
    ("POST", "/api/v1/command-reports/execution-result"),
    ("POST", "/api/v1/fleet/candidates/announce"),
}
ADMIN_PREFIXES = (
    "/api/v1/auth/users",
    "/api/v1/auth/tokens",
    "/api/v1/system/gcs-config",
    "/api/v1/system/runtime-update",
    "/api/v1/system/sitl",
    "/api/v1/git/sync-operations",
)
SELF_SERVICE_MUTATION_PATHS = {
    "/api/v1/auth/me/password",
}


def _auth_error(status_code: int, error: str, message: str, recovery_hint: str | None = None) -> JSONResponse:
    payload: dict[str, Any] = {
        "error": error,
        "message": message,
        "docs_url": AUTH_DOCS_URL,
    }
    if recovery_hint:
        payload["recovery_hint"] = recovery_hint
    return JSONResponse(status_code=status_code, content=payload)


def _extract_bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    prefix = "Bearer "
    if not value.startswith(prefix):
        return None
    token = value[len(prefix):].strip()
    return token or None


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    if path.startswith("/api/v1/auth/") and path in {"/api/v1/auth/login", "/api/v1/auth/status"}:
        return True
    return False


def _is_admin_path(path: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in ADMIN_PREFIXES)


def _is_machine_endpoint(method: str, path: str) -> bool:
    return (method.upper(), path) in MACHINE_ENDPOINTS


def _role_allows_request(role: str, method: str, path: str) -> tuple[bool, str | None]:
    normalized_role = (role or "viewer").lower()
    if normalized_role == "admin":
        return True, None
    if _is_admin_path(path):
        return False, "Admin role required for security/runtime administration."
    if path in SELF_SERVICE_MUTATION_PATHS:
        return True, None
    if normalized_role == "viewer" and method.upper() not in SAFE_METHODS:
        return False, "Viewer role is read-only."
    return True, None


class MDSAuthMiddleware(BaseHTTPMiddleware):
    """Protect dashboard/API routes when optional auth is enabled."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        service = build_auth_service()
        settings = service.settings
        path = request.url.path
        method = request.method.upper()

        request.state.mds_auth_context = {"kind": "disabled", "role": "admin", "username": "auth-disabled"}
        request.state.mds_auth_settings = settings

        if not settings.any_auth_enabled:
            return await call_next(request)

        bearer_token = _extract_bearer_token(request.headers.get("Authorization"))
        auth_context = service.authenticate_bearer(
            bearer_token,
            source_ip=request.client.host if request.client else None,
        )

        if auth_context is None:
            auth_context = service.verify_session(request.cookies.get(SESSION_COOKIE_NAME))

        if auth_context is not None:
            request.state.mds_auth_context = auth_context

        if _is_public_path(path):
            return await call_next(request)

        if _is_machine_endpoint(method, path) and not settings.api_auth_enabled:
            return await call_next(request)

        if path in DOC_PATHS and not settings.dashboard_auth_enabled and not settings.api_auth_enabled:
            return await call_next(request)

        if auth_context is None:
            recovery = None
            if service.setup_required():
                recovery = "Auth is enabled but no admin user exists. SSH to the GCS and run sudo tools/mds_auth_admin.py add-user admin."
            return _auth_error(
                401,
                "authentication_required",
                "Login session or bearer token required.",
                recovery_hint=recovery,
            )

        allowed, reason = _role_allows_request(str(auth_context.get("role", "viewer")), method, path)
        if not allowed:
            return _auth_error(403, "permission_denied", reason or "Role is not allowed for this action.")

        if method not in SAFE_METHODS and auth_context.get("kind") == "session":
            csrf_header = request.headers.get("X-MDS-CSRF-Token")
            if not service.verify_csrf(auth_context, csrf_header):
                return _auth_error(403, "csrf_required", "A valid X-MDS-CSRF-Token header is required.")

        return await call_next(request)


async def authorize_websocket(websocket: WebSocket) -> dict[str, Any] | None:
    """Authorize a WebSocket connection when optional auth is enabled."""
    service = build_auth_service()
    settings = service.settings
    if not settings.any_auth_enabled:
        return {"kind": "disabled", "role": "admin", "username": "auth-disabled"}

    bearer_token = _extract_bearer_token(websocket.headers.get("Authorization"))
    if bearer_token is None:
        bearer_token = websocket.query_params.get("access_token")

    auth_context = service.authenticate_bearer(
        bearer_token,
        source_ip=websocket.client.host if websocket.client else None,
    )
    if auth_context is None:
        auth_context = service.verify_session(websocket.cookies.get(SESSION_COOKIE_NAME))

    if auth_context is None:
        await websocket.close(code=1008)
        return None

    return auth_context

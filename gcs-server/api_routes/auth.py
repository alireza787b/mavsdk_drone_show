"""Optional dashboard/API authentication routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from src.security.auth import (
    AUTH_DOCS_URL,
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    AuthStore,
    build_auth_service,
)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)
    role: str = Field("operator")
    disabled: bool = False
    force_password_change: bool = False


class UserUpdateRequest(BaseModel):
    password: str | None = Field(None, min_length=1)
    role: str | None = None
    disabled: bool | None = None
    force_password_change: bool | None = None


class TokenCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=lambda: ["readonly"])
    ttl_hours: int | None = Field(None, ge=1, le=24 * 365)
    notes: str = ""


def _current_auth(request: Request) -> dict[str, Any]:
    return dict(getattr(request.state, "mds_auth_context", {}) or {})


def _require_admin(request: Request) -> dict[str, Any]:
    auth_context = _current_auth(request)
    if auth_context.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth_context


def _cookie_options(service) -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": service.settings.secure_cookies,
        "samesite": "lax",
        "path": "/",
        "max_age": service.settings.session_ttl_seconds,
    }


def _csrf_cookie_options(service) -> dict[str, Any]:
    return {
        "httponly": False,
        "secure": service.settings.secure_cookies,
        "samesite": "lax",
        "path": "/",
        "max_age": service.settings.session_ttl_seconds,
    }


def _status_payload(request: Request) -> dict[str, Any]:
    service = build_auth_service()
    auth_context = _current_auth(request)
    authenticated = bool(auth_context and auth_context.get("kind") not in {None, "disabled"})
    user = auth_context.get("user") if authenticated else None
    csrf_token = request.cookies.get(CSRF_COOKIE_NAME) if authenticated else None
    if authenticated and not csrf_token:
        csrf_token = service.csrf_token_for_context(auth_context)
    return {
        "dashboard_auth_enabled": service.settings.dashboard_auth_enabled,
        "api_auth_enabled": service.settings.api_auth_enabled,
        "setup_required": service.setup_required(),
        "authenticated": authenticated,
        "user": user,
        "role": auth_context.get("role") if authenticated else None,
        "csrf_token": csrf_token,
        "session_ttl_hours": service.settings.session_ttl_hours,
        "allowed_cidrs": list(service.settings.allowed_cidrs),
        "docs_url": AUTH_DOCS_URL,
    }


def create_auth_router(deps: Any) -> APIRouter:
    del deps
    router = APIRouter(tags=["Auth"])

    @router.get("/api/v1/auth/status")
    async def auth_status(request: Request):
        return _status_payload(request)

    @router.post("/api/v1/auth/login")
    async def login(payload: LoginRequest, response: Response):
        service = build_auth_service()
        if not service.settings.dashboard_auth_enabled:
            return {
                "authenticated": False,
                "dashboard_auth_enabled": False,
                "message": "Dashboard auth is disabled.",
                "docs_url": AUTH_DOCS_URL,
            }
        if service.setup_required():
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "setup_required",
                    "message": "Auth is enabled but no admin user exists.",
                    "recovery_hint": "SSH to the GCS and run sudo tools/mds_auth_admin.py add-user admin.",
                    "docs_url": AUTH_DOCS_URL,
                },
            )
        user = service.store.authenticate_user(payload.username, payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        session_token, csrf_token = service.create_session(user)
        response.set_cookie(SESSION_COOKIE_NAME, session_token, **_cookie_options(service))
        response.set_cookie(CSRF_COOKIE_NAME, csrf_token, **_csrf_cookie_options(service))
        return {
            "authenticated": True,
            "user": user,
            "role": user["role"],
            "csrf_token": csrf_token,
            "docs_url": AUTH_DOCS_URL,
        }

    @router.post("/api/v1/auth/logout")
    async def logout(response: Response):
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        response.delete_cookie(CSRF_COOKIE_NAME, path="/")
        return {"authenticated": False, "message": "Logged out"}

    @router.get("/api/v1/auth/me")
    async def me(request: Request):
        auth_context = _current_auth(request)
        return {
            "authenticated": bool(auth_context and auth_context.get("kind") not in {None, "disabled"}),
            "user": auth_context.get("user"),
            "role": auth_context.get("role"),
            "kind": auth_context.get("kind"),
        }

    @router.get("/api/v1/auth/users")
    async def list_users(request: Request):
        _require_admin(request)
        service = build_auth_service()
        return {"users": [AuthStore.sanitize_user(user) for user in service.store.list_users()]}

    @router.post("/api/v1/auth/users")
    async def create_user(payload: UserCreateRequest, request: Request):
        _require_admin(request)
        service = build_auth_service()
        user = service.store.upsert_user(
            payload.username,
            password=payload.password,
            role=payload.role,
            disabled=payload.disabled,
            force_password_change=payload.force_password_change,
        )
        return {"user": user, "message": "User saved"}

    @router.patch("/api/v1/auth/users/{username}")
    async def update_user(username: str, payload: UserUpdateRequest, request: Request):
        _require_admin(request)
        service = build_auth_service()
        try:
            if payload.password is not None:
                user = service.store.set_password(
                    username,
                    payload.password,
                    force_password_change=bool(payload.force_password_change),
                )
            else:
                user = service.store.set_user_state(
                    username,
                    role=payload.role,
                    disabled=payload.disabled,
                )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="User not found") from exc
        return {"user": user, "message": "User updated"}

    @router.get("/api/v1/auth/tokens")
    async def list_tokens(request: Request):
        _require_admin(request)
        service = build_auth_service()
        return {"tokens": service.store.list_tokens()}

    @router.post("/api/v1/auth/tokens")
    async def create_token(payload: TokenCreateRequest, request: Request):
        auth_context = _require_admin(request)
        service = build_auth_service()
        ttl_seconds = payload.ttl_hours * 3600 if payload.ttl_hours else None
        token = service.store.create_token(
            payload.name,
            scopes=payload.scopes,
            ttl_seconds=ttl_seconds,
            created_by=str(auth_context.get("username") or "admin"),
            notes=payload.notes,
        )
        return {
            "token": token,
            "message": "Token created. Copy it now; plaintext is shown only once.",
        }

    @router.post("/api/v1/auth/tokens/{token_id}/revoke")
    async def revoke_token(token_id: str, request: Request):
        _require_admin(request)
        service = build_auth_service()
        try:
            token = service.store.revoke_token(token_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Token not found") from exc
        return {"token": token, "message": "Token revoked"}

    return router

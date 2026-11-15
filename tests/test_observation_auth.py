"""Observation transport cannot broaden the canonical HTTP read authority."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import Headers, QueryParams, URL

from auth_runtime import authorize_websocket, revalidate_websocket
from src.security.auth import AuthService, AuthSettings, SESSION_COOKIE_NAME
from tests.test_mds_auth import _set_auth_env


def socket(*, token=None, cookie=None, origin=None, protocol="1", path="/ws/telemetry", query_token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    query = {"protocol_version": protocol}
    if query_token:
        query["access_token"] = query_token
    return SimpleNamespace(
        headers=Headers(headers), query_params=QueryParams(query),
        url=URL(f"ws://gcs.example:5030{path}"),
        cookies={SESSION_COOKIE_NAME: cookie} if cookie else {},
        client=SimpleNamespace(host="127.0.0.1"), close=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_auth_disabled_demo_keeps_existing_open_posture(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=False, api=False)
    ws = socket(origin="https://foreign.example")
    assert (await authorize_websocket(ws))["kind"] == "disabled"
    ws.close.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,allowed", [("readonly", True), ("operator", True), ("admin", True), ("agent", False)])
async def test_socket_matches_canonical_read_roles(monkeypatch, tmp_path, scope, allowed):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=True)
    service = AuthService(AuthSettings.from_env())
    token = service.store.create_token("reader", scopes=[scope])["token"]
    ws = socket(token=token)
    assert bool(await authorize_websocket(ws)) is allowed
    if not allowed:
        ws.close.assert_awaited_once_with(code=1008, reason="permission_denied")


@pytest.mark.asyncio
@pytest.mark.parametrize("origin,allowed", [
    ("http://gcs.example:3030", True), ("http://gcs.example:5030", True),
    ("http://foreign.example:3030", False), ("null", False),
    ("http://gcs.example.evil:3030", False), ("http://gcs.example:3030/path", False),
])
async def test_authenticated_cookie_origin_is_not_permissive_demo_cors(monkeypatch, tmp_path, origin, allowed):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=True)
    monkeypatch.delenv("MDS_CORS_ALLOW_ORIGIN_REGEX", raising=False)
    service = AuthService(AuthSettings.from_env())
    user = service.store.upsert_user("viewer", password="test-password", role="viewer")
    session, _ = service.create_session(user)
    ws = socket(cookie=session, origin=origin)
    assert bool(await authorize_websocket(ws)) is allowed
    if not allowed:
        ws.close.assert_awaited_once_with(code=1008, reason="origin_not_allowed")


@pytest.mark.asyncio
async def test_explicit_existing_cors_override_supports_separate_dashboard_host(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=True)
    monkeypatch.setenv("MDS_CORS_ALLOW_ORIGIN_REGEX", r"https://dashboard\.example")
    service = AuthService(AuthSettings.from_env())
    token = service.store.create_token("reader", scopes=["readonly"])["token"]
    assert await authorize_websocket(socket(token=token, origin="https://dashboard.example"))
    assert await authorize_websocket(socket(token=token, origin="https://dashboard.example.evil")) is None


@pytest.mark.asyncio
async def test_versioned_socket_does_not_accept_secrets_in_urls_but_legacy_stays_compatible(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=True)
    service = AuthService(AuthSettings.from_env())
    token = service.store.create_token("reader", scopes=["readonly"])["token"]
    assert await authorize_websocket(socket(query_token=token)) is None
    assert await authorize_websocket(socket(query_token=token, protocol="0"))


@pytest.mark.asyncio
async def test_token_revocation_and_expiry_are_rechecked_without_usage_writes(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=True)
    service = AuthService(AuthSettings.from_env())
    created = service.store.create_token("reader", scopes=["readonly"])
    ws = socket(token=created["token"])
    context = await authorize_websocket(ws)
    before = service.settings.tokens_file.read_bytes()
    assert await revalidate_websocket(ws, context)
    assert service.settings.tokens_file.read_bytes() == before
    service.store.revoke_token(created["id"])
    assert not await revalidate_websocket(ws, context)
    ws.close.assert_awaited_once_with(code=1008, reason="authentication_required")

    expired = service.store.create_token("expired", scopes=["readonly"])
    payload = service.store.load_tokens()
    for record in payload["tokens"]:
        if record["id"] == expired["id"]:
            record["expires_at"] = "2000-01-01T00:00:00Z"
    service.store.save_tokens(payload)
    assert await authorize_websocket(socket(token=expired["token"])) is None


@pytest.mark.asyncio
async def test_revoked_bearer_cannot_silently_switch_established_socket_to_cookie(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=True)
    service = AuthService(AuthSettings.from_env())
    user = service.store.upsert_user("viewer", password="test-password", role="viewer")
    session, _ = service.create_session(user)
    created = service.store.create_token("reader", scopes=["readonly"])
    ws = socket(token=created["token"], cookie=session)
    context = await authorize_websocket(ws)
    assert context["kind"] == "bearer"
    service.store.revoke_token(created["id"])
    assert not await revalidate_websocket(ws, context)
    ws.close.assert_awaited_once_with(code=1008, reason="authentication_required")


def test_bearer_expiry_uses_utc_not_the_hosts_local_timezone(monkeypatch, tmp_path):
    import src.security.auth as auth
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=True)
    service = AuthService(AuthSettings.from_env())
    created = service.store.create_token("reader", scopes=["readonly"], ttl_seconds=3600)
    def local_timezone_must_not_decide_token_expiry(*_):
        raise AssertionError("UTC token expiry must not use local mktime")
    monkeypatch.setattr(auth.time, "mktime", local_timezone_must_not_decide_token_expiry)
    assert service.authenticate_bearer(created["token"], record_usage=False)


@pytest.mark.asyncio
async def test_session_disable_and_ttl_are_rechecked(monkeypatch, tmp_path):
    import src.security.auth as auth
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=True)
    service = AuthService(AuthSettings.from_env())
    user = service.store.upsert_user("viewer", password="test-password", role="viewer")
    session, _ = service.create_session(user)
    ws = socket(cookie=session, origin="http://gcs.example:3030")
    context = await authorize_websocket(ws)
    service.store.set_user_state("viewer", disabled=True)
    assert not await revalidate_websocket(ws, context)
    service.store.set_user_state("viewer", disabled=False)
    assert await authorize_websocket(ws)
    now = time.time()
    monkeypatch.setattr(auth.time, "time", lambda: now + service.settings.session_ttl_seconds + 1)
    assert not await revalidate_websocket(ws, context)

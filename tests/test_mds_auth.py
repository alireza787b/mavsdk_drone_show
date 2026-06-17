import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.auth import create_auth_router
from auth_runtime import MDSAuthMiddleware
from src.security.auth import AuthService, AuthSettings, hash_password, verify_password

REPO_ROOT = Path(__file__).resolve().parents[1]


def _set_auth_env(monkeypatch, tmp_path, *, dashboard=True, api=False):
    auth_dir = tmp_path / "auth"
    monkeypatch.setenv("MDS_AUTH_ENABLED", "true" if dashboard else "false")
    monkeypatch.setenv("MDS_API_AUTH_ENABLED", "true" if api else "false")
    monkeypatch.setenv("MDS_AUTH_USERS_FILE", str(auth_dir / "users.json"))
    monkeypatch.setenv("MDS_API_TOKENS_FILE", str(auth_dir / "api_tokens.json"))
    monkeypatch.setenv("MDS_AUTH_SESSION_SECRET_FILE", str(auth_dir / "session_secret"))
    monkeypatch.setenv("MDS_AUTH_CSRF_SECRET_FILE", str(auth_dir / "csrf_secret"))
    monkeypatch.setenv("MDS_AUTH_SECURE_COOKIES", "false")
    monkeypatch.setenv("MDS_AUTH_SESSION_TTL_HOURS", "12")


def _make_app():
    app = FastAPI()
    app.add_middleware(MDSAuthMiddleware)
    app.include_router(create_auth_router(None))

    @app.get("/api/protected")
    async def protected_get():
        return {"ok": True}

    @app.post("/api/protected")
    async def protected_post():
        return {"ok": True}

    @app.get("/api/v1/system/env/gcs")
    async def gcs_env_get():
        return {"ok": True}

    @app.put("/api/v1/system/env/gcs")
    async def gcs_env_put():
        return {"ok": True}

    @app.post("/api/v1/system/env/fleet/plan")
    async def fleet_env_plan_post():
        return {"ok": True}

    @app.get("/api/v1/simurgh/runtime-settings")
    async def simurgh_runtime_settings_get():
        return {"ok": True}

    @app.put("/api/v1/simurgh/runtime-settings")
    async def simurgh_runtime_settings_put():
        return {"ok": True}

    @app.get("/api/v1/simurgh/provider-credentials")
    async def simurgh_provider_credentials_get():
        return {"ok": True}

    @app.put("/api/v1/simurgh/provider-credentials")
    async def simurgh_provider_credentials_put():
        return {"ok": True}

    @app.post("/api/v1/fleet/heartbeats")
    async def heartbeat_post():
        return {"success": True}

    @app.post("/api/v1/fleet/node-boot-status")
    async def node_boot_status_post():
        return {"success": True}

    @app.get("/api/v1/origin/bootstrap")
    async def origin_bootstrap_get():
        return {"lat": 0.0, "lon": 0.0, "alt": 0.0}

    @app.post("/api/sar/mission/{mission_id}/progress")
    async def quickscout_progress_post(mission_id: str):
        return {"success": True, "mission_id": mission_id}

    return app


def test_password_hash_round_trip():
    stored = hash_password("correct horse battery staple")

    assert stored != "correct horse battery staple"
    assert verify_password("correct horse battery staple", stored)
    assert not verify_password("wrong", stored)


def test_auth_store_user_and_token_lifecycle(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=True)
    service = AuthService(AuthSettings.from_env())

    user = service.store.upsert_user("Admin", password="test-password", role="admin")
    assert user["username"] == "admin"
    assert user["role"] == "admin"
    assert service.store.authenticate_user("admin", "test-password")["role"] == "admin"
    assert service.store.authenticate_user("admin", "wrong") is None

    created = service.store.create_token("debug", scopes=["operator"], ttl_seconds=3600, created_by="admin")
    plaintext = created["token"]
    assert plaintext.startswith("mds_")

    verified = service.store.verify_token(plaintext, source_ip="127.0.0.1")
    assert verified["name"] == "debug"
    assert "token" not in service.store.list_tokens()[0]

    service.store.revoke_token(created["id"])
    assert service.store.verify_token(plaintext) is None


def test_auth_admin_status_redacts_password_hashes(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=False)
    service = AuthService(AuthSettings.from_env())
    service.store.upsert_user("admin", password="test-password", role="admin")

    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "mds_auth_admin.py"), "status"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(result.stdout)

    assert payload["users"][0]["username"] == "admin"
    assert "password_hash" not in payload["users"][0]


def test_auth_disabled_keeps_existing_api_open(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=False, api=False)
    client = TestClient(_make_app())

    assert client.get("/api/protected").status_code == 200
    assert client.post("/api/protected").status_code == 200


def test_dashboard_auth_requires_login_and_csrf(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=False)
    service = AuthService(AuthSettings.from_env())
    service.store.upsert_user("admin", password="test-password", role="admin")
    client = TestClient(_make_app())

    assert client.get("/api/protected").status_code == 401

    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password"})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]

    assert client.get("/api/protected").status_code == 200
    assert client.post("/api/protected").status_code == 403
    assert client.post("/api/protected", headers={"X-MDS-CSRF-Token": csrf}).status_code == 200


def test_logout_remains_available_to_clear_stale_sessions(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=False)
    client = TestClient(_make_app())

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert response.json()["authenticated"] is False


def test_viewer_role_is_read_only(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=False)
    service = AuthService(AuthSettings.from_env())
    service.store.upsert_user("viewer", password="test-password", role="viewer")
    client = TestClient(_make_app())
    login = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "test-password"})
    csrf = login.json()["csrf_token"]

    assert client.get("/api/protected").status_code == 200
    response = client.post("/api/protected", headers={"X-MDS-CSRF-Token": csrf})
    assert response.status_code == 403
    assert response.json()["error"] == "permission_denied"


def test_runtime_env_mutation_requires_admin(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=False)
    service = AuthService(AuthSettings.from_env())
    service.store.upsert_user("operator", password="test-password", role="operator")
    service.store.upsert_user("admin", password="test-password", role="admin")
    client = TestClient(_make_app())

    operator_login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "test-password"})
    operator_csrf = operator_login.json()["csrf_token"]

    assert client.get("/api/v1/system/env/gcs").status_code == 403
    assert client.put("/api/v1/system/env/gcs", headers={"X-MDS-CSRF-Token": operator_csrf}).status_code == 403
    assert client.post("/api/v1/system/env/fleet/plan", headers={"X-MDS-CSRF-Token": operator_csrf}).status_code == 403

    client.post("/api/v1/auth/logout")
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password"})
    admin_csrf = admin_login.json()["csrf_token"]

    assert client.get("/api/v1/system/env/gcs").status_code == 200
    assert client.put("/api/v1/system/env/gcs", headers={"X-MDS-CSRF-Token": admin_csrf}).status_code == 200


def test_simurgh_runtime_and_provider_settings_require_admin(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=False)
    service = AuthService(AuthSettings.from_env())
    service.store.upsert_user("operator", password="test-password", role="operator")
    service.store.upsert_user("admin", password="test-password", role="admin")
    client = TestClient(_make_app())

    operator_login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "test-password"})
    operator_csrf = operator_login.json()["csrf_token"]

    assert client.get("/api/v1/simurgh/runtime-settings").status_code == 403
    assert client.put("/api/v1/simurgh/runtime-settings", headers={"X-MDS-CSRF-Token": operator_csrf}).status_code == 403
    assert client.get("/api/v1/simurgh/provider-credentials").status_code == 403
    assert client.put("/api/v1/simurgh/provider-credentials", headers={"X-MDS-CSRF-Token": operator_csrf}).status_code == 403

    client.post("/api/v1/auth/logout")
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-password"})
    admin_csrf = admin_login.json()["csrf_token"]

    assert client.get("/api/v1/simurgh/runtime-settings").status_code == 200
    assert client.put("/api/v1/simurgh/runtime-settings", headers={"X-MDS-CSRF-Token": admin_csrf}).status_code == 200
    assert client.get("/api/v1/simurgh/provider-credentials").status_code == 200
    assert client.put("/api/v1/simurgh/provider-credentials", headers={"X-MDS-CSRF-Token": admin_csrf}).status_code == 200


def test_signed_in_user_can_change_own_password(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=False)
    service = AuthService(AuthSettings.from_env())
    service.store.upsert_user("viewer", password="old-password", role="viewer")
    client = TestClient(_make_app())
    login = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "old-password"})
    csrf = login.json()["csrf_token"]

    response = client.patch(
        "/api/v1/auth/me/password",
        json={"current_password": "old-password", "new_password": "new-password"},
        headers={"X-MDS-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert service.store.authenticate_user("viewer", "old-password") is None
    assert service.store.authenticate_user("viewer", "new-password")["username"] == "viewer"


def test_machine_endpoint_open_until_api_auth_enabled(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=False)
    client = TestClient(_make_app())

    assert client.post("/api/v1/fleet/heartbeats").status_code == 200
    assert client.post("/api/v1/fleet/node-boot-status").status_code == 200
    assert client.get("/api/v1/origin/bootstrap").status_code == 200
    assert client.post("/api/sar/mission/mission-1/progress").status_code == 200


def test_machine_endpoint_requires_bearer_when_api_auth_enabled(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch, tmp_path, dashboard=True, api=True)
    service = AuthService(AuthSettings.from_env())
    service.store.upsert_user("admin", password="test-password", role="admin")
    token = service.store.create_token("drone", scopes=["drone"], ttl_seconds=3600)["token"]
    client = TestClient(_make_app())

    assert client.post("/api/v1/fleet/heartbeats").status_code == 401
    assert client.post("/api/v1/fleet/node-boot-status").status_code == 401
    assert client.get("/api/v1/origin/bootstrap").status_code == 401
    assert client.post("/api/sar/mission/mission-1/progress").status_code == 401
    response = client.post("/api/v1/fleet/heartbeats", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    response = client.post("/api/v1/fleet/node-boot-status", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    response = client.get("/api/v1/origin/bootstrap", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    response = client.post("/api/sar/mission/mission-1/progress", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

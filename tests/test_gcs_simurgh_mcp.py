from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_runtime import MCP_PROTOCOL_VERSION, MCP_RESOURCE_PREFIX
from api_routes.simurgh import create_simurgh_router
from auth_runtime import MDSAuthMiddleware
from src.security.auth import AuthService, AuthSettings, SESSION_COOKIE_NAME


MCP_PATH = "/api/v1/simurgh/mcp"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_simurgh_router())
    return TestClient(app)


def _auth_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(MDSAuthMiddleware)
    app.include_router(create_simurgh_router())
    return TestClient(app)


def _request(method: str, *, request_id: str | int = 1, params: dict | None = None) -> dict:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def _enable_mcp(monkeypatch, *, require_auth: bool = False):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_MCP_ENABLED", "true")
    monkeypatch.setenv("MDS_MCP_REQUIRE_AUTH", "true" if require_auth else "false")


def _set_auth_env(monkeypatch, tmp_path):
    auth_dir = tmp_path / "auth"
    monkeypatch.setenv("MDS_AUTH_ENABLED", "true")
    monkeypatch.setenv("MDS_API_AUTH_ENABLED", "true")
    monkeypatch.setenv("MDS_AUTH_USERS_FILE", str(auth_dir / "users.json"))
    monkeypatch.setenv("MDS_API_TOKENS_FILE", str(auth_dir / "api_tokens.json"))
    monkeypatch.setenv("MDS_AUTH_SESSION_SECRET_FILE", str(auth_dir / "session_secret"))
    monkeypatch.setenv("MDS_AUTH_CSRF_SECRET_FILE", str(auth_dir / "csrf_secret"))
    monkeypatch.setenv("MDS_AUTH_SECURE_COOKIES", "false")


def test_simurgh_mcp_is_disabled_by_default():
    client = _client()

    response = client.post(
        MCP_PATH,
        json=_request(
            "initialize",
            params={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        ),
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"]["code"] == -32000
    assert "disabled" in payload["error"]["message"]


def test_simurgh_mcp_initialize_exposes_resources_not_tools(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    response = client.post(
        MCP_PATH,
        json=_request(
            "initialize",
            params={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        ),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert result["capabilities"] == {"resources": {}}
    assert "tools" not in result["capabilities"]
    assert result["serverInfo"]["name"] == "mds-simurgh-operator"
    assert "cannot command drones" in result["instructions"]


def test_simurgh_mcp_requires_auth_by_default_when_enabled(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_MCP_ENABLED", "true")
    monkeypatch.setenv("MDS_MCP_RESOURCE_URL", "https://gcs.example/api/v1/simurgh/mcp")
    client = _client()

    response = client.post(MCP_PATH, json=_request("resources/list"))

    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == -32000
    assert "Authorization: Bearer" in payload["error"]["message"]
    assert "MDS_MCP_REQUIRE_AUTH=false" in payload["error"]["data"]["recovery_hint"]
    authenticate = response.headers["www-authenticate"]
    assert 'scope="agent"' in authenticate
    assert (
        'resource_metadata="https://gcs.example/.well-known/oauth-protected-resource/api/v1/simurgh/mcp"'
        in authenticate
    )


def test_simurgh_mcp_resource_metadata_challenge_uses_configured_resource_path(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_MCP_ENABLED", "true")
    monkeypatch.setenv("MDS_MCP_RESOURCE_URL", "https://gcs.example/mcp")
    client = _client()

    response = client.post(MCP_PATH, json=_request("resources/list"))

    assert response.status_code == 401
    assert 'resource_metadata="https://gcs.example/.well-known/oauth-protected-resource/mcp"' in (
        response.headers["www-authenticate"]
    )


def test_simurgh_mcp_protected_resource_metadata(monkeypatch):
    monkeypatch.setenv("MDS_MCP_AUTHORIZATION_SERVERS", "https://auth.example/issuer")
    monkeypatch.setenv("MDS_MCP_RESOURCE_URL", "https://gcs.example/api/v1/simurgh/mcp")
    client = _client()

    response = client.get("/.well-known/oauth-protected-resource/api/v1/simurgh/mcp")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resource"] == "https://gcs.example/api/v1/simurgh/mcp"
    assert payload["authorization_servers"] == ["https://auth.example/issuer"]
    assert payload["bearer_methods_supported"] == ["header"]
    assert "agent" in payload["scopes_supported"]
    assert payload["mds_auth_required"] is True
    assert payload["mds_boundary"] == "gcs-only"
    assert payload["mds_execution"] == "none"


def test_simurgh_mcp_protected_resource_metadata_derives_authorization_server(monkeypatch):
    monkeypatch.delenv("MDS_MCP_AUTHORIZATION_SERVERS", raising=False)
    monkeypatch.delenv("MDS_MCP_RESOURCE_URL", raising=False)
    client = _client()

    response = client.get("/.well-known/oauth-protected-resource/api/v1/simurgh/mcp")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resource"] == "http://testserver/api/v1/simurgh/mcp"
    assert payload["authorization_servers"] == ["http://testserver"]


def test_simurgh_mcp_auth_runs_before_json_parse(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_MCP_ENABLED", "true")
    client = _client()

    response = client.post(MCP_PATH, content="{not-json", headers={"Content-Type": "application/json"})

    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == -32000
    assert "Authorization: Bearer" in payload["error"]["message"]


def test_simurgh_mcp_auth_requires_agent_scope_for_bearer(monkeypatch, tmp_path):
    _enable_mcp(monkeypatch, require_auth=True)
    _set_auth_env(monkeypatch, tmp_path)
    service = AuthService(AuthSettings.from_env())
    drone_token = service.store.create_token("drone", scopes=["drone"], ttl_seconds=3600)["token"]
    agent_token = service.store.create_token("agent", scopes=["agent"], ttl_seconds=3600)["token"]
    client = _auth_client()

    unauthenticated = client.post(MCP_PATH, json=_request("resources/list"))
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"] == "authentication_required"
    assert "resource_metadata=" in unauthenticated.headers["www-authenticate"]
    assert 'scope="agent"' in unauthenticated.headers["www-authenticate"]

    wrong_scope = client.post(
        MCP_PATH,
        headers={"Authorization": f"Bearer {drone_token}"},
        json=_request("resources/list"),
    )
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["code"] == -32000
    assert wrong_scope.json()["error"]["data"]["required_scopes"] == ["admin", "agent"]
    assert 'error="insufficient_scope"' in wrong_scope.headers["www-authenticate"]

    allowed = client.post(
        MCP_PATH,
        headers={"Authorization": f"Bearer {agent_token}"},
        json=_request(
            "initialize",
            params={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agent-test", "version": "0"},
            },
        ),
    )
    assert allowed.status_code == 200
    assert allowed.json()["result"]["serverInfo"]["name"] == "mds-simurgh-operator"


def test_simurgh_mcp_required_scopes_ignore_weak_overrides(monkeypatch, tmp_path):
    _enable_mcp(monkeypatch, require_auth=True)
    monkeypatch.setenv("MDS_MCP_REQUIRED_SCOPES", "drone,operator")
    _set_auth_env(monkeypatch, tmp_path)
    service = AuthService(AuthSettings.from_env())
    drone_token = service.store.create_token("drone", scopes=["drone"], ttl_seconds=3600)["token"]
    agent_token = service.store.create_token("agent", scopes=["agent"], ttl_seconds=3600)["token"]
    client = _auth_client()

    wrong_scope = client.post(
        MCP_PATH,
        headers={"Authorization": f"Bearer {drone_token}"},
        json=_request("resources/list"),
    )
    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["error"]["data"]["required_scopes"] == ["admin", "agent"]

    allowed = client.post(
        MCP_PATH,
        headers={"Authorization": f"Bearer {agent_token}"},
        json=_request("resources/list"),
    )
    assert allowed.status_code == 200


def test_simurgh_mcp_rejects_dashboard_session_auth(monkeypatch, tmp_path):
    _enable_mcp(monkeypatch, require_auth=True)
    _set_auth_env(monkeypatch, tmp_path)
    service = AuthService(AuthSettings.from_env())
    user = service.store.upsert_user("admin", password="test-password", role="admin")
    session_token, csrf_token = service.create_session(user)
    client = _auth_client()
    client.cookies.set(SESSION_COOKIE_NAME, session_token)

    response = client.post(
        MCP_PATH,
        headers={"X-MDS-CSRF-Token": csrf_token},
        json=_request("resources/list"),
    )

    assert response.status_code == 401
    assert "requires Authorization: Bearer" in response.json()["error"]["message"]
    assert 'error="invalid_token"' in response.headers["www-authenticate"]


def test_simurgh_mcp_lists_and_reads_metadata_resources(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    list_response = client.post(MCP_PATH, json=_request("resources/list"))

    assert list_response.status_code == 200
    resources = list_response.json()["result"]["resources"]
    uris = {resource["uri"] for resource in resources}
    assert f"{MCP_RESOURCE_PREFIX}/status" in uris
    assert f"{MCP_RESOURCE_PREFIX}/tool-registry" in uris
    assert f"{MCP_RESOURCE_PREFIX}/context/simurgh.safety_policy" in uris
    assert all(resource["_meta"]["ai.mds/execution"] == "none" for resource in resources)

    read_response = client.post(
        MCP_PATH,
        json=_request("resources/read", params={"uri": f"{MCP_RESOURCE_PREFIX}/status"}),
    )

    assert read_response.status_code == 200
    content = read_response.json()["result"]["contents"][0]
    assert content["mimeType"] == "application/json"
    status = json.loads(content["text"])
    assert status["agent_enabled"] is True
    assert status["mcp_enabled"] is True
    assert status["assistant_provider"] == "mock"
    assert status["assistant_external_provider"] is False
    assert status["policy_path"] == "config/agent_policy.yaml"
    assert not status["policy_path"].startswith("/")


def test_simurgh_mcp_sessions_resource_omits_raw_session_metadata(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    create_response = client.post(
        "/api/v1/simurgh/sessions",
        json={
            "actor": "operator",
            "metadata": {
                "channel": "dashboard",
                "source": "simurgh-ui",
                "raw_prompt": "AIRFRAME-01 stopped streaming on 192.168.1.10",
                "notes": "customer field evidence",
            },
        },
    )
    assert create_response.status_code == 200

    read_response = client.post(
        MCP_PATH,
        json=_request("resources/read", params={"uri": f"{MCP_RESOURCE_PREFIX}/sessions"}),
    )

    assert read_response.status_code == 200
    content = read_response.json()["result"]["contents"][0]
    payload = json.loads(content["text"])
    assert payload["sessions"][0]["metadata"] == {"channel": "dashboard", "source": "simurgh-ui"}
    assert "raw_prompt" not in content["text"]
    assert "AIRFRAME-01" not in content["text"]
    assert "192.168.1.10" not in content["text"]


def test_simurgh_mcp_sessions_resource_omits_sensitive_allowed_metadata_values(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    create_response = client.post(
        "/api/v1/simurgh/sessions",
        json={
            "actor": "operator",
            "metadata": {
                "channel": "AIRFRAME-01",
                "source": "token=secret-value",
            },
        },
    )
    assert create_response.status_code == 200

    read_response = client.post(
        MCP_PATH,
        json=_request("resources/read", params={"uri": f"{MCP_RESOURCE_PREFIX}/sessions"}),
    )

    assert read_response.status_code == 200
    content = read_response.json()["result"]["contents"][0]
    payload = json.loads(content["text"])
    assert payload["sessions"][0]["metadata"] == {}
    assert "AIRFRAME-01" not in content["text"]
    assert "token=secret-value" not in content["text"]


def test_simurgh_mcp_tool_registry_resource_filters_unsafe_entries(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    response = client.post(
        MCP_PATH,
        json=_request("resources/read", params={"uri": f"{MCP_RESOURCE_PREFIX}/tool-registry"}),
    )

    assert response.status_code == 200
    content = response.json()["result"]["contents"][0]
    payload = json.loads(content["text"])
    tool_ids = {tool["id"] for tool in payload["tools"]}
    assert payload["filtered_tool_count"] > 0
    assert payload["mcp_metadata_tool_count"] == len(payload["tools"])
    assert "mds.commands.raw_submit" not in tool_ids
    assert "mds.drone.commands.raw_submit" not in tool_ids
    assert all(tool["boundary"] == "gcs" for tool in payload["tools"])
    assert all(tool["read_only"] is True for tool in payload["tools"])
    assert all(tool["destructive"] is False for tool in payload["tools"])
    assert all(tool["exposure"] != "exclude" for tool in payload["tools"])


def test_simurgh_mcp_reads_public_context_resource(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    response = client.post(
        MCP_PATH,
        json=_request("resources/read", params={"uri": f"{MCP_RESOURCE_PREFIX}/context/simurgh.safety_policy"}),
    )

    assert response.status_code == 200
    content = response.json()["result"]["contents"][0]
    assert content["mimeType"] == "text/markdown"
    assert "Raw GCS command submission" in content["text"]


def test_simurgh_mcp_rejects_tool_methods_and_batching(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    tools_response = client.post(MCP_PATH, json=_request("tools/list"))
    assert tools_response.status_code == 200
    assert tools_response.json()["error"]["code"] == -32601

    batch_response = client.post(MCP_PATH, json=[_request("resources/list")])
    assert batch_response.status_code == 200
    assert batch_response.json()["error"]["code"] == -32600

    params_response = client.post(MCP_PATH, json={**_request("resources/list"), "params": []})
    assert params_response.status_code == 200
    assert params_response.json()["error"]["code"] == -32602


def test_simurgh_mcp_enforces_origin_and_protocol_headers(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    origin_response = client.post(
        MCP_PATH,
        headers={"Origin": "https://attacker.example"},
        json=_request("resources/list"),
    )
    assert origin_response.status_code == 403
    assert "Origin" in origin_response.json()["error"]["message"]

    protocol_response = client.post(
        MCP_PATH,
        headers={"MCP-Protocol-Version": "2024-11-05"},
        json=_request("resources/list"),
    )
    assert protocol_response.status_code == 400
    assert "unsupported MCP protocol version" in protocol_response.json()["error"]["message"]


def test_simurgh_mcp_allows_configured_exact_origin_without_wildcard(monkeypatch):
    _enable_mcp(monkeypatch)
    monkeypatch.setenv("MDS_MCP_ALLOWED_ORIGINS", "https://ops.example")
    client = _client()

    allowed_response = client.post(
        MCP_PATH,
        headers={"Origin": "https://ops.example"},
        json=_request("resources/list"),
    )
    assert allowed_response.status_code == 200

    monkeypatch.setenv("MDS_MCP_ALLOWED_ORIGINS", "*")
    wildcard_response = client.post(
        MCP_PATH,
        headers={"Origin": "https://attacker.example"},
        json=_request("resources/list"),
    )
    assert wildcard_response.status_code == 403


def test_simurgh_mcp_notifications_and_get_have_no_stream(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    notify_response = client.post(MCP_PATH, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notify_response.status_code == 202
    assert notify_response.content == b""

    get_response = client.get(MCP_PATH)
    assert get_response.status_code == 405

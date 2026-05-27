from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_runtime import MCP_PROTOCOL_VERSION, MCP_RESOURCE_PREFIX
from api_routes.simurgh import create_simurgh_router
from agent_runtime.tool_executor import list_policy_allowed_read_only_tools
from auth_runtime import MDSAuthMiddleware
from src.security.auth import AuthService, AuthSettings, SESSION_COOKIE_NAME


MCP_PATH = "/api/v1/simurgh/mcp"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_simurgh_router())
    return TestClient(app)


def _auth_client_with_probe_routes() -> TestClient:
    app = FastAPI()
    app.add_middleware(MDSAuthMiddleware)

    @app.get("/api/logs/sessions/{session_id}")
    def log_session(session_id: str, limit: int):
        return {"session_id": session_id, "count": 1, "lines": [{"level": "INFO", "msg": "internal"}], "limit": limit}

    app.include_router(create_simurgh_router())
    app.post("/api/v1/commands")(lambda: {"accepted": True})
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


def test_simurgh_mcp_initialize_exposes_resources_and_read_only_tools(monkeypatch):
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
    assert result["capabilities"] == {"prompts": {"listChanged": False}, "resources": {}, "tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "mds-simurgh-operator"
    assert "policy-allowed read-only GCS tools" in result["instructions"]
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
    assert payload["mds_execution"] == "read_only_tools"


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


def test_agent_bearer_scope_is_restricted_to_simurgh_paths(monkeypatch, tmp_path):
    _enable_mcp(monkeypatch, require_auth=True)
    _set_auth_env(monkeypatch, tmp_path)
    service = AuthService(AuthSettings.from_env())
    agent_token = service.store.create_token("agent", scopes=["agent"], ttl_seconds=3600)["token"]
    client = _auth_client_with_probe_routes()

    outside_simurgh = client.post(
        "/api/v1/commands",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"command": "noop"},
    )
    assert outside_simurgh.status_code == 403
    assert outside_simurgh.json()["message"] == "Agent bearer tokens are restricted to Simurgh/MCP endpoints."

    mcp_allowed = client.post(
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
    assert mcp_allowed.status_code == 200

    status_allowed = client.get(
        "/api/v1/simurgh/status",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert status_allowed.status_code == 200
    assert status_allowed.json()["agent_enabled"] is True

    direct_log_denied = client.get(
        "/api/logs/sessions/s_20260525_001",
        headers={"Authorization": f"Bearer {agent_token}"},
        params={"limit": 5},
    )
    assert direct_log_denied.status_code == 403
    assert direct_log_denied.json()["message"] == "Agent bearer tokens are restricted to Simurgh/MCP endpoints."

    mcp_log_allowed = client.post(
        MCP_PATH,
        headers={"Authorization": f"Bearer {agent_token}"},
        json=_request(
            "tools/call",
            params={"name": "mds.logs.session.read", "arguments": {"session_id": "s_20260525_001", "limit": 5}},
        ),
    )
    assert mcp_log_allowed.status_code == 200
    assert mcp_log_allowed.json()["result"]["isError"] is False
    assert mcp_log_allowed.json()["result"]["structuredContent"]["session_id"] == "s_20260525_001"


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


def test_simurgh_mcp_lists_and_gets_mission_mode_prompt(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    list_response = client.post(MCP_PATH, json=_request("prompts/list"))

    assert list_response.status_code == 200
    prompts = list_response.json()["result"]["prompts"]
    prompt_names = {prompt["name"] for prompt in prompts}
    assert "mds.compare_mission_modes" in prompt_names
    compare_prompt = next(prompt for prompt in prompts if prompt["name"] == "mds.compare_mission_modes")
    assert "QuickScout" in compare_prompt["description"]
    assert f"{MCP_RESOURCE_PREFIX}/context/mds.quickscout" in compare_prompt["_meta"]["ai.mds/resources"]
    assert f"{MCP_RESOURCE_PREFIX}/context/mds.mission_planning_workspace" in compare_prompt["_meta"]["ai.mds/resources"]

    get_response = client.post(
        MCP_PATH,
        json=_request(
            "prompts/get",
            params={
                "name": "mds.compare_mission_modes",
                "arguments": {"question": "What's the difference of QuickScout and Swarm Trajectory mode?"},
            },
        ),
    )

    assert get_response.status_code == 200
    payload = get_response.json()["result"]
    assert "mission-planning modes" in payload["description"]
    messages = payload["messages"]
    assert messages[0]["content"]["type"] == "text"
    assert "conceptual workflow comparison" in messages[0]["content"]["text"]
    embedded_uris = {message["content"]["resource"]["uri"] for message in messages[1:]}
    assert f"{MCP_RESOURCE_PREFIX}/context/mds.quickscout" in embedded_uris
    assert f"{MCP_RESOURCE_PREFIX}/context/mds.swarm_trajectory" in embedded_uris
    assert any("QuickScout is" in message["content"]["resource"].get("text", "") for message in messages[1:])



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
                "raw_prompt": "CM4-99 stopped streaming on 192.168.1.10",
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
    assert "CM4-99" not in content["text"]
    assert "192.168.1.10" not in content["text"]


def test_simurgh_mcp_sessions_resource_omits_sensitive_allowed_metadata_values(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

    create_response = client.post(
        "/api/v1/simurgh/sessions",
        json={
            "actor": "operator",
            "metadata": {
                "channel": "CM4-99",
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
    assert "CM4-99" not in content["text"]
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

    candidate_response = client.post(
        MCP_PATH,
        json=_request("resources/read", params={"uri": f"{MCP_RESOURCE_PREFIX}/context/simurgh.openapi_tool_candidates"}),
    )

    assert candidate_response.status_code == 200
    candidate_content = candidate_response.json()["result"]["contents"][0]
    assert candidate_content["mimeType"] == "application/yaml"
    assert "runtime_loaded: false" in candidate_content["text"]
    assert "callable: false" in candidate_content["text"]
    assert "default_registry_exposure: exclude" in candidate_content["text"]


def test_simurgh_mcp_lists_and_calls_policy_allowed_read_only_tools(monkeypatch):
    _enable_mcp(monkeypatch)
    app = FastAPI()

    @app.get("/api/v1/system/health")
    def health_check():
        return {"status": "ok", "source": "test"}

    @app.get("/api/logs/sessions/{session_id}")
    def log_session(session_id: str, level: str | None = None, limit: int | None = None, offset: int = 0):
        return {
            "session_id": session_id,
            "count": 1,
            "filters": {"level": level, "limit": limit, "offset": offset},
            "lines": [{"level": level or "INFO", "msg": "test"}],
        }

    @app.get("/api/v1/shows/skybrush/metrics/snapshot")
    def skybrush_metrics_snapshot():
        return {"available": True, "snapshot_only": True, "cache_current": True, "metrics": {"basic_metrics": {"drone_count": 2}}}

    @app.get("/api/v1/shows/skybrush/safety-report")
    def skybrush_safety_report():
        return {"safety_analysis": {"safety_status": "SAFE"}, "recommendations": ["test review"]}

    @app.get("/api/v1/shows/skybrush/validation")
    def skybrush_validation():
        return {"validation_status": "PASS", "issues": [], "metrics_summary": {"safety_status": "SAFE"}}

    app.include_router(create_simurgh_router())
    client = TestClient(app)

    tools_response = client.post(MCP_PATH, json=_request("tools/list"))
    assert tools_response.status_code == 200
    tools = tools_response.json()["result"]["tools"]
    tool_names = {tool["name"] for tool in tools}
    executor_tool_names = {tool.id for tool in list_policy_allowed_read_only_tools(channel="mcp")}
    assert tool_names == executor_tool_names
    assert "mds.system.health.read" in tool_names
    assert "mds.operator.question.answer" in tool_names
    assert "mds.logs.session.read" in tool_names
    assert "mds.shows.skybrush.metrics_snapshot.read" in tool_names
    assert "mds.shows.skybrush.safety_report.read" in tool_names
    assert "mds.shows.skybrush.validation.read" in tool_names
    assert "mds.shows.skybrush.metrics.read" not in tool_names
    assert "mds.commands.raw_submit" not in tool_names
    exposed_route_paths = {tool["_meta"]["ai.mds/route"]["path"] for tool in tools}
    assert "/api/v1/shows/skybrush/metrics/snapshot" in exposed_route_paths
    assert "/api/v1/shows/skybrush/metrics" not in exposed_route_paths
    assert "/api/v1/shows/skybrush/import" not in exposed_route_paths
    assert "/api/v1/shows/skybrush/deployments" not in exposed_route_paths
    assert "/api/v1/shows/skybrush/archives/raw" not in exposed_route_paths
    assert "/api/v1/shows/skybrush/archives/processed" not in exposed_route_paths
    assert "/api/v1/shows/skybrush/plots" not in exposed_route_paths
    assert "/api/v1/shows/skybrush/plots/{filename}" not in exposed_route_paths
    assert "/api/v1/shows/custom/preview" not in exposed_route_paths
    health_tool = next(tool for tool in tools if tool["name"] == "mds.system.health.read")
    assert health_tool["inputSchema"] == {"type": "object", "additionalProperties": False}
    assert health_tool["annotations"]["readOnlyHint"] is True
    assert health_tool["annotations"]["destructiveHint"] is False
    advisory_tool = next(tool for tool in tools if tool["name"] == "mds.operator.question.answer")
    assert advisory_tool["inputSchema"]["required"] == ["question"]
    assert advisory_tool["annotations"]["readOnlyHint"] is True
    assert advisory_tool["_meta"]["ai.mds/route"] == {"method": None, "path": None}
    docs_search_tool = next(tool for tool in tools if tool["name"] == "mds.docs.search")
    assert docs_search_tool["inputSchema"]["required"] == ["query"]
    assert docs_search_tool["inputSchema"]["properties"]["limit"]["maximum"] == 8
    assert docs_search_tool["outputSchema"]["additionalProperties"] is False
    assert set(docs_search_tool["outputSchema"]["required"]) == {
        "query",
        "limit",
        "tags",
        "audience",
        "source_context_index",
        "index_path",
        "resource_count",
        "chunk_count",
        "results",
    }
    docs_result_schema = docs_search_tool["outputSchema"]["properties"]["results"]["items"]
    assert docs_result_schema["additionalProperties"] is False
    assert set(docs_result_schema["required"]) == {
        "id",
        "resource_id",
        "title",
        "heading",
        "path",
        "route_hint",
        "audience",
        "summary",
        "tags",
        "links",
        "canonical_url",
        "content_hash",
        "snippet",
        "score",
    }
    docs_chunk_tool = next(tool for tool in tools if tool["name"] == "mds.docs.chunk.read")
    assert docs_chunk_tool["inputSchema"]["required"] == ["chunk_id"]
    assert docs_chunk_tool["inputSchema"]["properties"]["max_chars"]["maximum"] == 8000
    assert docs_chunk_tool["outputSchema"]["additionalProperties"] is False
    assert set(docs_chunk_tool["outputSchema"]["required"]) == {"chunk", "text", "truncated", "max_chars", "index_path"}
    docs_chunk_schema = docs_chunk_tool["outputSchema"]["properties"]["chunk"]
    assert docs_chunk_schema["additionalProperties"] is False
    assert set(docs_chunk_schema["required"]) == {
        "id",
        "resource_id",
        "title",
        "heading",
        "path",
        "route_hint",
        "audience",
        "summary",
        "tags",
        "links",
        "canonical_url",
        "content_hash",
    }
    log_session_tool = next(tool for tool in tools if tool["name"] == "mds.logs.session.read")
    assert log_session_tool["inputSchema"]["required"] == ["session_id", "limit"]
    assert log_session_tool["inputSchema"]["properties"]["session_id"]["pattern"] == "^[A-Za-z0-9_.-]+$"
    assert log_session_tool["inputSchema"]["properties"]["limit"]["maximum"] == 200

    log_session_response = client.post(
        MCP_PATH,
        json=_request(
            "tools/call",
            params={
                "name": "mds.logs.session.read",
                "arguments": {"session_id": "s_20260525_001", "level": "WARNING", "limit": 5, "offset": 2},
            },
        ),
    )
    assert log_session_response.status_code == 200
    log_result = log_session_response.json()["result"]
    assert log_result["isError"] is False
    assert log_result["structuredContent"]["session_id"] == "s_20260525_001"
    assert log_result["structuredContent"]["filters"] == {"level": "WARNING", "limit": 5, "offset": 2}

    missing_arg_response = client.post(
        MCP_PATH,
        json=_request("tools/call", params={"name": "mds.logs.session.read", "arguments": {"limit": 5}}),
    )
    assert missing_arg_response.status_code == 200
    assert missing_arg_response.json()["result"]["isError"] is True
    assert "Missing required argument" in missing_arg_response.json()["result"]["content"][0]["text"]

    missing_limit_response = client.post(
        MCP_PATH,
        json=_request("tools/call", params={"name": "mds.logs.session.read", "arguments": {"session_id": "s_20260525_001"}}),
    )
    assert missing_limit_response.status_code == 200
    assert missing_limit_response.json()["result"]["isError"] is True
    assert "Missing required argument: limit" in missing_limit_response.json()["result"]["content"][0]["text"]

    invalid_arg_response = client.post(
        MCP_PATH,
        json=_request(
            "tools/call",
            params={"name": "mds.logs.session.read", "arguments": {"session_id": "../secret", "limit": 5}},
        ),
    )
    assert invalid_arg_response.status_code == 200
    assert invalid_arg_response.json()["result"]["isError"] is True

    invalid_enum_response = client.post(
        MCP_PATH,
        json=_request(
            "tools/call",
            params={"name": "mds.logs.session.read", "arguments": {"session_id": "s_20260525_001", "level": "WARN", "limit": 5}},
        ),
    )
    assert invalid_enum_response.status_code == 200
    assert invalid_enum_response.json()["result"]["isError"] is True

    invalid_range_response = client.post(
        MCP_PATH,
        json=_request(
            "tools/call",
            params={"name": "mds.logs.session.read", "arguments": {"session_id": "s_20260525_001", "limit": 0}},
        ),
    )
    assert invalid_range_response.status_code == 200
    assert invalid_range_response.json()["result"]["isError"] is True

    docs_search_response = client.post(
        MCP_PATH,
        json=_request(
            "tools/call",
            params={"name": "mds.docs.search", "arguments": {"query": "SkyBrush show upload", "limit": 3}},
        ),
    )
    assert docs_search_response.status_code == 200
    docs_search_result = docs_search_response.json()["result"]
    assert docs_search_result["isError"] is False
    docs_results = docs_search_result["structuredContent"]["results"]
    assert docs_results
    assert any(item["resource_id"] == "mds.drone_show" for item in docs_results)
    first_chunk_id = docs_results[0]["id"]

    docs_chunk_response = client.post(
        MCP_PATH,
        json=_request(
            "tools/call",
            params={"name": "mds.docs.chunk.read", "arguments": {"chunk_id": first_chunk_id, "max_chars": 1200}},
        ),
    )
    assert docs_chunk_response.status_code == 200
    docs_chunk_result = docs_chunk_response.json()["result"]
    assert docs_chunk_result["isError"] is False
    assert docs_chunk_result["structuredContent"]["chunk"]["canonical_url"].startswith("/api/v1/simurgh/context/")
    assert "show" in docs_chunk_result["structuredContent"]["text"].lower()

    docs_missing_query_response = client.post(
        MCP_PATH,
        json=_request("tools/call", params={"name": "mds.docs.search", "arguments": {"limit": 1}}),
    )
    assert docs_missing_query_response.status_code == 200
    assert docs_missing_query_response.json()["result"]["isError"] is True

    docs_invalid_chunk_response = client.post(
        MCP_PATH,
        json=_request(
            "tools/call",
            params={"name": "mds.docs.chunk.read", "arguments": {"chunk_id": "../secret"}},
        ),
    )
    assert docs_invalid_chunk_response.status_code == 200
    assert docs_invalid_chunk_response.json()["result"]["isError"] is True

    advisory_response = client.post(
        MCP_PATH,
        json=_request(
            "tools/call",
            params={
                "name": "mds.operator.question.answer",
                "arguments": {"question": "what are different modes of drone show and their different launch modes?"},
            },
        ),
    )
    assert advisory_response.status_code == 200
    advisory_result = advisory_response.json()["result"]
    assert advisory_result["isError"] is False
    assert advisory_result["structuredContent"]["intent"] == "show_modes_help"
    assert "Drone Show has two workflow families" in advisory_result["content"][0]["text"]

    blocked_advisory_response = client.post(
        MCP_PATH,
        json=_request(
            "tools/call",
            params={
                "name": "mds.operator.question.answer",
                "arguments": {"question": "Can you launch the drone show now?"},
            },
        ),
    )
    assert blocked_advisory_response.status_code == 200
    blocked_result = blocked_advisory_response.json()["result"]
    assert blocked_result["isError"] is True
    assert "blocked" in blocked_result["content"][0]["text"].lower()

    metrics_snapshot_response = client.post(
        MCP_PATH,
        json=_request("tools/call", params={"name": "mds.shows.skybrush.metrics_snapshot.read", "arguments": {}}),
    )
    assert metrics_snapshot_response.status_code == 200
    metrics_snapshot_result = metrics_snapshot_response.json()["result"]
    assert metrics_snapshot_result["isError"] is False
    assert metrics_snapshot_result["structuredContent"]["available"] is True
    assert metrics_snapshot_result["structuredContent"]["metrics"]["basic_metrics"]["drone_count"] == 2


    safety_report_response = client.post(
        MCP_PATH,
        json=_request("tools/call", params={"name": "mds.shows.skybrush.safety_report.read", "arguments": {}}),
    )
    assert safety_report_response.status_code == 200
    safety_report_result = safety_report_response.json()["result"]
    assert safety_report_result["isError"] is False
    assert safety_report_result["structuredContent"]["safety_analysis"]["safety_status"] == "SAFE"

    validation_response = client.post(
        MCP_PATH,
        json=_request("tools/call", params={"name": "mds.shows.skybrush.validation.read", "arguments": {}}),
    )
    assert validation_response.status_code == 200
    validation_result = validation_response.json()["result"]
    assert validation_result["isError"] is False
    assert validation_result["structuredContent"]["validation_status"] == "PASS"

    metrics_response = client.post(
        MCP_PATH,
        json=_request("tools/call", params={"name": "mds.shows.skybrush.metrics.read", "arguments": {}}),
    )
    assert metrics_response.status_code == 200
    assert metrics_response.json()["result"]["isError"] is True

    call_response = client.post(
        MCP_PATH,
        json=_request("tools/call", params={"name": "mds.system.health.read", "arguments": {}}),
    )
    assert call_response.status_code == 200
    result = call_response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"status": "ok", "source": "test"}
    assert '"status": "ok"' in result["content"][0]["text"]

    args_response = client.post(
        MCP_PATH,
        json=_request("tools/call", params={"name": "mds.system.health.read", "arguments": {"extra": True}}),
    )
    assert args_response.status_code == 200
    assert args_response.json()["result"]["isError"] is True

    unknown_response = client.post(
        MCP_PATH,
        json=_request("tools/call", params={"name": "mds.commands.raw_submit", "arguments": {}}),
    )
    assert unknown_response.status_code == 200
    assert unknown_response.json()["result"]["isError"] is True


def test_simurgh_mcp_rejects_batching_and_invalid_params(monkeypatch):
    _enable_mcp(monkeypatch)
    client = _client()

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

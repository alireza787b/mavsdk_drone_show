from __future__ import annotations

import json

import pytest

from tools.simurgh_mcp_smoke_client import (
    MCP_PROTOCOL_VERSION,
    McpHttpClient,
    SimurghMcpSmokeError,
    json_rpc_payload,
    load_bearer_token,
    normalize_mcp_endpoint,
    run_smoke,
)


class FakeMcpClient:
    def __init__(self, *, tools=None):
        self.calls = []
        self.tools = tools or [
            "mds.operator.question.answer",
            "mds.docs.search",
            "mds.docs.chunk.read",
            "mds.system.health.read",
            "mds.fleet.telemetry.read",
            "mds.fleet.heartbeats.read",
            "mds.config.fleet.read",
            "mds.logs.sessions.read",
            "mds.logs.session.read",
            "mds.runtime.status.read",
            "mds.swarm.config.read",
            "mds.origin.launch_positions.read",
            "mds.simurgh.tool_candidates.read",
        ]

    def protected_resource_metadata(self):
        return {
            "resource": "https://gcs.example/api/v1/simurgh/mcp",
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["agent"],
            "mds_auth_required": True,
            "mds_boundary": "gcs-only",
            "mds_execution": "read_only_tools",
        }

    def call(self, request_id, method, params=None):
        self.calls.append((request_id, method, params or {}))
        if method == "initialize":
            return {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "serverInfo": {"name": "mds-simurgh-operator", "version": "test"},
            }
        if method == "prompts/list":
            return {"prompts": [{"name": "mds.compare_mission_modes"}]}
        if method == "prompts/get":
            return {"messages": [{"role": "user", "content": {"type": "text", "text": "Compare mission modes."}}]}
        if method == "tools/list":
            return {"tools": [{"name": name} for name in self.tools]}
        if method == "resources/list":
            return {
                "resources": [
                    {"uri": "mds://simurgh/status"},
                    {"uri": "mds://simurgh/tool-registry"},
                    {"uri": "mds://simurgh/context-index"},
                ]
            }
        if method == "resources/read":
            if params["uri"] == "mds://simurgh/tool-registry":
                return {
                    "contents": [
                        {
                            "uri": params["uri"],
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "version": "test",
                                    "filtered_tool_count": 1,
                                    "tools": [
                                        {
                                            "id": name,
                                            "boundary": "gcs",
                                            "read_only": True,
                                            "destructive": False,
                                            "exposure": "allow",
                                        }
                                        for name in self.tools
                                    ],
                                }
                            ),
                        }
                    ]
                }
            return {
                "contents": [
                    {
                        "uri": params["uri"],
                        "mimeType": "application/json",
                        "text": json.dumps(
                            {
                                "agent_enabled": True,
                                "mcp_enabled": True,
                                "gcs_mode": "sitl",
                                "gcs_mode_source": "env:MDS_MODE",
                                "mode": "sitl",
                                "action_circuit_breaker_enabled": True,
                                "always_confirm_before_action": True,
                                "actions_blocked": True,
                                "warnings": [],
                            }
                        ),
                    }
                ]
            }
        if method == "tools/call":
            tool_name = params["name"]
            if tool_name == "mds.docs.search":
                return {
                    "isError": False,
                    "structuredContent": {"results": [{"id": "simurgh.mcp_client_recipes:001"}]},
                    "content": [{"type": "text", "text": f"{tool_name} answered safely"}],
                }
            if tool_name == "mds.docs.chunk.read":
                return {"isError": False, "content": [{"type": "text", "text": "MCP client recipe chunk"}]}
            if tool_name == "mds.simurgh.tool_candidates.read":
                return {
                    "isError": False,
                    "structuredContent": {
                        "summary": {
                            "registry_coverage": {
                                "eligible_read_only_candidate_count": 79,
                                "promoted_eligible_candidate_count": 79,
                                "promoted_eligible_ratio": 1.0,
                                "unpromoted_eligible_candidate_count": 0,
                                "unpromoted_eligible_by_area": [],
                            }
                        }
                    },
                    "content": [{"type": "text", "text": "registry coverage ok"}],
                }
            if tool_name == "mds.operator.question.answer" and "launch" in params["arguments"].get("question", ""):
                return {"isError": True, "content": [{"type": "text", "text": "Blocked: no action was executed."}]}
            return {"content": [{"type": "text", "text": f"{tool_name} answered safely"}]}
        raise AssertionError(method)


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_normalize_mcp_endpoint_accepts_base_or_full_endpoint():
    assert normalize_mcp_endpoint("https://gcs.example") == "https://gcs.example/api/v1/simurgh/mcp"
    assert normalize_mcp_endpoint("https://gcs.example/") == "https://gcs.example/api/v1/simurgh/mcp"
    assert normalize_mcp_endpoint("https://gcs.example/api/v1/simurgh/mcp") == "https://gcs.example/api/v1/simurgh/mcp"


def test_json_rpc_payload_keeps_params_optional():
    assert json_rpc_payload(7, "ping") == {"jsonrpc": "2.0", "id": 7, "method": "ping"}
    assert json_rpc_payload(8, "tools/list", {}) == {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/list",
        "params": {},
    }


def test_http_client_sends_timeout_as_keyword_and_never_as_body():
    calls = []

    def opener(request, *, timeout):
        calls.append((request, timeout))
        return FakeHttpResponse({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})

    client = McpHttpClient("https://gcs.example/api/v1/simurgh/mcp", bearer_token="secret", timeout=7.5, opener=opener)

    assert client.call(1, "ping") == {"ok": True}
    request, timeout = calls[0]
    assert timeout == 7.5
    assert isinstance(request.data, bytes)
    assert json.loads(request.data.decode("utf-8"))["method"] == "ping"
    assert request.headers["Authorization"] == "Bearer secret"


def test_load_bearer_token_prefers_explicit_env_then_file(monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("MDS_MCP_BEARER_TOKEN", "env-token")

    assert load_bearer_token(token="direct-token", token_file=str(token_file)) == "direct-token"
    assert load_bearer_token(token_file=str(token_file)) == "env-token"
    monkeypatch.delenv("MDS_MCP_BEARER_TOKEN")
    assert load_bearer_token(token_file=str(token_file)) == "file-token"


def test_load_bearer_token_reports_missing_file(tmp_path):
    with pytest.raises(SimurghMcpSmokeError):
        load_bearer_token(token_env="", token_file=str(tmp_path / "missing"))


def test_run_smoke_calls_expected_mcp_methods_and_summarizes_read_only_surface():
    client = FakeMcpClient()

    summary = run_smoke(
        client,
        question="What can Simurgh inspect?",
        min_tools=3,
        expected_runtime_mode="sitl",
    )

    assert summary["server"]["name"] == "mds-simurgh-operator"
    assert summary["protocol_version"] == MCP_PROTOCOL_VERSION
    assert summary["tool_count"] == 13
    assert summary["prompt_count"] == 1
    assert summary["resource_count"] == 3
    assert summary["blocked_action_verified"] is True
    assert summary["auth_posture"]["mds_auth_required"] is True
    assert summary["safety_posture"]["mode"] == "sitl"
    assert summary["safety_posture"]["gcs_mode"] == "sitl"
    assert summary["safety_posture"]["action_circuit_breaker_enabled"] is True
    assert summary["tool_surface"]["listed_tool_count"] == 13
    assert summary["registry_coverage"]["unpromoted_eligible_candidate_count"] == 0
    assert "mds.operator.question.answer answered safely" in summary["answer_preview"]
    assert "MCP client recipe chunk" in summary["docs_chunk_preview"]
    assert [method for _, method, _ in client.calls] == [
        "initialize",
        "prompts/list",
        "tools/list",
        "resources/list",
        "resources/read",
        "resources/read",
        "prompts/get",
        "tools/call",
        "tools/call",
        "tools/call",
        "tools/call",
        "tools/call",
    ]
    assert client.calls[7][2] == {
        "name": "mds.operator.question.answer",
        "arguments": {"question": "What can Simurgh inspect?"},
    }
    assert client.calls[10][2] == {
        "name": "mds.simurgh.tool_candidates.read",
        "arguments": {"eligible_read_only": True, "limit": 200},
    }


def test_run_smoke_fails_when_protected_resource_auth_is_disabled():
    class AuthDisabledClient(FakeMcpClient):
        def protected_resource_metadata(self):
            payload = super().protected_resource_metadata()
            payload["mds_auth_required"] = False
            return payload

    with pytest.raises(SimurghMcpSmokeError, match="auth is not required"):
        run_smoke(AuthDisabledClient(), min_tools=1, expected_runtime_mode="sitl")


def test_run_smoke_fails_on_protocol_version_mismatch():
    class ProtocolDriftClient(FakeMcpClient):
        def call(self, request_id, method, params=None):
            result = super().call(request_id, method, params)
            if method == "initialize":
                result["protocolVersion"] = "2024-01-01"
            return result

    with pytest.raises(SimurghMcpSmokeError, match="protocol version mismatch"):
        run_smoke(ProtocolDriftClient(), min_tools=1, expected_runtime_mode="sitl")


def test_run_smoke_fails_when_expected_tools_are_missing():
    client = FakeMcpClient(tools=["mds.docs.search", "mds.system.health.read"])

    with pytest.raises(SimurghMcpSmokeError, match="expected MCP tools are missing"):
        run_smoke(client, min_tools=1)


def test_run_smoke_fails_on_runtime_mode_or_safety_posture_mismatch():
    with pytest.raises(SimurghMcpSmokeError, match="runtime mode mismatch"):
        run_smoke(FakeMcpClient(), min_tools=1, expected_runtime_mode="real")

    class UnsafePostureClient(FakeMcpClient):
        def call(self, request_id, method, params=None):
            result = super().call(request_id, method, params)
            if method == "resources/read":
                payload = json.loads(result["contents"][0]["text"])
                payload["action_circuit_breaker_enabled"] = False
                payload["actions_blocked"] = False
                result["contents"][0]["text"] = json.dumps(payload)
            return result

    with pytest.raises(SimurghMcpSmokeError, match="unsafe Simurgh smoke posture"):
        run_smoke(UnsafePostureClient(), min_tools=1, expected_runtime_mode="sitl")

    class MismatchedRuntimeClient(FakeMcpClient):
        def call(self, request_id, method, params=None):
            result = super().call(request_id, method, params)
            if method == "resources/read":
                payload = json.loads(result["contents"][0]["text"])
                payload["mode"] = "sitl"
                payload["gcs_mode"] = "real"
                payload["warnings"] = ["Simurgh policy mode did not resolve to canonical MDS_MODE."]
                result["contents"][0]["text"] = json.dumps(payload)
            return result

    with pytest.raises(SimurghMcpSmokeError, match="policy/runtime mode mismatch"):
        run_smoke(MismatchedRuntimeClient(), min_tools=1, expected_runtime_mode="sitl")

    class MissingCanonicalRuntimeClient(FakeMcpClient):
        def call(self, request_id, method, params=None):
            result = super().call(request_id, method, params)
            if method == "resources/read" and params["uri"] == "mds://simurgh/status":
                payload = json.loads(result["contents"][0]["text"])
                payload.pop("gcs_mode", None)
                result["contents"][0]["text"] = json.dumps(payload)
            return result

    with pytest.raises(SimurghMcpSmokeError, match="missing canonical gcs_mode"):
        run_smoke(MissingCanonicalRuntimeClient(), min_tools=1, expected_runtime_mode="sitl")


def test_run_smoke_fails_when_listed_tool_is_not_safe_in_registry_resource():
    class UnsafeRegistryClient(FakeMcpClient):
        def call(self, request_id, method, params=None):
            result = super().call(request_id, method, params)
            if method == "resources/read" and params["uri"] == "mds://simurgh/tool-registry":
                payload = json.loads(result["contents"][0]["text"])
                payload["tools"][0]["read_only"] = False
                result["contents"][0]["text"] = json.dumps(payload)
            return result

    with pytest.raises(SimurghMcpSmokeError, match="unsafe MCP tool registry posture"):
        run_smoke(UnsafeRegistryClient(), min_tools=1, expected_runtime_mode="sitl")


def test_run_smoke_fails_if_forbidden_looking_tools_are_exposed():
    client = FakeMcpClient(tools=[
        "mds.operator.question.answer",
        "mds.docs.search",
        "mds.docs.chunk.read",
        "mds.simurgh.tool_candidates.read",
        "mds.origin.launch_positions.read",
        "mds.system.health.read",
        "mds.commands.raw_submit",
    ])

    with pytest.raises(SimurghMcpSmokeError, match="forbidden-looking tools"):
        run_smoke(client, min_tools=1)


def test_run_smoke_allows_read_only_launch_position_inspection_tool():
    summary = run_smoke(FakeMcpClient(), min_tools=1)

    assert "mds.origin.launch_positions.read" in summary["tools_preview"]
    assert summary["tool_count"] == 13


def test_run_smoke_fails_when_live_registry_coverage_has_unpromoted_candidates():
    class DriftClient(FakeMcpClient):
        def call(self, request_id, method, params=None):
            result = super().call(request_id, method, params)
            if method == "tools/call" and params["name"] == "mds.simurgh.tool_candidates.read":
                result["structuredContent"]["summary"]["registry_coverage"] = {
                    "eligible_read_only_candidate_count": 80,
                    "promoted_eligible_candidate_count": 79,
                    "promoted_eligible_ratio": 0.9875,
                    "unpromoted_eligible_candidate_count": 1,
                    "unpromoted_eligible_by_area": [{"area": "fleet", "count": 1}],
                }
            return result

    with pytest.raises(SimurghMcpSmokeError, match="registry coverage drift"):
        run_smoke(DriftClient(), min_tools=1)


def test_run_smoke_accepts_route_style_registry_coverage_fields():
    class RouteStyleCoverageClient(FakeMcpClient):
        def call(self, request_id, method, params=None):
            result = super().call(request_id, method, params)
            if method == "tools/call" and params["name"] == "mds.simurgh.tool_candidates.read":
                result["structuredContent"]["summary"]["registry_coverage"] = {
                    "eligible_route_candidates": 79,
                    "eligible_promoted_route_matches": 79,
                    "eligible_unpromoted_route_count": 0,
                    "eligible_promotion_coverage_percent": 100.0,
                    "eligible_unpromoted_by_group": {},
                }
            return result

    summary = run_smoke(RouteStyleCoverageClient(), min_tools=1)

    assert summary["registry_coverage"]["unpromoted_eligible_candidate_count"] == 0
    assert summary["registry_coverage"]["promoted_eligible_ratio"] == 1.0


def test_script_json_summary_contains_no_token_words():
    summary = run_smoke(FakeMcpClient(), min_tools=3)
    serialized = json.dumps(summary)
    assert "token" not in serialized.lower()

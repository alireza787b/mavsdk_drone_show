from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from agent_runtime import (
    AgentContextIndex,
    AgentPolicy,
    AgentRuntimeError,
    AgentSessionStore,
    InMemoryApprovalBroker,
    InMemoryAuditSink,
    JsonlAuditSink,
    PolicyDecisionStatus,
    ToolExposure,
    ToolRiskClass,
    load_default_context_index,
    load_default_policy,
    load_default_tool_registry,
)
from tests.test_api_route_inventory import GCS_EXPECTED_HTTP


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_REGISTRY_PATH = REPO_ROOT / "config" / "agent_tools.yaml"
POLICY_PATH = REPO_ROOT / "config" / "agent_policy.yaml"


def _enabled_policy_payload(*, mode: str = "read_only", mcp_enabled: bool = False) -> dict:
    payload = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    payload["defaults"]["agent_enabled"] = True
    payload["defaults"]["mcp_enabled"] = mcp_enabled
    payload["defaults"]["mode"] = mode
    return payload


def test_default_registry_loads_with_curated_exposure_boundaries():
    registry = load_default_tool_registry()

    assert registry.version == 1
    assert registry.require("mds.system.health.read").exposure is ToolExposure.ALLOW
    assert registry.require("mds.system.health.read").risk_class is ToolRiskClass.OBSERVE
    assert registry.require("mds.commands.raw_submit").exposure is ToolExposure.EXCLUDE
    assert registry.require("mds.drone.commands.raw_submit").boundary == "drone"

    unsafe_direct_allows = [
        tool.id
        for tool in registry.list_tools(exposure=ToolExposure.ALLOW)
        if tool.boundary != "gcs"
        or tool.risk_class in {ToolRiskClass.OPERATE, ToolRiskClass.ADMIN, ToolRiskClass.DESTRUCTIVE}
        or tool.destructive
    ]

    assert unsafe_direct_allows == []


def test_gcs_backed_tool_routes_match_frozen_inventory():
    registry = load_default_tool_registry()

    missing = []
    for tool in registry.list_tools():
        if tool.boundary != "gcs" or not tool.route_method or not tool.route_path:
            continue
        expected_paths = GCS_EXPECTED_HTTP.get(tool.route_method, set())
        if tool.route_path not in expected_paths:
            missing.append((tool.id, tool.route_method, tool.route_path))

    assert missing == []


def test_registry_rejects_unsafe_direct_flight_tool():
    payload = yaml.safe_load(TOOL_REGISTRY_PATH.read_text(encoding="utf-8"))
    payload["tools"].append(
        {
            "id": "bad.raw.flight",
            "title": "Bad raw flight",
            "description": "Invalid direct flight operation.",
            "exposure": "allow",
            "risk_class": "operate",
            "boundary": "gcs",
            "read_only": False,
            "route": {"method": "POST", "path": "/api/v1/commands"},
        }
    )

    with pytest.raises(AgentRuntimeError):
        load_default_tool_registry().__class__.from_mapping(payload, path=TOOL_REGISTRY_PATH)


def test_registry_wraps_invalid_enum_values_as_agent_errors():
    payload = yaml.safe_load(TOOL_REGISTRY_PATH.read_text(encoding="utf-8"))
    payload["tools"][0]["risk_class"] = "unknown_risk"

    with pytest.raises(AgentRuntimeError, match="invalid exposure or risk_class"):
        load_default_tool_registry().__class__.from_mapping(payload, path=TOOL_REGISTRY_PATH)


def test_default_policy_enables_non_executing_runtime_and_allows_safe_observe():
    registry = load_default_tool_registry()
    policy = load_default_policy()

    decision = policy.evaluate_tool(registry.require("mds.system.health.read"))

    assert policy.agent_enabled is True
    assert decision.status is PolicyDecisionStatus.ALLOW


def test_agent_runtime_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "false")
    registry = load_default_tool_registry()
    policy = load_default_policy()

    decision = policy.evaluate_tool(registry.require("mds.system.health.read"))

    assert decision.status is PolicyDecisionStatus.DENY
    assert "agent runtime disabled" in decision.reasons


def test_policy_rejects_malformed_runtime_policy():
    payload = _enabled_policy_payload()
    payload["runtime_modes"]["read_only"] = "bad"

    with pytest.raises(AgentRuntimeError, match="runtime mode 'read_only' must be an object"):
        AgentPolicy.from_mapping(payload, path=POLICY_PATH)

    payload = _enabled_policy_payload()
    payload["runtime_modes"]["read_only"]["allowed_risks"].append("bad_risk")

    with pytest.raises(AgentRuntimeError, match="invalid risk"):
        AgentPolicy.from_mapping(payload, path=POLICY_PATH)

    payload = _enabled_policy_payload()
    payload["defaults"]["unknown_tool_policy"] = "allow"

    with pytest.raises(AgentRuntimeError, match="unknown_tool_policy"):
        AgentPolicy.from_mapping(payload, path=POLICY_PATH)


def test_policy_env_overrides_are_strict_booleans(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "banana")

    with pytest.raises(AgentRuntimeError, match="MDS_AGENT_ENABLED must be boolean"):
        AgentPolicy.from_mapping(_enabled_policy_payload(), path=POLICY_PATH, apply_env=True)


def test_enabled_read_only_policy_allows_observe_and_denies_non_read_only_planning():
    registry = load_default_tool_registry()
    policy = AgentPolicy.from_mapping(_enabled_policy_payload(), path=POLICY_PATH)

    health = policy.evaluate_tool(registry.require("mds.system.health.read"))
    plan = policy.evaluate_tool(registry.require("mds.sar.mission.plan"))
    raw = policy.evaluate_tool(registry.require("mds.commands.raw_submit"))
    sitl_create = policy.evaluate_tool(registry.require("mds.sitl.instances.create"))

    assert health.status is PolicyDecisionStatus.ALLOW
    assert plan.status is PolicyDecisionStatus.DENY
    assert "tool is not available in mode 'read_only'" in plan.reasons
    assert "non-read-only tool is denied in read_only mode" in plan.reasons
    assert raw.status is PolicyDecisionStatus.DENY
    assert "tool is explicitly excluded" in raw.reasons
    assert sitl_create.status is PolicyDecisionStatus.DENY
    assert "risk class 'simulate' is denied in mode 'read_only'" in sitl_create.reasons


def test_mcp_channel_requires_separate_mcp_enablement():
    registry = load_default_tool_registry()
    disabled = AgentPolicy.from_mapping(_enabled_policy_payload(mcp_enabled=False), path=POLICY_PATH)
    enabled = AgentPolicy.from_mapping(_enabled_policy_payload(mcp_enabled=True), path=POLICY_PATH)
    tool = registry.require("mds.system.health.read")

    assert disabled.evaluate_tool(tool, channel="mcp").status is PolicyDecisionStatus.DENY
    assert enabled.evaluate_tool(tool, channel="mcp").status is PolicyDecisionStatus.ALLOW


def test_sitl_policy_approval_gate_can_be_satisfied_without_real_commands():
    registry = load_default_tool_registry()
    policy = AgentPolicy.from_mapping(_enabled_policy_payload(mode="sitl"), path=POLICY_PATH)
    tool = registry.require("mds.sitl.instances.create")

    assert policy.action_circuit_breaker_enabled is True
    blocked = policy.evaluate_tool(tool)
    assert blocked.status is PolicyDecisionStatus.DENY
    assert "Simurgh action circuit breaker is enabled" in blocked.reasons

    payload = _enabled_policy_payload(mode="sitl")
    payload["defaults"]["action_circuit_breaker_enabled"] = False
    policy = AgentPolicy.from_mapping(payload, path=POLICY_PATH)

    assert policy.evaluate_tool(tool).status is PolicyDecisionStatus.REQUIRE_APPROVAL
    assert policy.evaluate_tool(tool, approved=True).status is PolicyDecisionStatus.ALLOW
    assert policy.evaluate_tool(registry.require("mds.sar.mission.plan")).status is PolicyDecisionStatus.REQUIRE_APPROVAL
    assert policy.evaluate_tool(registry.require("mds.sar.mission.plan"), approved=True).status is PolicyDecisionStatus.ALLOW
    assert policy.evaluate_tool(registry.require("mds.sar.mission.launch"), approved=True).status is PolicyDecisionStatus.DENY


def test_policy_env_overrides_action_circuit_and_confirmation(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "false")

    policy = AgentPolicy.from_mapping(_enabled_policy_payload(), path=POLICY_PATH, apply_env=True)

    assert policy.action_circuit_breaker_enabled is False
    assert policy.always_confirm_before_action is False


def test_approval_broker_binds_approval_to_session_tool_and_input():
    broker = InMemoryApprovalBroker(ttl_seconds=60)
    request = broker.request(
        session_id="session-1",
        tool_id="mds.sar.mission.plan",
        actor="operator",
        rationale="Planning only",
        tool_input={"mission_id": "m-1"},
    )

    assert not broker.is_approved(
        request.id,
        session_id="session-1",
        tool_id="mds.sar.mission.plan",
        tool_input={"mission_id": "m-1"},
    )

    broker.decide(request.id, approved=True, decided_by="human-operator", reason="SITL planning accepted")

    assert broker.is_approved(
        request.id,
        session_id="session-1",
        tool_id="mds.sar.mission.plan",
        tool_input={"mission_id": "m-1"},
    )
    assert not broker.is_approved(
        request.id,
        session_id="session-1",
        tool_id="mds.sar.mission.plan",
        tool_input={"mission_id": "m-2"},
    )


def test_audit_sinks_store_hashes_not_raw_payloads(tmp_path):
    memory_sink = InMemoryAuditSink()
    event = memory_sink.record(
        "tool_decision",
        session_id="session-1",
        actor="operator",
        tool_id="mds.fleet.telemetry.read",
        decision="allow",
        payload={"lat": 47.0, "secret": "do-not-write"},
    )

    assert event.payload_hash
    assert "do-not-write" not in json.dumps(event.to_json_dict())

    jsonl_path = tmp_path / "audit.jsonl"
    jsonl_sink = JsonlAuditSink(jsonl_path)
    jsonl_sink.record("tool_decision", payload={"secret": "do-not-write"})

    assert "do-not-write" not in jsonl_path.read_text(encoding="utf-8")


def test_session_store_creates_and_closes_sessions():
    store = AgentSessionStore(ttl_seconds=60)
    session = store.create(
        actor="operator",
        mode="read_only",
        metadata={
            "channel": "dashboard",
            "source": "simurgh-ui",
            "raw_prompt": "AIRFRAME-01 stopped streaming on 192.168.1.10",
            "unsafe": "contains spaces",
        },
    )

    assert store.require(session.id).actor == "operator"
    assert store.require(session.id).metadata == {"channel": "dashboard", "source": "simurgh-ui"}
    assert store.close(session.id).closed
    assert store.list_sessions(include_closed=False) == []


def test_session_store_marks_expired_sessions_during_listing():
    store = AgentSessionStore(ttl_seconds=60)
    session = store.create(actor="operator", mode="read_only")
    store._sessions[session.id] = replace(session, expires_at=session.created_at - timedelta(seconds=1))

    assert store.list_sessions(include_closed=False) == []
    assert store.require(session.id).closed


def test_context_index_loads_agent_docs_and_blocks_path_escape():
    index = load_default_context_index()

    assert "raw gcs command submission" in index.read_text("simurgh.safety_policy").lower()
    assert index.require("simurgh.default_operator_prompt").path == Path("docs/agent-context/prompts/default-operator.md")

    payload = yaml.safe_load((REPO_ROOT / "docs" / "agent-context" / "context-index.yaml").read_text(encoding="utf-8"))
    payload["resources"].append(
        {
            "id": "bad.escape",
            "title": "Bad escape",
            "path": "../secret",
            "mime_type": "text/plain",
        }
    )

    with pytest.raises(AgentRuntimeError):
        AgentContextIndex.from_mapping(payload, repo_root=REPO_ROOT)


def test_context_index_blocks_symlink_prefix_escape(tmp_path):
    repo_root = tmp_path / "repo"
    docs_dir = repo_root / "docs"
    sibling_root = tmp_path / "repo-secret"
    docs_dir.mkdir(parents=True)
    sibling_root.mkdir()
    secret_path = sibling_root / "secret.md"
    secret_path.write_text("outside repo", encoding="utf-8")
    (docs_dir / "linked.md").symlink_to(secret_path)

    payload = {
        "version": 1,
        "resources": [
            {
                "id": "bad.symlink",
                "title": "Bad symlink",
                "path": "docs/linked.md",
                "mime_type": "text/markdown",
            }
        ],
    }

    with pytest.raises(AgentRuntimeError, match="escapes repo root"):
        AgentContextIndex.from_mapping(payload, repo_root=repo_root)


def test_context_index_read_revalidates_resource_path(tmp_path):
    repo_root = tmp_path / "repo"
    docs_dir = repo_root / "docs"
    sibling_root = tmp_path / "repo-secret"
    docs_dir.mkdir(parents=True)
    sibling_root.mkdir()
    safe_path = docs_dir / "safe.md"
    safe_path.write_text("safe", encoding="utf-8")
    secret_path = sibling_root / "secret.md"
    secret_path.write_text("outside repo", encoding="utf-8")

    payload = {
        "version": 1,
        "resources": [
            {
                "id": "safe",
                "title": "Safe",
                "path": "docs/safe.md",
                "mime_type": "text/markdown",
            }
        ],
    }
    index = AgentContextIndex.from_mapping(payload, repo_root=repo_root)

    safe_path.unlink()
    safe_path.symlink_to(secret_path)

    with pytest.raises(AgentRuntimeError, match="escapes repo root"):
        index.read_text("safe")

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI

from agent_runtime import AgentPolicy, AgentRuntimeError, PolicyDecisionStatus
from agent_runtime.tool_executor import (
    InternalToolExecutionContext,
    execute_policy_allowed_guarded_route_tool,
    list_policy_available_guarded_tools,
)
from agent_runtime.tool_registry import ToolRegistry, load_default_tool_registry


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "config" / "agent_policy.yaml"
TOOL_REGISTRY_PATH = REPO_ROOT / "config" / "agent_tools.yaml"


def _sitl_policy(*, circuit_breaker: bool) -> AgentPolicy:
    payload = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    payload["defaults"].update(
        {
            "agent_enabled": True,
            "mode": "sitl",
            "action_circuit_breaker_enabled": circuit_breaker,
        }
    )
    return AgentPolicy.from_mapping(payload, path=POLICY_PATH)


@pytest.mark.parametrize("actor_role", ["agent", "viewer"])
@pytest.mark.parametrize(
    ("tool_id", "required_role"),
    [
        ("mds.sar.mission.plan", "operator"),
        ("mds.sitl.instances.create", "admin"),
    ],
)
def test_viewer_and_agent_roles_cannot_use_elevated_tools(
    actor_role: str,
    tool_id: str,
    required_role: str,
) -> None:
    registry = load_default_tool_registry()
    policy = _sitl_policy(circuit_breaker=False)

    decision = policy.evaluate_tool(
        registry.require(tool_id),
        approved=True,
        actor_role=actor_role,
    )

    assert decision.status is PolicyDecisionStatus.DENY
    assert (
        f"actor role 'viewer' does not satisfy required role '{required_role}'"
        in decision.reasons
    )


def test_operator_can_use_operator_tool_but_not_admin_tool() -> None:
    registry = load_default_tool_registry()
    policy = _sitl_policy(circuit_breaker=False)

    operator_decision = policy.evaluate_tool(
        registry.require("mds.sar.mission.plan"),
        approved=True,
        actor_role="operator",
    )
    admin_decision = policy.evaluate_tool(
        registry.require("mds.sitl.instances.create"),
        approved=True,
        actor_role="operator",
    )

    assert operator_decision.status is PolicyDecisionStatus.ALLOW
    assert admin_decision.status is PolicyDecisionStatus.DENY
    assert (
        "actor role 'operator' does not satisfy required role 'admin'"
        in admin_decision.reasons
    )


def test_admin_can_use_operator_and_admin_tools() -> None:
    registry = load_default_tool_registry()
    policy = _sitl_policy(circuit_breaker=False)

    assert (
        policy.evaluate_tool(
            registry.require("mds.sar.mission.plan"),
            approved=True,
            actor_role="admin",
        ).status
        is PolicyDecisionStatus.ALLOW
    )
    assert (
        policy.evaluate_tool(
            registry.require("mds.sitl.instances.create"),
            approved=True,
            actor_role="admin",
        ).status
        is PolicyDecisionStatus.ALLOW
    )


def test_missing_or_unknown_actor_role_fails_closed() -> None:
    registry = load_default_tool_registry()
    policy = _sitl_policy(circuit_breaker=False)
    tool = registry.require("mds.system.health.read")

    for actor_role in (None, "", "superuser"):
        decision = policy.evaluate_tool(tool, actor_role=actor_role)
        assert decision.status is PolicyDecisionStatus.DENY
        assert "actor role is missing or unsupported" in decision.reasons


def test_guarded_tool_listing_is_role_filtered() -> None:
    registry = load_default_tool_registry()
    policy = _sitl_policy(circuit_breaker=False)

    viewer_ids = {
        tool.id
        for tool in list_policy_available_guarded_tools(
            channel="agent",
            actor_role="viewer",
            registry=registry,
            policy=policy,
        )
    }
    operator_ids = {
        tool.id
        for tool in list_policy_available_guarded_tools(
            channel="agent",
            actor_role="operator",
            registry=registry,
            policy=policy,
        )
    }
    admin_ids = {
        tool.id
        for tool in list_policy_available_guarded_tools(
            channel="agent",
            actor_role="admin",
            registry=registry,
            policy=policy,
        )
    }

    assert "mds.sar.mission.plan" not in viewer_ids
    assert "mds.sitl.instances.create" not in viewer_ids
    assert "mds.sar.mission.plan" in operator_ids
    assert "mds.sitl.instances.create" not in operator_ids
    assert "mds.sar.mission.plan" in admin_ids
    assert "mds.sitl.instances.create" in admin_ids


def test_registry_rejects_unknown_required_role() -> None:
    payload = yaml.safe_load(TOOL_REGISTRY_PATH.read_text(encoding="utf-8"))
    payload["tools"][0]["required_role"] = "superuser"

    with pytest.raises(AgentRuntimeError, match="unsupported required_role 'superuser'"):
        ToolRegistry.from_mapping(payload, path=TOOL_REGISTRY_PATH)


@pytest.mark.asyncio
async def test_guarded_dispatch_reloads_policy_and_observes_circuit_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    dispatch_count = 0

    @app.post("/api/v1/system/sitl/instances")
    async def create_sitl_instance() -> dict[str, str]:
        nonlocal dispatch_count
        dispatch_count += 1
        return {"status": "accepted"}

    planning_policy = _sitl_policy(circuit_breaker=False)
    current_policy = _sitl_policy(circuit_breaker=True)
    monkeypatch.setattr(
        "agent_runtime.tool_executor.load_default_policy",
        lambda: current_policy,
    )

    result = await execute_policy_allowed_guarded_route_tool(
        InternalToolExecutionContext(app=app, base_url="http://testserver"),
        name="mds.sitl.instances.create",
        arguments={},
        channel="agent",
        approved=True,
        actor_role="admin",
        policy=planning_policy,
    )

    assert result.is_error is True
    assert "Simurgh action circuit breaker is enabled" in result.text
    assert dispatch_count == 0

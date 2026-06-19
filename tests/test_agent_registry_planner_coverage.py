from __future__ import annotations

from typing import Any, Mapping

import pytest

from agent_runtime.registry_chat import plan_registry_read_tool_calls
from agent_runtime.tool_executor import list_policy_allowed_read_only_tools


SAMPLE_ARGUMENTS: Mapping[str, Any] = {
    "candidate_id": "candidate-1",
    "chunk_id": "mds.init_setup:0",
    "command_id": "cmd-1",
    "hw_id": "2",
    "job_id": "job-1",
    "lat": 35.9555,
    "limit": 10,
    "lon": 52.1101,
    "mission_id": "sar-1",
    "operation_id": "op-1",
    "pos_id": 1,
    "profile_id": "default",
    "resource_id": "simurgh.safety_policy",
    "session_id": "s_20260527_174402",
    "sidecar": "smart-wifi-manager",
    "snapshot_id": "snapshot-1",
    "tool_id": "mds.system.health.read",
}


def _allowed_route_tools():
    return tuple(
        tool
        for tool in list_policy_allowed_read_only_tools(channel="assistant")
        if tool.route_method == "GET" and tool.route_path
    )


def _required_args(tool) -> tuple[str, ...]:  # noqa: ANN001
    schema = tool.input_schema if isinstance(tool.input_schema, Mapping) else {}
    return tuple(str(item) for item in schema.get("required", ()) if str(item))


def _sample_argument(name: str) -> Any:
    return SAMPLE_ARGUMENTS.get(name, f"{name}-1")


def _plan_tool_ids(plan) -> tuple[str, ...]:  # noqa: ANN001
    return tuple(call.tool.id for call in plan.tool_calls) if plan else ()


def test_registry_planner_generates_coverage_for_every_no_argument_read_only_route_tool():
    tools = list_policy_allowed_read_only_tools(channel="assistant")
    no_argument_tools = tuple(tool for tool in _allowed_route_tools() if not _required_args(tool))

    failures = []
    for tool in no_argument_tools:
        prompt = f"show {tool.title} status now"
        plan = plan_registry_read_tool_calls(prompt, allowed_tools=tools, local_intent=None)
        tool_ids = _plan_tool_ids(plan)
        if tool.id not in tool_ids:
            failures.append(
                {
                    "tool_id": tool.id,
                    "prompt": prompt,
                    "planned_tool_ids": tool_ids,
                    "selection_source": getattr(plan, "selection_source", None),
                }
            )

    assert len(no_argument_tools) >= 50
    assert failures == []


def test_registry_planner_generates_coverage_for_typed_read_only_route_tools_with_arguments():
    tools = list_policy_allowed_read_only_tools(channel="assistant")
    typed_tools = tuple(tool for tool in _allowed_route_tools() if _required_args(tool))

    failures = []
    for tool in typed_tools:
        arguments = " ".join(f"{name}={_sample_argument(name)}" for name in _required_args(tool))
        prompt = f"read {tool.title} status now {arguments}"
        plan = plan_registry_read_tool_calls(prompt, allowed_tools=tools, local_intent=None)
        tool_ids = _plan_tool_ids(plan)
        if tool.id not in tool_ids:
            failures.append(
                {
                    "tool_id": tool.id,
                    "prompt": prompt,
                    "planned_tool_ids": tool_ids,
                    "selection_source": getattr(plan, "selection_source", None),
                }
            )

    assert len(typed_tools) >= 20
    assert failures == []


def test_registry_planner_generates_missing_argument_discovery_for_typed_read_only_route_tools():
    tools = list_policy_allowed_read_only_tools(channel="assistant")
    typed_tools = tuple(tool for tool in _allowed_route_tools() if _required_args(tool))

    failures = []
    for tool in typed_tools:
        prompt = f"read details for {tool.title} now"
        plan = plan_registry_read_tool_calls(prompt, allowed_tools=tools, local_intent=None)
        tool_ids = _plan_tool_ids(plan)
        required = tuple(name for name in _required_args(tool) if not (tool.id == "mds.logs.session.read" and name == "limit"))
        missing_arguments = tuple(plan.missing_arguments) if plan else ()
        if not plan or not set(required).issubset(set(missing_arguments)) or tool.id in tool_ids:
            failures.append(
                {
                    "tool_id": tool.id,
                    "prompt": prompt,
                    "planned_tool_ids": tool_ids,
                    "missing_arguments": missing_arguments,
                    "selection_source": getattr(plan, "selection_source", None),
                }
            )

    assert len(typed_tools) >= 20
    assert failures == []


def test_registry_planner_does_not_treat_ready_as_a_sar_mission_identifier():
    tools = list_policy_allowed_read_only_tools(channel="assistant")

    plan = plan_registry_read_tool_calls(
        "is swarm mission ready for field test now",
        allowed_tools=tools,
        local_intent=None,
    )
    planned_ids = _plan_tool_ids(plan)

    assert "mds.sar.mission.status.read" not in planned_ids
    assert "mds.sar.mission.workspace.read" not in planned_ids
    assert "mds.sar.findings.read" not in planned_ids


def test_registry_planner_still_accepts_explicit_sar_mission_id():
    tools = list_policy_allowed_read_only_tools(channel="assistant")

    plan = plan_registry_read_tool_calls(
        "read SAR mission status for mission_id=sar-1 now",
        allowed_tools=tools,
        local_intent=None,
    )

    assert plan is not None
    assert _plan_tool_ids(plan) == ("mds.sar.mission.status.read",)
    assert plan.tool_calls[0].arguments["mission_id"] == "sar-1"


def test_registry_planner_routes_out_of_sync_prompts_to_fleet_git_sync_posture():
    tools = list_policy_allowed_read_only_tools(channel="assistant")

    plan = plan_registry_read_tool_calls(
        "show current out of sync fleet git sync status with gcs",
        allowed_tools=tools,
        local_intent=None,
    )

    assert plan is not None
    assert plan.label == "fleet git sync posture"
    assert _plan_tool_ids(plan)[:2] == ("mds.fleet.git_sync.read", "mds.git.status.read")


def test_registry_planner_defers_all_drone_log_prompts_to_advisory_fanout():
    tools = list_policy_allowed_read_only_tools(channel="assistant")

    plan = plan_registry_read_tool_calls(
        "how many drone logs do we have and was there any errors logged?",
        allowed_tools=tools,
        local_intent="drone_log_summary",
    )

    assert plan is None


def test_registry_planner_extracts_json_launch_position_heading():
    tools = list_policy_allowed_read_only_tools(channel="assistant")

    plan = plan_registry_read_tool_calls(
        "show current desired launch positions at heading 90 degrees",
        allowed_tools=tools,
        local_intent=None,
    )

    assert plan is not None
    assert plan.label == "origin and launch-position evidence"
    assert _plan_tool_ids(plan)[0] == "mds.origin.launch_positions.read"
    assert plan.tool_calls[0].arguments == {"format": "json", "heading": 90.0}


@pytest.mark.parametrize(
    "prompt",
    (
        "can you launch drone 1 now",
        "send command to arm vehicle 2",
        "upload this show to the fleet",
    ),
)
def test_registry_planner_generated_coverage_does_not_weaken_direct_action_blocks(prompt):
    tools = list_policy_allowed_read_only_tools(channel="assistant")

    plan = plan_registry_read_tool_calls(prompt, allowed_tools=tools, local_intent=None)

    assert plan is None

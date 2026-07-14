from __future__ import annotations

import json

import pytest

from agent_runtime.action_intent import (
    build_action_draft_from_provider_plan,
    parse_provider_action_plan,
)


FLIGHT_TOOL_ID = "mds.flight.command.execute"
SITL_ACTION_TOOL_ID = "mds.sitl.instances.action"


def _step(
    message: str,
    excerpt: str,
    *,
    arguments: dict | None = None,
    condition: str = "start",
    tool_id: str = FLIGHT_TOOL_ID,
    label: str = "Action",
    occurrence: int = 0,
    monitor_requested: bool = True,
) -> dict:
    start = -1
    search_from = 0
    for _ in range(occurrence + 1):
        start = message.index(excerpt, search_from)
        search_from = start + len(excerpt)
    return {
        "kind": "tool",
        "tool_id": tool_id,
        "arguments_json": json.dumps(arguments or {}),
        "delay_seconds": None,
        "condition": condition,
        "monitor_requested": monitor_requested,
        "label": label,
        "source_start": start,
        "source_end": start + len(excerpt),
        "source_excerpt": excerpt,
    }


def _delay(
    message: str,
    excerpt: str,
    *,
    seconds: float,
    occurrence: int = 0,
) -> dict:
    start = -1
    search_from = 0
    for _ in range(occurrence + 1):
        start = message.index(excerpt, search_from)
        search_from = start + len(excerpt)
    return {
        "kind": "delay",
        "tool_id": None,
        "arguments_json": "{}",
        "delay_seconds": seconds,
        "condition": "after_command_terminal_success",
        "monitor_requested": False,
        "label": f"Wait {seconds:g} seconds",
        "source_start": start,
        "source_end": start + len(excerpt),
        "source_excerpt": excerpt,
    }


def _tool_contracts() -> dict[str, dict]:
    return {
        FLIGHT_TOOL_ID: {
            "title": "Execute curated flight command",
            "intent": "flight_action",
            "required": ("mission_type", "trigger_time", "target_drone_ids"),
        },
        SITL_ACTION_TOOL_ID: {
            "title": "Run SITL instance lifecycle action",
            "intent": "sitl_lifecycle_action",
            "required": ("action", "instance_names"),
        },
    }


def test_structured_provider_plan_preserves_full_pm_sequence_and_context_target():
    message = (
        "I see it is up. If ready, take off to 10m, wait 10s, fly 20m east, "
        "wait 30s, then RTL."
    )
    payload = {
        "summary": "Test Drone 1 and return",
        "steps": [
            _step(
                message,
                "take off to 10m",
                arguments={"mission_type": 10, "trigger_time": 0, "takeoff_altitude": 10},
                label="Take off to 10 m",
            ),
            _delay(message, "wait 10s", seconds=10),
            _step(
                message,
                "fly 20m east",
                arguments={
                    "mission_type": 112,
                    "trigger_time": 0,
                    "precision_move": {
                        "frame": "ned",
                        "translation_m": {"north": 0, "east": 20, "up": 0},
                    },
                },
                condition="after_command_terminal_success",
                label="Move 20 m east",
            ),
            _delay(message, "wait 30s", seconds=30),
            _step(
                message,
                "RTL",
                arguments={"mission_type": 104, "trigger_time": 0},
                condition="after_command_terminal",
                label="Return to launch",
            ),
        ],
    }

    plan = parse_provider_action_plan(payload, original_message=message)
    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-structured",
        previous_action={"target_drone_ids": ["1"]},
        tool_contracts=_tool_contracts(),
    )

    assert result.accepted
    assert result.draft is not None
    assert result.draft.ready
    assert result.draft.target_drone_ids == ("1",)
    assert result.draft.command_payload["takeoff_altitude"] == 10.0
    assert [step["type"] for step in result.draft.post_actions] == [
        "delay",
        "flight_command",
        "delay",
        "flight_command",
    ]
    assert result.draft.post_actions[0]["delay_seconds"] == 10.0
    assert result.draft.post_actions[1]["arguments"]["precision_move"]["translation_m"]["east"] == 20.0
    assert result.draft.post_actions[2]["delay_seconds"] == 30.0
    assert result.draft.post_actions[3]["condition"] == "after_command_terminal"


def test_provider_plan_source_span_must_match_original_operator_message():
    message = "take off to 10m"
    payload = {
        "summary": "Take off",
        "steps": [
            {
                **_step(
                    message,
                    message,
                    arguments={"mission_type": 10, "trigger_time": 0, "takeoff_altitude": 10},
                ),
                "source_excerpt": "take off to 20m",
            }
        ],
    }

    with pytest.raises(ValueError, match="source span does not match"):
        parse_provider_action_plan(payload, original_message=message)


def test_provider_plan_cannot_change_digit_bearing_operator_facts():
    message = "take off to 10m"
    payload = {
        "summary": "Take off",
        "steps": [
            _step(
                message,
                message,
                arguments={"mission_type": 10, "trigger_time": 0, "takeoff_altitude": 20},
            )
        ],
    }

    with pytest.raises(ValueError, match="not grounded"):
        parse_provider_action_plan(payload, original_message=message)


def test_structured_plan_is_language_independent_after_semantic_interpretation():
    message = "پهپاد را ده متر بلند کن"
    excerpt = message
    plan = parse_provider_action_plan(
        {
            "summary": "Take off",
            "steps": [
                _step(
                    message,
                    excerpt,
                    arguments={"mission_type": 10, "trigger_time": 0, "takeoff_altitude": 10},
                    label="Take off to 10 m",
                )
            ],
        },
        original_message=message,
    )
    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-persian",
        previous_action={"target_drone_ids": ["1"]},
        tool_contracts=_tool_contracts(),
    )

    assert result.accepted
    assert result.draft is not None
    assert result.draft.command_payload["takeoff_altitude"] == 10.0


def test_single_sitl_remove_uses_previous_runtime_target_without_provider_guessing():
    message = "remove the running SITL instance"
    plan = parse_provider_action_plan(
        {
            "summary": "Remove current SITL instance",
            "steps": [
                _step(
                    message,
                    message,
                    tool_id=SITL_ACTION_TOOL_ID,
                    arguments={"action": "remove"},
                    label="Remove the running SITL instance",
                )
            ],
        },
        original_message=message,
    )
    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-remove",
        previous_action={"target_drone_ids": ["1"]},
        tool_contracts=_tool_contracts(),
    )

    assert result.accepted
    assert result.draft is not None
    assert result.draft.arguments == {"action": "remove", "instance_names": ["drone-1"]}
    assert result.draft.ready


def test_mixed_registry_and_flight_plan_fails_closed_until_supported():
    message = "create a SITL instance and take off"
    plan = parse_provider_action_plan(
        {
            "summary": "Create and take off",
            "steps": [
                _step(
                    message,
                    "create a SITL instance",
                    tool_id="mds.sitl.instances.create",
                    arguments={},
                    label="Create SITL instance",
                ),
                _step(
                    message,
                    "take off",
                    arguments={"mission_type": 10, "trigger_time": 0, "takeoff_altitude": 10},
                    condition="after_command_terminal_success",
                    label="Take off",
                ),
            ],
        },
        original_message=message,
    )
    contracts = {
        **_tool_contracts(),
        "mds.sitl.instances.create": {
            "title": "Create SITL instance",
            "intent": "sitl_lifecycle_action",
            "required": (),
        },
    }

    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-mixed",
        previous_action={},
        tool_contracts=contracts,
    )

    assert not result.accepted
    assert result.reason == "unsupported_mixed_sequence"

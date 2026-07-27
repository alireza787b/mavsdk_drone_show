from __future__ import annotations

import json

import pytest

from agent_runtime.action_intent import (
    build_action_draft_from_provider_plan,
    parse_provider_action_plan,
)
from agent_runtime.action_preconditions import assistant_fact_map
from agent_runtime.tool_registry import load_default_tool_registry


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
    source_message_index: int = 0,
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
        "run_after_prior_failure": condition == "after_command_terminal",
        "monitor_requested": monitor_requested,
        "label": label,
        "source_message_index": source_message_index,
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
    source_message_index: int = 0,
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
        "run_after_prior_failure": False,
        "monitor_requested": False,
        "label": f"Wait {seconds:g} seconds",
        "source_message_index": source_message_index,
        "source_start": start,
        "source_end": start + len(excerpt),
        "source_excerpt": excerpt,
    }


def _precondition(
    message: str,
    excerpt: str,
    *,
    fact_id: str = "sitl.running_instance_count",
    operator: str = "eq",
    expected=0,
    label: str = "No SITL instance is running",
) -> dict:
    start = message.index(excerpt)
    return {
        "fact_id": fact_id,
        "arguments_json": "{}",
        "operator": operator,
        "expected_json": json.dumps(expected),
        "label": label,
        "source_message_index": 0,
        "source_start": start,
        "source_end": start + len(excerpt),
        "source_excerpt": excerpt,
    }


def _tool_contracts() -> dict[str, dict]:
    return {
        FLIGHT_TOOL_ID: {
            "title": "Execute curated flight command",
            "intent": "flight_action",
            "monitor_kind": "command",
            "required": ("mission_type", "trigger_time", "target_drone_ids"),
        },
        SITL_ACTION_TOOL_ID: {
            "title": "Run SITL instance lifecycle action",
            "intent": "sitl_lifecycle_action",
            "monitor_kind": "sitl_operation",
            "target_binding": {
                "argument": "instance_names",
                "value_template": "drone-{id}",
            },
            "required": ("action", "instance_names"),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "instance_names"],
                "properties": {
                    "action": {"type": "string", "enum": ["restart", "remove"]},
                    "instance_names": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
    }


def test_provider_plan_materializes_typed_registry_precondition():
    message = "If no SITL instance is running, create one."
    excerpt = "no SITL instance is running"
    plan = parse_provider_action_plan(
        {
            "summary": "Create one SITL instance when none is running",
            "preconditions": [_precondition(message, excerpt)],
            "steps": [
                _step(
                    message,
                    "create one",
                    tool_id="mds.sitl.instances.create",
                    arguments={},
                    label="Create one SITL instance",
                )
            ],
        },
        original_message=message,
    )
    contracts = {
        **_tool_contracts(),
        "mds.sitl.instances.create": {
            "title": "Create SITL instance",
            "intent": "sitl_lifecycle_action",
            "monitor_kind": "sitl_operation",
            "result_target_source": "affected_instances",
            "required": (),
        },
    }

    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-conditional-create",
        previous_action={},
        tool_contracts=contracts,
        fact_contracts=assistant_fact_map(load_default_tool_registry()),
    )

    assert result.accepted
    assert result.draft is not None
    assert result.draft.preconditions[0].public_payload() == {
        "fact_id": "sitl.running_instance_count",
        "arguments": {},
        "operator": "eq",
        "expected": 0,
        "label": "No SITL instance is running",
    }


def test_provider_plan_rejects_unregistered_precondition_fact():
    message = "If no SITL instance is running, create one."
    plan = parse_provider_action_plan(
        {
            "summary": "Create one SITL instance when none is running",
            "preconditions": [
                _precondition(
                    message,
                    "no SITL instance is running",
                    fact_id="unregistered.runtime.fact",
                )
            ],
            "steps": [
                _step(
                    message,
                    "create one",
                    tool_id="mds.sitl.instances.create",
                    arguments={},
                )
            ],
        },
        original_message=message,
    )

    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-invalid-condition",
        previous_action={},
        tool_contracts={
            **_tool_contracts(),
            "mds.sitl.instances.create": {
                "title": "Create SITL instance",
                "intent": "sitl_lifecycle_action",
                "monitor_kind": "sitl_operation",
                "required": (),
            },
        },
        fact_contracts=assistant_fact_map(load_default_tool_registry()),
    )

    assert not result.accepted
    assert result.reason == "invalid_action_precondition"


def test_provider_precondition_source_span_must_match_operator_message():
    message = "If no SITL instance is running, create one."
    condition = _precondition(message, "no SITL instance is running")
    condition["source_excerpt"] = "two SITL instances are running"

    with pytest.raises(ValueError, match="source span does not match"):
        parse_provider_action_plan(
            {
                "summary": "Create one SITL instance when none is running",
                "preconditions": [condition],
                "steps": [
                    _step(
                        message,
                        "create one",
                        tool_id="mds.sitl.instances.create",
                        arguments={},
                    )
                ],
            },
            original_message=message,
        )


def test_provider_precondition_numeric_threshold_must_be_source_grounded():
    message = "If fewer than 2 SITL instances are running, create one."

    with pytest.raises(ValueError, match="not grounded"):
        parse_provider_action_plan(
            {
                "summary": "Create one SITL instance under the threshold",
                "preconditions": [
                    _precondition(
                        message,
                        "fewer than 2 SITL instances are running",
                        operator="lt",
                        expected=3,
                    )
                ],
                "steps": [
                    _step(
                        message,
                        "create one",
                        tool_id="mds.sitl.instances.create",
                        arguments={},
                    )
                ],
            },
            original_message=message,
        )


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
                condition="after_command_terminal_success",
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
    assert result.draft.post_actions[3]["condition"] == "after_command_terminal_success"


def test_provider_plan_requires_explicit_failure_policy_for_recovery_step():
    message = "Take off drone 1 to 10m; even if takeoff fails, still RTL."
    payload = {
        "summary": "Take off, then attempt recovery if needed",
        "steps": [
            _step(
                message,
                "Take off drone 1 to 10m",
                arguments={
                    "mission_type": 10,
                    "trigger_time": 0,
                    "target_drone_ids": ["1"],
                    "takeoff_altitude": 10,
                },
                label="Take off to 10 m",
            ),
            _step(
                message,
                "even if takeoff fails, still RTL",
                arguments={"mission_type": 104, "trigger_time": 0},
                condition="after_command_terminal",
                label="Attempt return to launch",
            ),
        ],
    }

    plan = parse_provider_action_plan(payload, original_message=message)
    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-explicit-recovery",
        previous_action=None,
        tool_contracts=_tool_contracts(),
    )

    assert result.accepted
    assert result.draft is not None
    assert result.draft.post_actions[0]["condition"] == "after_command_terminal"
    assert result.draft.post_actions[0]["wait_condition"] == "command_terminal"


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


def test_provider_plan_uses_explicit_source_message_index_when_wording_repeats():
    message = "take off to 10m"
    payload = {
        "summary": "Take off",
        "steps": [
            _step(
                message,
                message,
                arguments={"mission_type": 10, "trigger_time": 0, "takeoff_altitude": 10},
            )
        ],
    }

    plan = parse_provider_action_plan(
        payload,
        original_message=message,
        grounding_messages=(message,),
    )

    assert plan is not None
    assert plan.steps[0].source_message_index == 0


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


def test_provider_plan_preserves_an_explicit_numeric_sign():
    message = "move drone 1 north -10m"
    payload = {
        "summary": "Move Drone 1",
        "steps": [
            _step(
                message,
                message,
                arguments={
                    "mission_type": 112,
                    "trigger_time": 0,
                    "target_drone_ids": ["1"],
                    "precision_move": {
                        "frame": "ned",
                        "translation_m": {"north": 10, "east": 0, "up": 0},
                    },
                },
            )
        ],
    }

    with pytest.raises(ValueError, match="not grounded"):
        parse_provider_action_plan(payload, original_message=message)


def test_provider_plan_cannot_flip_a_cardinal_direction():
    message = "move drone 1 5m south"
    payload = {
        "summary": "Move Drone 1",
        "steps": [
            _step(
                message,
                "5m south",
                arguments={
                    "mission_type": 112,
                    "trigger_time": 0,
                    "target_drone_ids": ["1"],
                    "precision_move": {
                        "frame": "ned",
                        "translation_m": {"north": 5, "east": 0, "up": 0},
                    },
                },
            )
        ],
    }

    with pytest.raises(ValueError, match="does not match the grounded direction"):
        parse_provider_action_plan(payload, original_message=message)


def test_provider_plan_cannot_reuse_altitude_as_vehicle_target():
    message = "take off to 10m"
    payload = {
        "summary": "Take off",
        "steps": [
            _step(
                message,
                message,
                arguments={
                    "mission_type": 10,
                    "trigger_time": 0,
                    "target_drone_ids": ["10"],
                    "takeoff_altitude": 10,
                },
            )
        ],
    }

    with pytest.raises(ValueError, match="target 10 not grounded"):
        parse_provider_action_plan(payload, original_message=message)


def test_provider_plan_accepts_target_explicitly_bound_to_vehicle_identity():
    message = "take off drone 10 to 10m"
    payload = {
        "summary": "Take off Drone 10",
        "steps": [
            _step(
                message,
                message,
                arguments={
                    "mission_type": 10,
                    "trigger_time": 0,
                    "target_drone_ids": ["10"],
                    "takeoff_altitude": 10,
                },
            )
        ],
    }

    plan = parse_provider_action_plan(payload, original_message=message)

    assert plan is not None


@pytest.mark.parametrize(
    ("message", "excerpt", "target"),
    (
        ("despega el dron 1 a 10 metros", "despega el dron 1 a 10 metros", "1"),
        ("پهپاد ۱ را تا ارتفاع ۱۰ متر بلند کن", "پهپاد ۱ را تا ارتفاع ۱۰ متر بلند کن", "1"),
    ),
)
def test_provider_plan_grounds_explicit_multilingual_target_without_local_aliases(
    message,
    excerpt,
    target,
):
    payload = {
        "summary": "Take off",
        "steps": [
            _step(
                message,
                excerpt,
                arguments={
                    "mission_type": 10,
                    "trigger_time": 0,
                    "target_drone_ids": [target],
                    "takeoff_altitude": 10,
                },
            )
        ],
    }

    plan = parse_provider_action_plan(payload, original_message=message)

    assert plan is not None
    assert plan.steps[0].arguments["target_drone_ids"] == [target]


def test_provider_plan_accepts_typed_context_target_without_parsing_summary_prose():
    message = "send the ready drone on this mission: take off to 10m"
    payload = {
        "summary": "Take off",
        "steps": [
            _step(
                message,
                "take off to 10m",
                arguments={
                    "mission_type": 10,
                    "trigger_time": 0,
                    "target_drone_ids": ["1"],
                    "takeoff_altitude": 10,
                },
            )
        ],
    }

    plan = parse_provider_action_plan(
        payload,
        original_message=message,
        allowed_target_ids=("1",),
    )

    assert plan is not None
    assert plan.steps[0].arguments["target_drone_ids"] == ["1"]


def test_provider_plan_rejects_target_reference_without_exact_identity_source():
    current = "Use the selected drone."
    prior = "Take off to 10m."
    payload = {
        "summary": "Take off",
        "target_references": [
            {
                "target_id": "1",
                "source_message_index": 0,
                "source_start": 0,
                "source_end": len(current),
                "source_excerpt": current,
            }
        ],
        "steps": [
            _step(
                prior,
                prior,
                source_message_index=1,
                arguments={
                    "mission_type": 10,
                    "trigger_time": 0,
                    "target_drone_ids": ["1"],
                    "takeoff_altitude": 10,
                },
            )
        ],
    }

    with pytest.raises(ValueError, match="target_id is not present"):
        parse_provider_action_plan(
            payload,
            original_message=current,
            grounding_messages=(prior,),
        )


def test_provider_plan_rejects_command_id_as_contextual_drone_target():
    message = "land it"
    payload = {
        "summary": "Land the current drone",
        "steps": [
            _step(
                message,
                message,
                arguments={
                    "mission_type": 105,
                    "trigger_time": 0,
                    "target_drone_ids": ["1"],
                },
            )
        ],
    }

    with pytest.raises(ValueError, match="target 1 not grounded"):
        parse_provider_action_plan(
            payload,
            original_message=message,
            grounding_messages=("The prior command id was cmd-1.",),
            allowed_target_ids=("9",),
        )


def test_provider_plan_rejects_self_reported_incomplete_coverage():
    message = "take off drone 1 to 10m"
    payload = {
        "summary": "Take off",
        "coverage_complete": False,
        "steps": [
            _step(
                message,
                message,
                arguments={
                    "mission_type": 10,
                    "trigger_time": 0,
                    "target_drone_ids": ["1"],
                    "takeoff_altitude": 10,
                },
            )
        ],
    }

    with pytest.raises(ValueError, match="incomplete source coverage"):
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


@pytest.mark.parametrize(
    "arguments",
    (
        {"action": "destroy", "instance_names": ["drone-1"]},
        {"action": "remove", "instance_names": ["drone-1"], "unsupported": True},
    ),
)
def test_registry_action_plan_is_schema_validated_before_confirmation(arguments):
    message = "remove SITL instance drone-1"
    plan = parse_provider_action_plan(
        {
            "summary": "Remove current SITL instance",
            "steps": [
                _step(
                    message,
                    message,
                    tool_id=SITL_ACTION_TOOL_ID,
                    arguments=arguments,
                    label="Remove the running SITL instance",
                )
            ],
        },
        original_message=message,
    )

    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-invalid-registry-arguments",
        previous_action={},
        tool_contracts=_tool_contracts(),
    )

    assert not result.accepted
    assert result.reason == "invalid_registry_arguments"


def test_registry_action_runtime_target_binding_ignores_stale_previous_action_target():
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
            "monitor_kind": "sitl_operation",
            "result_target_source": "affected_instances",
            "required": (),
        },
    }

    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-mixed",
        previous_action={"target_drone_ids": ["9"]},
        tool_contracts=contracts,
    )

    assert result.accepted
    assert result.draft is not None
    assert result.draft.tool_id == "mds.sitl.instances.create"
    assert result.draft.wait_condition == "operation_terminal_success"
    assert len(result.draft.post_actions) == 1
    assert result.draft.post_actions[0]["tool_id"] == FLIGHT_TOOL_ID
    assert result.draft.post_actions[0]["target_from_previous_result"] is True
    assert "target_drone_ids" not in result.draft.post_actions[0]["arguments"]


@pytest.mark.parametrize("previous_action", ({}, {"target_drone_ids": ["9"]}))
@pytest.mark.parametrize("lifecycle_action", ("restart", "remove"))
def test_registry_sequence_binds_lifecycle_target_from_created_result(
    previous_action,
    lifecycle_action,
):
    message = f"create a SITL instance and {lifecycle_action} it"
    plan = parse_provider_action_plan(
        {
            "summary": "Create and apply lifecycle action",
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
                    f"{lifecycle_action} it",
                    tool_id=SITL_ACTION_TOOL_ID,
                    arguments={"action": lifecycle_action},
                    condition="after_command_terminal_success",
                    label=f"{lifecycle_action.title()} created instance",
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
            "monitor_kind": "sitl_operation",
            "result_target_source": "affected_instances",
            "required": (),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
    }

    result = build_action_draft_from_provider_plan(
        plan,
        draft_id=f"act-create-{lifecycle_action}",
        previous_action=previous_action,
        tool_contracts=contracts,
    )

    assert result.accepted
    post_action = result.draft.post_actions[0]
    assert post_action["target_from_previous_result"] is True
    assert post_action["target_binding"] == {
        "argument": "instance_names",
        "value_template": "drone-{id}",
    }
    assert post_action["arguments"] == {"action": lifecycle_action}


def test_flight_with_valid_cleanup_cannot_erase_missing_primary_target():
    message = "land, then remove drone-1"
    plan = parse_provider_action_plan(
        {
            "summary": "Land and clean up",
            "steps": [
                _step(
                    message,
                    "land",
                    arguments={"mission_type": 101, "trigger_time": 0},
                    label="Land",
                ),
                _step(
                    message,
                    "remove drone-1",
                    tool_id=SITL_ACTION_TOOL_ID,
                    arguments={"action": "remove", "instance_names": ["drone-1"]},
                    condition="after_command_terminal_success",
                    label="Remove drone-1",
                ),
            ],
        },
        original_message=message,
    )

    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-missing-target",
        previous_action={},
        tool_contracts=_tool_contracts(),
    )

    assert result.accepted
    assert result.draft is not None
    assert not result.draft.ready
    assert result.draft.target_drone_ids == ()
    assert result.draft.missing_arguments == ("target_drone_ids",)
    assert result.draft.command_payload.get("target_drone_ids") is None

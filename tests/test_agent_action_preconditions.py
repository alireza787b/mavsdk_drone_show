from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime.action_preconditions import (
    AssistantFactDefinition,
    assistant_fact_contracts,
    assistant_fact_map,
    evaluate_action_preconditions,
    materialize_action_precondition,
)
from agent_runtime.tool_registry import load_default_tool_registry


def _result(payload=None, *, is_error=False):
    return SimpleNamespace(
        is_error=is_error,
        structured_content=payload,
    )


def test_default_registry_exposes_typed_runtime_facts():
    registry = load_default_tool_registry()

    assert assistant_fact_contracts(registry) == (
        {
            "id": "fleet.targets_ready_to_arm",
            "title": "Target drones ready to arm",
            "value_type": "boolean",
            "operators": ["eq", "ne"],
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["target_drone_ids"],
                "properties": {
                    "target_drone_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 64,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 64,
                        },
                    },
                },
            },
            "target_binding": {
                "argument": "target_drone_ids",
                "value_template": "{id}",
            },
        },
        {
            "id": "sitl.running_instance_count",
            "title": "Running SITL instances",
            "value_type": "integer",
            "operators": ["eq", "gt", "gte", "lt", "lte", "ne"],
            "input_schema": {},
        },
    )


def test_target_scoped_precondition_binds_structured_runtime_target():
    facts = assistant_fact_map(load_default_tool_registry())

    condition = materialize_action_precondition(
        fact_id="fleet.targets_ready_to_arm",
        arguments_json="{}",
        operator="eq",
        expected_json="true",
        label="The selected drone is ready",
        facts=facts,
        runtime_target_ids=("1",),
    )

    assert condition.arguments == {"target_drone_ids": ["1"]}


def test_target_scoped_precondition_requires_runtime_or_explicit_target():
    facts = assistant_fact_map(load_default_tool_registry())

    with pytest.raises(ValueError, match="Missing required argument: target_drone_ids"):
        materialize_action_precondition(
            fact_id="fleet.targets_ready_to_arm",
            arguments_json="{}",
            operator="eq",
            expected_json="true",
            label="The selected drone is ready",
            facts=facts,
        )


@pytest.mark.asyncio
async def test_target_scoped_precondition_reads_exact_bound_targets():
    facts = assistant_fact_map(load_default_tool_registry())
    condition = materialize_action_precondition(
        fact_id="fleet.targets_ready_to_arm",
        arguments_json="{}",
        operator="eq",
        expected_json="true",
        label="The selected drones are ready",
        facts=facts,
        runtime_target_ids=("1", "3"),
    )
    calls = []

    async def read_tool(tool_id, arguments):
        calls.append((tool_id, arguments))
        return _result({"all_targets_ready": True})

    evaluation = await evaluate_action_preconditions(
        (condition,),
        facts=facts,
        read_tool=read_tool,
    )

    assert evaluation.status == "met"
    assert calls == [
        (
            "mds.fleet.action_readiness.read",
            {"target_drone_ids": ["1", "3"]},
        )
    ]


@pytest.mark.asyncio
async def test_precondition_reads_registered_fact_and_compares_scalar():
    facts = assistant_fact_map(load_default_tool_registry())
    condition = materialize_action_precondition(
        fact_id="sitl.running_instance_count",
        arguments_json="{}",
        operator="eq",
        expected_json="0",
        label="No SITL instance is running",
        facts=facts,
    )
    calls = []

    async def read_tool(tool_id, arguments):
        calls.append((tool_id, arguments))
        return _result({"running_instance_count": 0})

    evaluation = await evaluate_action_preconditions(
        (condition,),
        facts=facts,
        read_tool=read_tool,
    )

    assert evaluation.status == "met"
    assert evaluation.observations[0].observed == 0
    assert calls == [("mds.sitl.instances.read", {})]


@pytest.mark.asyncio
async def test_precondition_is_not_met_when_authoritative_fact_changed():
    facts = assistant_fact_map(load_default_tool_registry())
    condition = materialize_action_precondition(
        fact_id="sitl.running_instance_count",
        arguments_json="{}",
        operator="eq",
        expected_json="0",
        label="No SITL instance is running",
        facts=facts,
    )

    async def read_tool(_tool_id, _arguments):
        return _result({"running_instance_count": 1})

    evaluation = await evaluate_action_preconditions(
        (condition,),
        facts=facts,
        read_tool=read_tool,
    )

    assert evaluation.status == "not_met"
    assert evaluation.observations[0].observed == 1


@pytest.mark.asyncio
async def test_precondition_blocks_when_fact_is_unknown():
    facts = assistant_fact_map(load_default_tool_registry())
    condition = materialize_action_precondition(
        fact_id="sitl.running_instance_count",
        arguments_json="{}",
        operator="eq",
        expected_json="0",
        label="No SITL instance is running",
        facts=facts,
    )

    async def read_tool(_tool_id, _arguments):
        return _result({"running_instance_count": None})

    evaluation = await evaluate_action_preconditions(
        (condition,),
        facts=facts,
        read_tool=read_tool,
    )

    assert evaluation.status == "unavailable"
    assert "unavailable" in evaluation.observations[0].detail


def test_precondition_rejects_wrong_expected_type():
    facts = assistant_fact_map(load_default_tool_registry())

    with pytest.raises(ValueError, match="registered integer"):
        materialize_action_precondition(
            fact_id="sitl.running_instance_count",
            arguments_json="{}",
            operator="eq",
            expected_json='"zero"',
            label="No SITL instance is running",
            facts=facts,
        )


def test_precondition_rejects_nonfinite_expected_value():
    facts = assistant_fact_map(load_default_tool_registry())
    number_fact = AssistantFactDefinition(
        id="test.numeric_fact",
        title="Numeric test fact",
        tool_id="mds.sitl.instances.read",
        path=("running_instance_count",),
        value_type="number",
        input_schema={},
    )

    with pytest.raises(ValueError, match="finite"):
        materialize_action_precondition(
            fact_id=number_fact.id,
            arguments_json="{}",
            operator="eq",
            expected_json="NaN",
            label="Invalid threshold",
            facts={**facts, number_fact.id: number_fact},
        )


def test_argumentless_fact_rejects_provider_supplied_read_arguments():
    facts = assistant_fact_map(load_default_tool_registry())

    with pytest.raises(ValueError, match="does not accept read arguments"):
        materialize_action_precondition(
            fact_id="sitl.running_instance_count",
            arguments_json='{"scope": "all"}',
            operator="eq",
            expected_json="0",
            label="No SITL instance is running",
            facts=facts,
        )


@pytest.mark.asyncio
async def test_preconditions_cache_identical_fact_reads():
    facts = assistant_fact_map(load_default_tool_registry())
    conditions = tuple(
        materialize_action_precondition(
            fact_id="sitl.running_instance_count",
            arguments_json="{}",
            operator=operator,
            expected_json=expected,
            label=label,
            facts=facts,
        )
        for operator, expected, label in (
            ("gte", "0", "SITL count is available"),
            ("lt", "2", "Fewer than two SITL instances are running"),
        )
    )
    calls = 0

    async def read_tool(_tool_id, _arguments):
        nonlocal calls
        calls += 1
        return _result({"running_instance_count": 1})

    evaluation = await evaluate_action_preconditions(
        conditions,
        facts=facts,
        read_tool=read_tool,
    )

    assert evaluation.status == "met"
    assert calls == 1


@pytest.mark.asyncio
async def test_definite_false_condition_dominates_unavailable_condition():
    facts = assistant_fact_map(load_default_tool_registry())
    first = materialize_action_precondition(
        fact_id="sitl.running_instance_count",
        arguments_json="{}",
        operator="eq",
        expected_json="0",
        label="No SITL instance is running",
        facts=facts,
    )
    optional_fact = AssistantFactDefinition(
        id="sitl.optional_instance_count",
        title="Optional SITL instance count",
        tool_id="mds.sitl.instances.read",
        path=("optional_instance_count",),
        value_type="integer",
        input_schema={},
    )
    expanded_facts = {**facts, optional_fact.id: optional_fact}
    second = materialize_action_precondition(
        fact_id=optional_fact.id,
        arguments_json="{}",
        operator="gte",
        expected_json="0",
        label="SITL count is available",
        facts=expanded_facts,
    )
    calls = 0

    async def read_tool(_tool_id, _arguments):
        nonlocal calls
        calls += 1
        return _result({"running_instance_count": 1})

    evaluation = await evaluate_action_preconditions(
        (first, second),
        facts=expanded_facts,
        read_tool=read_tool,
    )

    assert evaluation.status == "not_met"
    assert calls == 1

"""Typed, registry-backed preconditions for guarded Simurgh actions."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence

from .models import AgentRuntimeError
from .target_grounding import materialize_target_binding
from .tool_executor import validate_tool_arguments


ACTION_PRECONDITION_OPERATORS = frozenset({"eq", "ne", "lt", "lte", "gt", "gte"})
ACTION_PRECONDITION_MAX_ITEMS = 4
_ORDERED_OPERATORS = frozenset({"lt", "lte", "gt", "gte"})
_SCALAR_TYPES = (bool, int, float, str)


@dataclass(frozen=True)
class AssistantFactDefinition:
    id: str
    title: str
    tool_id: str
    path: tuple[str, ...]
    value_type: str
    input_schema: Mapping[str, Any]
    target_binding: Mapping[str, Any] = field(default_factory=dict)

    def provider_contract(self) -> dict[str, Any]:
        contract = {
            "id": self.id,
            "title": self.title,
            "value_type": self.value_type,
            "operators": sorted(
                ACTION_PRECONDITION_OPERATORS
                if self.value_type in {"integer", "number"}
                else {"eq", "ne"}
            ),
            "input_schema": dict(self.input_schema),
        }
        if self.target_binding:
            contract["target_binding"] = dict(self.target_binding)
        return contract


@dataclass(frozen=True)
class ActionPrecondition:
    fact_id: str
    arguments: Mapping[str, Any]
    operator: str
    expected: bool | int | float | str
    label: str = ""

    def public_payload(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "arguments": dict(self.arguments),
            "operator": self.operator,
            "expected": self.expected,
            "label": self.label,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ActionPrecondition":
        expected = payload.get("expected")
        if not isinstance(expected, _SCALAR_TYPES):
            raise ValueError("stored action precondition expected value must be scalar")
        if isinstance(expected, float) and not math.isfinite(expected):
            raise ValueError("stored action precondition expected value must be finite")
        operator = str(payload.get("operator") or "").strip().lower()
        if operator not in ACTION_PRECONDITION_OPERATORS:
            raise ValueError("stored action precondition operator is unsupported")
        fact_id = str(payload.get("fact_id") or "").strip()
        arguments = payload.get("arguments")
        if not fact_id or not isinstance(arguments, Mapping):
            raise ValueError("stored action precondition fact identity or arguments are incomplete")
        return cls(
            fact_id=fact_id,
            arguments=dict(arguments),
            operator=operator,
            expected=expected,
            label=str(payload.get("label") or "").strip()[:160],
        )


@dataclass(frozen=True)
class ActionPreconditionObservation:
    precondition: ActionPrecondition
    status: str
    observed: bool | int | float | str | None = None
    fact_title: str = ""
    detail: str = ""

    @property
    def met(self) -> bool:
        return self.status == "met"

    def public_payload(self) -> dict[str, Any]:
        return {
            **self.precondition.public_payload(),
            "fact_title": self.fact_title,
            "status": self.status,
            "observed": self.observed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ActionPreconditionEvaluation:
    status: str
    observations: tuple[ActionPreconditionObservation, ...] = ()

    @classmethod
    def not_required(cls) -> "ActionPreconditionEvaluation":
        return cls(status="not_required")

    def public_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "observations": [item.public_payload() for item in self.observations],
        }


def assistant_fact_definitions(registry: Any) -> tuple[AssistantFactDefinition, ...]:
    facts: list[AssistantFactDefinition] = []
    for tool in registry.list_tools():
        for fact_id, raw_fact in (tool.assistant_facts or {}).items():
            facts.append(
                AssistantFactDefinition(
                    id=str(fact_id),
                    title=str(raw_fact["title"]),
                    tool_id=tool.id,
                    path=tuple(str(item) for item in raw_fact["path"]),
                    value_type=str(raw_fact["value_type"]),
                    input_schema=dict(tool.input_schema or {}),
                    target_binding=dict(raw_fact.get("target_binding") or {}),
                )
            )
    return tuple(sorted(facts, key=lambda item: item.id))


def assistant_fact_contracts(registry: Any) -> tuple[dict[str, Any], ...]:
    return tuple(item.provider_contract() for item in assistant_fact_definitions(registry))


def assistant_fact_map(registry: Any) -> dict[str, AssistantFactDefinition]:
    return {item.id: item for item in assistant_fact_definitions(registry)}


def materialize_action_precondition(
    *,
    fact_id: str,
    arguments_json: str,
    operator: str,
    expected_json: str,
    label: str,
    facts: Mapping[str, AssistantFactDefinition],
    runtime_target_ids: Sequence[str] = (),
) -> ActionPrecondition:
    fact = facts.get(str(fact_id or "").strip())
    if fact is None:
        raise ValueError(f"unknown action precondition fact: {fact_id}")
    normalized_operator = str(operator or "").strip().lower()
    allowed_operators = (
        ACTION_PRECONDITION_OPERATORS
        if fact.value_type in {"integer", "number"}
        else {"eq", "ne"}
    )
    if normalized_operator not in allowed_operators:
        raise ValueError(
            f"operator {normalized_operator or '<empty>'} is unsupported for fact {fact.id}"
        )
    try:
        arguments = json.loads(str(arguments_json or "{}"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"arguments_json is invalid for fact {fact.id}") from exc
    if not isinstance(arguments, Mapping):
        raise ValueError(f"arguments_json must decode to an object for fact {fact.id}")
    materialized_arguments = dict(arguments)
    binding_argument, bound_values = materialize_target_binding(
        fact.target_binding,
        runtime_target_ids,
    )
    if (
        binding_argument
        and materialized_arguments.get(binding_argument) in (None, "", [])
        and bound_values
    ):
        materialized_arguments[binding_argument] = bound_values
    if materialized_arguments and not fact.input_schema:
        raise ValueError(f"fact {fact.id} does not accept read arguments")
    schema_error = validate_tool_arguments(
        materialized_arguments,
        dict(fact.input_schema or {}),
    )
    if schema_error:
        raise ValueError(f"invalid read arguments for fact {fact.id}: {schema_error}")
    try:
        expected = json.loads(str(expected_json or ""))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected_json is invalid for fact {fact.id}") from exc
    try:
        _require_fact_value_type(expected, fact.value_type, field_name="expected")
    except TypeError as exc:
        raise ValueError(str(exc)) from exc
    return ActionPrecondition(
        fact_id=fact.id,
        arguments=materialized_arguments,
        operator=normalized_operator,
        expected=expected,
        label=str(label or "").strip()[:160],
    )


async def evaluate_action_preconditions(
    preconditions: Sequence[ActionPrecondition],
    *,
    facts: Mapping[str, AssistantFactDefinition],
    read_tool: Callable[[str, dict[str, Any]], Awaitable[Any]],
) -> ActionPreconditionEvaluation:
    if not preconditions:
        return ActionPreconditionEvaluation.not_required()

    observations: list[ActionPreconditionObservation] = []
    tool_results: dict[tuple[str, str], Any] = {}
    for precondition in preconditions:
        fact = facts.get(precondition.fact_id)
        if fact is None:
            observations.append(
                ActionPreconditionObservation(
                    precondition=precondition,
                    status="unavailable",
                    fact_title=precondition.fact_id,
                    detail="The condition fact is no longer registered.",
                )
            )
            continue
        arguments = dict(precondition.arguments)
        cache_key = (
            fact.tool_id,
            json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str),
        )
        if cache_key not in tool_results:
            try:
                tool_results[cache_key] = await read_tool(fact.tool_id, arguments)
            except Exception as exc:  # pragma: no cover - transport wrappers normally return errors
                tool_results[cache_key] = exc
        result = tool_results[cache_key]
        if isinstance(result, Exception):
            observations.append(
                ActionPreconditionObservation(
                    precondition=precondition,
                    status="unavailable",
                    fact_title=fact.title,
                    detail="The condition source could not be read.",
                )
            )
            continue
        if bool(getattr(result, "is_error", True)):
            observations.append(
                ActionPreconditionObservation(
                    precondition=precondition,
                    status="unavailable",
                    fact_title=fact.title,
                    detail="The condition source returned an error.",
                )
            )
            continue
        structured = getattr(result, "structured_content", None)
        found, observed = _value_at_path(structured, fact.path)
        if not found or observed is None:
            observations.append(
                ActionPreconditionObservation(
                    precondition=precondition,
                    status="unavailable",
                    fact_title=fact.title,
                    detail="The condition value is unavailable.",
                )
            )
            continue
        try:
            _require_fact_value_type(observed, fact.value_type, field_name="observed")
            met = _compare_values(
                observed,
                precondition.expected,
                operator=precondition.operator,
            )
        except (TypeError, ValueError):
            observations.append(
                ActionPreconditionObservation(
                    precondition=precondition,
                    status="unavailable",
                    fact_title=fact.title,
                    detail="The condition value did not match its registered type.",
                )
            )
            continue
        observations.append(
            ActionPreconditionObservation(
                precondition=precondition,
                status="met" if met else "not_met",
                observed=observed,
                fact_title=fact.title,
            )
        )

    if any(item.status == "not_met" for item in observations):
        status = "not_met"
    elif any(item.status == "unavailable" for item in observations):
        status = "unavailable"
    else:
        status = "met"
    return ActionPreconditionEvaluation(status=status, observations=tuple(observations))


def _value_at_path(value: Any, path: Sequence[str]) -> tuple[bool, Any]:
    current = value
    for segment in path:
        if not isinstance(current, Mapping) or segment not in current:
            return False, None
        current = current[segment]
    return True, current


def _require_fact_value_type(value: Any, value_type: str, *, field_name: str) -> None:
    valid = {
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": isinstance(value, str),
    }.get(value_type, False)
    if not valid:
        raise TypeError(f"{field_name} does not match registered {value_type} fact type")
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError(f"{field_name} must be finite")


def _compare_values(observed: Any, expected: Any, *, operator: str) -> bool:
    if operator == "eq":
        return observed == expected
    if operator == "ne":
        return observed != expected
    if operator not in _ORDERED_OPERATORS:
        raise ValueError("unsupported action precondition operator")
    if (
        not isinstance(observed, (int, float))
        or isinstance(observed, bool)
        or not isinstance(expected, (int, float))
        or isinstance(expected, bool)
    ):
        raise TypeError("ordered action preconditions require numeric values")
    if operator == "lt":
        return observed < expected
    if operator == "lte":
        return observed <= expected
    if operator == "gt":
        return observed > expected
    return observed >= expected

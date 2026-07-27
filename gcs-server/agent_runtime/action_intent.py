"""Provider-neutral structured action intent for Simurgh.

Natural language is interpreted by the configured model into this strict,
ordered structure. Local code validates source grounding and tool contracts,
then materializes the existing typed action drafts. Provider prose is never
reparsed as executable English.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.command_contract import SubmitCommandRequest

from .action_planner import (
    ACTION_INTENT,
    ACTION_TOOL_ID,
    ActionDraft,
    FlightActionDraft,
    RegistryActionDraft,
    extract_ned_translation,
    normalize_action_text,
)
from .action_preconditions import (
    ACTION_PRECONDITION_MAX_ITEMS,
    AssistantFactDefinition,
    ActionPrecondition,
    materialize_action_precondition,
)
from .target_grounding import (
    canonical_numeric_token,
    canonical_target_id,
    extract_numeric_tokens,
    materialize_target_binding,
    structured_target_ids,
)
from .tool_executor import validate_tool_arguments


ACTION_PLAN_MAX_STEPS = 32
ACTION_PLAN_MAX_ARGUMENT_CHARS = 12_000
ACTION_TARGET_REFERENCE_MAX_ITEMS = 64
_GENERATED_NUMERIC_ARGUMENT_KEYS = frozenset({"mission_type", "trigger_time"})
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class ProviderActionStep:
    kind: str
    tool_id: str
    arguments: Mapping[str, Any]
    delay_seconds: float | None
    condition: str
    monitor_requested: bool
    label: str
    source_start: int
    source_end: int
    source_excerpt: str
    source_message_index: int = 0

    def public_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tool_id": self.tool_id,
            "arguments": dict(self.arguments),
            "delay_seconds": self.delay_seconds,
            "condition": self.condition,
            "monitor_requested": self.monitor_requested,
            "label": self.label,
            "source_message_index": self.source_message_index,
            "source_start": self.source_start,
            "source_end": self.source_end,
        }


@dataclass(frozen=True)
class ProviderActionPrecondition:
    fact_id: str
    arguments_json: str
    operator: str
    expected_json: str
    label: str
    source_start: int
    source_end: int
    source_excerpt: str
    source_message_index: int = 0


@dataclass(frozen=True)
class ProviderActionTargetReference:
    target_id: str
    source_start: int
    source_end: int
    source_excerpt: str
    source_message_index: int = 0


@dataclass(frozen=True)
class ProviderActionPlan:
    summary: str
    steps: tuple[ProviderActionStep, ...]
    preconditions: tuple[ProviderActionPrecondition, ...] = ()
    target_references: tuple[ProviderActionTargetReference, ...] = ()
    coverage_complete: bool = True

    def public_metadata(self) -> dict[str, Any]:
        return {
            "step_count": len(self.steps),
            "tool_ids": list(dict.fromkeys(step.tool_id for step in self.steps if step.tool_id)),
            "precondition_count": len(self.preconditions),
            "target_reference_count": len(self.target_references),
            "source_grounded": True,
        }


@dataclass(frozen=True)
class ProviderActionDraftResult:
    draft: ActionDraft | None
    reason: str = ""
    field_path: str = ""

    @property
    def accepted(self) -> bool:
        return self.draft is not None


def provider_semantic_rewrite_json_schema() -> dict[str, Any]:
    """Strict Responses API schema for routing plus optional action intent."""

    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    nullable_number = {"anyOf": [{"type": "number"}, {"type": "null"}]}
    nullable_integer = {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]}
    action_step = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": ["tool", "delay"]},
            "tool_id": nullable_string,
            "arguments_json": {"type": "string"},
            "delay_seconds": nullable_number,
            "run_after_prior_failure": {"type": "boolean"},
            "monitor_requested": {"type": "boolean"},
            "label": {"type": "string"},
            "source_message_index": {"type": "integer", "minimum": 0},
            "source_start": {"type": "integer", "minimum": 0},
            "source_end": {"type": "integer", "minimum": 0},
            "source_excerpt": {"type": "string"},
        },
        "required": [
            "kind",
            "tool_id",
            "arguments_json",
            "delay_seconds",
            "run_after_prior_failure",
            "monitor_requested",
            "label",
            "source_message_index",
            "source_start",
            "source_end",
            "source_excerpt",
        ],
    }
    action_plan = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "coverage_complete": {"type": "boolean"},
            "target_references": {
                "type": "array",
                "maxItems": ACTION_TARGET_REFERENCE_MAX_ITEMS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "target_id": {"type": "string"},
                        "source_message_index": {"type": "integer", "minimum": 0},
                        "source_start": {"type": "integer", "minimum": 0},
                        "source_end": {"type": "integer", "minimum": 0},
                        "source_excerpt": {"type": "string"},
                    },
                    "required": [
                        "target_id",
                        "source_message_index",
                        "source_start",
                        "source_end",
                        "source_excerpt",
                    ],
                },
            },
            "preconditions": {
                "type": "array",
                "maxItems": ACTION_PRECONDITION_MAX_ITEMS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "fact_id": {"type": "string"},
                        "arguments_json": {"type": "string"},
                        "operator": {
                            "type": "string",
                            "enum": ["eq", "ne", "lt", "lte", "gt", "gte"],
                        },
                        "expected_json": {"type": "string"},
                        "label": {"type": "string"},
                        "source_message_index": {"type": "integer", "minimum": 0},
                        "source_start": {"type": "integer", "minimum": 0},
                        "source_end": {"type": "integer", "minimum": 0},
                        "source_excerpt": {"type": "string"},
                    },
                    "required": [
                        "fact_id",
                        "arguments_json",
                        "operator",
                        "expected_json",
                        "label",
                        "source_message_index",
                        "source_start",
                        "source_end",
                        "source_excerpt",
                    ],
                },
            },
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": ACTION_PLAN_MAX_STEPS,
                "items": action_step,
            },
        },
        "required": [
            "summary",
            "coverage_complete",
            "target_references",
            "preconditions",
            "steps",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "normalized_message": {"type": "string"},
            "language": {"type": "string"},
            "response_detail": {
                "type": "string",
                "enum": ["brief", "standard", "detailed"],
            },
            "route_hint": {
                "type": "string",
                "enum": [
                    "read_status",
                    "general_question",
                    "draft_sitl_lifecycle_action",
                    "draft_flight_action",
                    "confirm_pending_action",
                    "reject_pending_action",
                    "transform_previous_answer",
                    "clarify",
                ],
            },
            "read_intents": {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string"},
            },
            "read_target_drone_ids": {
                "type": "array",
                "maxItems": 32,
                "items": {"type": "string"},
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": "string"},
            "clarification_reason": {
                "type": "string",
                "enum": ["none", "semantic_ambiguity", "missing_runtime_context"],
            },
            "action_control_explicit": {"type": "boolean"},
            "action_control_source_start": nullable_integer,
            "action_control_source_end": nullable_integer,
            "action_control_source_excerpt": nullable_string,
            "notes": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            "action_plan": {"anyOf": [action_plan, {"type": "null"}]},
        },
        "required": [
            "normalized_message",
            "language",
            "response_detail",
            "route_hint",
            "read_intents",
            "read_target_drone_ids",
            "confidence",
            "needs_clarification",
            "clarification_question",
            "clarification_reason",
            "action_control_explicit",
            "action_control_source_start",
            "action_control_source_end",
            "action_control_source_excerpt",
            "notes",
            "action_plan",
        ],
    }


def parse_provider_action_plan(
    payload: Mapping[str, Any] | None,
    *,
    original_message: str,
    grounding_messages: Sequence[str] = (),
    allowed_target_ids: Sequence[str] = (),
) -> ProviderActionPlan | None:
    """Validate ordered provider intent and exact source-span grounding."""

    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError("action_plan must be an object or null")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= ACTION_PLAN_MAX_STEPS:
        raise ValueError("action_plan.steps must contain between 1 and 32 steps")
    source_messages = tuple(
        message
        for message in (str(original_message or ""), *(str(item or "") for item in grounding_messages))
        if message
    )
    steps: list[ProviderActionStep] = []
    preconditions: list[ProviderActionPrecondition] = []
    target_references: list[ProviderActionTargetReference] = []
    raw_target_references = payload.get("target_references") or []
    if (
        not isinstance(raw_target_references, list)
        or len(raw_target_references) > ACTION_TARGET_REFERENCE_MAX_ITEMS
    ):
        raise ValueError(
            f"action_plan.target_references must contain at most "
            f"{ACTION_TARGET_REFERENCE_MAX_ITEMS} items"
        )
    for index, raw_reference in enumerate(raw_target_references):
        if not isinstance(raw_reference, Mapping):
            raise ValueError(f"action_plan.target_references[{index}] must be an object")
        try:
            source_index = int(raw_reference.get("source_message_index"))
            source_start = int(raw_reference.get("source_start"))
            source_end = int(raw_reference.get("source_end"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"action_plan.target_references[{index}] has invalid source coordinates"
            ) from exc
        if source_index < 0 or source_index >= len(source_messages):
            raise ValueError(
                f"action_plan.target_references[{index}].source_message_index is out of range"
            )
        excerpt = str(raw_reference.get("source_excerpt") or "")
        source_message = source_messages[source_index]
        if not (
            excerpt
            and source_start >= 0
            and source_end > source_start
            and source_end <= len(source_message)
            and source_message[source_start:source_end] == excerpt
        ):
            matches = list(re.finditer(re.escape(excerpt), source_message)) if excerpt else []
            if len(matches) != 1:
                raise ValueError(
                    f"action_plan.target_references[{index}] source span does not match "
                    "its selected operator turn"
                )
            source_start = matches[0].start()
            source_end = matches[0].end()
        target_id = str(raw_reference.get("target_id") or "").strip()
        if not target_id:
            raise ValueError(f"action_plan.target_references[{index}].target_id is required")
        canonical_id = canonical_target_id(target_id)
        if canonical_id:
            if canonical_id not in set(extract_numeric_tokens((excerpt,))):
                raise ValueError(
                    f"action_plan.target_references[{index}].target_id is not present "
                    "in its cited operator text"
                )
        elif target_id.casefold() not in excerpt.casefold():
            raise ValueError(
                f"action_plan.target_references[{index}].target_id is not present "
                "in its cited operator text"
            )
        target_references.append(
            ProviderActionTargetReference(
                target_id=target_id,
                source_message_index=source_index,
                source_start=source_start,
                source_end=source_end,
                source_excerpt=excerpt,
            )
        )
    raw_preconditions = payload.get("preconditions") or []
    if (
        not isinstance(raw_preconditions, list)
        or len(raw_preconditions) > ACTION_PRECONDITION_MAX_ITEMS
    ):
        raise ValueError("action_plan.preconditions must contain at most 4 items")
    for index, raw_precondition in enumerate(raw_preconditions):
        if not isinstance(raw_precondition, Mapping):
            raise ValueError(f"action_plan.preconditions[{index}] must be an object")
        try:
            source_index = int(raw_precondition.get("source_message_index"))
            source_start = int(raw_precondition.get("source_start"))
            source_end = int(raw_precondition.get("source_end"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"action_plan.preconditions[{index}] has invalid source coordinates"
            ) from exc
        excerpt = str(raw_precondition.get("source_excerpt") or "")
        if source_index < 0 or source_index >= len(source_messages):
            raise ValueError(
                f"action_plan.preconditions[{index}].source_message_index is out of range"
            )
        source_message = source_messages[source_index]
        if not (
            excerpt
            and source_start >= 0
            and source_end > source_start
            and source_end <= len(source_message)
            and source_message[source_start:source_end] == excerpt
        ):
            matches = list(re.finditer(re.escape(excerpt), source_message)) if excerpt else []
            if len(matches) != 1:
                raise ValueError(
                    f"action_plan.preconditions[{index}] source span does not match its selected operator turn"
                )
            source_start = matches[0].start()
            source_end = matches[0].end()
        arguments_json = str(raw_precondition.get("arguments_json") or "{}").strip()
        expected_json = str(raw_precondition.get("expected_json") or "").strip()
        try:
            condition_arguments = json.loads(arguments_json)
        except ValueError as exc:
            raise ValueError(
                f"action_plan.preconditions[{index}].arguments_json is invalid JSON"
            ) from exc
        if not isinstance(condition_arguments, Mapping):
            raise ValueError(
                f"action_plan.preconditions[{index}].arguments_json must decode to an object"
            )
        _validate_numeric_source_grounding(
            condition_arguments,
            excerpt=excerpt,
            field_path=f"action_plan.preconditions[{index}].arguments_json",
        )
        if _NUMBER_RE.search(excerpt):
            try:
                expected_for_grounding = json.loads(expected_json)
            except ValueError as exc:
                raise ValueError(
                    f"action_plan.preconditions[{index}].expected_json is invalid JSON"
                ) from exc
            _validate_numeric_source_grounding(
                {"expected": expected_for_grounding},
                excerpt=excerpt,
                field_path=f"action_plan.preconditions[{index}].expected_json",
            )
        preconditions.append(
            ProviderActionPrecondition(
                fact_id=str(raw_precondition.get("fact_id") or "").strip(),
                arguments_json=arguments_json,
                operator=str(raw_precondition.get("operator") or "").strip().lower(),
                expected_json=expected_json,
                label=str(raw_precondition.get("label") or "Action condition").strip()[:160],
                source_message_index=source_index,
                source_start=source_start,
                source_end=source_end,
                source_excerpt=excerpt,
            )
        )
    numeric_source_spans: list[tuple[int, int, int]] = []
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, Mapping):
            raise ValueError(f"action_plan.steps[{index}] must be an object")
        kind = str(raw_step.get("kind") or "").strip().casefold()
        if kind not in {"tool", "delay"}:
            raise ValueError(f"action_plan.steps[{index}].kind is unsupported")
        tool_id = str(raw_step.get("tool_id") or "").strip()
        if kind == "tool" and not tool_id:
            raise ValueError(f"action_plan.steps[{index}].tool_id is required")
        if kind == "delay" and tool_id:
            raise ValueError(f"action_plan.steps[{index}].tool_id must be null for a delay")
        arguments_text = str(raw_step.get("arguments_json") or "{}").strip()
        if len(arguments_text) > ACTION_PLAN_MAX_ARGUMENT_CHARS:
            raise ValueError(f"action_plan.steps[{index}].arguments_json is too large")
        try:
            arguments = json.loads(arguments_text)
        except ValueError as exc:
            raise ValueError(f"action_plan.steps[{index}].arguments_json is invalid JSON") from exc
        if not isinstance(arguments, Mapping):
            raise ValueError(f"action_plan.steps[{index}].arguments_json must decode to an object")
        delay_raw = raw_step.get("delay_seconds")
        delay_seconds: float | None = None
        if kind == "delay":
            try:
                delay_seconds = float(delay_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"action_plan.steps[{index}].delay_seconds is required") from exc
            if delay_seconds <= 0:
                raise ValueError(f"action_plan.steps[{index}].delay_seconds must be positive")
            if arguments:
                raise ValueError(f"action_plan.steps[{index}].arguments_json must be empty for a delay")
        elif delay_raw is not None:
            raise ValueError(f"action_plan.steps[{index}].delay_seconds must be null for a tool")
        run_after_prior_failure = bool(raw_step.get("run_after_prior_failure"))
        if index == 0 and run_after_prior_failure:
            raise ValueError(
                "action_plan.steps[0].run_after_prior_failure cannot be true"
            )
        condition = (
            "start"
            if index == 0
            else "after_command_terminal"
            if run_after_prior_failure
            else "after_command_terminal_success"
        )
        try:
            source_start = int(raw_step.get("source_start"))
            source_end = int(raw_step.get("source_end"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"action_plan.steps[{index}] has invalid source offsets") from exc
        excerpt = str(raw_step.get("source_excerpt") or "")
        try:
            source_index = int(raw_step.get("source_message_index"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"action_plan.steps[{index}].source_message_index is invalid"
            ) from exc
        if source_index < 0 or source_index >= len(source_messages):
            raise ValueError(
                f"action_plan.steps[{index}].source_message_index is out of range"
            )
        source_message = source_messages[source_index]
        exact_span = bool(
            excerpt
            and source_start >= 0
            and source_end > source_start
            and source_end <= len(source_message)
            and source_message[source_start:source_end] == excerpt
        )
        if not exact_span:
            matches = list(re.finditer(re.escape(excerpt), source_message)) if excerpt else []
            if len(matches) != 1:
                raise ValueError(
                    f"action_plan.steps[{index}] source span does not match its selected operator turn"
                )
            source_start = matches[0].start()
            source_end = matches[0].end()
        has_numeric_facts = bool(_numeric_argument_values(arguments)) or delay_seconds is not None
        if has_numeric_facts:
            for prior_source, prior_start, prior_end in numeric_source_spans:
                if prior_source == source_index and source_start < prior_end and prior_start < source_end:
                    raise ValueError(
                        f"action_plan.steps[{index}] must cite its own non-overlapping numeric source clause"
                    )
            numeric_source_spans.append((source_index, source_start, source_end))
        _validate_numeric_source_grounding(
            arguments,
            excerpt=excerpt,
            field_path=f"action_plan.steps[{index}].arguments_json",
        )
        _validate_directional_source_grounding(
            arguments,
            excerpt=excerpt,
            field_path=f"action_plan.steps[{index}].arguments_json",
        )
        if delay_seconds is not None:
            _validate_numeric_source_grounding(
                {"delay_seconds": delay_seconds},
                excerpt=excerpt,
                field_path=f"action_plan.steps[{index}].delay_seconds",
            )
        steps.append(
            ProviderActionStep(
                kind=kind,
                tool_id=tool_id,
                arguments=dict(arguments),
                delay_seconds=delay_seconds,
                condition=condition,
                monitor_requested=bool(raw_step.get("monitor_requested")),
                label=str(raw_step.get("label") or "Action step").strip()[:160] or "Action step",
                source_message_index=source_index,
                source_start=source_start,
                source_end=source_end,
                source_excerpt=excerpt,
            )
        )
    _validate_plan_target_source_grounding(
        steps,
        target_references=target_references,
        allowed_target_ids=allowed_target_ids,
    )
    coverage_complete = payload.get("coverage_complete", True)
    if coverage_complete is not True:
        raise ValueError("action_plan reports incomplete source coverage")
    plan = ProviderActionPlan(
        summary=str(payload.get("summary") or "Operator action plan").strip()[:240],
        steps=tuple(steps),
        preconditions=tuple(preconditions),
        target_references=tuple(target_references),
        coverage_complete=True,
    )
    return plan


def validate_provider_action_plan_source_coverage(
    plan: ProviderActionPlan,
    *,
    original_message: str,
    grounding_messages: Sequence[str] = (),
    allowed_target_ids: Sequence[str] = (),
    tool_contracts: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    """Reject plans that leave numeric facts unused inside their cited clauses.

    The semantic model remains responsible for language and action meaning.
    This validator only checks the model's exact source spans against its typed
    numeric facts, so it works across scripts without maintaining verb aliases.
    """

    if not plan.coverage_complete:
        raise ValueError("action_plan reports incomplete source coverage")
    source_messages = tuple(
        message
        for message in (str(original_message or ""), *(str(item or "") for item in grounding_messages))
        if message
    )
    _validate_plan_target_source_grounding(
        plan.steps,
        target_references=plan.target_references,
        allowed_target_ids=allowed_target_ids,
    )
    cited_spans: dict[tuple[int, int, int], str] = {}
    for item in (*plan.target_references, *plan.preconditions, *plan.steps):
        if item.source_message_index < 0 or item.source_message_index >= len(source_messages):
            raise ValueError("action_plan source_message_index is out of range")
        source = source_messages[item.source_message_index]
        if not (
            item.source_excerpt
            and item.source_start >= 0
            and item.source_end > item.source_start
            and item.source_end <= len(source)
            and source[item.source_start:item.source_end] == item.source_excerpt
        ):
            raise ValueError("action_plan source span does not match its selected operator turn")
        cited_spans.setdefault(
            (item.source_message_index, item.source_start, item.source_end),
            item.source_excerpt,
        )

    source_numbers = {
        canonical_numeric_token(abs(float(token)))
        for excerpt in cited_spans.values()
        for token in extract_numeric_tokens((excerpt,))
    }
    plan_numbers: set[str] = set()

    def add_number(value: object) -> None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return
        key = canonical_numeric_token(abs(numeric))
        if key:
            plan_numbers.add(key)

    for step in plan.steps:
        contract = (tool_contracts or {}).get(step.tool_id, {})
        fixed_cardinality = contract.get("fixed_cardinality")
        if isinstance(fixed_cardinality, int) and not isinstance(fixed_cardinality, bool):
            add_number(fixed_cardinality)
        for target in _argument_target_ids(step.arguments):
            add_number(target)
        for _path, value in _numeric_argument_values(step.arguments):
            add_number(value)
        if step.delay_seconds is not None:
            add_number(step.delay_seconds)
    for target in allowed_target_ids:
        add_number(target)
    for precondition in plan.preconditions:
        try:
            arguments = json.loads(precondition.arguments_json)
            expected = json.loads(precondition.expected_json)
        except ValueError:
            continue
        for _path, value in _numeric_argument_values(arguments):
            add_number(value)
        for _path, value in _numeric_argument_values(expected):
            add_number(value)

    unused = sorted(source_numbers - plan_numbers)
    if unused:
        raise ValueError(
            "action_plan leaves numeric fact(s) unused in cited operator clauses: "
            + ", ".join(unused)
        )


def build_action_draft_from_provider_plan(
    plan: ProviderActionPlan,
    *,
    draft_id: str,
    previous_action: Mapping[str, Any] | None,
    tool_contracts: Mapping[str, Mapping[str, Any]],
    fact_contracts: Mapping[str, AssistantFactDefinition] | None = None,
) -> ProviderActionDraftResult:
    """Materialize a validated provider plan without reparsing provider prose."""

    tool_steps = [step for step in plan.steps if step.kind == "tool"]
    if not tool_steps:
        return ProviderActionDraftResult(None, "missing_tool_step", "steps")
    unknown = [step.tool_id for step in tool_steps if step.tool_id not in tool_contracts]
    if unknown:
        return ProviderActionDraftResult(None, "tool_not_available", f"steps.tool_id:{unknown[0]}")
    preconditions, precondition_error = _materialize_plan_preconditions(
        plan,
        fact_contracts=fact_contracts or {},
        previous_action=previous_action,
    )
    if precondition_error is not None:
        return precondition_error

    if plan.steps[0].kind == "tool" and plan.steps[0].tool_id == ACTION_TOOL_ID:
        return _build_flight_draft(
            plan,
            draft_id=draft_id,
            previous_action=previous_action,
            tool_contracts=tool_contracts,
            preconditions=preconditions,
        )
    return _build_registry_draft(
        plan,
        draft_id=draft_id,
        previous_action=previous_action,
        tool_contracts=tool_contracts,
        preconditions=preconditions,
    )


def _materialize_plan_preconditions(
    plan: ProviderActionPlan,
    *,
    fact_contracts: Mapping[str, AssistantFactDefinition],
    previous_action: Mapping[str, Any] | None,
) -> tuple[tuple[ActionPrecondition, ...], ProviderActionDraftResult | None]:
    runtime_target_ids = structured_target_ids(previous_action)
    values: list[ActionPrecondition] = []
    for index, item in enumerate(plan.preconditions):
        try:
            values.append(
                materialize_action_precondition(
                    fact_id=item.fact_id,
                    arguments_json=item.arguments_json,
                    operator=item.operator,
                    expected_json=item.expected_json,
                    label=item.label,
                    facts=fact_contracts,
                    runtime_target_ids=runtime_target_ids,
                )
            )
        except ValueError as exc:
            return (), ProviderActionDraftResult(
                None,
                "invalid_action_precondition",
                f"preconditions[{index}].{exc}",
            )
    return tuple(values), None


def _build_registry_draft(
    plan: ProviderActionPlan,
    *,
    draft_id: str,
    previous_action: Mapping[str, Any] | None,
    tool_contracts: Mapping[str, Mapping[str, Any]],
    preconditions: tuple[ActionPrecondition, ...],
) -> ProviderActionDraftResult:
    first = plan.steps[0]
    if first.kind != "tool" or first.tool_id == ACTION_TOOL_ID:
        return ProviderActionDraftResult(None, "registry_sequence_must_start_with_tool", "steps[0]")
    contract = tool_contracts[first.tool_id]
    arguments = dict(first.arguments)
    target_binding = contract.get("target_binding")
    binding_argument, _ = materialize_target_binding(target_binding, ())
    if binding_argument and not arguments.get(binding_argument):
        inferred_targets = _previous_target_ids(previous_action)
        if inferred_targets:
            _, bound_values = materialize_target_binding(
                target_binding,
                inferred_targets,
            )
            arguments[binding_argument] = bound_values
    required = tuple(str(item) for item in contract.get("required") or ())
    missing = tuple(name for name in required if arguments.get(name) in (None, "", []))
    schema_error = validate_tool_arguments(
        arguments,
        dict(contract.get("input_schema") or {}),
        allow_missing_required=True,
    )
    if schema_error:
        return ProviderActionDraftResult(
            None,
            "invalid_registry_arguments",
            f"steps[0].{schema_error}",
        )
    monitor_kind = str(contract.get("monitor_kind") or "none")
    if monitor_kind not in {"none", "sitl_operation"}:
        return ProviderActionDraftResult(None, "unsupported_monitor_kind", first.tool_id)

    result_target_source_available = bool(contract.get("result_target_source"))
    initial_targets = _argument_target_ids(arguments)
    if not initial_targets and not result_target_source_available:
        initial_targets = _previous_target_ids(previous_action)
    post_actions, error = _build_sequence_post_actions(
        plan.steps[1:],
        draft_id=draft_id,
        previous_action=previous_action,
        tool_contracts=tool_contracts,
        initial_targets=initial_targets,
        runtime_target_source_available=result_target_source_available,
    )
    if error is not None:
        return error
    return ProviderActionDraftResult(
        RegistryActionDraft(
            draft_id=draft_id,
            tool_id=first.tool_id,
            tool_title=str(contract.get("title") or first.tool_id),
            intent=str(contract.get("intent") or "registry_action"),
            action_label=first.label,
            arguments=arguments,
            missing_arguments=missing,
            monitor_requested=monitor_kind == "sitl_operation",
            wait_condition=(
                "operation_terminal_success"
                if post_actions and monitor_kind == "sitl_operation"
                else "operation_terminal"
                if monitor_kind == "sitl_operation"
                else ""
            ),
            post_actions=post_actions,
            preconditions=preconditions,
        )
    )


def _build_sequence_post_actions(
    steps: Sequence[ProviderActionStep],
    *,
    draft_id: str,
    previous_action: Mapping[str, Any] | None,
    tool_contracts: Mapping[str, Mapping[str, Any]],
    initial_targets: Sequence[str] = (),
    runtime_target_source_available: bool = False,
) -> tuple[tuple[Mapping[str, Any], ...], ProviderActionDraftResult | None]:
    """Materialize an ordered tail without interpreting operator prose."""

    targets = tuple(dict.fromkeys(str(item).strip() for item in initial_targets if str(item).strip()))
    result_targets_pending = bool(runtime_target_source_available and not targets)
    runtime_targets_available = bool(result_targets_pending or targets)
    post_actions: list[Mapping[str, Any]] = []
    for index, step in enumerate(steps, start=2):
        if step.kind == "delay":
            post_actions.append(
                {
                    "type": "delay",
                    "action_label": step.label,
                    "condition": step.condition,
                    "delay_seconds": step.delay_seconds,
                }
            )
            continue
        if step.tool_id == ACTION_TOOL_ID:
            target_context: Mapping[str, Any] | None
            if targets:
                target_context = {"target_drone_ids": list(targets)}
            elif result_targets_pending:
                target_context = None
            else:
                target_context = previous_action
            try:
                arguments = _canonical_flight_payload(
                    step.arguments,
                    draft_id=draft_id,
                    step_index=index,
                    previous_action=target_context,
                )
            except ValueError as exc:
                return (), ProviderActionDraftResult(
                    None,
                    "invalid_flight_payload",
                    f"steps[{index - 1}].{exc}",
                )
            mission_type = int(arguments.get("mission_type") or 0)
            if mission_type not in {10, 101, 104, 112}:
                return (), ProviderActionDraftResult(
                    None,
                    "unsupported_flight_command",
                    f"steps[{index - 1}].mission_type",
                )
            target_from_previous_result = result_targets_pending and not bool(
                arguments.get("target_drone_ids")
            )
            if target_from_previous_result and not runtime_targets_available:
                return (), ProviderActionDraftResult(
                    None,
                    "missing_flight_arguments",
                    f"steps[{index - 1}].target_drone_ids",
                )
            if mission_type == 10 and arguments.get("takeoff_altitude") is None:
                return (), ProviderActionDraftResult(
                    None,
                    "missing_flight_arguments",
                    f"steps[{index - 1}].takeoff_altitude_m",
                )
            if mission_type == 112 and not isinstance(arguments.get("precision_move"), Mapping):
                return (), ProviderActionDraftResult(
                    None,
                    "missing_flight_arguments",
                    f"steps[{index - 1}].precision_move",
                )
            post_action = {
                "type": "flight_command",
                "tool_id": ACTION_TOOL_ID,
                "tool_title": str(
                    tool_contracts[ACTION_TOOL_ID].get("title")
                    or "Execute curated flight command"
                ),
                "action_label": step.label,
                "condition": step.condition,
                "arguments": arguments,
                "monitor_requested": True,
                "wait_condition": (
                    "command_terminal_success"
                    if step.condition == "after_command_terminal_success"
                    else "command_terminal"
                ),
            }
            if target_from_previous_result:
                post_action["target_from_previous_result"] = True
            post_actions.append(post_action)
            explicit_targets = tuple(
                str(item).strip()
                for item in arguments.get("target_drone_ids") or ()
                if str(item).strip()
            )
            if explicit_targets:
                targets = explicit_targets
                result_targets_pending = False
            runtime_targets_available = bool(targets or target_from_previous_result)
            continue

        contract = tool_contracts.get(step.tool_id)
        if not isinstance(contract, Mapping):
            return (), ProviderActionDraftResult(
                None,
                "tool_not_available",
                f"steps[{index - 1}].tool_id",
            )
        arguments = dict(step.arguments)
        target_binding = contract.get("target_binding")
        binding_argument, _ = materialize_target_binding(target_binding, ())
        target_from_previous_result = False
        if binding_argument and not arguments.get(binding_argument):
            inferred_targets = (
                targets
                if targets
                else ()
                if result_targets_pending
                else tuple(_previous_target_ids(previous_action))
            )
            if inferred_targets:
                _, bound_values = materialize_target_binding(
                    target_binding,
                    inferred_targets,
                )
                arguments[binding_argument] = bound_values
            elif result_targets_pending:
                target_from_previous_result = True
        required = tuple(str(item) for item in contract.get("required") or ())
        registry_missing = tuple(
            name
            for name in required
            if arguments.get(name) in (None, "", [])
            and not (target_from_previous_result and name == binding_argument)
        )
        if registry_missing:
            return (), ProviderActionDraftResult(
                None,
                "missing_registry_arguments",
                f"steps[{index - 1}].{registry_missing[0]}",
            )
        schema_error = validate_tool_arguments(
            arguments,
            dict(contract.get("input_schema") or {}),
            allow_missing_required=target_from_previous_result,
        )
        if schema_error:
            return (), ProviderActionDraftResult(
                None,
                "invalid_registry_arguments",
                f"steps[{index - 1}].{schema_error}",
            )
        monitor_kind = str(contract.get("monitor_kind") or "none")
        if monitor_kind not in {"none", "sitl_operation"}:
            return (), ProviderActionDraftResult(
                None,
                "unsupported_monitor_kind",
                f"steps[{index - 1}].tool_id",
            )
        post_action = {
            "type": "registry_action",
            "tool_id": step.tool_id,
            "tool_title": str(contract.get("title") or step.tool_id),
            "action_label": step.label,
            "condition": step.condition,
            "arguments": arguments,
            "monitor_requested": monitor_kind == "sitl_operation",
            "wait_condition": (
                "operation_terminal_success"
                if step.condition == "after_command_terminal_success"
                else "operation_terminal"
            )
            if monitor_kind == "sitl_operation"
            else "",
        }
        result_target_source = str(contract.get("result_target_source") or "")
        if result_target_source:
            post_action["result_target_source"] = result_target_source
        if target_from_previous_result:
            post_action["target_from_previous_result"] = True
            post_action["target_binding"] = dict(target_binding or {})
        post_actions.append(post_action)
        explicit_targets = _argument_target_ids(arguments)
        if explicit_targets:
            targets = tuple(explicit_targets)
            result_targets_pending = False
        if contract.get("result_target_source"):
            targets = ()
            result_targets_pending = True
            runtime_targets_available = True
    return tuple(post_actions), None


def _build_flight_draft(
    plan: ProviderActionPlan,
    *,
    draft_id: str,
    previous_action: Mapping[str, Any] | None,
    tool_contracts: Mapping[str, Mapping[str, Any]],
    preconditions: tuple[ActionPrecondition, ...],
) -> ProviderActionDraftResult:
    first = plan.steps[0]
    if first.kind != "tool" or first.tool_id != ACTION_TOOL_ID:
        return ProviderActionDraftResult(None, "flight_sequence_must_start_with_command", "steps[0]")
    try:
        primary = _canonical_flight_payload(
            first.arguments,
            draft_id=draft_id,
            step_index=1,
            previous_action=previous_action,
        )
    except ValueError as exc:
        return ProviderActionDraftResult(None, "invalid_flight_payload", str(exc))
    mission_type = int(primary.get("mission_type") or 0)
    mission_name = {10: "TAKE_OFF", 101: "LAND", 104: "RETURN_RTL", 112: "PRECISION_MOVE"}.get(mission_type)
    if not mission_name:
        return ProviderActionDraftResult(None, "unsupported_flight_command", "steps[0].mission_type")
    targets = tuple(str(item) for item in primary.get("target_drone_ids") or ())
    primary_missing: list[str] = []
    if not targets:
        primary_missing.append("target_drone_ids")
    if mission_type == 10 and primary.get("takeoff_altitude") is None:
        primary_missing.append("takeoff_altitude_m")
    if mission_type == 112 and not isinstance(primary.get("precision_move"), Mapping):
        primary_missing.append("precision_move")
    post_actions, error = _build_sequence_post_actions(
        plan.steps[1:],
        draft_id=draft_id,
        previous_action=previous_action,
        tool_contracts=tool_contracts,
        initial_targets=targets,
        # A missing primary target is resolved at the existing clarification
        # gate before this immutable sequence can be confirmed.
        runtime_target_source_available=True,
    )
    if error is not None:
        return error
    primary["operator_label"] = f"simurgh:{draft_id}:{mission_name.lower()}"
    return ProviderActionDraftResult(
        FlightActionDraft(
            draft_id=draft_id,
            mission_name=mission_name,
            mission_type=mission_type,
            target_drone_ids=targets,
            command_payload=primary,
            missing_arguments=tuple(primary_missing),
            monitor_requested=True,
            target_inferred_from=(
                _previous_target_source(
                    previous_action,
                    default="provider_plan_local_context",
                )
                if targets and not first.arguments.get("target_drone_ids")
                else ""
            ),
            wait_condition="command_terminal_success" if post_actions else "command_terminal",
            post_actions=post_actions,
            preconditions=preconditions,
        )
    )


def _canonical_flight_payload(
    payload: Mapping[str, Any],
    *,
    draft_id: str,
    step_index: int,
    previous_action: Mapping[str, Any] | None,
) -> dict[str, Any]:
    candidate = dict(payload)
    candidate.pop("idempotency_key", None)
    candidate.pop("operator_label", None)
    if not candidate.get("target_drone_ids"):
        inferred_targets = _previous_target_ids(previous_action)
        if inferred_targets:
            candidate["target_drone_ids"] = inferred_targets
    candidate.setdefault("trigger_time", 0)
    candidate["operator_label"] = f"simurgh:{draft_id}:step:{step_index}"
    try:
        command = SubmitCommandRequest.model_validate(candidate)
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    canonical = command.model_dump(mode="json", exclude_none=True)
    canonical.pop("idempotency_key", None)
    return canonical


def _previous_target_ids(previous_action: Mapping[str, Any] | None) -> list[str]:
    return list(structured_target_ids(previous_action))


def _previous_target_source(
    previous_action: Mapping[str, Any] | None,
    *,
    default: str,
) -> str:
    if not isinstance(previous_action, Mapping):
        return default
    source = str(previous_action.get("target_inferred_from") or "").strip()
    return source or default


def _argument_target_ids(arguments: Mapping[str, Any]) -> list[str]:
    """Extract explicit structured target identities without parsing prose."""

    return list(structured_target_ids(arguments))


def _validate_numeric_source_grounding(
    arguments: Mapping[str, Any],
    *,
    excerpt: str,
    field_path: str,
) -> None:
    """Reject changed numeric facts when the cited source contains digits.

    Language-dependent number words remain a semantic-model responsibility and
    are exposed in the confirmation plan. Digit-bearing operator facts can be
    checked exactly here without maintaining aliases for any language.
    """

    source_numbers = [
        (
            float(match.group(0)),
            match.group(0).startswith(("+", "-")),
        )
        for match in _NUMBER_RE.finditer(excerpt)
    ]
    if not source_numbers:
        return
    for path, value in _numeric_argument_values(arguments):
        normalized = float(value)
        if normalized == 0:
            continue
        if not any(
            (
                abs(normalized - source) <= 1e-9
                if explicit_sign
                else abs(abs(normalized) - abs(source)) <= 1e-9
            )
            for source, explicit_sign in source_numbers
        ):
            raise ValueError(
                f"{field_path}.{path}={value} is not grounded in the cited operator text"
            )


def _validate_directional_source_grounding(
    arguments: Mapping[str, Any],
    *,
    excerpt: str,
    field_path: str,
) -> None:
    """Keep a canonical NED provider payload aligned with its cited direction.

    This guard only runs when the local typed fallback can unambiguously
    interpret the cited excerpt and the provider selected the same NED frame.
    Other languages and frames remain the semantic provider's responsibility;
    they still pass through the typed command schema and human approval gate.
    """

    precision_move = arguments.get("precision_move")
    if not isinstance(precision_move, Mapping):
        return
    frame = str(precision_move.get("frame") or "ned").strip().casefold()
    if frame != "ned":
        return
    source_translation = extract_ned_translation(normalize_action_text(excerpt))
    if not source_translation:
        return
    candidate_translation = precision_move.get("translation_m")
    if not isinstance(candidate_translation, Mapping):
        return
    for axis, expected in source_translation.items():
        if abs(float(expected)) <= 1e-9:
            continue
        try:
            actual = float(candidate_translation.get(axis, 0.0))
        except (TypeError, ValueError):
            raise ValueError(
                f"{field_path}.precision_move.translation_m.{axis} is not numeric"
            ) from None
        if abs(actual - float(expected)) > 1e-9:
            raise ValueError(
                f"{field_path}.precision_move.translation_m.{axis}={actual:g} "
                f"does not match the grounded direction/value {expected:g}"
            )


def _numeric_argument_values(value: Any, *, path: tuple[str, ...] = ()) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text in _GENERATED_NUMERIC_ARGUMENT_KEYS or key_text in {
                "target_drone_ids",
                "instance_names",
            }:
                continue
            values.extend(_numeric_argument_values(item, path=(*path, key_text)))
        return values
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            values.extend(_numeric_argument_values(item, path=(*path, str(index))))
        return values
    if isinstance(value, bool):
        return values
    if isinstance(value, (int, float)):
        values.append((".".join(path) or "value", float(value)))
        return values
    return values


def _validate_plan_target_source_grounding(
    steps: Sequence[ProviderActionStep],
    *,
    target_references: Sequence[ProviderActionTargetReference] = (),
    allowed_target_ids: Sequence[str] = (),
) -> None:
    """Ground model-selected targets without interpreting any human language.

    A target numeral must occur in the bounded operator text. Its occurrence
    cannot simultaneously be reused as an altitude, distance, time, yaw, or
    other numeric fact. Target identity is counted once for the whole ordered
    plan because later steps commonly inherit the same vehicle.
    """

    source_spans: dict[tuple[int, int, int], str] = {}
    for step in steps:
        source_spans.setdefault(
            (step.source_message_index, step.source_start, step.source_end),
            step.source_excerpt,
        )
    # Only model-cited clauses may ground a model-selected identity. Scanning
    # every bounded turn would let unrelated numbers such as ``cmd-1`` become a
    # drone target. Typed runtime targets remain authoritative separately.
    source_messages = tuple(dict.fromkeys(source_spans.values()))
    source_counts = Counter(extract_numeric_tokens(source_messages))
    allowed_numeric_targets = {
        value
        for item in allowed_target_ids
        if (value := canonical_target_id(item))
    }
    allowed_opaque_targets = {
        str(item or "").strip().casefold()
        for item in allowed_target_ids
        if str(item or "").strip() and not canonical_target_id(item)
    }
    referenced_numeric_targets = {
        value
        for item in target_references
        if (value := canonical_target_id(item.target_id))
    }
    referenced_opaque_targets = {
        str(item.target_id or "").strip().casefold()
        for item in target_references
        if str(item.target_id or "").strip() and not canonical_target_id(item.target_id)
    }
    target_keys: dict[str, str] = {}
    opaque_targets: list[str] = []
    for step in steps:
        for key in ("target_drone_ids", "instance_names"):
            raw_values = step.arguments.get(key)
            if not isinstance(raw_values, (list, tuple)):
                continue
            for raw_value in raw_values:
                matches = tuple(_NUMBER_RE.finditer(str(raw_value)))
                if not matches:
                    value = str(raw_value or "").strip()
                    if value and value.casefold() not in opaque_targets:
                        opaque_targets.append(value.casefold())
                    continue
                for match in matches:
                    numeric_key = canonical_numeric_token(match.group(0))
                    if numeric_key:
                        target_keys.setdefault(numeric_key, str(raw_value).strip())

    source_text = "\n".join(str(item or "") for item in source_messages).casefold()
    for target in opaque_targets:
        if (
            target not in allowed_opaque_targets
            and target not in referenced_opaque_targets
            and target not in source_text
        ):
            raise ValueError(f"action_plan target {target} not grounded in operator context")

    measurement_counts: Counter[str] = Counter()
    for step in steps:
        numeric_values = _numeric_argument_values(step.arguments)
        if step.delay_seconds is not None:
            numeric_values.append(("delay_seconds", step.delay_seconds))
        for _path, value in numeric_values:
            numeric_key = canonical_numeric_token(value)
            if numeric_key and numeric_key != "0" and numeric_key in target_keys:
                measurement_counts[numeric_key] += 1

    for numeric_key, raw_target in target_keys.items():
        canonical_target = canonical_target_id(numeric_key)
        if (
            canonical_target in allowed_numeric_targets
            or canonical_target in referenced_numeric_targets
        ):
            continue
        required_occurrences = 1 + measurement_counts[numeric_key]
        if source_counts[numeric_key] < required_occurrences:
            raise ValueError(
                f"action_plan target {raw_target} not grounded independently from measurement values "
                "in operator context"
            )

"""Provider-neutral structured action intent for Simurgh.

Natural language is interpreted by the configured model into this strict,
ordered structure. Local code validates source grounding and tool contracts,
then materializes the existing typed action drafts. Provider prose is never
reparsed as executable English.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from src.command_contract import SubmitCommandRequest

from .action_planner import (
    ACTION_INTENT,
    ACTION_TOOL_ID,
    SITL_BATCH_ACTION_TOOL_ID,
    ActionDraft,
    FlightActionDraft,
    RegistryActionDraft,
)


ACTION_PLAN_MAX_STEPS = 32
ACTION_PLAN_MAX_ARGUMENT_CHARS = 12_000
ACTION_PLAN_CONDITIONS = frozenset(
    {"start", "after_command_terminal_success", "after_command_terminal"}
)
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

    def public_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tool_id": self.tool_id,
            "arguments": dict(self.arguments),
            "delay_seconds": self.delay_seconds,
            "condition": self.condition,
            "monitor_requested": self.monitor_requested,
            "label": self.label,
            "source_start": self.source_start,
            "source_end": self.source_end,
        }


@dataclass(frozen=True)
class ProviderActionPlan:
    summary: str
    steps: tuple[ProviderActionStep, ...]

    def public_metadata(self) -> dict[str, Any]:
        return {
            "step_count": len(self.steps),
            "tool_ids": list(dict.fromkeys(step.tool_id for step in self.steps if step.tool_id)),
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
    action_step = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": ["tool", "delay"]},
            "tool_id": nullable_string,
            "arguments_json": {"type": "string"},
            "delay_seconds": nullable_number,
            "condition": {
                "type": "string",
                "enum": ["start", "after_command_terminal_success", "after_command_terminal"],
            },
            "monitor_requested": {"type": "boolean"},
            "label": {"type": "string"},
            "source_start": {"type": "integer", "minimum": 0},
            "source_end": {"type": "integer", "minimum": 0},
            "source_excerpt": {"type": "string"},
        },
        "required": [
            "kind",
            "tool_id",
            "arguments_json",
            "delay_seconds",
            "condition",
            "monitor_requested",
            "label",
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
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": ACTION_PLAN_MAX_STEPS,
                "items": action_step,
            },
        },
        "required": ["summary", "steps"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "normalized_message": {"type": "string"},
            "language": {"type": "string"},
            "route_hint": {
                "type": "string",
                "enum": [
                    "read_status",
                    "general_question",
                    "draft_sitl_lifecycle_action",
                    "draft_flight_action",
                    "confirm_pending_action",
                    "reject_pending_action",
                    "clarify",
                ],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": "string"},
            "notes": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            "action_plan": {"anyOf": [action_plan, {"type": "null"}]},
        },
        "required": [
            "normalized_message",
            "language",
            "route_hint",
            "confidence",
            "needs_clarification",
            "clarification_question",
            "notes",
            "action_plan",
        ],
    }


def parse_provider_action_plan(
    payload: Mapping[str, Any] | None,
    *,
    original_message: str,
) -> ProviderActionPlan | None:
    """Validate ordered provider intent and exact source-span grounding."""

    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError("action_plan must be an object or null")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= ACTION_PLAN_MAX_STEPS:
        raise ValueError("action_plan.steps must contain between 1 and 32 steps")
    steps: list[ProviderActionStep] = []
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
        condition = str(raw_step.get("condition") or "").strip().casefold()
        if condition not in ACTION_PLAN_CONDITIONS:
            raise ValueError(f"action_plan.steps[{index}].condition is unsupported")
        if index == 0 and condition != "start":
            raise ValueError("action_plan.steps[0].condition must be start")
        if index > 0 and condition == "start":
            raise ValueError(f"action_plan.steps[{index}].condition cannot be start")
        try:
            source_start = int(raw_step.get("source_start"))
            source_end = int(raw_step.get("source_end"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"action_plan.steps[{index}] has invalid source offsets") from exc
        excerpt = str(raw_step.get("source_excerpt") or "")
        supplied_span_matches = bool(
            excerpt
            and source_start >= 0
            and source_end > source_start
            and source_end <= len(original_message)
            and original_message[source_start:source_end] == excerpt
        )
        if not supplied_span_matches:
            matches = [match.start() for match in re.finditer(re.escape(excerpt), original_message)] if excerpt else []
            if len(matches) != 1:
                raise ValueError(f"action_plan.steps[{index}] source span does not match the operator message")
            source_start = matches[0]
            source_end = source_start + len(excerpt)
        _validate_numeric_source_grounding(
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
                source_start=source_start,
                source_end=source_end,
                source_excerpt=excerpt,
            )
        )
    return ProviderActionPlan(
        summary=str(payload.get("summary") or "Operator action plan").strip()[:240],
        steps=tuple(steps),
    )


def build_action_draft_from_provider_plan(
    plan: ProviderActionPlan,
    *,
    draft_id: str,
    previous_action: Mapping[str, Any] | None,
    tool_contracts: Mapping[str, Mapping[str, Any]],
) -> ProviderActionDraftResult:
    """Materialize a validated provider plan without reparsing provider prose."""

    tool_steps = [step for step in plan.steps if step.kind == "tool"]
    if not tool_steps:
        return ProviderActionDraftResult(None, "missing_tool_step", "steps")
    unknown = [step.tool_id for step in tool_steps if step.tool_id not in tool_contracts]
    if unknown:
        return ProviderActionDraftResult(None, "tool_not_available", f"steps.tool_id:{unknown[0]}")

    if all(step.tool_id == ACTION_TOOL_ID for step in tool_steps):
        return _build_flight_draft(plan, draft_id=draft_id, previous_action=previous_action)
    if len(plan.steps) == 1 and tool_steps[0].tool_id != ACTION_TOOL_ID:
        step = tool_steps[0]
        contract = tool_contracts[step.tool_id]
        arguments = dict(step.arguments)
        if step.tool_id == SITL_BATCH_ACTION_TOOL_ID and not arguments.get("instance_names"):
            inferred_targets = _previous_target_ids(previous_action)
            if inferred_targets:
                arguments["instance_names"] = [f"drone-{target}" for target in inferred_targets]
        required = tuple(str(item) for item in contract.get("required") or ())
        missing = tuple(name for name in required if arguments.get(name) in (None, "", []))
        return ProviderActionDraftResult(
            RegistryActionDraft(
                draft_id=draft_id,
                tool_id=step.tool_id,
                tool_title=str(contract.get("title") or step.tool_id),
                intent=str(contract.get("intent") or "registry_action"),
                action_label=step.label,
                arguments=arguments,
                missing_arguments=missing,
                monitor_requested=step.monitor_requested,
            )
        )
    return ProviderActionDraftResult(None, "unsupported_mixed_sequence", "steps")


def _build_flight_draft(
    plan: ProviderActionPlan,
    *,
    draft_id: str,
    previous_action: Mapping[str, Any] | None,
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
    missing: list[str] = []
    if not targets:
        missing.append("target_drone_ids")
    if mission_type == 10 and primary.get("takeoff_altitude") is None:
        missing.append("takeoff_altitude_m")
    if mission_type == 112 and not isinstance(primary.get("precision_move"), Mapping):
        missing.append("precision_move")
    post_actions: list[Mapping[str, Any]] = []
    for index, step in enumerate(plan.steps[1:], start=2):
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
        try:
            arguments = _canonical_flight_payload(
                step.arguments,
                draft_id=draft_id,
                step_index=index,
                previous_action={"target_drone_ids": list(targets)} if targets else previous_action,
            )
        except ValueError as exc:
            return ProviderActionDraftResult(None, "invalid_flight_payload", f"steps[{index - 1}].{exc}")
        post_actions.append(
            {
                "type": "flight_command",
                "tool_id": ACTION_TOOL_ID,
                "tool_title": "Execute curated flight command",
                "action_label": step.label,
                "condition": step.condition,
                "arguments": arguments,
                "monitor_requested": step.monitor_requested,
                "wait_condition": "command_terminal_success"
                if step.condition == "after_command_terminal_success"
                else "command_terminal",
            }
        )
    primary["operator_label"] = f"simurgh:{draft_id}:{mission_name.lower()}"
    return ProviderActionDraftResult(
        FlightActionDraft(
            draft_id=draft_id,
            mission_name=mission_name,
            mission_type=mission_type,
            target_drone_ids=targets,
            command_payload=primary,
            missing_arguments=tuple(missing),
            monitor_requested=first.monitor_requested or bool(post_actions),
            target_inferred_from="provider_plan_local_context" if targets and not first.arguments.get("target_drone_ids") else "",
            wait_condition="command_terminal_success" if post_actions else "command_terminal",
            post_actions=tuple(post_actions),
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
    if not isinstance(previous_action, Mapping):
        return []
    raw = (
        previous_action.get("target_drone_ids")
        or previous_action.get("target_drones")
        or previous_action.get("inferred_target_drone_ids")
    )
    if not isinstance(raw, (list, tuple)):
        return []
    values: list[str] = []
    for item in raw:
        value = str(item).strip()
        if value and value not in values:
            values.append(value)
    return values


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

    source_numbers = [abs(float(match.group(0))) for match in _NUMBER_RE.finditer(excerpt)]
    if not source_numbers:
        return
    for path, value in _numeric_argument_values(arguments):
        normalized = abs(float(value))
        if normalized == 0:
            continue
        if not any(abs(normalized - source) <= 1e-9 for source in source_numbers):
            raise ValueError(
                f"{field_path}.{path}={value} is not grounded in the cited operator text"
            )


def _numeric_argument_values(value: Any, *, path: tuple[str, ...] = ()) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text in _GENERATED_NUMERIC_ARGUMENT_KEYS:
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
    if isinstance(value, str) and any(
        part in {"target_drone_ids", "instance_names"} for part in path
    ):
        for match in _NUMBER_RE.finditer(value):
            values.append((".".join(path), float(match.group(0))))
    return values

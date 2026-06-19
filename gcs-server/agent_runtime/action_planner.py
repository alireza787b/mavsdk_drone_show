"""Guarded action planning helpers for Simurgh chat.

This module deliberately plans against curated command envelopes, not the raw
GCS command endpoint. Runtime policy, final confirmation, and the circuit
breaker remain in the API route/executor layer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

try:  # pragma: no cover - import path differs in direct script/tests
    from .query_adaptation import normalize_operator_query_text
except ImportError:  # pragma: no cover
    from query_adaptation import normalize_operator_query_text


ACTION_TOOL_ID = "mds.flight.command.execute"
ACTION_INTENT = "flight_action"
ACTION_ADAPTER_VERSION = "action-planner-v1"
ACTION_MODEL = "local-action-planner"
SITL_RECONCILE_TOOL_ID = "mds.sitl.fleet.reconcile"
SITL_CREATE_TOOL_ID = "mds.sitl.instances.create"
SITL_BATCH_ACTION_TOOL_ID = "mds.sitl.instances.action"
SITL_ACTION_INTENT = "sitl_lifecycle_action"

_MISSION_TYPES = {
    "TAKE_OFF": 10,
    "LAND": 101,
    "RETURN_RTL": 104,
    "PRECISION_MOVE": 112,
}


@dataclass(frozen=True)
class FlightActionDraft:
    """Operator-visible draft for one curated flight command."""

    draft_id: str
    mission_name: str
    mission_type: int
    target_drone_ids: tuple[str, ...]
    command_payload: Mapping[str, Any]
    missing_arguments: tuple[str, ...] = ()
    monitor_requested: bool = False
    target_inferred_from: str = ""
    wait_condition: str = ""
    post_actions: tuple[Mapping[str, Any], ...] = ()

    @property
    def ready(self) -> bool:
        return not self.missing_arguments

    def public_payload(self) -> dict[str, Any]:
        return {
            "draft_type": ACTION_INTENT,
            "draft_id": self.draft_id,
            "tool_id": ACTION_TOOL_ID,
            "mission_name": self.mission_name,
            "mission_type": self.mission_type,
            "target_drone_ids": list(self.target_drone_ids),
            "command_payload": dict(self.command_payload),
            "missing_arguments": list(self.missing_arguments),
            "monitor_requested": self.monitor_requested,
            "target_inferred_from": self.target_inferred_from,
            "wait_condition": self.wait_condition,
            "post_actions": [dict(item) for item in self.post_actions],
        }

    def to_context_json(self) -> str:
        return json.dumps(self.public_payload(), sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def from_context_json(cls, value: str) -> "FlightActionDraft":
        payload = json.loads(value)
        command_payload = payload.get("command_payload")
        if not isinstance(command_payload, Mapping):
            raise ValueError("stored action draft has no command payload")
        return cls(
            draft_id=str(payload.get("draft_id") or "").strip(),
            mission_name=str(payload.get("mission_name") or "").strip(),
            mission_type=int(payload.get("mission_type") or 0),
            target_drone_ids=tuple(
                str(item).strip() for item in (payload.get("target_drone_ids") or []) if str(item).strip()
            ),
            command_payload=dict(command_payload),
            missing_arguments=tuple(
                str(item).strip() for item in (payload.get("missing_arguments") or []) if str(item).strip()
            ),
            monitor_requested=bool(payload.get("monitor_requested")),
            target_inferred_from=str(payload.get("target_inferred_from") or "").strip(),
            wait_condition=str(payload.get("wait_condition") or "").strip(),
            post_actions=tuple(
                dict(item) for item in (payload.get("post_actions") or []) if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True)
class RegistryActionDraft:
    """Operator-visible draft for one guarded registry-backed GCS action."""

    draft_id: str
    tool_id: str
    tool_title: str
    intent: str
    action_label: str
    arguments: Mapping[str, Any]
    missing_arguments: tuple[str, ...] = ()
    monitor_requested: bool = False

    @property
    def ready(self) -> bool:
        return not self.missing_arguments

    def public_payload(self) -> dict[str, Any]:
        return {
            "draft_type": self.intent,
            "draft_id": self.draft_id,
            "tool_id": self.tool_id,
            "tool_title": self.tool_title,
            "action_label": self.action_label,
            "arguments": dict(self.arguments),
            "missing_arguments": list(self.missing_arguments),
            "monitor_requested": self.monitor_requested,
        }

    def to_context_json(self) -> str:
        return json.dumps(self.public_payload(), sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def from_context_json(cls, value: str) -> "RegistryActionDraft":
        payload = json.loads(value)
        arguments = payload.get("arguments")
        if not isinstance(arguments, Mapping):
            raise ValueError("stored registry action draft has no arguments")
        return cls(
            draft_id=str(payload.get("draft_id") or "").strip(),
            tool_id=str(payload.get("tool_id") or "").strip(),
            tool_title=str(payload.get("tool_title") or "").strip(),
            intent=str(payload.get("draft_type") or "").strip(),
            action_label=str(payload.get("action_label") or "").strip(),
            arguments=dict(arguments),
            missing_arguments=tuple(
                str(item).strip() for item in (payload.get("missing_arguments") or []) if str(item).strip()
            ),
            monitor_requested=bool(payload.get("monitor_requested")),
        )


ActionDraft = FlightActionDraft | RegistryActionDraft


def action_draft_from_context_json(value: str) -> ActionDraft:
    payload = json.loads(value)
    draft_type = str(payload.get("draft_type") or ACTION_INTENT).strip()
    if draft_type == ACTION_INTENT:
        return FlightActionDraft.from_context_json(value)
    return RegistryActionDraft.from_context_json(value)


def normalize_action_text(message: str) -> str:
    return re.sub(r"\s+", " ", normalize_operator_query_text(message).strip().lower())


def is_action_confirmation_message(message: str, *, draft_id: str | None = None) -> bool:
    normalized = normalize_action_text(message)
    if not normalized:
        return False
    if draft_id and str(draft_id).lower() in normalized:
        return bool(re.search(r"\b(confirm|approve|execute|send|run|go ahead|yes)\b", normalized))
    return bool(
        re.search(
            r"\b(confirm|approved|approve|yes|go ahead|execute it|send it|run it|do it|confirmed)\b",
            normalized,
        )
    )


def is_action_rejection_message(message: str, *, draft_id: str | None = None) -> bool:
    normalized = normalize_action_text(message)
    if not normalized:
        return False
    if draft_id and str(draft_id).lower() in normalized:
        return bool(re.search(r"\b(cancel|reject|deny|discard|do not|don't|stop)\b", normalized))
    return bool(
        re.search(
            r"\b(cancel action|reject action|deny action|discard action|do not execute|don't execute|stop this action)\b",
            normalized,
        )
    )


def looks_like_action_replay_request(message: str) -> bool:
    normalized = normalize_action_text(message)
    if not normalized:
        return False
    return bool(
        re.search(
            r"\b(read\s+again|do\s+the\s+job|do\s+what\s+i\s+asked|previous\s+request|last\s+request|that\s+sequence|same\s+sequence|plan\s+that|try\s+again)\b",
            normalized,
        )
    )


def looks_like_direct_flight_action_request(message: str) -> bool:
    normalized = normalize_action_text(message)
    if not normalized:
        return False
    if _looks_conceptual(normalized):
        return False
    has_action = bool(
        re.search(r"\b(take\s*off|takeoff|land|rtl|return\s+to\s+launch|return\s+home)\b", normalized)
        or _looks_like_precision_move(normalized)
    )
    if not has_action:
        return False
    has_direct_verb = bool(re.search(r"\b(send|execute|run|start|command|make|put|tell)\b", normalized))
    has_target = bool(_extract_target_ids(normalized))
    has_implicit_target = bool(
        re.search(r"\b(the\s+drone|this\s+drone|that\s+drone|same\s+drone|it|them|vehicle|aircraft)\b", normalized)
    )
    has_imperative_motion = bool(
        re.search(r"\b(now|then|after|wait|move|go|fly|jog|climb|descend)\b", normalized)
        or _extract_takeoff_altitude_m(normalized) is not None
        or _extract_precision_move_payload(normalized) is not None
    )
    return has_direct_verb or has_target or has_implicit_target or has_imperative_motion


def looks_like_flight_followup_action_request(message: str, *, conversation_topic: str | None = None) -> bool:
    normalized = normalize_action_text(message)
    topic = str(conversation_topic or "").strip().lower()
    if topic != "flight":
        return False
    if _looks_conceptual(normalized):
        return False
    if _extract_mission_name(normalized):
        return True
    return bool(
        re.search(r"\b(landed|disarmed|cleanup|clean\s+up|remove|delete|destroy|rtl|return\s+home)\b", normalized)
    )


def _looks_like_sitl_context_term(normalized: str, *, conversation_topic: str | None = None) -> bool:
    topic = str(conversation_topic or "").strip().lower()
    if topic == "sitl":
        return True
    return bool(re.search(r"\b(sitl|sim|simulation|simulator|container|containers|docker)\b", normalized))


def _looks_like_sitl_lifecycle_target(normalized: str) -> bool:
    if re.search(
        r"\b(drone|drones|droen|droens|instance|instances|instace|instaces|isntance|isntances|container|containers)\b",
        normalized,
    ):
        return True
    # Operators often use "SITL" as shorthand for "a SITL instance/container".
    # Keep this behind the lifecycle-verb gate in looks_like_direct_sitl_lifecycle_request
    # so conceptual prompts such as "what is SITL" still route as help.
    return bool(re.search(r"\bsitl\b", normalized))


def looks_like_direct_sitl_lifecycle_request(message: str, *, conversation_topic: str | None = None) -> bool:
    normalized = normalize_action_text(message)
    if not normalized:
        return False
    if _looks_conceptual(normalized):
        return False
    if not _looks_like_sitl_context_term(normalized, conversation_topic=conversation_topic):
        return False
    if not re.search(
        r"\b(create|build|start|spawn|launch|prepare|reconcile|make|set\s*up|setup|restart|reboot|remove|delete|destroy|clear)\b",
        normalized,
    ):
        return False
    return _looks_like_sitl_lifecycle_target(normalized)


def build_flight_action_draft(
    message: str,
    *,
    draft_id: str,
    previous_action: Mapping[str, Any] | None = None,
) -> FlightActionDraft | None:
    normalized = normalize_action_text(message)
    mission_name = _extract_mission_name(normalized)
    if not mission_name:
        return None

    target_drone_ids = tuple(_extract_target_ids(normalized))
    target_inferred_from = ""
    if not target_drone_ids and _allows_previous_target_inference(normalized):
        inferred = _previous_target_ids(previous_action)
        if inferred:
            target_drone_ids = tuple(inferred)
            target_inferred_from = "previous_submitted_action"
    if not target_drone_ids and _allows_single_previous_target_inference(normalized):
        inferred = _previous_target_ids(previous_action)
        if len(inferred) == 1:
            target_drone_ids = tuple(inferred)
            target_inferred_from = "single_previous_action_target"
    missing: list[str] = []
    if not target_drone_ids:
        missing.append("target_drone_ids")

    payload: dict[str, Any] = {
        "mission_type": _MISSION_TYPES[mission_name],
        "trigger_time": 0,
        "operator_label": f"simurgh:{draft_id}:{mission_name.lower()}",
    }
    if target_drone_ids:
        payload["target_drone_ids"] = list(target_drone_ids)

    if mission_name == "TAKE_OFF":
        altitude = _extract_takeoff_altitude_m(normalized)
        if altitude is None:
            missing.append("takeoff_altitude_m")
        else:
            payload["takeoff_altitude"] = altitude
    elif mission_name == "PRECISION_MOVE":
        precision_move = _extract_precision_move_payload(normalized)
        if precision_move is None:
            missing.append("precision_move")
        else:
            payload["precision_move"] = precision_move

    monitor_requested = _flight_monitor_requested(normalized)
    post_actions = tuple(
        _build_post_actions(
            normalized,
            target_drone_ids,
            mission_name=mission_name,
            draft_id=draft_id,
        )
    )
    wait_condition = ""
    if post_actions:
        wait_condition = "command_terminal_success"
        monitor_requested = True
    elif monitor_requested:
        wait_condition = "command_terminal"

    return FlightActionDraft(
        draft_id=draft_id,
        mission_name=mission_name,
        mission_type=_MISSION_TYPES[mission_name],
        target_drone_ids=target_drone_ids,
        command_payload=payload,
        missing_arguments=tuple(missing),
        monitor_requested=monitor_requested,
        target_inferred_from=target_inferred_from,
        wait_condition=wait_condition,
        post_actions=post_actions,
    )


def _flight_monitor_requested(normalized: str) -> bool:
    return bool(
        re.search(
            r"\b(report|monitor|tell me|when done|until done|status|progress|wait|once|after|landed|disarmed)\b",
            normalized,
        )
    )


def _allows_previous_target_inference(normalized: str) -> bool:
    return bool(
        re.search(
            r"\b(the\s+drone|this\s+drone|that\s+drone|same\s+drone|only\s+(?:one\s+)?drone|it|them|just\s+took\s*off|tooked\s*off|previous|last)\b",
            normalized,
        )
    )


def _allows_single_previous_target_inference(normalized: str) -> bool:
    if re.search(r"\b(all|every|both|multiple|several)\s+(?:drone|drones|vehicle|vehicles)\b", normalized):
        return False
    if _extract_target_ids(normalized):
        return False
    return bool(_extract_mission_name(normalized))


def _previous_target_ids(previous_action: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(previous_action, Mapping):
        return []
    raw_targets = (
        previous_action.get("target_drone_ids")
        or previous_action.get("target_drones")
        or previous_action.get("inferred_target_drone_ids")
    )
    if not isinstance(raw_targets, (list, tuple)):
        return []
    values: list[str] = []
    for item in raw_targets:
        value = str(item).strip()
        if value and value not in values:
            values.append(value)
    return values


def _build_post_actions(
    normalized: str,
    target_drone_ids: tuple[str, ...],
    *,
    mission_name: str,
    draft_id: str,
) -> list[Mapping[str, Any]]:
    actions: list[Mapping[str, Any]] = []
    if mission_name == "TAKE_OFF" and target_drone_ids:
        delay_seconds = _extract_wait_seconds(normalized)
        precision_move = _extract_precision_move_payload(normalized)
        if precision_move is not None and re.search(r"\b(?:then|after|and then|wait)\b", normalized):
            if delay_seconds:
                actions.append(
                    {
                        "type": "delay",
                        "action_label": f"wait {delay_seconds:g} second(s)",
                        "condition": "after_command_terminal_success",
                        "delay_seconds": delay_seconds,
                    }
                )
            actions.append(
                {
                    "type": "flight_command",
                    "tool_id": ACTION_TOOL_ID,
                    "tool_title": "Execute curated flight command",
                    "action_label": "precision move",
                    "condition": "after_command_terminal_success",
                    "arguments": {
                        "mission_type": _MISSION_TYPES["PRECISION_MOVE"],
                        "trigger_time": 0,
                        "target_drone_ids": list(target_drone_ids),
                        "precision_move": precision_move,
                        "operator_label": f"simurgh:{draft_id}:precision_move",
                    },
                    "monitor_requested": True,
                    "wait_condition": "command_terminal_success",
                }
            )
        if _looks_like_rtl(normalized) and re.search(r"\b(?:then|after|and then|return|rtl)\b", normalized):
            actions.append(_flight_command_post_action(draft_id, target_drone_ids, "RETURN_RTL"))
    elif mission_name == "PRECISION_MOVE" and target_drone_ids:
        if _looks_like_rtl(normalized) and re.search(r"\b(?:then|after|and then|return|rtl)\b", normalized):
            actions.append(_flight_command_post_action(draft_id, target_drone_ids, "RETURN_RTL"))
    if mission_name != "LAND":
        return actions
    if not target_drone_ids:
        return actions
    if not re.search(r"\b(clean\s*up|cleanup|remove|delete|destroy|stop)\b", normalized):
        return actions
    if not re.search(r"\b(sitl|sim|simulation|instance|instances|instace|instaces|container|containers)\b", normalized):
        return actions
    instance_names = [f"drone-{target}" for target in target_drone_ids if str(target).strip().isdigit()]
    if not instance_names:
        return actions
    actions.append(
        {
            "type": "registry_action",
            "tool_id": SITL_BATCH_ACTION_TOOL_ID,
            "tool_title": "Run SITL instance lifecycle action",
            "action_label": "remove SITL instance(s)",
            "condition": "after_command_terminal_success",
            "arguments": {
                "action": "remove",
                "instance_names": instance_names,
            },
        }
    )
    return actions


def _flight_command_post_action(
    draft_id: str,
    target_drone_ids: tuple[str, ...],
    mission_name: str,
) -> Mapping[str, Any]:
    label = {
        "RETURN_RTL": "return rtl",
        "LAND": "land",
        "TAKE_OFF": "takeoff",
        "PRECISION_MOVE": "precision move",
    }.get(mission_name, mission_name.lower())
    return {
        "type": "flight_command",
        "tool_id": ACTION_TOOL_ID,
        "tool_title": "Execute curated flight command",
        "action_label": label,
        "condition": "after_command_terminal_success",
        "arguments": {
            "mission_type": _MISSION_TYPES[mission_name],
            "trigger_time": 0,
            "target_drone_ids": list(target_drone_ids),
            "operator_label": f"simurgh:{draft_id}:{mission_name.lower()}",
        },
        "monitor_requested": True,
        "wait_condition": "command_terminal_success",
    }


def build_sitl_reconcile_action_draft(
    message: str,
    *,
    draft_id: str,
    conversation_topic: str | None = None,
) -> RegistryActionDraft | None:
    normalized = normalize_action_text(message)
    if not looks_like_direct_sitl_lifecycle_request(normalized, conversation_topic=conversation_topic):
        return None

    batch_action = _extract_sitl_batch_action(normalized)
    if batch_action:
        instance_names = _extract_sitl_instance_names(normalized)
        missing: list[str] = []
        if not instance_names:
            missing.append("instance_names")
        return RegistryActionDraft(
            draft_id=draft_id,
            tool_id=SITL_BATCH_ACTION_TOOL_ID,
            tool_title="Run SITL instance lifecycle action",
            intent=SITL_ACTION_INTENT,
            action_label=f"{batch_action} SITL instance(s)",
            arguments={
                "action": batch_action,
                "instance_names": instance_names,
            },
            missing_arguments=tuple(missing),
            monitor_requested=_sitl_monitor_requested(normalized),
        )

    target_count = _extract_sitl_target_count(normalized)
    missing: list[str] = []
    if _looks_like_single_sitl_create(normalized, target_count):
        instance_id = _extract_explicit_sitl_instance_id(normalized)
        arguments = {
            "git_sync_enabled": True,
            "requirements_sync_enabled": True,
        }
        if instance_id is not None:
            arguments["instance_id"] = instance_id
            arguments["ip_last_octet"] = instance_id + 1
        return RegistryActionDraft(
            draft_id=draft_id,
            tool_id=SITL_CREATE_TOOL_ID,
            tool_title="Create SITL instance",
            intent=SITL_ACTION_INTENT,
            action_label="create SITL instance",
            arguments=arguments,
            missing_arguments=(),
            monitor_requested=_sitl_monitor_requested(normalized),
        )

    arguments = {
        "start_id": 1,
        "start_ip": 2,
        "git_sync_enabled": True,
        "requirements_sync_enabled": True,
    }
    if target_count is None:
        missing.append("target_count")
    else:
        arguments["target_count"] = target_count

    return RegistryActionDraft(
        draft_id=draft_id,
        tool_id=SITL_RECONCILE_TOOL_ID,
        tool_title="Reconcile SITL fleet",
        intent=SITL_ACTION_INTENT,
        action_label="reconcile SITL fleet",
        arguments=arguments,
        missing_arguments=tuple(missing),
        monitor_requested=_sitl_monitor_requested(normalized),
    )


def _extract_sitl_batch_action(normalized: str) -> str | None:
    if re.search(r"\b(restart|reboot)\b", normalized):
        return "restart"
    if re.search(r"\b(remove|delete|destroy|clear)\b", normalized):
        return "remove"
    return None


def _sitl_monitor_requested(normalized: str) -> bool:
    return bool(re.search(r"\b(report|monitor|tell me|when done|until done|status|progress|ready|created|finished|done)\b", normalized))


def _looks_like_single_sitl_create(normalized: str, target_count: int | None) -> bool:
    if not re.search(r"\b(create|build|start|spawn|launch|prepare|make|set\s*up|setup)\b", normalized):
        return False
    if re.search(r"\b(reconcile|fleet|all)\b", normalized):
        return False
    if target_count not in (None, 1):
        return False
    if re.search(r"\b(?:drones|droens|instances|instaces|isntances|containers)\b", normalized) and target_count != 1:
        return False
    if _implies_single_sitl_instance(normalized):
        return True
    return bool(re.search(r"\b(?:drone|droen|instance|instace|isntance|container)\b", normalized))


def _implies_single_sitl_instance(normalized: str) -> bool:
    return bool(re.search(r"\b(?:1|one|single|a|an)\s+sitl\b", normalized))


def _extract_explicit_sitl_instance_id(normalized: str) -> int | None:
    for pattern in (
        r"\b(?:drone|droen|instance|instace|isntance|container)\s*[-#]?\s*(?P<id>\d{1,3})\b",
        r"\b(?:id|hw|hardware)\s*[-#:=]?\s*(?P<id>\d{1,3})\b",
    ):
        match = re.search(pattern, normalized)
        if match:
            value = int(match.group("id"))
            return value if 1 <= value <= 999 else None
    return None


def _extract_sitl_instance_names(normalized: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"\bdrone[-\s]*(?P<id>\d{1,3})\b", normalized):
        value = int(match.group("id"))
        name = f"drone-{value}"
        if 1 <= value <= 999 and name not in values:
            values.append(name)
    for match in re.finditer(
        r"\b(?:instance|container|instances|containers)\s+(?P<ids>\d+(?:\s*(?:,|and|&|\+|\s)\s*\d+)*)",
        normalized,
    ):
        for item in re.findall(r"\d+", match.group("ids")):
            value = int(item)
            name = f"drone-{value}"
            if 1 <= value <= 999 and name not in values:
                values.append(name)
    return values


def _looks_conceptual(normalized: str) -> bool:
    instructional = (
        "how to",
        "how do i",
        "guide",
        "doc",
        "docs",
        "instruction",
        "instructions",
        "explain",
    )
    explicit_execution = ("send", "execute", "run", "command", "do it", "go ahead")
    if any(term in normalized for term in instructional) and not any(
        term in normalized for term in explicit_execution
    ):
        return True
    conceptual = (
        "what is",
        "what are",
        "difference",
        "different",
        "compare",
        "mode",
        "modes",
        "workflow",
        "guide",
        "doc",
        "docs",
        "how to",
        "how do i",
        "can you explain",
    )
    direct = ("send", "execute", "run", "start", "command", "do it", "go ahead")
    return any(term in normalized for term in conceptual) and not any(term in normalized for term in direct)


def _extract_mission_name(normalized: str) -> str | None:
    if re.search(r"\b(take\s*off|takeoff)\b", normalized):
        return "TAKE_OFF"
    if re.search(r"\bland\b", normalized):
        return "LAND"
    if _looks_like_precision_move(normalized):
        return "PRECISION_MOVE"
    if _looks_like_rtl(normalized):
        return "RETURN_RTL"
    return None


def _looks_like_rtl(normalized: str) -> bool:
    return bool(re.search(r"\b(rtl|return\s+to\s+launch|return\s+home|rtl\s+back|return\s+back)\b", normalized))


def _looks_like_precision_move(normalized: str) -> bool:
    if not re.search(r"\b(move|go|fly|jog|translate|climb|descend|yaw)\b", normalized):
        return False
    if _extract_precision_move_payload(normalized) is not None:
        return True
    return bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:m|meter|meters)\b", normalized))


def _extract_wait_seconds(normalized: str) -> float | None:
    match = re.search(
        r"\bwait(?:\s+(?:there|here))?(?:\s+for)?(?:\s+about|\s+around)?\s+(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>s|sec|secs|second|seconds|m|min|minute|minutes)\b(?:\s+(?:there|here))?",
        normalized,
    )
    if not match:
        return None
    value = float(match.group("value"))
    unit = match.group("unit")
    if unit.startswith("m"):
        return value * 60.0
    return value


def _extract_precision_move_payload(normalized: str) -> dict[str, Any] | None:
    translation = _extract_ned_translation(normalized)
    yaw = _extract_yaw_payload(normalized)
    if not translation and yaw is None:
        return None
    payload: dict[str, Any] = {
        "frame": "ned",
        "translation_m": {
            "north": float(translation.get("north", 0.0)),
            "east": float(translation.get("east", 0.0)),
            "up": float(translation.get("up", 0.0)),
        },
    }
    if yaw is not None:
        payload["yaw"] = yaw
    return payload


def _extract_ned_translation(normalized: str) -> dict[str, float]:
    values = {"north": 0.0, "east": 0.0, "up": 0.0}
    matched = False
    direction_map = {
        "north": ("north", 1.0),
        "south": ("north", -1.0),
        "east": ("east", 1.0),
        "west": ("east", -1.0),
        "up": ("up", 1.0),
        "higher": ("up", 1.0),
        "climb": ("up", 1.0),
        "down": ("up", -1.0),
        "lower": ("up", -1.0),
        "descend": ("up", -1.0),
    }
    for match in re.finditer(
        r"\b(?:(?P<verb>climb|descend)\s+)?(?P<value>\d+(?:\.\d+)?)\s*(?:m|meter|meters)(?:\s+(?:to\s+the|to|towards|toward))?\s*(?P<direction>north|south|east|west|up|down|higher|lower)?\b",
        normalized,
    ):
        verb = str(match.group("verb") or "").strip()
        direction = str(match.group("direction") or verb or "").strip()
        if not direction:
            continue
        axis_sign = direction_map.get(direction)
        if axis_sign is None:
            continue
        axis, sign = axis_sign
        values[axis] += float(match.group("value")) * sign
        matched = True
    return values if matched else {}


def _extract_yaw_payload(normalized: str) -> dict[str, Any] | None:
    match = re.search(r"\byaw\s+(?:to|at)?\s*(?P<value>-?\d+(?:\.\d+)?)\s*(?:deg|degree|degrees)?\b", normalized)
    if not match:
        return None
    degrees = float(match.group("value")) % 360.0
    return {"mode": "absolute_heading", "degrees": degrees}


def _extract_sitl_target_count(normalized: str) -> int | None:
    for pattern in (
        r"\b(?P<count>\d{1,2})\s+sitl\b",
        r"\b(?P<count>\d{1,2})\s+(?:sitl\s+)?(?:drone|drones|droen|droens|instance|instances|instace|instaces|isntance|isntances|container|containers)\b",
        r"\b(?:drone|drones|droen|droens|instance|instances|instace|instaces|isntance|isntances|container|containers)\s+(?P<count>\d{1,2})\b",
        r"\b(?:target|count|fleet)\s+(?:to|of|=)?\s*(?P<count>\d{1,2})\b",
    ):
        match = re.search(pattern, normalized)
        if match:
            value = int(match.group("count"))
            return value if 1 <= value <= 50 else None
    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    for word, value in number_words.items():
        if re.search(rf"\b{word}\s+sitl\b", normalized):
            return value
        if re.search(
            rf"\b{word}\s+(?:sitl\s+)?(?:drone|drones|droen|droens|instance|instances|instace|instaces|isntance|isntances|container|containers)\b",
            normalized,
        ):
            return value
    if re.search(r"\b(?:a|an|single)\s+sitl\b", normalized):
        return 1
    return None


def _extract_target_ids(normalized: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(
        r"\b(?:drone|drones|hw|vehicle|vehicles)\s+(?P<ids>\d+(?:\s*(?:,|and|&|\+|\s)\s*\d+)*)",
        normalized,
    ):
        for item in re.findall(r"\d+", match.group("ids")):
            if item not in values:
                values.append(item)
    return values


def _extract_takeoff_altitude_m(normalized: str) -> float | None:
    patterns = (
        r"\b(?:take\s*off|takeoff)\b(?:(?!\b(?:then|and then)\b).){0,80}?\b(?:to|at|altitude|height)\s*(?P<value>\d+(?:\.\d+)?)\s*(?:m|meter|meters)\b",
        r"\b(?:take\s*off|takeoff)\s+(?P<value>\d+(?:\.\d+)?)\s*(?:m|meter|meters)\b",
        r"\b(?P<value>\d+(?:\.\d+)?)\s*(?:m|meter|meters)\b.{0,40}?\b(?:take\s*off|takeoff)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return float(match.group("value"))
    return None

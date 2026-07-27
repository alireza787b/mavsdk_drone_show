"""YAML-backed curated tool registry for Simurgh Operator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import yaml

from .models import AgentRuntimeError, ToolDefinition, ToolExposure, ToolRiskClass


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOL_REGISTRY_PATH = REPO_ROOT / "config" / "agent_tools.yaml"
_MONITOR_REFERENCE_RISK_CLASSES = frozenset(
    {
        ToolRiskClass.OBSERVE,
        ToolRiskClass.SENSITIVE_OBSERVE,
    }
)
_ASSISTANT_FACT_VALUE_TYPES = frozenset({"boolean", "integer", "number", "string"})


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def _input_schema_required_fields(tool: ToolDefinition, *, reference_path: str) -> tuple[str, ...]:
    required = tool.input_schema.get("required", [])
    if required in (None, ""):
        return ()
    if not isinstance(required, list):
        raise AgentRuntimeError(
            f"{reference_path} references {tool.id!r}, whose input_schema.required must be a list"
        )
    return tuple(str(item).strip() for item in required if str(item).strip())


def _validate_reference_runtime_modes(
    source: ToolDefinition,
    target: ToolDefinition,
    *,
    reference_path: str,
) -> None:
    source_modes = set(source.runtime_modes)
    target_modes = set(target.runtime_modes)
    if not target_modes:
        return
    if not source_modes:
        raise AgentRuntimeError(
            f"{reference_path} references {target.id!r}, which is runtime-mode restricted "
            "while the assistant action is not"
        )
    missing_modes = sorted(source_modes - target_modes)
    if missing_modes:
        raise AgentRuntimeError(
            f"{reference_path} references {target.id!r}, which is unavailable in assistant "
            f"action runtime mode(s): {', '.join(missing_modes)}"
        )


def _validate_read_only_monitor_target(
    source: ToolDefinition,
    target: ToolDefinition,
    *,
    reference_path: str,
) -> None:
    if target.destructive:
        raise AgentRuntimeError(
            f"{reference_path} references destructive tool {target.id!r}; "
            "assistant monitor metadata may only use non-destructive read tools"
        )
    if not target.read_only:
        raise AgentRuntimeError(
            f"{reference_path} references non-read tool {target.id!r}; "
            "assistant monitor metadata may only use read-only tools"
        )
    if target.boundary != "gcs":
        raise AgentRuntimeError(
            f"{reference_path} references non-GCS tool {target.id!r}; "
            "assistant monitor metadata may only use GCS tools"
        )
    if target.exposure is not ToolExposure.ALLOW:
        raise AgentRuntimeError(
            f"{reference_path} references {target.exposure.value} tool {target.id!r}; "
            "assistant monitor metadata requires a directly allowed read tool"
        )
    if target.risk_class not in _MONITOR_REFERENCE_RISK_CLASSES:
        raise AgentRuntimeError(
            f"{reference_path} references policy-incompatible risk class "
            f"{target.risk_class.value!r} on {target.id!r}"
        )
    if target.route_path:
        if target.route_method != "GET":
            raise AgentRuntimeError(
                f"{reference_path} references {target.id!r}, whose read route must use GET"
            )
    elif target.route_method:
        raise AgentRuntimeError(
            f"{reference_path} references {target.id!r}, whose route metadata is incomplete"
        )
    elif target.side_effects:
        raise AgentRuntimeError(
            f"{reference_path} references route-less tool {target.id!r} with side effects; "
            "local advisory readers must not declare side effects"
        )
    _validate_reference_runtime_modes(source, target, reference_path=reference_path)


def _validate_operation_monitor_contract(
    target: ToolDefinition,
    *,
    reference_path: str,
) -> None:
    schema_type = str(target.input_schema.get("type") or "").strip()
    properties = target.input_schema.get("properties")
    if schema_type != "object" or not isinstance(properties, Mapping):
        raise AgentRuntimeError(
            f"{reference_path} references {target.id!r}, whose input schema must define "
            "an operation_id property"
        )
    required = _input_schema_required_fields(target, reference_path=reference_path)
    if "operation_id" not in properties or "operation_id" not in required:
        raise AgentRuntimeError(
            f"{reference_path} references {target.id!r}, which must require operation_id"
        )
    unsupported_required = sorted(set(required) - {"operation_id"})
    if unsupported_required:
        raise AgentRuntimeError(
            f"{reference_path} references {target.id!r}, which requires unsupported monitor "
            f"argument(s): {', '.join(unsupported_required)}"
        )


def _validate_completion_reader_contract(
    target: ToolDefinition,
    *,
    reference_path: str,
) -> None:
    required = _input_schema_required_fields(target, reference_path=reference_path)
    if required:
        raise AgentRuntimeError(
            f"{reference_path} references {target.id!r}, which requires argument(s) that "
            f"completion evidence does not provide: {', '.join(sorted(set(required)))}"
        )


def _validate_string_array_target_binding(
    tool: ToolDefinition,
    target_binding: object,
    *,
    reference_path: str,
    require_argument: bool = False,
) -> None:
    """Validate registry-owned target injection without domain-specific aliases."""

    if not isinstance(target_binding, Mapping):
        raise AgentRuntimeError(f"{reference_path} must be a mapping")
    unsupported = sorted(set(target_binding) - {"argument", "value_template"})
    if unsupported:
        raise AgentRuntimeError(
            f"{reference_path} has unsupported field(s): {', '.join(unsupported)}"
        )
    argument = str(target_binding.get("argument") or "").strip()
    value_template = str(target_binding.get("value_template") or "").strip()
    if not argument:
        raise AgentRuntimeError(f"{reference_path}.argument is required")
    if (
        value_template.count("{id}") != 1
        or "{" in value_template.replace("{id}", "")
        or "}" in value_template.replace("{id}", "")
    ):
        raise AgentRuntimeError(
            f"{reference_path}.value_template must contain exactly one {{id}} placeholder"
        )
    properties = tool.input_schema.get("properties")
    argument_schema = (
        properties.get(argument)
        if isinstance(properties, Mapping)
        else None
    )
    if (
        not isinstance(argument_schema, Mapping)
        or str(argument_schema.get("type") or "") != "array"
        or not isinstance(argument_schema.get("items"), Mapping)
        or str(argument_schema["items"].get("type") or "") != "string"
    ):
        raise AgentRuntimeError(
            f"{reference_path}.argument must reference a string-array input property"
        )
    if require_argument and argument not in _input_schema_required_fields(
        tool,
        reference_path=reference_path,
    ):
        raise AgentRuntimeError(
            f"{reference_path}.argument must reference a required input property"
        )


def _validate_assistant_monitor_references(tools: Mapping[str, ToolDefinition]) -> None:
    """Validate assistant monitor references after every registry tool is loaded."""

    for source in tools.values():
        action = source.assistant_action
        if not action:
            continue

        target_binding = action.get("target_binding")
        if target_binding is not None:
            reference_path = f"{source.id}.assistant_action.target_binding"
            _validate_string_array_target_binding(
                source,
                target_binding,
                reference_path=reference_path,
            )

        monitor_tool_id = str(action.get("monitor_tool_id") or "").strip()
        if "monitor_tool_id" in action:
            reference_path = f"{source.id}.assistant_action.monitor_tool_id"
            if not monitor_tool_id:
                raise AgentRuntimeError(f"{reference_path} must be a non-empty tool id")
            target = tools.get(monitor_tool_id)
            if target is None:
                raise AgentRuntimeError(
                    f"{reference_path} references unknown tool {monitor_tool_id!r}"
                )
            _validate_read_only_monitor_target(
                source,
                target,
                reference_path=reference_path,
            )
            if str(action.get("monitor_kind") or "").strip() == "sitl_operation":
                _validate_operation_monitor_contract(target, reference_path=reference_path)

        completion = action.get("completion_evidence")
        if completion is None:
            continue
        if not isinstance(completion, Mapping):
            raise AgentRuntimeError(
                f"{source.id}.assistant_action.completion_evidence must be a mapping"
            )
        for field_name, raw_tool_id in completion.items():
            if not str(field_name).endswith("_tool_id"):
                continue
            reference_path = (
                f"{source.id}.assistant_action.completion_evidence.{field_name}"
            )
            tool_id = str(raw_tool_id or "").strip()
            if not tool_id:
                raise AgentRuntimeError(f"{reference_path} must be a non-empty tool id")
            target = tools.get(tool_id)
            if target is None:
                raise AgentRuntimeError(
                    f"{reference_path} references unknown tool {tool_id!r}"
                )
            _validate_read_only_monitor_target(
                source,
                target,
                reference_path=reference_path,
            )
            _validate_completion_reader_contract(target, reference_path=reference_path)


def _schema_at_path(schema: Mapping[str, object], path: tuple[str, ...]) -> Mapping[str, object] | None:
    current: Mapping[str, object] = schema
    for segment in path:
        properties = current.get("properties")
        if not isinstance(properties, Mapping):
            return None
        child = properties.get(segment)
        if not isinstance(child, Mapping):
            return None
        current = child
    return current


def _schema_declares_type(schema: Mapping[str, object], expected_type: str) -> bool:
    declared = schema.get("type")
    if declared == expected_type:
        return True
    variants = schema.get("anyOf")
    return bool(
        isinstance(variants, list)
        and any(isinstance(item, Mapping) and item.get("type") == expected_type for item in variants)
    )


def _validate_assistant_facts(tools: Mapping[str, ToolDefinition]) -> None:
    """Validate named scalar facts used by conditional action plans."""

    fact_ids: set[str] = set()
    for tool in tools.values():
        if not tool.assistant_facts:
            continue
        if tool.route_method != "GET" or not tool.route_path:
            raise AgentRuntimeError(
                f"{tool.id}.assistant_facts require a read-only GET route"
            )
        for fact_id, raw_fact in tool.assistant_facts.items():
            normalized_id = str(fact_id or "").strip()
            reference_path = f"{tool.id}.assistant_facts.{normalized_id or '<empty>'}"
            if not normalized_id or any(char.isspace() for char in normalized_id):
                raise AgentRuntimeError(f"{reference_path} has an invalid fact id")
            if normalized_id in fact_ids:
                raise AgentRuntimeError(f"duplicate assistant fact id: {normalized_id}")
            if not isinstance(raw_fact, Mapping):
                raise AgentRuntimeError(f"{reference_path} must be an object")
            unsupported = sorted(
                set(raw_fact) - {"title", "path", "value_type", "target_binding"}
            )
            if unsupported:
                raise AgentRuntimeError(
                    f"{reference_path} has unsupported field(s): {', '.join(unsupported)}"
                )
            title = str(raw_fact.get("title") or "").strip()
            raw_path = raw_fact.get("path")
            value_type = str(raw_fact.get("value_type") or "").strip()
            if not title:
                raise AgentRuntimeError(f"{reference_path}.title is required")
            if (
                not isinstance(raw_path, list)
                or not raw_path
                or any(not str(item or "").strip() for item in raw_path)
            ):
                raise AgentRuntimeError(f"{reference_path}.path must be a non-empty string list")
            if value_type not in _ASSISTANT_FACT_VALUE_TYPES:
                raise AgentRuntimeError(f"{reference_path}.value_type is unsupported")
            path = tuple(str(item).strip() for item in raw_path)
            fact_schema = _schema_at_path(tool.output_schema, path)
            if fact_schema is None:
                raise AgentRuntimeError(
                    f"{reference_path}.path is not declared by {tool.id}.output_schema"
                )
            if not _schema_declares_type(fact_schema, value_type):
                raise AgentRuntimeError(
                    f"{reference_path}.value_type does not match {tool.id}.output_schema"
                )
            target_binding = raw_fact.get("target_binding")
            if target_binding is not None:
                _validate_string_array_target_binding(
                    tool,
                    target_binding,
                    reference_path=f"{reference_path}.target_binding",
                    require_argument=True,
                )
            fact_ids.add(normalized_id)


def _validate_assistant_execution_guards(
    tools: Mapping[str, ToolDefinition],
) -> None:
    fact_ids = {
        str(fact_id)
        for tool in tools.values()
        for fact_id in (tool.assistant_facts or {})
    }
    for tool in tools.values():
        guards = (tool.assistant_action or {}).get("execution_guards")
        if guards is None:
            continue
        reference_path = f"{tool.id}.assistant_action.execution_guards"
        if not isinstance(guards, Mapping) or not guards:
            raise AgentRuntimeError(f"{reference_path} must be a non-empty mapping")
        properties = tool.input_schema.get("properties")
        for fact_id, raw_guard in guards.items():
            guard_path = f"{reference_path}.{fact_id}"
            if str(fact_id) not in fact_ids:
                raise AgentRuntimeError(
                    f"{guard_path} references unknown assistant fact {fact_id!r}"
                )
            if not isinstance(raw_guard, Mapping):
                raise AgentRuntimeError(f"{guard_path} must be a mapping")
            unsupported = sorted(set(raw_guard) - {"argument"})
            if unsupported:
                raise AgentRuntimeError(
                    f"{guard_path} has unsupported field(s): {', '.join(unsupported)}"
                )
            argument = str(raw_guard.get("argument") or "").strip()
            argument_schema = (
                properties.get(argument)
                if argument and isinstance(properties, Mapping)
                else None
            )
            if not isinstance(argument_schema, Mapping):
                raise AgentRuntimeError(
                    f"{guard_path}.argument must reference an input property"
                )
            if argument_schema.get("x-simurgh-internal") is not True:
                raise AgentRuntimeError(
                    f"{guard_path}.argument must reference an internal input property"
                )


@dataclass(frozen=True)
class ToolRegistry:
    """Validated tool metadata loaded from a versioned artifact."""

    version: int
    path: Path
    tools: Mapping[str, ToolDefinition]

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_TOOL_REGISTRY_PATH) -> "ToolRegistry":
        registry_path = Path(path)
        try:
            payload = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as exc:
            raise AgentRuntimeError(f"tool registry not found: {registry_path}") from exc
        if not isinstance(payload, dict):
            raise AgentRuntimeError("tool registry root must be an object")
        return cls.from_mapping(payload, path=registry_path)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object], *, path: Path | None = None) -> "ToolRegistry":
        version = int(payload.get("version") or 0)
        if version < 1:
            raise AgentRuntimeError("tool registry version must be >= 1")
        raw_tools = payload.get("tools")
        if not isinstance(raw_tools, list):
            raise AgentRuntimeError("tool registry must contain a tools list")

        tools: dict[str, ToolDefinition] = {}
        for raw_tool in raw_tools:
            if not isinstance(raw_tool, dict):
                raise AgentRuntimeError("each tool registry entry must be an object")
            tool = ToolDefinition.from_mapping(raw_tool)
            if tool.id in tools:
                raise AgentRuntimeError(f"duplicate tool id: {tool.id}")
            tools[tool.id] = tool

        _validate_assistant_monitor_references(tools)
        _validate_assistant_facts(tools)
        _validate_assistant_execution_guards(tools)
        return cls(version=version, path=path or DEFAULT_TOOL_REGISTRY_PATH, tools=tools)

    def require(self, tool_id: str) -> ToolDefinition:
        tool = self.tools.get(tool_id)
        if tool is None:
            raise KeyError(f"unknown Simurgh tool id: {tool_id}")
        return tool

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self.tools.get(tool_id)

    def list_tools(self, *, exposure: ToolExposure | str | None = None) -> list[ToolDefinition]:
        values: Iterable[ToolDefinition] = self.tools.values()
        if exposure is not None:
            normalized = exposure if isinstance(exposure, ToolExposure) else ToolExposure(str(exposure))
            values = [tool for tool in values if tool.exposure is normalized]
        return sorted(values, key=lambda tool: tool.id)


def load_default_tool_registry() -> ToolRegistry:
    """Load the repository default Simurgh tool registry."""

    return ToolRegistry.from_file(_env_path("MDS_AGENT_TOOL_REGISTRY_FILE", DEFAULT_TOOL_REGISTRY_PATH))

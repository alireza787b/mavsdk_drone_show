"""Registry-backed read-only execution planning for dashboard chat."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .answer_composer import AnswerComposer
from .models import ToolDefinition
from .query_understanding import build_assistant_query_plan
from .tool_executor import ReadOnlyToolCallResult


REGISTRY_READ_EXECUTION_INTENT = "registry_read_execution"

_CAPABILITY_TERMS = (
    "api",
    "apis",
    "capability",
    "capabilities",
    "endpoint",
    "endpoints",
    "mcp",
    "menu",
    "route",
    "routes",
    "tool",
    "tools",
    "what can you inspect",
    "what can you query",
    "what can you read",
    "what read-only",
    "what read only",
    "which read-only",
    "which read only",
)

_DIRECT_ACTION_TERMS = (
    "arm",
    "command",
    "deploy",
    "execute",
    "land",
    "launch",
    "rtl",
    "send",
    "start mission",
    "take off",
    "takeoff",
    "trigger",
    "upload",
)

_STATE_TERMS = (
    "available",
    "check",
    "configured",
    "current",
    "do we have",
    "is there",
    "list",
    "loaded",
    "now",
    "read",
    "report",
    "running",
    "show me",
    "status",
    "state",
    "what is",
    "what are",
    "what's",
)

_DOMAIN_TOOLS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("quickscout", "quick scout", "sar", "search and rescue", "scout mission"), ("mds.sar.missions.read",), "QuickScout/SAR mission catalog"),
    (("sitl", "simulator", "simulation instance", "sim instance"), ("mds.sitl.instances.read", "mds.sitl.policy.read"), "SITL runtime state"),
    (("sidecar", "wifi manager", "mavlink dashboard", "board dashboard", "board sidecar"), ("mds.fleet.sidecars.read", "mds.fleet.network_status.read"), "fleet sidecar and board connectivity state"),
    (("git", "repo status", "repository", "sync status"), ("mds.git.status.read",), "repository sync state"),
    (("runtime", "gcs mode", "current mode", "real mode", "environment", "env"), ("mds.system.runtime_status.read", "mds.simurgh.status.read"), "GCS runtime and Simurgh posture"),
    (("env registry", "environment registry", "gcs env", "environment page"), ("mds.system.env_registry.read", "mds.system.env_gcs.read"), "environment registry state"),
    (("px4", "param", "parameter", "params"), ("mds.px4_params.policy.read", "mds.px4_params.profiles.read"), "PX4 parameter read-only evidence"),
    (("origin", "global origin", "launch position", "launch positions", "deviation", "deviations"), ("mds.origin.read", "mds.origin.deviations.read", "mds.navigation.global_origin.read"), "origin and launch-position evidence"),
    (("swarm trajectory", "trajectory status", "trajectory validation", "trajectory validate", "cluster mission"), ("mds.swarm_trajectories.status.read", "mds.swarm_trajectories.validate.read", "mds.swarm_trajectories.leaders.read"), "swarm trajectory state"),
    (("show validation", "safety report", "show safety", "show metrics", "skybrush validation", "skybrush metrics"), ("mds.shows.skybrush.validation.read", "mds.shows.skybrush.safety_report.read", "mds.shows.skybrush.metrics_snapshot.read"), "Drone Show validation and safety evidence"),
    (("fleet candidate", "fleet candidates", "enrollment", "onboarding queue"), ("mds.fleet.candidates.read",), "fleet enrollment candidates"),
    (("system health", "health check", "server health", "gcs health"), ("mds.system.health.read", "mds.system.runtime_status.read"), "GCS system health"),
)


@dataclass(frozen=True)
class RegistryReadCall:
    tool: ToolDefinition
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class RegistryReadPlan:
    label: str
    domain: str
    tool_calls: tuple[RegistryReadCall, ...]


@dataclass(frozen=True)
class RegistryReadToolResult:
    tool: ToolDefinition
    arguments: Mapping[str, Any]
    result: ReadOnlyToolCallResult


def plan_registry_read_tool_calls(
    message: str,
    *,
    allowed_tools: Sequence[ToolDefinition],
    conversation_topic: str | None = None,
) -> RegistryReadPlan | None:
    """Select safe registry read tools for concrete current-state chat questions."""

    normalized = " ".join(str(message or "").casefold().split())
    if not normalized:
        return None
    if _has_any(normalized, _CAPABILITY_TERMS):
        return None
    if _has_any(normalized, _DIRECT_ACTION_TERMS):
        return None
    if not _has_any(normalized, _STATE_TERMS):
        return None

    allowed_by_id = {tool.id: tool for tool in allowed_tools}
    plan = build_assistant_query_plan(normalized, conversation_topic=conversation_topic)
    selected_ids: list[str] = []
    label = "read-only GCS state"
    for signals, tool_ids, candidate_label in _DOMAIN_TOOLS:
        if _has_any(normalized, signals):
            selected_ids.extend(tool_ids)
            label = candidate_label
            break

    if not selected_ids:
        if plan.domain == "sitl":
            selected_ids = ["mds.sitl.instances.read", "mds.sitl.policy.read"]
            label = "SITL runtime state"
        elif plan.domain == "sar":
            selected_ids = ["mds.sar.missions.read"]
            label = "QuickScout/SAR mission catalog"
        elif plan.domain == "runtime":
            selected_ids = ["mds.system.runtime_status.read", "mds.simurgh.status.read"]
            label = "GCS runtime and Simurgh posture"

    calls: list[RegistryReadCall] = []
    seen: set[str] = set()
    for tool_id in selected_ids:
        tool = allowed_by_id.get(tool_id)
        if tool is None or tool.id in seen or _required_args(tool):
            continue
        calls.append(RegistryReadCall(tool=tool, arguments={}))
        seen.add(tool.id)
    if not calls:
        return None
    return RegistryReadPlan(label=label, domain=plan.domain, tool_calls=tuple(calls[:4]))


def format_registry_read_results(
    plan: RegistryReadPlan,
    results: Sequence[RegistryReadToolResult],
    *,
    registry_path: str = "config/agent_tools.yaml",
) -> str:
    """Format bounded registry tool evidence for the dashboard chat renderer."""

    composer = AnswerComposer()
    composer.line(f"Read-only registry check for {plan.label}:")
    composer.line(
        f"Source: `{registry_path}` filtered by current Simurgh policy; executed through the same internal adapter used by MCP `tools/call`."
    )
    composer.blank()
    rows = []
    for item in results:
        status = f"HTTP {item.result.status_code}" if item.result.status_code else "local"
        if item.result.is_error:
            status = f"error ({status})"
        rows.append((f"{item.tool.title} (`{item.tool.id}`)", status, _result_highlights(item.result)))
    composer.table(("Tool", "Result", "Highlights"), rows)
    composer.blank()
    composer.line("This was read-only registry execution. No config write, upload, mission action, drone API call, or command was attempted.")
    return composer.render()


def _required_args(tool: ToolDefinition) -> tuple[str, ...]:
    schema = tool.input_schema if isinstance(tool.input_schema, Mapping) else {}
    return tuple(str(item) for item in schema.get("required", []) if str(item))


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def _result_highlights(result: ReadOnlyToolCallResult) -> str:
    if result.structured_content is None:
        return _compact_text(result.text)
    return _preview_value(result.structured_content)


def _preview_value(value: Any, *, depth: int = 0) -> str:
    if depth > 1:
        return _compact_text(json.dumps(value, default=str, sort_keys=True))
    if isinstance(value, Mapping):
        scalar_parts: list[str] = []
        collection_parts: list[str] = []
        for key, item in value.items():
            if item is None or item == "":
                continue
            if isinstance(item, (str, int, float, bool)):
                scalar_parts.append(f"{key}: {item}")
            elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
                collection_parts.append(f"{key}: {len(item)} item(s){_first_item_hint(item)}")
            elif isinstance(item, Mapping):
                nested_scalars = [nested_key for nested_key, nested_value in item.items() if isinstance(nested_value, (str, int, float, bool))]
                if nested_scalars:
                    collection_parts.append(f"{key}: {{{', '.join(str(k) for k in nested_scalars[:4])}}}")
        parts = scalar_parts[:6] + collection_parts[:4]
        if parts:
            return _compact_text("; ".join(parts), limit=360)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _compact_text(f"{len(value)} item(s){_first_item_hint(value)}", limit=360)
    return _compact_text(json.dumps(value, default=str, sort_keys=True), limit=360)


def _first_item_hint(items: Sequence[Any]) -> str:
    if not items:
        return ""
    first = items[0]
    if isinstance(first, Mapping):
        hints = []
        for key in ("id", "mission_id", "name", "status", "state", "label"):
            value = first.get(key)
            if value not in (None, ""):
                hints.append(f"{key}={value}")
        if hints:
            return " (first: " + ", ".join(hints[:3]) + ")"
    return ""


def _compact_text(text: str, *, limit: int = 300) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact or "No text content returned."
    return compact[: limit - 1].rstrip() + "..."

"""Registry-backed read-only execution planning for dashboard chat."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .answer_composer import AnswerComposer
from .evidence import REGISTRY_EVIDENCE_SOURCE, ReadOnlyEvidenceBundle
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
    "show",
    "show me",
    "status",
    "state",
    "what is",
    "what are",
    "what's",
)

_DOCS_OR_WORKFLOW_TERMS = (
    "doc",
    "docs",
    "documentation",
    "guide",
    "manual",
    "read about",
    "where can i read",
    "how do i",
    "how to",
    "what should i do",
    "workflow",
    "step",
    "steps",
    "setup",
    "set up",
    "script",
    "scripts",
    "install",
    "configure",
)

_CONCRETE_STATE_TERMS = (
    "active",
    "available",
    "check",
    "connected",
    "current",
    "details",
    "inspect",
    "latest",
    "loaded",
    "now",
    "online",
    "read",
    "report",
    "running",
    "show me",
    "status",
    "state",
)

_ARGUMENT_STATE_TERMS = _STATE_TERMS + (
    "details",
    "detail",
    "explain",
    "inspect",
    "open",
    "review",
)

_IDENTIFIER_RE = r"[A-Za-z0-9_.:-]+"
_BAD_ARGUMENT_VALUES = {
    "a",
    "an",
    "are",
    "as",
    "available",
    "boot",
    "candidates",
    "detail",
    "details",
    "environment",
    "events",
    "for",
    "findings",
    "is",
    "init",
    "initializing",
    "initialization",
    "metadata",
    "mission",
    "now",
    "origin",
    "policy",
    "position",
    "positions",
    "read",
    "ready",
    "reay",
    "registry",
    "rows",
    "show",
    "statistics",
    "status",
    "summary",
    "test",
    "the",
    "workspace",
}

_SIDECAR_ALIASES: Mapping[str, tuple[str, ...]] = {
    "smart-wifi-manager": (
        "smart wifi manager",
        "smart-wifi-manager",
        "wifi manager",
        "wifi sidecar",
        "wifi dashboard",
    ),
    "mavlink-anywhere": (
        "mavlink anywhere",
        "mavlink-anywhere",
        "mavlink dashboard",
        "mavlink sidecar",
        "telemetry dashboard",
    ),
}

_ADVISORY_FIRST_INTENTS = frozenset(
    {
        "action_capability",
        "add_drone_workflow",
        "autopilot_support",
        "backend_log_summary",
        "board_setup_help",
        "capability_catalog",
        "command_summary",
        "companion_setup_help",
        "docs_help",
        "environment_summary",
        "fleet_connectivity",
        "fleet_summary",
        "general_knowledge",
        "mission_mode_comparison",
        "operator_help",
        "origin_status",
        "public_geography",
        "px4_params_summary",
        "registry_domain_tool_summary",
        "runtime_summary",
        "show_modes_help",
        "show_summary",
        "show_upload_help",
        "sitl_help",
        "swarm_readiness",
        "swarm_topology",
        "system_status",
    }
)


_ARGUMENT_TOOL_HINTS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("log session", "logs session", "session_id", "session id", "logs/session"), ("mds.logs.session.read",), "one GCS log session"),
    (("command_id", "command id", "command status"), ("mds.commands.status.read",), "one command status"),
    (("position id", "pos_id", "pos id", "launch position"), ("mds.config.position.read",), "one launch position"),
    (("candidate_id", "candidate id", "fleet candidate"), ("mds.fleet.candidate.read",), "one fleet candidate"),
    (("wifi manager", "mavlink anywhere", "mavlink dashboard"), ("mds.fleet.sidecar.read",), "one fleet sidecar table"),
    (("sidecar baseline", "wifi baseline", "mavlink baseline"), ("mds.fleet.sidecar.baseline.read",), "one fleet sidecar baseline"),
    (("sidecar node", "wifi node", "mavlink node", "board sidecar"), ("mds.fleet.sidecar.node.read",), "one fleet sidecar node"),
    (("elevation", "terrain altitude", "terrain height"), ("mds.origin.elevation.read",), "origin terrain elevation lookup"),
    (("px4 profile", "parameter profile", "profile_id", "profile id"), ("mds.px4_params.profile.read",), "one PX4 parameter profile"),
    (("snapshot_id", "snapshot id", "px4 snapshot"), ("mds.px4_params.snapshot.read", "mds.px4_params.snapshot_rows.read"), "one PX4 parameter snapshot"),
    (("px4 job", "patch job", "patch_job", "patch-job"), ("mds.px4_params.patch_job.read",), "one PX4 parameter job"),
    (("sar findings", "mission findings"), ("mds.sar.findings.read",), "one SAR findings set"),
    (("sar workspace", "mission workspace"), ("mds.sar.mission.workspace.read",), "one SAR mission workspace"),
    (("sar status", "mission status", "quickscout status"), ("mds.sar.mission.status.read",), "one SAR mission status"),
    (("sar job", "planning job"), ("mds.sar.plan_job.read",), "one SAR planning job"),
    (("swarm trajectory job", "trajectory job", "process job"), ("mds.swarm_trajectories.process_job.read",), "one swarm trajectory job"),
    (("node boot", "boot status", "boot init", "initializing", "initialization", "git sync phase"), ("mds.fleet.node_boot_status.read",), "fleet node boot/init status"),
    (("fleet node env", "node environment", "board environment", "drone environment"), ("mds.system.env_fleet_node.read",), "one fleet-node environment posture"),
    (("sitl operation", "operation_id", "operation id"), ("mds.sitl.operation.read",), "one SITL operation"),
    (("tool_id", "tool id", "simurgh tool"), ("mds.simurgh.tool.read",), "one Simurgh tool definition"),
    (("context resource", "resource_id", "resource id"), ("mds.simurgh.context_resource.read", "mds.simurgh.context_markdown.read"), "one Simurgh context resource"),
    (("chunk_id", "chunk id", "docs chunk"), ("mds.docs.chunk.read",), "one public docs chunk"),
)

_DOMAIN_TOOLS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("simurgh status", "assistant status", "agent status"), ("mds.simurgh.status.read",), "Simurgh status"),
    (("quickscout", "quick scout", "sar", "search and rescue", "scout mission"), ("mds.sar.missions.read",), "QuickScout/SAR mission catalog"),
    (("sitl", "simulator", "simulation instance", "sim instance"), ("mds.sitl.instances.read", "mds.sitl.policy.read"), "SITL runtime state"),
    (("node boot", "boot status", "boot init", "initializing", "initialisation", "initialization", "git sync phase"), ("mds.fleet.node_boot_status.read",), "fleet node boot/init status"),
    (("sidecar", "wifi manager", "mavlink dashboard", "board dashboard", "board sidecar"), ("mds.fleet.sidecars.read", "mds.fleet.network_status.read"), "fleet sidecar and board connectivity state"),
    (("git sync", "repo sync", "repository sync", "sync posture", "sync status", "out of sync"), ("mds.fleet.git_sync.read", "mds.git.status.read", "mds.fleet.node_boot_status.read"), "fleet git sync posture"),
    (("git", "repo status", "repository"), ("mds.git.status.read",), "repository sync state"),
    (("runtime", "gcs mode", "current mode", "real mode", "environment", "env"), ("mds.system.runtime_status.read", "mds.simurgh.status.read"), "GCS runtime and Simurgh posture"),
    (("env registry", "environment registry", "gcs env", "environment page"), ("mds.system.env_registry.read", "mds.system.env_gcs.read"), "environment registry state"),
    (("px4", "param", "parameter", "params"), ("mds.px4_params.policy.read", "mds.px4_params.profiles.read"), "PX4 parameter read-only evidence"),
    (("launch position", "launch positions", "desired launch", "planned launch"), ("mds.origin.launch_positions.read", "mds.config.positions.read", "mds.origin.read", "mds.origin.deviations.read", "mds.navigation.global_origin.read"), "origin and launch-position evidence"),
    (("deviation", "deviations"), ("mds.origin.deviations.read", "mds.origin.read", "mds.navigation.global_origin.read"), "origin deviation evidence"),
    (("origin", "global origin"), ("mds.origin.read", "mds.origin.deviations.read", "mds.navigation.global_origin.read"), "origin and launch-position evidence"),
    (("swarm trajectory", "trajectory status", "trajectory validation", "trajectory validate", "cluster mission"), ("mds.swarm_trajectories.status.read", "mds.swarm_trajectories.validate.read", "mds.swarm_trajectories.leaders.read"), "swarm trajectory state"),
    (("show validation", "safety report", "show safety", "show metrics", "skybrush validation", "skybrush metrics"), ("mds.shows.skybrush.validation.read", "mds.shows.skybrush.safety_report.read", "mds.shows.skybrush.metrics_snapshot.read"), "Drone Show validation and safety evidence"),
    (("fleet candidate", "fleet candidates", "enrollment", "onboarding queue"), ("mds.fleet.candidates.read",), "fleet enrollment candidates"),
    (("system health", "health check", "server health", "gcs health"), ("mds.system.health.read", "mds.system.runtime_status.read"), "GCS system health"),
)

_DOMAIN_SEARCH_ALIASES: Mapping[str, tuple[str, ...]] = {
    "capabilities": ("simurgh", "tool", "tools", "mcp", "api"),
    "docs": ("docs", "documentation", "context", "simurgh"),
    "drone_show": ("show", "shows", "skybrush", "custom"),
    "fleet": ("fleet", "config", "sidecar", "network", "telemetry"),
    "logs": ("log", "logs", "audit", "diagnostics", "simurgh"),
    "mcp": ("simurgh", "tool", "tools", "mcp"),
    "runtime": ("runtime", "system", "simurgh", "environment"),
    "safety": ("policy", "commands", "origin", "px4", "simurgh"),
    "sar": ("sar", "quickscout", "mission"),
    "setup": ("fleet", "system", "docs", "environment"),
    "sitl": ("sitl", "simulation"),
    "swarm": ("swarm", "trajectory", "swarm_trajectories", "config", "origin"),
    "ui": ("simurgh", "dashboard", "context"),
}

_TYPED_TOOL_DISCOVERY: Mapping[str, tuple[tuple[str, ...], str]] = {
    "mds.commands.status.read": (("mds.commands.active.read", "mds.commands.recent.read"), "Choose a command_id from active/recent command records."),
    "mds.config.position.read": (("mds.config.positions.read",), "Choose a pos_id from configured launch positions."),
    "mds.docs.chunk.read": (("mds.docs.search",), "Choose a chunk_id from docs search results, or ask the docs question directly."),
    "mds.fleet.candidate.read": (("mds.fleet.candidates.read",), "Choose a candidate_id from fleet enrollment candidates."),
    "mds.fleet.sidecar.baseline.read": (("mds.fleet.sidecars.read", "mds.fleet.network_status.read"), "Choose a sidecar name, for example smart-wifi-manager or mavlink-anywhere."),
    "mds.fleet.sidecar.node.read": (("mds.fleet.sidecars.read", "mds.fleet.network_status.read"), "Choose both sidecar and hw_id to inspect one node."),
    "mds.fleet.sidecar.read": (("mds.fleet.sidecars.read", "mds.fleet.network_status.read"), "Choose a sidecar name, for example smart-wifi-manager or mavlink-anywhere."),
    "mds.fleet.sidecars.job.read": (("mds.fleet.sidecars.read",), "Choose a sidecar job_id from the relevant sidecar operation result."),
    "mds.logs.session.read": (("mds.logs.sessions.read",), "Choose a session_id from the log sessions list."),
    "mds.origin.elevation.read": (("mds.origin.read", "mds.navigation.global_origin.read"), "Provide latitude and longitude, or ask for current origin status."),
    "mds.px4_params.patch_job.read": (("mds.px4_params.policy.read", "mds.px4_params.profiles.read"), "Choose a PX4 patch job_id from the patch job that was created earlier."),
    "mds.px4_params.profile.read": (("mds.px4_params.profiles.read",), "Choose a profile_id from available PX4 parameter profiles."),
    "mds.px4_params.snapshot.read": (("mds.px4_params.policy.read",), "Choose a snapshot_id from the PX4 Parameters page or prior snapshot result."),
    "mds.px4_params.snapshot_rows.read": (("mds.px4_params.policy.read",), "Choose a snapshot_id from the PX4 Parameters page or prior snapshot result."),
    "mds.sar.findings.read": (("mds.sar.missions.read",), "Choose a mission_id from the QuickScout/SAR mission catalog."),
    "mds.sar.mission.status.read": (("mds.sar.missions.read",), "Choose a mission_id from the QuickScout/SAR mission catalog."),
    "mds.sar.mission.workspace.read": (("mds.sar.missions.read",), "Choose a mission_id from the QuickScout/SAR mission catalog."),
    "mds.sar.plan_job.read": (("mds.sar.missions.read",), "Choose a planning job_id from the SAR planning result."),
    "mds.simurgh.context_markdown.read": (("mds.simurgh.context.read",), "Choose a resource_id from the Simurgh context index."),
    "mds.simurgh.context_resource.read": (("mds.simurgh.context.read",), "Choose a resource_id from the Simurgh context index."),
    "mds.simurgh.tool.read": (("mds.simurgh.tools.read",), "Choose a tool_id from the Simurgh tool registry."),
    "mds.sitl.operation.read": (("mds.sitl.operations.read",), "Choose an operation_id from SITL operations."),
    "mds.swarm_trajectories.process_job.read": (("mds.swarm_trajectories.status.read",), "Choose a process job_id from the trajectory processing result."),
    "mds.system.env_fleet_node.read": (("mds.config.fleet.read",), "Choose a hw_id from the fleet configuration."),
}


@dataclass(frozen=True)
class RegistryReadCall:
    tool: ToolDefinition
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class RegistryReadPlan:
    label: str
    domain: str
    tool_calls: tuple[RegistryReadCall, ...]
    clarification: str = ""
    missing_arguments: tuple[str, ...] = ()
    selection_source: str = "domain_rules"

    def public_metadata(self) -> dict[str, Any]:
        return {
            "intent": REGISTRY_READ_EXECUTION_INTENT,
            "response_mode": "status",
            "topic": self.domain,
            "query_domain": self.domain,
            "confidence": 1.0,
            "unclear": bool(self.clarification),
            "reason": "registry_read_tool_plan",
            "label": self.label,
            "tool_ids": [call.tool.id for call in self.tool_calls],
            "missing_arguments": list(self.missing_arguments),
            "selection_source": self.selection_source,
            "execution_layer": "registry_read_adapter",
            "safety_posture": "read-only-registry; policy-filtered MCP-compatible tool execution only",
        }


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
    local_intent: str | None = None,
) -> RegistryReadPlan | None:
    """Select safe registry read tools for concrete current-state chat questions."""

    normalized = " ".join(str(message or "").casefold().split())
    if not normalized:
        return None
    if _looks_like_capability_catalog_prompt(normalized):
        return None
    if _has_direct_action_term(normalized):
        return None
    if _looks_like_docs_or_workflow_prompt(normalized):
        return None
    if not _has_any(normalized, _STATE_TERMS):
        return None

    allowed_by_id = {tool.id: tool for tool in allowed_tools}
    plan = build_assistant_query_plan(normalized, conversation_topic=conversation_topic)
    selected_ids: list[str] = []
    label = "read-only GCS state"
    selection_source = "domain_rules"
    for signals, tool_ids, candidate_label in _DOMAIN_TOOLS:
        if _has_any(normalized, signals):
            selected_ids.extend(tool_ids)
            label = candidate_label
            break

    argument_ids, argument_label = _argument_tool_ids_for_query(normalized, domain=plan.domain)
    had_argument_rule_ids = bool(argument_ids)
    supplied_typed_metadata_ids, supplied_typed_metadata_label = _metadata_ranked_tool_ids(
        normalized,
        allowed_tools,
        domain=plan.domain,
        include_typed=True,
        require_typed_arguments=True,
        typed_only=True,
    )
    missing_typed_metadata_ids: tuple[str, ...] = ()
    missing_typed_metadata_label = ""
    if not supplied_typed_metadata_ids:
        missing_typed_metadata_ids, missing_typed_metadata_label = _metadata_ranked_tool_ids(
            normalized,
            allowed_tools,
            domain=plan.domain,
            include_typed=True,
            typed_only=True,
        )
    if supplied_typed_metadata_ids:
        argument_label = supplied_typed_metadata_label or argument_label
        if had_argument_rule_ids:
            selection_source = "typed_argument_rules"
        else:
            argument_ids = supplied_typed_metadata_ids
            selection_source = "metadata_typed_ranker"
    elif missing_typed_metadata_ids and not argument_ids and _looks_like_typed_detail_prompt(normalized):
        argument_ids = missing_typed_metadata_ids
        argument_label = missing_typed_metadata_label or "typed read-only GCS state"
        selection_source = "metadata_typed_discovery"
    if _should_defer_to_advisory(local_intent, normalized, argument_ids=argument_ids):
        return None

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

    if not selected_ids and not argument_ids:
        metadata_ids, metadata_label = _metadata_ranked_tool_ids(normalized, allowed_tools, domain=plan.domain)
        selected_ids = list(metadata_ids)
        if metadata_label:
            label = metadata_label
        if selected_ids:
            selection_source = "metadata_ranker"
    elif selected_ids and not argument_ids:
        metadata_ids, _metadata_label = _metadata_ranked_tool_ids(
            normalized,
            allowed_tools,
            domain=plan.domain,
            context_tool_ids=selected_ids,
        )
        merged_ids = _merge_specific_tool_ids(metadata_ids, selected_ids)
        if tuple(selected_ids) != merged_ids:
            selected_ids = list(merged_ids)
            selection_source = "domain_rules+metadata_ranker"

    base_label = label
    candidate_groups: list[tuple[list[str], str]] = []
    if argument_ids:
        candidate_groups.append((list(argument_ids), argument_label or base_label))
        if selection_source == "domain_rules":
            selection_source = "typed_argument_rules"
    candidate_groups.append((list(selected_ids), base_label))
    selected_label = base_label
    calls: list[RegistryReadCall] = []
    clarification = ""
    missing_arguments: tuple[str, ...] = ()
    for candidate_ids, candidate_label in candidate_groups:
        candidate_calls: list[RegistryReadCall] = []
        seen: set[str] = set()
        for tool_id in candidate_ids:
            tool = allowed_by_id.get(tool_id)
            if tool is None or tool.id in seen:
                continue
            arguments = _arguments_for_tool(tool, normalized, domain=plan.domain)
            if arguments is None:
                continue
            candidate_calls.append(RegistryReadCall(tool=tool, arguments=arguments))
            seen.add(tool.id)
        if candidate_calls:
            calls = candidate_calls
            selected_label = candidate_label
            break
        if candidate_ids == list(argument_ids):
            discovery_ids, clarification = _discovery_ids_for_missing_typed_args(candidate_ids, allowed_by_id=allowed_by_id)
            missing_arguments = _required_argument_names(candidate_ids, allowed_by_id)
            discovery_calls = []
            seen_discovery: set[str] = set()
            for tool_id in discovery_ids:
                tool = allowed_by_id.get(tool_id)
                if tool is None or tool.id in seen_discovery:
                    continue
                arguments = _arguments_for_discovery_tool(tool, normalized)
                if arguments is None:
                    continue
                discovery_calls.append(RegistryReadCall(tool=tool, arguments=arguments))
                seen_discovery.add(tool.id)
            if discovery_calls:
                calls = discovery_calls
                selected_label = candidate_label
                if selection_source in {"typed_argument_rules", "domain_rules"}:
                    selection_source = "typed_argument_discovery"
                break
    if not calls:
        return None
    return RegistryReadPlan(
        label=selected_label,
        domain=plan.domain,
        tool_calls=tuple(calls[:4]),
        clarification=clarification,
        missing_arguments=missing_arguments,
        selection_source=selection_source,
    )


def _merge_specific_tool_ids(preferred: Sequence[str], fallback: Sequence[str], *, limit: int = 4) -> tuple[str, ...]:
    extras = [tool_id for tool_id in preferred if tool_id not in fallback]
    if not extras:
        return tuple(fallback[:limit])
    merged: list[str] = []
    for tool_id in tuple(extras) + tuple(fallback):
        if tool_id not in merged:
            merged.append(tool_id)
        if len(merged) >= limit:
            break
    return tuple(merged)


def _should_defer_to_advisory(local_intent: str | None, text: str, *, argument_ids: Sequence[str]) -> bool:
    intent = str(local_intent or "").strip()
    if intent not in _ADVISORY_FIRST_INTENTS:
        return False
    if argument_ids:
        return False
    if intent == "fleet_summary" and _has_any(
        text,
        (
            "sidecar",
            "sidecars",
            "wifi",
            "wi-fi",
            "mavlink-anywhere",
            "mavlink dashboard",
            "network detail",
            "network details",
            "connectivity profile",
        ),
    ):
        return False
    if intent in {"backend_log_summary", "fleet_connectivity", "fleet_summary"}:
        return True
    if intent == "docs_help" and _has_any(text, ("mission", "missions", "available", "current", "status", "running", "state")):
        return False
    if intent == "sitl_help" and _has_any(text, ("instance", "instances", "policy", "operation", "operations", "running", "status", "state")):
        return False
    if intent == "sitl_help" and _has_any(text, ("host", "hosts")):
        return False
    if intent in {"docs_help", "show_upload_help", "sitl_help", "board_setup_help", "companion_setup_help", "add_drone_workflow", "operator_help"}:
        return True
    if intent in {"general_knowledge", "public_geography", "autopilot_support", "mission_mode_comparison"}:
        return True
    if intent in {"show_summary", "swarm_readiness", "swarm_topology", "runtime_summary", "system_status", "environment_summary", "px4_params_summary", "origin_status", "command_summary"}:
        return not _has_any(
            text,
            (
                "validation",
                "metrics",
                "safety report",
                "tool_id",
                "resource_id",
                "command_id",
                "bootstrap",
                "network detail",
                "network details",
                "connectivity profile",
                "policy",
                "recommendation",
                "preview",
            ),
        )
    return True


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
        f"I checked the approved MDS registry/MCP read-only surface for this. Source: `{registry_path}`, executed through the same internal adapter used by MCP `tools/call`."
    )
    if plan.clarification:
        composer.line(plan.clarification)
    composer.blank()
    for item in results:
        status = f"HTTP {item.result.status_code}" if item.result.status_code else "local"
        if item.result.is_error:
            status = f"error ({status})"
        arguments = _argument_summary(item.arguments)
        argument_text = f"; arguments: {arguments}" if arguments != "none" else ""
        composer.line(
            f"- {item.tool.title}: {_result_evidence_summary(item.result)} "
            f"({status}; `{item.tool.id}`{argument_text})"
        )
    composer.blank()
    composer.line("This was read-only registry execution. No config write, upload, mission action, drone API call, or command was attempted.")
    return composer.render()


def build_registry_read_evidence_bundle(
    plan: RegistryReadPlan,
    results: Sequence[RegistryReadToolResult],
    *,
    registry_path: str = "config/agent_tools.yaml",
) -> ReadOnlyEvidenceBundle:
    """Aggregate registry route evidence into one audit/session-safe bundle."""

    tool_ids = tuple(item.tool.id for item in results)
    summaries = [_result_evidence_summary(item.result) for item in results]
    content = json.dumps(
        {
            "intent": REGISTRY_READ_EXECUTION_INTENT,
            "label": plan.label,
            "domain": plan.domain,
            "registry_path": registry_path,
            "tool_ids": tool_ids,
            "summaries": summaries,
            "missing_arguments": list(plan.missing_arguments),
            "selection_source": plan.selection_source,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    joined = "; ".join(summary for summary in summaries if summary) or "no result summaries"
    source_refs: list[dict[str, Any]] = []
    for item in results:
        result_metadata = item.result.evidence_metadata() or {}
        route_path = item.tool.route_path or ""
        route_method = item.tool.route_method or "GET"
        if isinstance(result_metadata, Mapping):
            raw_items = result_metadata.get("items")
            if isinstance(raw_items, list) and raw_items and isinstance(raw_items[0], Mapping):
                metadata = raw_items[0].get("metadata")
                if isinstance(metadata, Mapping):
                    route_path = str(metadata.get("route_path") or route_path)
                    route_method = str(metadata.get("route_method") or route_method)
        source_refs.append(
            {
                "tool_id": item.tool.id,
                "title": item.tool.title,
                "source": REGISTRY_EVIDENCE_SOURCE,
                "route_method": route_method,
                "route_path": route_path,
                "route_template": item.tool.route_path or route_path,
                "status_code": item.result.status_code,
                "truncated": item.result.truncated,
                "docs": item.tool.docs,
            }
        )
    return ReadOnlyEvidenceBundle.from_answer(
        intent=REGISTRY_READ_EXECUTION_INTENT,
        response_mode="status",
        tool_ids=tool_ids,
        content=content,
        source=REGISTRY_EVIDENCE_SOURCE,
        summary=f"{plan.label}: {joined}",
        source_refs=source_refs,
    )


def _looks_like_docs_or_workflow_prompt(text: str) -> bool:
    if not _has_any(text, _DOCS_OR_WORKFLOW_TERMS):
        return False
    if _has_any(text, ("session_id", "command_id", "tool_id", "resource_id", "chunk_id")):
        return False
    if _has_any(text, ("what is running", "which are running", "current status", "status now", "running now")):
        return False
    docs_signal = _has_any(text, ("doc", "docs", "documentation", "guide", "manual", "read about", "where can i read"))
    workflow_signal = _has_any(text, ("how do i", "how to", "what should i do", "workflow", "step", "steps", "setup", "set up", "script", "scripts", "install"))
    if docs_signal or workflow_signal:
        concrete_signal_count = sum(1 for term in _CONCRETE_STATE_TERMS if term in text)
        return concrete_signal_count <= 2 or docs_signal
    return False


def _looks_like_typed_detail_prompt(text: str) -> bool:
    return _has_any(
        text,
        (
            "detail",
            "details",
            "specific",
            "single",
            "one ",
            " by id",
            " for id",
            " with id",
        ),
    )


def _looks_like_capability_catalog_prompt(text: str) -> bool:
    if not _has_any(text, _CAPABILITY_TERMS):
        return False
    if _has_any(text, ("tool_id", "tool id", "resource_id", "resource id", "command_id", "command id")):
        return False
    if _has_any(text, ("status", "state", "current", "now", "latest", "details", "read", "show", "list", "open")):
        concrete_registry_terms = (
            "audit",
            "candidate",
            "candidates",
            "registry",
            "runtime settings",
            "provider credentials",
            "session",
            "sessions",
        )
        if _has_any(text, concrete_registry_terms):
            return False
    return _has_any(
        text,
        (
            "what can",
            "can n8n",
            "can claude",
            "capability",
            "capabilities",
            "mcp menu",
            "same menu",
            "tools/list",
            "tools/call",
            "what read-only",
            "what read only",
            "which read-only",
            "which read only",
        ),
    )


def _metadata_ranked_tool_ids(
    text: str,
    allowed_tools: Sequence[ToolDefinition],
    *,
    domain: str,
    context_tool_ids: Sequence[str] = (),
    include_typed: bool = False,
    require_typed_arguments: bool = False,
    typed_only: bool = False,
) -> tuple[tuple[str, ...], str]:
    terms = _query_terms(text)
    if not terms:
        return (), ""
    context_prefixes = _tool_namespace_prefixes(context_tool_ids)
    ranked: list[tuple[int, str, ToolDefinition]] = []
    for tool in allowed_tools:
        if tool.route_path is None or tool.route_method != "GET":
            continue
        required_args = _required_args(tool)
        if required_args and not include_typed:
            continue
        if typed_only and not required_args:
            continue
        if required_args and require_typed_arguments and _arguments_for_tool(tool, text, domain=domain) is None:
            continue
        searchable = _tool_search_text(tool)
        if context_prefixes and not any(tool.id.startswith(prefix) for prefix in context_prefixes):
            continue
        score = 0
        for term in terms:
            if term in str(tool.id).casefold():
                score += 4
            elif term in str(tool.title).casefold():
                score += 3
            elif term in " ".join(tool.tags).casefold():
                score += 3
            elif tool.route_path and term in tool.route_path.casefold():
                score += 2
            elif term in searchable:
                score += 1
        domain_match = _searchable_matches_domain(searchable, domain)
        if not context_prefixes and domain and domain not in {"docs", "general"} and not domain_match and score < 6:
            continue
        if score < 3:
            continue
        if domain_match:
            score += 3
        ranked.append((score, tool.id, tool))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    best_score = ranked[0][0] if ranked else 0
    score_floor = max(3, best_score - 2)
    selected = [tool for score, _tool_id, tool in ranked if score >= score_floor][:3]
    if not selected:
        return (), ""
    label = _registry_label_from_tools(selected)
    return tuple(tool.id for tool in selected), label


def _searchable_matches_domain(searchable: str, domain: str) -> bool:
    if not domain:
        return False
    aliases = _DOMAIN_SEARCH_ALIASES.get(domain, (domain,))
    return any(alias and alias in searchable for alias in aliases)


def _tool_namespace_prefixes(tool_ids: Sequence[str]) -> tuple[str, ...]:
    prefixes: list[str] = []
    for tool_id in tool_ids:
        parts = str(tool_id).split(".")
        if len(parts) < 3:
            continue
        prefix = ".".join(parts[:2])
        if len(parts) >= 3 and parts[1] in {"swarm_trajectories", "px4_params"}:
            prefix = ".".join(parts[:2])
        if prefix not in prefixes:
            prefixes.append(prefix)
    return tuple(prefixes)


def _tool_search_text(tool: ToolDefinition) -> str:
    values = (
        tool.id,
        tool.title,
        tool.description,
        tool.route_path or "",
        " ".join(tool.tags),
        " ".join(tool.docs),
    )
    return " ".join(str(value or "").casefold() for value in values)


def _query_terms(text: str) -> tuple[str, ...]:
    ignored = {
        "about",
        "any",
        "are",
        "can",
        "check",
        "current",
        "configured",
        "details",
        "for",
        "fleet",
        "from",
        "have",
        "latest",
        "now",
        "read",
        "report",
        "show",
        "sidecar",
        "sidecars",
        "status",
        "that",
        "the",
        "what",
        "which",
        "with",
        "you",
        "sitl",
        "swarm",
        "trajectory",
        "origin",
    }
    terms = []
    for term in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text):
        normalized = term.replace("_", "-")
        if normalized not in ignored:
            terms.append(normalized)
    return tuple(dict.fromkeys(terms))


def _registry_label_from_tools(tools: Sequence[ToolDefinition]) -> str:
    domains = []
    for tool in tools:
        parts = tool.id.split(".")
        domain = parts[1] if tool.id.startswith("mds.") and len(parts) > 2 else parts[0]
        if domain and domain not in domains:
            domains.append(domain)
    if not domains:
        return "read-only GCS state"
    label = ", ".join(domain.replace("_", " ") for domain in domains[:3])
    return f"{label} state"


def _discovery_ids_for_missing_typed_args(
    tool_ids: Sequence[str],
    *,
    allowed_by_id: Mapping[str, ToolDefinition],
) -> tuple[tuple[str, ...], str]:
    discovery: list[str] = []
    clarifications: list[str] = []
    for tool_id in tool_ids:
        configured = _TYPED_TOOL_DISCOVERY.get(tool_id)
        if not configured:
            discovery.extend(_generic_discovery_ids_for_tool(tool_id, allowed_by_id=allowed_by_id))
            tool = allowed_by_id.get(tool_id)
            if tool is not None:
                names = ", ".join(_required_args(tool)) or "the required identifier"
                clarifications.append(f"Choose {names} from the relevant list/status route before reading {tool.title}.")
            continue
        ids, clarification = configured
        discovery.extend(ids)
        if clarification not in clarifications:
            clarifications.append(clarification)
    deduped = tuple(dict.fromkeys(discovery))
    if not deduped:
        return (), ""
    message = "I need one more identifier before reading the specific typed record. " + " ".join(clarifications[:2])
    return deduped, message


def _generic_discovery_ids_for_tool(
    tool_id: str,
    *,
    allowed_by_id: Mapping[str, ToolDefinition],
) -> tuple[str, ...]:
    tool = allowed_by_id.get(tool_id)
    if tool is None:
        return ()
    prefix = _tool_namespace_prefixes((tool_id,))
    if not prefix:
        return ()
    candidates = []
    for candidate in allowed_by_id.values():
        if candidate.id == tool_id:
            continue
        if candidate.route_method != "GET" or not candidate.route_path or _required_args(candidate):
            continue
        if any(candidate.id.startswith(item) for item in prefix):
            candidates.append(candidate.id)
    return tuple(sorted(candidates)[:2])


def _required_argument_names(tool_ids: Sequence[str], allowed_by_id: Mapping[str, ToolDefinition]) -> tuple[str, ...]:
    names: list[str] = []
    for tool_id in tool_ids:
        tool = allowed_by_id.get(tool_id)
        if tool is None:
            continue
        for name in _required_args(tool):
            if tool.id == "mds.logs.session.read" and name == "limit":
                continue
            if name not in names:
                names.append(name)
    return tuple(names or ("identifier",))


def _arguments_for_discovery_tool(tool: ToolDefinition, text: str) -> Mapping[str, Any] | None:
    required = _required_args(tool)
    if not required:
        return {}
    if tool.id == "mds.docs.search":
        return {"query": text, "limit": 5}
    return _arguments_for_tool(tool, text, domain="docs")


def _argument_tool_ids_for_query(text: str, *, domain: str) -> tuple[tuple[str, ...], str]:
    selected: list[str] = []
    label = "typed read-only GCS state"
    for signals, tool_ids, candidate_label in _ARGUMENT_TOOL_HINTS:
        if _has_any(text, signals):
            if "mds.config.position.read" in tool_ids and _has_any(text, ("launch positions", "positions", "deviations")):
                continue
            selected.extend(tool_ids)
            label = candidate_label

    sidecar = _extract_sidecar(text)
    hw_id = _extract_hw_id(text)
    if sidecar:
        if _has_any(text, ("baseline", "approved baseline")):
            selected.insert(0, "mds.fleet.sidecar.baseline.read")
            label = "one fleet sidecar baseline"
        elif hw_id or _has_any(text, ("node", "board", "drone", "cm4", "hardware")):
            selected.insert(0, "mds.fleet.sidecar.node.read")
            label = "one fleet sidecar node"
        else:
            selected.insert(0, "mds.fleet.sidecar.read")
            label = "one fleet sidecar table"

    if _extract_log_session_id(text):
        selected.insert(0, "mds.logs.session.read")
        label = "one GCS log session"

    if _extract_mission_id(text):
        if _has_any(text, ("finding", "findings", "detection", "detections")):
            selected.insert(0, "mds.sar.findings.read")
            label = "one SAR findings set"
        elif _has_any(text, ("workspace", "plan workspace")):
            selected.insert(0, "mds.sar.mission.workspace.read")
            label = "one SAR mission workspace"
        elif domain == "sar" or _has_any(text, ("sar", "quickscout", "mission")):
            selected.insert(0, "mds.sar.mission.status.read")
            label = "one SAR mission status"

    if hw_id and _has_any(text, ("environment", "env", "registry", "node env", "board env")):
        selected.insert(0, "mds.system.env_fleet_node.read")
        label = "one fleet-node environment posture"

    if _extract_lat_lon(text) and _has_any(text, ("elevation", "terrain", "altitude", "height")):
        selected.insert(0, "mds.origin.elevation.read")
        label = "origin terrain elevation lookup"

    deduped = list(dict.fromkeys(selected))
    if "mds.fleet.sidecar.node.read" in deduped:
        deduped = [tool_id for tool_id in deduped if tool_id != "mds.fleet.sidecar.read"]
    if "mds.fleet.sidecar.baseline.read" in deduped:
        deduped = [tool_id for tool_id in deduped if tool_id != "mds.fleet.sidecar.read"]
    return tuple(deduped), label


def _arguments_for_tool(tool: ToolDefinition, text: str, *, domain: str) -> Mapping[str, Any] | None:
    schema = tool.input_schema if isinstance(tool.input_schema, Mapping) else {}
    required = _required_args(tool)
    if tool.id == "mds.origin.launch_positions.read":
        arguments: dict[str, Any] = {"format": "json"}
        heading = _extract_heading(text)
        if heading is not None:
            arguments["heading"] = heading
        return arguments
    if not schema or not required:
        return {}
    if not _has_any(text, _ARGUMENT_STATE_TERMS):
        return None
    properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
    arguments: dict[str, Any] = {}
    for name, raw_property_schema in properties.items():
        if not isinstance(raw_property_schema, Mapping):
            continue
        value = _extract_argument_value(str(name), raw_property_schema, text, tool=tool, domain=domain)
        if value is not None and _value_matches_schema(value, raw_property_schema):
            arguments[str(name)] = value

    if "limit" in required and "limit" not in arguments and tool.id == "mds.logs.session.read" and "session_id" in arguments:
        arguments["limit"] = 20

    if all(name in arguments for name in required):
        return arguments
    return None


def _extract_argument_value(
    name: str,
    schema: Mapping[str, Any],
    text: str,
    *,
    tool: ToolDefinition,
    domain: str,
) -> Any | None:
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return _extract_enum_value(name, tuple(str(item) for item in enum), text)
    expected_type = str(schema.get("type") or "")
    if expected_type == "integer":
        return _extract_integer_arg(name, text)
    if expected_type == "number":
        return _extract_number_arg(name, text)
    if expected_type != "string":
        return None
    if name == "sidecar":
        return _extract_sidecar(text)
    if name == "hw_id":
        return _extract_hw_id(text)
    if name == "session_id":
        return _extract_log_session_id(text) or _extract_named_string(name, text)
    if name == "mission_id":
        return _extract_mission_id(text) or _extract_named_string(name, text)
    if name == "resource_id":
        return _extract_named_string(name, text, aliases=("context resource", "resource"))
    if name == "tool_id":
        return _extract_named_string(name, text, aliases=("simurgh tool", "tool"))
    if name == "profile_id":
        return _extract_named_string(name, text, aliases=("px4 profile", "parameter profile", "profile"))
    if name == "snapshot_id":
        return _extract_named_string(name, text, aliases=("snapshot", "px4 snapshot"))
    if name == "job_id":
        return _extract_named_string(name, text, aliases=_job_aliases_for(tool=tool, domain=domain))
    if name == "candidate_id":
        return _extract_named_string(name, text, aliases=("fleet candidate", "candidate"))
    if name == "operation_id":
        return _extract_named_string(name, text, aliases=("sitl operation", "operation"))
    if name == "command_id":
        return _extract_named_string(name, text, aliases=("command", "command status"))
    if name == "chunk_id":
        return _extract_named_string(name, text, aliases=("docs chunk", "chunk"))
    return _extract_named_string(name, text)


def _extract_enum_value(name: str, values: tuple[str, ...], text: str) -> str | None:
    if name == "sidecar":
        sidecar = _extract_sidecar(text)
        if sidecar in values:
            return sidecar
    for value in values:
        aliases = {value, value.replace("-", " "), value.replace("_", " ")}
        if any(alias in text for alias in aliases):
            return value
    upper_text = text.upper()
    for value in values:
        if value.upper() in upper_text:
            return value
    return None


def _extract_sidecar(text: str) -> str | None:
    for sidecar, aliases in _SIDECAR_ALIASES.items():
        if _has_any(text, aliases):
            return sidecar
    return None


def _extract_hw_id(text: str) -> str | None:
    patterns = (
        r"\bhw_id\s*(?:=|:|is|#)?\s*([A-Za-z0-9_.:-]+)\b",
        r"\b(?:hw|hardware|node)\s*(?:id|number|#)?\s*[:=]?\s*([A-Za-z0-9_.:-]+)\b",
        r"\b(?:board|drone|vehicle)\s*(?:id|number|#)\s*[:=]?\s*([A-Za-z0-9_.:-]+)\b",
        r"\b(?:board|drone|vehicle)\s+([0-9][A-Za-z0-9_.:-]*)\b",
        r"\bcm4[-_ ]?0*([0-9]+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip(".,;()[]{}")
            if value and value not in _BAD_ARGUMENT_VALUES:
                return value
    return None


def _extract_log_session_id(text: str) -> str | None:
    explicit = _extract_named_string("session_id", text, aliases=("log session", "session"))
    if explicit:
        return explicit
    match = re.search(r"\b(s_[0-9A-Za-z_.-]+)\b", text)
    return match.group(1) if match else None


def _extract_mission_id(text: str) -> str | None:
    explicit = _extract_named_string(
        "mission_id",
        text,
        aliases=("mission id", "sar mission id", "quickscout mission id"),
    )
    if explicit:
        return explicit
    for pattern in (
        rf"\b(?:sar|quickscout|quick scout)\s+mission\s+(?:id\s*)?(?:=|:|is|#)?\s*({_IDENTIFIER_RE})\b",
        rf"\bmission\s+(?:id|number|#)\s*(?:=|:|is)?\s*({_IDENTIFIER_RE})\b",
    ):
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip(".,;()[]{}")
            if value and value not in _BAD_ARGUMENT_VALUES and value not in {"id", "number"}:
                return value
    return None


def _extract_named_string(name: str, text: str, *, aliases: Sequence[str] = ()) -> str | None:
    labels = [name, name.replace("_", " "), name.replace("_id", " id")]
    labels.extend(str(alias) for alias in aliases if str(alias).strip())
    for label in sorted(set(labels), key=len, reverse=True):
        escaped = re.escape(label.casefold())
        label_pattern = rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])"
        patterns = (
            rf"{label_pattern}\s*(?:=|:|is|as|#)\s*({_IDENTIFIER_RE})\b",
            rf"{label_pattern}\s+(?:id|number)\s*(?:=|:|is|as|#)?\s*({_IDENTIFIER_RE})\b",
            rf"{label_pattern}\s+({_IDENTIFIER_RE})\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip(".,;()[]{}")
                if value and value not in _BAD_ARGUMENT_VALUES and value not in {"id", "number"}:
                    return value
    return None


def _extract_integer_arg(name: str, text: str) -> int | None:
    labels = (name, name.replace("_", " "), name.replace("_id", " id"))
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\s*(?:=|:|is|#)?\s*([0-9]+)\b", text)
        if match:
            return int(match.group(1))
    if name == "limit":
        match = re.search(r"\b(?:limit|last|latest|max)\s+([0-9]+)\b", text)
        if match:
            return int(match.group(1))
    if name == "pos_id":
        match = re.search(r"\b(?:position|pos)\s*(?:id|number|#)?\s*([0-9]+)\b", text)
        if match:
            return int(match.group(1))
    return None


def _extract_number_arg(name: str, text: str) -> float | None:
    if name in {"lat", "lon"}:
        lat_lon = _extract_lat_lon(text)
        if lat_lon:
            return lat_lon[0] if name == "lat" else lat_lon[1]
    labels = (name, name.replace("_", " "))
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\s*(?:=|:|is)?\s*(-?[0-9]+(?:\.[0-9]+)?)\b", text)
        if match:
            return float(match.group(1))
    return None


def _extract_lat_lon(text: str) -> tuple[float, float] | None:
    lat = None
    lon = None
    lat_match = re.search(r"\b(?:lat|latitude)\s*(?:=|:|is)?\s*(-?[0-9]+(?:\.[0-9]+)?)\b", text)
    lon_match = re.search(r"\b(?:lon|lng|longitude)\s*(?:=|:|is)?\s*(-?[0-9]+(?:\.[0-9]+)?)\b", text)
    if lat_match:
        lat = float(lat_match.group(1))
    if lon_match:
        lon = float(lon_match.group(1))
    if lat is None or lon is None:
        pair = re.search(r"\b(-?[0-9]+\.[0-9]+)\s*,\s*(-?[0-9]+\.[0-9]+)\b", text)
        if pair:
            lat = float(pair.group(1))
            lon = float(pair.group(2))
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _extract_heading(text: str) -> float | None:
    patterns = (
        r"\b(?:formation\s+)?heading\s*(?:=|:|is|at|of)?\s*(-?[0-9]+(?:\.[0-9]+)?)\b",
        r"\b(-?[0-9]+(?:\.[0-9]+)?)\s*(?:deg|degree|degrees)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = float(match.group(1))
        if 0 <= value < 360:
            return value
    return None


def _job_aliases_for(*, tool: ToolDefinition, domain: str) -> tuple[str, ...]:
    if "sar" in tool.id or domain == "sar":
        return ("sar job", "planning job", "job")
    if "px4" in tool.id:
        return ("px4 job", "patch job", "job")
    if "swarm" in tool.id:
        return ("trajectory job", "process job", "job")
    if "sidecar" in tool.id:
        return ("sidecar job", "job")
    return ("job",)


def _value_matches_schema(value: Any, schema: Mapping[str, Any]) -> bool:
    expected_type = schema.get("type")
    if expected_type == "string" and not isinstance(value, str):
        return False
    if expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return False
    if expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return False
    enum = schema.get("enum")
    if isinstance(enum, list) and enum and value not in enum:
        return False
    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            return False
        if isinstance(max_length, int) and len(value) > max_length:
            return False
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and not re.fullmatch(pattern, value):
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return False
        if isinstance(maximum, (int, float)) and value > maximum:
            return False
    return True


def _argument_summary(arguments: Mapping[str, Any]) -> str:
    if not arguments:
        return "none"
    parts = []
    for key, value in sorted(arguments.items()):
        parts.append(f"{key}={value}")
    return ", ".join(parts[:6])


def _required_args(tool: ToolDefinition) -> tuple[str, ...]:
    schema = tool.input_schema if isinstance(tool.input_schema, Mapping) else {}
    return tuple(str(item) for item in schema.get("required", []) if str(item))


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def _has_direct_action_term(text: str) -> bool:
    for term in _DIRECT_ACTION_TERMS:
        if term == "command" and _looks_like_command_tracker_read(text):
            continue
        if term == "launch" and _looks_like_launch_metadata_read(text):
            continue
        if " " in term:
            if term in text:
                return True
            continue
        if re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", text):
            return True
    return False


def _looks_like_command_tracker_read(text: str) -> bool:
    return _has_any(
        text,
        (
            "active command",
            "command history",
            "command policy",
            "command statistics",
            "command status",
            "command tracker",
            "commands active",
            "precision move policy",
            "recent command",
            "read command",
            "show command",
        ),
    )


def _looks_like_launch_metadata_read(text: str) -> bool:
    return _has_any(
        text,
        (
            "launch geometry",
            "launch mode",
            "launch origin",
            "launch position",
            "launch positions",
            "launch site",
            "mission origin",
        ),
    )


def _result_highlights(result: ReadOnlyToolCallResult) -> str:
    if result.structured_content is None:
        return _compact_text(result.text)
    return _preview_value(result.structured_content)


def _result_evidence_summary(result: ReadOnlyToolCallResult) -> str:
    metadata = result.evidence_metadata()
    items = metadata.get("items") if isinstance(metadata, Mapping) else None
    first = items[0] if isinstance(items, list) and items and isinstance(items[0], Mapping) else {}
    summary = str(first.get("summary") or "").strip() if isinstance(first, Mapping) else ""
    if summary:
        return summary
    return _result_highlights(result)


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
        for key in (
            "id",
            "hw_id",
            "sidecar",
            "transport",
            "session_id",
            "mission_id",
            "name",
            "status",
            "state",
            "label",
            "level",
            "component",
            "message",
        ):
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

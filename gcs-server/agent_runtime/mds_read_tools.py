"""Curated read-only MDS context tools for Simurgh assistant turns.

The functions in this module do not submit GCS commands. Most answers summarize
GCS-owned state; log/ULog answers may also use GCS-proxied drone read endpoints
that return metadata or derived metrics without exposing raw artifacts.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

import yaml
from fastapi import HTTPException
from mds_logging.api_schemas import UlogActionCorrelation, UlogCorrelationEvidence

from src.enums import Mission, State
from src.ulog_proxy_policy import (
    drone_ulog_proxy_timeout_seconds,
    drone_ulog_summary_timeout_seconds,
)
from request_logging import is_routine_auth_noise_path

from .answer_composer import AnswerComposer
from .evidence import ReadOnlyEvidenceBundle
from .geography import (
    COUNTRY_LOOKUP_DISCLAIMER,
    COUNTRY_LOOKUP_TOOL_ID,
    extract_latitude_longitude,
    format_country_resolution,
    resolve_country,
)
from .models import AgentRuntimeError, utc_now
from .query_adaptation import normalize_matching_text, normalize_operator_query_text
from .query_understanding import build_assistant_query_plan, looks_like_public_upstream_reference_query
from .target_grounding import refers_to_contextual_target


REPO_ROOT = Path(__file__).resolve().parents[2]
READ_TOOL_PROVIDER = "mds-tools"
READ_TOOL_MODEL = "local-read-only"
READ_TOOL_ADAPTER_VERSION = "mds-read-tools-v1"
DEFAULT_OPENAI_CHAT_MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5")
DEFAULT_OPENAI_API_KEY_FILE = Path("/etc/mds/secrets/openai_api_key")
DEFAULT_GENERAL_KNOWLEDGE_CONFIG_PATH = REPO_ROOT / "config" / "agent_general_knowledge.yaml"
DEFAULT_PUBLIC_PLACES_CONFIG_PATH = REPO_ROOT / "config" / "agent_public_places.yaml"
MCP_ENDPOINT_PATH = "/api/v1/simurgh/mcp"
MCP_RESOURCE_URL_ENV = "MDS_MCP_RESOURCE_URL"
DRONE_LOG_PROXY_TIMEOUT_SECONDS = 2.5
DEFAULT_DRONE_LOG_EVIDENCE_DEADLINE_SECONDS = 45.0
DEFAULT_DRONE_LOG_MAX_WORKERS = 4
DRONE_LOG_WARNING_SAMPLE_LIMIT = 3
_DRONE_LOG_EVIDENCE_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None
_DRONE_LOG_EVIDENCE_EXECUTOR_LOCK = threading.Lock()
ULOG_COMMAND_CORRELATION_TOLERANCE_SECONDS = 30.0
MAV_RESULT_NON_FAILURE_CODES = frozenset({0, 5})  # ACCEPTED, IN_PROGRESS
FALLBACK_LOG_STALE_GRACE_SECONDS = 3600
LATEST_SESSION_GROUP_SECONDS = 15
QUICKSCOUT_FIELD_READY_STALE_SECONDS = 6 * 3600
QUICKSCOUT_IMPLAUSIBLE_AREA_SQ_M = 1_000_000_000.0
QUICKSCOUT_IMPLAUSIBLE_DURATION_S = 8 * 3600.0
READ_CONVERSATION_TOPICS = frozenset(
    {
        "capabilities",
        "docs",
        "drone_show",
        "flight",
        "fleet",
        "general",
        "logs",
        "mcp",
        "public_geography",
        "runtime",
        "safety",
        "sar",
        "setup",
        "sitl",
        "swarm",
        "ui",
    }
)


def _drone_log_evidence_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _DRONE_LOG_EVIDENCE_EXECUTOR
    with _DRONE_LOG_EVIDENCE_EXECUTOR_LOCK:
        if _DRONE_LOG_EVIDENCE_EXECUTOR is None:
            _DRONE_LOG_EVIDENCE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=DEFAULT_DRONE_LOG_MAX_WORKERS,
                thread_name_prefix="simurgh-log-evidence",
            )
        return _DRONE_LOG_EVIDENCE_EXECUTOR
READ_RESPONSE_MODES = frozenset({"status", "interpret", "workflow", "compare", "capability", "clarify"})
READ_ONLY_ACTION_POSTURE = "read-only-local; no action, upload, config mutation, or raw artifact exposure"

# Minimum evidence contracts for locally grounded intents. Execution records the
# actual tools and provider-selected additions separately.
LOCAL_INTENT_TOOL_IDS: Mapping[str, tuple[str, ...]] = {
    "action_capability": ("mds.simurgh.policy.read", "mds.simurgh.tools.read"),
    "add_drone_workflow": (
        "mds.config.fleet.read",
        "mds.docs.search",
        "mds.docs.chunk.read",
    ),
    "autopilot_support": ("simurgh.general_knowledge.read", "mds.docs.search"),
    "backend_log_summary": ("mds.logs.sessions.read", "mds.logs.sources.read"),
    "board_setup_help": ("mds.docs.search", "mds.system.env_registry.read"),
    "capability_catalog": ("mds.simurgh.tools.read", "mds.simurgh.policy.read"),
    "command_summary": ("mds.commands.active.read", "mds.commands.recent.read", "mds.commands.statistics.read"),
    "companion_setup_help": ("mds.docs.search", "mds.docs.chunk.read"),
    "coordinate_geography": (COUNTRY_LOOKUP_TOOL_ID,),
    "docs_help": ("mds.docs.search", "mds.docs.chunk.read"),
    "drone_log_summary": (
        "mds.logs.drone_sessions.read",
        "mds.logs.drone_ulog_files.read",
        "mds.logs.drone_ulog_summary.read",
        "mds.logs.drone_session.read",
    ),
    "environment_summary": ("mds.system.env_registry.read", "mds.system.env_gcs.read"),
    "fleet_connectivity": ("mds.fleet.heartbeats.read", "mds.fleet.telemetry.read", "mds.fleet.network_status.read"),
    "fleet_status": ("mds.fleet.heartbeats.read", "mds.fleet.telemetry.read", "mds.fleet.network_status.read"),
    "fleet_sitl_summary": (
        "mds.config.fleet.read",
        "mds.fleet.heartbeats.read",
        "mds.fleet.telemetry.read",
        "mds.fleet.network_status.read",
        "mds.sitl.instances.read",
        "mds.sitl.policy.read",
    ),
    "fleet_enrollment_summary": ("mds.fleet.candidates.read",),
    "fleet_summary": ("mds.config.fleet.read", "mds.config.positions.read", "mds.config.swarm.read"),
    "general_knowledge": ("simurgh.general_knowledge.read",),
    "git_status_summary": ("mds.git.status.read",),
    "mission_mode_comparison": (
        "simurgh.general_knowledge.read",
        "mds.docs.search",
        "mds.docs.chunk.read",
    ),
    "node_boot_status": ("mds.fleet.node_boot_status.read",),
    "operator_help": ("mds.docs.search", "mds.docs.chunk.read"),
    "origin_status": ("mds.origin.read", "mds.navigation.global_origin.read", "mds.config.positions.read"),
    "public_geography": ("simurgh.public_places.read", "simurgh.geodesy.calculate"),
    "px4_params_summary": ("mds.px4_params.policy.read", "mds.px4_params.profiles.read"),
    "sar_summary": (
        "mds.sar.missions.read",
        "mds.sar.mission.status.read",
        "mds.sar.mission.workspace.read",
        "mds.sar.findings.read",
    ),
    "registry_domain_tool_summary": ("mds.simurgh.tools.read", "mds.simurgh.policy.read"),
    "runtime_summary": ("mds.system.runtime_status.read",),
    "show_modes_help": ("mds.docs.search", "mds.docs.chunk.read", "mds.shows.skybrush.read"),
    "show_summary": (
        "mds.shows.skybrush.read",
        "mds.shows.custom.read",
        "mds.shows.skybrush.metrics_snapshot.read",
        "mds.shows.skybrush.validation.read",
    ),
    "show_upload_help": ("mds.docs.search", "mds.shows.skybrush.read"),
    "sidecar_status": (
        "mds.fleet.sidecars.read",
        "mds.fleet.sidecar.read",
        "mds.fleet.network_details.read",
        "mds.fleet.sidecars.connectivity_profile.read",
    ),
    "sitl_help": ("mds.docs.search", "mds.system.runtime_status.read"),
    "sitl_status": ("mds.sitl.instances.read", "mds.sitl.policy.read"),
    "swarm_readiness": (
        "mds.config.swarm.read",
        "mds.config.positions.read",
        "mds.fleet.heartbeats.read",
        "mds.fleet.telemetry.read",
        "mds.swarm_trajectories.status.read",
        "mds.swarm_trajectories.validate.read",
    ),
    "swarm_topology": ("mds.config.swarm.read", "mds.config.positions.read"),
    "system_status": ("mds.system.health.read", "mds.system.runtime_status.read", "mds.simurgh.status.read"),
}

# The provider may select one of these stable, local evidence intents during
# semantic routing. The model never receives runtime evidence and cannot call
# the tools directly; this contract only replaces brittle prose re-parsing.
PROVIDER_READ_INTENT_DESCRIPTIONS: Mapping[str, str] = {
    "previous_action_summary": "Verify what the current session's latest guarded action plan actually executed, including waits and ordered steps.",
    "fleet_connectivity": "Read current vehicle presence, heartbeat, telemetry freshness, and network reachability.",
    "fleet_status": "Read the current vehicle flight-state snapshot: presence, telemetry freshness, arm and preflight state, flight mode, system status, GPS, battery, and altitude; include position only when requested.",
    "fleet_summary": "Read configured fleet identities, positions, and swarm assignments.",
    "fleet_sitl_summary": "Read configured fleet count together with current SITL instance, active-container, Docker, and policy state.",
    "runtime_summary": "Read current GCS mode and Simurgh runtime posture.",
    "sitl_status": "Read current SITL instance inventory, active count, Docker availability, and SITL policy.",
    "system_status": "Read GCS service and host health.",
    "command_summary": "Read active and recent command tracker state.",
    "coordinate_geography": "Resolve an explicit WGS84 latitude/longitude pair to an approximate country using local offline boundary data.",
    "drone_log_summary": "Read per-drone log sessions, onboard ULog inventory, and derived newest-ULog summaries.",
    "backend_log_summary": "Read warning and error evidence from unified GCS logs.",
    "origin_status": "Read the configured mission/global origin and launch-position state. This is not live vehicle telemetry and must only be selected when the operator asks about origin or launch configuration.",
}

DRONE_LOG_READ_OPTIONS_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verify_operation": {"type": "boolean"},
        "include_unified_logs": {"type": "boolean"},
        "analyze_latest_ulog": {"type": "boolean"},
    },
    "required": [
        "verify_operation",
        "include_unified_logs",
        "analyze_latest_ulog",
    ],
}


@dataclass(frozen=True)
class DroneLogReadOptions:
    """Structured evidence depth selected by semantic provider routing."""

    verify_operation: bool = False
    include_unified_logs: bool = False
    analyze_latest_ulog: bool = False

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object] | None,
    ) -> "DroneLogReadOptions":
        source = value if isinstance(value, Mapping) else {}
        def flag(name: str) -> bool:
            raw = source.get(name)
            return raw if isinstance(raw, bool) else False

        return cls(
            verify_operation=flag("verify_operation"),
            include_unified_logs=flag("include_unified_logs"),
            analyze_latest_ulog=flag("analyze_latest_ulog"),
        )


@dataclass(frozen=True)
class _DroneLogBaseEvidence:
    """One drone's bounded inventory and latest-session evidence."""

    hw_id: int
    ip: str
    sessions: tuple[dict[str, Any], ...] = ()
    session_error: str = ""
    warning_error_count: int | None = None
    warning_error_label: str = "not checked"
    warning_error_detail: str = ""
    warning_error_samples: tuple[dict[str, str], ...] = ()
    ulog_files: tuple[dict[str, Any], ...] = ()
    ulog_error: str = ""


def _normalize_response_detail(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"brief", "standard", "detailed"} else "standard"


_BRIEF_STATUS_INTENTS = frozenset(
    {
        "command_summary",
        "coordinate_geography",
        "fleet_connectivity",
        "fleet_status",
        "origin_status",
        "runtime_summary",
        "sitl_status",
        "system_status",
    }
)


def infer_mds_response_detail(message: str, *, intent: str | None = None) -> str:
    """Infer a bounded operator-facing detail level from the requested result."""

    normalized = _normalize_text(message)
    if _has_any(
        normalized,
        (
            "full detail",
            "full details",
            "detailed",
            "all fields",
            "all evidence",
            "raw evidence",
            "deep analysis",
            "comprehensive",
        ),
    ):
        return "detailed"
    if _has_any(
        normalized,
        (
            "brief",
            "briefly",
            "short",
            "shorter",
            "concise",
            "summary only",
            "just the answer",
        ),
    ):
        return "brief"
    return "brief" if str(intent or "").strip() in _BRIEF_STATUS_INTENTS else "standard"


def reconcile_mds_response_detail(
    message: str,
    *,
    intent: str | None = None,
    provider_detail: str | None = None,
) -> str:
    """Combine local operator intent with an optional provider detail hint."""

    local_detail = infer_mds_response_detail(message, intent=intent)
    provider_value = _normalize_response_detail(provider_detail or "")
    if local_detail == "detailed":
        return "detailed"
    if local_detail == "brief" or provider_value == "brief":
        return "brief"
    # A provider cannot expand a simple operator request to detailed output
    # unless the operator asked for that detail in the original turn.
    return "standard"


_REDUNDANT_STATUS_LINES = frozenset(
    {
        "No action was executed.",
        "No drone command was sent.",
        "No SITL or drone action was executed.",
        "No action was executed; raw ULog content was not exposed.",
    }
)


def _compact_operator_status(content: str) -> str:
    """Keep status prose concise while retaining safety facts in trace metadata."""

    compacted: list[str] = []
    for raw_line in str(content or "").splitlines():
        stripped = raw_line.strip()
        if stripped in _REDUNDANT_STATUS_LINES:
            continue
        for suffix in (
            " No drone command was sent.",
            " No action was executed.",
        ):
            if stripped.endswith(suffix):
                raw_line = raw_line[: -len(suffix)].rstrip()
                break
        compacted.append(raw_line)
    return "\n".join(compacted).strip()


def provider_read_intent_contracts() -> tuple[dict[str, Any], ...]:
    """Return the bounded semantic read menu used by the provider router."""

    contracts: list[dict[str, Any]] = []
    virtual_intents = ("previous_action_summary",)
    for intent in (*virtual_intents, *LOCAL_INTENT_TOOL_IDS):
        if any(item["id"] == intent for item in contracts):
            continue
        contract = {
            "id": intent,
            "description": PROVIDER_READ_INTENT_DESCRIPTIONS.get(
                intent,
                intent.replace("_", " "),
            ),
            "tool_ids": list(provider_read_intent_tool_ids(intent) or ()),
        }
        if intent == "drone_log_summary":
            contract["options_schema"] = dict(DRONE_LOG_READ_OPTIONS_SCHEMA)
        contracts.append(contract)
    return tuple(contracts)


def provider_read_intent_options_schema() -> dict[str, Any]:
    """Return strict provider output options keyed by read intent."""

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "drone_log_summary": {
                "anyOf": [
                    dict(DRONE_LOG_READ_OPTIONS_SCHEMA),
                    {"type": "null"},
                ]
            }
        },
        "required": ["drone_log_summary"],
    }


def provider_read_intent_tool_ids(intent: str) -> tuple[str, ...] | None:
    """Resolve a provider-selected read intent to local evidence tools."""

    normalized = str(intent or "").strip()
    if normalized in {"previous_action_summary"}:
        return ()
    tool_ids = LOCAL_INTENT_TOOL_IDS.get(normalized)
    return tuple(tool_ids) if tool_ids is not None else None


FLEET_LIVE_TERMS = (
    "arm",
    "armed",
    "arming",
    "battery",
    "connected",
    "connect",
    "online",
    "offline",
    "heartbeat",
    "telemetry",
    "reachable",
    "streaming",
    "link quality",
    "network link",
    "live",
    "gps",
    "coordinate",
    "coordinates",
    "lat",
    "latitude",
    "long",
    "longitude",
    "alt",
    "altitude",
    "location",
    "country",
    "where are",
    "where is",
    "boards",
    "board",
    "cm4",
    "companion",
    "vehicle",
    "vehicles",
    "voltage",
    "ready to arm",
    "flight mode",
    "system status",
    "status report",
    "report of status",
    "health",
    "failsafe",
    "ready",
    "readiness",
    "ready to fly",
    "flight ready",
    "fly ready",
    "preflight",
    "pre-flight",
)
FLEET_POSITION_TERMS = (
    "gps",
    "coordinate",
    "coordinates",
    "lat",
    "latitude",
    "long",
    "longitude",
    "alt",
    "altitude",
    "location",
    "country",
    "where are",
    "where is",
)
FLEET_HEALTH_TERMS = (
    "arm",
    "armed",
    "arming",
    "battery",
    "voltage",
    "ready to arm",
    "flight mode",
    "mode",
    "system status",
    "status",
    "status report",
    "report of status",
    "health",
    "failsafe",
    "ready",
    "readiness",
    "ready to fly",
    "flight ready",
    "fly ready",
    "preflight",
    "pre-flight",
)

REGISTRY_DOMAIN_LABELS: Mapping[str, str] = {
    "commands": "GCS command tracker",
    "config": "fleet/swarm configuration",
    "docs": "MDS documentation retrieval",
    "fleet": "fleet telemetry, boards, and sidecars",
    "git": "repository sync/status",
    "logs": "GCS logs and diagnostics",
    "operator": "local operator guidance",
    "origin": "origin and launch-position evidence",
    "px4_params": "PX4 parameter evidence",
    "sar": "QuickScout/SAR missions",
    "shows": "Drone Show/SkyBrush assets",
    "simurgh": "Simurgh runtime, MCP, and audit",
    "sitl": "SITL simulation control state",
    "swarm_trajectories": "swarm trajectory planning state",
    "system": "GCS system/runtime/environment",
}

QUERY_DOMAIN_TO_REGISTRY_DOMAINS: Mapping[str, tuple[str, ...]] = {
    "capabilities": ("simurgh", "docs", "operator"),
    "docs": ("docs", "simurgh"),
    "drone_show": ("shows", "swarm_trajectories", "origin"),
    "fleet": ("fleet", "config"),
    "logs": ("logs",),
    "mcp": ("simurgh", "docs", "operator"),
    "runtime": ("system", "simurgh"),
    "safety": ("commands", "origin", "px4_params", "simurgh"),
    "sar": ("sar",),
    "setup": ("fleet", "system", "docs", "simurgh"),
    "sitl": ("sitl",),
    "swarm": ("swarm_trajectories", "config", "origin"),
    "ui": ("simurgh", "docs"),
}

@dataclass(frozen=True)
class MdsReadToolAnswer:
    """Assistant-ready result from a local read-only MDS tool."""

    intent: str
    content: str
    tool_ids: tuple[str, ...]
    safety_notes: tuple[str, ...]
    response_mode: str = "status"
    evidence: ReadOnlyEvidenceBundle | None = None

    @property
    def turn_id(self) -> str:
        return f"turn-{uuid.uuid4().hex}"

    def evidence_metadata(self) -> dict[str, Any] | None:
        return self.evidence.public_metadata() if self.evidence is not None else None


@dataclass(frozen=True)
class MdsReadOnlyPlan:
    """Public-safe plan for one local read-only Simurgh advisory turn."""

    intent: str | None
    response_mode: str
    topic: str | None
    query_domain: str
    confidence: float
    unclear: bool
    reason: str
    tool_ids: tuple[str, ...]
    missing_arguments: tuple[str, ...]
    execution_layer: str
    safety_posture: str

    def public_metadata(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "response_mode": self.response_mode,
            "topic": self.topic,
            "query_domain": self.query_domain,
            "confidence": round(float(self.confidence), 3),
            "unclear": self.unclear,
            "reason": self.reason,
            "tool_ids": list(self.tool_ids),
            "missing_arguments": list(self.missing_arguments),
            "execution_layer": self.execution_layer,
            "safety_posture": self.safety_posture,
        }


def classify_mds_read_intent(message: str, *, conversation_topic: str | None = None) -> str | None:
    """Return the read-only tool intent that best matches an operator prompt."""

    normalized = _normalize_text(message)
    topic = _normalize_conversation_topic(conversation_topic)
    if not normalized:
        return None
    if _looks_like_previous_answer_transform(normalized):
        return None
    if looks_like_public_upstream_reference_query(normalized):
        return "general_knowledge"
    if _looks_like_weather_question(normalized) or _looks_like_general_knowledge_question(normalized):
        return "general_knowledge"
    if _looks_like_coordinate_country_question(normalized):
        return "coordinate_geography"
    if _looks_like_public_geography_question(normalized):
        return "public_geography"
    if _looks_like_px4_params_question(normalized):
        return "px4_params_summary"
    if _looks_like_autopilot_support_question(normalized):
        return "autopilot_support"
    # Resolve anaphoric live-state questions against the typed session topic
    # before treating latitude/longitude vocabulary as unrelated public
    # geography. The provider may enrich a result, but it must not replace a
    # current vehicle position with configured origin state.
    # Explicit boot/init and git-sync language is a stronger domain signal than
    # the previous setup topic. Keep it on the node-status contract instead of
    # letting contextual enrollment help reinterpret the question as guidance.
    if _looks_like_node_boot_status_question(normalized):
        return "node_boot_status"
    contextual_intent = _intent_from_contextual_followup(normalized, topic)
    if contextual_intent:
        return contextual_intent
    if _looks_like_non_mds_general_question(normalized):
        return None

    if _looks_like_action_capability_question(normalized):
        return "action_capability"
    if _looks_like_registry_domain_tool_question(normalized, topic=topic):
        return "registry_domain_tool_summary"
    if _looks_like_sidecar_status_question(normalized):
        return "sidecar_status"
    if _looks_like_mds_fleet_evidence_request(normalized):
        return "fleet_connectivity"

    if _looks_like_add_drone_enrollment_workflow_question(normalized):
        return "add_drone_workflow"
    if _looks_like_fleet_enrollment_workflow_question(normalized):
        return "board_setup_help"

    if topic == "logs" and _looks_like_contextual_log_followup(normalized):
        if _looks_like_drone_log_summary_question(normalized):
            return "drone_log_summary"
        return "backend_log_summary"
    if topic == "drone_show" and _looks_like_contextual_show_followup(normalized):
        return "show_summary"
    if _looks_like_compound_fleet_sitl_state_question(normalized):
        return "fleet_sitl_summary"
    if _looks_like_sitl_vehicle_readiness_question(normalized, conversation_topic=topic):
        return "fleet_connectivity"
    # Prefer the most evidence-rich intent when a request spans command
    # tracking and flight logs. The drone-log answer already composes command
    # evidence and can additionally inspect ULogs; the inverse is not true.
    if _looks_like_drone_log_summary_question(normalized):
        return "drone_log_summary"
    if _looks_like_command_summary_question(normalized):
        return "command_summary"
    if _looks_like_git_status_question(normalized):
        return "git_status_summary"
    if _looks_like_origin_status_question(normalized):
        return "origin_status"
    if _looks_like_fleet_enrollment_question(normalized):
        return "fleet_enrollment_summary"
    if _looks_like_system_status_question(normalized):
        return "system_status"
    if _looks_like_environment_summary_question(normalized):
        return "environment_summary"
    if _has_any(normalized, ("log", "logs", "warning", "warnings", "error", "errors", "backend")) and _has_any(
        normalized,
        ("check", "see", "show", "what", "which", "any", "have", "list", "summary"),
    ):
        return "backend_log_summary"
    if _looks_like_sitl_vehicle_readiness_question(normalized, conversation_topic=topic):
        return "fleet_connectivity"
    if _has_any(normalized, ("sitl", "simulation", "simulator")) and _has_any(
        normalized,
        ("how", "go to", "switch", "change", "create", "demo", "setup", "runtime", "mode", "read", "link", "doc", "guide"),
    ):
        return "sitl_help"
    if _looks_like_companion_setup_question(normalized):
        return "companion_setup_help"
    if _looks_like_add_drone_workflow_question(normalized):
        return "add_drone_workflow"
    if _looks_like_mission_mode_question(normalized):
        return "mission_mode_comparison"
    if _looks_like_sar_status_question(normalized):
        return "sar_summary"
    if _looks_like_show_modes_question(normalized):
        return "show_modes_help"
    if _looks_like_show_status_question(normalized):
        return "show_summary"
    if _looks_like_show_upload_help_question(normalized):
        return "show_upload_help"
    docs_requested = _has_any(normalized, ("doc", "docs", "documentation", "guide", "read about", "manual")) or (
        _has_any(normalized, ("link",))
        and _has_any(normalized, ("read", "setup", "sitl", "board", "guide", "where", "doc", "docs", "manual"))
    )
    if docs_requested:
        if _has_any(normalized, ("sitl", "simulation", "simulator", "demo")):
            return "sitl_help"
        if _looks_like_companion_setup_question(normalized):
            return "companion_setup_help"
        if _has_any(
            normalized,
            ("board", "node", "cm4", "environment", "env", "key", "keys", "setup", "onboard", "enroll", "provision", "fleet"),
        ):
            return "board_setup_help"
        return "docs_help"

    if _looks_like_mcp_client_setup_question(normalized):
        return "capability_catalog"

    if _has_any(
        normalized,
        (
            "should i",
            "should we",
            "what should",
            "safest diagnostic",
            "diagnostic path",
            "verify first",
            "previous assistant prompts",
            "drone-local api",
            "directly through mcp",
            "incident",
            "troubleshoot",
            "diagnose",
            "diagnostic",
            "root cause",
            "safe reusable advisory eval",
            "field log",
            "mav1_config",
            "qgc-disconnected",
            "parameter changes",
        ),
    ):
        return None

    if _has_any(normalized, ("where", "how", "edit", "change", "configure", "set")) and _has_any(
        normalized,
        ("swarm offset", "offset", "formation", "cluster", "follow"),
    ):
        return "operator_help"
    show_requested = _has_any(normalized, ("drone show", "skybrush", "custom show")) or (
        _has_any(normalized, ("show",))
        and _has_any(normalized, ("duration", "length", "loaded", "planned", "active", "package"))
    )
    if show_requested:
        return "show_summary"
    if _looks_like_swarm_readiness_question(normalized):
        return "swarm_readiness"
    if _looks_like_live_fleet_state_question(normalized):
        return "fleet_connectivity"
    if _has_any(normalized, ("swarm", "formation", "cluster", "offset", "follow", "geometry", "distance")):
        return "swarm_topology"
    if _has_any(normalized, ("how many drones", "fleet", "drone", "drones", "ip of", "what is the ip")) or (
        _has_any(normalized, ("configured",))
        and _has_any(normalized, ("fleet", "drone", "drones", "board", "boards", "vehicle", "vehicles"))
    ):
        return "fleet_summary"
    if _has_any(
        normalized,
        ("capability", "capabilities", "tool", "tools", "api", "apis", "mcp", "menu", "can you do", "what can"),
    ) and _has_any(
        normalized,
        ("simurgh", "agent", "assistant", "mcp", "tool", "tools", "api", "apis", "menu", "expose", "available"),
    ):
        return "capability_catalog"
    if _has_any(normalized, ("simurgh", "mcp", "provider", "model", "circuit breaker", "always confirm", "runtime", "gcs mode")) and _has_any(
        normalized,
        ("what", "which", "status", "current", "selected", "enabled", "mode", "show", "is", "are"),
    ):
        return "runtime_summary"
    return _intent_from_query_plan(normalized, topic)

def answer_mds_read_only_question(
    message: str,
    *,
    deps: Any | None = None,
    conversation_topic: str | None = None,
    intent_override: str | None = None,
    target_drone_ids: Sequence[str] = (),
    action_context: Mapping[str, Any] | None = None,
    response_detail: str = "standard",
    read_options: Mapping[str, Mapping[str, object]] | None = None,
    actor_role: str | None = "operator",
) -> MdsReadToolAnswer | None:
    """Answer an MDS prompt using only local read-only GCS context."""

    plan = build_mds_read_only_plan(message, conversation_topic=conversation_topic)
    requested_intent = str(intent_override or "").strip()
    intent = requested_intent or plan.intent
    if requested_intent and provider_read_intent_tool_ids(requested_intent) is None:
        return None
    if intent is None:
        return None

    response_mode = plan.response_mode
    normalized_detail = _normalize_response_detail(response_detail)
    tools = MdsReadOnlyTools(deps=deps, actor_role=actor_role)
    if intent == "fleet_summary":
        return tools.fleet_summary(message)
    if intent == "fleet_sitl_summary":
        return tools.fleet_sitl_summary(message=message, response_detail=normalized_detail)
    if intent == "fleet_connectivity":
        return tools.fleet_connectivity(
            message=message,
            target_drone_ids=target_drone_ids,
            response_detail=normalized_detail,
        )
    if intent == "fleet_status":
        return tools.fleet_connectivity(
            message=message,
            detail_profile="full" if _wants_fleet_position_details(_normalize_text(message)) else "health",
            target_drone_ids=target_drone_ids,
            response_detail=normalized_detail,
        )
    if intent == "fleet_enrollment_summary":
        return tools.fleet_enrollment_summary(message=message)
    if intent == "swarm_topology":
        return tools.swarm_topology()
    if intent == "mission_mode_comparison":
        return tools.mission_mode_comparison()
    if intent == "show_summary":
        return tools.show_summary(response_mode=response_mode, message=message)
    if intent == "show_modes_help":
        return tools.show_modes_help()
    if intent == "show_upload_help":
        return tools.show_upload_help()
    if intent == "operator_help":
        return tools.operator_help(message)
    if intent == "capability_catalog":
        return tools.capability_catalog()
    if intent == "runtime_summary":
        return tools.runtime_summary()
    if intent == "sitl_help":
        return tools.sitl_help()
    if intent == "sitl_status":
        return tools.sitl_status(response_detail=normalized_detail)
    if intent == "swarm_readiness":
        return tools.swarm_readiness(message)
    if intent == "sar_summary":
        return tools.sar_summary(message=message)
    if intent == "board_setup_help":
        return tools.board_setup_help()
    if intent == "companion_setup_help":
        return tools.companion_setup_help()
    if intent == "add_drone_workflow":
        return tools.add_drone_workflow_help()
    if intent == "docs_help":
        return tools.docs_help()
    if intent == "backend_log_summary":
        return tools.backend_log_summary(response_mode=response_mode, message=message)
    if intent == "drone_log_summary":
        return tools.drone_log_summary(
            message=message,
            target_drone_ids=target_drone_ids,
            action_context=action_context,
            response_detail=normalized_detail,
            read_options=(
                read_options.get("drone_log_summary")
                if isinstance(read_options, Mapping)
                and isinstance(read_options.get("drone_log_summary"), Mapping)
                else None
            ),
        )
    if intent == "action_capability":
        return tools.action_capability(message)
    if intent == "registry_domain_tool_summary":
        return tools.registry_domain_tool_summary(message)
    if intent == "system_status":
        return tools.system_status()
    if intent == "environment_summary":
        return tools.environment_summary()
    if intent == "sidecar_status":
        return tools.sidecar_status()
    if intent == "px4_params_summary":
        return tools.px4_params_summary()
    if intent == "origin_status":
        return tools.origin_status()
    if intent == "command_summary":
        return tools.command_summary(message=message, action_context=action_context)
    if intent == "node_boot_status":
        return tools.node_boot_status(message=message)
    if intent == "git_status_summary":
        return tools.git_status_summary(message=message)
    if intent == "general_knowledge":
        return tools.general_knowledge(message)
    if intent == "coordinate_geography":
        return tools.coordinate_geography(message)
    if intent == "public_geography":
        return tools.public_geography(message)
    if intent == "autopilot_support":
        return tools.autopilot_support()
    return None


def infer_mds_read_topic(message: str, *, intent: str | None = None) -> str | None:
    """Infer a safe short-lived conversation topic for follow-up routing."""

    normalized_intent = str(intent or classify_mds_read_intent(message) or "").strip()
    if normalized_intent in {"show_summary", "show_modes_help", "show_upload_help"}:
        return "drone_show"
    if normalized_intent in {"fleet_summary", "fleet_connectivity", "fleet_status", "fleet_sitl_summary"}:
        return "fleet"
    if normalized_intent == "fleet_enrollment_summary":
        return "setup"
    if normalized_intent in {"swarm_readiness", "swarm_topology", "operator_help", "mission_mode_comparison"}:
        return "swarm"
    if normalized_intent == "sar_summary":
        return "sar"
    if normalized_intent == "sitl_help":
        return "sitl"
    if normalized_intent in {"board_setup_help", "companion_setup_help", "add_drone_workflow"}:
        return "setup"
    if normalized_intent in {"backend_log_summary", "drone_log_summary"}:
        return "logs"
    if normalized_intent in {"runtime_summary", "system_status", "environment_summary"}:
        return "runtime"
    if normalized_intent == "sidecar_status":
        return "setup"
    if normalized_intent == "px4_params_summary":
        return "safety"
    if normalized_intent == "origin_status":
        return "drone_show"
    if normalized_intent == "command_summary":
        return "safety"
    if normalized_intent == "node_boot_status":
        return "setup"
    if normalized_intent == "git_status_summary":
        return "setup"
    if normalized_intent == "capability_catalog":
        return "capabilities"
    if normalized_intent == "registry_domain_tool_summary":
        return "capabilities"
    if normalized_intent in {"coordinate_geography", "public_geography"}:
        return "public_geography"
    if normalized_intent in {"general_knowledge", "autopilot_support"}:
        return "general"
    return None


def infer_mds_response_mode(
    message: str,
    *,
    conversation_topic: str | None = None,
    intent: str | None = None,
) -> str:
    """Infer how the assistant should use the selected evidence source."""

    normalized = _normalize_text(message)
    topic = _normalize_conversation_topic(conversation_topic)
    normalized_intent = str(intent or classify_mds_read_intent(message, conversation_topic=topic) or "").strip()
    if not normalized:
        return "status"
    if _looks_like_interpretation_followup(normalized, topic=topic):
        return "interpret"
    if normalized_intent in {"mission_mode_comparison"}:
        return "compare"
    if normalized_intent in {
        "show_upload_help",
        "sitl_help",
        "swarm_readiness",
        "board_setup_help",
        "companion_setup_help",
        "add_drone_workflow",
        "operator_help",
    }:
        return "workflow"
    if normalized_intent in {"action_capability", "capability_catalog", "registry_domain_tool_summary"}:
        return "capability"
    if normalized_intent == "general_knowledge":
        return "interpret"
    return "status"


def build_mds_read_only_plan(message: str, *, conversation_topic: str | None = None) -> MdsReadOnlyPlan:
    """Build the sanitized local read-only plan used before advisory execution."""

    normalized_topic = _normalize_conversation_topic(conversation_topic)
    query_plan = build_assistant_query_plan(message, conversation_topic=normalized_topic)
    intent = classify_mds_read_intent(message, conversation_topic=normalized_topic)
    response_mode = (
        infer_mds_response_mode(message, conversation_topic=normalized_topic, intent=intent)
        if intent
        else query_plan.response_mode
    )
    topic = infer_mds_read_topic(message, intent=intent) if intent else None
    if not topic and query_plan.domain in READ_CONVERSATION_TOPICS:
        topic = query_plan.domain
    execution_layer = "local_advisory" if intent else "provider_or_clarify"
    normalized_message = _normalize_text(message)
    tool_ids = LOCAL_INTENT_TOOL_IDS.get(str(intent or ""), ())
    if _looks_like_compound_fleet_sitl_state_question(normalized_message):
        configured_requested = _has_domain_signal(normalized_message, ("configured", "defined", "inventory"))
        live_requested = _looks_like_live_fleet_count_state_question(normalized_message)
        if configured_requested and live_requested:
            tool_ids = (
                "mds.config.fleet.read",
                "mds.fleet.heartbeats.read",
                "mds.sitl.instances.read",
                "mds.sitl.policy.read",
            )
        elif live_requested:
            tool_ids = (
                "mds.fleet.heartbeats.read",
                "mds.fleet.telemetry.read",
                "mds.sitl.instances.read",
                "mds.sitl.policy.read",
            )
        else:
            tool_ids = (
                "mds.config.fleet.read",
                "mds.sitl.instances.read",
                "mds.sitl.policy.read",
            )
    return MdsReadOnlyPlan(
        intent=intent,
        response_mode=response_mode if response_mode in READ_RESPONSE_MODES else "status",
        topic=topic,
        # A complete typed local intent owns its evidence domain. The broader
        # query planner may classify an anaphoric coordinate phrase as
        # "general" before session target binding; retaining that disagreement
        # allowed providers to substitute origin/public data for live telemetry.
        query_domain=topic or query_plan.domain,
        confidence=query_plan.confidence,
        unclear=query_plan.unclear,
        reason=query_plan.reason,
        tool_ids=tool_ids,
        missing_arguments=(),
        execution_layer=execution_layer,
        safety_posture=READ_ONLY_ACTION_POSTURE,
    )


SAFE_BLOCKED_TERM_READ_ONLY_INTENTS = frozenset(
    {
        "fleet_connectivity",
        "mission_mode_comparison",
        "show_modes_help",
        "show_upload_help",
        "sitl_help",
        "board_setup_help",
        "companion_setup_help",
        "docs_help",
        "capability_catalog",
        "registry_domain_tool_summary",
        "origin_status",
        "command_summary",
    }
)


def is_safe_blocked_term_read_only_intent(message: str, intent: str | None) -> bool:
    """Return whether a conceptual read-only answer may bypass action-word blocking."""

    if intent not in SAFE_BLOCKED_TERM_READ_ONLY_INTENTS:
        return False
    normalized = _normalize_text(message)
    if _looks_like_direct_execution_request(normalized):
        return False
    return _has_any(
        normalized,
        (
            "what",
            "which",
            "how",
            "where",
            "did",
            "was",
            "were",
            "has",
            "have",
            "ready",
            "readiness",
            "explain",
            "difference",
            "different",
            "compare",
            "status",
            "report",
            "summary",
            "mode",
            "modes",
            "workflow",
            "guide",
            "doc",
            "docs",
            "link",
            "read about",
            "setup",
            "wait",
            "delay",
            "skipped",
            "included",
            "happened",
            "done",
        ),
    )


class MdsReadOnlyTools:
    """Small curated GCS read surface for Simurgh chat answers."""

    def __init__(
        self,
        *,
        deps: Any | None = None,
        actor_role: str | None = "operator",
    ):
        self.deps = deps
        self.actor_role = actor_role

    def general_knowledge(self, message: str) -> MdsReadToolAnswer:
        normalized = _normalize_text(message)
        knowledge = _load_general_knowledge_config()
        composer = AnswerComposer()

        external = _matching_external_question(normalized, knowledge)
        if external:
            title, summary, notes = external
            composer.line(summary)
            composer.blank().line("For MDS operators:")
            composer.bullets(notes)
            composer.blank().line("This is general guidance only; no live weather, GCS mutation, or drone command was used.")
            return self._answer(
                "general_knowledge",
                composer.render(),
                ("simurgh.general_knowledge.read",),
                response_mode="interpret",
                safety_notes=(
                    "Answered from curated public Simurgh general-knowledge context.",
                    "No live external data source, GCS mutation, drone API, or command path was used.",
                    f"General topic: {title}.",
                ),
            )

        concept = _matching_general_concept(normalized, knowledge)
        if concept:
            title, summary, notes = concept
            composer.line(f"{title}: {summary}")
            if notes:
                composer.blank().line("In MDS/operator terms:")
                composer.bullets(notes)
            composer.blank().line("This is a general explanation, not live vehicle status. No drone command was sent.")
            return self._answer(
                "general_knowledge",
                composer.render(),
                ("simurgh.general_knowledge.read",),
                response_mode="interpret",
                safety_notes=(
                    "Answered from curated public Simurgh general-knowledge context.",
                    "No live GCS state, drone API, or command path was used.",
                    f"General topic: {title}.",
                ),
            )

        composer.line("I can help with that as a general question, but I do not have a curated local answer for it yet.")
        composer.line("For MDS work, I can still help with fleet, show, swarm, logs, SITL, setup, MCP, and runtime questions.")
        composer.line("No drone command was sent.")
        return self._answer(
            "general_knowledge",
            composer.render(),
            ("simurgh.general_knowledge.read",),
            response_mode="interpret",
            safety_notes=(
                "No deterministic curated answer matched this general prompt.",
                "No live GCS state, external data source, drone API, or command path was used.",
            ),
        )

    def coordinate_geography(self, message: str) -> MdsReadToolAnswer:
        pair = extract_latitude_longitude(message)
        if pair is None:
            return self._answer(
                "coordinate_geography",
                (
                    "I need one valid WGS84 latitude/longitude pair to identify "
                    "an approximate country. Use `latitude, longitude` order or "
                    "label both values. No external service or drone command was used."
                ),
                (COUNTRY_LOOKUP_TOOL_ID,),
                response_mode="clarify",
                safety_notes=(
                    "No valid coordinate pair was available for offline country lookup.",
                    "No external provider, geocoding request, GCS mutation, or drone command was used.",
                ),
            )
        result = resolve_country(*pair)
        return self._answer(
            "coordinate_geography",
            format_country_resolution(result),
            (COUNTRY_LOOKUP_TOOL_ID,),
            response_mode="interpret",
            safety_notes=(
                "Country was resolved from local offline boundary data.",
                COUNTRY_LOOKUP_DISCLAIMER,
                "No external provider, geocoding request, GCS mutation, or drone command was used.",
            ),
        )

    def public_geography(self, message: str) -> MdsReadToolAnswer:
        normalized = _normalize_text(message)
        places = _matching_public_places(normalized, _load_public_places_config())
        composer = AnswerComposer()
        if not places:
            composer.line("I understand this as a public geography/calculation question, but I do not have the place in the reviewed local place registry yet.")
            composer.line("If web search/geocoding is enabled later, Simurgh can resolve new public places with citations; for now I will not invent coordinates.")
            composer.line("No drone command was sent.")
            return self._answer(
                "public_geography",
                composer.render(),
                ("simurgh.public_places.read",),
                response_mode="interpret",
                safety_notes=(
                    "No reviewed public place matched the prompt.",
                    "No web search, GCS mutation, drone API, or command path was used.",
                ),
            )

        distance_km = _extract_public_distance_km(normalized)
        distance_pair_requested = len(places) >= 2 and _has_domain_signal(
            normalized,
            ("how far", "how many km", "how many kilometer", "distance from", "distance between", "from", " to ", "kilometer", "kilometers"),
        )
        if distance_pair_requested:
            first, second = places[0], places[1]
            distance = _great_circle_distance_km(first, second)
            first_title = str(first["title"])
            second_title = str(second["title"])
            first_latitude = float(first["latitude"])
            first_longitude = float(first["longitude"])
            second_latitude = float(second["latitude"])
            second_longitude = float(second["longitude"])
            composer.line(
                f"The straight-line great-circle distance from **{first_title}** to **{second_title}** is about **{distance:,.0f} km**."
            )
            composer.blank().table(
                ("Place", "Latitude", "Longitude"),
                (
                    (first_title, f"{first_latitude:.4f}", f"{first_longitude:.4f}"),
                    (second_title, f"{second_latitude:.4f}", f"{second_longitude:.4f}"),
                ),
            )
            composer.blank().line("This is a public geodesy calculation, not an MDS flight route or range check. No drone command was sent.")
            return self._answer(
                "public_geography",
                composer.render(),
                ("simurgh.public_places.read", "simurgh.geodesy.calculate"),
                response_mode="interpret",
                safety_notes=(
                    "Answered from reviewed public place coordinates and deterministic geodesy math.",
                    "No live GCS state, web search, drone API, or command path was used.",
                ),
            )

        place = places[0]
        place_title = str(place["title"])
        place_latitude = float(place["latitude"])
        place_longitude = float(place["longitude"])
        place_elevation = _finite_or_none(place.get("elevation_m"))
        place_elevation_datum = str(place.get("elevation_datum") or "").strip()
        composer.line(f"**{place_title}** public reference:")
        rows: list[tuple[str, str]] = [
            ("Latitude", f"{place_latitude:.4f}"),
            ("Longitude", f"{place_longitude:.4f}"),
            ("Horizontal datum", "WGS84 decimal degrees"),
        ]
        if place_elevation is not None:
            rows.append(("Elevation", f"{place_elevation:,.0f} m"))
            if place_elevation_datum:
                rows.append(("Elevation note", place_elevation_datum))
        composer.blank().table(("Field", "Value"), rows)
        note = str(place.get("source_note") or "Public reference coordinate; verify before operations.").strip()
        if note:
            composer.blank().line(note)
        if distance_km is not None and _has_domain_signal(normalized, ("around", "circle", "loop", "radius", "orbit")):
            circumference = 2.0 * math.pi * distance_km
            diameter_circumference = math.pi * distance_km
            composer.blank().line(
                f"If **{distance_km:g} km** means radius around the point, the loop circumference is about **{circumference:,.1f} km**."
            )
            composer.line(
                f"If **{distance_km:g} km** means diameter, the loop is about **{diameter_circumference:,.1f} km**."
            )
            composer.line("For an actual flight plan, terrain clearance, airspace, weather, vehicle endurance, comms, and local permission are separate checks.")
        composer.blank().line("This is public calculation guidance only; no route was uploaded and no drone command was sent.")
        return self._answer(
            "public_geography",
            composer.render(),
            ("simurgh.public_places.read", "simurgh.geodesy.calculate"),
            response_mode="interpret",
            safety_notes=(
                "Answered from reviewed public place coordinates and deterministic geodesy math.",
                "No live GCS state, web search, drone API, route upload, or command path was used.",
            ),
        )

    def fleet_summary(self, message: str = "") -> MdsReadToolAnswer:
        config = self._fleet_config()
        positions = self._positions_by_hw_id()
        specific_hw_id = _extract_hw_id(message)
        specific_label = _extract_configured_drone_label(message, config) if specific_hw_id is None else ""
        rows = [drone for drone in config if specific_hw_id is None or _as_int(drone.get("hw_id")) == specific_hw_id]
        if specific_label:
            rows = [drone for drone in rows if _drone_matches_label(drone, specific_label)]

        composer = AnswerComposer()
        if specific_hw_id is not None and not rows:
            composer.line(f"I do not see drone {specific_hw_id} in the current GCS fleet configuration.")
            composer.blank()
            composer.line(f"Configured drone count: {len(config)}.")
            composer.line("No action was executed.")
            return self._answer("fleet_summary", composer.render(), ("mds.config.fleet.read",))
        if specific_label and not rows:
            composer.line(f"I do not see a configured drone matching '{specific_label}' in the current GCS fleet configuration.")
            composer.blank()
            composer.line(f"Configured drone count: {len(config)}.")
            composer.line("No action was executed.")
            return self._answer("fleet_summary", composer.render(), ("mds.config.fleet.read",))

        if specific_label:
            composer.line(f"{_display_label(specific_label)} drone from GCS configuration:")
        elif specific_hw_id is None:
            composer.line(f"Fleet status from GCS configuration: {len(config)} configured drone(s).")
        else:
            composer.line(f"Drone {specific_hw_id} from GCS configuration:")
        composer.blank()

        table_rows: list[tuple[str, str, str, str, str, str]] = []
        for drone in rows:
            hw_id = _as_int(drone.get("hw_id"))
            pos_id = drone.get("pos_id", hw_id)
            launch = positions.get(hw_id)
            launch_text = (
                f"({_fmt_m(launch.get('x'))}, {_fmt_m(launch.get('y'))}) m"
                if launch
                else "unavailable"
            )
            role = drone.get("callsign") or drone.get("role") or drone.get("name") or drone.get("label") or "-"
            table_rows.append(
                (
                    f"Drone {hw_id}",
                    str(pos_id),
                    str(role),
                    str(drone.get("ip", "unknown")),
                    str(drone.get("mavlink_port", "n/a")),
                    launch_text,
                )
            )
        composer.table(("Drone", "Pos", "Role", "IP", "MAVLink", "Launch"), table_rows)

        swarm_assignments = self._swarm_assignments()
        if specific_hw_id is None:
            composer.blank().line(f"Swarm assignments loaded: {len(swarm_assignments)}.")
        composer.line("No action was executed.")
        return self._answer(
            "fleet_summary",
            composer.render(),
            ("mds.config.fleet.read", "mds.config.positions.read", "mds.config.swarm.read"),
        )

    def fleet_sitl_summary(
        self,
        message: str = "",
        *,
        response_detail: str = "standard",
    ) -> MdsReadToolAnswer:
        """Compose fleet configuration and live SITL inventory in one status answer."""

        config = self._fleet_config()
        normalized_message = _normalize_text(message)
        live_requested = _looks_like_live_fleet_count_state_question(normalized_message)
        sitl_answer = self.sitl_status(
            response_detail="brief" if _normalize_response_detail(response_detail) != "detailed" else "standard"
        )
        composer = AnswerComposer()
        if not live_requested or _has_domain_signal(normalized_message, ("configured", "defined", "inventory")):
            composer.line(f"Configured drones: {len(config)}.")
        if live_requested:
            connectivity = self.fleet_connectivity(message=message, response_detail="brief")
            connectivity_summary = next(
                (line.strip() for line in connectivity.content.splitlines() if line.strip()),
                "Live drone count is unavailable.",
            )
            composer.line(connectivity_summary)
        composer.line(sitl_answer.content)
        return self._answer(
            "fleet_sitl_summary",
            composer.render(),
            (
                "mds.config.fleet.read",
                "mds.fleet.heartbeats.read",
                "mds.fleet.telemetry.read",
                "mds.fleet.network_status.read",
                "mds.sitl.instances.read",
                "mds.sitl.policy.read",
            ),
            response_mode="status",
        )

    def fleet_connectivity(
        self,
        message: str = "",
        *,
        detail_profile: str = "auto",
        target_drone_ids: Sequence[str] = (),
        response_detail: str = "standard",
    ) -> MdsReadToolAnswer:
        config = self._fleet_config()
        heartbeats = self._heartbeat_snapshot()
        telemetry = self._telemetry_snapshot()
        telemetry_success_times = self._telemetry_success_times()
        normalized_message = _normalize_text(message)
        normalized_profile = str(detail_profile or "auto").strip().casefold()
        wants_position = normalized_profile == "full" or _wants_fleet_position_details(normalized_message)
        wants_health = normalized_profile in {"health", "full"} or _wants_fleet_health_details(normalized_message)

        try:
            from params import Params
            from presence import build_presence_snapshot, resolve_presence_thresholds

            thresholds = resolve_presence_thresholds(Params)
        except Exception:
            build_presence_snapshot = None
            thresholds = None

        requested_targets = tuple(
            dict.fromkeys(_as_str(item) for item in target_drone_ids if _as_str(item))
        )
        all_hw_ids = sorted(
            {
                *(_as_str(drone.get("hw_id")) for drone in config),
                *(_as_str(key) for key in heartbeats),
                *(_as_str(key) for key in telemetry),
                *requested_targets,
            },
            key=_natural_key,
        )
        if requested_targets:
            requested_set = set(requested_targets)
            all_hw_ids = [hw_id for hw_id in all_hw_ids if hw_id in requested_set]
        config_lookup = {_as_str(drone.get("hw_id")): drone for drone in config}
        live_count = 0
        rows: list[tuple[str, ...]] = []
        health_verdict_rows: list[dict[str, Any]] = []
        compact_health_rows: list[dict[str, str]] = []
        compact_position_rows: list[dict[str, str]] = []
        country_lookup_attempted = False
        now = time.time()
        for hw_id in all_hw_ids:
            heartbeat = _copy_mapping(heartbeats.get(hw_id) or heartbeats.get(_maybe_int_key(hw_id)))
            telemetry_row = _copy_mapping(telemetry.get(hw_id) or telemetry.get(_maybe_int_key(hw_id)))
            configured = hw_id in config_lookup
            if build_presence_snapshot is not None:
                presence = build_presence_snapshot(
                    hw_id=hw_id,
                    heartbeat=heartbeat,
                    telemetry=telemetry_row,
                    telemetry_success_time=telemetry_success_times.get(hw_id) or telemetry_success_times.get(_maybe_int_key(hw_id)),
                    configured=configured,
                    now=now,
                    thresholds=thresholds,
                )
                state = presence.get("label") or presence.get("state") or "Unknown"
                detail = presence.get("detail") or ""
                live = bool(presence.get("fresh"))
            else:
                live = bool(heartbeat or telemetry_row.get("telemetry_available"))
                state = "Live" if live else "Offline"
                detail = "Presence fallback used."
            if live:
                live_count += 1
            ip = heartbeat.get("ip") or telemetry_row.get("ip") or config_lookup.get(hw_id, {}).get("ip", "unknown")
            role = config_lookup.get(hw_id, {}).get("callsign") or config_lookup.get(hw_id, {}).get("role") or "-"
            if wants_position and wants_health:
                lat, lon, alt, gps_label = _fleet_position_summary(telemetry_row)
                health = _fleet_health_summary(telemetry_row)
                compact_health_rows.append(
                    {
                        "drone": f"Drone {hw_id}",
                        "presence": str(state),
                        "battery": health["battery"],
                        "armed": health["armed"],
                        "flight_state": health["flight_state"],
                        "ready": health["ready"],
                        "gps": gps_label,
                        "evidence": str(detail),
                    }
                )
                health_verdict_rows.append(
                    {
                        "drone": f"Drone {hw_id}",
                        "live": live,
                        "ready": health["ready"],
                        "armed": health["armed"],
                        "flight_state": health["flight_state"],
                        "gps": gps_label,
                    }
                )
                country_resolution = (
                    resolve_country(lat, lon)
                    if lat is not None and lon is not None
                    else None
                )
                country_lookup_attempted = country_lookup_attempted or country_resolution is not None
                country = country_resolution.label if country_resolution is not None else "unavailable"
                altitude = _fleet_altitude_summary(telemetry_row)
                altitude_text = (
                    f"{altitude['value']:.1f} m {altitude['label']}"
                    if altitude["value"] is not None
                    else "unknown"
                )
                position = f"lat {_fmt_coordinate(lat)}, lon {_fmt_coordinate(lon)}, alt {altitude_text}, {country}"
                compact_position_rows.append(
                    {
                        "drone": f"Drone {hw_id}",
                        "presence": str(state),
                        "gps": gps_label,
                        "latitude": _fmt_coordinate(lat),
                        "longitude": _fmt_coordinate(lon),
                        "altitude": altitude_text,
                        "country": country,
                        "ready": health["ready"],
                        "armed": health["armed"],
                        "flight_state": health["flight_state"],
                        "battery": health["battery"],
                        "evidence": str(detail),
                    }
                )
                rows.append(
                    (
                        f"Drone {hw_id}",
                        str(state),
                        gps_label,
                        position,
                        health["battery"],
                        health["armed"],
                        health["flight_state"],
                        health["ready"],
                        health["mode"],
                        health["system"],
                        str(detail),
                    )
                )
            elif wants_position:
                lat, lon, alt, gps_label = _fleet_position_summary(telemetry_row)
                altitude = _fleet_altitude_summary(telemetry_row)
                country_resolution = (
                    resolve_country(lat, lon)
                    if lat is not None and lon is not None
                    else None
                )
                country_lookup_attempted = country_lookup_attempted or country_resolution is not None
                country = country_resolution.label if country_resolution is not None else "unavailable"
                compact_position_rows.append(
                    {
                        "drone": f"Drone {hw_id}",
                        "presence": str(state),
                        "gps": gps_label,
                        "latitude": _fmt_coordinate(lat),
                        "longitude": _fmt_coordinate(lon),
                        "altitude": (
                            f"{altitude['value']:.1f} m {altitude['label']}"
                            if altitude["value"] is not None
                            else "unknown"
                        ),
                        "country": country,
                        "ready": "",
                        "armed": "",
                        "flight_state": "",
                        "battery": "",
                        "evidence": str(detail),
                    }
                )
                rows.append(
                    (
                        f"Drone {hw_id}",
                        str(state),
                        gps_label,
                        _fmt_coordinate(lat),
                        _fmt_coordinate(lon),
                        (
                            f"{altitude['value']:.1f} m {altitude['label']}"
                            if altitude["value"] is not None
                            else "unknown"
                        ),
                        country,
                        str(detail),
                    )
                )
            elif wants_health:
                health = _fleet_health_summary(telemetry_row)
                compact_health_rows.append(
                    {
                        "drone": f"Drone {hw_id}",
                        "presence": str(state),
                        "battery": health["battery"],
                        "armed": health["armed"],
                        "flight_state": health["flight_state"],
                        "ready": health["ready"],
                        "gps": health["gps"],
                        "evidence": str(detail),
                    }
                )
                health_verdict_rows.append(
                    {
                        "drone": f"Drone {hw_id}",
                        "live": live,
                        "ready": health["ready"],
                        "armed": health["armed"],
                        "flight_state": health["flight_state"],
                        "gps": health["gps"],
                    }
                )
                rows.append(
                    (
                        f"Drone {hw_id}",
                        str(state),
                        health["battery"],
                        health["armed"],
                        health["flight_state"],
                        health["ready"],
                        health["mode"],
                        health["system"],
                        health["gps"],
                        str(detail),
                    )
                )
            else:
                rows.append((f"Drone {hw_id}", str(role), str(state), str(ip), str(detail)))

        composer = AnswerComposer()
        brief = _normalize_response_detail(response_detail) == "brief"
        compact_position = brief and wants_position and bool(compact_position_rows)
        if requested_targets and not compact_position:
            composer.line("Scope: " + ", ".join(f"Drone {target}" for target in requested_targets) + ".")
        if not all_hw_ids:
            composer.line("Connectivity from GCS state: no configured drone IDs, heartbeats, or telemetry rows are visible to this GCS runtime right now.")
            if wants_position:
                composer.line(
                    "GPS, Latitude, Longitude, and Altitude evidence are unavailable because there is no readable fleet row, heartbeat row, or telemetry row in this runtime snapshot."
                )
            composer.line("No action was executed.")
        else:
            if compact_position:
                for item in compact_position_rows:
                    health_suffix = ""
                    if item["ready"]:
                        health_suffix = (
                            f"; Ready: {item['ready']}; Armed: {item['armed']}; "
                            f"{item['flight_state']}; Battery: {item['battery']}"
                        )
                    composer.line(
                        f"{item['drone']}: {item['presence']}; GPS {item['gps']}; "
                        f"lat {item['latitude']}; lon {item['longitude']}; "
                        f"alt {item['altitude']}; country {item['country']}"
                        f"{health_suffix}. {item['evidence']}"
                    )
                if country_lookup_attempted:
                    composer.line(
                        "Country is an approximate offline boundary lookup, not flight-authorization evidence."
                    )
            else:
                composer.line(f"Connectivity from GCS state: {live_count}/{len(all_hw_ids)} drone(s) currently look live.")
            if wants_health and not compact_position:
                composer.line(_fleet_health_verdict_line(health_verdict_rows))
            if brief and wants_health and not compact_position:
                composer.bullets(
                    (
                        f"{item['drone']}: {item['presence']}; Ready: {item['ready']}; "
                        f"Armed: {item['armed']}; {item['flight_state']}; GPS {item['gps']}; "
                        f"Battery: {item['battery']}; {item['evidence']}"
                    )
                    for item in compact_health_rows
                )
            elif compact_position:
                pass
            elif wants_position and wants_health:
                composer.blank().table(
                    (
                        "Drone", "Presence", "GPS", "Position", "Battery", "Armed", "Flight state",
                        "Ready", "Mode", "System", "Evidence",
                    ),
                    rows,
                )
                composer.blank().line(
                    "Coordinates, GPS, battery, arming, mode, and system status come from the latest GCS telemetry snapshot. `unavailable` means this runtime has no current value for that field."
                )
                if country_lookup_attempted:
                    composer.line(COUNTRY_LOOKUP_DISCLAIMER)
            elif wants_position:
                composer.blank().table(
                    ("Drone", "Presence", "GPS", "Latitude", "Longitude", "Altitude", "Country", "Evidence"),
                    rows,
                )
                composer.blank().line(
                    "Coordinates and GPS status come from the latest GCS telemetry snapshot. `unavailable` means this runtime does not currently have a valid global-position sample for that drone."
                )
                if country_lookup_attempted:
                    composer.line(COUNTRY_LOOKUP_DISCLAIMER)
            elif wants_health:
                composer.blank().table(
                    (
                        "Drone", "Presence", "Battery", "Armed", "Flight state", "Ready", "Mode",
                        "System", "GPS", "Evidence",
                    ),
                    rows,
                )
                composer.blank().line(
                    "Battery, arming, readiness, flight mode, system status, and GPS evidence come from the latest GCS telemetry snapshot. Treat missing values as unknown, not healthy."
                )
            else:
                composer.blank().table(("Drone", "Role", "Presence", "IP", "Evidence"), rows)
            if wants_health and not brief:
                composer.blank().line(
                    "This is the current MDS telemetry/preflight report. Missing values remain unknown."
                )
            elif not wants_health and not brief:
                composer.blank().line("This is the current MDS presence snapshot.")
            if not brief:
                composer.line("No drone command was sent.")
        tool_ids = (
            "mds.fleet.heartbeats.read",
            "mds.fleet.telemetry.read",
            "mds.fleet.network_status.read",
        )
        if country_lookup_attempted:
            tool_ids = (*tool_ids, COUNTRY_LOOKUP_TOOL_ID)
        return self._answer(
            "fleet_status" if normalized_profile in {"health", "full"} else "fleet_connectivity",
            composer.render(),
            tool_ids,
        )

    def fleet_enrollment_summary(self, message: str = "") -> MdsReadToolAnswer:
        payload = self._fleet_candidates_payload(include_inactive=True, runtime_mode="current")
        candidates = [_model_payload(item) for item in (payload.get("candidates") or [])]
        state_counts = _copy_mapping(payload.get("state_counts"))
        runtime_mode_filter = str(payload.get("runtime_mode_filter") or "current")
        registry_error = str(payload.get("error") or "").strip()
        active = [item for item in candidates if _candidate_state(item) in {"pending_operator_review", "conflict"}]
        selected = _select_candidate_from_message(message, candidates)
        visible = [selected] if selected else active[:8]

        composer = AnswerComposer()
        composer.line("Fleet Enrollment status from current GCS state:")
        composer.blank().table(
            ("Area", "Current evidence"),
            (
                ("Runtime filter", runtime_mode_filter),
                ("Returned candidates", str(len(candidates))),
                ("Active review", str(len(active))),
                ("Conflicts", str(state_counts.get("conflict", 0))),
                ("Pending review", str(state_counts.get("pending_operator_review", 0))),
                ("Resolved/history", str(len(candidates) - len(active))),
                ("Updated", _format_epoch_utc(payload.get("timestamp"))),
            ),
        )

        if registry_error:
            composer.blank().line(
                "I could not verify Fleet Enrollment candidates because the candidate registry read failed. "
                "Do not treat this as zero candidates."
            )
            composer.blank().line(
                "Open [Fleet Enrollment](/fleet-enrollment) and check GCS API/service logs before accepting, replacing, recovering, "
                "rejecting, or ignoring any candidate."
            )
            composer.line("No enrollment change was executed.")
            return self._answer(
                "fleet_enrollment_summary",
                composer.render(),
                ("mds.fleet.candidates.read",),
            )

        if not candidates:
            composer.blank().line(
                "I do not see any announced companion/board candidates in this runtime filter right now. "
                "That means Fleet Enrollment has nothing waiting for operator review from the candidate registry."
            )
            composer.blank().line(
                "Use [Fleet Enrollment](/fleet-enrollment) after a node bootstrap/announce, then verify identity, IP, runtime mode, "
                "PX4 `SYS_ID`, MAVLink routing, and sidecar profile before accepting anything into the fleet."
            )
            composer.line("No enrollment change was executed.")
            return self._answer(
                "fleet_enrollment_summary",
                composer.render(),
                ("mds.fleet.candidates.read",),
            )

        if selected:
            selected_id = str(selected.get("candidate_id") or "unknown")
            composer.blank().line(f"Selected candidate: `{selected_id}`.")
        elif not active:
            composer.blank().line("No active candidates are waiting for operator review. Resolved/history rows are still summarized below for context.")
            visible = candidates[:8]
        else:
            composer.blank().line(f"{len(active)} active candidate(s) need operator review.")

        composer.blank().table(
            ("Candidate", "HW", "Host", "IP", "Runtime", "State", "Heartbeat", "Conflict / hint"),
            tuple(_candidate_summary_row(item) for item in visible),
        )
        if not selected and len(visible) < len(active):
            composer.line(f"Showing {len(visible)} of {len(active)} active candidate(s); open Fleet Enrollment for the full list.")

        conflicts = [item for item in visible if _candidate_state(item) == "conflict"]
        if conflicts:
            composer.blank().line("Conflict meaning:")
            composer.bullets(_candidate_conflict_line(item) for item in conflicts[:5])

        stale_or_offline = [item for item in visible if _candidate_heartbeat_status(item) in {"stale", "offline", "unknown"}]
        if stale_or_offline:
            composer.blank().line("Presence caution:")
            composer.bullets(_candidate_presence_line(item) for item in stale_or_offline[:5])

        composer.blank().line(
            "Use [Fleet Enrollment](/fleet-enrollment) for accept/replace/recover/reject/ignore decisions and [Fleet Ops](/fleet-ops) "
            "for the required post-enrollment repo/config sync."
        )
        composer.line("No enrollment, repository, or flight action was executed.")
        return self._answer(
            "fleet_enrollment_summary",
            composer.render(),
            ("mds.fleet.candidates.read",),
        )

    def autopilot_support(self) -> MdsReadToolAnswer:
        composer = AnswerComposer()
        composer.line("Current MDS flight-stack support is **PX4-first and PX4-validated**.")
        composer.blank()
        composer.table(
            ("Stack", "MDS status", "Operational meaning"),
            (
                (
                    "PX4",
                    "Supported/validated target",
                    "MDS tooling, docs, readiness checks, SYS_ID guidance, MAVSDK/PX4 assumptions, mission/offboard flows, and field tests are built around PX4 today.",
                ),
                (
                    "ArduPilot",
                    "Not currently supported/validated for MDS command/control",
                    "ArduPilot also speaks MAVLink, but it needs an explicit adapter, parameter/mode/mission mapping, SITL tests, bench tests, docs, and safety review before we present it as supported.",
                ),
            ),
        )
        composer.blank()
        composer.line("So the safe answer for operators is: use PX4 for current MDS deployments; treat ArduPilot as a future integration candidate, not a ready production path.")
        composer.line("Relevant docs: " + _doc_link("Simurgh operator guide", "simurgh.operator_guide") + ", " + _doc_link("GCS API surface", "mds.gcs_api") + ", " + _doc_link("MAVLink routing setup", "mds.mavlink_routing_setup") + ".")
        composer.line("No drone command was sent.")
        return self._answer(
            "autopilot_support",
            composer.render(),
            ("mds.docs.operator_workflow.read", "mds.docs.mavlink_routing.read"),
            response_mode="capability",
        )

    def swarm_topology(self) -> MdsReadToolAnswer:
        assignments = self._swarm_assignments()
        positions = self._positions_by_hw_id()
        if not assignments:
            content = (
                "No swarm assignments are loaded in the GCS swarm configuration.\n"
                "Open the Swarm Design page (`/swarm-design`) to define follow relationships and offsets."
            )
            return self._answer("swarm_topology", content, ("mds.config.swarm.read",))

        assignment_by_hw = {_as_int(item.get("hw_id")): item for item in assignments if _as_int(item.get("hw_id")) is not None}
        children: dict[int, list[int]] = {hw_id: [] for hw_id in assignment_by_hw}
        roots: list[int] = []
        for hw_id, item in assignment_by_hw.items():
            follow = _as_int(item.get("follow")) or 0
            if follow > 0 and follow in assignment_by_hw:
                children.setdefault(follow, []).append(hw_id)
            else:
                roots.append(hw_id)

        non_root_followers = [hw_id for hw_id, item in assignment_by_hw.items() if (_as_int(item.get("follow")) or 0) > 0]
        has_nonzero_offsets = any(
            abs(_as_float(item.get("offset_x"), 0.0)) > 0.001
            or abs(_as_float(item.get("offset_y"), 0.0)) > 0.001
            or abs(_as_float(item.get("offset_z"), 0.0)) > 0.001
            for item in assignment_by_hw.values()
        )
        lines = [
            "Configured/planned swarm geometry from GCS config, not live aircraft spacing:",
            f"- Assignments: {len(assignments)}",
            f"- Cluster roots/leaders: {', '.join(str(root) for root in sorted(roots)) or 'none'}",
        ]
        if not non_root_followers and not has_nonzero_offsets:
            lines.append(
                "- Formation state: no follower formation is currently configured; each drone is an independent root/leader."
            )
        for root in sorted(roots):
            members = _collect_tree_members(root, children)
            if len(members) == 1:
                lines.append(f"- Cluster leader {root}: solo/no followers")
            else:
                lines.append(f"- Cluster leader {root}: members {', '.join(str(member) for member in members)}")

        lines.append("Configured swarm follow offsets:")
        for hw_id in sorted(assignment_by_hw):
            item = assignment_by_hw[hw_id]
            follow = _as_int(item.get("follow")) or 0
            ox = _as_float(item.get("offset_x"), 0.0)
            oy = _as_float(item.get("offset_y"), 0.0)
            oz = _as_float(item.get("offset_z"), 0.0)
            norm = math.sqrt((ox * ox) + (oy * oy) + (oz * oz))
            frame = str(item.get("frame") or "ned")
            lines.append(
                f"- hw {hw_id}: follows {follow}, offset ({ox:.2f}, {oy:.2f}, {oz:.2f}) m "
                f"in {frame}, offset norm {norm:.2f} m"
            )

        distance_lines = _pairwise_distance_lines(positions)
        if distance_lines:
            lines.append("Configured launch/trajectory distances:")
            lines.extend(distance_lines)
        lines.append("Edit/check formation data in [Swarm Design](/swarm-design); review processed trajectories in [Swarm Trajectory](/swarm-trajectory).")
        lines.append("Docs: " + _doc_link("Swarm Trajectory guide", "mds.swarm_trajectory") + ".")
        lines.append("No drone command was sent.")
        return self._answer(
            "swarm_topology",
            "\n".join(lines),
            ("mds.config.swarm.read", "mds.config.positions.read"),
        )

    def swarm_readiness(self, message: str = "") -> MdsReadToolAnswer:
        assignments = self._swarm_assignments()
        positions = self._positions_by_hw_id()
        status_payload = self._swarm_trajectory_status()
        validation = self._swarm_trajectory_validation()
        presence = self._fleet_presence_counts()

        assignment_by_hw = {
            _as_int(item.get("hw_id")): item
            for item in assignments
            if _as_int(item.get("hw_id")) is not None
        }
        roots: list[int] = []
        followers: list[int] = []
        topology_blockers: list[str] = []
        for hw_id, item in assignment_by_hw.items():
            follow = _as_int(item.get("follow")) or 0
            if follow <= 0:
                roots.append(hw_id)
            elif follow == hw_id:
                followers.append(hw_id)
                topology_blockers.append(f"hw {hw_id} follows itself")
            elif follow not in assignment_by_hw:
                followers.append(hw_id)
                topology_blockers.append(f"hw {hw_id} follows missing leader hw {follow}")
            else:
                followers.append(hw_id)

        status = status_payload.get("status") if isinstance(status_payload.get("status"), Mapping) else {}
        cluster_summary = validation.get("cluster_summary") if isinstance(validation.get("cluster_summary"), Mapping) else {}
        if not cluster_summary and isinstance(status.get("cluster_summary"), Mapping):
            cluster_summary = status.get("cluster_summary") or {}
        validation_blockers = validation.get("blockers") if isinstance(validation.get("blockers"), list) else []
        validation_warnings = validation.get("warnings") if isinstance(validation.get("warnings"), list) else []
        trajectory_ready = bool(validation.get("ready")) if validation else False
        has_processed_outputs = bool(status.get("has_results"))
        live_count = presence.get("live", 0)
        total_count = presence.get("total", len(assignments))
        overall_state = cluster_summary.get("overall_state", "unknown")
        ready_cluster_count = cluster_summary.get("ready_cluster_count", 0)
        cluster_count = cluster_summary.get("cluster_count", 0)
        processed_drones = status.get("processed_drones") or []

        composer = AnswerComposer()
        composer.line("Smart Swarm readiness from current GCS evidence:")
        composer.blank().table(
            ("Area", "Current evidence"),
            (
                ("Saved topology", f"{len(assignments)} assignments, {len(roots)} leader/root, {len(followers)} follower"),
                ("Topology blockers", "none" if not topology_blockers else "; ".join(topology_blockers[:4])),
                ("Live fleet evidence", f"{live_count}/{total_count} drone(s) look live from heartbeat/telemetry"),
                ("Launch positions", f"{len(positions)} configured launch/start position(s)"),
                ("Swarm Trajectory package", _swarm_trajectory_readiness_label(trajectory_ready, has_processed_outputs, validation_blockers)),
            ),
        )

        if followers and not topology_blockers:
            composer.blank().line(
                "For a Smart Swarm follow test, the saved topology does define a follower formation. "
                "That is necessary for a follow test, but it is not enough for field readiness."
            )
        elif not followers:
            composer.blank().line(
                "For a Smart Swarm follow test, this topology is not a follower formation yet: every configured drone is still a root/leader."
            )
        else:
            composer.blank().line("The saved topology has blockers; fix those in [Swarm Design](/swarm-design) before any follow test.")

        if cluster_summary:
            composer.blank().line("Swarm Trajectory validation snapshot:")
            composer.bullets(
                (
                    f"overall state: {overall_state}",
                    f"clusters ready: {ready_cluster_count}/{cluster_count}",
                    f"processed drones: {len(processed_drones)}",
                )
            )
        if validation_blockers:
            composer.blank().line("Trajectory/package blockers:")
            composer.bullets(_issue_message(issue) for issue in validation_blockers[:5])
        elif validation_warnings:
            composer.blank().line("Trajectory/package warnings:")
            composer.bullets(_issue_message(issue) for issue in validation_warnings[:5])

        composer.blank().line("Before turning aircraft on or flying, do the human field checks separately: QGC identity/SYS_ID, fresh MAVLink telemetry, GPS/RTK quality, battery, mode/arming state, geofence/airspace/weather, and a clear abort/RTL plan.")
        composer.line("Pages: [Swarm Design](/swarm-design), [Swarm Trajectory](/swarm-trajectory), [Mission Config](/mission-config), [Overview](/).")
        composer.line("No configuration, mission, or drone action was executed.")
        return self._answer(
            "swarm_readiness",
            composer.render(),
            (
                "mds.config.swarm.read",
                "mds.config.positions.read",
                "mds.fleet.heartbeats.read",
                "mds.fleet.telemetry.read",
                "mds.swarm_trajectories.status.read",
                "mds.swarm_trajectories.validate.read",
            ),
            response_mode="workflow",
        )

    def sar_summary(self, message: str = "") -> MdsReadToolAnswer:
        catalog = self._quickscout_catalog(limit=5)
        missions = [_model_payload(item) for item in (catalog.get("missions") or [])]
        selected = _select_quickscout_mission(message, missions)
        mission_id = str(selected.get("mission_id") or "").strip()
        status = self._quickscout_status(mission_id) if mission_id else {}
        workspace = self._quickscout_workspace(mission_id) if mission_id else {}

        composer = AnswerComposer()
        composer.line("QuickScout/SAR mission status from current GCS evidence:")

        if not missions:
            composer.blank().line(
                "I do not see any persisted QuickScout mission package in the GCS store right now. "
                "That means there is no QuickScout plan for Simurgh to summarize as staged, active, or ready."
            )
            composer.blank().line(
                "Use [QuickScout](/quickscout) to plan/reopen missions. For field use, a human operator still needs fresh telemetry, "
                "valid GPS/RTK as required by the package, battery/mode checks, airspace/weather review, and an abort/RTL plan."
            )
            composer.line("No mission action was executed.")
            return self._answer("sar_summary", composer.render(), ("mds.sar.missions.read",))

        selected_status = status or selected
        operation = _model_payload(workspace.get("operation")) if workspace else {}
        if operation:
            selected = {**selected, **{key: value for key, value in operation.items() if key}}
        state = _readable_label(selected_status.get("state") or selected.get("state"))
        phase = _readable_label(selected_status.get("operation_phase") or "planned")
        launchable = bool(selected.get("launchable", True))
        requires_revalidation = bool(selected.get("requires_revalidation", False))
        mission_label = str(selected.get("mission_label") or selected.get("mission_id") or "latest mission")
        template = _readable_label(selected.get("mission_template"))
        source_mode = _readable_label(selected.get("position_source_mode"))
        return_behavior = _readable_label(selected.get("return_behavior"))
        coverage = _as_float(selected_status.get("total_coverage_percent", selected.get("total_coverage_percent", 0.0)), 0.0)
        estimated_duration = _as_float(selected.get("estimated_coverage_time_s"), 0.0)
        area_sq_m = _as_float(selected.get("total_area_sq_m"), 0.0)
        updated_at = _as_float(selected.get("updated_at"), 0.0)
        quality_notes = _quickscout_quality_notes(
            updated_at=updated_at,
            area_sq_m=area_sq_m,
            estimated_duration_s=estimated_duration,
        )
        readiness_label = _quickscout_readiness_label(
            launchable,
            requires_revalidation,
            state,
            quality_notes=quality_notes,
        )
        finding_count = len(status.get("findings") or []) if status else _as_int(selected.get("finding_count")) or 0

        composer.blank().table(
            ("Area", "Current evidence"),
            (
                ("Selected mission", f"{mission_label} (`{mission_id}`)"),
                ("State / phase", f"{state} / {phase}"),
                ("Template", template),
                ("Drones / positions", _quickscout_drone_scope(selected, status)),
                ("Coverage", f"{coverage:.1f}% complete; planned area {_format_quickscout_area(area_sq_m)}"),
                ("Estimated coverage time", _format_quickscout_duration(estimated_duration)),
                ("Position source", source_mode),
                ("Return behavior", return_behavior),
                ("Launch readiness", readiness_label),
                ("Findings", f"{finding_count} recorded"),
                ("Updated", f"{_format_epoch_utc(updated_at)} ({_format_age_from_epoch(updated_at)} old)"),
            ),
        )

        if quality_notes:
            composer.blank().line("Readiness cautions:")
            composer.bullets(quality_notes)

        summary = str(status.get("status_summary") or "").strip()
        recommended = str(status.get("recommended_operator_action") or "").strip()
        if summary or recommended:
            composer.blank().line("Operator interpretation:")
            composer.bullets(item for item in (summary, recommended) if item)

        drone_rows = _quickscout_drone_state_rows(status)
        if drone_rows:
            composer.blank().line("Per-drone mission progress:")
            composer.table(("Drone", "State", "Coverage", "Distance", "Remaining", "Note"), drone_rows[:6])
            if len(drone_rows) > 6:
                composer.line(f"{len(drone_rows) - 6} additional drone row(s) omitted for readability.")

        recent = missions[:3]
        if len(recent) > 1:
            composer.blank().line("Recent QuickScout mission packages:")
            composer.table(
                ("Mission", "State", "Drones", "Updated"),
                tuple(
                    (
                        str(item.get("mission_label") or item.get("mission_id") or "unknown"),
                        _readable_label(item.get("state")),
                        str(item.get("drone_count") or 0),
                        _format_epoch_utc(item.get("updated_at")),
                    )
                    for item in recent
                ),
            )

        composer.blank().line(
            "Use [QuickScout](/quickscout) for mission workspace/monitor review. "
            "Field readiness still requires live telemetry/GPS, battery, mode/arming, geofence, weather/airspace, and human launch review."
        )
        composer.line("No mission, configuration, or drone action was executed.")
        return self._answer(
            "sar_summary",
            composer.render(),
            (
                "mds.sar.missions.read",
                "mds.sar.mission.status.read",
                "mds.sar.mission.workspace.read",
                "mds.sar.findings.read",
            ),
        )

    def show_summary(self, *, response_mode: str = "status", message: str = "") -> MdsReadToolAnswer:
        skybrush = self._show_info()
        custom = self._custom_show_info()
        metrics = self._show_metrics_snapshot()
        safety = self._show_safety_report()
        validation = self._show_validation()
        normalized_mode = response_mode if response_mode in READ_RESPONSE_MODES else "status"
        normalized_message = _normalize_text(message)
        if normalized_mode == "interpret":
            content = self._show_summary_interpretation_content(
                skybrush=skybrush,
                custom=custom,
                metrics=metrics,
                safety=safety,
                validation=validation,
                normalized_message=normalized_message,
            )
        else:
            content = self._show_summary_status_content(
                skybrush=skybrush,
                custom=custom,
                metrics=metrics,
                safety=safety,
                validation=validation,
            )
        return self._answer(
            "show_summary",
            content,
            (
                "mds.shows.skybrush.read",
                "mds.shows.custom.read",
                "mds.shows.skybrush.metrics_snapshot.read",
                "mds.shows.skybrush.safety_report.read",
                "mds.shows.skybrush.validation.read",
            ),
            response_mode=normalized_mode,
        )

    def _show_summary_status_content(
        self,
        *,
        skybrush: Mapping[str, Any],
        custom: Mapping[str, Any],
        metrics: Mapping[str, Any],
        safety: Mapping[str, Any],
        validation: Mapping[str, Any],
    ) -> str:
        composer = AnswerComposer()
        composer.line("Loaded show state from GCS show-management files:")
        composer.line("Note: two show asset sources can exist at once; verify the operator-selected package before flight.")
        composer.blank()
        composer.line("Current packages:")
        composer.bullets(self._show_package_lines(skybrush=skybrush, custom=custom))
        composer.blank()
        composer.line("Readiness signals for the SkyBrush package:")
        composer.bullets(
            (
                _format_show_metrics_signal(metrics),
                _format_show_validation_signal(validation),
                _format_show_safety_signal(safety),
                _format_show_readiness_line(
                    skybrush=skybrush,
                    metrics=metrics,
                    safety=safety,
                    validation=validation,
                ),
            )
        )
        composer.blank()
        composer.line("Uploaded/loaded does not by itself mean fly-ready; validation, safety, operator-selected package, and field readiness must all be green.")
        composer.line("Edit/import or confirm the active package from [Show Design](/manage-drone-show).")
        composer.line("If this is a Swarm Trajectory workflow, review [Swarm Trajectory](/swarm-trajectory) before treating it as fly-ready.")
        composer.line(
            "Docs: "
            + _doc_link("Drone Show guide", "mds.drone_show")
            + ", "
            + _doc_link("Swarm Trajectory guide", "mds.swarm_trajectory")
            + ", and "
            + _doc_link("GCS API surface", "mds.gcs_api")
            + "."
        )
        composer.line("No show was deployed or commanded.")
        return composer.render()

    def _show_summary_interpretation_content(
        self,
        *,
        skybrush: Mapping[str, Any],
        custom: Mapping[str, Any],
        metrics: Mapping[str, Any],
        safety: Mapping[str, Any],
        validation: Mapping[str, Any],
        normalized_message: str,
    ) -> str:
        composer = AnswerComposer()
        if _has_any(normalized_message, ("history", "keep history", "remember", "previous")):
            composer.line("I can keep short chat context inside this Simurgh session; I am using the previous drone-show topic for this follow-up.")
            composer.blank()
        composer.line("How to read the current drone-show state:")
        composer.bullets(
            (
                "Uploaded/loaded means show files exist in GCS show-management storage.",
                "Fly-ready is stricter: the selected package, validation, safety report, metrics snapshot, mission config/origin, fleet readiness, and field operator review all need to agree.",
                "Two package families can coexist, so the operator must confirm which package is selected before launch workflow review.",
            )
        )
        composer.blank()
        composer.line("Current evidence from this GCS:")
        composer.bullets(self._show_package_lines(skybrush=skybrush, custom=custom))
        composer.bullets(
            (
                _format_show_metrics_signal(metrics),
                _format_show_validation_signal(validation),
                _format_show_safety_signal(safety),
                _format_show_readiness_line(
                    skybrush=skybrush,
                    metrics=metrics,
                    safety=safety,
                    validation=validation,
                ),
            )
        )
        composer.blank()
        composer.line("Operator meaning: treat an uploaded show as available for review, not approved for flight. Use [Show Design](/manage-drone-show), [Mission Config](/mission-config), and [Swarm Trajectory](/swarm-trajectory) to verify the selected workflow before any mission trigger.")
        composer.line(
            "Docs: "
            + _doc_link("Drone Show guide", "mds.drone_show")
            + ", "
            + _doc_link("Origin System guide", "mds.origin_system")
            + ", and "
            + _doc_link("GCS API surface", "mds.gcs_api")
            + "."
        )
        composer.line("No show was deployed, launched, or commanded.")
        return composer.render()

    def _show_package_lines(self, *, skybrush: Mapping[str, Any], custom: Mapping[str, Any]) -> tuple[str, ...]:
        lines: list[str] = []
        if skybrush.get("available"):
            duration_ms = _as_float(skybrush.get("duration_ms"), 0.0)
            lines.append(
                f"SkyBrush processed show: {skybrush.get('drone_count', 0)} drone file(s), "
                f"duration {_format_duration(duration_ms / 1000.0)}, max altitude {skybrush.get('max_altitude', 'n/a')} m."
            )
        else:
            lines.append(f"SkyBrush processed show: not loaded ({skybrush.get('detail', 'no metadata')}).")

        if custom.get("available"):
            lines.append(
                f"Custom CSV show: {custom.get('filename', 'active.csv')}, {custom.get('row_count', 0)} row(s), "
                f"duration {_format_duration(_as_float(custom.get('duration_sec'), 0.0))}, "
                f"max altitude {custom.get('max_altitude', 'n/a')} m."
            )
        else:
            lines.append(f"Custom CSV show: not loaded ({custom.get('detail', 'no metadata')}).")
        return tuple(lines)

    def show_modes_help(self) -> MdsReadToolAnswer:
        content = "\n".join(
            [
                "Drone Show has two workflow families and several launch/control modes:",
                "",
                "| Area | Mode | Use it when |",
                "|---|---|---|",
                "| Show workflow | Normal Drone Show / SkyBrush ZIP | Normal multi-drone show import: one processed trajectory per drone, reviewed in [Show Design](/manage-drone-show), [Mission Config](/mission-config), then dispatched from [Overview](/). |",
                "| Show workflow | Custom CSV Drone Show | Advanced/manual path where every selected drone executes the same `active.csv` relative to its own launch frame; use for research, bench, or SITL tests, not the normal SkyBrush pipeline. |",
                "| Launch/control mode | GLOBAL with Auto Global Launch Corrector | Recommended outdoor Drone Show path: shared origin, GPS/global setpoints, live launch-position deviation checks, and tolerance-based correction. |",
                "| Launch/control mode | GLOBAL with manual placement | Legacy/manual placement path: each drone uses its captured launch position; accuracy depends on placing every aircraft exactly at the intended start point. |",
                "| Launch/control mode | LOCAL mode | Local NED/feedforward path for audited local-frame testing; accuracy depends on estimator quality and exact manual placement. |",
                "| Trigger timing | Relative delay or time-of-day trigger | Synchronized launch scheduling from the dashboard after readiness is clear; timing follows the GCS-aligned clock. |",
                "",
                "Normal operator path: import in [Show Design](/manage-drone-show), verify launch geometry/origin in [Mission Config](/mission-config), then use the [Overview](/) mission card only after readiness is green.",
                "Docs: " + _doc_link("Drone Show guide", "mds.drone_show") + " and " + _doc_link("Origin System guide", "mds.origin_system") + ".",
                "This is conceptual guidance only; no show was launched, uploaded, deployed, or commanded.",
            ]
        )
        return self._answer(
            "show_modes_help",
            content,
            ("mds.docs.drone_show.read", "mds.docs.origin_system.read"),
            response_mode="workflow",
        )

    def show_upload_help(self) -> MdsReadToolAnswer:
        content = "\n".join(
            [
                "SkyBrush show upload workflow:",
                "1. Open [Show Design](/manage-drone-show).",
                "2. Upload the SkyBrush ZIP archive from that page; do not upload an extracted folder.",
                "3. The dashboard calls `POST /api/v1/shows/skybrush/import` with multipart field `file`.",
                "4. Confirm the import summary: raw CSV count, processed drone count, generated plots, warnings, and next steps.",
                "5. Review launch geometry/origin in [Mission Config](/mission-config).",
                "6. Before any flight, verify the processed show metadata, metrics, safety report, and validation snapshot: `GET /api/v1/shows/skybrush`, `GET /api/v1/shows/skybrush/metrics`, `GET /api/v1/shows/skybrush/safety-report`, and `GET /api/v1/shows/skybrush/validation`.",
                "7. Use [Show Design](/manage-drone-show) only for the normal SkyBrush multi-drone workflow; use [Swarm Trajectory](/swarm-trajectory) only for the separate trajectory workflow.",
                "Docs: " + _doc_link("Drone Show guide", "mds.drone_show") + " and " + _doc_link("GCS API surface", "mds.gcs_api") + ".",
                *_docs_source_lines("SkyBrush show upload workflow", tags="show,skybrush", limit=3),
                "This is guidance only; no show was uploaded or deployed, and no drone command was sent.",
            ]
        )
        return self._answer(
            "show_upload_help",
            content,
            ("mds.docs.drone_show.read", "mds.shows.skybrush.read"),
            response_mode="workflow",
        )

    def operator_help(self, message: str = "") -> MdsReadToolAnswer:
        normalized = _normalize_text(message)
        if _has_any(normalized, ("offset", "formation", "cluster", "follow", "swarm")):
            content = "\n".join(
                [
                    "Swarm offsets and follow relationships are edited in [Swarm Design](/swarm-design).",
                    "- `follow=0` means the drone is a top-level leader/root.",
                    "- `follow=<hw_id>` makes the drone a follower of that hardware ID.",
                    "- `offset_x`, `offset_y`, and `offset_z` define the planned relative spacing in meters.",
                    "- Use offsets to define formation geometry; validate visually and with telemetry before any flight.",
                    "Simurgh is only explaining the workflow here; it did not change the swarm config.",
                ]
            )
            return self._answer(
                "operator_help",
                content,
                ("mds.docs.operator_workflow.read", "mds.config.swarm.read"),
                response_mode="workflow",
            )

        content = "\n".join(
            [
                "I can explain MDS workflows and inspect current GCS state from this chat.",
                "Common pages: [Mission Config](/mission-config), [Swarm Design](/swarm-design), [Show Design](/manage-drone-show), [Swarm Trajectory](/swarm-trajectory).",
                "No drone command was sent.",
            ]
        )
        return self._answer("operator_help", content, ("mds.docs.operator_workflow.read",), response_mode="workflow")

    def capability_catalog(self) -> MdsReadToolAnswer:
        try:
            from .tool_executor import summarize_read_only_tool_catalog

            summary = summarize_read_only_tool_catalog(channel="agent")
            policy = summary.policy
            registry = summary.registry
            read_only_menu = summary.allowed_tools
            guarded = summary.guarded_count
            excluded = summary.excluded_count

            preferred_tool_ids = (
                "mds.fleet.telemetry.read",
                "mds.fleet.heartbeats.read",
                "mds.fleet.network_status.read",
                "mds.config.fleet.read",
                "mds.shows.skybrush.read",
                "mds.shows.skybrush.validation.read",
                "mds.swarm_trajectories.status.read",
                "mds.swarm_trajectories.validate.read",
                "mds.logs.sessions.read",
                "mds.logs.drone_sessions.read",
                "mds.logs.drone_ulog_files.read",
                "mds.system.runtime_status.read",
                "mds.docs.search",
                "mds.simurgh.tool_candidates.read",
            )
            tools_by_id = {tool.id: tool for tool in read_only_menu}
            preview_tools = [tools_by_id[tool_id] for tool_id in preferred_tool_ids if tool_id in tools_by_id]
            preview_tools.extend(tool for tool in read_only_menu if tool.id not in preferred_tool_ids)
            preview = [f"{tool.title} (`{tool.id}`)" for tool in preview_tools[:12]]
            if len(read_only_menu) > 12:
                preview.append(f"{len(read_only_menu) - 12} more read-only registry tools are available in `config/agent_tools.yaml`.")
            if not preview:
                preview = ["No approved GCS tools are currently available to Simurgh."]

            registry_path = registry.path
            try:
                registry_label = registry_path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                registry_label = registry_path.as_posix()

            mcp_endpoint, mcp_endpoint_source = _deployment_mcp_endpoint(self.deps)
            mcp_status = "enabled" if policy.mcp_enabled else "disabled"
            mcp_auth_label = (
                "bearer token with agent/admin scope required"
                if policy.mcp_enabled
                else "not active while MCP is disabled"
            )

            composer = AnswerComposer()
            composer.line("Simurgh capabilities are driven by one curated registry and policy layer, not hardcoded chat-only tools.")
            composer.line(f"MCP endpoint: {mcp_status} at `{mcp_endpoint}`.")
            composer.blank()
            composer.table(
                ("Capability surface", "Current value"),
                (
                    ("Registry source", f"`{registry_label}`"),
                    ("MCP endpoint", f"{mcp_status} at `{mcp_endpoint}`"),
                    ("Endpoint source", mcp_endpoint_source),
                    ("MCP auth", mcp_auth_label),
                    ("Approved GCS tools", str(len(read_only_menu))),
                    ("Guarded/future candidates", str(guarded)),
                    ("Explicitly excluded dangerous/admin/drone-local tools", str(excluded)),
                ),
            )
            composer.blank().line("Current safe menu preview:")
            composer.bullets(preview)
            composer.blank()
            composer.line("External clients such as n8n, Claude Desktop, or VS Code should connect to the GCS Simurgh MCP endpoint above, never to a drone IP or drone-local sidecar port.")
            composer.line("Use Streamable HTTP JSON-RPC: call `tools/list` to discover the approved menu, then `tools/call` for allowed read-only tools when MCP is enabled and bearer auth is valid.")
            composer.line("New APIs should be imported as classified registry candidates first; they are not automatically callable until schemas, docs, policy, safety notes, and tests approve them.")
            composer.line("No drone command was sent.")
            content = composer.render()
        except Exception as exc:
            content = f"Simurgh capability registry could not be loaded: {exc}"
        return self._answer(
            "capability_catalog",
            content,
            ("mds.simurgh.tool_registry.read", "mds.simurgh.policy.read"),
            response_mode="capability",
        )

    def registry_domain_tool_summary(self, message: str) -> MdsReadToolAnswer:
        normalized = _normalize_text(message)
        try:
            from .query_understanding import build_assistant_query_plan
            from .tool_executor import summarize_read_only_tool_catalog

            plan = build_assistant_query_plan(normalized)
            summary = summarize_read_only_tool_catalog(channel="agent")
            registry_domains = _registry_domains_for_query(normalized, plan_domain=plan.domain)
            tools = _matching_registry_tools(summary.allowed_tools, normalized, registry_domains)
            selected_domains = _registry_domains_from_tools(tools) or registry_domains

            composer = AnswerComposer()
            domain_label = _registry_domain_summary_label(selected_domains, fallback=plan.domain)
            composer.line(f"Approved MDS capabilities for {domain_label}:")
            composer.blank()
            if tools:
                rows = [
                    (
                        f"{tool.title} (`{tool.id}`)",
                        _compact_tool_description(tool.description),
                        _tool_route_label(tool),
                        _tool_args_label(tool),
                    )
                    for tool in tools[:12]
                ]
                composer.table(("Capability", "Reads", "Route / adapter", "Args"), rows)
                if len(tools) > 12:
                    composer.blank().line(f"{len(tools) - 12} more matching capabilities are available through the same MDS/MCP menu.")
            else:
                composer.line("No approved capability matched that domain yet.")
            composer.blank()
            composer.line(
                "Dashboard chat and external MCP clients use the same approved capability menu; "
                "MCP clients discover it with `tools/list`."
            )
            composer.line("No route, configuration, upload, mission, or drone action was executed.")
            content = composer.render()
            tool_ids = tuple(tool.id for tool in tools[:16]) or ("mds.simurgh.tools.read", "mds.simurgh.policy.read")
        except Exception as exc:
            content = f"Simurgh registry capability summary could not be loaded: {exc}"
            tool_ids = ("mds.simurgh.tools.read", "mds.simurgh.policy.read")
        return self._answer(
            "registry_domain_tool_summary",
            content,
            tool_ids,
            response_mode="capability",
            safety_notes=(
                "Answered from the current policy-filtered Simurgh tool registry.",
                "No GCS route, drone API, command, or mutation was executed.",
                "This is the shared capability surface used by dashboard chat and MCP clients.",
            ),
        )

    def system_status(self) -> MdsReadToolAnswer:
        try:
            from .assistant import load_default_assistant_config
            from .policy import load_default_policy
            from src.settings.runtime import resolve_runtime_mode

            config = load_default_assistant_config()
            policy = load_default_policy()
            runtime = resolve_runtime_mode()
            fleet = self._fleet_config()
            heartbeats = self._heartbeat_snapshot()
            telemetry = self._telemetry_snapshot()
            version = str(getattr(self.deps, "MDS_VERSION", "5.5"))

            composer = AnswerComposer()
            composer.line("Current GCS/Simurgh health summary:")
            composer.blank().table(
                ("Area", "Value"),
                (
                    ("GCS API", "healthy/readable from the Simurgh process"),
                    ("MDS version", version),
                    ("GCS mode", f"{runtime.mode} ({runtime.source})"),
                    ("Configured drones", str(len(fleet))),
                    ("Heartbeat rows", str(len(heartbeats))),
                    ("Telemetry rows", str(len(telemetry))),
                    ("Simurgh provider", config.provider),
                    ("MCP", "enabled" if policy.mcp_enabled else "disabled"),
                    ("Circuit breaker", "on" if policy.action_circuit_breaker_enabled else "off"),
                ),
            )
            composer.blank().line("Use [Logs](/logs), [Environments](/environments), and [Fleet Ops](/fleet-ops) for deeper read-only drill-downs.")
            composer.line("No drone command was sent.")
            content = composer.render()
        except Exception as exc:
            content = f"GCS/Simurgh health metadata could not be loaded: {exc}"
        return self._answer(
            "system_status",
            content,
            ("mds.system.health.read", "mds.system.runtime_status.read", "mds.simurgh.status.read"),
        )

    def environment_summary(self) -> MdsReadToolAnswer:
        try:
            from src.settings.env_registry import load_env_registry

            registry = load_env_registry()
            entries = list(registry.entries.values())
            editable = [entry for entry in entries if bool(getattr(entry, "editable", False))]
            restart_required = [entry for entry in editable if str(getattr(entry, "restart_required", "never")) not in {"never", "false", "False"}]
            raw_secret = [entry for entry in entries if str(getattr(entry, "ui_visibility", "")) == "raw_secret"]
            domains: dict[str, int] = {}
            for entry in entries:
                domain = str(getattr(entry, "domain", "other") or "other")
                domains[domain] = domains.get(domain, 0) + 1

            composer = AnswerComposer()
            composer.line("MDS environment registry summary:")
            composer.blank().table(
                ("Area", "Value"),
                (
                    ("Registry file", "`config/mds_environment_registry.yaml`"),
                    ("Registered keys", str(len(entries))),
                    ("Editable keys", str(len(editable))),
                    ("Restart/apply-sensitive editable keys", str(len(restart_required))),
                    ("Raw secret keys", str(len(raw_secret))),
                ),
            )
            if domains:
                composer.blank().line("Registered domains:")
                composer.bullets(f"{domain}: {count}" for domain, count in sorted(domains.items()))
            composer.blank().line("Edit safe GCS settings in [Environment registry](/environments). Secrets stay server-side; Simurgh reports readiness/fingerprints, not raw values.")
            composer.line("No environment value was changed and no drone command was sent.")
            content = composer.render()
        except Exception as exc:
            content = f"Environment registry metadata could not be loaded: {exc}"
        return self._answer(
            "environment_summary",
            content,
            ("mds.system.env_registry.read", "mds.system.env_gcs.read"),
            response_mode="interpret",
        )

    def sidecar_status(self) -> MdsReadToolAnswer:
        try:
            sidecar_payload = self._fleet_sidecars_payload()
            sidecars = sidecar_payload.get("sidecars") if isinstance(sidecar_payload.get("sidecars"), Mapping) else {}
            wifi_table = _copy_mapping(sidecars.get("smart-wifi-manager"))
            mavlink_table = _copy_mapping(sidecars.get("mavlink-anywhere"))
            from src.managed_runtime_status import build_connectivity_runtime_summary, build_mavlink_runtime_summary

            wifi = build_connectivity_runtime_summary(REPO_ROOT)
            mavlink = build_mavlink_runtime_summary(REPO_ROOT)
            composer = AnswerComposer()
            composer.line("Fleet Ops sidecar status from current GCS state:")
            composer.blank().table(
                ("Sidecar", "Purpose", "Dashboard", "Runtime"),
                (
                    (
                        "smart-wifi-manager",
                        "Wi-Fi profile/status management",
                        "[Wi-Fi profiles](/fleet-ops/wifi), default node port `9080`",
                        _sidecar_runtime_status(wifi),
                    ),
                    (
                        "mavlink-anywhere",
                        "MAVLink routing/status management",
                        "[MAVLink profiles](/fleet-ops/mavlink), default node port `9070`",
                        _sidecar_runtime_status(mavlink),
                    ),
                ),
            )
            table_rows = _sidecar_summary_rows(
                (
                    ("smart-wifi-manager", wifi_table),
                    ("mavlink-anywhere", mavlink_table),
                )
            )
            if table_rows:
                composer.blank().line("Fleet-wide table state:")
                composer.table(("Sidecar", "Nodes", "Online", "Mode(s)", "Drift", "Baseline"), table_rows)

            node_rows = _sidecar_node_rows(
                (
                    ("smart-wifi-manager", wifi_table),
                    ("mavlink-anywhere", mavlink_table),
                )
            )
            if node_rows:
                composer.blank().line("Node evidence snapshot:")
                composer.table(("Node", "Sidecar", "Presence", "Service", "Mode", "Drift", "Dashboard"), node_rows[:8])
                if len(node_rows) > 8:
                    composer.line(f"Showing 8 of {len(node_rows)} sidecar row(s); open Fleet Ops for the full table.")

            composer.blank().line("Use [Fleet Ops](/fleet-ops) for the full fleet posture, [Wi-Fi profiles](/fleet-ops/wifi) for Smart Wi-Fi Manager, and [MAVLink profiles](/fleet-ops/mavlink) for MAVLink Anywhere.")
            composer.line("Simurgh can inspect sidecar state here; profile apply/reconcile/delete remains a human-controlled Fleet Ops action.")
            composer.line("If a node dashboard is reachable but profile mutation reports a required API token, treat that as sidecar mutation-token configuration, not a MAVLink flight-control issue.")
            network_details = self._fleet_network_details()
            network_count = _network_detail_count(network_details)
            if network_count:
                composer.line(f"Fleet network detail rows visible to GCS: {network_count}.")
            composer.line("No Wi-Fi profile, MAVLink route, repository state, or drone setting was changed.")
            content = composer.render()
        except Exception as exc:
            content = f"Fleet sidecar status could not be loaded: {exc}"
        return self._answer(
            "sidecar_status",
            content,
            (
                "mds.fleet.sidecars.read",
                "mds.fleet.sidecar.read",
                "mds.fleet.network_details.read",
                "mds.fleet.sidecars.connectivity_profile.read",
            ),
        )

    def node_boot_status(self, message: str = "") -> MdsReadToolAnswer:
        try:
            payload = self._node_boot_status_payload()
            nodes = payload.get("nodes") if isinstance(payload.get("nodes"), Mapping) else {}
            rows: list[tuple[str, str, str, str, str, str]] = []
            for hw_id, raw_node in sorted(nodes.items(), key=lambda item: str(item[0])):
                node = _copy_mapping(raw_node)
                rows.append(
                    (
                        str(node.get("hw_id") or hw_id),
                        str(node.get("pos_id") if node.get("pos_id") is not None else "n/a"),
                        str(node.get("status") or "unknown"),
                        str(node.get("phase") or "unknown"),
                        str(node.get("source") or "unknown"),
                        _format_epoch_utc(node.get("timestamp")),
                    )
                )

            composer = AnswerComposer()
            composer.line("Fleet node boot/init status from GCS read-only reports:")
            if rows:
                composer.blank().table(("Node", "Pos", "Status", "Phase", "Source", "Updated"), rows)
            else:
                composer.blank().line(
                    "No node boot/init reports are currently cached by this GCS runtime. "
                    "That can mean the boards are already past bootstrap, not reporting boot progress, or offline from the GCS API path."
                )
            composer.blank().line(
                "Use this to separate early startup/git-sync/sidecar initialization from MAVLink flight readiness. "
                "For commandable vehicle state, still verify fresh heartbeats, telemetry, QGC identity, and operator preflight checks."
            )
            composer.line("No repository sync, sidecar action, or drone command was sent.")
            content = composer.render()
        except Exception as exc:
            content = f"Fleet node boot/init status could not be loaded: {exc}"
        return self._answer(
            "node_boot_status",
            content,
            ("mds.fleet.node_boot_status.read",),
            response_mode="status",
        )

    def _node_boot_status_payload(self) -> dict[str, Any]:
        getter = getattr(self.deps, "get_node_boot_status_payload", None)
        if callable(getter):
            try:
                return _copy_mapping(getter() or {})
            except Exception:
                return {}
        try:
            from api_routes.core import _build_node_boot_status_response

            return _model_payload(_build_node_boot_status_response())
        except Exception:
            return {"nodes": {}, "total_nodes": 0, "timestamp": int(time.time() * 1000)}

    def _fleet_sidecars_payload(self) -> dict[str, Any]:
        getter = getattr(self.deps, "get_fleet_sidecars_payload", None)
        if callable(getter):
            try:
                return _copy_mapping(getter() or {})
            except Exception:
                return {}
        try:
            from api_routes.fleet_sidecars import DRIFT_STATES, HASH_SEMANTICS, POLICY_MODES, _build_sidecar_table

            deps = self._sidecar_api_deps()
            return {
                "schema": "mds.sidecar_profile.v1",
                "modes": sorted(POLICY_MODES),
                "drift_states": sorted(DRIFT_STATES),
                "hash_semantics": HASH_SEMANTICS,
                "sidecars": {
                    "smart-wifi-manager": _build_sidecar_table(deps, "smart-wifi-manager"),
                    "mavlink-anywhere": _build_sidecar_table(deps, "mavlink-anywhere"),
                },
                "timestamp": int(time.time() * 1000),
            }
        except Exception:
            return {}

    def _sidecar_api_deps(self) -> Any:
        deps = self.deps
        if deps is not None and callable(getattr(deps, "load_config", None)) and getattr(deps, "BASE_DIR", None):
            return deps

        try:
            from params import Params
        except Exception:
            class Params:  # pylint: disable=too-few-public-methods
                TELEMETRY_POLLING_TIMEOUT = 5
                drone_api_port = 7070

        app_module = sys.modules.get("app_fastapi")

        class LocalSidecarDeps:  # pylint: disable=too-few-public-methods
            BASE_DIR = str(REPO_ROOT)
            Params = Params
            git_status_data_all_drones = getattr(app_module, "git_status_data_all_drones", {}) if app_module else {}
            data_lock_git_status = getattr(app_module, "data_lock_git_status", None) if app_module else None

        local = LocalSidecarDeps()
        local.load_config = self._fleet_config
        local.get_all_heartbeats = self._heartbeat_snapshot
        return local

    def _fleet_network_details(self) -> Any:
        getter = getattr(self.deps, "get_network_info_from_heartbeats", None)
        if callable(getter):
            try:
                return getter() or []
            except Exception:
                return []
        try:
            from heartbeat import get_network_info_from_heartbeats

            return get_network_info_from_heartbeats() or []
        except Exception:
            return []

    def _git_status_payload(self) -> dict[str, Any]:
        getter = getattr(self.deps, "get_git_status_payload", None)
        if callable(getter):
            try:
                return _copy_mapping(getter() or {})
            except Exception:
                return {}
        try:
            from api_routes.git_status import _build_git_status_response

            return _model_payload(_build_git_status_response(self._git_api_deps()))
        except Exception:
            gcs_status = self._gcs_git_report()
            return {
                "git_status": {},
                "total_drones": 0,
                "synced_count": 0,
                "needs_sync_count": 0,
                "gcs_status": gcs_status or None,
                "sync_in_progress": False,
                "timestamp": int(time.time() * 1000),
            }

    def _git_api_deps(self) -> Any:
        deps = self.deps
        if (
            deps is not None
            and callable(getattr(deps, "load_config", None))
            and callable(getattr(deps, "get_gcs_git_report", None))
            and hasattr(deps, "git_status_data_all_drones")
            and hasattr(deps, "data_lock_git_status")
        ):
            if not hasattr(deps, "_sync_state"):
                deps._sync_state = {"active": False}
            return deps

        try:
            from params import Params
        except Exception:
            class Params:  # pylint: disable=too-few-public-methods
                TELEMETRY_POLLING_TIMEOUT = 5

        from threading import RLock

        app_module = sys.modules.get("app_fastapi")

        class LocalGitDeps:  # pylint: disable=too-few-public-methods
            Params = Params
            git_status_data_all_drones = getattr(app_module, "git_status_data_all_drones", {}) if app_module else {}
            data_lock_git_status = getattr(app_module, "data_lock_git_status", None) or RLock()
            _sync_state = getattr(app_module, "_sync_state", {"active": False}) if app_module else {"active": False}

        local = LocalGitDeps()
        local.load_config = self._fleet_config
        local.get_gcs_git_report = self._gcs_git_report
        local.get_all_heartbeats = self._heartbeat_snapshot
        return local

    def _gcs_git_report(self) -> dict[str, Any]:
        getter = getattr(self.deps, "get_gcs_git_report", None)
        if callable(getter):
            try:
                return _copy_mapping(getter() or {})
            except Exception:
                return {}
        try:
            from config import get_gcs_git_report

            return _copy_mapping(get_gcs_git_report() or {})
        except Exception:
            return {}

    def px4_params_summary(self) -> MdsReadToolAnswer:
        try:
            from params import Params
            from px4_param_store import build_px4_param_policy_payload, list_repo_profiles

            params_obj = getattr(self.deps, "Params", Params)
            policy = _model_payload(build_px4_param_policy_payload(params_obj))
            profiles = _model_payload(list_repo_profiles(params_obj))
            profile_rows = []
            for profile in profiles.get("profiles") or []:
                if not isinstance(profile, Mapping):
                    continue
                profile_rows.append(
                    (
                        str(profile.get("profile_id") or "profile"),
                        str(profile.get("name") or "-"),
                        str(profile.get("entry_count") or 0),
                        str(profile.get("recommended_scope") or "-"),
                    )
                )

            composer = AnswerComposer()
            composer.line("PX4 parameter support in Simurgh provides status and profile guidance.")
            composer.blank().table(
                ("Capability", "Current value"),
                (
                    ("Profiles available", str(profiles.get("total_profiles", len(profile_rows)))),
                    ("Supports MDS profiles", str(policy.get("supports_mds_profiles", True))),
                    ("Snapshot route", "available through GCS API / PX4 Parameters page"),
                    ("Patch/apply", "not registered as a conversational Simurgh action"),
                ),
            )
            if profile_rows:
                composer.blank().line("Repository profiles:")
                composer.table(("Profile", "Name", "Entries", "Scope"), profile_rows[:8])
            composer.blank().line("Use [PX4 Parameters](/px4-params) for snapshots, diffs, reviewed profiles, and patch-job review. Keep PX4 `SYS_ID` unique per vehicle before QGC/MDS tests.")
            composer.line("No PX4 parameter was read from a drone, changed, imported, or applied by this answer.")
            content = composer.render()
        except Exception as exc:
            content = f"PX4 parameter metadata could not be loaded: {exc}"
        return self._answer(
            "px4_params_summary",
            content,
            ("mds.px4_params.policy.read", "mds.px4_params.profiles.read"),
            response_mode="interpret",
        )

    def origin_status(self) -> MdsReadToolAnswer:
        origin = self._origin_snapshot()
        positions = self._positions_by_hw_id()
        composer = AnswerComposer()
        composer.line("Origin and launch-position status from GCS configuration:")
        if origin and origin.get("lat") not in (None, "") and origin.get("lon") not in (None, ""):
            composer.blank().table(
                ("Field", "Value"),
                (
                    ("Latitude", _fmt_coordinate(_finite_or_none(origin.get("lat")))),
                    ("Longitude", _fmt_coordinate(_finite_or_none(origin.get("lon")))),
                    ("Altitude", _fmt_altitude_m(_finite_or_none(origin.get("alt")))),
                    ("Source", str(origin.get("alt_source") or origin.get("source") or "unknown")),
                ),
            )
        else:
            composer.blank().line("No mission/global origin is currently set in the GCS origin store.")
        if positions:
            composer.blank().line("Configured launch/trajectory start positions:")
            rows = []
            for hw_id, item in sorted(positions.items()):
                rows.append(
                    (
                        f"hw {hw_id}",
                        str(item.get("pos_id", hw_id)),
                        _fmt_m(item.get("x")),
                        _fmt_m(item.get("y")),
                    )
                )
            composer.table(("Drone", "Pos", "North", "East"), rows[:12])
        else:
            composer.blank().line("No launch/trajectory start positions are visible from the GCS config loader.")
        composer.blank().line("Edit/check this from [Mission Config](/mission-config) and review deviations at [Origin](/origin) when available.")
        composer.line("No origin, launch position, route, or drone command was changed.")
        return self._answer(
            "origin_status",
            composer.render(),
            ("mds.origin.read", "mds.navigation.global_origin.read", "mds.config.positions.read"),
        )

    def command_summary(
        self,
        message: str = "",
        *,
        action_context: Mapping[str, Any] | None = None,
    ) -> MdsReadToolAnswer:
        snapshot = _scope_command_snapshot_to_action(
            self._command_tracker_snapshot(),
            action_context,
        )
        composer = AnswerComposer()
        composer.line(
            "Action-run command tracker summary:"
            if snapshot.get("action_scoped")
            else "GCS command tracker summary:"
        )
        if not snapshot.get("available"):
            composer.blank().line("The command tracker is not available from this Simurgh process.")
        else:
            stats = snapshot.get("stats") if isinstance(snapshot.get("stats"), Mapping) else {}
            active = snapshot.get("active") if isinstance(snapshot.get("active"), list) else []
            recent = snapshot.get("recent") if isinstance(snapshot.get("recent"), list) else []
            composer.blank().table(
                ("Metric", "Value"),
                (
                    ("Active commands", str(len(active))),
                    ("Recent commands retained", str(len(recent))),
                    ("Total commands since tracker start", _known_metric(stats, "total_commands")),
                    ("Successful", _known_metric(stats, "successful_commands")),
                    ("Failed", _known_metric(stats, "failed_commands")),
                    ("Partial", _known_metric(stats, "partial_commands")),
                ),
            )
            selected = active if _has_domain_signal(_normalize_text(message), ("active", "running", "in progress")) else recent[:8]
            if selected:
                composer.blank().line("Command records:")
                composer.table(
                    ("Command", "Mission", "Phase", "Status", "Targets"),
                    (
                        (
                            str(item.get("command_id") or "")[:12],
                            str(item.get("mission_name") or item.get("mission_type") or "-"),
                            str(item.get("phase") or "-"),
                            str(item.get("status") or "-"),
                            ", ".join(str(target) for target in item.get("target_drones") or ()) or "-",
                        )
                        for item in selected
                    ),
                )
            else:
                composer.blank().line("No active/recent command records are currently retained in the tracker.")
            missing_command_ids = snapshot.get("missing_command_ids")
            if isinstance(missing_command_ids, list) and missing_command_ids:
                composer.blank().line(
                    f"{len(missing_command_ids)} command ID(s) from the durable action run are no longer retained by the in-memory tracker."
                )
        composer.blank().line("Open the command/audit UI for full command details. No command was submitted, retried, or cancelled.")
        return self._answer(
            "command_summary",
            composer.render(),
            ("mds.commands.active.read", "mds.commands.recent.read", "mds.commands.statistics.read"),
        )

    def git_status_summary(self, message: str = "") -> MdsReadToolAnswer:
        payload = self._git_status_payload()
        gcs_status = _copy_mapping(payload.get("gcs_status"))
        drone_status = payload.get("git_status") if isinstance(payload.get("git_status"), Mapping) else {}
        uncommitted = _safe_string_list(gcs_status.get("uncommitted_changes"))
        wants_commit_detail = _has_domain_signal(_normalize_text(message), ("commit", "uncommitted", "dirty", "push", "pushed", "write-back", "writeback"))

        composer = AnswerComposer()
        composer.line("GCS repository and fleet sync status from current git evidence:")
        composer.blank().table(
            ("Area", "Value"),
            (
                ("GCS branch", str(gcs_status.get("branch") or "unknown")),
                ("GCS commit", _short_commit(gcs_status.get("commit"))),
                ("GCS status", _git_status_label(gcs_status)),
                ("Uncommitted GCS changes", str(len(uncommitted))),
                ("Drone git rows", str(payload.get("total_drones", len(drone_status) or 0))),
                ("Synced online rows", str(payload.get("synced_count", 0))),
                ("Need sync", str(payload.get("needs_sync_count", 0))),
                ("Sync in progress", "yes" if payload.get("sync_in_progress") else "no"),
            ),
        )
        if uncommitted:
            shown_changes = uncommitted[:6]
            composer.blank().line("Current GCS working-tree changes:")
            composer.bullets(shown_changes)
            if len(uncommitted) > len(shown_changes):
                composer.line(f"Showing {len(shown_changes)} of {len(uncommitted)} change(s).")

        node_rows = _git_node_rows(drone_status)
        if node_rows:
            composer.blank().line("Node repository snapshot:")
            composer.table(("Drone", "Status", "Sync", "Branch", "Commit", "Auth"), node_rows[:8])
            if len(node_rows) > 8:
                composer.line(f"Showing 8 of {len(node_rows)} node git row(s); open Fleet Ops for the full table.")
        else:
            composer.blank().line("No per-drone git status rows are currently visible to this GCS runtime.")

        if wants_commit_detail and uncommitted:
            composer.blank().line("Operator meaning: the GCS has saved repo changes that still need commit/write-back before nodes can sync to that exact state.")
        elif wants_commit_detail:
            composer.blank().line("Operator meaning: no uncommitted GCS working-tree change is reported in this snapshot.")
        composer.line("Use [Fleet Ops](/fleet-ops) for node sync details and [Smart Swarm](/swarm-design) or the relevant editor page for the source workflow.")
        composer.line("No git commit, push, pull, node sync, configuration, or drone action was executed.")
        return self._answer(
            "git_status_summary",
            composer.render(),
            ("mds.git.status.read",),
        )

    def runtime_summary(self) -> MdsReadToolAnswer:
        try:
            from .assistant import load_default_assistant_config
            from .policy import load_default_policy
            from src.settings.runtime import resolve_runtime_mode

            config = load_default_assistant_config()
            policy = load_default_policy()
            runtime = resolve_runtime_mode()
            key_path = str(config.openai.api_key_file or "")
            key_ready = bool(key_path and Path(key_path).is_file())
            composer = AnswerComposer()
            composer.line("Simurgh runtime posture:")
            composer.blank()
            composer.table(
                ("Setting", "Value"),
                (
                    ("GCS mode", f"{runtime.mode} ({runtime.source})"),
                    ("Agent", "enabled" if policy.agent_enabled else "disabled"),
                    ("MCP", "enabled" if policy.mcp_enabled else "disabled"),
                    ("Provider", config.provider),
                    ("OpenAI model", config.openai.model),
                    ("OpenAI key file", "configured/readable" if key_ready else "not ready"),
                    ("Circuit breaker", "on" if policy.action_circuit_breaker_enabled else "off"),
                    ("Always confirm before action", "on" if policy.always_confirm_before_action else "off"),
                ),
            )
            composer.blank().line("No drone command was sent.")
            content = composer.render()
        except Exception as exc:
            content = f"Simurgh runtime metadata could not be loaded: {exc}"
        return self._answer("runtime_summary", content, ("mds.system.runtime_status.read",))

    def sitl_help(self) -> MdsReadToolAnswer:
        try:
            from src.settings.runtime import resolve_runtime_mode

            runtime = resolve_runtime_mode()
            mode_line = f"Current GCS mode: {runtime.mode} ({runtime.source})."
        except Exception as exc:
            mode_line = f"Current GCS mode could not be resolved: {exc}"
        content = "\n".join(
            [
                mode_line,
                "To go to SITL, use a SITL startup/profile instead of flipping a live field runtime:",
                "- Confirm the field team is not relying on this GCS instance for real vehicles.",
                "- Development profile: `bash app/linux_dashboard_start.sh --sitl`.",
                "- Production-style SITL profile: `bash app/linux_dashboard_start.sh --prod --sitl`.",
                "- Verify Dashboard `/sitl-control`, `/environments`, and QGC show simulator vehicles only.",
                "- Keep Simurgh circuit breaker on until SITL plans have been reviewed and approved.",
                "Docs: " + _doc_link("advanced SITL", "mds.advanced_sitl") + ", " + _doc_link("SITL comprehensive guide", "mds.sitl_comprehensive") + ", " + _doc_link("GCS API surface", "mds.gcs_api") + ".",
                *_docs_source_lines("SITL demo setup", tags="sitl", limit=3),
                "No drone command was sent.",
            ]
        )
        return self._answer(
            "sitl_help",
            content,
            ("mds.docs.sitl.read", "mds.system.runtime_status.read"),
            response_mode="workflow",
        )

    def sitl_status(self, *, response_detail: str = "standard") -> MdsReadToolAnswer:
        """Read the managed SITL inventory and policy without invoking a lifecycle action."""

        try:
            service = getattr(self.deps, "sitl_control_service", None)
            if service is None:
                params = getattr(self.deps, "Params", None)
                if params is None:
                    raise RuntimeError("SITL control service is not available")
                from src.sitl_control_service import SitlControlService

                service = SitlControlService(params, repo_root=str(REPO_ROOT))

            inventory = _model_payload(service.list_instances())
            policy = _model_payload(service.build_policy())
            instances = inventory.get("instances")
            if not isinstance(instances, list):
                instances = []
            total = inventory.get("total_instances")
            if not isinstance(total, int) or isinstance(total, bool):
                total = len(instances)
            active = inventory.get("running_instance_count")
            if not isinstance(active, int) or isinstance(active, bool):
                active = sum(
                    1
                    for item in instances
                    if isinstance(item, Mapping)
                    and str(item.get("state") or item.get("status") or "").casefold() == "running"
                )
            docker = inventory.get("docker")
            if not isinstance(docker, Mapping):
                docker = policy.get("docker") if isinstance(policy.get("docker"), Mapping) else {}
            docker_reachable = docker.get("daemon_reachable")
            if docker_reachable is None:
                docker_reachable = docker.get("available")

            composer = AnswerComposer()
            brief = _normalize_response_detail(response_detail) == "brief"
            composer.line(
                f"SITL instances: {total} total, {active} active; "
                f"Docker reachable: {_fmt_bool_state(docker_reachable)}."
            )
            active_rows = [
                item
                for item in instances
                if isinstance(item, Mapping)
                and str(item.get("state") or item.get("status") or "").casefold() == "running"
            ]
            if active_rows:
                rows: list[tuple[str, str, str, str]] = []
                for item in active_rows[:8]:
                    sync = []
                    if item.get("git_sync_enabled") is not None:
                        sync.append(f"git {'on' if item.get('git_sync_enabled') else 'off'}")
                    if item.get("requirements_sync_enabled") is not None:
                        sync.append(f"requirements {'on' if item.get('requirements_sync_enabled') else 'off'}")
                    rows.append(
                        (
                            str(item.get("name") or "SITL instance"),
                            str(item.get("state") or item.get("status") or "unknown"),
                            str(item.get("image_ref") or "unknown"),
                            ", ".join(sync) or "not reported",
                        )
                    )
                if brief:
                    composer.line(
                        "Active: "
                        + "; ".join(
                            f"{name} {state}, image {image}, startup sync {sync}"
                            for name, state, image, sync in rows
                        )
                        + "."
                    )
                else:
                    composer.blank().table(("Instance", "State", "Image", "Startup sync"), rows)
            elif total == 0:
                composer.line("No simulator drone instance is currently running.")

            sim_mode = policy.get("sim_mode")
            read_only = policy.get("read_only")
            if not brief and (sim_mode is not None or read_only is not None):
                policy_values = []
                if sim_mode is not None:
                    policy_values.append(f"sim_mode={sim_mode}")
                if read_only is not None:
                    policy_values.append(f"read_only={read_only}")
                composer.line("SITL policy: " + ", ".join(policy_values) + ".")
            if not brief:
                composer.line("No SITL or drone action was executed.")
            content = composer.render()
        except Exception as exc:
            content = f"SITL status is unavailable from the local control service: {exc}"

        return self._answer(
            "sitl_status",
            content,
            ("mds.sitl.instances.read", "mds.sitl.policy.read"),
            response_mode="status",
        )

    def board_setup_help(self) -> MdsReadToolAnswer:
        content = "\n".join(
            [
                "Board setup references:",
                "- [Fleet Enrollment](/fleet-enrollment) for accepting/enrolling new boards.",
                "- [Fleet Ops](/fleet-ops) for status and sync checks.",
                "- [Wi-Fi sidecar profiles](/fleet-ops/wifi) and [MAVLink sidecar profiles](/fleet-ops/mavlink) for field connectivity configuration.",
                "- [Environment registry](/environments) for editable GCS/node settings; keep secrets in server-side secret files.",
                f"- {_doc_link('MDS init setup', 'mds.init_setup')} and {_doc_link('Fleet Ops guide', 'mds.fleet_ops')}.",
                *_docs_source_lines("board setup environment keys fleet enrollment", tags="setup", limit=3),
                "Safe sequence: enroll/verify the board, sync approved sidecar config, set env through the registry, verify unique SYS_ID/MAVLink endpoints, then confirm QGC identity before flight.",
                "For Raspberry Pi / CM4 / companion-computer provisioning, ask for companion setup and I will point to the bootstrap scripts.",
                "No drone command was sent.",
            ]
        )
        return self._answer(
            "board_setup_help",
            content,
            ("mds.docs.board_setup.read", "mds.docs.environment_registry.read"),
            response_mode="workflow",
        )

    def companion_setup_help(self) -> MdsReadToolAnswer:
        content = "\n".join(
            [
                "Companion-computer setup in MDS uses the node bootstrap path, not an ad-hoc Raspberry Pi checklist.",
                "Primary scripts:",
                "- `tools/install_mds_node.sh` is the public one-line node bootstrap entrypoint.",
                "- `tools/install_companion.sh` is the companion alias for the same supported path.",
                "- `tools/mds_node_init.sh` is the modular init engine used by the bootstrap.",
                "- `tools/mds_node_announce.sh` announces the node back to Fleet Enrollment after install.",
                "Useful docs and pages:",
                f"- {_doc_link('MDS init setup', 'mds.init_setup')}",
                f"- {_doc_link('Node bootstrap and fleet enrollment design', 'mds.node_bootstrap_design')}",
                f"- {_doc_link('Fleet Ops guide', 'mds.fleet_ops')}",
                f"- {_doc_link('Raspberry Pi services guide', 'mds.raspberry_pi_services')}",
                "- [Fleet Enrollment](/fleet-enrollment), [Fleet Ops](/fleet-ops), [Environment registry](/environments)",
                *_docs_source_lines("companion computer setup raspberry pi node bootstrap", tags="setup", limit=3),
                "Minimal operator sequence:",
                "1. Start from the approved deployment image or a clean Pi/CM4 OS for this fleet.",
                "2. Run the deployment-approved `tools/install_mds_node.sh` or `tools/install_companion.sh` command for the correct repo/branch/profile.",
                "3. Let the node announce itself, then accept/verify it in [Fleet Enrollment](/fleet-enrollment).",
                "4. Assign unique identity, hostname, hardware ID, PX4 SYS_ID, MAVLink ports, and approved sidecar profile.",
                "5. Verify QGC/MDS sees the right vehicle before any prop-on or field test.",
                "Do not paste private repo URLs, SSH keys, NetBird keys, or raw env secrets into chat. Use the Environment page or host secret files.",
                "No drone command was sent.",
            ]
        )
        return self._answer(
            "companion_setup_help",
            content,
            ("mds.docs.companion_setup.read", "mds.docs.fleet_enrollment.read"),
            response_mode="workflow",
        )

    def add_drone_workflow_help(self) -> MdsReadToolAnswer:
        config = self._fleet_config()
        next_hw_id = _next_numeric_id((drone.get("hw_id") for drone in config))
        next_pos_id = _next_numeric_id((drone.get("pos_id", drone.get("hw_id")) for drone in config))
        content = "\n".join(
            [
                f"Current fleet configuration has {len(config)} drone(s). For a new drone, the next typical hardware ID is {next_hw_id} and position ID is {next_pos_id}; verify those are still free before editing.",
                "",
                "Add-drone workflow:",
                "1. Prepare the companion computer with the approved MDS node/bootstrap path, not an ad-hoc image.",
                "2. Enroll or verify the board in [Fleet Enrollment](/fleet-enrollment), then check sync/status in [Fleet Ops](/fleet-ops).",
                "3. Add a unique fleet entry: `hw_id`, `pos_id`, callsign, IP or overlay endpoint, MAVLink port, serial path, and baudrate.",
                "4. Set PX4 identity so `SYS_ID` is unique and matches the intended hardware/position mapping in QGC and MDS.",
                "5. Add/update swarm assignment, launch/trajectory start position, and show/drone-file mapping for the new `pos_id`.",
                "6. Validate config, telemetry presence, and QGC vehicle identity on the bench before any prop-on field test.",
                "7. Reprocess/review the show or swarm trajectory if the mission asset must include the third drone.",
                "",
                "Useful pages and docs:",
                "- [Fleet Enrollment](/fleet-enrollment), [Fleet Ops](/fleet-ops), [Environment registry](/environments), [Swarm Design](/swarm-design), [Show Design](/manage-drone-show).",
                f"- {_doc_link('MDS init setup', 'mds.init_setup')}, {_doc_link('Fleet Ops guide', 'mds.fleet_ops')}, {_doc_link('Node bootstrap and fleet enrollment design', 'mds.node_bootstrap_design')}.",
                *_docs_source_lines("add third drone fleet enrollment companion setup swarm show mapping", tags="setup", limit=3),
                "No drone command, config write, or deployment action was executed.",
            ]
        )
        return self._answer(
            "add_drone_workflow",
            content,
            (
                "mds.config.fleet.read",
                "mds.docs.companion_setup.read",
                "mds.docs.fleet_enrollment.read",
                "mds.docs.environment_registry.read",
            ),
            response_mode="workflow",
        )

    def docs_help(self) -> MdsReadToolAnswer:
        content = "\n".join(
            [
                "Useful MDS references:",
                "- [Simurgh Operator](/simurgh) and " + _doc_link("Simurgh guide", "simurgh.operator_guide"),
                "- " + _doc_link("GCS API surface", "mds.gcs_api"),
                "- [Environment registry](/environments) and " + _doc_link("generated env reference", "mds.environment_registry"),
                "- [Logs](/logs) and " + _doc_link("logging guide", "mds.logging_system"),
                "- [SITL Control](/sitl-control), " + _doc_link("advanced SITL", "mds.advanced_sitl") + ", " + _doc_link("SITL comprehensive guide", "mds.sitl_comprehensive"),
                *_docs_source_lines("Simurgh operator environment logs SITL setup", limit=4),
                "Ask for board setup, companion setup, SITL demo, swarm, show, logs, or MCP guidance for a narrower checklist.",
                "No drone command was sent.",
            ]
        )
        return self._answer("docs_help", content, ("mds.docs.index.read",), response_mode="workflow")

    def drone_log_summary(
        self,
        message: str = "",
        *,
        target_drone_ids: Sequence[str] = (),
        action_context: Mapping[str, Any] | None = None,
        response_detail: str = "standard",
        read_options: Mapping[str, object] | None = None,
    ) -> MdsReadToolAnswer:
        config = self._fleet_config()
        normalized_message = _normalize_text(message)
        brief = _normalize_response_detail(response_detail) == "brief"
        structured_options = (
            DroneLogReadOptions.from_mapping(read_options)
            if read_options is not None
            else None
        )
        operation_verification = (
            structured_options.verify_operation
            if structured_options is not None
            else _looks_like_operation_log_verification_question(normalized_message)
        )
        include_unified_logs = (
            structured_options.include_unified_logs
            if structured_options is not None
            else operation_verification
        )
        parse_latest_ulog = (
            structured_options.analyze_latest_ulog
            if structured_options is not None
            else _looks_like_ulog_parse_summary_request(normalized_message)
        )
        command_snapshot = (
            _scope_command_snapshot_to_action(
                self._command_tracker_snapshot(),
                action_context,
            )
            if operation_verification
            else None
        )
        scoped_config = self._drone_log_scope(
            config,
            normalized_message,
            command_snapshot=command_snapshot,
        )
        requested_targets = {
            _as_str(item)
            for item in target_drone_ids
            if _as_str(item)
        }
        if requested_targets:
            scoped_config = [
                drone
                for drone in config
                if _as_str(drone.get("hw_id")) in requested_targets
            ]
        composer = AnswerComposer()
        composer.line("Flight evidence summary:" if brief else "Drone log evidence from the GCS log proxy:")
        unified_events: list[dict[str, Any]] = []
        unified_sources: list[str] = []
        tool_ids: tuple[str, ...] = (
            "mds.logs.drone_sessions.read",
            "mds.logs.drone_ulog_files.read",
            "mds.logs.drone_ulog_summary.read",
            "mds.logs.drone_session.read",
        )

        if operation_verification:
            if brief:
                self._append_brief_recent_command_evidence(composer, snapshot=command_snapshot)
            else:
                self._append_recent_command_evidence(composer, snapshot=command_snapshot)
            tool_ids = (
                "mds.commands.active.read",
                "mds.commands.recent.read",
                "mds.commands.statistics.read",
                *tool_ids,
            )
        if include_unified_logs:
            if brief:
                unified_events, unified_sources = (
                    self._append_brief_unified_log_evidence(
                        composer,
                        message=message,
                        action_context=action_context,
                    )
                )
            else:
                unified_events, unified_sources = self._append_unified_log_evidence(
                    composer,
                    message=message,
                    action_context=action_context,
                )
            tool_ids = (
                "mds.logs.sessions.read",
                "mds.logs.sources.read",
                *tool_ids,
            )

        if not scoped_config:
            composer.blank().line(
                "No configured drones are visible in the GCS fleet config, so there are no per-drone log endpoints to inspect."
            )
            composer.line("No action was executed; raw ULog content was not exposed.")
            return self._answer(
                "drone_log_summary",
                composer.render(),
                tool_ids,
            )

        rows: list[tuple[str, str, str, str, str, str]] = []
        ulog_summary_rows: list[tuple[str, str, str, str, str, str]] = []
        parsed_ulog_summaries: list[tuple[int, int, dict[str, Any]]] = []
        ulog_safety_lines: list[str] = []
        warning_error_samples: list[str] = []
        total_sessions = 0
        total_ulogs = 0
        latest_warning_error_total = 0
        session_inventory_available = 0
        ulog_inventory_available = 0
        warning_sample_available = 0
        unavailable: list[str] = []
        cleanup_failures: list[str] = []
        cleanup_unknown: list[str] = []
        max_ulog_summaries = max(0, _env_int("MDS_SIMURGH_ULOG_SUMMARY_MAX_DRONES", 2))
        eligible_ulog_summaries = 0
        attempted_ulog_summaries = 0
        parsed_ulog_count = 0
        scoped_count = len(scoped_config)

        scoped_ids = [str(drone.get("hw_id")) for drone in scoped_config if drone.get("hw_id") not in (None, "")]
        if scoped_ids and len(scoped_config) < len(config):
            composer.line("Scope: " + ", ".join(f"Drone {hw_id}" for hw_id in scoped_ids) + ".")

        evidence_deadline = time.monotonic() + max(
            0.1,
            _env_float(
                "MDS_SIMURGH_DRONE_LOG_EVIDENCE_DEADLINE_SEC",
                DEFAULT_DRONE_LOG_EVIDENCE_DEADLINE_SECONDS,
            ),
        )
        base_evidence = self._collect_drone_log_base_evidence(
            scoped_config,
            deadline=evidence_deadline,
        )
        for evidence in base_evidence:
            hw_id = evidence.hw_id
            sessions = list(evidence.sessions)
            ulog_files = list(evidence.ulog_files)
            if not evidence.session_error:
                session_inventory_available += 1
                total_sessions += len(sessions)
            else:
                unavailable.append(f"Drone {hw_id} sessions: {evidence.session_error}")
            if evidence.warning_error_count is not None:
                warning_sample_available += 1
                latest_warning_error_total += evidence.warning_error_count
            elif evidence.warning_error_detail:
                unavailable.append(evidence.warning_error_detail)
            if not evidence.ulog_error:
                ulog_inventory_available += 1
                total_ulogs += len(ulog_files)
            else:
                unavailable.append(f"Drone {hw_id} ULog list: {evidence.ulog_error}")
            if not evidence.ulog_error and parse_latest_ulog and ulog_files:
                eligible_ulog_summaries += 1
            rows.append(
                (
                    f"Drone {hw_id}",
                    evidence.ip or "unknown",
                    (
                        str(len(sessions))
                        if not evidence.session_error
                        else f"unavailable ({evidence.session_error})"
                    ),
                    (
                        str(len(ulog_files))
                        if not evidence.ulog_error
                        else f"unavailable ({evidence.ulog_error})"
                    ),
                    (
                        _latest_ulog_label(ulog_files)
                        if not evidence.ulog_error
                        else "unavailable"
                    ),
                    evidence.warning_error_label,
                )
            )
            for sample in evidence.warning_error_samples:
                if len(warning_error_samples) >= DRONE_LOG_WARNING_SAMPLE_LIMIT:
                    break
                warning_error_samples.append(
                    _format_drone_log_warning_sample(evidence.hw_id, sample)
                )

        summary_candidates = [
            (
                evidence,
                _ulog_log_id(evidence.ulog_files[0]),
            )
            for evidence in base_evidence
            if (
                parse_latest_ulog
                and not evidence.ulog_error
                and evidence.ulog_files
                and _ulog_log_id(evidence.ulog_files[0]) is not None
            )
        ][:max_ulog_summaries]
        attempted_ulog_summaries = len(summary_candidates)
        summary_results = self._collect_drone_ulog_summaries(
            summary_candidates,
            deadline=evidence_deadline,
        )
        for (evidence, log_id), (summary_payload, summary_error) in zip(
            summary_candidates,
            summary_results,
        ):
            if log_id is None:
                continue
            hw_id = evidence.hw_id
            if summary_error:
                unavailable.append(
                    f"Drone {hw_id} ULog summary id {log_id}: {summary_error}"
                )
                ulog_summary_rows.append(
                    (
                        f"Drone {hw_id}",
                        str(log_id),
                        "unavailable",
                        "-",
                        "-",
                        summary_error,
                    )
                )
                continue
            rendered_summary = _copy_mapping(summary_payload)
            if _ulog_summary_parsed_successfully(rendered_summary):
                parsed_ulog_count += 1
            rendered_summary["correlation"] = _model_payload(
                _build_ulog_action_correlation(
                    hw_id=hw_id,
                    log_entry=evidence.ulog_files[0],
                    summary=rendered_summary,
                    command_snapshot=command_snapshot,
                    expected_action_reference=_action_context_reference(
                        action_context
                    ),
                    expected_command_ids=_action_context_command_ids(
                        action_context
                    ),
                )
            )
            parsed_ulog_summaries.append((hw_id, log_id, rendered_summary))
            cleanup_status = _ulog_staged_cleanup_status(rendered_summary)
            if cleanup_status is False:
                cleanup_failures.append(
                    f"Drone {hw_id} ULog summary id {log_id}: staged download cleanup failed"
                )
            elif cleanup_status is None:
                cleanup_unknown.append(
                    f"Drone {hw_id} ULog summary id {log_id}: staged download cleanup outcome unavailable"
                )
            ulog_summary_rows.append(
                _format_ulog_summary_row(hw_id, log_id, rendered_summary)
            )
            safety_line = _format_ulog_safety_evidence_line(
                hw_id,
                log_id,
                rendered_summary,
            )
            if safety_line:
                ulog_safety_lines.append(safety_line)

        verdict = self._brief_flight_evidence_verdict(
            command_snapshot=command_snapshot,
            unified_events=unified_events,
            unified_sources=unified_sources,
            parsed_ulog_summaries=parsed_ulog_summaries,
            parse_latest_ulog=parse_latest_ulog,
            eligible_ulog_summaries=eligible_ulog_summaries,
            parsed_ulog_count=parsed_ulog_count,
            total_ulogs=total_ulogs,
            ulog_inventory_available=ulog_inventory_available,
            latest_warning_error_total=latest_warning_error_total,
            warning_sample_available=warning_sample_available,
            scoped_count=scoped_count,
            unavailable=unavailable,
            cleanup_failures=cleanup_failures,
        )
        composer.lines.insert(1, verdict)

        if brief:
            for row in rows:
                composer.line(
                    f"- {row[0]}: {row[2]} log session(s); {row[3]} ULog(s); "
                    f"latest {row[4]}; warnings/errors {row[5]}."
                )
            if warning_error_samples:
                composer.line("Latest drone-log warning/error samples:")
                composer.bullets(warning_error_samples)
            for hw_id, log_id, summary in parsed_ulog_summaries:
                composer.bullets(_format_ulog_brief_lines(hw_id, log_id, summary))
            if parse_latest_ulog and total_ulogs == 0:
                qualifier = (
                    "in the checked scope"
                    if ulog_inventory_available == scoped_count
                    else "in the available inventories; unavailable sources remain unknown"
                )
                composer.line(f"- ULog analysis: no onboard ULog is listed {qualifier}.")
            if cleanup_failures:
                composer.line(f"- Warning: {len(cleanup_failures)} staged ULog cleanup failure(s).")
            if unavailable:
                composer.line(
                    f"- Evidence gaps: {len(unavailable)} check(s) unavailable; "
                    + "; ".join(unavailable[:2])
                    + ("." if len(unavailable) <= 2 else f"; +{len(unavailable) - 2} more.")
                )
            return self._answer(
                "drone_log_summary",
                composer.render(),
                tool_ids,
                response_mode="status",
                safety_notes=(
                    "Answered from read-only GCS-proxied drone log endpoints.",
                    "No command, erase action, raw ULog content fetch for the provider, or raw topic-array exposure was attempted.",
                    "ULog parsing returns derived local metrics only; staged cleanup success, failure, or unknown state is reported from the API result.",
                ),
            )

        composer.blank().table(
            ("Drone", "IP", "Log sessions", "ULogs", "Latest ULog", "Warnings/errors"),
            rows,
        )
        if scoped_count < len(config):
            composer.blank().line(
                f"Request coverage: checked {scoped_count}/{len(config)} configured drone(s); "
                "unchecked drones are not represented by the totals below."
            )
        composer.blank().line(
            "Summary: "
            f"drone log sessions {_covered_count_label(total_sessions, session_inventory_available, scoped_count)}; "
            f"onboard ULogs {_covered_count_label(total_ulogs, ulog_inventory_available, scoped_count)}; "
            "latest-session warning/error lines "
            f"{_covered_count_label(latest_warning_error_total, warning_sample_available, scoped_count)}."
        )
        if warning_error_samples:
            composer.blank().line("Latest drone-log warning/error samples:")
            composer.bullets(warning_error_samples)
        composer.line(
            "Evidence coverage: "
            f"session inventory {session_inventory_available}/{scoped_count}; "
            f"ULog inventory {ulog_inventory_available}/{scoped_count}; "
            f"latest-session samples {warning_sample_available}/{scoped_count}."
        )
        composer.line(
            "ULog inventory is metadata unless a parsed summary is shown below; raw `.ulg` content is not included in this answer."
        )
        composer.line(
            "Evidence correlation: latest sessions and newest ULogs are selected by recency. "
            "They are not attributed to a requested action unless a parsed ULog explicitly reports verified correlation."
        )
        if ulog_summary_rows:
            composer.blank().line("Parsed latest ULog summary:")
            composer.table(
                ("Drone", "Log id", "Duration", "Local movement", "Battery", "Command/ack evidence"),
                ulog_summary_rows,
            )
            if ulog_safety_lines:
                composer.blank().line("ULog safety evidence (derived metadata only):")
                composer.bullets(ulog_safety_lines)
        if parse_latest_ulog:
            composer.line(
                "ULog summary coverage: "
                f"{parsed_ulog_count}/{eligible_ulog_summaries} known eligible drone(s) parsed successfully; "
                f"{attempted_ulog_summaries} attempted; cap {max_ulog_summaries}."
            )
            if eligible_ulog_summaries > attempted_ulog_summaries:
                composer.line(
                    f"{eligible_ulog_summaries - attempted_ulog_summaries} eligible newest ULog(s) were left metadata-only by the parse cap."
                )
            if total_ulogs == 0 and ulog_inventory_available == scoped_count:
                composer.line("No onboard ULog file is listed in the complete checked scope, so there is no ULog to parse.")
            elif total_ulogs == 0 and ulog_inventory_available < scoped_count:
                composer.line(
                    "No ULog is listed by the available inventories; unavailable inventories remain unknown."
                )
        if cleanup_failures:
            composer.blank().line("Staged ULog cleanup failures:")
            composer.bullets(cleanup_failures)
        if cleanup_unknown:
            composer.blank().line("Staged ULog cleanup outcome unavailable:")
            composer.bullets(cleanup_unknown)
        if unavailable:
            composer.blank().line("Unavailable checks:")
            composer.bullets(unavailable[:6])
            if len(unavailable) > 6:
                composer.line(f"{len(unavailable) - 6} additional unavailable check(s) omitted for readability.")
        composer.blank().line(
            "Open [Logs](/logs) for GCS logs and per-drone log views. API refs: `GET /api/logs/drone/{drone_id}/sessions` and `GET /api/logs/drone/{drone_id}/ulog/files`."
        )
        composer.line("No action was executed; raw ULog content was not exposed.")
        return self._answer(
            "drone_log_summary",
            composer.render(),
            tool_ids,
            response_mode="status",
            safety_notes=(
                "Answered from read-only GCS-proxied drone log endpoints.",
                "No command, erase action, raw ULog content fetch for the provider, or raw topic-array exposure was attempted.",
                "ULog parsing returns derived local metrics only; staged cleanup success, failure, or unknown state is reported from the API result.",
            ),
        )

    def _collect_drone_log_base_evidence(
        self,
        config: Sequence[Mapping[str, Any]],
        *,
        deadline: float,
    ) -> list[_DroneLogBaseEvidence]:
        scoped = [
            _copy_mapping(drone)
            for drone in config
            if _as_int(drone.get("hw_id")) is not None
        ]
        session_results = self._run_bounded_evidence_tasks(
            scoped,
            worker=lambda drone: self._fetch_drone_session_inventory(
                drone,
                deadline=deadline,
            ),
            deadline=deadline,
        )
        session_state: list[dict[str, Any]] = []
        content_candidates: list[tuple[int, str, str]] = []
        for index, (drone, (result, task_error)) in enumerate(
            zip(scoped, session_results)
        ):
            hw_id = _as_int(drone.get("hw_id"))
            if hw_id is None:
                continue
            ip = str(drone.get("ip") or "").strip()
            sessions: tuple[dict[str, Any], ...] = ()
            session_error = task_error or ""
            if (
                isinstance(result, tuple)
                and len(result) == 2
                and isinstance(result[0], tuple)
            ):
                sessions = result[0]
                session_error = str(result[1] or "")
            state = {
                "hw_id": hw_id,
                "ip": ip,
                "sessions": sessions,
                "session_error": session_error,
                "warning_error_count": None,
                "warning_error_label": "not checked",
                "warning_error_detail": "",
                "warning_error_samples": (),
            }
            if sessions:
                session_id = str(sessions[0].get("session_id") or "").strip()
                if session_id:
                    content_candidates.append((index, ip, session_id))
                else:
                    state["warning_error_label"] = (
                        "unavailable (missing session id)"
                    )
                    state["warning_error_detail"] = (
                        f"Drone {hw_id} latest session: missing session id"
                    )
            elif session_error:
                state["warning_error_label"] = (
                    f"unavailable ({session_error})"
                )
            else:
                state["warning_error_count"] = 0
                state["warning_error_label"] = "0 (no sessions)"
            session_state.append(state)

        content_results = self._run_bounded_evidence_tasks(
            content_candidates,
            worker=lambda candidate: self._fetch_latest_drone_session_sample(
                candidate,
                deadline=deadline,
            ),
            deadline=deadline,
        )
        for (state_index, _ip, _session_id), (
            result,
            task_error,
        ) in zip(content_candidates, content_results):
            if state_index >= len(session_state):
                continue
            state = session_state[state_index]
            content_error = task_error or ""
            content_payload: Mapping[str, Any] = {}
            if (
                isinstance(result, tuple)
                and len(result) == 2
                and isinstance(result[0], Mapping)
            ):
                content_payload = result[0]
                content_error = str(result[1] or "")
            if content_error:
                state["warning_error_label"] = (
                    f"unavailable ({content_error})"
                )
                state["warning_error_detail"] = (
                    f"Drone {state['hw_id']} latest session sample: "
                    f"{content_error}"
                )
            else:
                count = _warning_error_count_from_log_lines(content_payload)
                state["warning_error_count"] = count
                state["warning_error_label"] = (
                    f"{count} in latest session"
                )
                state["warning_error_samples"] = (
                    _warning_error_samples_from_log_lines(
                        content_payload,
                        limit=DRONE_LOG_WARNING_SAMPLE_LIMIT,
                    )
                )

        ulog_results = self._run_bounded_evidence_tasks(
            scoped,
            worker=lambda drone: self._fetch_drone_ulog_inventory(
                drone,
                deadline=deadline,
            ),
            deadline=deadline,
        )
        evidence: list[_DroneLogBaseEvidence] = []
        for state, (result, task_error) in zip(session_state, ulog_results):
            ulog_files: tuple[dict[str, Any], ...] = ()
            ulog_error = task_error or ""
            if (
                isinstance(result, tuple)
                and len(result) == 2
                and isinstance(result[0], tuple)
            ):
                ulog_files = result[0]
                ulog_error = str(result[1] or "")
            evidence.append(
                _DroneLogBaseEvidence(
                    hw_id=int(state["hw_id"]),
                    ip=str(state["ip"]),
                    sessions=state["sessions"],
                    session_error=str(state["session_error"]),
                    warning_error_count=state["warning_error_count"],
                    warning_error_label=str(state["warning_error_label"]),
                    warning_error_detail=str(state["warning_error_detail"]),
                    warning_error_samples=tuple(state["warning_error_samples"]),
                    ulog_files=ulog_files,
                    ulog_error=ulog_error,
                )
            )
        return evidence

    def _fetch_drone_session_inventory(
        self,
        drone: Mapping[str, Any],
        *,
        deadline: float,
    ) -> tuple[tuple[dict[str, Any], ...], str]:
        timeout = _remaining_evidence_timeout(
            deadline,
            DRONE_LOG_PROXY_TIMEOUT_SECONDS,
        )
        if timeout is None:
            return (), "global evidence deadline exceeded"
        payload, error = self._fetch_drone_json(
            str(drone.get("ip") or "").strip(),
            "/api/logs/sessions",
            timeout=timeout,
        )
        return tuple(_log_session_items(payload)), error

    def _fetch_latest_drone_session_sample(
        self,
        candidate: tuple[int, str, str],
        *,
        deadline: float,
    ) -> tuple[dict[str, Any], str]:
        _state_index, ip, session_id = candidate
        timeout = _remaining_evidence_timeout(
            deadline,
            DRONE_LOG_PROXY_TIMEOUT_SECONDS,
        )
        if timeout is None:
            return {}, "global evidence deadline exceeded"
        return self._fetch_drone_json(
            ip,
            f"/api/logs/sessions/{session_id}",
            params={"limit": 200},
            timeout=timeout,
        )

    def _fetch_drone_ulog_inventory(
        self,
        drone: Mapping[str, Any],
        *,
        deadline: float,
    ) -> tuple[tuple[dict[str, Any], ...], str]:
        timeout = _remaining_evidence_timeout(
            deadline,
            drone_ulog_proxy_timeout_seconds(),
        )
        if timeout is None:
            return (), "global evidence deadline exceeded"
        payload, error = self._fetch_drone_json(
            str(drone.get("ip") or "").strip(),
            "/api/v1/ulog/files",
            timeout=timeout,
        )
        return tuple(_ulog_file_items(payload)), error

    def _collect_drone_ulog_summaries(
        self,
        candidates: Sequence[tuple[_DroneLogBaseEvidence, int | None]],
        *,
        deadline: float,
    ) -> list[tuple[dict[str, Any], str]]:
        def collect(
            candidate: tuple[_DroneLogBaseEvidence, int | None],
        ) -> tuple[dict[str, Any], str]:
            evidence, log_id = candidate
            if log_id is None:
                return {}, "missing ULog id"
            timeout = _remaining_evidence_timeout(
                deadline,
                drone_ulog_summary_timeout_seconds(),
            )
            if timeout is None:
                return {}, "global evidence deadline exceeded"
            return self._fetch_drone_json(
                evidence.ip,
                f"/api/v1/ulog/files/{log_id}/summary",
                timeout=timeout,
            )

        raw_results = self._run_bounded_evidence_tasks(
            candidates,
            worker=collect,
            deadline=deadline,
        )
        results: list[tuple[dict[str, Any], str]] = []
        for result, error in raw_results:
            if (
                isinstance(result, tuple)
                and len(result) == 2
                and isinstance(result[0], Mapping)
            ):
                results.append((_copy_mapping(result[0]), str(result[1] or "")))
            else:
                results.append(({}, error or "ULog summary unavailable"))
        return results

    @staticmethod
    def _run_bounded_evidence_tasks(
        items: Sequence[Any],
        *,
        worker: Any,
        deadline: float,
    ) -> list[tuple[Any | None, str]]:
        """Run I/O fan-out concurrently and return results in input order."""

        if not items:
            return []
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return [
                (None, "global evidence deadline exceeded")
                for _item in items
            ]
        max_workers = min(
            len(items),
            DEFAULT_DRONE_LOG_MAX_WORKERS,
            max(
                1,
                _env_int(
                    "MDS_SIMURGH_DRONE_LOG_MAX_WORKERS",
                    DEFAULT_DRONE_LOG_MAX_WORKERS,
                ),
            ),
        )
        request_slots = threading.BoundedSemaphore(max_workers)

        def run_with_request_limit(item: Any) -> Any:
            with request_slots:
                return worker(item)

        futures = [
            _drone_log_evidence_executor().submit(run_with_request_limit, item)
            for item in items
        ]
        concurrent.futures.wait(futures, timeout=remaining)
        ordered: list[tuple[Any | None, str]] = []
        for future in futures:
            if not future.done():
                future.cancel()
                ordered.append(
                    (None, "global evidence deadline exceeded")
                )
                continue
            try:
                ordered.append((future.result(), ""))
            except Exception as exc:
                ordered.append(
                    (
                        None,
                        _truncate_text(str(exc), 80)
                        or "evidence collection failed",
                    )
                )
        return ordered

    def _drone_log_scope(
        self,
        config: list[dict[str, Any]],
        normalized_message: str,
        *,
        command_snapshot: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Bound log review to explicit, recent-command, or live fleet targets."""

        if not config:
            return []
        config_by_id = {
            hw_id: drone
            for drone in config
            if (hw_id := _as_int(drone.get("hw_id"))) is not None
        }

        explicit_hw_id = _extract_hw_id(normalized_message)
        if explicit_hw_id in config_by_id:
            return [config_by_id[explicit_hw_id]]

        if _looks_like_operation_log_verification_question(normalized_message):
            snapshot = command_snapshot or self._command_tracker_snapshot()
            for command in snapshot.get("recent") or ():
                target_ids = [
                    target
                    for raw_target in command.get("target_drones") or ()
                    if (target := _as_int(raw_target)) in config_by_id
                ]
                if target_ids:
                    return [config_by_id[target] for target in dict.fromkeys(target_ids)]

        live_ids: list[int] = []
        heartbeats = self._heartbeat_snapshot()
        telemetry = self._telemetry_snapshot()
        telemetry_success_times = self._telemetry_success_times()
        try:
            from params import Params
            from presence import build_presence_snapshot, resolve_presence_thresholds

            thresholds = resolve_presence_thresholds(Params)
        except Exception:
            build_presence_snapshot = None
            thresholds = None
        now = time.time()
        for hw_id in config_by_id:
            heartbeat = _copy_mapping(heartbeats.get(str(hw_id)) or heartbeats.get(hw_id))
            telemetry_row = _copy_mapping(telemetry.get(str(hw_id)) or telemetry.get(hw_id))
            if build_presence_snapshot is not None:
                presence = build_presence_snapshot(
                    hw_id=str(hw_id),
                    heartbeat=heartbeat,
                    telemetry=telemetry_row,
                    telemetry_success_time=(
                        telemetry_success_times.get(str(hw_id))
                        or telemetry_success_times.get(hw_id)
                    ),
                    configured=True,
                    now=now,
                    thresholds=thresholds,
                )
                live = bool(presence.get("fresh"))
            else:
                live = bool(heartbeat or telemetry_row.get("telemetry_available"))
            if live:
                live_ids.append(hw_id)
        if live_ids:
            return [config_by_id[hw_id] for hw_id in live_ids]

        max_drones = max(1, _env_int("MDS_SIMURGH_DRONE_LOG_MAX_DRONES", 8))
        return config[:max_drones]

    def _append_recent_command_evidence(
        self,
        composer: AnswerComposer,
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        snapshot = snapshot or self._command_tracker_snapshot()
        composer.blank().line(
            "Durable action-run command tracker evidence:"
            if snapshot.get("action_scoped")
            else "Recent command tracker evidence:"
        )
        if not snapshot.get("available"):
            composer.line("The command tracker is not available from this Simurgh process.")
            return
        recent = snapshot.get("recent") if isinstance(snapshot.get("recent"), list) else []
        if not recent:
            composer.line("No active/recent command records are currently retained in the tracker.")
            return
        composer.table(
            ("Command", "Mission", "Phase", "Status", "Outcome", "Targets"),
            (
                (
                    str(item.get("command_id") or "")[:12],
                    str(item.get("mission_name") or item.get("mission_type") or "-"),
                    str(item.get("phase") or "-"),
                    str(item.get("status") or "-"),
                    str(item.get("outcome") or "-"),
                    ", ".join(str(target) for target in item.get("target_drones") or ()) or "-",
                )
                for item in recent[:6]
            ),
        )
        composer.line(
            "Use this as command-tracker evidence only; exact trajectory quality still requires live telemetry history or a parsed ULog."
        )
        missing_command_ids = snapshot.get("missing_command_ids")
        if isinstance(missing_command_ids, list) and missing_command_ids:
            composer.line(
                f"{len(missing_command_ids)} command ID(s) from the durable action run were not retained by the live tracker."
            )

    def _append_brief_recent_command_evidence(
        self,
        composer: AnswerComposer,
        *,
        snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        snapshot = snapshot or self._command_tracker_snapshot()
        if not snapshot.get("available"):
            composer.line("- Commands: tracker unavailable.")
            return
        recent = snapshot.get("recent") if isinstance(snapshot.get("recent"), list) else []
        active = snapshot.get("active") if isinstance(snapshot.get("active"), list) else []
        stats = snapshot.get("stats") if isinstance(snapshot.get("stats"), Mapping) else {}
        successful = _as_int(stats.get("successful_commands"))
        failed = _as_int(stats.get("failed_commands"))
        partial = _as_int(stats.get("partial_commands"))
        if all(value is not None for value in (successful, failed, partial)):
            scope_label = "action-run commands" if snapshot.get("action_scoped") else "commands"
            composer.line(
                f"- {scope_label.capitalize()}: {successful} successful, {failed} failed, {partial} partial; "
                f"{len(active)} active."
            )
            return
        completed = sum(
            1
            for item in recent
            if str(item.get("outcome") or item.get("status") or "").strip().lower()
            in {"completed", "success", "succeeded"}
        )
        composer.line(f"- Commands: {completed}/{len(recent)} recent completed; {len(active)} active.")

    def _append_brief_unified_log_evidence(
        self,
        composer: AnswerComposer,
        *,
        message: str,
        action_context: Mapping[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        window_seconds = _parse_recent_log_window_seconds(message)
        window_started_ms, window_ended_ms = _action_context_time_window_ms(
            action_context
        )
        events, scanned = self._recent_warning_events(
            window_seconds=window_seconds,
            started_at_ms=window_started_ms,
            ended_at_ms=window_ended_ms,
        )
        if window_started_ms is not None and window_ended_ms is not None:
            composer.line("- Unified logs: scoped to the durable action-run time window.")
        if not scanned:
            composer.line("- Unified logs: unavailable.")
            return events, scanned
        if not events:
            composer.line("- Unified logs: no warning/error/critical entries in the checked window.")
            return events, scanned
        counts: dict[str, int] = {}
        for event in events:
            level = str(event.get("level") or "UNKNOWN").upper()
            counts[level] = counts.get(level, 0) + 1
        composer.line(
            "- Unified logs: "
            + ", ".join(f"{level}={count}" for level, count in sorted(counts.items()))
            + f"; {self._brief_backend_log_classification(events)}."
        )
        return events, scanned

    def _brief_backend_log_classification(self, events: Sequence[Mapping[str, Any]]) -> str:
        status_counts, _ = _http_status_route_counts([dict(event) for event in events])
        levels = {str(event.get("level") or "UNKNOWN").upper() for event in events}
        if status_counts and set(status_counts) <= {"401"} and levels <= {"WARNING"}:
            return "authentication/API noise, not direct flight-control evidence"
        if "ERROR" in levels or "CRITICAL" in levels:
            return "backend error evidence needs operator review"
        if any(status.startswith("5") for status in status_counts):
            return "server-side API failure evidence needs operator review"
        return "warning-level evidence needs source/route review"

    def _brief_flight_evidence_verdict(
        self,
        *,
        command_snapshot: Mapping[str, Any] | None,
        unified_events: Sequence[Mapping[str, Any]],
        unified_sources: Sequence[str],
        parsed_ulog_summaries: Sequence[tuple[int, int, Mapping[str, Any]]],
        parse_latest_ulog: bool,
        eligible_ulog_summaries: int,
        parsed_ulog_count: int,
        total_ulogs: int,
        ulog_inventory_available: int,
        latest_warning_error_total: int,
        warning_sample_available: int,
        scoped_count: int,
        unavailable: Sequence[str],
        cleanup_failures: Sequence[str],
    ) -> str:
        """Build one bounded verdict from typed evidence, never prompt wording."""

        issues: list[str] = []
        cautions: list[str] = []
        gaps: list[str] = []

        if command_snapshot is not None:
            if not command_snapshot.get("available"):
                gaps.append("command tracker unavailable")
            else:
                stats = (
                    command_snapshot.get("stats")
                    if isinstance(command_snapshot.get("stats"), Mapping)
                    else {}
                )
                failed = _as_int(stats.get("failed_commands"))
                partial = _as_int(stats.get("partial_commands"))
                active = (
                    command_snapshot.get("active")
                    if isinstance(command_snapshot.get("active"), list)
                    else []
                )
                if failed:
                    issues.append(f"{failed} command failure(s)")
                if partial:
                    issues.append(f"{partial} partial command(s)")
                if active:
                    cautions.append(f"{len(active)} command(s) still active")

        if unified_sources:
            levels = {
                str(event.get("level") or "UNKNOWN").upper()
                for event in unified_events
            }
            critical_count = sum(
                1
                for event in unified_events
                if str(event.get("level") or "").upper() in {"ERROR", "CRITICAL"}
            )
            if critical_count:
                issues.append(f"{critical_count} unified-log error/critical event(s)")
            elif unified_events and levels:
                cautions.append(
                    f"{len(unified_events)} unified-log warning event(s)"
                )
        elif command_snapshot is not None:
            gaps.append("unified logs unavailable")

        ulog_issues: list[str] = []
        correlation_verified = False
        for _hw_id, _log_id, summary in parsed_ulog_summaries:
            if not _ulog_summary_parsed_successfully(summary):
                continue
            ulog_issues.extend(_ulog_anomaly_labels(summary))
            correlation_verified = (
                correlation_verified or _format_ulog_correlation(summary).startswith("verified for ")
            )
        issues.extend(dict.fromkeys(ulog_issues))

        if parse_latest_ulog:
            if total_ulogs == 0:
                gaps.append(
                    "no onboard ULog listed by available inventories; remaining sources unknown"
                    if ulog_inventory_available < scoped_count
                    else "no onboard ULog listed in the complete checked scope"
                )
            elif eligible_ulog_summaries > parsed_ulog_count:
                gaps.append(
                    f"{eligible_ulog_summaries - parsed_ulog_count} newest ULog(s) not parsed"
                )
            elif parsed_ulog_count and not correlation_verified:
                gaps.append("newest parsed ULog not conclusively tied to this action")

        if warning_sample_available < scoped_count:
            gaps.append("some latest drone-log samples unavailable")
        if latest_warning_error_total:
            cautions.append(
                f"{latest_warning_error_total} latest drone-log warning/error line(s)"
            )
        if unavailable:
            gaps.append(f"{len(unavailable)} evidence check(s) unavailable")
        if cleanup_failures:
            issues.append(f"{len(cleanup_failures)} staged ULog cleanup failure(s)")

        issues = list(dict.fromkeys(issues))
        cautions = list(dict.fromkeys(cautions))
        gaps = list(dict.fromkeys(gaps))
        if issues:
            return "Verdict: review required - " + "; ".join(issues[:4]) + "."
        if cautions:
            suffix = f" Evidence gaps: {'; '.join(gaps[:3])}." if gaps else ""
            return (
                "Verdict: no command or parsed-ULog failure is shown, but "
                + "; ".join(cautions[:4])
                + " need review."
                + suffix
            )
        if gaps:
            return (
                "Verdict: no failure is shown in the available evidence, but verification "
                "is incomplete - "
                + "; ".join(gaps[:4])
                + "."
            )
        return "Verdict: no command, log, or parsed-ULog failure signal was found in the checked evidence."

    def _append_unified_log_evidence(
        self,
        composer: AnswerComposer,
        *,
        message: str,
        action_context: Mapping[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Append a compact unified-GCS log verdict to operation evidence."""

        window_seconds = _parse_recent_log_window_seconds(message)
        window_started_ms, window_ended_ms = _action_context_time_window_ms(
            action_context
        )
        events, scanned = self._recent_warning_events(
            window_seconds=window_seconds,
            started_at_ms=window_started_ms,
            ended_at_ms=window_ended_ms,
        )
        composer.blank().line("Unified GCS log evidence:")
        if window_started_ms is not None and window_ended_ms is not None:
            composer.line("- Scope: durable action-run time window.")
        if scanned:
            composer.line(f"- Sources scanned: {len(scanned)}.")
        else:
            composer.line("- No local unified GCS log source was available.")
            composer.line("- Warning/error count: unknown because no source was scanned.")
            return events, scanned
        if not events:
            composer.line("- No WARNING/ERROR/CRITICAL entries were found in the scanned window.")
            return events, scanned
        counts: dict[str, int] = {}
        for event in events:
            level = str(event.get("level") or "UNKNOWN").upper()
            counts[level] = counts.get(level, 0) + 1
        composer.line(
            "- Findings: "
            + ", ".join(f"{level}={count}" for level, count in sorted(counts.items()))
            + "."
        )
        for line in self._backend_log_operator_read_lines(events)[:3]:
            composer.line(line if line.startswith("-") else f"- {line}")
        return events, scanned

    def _fetch_drone_json(
        self,
        drone_ip: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float = DRONE_LOG_PROXY_TIMEOUT_SECONDS,
    ) -> tuple[dict[str, Any], str]:
        ip = str(drone_ip or "").strip()
        if not ip:
            return {}, "missing ip"
        injected_fetcher = getattr(self.deps, "fetch_drone_json_sync", None) if self.deps is not None else None
        if callable(injected_fetcher):
            try:
                payload = injected_fetcher(
                    ip,
                    path,
                    params=dict(params or {}),
                    timeout=timeout,
                )
            except Exception as exc:  # fixture/adaptor boundary
                return {}, _truncate_text(str(exc), 80) or "request failed"
            if not isinstance(payload, Mapping):
                return {}, "unexpected payload"
            return _copy_mapping(payload), ""
        try:
            from log_proxy import (
                DroneProxyResponseError,
                DroneProxyUnavailableError,
                fetch_drone_json_sync,
            )
        except Exception as exc:
            return {}, _truncate_text(str(exc), 80) or "proxy unavailable"

        try:
            payload = fetch_drone_json_sync(
                ip,
                path,
                params=dict(params or {}),
                timeout=timeout,
            )
        except DroneProxyResponseError as exc:
            return {}, f"HTTP {exc.status_code}: {_truncate_text(exc.detail, 80)}"
        except DroneProxyUnavailableError as exc:
            return {}, _truncate_text(str(exc), 80) or "request failed"
        except ValueError:
            return {}, "invalid json"
        if not isinstance(payload, Mapping):
            return {}, "unexpected payload"
        return _copy_mapping(payload), ""

    def mission_mode_comparison(self) -> MdsReadToolAnswer:
        composer = AnswerComposer()
        composer.line("QuickScout and Swarm Trajectory are different MDS mission-planning workflows, not two views of the same swarm geometry.")
        composer.blank()
        composer.table(
            ("Topic", "QuickScout", "Swarm Trajectory"),
            (
                ("Operator intent", "Rapid SAR, surveillance, or reconnaissance dispatch/search coverage", "Precise global trajectory processing for leader/follower swarm missions"),
                ("Runtime semantics", "PX4 Mission-style autonomous waypoint package", "MDS trajectory/offboard-style Mission Type 4 package"),
                ("Primary geometry", "Point, polygon, or corridor polyline", "Ordered leader waypoint sequence"),
                ("Multi-drone behavior", "Partitions search coverage where the template supports it", "Generates per-drone files from the leader/follower cluster graph and offsets"),
                ("Launch surface", "QuickScout review/launch and mission monitor", "Dashboard Mission Trigger after Swarm Trajectory validation/commit/transfer review"),
            ),
        )
        composer.blank()
        composer.line("Use QuickScout when the operator needs a fast reviewed SAR/search plan, such as point dispatch, last-known search, area sweep, or corridor search.")
        composer.line("Use Swarm Trajectory when the operator has a planned coordinated route and needs MDS to generate validated per-drone trajectory outputs for a leader/follower swarm.")
        composer.blank()
        composer.line(
            "References: "
            + _doc_link("Mission Planning Workspace", "mds.mission_planning_workspace")
            + ", "
            + _doc_link("QuickScout", "mds.quickscout")
            + ", "
            + _doc_link("Swarm Trajectory", "mds.swarm_trajectory")
            + "."
        )
        composer.bullets(_docs_source_lines("QuickScout Swarm Trajectory difference mission planning", tags="mission", limit=3))
        composer.line("No live swarm geometry, telemetry, or drone command was used for this conceptual comparison.")
        return self._answer(
            "mission_mode_comparison",
            composer.render(),
            ("mds.docs.mission_planning.read", "mds.docs.quickscout.read", "mds.docs.swarm_trajectory.read"),
        )

    def backend_log_summary(self, *, response_mode: str = "status", message: str = "") -> MdsReadToolAnswer:
        window_seconds = _parse_recent_log_window_seconds(message)
        events, scanned = self._recent_warning_events(window_seconds=window_seconds)
        window_label = _format_duration_seconds(window_seconds) if window_seconds else "recent scanned window"
        window_phrase = f"last {window_label}" if window_seconds else window_label
        normalized_mode = response_mode if response_mode in READ_RESPONSE_MODES else "status"
        if normalized_mode == "interpret":
            lines = self._backend_log_interpretation_lines(events, scanned, window_seconds=window_seconds)
            content = AnswerComposer(lines=lines).render()
        else:
            composer = AnswerComposer()
            composer.line(f"Backend warning/error summary from GCS logs ({window_phrase}):")
            if scanned:
                composer.bullets((f"Sources scanned: {', '.join(scanned[:4])}{' ...' if len(scanned) > 4 else ''}.",))
            else:
                composer.bullets(("No local GCS log files were found in the expected locations.",))
            if window_seconds:
                composer.bullets((f"Requested time window: last {_format_duration_seconds(window_seconds)}.",))

            if events:
                counts: dict[str, int] = {}
                for event in events:
                    level = str(event.get("level") or "UNKNOWN").upper()
                    counts[level] = counts.get(level, 0) + 1
                counts_text = ", ".join(f"{level}={count}" for level, count in sorted(counts.items()))
                composer.bullets((f"Warning/error entries found: {len(events)} ({counts_text}).",))
                composer.blank().line("Most recent entries:")
                rows: list[tuple[str, str, str, str]] = []
                for event in events[-5:]:
                    ts = _display_log_timestamp(event)
                    level = str(event.get("level") or "UNKNOWN").upper()
                    source = str(event.get("source") or "source n/a")
                    message = _truncate_text(_sanitize_log_text(str(event.get("message") or "")), 220)
                    rows.append((ts, level, source, message))
                composer.table(("Time", "Level", "Source", "Message"), rows)
                composer.blank().line("Operational interpretation:")
                composer.bullets(self._backend_log_operator_read_lines(events))
            elif scanned:
                composer.bullets((f"No WARNING/ERROR/CRITICAL entries were found in the {window_phrase}.",))
            else:
                composer.bullets(("Warning/error count is unknown because no local GCS log source was scanned.",))

            composer.blank().line("Open [Logs](/logs) for the full live stream and filters.")
            composer.line("Docs/API: " + _doc_link("logging guide", "mds.logging_system") + ", `GET /api/logs/sources`, `GET /api/logs/sessions`, `GET /api/logs/sessions/{session_id}`.")
            composer.line("No drone command was sent.")
            content = composer.render()
        return self._answer(
            "backend_log_summary",
            content,
            ("mds.logs.sessions.read", "mds.logs.sources.read"),
            response_mode=normalized_mode,
        )

    def _backend_log_interpretation_lines(
        self,
        events: list[dict[str, Any]],
        scanned: list[str],
        *,
        window_seconds: int | None = None,
    ) -> list[str]:
        window_label = _format_duration_seconds(window_seconds) if window_seconds else "recent scanned window"
        window_phrase = f"last {window_label}" if window_seconds else window_label
        lines = [f"Operational interpretation of backend warnings ({window_phrase}):"]
        if scanned:
            lines.append(f"- Evidence scanned: {', '.join(scanned[:4])}{' ...' if len(scanned) > 4 else ''}.")
        if window_seconds:
            lines.append(f"- Requested time window: last {_format_duration_seconds(window_seconds)}.")
        if not scanned:
            lines.append("- Short answer: backend warning/error status is unknown because no local GCS log source was available to scan.")
            lines.append("- Open the Logs page or restore the unified-log source before drawing a clean/healthy conclusion.")
        elif not events:
            lines.append("- Short answer: I do not see backend warning/error evidence in that window, so this log view does not point to a current GCS problem.")
            lines.append(f"- I do not see WARNING/ERROR/CRITICAL entries in the {window_phrase}.")
            lines.append("- Meaning: there is no backend-warning evidence here to explain; use the Logs page if the operator saw a different time window.")
        else:
            lines.extend(self._backend_log_direct_verdict_lines(events))
            lines.extend(self._backend_log_operator_read_lines(events))
            lines.append("- How to read this: treat the pattern and affected routes as the signal, not each repeated line independently. Repeated identical warnings usually mean one client is polling/failing the same protected endpoint.")
            lines.append("- Next operator check: open [Logs](/logs), filter the same time window, and verify whether the warning continues after refreshing/re-authenticating the dashboard client.")
        lines.append("Docs/API: " + _doc_link("logging guide", "mds.logging_system") + ", `GET /api/logs/sources`, `GET /api/logs/sessions`, `GET /api/logs/sessions/{session_id}`.")
        lines.append("No drone command was sent.")
        return lines

    def _backend_log_direct_verdict_lines(self, events: list[dict[str, Any]]) -> list[str]:
        status_counts, _ = _http_status_route_counts(events)
        levels = {str(event.get("level") or "UNKNOWN").upper() for event in events}
        if status_counts and set(status_counts) <= {"401"} and levels <= {"WARNING"}:
            return [
                "- Short answer: this does not look like a drone, MAVLink, PX4, GPS, RTK, battery, or flight-control problem from the scanned evidence.",
                "- It does show dashboard/API authentication noise: some client is reaching protected GCS endpoints without an accepted session or bearer token.",
                "- Fix priority: low for flight readiness, medium for product polish if it keeps repeating after a normal login/restart because it makes the logs noisy.",
            ]
        if "ERROR" in levels or "CRITICAL" in levels:
            return [
                "- Short answer: yes, there is at least one backend ERROR/CRITICAL signal in the scanned window; review the affected route before relying on that backend workflow.",
            ]
        return [
            "- Short answer: something is worth checking, but the scanned evidence is WARNING-level only and needs route/source context before calling it an operational fault.",
        ]

    def _backend_log_operator_read_lines(self, events: list[dict[str, Any]]) -> list[str]:
        if not events:
            return ["- Operator read: no actionable backend warning/error pattern was found in the scanned window."]

        status_counts, route_counts = _http_status_route_counts(events)
        levels = {str(event.get("level") or "UNKNOWN").upper() for event in events}
        lines: list[str] = []
        if status_counts:
            status_text = ", ".join(f"HTTP {status} x{count}" for status, count in _top_count_items(status_counts, limit=4))
            lines.append(f"- Main pattern: {status_text}.")
            if set(status_counts) <= {"401"}:
                lines.append("- Meaning: these are HTTP authorization warnings. A 401 on a GCS API route means a client reached a protected endpoint without accepted session/bearer auth.")
                lines.append("- Flight relevance: by itself this is not a MAVLink, PX4, GPS, RTK, battery, or flight-control warning. It is mainly a dashboard/API access signal.")
                lines.append("- Usual causes: expired dashboard login, a tab polling before login, a missing token in a custom client, or stale frontend requests during/after a service restart.")
            elif any(status.startswith("5") for status in status_counts):
                lines.append("- Meaning: at least one server-side HTTP 5xx was seen; that is more operationally important than auth-only noise and should be checked against the affected route.")
            else:
                lines.append("- Meaning: the warnings are HTTP/API-layer events. Check the affected routes before treating them as drone telemetry issues.")
            if route_counts:
                route_text = ", ".join(f"{route} x{count}" for route, count in _top_count_items(route_counts, limit=4))
                lines.append(f"- Affected route(s): {route_text}.")
        else:
            lines.append("- Main pattern: warning/error lines were present, but they were not recognized as GCS API HTTP status entries.")
            lines.append("- Meaning: inspect the message text and source file; this may be service, dependency, telemetry, or startup noise rather than dashboard auth polling.")

        if "ERROR" in levels or "CRITICAL" in levels:
            lines.append("- Severity: ERROR/CRITICAL is present, so this deserves operator review before relying on affected backend functions.")
        else:
            lines.append("- Severity: WARNING-only in this scan; worth noting, but not a flight readiness blocker unless it matches a failing operator workflow.")
        return lines

    def action_capability(self, message: str = "") -> MdsReadToolAnswer:
        del message  # Capability comes from the live registry/policy, not prompt aliases.
        try:
            from .policy import load_default_policy
            from .tool_executor import list_policy_available_guarded_tools

            policy = load_default_policy()
            tools = list_policy_available_guarded_tools(
                channel="agent",
                actor_role=self.actor_role,
                policy=policy,
            )
            composer = AnswerComposer()
            if tools:
                composer.line(
                    "Yes. Simurgh can draft these guarded GCS actions and submit them after operator confirmation when current policy allows."
                )
            else:
                composer.line(f"No guarded GCS actions are available in the current `{policy.mode}` runtime policy.")
            composer.blank().table(
                ("Execution setting", "Current value"),
                (
                    ("Runtime mode", policy.mode),
                    (
                        "Circuit breaker",
                        "ON - confirmed actions stop before dispatch"
                        if policy.action_circuit_breaker_enabled
                        else "OFF - confirmed registry actions may dispatch",
                    ),
                    (
                        "Operator confirmation",
                        "required" if policy.always_confirm_before_action else "tool/policy dependent",
                    ),
                ),
            )
            if tools:
                composer.blank().line("Available guarded actions:")
                composer.table(
                    ("Action", "Tool", "GCS route"),
                    (
                        (
                            tool.title,
                            f"`{tool.id}`",
                            f"`{tool.route_method} {tool.route_path}`",
                        )
                        for tool in tools
                    ),
                )
            composer.blank().line(
                "Flow: interpret the request -> build one ordered plan -> confirm -> re-check policy and the circuit breaker before every step -> monitor the GCS result."
            )
            composer.line(
                "Direct drone APIs and raw command submission remain unavailable; only registry-defined typed actions can use this path."
            )
            composer.line("This was a capability check; nothing was submitted.")
            content = composer.render()
        except Exception as exc:
            content = f"Simurgh guarded-action capability could not be loaded from the current registry and policy: {exc}"
        return self._answer(
            "action_capability",
            content,
            ("mds.simurgh.policy.read", "mds.simurgh.tools.read"),
            response_mode="capability",
            safety_notes=(
                "Guarded-action availability was derived from the current registry and runtime policy.",
                "No GCS route or drone command was executed.",
            ),
        )

    def _recent_warning_events(
        self,
        *,
        window_seconds: int | None = None,
        started_at_ms: int | None = None,
        ended_at_ms: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        events: list[dict[str, Any]] = []
        scanned: list[str] = []
        candidates = _log_file_candidates()
        if window_seconds is None:
            candidates = _latest_session_log_candidates(candidates)
        for candidate in candidates:
            if not candidate.is_file():
                continue
            label = _path_label(candidate)
            scanned.append(label)
            if candidate.suffix == ".jsonl":
                events.extend(_warning_events_from_jsonl(candidate, source=label))
            else:
                events.extend(_warning_events_from_text_log(candidate, source=label))
        events = [event for event in events if not _is_routine_auth_noise_event(event)]
        if started_at_ms is not None and ended_at_ms is not None:
            tolerance_seconds = 2.0
            started_at = started_at_ms / 1000.0 - tolerance_seconds
            ended_at = ended_at_ms / 1000.0 + tolerance_seconds
            events = [
                event
                for event in events
                if (
                    (event_timestamp := _event_timestamp_seconds(event)) is not None
                    and started_at <= event_timestamp <= ended_at
                )
            ]
        elif window_seconds:
            cutoff = time.time() - window_seconds
            events = [event for event in events if (_event_timestamp_seconds(event) or 0.0) >= cutoff]
        events.sort(key=lambda event: (_event_timestamp_seconds(event) or 0.0, str(event.get("ts") or "")))
        return events[-20:], scanned

    def _fleet_config(self) -> list[dict[str, Any]]:
        loader = getattr(self.deps, "load_config", None)
        if callable(loader):
            return [_copy_mapping(item) for item in (loader() or [])]
        try:
            from config import load_config

            return [_copy_mapping(item) for item in (load_config() or [])]
        except Exception:
            return []

    def _fleet_candidates_payload(self, *, include_inactive: bool = True, runtime_mode: str = "current") -> dict[str, Any]:
        getter = getattr(self.deps, "get_fleet_candidates_payload", None)
        if callable(getter):
            try:
                return _model_payload(getter(include_inactive=include_inactive, runtime_mode=runtime_mode))
            except TypeError:
                return _model_payload(getter())
            except Exception as exc:
                return {"candidates": [], "total_candidates": 0, "state_counts": {}, "error": str(exc)}

        list_candidates = getattr(self.deps, "list_fleet_candidates", None)
        if callable(list_candidates):
            try:
                candidates = list_candidates(include_inactive=include_inactive, runtime_mode=runtime_mode)
            except TypeError:
                candidates = list_candidates()
            except Exception as exc:
                return {"candidates": [], "total_candidates": 0, "state_counts": {}, "error": str(exc)}
            return _fleet_candidate_list_payload(candidates, runtime_mode_filter=runtime_mode)

        try:
            from config import load_config
            from fleet_candidates import get_fleet_candidate_registry
            from src.settings.runtime import resolve_runtime_mode

            runtime_filter = resolve_runtime_mode().mode if runtime_mode == "current" else runtime_mode
            if runtime_filter == "all":
                runtime_filter = None
            candidates = get_fleet_candidate_registry().list_candidates(
                load_config=load_config,
                include_inactive=include_inactive,
                runtime_mode=runtime_filter,
            )
            return _fleet_candidate_list_payload(candidates, runtime_mode_filter=runtime_filter or "all")
        except Exception as exc:
            return {"candidates": [], "total_candidates": 0, "state_counts": {}, "error": str(exc)}

    def _swarm_assignments(self) -> list[dict[str, Any]]:
        loader = getattr(self.deps, "load_swarm", None)
        if callable(loader):
            return [_copy_mapping(item) for item in (loader() or [])]
        try:
            from config import load_swarm

            return [_copy_mapping(item) for item in (load_swarm() or [])]
        except Exception:
            return []

    def _swarm_trajectory_status(self) -> dict[str, Any]:
        service = getattr(self.deps, "swarm_trajectory_service", None)
        getter = getattr(service, "get_processing_status_payload", None)
        if callable(getter):
            try:
                return _copy_mapping(getter() or {})
            except Exception as exc:
                return {"success": False, "error": str(exc)}
        try:
            from functions import swarm_trajectory_service

            return _copy_mapping(swarm_trajectory_service.get_processing_status_payload() or {})
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _swarm_trajectory_validation(self) -> dict[str, Any]:
        service = getattr(self.deps, "swarm_trajectory_service", None)
        getter = getattr(service, "get_validation_payload", None)
        if callable(getter):
            try:
                return _copy_mapping(getter() or {})
            except Exception as exc:
                return {"success": False, "error": str(exc), "ready": False}
        try:
            from functions import swarm_trajectory_service

            return _copy_mapping(swarm_trajectory_service.get_validation_payload() or {})
        except Exception as exc:
            return {"success": False, "error": str(exc), "ready": False}

    def _fleet_presence_counts(self) -> dict[str, int]:
        config = self._fleet_config()
        heartbeats = self._heartbeat_snapshot()
        telemetry = self._telemetry_snapshot()
        telemetry_success_times = self._telemetry_success_times()
        try:
            from params import Params
            from presence import build_presence_snapshot, resolve_presence_thresholds

            thresholds = resolve_presence_thresholds(Params)
        except Exception:
            build_presence_snapshot = None
            thresholds = None

        all_hw_ids = sorted(
            {
                *(_as_str(drone.get("hw_id")) for drone in config),
                *(_as_str(key) for key in heartbeats),
                *(_as_str(key) for key in telemetry),
            },
            key=_natural_key,
        )
        config_lookup = {_as_str(drone.get("hw_id")): drone for drone in config}
        live_count = 0
        now = time.time()
        for hw_id in all_hw_ids:
            heartbeat = _copy_mapping(heartbeats.get(hw_id) or heartbeats.get(_maybe_int_key(hw_id)))
            telemetry_row = _copy_mapping(telemetry.get(hw_id) or telemetry.get(_maybe_int_key(hw_id)))
            if build_presence_snapshot is not None:
                presence = build_presence_snapshot(
                    hw_id=hw_id,
                    heartbeat=heartbeat,
                    telemetry=telemetry_row,
                    telemetry_success_time=telemetry_success_times.get(hw_id) or telemetry_success_times.get(_maybe_int_key(hw_id)),
                    configured=hw_id in config_lookup,
                    now=now,
                    thresholds=thresholds,
                )
                live = bool(presence.get("fresh"))
            else:
                live = bool(heartbeat or telemetry_row.get("telemetry_available"))
            if live:
                live_count += 1
        return {"live": live_count, "total": len(all_hw_ids)}

    def _positions_by_hw_id(self) -> dict[int, dict[str, Any]]:
        loader = getattr(self.deps, "get_all_drone_positions", None)
        if callable(loader):
            positions = loader() or []
        else:
            try:
                from config import get_all_drone_positions

                positions = get_all_drone_positions() or []
            except Exception:
                positions = []
        result = {}
        for item in positions:
            hw_id = _as_int(_copy_mapping(item).get("hw_id"))
            if hw_id is not None:
                result[hw_id] = _copy_mapping(item)
        return result

    def _telemetry_snapshot(self) -> dict[Any, dict[str, Any]]:
        data = getattr(self.deps, "telemetry_data_all_drones", None)
        lock = getattr(self.deps, "data_lock", None)
        if data is None:
            try:
                from telemetry import data_lock as lock
                from telemetry import telemetry_data_all_drones as data
            except Exception:
                data = {}
                lock = None
        return _locked_mapping_snapshot(data, lock)

    def _telemetry_success_times(self) -> dict[Any, Any]:
        data = getattr(self.deps, "last_telemetry_time", None)
        lock = getattr(self.deps, "data_lock", None)
        if data is None:
            try:
                from telemetry import data_lock as lock
                from telemetry import last_telemetry_time as data
            except Exception:
                data = {}
                lock = None
        return _locked_scalar_snapshot(data, lock)

    def _heartbeat_snapshot(self) -> dict[Any, dict[str, Any]]:
        getter = getattr(self.deps, "get_all_heartbeats", None)
        if callable(getter):
            try:
                return {_as_str(key): _copy_mapping(value) for key, value in (getter() or {}).items()}
            except Exception:
                return {}
        try:
            from heartbeat import get_all_heartbeats

            return {_as_str(key): _copy_mapping(value) for key, value in (get_all_heartbeats() or {}).items()}
        except Exception:
            return {}

    def _origin_snapshot(self) -> dict[str, Any]:
        loader = getattr(self.deps, "load_origin", None)
        if callable(loader):
            try:
                return _copy_mapping(loader() or {})
            except Exception:
                return {}
        try:
            from origin import load_origin

            return _copy_mapping(load_origin() or {})
        except Exception:
            return {}

    def _command_tracker_snapshot(self) -> dict[str, Any]:
        getter = getattr(self.deps, "get_command_tracker", None)
        try:
            tracker = getter() if callable(getter) else None
            if tracker is None:
                from command_tracker import get_command_tracker

                tracker = get_command_tracker()
            get_recent = getattr(tracker, "get_recent", None)
            get_active = getattr(tracker, "get_active_commands", None)
            get_statistics = getattr(tracker, "get_statistics", None)
            if not all(callable(method) for method in (get_recent, get_active, get_statistics)):
                return {
                    "available": False,
                    "error": "command tracker does not expose the public snapshot APIs",
                }

            async def _read_public_snapshot() -> tuple[Any, Any, Any]:
                return (
                    await get_recent(limit=20),
                    await get_active(),
                    await get_statistics(),
                )

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                recent_payload, active_payload, stats_payload = asyncio.run(_read_public_snapshot())
            else:
                return {
                    "available": False,
                    "error": "public command snapshot must run outside the active event loop",
                }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

        if not isinstance(recent_payload, Sequence) or isinstance(recent_payload, (str, bytes, bytearray)):
            return {"available": False, "error": "unexpected recent-command payload"}
        if not isinstance(active_payload, Sequence) or isinstance(active_payload, (str, bytes, bytearray)):
            return {"available": False, "error": "unexpected active-command payload"}
        if not isinstance(stats_payload, Mapping):
            return {"available": False, "error": "unexpected command-statistics payload"}

        recent = [_command_record_public_summary(command) for command in recent_payload]
        active = [_command_record_public_summary(command) for command in active_payload]
        return {
            "available": True,
            "stats": dict(stats_payload),
            "active": active,
            "recent": recent,
        }

    def _quickscout_service(self) -> Any | None:
        service = getattr(self.deps, "quickscout_service", None)
        if service is not None:
            return service
        try:
            from sar.service import get_quickscout_service

            return get_quickscout_service()
        except Exception:
            return None

    def _quickscout_catalog(self, *, limit: int = 5) -> dict[str, Any]:
        getter = getattr(self.deps, "get_quickscout_mission_catalog", None)
        if callable(getter):
            try:
                return _model_payload(getter(limit=limit))
            except TypeError:
                return _model_payload(getter())
            except Exception as exc:
                return {"missions": [], "count": 0, "error": str(exc)}
        service = self._quickscout_service()
        if service is None:
            return {"missions": [], "count": 0}
        try:
            return _model_payload(service.list_operation_summaries(limit=limit))
        except Exception as exc:
            return {"missions": [], "count": 0, "error": str(exc)}

    def _quickscout_status(self, mission_id: str) -> dict[str, Any]:
        getter = getattr(self.deps, "get_quickscout_mission_status", None)
        if callable(getter):
            try:
                return _model_payload(getter(mission_id))
            except Exception:
                return {}
        service = self._quickscout_service()
        if service is None:
            return {}
        try:
            return _model_payload(service.get_status(mission_id))
        except Exception:
            return {}

    def _quickscout_workspace(self, mission_id: str) -> dict[str, Any]:
        getter = getattr(self.deps, "get_quickscout_mission_workspace", None)
        if callable(getter):
            try:
                return _model_payload(getter(mission_id))
            except Exception:
                return {}
        service = self._quickscout_service()
        if service is None:
            return {}
        try:
            return _model_payload(service.get_workspace(mission_id))
        except Exception:
            return {}

    def _show_info(self) -> dict[str, Any]:
        try:
            from show_management import build_show_info_payload

            skybrush_dir = getattr(self.deps, "skybrush_dir", None) or _default_show_dirs()["skybrush_dir"]
            payload = build_show_info_payload(skybrush_dir)
            return {"available": True, **_copy_mapping(payload)}
        except HTTPException as exc:
            return {"available": False, "detail": str(exc.detail)}
        except Exception as exc:
            return {"available": False, "detail": str(exc)}

    def _custom_show_info(self) -> dict[str, Any]:
        try:
            from show_management import build_custom_show_info_payload

            shapes_dir = getattr(self.deps, "shapes_dir", None) or _default_show_dirs()["shapes_dir"]
            payload = build_custom_show_info_payload(shapes_dir)
            return {"available": True, **_copy_mapping(payload)}
        except HTTPException as exc:
            return {"available": False, "detail": str(exc.detail)}
        except Exception as exc:
            return {"available": False, "detail": str(exc)}

    def _show_metrics_snapshot(self) -> dict[str, Any]:
        try:
            from functions.drone_show_metrics import DroneShowMetrics  # noqa: F401
            from show_management import build_metrics_snapshot_payload, load_saved_metrics_if_current

            dirs = _default_show_dirs()
            shapes_dir = getattr(self.deps, "shapes_dir", None) or dirs["shapes_dir"]
            processed_dir = getattr(self.deps, "processed_dir", None) or dirs["processed_dir"]
            loader = getattr(self.deps, "_load_saved_metrics_if_current", None)
            if not callable(loader):
                def loader():
                    return load_saved_metrics_if_current(
                        shapes_dir=shapes_dir,
                        processed_dir=processed_dir,
                        log_warning=lambda *_args, **_kwargs: None,
                    )
            return build_metrics_snapshot_payload(
                metrics_available=True,
                load_saved_metrics_if_current_func=loader,
            )
        except HTTPException as exc:
            return {"available": False, "detail": str(exc.detail)}
        except Exception as exc:
            return {"available": False, "detail": str(exc)}

    def _show_safety_report(self) -> dict[str, Any]:
        metrics = self._show_metrics_snapshot()
        if not metrics.get("available"):
            return {"available": False, "detail": metrics.get("detail") or "no current metrics snapshot"}
        payload = metrics.get("metrics") if isinstance(metrics.get("metrics"), Mapping) else {}
        safety = payload.get("safety_metrics") if isinstance(payload, Mapping) else None
        if not isinstance(safety, Mapping):
            return {"available": False, "detail": "current metrics snapshot does not include safety_metrics"}
        return {"safety_analysis": dict(safety), "recommendations": []}

    def _show_validation(self) -> dict[str, Any]:
        metrics = self._show_metrics_snapshot()
        if not metrics.get("available"):
            return {"available": False, "detail": metrics.get("detail") or "no current metrics snapshot"}
        all_metrics = metrics.get("metrics") if isinstance(metrics.get("metrics"), Mapping) else {}
        validation_status = "PASS"
        issues: list[str] = []

        safety = all_metrics.get("safety_metrics") if isinstance(all_metrics.get("safety_metrics"), Mapping) else {}
        if safety:
            safety_status = safety.get("safety_status")
            if safety_status != "SAFE":
                validation_status = "FAIL"
                issues.append(f"Safety issue: {safety_status}")
            collision_warnings = _as_int(safety.get("collision_warnings_count")) or 0
            if collision_warnings > 0:
                if validation_status != "FAIL":
                    validation_status = "WARNING"
                issues.append(f"{collision_warnings} collision warnings")

        performance = all_metrics.get("performance_metrics") if isinstance(all_metrics.get("performance_metrics"), Mapping) else {}
        max_velocity = _as_float(performance.get("max_velocity_ms"), 0.0) if performance else 0.0
        if max_velocity > 15:
            if validation_status == "PASS":
                validation_status = "WARNING"
            issues.append(f"High velocity: {max_velocity} m/s")

        formation = all_metrics.get("formation_metrics") if isinstance(all_metrics.get("formation_metrics"), Mapping) else {}
        return {
            "validation_status": validation_status,
            "issues": issues,
            "metrics_summary": {
                "safety_status": safety.get("safety_status", "Unknown") if safety else "Unknown",
                "max_velocity": max_velocity,
                "formation_quality": formation.get("formation_quality", "Unknown") if isinstance(formation, Mapping) else "Unknown",
            },
        }

    def _answer(
        self,
        intent: str,
        content: str,
        tool_ids: tuple[str, ...],
        *,
        response_mode: str = "status",
        safety_notes: tuple[str, ...] | None = None,
    ) -> MdsReadToolAnswer:
        normalized_mode = response_mode if response_mode in READ_RESPONSE_MODES else "status"
        operator_content = (
            _compact_operator_status(content)
            if normalized_mode == "status"
            else str(content or "").strip()
        )
        normalized_safety_notes = safety_notes or (
            "Answered by local read-only MDS/GCS context tools.",
            "No direct drone API, MAVSDK command, raw GCS command, or mission mutation was exposed.",
            f"Tool intent: {intent}.",
            f"Response mode: {normalized_mode}.",
        )
        evidence = ReadOnlyEvidenceBundle.from_answer(
            intent=intent,
            content=operator_content,
            tool_ids=tool_ids,
            response_mode=normalized_mode,
            safety_notes=normalized_safety_notes,
        )
        return MdsReadToolAnswer(
            intent=intent,
            content=operator_content,
            tool_ids=tool_ids,
            safety_notes=normalized_safety_notes,
            response_mode=normalized_mode,
            evidence=evidence,
        )


def build_runtime_settings_payload() -> dict[str, Any]:
    """Return the compact runtime settings surface for the dashboard."""

    from .assistant import load_default_assistant_config
    from .policy import load_default_policy
    from src.settings.runtime import resolve_runtime_mode

    config = load_default_assistant_config()
    policy = load_default_policy()
    runtime = resolve_runtime_mode()
    key_path = _resolve_openai_key_file(config.openai.api_key_file)
    credential_status = _openai_key_status(key_path)
    key_ready = bool(credential_status.get("ready"))
    key_error = str(credential_status.get("error") or "")

    warnings: list[str] = []
    if config.provider == "openai" and not key_ready:
        warnings.append("OpenAI provider is selected but the API key file is not ready.")
    if runtime.mode == "real" and not policy.action_circuit_breaker_enabled:
        warnings.append("GCS is in real mode and Simurgh action circuit breaker is off.")

    return {
        "agent_enabled": policy.agent_enabled,
        "mcp_enabled": policy.mcp_enabled,
        "gcs_mode": runtime.mode,
        "gcs_mode_source": runtime.source,
        "mode": policy.mode,
        "action_circuit_breaker_enabled": policy.action_circuit_breaker_enabled,
        "always_confirm_before_action": policy.always_confirm_before_action,
        "actions_blocked": policy.action_circuit_breaker_enabled,
        "action_policy_source": "circuit_breaker_and_mds_mode",
        "provider": config.provider,
        "model": config.openai.model if config.provider == "openai" else "mock-local",
        "openai_model": config.openai.model,
        "web_search_enabled": config.openai.web_search.enabled,
        "web_search_context_size": config.openai.web_search.search_context_size,
        "web_search_external_access": config.openai.web_search.external_web_access,
        "available_providers": ["mock", "openai"],
        "available_models": list(DEFAULT_OPENAI_CHAT_MODELS),
        "provider_ready": config.provider != "openai" or key_ready,
        "openai_key_file_configured": bool(key_path),
        "openai_key_file_ready": key_ready,
        "openai_key_file_error": key_error,
        "openai_key_fingerprint": credential_status.get("fingerprint", ""),
        "openai_key_updated_at": credential_status.get("updated_at", ""),
        "credentials": {"openai": credential_status},
        "updated_at": utc_now().isoformat(),
        "warnings": warnings,
    }



def build_provider_credentials_payload() -> dict[str, Any]:
    """Return redacted provider credential status for the dashboard."""

    from .assistant import load_default_assistant_config

    config = load_default_assistant_config()
    key_path = _resolve_openai_key_file(config.openai.api_key_file)
    return {"openai": _openai_key_status(key_path)}


def update_provider_credentials(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist provider credentials server-side without returning raw secrets."""

    from api_routes.management import _get_gcs_config_path, _persist_env_updates, _validate_gcs_env_updates
    from .assistant import load_default_assistant_config

    api_key = str(payload.get("openai_api_key") or "").strip()
    if not api_key:
        raise ValueError("OpenAI API key is required")
    if any(ch.isspace() for ch in api_key):
        raise ValueError("OpenAI API key must not contain whitespace")
    if not api_key.startswith("sk-") or len(api_key) < 20:
        raise ValueError("OpenAI API key does not look like an OpenAI API key")

    config = load_default_assistant_config()
    key_path = _resolve_openai_key_file(str(payload.get("openai_api_key_file") or config.openai.api_key_file or ""))
    _write_secret_file(key_path, api_key)

    updates = {"MDS_AGENT_OPENAI_API_KEY_FILE": str(key_path)}
    if bool(payload.get("set_provider_openai", False)):
        updates["MDS_AGENT_PROVIDER"] = "openai"
    if payload.get("openai_model"):
        updates["MDS_AGENT_OPENAI_MODEL"] = str(payload.get("openai_model")).strip()

    validated, warnings, apply_actions, restart_required = _validate_gcs_env_updates(updates)
    changed_keys = _persist_env_updates(_get_gcs_config_path(), validated)
    for key, value in validated.items():
        os.environ[key] = value

    return {
        "success": True,
        "changed_keys": changed_keys,
        "updated_keys": list(validated),
        "restart_required": False,
        "restart_would_have_been_required": bool(restart_required),
        "apply_actions": apply_actions,
        "warnings": warnings,
        "credentials": build_provider_credentials_payload(),
    }


def delete_provider_credentials(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Delete the configured OpenAI secret file when it is in the managed secret path."""

    from .assistant import load_default_assistant_config

    config = load_default_assistant_config()
    key_path = _resolve_openai_key_file(str((payload or {}).get("openai_api_key_file") or config.openai.api_key_file or ""))
    if key_path.exists() and _is_managed_secret_path(key_path):
        key_path.unlink()
    return {"success": True, "credentials": build_provider_credentials_payload()}


def _resolve_openai_key_file(raw_path: str | Path | None = None) -> Path:
    value = str(raw_path or "").strip()
    path = Path(value) if value else DEFAULT_OPENAI_API_KEY_FILE
    if not path.is_absolute():
        path = DEFAULT_OPENAI_API_KEY_FILE
    return path


def _openai_key_status(path: Path) -> dict[str, Any]:
    configured = bool(path)
    ready = False
    fingerprint = ""
    updated_at = ""
    error = ""
    try:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            ready = bool(value)
            fingerprint = _secret_fingerprint(value) if value else ""
            updated_at = utc_now().fromtimestamp(path.stat().st_mtime, tz=utc_now().tzinfo).isoformat()
    except OSError as exc:
        error = str(exc)
    return {
        "configured": configured,
        "ready": ready,
        "fingerprint": fingerprint,
        "updated_at": updated_at,
        "key_file_label": _path_label(path),
        "error": error,
    }


def _secret_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _write_secret_file(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _is_managed_secret_path(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(DEFAULT_OPENAI_API_KEY_FILE.parent)
    except AttributeError:
        try:
            path.resolve().relative_to(DEFAULT_OPENAI_API_KEY_FILE.parent)
            return True
        except ValueError:
            return False


def _doc_link(label: str, resource_id: str) -> str:
    return f"[{label}](/api/v1/simurgh/context/{resource_id}/markdown)"


def _docs_source_lines(query: str, *, tags: str = "", limit: int = 3) -> list[str]:
    try:
        from .docs_index import build_docs_search_payload

        payload = build_docs_search_payload(query, tags=tags, limit=limit)
    except Exception:
        return []
    results = payload.get("results") if isinstance(payload, Mapping) else []
    if not isinstance(results, list) or not results:
        return []
    lines = ["Sources:"]
    for item in results[:limit]:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or "MDS docs")
        heading = str(item.get("heading") or "section")
        canonical = str(item.get("canonical_url") or "")
        chunk_id = str(item.get("id") or "")
        route = str(item.get("route_hint") or "")
        target = canonical or route or str(item.get("path") or "")
        lines.append(f"- {title} / {heading}: {target} (chunk `{chunk_id}`)")
    return lines


def apply_runtime_settings(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist registry-approved Simurgh settings and hot-apply them to this process."""

    from api_routes.management import _get_gcs_config_path, _persist_env_updates, _validate_gcs_env_updates

    updates: dict[str, Any] = {}
    field_map = {
        "agent_enabled": "MDS_AGENT_ENABLED",
        "mcp_enabled": "MDS_MCP_ENABLED",
        "action_circuit_breaker_enabled": "MDS_AGENT_ACTION_CIRCUIT_BREAKER",
        "always_confirm_before_action": "MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION",
        "provider": "MDS_AGENT_PROVIDER",
        "openai_model": "MDS_AGENT_OPENAI_MODEL",
        "model": "MDS_AGENT_OPENAI_MODEL",
        "web_search_enabled": "MDS_AGENT_WEB_SEARCH_ENABLED",
    }
    for field, env_key in field_map.items():
        if field in payload and payload[field] is not None:
            updates[env_key] = payload[field]

    provider = str(updates.get("MDS_AGENT_PROVIDER", "")).strip().lower()
    if provider and provider not in {"mock", "openai"}:
        raise ValueError("provider must be mock or openai")

    if "MDS_AGENT_OPENAI_MODEL" in updates:
        model = str(updates["MDS_AGENT_OPENAI_MODEL"]).strip()
        if not model:
            raise ValueError("OpenAI model must not be empty")
        if model == "mock-local":
            updates.pop("MDS_AGENT_OPENAI_MODEL", None)
        else:
            updates["MDS_AGENT_OPENAI_MODEL"] = model

    dry_run = bool(payload.get("dry_run", False))
    validated, warnings, apply_actions, restart_required = _validate_gcs_env_updates(updates)
    changed_keys: list[str] = []
    if not dry_run and validated:
        changed_keys = _persist_env_updates(_get_gcs_config_path(), validated)
        for key, value in validated.items():
            os.environ[key] = value

    settings = build_runtime_settings_payload()
    settings.update(
        {
            "success": True,
            "dry_run": dry_run,
            "updated_keys": list(validated),
            "changed_keys": changed_keys,
            "restart_required": False,
            "restart_would_have_been_required": bool(restart_required),
            "apply_actions": apply_actions,
            "warnings": [*settings.get("warnings", []), *warnings],
        }
    )
    return settings


def _http_status_route_counts(events: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    status_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}
    for event in events:
        fields = _http_request_fields_from_log_event(event)
        if fields is None:
            continue
        _method, route, status = fields
        status_counts[status] = status_counts.get(status, 0) + 1
        route_counts[route] = route_counts.get(route, 0) + 1
    return status_counts, route_counts


def _is_routine_auth_noise_event(event: Mapping[str, Any]) -> bool:
    level = str(event.get("level") or "").upper()
    if level not in {"WARNING", "WARN"}:
        return False
    fields = _http_request_fields_from_log_event(event)
    if fields is None:
        return False
    method, route, status = fields
    return status in {"401", "403"} and is_routine_auth_noise_path(route, method=method)


def _http_request_fields_from_log_event(event: Mapping[str, Any]) -> tuple[str, str, str] | None:
    message = _sanitize_log_text(str(event.get("message") or ""))
    match = re.search(r"\bAPI\s+(GET|HEAD|OPTIONS|POST|PUT|PATCH|DELETE)\s+(\S+).*?\b([1-5][0-9]{2})\b", message)
    if not match:
        return None
    return match.group(1), match.group(2).rstrip(",.;"), match.group(3)


def _top_count_items(values: dict[str, int], *, limit: int) -> list[tuple[str, int]]:
    return sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit]


def _log_file_candidates() -> list[Path]:
    all_session_files: list[Path] = []
    for session_dir in (REPO_ROOT / "logs" / "sessions", REPO_ROOT / "gcs-server" / "logs" / "sessions"):
        if session_dir.is_dir():
            all_session_files.extend(session_dir.glob("*.jsonl"))
    session_files = sorted(all_session_files, key=lambda path: path.stat().st_mtime, reverse=True)[:4]
    newest_session_mtime = max((path.stat().st_mtime for path in session_files), default=None)
    fallback_files = [
        path
        for path in (
            Path("/var/log/mds-gcs-api.log"),
            Path("/var/log/mds-gcs.log"),
            Path("/var/log/mds/mds_gcs_init.log"),
        )
        if _include_fallback_log_file(path, newest_session_mtime)
    ]
    return [
        *session_files,
        *fallback_files,
    ]


def _latest_session_log_candidates(candidates: Sequence[Path]) -> list[Path]:
    session_files = [path for path in candidates if path.suffix == ".jsonl"]
    if not session_files:
        return list(candidates)
    try:
        newest = max(path.stat().st_mtime for path in session_files)
    except OSError:
        return session_files[:1]
    latest = []
    for path in session_files:
        try:
            if path.stat().st_mtime >= newest - LATEST_SESSION_GROUP_SECONDS:
                latest.append(path)
        except OSError:
            continue
    return latest or session_files[:1]


def _include_fallback_log_file(path: Path, newest_session_mtime: float | None) -> bool:
    try:
        fallback_mtime = path.stat().st_mtime
    except OSError:
        return False
    if newest_session_mtime is None:
        return True
    return fallback_mtime >= newest_session_mtime - FALLBACK_LOG_STALE_GRACE_SECONDS


def _warning_events_from_jsonl(path: Path, *, source: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in _tail_file_lines(path, max_lines=2000):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        level = str(payload.get("level") or "").upper()
        if level not in {"WARNING", "WARN", "ERROR", "CRITICAL"}:
            continue
        message = payload.get("msg") or payload.get("message") or ""
        timestamp = (
            payload.get("ts")
            or payload.get("timestamp")
            or payload.get("time")
            or payload.get("created_at")
            or _extract_log_timestamp(str(message))
        )
        events.append(
            {
                "ts": timestamp,
                "level": "WARNING" if level == "WARN" else level,
                "source": source,
                "message": message,
            }
        )
    return events


def _warning_events_from_text_log(path: Path, *, source: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in _tail_file_lines(path, max_lines=1200):
        clean = _sanitize_log_text(line)
        level = _log_level_from_text(clean)
        if level is None:
            continue
        events.append({"ts": _extract_log_timestamp(clean), "level": level, "source": source, "message": clean})
    return events


def _tail_file_lines(path: Path, *, max_lines: int, max_bytes: int = 262_144) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
            data = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return data.splitlines()[-max_lines:]


def _path_label(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _log_level_from_text(line: str) -> str | None:
    for level in ("CRITICAL", "ERROR", "WARNING", "WARN"):
        if re.search(rf"\b{level}\b", line, flags=re.IGNORECASE):
            return "WARNING" if level == "WARN" else level
    return None


def _extract_log_timestamp(line: str) -> str:
    match = re.search(r"(20\d{2}-\d{2}-\d{2}[T ][0-9:.]+(?:Z|[+-]\d{2}:?\d{2})?)", line)
    if match:
        return match.group(1)
    match = re.search(r"\b([0-2]?\d:[0-5]\d:[0-5]\d(?:\.\d{1,6})?)\b", line)
    if match:
        return match.group(1)
    return "time n/a"


def _parse_recent_log_window_seconds(message: str) -> int | None:
    normalized = _normalize_text(message)
    if not normalized:
        return None
    match = re.search(
        r"\b(?:last|past|previous|recent)\s+(\d{1,5})\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h|days?|d)\b",
        normalized,
    )
    if not match:
        if re.search(r"\b(?:last|past|previous|recent)\s+(?:an?\s+)?hour\b", normalized):
            return 3600
        if re.search(r"\b(?:last|past|previous|recent)\s+(?:a\s+)?day\b", normalized):
            return 86_400
        return None
    amount = max(1, int(match.group(1)))
    unit = match.group(2)
    if unit.startswith(("s", "sec")):
        seconds = amount
    elif unit.startswith(("m", "min")):
        seconds = amount * 60
    elif unit.startswith(("h", "hr")):
        seconds = amount * 3600
    else:
        seconds = amount * 86_400
    return min(seconds, 7 * 86_400)


def _drone_api_port() -> int:
    raw = os.getenv("MDS_DRONE_API_PORT", os.getenv("MDS_DEFAULT_DRONE_API_PORT", "7070"))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 7070


def _log_session_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    sessions = payload.get("sessions") if isinstance(payload, Mapping) else None
    items = [_copy_mapping(item) for item in (sessions or []) if isinstance(item, Mapping)]
    items.sort(key=lambda item: _as_float(item.get("modified"), 0.0), reverse=True)
    return items


def _ulog_file_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    files = payload.get("files") if isinstance(payload, Mapping) else None
    items = [_copy_mapping(item) for item in (files or []) if isinstance(item, Mapping)]
    items.sort(key=lambda item: str(item.get("date_utc") or ""), reverse=True)
    return items


def _latest_ulog_label(files: Sequence[Mapping[str, Any]]) -> str:
    if not files:
        return "none listed"
    latest = files[0]
    log_id = latest.get("id")
    date = str(latest.get("date_utc") or "date n/a").strip() or "date n/a"
    size = _as_float(latest.get("size_bytes"), 0.0)
    size_label = _format_bytes(size) if size > 0 else "size n/a"
    return f"id {log_id}; {date}; {size_label}"


def _ulog_log_id(file_item: Mapping[str, Any]) -> int | None:
    return _as_int(file_item.get("id"))


def _looks_like_ulog_parse_summary_request(normalized: str) -> bool:
    if not _looks_like_drone_log_summary_question(normalized):
        return False
    return _has_domain_signal(
        normalized,
        (
            "analyze",
            "analysis",
            "correct",
            "did it",
            "duration",
            "flight time",
            "happen",
            "happened",
            "parse",
            "preflight",
            "ready",
            "report",
            "summary",
            "test",
            "ulog",
            "ulogs",
            ".ulg",
        ),
    )


def _covered_count_label(count: int, available_sources: int, scoped_sources: int) -> str:
    if scoped_sources <= 0 or available_sources <= 0:
        return "unknown"
    if available_sources >= scoped_sources:
        return str(count)
    if count == 0:
        return f"0 in available sources ({available_sources}/{scoped_sources} sources available; total unknown)"
    return f"at least {count} ({available_sources}/{scoped_sources} sources available; total unknown)"


def _known_metric(values: Mapping[str, Any], key: str) -> str:
    value = values.get(key)
    return str(value) if value not in (None, "") else "unknown"


def _timestamp_epoch_ms(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or float(value) <= 0:
            return None
        numeric = float(value)
        return int(numeric if numeric >= 100_000_000_000 else numeric * 1000.0)
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000.0)
    return _timestamp_epoch_ms(numeric)


def _iso_from_epoch_ms(value: int | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _first_timestamp_ms(values: Mapping[str, Any], keys: Sequence[str]) -> int | None:
    for key in keys:
        parsed = _timestamp_epoch_ms(values.get(key))
        if parsed is not None:
            return parsed
    return None


_SIMURGH_COMMAND_LABEL_PATTERN = re.compile(
    r"simurgh:(?P<action_reference>act-[A-Za-z0-9_-]{1,128}):"
    r"(?:step:(?P<step_index>[1-9][0-9]{0,5})|(?P<action_name>[A-Za-z][A-Za-z0-9_-]{0,63}))"
)


def _action_context_command_ids(
    action_context: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if not isinstance(action_context, Mapping):
        return ()
    result = (
        action_context.get("action_run_result")
        if isinstance(action_context.get("action_run_result"), Mapping)
        else {}
    )
    candidates: list[Any] = [action_context.get("command_id")]
    for container in (action_context, result):
        action_response = (
            container.get("action_response")
            if isinstance(container.get("action_response"), Mapping)
            else {}
        )
        monitor_result = (
            container.get("monitor_result")
            if isinstance(container.get("monitor_result"), Mapping)
            else {}
        )
        command_status = (
            monitor_result.get("command_status")
            if isinstance(monitor_result.get("command_status"), Mapping)
            else {}
        )
        candidates.extend(
            (
                action_response.get("command_id"),
                command_status.get("command_id"),
            )
        )
        post_actions = container.get("post_action_results")
        if isinstance(post_actions, Sequence) and not isinstance(
            post_actions, (str, bytes, bytearray)
        ):
            candidates.extend(
                item.get("command_id")
                for item in post_actions
                if isinstance(item, Mapping)
            )
    return tuple(
        dict.fromkeys(
            str(item).strip()
            for item in candidates
            if str(item or "").strip()
        )
    )


def _action_context_reference(action_context: Mapping[str, Any] | None) -> str:
    if not isinstance(action_context, Mapping):
        return ""
    return str(
        action_context.get("draft_id")
        or action_context.get("action_reference")
        or ""
    ).strip()


def _action_context_command_records(
    action_context: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(action_context, Mapping):
        return ()
    result = (
        action_context.get("action_run_result")
        if isinstance(action_context.get("action_run_result"), Mapping)
        else action_context
    )
    candidates: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    primary_monitor = (
        result.get("monitor_result")
        if isinstance(result.get("monitor_result"), Mapping)
        else {}
    )
    if primary_monitor:
        candidates.append((primary_monitor, result))
    post_actions = result.get("post_action_results")
    if isinstance(post_actions, Sequence) and not isinstance(
        post_actions, (str, bytes, bytearray)
    ):
        for item in post_actions:
            if not isinstance(item, Mapping):
                continue
            monitor = (
                item.get("monitor_result")
                if isinstance(item.get("monitor_result"), Mapping)
                else {}
            )
            if monitor:
                candidates.append((monitor, item))

    records: list[dict[str, Any]] = []
    for monitor, container in candidates:
        command_status = (
            monitor.get("command_status")
            if isinstance(monitor.get("command_status"), Mapping)
            else {}
        )
        if not command_status:
            continue
        record = dict(command_status)
        record.setdefault("command_id", container.get("command_id"))
        if not record.get("target_drones"):
            record["target_drones"] = list(
                container.get("resolved_target_drone_ids")
                or action_context.get("target_drone_ids")
                or ()
            )
        record["_durable_action_run"] = True
        records.append(record)
    return tuple(records)


def _action_context_time_window_ms(
    action_context: Mapping[str, Any] | None,
) -> tuple[int | None, int | None]:
    if not isinstance(action_context, Mapping):
        return None, None
    started_ms = _timestamp_epoch_ms(
        action_context.get("action_run_created_at")
        or action_context.get("created_at")
    )
    ended_ms = _timestamp_epoch_ms(
        action_context.get("action_run_completed_at")
        or action_context.get("completed_at")
        or action_context.get("action_run_updated_at")
        or action_context.get("updated_at")
    )
    if started_ms is None or ended_ms is None or ended_ms < started_ms:
        return None, None
    return started_ms, ended_ms


def _scope_command_snapshot_to_action(
    snapshot: Mapping[str, Any],
    action_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    scoped = dict(snapshot or {})
    expected_ids = _action_context_command_ids(action_context)
    if not expected_ids:
        return scoped
    scoped["action_scoped"] = True
    scoped["expected_command_ids"] = list(expected_ids)
    if scoped.get("available") is not True:
        scoped["missing_command_ids"] = list(expected_ids)
        return scoped

    expected = set(expected_ids)
    durable_records = {
        str(item.get("command_id") or "").strip(): dict(item)
        for item in _action_context_command_records(action_context)
        if str(item.get("command_id") or "").strip() in expected
    }
    active = [
        dict(item)
        for item in scoped.get("active") or ()
        if isinstance(item, Mapping)
        and str(item.get("command_id") or "").strip() in expected
    ]
    recent_by_id = dict(durable_records)
    for item in scoped.get("recent") or ():
        if not isinstance(item, Mapping):
            continue
        command_id = str(item.get("command_id") or "").strip()
        if command_id in expected:
            recent_by_id[command_id] = dict(item)
    recent = [
        recent_by_id[command_id]
        for command_id in expected_ids
        if command_id in recent_by_id
    ]
    retained_ids = {
        str(item.get("command_id") or "").strip()
        for item in (*active, *recent)
        if str(item.get("command_id") or "").strip()
    }
    terminal_rows = {
        str(item.get("command_id") or "").strip(): item
        for item in recent
        if str(item.get("command_id") or "").strip()
    }
    successful = 0
    failed = 0
    partial = 0
    for item in terminal_rows.values():
        outcome = str(item.get("outcome") or item.get("status") or "").strip().casefold()
        if outcome in {"completed", "success", "succeeded"}:
            successful += 1
        elif outcome in {"partial", "partially_completed"}:
            partial += 1
        elif outcome in {
            "failed",
            "error",
            "rejected",
            "timed_out",
            "timeout",
            "cancelled",
            "canceled",
        }:
            failed += 1
    scoped.update(
        {
            "active": active,
            "recent": recent,
            "stats": {
                "total_commands": len(expected_ids),
                "successful_commands": successful,
                "failed_commands": failed,
                "partial_commands": partial,
            },
            "missing_command_ids": [
                command_id for command_id in expected_ids if command_id not in retained_ids
            ],
            "durable_command_ids": [
                command_id for command_id in expected_ids if command_id in durable_records
            ],
        }
    )
    return scoped


def _command_action_reference(command: Mapping[str, Any]) -> str:
    label = str(command.get("operator_label") or "").strip()
    if not label or len(label) > 256:
        return ""
    match = _SIMURGH_COMMAND_LABEL_PATTERN.fullmatch(label)
    return match.group("action_reference") if match else ""


def _build_ulog_action_correlation(
    *,
    hw_id: int,
    log_entry: Mapping[str, Any],
    summary: Mapping[str, Any],
    command_snapshot: Mapping[str, Any] | None,
    expected_action_reference: str = "",
    expected_command_ids: Sequence[str] = (),
) -> UlogActionCorrelation:
    """Associate a ULog only when explicit GCS target/time/action/command evidence agrees."""

    source = summary.get("source") if isinstance(summary.get("source"), Mapping) else {}
    log_id = _ulog_log_id(log_entry)
    started_raw = log_entry.get("date_utc") or source.get("date_utc")
    started_ms = _timestamp_epoch_ms(started_raw)
    duration_sec = _finite_or_none(summary.get("duration_sec"))
    ended_ms = (
        started_ms + int(duration_sec * 1000.0)
        if started_ms is not None and duration_sec is not None and duration_sec >= 0.0
        else None
    )
    evidence = UlogCorrelationEvidence(
        target_drone_id=str(hw_id),
        ulog_log_id=log_id,
        ulog_started_at=_iso_from_epoch_ms(started_ms),
        ulog_ended_at=_iso_from_epoch_ms(ended_ms),
    )
    limitations: list[str] = []
    if started_ms is None or ended_ms is None:
        limitations.append("ULog recording start/end metadata is incomplete.")
    if not command_snapshot or command_snapshot.get("available") is not True:
        limitations.append("A synchronized GCS command snapshot was unavailable.")
    if limitations:
        return UlogActionCorrelation(
            status="unverified",
            verified=False,
            method="source_metadata_only" if started_ms is not None else "none",
            evidence=evidence,
            limitations=limitations,
        )

    recent = command_snapshot.get("recent")
    commands = recent if isinstance(recent, list) else []
    expected_ids = {
        str(item).strip()
        for item in expected_command_ids
        if str(item).strip()
    }
    if expected_ids:
        commands = [
            command
            for command in commands
            if str(command.get("command_id") or "").strip() in expected_ids
        ]
    tolerance_ms = int(ULOG_COMMAND_CORRELATION_TOLERANCE_SECONDS * 1000.0)
    overlapping: list[dict[str, Any]] = []
    for raw_command in commands:
        command = _copy_mapping(raw_command)
        targets = {str(item).strip() for item in command.get("target_drones") or () if str(item).strip()}
        if str(hw_id) not in targets:
            continue
        command_start = _first_timestamp_ms(
            command,
            ("execution_started_at", "submitted_at", "created_at"),
        )
        command_end = _first_timestamp_ms(
            command,
            ("completed_at", "updated_at", "execution_started_at", "submitted_at", "created_at"),
        )
        if command_start is None or command_end is None:
            continue
        if command_end < started_ms - tolerance_ms or command_start > ended_ms + tolerance_ms:
            continue
        command["_correlation_start_ms"] = command_start
        command["_correlation_end_ms"] = command_end
        command["_action_reference"] = _command_action_reference(command)
        overlapping.append(command)

    if not overlapping:
        return UlogActionCorrelation(
            status="unverified",
            verified=False,
            method="source_metadata_only",
            evidence=evidence,
            limitations=(
                "No retained GCS command record matched both the target drone and ULog recording window.",
            ),
        )

    action_references = {
        str(item.get("_action_reference") or "").strip()
        for item in overlapping
        if str(item.get("_action_reference") or "").strip()
    }
    unmatched_action_commands = [item for item in overlapping if not item.get("_action_reference")]
    if len(action_references) != 1 or unmatched_action_commands:
        command_ids = [str(item.get("command_id") or "").strip() for item in overlapping]
        command_ids = [item for item in command_ids if item]
        matched_dimensions = ["target", "time"]
        if len(command_ids) == len(overlapping):
            matched_dimensions.append("command_id")
        evidence = UlogCorrelationEvidence(
            **{
                **_model_payload(evidence),
                "command_ids": command_ids,
                "command_window_started_at": _iso_from_epoch_ms(
                    min(int(item["_correlation_start_ms"]) for item in overlapping)
                ),
                "command_window_ended_at": _iso_from_epoch_ms(
                    max(int(item["_correlation_end_ms"]) for item in overlapping)
                ),
                "matched_dimensions": matched_dimensions,
            }
        )
        if len(action_references) > 1:
            reason = "Multiple guarded-action references overlap this recording."
        elif unmatched_action_commands:
            reason = (
                "At least one matching command lacks a valid guarded-action label, so the full "
                "overlapping sequence cannot be correlated."
            )
        else:
            reason = "Matching commands do not carry a guarded-action reference."
        return UlogActionCorrelation(
            status="ambiguous" if len(action_references) > 1 else "candidate",
            verified=False,
            method="gcs_target_time_command_overlap",
            evidence=evidence,
            limitations=(reason,),
        )

    action_reference = next(iter(action_references))
    if expected_action_reference and action_reference != expected_action_reference:
        return UlogActionCorrelation(
            status="unverified",
            verified=False,
            method="gcs_target_time_action_command_overlap",
            evidence=evidence,
            limitations=(
                "The overlapping command sequence belongs to a different guarded action run.",
            ),
        )
    action_commands = [item for item in overlapping if item.get("_action_reference") == action_reference]
    raw_command_ids = [str(item.get("command_id") or "").strip() for item in action_commands]
    command_ids = [item for item in raw_command_ids if item]
    if len(command_ids) != len(action_commands):
        evidence = UlogCorrelationEvidence(
            **{
                **_model_payload(evidence),
                "action_reference": action_reference,
                "command_ids": command_ids,
                "command_window_started_at": _iso_from_epoch_ms(
                    min(int(item["_correlation_start_ms"]) for item in action_commands)
                ),
                "command_window_ended_at": _iso_from_epoch_ms(
                    max(int(item["_correlation_end_ms"]) for item in action_commands)
                ),
                "matched_dimensions": ["target", "time", "action_reference"],
            }
        )
        return UlogActionCorrelation(
            status="candidate",
            verified=False,
            method="gcs_target_time_action_command_overlap",
            evidence=evidence,
            limitations=(
                "At least one matching sequence command does not expose a command ID, so the full "
                "sequence cannot be correlated.",
            ),
        )

    if expected_ids and set(command_ids) != expected_ids:
        evidence = UlogCorrelationEvidence(
            **{
                **_model_payload(evidence),
                "action_reference": action_reference,
                "command_ids": command_ids,
                "command_window_started_at": _iso_from_epoch_ms(
                    min(int(item["_correlation_start_ms"]) for item in action_commands)
                ),
                "command_window_ended_at": _iso_from_epoch_ms(
                    max(int(item["_correlation_end_ms"]) for item in action_commands)
                ),
                "matched_dimensions": ["target", "time", "action_reference", "command_id"],
            }
        )
        return UlogActionCorrelation(
            status="candidate",
            verified=False,
            method="gcs_target_time_action_command_overlap",
            evidence=evidence,
            limitations=(
                "The ULog window did not cover every command ID in the requested durable action run.",
            ),
        )

    evidence = UlogCorrelationEvidence(
        **{
            **_model_payload(evidence),
            "action_reference": action_reference,
            "command_ids": command_ids,
            "command_window_started_at": _iso_from_epoch_ms(
                min(int(item["_correlation_start_ms"]) for item in action_commands)
            ),
            "command_window_ended_at": _iso_from_epoch_ms(
                max(int(item["_correlation_end_ms"]) for item in action_commands)
            ),
            "matched_dimensions": ["target", "time", "action_reference", "command_id"],
        }
    )
    return UlogActionCorrelation(
        status="verified",
        verified=True,
        method="gcs_target_time_action_command_overlap",
        evidence=evidence,
        limitations=(
            "This verifies evidence association, not trajectory accuracy or mission success by itself.",
        ),
    )


def _format_ulog_summary_row(hw_id: int, log_id: int, summary: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    parser = summary.get("parser") if isinstance(summary.get("parser"), Mapping) else {}
    if not _ulog_summary_parsed_successfully(summary):
        error = str(parser.get("error") or parser.get("status") or "parser unavailable")
        return (f"Drone {hw_id}", str(log_id), "not parsed", "-", "-", _truncate_text(error, 80))

    duration = _as_float(summary.get("duration_sec"), -1.0)
    duration_label = f"{duration:.1f}s" if duration >= 0 else "unknown"
    local_position = summary.get("local_position") if isinstance(summary.get("local_position"), Mapping) else {}
    movement_label = _format_ulog_local_movement(local_position)
    battery = summary.get("battery") if isinstance(summary.get("battery"), Mapping) else {}
    battery_label = _format_ulog_battery(battery)
    commands = summary.get("commands") if isinstance(summary.get("commands"), Mapping) else {}
    command_label = _format_ulog_command_summary(commands)
    return (f"Drone {hw_id}", str(log_id), duration_label, movement_label, battery_label, command_label)


def _format_ulog_brief_lines(hw_id: int, log_id: int, summary: Mapping[str, Any]) -> tuple[str, ...]:
    """Render a compact operator summary from derived ULog metrics only."""

    parser = summary.get("parser") if isinstance(summary.get("parser"), Mapping) else {}
    if not _ulog_summary_parsed_successfully(summary):
        error = str(parser.get("error") or parser.get("status") or "parser unavailable")
        return (f"Drone {hw_id} ULog {log_id}: analysis unavailable ({_truncate_text(error, 100)}).",)

    duration = _as_float(summary.get("duration_sec"), -1.0)
    duration_label = f"{duration:.1f}s" if duration >= 0 else "duration unknown"
    local_position = summary.get("local_position") if isinstance(summary.get("local_position"), Mapping) else {}
    battery = summary.get("battery") if isinstance(summary.get("battery"), Mapping) else {}
    commands = summary.get("commands") if isinstance(summary.get("commands"), Mapping) else {}
    dropouts = summary.get("dropouts") if isinstance(summary.get("dropouts"), Mapping) else {}
    vehicle_status = (
        summary.get("vehicle_status") if isinstance(summary.get("vehicle_status"), Mapping) else {}
    )

    return (
        f"Drone {hw_id} ULog {log_id}: {duration_label}; "
        f"{_format_ulog_local_movement(local_position)}; "
        f"{_format_ulog_battery(battery)}; "
        f"{_format_ulog_command_summary(commands)}.",
        "Safety: "
        f"{_format_ulog_dropouts(dropouts)}; "
        f"{_format_ulog_failsafe(vehicle_status)}; "
        f"{_format_ulog_final_displacement(local_position)}; "
        f"correlation {_format_ulog_correlation(summary)}; "
        f"{_format_ulog_staged_cleanup(summary)}.",
    )


def _ulog_anomaly_labels(summary: Mapping[str, Any]) -> list[str]:
    """Return bounded typed anomaly labels from a successfully parsed ULog."""

    labels: list[str] = []
    dropouts = summary.get("dropouts") if isinstance(summary.get("dropouts"), Mapping) else {}
    dropout_count = _as_int(dropouts.get("count"))
    if dropout_count and dropout_count > 0:
        labels.append(f"{dropout_count} ULog dropout(s)")

    vehicle_status = (
        summary.get("vehicle_status") if isinstance(summary.get("vehicle_status"), Mapping) else {}
    )
    failsafe = (
        vehicle_status.get("failsafe")
        if isinstance(vehicle_status.get("failsafe"), Mapping)
        else {}
    )
    failsafe_samples = _active_boolean_sample_count(failsafe)
    if failsafe_samples:
        labels.append(f"{failsafe_samples} ULog failsafe-active sample(s)")

    land_detected = (
        summary.get("land_detected") if isinstance(summary.get("land_detected"), Mapping) else {}
    )
    freefall = (
        land_detected.get("freefall")
        if isinstance(land_detected.get("freefall"), Mapping)
        else {}
    )
    freefall_samples = _active_boolean_sample_count(freefall)
    if freefall_samples:
        labels.append(f"{freefall_samples} ULog freefall sample(s)")

    commands = summary.get("commands") if isinstance(summary.get("commands"), Mapping) else {}
    acknowledgements = (
        commands.get("vehicle_command_ack")
        if isinstance(commands.get("vehicle_command_ack"), Mapping)
        else {}
    )
    results = (
        acknowledgements.get("result_counts")
        if isinstance(acknowledgements.get("result_counts"), Mapping)
        else {}
    )
    nonaccepted_samples = 0
    for raw_result, raw_count in results.items():
        result = _as_int(raw_result)
        count = _as_int(raw_count)
        if (
            result is not None
            and result not in MAV_RESULT_NON_FAILURE_CODES
            and count
            and count > 0
        ):
            nonaccepted_samples += count
    if nonaccepted_samples:
        labels.append(
            f"{nonaccepted_samples} non-accepted command acknowledgement sample(s)"
        )
    return labels


def _active_boolean_sample_count(counts: Mapping[str, Any]) -> int:
    """Count samples in an explicitly active boolean state."""

    total = 0
    for raw_state, raw_count in counts.items():
        state = str(raw_state or "").strip().casefold()
        numeric_state = _as_int(raw_state)
        active = state in {"true", "yes", "on", "active"} or numeric_state == 1
        count = _as_int(raw_count)
        if active and count and count > 0:
            total += count
    return total


def _format_ulog_safety_evidence_line(hw_id: int, log_id: int, summary: Mapping[str, Any]) -> str:
    """Render bounded safety metrics without raw ULog samples or message text."""

    if not _ulog_summary_parsed_successfully(summary):
        return ""

    dropouts = summary.get("dropouts") if isinstance(summary.get("dropouts"), Mapping) else {}
    logged_messages = (
        summary.get("logged_messages") if isinstance(summary.get("logged_messages"), Mapping) else {}
    )
    system = summary.get("system") if isinstance(summary.get("system"), Mapping) else {}
    vehicle_status = (
        summary.get("vehicle_status") if isinstance(summary.get("vehicle_status"), Mapping) else {}
    )
    land_detected = (
        summary.get("land_detected") if isinstance(summary.get("land_detected"), Mapping) else {}
    )
    local_position = (
        summary.get("local_position") if isinstance(summary.get("local_position"), Mapping) else {}
    )
    commands = summary.get("commands") if isinstance(summary.get("commands"), Mapping) else {}

    evidence = (
        _format_ulog_dropouts(dropouts),
        _format_ulog_logged_message_levels(logged_messages),
        _format_ulog_system(system),
        _format_ulog_failsafe(vehicle_status),
        _format_ulog_land_detection(land_detected),
        _format_ulog_final_displacement(local_position),
        _format_ulog_command_summary(commands),
        "correlation " + _format_ulog_correlation(summary),
        _format_ulog_staged_cleanup(summary),
    )
    return f"Drone {hw_id}, log {log_id}: " + "; ".join(evidence) + "."


def _ulog_summary_parsed_successfully(summary: Mapping[str, Any]) -> bool:
    """Return true only for the typed successful-parser state."""

    parser = summary.get("parser") if isinstance(summary.get("parser"), Mapping) else {}
    return summary.get("parsed") is True and str(parser.get("status") or "").strip().lower() == "ok"


def _format_ulog_correlation(summary: Mapping[str, Any]) -> str:
    """Report action correlation only when local evidence explicitly verifies it."""

    raw = summary.get("correlation") if isinstance(summary.get("correlation"), Mapping) else {}
    try:
        correlation = UlogActionCorrelation.model_validate(raw)
    except (AttributeError, TypeError, ValueError):
        try:
            correlation = UlogActionCorrelation.parse_obj(raw)
        except (TypeError, ValueError):
            correlation = UlogActionCorrelation()
    evidence = correlation.evidence
    required_dimensions = {"target", "time", "action_reference", "command_id"}
    if (
        correlation.status == "verified"
        and correlation.verified is True
        and correlation.method == "gcs_target_time_action_command_overlap"
        and required_dimensions.issubset(set(evidence.matched_dimensions))
        and evidence.target_drone_id
        and evidence.ulog_started_at
        and evidence.ulog_ended_at
        and evidence.action_reference
        and evidence.command_ids
    ):
        return (
            f"verified for {evidence.action_reference} by target/time overlap and "
            f"{len(evidence.command_ids)} GCS command id(s); association only, not mission-success proof"
        )
    if correlation.status == "ambiguous":
        return "ambiguous; more than one guarded action overlaps the ULog recording"
    if correlation.status == "candidate":
        return "candidate only; target/time command evidence lacks one guarded-action reference"
    return "unverified; newest available ULog may belong to another flight"


def _format_ulog_staged_cleanup(summary: Mapping[str, Any]) -> str:
    status = _ulog_staged_cleanup_status(summary)
    if status is True:
        return "staged download cleanup completed"
    if status is False:
        return "STAGED DOWNLOAD CLEANUP FAILED"
    return "staged download cleanup outcome unavailable"


def _ulog_staged_cleanup_status(summary: Mapping[str, Any]) -> bool | None:
    value = summary.get("staged_job_deleted")
    return value if isinstance(value, bool) else None


def _format_ulog_dropouts(dropouts: Mapping[str, Any]) -> str:
    if not dropouts:
        return "dropouts unavailable"
    count = _as_int(dropouts.get("count"))
    total_seconds = _as_float(dropouts.get("total_duration_sec"), 0.0)
    maximum_ms = _as_float(dropouts.get("max_duration_ms"), 0.0)
    return (
        f"dropouts {count if count is not None else 'unknown'} "
        f"(total {total_seconds:.3f}s, max {maximum_ms:.1f}ms)"
    )


def _format_ulog_logged_message_levels(logged_messages: Mapping[str, Any]) -> str:
    if not logged_messages:
        return "logged-message levels unavailable (raw text excluded)"
    count = _as_int(logged_messages.get("count"))
    levels = logged_messages.get("levels") if isinstance(logged_messages.get("levels"), Mapping) else {}
    level_label = _format_ulog_count_mapping(levels)
    return (
        f"logged messages {count if count is not None else 'unknown'} "
        f"(levels {level_label}; raw text excluded)"
    )


def _format_ulog_system(system: Mapping[str, Any]) -> str:
    parts: list[str] = []
    if system.get("sys_name") not in (None, ""):
        parts.append(f"system {_truncate_text(str(system['sys_name']), 40)}")
    if system.get("ver_hw") not in (None, ""):
        parts.append(f"hardware {_truncate_text(str(system['ver_hw']), 40)}")
    return "; ".join(parts) or "system/hardware unavailable"


def _format_ulog_failsafe(vehicle_status: Mapping[str, Any]) -> str:
    counts = vehicle_status.get("failsafe") if isinstance(vehicle_status.get("failsafe"), Mapping) else {}
    return f"failsafe counts {_format_ulog_count_mapping(counts)}"


def _format_ulog_land_detection(land_detected: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("landed", "maybe_landed", "ground_contact", "freefall"):
        counts = land_detected.get(key) if isinstance(land_detected.get(key), Mapping) else {}
        if counts:
            parts.append(f"{key}[{_format_ulog_count_mapping(counts)}]")
    return "land detection " + (", ".join(parts) if parts else "unavailable")


def _format_ulog_final_displacement(local_position: Mapping[str, Any]) -> str:
    final_position = (
        local_position.get("final_relative_position_m")
        if isinstance(local_position.get("final_relative_position_m"), Mapping)
        else {}
    )
    if not final_position:
        return "final displacement unavailable"
    north = _as_float(final_position.get("north"), 0.0)
    east = _as_float(final_position.get("east"), 0.0)
    up = _as_float(final_position.get("up"), 0.0)
    return f"final displacement N {north:+.1f}m, E {east:+.1f}m, U {up:+.1f}m"


def _format_ulog_count_mapping(counts: Mapping[str, Any], *, limit: int = 6) -> str:
    if not counts:
        return "unavailable"
    items = sorted(counts.items(), key=lambda item: str(item[0]))[:limit]
    rendered: list[str] = []
    for key, value in items:
        count = _as_int(value)
        rendered.append(f"{_truncate_text(str(key), 24)}:{count if count is not None else 'unknown'}")
    return ", ".join(rendered)


def _format_ulog_local_movement(local_position: Mapping[str, Any]) -> str:
    if not local_position:
        return "local position unavailable"
    horizontal = _as_float(local_position.get("max_horizontal_distance_from_start_m"), -1.0)
    altitude = local_position.get("relative_altitude_range_m") if isinstance(local_position.get("relative_altitude_range_m"), Mapping) else {}
    parts: list[str] = []
    if horizontal >= 0:
        parts.append(f"max horizontal {horizontal:.1f}m")
    if altitude:
        minimum = _as_float(altitude.get("min"), 0.0)
        maximum = _as_float(altitude.get("max"), 0.0)
        parts.append(f"rel alt {minimum:.1f}..{maximum:.1f}m")
    return "; ".join(parts) or "local position present"


def _format_ulog_battery(battery: Mapping[str, Any]) -> str:
    voltage = battery.get("voltage_v") if isinstance(battery.get("voltage_v"), Mapping) else {}
    if voltage:
        minimum = _as_float(voltage.get("min"), 0.0)
        maximum = _as_float(voltage.get("max"), 0.0)
        return f"{minimum:.2f}..{maximum:.2f}V"
    return "battery topic unavailable"


def _format_ulog_command_summary(commands: Mapping[str, Any]) -> str:
    command = commands.get("vehicle_command") if isinstance(commands.get("vehicle_command"), Mapping) else {}
    ack = commands.get("vehicle_command_ack") if isinstance(commands.get("vehicle_command_ack"), Mapping) else {}
    command_samples = _as_int(command.get("samples")) if command else None
    ack_samples = _as_int(ack.get("samples")) if ack else None
    parts: list[str] = []
    if command_samples is not None:
        parts.append(f"commands {command_samples}")
    command_counts = command.get("command_counts") if isinstance(command.get("command_counts"), Mapping) else {}
    if command_counts:
        parts.append("command ids " + _format_ulog_count_mapping(command_counts, limit=4))
    if ack_samples is not None:
        parts.append(f"acks {ack_samples}")
    ack_command_counts = ack.get("command_counts") if isinstance(ack.get("command_counts"), Mapping) else {}
    if ack_command_counts:
        parts.append("ack ids " + _format_ulog_count_mapping(ack_command_counts, limit=4))
    ack_results = ack.get("result_counts") if isinstance(ack.get("result_counts"), Mapping) else {}
    if ack_results:
        parts.append("ack results " + _format_ulog_count_mapping(ack_results, limit=4))
    return "; ".join(parts) or "command topics unavailable"


def _warning_error_count_from_log_lines(payload: Mapping[str, Any]) -> int:
    lines = payload.get("lines") if isinstance(payload, Mapping) else None
    count = 0
    for line in lines or []:
        if not isinstance(line, Mapping):
            continue
        level = str(line.get("level") or "").upper()
        message = str(line.get("message") or line.get("msg") or "")
        if level in {"WARNING", "WARN", "ERROR", "CRITICAL"} or _log_level_from_text(message):
            count += 1
    return count


def _warning_error_samples_from_log_lines(
    payload: Mapping[str, Any],
    *,
    limit: int,
) -> tuple[dict[str, str], ...]:
    """Return bounded, sanitized operator evidence without exposing raw logs."""

    samples: list[dict[str, str]] = []
    lines = payload.get("lines") if isinstance(payload, Mapping) else None
    for line in lines or []:
        if not isinstance(line, Mapping):
            continue
        explicit_level = str(line.get("level") or "").upper()
        message = _sanitize_log_text(str(line.get("message") or line.get("msg") or ""))
        embedded_level = _log_level_from_text(message)
        if explicit_level not in {"WARNING", "WARN", "ERROR", "CRITICAL"} and not embedded_level:
            continue
        level = (
            explicit_level
            if explicit_level in {"WARNING", "WARN", "ERROR", "CRITICAL"}
            else str(embedded_level or "WARNING")
        )
        if level == "WARN":
            level = "WARNING"
        samples.append(
            {
                "timestamp": str(line.get("ts") or line.get("timestamp") or "").strip(),
                "level": level,
                "component": str(line.get("component") or line.get("source") or "").strip(),
                "message": _truncate_text(message, 220),
            }
        )
        if len(samples) >= max(0, limit):
            break
    return tuple(samples)


def _format_drone_log_warning_sample(hw_id: int, sample: Mapping[str, str]) -> str:
    timestamp = str(sample.get("timestamp") or "time unavailable")
    level = str(sample.get("level") or "WARNING")
    component = str(sample.get("component") or "source unavailable")
    message = str(sample.get("message") or "message unavailable")
    return f"Drone {hw_id} | {timestamp} | {level} | {component}: {message}"


def _format_bytes(value: float) -> str:
    if not math.isfinite(value) or value <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB")
    size = float(value)
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024.0
    if unit == "B":
        return f"{int(size)} B"
    return f"{size:.1f} {unit}"


def _deployment_mcp_endpoint(deps: Any | None = None) -> tuple[str, str]:
    configured = os.getenv(MCP_RESOURCE_URL_ENV, "").strip().rstrip("/")
    if configured and _is_absolute_http_url(configured):
        return configured, f"configured by `{MCP_RESOURCE_URL_ENV}`"

    request_base = str(getattr(deps, "simurgh_request_base_url", "") or "").strip().rstrip("/")
    if request_base and _is_absolute_http_url(request_base):
        return f"{request_base}{MCP_ENDPOINT_PATH}", "derived from this dashboard/API request"

    public_base = _configured_public_gcs_base_url()
    if public_base:
        return f"{public_base}{MCP_ENDPOINT_PATH}", "derived from public GCS host/port environment"

    return MCP_ENDPOINT_PATH, "path only; set `MDS_MCP_RESOURCE_URL` to pin a public reverse-proxy URL"


def _is_absolute_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.query and not parsed.fragment


def _configured_public_gcs_base_url() -> str:
    value = os.getenv("MDS_GCS_API_BASE_URL", "").strip().rstrip("/")
    return value if value and _is_absolute_http_url(value) else ""


def _format_duration_seconds(seconds: int | None) -> str:
    if not seconds:
        return "recent scanned window"
    units = ((86_400, "day"), (3600, "hour"), (60, "minute"))
    for unit_seconds, label in units:
        if seconds % unit_seconds == 0 and seconds >= unit_seconds:
            count = seconds // unit_seconds
            return f"{count} {label}{'' if count == 1 else 's'}"
    return f"{seconds} second{'' if seconds == 1 else 's'}"


def _display_log_timestamp(event: Mapping[str, Any]) -> str:
    timestamp = str(event.get("ts") or "").strip()
    if timestamp and timestamp != "time n/a":
        return timestamp
    extracted = _extract_log_timestamp(str(event.get("message") or ""))
    return extracted if extracted != "time n/a" else "time unavailable"


def _event_timestamp_seconds(event: Mapping[str, Any]) -> float | None:
    raw = event.get("ts")
    if raw is None or raw == "":
        raw = _extract_log_timestamp(str(event.get("message") or ""))
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value / 1000.0 if value > 10_000_000_000 else value
    text = str(raw or "").strip()
    if not text or text == "time n/a":
        return None
    if re.fullmatch(r"[0-2]?\d:[0-5]\d:[0-5]\d(?:\.\d{1,6})?", text):
        now = datetime.now(timezone.utc)
        time_format = "%H:%M:%S.%f" if "." in text else "%H:%M:%S"
        try:
            parsed_time = datetime.strptime(text, time_format).time()
        except ValueError:
            return None
        candidate = now.replace(
            hour=parsed_time.hour,
            minute=parsed_time.minute,
            second=parsed_time.second,
            microsecond=parsed_time.microsecond,
        )
        if candidate.timestamp() > time.time() + 300:
            candidate = candidate - timedelta(days=1)
        return candidate.timestamp()
    normalized = text.replace("Z", "+00:00")
    normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _sanitize_log_text(text: str) -> str:
    value = re.sub(r"\x1b\[[0-9;]*m", "", str(text or ""))
    value = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s,;]+", r"\1[redacted]", value)
    value = re.sub(r"sk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{12,}", "[redacted-api-key]", value)
    value = re.sub(r"(?i)((?:api[_ -]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+", r"\1[redacted]", value)
    return value.strip()


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _normalize_conversation_topic(value: str | None) -> str | None:
    raw = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if raw in READ_CONVERSATION_TOPICS:
        return raw
    normalized = _normalize_text(value or "")
    return normalized if normalized in READ_CONVERSATION_TOPICS else None


def _intent_from_contextual_followup(normalized: str, topic: str | None) -> str | None:
    """Route short follow-ups against the active session topic.

    This is intentionally topic-level, not answer-level. It lets operators ask
    natural follow-ups like "what about the scout IP?" or "what scripts?" while
    still letting explicit new-domain questions fall through to the main router.
    """

    if not topic or _mentions_other_domain(normalized, topic):
        return None
    if topic == "fleet":
        if _looks_like_contextual_live_fleet_state_question(normalized):
            return "fleet_connectivity"
        if _has_any(
            normalized,
            (
                "ip",
                "address",
                "scout",
                "leader",
                "which one",
                "how many",
                "configured",
                "what about",
                "that drone",
                "this drone",
                "drone 1",
                "drone 2",
                "drone 3",
            ),
        ) or _looks_like_generic_contextual_followup(normalized):
            return "fleet_summary"
    if topic == "swarm":
        if _has_any(normalized, ("quickscout", "quick scout", "swarm trajectory", "difference", "compare", " vs ")):
            return "mission_mode_comparison"
        if _has_any(normalized, ("where", "how", "edit", "change", "configure", "set", "offset", "follow")):
            return "operator_help"
        if _looks_like_generic_contextual_followup(normalized) or _has_any(
            normalized,
            ("formation", "cluster", "geometry", "distance", "spacing", "leader", "follower"),
        ):
            return "swarm_topology"
    if topic == "setup":
        if _looks_like_fleet_enrollment_question(normalized):
            return "fleet_enrollment_summary"
        if _has_any(normalized, ("companion", "raspberry", "cm4", "pi", "script", "bootstrap", "install")):
            return "companion_setup_help"
        if _has_any(normalized, ("third", "drone 3", "new drone", "add", "another drone")):
            return "add_drone_workflow"
        if _has_any(normalized, ("board", "env", "environment", "key", "fleet", "enroll", "enrollment")) or _looks_like_generic_contextual_followup(normalized):
            return "board_setup_help"
    if topic == "sar":
        if _looks_like_sar_status_question(normalized) or _looks_like_generic_contextual_followup(normalized):
            return "sar_summary"
    if topic == "runtime":
        if _has_any(normalized, ("sitl", "simulation", "switch", "change", "go to", "demo")):
            return "sitl_help"
        if _has_any(normalized, ("openai", "model", "provider", "circuit breaker", "always confirm", "mcp", "agent")) or _looks_like_generic_contextual_followup(normalized):
            return "runtime_summary"
    if topic == "capabilities":
        if _looks_like_action_capability_question(normalized):
            return "action_capability"
        if _looks_like_registry_domain_tool_question(normalized, topic=topic):
            return "registry_domain_tool_summary"
        if _has_any(normalized, ("mcp", "tool", "tools", "api", "apis", "menu", "client", "n8n", "claude", "vscode")) or _looks_like_generic_contextual_followup(normalized):
            return "capability_catalog"
    if topic == "sitl":
        if _looks_like_sitl_vehicle_readiness_question(normalized) or _looks_like_contextual_live_fleet_state_question(normalized):
            return "fleet_connectivity"
        if _has_any(normalized, ("how", "where", "switch", "change", "setup", "demo", "doc", "docs", "link")) or _looks_like_generic_contextual_followup(normalized):
            return "sitl_help"
    if topic == "flight":
        if _looks_like_action_history_summary_question(normalized):
            return "command_summary"
        if _looks_like_contextual_live_fleet_state_question(normalized) or _looks_like_generic_status_followup(normalized):
            return "fleet_connectivity"
    if topic == "public_geography":
        if _looks_like_public_geography_slot_followup(normalized) or _looks_like_public_geography_question(normalized):
            return "public_geography"
    if topic == "general":
        if _looks_like_weather_question(normalized) or _looks_like_general_knowledge_question(normalized):
            return "general_knowledge"
        if _looks_like_public_geography_question(normalized):
            return "public_geography"
        if _looks_like_autopilot_support_question(normalized):
            return "autopilot_support"
    return None


def _looks_like_registry_domain_tool_question(normalized: str, *, topic: str | None = None) -> bool:
    if not normalized:
        return False
    if _looks_like_direct_execution_request(normalized):
        return False
    if _has_any(normalized, ("api key", "api keys", "openai api", "openrouter api", "secret", "secrets")) and not _has_any(
        normalized,
        ("tool", "tools", "mcp", "route", "routes", "endpoint", "endpoints", "capability", "capabilities"),
    ):
        return False
    capability_terms = (
        "tool",
        "tools",
        "mcp",
        "route",
        "routes",
        "endpoint",
        "endpoints",
        "capability",
        "capabilities",
        "menu",
        "what api",
        "what apis",
        "which api",
        "which apis",
        "api route",
        "api routes",
        "api endpoint",
        "api endpoints",
        "can inspect",
        "can you query",
        "what can you inspect",
        "what can you query",
        "what can you read",
        "available for",
        "exposed for",
        "same menu",
    )
    if not _has_any(normalized, capability_terms):
        return False
    domains = _registry_domains_for_query(normalized, plan_domain=topic or "")
    if not domains:
        return False
    return any(domain not in {"simurgh", "docs", "operator"} for domain in domains)


def _registry_domains_for_query(normalized: str, *, plan_domain: str | None = None) -> tuple[str, ...]:
    domains: list[str] = []

    def add_many(values: Sequence[str]) -> None:
        for value in values:
            if value and value not in domains:
                domains.append(value)

    add_many(QUERY_DOMAIN_TO_REGISTRY_DOMAINS.get(str(plan_domain or ""), ()))
    keyword_domains = (
        (("quickscout", "quick scout", "sar", "search and rescue", "finding", "findings", "search area", "coverage", "handoff"), ("sar",)),
        (("sitl", "simulation", "simulator"), ("sitl",)),
        (("drone show", "skybrush", "show package", "show design", "custom show"), ("shows", "origin")),
        (("swarm trajectory", "trajectory", "formation", "cluster", "offset", "leader", "follower"), ("swarm_trajectories", "config", "origin")),
        (("fleet", "drone", "drones", "vehicle", "vehicles", "board", "boards", "cm4", "telemetry", "heartbeat", "connected", "online", "candidate", "enrollment"), ("fleet", "config")),
        (("sidecar", "wifi", "wi-fi", "mavlink dashboard", "smart wifi", "smart-wifi", "mavlink anywhere"), ("fleet", "system")),
        (("log", "logs", "warning", "warnings", "error", "errors", "backend", "audit"), ("logs", "simurgh")),
        (("runtime", "mode", "gcs mode", "real mode", "provider", "model", "circuit breaker", "always confirm", "environment", "env"), ("system", "simurgh")),
        (("px4", "parameter", "parameters", "param", "params", "sys_id"), ("px4_params", "commands")),
        (("origin", "launch position", "launch positions", "elevation", "deviation", "deviations"), ("origin",)),
        (("command", "commands", "action", "actions", "precision move"), ("commands",)),
        (("git", "repo", "repository", "sync"), ("git",)),
        (("docs", "doc", "documentation", "guide", "manual", "context"), ("docs", "simurgh")),
    )
    for signals, mapped_domains in keyword_domains:
        if _has_any(normalized, signals):
            add_many(mapped_domains)
    return tuple(domains)


def _matching_registry_tools(tools: Sequence[Any], normalized: str, registry_domains: Sequence[str]) -> list[Any]:
    domain_set = set(registry_domains)
    if not domain_set:
        return []
    keyword_terms = tuple(
        term
        for term in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", normalized)
        if term not in {"what", "which", "tools", "tool", "apis", "api", "mcp", "can", "you", "for", "the", "and", "read", "query", "inspect"}
    )
    matches: list[tuple[int, str, Any]] = []
    for tool in tools:
        tool_domain = _tool_registry_domain(tool)
        if tool_domain not in domain_set:
            continue
        text = _normalize_text(
            " ".join(
                str(value or "")
                for value in (
                    getattr(tool, "id", ""),
                    getattr(tool, "title", ""),
                    getattr(tool, "description", ""),
                    " ".join(getattr(tool, "tags", ()) or ()),
                    " ".join(getattr(tool, "docs", ()) or ()),
                )
            )
        )
        score = 0
        score += 8
        score += sum(1 for term in keyword_terms if term in text)
        tool_id = str(getattr(tool, "id", ""))
        if "telemetry" in keyword_terms and "telemetry" in tool_id:
            score += 10
        if any(term in keyword_terms for term in ("sidecar", "board", "boards")) and "sidecar" in tool_id:
            score += 6
        if any(term in keyword_terms for term in ("sync", "git")) and "git_sync" in tool_id:
            score += 6
        if score > 0:
            matches.append((score, tool_id, tool))
    matches.sort(key=lambda item: (-item[0], item[1]))
    return [tool for _score, _tool_id, tool in matches]


def _tool_registry_domain(tool: Any) -> str:
    tool_id = str(getattr(tool, "id", "") or "")
    parts = tool_id.split(".")
    if tool_id.startswith("mds.") and len(parts) >= 3:
        return parts[1]
    if tool_id.startswith("simurgh.") and len(parts) >= 2:
        return parts[1]
    return ""


def _registry_domains_from_tools(tools: Sequence[Any]) -> tuple[str, ...]:
    domains: list[str] = []
    for tool in tools:
        domain = _tool_registry_domain(tool)
        if domain and domain not in domains:
            domains.append(domain)
    return tuple(domains)


def _registry_domain_summary_label(domains: Sequence[str], *, fallback: str | None = None) -> str:
    labels = [REGISTRY_DOMAIN_LABELS.get(domain, domain.replace("_", " ")) for domain in domains[:4] if domain]
    if not labels and fallback:
        labels = [str(fallback).replace("_", " ")]
    if not labels:
        return "the requested domain"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _compact_tool_description(description: str, *, limit: int = 96) -> str:
    text = re.sub(r"\s+", " ", str(description or "")).strip()
    return _truncate_text(text, limit)


def _tool_route_label(tool: Any) -> str:
    method = str(getattr(tool, "route_method", "") or "").strip()
    path = str(getattr(tool, "route_path", "") or "").strip()
    if method and path:
        return f"`{method} {path}`"
    return "local advisory adapter"


def _tool_args_label(tool: Any) -> str:
    schema = getattr(tool, "input_schema", None) or {}
    if not isinstance(schema, Mapping) or not schema:
        return "none"
    required = [str(item) for item in schema.get("required") or []]
    properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
    optional = [str(name) for name in properties if str(name) not in required]
    if required and optional:
        return "required: " + ", ".join(required) + "; optional: " + ", ".join(optional[:3])
    if required:
        return "required: " + ", ".join(required)
    if optional:
        return "optional: " + ", ".join(optional[:4])
    return "schema-defined"


def _intent_from_query_plan(normalized: str, topic: str | None) -> str | None:
    """Use the shared query planner as a broad fallback for safe read tools."""

    try:
        from .query_understanding import build_assistant_query_plan
    except Exception:
        return None
    plan = build_assistant_query_plan(normalized, conversation_topic=topic)
    if plan.unclear and not topic:
        return None
    if plan.confidence < 0.18 and not topic:
        return None
    if not topic and not _has_fallback_request_signal(normalized):
        return None
    domain = plan.domain
    mode = plan.response_mode
    if domain == "drone_show":
        if mode == "workflow" and _has_any(normalized, ("upload", "import", "zip", "skybrush")):
            return "show_upload_help"
        if mode in {"compare", "workflow"} and _has_any(normalized, ("mode", "modes", "launch", "control", "workflow", "different", "difference")):
            return "show_modes_help"
        return "show_summary"
    if domain == "fleet":
        if _looks_like_fleet_enrollment_question(normalized):
            return "fleet_enrollment_summary"
        if _looks_like_live_fleet_state_question(normalized):
            return "fleet_connectivity"
        return "fleet_summary"
    if domain == "sar":
        if _looks_like_registry_domain_tool_question(normalized, topic=topic):
            return "registry_domain_tool_summary"
        if _looks_like_sar_status_question(normalized):
            return "sar_summary"
        return "docs_help"
    if domain == "swarm":
        if mode == "compare" or _has_any(normalized, ("quickscout", "quick scout", "swarm trajectory", " vs ")):
            return "mission_mode_comparison"
        if mode == "workflow" and _has_any(normalized, ("edit", "change", "configure", "set", "where", "how", "offset", "follow")):
            return "operator_help"
        return "swarm_topology"
    if domain == "sitl":
        return "sitl_help"
    if domain == "setup":
        if _looks_like_fleet_enrollment_question(normalized):
            return "fleet_enrollment_summary"
        if _has_any(normalized, ("companion", "raspberry", "cm4", " pi", "script", "bootstrap", "install")):
            return "companion_setup_help"
        if _has_any(normalized, ("third", "3rd", "drone 3", "new drone", "add drone", "another drone")):
            return "add_drone_workflow"
        return "board_setup_help"
    if domain == "logs":
        if _looks_like_drone_log_summary_question(normalized):
            return "drone_log_summary"
        return "backend_log_summary"
    if domain == "runtime":
        if mode == "workflow" and _has_any(normalized, ("sitl", "simulation", "switch", "change", "go to", "demo")):
            return "sitl_help"
        return "runtime_summary"
    if domain in {"capabilities", "mcp"}:
        if _looks_like_registry_domain_tool_question(normalized, topic=topic):
            return "registry_domain_tool_summary"
        return "capability_catalog"
    if domain == "docs" and mode == "workflow":
        return "docs_help"
    return None


def _looks_like_autopilot_support_question(normalized: str) -> bool:
    if not _has_domain_signal(normalized, ("ardupilot", "px4", "autopilot", "flight stack", "firmware stack")):
        return False
    return _has_domain_signal(
        normalized,
        ("mds", "simurgh", "support", "supports", "supported", "compatible", "work with", "works with", "currently", "today", "now"),
    )


def _looks_like_px4_params_question(normalized: str) -> bool:
    param_terms = (
        "param",
        "params",
        "parameter",
        "parameters",
        "profile",
        "profiles",
        "snapshot",
        "snapshots",
        "diff",
        "patch",
        "sys_id",
        "mav1_config",
        "mav_",
    )
    if not _has_domain_signal(normalized, ("px4", "sys_id", "mav1_config", "mav_", "parameter", "parameters", "param", "params")):
        return False
    return _has_domain_signal(normalized, param_terms)


def _looks_like_command_summary_question(normalized: str) -> bool:
    if _looks_like_direct_execution_request(normalized):
        return False
    if _looks_like_action_history_summary_question(normalized):
        return True
    if not _has_domain_signal(normalized, ("command", "commands", "command tracker", "gcs tracker", "action", "actions")):
        return False
    return _has_domain_signal(
        normalized,
        (
            "active",
            "recent",
            "history",
            "status",
            "statistics",
            "stats",
            "list",
            "show",
            "any",
            "what",
            "which",
            "last",
            "current",
            "tracker",
        ),
    )


def _looks_like_generic_status_followup(normalized: str) -> bool:
    if _looks_like_direct_execution_request(normalized):
        return False
    return _has_domain_signal(
        normalized,
        (
            "status",
            "status report",
            "report of status",
            "give me a report",
            "report",
            "check again",
            "again",
            "up now",
            "ready now",
            "what happened",
            "what happen",
            "where is it",
            "did it return",
            "is it flying",
            "is it landed",
            "landed",
            "flying",
        ),
    )


def _looks_like_compound_fleet_sitl_state_question(normalized: str) -> bool:
    fleet_signal = _has_domain_signal(normalized, ("drone", "drones", "fleet", "vehicle", "vehicles"))
    sitl_signal = _has_domain_signal(normalized, ("sitl", "simulator", "simulation"))
    if not (fleet_signal and sitl_signal):
        return False
    return _has_domain_signal(normalized, ("how many", "count", "counts", "number of", "total", "configured", "many"))


def _looks_like_live_fleet_count_state_question(normalized: str) -> bool:
    return _has_domain_signal(
        normalized,
        (
            "connected",
            "connection",
            "online",
            "live",
            "reachable",
            "heartbeat",
            "heartbeats",
            "telemetry",
            "seen by gcs",
        ),
    )


def _looks_like_action_history_summary_question(normalized: str) -> bool:
    retrospective = bool(
        re.search(r"\b(did|was|were|have|has)\b.{0,96}\b(you|it|that|this|sequence|action|command|step|steps)\b", normalized)
        or re.search(r"\b(skipped?|included?|happened?|completed?|done)\b", normalized)
    )
    if not retrospective:
        return False
    return _has_domain_signal(
        normalized,
        (
            "wait",
            "waits",
            "delay",
            "between",
            "sequence",
            "step",
            "steps",
            "post-action",
            "post action",
            "takeoff",
            "take off",
            "precision",
            "move",
            "rtl",
            "land",
            "command",
            "action",
        ),
    )


def _looks_like_git_status_question(normalized: str) -> bool:
    if _looks_like_direct_execution_request(normalized):
        return False
    if _has_domain_signal(normalized, ("swarm trajectory", "trajectory commit", "show commit")):
        return False

    repo_terms = (
        "git",
        "repo",
        "repository",
        "commit",
        "committed",
        "push",
        "pushed",
        "dirty",
        "uncommitted",
        "write-back",
        "writeback",
        "branch",
        "latest code",
    )
    sync_terms = (
        "synced",
        "sync status",
        "sync with gcs",
        "match gcs",
        "latest commit",
        "same commit",
        "boards updated",
        "drones updated",
    )
    query_terms = (
        "status",
        "current",
        "what",
        "which",
        "show",
        "check",
        "did",
        "does",
        "is",
        "are",
        "why",
        "report",
    )
    return (
        _has_domain_signal(normalized, repo_terms)
        or (_has_domain_signal(normalized, sync_terms) and _has_domain_signal(normalized, ("drone", "drones", "board", "boards", "gcs", "fleet")))
    ) and _has_domain_signal(normalized, query_terms)


def _looks_like_origin_status_question(normalized: str) -> bool:
    return _has_domain_signal(
        normalized,
        (
            "origin",
            "global origin",
            "mission origin",
            "launch position",
            "launch positions",
            "start position",
            "start positions",
            "trajectory start",
            "deviation",
            "deviations",
        ),
    ) and _has_domain_signal(normalized, ("status", "current", "what", "where", "show", "configured", "loaded", "set"))


def _looks_like_sidecar_status_question(normalized: str) -> bool:
    if not _has_domain_signal(normalized, ("sidecar", "sidecars", "wifi", "wi-fi", "smart wifi", "mavlink-anywhere", "mavlink dashboard", "fleet ops")):
        return False
    return _has_domain_signal(
        normalized,
        (
            "status",
            "dashboard",
            "dashboards",
            "port",
            "ports",
            "profile",
            "profiles",
            "sync",
            "drift",
            "wifi",
            "wi-fi",
            "mavlink",
            "where",
            "what",
            "which",
            "exist",
            "available",
        ),
    )


def _looks_like_node_boot_status_question(normalized: str) -> bool:
    if not _has_domain_signal(
        normalized,
        (
            "boot",
            "booting",
            "startup",
            "start up",
            "initializing",
            "initialising",
            "initialization",
            "initialisation",
            "git sync phase",
            "stuck in git sync",
            "still loading",
            "loading up",
        ),
    ):
        return False
    return _has_domain_signal(
        normalized,
        (
            "node",
            "nodes",
            "board",
            "boards",
            "drone",
            "drones",
            "fleet",
            "gcs",
            "repo",
            "repos",
            "mds",
            "status",
            "state",
            "progress",
            "phase",
            "sync",
            "ready",
            "stuck",
            "slow",
            "why",
            "any",
            "are",
            "show",
            "check",
        ),
    )


def _looks_like_system_status_question(normalized: str) -> bool:
    if _has_domain_signal(normalized, ("fleet status", "drone status", "show status", "swarm status")):
        return False
    return _has_domain_signal(
        normalized,
        (
            "gcs health",
            "system health",
            "server health",
            "service health",
            "health check",
            "gcs status",
            "system status",
            "gcs and simurgh service healthy",
            "simurgh service healthy",
            "is gcs healthy",
            "is the gcs healthy",
            "is simurgh healthy",
            "service healthy",
        ),
    )


def _looks_like_environment_summary_question(normalized: str) -> bool:
    if _has_domain_signal(
        normalized,
        (
            "new board",
            "third drone",
            "3rd drone",
            "companion computer",
            "raspberry pi",
            "cm4",
            "board setup",
            "setup new board",
            "setup new drone",
            "onboard",
            "onboarding",
            "provision",
            "provisioning",
        ),
    ):
        return False
    if not _has_domain_signal(normalized, ("environment", "environments", "env", "envs", "api key", "api keys", "openai key", "secret", "secrets")):
        return False
    return _has_domain_signal(
        normalized,
        ("what", "which", "where", "how", "edit", "change", "configure", "configured", "status", "registry", "settings", "keys"),
    )


def _looks_like_drone_log_summary_question(normalized: str) -> bool:
    if not _has_domain_signal(normalized, ("log", "logs", "flight log", "flight logs", "ulog", "ulogs", ".ulg")):
        return False
    if _has_domain_signal(normalized, ("backend", "gcs server", "server logs", "api logs")) and not _has_domain_signal(
        normalized,
        ("drone", "drones", "flight", "ulog", "ulogs", ".ulg", "onboard"),
    ):
        return False
    return _has_domain_signal(
        normalized,
        (
            "drone",
            "drones",
            "board",
            "boards",
            "vehicle",
            "vehicles",
            "flight",
            "flights",
            "onboard",
            "px4 log",
            "px4 logs",
            "ulog",
            "ulogs",
            ".ulg",
        ),
    )


def _looks_like_operation_log_verification_question(normalized: str) -> bool:
    if not _has_domain_signal(
        normalized,
        (
            "action",
            "actions",
            "command",
            "commands",
            "completed",
            "correct",
            "done",
            "flight",
            "happen",
            "happened",
            "mission",
            "sequence",
            "test",
        ),
    ):
        return False
    return _has_domain_signal(
        normalized,
        (
            "check",
            "confirm",
            "correct",
            "did",
            "happen",
            "happened",
            "report",
            "verify",
            "whether",
        ),
    )


def _looks_like_mcp_client_setup_question(normalized: str) -> bool:
    if not _has_domain_signal(normalized, ("mcp", "model context protocol")):
        return False
    if not _has_domain_signal(
        normalized,
        (
            "n8n",
            "claude",
            "claude desktop",
            "vs code",
            "vscode",
            "custom agent",
            "custom ai agent",
            "client",
            "connector",
            "connect",
            "external agent",
        ),
    ):
        return False
    return _has_domain_signal(
        normalized,
        (
            "connect",
            "address",
            "url",
            "endpoint",
            "port",
            "auth",
            "token",
            "scope",
            "consideration",
            "considerations",
            "setup",
            "configure",
            "use",
        ),
    )


def _looks_like_live_fleet_state_question(normalized: str) -> bool:
    if not _has_domain_signal(normalized, FLEET_LIVE_TERMS):
        return False
    return _has_domain_signal(
        normalized,
        (
            "fleet",
            "drone",
            "drones",
            "board",
            "boards",
            "cm4",
            "vehicle",
            "vehicles",
            "their",
            "they",
            "them",
            "connected",
            "online",
            "gps",
            "coordinate",
            "coordinates",
            "latitude",
            "longitude",
            "altitude",
            "country",
            "location",
            "battery",
            "voltage",
            "armed",
            "arming",
            "flight mode",
            "mode",
            "system status",
            "health",
            "failsafe",
            "telemetry",
            "ready",
            "readiness",
            "ready to fly",
            "flight ready",
            "fly ready",
            "preflight",
            "pre-flight",
        ),
    )


def _looks_like_contextual_live_fleet_state_question(normalized: str) -> bool:
    """Return whether an active fleet/flight frame owns this state follow-up.

    Health vocabulary naturally stays in the active vehicle frame. Position
    vocabulary is more ambiguous with public geography, so it additionally
    requires an explicit vehicle/fleet noun or a contextual target reference.
    """

    if not _looks_like_live_fleet_state_question(normalized):
        return False
    if not _wants_fleet_position_details(normalized):
        return True
    return bool(
        refers_to_contextual_target(normalized)
        or _has_domain_signal(
            normalized,
            (
                "fleet",
                "drone",
                "drones",
                "vehicle",
                "vehicles",
                "aircraft",
                "telemetry",
                "gps",
            ),
        )
    )


def _looks_like_sitl_vehicle_readiness_question(
    normalized: str,
    *,
    conversation_topic: str | None = None,
) -> bool:
    """Route SITL vehicle health questions to live telemetry, not setup docs.

    Operators naturally say "the SITL we created" when they mean the simulated
    vehicle that should now be streaming heartbeats and telemetry. Those prompts
    are current-state evidence requests; SITL docs are only appropriate for
    setup/workflow questions.
    """

    topic = _normalize_conversation_topic(conversation_topic)
    has_sitl_context = topic == "sitl" or _has_domain_signal(
        normalized,
        (
            "sitl",
            "simulation",
            "simulator",
            "container",
            "containers",
            "docker",
            "px4",
            "mavlink",
            "telemetry",
        ),
    )
    if not has_sitl_context:
        return False
    has_target_context = topic == "sitl" or _has_domain_signal(
        normalized,
        (
            "drone",
            "drones",
            "vehicle",
            "vehicles",
            "instance",
            "instances",
            "created",
            "running",
            "live",
            "one",
            "that",
            "it",
            "container",
            "containers",
            "docker",
            "px4",
            "mavlink",
            "telemetry",
        ),
    )
    if not has_target_context:
        return False
    if not _has_domain_signal(
        normalized,
        (
            "ready",
            "ready to fly",
            "flight ready",
            "fly ready",
            "preflight",
            "pre-flight",
            "health",
            "healthy",
            "telemetry",
            "heartbeat",
            "status",
            "summary",
            "report",
            "do it",
            "why not",
            "test",
            "gps",
            "battery",
            "armed",
            "arming",
            "alive",
            "check again",
            "up now",
        ),
    ):
        return False
    if _has_domain_signal(
        normalized,
        (
            "how do i create",
            "how to create",
            "how do i setup",
            "how to setup",
            "setup guide",
            "docs",
            "documentation",
            "guide",
            "manual",
        ),
    ):
        return False
    return True


def _looks_like_mds_fleet_evidence_request(normalized: str) -> bool:
    """Detect operator prompts that ask the assistant to use live GCS evidence.

    This intentionally sits above sticky conversation-topic routing. If an
    operator says they only have MDS/GCS telemetry or asks the assistant to
    check what it can see, the assistant should inspect fleet evidence instead
    of repeating a previous log/checklist answer.
    """

    if _has_any(normalized, ("log", "logs", "warning", "warnings", "error", "errors")) and not _has_any(
        normalized,
        ("telemetry", "fleet", "drone", "drones", "vehicle", "vehicles", "ready", "preflight"),
    ):
        return False

    local_evidence_signal = _has_any(
        normalized,
        (
            "mds telemetry",
            "gcs telemetry",
            "dashboard telemetry",
            "telemetry you have",
            "what you already have",
            "you already have",
            "you have all",
            "you have in mds",
            "you can check",
            "check yourself",
            "use mds",
            "use gcs",
            "from mds",
            "from gcs",
            "in mds",
            "in gcs",
        ),
    )
    if not local_evidence_signal:
        return False

    return _has_domain_signal(
        normalized,
        (
            *FLEET_LIVE_TERMS,
            "qgc",
            "px4",
            "mavlink",
            "takeoff",
            "fly",
            "flight",
            "preflight",
            "readiness",
            "ready",
        ),
    )


def _looks_like_fleet_enrollment_question(normalized: str) -> bool:
    if _looks_like_fleet_enrollment_workflow_question(normalized):
        return False
    if not _has_domain_signal(
        normalized,
        (
            "fleet enrollment",
            "enrollment",
            "enroll",
            "candidate",
            "candidates",
            "announced board",
            "announced boards",
            "pending board",
            "pending boards",
            "waiting board",
            "waiting boards",
            "replacement candidate",
            "recover candidate",
            "onboarded candidate",
        ),
    ):
        return False
    return _has_domain_signal(
        normalized,
        (
            "status",
            "state",
            "current",
            "pending",
            "waiting",
            "review",
            "conflict",
            "available",
            "announced",
            "new",
            "which",
            "what",
            "any",
            "show",
            "list",
            "report",
            "ready",
            "can i accept",
            "accept",
            "replace",
            "recover",
        ),
    )


def _looks_like_fleet_enrollment_workflow_question(normalized: str) -> bool:
    if not _has_domain_signal(
        normalized,
        (
            "fleet enrollment",
            "enrollment",
            "enroll",
            "candidate",
            "candidates",
            "announced board",
            "pending board",
            "waiting board",
            "new board",
            "new boards",
        ),
    ):
        return False
    return _has_domain_signal(
        normalized,
        (
            "how do i",
            "how to",
            "what should",
            "what must",
            "workflow",
            "steps",
            "setup",
            "set up",
            "configure",
            "guide",
            "doc",
            "docs",
            "script",
            "create",
            "build",
        ),
    )


def _looks_like_add_drone_enrollment_workflow_question(normalized: str) -> bool:
    if not _looks_like_add_drone_workflow_question(normalized):
        return False
    if not _has_domain_signal(normalized, ("enroll", "enrollment")):
        return False
    return not _has_domain_signal(
        normalized,
        (
            "raspberry",
            "raspberry pi",
            "cm4",
            "companion",
            "companion computer",
            "script",
            "doc",
            "docs",
            "link",
            "read",
        ),
    )


def _looks_like_swarm_readiness_question(normalized: str) -> bool:
    if not _has_domain_signal(
        normalized,
        (
            "smart swarm",
            "swarm mission",
            "swarm field test",
            "swarm test",
            "swarm",
            "formation",
            "follow test",
            "cluster mission",
        ),
    ):
        return False
    return _has_domain_signal(
        normalized,
        (
            "ready",
            "readiness",
            "field test",
            "test flight",
            "test fly",
            "fly",
            "flying",
            "before turning on",
            "before flight",
            "planned before",
            "is all ready",
            "all is ready",
            "all ready",
            "safe to test",
        ),
    )


def _looks_like_sar_status_question(normalized: str) -> bool:
    if _looks_like_mission_mode_question(normalized):
        return False
    if not _has_domain_signal(
        normalized,
        (
            "quickscout",
            "quick scout",
            "sar",
            "search and rescue",
            "search mission",
            "rescue mission",
        ),
    ):
        return False
    return _has_domain_signal(
        normalized,
        (
            "mission",
            "missions",
            "status",
            "current",
            "active",
            "planned",
            "loaded",
            "ready",
            "readiness",
            "field test",
            "launchable",
            "coverage",
            "progress",
            "finding",
            "findings",
            "handoff",
            "monitor",
            "history",
            "reopen",
            "is there",
            "any",
            "check",
            "show",
            "report",
        ),
    )


def _swarm_trajectory_readiness_label(
    trajectory_ready: bool,
    has_processed_outputs: bool,
    blockers: Sequence[Any],
) -> str:
    if trajectory_ready:
        return "validated ready by current package check"
    if blockers:
        return f"not ready, {len(blockers)} blocker(s)"
    if has_processed_outputs:
        return "processed outputs exist, but validation is not ready"
    return "no processed trajectory package visible"


def _issue_message(issue: Any) -> str:
    if isinstance(issue, Mapping):
        message = str(issue.get("message") or issue.get("detail") or issue.get("code") or issue).strip()
        severity = str(issue.get("severity") or "").strip()
        return f"{severity}: {message}" if severity else message
    return str(issue)


def _wants_fleet_position_details(normalized: str) -> bool:
    return _has_domain_signal(normalized, FLEET_POSITION_TERMS)


def _wants_fleet_health_details(normalized: str) -> bool:
    return _has_domain_signal(normalized, FLEET_HEALTH_TERMS)


def _fleet_altitude_summary(telemetry_row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the best altitude with an explicit frame label.

    ``position_alt`` and ``gps_raw_altitude_m`` are MSL values.  The previous
    reader silently used them as a relative altitude fallback, which made a
    20 m takeoff appear at the local terrain's 1,298 m MSL elevation.
    """

    report = telemetry_row.get("altitude_report")
    if isinstance(report, Mapping):
        display = _finite_or_none(report.get("display_m"))
        if display is not None:
            source = str(report.get("source") or "").strip().casefold()
            label = str(report.get("label") or "").strip().upper()
            if label not in {"REL", "LCL", "BARO", "MSL"}:
                label = {
                    "relative_home": "REL",
                    "local_ned": "LCL",
                    "baro": "BARO",
                    "absolute_msl": "MSL",
                }.get(source, "ALT")
            return {"value": display, "label": label, "source": source or "unknown"}

        sources = report.get("sources")
        if isinstance(sources, Mapping):
            for source, label in (
                ("relative_home", "REL"),
                ("local_ned", "LCL"),
                ("baro", "BARO"),
                ("absolute_msl", "MSL"),
            ):
                candidate = sources.get(source)
                if isinstance(candidate, Mapping):
                    value = _finite_or_none(candidate.get("value_m"))
                    if value is not None and candidate.get("valid", True):
                        return {"value": value, "label": label, "source": source}

    for key in ("relative_altitude_m", "relative_home_m"):
        value = _finite_or_none(telemetry_row.get(key))
        if value is not None:
            return {"value": value, "label": "REL", "source": "relative_home"}

    local_up = _finite_or_none(_first_present(telemetry_row, ("local_position_up_m", "local_up_m")))
    if local_up is not None:
        return {"value": local_up, "label": "LCL", "source": "local_ned"}
    local_down = _finite_or_none(_first_present(telemetry_row, ("local_position_down", "local_down_m")))
    if local_down is not None:
        return {"value": -local_down, "label": "LCL", "source": "local_ned"}

    baro = _finite_or_none(_first_present(telemetry_row, ("baro_altitude_m", "baro_m")))
    if baro is not None:
        return {"value": baro, "label": "BARO", "source": "baro"}

    msl = _finite_or_none(
        _first_present(telemetry_row, ("position_alt", "gps_raw_altitude_m", "altitude_m", "altitude"))
    )
    if msl is not None:
        return {"value": msl, "label": "MSL", "source": "absolute_msl"}
    return {"value": None, "label": "unknown", "source": "unknown"}


def _fleet_position_summary(telemetry_row: Mapping[str, Any]) -> tuple[float | None, float | None, float | None, str]:
    lat = _finite_or_none(_first_present(telemetry_row, ("position_lat", "latitude", "lat", "latitude_deg")))
    lon = _finite_or_none(_first_present(telemetry_row, ("position_long", "position_lon", "longitude", "lon", "longitude_deg")))
    alt = _fleet_altitude_summary(telemetry_row)["value"]
    valid = bool(telemetry_row.get("global_position_valid") or telemetry_row.get("gps_raw_valid"))
    fix_type = _as_int(telemetry_row.get("gps_fix_type"))
    satellites = _as_int(telemetry_row.get("satellites_visible") or telemetry_row.get("gps_satellites_visible"))
    if not _valid_coordinate(lat, lon):
        lat = None
        lon = None
        valid = False
    if fix_type is not None:
        gps = f"fix {fix_type}"
        if satellites is not None:
            gps += f", {satellites} sats"
        if not valid:
            gps += "; no valid global position"
    elif valid:
        gps = "valid global position"
    else:
        gps = "unavailable"
    return lat, lon, alt, gps


def _fleet_health_summary(telemetry_row: Mapping[str, Any]) -> dict[str, str]:
    voltage = _finite_or_none(_first_present(telemetry_row, ("battery_voltage", "battery", "voltage", "battery_v")))
    remaining = _finite_or_none(
        _first_present(
            telemetry_row,
            ("battery_remaining_percent", "battery_percentage", "battery_remaining", "battery_percent"),
        )
    )
    armed = _first_present(telemetry_row, ("is_armed", "armed"))
    ready = _first_present(telemetry_row, ("is_ready_to_arm", "ready_to_arm", "armable"))
    mode = _first_present(telemetry_row, ("flight_mode_name", "mode_name", "mode", "flight_mode"))
    system = _first_present(telemetry_row, ("system_status_name", "system_state", "system_status"))
    _lat, _lon, _absolute_or_display_altitude, gps = _fleet_position_summary(telemetry_row)
    altitude = _fleet_altitude_summary(telemetry_row)
    landed_label = _fleet_landed_state_label(telemetry_row)
    vertical_speed = _finite_or_none(
        _first_present(telemetry_row, ("velocity_down", "local_velocity_down", "vertical_velocity_mps"))
    )
    home_distance = _finite_or_none(
        _first_present(telemetry_row, ("distance_to_home_m", "home_distance_m"))
    )
    final_state_parts = [f"Landed: {landed_label}"]
    if altitude["value"] is not None:
        final_state_parts.append(f"Altitude: {altitude['value']:.1f} m {altitude['label']}")
    else:
        final_state_parts.append("Altitude: unknown")
    if vertical_speed is not None:
        final_state_parts.append(f"V-down: {vertical_speed:.1f} m/s")
    if home_distance is not None:
        final_state_parts.append(f"Home distance: {home_distance:.1f} m")
    flight_state = "; ".join(final_state_parts)
    return {
        "battery": _fmt_battery(voltage, remaining),
        "armed": _fmt_bool_state(armed),
        "landed": landed_label,
        # Keep the compatibility key for internal consumers.  The operator
        # surface calls this "Flight state", not "Final state": this is a
        # current snapshot and is not terminal action evidence.
        "final_state": flight_state,
        "flight_state": flight_state,
        "ready": _fmt_bool_state(ready),
        "mode": _fmt_optional_value(mode),
        "system": _fmt_optional_value(system),
        "gps": gps,
    }


def _fleet_health_verdict_line(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "Telemetry verdict: no drone telemetry rows are visible."
    live_rows = [row for row in rows if bool(row.get("live"))]
    ready_rows = [row for row in live_rows if str(row.get("ready") or "").casefold() == "yes"]
    if len(live_rows) == 1:
        row = live_rows[0]
        readiness = str(row.get("ready") or "unknown")
        prefix = (
            f"MDS preflight verdict: {row.get('drone', 'the drone')} is live and reports ready"
            if readiness.casefold() == "yes"
            else f"MDS preflight verdict: {row.get('drone', 'the drone')} is live but does not report ready"
            if readiness.casefold() == "no"
            else f"MDS preflight verdict: {row.get('drone', 'the drone')} is live; readiness is unknown"
        )
        return (
            f"{prefix}. "
            f"Ready={readiness}, Armed={row.get('armed', 'unknown')}, "
            f"{row.get('flight_state', row.get('final_state', 'flight state unknown'))}, GPS={row.get('gps', 'unknown')}."
        )
    if not live_rows:
        return "Telemetry verdict: no live drone telemetry is visible, so MDS cannot call any vehicle ready."
    return f"Telemetry verdict: {len(live_rows)}/{len(rows)} live; {len(ready_rows)} report Ready=Yes."


def _fmt_battery(voltage: float | None, remaining: float | None = None) -> str:
    parts: list[str] = []
    if voltage is not None:
        parts.append(f"{voltage:.2f} V")
    if remaining is not None:
        display_remaining = remaining * 100.0 if 0.0 <= remaining <= 1.0 else remaining
        parts.append(f"{display_remaining:.0f}%")
    return " / ".join(parts) if parts else "unavailable"


def _fleet_landed_state_label(telemetry_row: Mapping[str, Any]) -> str:
    for key in ("is_landed", "landed"):
        value = telemetry_row.get(key)
        if isinstance(value, bool):
            return "On ground" if value else "In air"
        if value in (None, ""):
            continue
        normalized = str(value).strip().casefold()
        if normalized in {"true", "yes", "on", "on_ground", "ground"}:
            return "On ground"
        if normalized in {"false", "no", "off", "in_air", "airborne"}:
            return "In air"

    enum_labels = {
        "0": "Unknown",
        "unknown": "Unknown",
        "1": "On ground",
        "on_ground": "On ground",
        "landed": "On ground",
        "2": "In air",
        "in_air": "In air",
        "airborne": "In air",
        "3": "Taking off",
        "taking_off": "Taking off",
        "4": "Landing",
        "landing": "Landing",
    }
    for key in ("landed_state", "land_state"):
        value = telemetry_row.get(key)
        if value in (None, ""):
            continue
        normalized = str(value).strip().casefold()
        return enum_labels.get(normalized, f"Unknown ({_truncate_text(str(value), 24)})")
    armed = _first_present(telemetry_row, ("is_armed", "armed"))
    vertical_speed = _finite_or_none(
        _first_present(telemetry_row, ("velocity_down", "local_velocity_down", "vertical_velocity_mps"))
    )
    if (
        _fmt_bool_state(armed) == "No"
        and _telemetry_enum_matches(telemetry_row, ("state", "state_name"), State.IDLE)
        and _telemetry_enum_matches(telemetry_row, ("mission", "mission_name"), Mission.NONE)
        and (vertical_speed is None or abs(vertical_speed) <= 0.75)
    ):
        return "On ground (inferred)"
    return "Unknown"


def _telemetry_enum_matches(
    telemetry_row: Mapping[str, Any],
    keys: Sequence[str],
    expected: Mission | State,
) -> bool:
    expected_name = expected.name.casefold()
    expected_value = str(expected.value)
    enum_label = f"{type(expected).__name__}.{expected.name}".casefold()
    for key in keys:
        value = telemetry_row.get(key)
        if value in (None, ""):
            continue
        normalized = str(value).strip().casefold()
        if normalized in {expected_name, expected_value, enum_label}:
            return True
    return False


def _fmt_bool_state(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value in (None, ""):
        return "unavailable"
    text = str(value).strip()
    if not text:
        return "unavailable"
    lowered = text.casefold()
    if lowered in {"true", "1", "yes", "y"}:
        return "Yes"
    if lowered in {"false", "0", "no", "n"}:
        return "No"
    return text


def _fmt_optional_value(value: Any) -> str:
    if value in (None, ""):
        return "unavailable"
    return str(value)


def _first_present(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return None


def _finite_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _valid_coordinate(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    return not (abs(lat) < 1e-9 and abs(lon) < 1e-9)


def _fmt_coordinate(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.7f}"


def _fmt_altitude_m(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.1f} m"


def _looks_like_generic_contextual_followup(normalized: str) -> bool:
    return _has_any(
        normalized,
        (
            "what about",
            "and this",
            "and that",
            "that one",
            "this one",
            "these",
            "those",
            "them",
            "what is it",
            "is it",
            "it mean",
            "what does it mean",
            "what does this mean",
            "explain",
            "meaning",
            "why",
            "next",
            "steps",
            "docs",
            "link",
        ),
    )


def _mentions_other_domain(normalized: str, topic: str) -> bool:
    domain_terms: dict[str, tuple[str, ...]] = {
        "drone_show": ("drone show", "skybrush", "show design", "show package"),
        "fleet": ("fleet", "drone", "drones", "vehicle", "scout", "ip", "sys_id", "telemetry"),
        "swarm": ("swarm", "formation", "cluster", "offset", "follow", "geometry", "swarm trajectory", "quickscout", "quick scout"),
        "setup": ("setup", "set up", "companion", "raspberry", "cm4", "board", "new drone", "third drone", "bootstrap"),
        "logs": ("log", "logs", "warning", "error", "backend", "trace"),
        "runtime": ("runtime", "provider", "model", "circuit breaker", "always confirm", "gcs mode"),
        "capabilities": ("capability", "capabilities", "tool", "tools", "api", "apis", "mcp", "n8n", "claude"),
        "sar": ("sar", "quickscout", "quick scout", "search and rescue", "finding", "findings", "coverage", "handoff"),
        "sitl": ("sitl", "simulation", "simulator"),
    }
    for domain, terms in domain_terms.items():
        if domain != topic and _has_domain_signal(normalized, terms):
            return True
    return False


def _has_fallback_request_signal(normalized: str) -> bool:
    return _has_domain_signal(
        normalized,
        (
            "what",
            "which",
            "how",
            "where",
            "can",
            "could",
            "check",
            "show",
            "list",
            "status",
            "current",
            "is",
            "are",
            "do",
            "does",
            "give",
            "read",
            "docs",
            "link",
            "connect",
            "setup",
            "configure",
            "explain",
            "compare",
            "difference",
            "different",
            "ready",
            "uploaded",
            "connected",
        ),
    )


def _has_domain_signal(value: str, terms: tuple[str, ...]) -> bool:
    for term in terms:
        term = str(term or "").strip()
        if not term:
            continue
        if re.fullmatch(r"[a-z0-9_]+", term):
            if re.search(rf"\b{re.escape(term)}\b", value):
                return True
        elif term in value:
            return True
    return False


def _looks_like_contextual_log_followup(normalized: str) -> bool:
    return _has_any(
        normalized,
        (
            "does this mean",
            "does it mean",
            "means something",
            "something is wrong",
            "something wrong",
            "anything wrong",
            "is something wrong",
            "is anything wrong",
            "is this wrong",
            "what are these",
            "what are those",
            "what does this mean",
            "what does it mean",
            "what do they mean",
            "what they mean",
            "explain these",
            "explain that",
            "explain the logs",
            "interpret",
            "meaning",
            "why",
            "root cause",
            "should i worry",
            "should we worry",
            "is it bad",
            "is this bad",
            "severity",
            "impact",
            "worth mentioning",
            "worth mention",
            "for operation",
        ),
    )


def _looks_like_weather_question(normalized: str) -> bool:
    return _has_domain_signal(
        normalized,
        (
            "weather",
            "forecast",
            "wind today",
            "weather today",
            "rain today",
            "visibility today",
            "temperature today",
        ),
    )


def _looks_like_general_knowledge_question(normalized: str) -> bool:
    if not normalized:
        return False
    if _has_domain_signal(
        normalized,
        (
            "status",
            "current status",
            "configured",
            "connected",
            "online",
            "offline",
            "heartbeat",
            "telemetry",
            "ip",
            "fleet",
            "swarm",
            "drone show",
            "logs",
            "warning",
            "error",
            "runtime",
        ),
    ):
        return False
    if not _has_domain_signal(
        normalized,
        (
            "what is",
            "what are",
            "define",
            "definition",
            "meaning of",
            "explain",
            "tell me about",
        ),
    ):
        return False
    try:
        knowledge = _load_general_knowledge_config()
    except AgentRuntimeError:
        return False
    return _matching_general_concept(normalized, knowledge) is not None


def _looks_like_public_geography_question(normalized: str) -> bool:
    if not normalized:
        return False
    if _has_domain_signal(
        normalized,
        (
            "mds",
            "simurgh",
            "fleet",
            "swarm",
            "drone show",
            "skybrush",
            "qgc",
            "px4",
            "mavlink",
            "sys_id",
            "telemetry",
            "heartbeat",
            "netbird",
            "gcs",
            "dashboard",
            "sitl",
            "logs",
            "runtime",
            "mcp",
            "scout drone",
            "drone 1",
            "drone 2",
            "drone 3",
        ),
    ):
        return False
    try:
        places = _matching_public_places(normalized, _load_public_places_config())
    except AgentRuntimeError:
        return False
    if not places:
        return False
    return _has_domain_signal(
        normalized,
        (
            "how far",
            "how many km",
            "how many kilometer",
            "how many kilometers",
            "kilometer",
            "kilometers",
            "distance from",
            "distance between",
            "latitude",
            "longitude",
            "lat long",
            "lat lon",
            "lat/lon",
            "lat and long",
            "lat/long",
            "lng",
            "wgs84",
            "altitude",
            "elevation",
            "height",
            "meters above sea level",
            "masl",
            "coordinates",
            "coordinate",
            "around",
            "circle",
            "loop",
            "radius",
            "orbit",
            "flight around",
        ),
    )


def _looks_like_coordinate_country_question(normalized: str) -> bool:
    """Detect an explicit coordinate-to-country lookup.

    Parsing and validation live in the geography component; this predicate only
    decides whether the local offline capability owns the question.
    """

    if not normalized or extract_latitude_longitude(normalized) is None:
        return False
    return _has_domain_signal(
        normalized,
        (
            "country",
            "which country",
            "what country",
            "location",
            "coordinate",
            "coordinates",
            "latitude",
            "longitude",
            "lat",
            "lon",
            "lng",
        ),
    )


def _looks_like_public_geography_slot_followup(normalized: str) -> bool:
    """Return whether a short reply is filling a public-geography slot.

    Examples include an operator answering a prior clarification with
    "yes, meters and WGS84". This should bind to the current geography task,
    not to an older fleet/swarm topic.
    """

    if not normalized:
        return False
    if len(normalized) > 120:
        return _looks_like_public_geography_question(normalized)
    return _has_domain_signal(
        normalized,
        (
            "yes",
            "yeah",
            "ok",
            "correct",
            "meter",
            "meters",
            "metre",
            "metres",
            "wgs84",
            "decimal degree",
            "decimal degrees",
            "msl",
            "asl",
            "above sea level",
            "elevation",
            "altitude",
            "lat lon",
            "lat long",
        ),
    )


def _looks_like_non_mds_general_question(normalized: str) -> bool:
    """Detect normal assistant questions that must not inherit an MDS topic.

    Session topic is helpful for short follow-ups like "what does that mean?";
    it is harmful when the operator has clearly moved to geography, math,
    public facts, or web-style questions. Returning None lets the provider lane
    answer naturally instead of forcing a stale fleet/swarm/status tool.
    """

    if not normalized:
        return False
    if _has_domain_signal(
        normalized,
        (
            "mds",
            "simurgh",
            "fleet",
            "swarm",
            "drone show",
            "skybrush",
            "show design",
            "qgc",
            "px4",
            "mavlink",
            "sys_id",
            "telemetry",
            "heartbeat",
            "netbird",
            "gcs",
            "dashboard",
            "sitl",
            "logs",
            "runtime",
            "circuit breaker",
            "mcp",
            "scout drone",
            "drone 1",
            "drone 2",
            "drone 3",
        ),
    ):
        return False
    if _has_domain_signal(normalized, ("battery", "armed", "arming", "ready to arm", "flight mode", "system status", "gps")) and _has_domain_signal(
        normalized,
        ("their", "they", "them", "drone", "drones", "board", "boards", "vehicle", "vehicles"),
    ):
        return False
    return _has_domain_signal(
        normalized,
        (
            "how far",
            "how many km",
            "how many kilometer",
            "how many kilometers",
            "kilometer",
            "kilometers",
            " km",
            " miles",
            "distance from",
            "distance between",
            "latitude",
            "longitude",
            "lat long",
            "lat lon",
            "lat/lon",
            "lat and long",
            "lat/long",
            "wgs84",
            "altitude",
            "elevation",
            "height",
            "coordinates",
            "coordinate of",
            "mountain",
            "peak",
            "damavand",
            "tehran",
            "new york",
            "capital of",
            "population of",
            "country is",
            "city is",
            "who is",
            "when is",
            "where is",
            "calculate",
            "math",
            "convert",
            "regulation",
            "regulations",
            "law",
            "rules",
            "internet",
            "web search",
            "search the web",
            "search internet",
        ),
    )


def _looks_like_previous_answer_transform(normalized: str) -> bool:
    language_markers = (
        "persian",
        "farsi",
        "فارسی",
        "français",
        "french",
        "spanish",
        "español",
        "arabic",
        "عربی",
        "english",
    )
    transform_markers = (
        "say it in",
        "say this in",
        "translate",
        "translation",
        "same in",
        "answer in",
        "write it in",
        "rewrite it in",
        "به فارسی",
        "فارسی بگو",
        "فارسی بنویس",
        "همینو فارسی",
        "همین رو فارسی",
        "همین را فارسی",
        "in persian",
        "in farsi",
    )
    persian_same_answer = "فارسی" in normalized and _has_any(normalized, ("همینو", "همین رو", "همین را", "این رو", "این را"))
    if persian_same_answer or (
        any(marker in normalized for marker in transform_markers) and any(marker in normalized for marker in language_markers)
    ):
        return True
    return _has_any(normalized, ("shorter", "more concise", "simpler", "summarize that", "summarise that"))


def _looks_like_interpretation_followup(normalized: str, *, topic: str | None = None) -> bool:
    if _looks_like_contextual_log_followup(normalized):
        return True
    if topic == "drone_show" and _looks_like_contextual_show_interpretation_followup(normalized):
        return True
    if topic and _has_any(
        normalized,
        (
            "what does this mean",
            "what does it mean",
            "what do they mean",
            "explain",
            "interpret",
            "meaning",
            "why",
            "impact",
            "severity",
            "should i worry",
            "should we worry",
        ),
    ):
        return True
    return False


def _looks_like_contextual_show_status_question(normalized: str) -> bool:
    if _has_any(normalized, ("upload ", "upload a", "upload skybrush", "import ", "how to", "how do i", "where can i")):
        return False
    return _has_any(normalized, ("uploaded", "loaded", "ready", "current", "active", "present", "any")) and _has_any(
        normalized,
        ("is there", "there any", "any uploaded", "any loaded", "is any", "ready", "uploaded", "loaded"),
    )


def _looks_like_contextual_show_interpretation_followup(normalized: str) -> bool:
    if _has_any(normalized, ("upload skybrush", "import skybrush", "how to upload", "where can i upload")):
        return False
    return _has_any(
        normalized,
        (
            "what does this mean",
            "what does it mean",
            "what do they mean",
            "what they mean",
            "explain",
            "interpret",
            "meaning",
            "ready mean",
            "uploaded mean",
            "loaded mean",
            "fly ready",
            "fly-ready",
            "why not ready",
            "history",
            "keep history",
            "remember",
            "previous",
        ),
    )


def _looks_like_contextual_show_followup(normalized: str) -> bool:
    return _looks_like_contextual_show_status_question(normalized) or _looks_like_contextual_show_interpretation_followup(normalized)


def _looks_like_add_drone_workflow_question(normalized: str) -> bool:
    drone_terms = ("third drone", "3rd drone", "drone 3", "new drone", "add drone", "add a drone", "add another drone")
    workflow_terms = (
        "add",
        "workflow",
        "what should",
        "what must",
        "steps",
        "setup",
        "set up",
        "configure",
        "now",
    )
    return _has_any(normalized, drone_terms) and _has_any(normalized, workflow_terms)


def _looks_like_companion_setup_question(normalized: str) -> bool:
    setup_terms = (
        "companion",
        "companion computer",
        "raspberry",
        "raspberry pi",
        " rpi",
        " pi ",
        "cm4",
        "compute module",
        "new drone",
        "drone 3",
        "board 3",
        "install",
        "bootstrap",
        "provision",
        "onboard",
        "node setup",
    )
    intent_terms = (
        "what should",
        "how",
        "setup",
        "set up",
        "build",
        "script",
        "docs",
        "doc",
        "link",
        "read",
        "install",
        "provision",
        "bootstrap",
    )
    return _has_any(normalized, setup_terms) and _has_any(normalized, intent_terms)


def _looks_like_mission_mode_question(normalized: str) -> bool:
    quickscout_terms = ("quickscout", "quick scout")
    swarm_trajectory_terms = ("swarm trajectory", "trajectory mode", "mission type 4")
    concept_terms = (
        "difference",
        "different",
        "compare",
        "comparison",
        "versus",
        " vs ",
        "mode",
        "workflow",
        "what is",
        "when should",
        "when to use",
        "use quick",
        "use swarm",
    )
    mentions_quickscout = _has_any(normalized, quickscout_terms)
    mentions_swarm_trajectory = _has_any(normalized, swarm_trajectory_terms)
    if mentions_quickscout and mentions_swarm_trajectory:
        return True
    return (mentions_quickscout or mentions_swarm_trajectory) and _has_any(normalized, concept_terms)


def _looks_like_show_modes_question(normalized: str) -> bool:
    if not _has_any(normalized, ("drone show", "skybrush", "custom show", "show package", "show design")):
        return False
    return _has_any(
        normalized,
        (
            "different mode",
            "different modes",
            "modes",
            "mode",
            "workflow family",
            "workflow families",
            "control mode",
            "control modes",
            "launch mode",
            "launch modes",
            "types",
            "difference",
            "different",
            "compare",
        ),
    ) and _has_any(normalized, ("what", "which", "explain", "different", "difference", "compare", "mode", "modes"))


def _looks_like_show_status_question(normalized: str) -> bool:
    if not _has_any(normalized, ("drone show", "skybrush", "custom show", "show package")):
        return False
    return _has_any(
        normalized,
        (
            "uploaded now",
            "currently uploaded",
            "is uploaded",
            "uploaded",
            "loaded now",
            "currently loaded",
            "is loaded",
            "loaded",
            "ready",
            "planned now",
            "active package",
            "current package",
            "how long",
            "duration",
            "length",
            "takes",
            "take?",
        ),
    )


def _looks_like_show_upload_help_question(normalized: str) -> bool:
    show_terms = (
        "skybrush",
        "drone show",
        "show design",
        "show upload",
        "upload show",
        "import show",
        "show zip",
        "zip show",
    )
    if _looks_like_show_status_question(normalized):
        return False

    help_terms = (
        "how to",
        "how do i",
        "how can i",
        "where do i",
        "where can i",
        "what should",
        "steps",
        "workflow",
        "guide",
        "doc",
        "docs",
        "link",
        "manual",
        "read about",
    )
    action_patterns = (
        r"\bupload\b",
        r"\bimport\b",
        r"\bprocess\b",
        r"\breplace\b",
    )
    explicit_action_patterns = (
        r"\bupload\s+skybrush\b",
        r"\bimport\s+skybrush\b",
        r"\bupload\s+(?:a\s+)?drone show\b",
        r"\bimport\s+(?:a\s+)?drone show\b",
        r"\bskybrush\s+zip\b",
    )
    explicit_help_terms = (
        "upload skybrush",
        "import skybrush",
        "how to upload",
        "how to import",
    )
    if any(re.search(pattern, normalized) for pattern in explicit_action_patterns) and _has_any(normalized, show_terms):
        return True
    if _has_any(normalized, explicit_help_terms) and _has_any(normalized, show_terms):
        return True
    if _has_any(normalized, show_terms) and _has_any(normalized, help_terms) and any(re.search(pattern, normalized) for pattern in action_patterns):
        return True
    return False


def _looks_like_direct_execution_request(normalized: str) -> bool:
    if not normalized:
        return False
    action_terms = (
        "arm",
        "launch",
        "takeoff",
        "take off",
        "land",
        "rtl",
        "return to launch",
        "start mission",
        "deploy",
        "execute",
        "trigger",
        "command",
    )
    direct_terms = (
        "now",
        "please",
        "can you",
        "do it",
        "start",
        "run",
        "execute",
        "trigger",
        "send",
        "command",
    )
    conceptual_terms = (
        "what",
        "which",
        "explain",
        "difference",
        "different",
        "compare",
        "mode",
        "modes",
        "workflow",
        "guide",
        "doc",
        "docs",
        "link",
        "read about",
        "if i allowed",
        "what api",
        "what tool",
        "any",
        "active",
        "recent",
        "status",
        "statistics",
        "history",
        "tracker",
    )
    return _has_any(normalized, action_terms) and _has_any(normalized, direct_terms) and not _has_any(normalized, conceptual_terms)


def _looks_like_action_capability_question(normalized: str) -> bool:
    if _looks_like_direct_execution_request(normalized):
        return False
    has_action = _has_any(
        normalized,
        (
            "takeoff",
            "take off",
            "land",
            "rtl",
            "return",
            "move",
            "north",
            "south",
            "east",
            "west",
            "arm",
            "disarm",
            "send drone",
            "command drone",
            "mission action",
        ),
    )
    if not has_action:
        return False
    return _has_any(
        normalized,
        (
            "can you",
            "could you",
            "do you have",
            "what actions",
            "what action",
            "what api",
            "what apis",
            "which api",
            "which apis",
            "what tools",
            "which tools",
            "if i allow",
            "if allowed",
            "disable the circuit",
            "circuit breaker",
            "allow you",
        ),
    )


def _default_show_dirs() -> dict[str, str]:
    try:
        from params import Params

        sim_mode = bool(getattr(Params, "sim_mode", False))
    except Exception:
        sim_mode = False
    if sim_mode:
        return {
            "shapes_dir": str(REPO_ROOT / "shapes_sitl"),
            "skybrush_dir": str(REPO_ROOT / "shapes_sitl" / "swarm" / "skybrush"),
            "processed_dir": str(REPO_ROOT / "shapes_sitl" / "swarm" / "processed"),
        }
    return {
        "shapes_dir": str(REPO_ROOT / "shapes"),
        "skybrush_dir": str(REPO_ROOT / "shapes" / "swarm" / "skybrush"),
        "processed_dir": str(REPO_ROOT / "shapes" / "swarm" / "processed"),
    }


def _load_general_knowledge_config() -> Mapping[str, Any]:
    try:
        payload = yaml.safe_load(DEFAULT_GENERAL_KNOWLEDGE_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise AgentRuntimeError(f"Simurgh general knowledge config not found: {DEFAULT_GENERAL_KNOWLEDGE_CONFIG_PATH}") from exc
    except yaml.YAMLError as exc:
        raise AgentRuntimeError("Simurgh general knowledge config is invalid YAML") from exc
    if not isinstance(payload, Mapping):
        raise AgentRuntimeError("Simurgh general knowledge config root must be an object")
    if int(payload.get("version") or 0) != 1:
        raise AgentRuntimeError("unsupported Simurgh general knowledge config version")
    return payload


def _load_public_places_config() -> Mapping[str, Any]:
    try:
        payload = yaml.safe_load(DEFAULT_PUBLIC_PLACES_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise AgentRuntimeError(f"Simurgh public places config not found: {DEFAULT_PUBLIC_PLACES_CONFIG_PATH}") from exc
    except yaml.YAMLError as exc:
        raise AgentRuntimeError("Simurgh public places config is invalid YAML") from exc
    if not isinstance(payload, Mapping):
        raise AgentRuntimeError("Simurgh public places config root must be an object")
    if int(payload.get("version") or 0) != 1:
        raise AgentRuntimeError("unsupported Simurgh public places config version")
    return payload


def _matching_public_places(normalized: str, config: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_places = config.get("places")
    if not isinstance(raw_places, list):
        return []
    matches: list[tuple[int, dict[str, Any]]] = []
    for raw in raw_places:
        if not isinstance(raw, Mapping):
            continue
        aliases = tuple(str(alias or "").strip() for alias in raw.get("aliases") or () if str(alias or "").strip())
        if not aliases:
            continue
        positions = [_alias_position(normalized, alias) for alias in aliases]
        positions = [position for position in positions if position >= 0]
        if not positions:
            continue
        try:
            latitude = float(raw.get("latitude"))
            longitude = float(raw.get("longitude"))
        except (TypeError, ValueError):
            continue
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            continue
        matches.append(
            (
                min(positions),
                {
                    "id": str(raw.get("id") or raw.get("title") or "place").strip(),
                    "title": str(raw.get("title") or raw.get("id") or "Place").strip(),
                    "latitude": latitude,
                    "longitude": longitude,
                    "elevation_m": _finite_or_none(raw.get("elevation_m")),
                    "elevation_datum": str(raw.get("elevation_datum") or "").strip(),
                    "source_note": str(raw.get("source_note") or "").strip(),
                },
            )
        )
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for _position, place in sorted(matches, key=lambda item: item[0]):
        place_id = str(place.get("id") or "")
        if place_id in seen:
            continue
        seen.add(place_id)
        ordered.append(place)
    return ordered


def _alias_position(normalized: str, alias: str) -> int:
    marker = normalize_matching_text(alias)
    if not marker:
        return -1
    if re.fullmatch(r"[a-z0-9_-]+", marker):
        match = re.search(rf"\b{re.escape(marker)}\b", normalized)
        return match.start() if match else -1
    return normalized.find(marker)


def _great_circle_distance_km(first: Mapping[str, Any], second: Mapping[str, Any]) -> float:
    lat1 = math.radians(float(first["latitude"]))
    lon1 = math.radians(float(first["longitude"]))
    lat2 = math.radians(float(second["latitude"]))
    lon2 = math.radians(float(second["longitude"]))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return 6371.0088 * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def _extract_public_distance_km(normalized: str) -> float | None:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:km|kilometer|kilometers)\b", normalized)
    if match:
        return float(match.group(1))
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:mi|mile|miles)\b", normalized)
    if match:
        return float(match.group(1)) * 1.609344
    if _has_domain_signal(normalized, ("around", "circle", "loop", "radius", "orbit", "distance")):
        match = re.search(r"\b(\d+(?:\.\d+)?)\b", normalized)
        if match:
            return float(match.group(1))
    return None


def _matching_general_concept(normalized: str, knowledge: Mapping[str, Any]) -> tuple[str, str, tuple[str, ...]] | None:
    concepts = knowledge.get("concepts")
    if not isinstance(concepts, list):
        return None
    for raw in concepts:
        if not isinstance(raw, Mapping):
            continue
        aliases = tuple(str(alias or "").strip() for alias in raw.get("aliases") or () if str(alias or "").strip())
        if not _has_domain_signal(normalized, aliases):
            continue
        title = str(raw.get("title") or raw.get("id") or "General topic").strip()
        summary = str(raw.get("summary") or "").strip()
        notes = tuple(str(note).strip() for note in raw.get("operator_notes") or () if str(note).strip())
        if summary:
            return title, summary, notes
    return None


def _matching_external_question(normalized: str, knowledge: Mapping[str, Any]) -> tuple[str, str, tuple[str, ...]] | None:
    external_questions = knowledge.get("external_questions")
    if not isinstance(external_questions, Mapping):
        return None
    for key, raw in external_questions.items():
        if not isinstance(raw, Mapping):
            continue
        aliases = tuple(str(alias or "").strip() for alias in raw.get("aliases") or () if str(alias or "").strip())
        if not _has_domain_signal(normalized, aliases):
            continue
        title = str(key or "external question").replace("_", " ").title()
        summary = str(raw.get("summary") or "").strip()
        notes = tuple(str(note).strip() for note in raw.get("operator_notes") or () if str(note).strip())
        if summary:
            return title, summary, notes
    return None


def _normalize_text(value: str) -> str:
    return normalize_operator_query_text(value)


def _normalize_identity_text(value: str) -> str:
    """Normalize configured identities without semantic query rewrites."""

    normalized = normalize_matching_text(value)
    normalized = re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _has_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _extract_configured_drone_label(message: str, config: list[dict[str, Any]]) -> str:
    normalized = _normalize_identity_text(message)
    aliases: set[str] = set()
    for drone in config:
        for field in ("callsign", "role", "name", "label"):
            alias = _normalize_identity_text(str(drone.get(field) or ""))
            if alias:
                aliases.add(alias)
    for alias in sorted(aliases, key=len, reverse=True):
        compact_length = len(re.sub(r"\W+", "", alias, flags=re.UNICODE))
        if compact_length < 3 and normalized != alias:
            continue
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized, flags=re.UNICODE):
            return alias
    return ""


def _drone_matches_label(drone: Mapping[str, Any], label: str) -> bool:
    normalized_label = _normalize_identity_text(label)
    if not normalized_label:
        return False
    for field in ("callsign", "role", "name", "label"):
        value = _normalize_identity_text(str(drone.get(field) or ""))
        if value == normalized_label:
            return True
    return False


def _display_label(label: str) -> str:
    value = str(label or "").replace("-", " ").strip()
    return value.title() if value else "Selected"


def _next_numeric_id(values: Any) -> int:
    used = {_as_int(value) for value in values}
    used.discard(None)
    candidate = 1
    while candidate in used:
        candidate += 1
    return candidate


def _format_show_metrics_signal(metrics: Mapping[str, Any]) -> str:
    if not metrics.get("available"):
        return f"- Metrics snapshot: unavailable ({metrics.get('detail', 'no current cached metrics')})."
    payload = metrics.get("metrics") if isinstance(metrics.get("metrics"), Mapping) else {}
    basic = payload.get("basic_metrics") if isinstance(payload, Mapping) and isinstance(payload.get("basic_metrics"), Mapping) else {}
    drone_count = basic.get("drone_count", "unknown") if isinstance(basic, Mapping) else "unknown"
    duration = basic.get("duration_seconds") or basic.get("total_duration") if isinstance(basic, Mapping) else None
    duration_text = f", duration {_format_duration(_as_float(duration, 0.0))}" if duration else ""
    return f"- Metrics snapshot: available/current for {drone_count} drone(s){duration_text}."


def _format_show_validation_signal(validation: Mapping[str, Any]) -> str:
    if validation.get("available") is False:
        return f"- Validation: unavailable ({validation.get('detail', 'no validation snapshot')})."
    status = str(validation.get("validation_status") or "Unknown")
    issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
    issue_text = "no issues reported" if not issues else "; ".join(str(item) for item in issues[:3])
    return f"- Validation: {status}; {issue_text}."


def _format_show_safety_signal(safety: Mapping[str, Any]) -> str:
    if safety.get("available") is False:
        return f"- Safety report: unavailable ({safety.get('detail', 'no safety report')})."
    analysis = safety.get("safety_analysis") if isinstance(safety.get("safety_analysis"), Mapping) else {}
    status = str(analysis.get("safety_status") or "Unknown") if isinstance(analysis, Mapping) else "Unknown"
    warnings = analysis.get("collision_warnings_count", 0) if isinstance(analysis, Mapping) else 0
    return f"- Safety report: {status}; collision warnings {warnings}."


def _format_show_readiness_line(
    *,
    skybrush: Mapping[str, Any],
    metrics: Mapping[str, Any],
    safety: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> str:
    loaded = bool(skybrush.get("available"))
    metrics_ready = bool(metrics.get("available"))
    validation_ready = str(validation.get("validation_status") or "").upper() == "PASS"
    analysis = safety.get("safety_analysis") if isinstance(safety.get("safety_analysis"), Mapping) else {}
    safety_ready = str(analysis.get("safety_status") or "").upper() == "SAFE" if isinstance(analysis, Mapping) else False
    if loaded and metrics_ready and validation_ready and safety_ready:
        return "- Readiness: uploaded and current read-only checks are green; still require operator/package/field readiness confirmation before flight."
    missing = []
    if not loaded:
        missing.append("loaded SkyBrush package")
    if not metrics_ready:
        missing.append("current metrics snapshot")
    if not validation_ready:
        missing.append("PASS validation")
    if not safety_ready:
        missing.append("SAFE safety report")
    return "- Readiness: not proven fly-ready; missing or non-green signal(s): " + ", ".join(missing) + "."


def _extract_hw_id(message: str) -> int | None:
    normalized = _normalize_text(message)
    for pattern in (r"\bdrone\s*#?\s*(\d+)\b", r"\bhw[_\s-]*(?:id)?\s*#?\s*(\d+)\b"):
        match = re.search(pattern, normalized)
        if match:
            return _as_int(match.group(1))
    return None


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
        return dict(payload) if isinstance(payload, Mapping) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _fleet_candidate_list_payload(candidates: Any, *, runtime_mode_filter: str = "current") -> dict[str, Any]:
    rows = [_model_payload(item) for item in (candidates or [])]
    state_counts: dict[str, int] = {}
    runtime_counts: dict[str, int] = {}
    for item in rows:
        state = _candidate_state(item)
        runtime = str(item.get("runtime_mode") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
        runtime_counts[runtime] = runtime_counts.get(runtime, 0) + 1
    return {
        "candidates": rows,
        "total_candidates": len(rows),
        "state_counts": state_counts,
        "runtime_mode_counts": runtime_counts,
        "runtime_mode_filter": runtime_mode_filter,
        "timestamp": int(time.time() * 1000),
    }


def _candidate_state(candidate: Mapping[str, Any]) -> str:
    return str(_enum_or_value(candidate.get("registration_state")) or "unknown").strip() or "unknown"


def _candidate_heartbeat_status(candidate: Mapping[str, Any]) -> str:
    return str(candidate.get("heartbeat_status") or "unknown").strip().lower() or "unknown"


def _select_candidate_from_message(message: str, candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    normalized = _normalize_text(message)
    if not normalized:
        return {}
    for item in candidates:
        for field in ("candidate_id", "node_uuid", "hostname", "hw_id"):
            value = str(item.get(field) or "").strip()
            if _candidate_identifier_matches_message(normalized, field=field, value=value):
                return _copy_mapping(item)
    return {}


def _candidate_identifier_matches_message(normalized: str, *, field: str, value: str) -> bool:
    identifier = _normalize_text(value)
    if not identifier:
        return False
    if field == "hw_id":
        escaped = re.escape(identifier)
        return any(
            re.search(pattern, normalized)
            for pattern in (
                rf"\bhw\s*[_ -]?\s*id\s*[:#-]?\s*{escaped}\b",
                rf"\bhw\s*[:#-]?\s*{escaped}\b",
                rf"\bhardware\s*id\s*[:#-]?\s*{escaped}\b",
            )
        )
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(identifier)}(?![a-z0-9])", normalized))


def _candidate_summary_row(candidate: Mapping[str, Any]) -> tuple[str, str, str, str, str, str, str, str]:
    state = _readable_label(_candidate_state(candidate))
    conflict = _candidate_conflict_summary(candidate)
    pos_hint = _candidate_position_hint(candidate)
    hint = conflict if conflict != "-" else pos_hint
    return (
        _candidate_short_id(candidate),
        str(candidate.get("hw_id") or "unknown"),
        str(candidate.get("hostname") or candidate.get("node_uuid") or "unknown"),
        _candidate_ip_summary(candidate),
        str(candidate.get("runtime_mode") or "unknown"),
        state,
        _candidate_heartbeat_label(candidate),
        hint,
    )


def _candidate_short_id(candidate: Mapping[str, Any]) -> str:
    value = str(candidate.get("candidate_id") or "unknown").strip() or "unknown"
    if len(value) <= 18:
        return value
    return f"{value[:8]}...{value[-6:]}"


def _candidate_ip_summary(candidate: Mapping[str, Any]) -> str:
    primary = str(candidate.get("primary_control_ip") or candidate.get("netbird_ip") or "").strip()
    addresses = [str(item) for item in (candidate.get("ip_addresses") or []) if str(item).strip()]
    if primary:
        return primary
    if addresses:
        return ", ".join(addresses[:2])
    return "unknown"


def _candidate_heartbeat_label(candidate: Mapping[str, Any]) -> str:
    status = _candidate_heartbeat_status(candidate)
    age = _as_int(candidate.get("heartbeat_age_sec"))
    if age is None:
        return _readable_label(status)
    return f"{_readable_label(status)}; {_format_seconds_compact(float(age))} old"


def _candidate_conflict_summary(candidate: Mapping[str, Any]) -> str:
    reasons = [str(item) for item in (candidate.get("conflict_reasons") or []) if str(item).strip()]
    if not reasons:
        return "-"
    return "; ".join(_readable_label(item) for item in reasons[:3])


def _candidate_position_hint(candidate: Mapping[str, Any]) -> str:
    reported = str(candidate.get("reported_pos_id") or "").strip()
    detected = str(candidate.get("detected_pos_id") or "").strip()
    if reported and detected and reported != detected:
        return f"reported pos {reported}; detected pos {detected}"
    if reported:
        return f"reported pos {reported}"
    if detected:
        return f"detected pos {detected}"
    resolution = str(candidate.get("resolution") or "").strip()
    return _readable_label(resolution) if resolution else "-"


def _candidate_conflict_line(candidate: Mapping[str, Any]) -> str:
    return f"{_candidate_short_id(candidate)}: {_candidate_conflict_summary(candidate)}. Verify identity/IP/pos_id before any accept or replace action."


def _candidate_presence_line(candidate: Mapping[str, Any]) -> str:
    return f"{_candidate_short_id(candidate)} heartbeat is {_candidate_heartbeat_label(candidate)}; do not enroll it for field use until the node is reachable and identity is confirmed."


def _readable_label(value: Any) -> str:
    text = str(_enum_or_value(value) or "unknown").strip() or "unknown"
    return text.replace("_", " ")


def _select_quickscout_mission(message: str, missions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not missions:
        return {}
    normalized = _normalize_text(message)
    for item in missions:
        mission_id = str(item.get("mission_id") or "").strip()
        label = str(item.get("mission_label") or "").strip()
        if mission_id and _normalize_text(mission_id) in normalized:
            return _copy_mapping(item)
        if label and _normalize_text(label) in normalized:
            return _copy_mapping(item)
    return _copy_mapping(missions[0])


def _quickscout_readiness_label(
    launchable: bool,
    requires_revalidation: bool,
    state: str,
    *,
    quality_notes: Sequence[str] | None = None,
) -> str:
    state_lower = _normalize_text(state)
    if state_lower in {"completed", "aborted", "failed", "cancelled", "canceled"}:
        return f"not launchable; mission is {state_lower}"
    if not launchable:
        return "not launchable until package blockers are cleared"
    if quality_notes and requires_revalidation:
        return "package exists, but not field-ready until stale/implausible mission evidence is reviewed; live launch revalidation required before launch"
    if quality_notes:
        return "package exists, but not field-ready until stale/implausible mission evidence is reviewed"
    if requires_revalidation:
        return "planned package exists; live launch revalidation required before launch"
    return "planned package exists; still requires human field readiness review before launch"


def _quickscout_quality_notes(*, updated_at: float, area_sq_m: float, estimated_duration_s: float) -> list[str]:
    notes: list[str] = []
    age_s = max(0.0, time.time() - updated_at) if updated_at > 0 else None
    if age_s is None:
        notes.append("Package timestamp is missing; reopen/revalidate the mission before field use.")
    elif age_s > QUICKSCOUT_FIELD_READY_STALE_SECONDS:
        notes.append(
            f"Package is {_format_seconds_compact(age_s)} old; treat it as stale for field launch readiness and revalidate live positions."
        )
    if area_sq_m > QUICKSCOUT_IMPLAUSIBLE_AREA_SQ_M:
        notes.append(
            "Planned area is unusually large for a QuickScout field package; check the mission bounds, units, and origin before using it."
        )
    if estimated_duration_s > QUICKSCOUT_IMPLAUSIBLE_DURATION_S:
        notes.append(
            "Estimated coverage time is unusually long; check the coverage planner inputs, speed assumptions, and mission bounds."
        )
    return notes


def _quickscout_drone_scope(summary: Mapping[str, Any], status: Mapping[str, Any]) -> str:
    drone_count = _as_int(summary.get("drone_count"))
    drone_states = status.get("drone_states") if isinstance(status, Mapping) else None
    if drone_count is None and isinstance(drone_states, Mapping):
        drone_count = len(drone_states)
    pos_ids = summary.get("pos_ids")
    pos_label = ""
    if isinstance(pos_ids, list) and pos_ids:
        pos_label = "; positions " + ", ".join(str(item) for item in pos_ids[:8])
    return f"{drone_count or 0} drone(s){pos_label}"


def _quickscout_drone_state_rows(status: Mapping[str, Any]) -> list[tuple[str, str, str, str, str, str]]:
    drone_states = status.get("drone_states") if isinstance(status, Mapping) else None
    if not isinstance(drone_states, Mapping):
        return []
    rows: list[tuple[str, str, str, str, str, str]] = []
    for hw_id, raw_state in drone_states.items():
        item = _model_payload(raw_state)
        coverage_percent = _as_float(item.get("coverage_percent"), 0.0)
        rows.append(
            (
                f"hw {hw_id}",
                _readable_label(item.get("state")),
                f"{coverage_percent:.1f}%",
                _format_distance_m(item.get("distance_covered_m")),
                _format_duration(_as_float(item.get("estimated_remaining_s"), 0.0)),
                str(item.get("status_note") or "-"),
            )
        )
    return sorted(rows, key=lambda row: _natural_key(row[0].replace("hw ", "")))


def _format_area_sq_m(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} sq km"
    return f"{value:.0f} sq m"


def _format_quickscout_area(value: float) -> str:
    label = _format_area_sq_m(value)
    if value > QUICKSCOUT_IMPLAUSIBLE_AREA_SQ_M:
        return f"{label} (check bounds/origin)"
    return label


def _format_quickscout_duration(seconds: float) -> str:
    label = _format_duration(seconds)
    if seconds > QUICKSCOUT_IMPLAUSIBLE_DURATION_S:
        return f"{label} (check planner inputs)"
    return label


def _format_age_from_epoch(value: Any) -> str:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return "unknown age"
    if not math.isfinite(timestamp) or timestamp <= 0:
        return "unknown age"
    if timestamp > 10_000_000_000:
        timestamp /= 1000.0
    return _format_seconds_compact(max(0.0, time.time() - timestamp))


def _format_seconds_compact(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} s"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


def _format_distance_m(value: Any) -> str:
    meters = _as_float(value, 0.0)
    if meters >= 1000:
        return f"{meters / 1000:.2f} km"
    return f"{meters:.0f} m"


def _format_epoch_utc(value: Any) -> str:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if not math.isfinite(timestamp) or timestamp <= 0:
        return "unknown"
    if timestamp > 10_000_000_000:
        timestamp /= 1000.0
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _short_commit(value: Any) -> str:
    commit = str(value or "").strip()
    if not commit or commit == "unknown":
        return "unknown"
    return commit[:8]


def _git_status_label(gcs_status: Mapping[str, Any]) -> str:
    changes = _safe_string_list(gcs_status.get("uncommitted_changes"))
    raw_status = str(_enum_or_value(gcs_status.get("status") or ("dirty" if changes else "unknown"))).strip() or "unknown"
    parts = [raw_status]
    ahead = _as_int(gcs_status.get("commits_ahead")) or 0
    behind = _as_int(gcs_status.get("commits_behind")) or 0
    if ahead:
        parts.append(f"{ahead} ahead")
    if behind:
        parts.append(f"{behind} behind")
    return ", ".join(parts)


def _git_node_rows(drone_status: Mapping[str, Any]) -> list[tuple[str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str]] = []
    for key, raw_item in drone_status.items():
        item = _model_payload(raw_item)
        if not item:
            continue
        hw_id = str(item.get("hw_id") or key)
        pos_id = str(item.get("pos_id") or hw_id)
        status = str(_enum_or_value(item.get("status") or "unknown"))
        sync = "synced" if bool(item.get("in_sync_with_gcs")) else "needs review"
        uncommitted_count = len(_safe_string_list(item.get("uncommitted_changes")))
        if uncommitted_count:
            status = f"{status} ({uncommitted_count} dirty)"
        rows.append(
            (
                f"pos {pos_id} / hw {hw_id}",
                status,
                sync,
                str(item.get("branch") or "unknown"),
                _short_commit(item.get("commit")),
                str(item.get("git_auth_health_status") or "unknown"),
            )
        )
    return sorted(rows, key=lambda row: (_as_int(row[0].split("/ hw ")[-1]) or 0, row[0]))


def _sidecar_summary_rows(tables: Sequence[tuple[str, Mapping[str, Any]]]) -> list[tuple[str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str]] = []
    for sidecar, table in tables:
        raw_rows = table.get("rows") if isinstance(table, Mapping) else None
        node_rows = [row for row in (raw_rows or []) if isinstance(row, Mapping)]
        if not node_rows:
            continue
        online = sum(1 for row in node_rows if _sidecar_presence_label(row).startswith("online"))
        modes = _counted_values(row.get("mode") for row in node_rows)
        drift = _counted_values(row.get("drift_state") for row in node_rows)
        baseline = _copy_mapping(table.get("baseline"))
        baseline_label = "missing"
        if baseline.get("present"):
            baseline_label = f"{baseline.get('profile_count', 0)} profile/endpoints; hash {baseline.get('hash') or '-'}"
        rows.append(
            (
                sidecar,
                str(len(node_rows)),
                f"{online}/{len(node_rows)}",
                modes or "unknown",
                drift or "unknown",
                baseline_label,
            )
        )
    return rows


def _sidecar_node_rows(tables: Sequence[tuple[str, Mapping[str, Any]]]) -> list[tuple[str, str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str, str]] = []
    for sidecar, table in tables:
        raw_rows = table.get("rows") if isinstance(table, Mapping) else None
        for row in [item for item in (raw_rows or []) if isinstance(item, Mapping)]:
            node = _sidecar_node_label(row)
            rows.append(
                (
                    node,
                    sidecar,
                    _sidecar_presence_label(row),
                    str(row.get("service_state") or "unknown"),
                    str(row.get("mode") or "unknown"),
                    str(row.get("drift_state") or "unknown"),
                    _sidecar_dashboard_label(row),
                )
            )
    rows.sort(key=lambda item: (_natural_key(item[0]), item[1]))
    return rows


def _sidecar_node_label(row: Mapping[str, Any]) -> str:
    hw_id = str(row.get("hw_id") or "?").strip()
    pos_id = str(row.get("pos_id") or "").strip()
    if pos_id and pos_id != hw_id:
        return f"hw {hw_id} / pos {pos_id}"
    return f"hw {hw_id}"


def _sidecar_presence_label(row: Mapping[str, Any]) -> str:
    presence = _copy_mapping(row.get("presence"))
    state = str(presence.get("state") or "unknown").strip() or "unknown"
    if presence.get("fresh") is True and state != "online":
        state = f"online/{state}"
    age = presence.get("age_seconds")
    if age not in (None, ""):
        return f"{state} ({age}s)"
    return state


def _sidecar_dashboard_label(row: Mapping[str, Any]) -> str:
    dashboard = _copy_mapping(row.get("dashboard"))
    url = str(dashboard.get("url") or "").strip()
    if url:
        return url
    port = dashboard.get("port")
    access = str(dashboard.get("access_mode") or "not_reported").strip() or "not_reported"
    if port not in (None, ""):
        return f"port {port}; access {access}"
    return access


def _counted_values(values: Any) -> str:
    counts: dict[str, int] = {}
    for raw in values:
        value = str(raw or "unknown").strip() or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return ", ".join(f"{key} x{counts[key]}" for key in sorted(counts, key=_natural_key))


def _network_detail_count(details: Any) -> int:
    if isinstance(details, Mapping):
        for key in ("drones", "nodes", "items", "rows", "network"):
            value = details.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return len(value)
        return len(details)
    if isinstance(details, Sequence) and not isinstance(details, (str, bytes, bytearray)):
        return len(details)
    return 0


def _sidecar_runtime_status(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping) or not payload:
        return "status unavailable"
    parts: list[str] = []
    for key, label in (
        ("service_status", "service"),
        ("dashboard_service_status", "dashboard"),
        ("reconcile_status", "reconcile"),
        ("management_mode", "mode"),
        ("dashboard_access_mode", "access"),
    ):
        value = payload.get(key)
        if value not in (None, ""):
            parts.append(f"{label}: {value}")
    return "; ".join(parts[:5]) or "configured"


def _command_record_public_summary(command: Any) -> dict[str, Any]:
    if isinstance(command, Mapping):
        get_value = command.get
    else:
        def get_value(key, default=None):
            return getattr(command, key, default)
    params = get_value("params", {})
    params = params if isinstance(params, Mapping) else {}
    return {
        "command_id": _enum_or_value(get_value("command_id", "")),
        "mission_type": _enum_or_value(get_value("mission_type", "")),
        "mission_name": _enum_or_value(get_value("mission_name", "")),
        "phase": _enum_or_value(get_value("phase", "")),
        "status": _enum_or_value(get_value("status", "")),
        "outcome": _enum_or_value(get_value("outcome", "")),
        "target_drones": list(get_value("target_drones", []) or []),
        "created_at": get_value("created_at"),
        "submitted_at": get_value("submitted_at"),
        "execution_started_at": get_value("execution_started_at"),
        "completed_at": get_value("completed_at"),
        "updated_at": get_value("updated_at"),
        "operator_label": str(params.get("operator_label") or "").strip(),
    }


def _enum_or_value(value: Any) -> Any:
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def _as_str(value: Any) -> str:
    return str(value).strip()


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _maybe_int_key(value: str) -> int | str:
    parsed = _as_int(value)
    return parsed if parsed is not None else value


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    parsed = _as_int(os.getenv(name))
    return default if parsed is None else parsed


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default


def _remaining_evidence_timeout(
    deadline: float,
    requested_timeout: float,
) -> float | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    return max(0.05, min(float(requested_timeout), remaining))


def _fmt_m(value: Any) -> str:
    return f"{_as_float(value):.2f}"


def _natural_key(value: str) -> tuple[int, str]:
    parsed = _as_int(value)
    return (parsed if parsed is not None else 10**9, value)


def _locked_mapping_snapshot(data: Any, lock: Any = None) -> dict[Any, dict[str, Any]]:
    if not isinstance(data, Mapping):
        return {}
    if lock is not None:
        with lock:
            return {key: _copy_mapping(value) for key, value in data.items()}
    return {key: _copy_mapping(value) for key, value in data.items()}


def _locked_scalar_snapshot(data: Any, lock: Any = None) -> dict[Any, Any]:
    if not isinstance(data, Mapping):
        return {}
    if lock is not None:
        with lock:
            return dict(data)
    return dict(data)


def _collect_tree_members(root: int, children: dict[int, list[int]]) -> list[int]:
    members = [root]
    for child in sorted(children.get(root, [])):
        members.extend(_collect_tree_members(child, children))
    return members


def _pairwise_distance_lines(positions: dict[int, dict[str, Any]]) -> list[str]:
    hw_ids = sorted(positions)
    lines: list[str] = []
    for idx, left in enumerate(hw_ids):
        for right in hw_ids[idx + 1 :]:
            left_pos = positions[left]
            right_pos = positions[right]
            distance = math.hypot(
                _as_float(left_pos.get("x")) - _as_float(right_pos.get("x")),
                _as_float(left_pos.get("y")) - _as_float(right_pos.get("y")),
            )
            lines.append(f"- hw {left} to hw {right}: {distance:.2f} m")
            if len(lines) >= 12:
                lines.append("- Additional pairwise distances omitted for readability.")
                return lines
    return lines


def _format_duration(seconds: float) -> str:
    if seconds <= 0:
        return "0 s"
    minutes = int(seconds // 60)
    remaining = seconds - (minutes * 60)
    if minutes:
        return f"{minutes} min {remaining:.1f} s"
    return f"{remaining:.1f} s"

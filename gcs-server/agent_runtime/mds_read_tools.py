"""Curated read-only MDS context tools for Simurgh assistant turns.

The functions in this module do not call drone-side APIs and do not submit GCS
commands. They summarize already-owned GCS state for the chat assistant and the
future MCP tool adapter.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from fastapi import HTTPException

from request_logging import is_routine_auth_noise_path

from .answer_composer import AnswerComposer
from .models import AgentRuntimeError, utc_now
from .query_adaptation import normalize_matching_text, normalize_operator_query_text
from .query_understanding import build_assistant_query_plan


REPO_ROOT = Path(__file__).resolve().parents[2]
READ_TOOL_PROVIDER = "mds-tools"
READ_TOOL_MODEL = "local-read-only"
READ_TOOL_ADAPTER_VERSION = "mds-read-tools-v1"
DEFAULT_OPENAI_CHAT_MODELS = ("gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano")
DEFAULT_OPENAI_API_KEY_FILE = Path("/etc/mds/secrets/openai_api_key")
DEFAULT_GENERAL_KNOWLEDGE_CONFIG_PATH = REPO_ROOT / "config" / "agent_general_knowledge.yaml"
DEFAULT_PUBLIC_PLACES_CONFIG_PATH = REPO_ROOT / "config" / "agent_public_places.yaml"
FALLBACK_LOG_STALE_GRACE_SECONDS = 3600
LATEST_SESSION_GROUP_SECONDS = 15
READ_CONVERSATION_TOPICS = frozenset(
    {
        "capabilities",
        "docs",
        "drone_show",
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
READ_RESPONSE_MODES = frozenset({"status", "interpret", "workflow", "compare", "capability", "clarify"})
READ_ONLY_ACTION_POSTURE = "read-only-local; no action, upload, config mutation, or drone-local API execution"

# Trace-only expected evidence IDs. Execution still records the actual tool IDs
# returned by the selected local read-only answer.
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
    "docs_help": ("mds.docs.search", "mds.docs.chunk.read"),
    "environment_summary": ("mds.system.env_registry.read", "mds.system.env_gcs.read"),
    "fleet_connectivity": ("mds.fleet.heartbeats.read", "mds.fleet.telemetry.read", "mds.fleet.network_status.read"),
    "fleet_summary": ("mds.config.fleet.read", "mds.config.positions.read", "mds.config.swarm.read"),
    "general_knowledge": ("simurgh.general_knowledge.read",),
    "git_status_summary": ("mds.git.status.read",),
    "mission_mode_comparison": (
        "simurgh.general_knowledge.read",
        "mds.docs.search",
        "mds.docs.chunk.read",
    ),
    "operator_help": ("mds.docs.search", "mds.docs.chunk.read"),
    "origin_status": ("mds.origin.read", "mds.navigation.global_origin.read", "mds.config.positions.read"),
    "public_geography": ("simurgh.public_places.read", "simurgh.geodesy.calculate"),
    "px4_params_summary": ("mds.px4_params.policy.read", "mds.px4_params.profiles.read"),
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
    "health",
    "failsafe",
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
    "health",
    "failsafe",
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

    @property
    def turn_id(self) -> str:
        return f"turn-{uuid.uuid4().hex}"


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
    if _looks_like_weather_question(normalized) or _looks_like_general_knowledge_question(normalized):
        return "general_knowledge"
    if _looks_like_public_geography_question(normalized):
        return "public_geography"
    if _looks_like_px4_params_question(normalized):
        return "px4_params_summary"
    if _looks_like_autopilot_support_question(normalized):
        return "autopilot_support"
    if _looks_like_non_mds_general_question(normalized):
        return None

    if topic == "logs" and _looks_like_contextual_log_followup(normalized):
        return "backend_log_summary"
    if topic == "drone_show" and _looks_like_contextual_show_followup(normalized):
        return "show_summary"
    contextual_intent = _intent_from_contextual_followup(normalized, topic)
    if contextual_intent:
        return contextual_intent

    if _looks_like_action_capability_question(normalized):
        return "action_capability"
    if _looks_like_registry_domain_tool_question(normalized, topic=topic):
        return "registry_domain_tool_summary"
    if _looks_like_command_summary_question(normalized):
        return "command_summary"
    if _looks_like_git_status_question(normalized):
        return "git_status_summary"
    if _looks_like_origin_status_question(normalized):
        return "origin_status"
    if _looks_like_sidecar_status_question(normalized):
        return "sidecar_status"
    if _looks_like_system_status_question(normalized):
        return "system_status"
    if _looks_like_environment_summary_question(normalized):
        return "environment_summary"
    if _has_any(normalized, ("log", "logs", "warning", "warnings", "error", "errors", "backend")) and _has_any(
        normalized,
        ("check", "see", "show", "what", "which", "any", "have", "list", "summary"),
    ):
        return "backend_log_summary"
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
    if _looks_like_live_fleet_state_question(normalized):
        return "fleet_connectivity"
    if _looks_like_swarm_readiness_question(normalized):
        return "swarm_readiness"
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
) -> MdsReadToolAnswer | None:
    """Answer an MDS prompt using only local read-only GCS context."""

    plan = build_mds_read_only_plan(message, conversation_topic=conversation_topic)
    intent = plan.intent
    if intent is None:
        return None

    response_mode = plan.response_mode
    tools = MdsReadOnlyTools(deps=deps)
    if intent == "fleet_summary":
        return tools.fleet_summary(message)
    if intent == "fleet_connectivity":
        return tools.fleet_connectivity(message=message)
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
    if intent == "swarm_readiness":
        return tools.swarm_readiness(message)
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
    if intent == "action_capability":
        return tools.action_capability()
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
        return tools.command_summary(message=message)
    if intent == "git_status_summary":
        return tools.git_status_summary(message=message)
    if intent == "general_knowledge":
        return tools.general_knowledge(message)
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
    if normalized_intent in {"fleet_summary", "fleet_connectivity"}:
        return "fleet"
    if normalized_intent in {"swarm_readiness", "swarm_topology", "operator_help", "mission_mode_comparison"}:
        return "swarm"
    if normalized_intent == "sitl_help":
        return "sitl"
    if normalized_intent in {"board_setup_help", "companion_setup_help", "add_drone_workflow"}:
        return "setup"
    if normalized_intent == "backend_log_summary":
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
    if normalized_intent == "git_status_summary":
        return "setup"
    if normalized_intent == "capability_catalog":
        return "capabilities"
    if normalized_intent == "registry_domain_tool_summary":
        return "capabilities"
    if normalized_intent == "public_geography":
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
    return MdsReadOnlyPlan(
        intent=intent,
        response_mode=response_mode if response_mode in READ_RESPONSE_MODES else "status",
        topic=topic,
        query_domain=query_plan.domain,
        confidence=query_plan.confidence,
        unclear=query_plan.unclear,
        reason=query_plan.reason,
        tool_ids=LOCAL_INTENT_TOOL_IDS.get(str(intent or ""), ()),
        missing_arguments=(),
        execution_layer=execution_layer,
        safety_posture=READ_ONLY_ACTION_POSTURE,
    )


SAFE_BLOCKED_TERM_READ_ONLY_INTENTS = frozenset(
    {
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
            "setup",
        ),
    )


class MdsReadOnlyTools:
    """Small curated GCS read surface for Simurgh chat answers."""

    def __init__(self, *, deps: Any | None = None):
        self.deps = deps

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
            composer.line("This is read-only GCS configuration; no drone command was sent.")
            return self._answer("fleet_summary", composer.render(), ("mds.config.fleet.read",))
        if specific_label and not rows:
            composer.line(f"I do not see a configured drone matching '{specific_label}' in the current GCS fleet configuration.")
            composer.blank()
            composer.line(f"Configured drone count: {len(config)}.")
            composer.line("This is read-only GCS configuration; no drone command was sent.")
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
        composer.line("This is a read-only dashboard answer; no action was executed.")
        return self._answer(
            "fleet_summary",
            composer.render(),
            ("mds.config.fleet.read", "mds.config.positions.read", "mds.config.swarm.read"),
        )

    def fleet_connectivity(self, message: str = "") -> MdsReadToolAnswer:
        config = self._fleet_config()
        heartbeats = self._heartbeat_snapshot()
        telemetry = self._telemetry_snapshot()
        telemetry_success_times = self._telemetry_success_times()
        normalized_message = _normalize_text(message)
        wants_position = _wants_fleet_position_details(normalized_message)
        wants_health = _wants_fleet_health_details(normalized_message)

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
        rows: list[tuple[str, ...]] = []
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
                country = _country_from_coordinates(lat, lon) if lat is not None and lon is not None else "unavailable"
                position = f"lat {_fmt_coordinate(lat)}, lon {_fmt_coordinate(lon)}, alt {_fmt_altitude_m(alt)}, {country}"
                rows.append(
                    (
                        f"Drone {hw_id}",
                        str(state),
                        gps_label,
                        position,
                        health["battery"],
                        health["armed"],
                        health["ready"],
                        health["mode"],
                        health["system"],
                        str(detail),
                    )
                )
            elif wants_position:
                lat, lon, alt, gps_label = _fleet_position_summary(telemetry_row)
                country = _country_from_coordinates(lat, lon) if lat is not None and lon is not None else "unavailable"
                rows.append(
                    (
                        f"Drone {hw_id}",
                        str(state),
                        gps_label,
                        _fmt_coordinate(lat),
                        _fmt_coordinate(lon),
                        _fmt_altitude_m(alt),
                        country,
                        str(detail),
                    )
                )
            elif wants_health:
                health = _fleet_health_summary(telemetry_row)
                rows.append(
                    (
                        f"Drone {hw_id}",
                        str(state),
                        health["battery"],
                        health["armed"],
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
        if not all_hw_ids:
            composer.line("Connectivity from GCS state: no configured drone IDs, heartbeats, or telemetry rows are visible to this GCS runtime right now.")
            if wants_position:
                composer.line(
                    "GPS, Latitude, Longitude, and Altitude evidence are unavailable because there is no readable fleet row, heartbeat row, or telemetry row in this runtime snapshot."
                )
            composer.line("This is a read-only presence check; no drone command was sent.")
        else:
            composer.line(f"Connectivity from GCS state: {live_count}/{len(all_hw_ids)} drone(s) currently look live.")
            if wants_position and wants_health:
                composer.blank().table(
                    ("Drone", "Presence", "GPS", "Position", "Battery", "Armed", "Ready", "Mode", "System", "Evidence"),
                    rows,
                )
                composer.blank().line(
                    "Coordinates, GPS, battery, arming, mode, and system status come from the latest GCS telemetry snapshot. `unavailable` means this runtime has no current value for that field."
                )
            elif wants_position:
                composer.blank().table(
                    ("Drone", "Presence", "GPS", "Latitude", "Longitude", "Altitude", "Country", "Evidence"),
                    rows,
                )
                composer.blank().line(
                    "Coordinates and GPS status come from the latest GCS telemetry snapshot. `unavailable` means this runtime does not currently have a valid global-position sample for that drone."
                )
            elif wants_health:
                composer.blank().table(
                    ("Drone", "Presence", "Battery", "Armed", "Ready", "Mode", "System", "GPS", "Evidence"),
                    rows,
                )
                composer.blank().line(
                    "Battery, arming, readiness, flight mode, system status, and GPS evidence come from the latest GCS telemetry snapshot. Treat missing values as unknown, not healthy."
                )
            else:
                composer.blank().table(("Drone", "Role", "Presence", "IP", "Evidence"), rows)
            composer.blank().line("Use this as operator presence evidence only; it is not a readiness-to-fly decision.")
            composer.line("No drone command was sent.")
        return self._answer(
            "fleet_connectivity",
            composer.render(),
            ("mds.fleet.heartbeats.read", "mds.fleet.telemetry.read", "mds.fleet.network_status.read"),
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
        composer.line("Smart Swarm readiness snapshot from read-only GCS evidence:")
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
        composer.line("This is a read-only readiness advisory; no config write, mission action, or drone command was sent.")
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
        composer.line("This is read-only file/config inspection; no show was deployed or commanded.")
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
        composer.line("This is read-only interpretation; no show was deployed, launched, or commanded.")
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
                "I can explain MDS workflows and inspect read-only GCS state from this chat.",
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
                preview = ["No read-only GCS tools are currently allowed by Simurgh policy."]

            registry_path = registry.path
            try:
                registry_label = registry_path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                registry_label = registry_path.as_posix()

            composer = AnswerComposer()
            composer.line("Simurgh capabilities are driven by one curated registry and policy layer, not hardcoded chat-only tools.")
            composer.line(f"MCP endpoint: {'enabled' if policy.mcp_enabled else 'disabled'} at `/api/v1/simurgh/mcp`.")
            composer.blank()
            composer.table(
                ("Capability surface", "Current value"),
                (
                    ("Registry source", f"`{registry_label}`"),
                    ("MCP endpoint", f"{'enabled' if policy.mcp_enabled else 'disabled'} at `/api/v1/simurgh/mcp`"),
                    ("Read-only GCS tools allowed", str(len(read_only_menu))),
                    ("Guarded/future candidates", str(guarded)),
                    ("Explicitly excluded dangerous/admin/drone-local tools", str(excluded)),
                ),
            )
            composer.blank().line("Current safe menu preview:")
            composer.bullets(preview)
            composer.blank()
            composer.line("External clients discover the MCP menu with `tools/list` and call approved read-only tools with `tools/call` when MCP is enabled and bearer auth is valid.")
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

            registry_path = summary.registry.path
            try:
                registry_label = registry_path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                registry_label = registry_path.as_posix()

            composer = AnswerComposer()
            domain_label = _registry_domain_summary_label(selected_domains, fallback=plan.domain)
            composer.line(f"Registry-backed read-only capability summary for {domain_label}:")
            composer.line(f"Source: `{registry_label}` filtered by current Simurgh policy for the dashboard/agent channel.")
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
                    composer.blank().line(f"{len(tools) - 12} more matching read-only tools are available through the same registry/MCP menu.")
            else:
                composer.line("No policy-allowed read-only registry tools matched that domain yet.")
            composer.blank()
            composer.line("How this is used: Dashboard chat and external MCP clients discover the same approved menu; external clients call it with `tools/list` and `tools/call` when MCP auth is valid.")
            composer.line("This answer only describes the approved capability surface; it did not call a route, mutate config, upload assets, or command a drone.")
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
            composer.line("Fleet Ops sidecar status from read-only GCS state:")
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
            composer.line("Read-only meaning: Simurgh can inspect sidecar state, dashboards, modes, drift, profiles/endpoints, and job results. Profile apply/reconcile/delete remains a human-controlled Fleet Ops action.")
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
            composer.line("PX4 parameter support in MDS is read-only/advisory from Simurgh right now.")
            composer.blank().table(
                ("Capability", "Current value"),
                (
                    ("Profiles available", str(profiles.get("total_profiles", len(profile_rows)))),
                    ("Supports MDS profiles", str(policy.get("supports_mds_profiles", True))),
                    ("Snapshot route", "available through GCS API / PX4 Parameters page"),
                    ("Patch/apply", "not executable by Simurgh in this read-only slice"),
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
        composer.line("This is read-only configuration inspection; no origin, launch position, route, or drone command was changed.")
        return self._answer(
            "origin_status",
            composer.render(),
            ("mds.origin.read", "mds.navigation.global_origin.read", "mds.config.positions.read"),
        )

    def command_summary(self, message: str = "") -> MdsReadToolAnswer:
        snapshot = self._command_tracker_snapshot()
        composer = AnswerComposer()
        composer.line("GCS command tracker summary:")
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
                    ("Total commands since tracker start", str(stats.get("total_commands", 0))),
                    ("Successful", str(stats.get("successful_commands", 0))),
                    ("Failed", str(stats.get("failed_commands", 0))),
                    ("Partial", str(stats.get("partial_commands", 0))),
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
        composer.blank().line("Open the command/audit UI for full command details. This is read-only tracker inspection; no command was submitted, retried, or cancelled.")
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
        composer.line("GCS repository and fleet sync status from read-only git evidence:")
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
        composer.line("This is read-only repository inspection; no git commit, push, pull, node sync, config write, or drone command was executed.")
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
            else:
                composer.bullets((f"No WARNING/ERROR/CRITICAL entries were found in the {window_phrase}.",))

            composer.blank().line("Open [Logs](/logs) for the full live stream and filters.")
            composer.line("Docs/API: " + _doc_link("logging guide", "mds.logging_system") + ", `GET /api/logs/sources`, `GET /api/logs/sessions`, `GET /api/logs/sessions/{session_id}`.")
            composer.line("This is read-only log inspection; no drone command was sent.")
            content = composer.render()
        return self._answer(
            "backend_log_summary",
            content,
            ("mds.logs.gcs.read",),
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
        if not events:
            lines.append("- Short answer: I do not see backend warning/error evidence in that window, so this log view does not point to a current GCS problem.")
            lines.append(f"- I do not see WARNING/ERROR/CRITICAL entries in the {window_phrase}.")
            lines.append("- Meaning: there is no backend-warning evidence here to explain; use the Logs page if the operator saw a different time window.")
        else:
            lines.extend(self._backend_log_direct_verdict_lines(events))
            lines.extend(self._backend_log_operator_read_lines(events))
            lines.append("- How to read this: treat the pattern and affected routes as the signal, not each repeated line independently. Repeated identical warnings usually mean one client is polling/failing the same protected endpoint.")
            lines.append("- Next operator check: open [Logs](/logs), filter the same time window, and verify whether the warning continues after refreshing/re-authenticating the dashboard client.")
        lines.append("Docs/API: " + _doc_link("logging guide", "mds.logging_system") + ", `GET /api/logs/sources`, `GET /api/logs/sessions`, `GET /api/logs/sessions/{session_id}`.")
        lines.append("This is read-only log interpretation; no drone command was sent.")
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

    def action_capability(self) -> MdsReadToolAnswer:
        content = "\n".join(
            [
                "I cannot execute that action in this Simurgh release, and disabling the circuit breaker alone would not make it callable.",
                "The raw GCS command route, direct drone API, MAVSDK command path, and mission mutation APIs are deliberately excluded from Simurgh/MCP tools today.",
                "For a future approved action wrapper, the safe plan would need typed steps such as takeoff(5 m), hold(10 s), relative move north(6 m), then RTL/return, plus live telemetry freshness, preflight/readiness checks, geofence/airspace checks, operator approval, audit logging, and SITL validation before any real flight use.",
                "Current Simurgh can answer read-only readiness/config/log/docs questions and explain which future wrapper would be needed; it will not command the aircraft.",
                "Relevant docs: " + _doc_link("Simurgh guide", "simurgh.operator_guide") + ", " + _doc_link("safety policy", "simurgh.safety_policy") + ", " + _doc_link("tool usage guidelines", "simurgh.tool_usage") + ", and " + _doc_link("GCS API surface", "mds.gcs_api") + ".",
                "No drone command was sent.",
            ]
        )
        return self._answer("action_capability", content, ("mds.simurgh.safety_policy.read", "mds.simurgh.tool_policy.read"))

    def _recent_warning_events(self, *, window_seconds: int | None = None) -> tuple[list[dict[str, Any]], list[str]]:
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
        if window_seconds:
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
            commands = list(getattr(tracker, "_commands", {}).values())
            stats = dict(getattr(tracker, "_stats", {}) or {})
        except Exception as exc:
            return {"available": False, "error": str(exc)}

        recent = [_command_record_public_summary(command) for command in commands[-20:]][::-1]
        active = [item for item in recent if str(item.get("phase") or "").lower() != "terminal"]
        return {
            "available": True,
            "stats": stats,
            "active": active,
            "recent": recent,
        }

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
                loader = lambda: load_saved_metrics_if_current(
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
        return MdsReadToolAnswer(
            intent=intent,
            content=content,
            tool_ids=tool_ids,
            safety_notes=safety_notes or (
                "Answered by local read-only MDS/GCS context tools.",
                "No direct drone API, MAVSDK command, raw GCS command, or mission mutation was exposed.",
                f"Tool intent: {intent}.",
                f"Response mode: {normalized_mode}.",
            ),
            response_mode=normalized_mode,
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
        if _looks_like_live_fleet_state_question(normalized):
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
        if _has_any(normalized, ("companion", "raspberry", "cm4", "pi", "script", "bootstrap", "install")):
            return "companion_setup_help"
        if _has_any(normalized, ("third", "drone 3", "new drone", "add", "another drone")):
            return "add_drone_workflow"
        if _has_any(normalized, ("board", "env", "environment", "key", "fleet", "enroll", "enrollment")) or _looks_like_generic_contextual_followup(normalized):
            return "board_setup_help"
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
        if _has_any(normalized, ("how", "where", "switch", "change", "setup", "demo", "doc", "docs", "link")) or _looks_like_generic_contextual_followup(normalized):
            return "sitl_help"
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
        (("quickscout", "quick scout", "quick scoute", "sar", "search and rescue", "finding", "findings", "search area", "coverage", "handoff"), ("sar",)),
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
        if score > 0:
            matches.append((score, str(getattr(tool, "id", "")), tool))
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
        if _looks_like_live_fleet_state_question(normalized):
            return "fleet_connectivity"
        return "fleet_summary"
    if domain == "sar":
        if _looks_like_registry_domain_tool_question(normalized, topic=topic):
            return "registry_domain_tool_summary"
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
        if _has_any(normalized, ("companion", "raspberry", "cm4", " pi", "script", "bootstrap", "install")):
            return "companion_setup_help"
        if _has_any(normalized, ("third", "3rd", "drone 3", "new drone", "add drone", "another drone")):
            return "add_drone_workflow"
        return "board_setup_help"
    if domain == "logs":
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
    if not _has_domain_signal(normalized, ("command", "commands", "action", "actions")):
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


def _looks_like_system_status_question(normalized: str) -> bool:
    if _has_domain_signal(normalized, ("fleet status", "drone status", "show status", "swarm status")):
        return False
    return _has_domain_signal(
        normalized,
        ("gcs health", "system health", "server health", "health check", "gcs status", "system status"),
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


def _fleet_position_summary(telemetry_row: Mapping[str, Any]) -> tuple[float | None, float | None, float | None, str]:
    lat = _finite_or_none(_first_present(telemetry_row, ("position_lat", "latitude", "lat", "latitude_deg")))
    lon = _finite_or_none(_first_present(telemetry_row, ("position_long", "position_lon", "longitude", "lon", "longitude_deg")))
    alt = _finite_or_none(
        _first_present(
            telemetry_row,
            ("relative_altitude_m", "position_alt", "altitude_m", "gps_raw_altitude_m", "altitude"),
        )
    )
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
    _lat, _lon, _alt, gps = _fleet_position_summary(telemetry_row)
    return {
        "battery": _fmt_battery(voltage, remaining),
        "armed": _fmt_bool_state(armed),
        "ready": _fmt_bool_state(ready),
        "mode": _fmt_optional_value(mode),
        "system": _fmt_optional_value(system),
        "gps": gps,
    }


def _fmt_battery(voltage: float | None, remaining: float | None = None) -> str:
    parts: list[str] = []
    if voltage is not None:
        parts.append(f"{voltage:.2f} V")
    if remaining is not None:
        display_remaining = remaining * 100.0 if 0.0 <= remaining <= 1.0 else remaining
        parts.append(f"{display_remaining:.0f}%")
    return " / ".join(parts) if parts else "unavailable"


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


def _country_from_coordinates(lat: float, lon: float) -> str:
    # Lightweight operator hint only. It avoids external geocoding and returns
    # unknown instead of inventing precision outside the common MDS test regions.
    regions = (
        ("France", 41.0, 51.5, -5.5, 10.0),
        ("Taiwan", 21.8, 25.5, 119.0, 122.5),
        ("Iran", 24.0, 40.5, 44.0, 64.5),
        ("United States", 24.0, 49.5, -125.0, -66.0),
        ("Switzerland", 45.6, 47.9, 5.8, 10.6),
    )
    for label, min_lat, max_lat, min_lon, max_lon in regions:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return label
    return "unknown"


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
        "sar": ("sar", "quickscout", "quick scout", "quick scoute", "search and rescue", "finding", "findings", "coverage", "handoff"),
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
        "what shuld",
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
        "raspbeery",
        "raspberry pi",
        " rpi",
        " pi ",
        "cm4",
        "compute module",
        "new drone",
        "new doren",
        "new droen",
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
    quickscout_terms = ("quickscout", "quick scout", "quick scoute", "quickscoute")
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


def _has_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _extract_configured_drone_label(message: str, config: list[dict[str, Any]]) -> str:
    normalized = _normalize_text(message)
    if not _has_any(normalized, ("ip", "drone", "vehicle", "fleet", "configured", "callsign")):
        return ""
    if re.search(r"\bscout\b", normalized):
        return "scout"
    aliases: list[str] = []
    for drone in config:
        for field in ("callsign", "role", "name", "label"):
            alias = _normalize_text(str(drone.get(field) or ""))
            if alias:
                aliases.append(alias)
                aliases.extend(part for part in re.split(r"[^a-z0-9]+", alias) if len(part) >= 3)
    for alias in sorted(set(aliases), key=len, reverse=True):
        if alias and re.search(rf"\b{re.escape(alias)}\b", normalized):
            return alias
    return ""


def _drone_matches_label(drone: Mapping[str, Any], label: str) -> bool:
    normalized_label = _normalize_text(label)
    if not normalized_label:
        return False
    for field in ("callsign", "role", "name", "label"):
        value = _normalize_text(str(drone.get(field) or ""))
        if value == normalized_label:
            return True
        parts = {part for part in re.split(r"[^a-z0-9]+", value) if part}
        if normalized_label in parts:
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
    return "- Readiness: not proven fly-ready from read-only checks; missing or non-green signal(s): " + ", ".join(missing) + "."


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
    return {
        "command_id": _enum_or_value(getattr(command, "command_id", "")),
        "mission_type": _enum_or_value(getattr(command, "mission_type", "")),
        "mission_name": _enum_or_value(getattr(command, "mission_name", "")),
        "phase": _enum_or_value(getattr(command, "phase", "")),
        "status": _enum_or_value(getattr(command, "status", "")),
        "outcome": _enum_or_value(getattr(command, "outcome", "")),
        "target_drones": list(getattr(command, "target_drones", []) or []),
        "created_at": getattr(command, "created_at", None),
        "updated_at": getattr(command, "updated_at", None),
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

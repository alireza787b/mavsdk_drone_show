"""Simurgh Operator GCS routes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from src.enums import Mission, State
from src.settings.runtime import resolve_runtime_mode
from agent_runtime.tool_executor import (
    InternalToolExecutionContext,
    execute_policy_allowed_guarded_route_tool,
    execute_policy_allowed_read_only_tool,
    list_policy_allowed_read_only_tools,
)

from agent_runtime import (
    AgentRuntimeError,
    AgentSessionStore,
    AssistantContextAssembler,
    AssistantContextDocument,
    AssistantHistoryStore,
    AssistantTurnHistoryRecord,
    AssistantTurnRecord,
    AssistantTurnResult,
    InMemoryAuditSink,
    MCP_ENDPOINT_PATH,
    MCP_PROTOCOL_VERSION,
    MCP_RESOURCE_PREFIX,
    PolicyDecisionStatus,
    SimurghMcpResourceProvider,
    ToolExposure,
    blocked_intent_matches,
    create_assistant_turn,
    filter_safe_read_only_sensitive_input_matches,
    is_mcp_auth_required,
    is_mcp_origin_allowed,
    is_previous_evidence_followup_message,
    load_default_assistant_config,
    load_default_context_index,
    load_default_policy,
    load_default_tool_registry,
    mcp_bearer_challenge,
    mcp_protected_resource_metadata,
    mcp_required_scopes,
    mcp_server_info,
    mcp_server_instructions,
    require_mcp_runtime_enabled,
    sensitive_input_matches,
)
from agent_runtime.assistant import (
    READ_TOOL_ADAPTER_VERSION,
    READ_TOOL_MODEL,
    READ_TOOL_PROVIDER,
    compose_read_only_tool_turn_with_provider,
    rewrite_operator_message_with_provider,
)
from agent_runtime.action_planner import (
    ACTION_ADAPTER_VERSION,
    ACTION_INTENT,
    ACTION_MODEL,
    ACTION_TOOL_ID,
    ActionDraft,
    FlightActionDraft,
    RegistryActionDraft,
    SITL_BATCH_ACTION_TOOL_ID,
    SITL_CREATE_TOOL_ID,
    SITL_RECONCILE_TOOL_ID,
    action_draft_from_context_json,
    build_flight_action_draft,
    build_sitl_reconcile_action_draft,
    approval_window_status,
    is_action_confirmation_message,
    is_action_rejection_message,
    with_approval_window,
)
from agent_runtime.action_runs import (
    DEFAULT_RUNNER_LEASE_SECONDS,
    MAX_RUNNER_LEASE_SECONDS,
    MIN_RUNNER_LEASE_SECONDS,
    ActionRunOwnership,
    ActionRunOwnershipError,
    ActionRunResourceConflict,
    ActionRunSnapshot,
    ActionRunStore,
    ActionRunTerminalStateError,
)
from agent_runtime.action_intent import (
    build_action_draft_from_provider_plan,
    validate_provider_action_plan_source_coverage,
)
from agent_runtime.action_preconditions import (
    ActionPreconditionEvaluation,
    assistant_fact_contracts,
    assistant_fact_map,
    evaluate_action_preconditions,
)
from agent_runtime.mds_read_tools import (
    answer_mds_read_only_question,
    apply_runtime_settings,
    build_provider_credentials_payload,
    build_runtime_settings_payload,
    delete_provider_credentials,
    infer_mds_read_topic,
    is_safe_blocked_term_read_only_intent,
    provider_read_intent_contracts,
    provider_read_intent_tool_ids,
    update_provider_credentials,
)
from agent_runtime.language import detect_language_profile
from agent_runtime.evidence import ReadOnlyEvidenceBundle
from agent_runtime.models import AgentSession, AuditEvent, ContextResource, ToolDefinition, stable_payload_hash, utc_now
from agent_runtime.query_adaptation import adapt_operator_query, normalize_operator_query_text
from agent_runtime.target_grounding import (
    extract_numeric_tokens,
    materialize_target_binding,
    structured_target_ids,
)
from agent_runtime.sitl_lifecycle import (
    evaluate_sitl_lifecycle_completion,
    sitl_lifecycle_evidence_roles,
)
from agent_runtime.registry_chat import (
    REGISTRY_READ_EXECUTION_INTENT,
    RegistryReadPlan,
    RegistryReadToolResult,
    build_registry_read_plan_from_tool_ids,
    build_registry_read_evidence_bundle,
    format_registry_read_results,
    plan_registry_read_tool_calls,
    reconcile_registry_read_tool_ids,
    registry_read_tool_ids_have_operator_summary,
)
from agent_runtime.tool_candidates import candidate_review_payload, load_default_tool_candidate_artifact
from agent_runtime.turn_intent import build_turn_intent_frame
from command_submission import submit_tracked_command
from schemas import SubmitCommandRequest


REPO_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("mds.simurgh")

JSONRPC_VERSION = "2.0"
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
JSONRPC_SERVER_ERROR = -32000
MCP_PROMPT_COMPARE_MISSION_MODES = "mds.compare_mission_modes"
MAX_ASSISTANT_METADATA_BYTES = 4096
MAX_ASSISTANT_CONTEXT_RESOURCE_IDS = 12
MAX_ASSISTANT_HISTORY_LIMIT = 100
ACTION_MONITOR_POLL_SECONDS = 2.0
ACTION_MONITOR_TIMEOUT_SECONDS = 90.0
ACTION_MONITOR_HEARTBEAT_SECONDS = 10.0
ACTION_RUNNER_LEASE_RENEWAL_FRACTION = 1.0 / 3.0
ACTION_RUNNER_LEASE_RENEWAL_MAX_SECONDS = 10.0
COMMAND_TERMINAL_PHASE = "terminal"
DEFAULT_PROVIDER_MAX_CONCURRENCY = 4


def _bounded_float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _bounded_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _action_runner_lease_renewal_interval(lease_seconds: int | float) -> float:
    """Renew ownership well before expiry, independently of progress events."""

    return min(
        ACTION_RUNNER_LEASE_RENEWAL_MAX_SECONDS,
        max(0.25, float(lease_seconds) * ACTION_RUNNER_LEASE_RENEWAL_FRACTION),
    )


async def _maintain_action_run_ownership(
    renew_ownership: Callable[[ActionRunOwnership], Awaitable[ActionRunSnapshot]],
    ownership: ActionRunOwnership,
    stop_event: asyncio.Event,
    *,
    lease_seconds: int | float,
) -> None:
    """Renew a runner lease until execution ends or ownership is lost."""

    renewal_interval = _action_runner_lease_renewal_interval(lease_seconds)
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=renewal_interval)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            return
        try:
            await renew_ownership(ownership)
        except ActionRunTerminalStateError:
            return
        except (ActionRunOwnershipError, KeyError) as exc:
            raise ActionRunOwnershipError(
                f"action-run ownership was lost for {ownership.run_id}"
            ) from exc


async def _run_with_action_run_ownership(
    operation: Awaitable[None],
    *,
    renew_ownership: Callable[[ActionRunOwnership], Awaitable[ActionRunSnapshot]],
    ownership: ActionRunOwnership,
    lease_seconds: int | float,
) -> None:
    """Run orchestration and its ownership heartbeat as one failure domain."""

    stop_event = asyncio.Event()
    operation_task = asyncio.create_task(
        operation,
        name=f"simurgh-action-operation:{ownership.run_id}",
    )
    keepalive_task = asyncio.create_task(
        _maintain_action_run_ownership(
            renew_ownership,
            ownership,
            stop_event,
            lease_seconds=lease_seconds,
        ),
        name=f"simurgh-action-lease:{ownership.run_id}",
    )
    try:
        done, _ = await asyncio.wait(
            {operation_task, keepalive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if operation_task in done:
            await operation_task
            stop_event.set()
            await keepalive_task
            return

        await keepalive_task
        await operation_task
    finally:
        stop_event.set()
        for task in (operation_task, keepalive_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(operation_task, keepalive_task, return_exceptions=True)


def _final_state_thresholds() -> dict[str, float]:
    """Centralize configurable telemetry tolerances for terminal flight verification."""

    return {
        "max_relative_altitude_m": _bounded_float_env(
            "MDS_AGENT_FINAL_STATE_MAX_RELATIVE_ALTITUDE_M", 1.0, minimum=0.05, maximum=10.0
        ),
        "max_vertical_speed_mps": _bounded_float_env(
            "MDS_AGENT_FINAL_STATE_MAX_VERTICAL_SPEED_MPS", 0.75, minimum=0.05, maximum=5.0
        ),
        "max_rtl_home_distance_m": _bounded_float_env(
            "MDS_AGENT_RTL_MAX_HOME_DISTANCE_M", 5.0, minimum=0.25, maximum=100.0
        ),
    }


def _telemetry_float(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number and abs(number) != float("inf"):
            return number
    return None


def _telemetry_bool(row: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            return value
        if value in (None, ""):
            continue
        normalized = str(value).strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def _telemetry_landed_state(row: Mapping[str, Any]) -> bool | None:
    """Normalize common PX4/MAVSDK landed-state representations without guessing unknown values."""

    for key in ("is_landed", "landed", "landed_state", "land_state"):
        value = row.get(key)
        if isinstance(value, bool):
            return value
        if value in (None, ""):
            continue
        normalized = str(value).strip().casefold()
        if normalized in {"true", "1", "yes", "on", "on_ground", "landed", "ground"}:
            return True
        if normalized in {
            "false",
            "2",
            "3",
            "4",
            "no",
            "off",
            "in_air",
            "airborne",
            "taking_off",
            "landing",
        }:
            return False
    return None


def _telemetry_enum_matches(row: Mapping[str, Any], key: str, expected: Any) -> bool:
    """Match canonical telemetry enum values while accepting their serialized names."""

    value = row.get(key)
    if value is None or isinstance(value, bool):
        return False
    expected_value = getattr(expected, "value", expected)
    expected_name = str(getattr(expected, "name", "")).strip().casefold()
    try:
        if int(value) == int(expected_value):
            return True
    except (TypeError, ValueError):
        pass
    return bool(expected_name and str(value).strip().casefold() == expected_name)


def _terminal_flight_state_observation(
    row: Mapping[str, Any],
    *,
    target: str,
    mission_type: int,
) -> dict[str, Any]:
    """Evaluate terminal LAND/RTL evidence from one fresh telemetry row."""

    thresholds = _final_state_thresholds()
    armed = _telemetry_bool(row, "is_armed", "armed")
    landed = _telemetry_landed_state(row)
    relative_altitude = _telemetry_float(row, "relative_altitude_m", "relative_home_m")
    vertical_speed = _telemetry_float(
        row,
        "velocity_down",
        "local_velocity_down",
        "vertical_velocity_mps",
    )
    distance_to_home = _telemetry_float(row, "distance_to_home_m", "home_distance_m")
    canonical_idle = _telemetry_enum_matches(row, "state", State.IDLE)
    canonical_mission_none = _telemetry_enum_matches(row, "mission", Mission.NONE)
    settled = (
        vertical_speed is not None
        and abs(vertical_speed) <= thresholds["max_vertical_speed_mps"]
    )
    within_home_threshold = (
        distance_to_home is not None
        and distance_to_home >= 0
        and distance_to_home <= thresholds["max_rtl_home_distance_m"]
    )
    canonical_grounded = bool(
        armed is False
        and canonical_idle
        and canonical_mission_none
        and settled
        and (
            relative_altitude is not None
            and abs(relative_altitude) <= thresholds["max_relative_altitude_m"]
            or mission_type == Mission.RETURN_RTL.value
            and within_home_threshold
        )
    )
    grounded_evidence = (
        "land_detector"
        if landed is True
        else "canonical_idle_settled"
        if canonical_grounded
        else "relative_altitude_settled"
        if (
            landed is None
            and relative_altitude is not None
            and abs(relative_altitude) <= thresholds["max_relative_altitude_m"]
            and settled
        )
        else ""
    )
    reasons: list[str] = []
    if armed is not False:
        reasons.append("disarm not confirmed")
    if landed is False:
        reasons.append("land detector does not report on-ground")
    elif landed is not True and not canonical_grounded:
        if relative_altitude is None or vertical_speed is None:
            reasons.append("land detector or altitude/vertical-speed evidence is unavailable")
        else:
            if abs(relative_altitude) > thresholds["max_relative_altitude_m"]:
                reasons.append("relative altitude remains outside the landed threshold")
            if abs(vertical_speed) > thresholds["max_vertical_speed_mps"]:
                reasons.append("vertical speed remains above the settled threshold")
    if mission_type == Mission.RETURN_RTL.value:
        if distance_to_home is None:
            reasons.append("distance-to-home evidence is unavailable")
        elif distance_to_home < 0:
            reasons.append("distance-to-home evidence is invalid")
        elif distance_to_home > thresholds["max_rtl_home_distance_m"]:
            reasons.append("vehicle is not within the RTL home-distance threshold")
    return {
        "target_drone_id": target,
        "verified": not reasons,
        "armed": armed,
        "landed": landed,
        "relative_altitude_m": relative_altitude,
        "vertical_speed_mps": vertical_speed,
        "distance_to_home_m": distance_to_home,
        "canonical_state_idle": canonical_idle,
        "canonical_mission_none": canonical_mission_none,
        "grounded_evidence": grounded_evidence,
        "reasons": reasons,
    }


COMMAND_SUCCESS_OUTCOMES = {"completed"}
COMMAND_TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "timeout"}
SITL_TERMINAL_STATUSES = {"completed", "succeeded", "failed", "cancelled", "canceled", "timeout"}
EXTERNAL_ASSISTANT_PROVIDER_SESSION_ROLES = {"admin", "operator"}
EXTERNAL_ASSISTANT_PROVIDER_BEARER_SCOPES = {"admin", "agent", "operator"}
QUERY_DOMAIN_PROGRESS_LABELS = {
    "capabilities": "capabilities",
    "docs": "documentation",
    "drone_show": "drone show",
    "fleet": "fleet status",
    "flight": "flight action",
    "general": "general question",
    "logs": "logs",
    "mcp": "MCP/tools",
    "runtime": "runtime settings",
    "safety": "safety policy",
    "sar": "SAR/QuickScout",
    "setup": "setup workflow",
    "sitl": "SITL",
    "swarm": "swarm mission",
    "ui": "dashboard UI",
}


async def _sleep_action_sequence_delay(delay_seconds: float) -> None:
    """Sleep one validated operator-requested sequence delay."""

    await asyncio.sleep(delay_seconds)


QUERY_RESPONSE_MODE_PROGRESS_LABELS = {
    "capability": "capability answer",
    "clarify": "clarification",
    "compare": "comparison",
    "interpret": "explanation",
    "status": "status check",
    "workflow": "workflow guidance",
}


@dataclass(frozen=True)
class ActionExecutionOutcome:
    action_execution: str
    action_response: Any | None = None
    monitor_result: Mapping[str, Any] | None = None
    post_action_results: tuple[Mapping[str, Any], ...] = ()
    rejection_detail: str = ""


PREVIOUS_ACTION_EVIDENCE_TOOL_ID = "simurgh.session.previous_action.read"
LOCAL_READ_INTENT_SUBSUMPTIONS: Mapping[str, frozenset[str]] = {
    "fleet_status": frozenset({"fleet_connectivity"}),
    "drone_log_summary": frozenset({"backend_log_summary", "command_summary"}),
}
SEMANTIC_REWRITE_TERMINAL_ROUTES = {
    "action_confirmation",
    "action_rejection",
}
SEMANTIC_REWRITE_DRAFT_ACTION_HINTS = {
    "draft_sitl_lifecycle_action",
    "draft_flight_action",
}
SEMANTIC_REWRITE_ACTION_HINTS = {
    *SEMANTIC_REWRITE_DRAFT_ACTION_HINTS,
}
SEMANTIC_REWRITE_HELP_INTENTS = {
    "docs_help",
    "sitl_help",
    "operator_help",
    "board_setup_help",
    "companion_setup_help",
}
AUTHORITATIVE_TYPED_ACTION_TERM_READ_INTENTS = frozenset(
    {
        # The local fleet-connectivity contract owns ready/armed/live status
        # questions even when the question names a possible next action.
        "fleet_connectivity",
    }
)


class SimurghRouteRef(BaseModel):
    method: str | None = None
    path: str | None = None


class SimurghToolResponse(BaseModel):
    id: str
    title: str
    description: str
    exposure: str
    risk_class: str
    boundary: str
    read_only: bool
    route: SimurghRouteRef
    required_role: str
    requires_approval: bool
    destructive: bool
    runtime_modes: list[str]
    side_effects: list[str]
    sensitivity: list[str]
    tags: list[str]
    docs: list[str]
    safety_notes: list[str]


class SimurghToolListResponse(BaseModel):
    version: int
    tools: list[SimurghToolResponse]


class SimurghToolCandidateResponse(BaseModel):
    id: str
    review_status: str
    callable: bool
    source: dict[str, Any]
    classification: dict[str, Any]
    has_request_body: bool
    parameter_count: int
    promoted: bool
    promoted_tools: list[dict[str, Any]]


class SimurghToolCandidateReviewResponse(BaseModel):
    schema_version: int
    artifact: str
    artifact_path: str
    source: dict[str, Any]
    policy: dict[str, Any]
    summary: dict[str, Any]
    candidate_count: int
    filtered_count: int
    returned_count: int
    offset: int
    limit: int
    filters: dict[str, Any]
    candidates: list[SimurghToolCandidateResponse]


class SimurghRuntimeModePolicyResponse(BaseModel):
    allowed_risks: list[str]
    denied_risks: list[str]
    approval_required_risks: list[str]


class SimurghPolicyResponse(BaseModel):
    version: int
    agent_enabled: bool
    mcp_enabled: bool
    mode: str
    action_circuit_breaker_enabled: bool
    always_confirm_before_action: bool
    actions_blocked: bool
    action_policy_source: str
    allow_drone_api_exposure: bool
    unknown_tool_policy: str
    approval_ttl_seconds: int
    approval_required_risks: list[str]
    runtime_modes: dict[str, SimurghRuntimeModePolicyResponse]


class SimurghStatusResponse(BaseModel):
    agent_enabled: bool
    mcp_enabled: bool
    gcs_mode: str
    gcs_mode_source: str
    mode: str
    action_circuit_breaker_enabled: bool
    always_confirm_before_action: bool
    actions_blocked: bool
    action_policy_source: str
    tool_registry_version: int
    tool_count: int
    allowed_tool_count: int
    guarded_tool_count: int
    excluded_tool_count: int
    context_resource_count: int
    active_session_count: int
    audit_event_count: int
    assistant_provider: str
    assistant_model: str
    assistant_external_provider: bool
    assistant_external_provider_auth_required: bool
    policy_path: str
    tool_registry_path: str
    context_index_path: str
    warnings: list[str] = Field(default_factory=list)


class SimurghContextResourceResponse(BaseModel):
    id: str
    title: str
    path: str
    mime_type: str
    audience: str
    sensitivity: str
    summary: str
    tags: list[str]
    content_hash: str


class SimurghContextListResponse(BaseModel):
    version: int
    resources: list[SimurghContextResourceResponse]


class SimurghContextContentResponse(BaseModel):
    resource: SimurghContextResourceResponse
    content: str


class SimurghSessionCreateRequest(BaseModel):
    actor: str = Field(default="operator", min_length=1)
    mode: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimurghSessionResponse(BaseModel):
    id: str
    actor: str
    mode: str
    created_at: str
    expires_at: str
    closed_at: str | None
    closed: bool
    metadata: dict[str, Any]


class SimurghSessionListResponse(BaseModel):
    sessions: list[SimurghSessionResponse]


class SimurghAuditEventResponse(BaseModel):
    id: str
    event_type: str
    created_at: str
    session_id: str | None
    actor: str | None
    tool_id: str | None
    decision: str | None
    payload_hash: str
    metadata: dict[str, Any]


class SimurghAuditListResponse(BaseModel):
    events: list[SimurghAuditEventResponse]


class SimurghAssistantTurnRequest(BaseModel):
    actor: str = Field(default="operator", min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    mode: str | None = None
    context_resource_ids: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimurghActionRunControlRequest(BaseModel):
    actor: str = Field(default="operator", min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="", max_length=500)
    control_id: str | None = Field(default=None, min_length=1, max_length=128)


class SimurghRuntimeSettingsRequest(BaseModel):
    agent_enabled: bool | None = None
    mcp_enabled: bool | None = None
    action_circuit_breaker_enabled: bool | None = None
    always_confirm_before_action: bool | None = None
    provider: str | None = None
    model: str | None = None
    openai_model: str | None = None
    web_search_enabled: bool | None = None
    dry_run: bool = False


class SimurghProviderCredentialsRequest(BaseModel):
    openai_api_key: str = Field(min_length=20, max_length=4096)
    set_provider_openai: bool = False
    openai_model: str | None = None


class SimurghProviderCredentialsDeleteRequest(BaseModel):
    openai_api_key_file: str | None = None


class SimurghAssistantContextResponse(BaseModel):
    id: str
    title: str
    uri: str
    mime_type: str
    summary: str
    tags: list[str]
    content_hash: str


class SimurghAssistantTurnTraceResponse(BaseModel):
    schema_version: int = 1
    provider: str | None = None
    model: str | None = None
    adapter_version: str | None = None
    provider_tools: dict[str, Any] = Field(default_factory=dict)
    intent: dict[str, Any] = Field(default_factory=dict)
    session: dict[str, Any] = Field(default_factory=dict)
    language: dict[str, Any] = Field(default_factory=dict)
    adaptation: dict[str, Any] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    tool: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)


class SimurghAssistantTurnResponse(BaseModel):
    id: str
    created_at: str
    provider: str
    model: str
    adapter_version: str
    session: SimurghSessionResponse
    actor: str
    mode: str
    message_hash: str
    message_chars: int
    content: str
    context_resources: list[SimurghAssistantContextResponse]
    blocked_intents: list[str]
    safety_notes: list[str]
    audit_event_id: str
    trace: SimurghAssistantTurnTraceResponse = Field(default_factory=SimurghAssistantTurnTraceResponse)


class SimurghAssistantTurnHistoryResponse(BaseModel):
    id: str
    created_at: str
    provider: str
    model: str
    adapter_version: str
    session_id: str
    actor: str
    mode: str
    message: str
    content: str
    context_resources: list[SimurghAssistantContextResponse]
    blocked_intents: list[str]
    safety_notes: list[str]
    audit_event_id: str
    message_hash: str
    message_chars: int


class SimurghAssistantTurnListResponse(BaseModel):
    turns: list[SimurghAssistantTurnHistoryResponse]


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _tool_response(tool: ToolDefinition) -> SimurghToolResponse:
    return SimurghToolResponse(
        id=tool.id,
        title=tool.title,
        description=tool.description,
        exposure=tool.exposure.value,
        risk_class=tool.risk_class.value,
        boundary=tool.boundary,
        read_only=tool.read_only,
        route=SimurghRouteRef(method=tool.route_method, path=tool.route_path),
        required_role=tool.required_role,
        requires_approval=tool.requires_approval,
        destructive=tool.destructive,
        runtime_modes=list(tool.runtime_modes),
        side_effects=list(tool.side_effects),
        sensitivity=list(tool.sensitivity),
        tags=list(tool.tags),
        docs=list(tool.docs),
        safety_notes=list(tool.safety_notes),
    )


def _context_resource_response(index, resource: ContextResource) -> SimurghContextResourceResponse:
    return SimurghContextResourceResponse(
        id=resource.id,
        title=resource.title,
        path=resource.path.as_posix(),
        mime_type=resource.mime_type,
        audience=resource.audience,
        sensitivity=resource.sensitivity,
        summary=resource.summary,
        tags=list(resource.tags),
        content_hash=resource.content_hash(repo_root=index.repo_root),
    )


def _session_response(session: AgentSession) -> SimurghSessionResponse:
    return SimurghSessionResponse(
        id=session.id,
        actor=session.actor,
        mode=session.mode,
        created_at=session.created_at.isoformat(),
        expires_at=session.expires_at.isoformat(),
        closed_at=session.closed_at.isoformat() if session.closed_at else None,
        closed=session.closed,
        metadata=dict(session.metadata),
    )


def _audit_event_response(event: AuditEvent) -> SimurghAuditEventResponse:
    payload = event.to_json_dict()
    return SimurghAuditEventResponse(**payload)


def _assistant_context_response(document: AssistantContextDocument) -> SimurghAssistantContextResponse:
    return SimurghAssistantContextResponse(**document.public_metadata())


def _assistant_context_history_response(payload: dict[str, Any]) -> SimurghAssistantContextResponse:
    return SimurghAssistantContextResponse(**payload)


def _assistant_trace_response(record) -> SimurghAssistantTurnTraceResponse:
    """Return sanitized orchestration trace metadata for PM/test inspection."""

    metadata = dict(record.audit_event.metadata or {})
    turn_intent = metadata.get("turn_intent") if isinstance(metadata.get("turn_intent"), dict) else {}
    language = metadata.get("language_profile") if isinstance(metadata.get("language_profile"), dict) else {}
    adaptation = metadata.get("query_adaptation") if isinstance(metadata.get("query_adaptation"), dict) else {}
    provider_tools = metadata.get("provider_tools") if isinstance(metadata.get("provider_tools"), dict) else {}
    web_search_requested = bool(provider_tools.get("web_search_requested") or metadata.get("web_search_enabled"))
    web_search_returned = bool(provider_tools.get("web_search_returned"))
    try:
        citation_count = max(0, int(provider_tools.get("citation_count") or 0))
    except (TypeError, ValueError):
        citation_count = 0
    source_status = str(provider_tools.get("source_status") or "").strip()
    if not source_status:
        if not web_search_requested:
            source_status = "not_requested"
        elif citation_count > 0:
            source_status = "citations_returned"
        elif web_search_returned:
            source_status = "search_returned_without_citations"
        else:
            source_status = "search_requested_without_returned_call"
    action_execution = str(metadata.get("action_execution") or "none")
    circuit_breaker_layer = str(
        metadata.get("circuit_breaker_layer")
        or "final-action layer; no action tool was invoked for this turn"
    )
    safety: dict[str, Any] = {
        "blocked_intent_count": metadata.get("blocked_intent_count"),
        "action_execution": action_execution,
        "circuit_breaker_layer": circuit_breaker_layer,
    }
    action_draft = metadata.get("action_draft")
    if isinstance(action_draft, dict):
        public_draft = dict(action_draft)
        try:
            draft = action_draft_from_context_json(
                json.dumps(public_draft, sort_keys=True, separators=(",", ":"), default=str)
            )
            public_draft["display_plan"] = _action_draft_display_plan(draft)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        safety["action_draft"] = public_draft
    policy_reasons = metadata.get("policy_reasons")
    if isinstance(policy_reasons, list):
        safety["policy_reasons"] = policy_reasons
    action_monitor = metadata.get("action_monitor")
    if isinstance(action_monitor, dict):
        safety["action_monitor"] = action_monitor
    post_action_results = metadata.get("post_action_results")
    if isinstance(post_action_results, list):
        safety["post_action_results"] = [
            dict(item) for item in post_action_results if isinstance(item, dict)
        ]
    action_run = metadata.get("action_run")
    if isinstance(action_run, dict):
        safety["action_run"] = dict(action_run)
    action_preconditions = metadata.get("action_preconditions")
    if isinstance(action_preconditions, dict):
        safety["action_preconditions"] = dict(action_preconditions)
    pre_action_read_only_tool_ids = metadata.get("pre_action_read_only_tool_ids")
    if isinstance(pre_action_read_only_tool_ids, list):
        safety["pre_action_read_only_tool_ids"] = [
            str(tool_id) for tool_id in pre_action_read_only_tool_ids
        ]
    pre_action_read_only_evidence = metadata.get("pre_action_read_only_evidence")
    if isinstance(pre_action_read_only_evidence, dict):
        safety["pre_action_read_only_evidence"] = pre_action_read_only_evidence
    return SimurghAssistantTurnTraceResponse(
        provider=record.turn.provider,
        model=record.turn.model,
        adapter_version=record.turn.adapter_version,
        provider_tools={
            "web_search_enabled": web_search_requested,
            "web_search_requested": web_search_requested,
            "web_search_returned": web_search_returned,
            "web_search_scope": "public_general_only" if web_search_requested else "disabled",
            "citation_count": citation_count,
            "source_status": source_status,
        },
        intent=dict(turn_intent),
        session={
            "id": record.session.id,
            "mode": record.session.mode,
            "topic": str(record.session.metadata.get("last_domain") or ""),
        },
        language=dict(language),
        adaptation=dict(adaptation),
        query={
            "domain": metadata.get("query_domain"),
            "confidence": metadata.get("query_confidence"),
            "unclear": metadata.get("query_unclear"),
            "reason": metadata.get("query_reason"),
            "response_mode": metadata.get("response_mode"),
            "read_only_plan": (
                metadata.get("read_only_plan")
                if isinstance(metadata.get("read_only_plan"), dict)
                else {}
            ),
        },
        tool={
            "id": metadata.get("tool_id"),
            "intent": metadata.get("tool_intent"),
            "ids": metadata.get("tool_ids") or [],
            "evidence": metadata.get("read_only_evidence") if isinstance(metadata.get("read_only_evidence"), dict) else {},
        },
        context={
            "resource_count": metadata.get("context_count"),
            "retrieved_context_count": metadata.get("retrieved_context_count"),
        },
        safety=safety,
    )


def _assistant_history_response(record: AssistantTurnHistoryRecord) -> SimurghAssistantTurnHistoryResponse:
    return SimurghAssistantTurnHistoryResponse(
        id=record.id,
        created_at=record.created_at,
        provider=record.provider,
        model=record.model,
        adapter_version=record.adapter_version,
        session_id=record.session_id,
        actor=record.actor,
        mode=record.mode,
        message="",
        content="",
        context_resources=[_assistant_context_history_response(resource) for resource in record.context_resources],
        blocked_intents=list(record.blocked_intents),
        safety_notes=list(record.safety_notes),
        audit_event_id=record.audit_event_id,
        message_hash=record.message_hash,
        message_chars=record.message_chars,
    )


def _assistant_turn_response_model(record, history_record: AssistantTurnHistoryRecord) -> SimurghAssistantTurnResponse:
    return SimurghAssistantTurnResponse(
        id=record.turn.id,
        created_at=record.turn.created_at,
        provider=record.turn.provider,
        model=history_record.model,
        adapter_version=history_record.adapter_version,
        session=_session_response(record.session),
        actor=history_record.actor,
        mode=history_record.mode,
        message_hash=history_record.message_hash,
        message_chars=history_record.message_chars,
        content=record.turn.content,
        context_resources=[
            _assistant_context_response(document) for document in record.turn.context_documents
        ],
        blocked_intents=list(record.turn.blocked_intents),
        safety_notes=list(record.turn.safety_notes),
        audit_event_id=record.audit_event.id,
        trace=_assistant_trace_response(record),
    )


def _assistant_turn_response_payload(record, history_record: AssistantTurnHistoryRecord) -> dict[str, Any]:
    response = _assistant_turn_response_model(record, history_record)
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    return response.dict()


def _assistant_sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _action_run_sse_event(event_id: int, event: str, data: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(data), ensure_ascii=False, separators=(",", ":"), default=str)
    return f"id: {int(event_id)}\nevent: {event}\ndata: {payload}\n\n"


def _assistant_content_chunks(content: str, chunk_size: int = 96):
    text = str(content or "")
    if not text:
        return
    for line in text.splitlines(keepends=True):
        while line:
            yield line[:chunk_size]
            line = line[chunk_size:]


def _tool_titles_for_progress(tool_ids: list[str]) -> list[str]:
    if not tool_ids:
        return []
    try:
        registry = load_default_tool_registry()
    except AgentRuntimeError:
        return tool_ids[:3]
    titles: list[str] = []
    for tool_id in tool_ids[:3]:
        tool = registry.get(tool_id)
        titles.append(tool.title if tool else tool_id)
    return titles


def _assistant_tool_progress_payload(payload: dict[str, Any]) -> dict[str, Any]:
    trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
    tool = trace.get("tool") if isinstance(trace.get("tool"), dict) else {}
    safety = trace.get("safety") if isinstance(trace.get("safety"), dict) else {}
    tool_ids = [str(item).strip() for item in (tool.get("ids") or []) if str(item).strip()]
    tool_intent = str(tool.get("intent") or "").strip()
    action_execution = str(safety.get("action_execution") or "").strip()
    provider = str(payload.get("provider") or "").strip()
    provider_tools = trace.get("provider_tools") if isinstance(trace.get("provider_tools"), dict) else {}

    action_progress_labels = {
        "awaiting_confirmation": "Action draft ready",
        "approval_expired": "Action approval expired",
        "missing_arguments": "Action needs more details",
        "blocked_by_circuit_breaker": "Circuit breaker stopped action",
        "policy_denied": "Policy denied action",
        "validation_rejected": "GCS rejected action",
        "submitted": "GCS accepted action submission",
        "cancelled_confirmation": "Action cancelled",
    }
    if action_execution in action_progress_labels:
        label = action_progress_labels[action_execution]
        return {
            "stage": "safety",
            "state": "complete",
            "label": label,
            "intent": tool_intent,
            "tool_ids": tool_ids,
            "action_execution": action_execution,
        }

    if tool_ids:
        titles = _tool_titles_for_progress(tool_ids)
        joined_titles = "; ".join(titles)
        if len(tool_ids) > len(titles):
            joined_titles = f"{joined_titles}; +{len(tool_ids) - len(titles)} more" if joined_titles else f"{len(tool_ids)} tools"
        label = (
            f"Evidence ready: {joined_titles}"
            if len(tool_ids) == 1
            else f"Evidence ready from {len(tool_ids)} sources: {joined_titles}"
        )
        return {"stage": "tool", "state": "complete", "label": label, "intent": tool_intent, "tool_ids": tool_ids}

    if tool_intent:
        return {"stage": "tool", "state": "complete", "label": f"Evidence ready: {tool_intent.replace('_', ' ')}", "intent": tool_intent}
    if provider == "openai" and provider_tools.get("web_search_requested") is True:
        returned = provider_tools.get("web_search_returned") is True
        return {
            "stage": "search",
            "state": "complete" if returned else "requested",
            "label": "Searched public web" if returned else "Searching public web",
            "provider": "openai",
            "scope": "public_general_only",
        }
    if provider == "openai":
        return {"stage": "provider", "state": "complete", "label": "OpenAI answer ready"}
    return {"stage": "provider", "state": "complete", "label": "Local answer ready"}


AssistantProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


class _RequestScopedDeps:
    def __init__(self, base: Any | None, request: Request):
        self._base = base
        self.simurgh_request_base_url = str(request.base_url).rstrip("/")

    def __getattr__(self, name: str) -> Any:
        if self._base is None:
            raise AttributeError(name)
        return getattr(self._base, name)


def _request_scoped_deps(base: Any | None, request: Request) -> Any:
    return _RequestScopedDeps(base, request)


async def _emit_assistant_progress(
    callback: AssistantProgressCallback | None,
    payload: dict[str, Any],
) -> None:
    if callback is None:
        return
    await callback(payload)


def _title_case_progress_value(value: str) -> str:
    return str(value or "").replace("_", " ").strip().title()


def _assistant_understanding_progress_payload(
    *,
    query_plan,
    read_only_plan,
    previous_evidence_followup: bool = False,
) -> dict[str, Any]:
    domain = str(getattr(read_only_plan, "query_domain", "") or getattr(query_plan, "domain", "") or "general")
    response_mode = str(
        getattr(read_only_plan, "response_mode", "")
        or getattr(query_plan, "response_mode", "")
        or "status"
    )
    intent = str(getattr(read_only_plan, "intent", "") or "")
    domain_label = QUERY_DOMAIN_PROGRESS_LABELS.get(domain, _title_case_progress_value(domain) or "request")
    mode_label = QUERY_RESPONSE_MODE_PROGRESS_LABELS.get(response_mode, _title_case_progress_value(response_mode))

    if previous_evidence_followup:
        label = f"Following up on previous {domain_label} evidence"
    elif intent:
        label = f"Understanding: {domain_label} - {_title_case_progress_value(intent)}"
    elif mode_label:
        label = f"Understanding: {domain_label} - {mode_label}"
    else:
        label = f"Understanding: {domain_label}"

    return {
        "stage": "understanding",
        "state": "complete",
        "label": label,
        "domain": domain,
        "response_mode": response_mode,
        "intent": intent,
        "confidence": round(float(getattr(query_plan, "confidence", 0.0) or 0.0), 3),
        "unclear": bool(getattr(query_plan, "unclear", False)),
        "followup": bool(previous_evidence_followup),
    }


def _registry_plan_progress_payload(plan) -> dict[str, Any]:
    tool_ids = [call.tool.id for call in plan.tool_calls]
    count = len(tool_ids)
    label = "Selecting live evidence"
    if count == 1:
        label = f"Selected evidence: {plan.tool_calls[0].tool.title}"
    elif count > 1:
        label = f"Selected {count} evidence sources"
    return {
        "stage": "plan",
        "state": "complete",
        "label": label,
        "intent": REGISTRY_READ_EXECUTION_INTENT,
        "tool_ids": tool_ids,
        "count": count,
    }


def _registry_tool_call_progress_payload(call, *, state: str, result=None) -> dict[str, Any]:
    if state == "running":
        label = f"Checking {call.tool.title}"
    elif result is not None and getattr(result, "is_error", False):
        label = f"{call.tool.title} returned an error"
    else:
        label = f"Checked {call.tool.title}"
    payload: dict[str, Any] = {
        "stage": "tool",
        "state": state,
        "label": label,
        "intent": REGISTRY_READ_EXECUTION_INTENT,
        "tool_id": call.tool.id,
        "tool_ids": [call.tool.id],
        "title": call.tool.title,
    }
    if result is not None:
        if getattr(result, "status_code", None):
            payload["status_code"] = result.status_code
        payload["is_error"] = bool(getattr(result, "is_error", False))
        payload["truncated"] = bool(getattr(result, "truncated", False))
    return payload


def _action_progress_payload(
    *,
    stage: str,
    state: str,
    label: str,
    draft: ActionDraft | None = None,
    policy_status: str | None = None,
) -> dict[str, Any]:
    tool_id = _action_draft_tool_id(draft) if draft is not None else ACTION_TOOL_ID
    intent = _action_draft_intent(draft) if draft is not None else ACTION_INTENT
    payload: dict[str, Any] = {
        "stage": stage,
        "state": state,
        "label": label,
        "intent": intent,
        "tool_id": tool_id,
        "tool_ids": [tool_id],
    }
    if draft is not None:
        payload["draft_id"] = draft.draft_id
        payload["action_label"] = _action_draft_label(draft)
        payload["ready"] = draft.ready
        if isinstance(draft, FlightActionDraft):
            payload["mission_name"] = draft.mission_name
            payload["target_drone_ids"] = list(draft.target_drone_ids)
            if draft.post_actions:
                payload["sequence_id"] = draft.draft_id
                payload["step_count"] = 1 + len(draft.post_actions)
    if policy_status:
        payload["policy_status"] = policy_status
    return payload


def _sequence_progress_label(
    fallback: str,
    *,
    step_label: str = "",
    step_index: int | None = None,
    step_count: int | None = None,
    activity: str = "",
) -> str:
    label = str(step_label or "").strip()
    action = str(activity or "").strip()
    if label and step_index and step_count:
        suffix = f" - {action}" if action else ""
        return f"Step {step_index}/{step_count}: {label}{suffix}"
    if label and action:
        return f"{label} - {action}"
    if label:
        return label
    return fallback


def _sequence_progress_fields(
    *,
    sequence_id: str = "",
    step_index: int | None = None,
    step_count: int | None = None,
    step_label: str = "",
    step_kind: str = "",
    command_id: str = "",
    mission_name: str = "",
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if sequence_id:
        fields["sequence_id"] = sequence_id
    if step_index is not None:
        fields["step_index"] = step_index
    if step_count is not None:
        fields["step_count"] = step_count
    if step_label:
        fields["step_label"] = step_label
    if step_kind:
        fields["step_kind"] = step_kind
    if command_id:
        fields["command_id"] = command_id
    if mission_name:
        fields["mission_name"] = mission_name
    return fields


def _monitor_heartbeat_progress_payload(
    *,
    started_at: float,
    observed_at: float,
    label: str,
    latest_evidence: Mapping[str, Any],
    sequence_id: str = "",
    step_index: int | None = None,
    step_count: int | None = None,
    step_label: str = "",
    step_kind: str = "",
) -> dict[str, Any]:
    return {
        "stage": "monitor",
        "state": "running",
        "progress_kind": "heartbeat",
        "label": label[:160],
        "observed_at": utc_now().isoformat(),
        "elapsed_seconds": round(max(0.0, observed_at - started_at), 1),
        "current_step": {
            "index": int(step_index or 0),
            "count": int(step_count or 0),
            "label": str(step_label or "")[:160],
            "kind": str(step_kind or "")[:80],
        },
        "latest_evidence": dict(latest_evidence),
        **_sequence_progress_fields(
            sequence_id=sequence_id,
            step_index=step_index,
            step_count=step_count,
            step_label=step_label,
            step_kind=step_kind,
        ),
    }


def _submitted_action_progress_outcome(
    draft: ActionDraft,
    *,
    monitor_result: Mapping[str, Any] | None = None,
    post_action_results: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, str]:
    is_flight = isinstance(draft, FlightActionDraft)
    if not monitor_result:
        return (
            (
                "requested",
                "GCS accepted command sequence" if is_flight else "GCS accepted action sequence",
            )
            if draft.monitor_requested
            else ("complete", "GCS accepted action submission")
        )
    completion_verification = (
        monitor_result.get("completion_verification")
        if isinstance(monitor_result.get("completion_verification"), Mapping)
        else None
    )
    if completion_verification and not completion_verification.get("verified"):
        lifecycle = str(completion_verification.get("kind") or "").casefold() == "sitl_lifecycle"
        if str(completion_verification.get("status") or "").casefold() == "timeout":
            return (
                ("timeout", "SITL readiness verification timed out")
                if lifecycle
                else ("timeout", "Final disarm verification timed out")
            )
        if draft.post_actions:
            return (
                ("failed", "SITL readiness was not verified; dependent steps were not run")
                if lifecycle
                else ("failed", "Final landed state was not verified; dependent steps were not run")
            )
        return (
            ("failed", "SITL operation completed; readiness was not verified")
            if lifecycle
            else ("failed", "Command completed; final landed state was not verified")
        )

    if monitor_result.get("timed_out"):
        return (
            "timeout",
            "Command sequence monitoring timed out" if is_flight else "Action sequence monitoring timed out",
        )
    if not monitor_result.get("success"):
        return (
            "failed",
            "Command sequence stopped after primary command"
            if is_flight
            else "Action sequence stopped after the primary step",
        )

    if not draft.post_actions:
        return "complete", "Command complete" if is_flight else "Action complete"

    results = tuple(post_action_results)
    if len(results) < len(draft.post_actions):
        return (
            "failed",
            "Command sequence stopped before all steps completed"
            if is_flight
            else "Action sequence stopped before all steps completed",
        )
    if any(str(item.get("status") or "").casefold() in {"timeout", "timed_out"} for item in results):
        return (
            "timeout",
            "Command sequence monitoring timed out" if is_flight else "Action sequence monitoring timed out",
        )
    if any(bool(item.get("is_error")) for item in results):
        return (
            "failed",
            "Command sequence stopped before all steps completed"
            if is_flight
            else "Action sequence stopped before all steps completed",
        )
    return (
        "complete",
        "Command sequence complete" if is_flight else "Action sequence complete",
    )


def _action_run_terminal_outcome(
    *,
    action_execution: str,
    monitor_result: Mapping[str, Any] | None,
    post_action_results: Sequence[Mapping[str, Any]],
    cancelled: bool,
    total_steps: int,
    terminal_evidence_required: bool,
) -> tuple[str, str]:
    """Reduce execution evidence to one truthful durable-run terminal state."""

    monitor = monitor_result if isinstance(monitor_result, Mapping) else {}
    if cancelled:
        incomplete_statuses = {
            "",
            "cancelled",
            "executing",
            "monitor_error",
            "queued",
            "running",
            "submitted",
            "timed_out",
            "timeout",
        }
        monitor_status = str(monitor.get("status") or "").strip().casefold()
        post_statuses = {
            str(item.get("status") or "").strip().casefold()
            for item in post_action_results
            if str(item.get("status") or "").strip().casefold() != "cancelled"
        }
        drain_incomplete = bool(
            (terminal_evidence_required and (not monitor or monitor.get("timed_out")))
            or (bool(monitor) and monitor_status in incomplete_statuses)
            or post_statuses.intersection(incomplete_statuses)
        )
        if drain_incomplete:
            return (
                "failed",
                "Remaining steps were cancelled, but the dispatched step did not reach a verified terminal state.",
            )
        return (
            "cancelled",
            "Cancellation completed at a safe step boundary; every dispatched command or SITL operation reached terminal state, and no later step was dispatched.",
        )
    completion = monitor.get("completion_verification")
    if isinstance(completion, Mapping) and not bool(completion.get("verified")):
        return "failed", str(
            completion.get("summary")
            or "The final landed/RTL state was not verified; dependent steps were not dispatched."
        )
    monitor_status = str(monitor.get("status") or "").strip().casefold()
    monitor_failed = bool(
        monitor
        and (
            monitor.get("success") is False
            or monitor_status
            in {
                "blocked",
                "cancelled",
                "completion_unverified",
                "error",
                "failed",
                "failure",
                "monitor_error",
                "rejected",
                "terminal_non_success",
                "timeout",
            }
        )
    )
    post_failed = any(bool(item.get("is_error")) for item in post_action_results)
    if action_execution == "submitted" and terminal_evidence_required and not monitor:
        return "failed", "The action was accepted, but no terminal completion evidence was recorded."
    if monitor_failed:
        monitor_summary = str(
            monitor.get("detail")
            or monitor.get("summary")
            or monitor.get("message")
            or ""
        ).strip()
        if monitor_summary:
            return "failed", monitor_summary[:1000]
    if post_failed:
        failed_step = next(
            (item for item in post_action_results if bool(item.get("is_error"))),
            {},
        )
        failed_label = str(failed_step.get("label") or "Action step").strip()
        failed_summary = str(failed_step.get("summary") or "").strip()
        if failed_summary:
            return "failed", f"{failed_label}: {failed_summary}"[:1000]
    if action_execution != "submitted" or monitor_failed or post_failed:
        return "failed", "The action run stopped before every planned step succeeded."
    return "succeeded", f"Completed {total_steps} of {total_steps} planned steps."


def _action_draft_tool_id(draft: ActionDraft) -> str:
    return ACTION_TOOL_ID if isinstance(draft, FlightActionDraft) else draft.tool_id


def _action_draft_intent(draft: ActionDraft) -> str:
    return ACTION_INTENT if isinstance(draft, FlightActionDraft) else draft.intent


def _action_draft_label(draft: ActionDraft) -> str:
    if isinstance(draft, FlightActionDraft):
        return {
            "TAKE_OFF": "takeoff",
            "RETURN_RTL": "return rtl",
            "PRECISION_MOVE": "precision move",
        }.get(draft.mission_name, draft.mission_name.replace("_", " ").lower())
    return draft.action_label


def _action_draft_payload(draft: ActionDraft) -> dict[str, Any]:
    if isinstance(draft, FlightActionDraft):
        payload = dict(draft.command_payload)
    else:
        payload = dict(draft.arguments)
    if draft.wait_condition:
        payload["wait_condition"] = draft.wait_condition
    if draft.post_actions:
        payload["post_actions"] = [dict(item) for item in draft.post_actions]
    return payload


def _format_metric_meters(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:g} m"


def _precision_translation_summary(translation: Any) -> str:
    if not isinstance(translation, Mapping):
        return "movement details unavailable"
    parts: list[str] = []
    axis_labels = (
        ("north", "north", "south"),
        ("east", "east", "west"),
        ("up", "up", "down"),
    )
    for axis, positive_label, negative_label in axis_labels:
        raw_value = translation.get(axis)
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if abs(value) <= 1e-9:
            continue
        label = positive_label if value > 0 else negative_label
        parts.append(f"{abs(value):g} m {label}")
    return ", ".join(parts) if parts else "hold position / no translation"


def _flight_payload_step_label(payload: Mapping[str, Any], *, fallback: str = "flight command") -> str:
    mission_type = payload.get("mission_type")
    mission_name = str(payload.get("mission_name") or "").strip().upper()
    label = {
        10: "Take off",
        101: "Land",
        104: "Return to launch",
        112: "Precision move",
        "TAKE_OFF": "Take off",
        "LAND": "Land",
        "RETURN_RTL": "Return to launch",
        "PRECISION_MOVE": "Precision move",
    }.get(mission_type, {
        "TAKE_OFF": "Take off",
        "LAND": "Land",
        "RETURN_RTL": "Return to launch",
        "PRECISION_MOVE": "Precision move",
    }.get(mission_name, fallback.replace("_", " ").strip().title() or "Flight command"))
    if mission_type == 10 or mission_name == "TAKE_OFF":
        altitude = _format_metric_meters(payload.get("takeoff_altitude"))
        return f"{label} to {altitude}" if altitude else label
    if mission_type == 112 or mission_name == "PRECISION_MOVE":
        precision_move = payload.get("precision_move") if isinstance(payload.get("precision_move"), Mapping) else {}
        translation = precision_move.get("translation_m") if isinstance(precision_move, Mapping) else None
        return f"{label}: {_precision_translation_summary(translation)}"
    return label


def _action_draft_summary_lines(draft: ActionDraft) -> list[str]:
    lines: list[str] = []
    condition_labels = _action_precondition_display_labels(draft)
    if condition_labels:
        lines.append("Run only when:")
        lines.extend(f"- {label}" for label in condition_labels)
        lines.append("")
    lines.append("Mission plan:" if isinstance(draft, FlightActionDraft) else "Action plan:")
    if isinstance(draft, FlightActionDraft):
        lines.append(
            f"1. {_flight_payload_step_label(draft.command_payload, fallback=_action_draft_label(draft))} "
            f"for {_format_drone_targets(draft.target_drone_ids)}."
        )
        for index, item in enumerate(draft.post_actions, start=2):
            action_type = str(item.get("type") or "").strip().lower()
            if action_type == "delay":
                delay = item.get("delay_seconds")
                delay_text = f"{float(delay):g} second(s)" if isinstance(delay, (int, float)) else "the requested interval"
                lines.append(f"{index}. Wait {delay_text}.")
                continue
            arguments = item.get("arguments") if isinstance(item.get("arguments"), Mapping) else {}
            label = _flight_payload_step_label(arguments, fallback=str(item.get("action_label") or "flight command"))
            lines.append(f"{index}. {label} for {_format_drone_targets(draft.target_drone_ids)}.")
        if draft.monitor_requested:
            lines.append("- I will monitor each step and report its result.")
        return lines

    lines.append(f"1. {_action_draft_label(draft)}.")
    if draft.tool_id == SITL_CREATE_TOOL_ID:
        instance_id = draft.arguments.get("instance_id")
        if instance_id is not None:
            lines.append(f"- Requested instance: drone-{instance_id}.")
        ip_last_octet = draft.arguments.get("ip_last_octet")
        if ip_last_octet is not None:
            lines.append(f"- Requested IP last octet: {ip_last_octet}.")
        sync_flags: list[str] = []
        if draft.arguments.get("git_sync_enabled") is not None:
            sync_flags.append(f"git sync {'on' if draft.arguments.get('git_sync_enabled') else 'off'}")
        if draft.arguments.get("requirements_sync_enabled") is not None:
            sync_flags.append(
                f"requirements sync {'on' if draft.arguments.get('requirements_sync_enabled') else 'off'}"
            )
        if sync_flags:
            lines.append("- Startup sync: " + "; ".join(sync_flags) + ".")
    target_count = draft.arguments.get("target_count")
    instance_names = draft.arguments.get("instance_names")
    action = str(draft.arguments.get("action") or "").strip()
    if target_count is not None:
        lines.append(f"- Requested fleet target: {target_count} SITL instance(s).")
    if isinstance(instance_names, (list, tuple)) and instance_names:
        names = ", ".join(str(name) for name in instance_names)
        action_label = action or "apply lifecycle action to"
        lines.append(f"- Instance action: {action_label} {names}.")
    if draft.monitor_requested:
        lines.append("- I will monitor the operation and report the terminal result.")
    for index, item in enumerate(draft.post_actions, start=2):
        action_type = str(item.get("type") or "").strip().lower()
        if action_type == "delay":
            delay = item.get("delay_seconds")
            delay_text = f"{float(delay):g} second(s)" if isinstance(delay, (int, float)) else "the requested interval"
            lines.append(f"{index}. Wait {delay_text}.")
            continue
        arguments = item.get("arguments") if isinstance(item.get("arguments"), Mapping) else {}
        if str(item.get("tool_id") or "") == ACTION_TOOL_ID:
            label = _flight_payload_step_label(
                arguments,
                fallback=str(item.get("action_label") or "flight command"),
            )
        else:
            label = str(item.get("action_label") or item.get("tool_title") or "Run guarded action")
        lines.append(f"{index}. {label}.")
    return lines


def _action_draft_display_plan(draft: ActionDraft) -> dict[str, Any]:
    """Return a renderer-neutral operator plan from the canonical action draft."""

    steps: list[dict[str, Any]] = []
    conditions = [
        {
            "fact_id": condition.fact_id,
            "label": label,
            "operator": condition.operator,
            "expected": condition.expected,
        }
        for condition, label in zip(
            draft.preconditions,
            _action_precondition_display_labels(draft),
        )
    ]
    if isinstance(draft, FlightActionDraft):
        steps.append(
            {
                "index": 1,
                "kind": "flight_command",
                "label": _flight_payload_step_label(
                    draft.command_payload,
                    fallback=_action_draft_label(draft),
                ),
            }
        )
        for index, item in enumerate(draft.post_actions, start=2):
            action_type = str(item.get("type") or "").strip().lower()
            if action_type == "delay":
                delay = item.get("delay_seconds")
                label = (
                    f"Wait {float(delay):g} seconds"
                    if isinstance(delay, (int, float))
                    else "Wait"
                )
                kind = "wait"
            elif action_type == "registry_action":
                raw_label = str(
                    item.get("action_label")
                    or item.get("tool_title")
                    or "Run guarded system action"
                ).strip()
                label = raw_label[:1].upper() + raw_label[1:]
                kind = action_type
            else:
                arguments = item.get("arguments") if isinstance(item.get("arguments"), Mapping) else {}
                label = _flight_payload_step_label(
                    arguments,
                    fallback=str(item.get("action_label") or item.get("tool_title") or "flight command"),
                )
                kind = action_type or "action"
            steps.append({"index": index, "kind": kind, "label": label})
        return {
            "title": "Review flight plan",
            "target": _format_drone_targets(draft.target_drone_ids),
            "conditions": conditions,
            "steps": steps,
        }

    registry_label = str(draft.action_label or draft.tool_title or "Run guarded action").strip()
    registry_label = registry_label[:1].upper() + registry_label[1:]
    steps.append(
        {
            "index": 1,
            "kind": "system_action",
            "label": registry_label,
        }
    )
    for index, item in enumerate(draft.post_actions, start=2):
        action_type = str(item.get("type") or "").strip().lower()
        if action_type == "delay":
            delay = item.get("delay_seconds")
            label = f"Wait {float(delay):g} seconds" if isinstance(delay, (int, float)) else "Wait"
            kind = "wait"
        elif str(item.get("tool_id") or "") == ACTION_TOOL_ID:
            arguments = item.get("arguments") if isinstance(item.get("arguments"), Mapping) else {}
            label = _flight_payload_step_label(
                arguments,
                fallback=str(item.get("action_label") or "Flight command"),
            )
            kind = "flight_command"
        else:
            raw_label = str(item.get("action_label") or item.get("tool_title") or "Run guarded action").strip()
            label = raw_label[:1].upper() + raw_label[1:]
            kind = action_type or "system_action"
        steps.append({"index": index, "kind": kind, "label": label})
    return {
        "title": "Review action plan" if draft.post_actions else "Review system action",
        "target": str(draft.tool_title or "Guarded GCS operation"),
        "conditions": conditions,
        "steps": steps,
    }


def _action_precondition_display_labels(draft: ActionDraft) -> list[str]:
    labels: list[str] = []
    operator_labels = {
        "eq": "equals",
        "ne": "does not equal",
        "lt": "is less than",
        "lte": "is at most",
        "gt": "is greater than",
        "gte": "is at least",
    }
    for condition in draft.preconditions:
        label = str(condition.label or "").strip()
        if not label:
            fact_label = condition.fact_id.replace(".", " ").replace("_", " ")
            expected = json.dumps(condition.expected, ensure_ascii=False, default=str)
            label = (
                f"{fact_label} {operator_labels.get(condition.operator, condition.operator)} "
                f"{expected}"
            )
        labels.append(label[:240])
    return labels


def _precondition_observation_summary(
    evaluation: ActionPreconditionEvaluation,
) -> tuple[str, str]:
    observation = evaluation.observations[0] if evaluation.observations else None
    if observation is None:
        return "Requested action condition", "unavailable"
    label = (
        str(observation.precondition.label or "").strip()
        or str(observation.fact_title or observation.precondition.fact_id).strip()
    )
    observed = (
        json.dumps(observation.observed, ensure_ascii=False, default=str)
        if observation.observed is not None
        else "unavailable"
    )
    return label[:240], observed[:160]


async def _evaluate_draft_preconditions(
    execution_context: Request | InternalToolExecutionContext,
    *,
    draft: ActionDraft,
    registry: Any,
    policy: Any,
) -> ActionPreconditionEvaluation:
    async def read_fact(tool_id: str, arguments: dict[str, Any]) -> Any:
        return await execute_policy_allowed_read_only_tool(
            execution_context,
            name=tool_id,
            arguments=arguments,
            channel="agent",
            registry=registry,
            policy=policy,
        )

    return await evaluate_action_preconditions(
        draft.preconditions,
        facts=assistant_fact_map(registry),
        read_tool=read_fact,
    )


def _execution_guard_arguments(
    tool: ToolDefinition,
    evaluation: ActionPreconditionEvaluation,
) -> dict[str, Any]:
    """Materialize registered observations that narrow canonical execution."""

    raw_guards = (tool.assistant_action or {}).get("execution_guards")
    if not isinstance(raw_guards, Mapping) or evaluation.status != "met":
        return {}
    arguments: dict[str, Any] = {}
    for observation in evaluation.observations:
        guard = raw_guards.get(observation.precondition.fact_id)
        if not observation.met or not isinstance(guard, Mapping):
            continue
        argument = str(guard.get("argument") or "").strip()
        if argument:
            arguments[argument] = observation.observed
    return arguments


def _action_draft_summary_block(draft: ActionDraft) -> str:
    return "\n".join(_action_draft_summary_lines(draft))


def _pre_action_read_only_context_block(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    return f"Current status checked before drafting:\n{text}\n\n"


def _should_prepend_action_read_only_context(message: str, read_only_plan: Any) -> bool:
    """Detect mixed state-question plus action turns without slowing pure actions."""

    intent = str(getattr(read_only_plan, "intent", "") or "").strip()
    tool_ids = tuple(str(item) for item in getattr(read_only_plan, "tool_ids", ()) or ())
    if not intent or not tool_ids:
        return False
    text = " ".join(str(message or "").casefold().split())
    if not text:
        return False
    question_signal = any(
        signal in text
        for signal in (
            "?",
            "how many",
            "do we have",
            "what about",
            "is there",
            "are there",
            "check",
            "tell me",
            "first",
        )
    )
    state_signal = any(
        signal in text
        for signal in (
            "configured",
            "active",
            "running",
            "connected",
            "online",
            "ready",
            "healthy",
            "status",
            "sitl instance",
            "sitl instances",
            "fleet",
        )
    )
    conditional_readiness = "if" in text and any(signal in text for signal in ("ready", "healthy", "active", "running"))
    return state_signal and (question_signal or conditional_readiness)


def _should_prepend_sitl_lifecycle_read_only_context(message: str, draft: ActionDraft | None) -> bool:
    if not isinstance(draft, RegistryActionDraft) or draft.tool_id != SITL_BATCH_ACTION_TOOL_ID:
        return False
    text = " ".join(str(message or "").casefold().split())
    if not text:
        return False
    question_or_condition = any(signal in text for signal in ("?", "if ", "first", "check", "see", "look", "stale"))
    state_reference = any(
        signal in text
        for signal in (
            "sitl",
            "simulation",
            "simulator",
            "instance",
            "instances",
            "container",
            "containers",
            "only one",
            "single",
            "stale",
        )
    )
    return question_or_condition and state_reference


def _format_drone_targets(targets: tuple[str, ...] | list[str]) -> str:
    values = [str(item).strip() for item in targets if str(item).strip()]
    if not values:
        return "not selected"
    if len(values) == 1:
        return f"drone {values[0]}"
    return "drones " + ", ".join(values[:-1]) + f" and {values[-1]}"


def _compact_status_value(value: Any) -> str:
    if value is None:
        return "unknown"
    raw = getattr(value, "value", value)
    return str(raw or "unknown")


def _command_monitor_summary(status: Mapping[str, Any] | None) -> str:
    if not isinstance(status, Mapping):
        return "No command status was available from the tracker."
    progress = status.get("progress") if isinstance(status.get("progress"), Mapping) else {}
    label = progress.get("label") or progress.get("stage") or "command status"
    message = progress.get("message") or ""
    phase = _compact_status_value(status.get("phase"))
    outcome = _compact_status_value(status.get("outcome"))
    command_status = _compact_status_value(status.get("status"))
    parts = [f"status={command_status}", f"phase={phase}"]
    if outcome != "unknown":
        parts.append(f"outcome={outcome}")
    if label:
        parts.append(f"progress={label}")
    if message:
        parts.append(str(message))
    return "; ".join(parts)


def _command_monitor_terminal(status: Mapping[str, Any] | None) -> bool:
    if not isinstance(status, Mapping):
        return False
    phase = _compact_status_value(status.get("phase")).lower()
    command_status = _compact_status_value(status.get("status")).lower()
    return phase == COMMAND_TERMINAL_PHASE or command_status in COMMAND_TERMINAL_STATUSES


def _command_monitor_success(status: Mapping[str, Any] | None) -> bool:
    if not isinstance(status, Mapping):
        return False
    outcome = _compact_status_value(status.get("outcome")).lower()
    command_status = _compact_status_value(status.get("status")).lower()
    outcome_known = outcome != "unknown"
    status_known = command_status != "unknown"
    if outcome_known and status_known:
        return outcome in COMMAND_SUCCESS_OUTCOMES and command_status == "completed"
    if outcome_known:
        return outcome in COMMAND_SUCCESS_OUTCOMES
    return command_status == "completed"


def _operation_terminal(status: Mapping[str, Any] | None) -> bool:
    if not isinstance(status, Mapping):
        return False
    return _compact_status_value(status.get("status")).lower() in SITL_TERMINAL_STATUSES


def _operation_success(status: Mapping[str, Any] | None) -> bool:
    if not isinstance(status, Mapping):
        return False
    return _compact_status_value(status.get("status")).lower() in {"completed", "succeeded", "success"}


def _sitl_readiness_timeout_seconds() -> float:
    return _bounded_float_env(
        "MDS_AGENT_SITL_READY_TIMEOUT_SEC",
        ACTION_MONITOR_TIMEOUT_SECONDS,
        minimum=5.0,
        maximum=900.0,
    )


def _auth_context(request: Request) -> dict[str, Any]:
    return dict(getattr(request.state, "mds_auth_context", {}) or {})


def _auth_enabled(context: dict[str, Any]) -> bool:
    return bool(context and context.get("kind") not in {None, "disabled"})


def _auth_actor(context: dict[str, Any]) -> str:
    return str(context.get("username") or context.get("user") or "").strip()


def _resolve_actor(request: Request, requested_actor: str) -> str:
    context = _auth_context(request)
    if _auth_enabled(context):
        actor = _auth_actor(context)
    else:
        actor = requested_actor
    actor = str(actor or "").strip()
    if not actor:
        raise HTTPException(status_code=400, detail="Simurgh actor is required")
    return actor


def _auth_tool_role(request: Request) -> str:
    """Return the authenticated role used for policy-gated tool access."""

    context = _auth_context(request)
    if not _auth_enabled(context):
        return "admin"
    return str(context.get("role") or "").strip().lower()


def _require_actor_access(request: Request, actor: str) -> None:
    context = _auth_context(request)
    if not _auth_enabled(context):
        return
    if str(context.get("role") or "").lower() == "admin":
        return
    if _auth_actor(context) != actor:
        raise HTTPException(status_code=403, detail="Simurgh actor access denied")


def _require_external_assistant_provider_auth(request: Request, provider: str) -> None:
    if provider == "mock":
        return
    if _has_external_assistant_provider_auth(request):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "External Simurgh assistant providers require MDS auth and an authenticated "
            "operator/admin session or bearer token with agent, operator, or admin scope. "
            "Keep MDS_AGENT_PROVIDER=mock when MDS auth is disabled."
        ),
    )


def _has_external_assistant_provider_auth(request: Request) -> bool:
    context = _auth_context(request)
    if _auth_enabled(context):
        context_kind = str(context.get("kind") or "").lower()
        role = str(context.get("role") or "").lower()
        if context_kind == "session" and role in EXTERNAL_ASSISTANT_PROVIDER_SESSION_ROLES:
            return True
        if context_kind == "bearer":
            scopes = {str(scope).strip().lower() for scope in context.get("scopes", []) if str(scope).strip()}
            if not scopes.isdisjoint(EXTERNAL_ASSISTANT_PROVIDER_BEARER_SCOPES):
                return True
    return False


def _bounded_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    except TypeError as exc:
        raise HTTPException(status_code=400, detail="assistant metadata must be JSON serializable") from exc
    if len(encoded) > MAX_ASSISTANT_METADATA_BYTES:
        raise HTTPException(status_code=400, detail="assistant metadata exceeds max bytes")
    return dict(metadata)


def _bounded_context_resource_ids(context_resource_ids: list[str] | None) -> tuple[str, ...] | None:
    if not context_resource_ids:
        return None
    normalized = tuple(str(resource_id).strip() for resource_id in context_resource_ids if str(resource_id).strip())
    if len(normalized) > MAX_ASSISTANT_CONTEXT_RESOURCE_IDS:
        raise HTTPException(status_code=400, detail="assistant context_resource_ids exceeds max items")
    return normalized


def _turn_request_with_session(
    turn_request: SimurghAssistantTurnRequest,
    *,
    session_id: str | None,
) -> SimurghAssistantTurnRequest:
    if hasattr(turn_request, "model_copy"):
        return turn_request.model_copy(update={"session_id": session_id})
    return turn_request.copy(update={"session_id": session_id})


def _turn_request_with_message(
    turn_request: SimurghAssistantTurnRequest,
    *,
    message: str,
) -> SimurghAssistantTurnRequest:
    if hasattr(turn_request, "model_copy"):
        return turn_request.model_copy(update={"message": message})
    return turn_request.copy(update={"message": message})


def _semantic_rewrite_previous_action_summary(previous_action: Mapping[str, Any]) -> str:
    if not isinstance(previous_action, Mapping) or not previous_action:
        return ""
    parts: list[str] = []
    for key in (
        "tool_id",
        "action_type",
        "mission_name",
        "action_label",
        "operation_id",
        "command_id",
        "action_run_state",
        "action_run_summary",
    ):
        value = previous_action.get(key)
        if value is not None and str(value).strip():
            parts.append(f"{key}={str(value).strip()[:80]}")
    targets = structured_target_ids(previous_action)
    if targets:
        parts.append("targets=" + ",".join(targets[:8]))
        target_source = str(previous_action.get("target_inferred_from") or "").strip()
        if target_source:
            parts.append(f"target_source={target_source[:80]}")
    run_result = previous_action.get("action_run_result")
    if isinstance(run_result, Mapping):
        post_results = run_result.get("post_action_results")
        if isinstance(post_results, (list, tuple)):
            step_parts = []
            for item in post_results[:12]:
                if not isinstance(item, Mapping):
                    continue
                label = str(item.get("label") or item.get("tool_id") or item.get("type") or "step").strip()
                status = str(item.get("status") or "unknown").strip()
                step_parts.append(f"{label}:{status}")
            if step_parts:
                parts.append("steps=" + "|".join(step_parts))
    return "; ".join(parts)[:1200]


def _provider_action_tool_contracts(registry: Any) -> tuple[dict[str, Any], ...]:
    contracts: list[dict[str, Any]] = []
    for tool in registry.list_tools(exposure=ToolExposure.GUARDED):
        action_contract = tool.assistant_action
        if tool.boundary != "gcs" or tool.destructive or not action_contract:
            continue
        input_schema = dict(tool.input_schema or {})
        properties = input_schema.get("properties")
        if isinstance(properties, Mapping):
            internal_arguments = {
                str(name)
                for name, raw_schema in properties.items()
                if isinstance(raw_schema, Mapping)
                and raw_schema.get("x-simurgh-internal") is True
            }
            input_schema["properties"] = {
                str(name): dict(raw_schema)
                for name, raw_schema in properties.items()
                if str(name) not in internal_arguments
            }
            required = input_schema.get("required")
            if isinstance(required, list):
                input_schema["required"] = [
                    str(name)
                    for name in required
                    if str(name) not in internal_arguments
                ]
        contracts.append(
            {
                "id": tool.id,
                "title": tool.title,
                "description": tool.description,
                "input_schema": input_schema,
                "runtime_modes": list(tool.runtime_modes),
                "intent": str(action_contract.get("intent") or "registry_action"),
                "fixed_cardinality": action_contract.get("fixed_cardinality"),
                "monitor_kind": str(action_contract.get("monitor_kind") or "none"),
                "result_target_source": str(action_contract.get("result_target_source") or ""),
                "target_binding": dict(action_contract.get("target_binding") or {}),
            }
        )
    return tuple(contracts)


def _provider_action_tool_contract_map(
    contracts: tuple[Mapping[str, Any], ...],
) -> dict[str, dict[str, Any]]:
    """Return the local materialization contract for provider-selected tools."""

    result: dict[str, dict[str, Any]] = {}
    for contract in contracts:
        tool_id = str(contract.get("id") or "").strip()
        if not tool_id:
            continue
        input_schema = contract.get("input_schema")
        required = input_schema.get("required") if isinstance(input_schema, Mapping) else ()
        result[tool_id] = {
            "title": str(contract.get("title") or tool_id),
            "intent": str(contract.get("intent") or "registry_action"),
            "fixed_cardinality": contract.get("fixed_cardinality"),
            "monitor_kind": str(contract.get("monitor_kind") or "none"),
            "result_target_source": str(contract.get("result_target_source") or ""),
            "target_binding": dict(contract.get("target_binding") or {}),
            "required": tuple(str(item) for item in (required or ())),
            "input_schema": dict(input_schema or {}),
        }
    return result


def _provider_action_materialization_question(
    materialized: Any,
    action_plan: Any,
) -> str:
    """Turn a typed plan-materialization gap into one operator-facing question."""

    field_path = str(getattr(materialized, "field_path", "") or "").strip()
    field_name = field_path.rstrip(". ").rsplit(".", 1)[-1].replace("_", " ").strip()
    steps = tuple(getattr(action_plan, "steps", ()) or ())
    first_label = ""
    missing_target_value = False
    if steps:
        first_step = steps[0]
        first_label = str(getattr(first_step, "label", "") or "").strip().rstrip(".")
        first_arguments = getattr(first_step, "arguments", {})
        if isinstance(first_arguments, Mapping):
            missing_target_value = any(
                (
                    "target" in str(name).casefold()
                    or str(name).casefold().endswith("_names")
                )
                and value in (None, "", [])
                for name, value in first_arguments.items()
            )
    if missing_target_value or (
        field_name
        and (
            "target" in field_name.casefold()
            or " instance names" in f" {field_name.casefold()}"
        )
    ):
        if first_label:
            return f'Which target should I use for the "{first_label}" step?'
        return "Which target should I use for this action?"
    if field_name:
        return f"What value should I use for {field_name}?"
    return "I need one more detail before I can prepare this action. What should I use?"


def _semantic_rewrite_clarification_context(previous_context: Mapping[str, str]) -> str:
    if str(previous_context.get("last_domain") or "") != "clarification":
        return ""
    messages = _clarification_operator_messages(previous_context)
    question = " ".join(str(previous_context.get("last_assistant_content") or "").split()).strip()
    if not messages or not question:
        return ""
    prior = "\n".join(
        f"Operator message {index}: {message[:1000]}"
        for index, message in enumerate(messages, start=1)
    )
    return f"{prior[:4200]}\nClarification asked: {question[:500]}"


def _semantic_rewrite_grounding_messages(previous_context: Mapping[str, str]) -> tuple[str, ...]:
    """Return bounded prior operator text for semantic follow-up resolution."""

    if str(previous_context.get("last_domain") or "") == "clarification":
        return tuple(message[:4000] for message in _clarification_operator_messages(previous_context)[:4])
    return _recent_operator_messages(previous_context)


def _recent_operator_messages(previous_context: Mapping[str, str]) -> tuple[str, ...]:
    """Decode the private, bounded operator-message ring without exposing it."""

    raw = str(previous_context.get("recent_operator_messages") or "").strip()
    values: list[str] = []
    if raw:
        try:
            decoded = json.loads(raw)
        except ValueError:
            decoded = []
        if isinstance(decoded, list):
            values.extend(
                " ".join(str(item or "").split()).strip()[:4000]
                for item in decoded
                if str(item or "").strip()
            )
    if not values:
        fallback = " ".join(str(previous_context.get("last_user_message") or "").split()).strip()
        if fallback:
            values.append(fallback[:4000])
    return tuple(dict.fromkeys(values[-4:]))


def _clarification_operator_messages(previous_context: Mapping[str, str]) -> tuple[str, ...]:
    """Read the bounded root request and clarification replies from private session state."""

    raw = str(previous_context.get("clarification_operator_messages") or "").strip()
    values: list[str] = []
    if raw:
        try:
            decoded = json.loads(raw)
        except ValueError:
            decoded = []
        if isinstance(decoded, list):
            values.extend(
                " ".join(str(item or "").split()).strip()[:4000]
                for item in decoded
                if str(item or "").strip()
            )
    if not values:
        fallback = " ".join(str(previous_context.get("last_user_message") or "").split()).strip()
        if fallback:
            values.append(fallback[:4000])
    return tuple(values[-4:])


def _updated_clarification_operator_messages(
    previous_context: Mapping[str, str],
    current_message: str,
) -> str:
    values = list(_clarification_operator_messages(previous_context))
    current = " ".join(str(current_message or "").split()).strip()[:4000]
    if current and (not values or values[-1] != current):
        values.append(current)
    while len(values) > 4 or len(json.dumps(values, ensure_ascii=False)) > 5600:
        values.pop(0)
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _registry_plan_tool_ids(plan: Any) -> tuple[str, ...]:
    calls = getattr(plan, "tool_calls", ()) or ()
    return tuple(str(getattr(call.tool, "id", "") or "") for call in calls if str(getattr(call.tool, "id", "") or ""))


def _turn_intent_metadata_with_read_execution(
    metadata: Mapping[str, Any] | None,
    executed_tool_ids: Sequence[str],
) -> dict[str, Any]:
    payload = dict(metadata or {})
    resolution = payload.get("provider_read_plan_resolution")
    if not isinstance(resolution, Mapping):
        return payload
    executed = tuple(
        dict.fromkeys(
            str(tool_id or "").strip()
            for tool_id in executed_tool_ids
            if str(tool_id or "").strip()
        )
    )
    required_key = (
        "provider_tool_ids"
        if resolution.get("execution") == "provider_registry_plan"
        else "grounded_tool_ids"
    )
    required = tuple(
        str(tool_id or "").strip()
        for tool_id in resolution.get(required_key, ())
        if str(tool_id or "").strip()
    )
    payload["provider_read_plan_resolution"] = {
        **dict(resolution),
        "executed_tool_ids": list(executed),
        "missing_required_tool_ids": [
            tool_id for tool_id in required if tool_id not in executed
        ],
    }
    return payload


def _registry_plan_prefers_deterministic_state_summary(plan: Any) -> bool:
    return registry_read_tool_ids_have_operator_summary(_registry_plan_tool_ids(plan))


def _semantic_rewrite_is_safe_to_try(
    *,
    assistant_config: Any,
    request: Request,
    original_message: str,
    turn_intent: Any,
) -> bool:
    if assistant_config.provider == "mock":
        return False
    route = str(getattr(turn_intent, "route", "") or "")
    if route in SEMANTIC_REWRITE_TERMINAL_ROUTES:
        return False
    if route not in {"read_only", "action_draft", "provider_or_registry"}:
        return False
    if not _has_external_assistant_provider_auth(request):
        return False
    return True


def _is_authoritative_typed_read_only_intent(turn_intent: Any) -> bool:
    """Return whether the local parser owns this action-term read route.

    A status/readiness question may contain a configured action word (for
    example, "is drone 1 ready to takeoff?").  The action-word safety block is
    still correct for direct execution requests, but it must not suppress a
    typed local read route.  Keeping this predicate on the typed frame avoids
    adding language-specific aliases to the blocked-term policy.
    """

    if str(getattr(turn_intent, "route", "") or "") != "read_only":
        return False
    action = getattr(turn_intent, "action", None)
    read_only_plan = getattr(turn_intent, "read_only_plan", None)
    if action is None or read_only_plan is None:
        return False
    if bool(getattr(action, "has_action_request", False)):
        return False
    read_intent = str(getattr(read_only_plan, "intent", "") or "").strip()
    query_domain = str(
        getattr(read_only_plan, "query_domain", "") or ""
    ).strip()
    return bool(
        read_intent in AUTHORITATIVE_TYPED_ACTION_TERM_READ_INTENTS
        and query_domain == "fleet"
        and not bool(getattr(read_only_plan, "unclear", True))
        and is_safe_blocked_term_read_only_intent(
            str(getattr(turn_intent, "routing_message", "") or ""),
            read_intent,
        )
    )


def _should_accept_semantic_rewrite(
    *,
    initial_intent: Any,
    rewritten_intent: Any,
    semantic_rewrite: Any,
) -> bool:
    """Accept provider normalization only when it improves local typed routing."""

    if not getattr(semantic_rewrite, "usable_for_routing", False):
        return False
    route_hint = str(getattr(semantic_rewrite, "route_hint", "") or "")
    initial_route = str(getattr(initial_intent, "route", "") or "")
    rewritten_route = str(getattr(rewritten_intent, "route", "") or "")
    if route_hint in SEMANTIC_REWRITE_ACTION_HINTS and rewritten_route == "action_draft":
        initial_action = getattr(initial_intent, "action", None)
        rewritten_action = getattr(rewritten_intent, "action", None)
        initial_draft = getattr(initial_action, "draft", None)
        rewritten_draft = getattr(rewritten_action, "draft", None)
        if rewritten_draft is None:
            return False
        if route_hint == "draft_flight_action" and not isinstance(rewritten_draft, FlightActionDraft):
            return False
        if route_hint == "draft_sitl_lifecycle_action" and not isinstance(rewritten_draft, RegistryActionDraft):
            return False
        if not _semantic_rewrite_preserves_numeric_literals(
            str(getattr(initial_intent, "routing_message", "") or ""),
            str(getattr(rewritten_intent, "routing_message", "") or ""),
        ):
            return False
        if initial_draft is not None and not _semantic_rewrite_preserves_draft_facts(
            initial_draft,
            rewritten_draft,
        ):
            return False
        return True
    if rewritten_route in SEMANTIC_REWRITE_TERMINAL_ROUTES:
        if route_hint in SEMANTIC_REWRITE_ACTION_HINTS:
            return True
        return initial_route not in SEMANTIC_REWRITE_TERMINAL_ROUTES
    if route_hint == "read_status" and rewritten_route == "read_only":
        initial_read = getattr(initial_intent, "read_only_plan", None)
        rewritten_read = getattr(rewritten_intent, "read_only_plan", None)
        initial_intent_name = str(getattr(initial_read, "intent", "") or "")
        rewritten_intent_name = str(getattr(rewritten_read, "intent", "") or "")
        if initial_route != "read_only":
            return True
        if initial_intent_name in SEMANTIC_REWRITE_HELP_INTENTS and rewritten_intent_name not in SEMANTIC_REWRITE_HELP_INTENTS:
            return True
    return False


def _resolve_provider_plan_with_unique_runtime_context(
    semantic_rewrite: Any,
    *,
    original_message: str,
    grounding_messages: Sequence[str],
    previous_action: Mapping[str, Any],
    tool_contracts: Mapping[str, Mapping[str, Any]],
    fact_contracts: Mapping[str, Any],
) -> Any:
    """Resolve a target-only clarification from one structured live target.

    The provider remains responsible for language and ordered-plan semantics.
    This layer only proves that the unchanged, source-grounded plan becomes a
    ready immutable draft when bound to exactly one runtime target.
    """

    action_plan = getattr(semantic_rewrite, "action_plan", None)
    if (
        action_plan is None
        or not getattr(semantic_rewrite, "needs_clarification", False)
        or str(getattr(semantic_rewrite, "clarification_reason", "") or "")
        != "missing_runtime_context"
        or float(getattr(semantic_rewrite, "confidence", 0.0) or 0.0) < 0.62
    ):
        return semantic_rewrite
    runtime_targets = structured_target_ids(previous_action)
    if len(runtime_targets) != 1:
        return semantic_rewrite
    if not _provider_plan_has_exact_missing_target_binding(
        action_plan,
        runtime_targets=runtime_targets,
        tool_contracts=tool_contracts,
        fact_contracts=fact_contracts,
    ):
        return semantic_rewrite
    try:
        validate_provider_action_plan_source_coverage(
            action_plan,
            original_message=original_message,
            grounding_messages=grounding_messages,
            allowed_target_ids=runtime_targets,
            tool_contracts=tool_contracts,
        )
        unbound = build_action_draft_from_provider_plan(
            action_plan,
            draft_id="act-runtime-context-unbound-check",
            previous_action={},
            tool_contracts=tool_contracts,
            fact_contracts=fact_contracts,
        )
        materialized = build_action_draft_from_provider_plan(
            action_plan,
            draft_id="act-runtime-context-check",
            previous_action=previous_action,
            tool_contracts=tool_contracts,
            fact_contracts=fact_contracts,
        )
    except (TypeError, ValueError):
        return semantic_rewrite
    if unbound.accepted and unbound.draft is not None and unbound.draft.ready:
        return semantic_rewrite
    if not materialized.accepted or materialized.draft is None or not materialized.draft.ready:
        return semantic_rewrite
    if tuple(structured_target_ids(materialized.draft.public_payload())) != runtime_targets:
        return semantic_rewrite
    route_hint = (
        "draft_flight_action"
        if isinstance(materialized.draft, FlightActionDraft)
        else "draft_sitl_lifecycle_action"
    )
    notes = tuple(
        dict.fromkeys(
            (
                *tuple(getattr(semantic_rewrite, "notes", ()) or ()),
                "unique_structured_runtime_target_resolved_locally",
            )
        )
    )
    return replace(
        semantic_rewrite,
        route_hint=route_hint,
        needs_clarification=False,
        clarification_question="",
        clarification_reason="none",
        notes=notes,
    )


def _provider_plan_has_exact_missing_target_binding(
    action_plan: Any,
    *,
    runtime_targets: Sequence[str],
    tool_contracts: Mapping[str, Mapping[str, Any]],
    fact_contracts: Mapping[str, Any],
) -> bool:
    """Prove that runtime context fills a registry-declared action target slot."""

    missing_action_binding = False

    def binding_matches(
        binding: Mapping[str, Any] | None,
        arguments: Mapping[str, Any],
        *,
        action_binding: bool,
    ) -> bool:
        nonlocal missing_action_binding
        argument, expected_values = materialize_target_binding(binding, runtime_targets)
        if not argument or not expected_values:
            return True
        supplied = arguments.get(argument)
        if supplied in (None, "", []):
            if action_binding:
                missing_action_binding = True
            return True
        if not isinstance(supplied, (list, tuple)):
            return False
        actual_values = tuple(
            str(item).strip()
            for item in supplied
            if str(item).strip()
        )
        return actual_values == tuple(expected_values)

    for step in tuple(getattr(action_plan, "steps", ()) or ()):
        if str(getattr(step, "kind", "") or "") != "tool":
            continue
        contract = tool_contracts.get(str(getattr(step, "tool_id", "") or ""))
        arguments = getattr(step, "arguments", {})
        if (
            not isinstance(contract, Mapping)
            or not isinstance(arguments, Mapping)
            or not binding_matches(
                contract.get("target_binding"),
                arguments,
                action_binding=True,
            )
        ):
            return False

    for precondition in tuple(getattr(action_plan, "preconditions", ()) or ()):
        fact = fact_contracts.get(str(getattr(precondition, "fact_id", "") or ""))
        if fact is None:
            return False
        try:
            arguments = json.loads(
                str(getattr(precondition, "arguments_json", "{}") or "{}")
            )
        except (TypeError, ValueError):
            return False
        if (
            not isinstance(arguments, Mapping)
            or not binding_matches(
                getattr(fact, "target_binding", {}),
                arguments,
                action_binding=False,
            )
        ):
            return False
    return missing_action_binding


def _semantic_rewrite_draft_facts(draft: ActionDraft) -> tuple[tuple[str, str], ...]:
    """Return execution-critical typed facts in stable sequence order."""

    facts: list[tuple[str, str]] = []

    def append_fact(path: str, value: Any) -> None:
        if value in (None, ""):
            return
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = f"{float(value):g}"
        elif isinstance(value, (list, tuple)):
            rendered = json.dumps([str(item) for item in value], separators=(",", ":"))
        else:
            rendered = str(value).strip()
        if rendered:
            facts.append((path, rendered))

    def append_flight_payload(payload: Mapping[str, Any], *, prefix: str) -> None:
        try:
            mission_type = int(payload.get("mission_type"))
        except (TypeError, ValueError):
            mission_type = 0
        if mission_type > 0:
            append_fact(f"{prefix}.mission_type", mission_type)
        append_fact(f"{prefix}.target_drone_ids", payload.get("target_drone_ids") or ())
        append_fact(f"{prefix}.takeoff_altitude", payload.get("takeoff_altitude"))
        trigger_time = payload.get("trigger_time")
        if trigger_time not in (None, 0, 0.0, "0"):
            append_fact(f"{prefix}.trigger_time", trigger_time)
        precision_move = payload.get("precision_move")
        translation = precision_move.get("translation_m") if isinstance(precision_move, Mapping) else None
        if isinstance(precision_move, Mapping):
            append_fact(f"{prefix}.precision_move.frame", precision_move.get("frame"))
        if isinstance(translation, Mapping):
            for axis in ("north", "east", "up"):
                value = translation.get(axis)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    append_fact(f"{prefix}.precision_move.translation_m.{axis}", value)
        yaw = precision_move.get("yaw") if isinstance(precision_move, Mapping) else None
        if isinstance(yaw, Mapping):
            append_fact(
                f"{prefix}.precision_move.yaw.mode",
                yaw.get("mode") or "hold_current",
            )
            append_fact(f"{prefix}.precision_move.yaw.degrees", yaw.get("degrees"))
        elif isinstance(precision_move, Mapping):
            # SubmitCommandRequest supplies this runtime default. Treat an
            # omitted value and the canonical default as the same typed fact.
            append_fact(f"{prefix}.precision_move.yaw.mode", "hold_current")

    def append_sequence_tail(post_actions: Sequence[Mapping[str, Any]]) -> None:
        for index, item in enumerate(post_actions, start=1):
            prefix = f"steps[{index}]"
            item_type = str(item.get("type") or "").strip().casefold()
            append_fact(f"{prefix}.type", item_type)
            append_fact(f"{prefix}.condition", item.get("condition"))
            if item_type == "delay":
                delay = item.get("delay_seconds")
                if isinstance(delay, (int, float)) and not isinstance(delay, bool):
                    append_fact(f"{prefix}.delay_seconds", delay)
                continue
            append_fact(f"{prefix}.tool_id", item.get("tool_id"))
            append_fact(f"{prefix}.wait_condition", item.get("wait_condition"))
            append_fact(
                f"{prefix}.target_from_previous_result",
                bool(item.get("target_from_previous_result")),
            )
            arguments = item.get("arguments") if isinstance(item.get("arguments"), Mapping) else {}
            if str(item.get("tool_id") or "") == ACTION_TOOL_ID:
                append_flight_payload(arguments, prefix=prefix)
            else:
                clean_arguments = {
                    str(key): value
                    for key, value in arguments.items()
                    if str(key) not in {"idempotency_key", "operator_label"}
                }
                append_fact(
                    f"{prefix}.arguments",
                    json.dumps(clean_arguments, sort_keys=True, separators=(",", ":"), default=str),
                )

    if isinstance(draft, FlightActionDraft):
        append_fact("draft.type", "flight")
        append_fact("draft.target_drone_ids", draft.target_drone_ids)
        append_fact("draft.wait_condition", draft.wait_condition)
        append_flight_payload(draft.command_payload, prefix="steps[0]")
        append_sequence_tail(draft.post_actions)
        return tuple(facts)

    append_fact("draft.type", "registry")
    append_fact("draft.tool_id", draft.tool_id)
    append_fact("draft.wait_condition", draft.wait_condition)
    append_fact(
        "draft.arguments",
        json.dumps(dict(draft.arguments), sort_keys=True, separators=(",", ":"), default=str),
    )
    append_sequence_tail(draft.post_actions)
    return tuple(facts)


def _semantic_rewrite_preserves_draft_facts(initial: ActionDraft, rewritten: ActionDraft) -> bool:
    """Preserve a complete typed plan exactly; only fill incomplete drafts."""

    expected = _semantic_rewrite_draft_facts(initial)
    actual = _semantic_rewrite_draft_facts(rewritten)
    if initial.ready:
        return expected == actual
    if not expected:
        return True

    def split_facts(
        facts: Sequence[tuple[str, str]],
    ) -> tuple[set[tuple[str, str]], tuple[frozenset[tuple[str, str]], ...]]:
        draft_facts: set[tuple[str, str]] = set()
        step_facts: dict[int, set[tuple[str, str]]] = {}
        for path, value in facts:
            match = re.fullmatch(r"steps\[(\d+)]\.(.+)", path)
            if match is None:
                draft_facts.add((path, value))
                continue
            step_facts.setdefault(int(match.group(1)), set()).add(
                (match.group(2), value)
            )
        return draft_facts, tuple(
            frozenset(step_facts[index]) for index in sorted(step_facts)
        )

    expected_draft_facts, expected_steps = split_facts(expected)
    actual_draft_facts, actual_steps = split_facts(actual)
    if not expected_draft_facts.issubset(actual_draft_facts):
        return False

    # An incomplete deterministic parse is a safety hint, not the language
    # authority. Preserve every fact it did establish in order while allowing
    # a source-grounded semantic plan to restore intervening steps or fields.
    cursor = 0
    for actual_step in actual_steps:
        if expected_steps[cursor].issubset(actual_step):
            cursor += 1
            if cursor == len(expected_steps):
                return True
    return not expected_steps


def _action_draft_step_count(draft: ActionDraft) -> int:
    """Return the number of operator-visible ordered action steps."""

    return 1 + len(draft.post_actions)


def _action_draft_uses_sitl_lifecycle_resource(draft: ActionDraft) -> bool:
    """Return whether one immutable run reads or mutates SITL lifecycle state."""

    tool_ids = {_action_draft_tool_id(draft)}
    tool_ids.update(
        str(item.get("tool_id") or "").strip()
        for item in draft.post_actions
        if isinstance(item, Mapping)
    )
    if any(tool_id.startswith("mds.sitl.") for tool_id in tool_ids):
        return True
    return any(
        str(precondition.fact_id or "").startswith("sitl.")
        for precondition in draft.preconditions
    )


def _action_draft_resource_keys(
    draft: ActionDraft,
    *,
    registry,
) -> tuple[str, ...]:
    """Resolve durable action-run resources from registry metadata.

    Resource ownership is deliberately described by the tool registry rather
    than by action-name branches in the route. A sequence reserves every
    vehicle, SITL fleet, or named SITL instance it may touch before dispatch,
    so overlapping runs fail closed while independent targets can proceed.
    """

    steps: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(draft, FlightActionDraft):
        steps.append((ACTION_TOOL_ID, draft.command_payload))
    else:
        steps.append((draft.tool_id, draft.arguments))
    for item in draft.post_actions:
        if not isinstance(item, Mapping):
            continue
        tool_id = str(item.get("tool_id") or "").strip()
        arguments = item.get("arguments")
        if tool_id and isinstance(arguments, Mapping):
            steps.append((tool_id, arguments))

    resolved: set[str] = set()
    for tool_id, arguments in steps:
        try:
            tool = registry.require(tool_id)
        except (AgentRuntimeError, KeyError):
            continue
        bindings = tool.assistant_action.get("resource_bindings")
        if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
            continue
        for binding in bindings:
            if not isinstance(binding, Mapping):
                continue
            namespace = str(binding.get("namespace") or "").strip()
            if not namespace:
                continue
            raw_values: list[Any] = []
            argument_name = str(binding.get("argument") or "").strip()
            if argument_name:
                value = arguments.get(argument_name)
                if isinstance(value, (list, tuple, set, frozenset)):
                    raw_values.extend(value)
                elif value is not None:
                    raw_values.append(value)
            key = str(binding.get("key") or "").strip()
            if key:
                raw_values.append(key)
            value_template = str(binding.get("value_template") or "{value}")
            for raw_value in raw_values:
                value_text = str(raw_value or "").strip()
                if not value_text:
                    continue
                try:
                    rendered = value_template.format(
                        id=value_text,
                        value=value_text,
                    )
                except (IndexError, KeyError, ValueError):
                    rendered = value_text
                rendered = str(rendered).strip()
                if rendered:
                    resolved.add(f"{namespace}:{rendered}")
    return tuple(sorted(resolved))


def _semantic_rewrite_preserves_numeric_literals(original: str, rewritten: str) -> bool:
    """Reject numeric action facts introduced by provider normalization.

    The provider may translate or repair surrounding language, but an Arabic
    numeric literal in its routing text must already exist in the operator's
    request. Spelled-number interpretation remains reviewable at confirmation.
    """

    def literals(value: str) -> set[str]:
        normalized: set[str] = set()
        for match in re.finditer(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?", value):
            try:
                normalized.add(f"{float(match.group(0)):g}")
            except ValueError:
                continue
        return normalized

    source = literals(original)
    return not source or literals(rewritten).issubset(source)


def _extract_action_draft_id(message: str) -> str:
    match = re.search(r"\b(act-[0-9a-fA-F]{6,24})\b", str(message or ""))
    return match.group(1).lower() if match else ""


def _structured_action_control(turn_request: SimurghAssistantTurnRequest) -> tuple[str, str]:
    """Return a validated UI action control without interpreting user prose.

    Natural-language confirmation remains supported for external clients. The
    dashboard additionally sends this small protocol envelope so a localized
    button click does not depend on English parsing or provider routing.
    Actor/session/draft ownership is still checked by the normal pending-draft
    resolution below.
    """

    metadata = turn_request.metadata if isinstance(turn_request.metadata, dict) else {}
    intent = str(metadata.get("action_intent") or "").strip().lower()
    if intent not in {"confirm", "reject", "amend"}:
        return "", ""
    draft_id = _extract_action_draft_id(str(metadata.get("draft_id") or ""))
    if not draft_id:
        return "", ""
    return intent, draft_id


def _mcp_request_id(message: Any) -> str | int | None:
    if isinstance(message, dict):
        value = message.get("id")
        if isinstance(value, (str, int)) or value is None:
            return value
    return None


def _mcp_error(
    request_id: str | int | None,
    *,
    code: int,
    message: str,
    data: Any | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


def _mcp_result(request_id: str | int | None, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def _mcp_json_error(
    request_id: str | int | None,
    *,
    code: int,
    message: str,
    status_code: int = 200,
    data: Any | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=_mcp_error(request_id, code=code, message=message, data=data),
        headers=headers,
    )


def _require_mcp_bearer_scope(request: Request, request_id: str | int | None) -> JSONResponse | None:
    """Require agent/admin bearer scope when optional MDS auth is enabled."""

    context = _auth_context(request)
    if not _auth_enabled(context):
        if not is_mcp_auth_required():
            return None
        base_url = str(request.base_url).rstrip("/")
        return _mcp_json_error(
            request_id,
            code=JSONRPC_SERVER_ERROR,
            message="Simurgh MCP requires Authorization: Bearer with agent scope",
            status_code=401,
            data={
                "recovery_hint": (
                    "Enable MDS auth and use an API token with agent scope, "
                    "or set MDS_MCP_REQUIRE_AUTH=false only for isolated local development."
                )
            },
            headers={
                "WWW-Authenticate": mcp_bearer_challenge(
                    base_url,
                    error="invalid_token",
                    error_description="MCP requires a bearer token with agent scope.",
                )
            },
        )

    if not is_mcp_auth_required():
        return None

    base_url = str(request.base_url).rstrip("/")
    if context.get("kind") != "bearer":
        return _mcp_json_error(
            request_id,
            code=JSONRPC_SERVER_ERROR,
            message="Simurgh MCP requires Authorization: Bearer with agent scope",
            status_code=401,
            headers={
                "WWW-Authenticate": mcp_bearer_challenge(
                    base_url,
                    error="invalid_token",
                    error_description="MCP HTTP access requires a bearer token.",
                )
            },
        )

    token_scopes = {str(scope).strip().lower() for scope in context.get("scopes", []) if str(scope).strip()}
    required_scopes = set(mcp_required_scopes())
    if token_scopes.isdisjoint(required_scopes):
        return _mcp_json_error(
            request_id,
            code=JSONRPC_SERVER_ERROR,
            message="Simurgh MCP bearer token does not include a required scope",
            status_code=403,
            data={"required_scopes": sorted(required_scopes)},
            headers={
                "WWW-Authenticate": mcp_bearer_challenge(
                    base_url,
                    error="insufficient_scope",
                    error_description="MCP requires an agent-scoped bearer token.",
                )
            },
        )

    return None


def _mcp_prompt_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": MCP_PROMPT_COMPARE_MISSION_MODES,
            "title": "Compare MDS Mission Modes",
            "description": (
                "Compare QuickScout, Swarm Trajectory, and related MDS mission workflows "
                "using static operator docs before live state."
            ),
            "arguments": [
                {
                    "name": "question",
                    "description": "Operator wording to answer, if different from the default comparison.",
                    "required": False,
                }
            ],
            "_meta": {
                "ai.mds/resources": [
                    f"{MCP_RESOURCE_PREFIX}/context/mds.mission_planning_workspace",
                    f"{MCP_RESOURCE_PREFIX}/context/mds.quickscout",
                    f"{MCP_RESOURCE_PREFIX}/context/mds.swarm_trajectory",
                ],
                "ai.mds/execution": "none",
            },
        }
    ]


def _mcp_prompt_definition_names() -> set[str]:
    return {prompt["name"] for prompt in _mcp_prompt_definitions()}


def _mcp_embedded_context_message(
    resources: SimurghMcpResourceProvider,
    resource_id: str,
) -> dict[str, Any]:
    content = resources.read_resource(f"{MCP_RESOURCE_PREFIX}/context/{resource_id}")
    return {
        "role": "user",
        "content": {
            "type": "resource",
            "resource": content.as_mcp_content(),
        },
    }


def _mcp_get_prompt(
    name: str,
    *,
    arguments: dict[str, Any],
    resources: SimurghMcpResourceProvider,
) -> dict[str, Any]:
    if name not in _mcp_prompt_definition_names():
        raise KeyError(f"unknown Simurgh MCP prompt: {name}")
    question = str(arguments.get("question") or "Compare QuickScout and Swarm Trajectory mode.").strip()
    if not question:
        question = "Compare QuickScout and Swarm Trajectory mode."
    return {
        "description": "Compare MDS mission-planning modes from static operator documentation.",
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        f"Operator question: {question}\n\n"
                        "Answer from the embedded MDS operator docs. Treat this as a conceptual workflow comparison. "
                        "Do not inspect live swarm topology, telemetry, or show state unless the operator explicitly asks for current status."
                    ),
                },
            },
            _mcp_embedded_context_message(resources, "mds.mission_planning_workspace"),
            _mcp_embedded_context_message(resources, "mds.quickscout"),
            _mcp_embedded_context_message(resources, "mds.swarm_trajectory"),
        ],
    }


def _mcp_tool_input_schema(tool: ToolDefinition) -> dict[str, Any]:
    if tool.input_schema:
        return dict(tool.input_schema)
    return {"type": "object", "additionalProperties": False}


def _mcp_tool_definition(tool: ToolDefinition) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": tool.id,
        "title": tool.title,
        "description": tool.description,
        "inputSchema": _mcp_tool_input_schema(tool),
        "annotations": {
            "readOnlyHint": tool.read_only,
            "destructiveHint": tool.destructive,
            "idempotentHint": tool.read_only,
            "openWorldHint": False,
        },
        "_meta": {
            "ai.mds/risk_class": tool.risk_class.value,
            "ai.mds/boundary": tool.boundary,
            "ai.mds/required_role": tool.required_role,
            "ai.mds/route": {
                "method": tool.route_method,
                "path": tool.route_path,
            },
        },
    }
    if tool.output_schema:
        payload["outputSchema"] = dict(tool.output_schema)
    return payload


def _mcp_callable_tools() -> list[ToolDefinition]:
    return list(list_policy_allowed_read_only_tools(channel="mcp"))


async def _mcp_call_registry_tool(
    request: Request,
    *,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result = await execute_policy_allowed_read_only_tool(
        request,
        name=name,
        arguments=arguments,
        channel="mcp",
    )
    return result.as_mcp_result()


async def _handle_mcp_jsonrpc(
    message: Any,
    *,
    request: Request,
    resources: SimurghMcpResourceProvider,
) -> dict[str, Any] | None:
    if isinstance(message, list):
        return _mcp_error(
            None,
            code=JSONRPC_INVALID_REQUEST,
            message="JSON-RPC batching is not supported by this MCP endpoint",
        )
    if not isinstance(message, dict):
        return _mcp_error(None, code=JSONRPC_INVALID_REQUEST, message="JSON-RPC message must be an object")
    if message.get("jsonrpc") != JSONRPC_VERSION:
        return _mcp_error(_mcp_request_id(message), code=JSONRPC_INVALID_REQUEST, message="jsonrpc must be '2.0'")

    if "method" not in message and ("result" in message or "error" in message):
        return None

    method = message.get("method")
    if not isinstance(method, str) or not method:
        return _mcp_error(_mcp_request_id(message), code=JSONRPC_INVALID_REQUEST, message="method is required")

    has_id = "id" in message
    request_id = _mcp_request_id(message)
    raw_params = message.get("params", {})
    if raw_params is None:
        params = {}
    elif isinstance(raw_params, dict):
        params = raw_params
    else:
        return _mcp_error(request_id, code=JSONRPC_INVALID_PARAMS, message="params must be an object")

    if not has_id:
        return None

    if method == "initialize":
        requested_version = str(params.get("protocolVersion") or "")
        protocol_version = requested_version if requested_version == MCP_PROTOCOL_VERSION else MCP_PROTOCOL_VERSION
        return _mcp_result(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"prompts": {"listChanged": False}, "resources": {}, "tools": {"listChanged": False}},
                "serverInfo": mcp_server_info(),
                "instructions": mcp_server_instructions(),
            },
        )
    if method == "ping":
        return _mcp_result(request_id, {})
    if method == "prompts/list":
        return _mcp_result(request_id, {"prompts": _mcp_prompt_definitions()})
    if method == "prompts/get":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name:
            return _mcp_error(request_id, code=JSONRPC_INVALID_PARAMS, message="prompts/get requires params.name")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _mcp_error(request_id, code=JSONRPC_INVALID_PARAMS, message="prompts/get params.arguments must be an object")
        try:
            return _mcp_result(request_id, _mcp_get_prompt(name, arguments=arguments, resources=resources))
        except KeyError as exc:
            return _mcp_error(request_id, code=JSONRPC_INVALID_PARAMS, message=str(exc))
        except AgentRuntimeError as exc:
            return _mcp_error(request_id, code=JSONRPC_INTERNAL_ERROR, message=str(exc))
    if method == "resources/list":
        try:
            return _mcp_result(request_id, {"resources": resources.list_resources()})
        except AgentRuntimeError as exc:
            return _mcp_error(request_id, code=JSONRPC_INTERNAL_ERROR, message=str(exc))
    if method == "resources/templates/list":
        return _mcp_result(request_id, {"resourceTemplates": []})
    if method == "resources/read":
        uri = params.get("uri")
        if not isinstance(uri, str) or not uri:
            return _mcp_error(request_id, code=JSONRPC_INVALID_PARAMS, message="resources/read requires params.uri")
        try:
            content = resources.read_resource(uri)
        except KeyError as exc:
            return _mcp_error(request_id, code=JSONRPC_INVALID_PARAMS, message=str(exc))
        except PermissionError as exc:
            return _mcp_error(request_id, code=JSONRPC_INVALID_PARAMS, message=str(exc))
        except AgentRuntimeError as exc:
            return _mcp_error(request_id, code=JSONRPC_INTERNAL_ERROR, message=str(exc))
        return _mcp_result(request_id, {"contents": [content.as_mcp_content()]})

    if method == "tools/list":
        return _mcp_result(request_id, {"tools": [_mcp_tool_definition(tool) for tool in _mcp_callable_tools()]})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name:
            return _mcp_error(request_id, code=JSONRPC_INVALID_PARAMS, message="tools/call requires params.name")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return _mcp_error(request_id, code=JSONRPC_INVALID_PARAMS, message="tools/call params.arguments must be an object")
        return _mcp_result(request_id, await _mcp_call_registry_tool(request, name=name, arguments=arguments))

    return _mcp_error(request_id, code=JSONRPC_METHOD_NOT_FOUND, message=f"unsupported MCP method: {method}")


def create_simurgh_router(deps: Any | None = None) -> APIRouter:
    """Create the governed Simurgh GCS assistant and MCP router."""

    router = APIRouter(tags=["Simurgh Operator"])
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    history = AssistantHistoryStore.from_env(load_on_init=False)
    mcp_resources = SimurghMcpResourceProvider(sessions=sessions, audit=audit)
    assistant_actor_locks: dict[str, asyncio.Lock] = {}
    provider_call_semaphore = asyncio.Semaphore(
        _bounded_int_env(
            "MDS_AGENT_PROVIDER_MAX_CONCURRENCY",
            DEFAULT_PROVIDER_MAX_CONCURRENCY,
            minimum=1,
            maximum=32,
        )
    )
    # Durable resource leases serialize across processes. This lock protects
    # shared in-process SITL service state on the owning ASGI event loop.
    sitl_action_run_lock = asyncio.Lock()
    # Safety settings and the final policy check/dispatch form one in-process
    # critical section. Long preconditions and monitoring remain outside it.
    action_policy_dispatch_lock = asyncio.Lock()
    assistant_turn_tasks: set[asyncio.Task[Any]] = set()
    action_run_tasks: set[asyncio.Task[Any]] = set()
    configured_action_run_store = getattr(deps, "simurgh_action_run_store", None)
    action_runs = (
        configured_action_run_store
        if isinstance(configured_action_run_store, ActionRunStore)
        else ActionRunStore.from_env()
    )
    action_runner_id = f"runner-{uuid.uuid4().hex}"
    action_runner_lease_seconds = _bounded_int_env(
        "MDS_AGENT_ACTION_RUNNER_LEASE_SECONDS",
        DEFAULT_RUNNER_LEASE_SECONDS,
        minimum=MIN_RUNNER_LEASE_SECONDS,
        maximum=MAX_RUNNER_LEASE_SECONDS,
    )

    async def action_run_store_call(function: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        """Keep synchronous SQLite journal work off the GCS event loop."""

        return await asyncio.to_thread(function, *args, **kwargs)

    async def action_run_require_async(run_id: str) -> ActionRunSnapshot:
        return await action_run_store_call(action_runs.require, run_id)

    async def action_run_append_event_async(
        run_id: str,
        *,
        ownership: ActionRunOwnership | None = None,
        **kwargs: Any,
    ) -> Any:
        if ownership is not None:
            await action_run_renew_async(ownership)
        return await action_run_store_call(
            action_runs.append_event,
            run_id,
            ownership=ownership,
            **kwargs,
        )

    async def action_run_renew_async(ownership: ActionRunOwnership) -> ActionRunSnapshot:
        return await action_run_store_call(
            action_runs.renew_ownership,
            ownership,
            runner_lease_seconds=action_runner_lease_seconds,
        )

    async def action_run_cancel_requested_async(run_id: str) -> bool:
        if not run_id:
            return False
        try:
            run = await action_run_require_async(run_id)
        except (KeyError, ActionRunOwnershipError):
            return False
        return (
            run.state in {"cancel_requested", "cancelled"}
            or run.control_state == "cancel_requested"
        )

    async def run_blocking_provider_call(
        function: Callable[..., Any],
        /,
        *args: Any,
        finish_on_cancel: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Keep blocking provider SDK/HTTP work off the GCS event loop."""

        async with provider_call_semaphore:
            worker = asyncio.create_task(
                asyncio.to_thread(function, *args, **kwargs),
                name=f"simurgh-provider:{getattr(function, '__name__', 'call')}",
            )
            if not finish_on_cancel:
                return await worker
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                # The legacy general-turn path also commits session/audit state.
                # Keep the actor lock until that bounded worker has completed.
                await worker
                raise

    def retain_assistant_turn_task(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        """Keep a turn alive when an SSE subscriber disconnects mid-operation."""

        assistant_turn_tasks.add(task)
        task.add_done_callback(assistant_turn_tasks.discard)
        return task

    def retain_action_run_task(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        """Keep execution alive independently of an HTTP/SSE subscriber.

        Action orchestration remains on the ASGI loop because canonical GCS
        dependencies own asyncio primitives there. Durable ownership and the
        journal handle process-level interruption without cross-loop access.
        """

        action_run_tasks.add(task)

        def report_action_run_task_result(completed: asyncio.Task[Any]) -> None:
            action_run_tasks.discard(completed)
            if completed.cancelled():
                return
            try:
                error = completed.exception()
            except asyncio.CancelledError:
                return
            if error is not None:
                logger.error("Simurgh action-run task failed: %s", error, exc_info=error)

        task.add_done_callback(report_action_run_task_result)
        return task

    async def require_action_run_access(request: Request, run_id: str) -> ActionRunSnapshot:
        try:
            run = await action_run_require_async(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _require_actor_access(request, run.actor)
        return run

    @router.get("/api/v1/simurgh/action-runs")
    async def list_simurgh_action_runs(
        request: Request,
        actor: str | None = Query(default=None),
        session_id: str | None = Query(default=None),
        active_only: bool = Query(default=False),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        context = _auth_context(request)
        if _auth_enabled(context):
            actor_filter = _auth_actor(context)
        else:
            actor_filter = actor.strip() if actor else _resolve_actor(request, "operator")
        _require_actor_access(request, actor_filter)
        runs = await action_run_store_call(
            action_runs.list_runs,
            actor=actor_filter,
            session_id=session_id,
            active_only=active_only,
            limit=limit,
        )
        return {"runs": [run.public_payload() for run in runs]}

    @router.get("/api/v1/simurgh/action-runs/{run_id}")
    async def get_simurgh_action_run(request: Request, run_id: str):
        return (await require_action_run_access(request, run_id)).public_payload()

    @router.get("/api/v1/simurgh/action-runs/{run_id}/events")
    async def list_simurgh_action_run_events(
        request: Request,
        run_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        await require_action_run_access(request, run_id)
        return {
            "run_id": run_id,
            "events": [
                event.public_payload()
                for event in await action_run_store_call(
                    action_runs.list_events,
                    run_id,
                    after_id=after,
                    limit=limit,
                )
            ],
        }

    @router.get("/api/v1/simurgh/action-runs/{run_id}/events/stream")
    async def stream_simurgh_action_run_events(
        request: Request,
        run_id: str,
        after: int = Query(default=0, ge=0),
    ):
        await require_action_run_access(request, run_id)
        last_event_header = request.headers.get("last-event-id", "").strip()
        try:
            cursor = max(after, int(last_event_header)) if last_event_header else after
        except ValueError:
            cursor = after

        async def event_stream():
            nonlocal cursor
            keepalive_at = asyncio.get_running_loop().time() + 15.0
            while True:
                if await request.is_disconnected():
                    return
                events = await action_run_store_call(
                    action_runs.list_events,
                    run_id,
                    after_id=cursor,
                    limit=200,
                )
                for event in events:
                    cursor = event.id
                    yield _action_run_sse_event(event.id, event.event_type, event.public_payload())
                run = await action_run_require_async(run_id)
                if run.terminal and not events:
                    yield _action_run_sse_event(
                        cursor,
                        "run_snapshot",
                        {"run": run.public_payload(), "replay_complete": True},
                    )
                    return
                now = asyncio.get_running_loop().time()
                if now >= keepalive_at:
                    yield ": keepalive\n\n"
                    keepalive_at = now + 15.0
                await asyncio.sleep(0.5)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/v1/simurgh/action-runs/{run_id}/controls")
    async def control_simurgh_action_run(
        request: Request,
        run_id: str,
        control: SimurghActionRunControlRequest,
    ):
        run = await require_action_run_access(request, run_id)
        actor = _resolve_actor(request, control.actor)
        if actor != run.actor:
            raise HTTPException(status_code=403, detail="action run belongs to a different operator")
        try:
            updated = await action_run_store_call(
                action_runs.request_control,
                run_id,
                actor=actor,
                action=control.action,
                reason=control.reason,
                control_id=control.control_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return updated.public_payload()

    @router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
    async def get_mcp_protected_resource_metadata(request: Request):
        return mcp_protected_resource_metadata(str(request.base_url).rstrip("/"))

    @router.get("/.well-known/oauth-protected-resource/{resource_path:path}", include_in_schema=False)
    async def get_mcp_protected_resource_metadata_for_path(request: Request, resource_path: str):
        return mcp_protected_resource_metadata(str(request.base_url).rstrip("/"))

    @router.get("/api/v1/simurgh/status", response_model=SimurghStatusResponse)
    async def get_simurgh_status():
        try:
            policy = load_default_policy()
            registry = load_default_tool_registry()
            context_index = load_default_context_index()
            assistant_config = load_default_assistant_config()
            gcs_runtime = resolve_runtime_mode()
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        external_provider = assistant_config.provider != "mock"
        warnings: list[str] = []
        if policy.mode != gcs_runtime.mode:
            warnings.append(
                "Simurgh policy mode did not resolve to canonical MDS_MODE; verify runtime configuration before testing."
            )
        if gcs_runtime.mode == "real" and not policy.action_circuit_breaker_enabled:
            warnings.append(
                "GCS is in real mode and the Simurgh action circuit breaker is off."
            )
        return SimurghStatusResponse(
            agent_enabled=policy.agent_enabled,
            mcp_enabled=policy.mcp_enabled,
            gcs_mode=gcs_runtime.mode,
            gcs_mode_source=gcs_runtime.source,
            mode=policy.mode,
            action_circuit_breaker_enabled=policy.action_circuit_breaker_enabled,
            always_confirm_before_action=policy.always_confirm_before_action,
            actions_blocked=policy.action_circuit_breaker_enabled,
            action_policy_source="circuit_breaker_and_mds_mode",
            tool_registry_version=registry.version,
            tool_count=len(registry.tools),
            allowed_tool_count=len(registry.list_tools(exposure=ToolExposure.ALLOW)),
            guarded_tool_count=len(registry.list_tools(exposure=ToolExposure.GUARDED)),
            excluded_tool_count=len(registry.list_tools(exposure=ToolExposure.EXCLUDE)),
            context_resource_count=len(context_index.resources),
            active_session_count=len(sessions.list_sessions(include_closed=False)),
            audit_event_count=len(audit.list_events()),
            assistant_provider=assistant_config.provider,
            assistant_model=(
                assistant_config.openai.model
                if assistant_config.provider == "openai"
                else "mock-local"
            ),
            assistant_external_provider=external_provider,
            assistant_external_provider_auth_required=external_provider,
            policy_path=_display_path(policy.path),
            tool_registry_path=_display_path(registry.path),
            context_index_path=_display_path(context_index.path),
            warnings=warnings,
        )

    @router.get("/api/v1/simurgh/policy", response_model=SimurghPolicyResponse)
    async def get_simurgh_policy():
        try:
            policy = load_default_policy()
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return SimurghPolicyResponse(
            version=policy.version,
            agent_enabled=policy.agent_enabled,
            mcp_enabled=policy.mcp_enabled,
            mode=policy.mode,
            action_circuit_breaker_enabled=policy.action_circuit_breaker_enabled,
            always_confirm_before_action=policy.always_confirm_before_action,
            actions_blocked=policy.action_circuit_breaker_enabled,
            action_policy_source="circuit_breaker_and_mds_mode",
            allow_drone_api_exposure=policy.allow_drone_api_exposure,
            unknown_tool_policy=policy.unknown_tool_policy,
            approval_ttl_seconds=policy.approval_ttl_seconds,
            approval_required_risks=sorted(policy.approval_required_risks),
            runtime_modes={
                mode: SimurghRuntimeModePolicyResponse(
                    allowed_risks=sorted(mode_policy.allowed_risks),
                    denied_risks=sorted(mode_policy.denied_risks),
                    approval_required_risks=sorted(mode_policy.approval_required_risks),
                )
                for mode, mode_policy in sorted(policy.runtime_modes.items())
            },
        )

    @router.get("/api/v1/simurgh/runtime-settings")
    async def get_simurgh_runtime_settings():
        """Read compact hot-reloadable Simurgh settings for the dashboard."""

        try:
            return build_runtime_settings_payload()
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put("/api/v1/simurgh/runtime-settings")
    async def put_simurgh_runtime_settings(request: SimurghRuntimeSettingsRequest):
        """Persist and hot-apply Simurgh settings without restarting the whole GCS."""

        try:
            async with action_policy_dispatch_lock:
                return apply_runtime_settings(request.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HTTPException:
            raise
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/simurgh/provider-credentials")
    async def get_simurgh_provider_credentials():
        """Read redacted provider credential status for the dashboard."""

        try:
            return build_provider_credentials_payload()
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put("/api/v1/simurgh/provider-credentials")
    async def put_simurgh_provider_credentials(request: SimurghProviderCredentialsRequest):
        """Persist provider credentials in server-side secret files only."""

        try:
            return update_provider_credentials(request.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.delete("/api/v1/simurgh/provider-credentials")
    async def delete_simurgh_provider_credentials(request: SimurghProviderCredentialsDeleteRequest | None = None):
        """Delete managed provider credentials without exposing secret values."""

        try:
            return delete_provider_credentials(request.model_dump(exclude_none=True) if request else {})
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/simurgh/tools", response_model=SimurghToolListResponse)
    async def list_simurgh_tools(include_excluded: bool = Query(default=True)):
        try:
            registry = load_default_tool_registry()
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        tools = registry.list_tools()
        if not include_excluded:
            tools = [tool for tool in tools if tool.exposure is not ToolExposure.EXCLUDE]
        return SimurghToolListResponse(version=registry.version, tools=[_tool_response(tool) for tool in tools])

    @router.get("/api/v1/simurgh/tools/{tool_id}", response_model=SimurghToolResponse)
    async def get_simurgh_tool(tool_id: str):
        try:
            registry = load_default_tool_registry()
            tool = registry.get(tool_id)
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if tool is None:
            raise HTTPException(status_code=404, detail=f"unknown Simurgh tool: {tool_id}")
        return _tool_response(tool)

    @router.get("/api/v1/simurgh/tool-candidates", response_model=SimurghToolCandidateReviewResponse)
    async def list_simurgh_tool_candidates(
        eligible_read_only: bool | None = Query(default=None),
        risk_class: str | None = Query(default=None, max_length=64),
        search: str | None = Query(default=None, max_length=120),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        """Review generated OpenAPI candidates before MCP registry promotion.

        This endpoint is intentionally read-only. It reports what the generator
        discovered and whether a route already maps to a curated registry tool;
        it does not make any candidate callable.
        """

        try:
            artifact, artifact_path = load_default_tool_candidate_artifact()
            registry = load_default_tool_registry()
            return candidate_review_payload(
                artifact,
                artifact_path=artifact_path,
                registry=registry,
                eligible_read_only=eligible_read_only,
                risk_class=risk_class,
                search=search,
                limit=limit,
                offset=offset,
            )
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/simurgh/context", response_model=SimurghContextListResponse)
    async def list_simurgh_context_resources():
        try:
            index = load_default_context_index()
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        resources = [
            _context_resource_response(index, resource)
            for resource in index.resources.values()
            if resource.sensitivity == "public"
        ]
        return SimurghContextListResponse(version=index.version, resources=sorted(resources, key=lambda item: item.id))

    @router.get("/api/v1/simurgh/context/{resource_id}/markdown", response_class=Response)
    async def get_simurgh_context_resource_markdown(resource_id: str):
        try:
            index = load_default_context_index()
            resource = index.require(resource_id)
            if resource.sensitivity != "public":
                raise HTTPException(status_code=403, detail="context resource is not public")
            media_type = resource.mime_type if resource.mime_type.startswith("text/") else "text/plain"
            return Response(content=index.read_text(resource_id), media_type=media_type)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown context resource: {resource_id}") from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/simurgh/context/{resource_id}", response_model=SimurghContextContentResponse)
    async def get_simurgh_context_resource(resource_id: str):
        try:
            index = load_default_context_index()
            resource = index.require(resource_id)
            if resource.sensitivity != "public":
                raise HTTPException(status_code=403, detail="context resource is not public")
            return SimurghContextContentResponse(
                resource=_context_resource_response(index, resource),
                content=index.read_text(resource_id),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown context resource: {resource_id}") from exc
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/api/v1/simurgh/sessions", response_model=SimurghSessionResponse)
    async def create_simurgh_session(http_request: Request, request: SimurghSessionCreateRequest):
        try:
            policy = load_default_policy()
            if not policy.agent_enabled:
                raise HTTPException(status_code=403, detail="Simurgh agent runtime is disabled")
            mode = request.mode or policy.mode
            if mode not in policy.runtime_modes:
                raise HTTPException(status_code=400, detail=f"unknown Simurgh mode: {mode}")
            actor = _resolve_actor(http_request, request.actor)
            session = sessions.create(actor=actor, mode=mode, metadata=_bounded_metadata(request.metadata))
            audit.record(
                "session_created",
                session_id=session.id,
                actor=session.actor,
                decision=PolicyDecisionStatus.ALLOW.value,
                metadata={"mode": session.mode},
            )
            return _session_response(session)
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/simurgh/sessions", response_model=SimurghSessionListResponse)
    async def list_simurgh_sessions(
        request: Request,
        include_closed: bool = Query(default=True),
        actor: str | None = Query(default=None),
    ):
        context = _auth_context(request)
        actor_filter = actor.strip() if actor else None
        if _auth_enabled(context) and str(context.get("role") or "").lower() != "admin":
            actor_filter = _auth_actor(context)
        if actor_filter:
            _require_actor_access(request, actor_filter)
        session_values = sessions.list_sessions(include_closed=include_closed)
        if actor_filter:
            session_values = [session for session in session_values if session.actor == actor_filter]
        return SimurghSessionListResponse(
            sessions=[_session_response(session) for session in session_values]
        )

    @router.delete("/api/v1/simurgh/sessions/{session_id}", response_model=SimurghSessionResponse)
    async def close_simurgh_session(request: Request, session_id: str):
        try:
            existing = sessions.require(session_id)
            _require_actor_access(request, existing.actor)
            session = sessions.close(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown Simurgh session: {session_id}") from exc
        audit.record(
            "session_closed",
            session_id=session.id,
            actor=session.actor,
            decision=PolicyDecisionStatus.ALLOW.value,
            metadata={"mode": session.mode},
        )
        return _session_response(session)

    @router.get("/api/v1/simurgh/audit", response_model=SimurghAuditListResponse)
    async def list_simurgh_audit_events(
        request: Request,
        session_id: str | None = Query(default=None),
        actor: str | None = Query(default=None),
    ):
        context = _auth_context(request)
        actor_filter = actor.strip() if actor else None
        if _auth_enabled(context) and str(context.get("role") or "").lower() != "admin":
            actor_filter = _auth_actor(context)
        if actor_filter:
            _require_actor_access(request, actor_filter)
        event_values = audit.list_events(session_id=session_id)
        if actor_filter:
            event_values = [event for event in event_values if event.actor == actor_filter]
        return SimurghAuditListResponse(
            events=[_audit_event_response(event) for event in event_values]
        )

    def _require_or_create_assistant_session(
        *,
        policy,
        actor: str,
        turn_request: SimurghAssistantTurnRequest,
    ) -> AgentSession:
        if turn_request.session_id:
            session = sessions.require(turn_request.session_id)
            if session.closed:
                raise AgentRuntimeError("assistant session is closed")
            if session.actor != actor:
                raise PermissionError("assistant session belongs to a different actor")
            return session

        session_mode = turn_request.mode or policy.mode
        if session_mode not in policy.runtime_modes:
            raise AgentRuntimeError(f"unknown Simurgh mode: {session_mode}")
        return sessions.create(
            actor=actor,
            mode=session_mode,
            metadata=_bounded_metadata(turn_request.metadata),
        )

    def _stored_action_draft(session_id: str | None) -> ActionDraft | None:
        if not session_id:
            return None
        try:
            context = sessions.get_private_context(session_id)
        except KeyError:
            return None
        raw_draft = context.get("last_action_draft")
        if not raw_draft:
            return None
        try:
            draft = action_draft_from_context_json(raw_draft)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        stored_id = context.get("last_action_draft_id")
        stored_hash = context.get("last_action_draft_hash")
        if stored_id and stored_id != draft.draft_id:
            return None
        if stored_hash and stored_hash != stable_payload_hash(draft.public_payload()):
            return None
        return draft if draft.ready else None

    def _action_run_previous_action_payload(run: ActionRunSnapshot) -> dict[str, Any]:
        plan = dict(run.plan)
        result = dict(run.result)
        payload = {
            **plan,
            "action_run_id": run.run_id,
            "action_run_state": run.state,
            "action_run_summary": run.summary,
            "action_run_result": result,
            "action_run_created_at": run.created_at,
            "action_run_updated_at": run.updated_at,
            "action_run_completed_at": run.completed_at,
        }
        action_response = (
            result.get("action_response")
            if isinstance(result.get("action_response"), Mapping)
            else {}
        )
        if action_response:
            payload.setdefault("command_id", action_response.get("command_id"))
            payload.setdefault("operation_id", action_response.get("operation_id"))
            payload.setdefault("mission_name", action_response.get("mission_name"))
            payload.setdefault("mission_type", action_response.get("mission_type"))
            payload.setdefault("target_drone_ids", action_response.get("target_drones"))
        for key in ("monitor_result", "post_action_results", "rejection_detail"):
            if key in result:
                payload[key] = result[key]
        return payload

    def _latest_action_run(
        *,
        actor: str,
        session_id: str | None,
    ) -> ActionRunSnapshot | None:
        if session_id:
            session_runs = action_runs.list_runs(session_id=session_id, limit=1)
            if session_runs and session_runs[0].actor == actor:
                return session_runs[0]
        actor_runs = action_runs.list_runs(actor=actor, limit=1)
        return actor_runs[0] if actor_runs else None

    def _stored_last_submitted_action(
        session_id: str | None,
        *,
        actor: str = "",
    ) -> dict[str, Any]:
        context: dict[str, str] = {}
        if session_id:
            try:
                context = sessions.get_private_context(session_id)
            except KeyError:
                context = {}
        payload: dict[str, Any] = {}
        raw_action = context.get("last_submitted_action")
        if raw_action:
            try:
                decoded = json.loads(raw_action)
            except (TypeError, ValueError, json.JSONDecodeError):
                decoded = {}
            if isinstance(decoded, Mapping):
                payload = dict(decoded)
        run_id = str(context.get("last_action_run_id") or payload.get("action_run_id") or "").strip()
        run: ActionRunSnapshot | None = None
        if run_id:
            try:
                run = action_runs.require(run_id)
            except KeyError:
                run = None
            if run is not None and actor and run.actor != actor:
                run = None
        if run is None and actor:
            run = _latest_action_run(actor=actor, session_id=session_id)
        if run is not None:
            payload.update(_action_run_previous_action_payload(run))
        return payload

    def _previous_action_with_live_single_target(
        http_request: Request,
        previous_action: Mapping[str, Any],
    ) -> dict[str, Any]:
        base = dict(previous_action or {})
        context_targets = _action_context_target_ids(base)
        live_target = _single_live_action_target_context(http_request)
        live_targets = _action_context_target_ids(live_target)
        if len(context_targets) == 1 and (
            not live_targets or context_targets == live_targets
        ):
            previous_source = str(base.get("target_inferred_from") or "").strip()
            if previous_source and previous_source != "previous_submitted_action":
                base["previous_target_inferred_from"] = previous_source
            base["target_inferred_from"] = "previous_submitted_action"
            return base
        if context_targets:
            if live_targets and context_targets != live_targets:
                for key in (
                    "target_drone_ids",
                    "target_drones",
                    "inferred_target_drone_ids",
                    "instance_names",
                    "instance_id",
                    "hw_id",
                    "target_inferred_from",
                ):
                    base.pop(key, None)
            return base
        if not live_target:
            return base
        return {**base, **live_target}

    def _previous_action_with_single_listed_sitl_target(
        http_request: Request,
        previous_action: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Bind an implicit lifecycle target only when one SITL instance exists."""

        base = dict(previous_action or {})
        if _action_context_target_ids(base):
            base.setdefault("target_inferred_from", "previous_submitted_action")
            return base
        names = _listed_sitl_instance_names(_request_scoped_deps(deps, http_request))
        if len(names) != 1:
            return base
        match = re.fullmatch(r"drone-(\d+)", names[0].strip(), flags=re.IGNORECASE)
        if not match:
            return base
        target = match.group(1)
        return {
            **base,
            "target_drone_ids": [target],
            "inferred_target_drone_ids": [target],
            "target_inferred_from": "single_listed_sitl_instance",
        }

    def _action_context_target_ids(action_context: Mapping[str, Any]) -> list[str]:
        return list(structured_target_ids(action_context))

    def _single_live_action_target_context(http_request: Request) -> dict[str, Any]:
        """Return one target from live runtime evidence, never configured inventory alone."""

        request_deps = _request_scoped_deps(deps, http_request)
        candidates: dict[str, set[str]] = {}

        def add_candidate(value: Any, source: str) -> None:
            target = _coerce_int_like_text(value)
            if target:
                candidates.setdefault(target, set()).add(source)

        for target in _live_fleet_presence_target_ids(request_deps):
            add_candidate(target, "single_live_fleet_presence")

        if len(candidates) != 1:
            return {}
        target, sources = next(iter(candidates.items()))
        source = "single_live_runtime_target"
        if len(sources) == 1:
            source = next(iter(sources))
        return {
            "target_drone_ids": [target],
            "inferred_target_drone_ids": [target],
            "target_inferred_from": source,
        }

    def _active_sitl_instance_target_ids(request_deps: Any) -> list[str]:
        try:
            service = getattr(request_deps, "sitl_control_service", None)
            if service is None:
                params = getattr(request_deps, "Params", None)
                if params is None:
                    return []
                from src.sitl_control_service import SitlControlService

                service = SitlControlService(params)
            response = service.list_instances()
        except Exception:
            return []
        raw_instances = _mapping_or_attr(response, "instances") or []
        if not isinstance(raw_instances, (list, tuple)):
            return []
        values: list[str] = []
        for instance in raw_instances:
            state = str(_mapping_or_attr(instance, "state") or _mapping_or_attr(instance, "status") or "").strip().lower()
            if state != "running":
                continue
            target = _coerce_int_like_text(_mapping_or_attr(instance, "hw_id"))
            if not target:
                name = str(_mapping_or_attr(instance, "name") or "").strip().lower()
                match = re.search(r"\bdrone-(\d+)\b", name)
                target = match.group(1) if match else ""
            if target and target not in values:
                values.append(target)
        return values

    def _listed_sitl_instance_names(request_deps: Any) -> list[str]:
        try:
            service = getattr(request_deps, "sitl_control_service", None)
            if service is None:
                params = getattr(request_deps, "Params", None)
                if params is None:
                    return []
                from src.sitl_control_service import SitlControlService

                service = SitlControlService(params)
            response = service.list_instances()
        except Exception:
            return []
        raw_instances = _mapping_or_attr(response, "instances") or []
        if not isinstance(raw_instances, (list, tuple)):
            return []
        values: list[str] = []
        for instance in raw_instances:
            name = str(
                _mapping_or_attr(instance, "name")
                or _mapping_or_attr(instance, "id")
                or _mapping_or_attr(instance, "container_name")
                or ""
            ).strip()
            if not name:
                instance_id = (
                    _coerce_int_like_text(_mapping_or_attr(instance, "hw_id"))
                    or _coerce_int_like_text(_mapping_or_attr(instance, "instance_id"))
                    or _coerce_int_like_text(_mapping_or_attr(instance, "pos_id"))
                )
                if instance_id:
                    name = f"drone-{instance_id}"
            if name and name not in values:
                values.append(name)
        return values

    def _action_draft_with_inferred_single_sitl_instance(
        http_request: Request,
        draft: ActionDraft | None,
    ) -> ActionDraft | None:
        if not isinstance(draft, RegistryActionDraft) or draft.tool_id != SITL_BATCH_ACTION_TOOL_ID:
            return draft
        if "instance_names" not in draft.missing_arguments:
            return draft
        names = _listed_sitl_instance_names(_request_scoped_deps(deps, http_request))
        if len(names) != 1:
            return draft
        arguments = dict(draft.arguments)
        arguments["instance_names"] = names
        missing_arguments = tuple(item for item in draft.missing_arguments if item != "instance_names")
        return replace(draft, arguments=arguments, missing_arguments=missing_arguments)

    def _live_fleet_presence_target_ids(request_deps: Any) -> list[str]:
        telemetry = _mapping_snapshot(getattr(request_deps, "telemetry_data_all_drones", {}) or {})
        telemetry_success_times = _mapping_snapshot(getattr(request_deps, "last_telemetry_time", {}) or {})
        heartbeats: Mapping[Any, Any] = {}
        getter = getattr(request_deps, "get_all_heartbeats", None)
        if callable(getter):
            try:
                heartbeats = _mapping_snapshot(getter() or {})
            except Exception:
                heartbeats = {}
        all_ids = {
            *(_coerce_int_like_text(key) for key in telemetry.keys()),
            *(_coerce_int_like_text(key) for key in heartbeats.keys()),
        }
        values: list[str] = []
        for target in sorted((item for item in all_ids if item), key=lambda item: int(item)):
            telemetry_row = _lookup_mapping_by_text_key(telemetry, target)
            heartbeat_row = _lookup_mapping_by_text_key(heartbeats, target)
            success_time = _lookup_mapping_by_text_key(telemetry_success_times, target)
            if _looks_live_for_action_target(
                target=target,
                telemetry_row=telemetry_row if isinstance(telemetry_row, Mapping) else {},
                heartbeat_row=heartbeat_row if isinstance(heartbeat_row, Mapping) else {},
                telemetry_success_time=success_time,
            ):
                values.append(target)
        return values

    def _configured_fleet_target_ids(request_deps: Any) -> list[str]:
        """Return canonical vehicle IDs from the active fleet source of truth."""

        loader = getattr(request_deps, "load_config", None)
        if not callable(loader):
            try:
                from config import load_config
            except ImportError:
                return []
            loader = load_config
        try:
            rows = loader()
        except Exception:
            return []
        if isinstance(rows, Mapping):
            rows = rows.get("drones") or []
        if not isinstance(rows, (list, tuple)):
            return []
        values: list[str] = []
        for row in rows:
            target = _coerce_int_like_text(_mapping_or_attr(row, "hw_id"))
            if target and target not in values:
                values.append(target)
        return values

    def _resolve_provider_read_targets(
        *,
        request_deps: Any,
        requested_targets: tuple[str, ...],
        grounding_messages: tuple[str, ...],
        action_context: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """Ground model-proposed read scope against local identity evidence.

        The model may interpret language, but it cannot invent the vehicle scope
        used by local tools. Context targets are already part of the bounded
        provider input; other targets must occur in operator text and exist in
        configured or live runtime state.
        """

        normalized_targets = tuple(
            dict.fromkeys(
                target
                for target in (_coerce_int_like_text(item) for item in requested_targets)
                if target
            )
        )
        if not normalized_targets:
            return (), (), ()

        context_targets = set(_action_context_target_ids(action_context))
        known_targets = {
            *_configured_fleet_target_ids(request_deps),
            *_active_sitl_instance_target_ids(request_deps),
            *_live_fleet_presence_target_ids(request_deps),
            *context_targets,
        }
        mentioned_targets = set(extract_numeric_tokens(grounding_messages))

        accepted: list[str] = []
        unknown_explicit: list[str] = []
        dropped_ungrounded: list[str] = []
        for target in normalized_targets:
            grounded = target in context_targets or target in mentioned_targets
            if not grounded:
                dropped_ungrounded.append(target)
            elif target not in known_targets:
                unknown_explicit.append(target)
            else:
                accepted.append(target)
        return tuple(accepted), tuple(unknown_explicit), tuple(dropped_ungrounded)

    def _looks_live_for_action_target(
        *,
        target: str,
        telemetry_row: Mapping[str, Any],
        heartbeat_row: Mapping[str, Any],
        telemetry_success_time: Any,
    ) -> bool:
        try:
            from params import Params
            from presence import build_presence_snapshot, resolve_presence_thresholds

            presence = build_presence_snapshot(
                hw_id=target,
                heartbeat=dict(heartbeat_row),
                telemetry=dict(telemetry_row),
                telemetry_success_time=telemetry_success_time,
                configured=True,
                now=time.time(),
                thresholds=resolve_presence_thresholds(Params),
            )
            return bool(presence.get("telemetry_recent"))
        except Exception:
            # Action target inference and terminal verification must fail
            # closed when the canonical presence evaluator is unavailable.
            return False

    def _mapping_snapshot(value: Any) -> dict[Any, Any]:
        if not isinstance(value, Mapping):
            return {}
        return dict(value)

    def _lookup_mapping_by_text_key(mapping: Mapping[Any, Any], target: str) -> Any:
        if target in mapping:
            return mapping[target]
        try:
            number = int(target)
        except (TypeError, ValueError):
            return None
        return mapping.get(number)

    def _mapping_or_attr(value: Any, name: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(name)
        return getattr(value, name, None)

    def _stored_last_action_request_message(session_id: str | None) -> str:
        if not session_id:
            return ""
        try:
            context = sessions.get_private_context(session_id)
        except KeyError:
            return ""
        return str(context.get("last_action_request_message") or "").strip()

    def _looks_like_previous_action_result_question(message: str) -> bool:
        normalized = " ".join(normalize_operator_query_text(message).casefold().split())
        if not normalized or len(normalized) > 360:
            return False
        retrospective = bool(
            re.search(
                r"\b(did|was|were|have|has)\b.{0,96}\b(you|it|that|this|sequence|action|command|step|steps)\b",
                normalized,
            )
            or re.search(r"\b(skipped?|included?|happened?|completed?|done)\b", normalized)
        )
        if not retrospective:
            return False
        return bool(
            re.search(
                r"\b(wait|waits|delay|between|sequence|step|steps|post[-\s]*action|take\s*off|takeoff|precision|move|rtl|land|command|action)\b",
                normalized,
            )
        )

    def _last_submitted_action_context(session_id: str | None) -> tuple[dict[str, Any], dict[str, str]]:
        if not session_id:
            return {}, {}
        try:
            context = sessions.get_private_context(session_id)
        except KeyError:
            return {}, {}
        raw_action = context.get("last_submitted_action")
        if not raw_action:
            return {}, context
        try:
            payload = json.loads(raw_action)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}, context
        return (dict(payload) if isinstance(payload, Mapping) else {}), context

    def _previous_action_summary_content(
        _question: str,
        action: Mapping[str, Any],
        context: Mapping[str, str],
        *,
        response_detail: str = "standard",
    ) -> str:
        if not action:
            return (
                "No submitted action is retained for this Simurgh session.\n\n"
                "No new action was executed."
            )
        run_result = action.get("action_run_result")
        if not isinstance(run_result, Mapping):
            run_result = action.get("result") if isinstance(action.get("result"), Mapping) else {}
        action_response = (
            run_result.get("action_response")
            if isinstance(run_result.get("action_response"), Mapping)
            else {}
        )
        action_type = str(action.get("action_type") or "action").strip()
        mission = str(action.get("mission_name") or action.get("action_label") or action.get("tool_id") or action_type).strip()
        command_id = str(
            action.get("command_id")
            or action.get("operation_id")
            or action_response.get("command_id")
            or action_response.get("operation_id")
            or action_response.get("id")
            or ""
        ).strip()
        targets = action.get("target_drone_ids")
        target_label = ", ".join(str(item) for item in targets or [] if str(item).strip()) or "-"
        monitor = action.get("monitor_result") if isinstance(action.get("monitor_result"), Mapping) else {}
        if not monitor and isinstance(run_result.get("monitor_result"), Mapping):
            monitor = run_result.get("monitor_result")
        raw_post_results = action.get("post_action_results") or run_result.get("post_action_results") or []
        post_results = [dict(item) for item in raw_post_results if isinstance(item, Mapping)]
        wait_results = [
            item
            for item in post_results
            if str(item.get("type") or "").lower() == "delay"
        ]
        run_state = str(action.get("action_run_state") or action.get("state") or "").strip()
        run_summary = str(action.get("action_run_summary") or "").strip()
        lead = "Last action run"
        if run_state:
            lead += f": {run_state}"
        if run_summary:
            lead += f" — {run_summary}"

        if str(response_detail or "").strip().casefold() == "brief":
            lines = [lead]
            target_text = f"; target(s): {target_label}" if target_label != "-" else ""
            lines.append(f"- Action: {mission}{target_text}.")
            if monitor:
                monitor_status = str(monitor.get("status") or "unknown")
                monitor_line = f"- Primary result: {monitor_status}"
                verification = monitor.get("completion_verification")
                if isinstance(verification, Mapping):
                    verified = verification.get("verified")
                    summary = str(
                        verification.get("summary")
                        or verification.get("detail")
                        or ""
                    ).strip()
                    if verified is not None:
                        monitor_line += f"; verified={bool(verified)}"
                    if summary:
                        monitor_line += f" — {summary[:220]}"
                lines.append(monitor_line + ".")
            if wait_results:
                completed_waits = sum(
                    str(item.get("status") or "").casefold() == "completed"
                    for item in wait_results
                )
                lines.append(
                    f"- Wait steps: {completed_waits}/{len(wait_results)} completed."
                )
            if post_results:
                compact_steps: list[str] = []
                for item in post_results[:8]:
                    label = str(
                        item.get("label") or item.get("tool_id") or "step"
                    ).strip()
                    status = str(item.get("status") or "unknown").strip()
                    verification = item.get("completion_verification")
                    verified_suffix = ""
                    if isinstance(verification, Mapping) and verification.get("verified") is not None:
                        verified_suffix = f", verified={bool(verification.get('verified'))}"
                    compact_steps.append(f"{label}: {status}{verified_suffix}")
                lines.append("- Sequence: " + " -> ".join(compact_steps) + ".")
            else:
                lines.append("- Detailed sequence results are not present in the durable action journal.")
            return "\n".join(lines)

        lines = [
            lead,
            "",
            f"- Primary action: {mission}",
            f"- Target(s): {target_label}",
        ]
        if command_id:
            lines.append(f"- Command/operation ID: `{command_id}`")
        if monitor:
            monitor_status = str(monitor.get("status") or "unknown")
            monitor_success = monitor.get("success")
            success_text = ""
            if monitor_success is not None:
                success_text = f", success={bool(monitor_success)}"
            lines.append(f"- Primary monitor: {monitor_status}{success_text}")
            verification = monitor.get("completion_verification")
            if isinstance(verification, Mapping):
                verified = verification.get("verified")
                summary = str(verification.get("summary") or verification.get("detail") or "").strip()
                verification_text = f"verified={bool(verified)}" if verified is not None else "verification recorded"
                if summary:
                    verification_text += f" — {summary}"
                lines.append(f"- Completion verification: {verification_text}")
        if wait_results:
            completed_waits = sum(str(item.get("status") or "").casefold() == "completed" for item in wait_results)
            lines.append(f"- Wait steps: {completed_waits}/{len(wait_results)} completed")
        if post_results:
            lines.append("- Sequence steps:")
            for item in post_results:
                label = str(item.get("label") or item.get("tool_id") or "post-action").strip()
                status = str(item.get("status") or "unknown").strip()
                summary = str(item.get("summary") or "").strip()
                verification = item.get("completion_verification")
                if isinstance(verification, Mapping):
                    verified = verification.get("verified")
                    detail = str(verification.get("summary") or verification.get("detail") or "").strip()
                    verification_text = f"verified={bool(verified)}" if verified is not None else "verification recorded"
                    summary = "; ".join(part for part in (summary, verification_text, detail) if part)
                suffix = f" ({summary})" if summary else ""
                lines.append(f"  - {label}: {status}{suffix}")
        else:
            lines.append("- No post-action result rows are present in the durable action journal.")
        lines.append("")
        lines.append("No new action was executed.")
        return "\n".join(lines)

    def _pending_action_summary_content(question: str, draft: ActionDraft) -> str:
        normalized_question = " ".join(str(question or "").casefold().split())
        payload = _action_draft_payload(draft)
        action_label = _action_draft_label(draft)
        wait_steps: list[Mapping[str, Any]] = []
        post_actions: list[Mapping[str, Any]] = []
        targets = "-"

        if isinstance(draft, FlightActionDraft):
            targets = _format_drone_targets(draft.target_drone_ids)
            post_actions = [dict(item) for item in draft.post_actions if isinstance(item, Mapping)]
            wait_steps = [
                item
                for item in post_actions
                if str(item.get("type") or "").lower() == "delay"
                or "wait" in str(item.get("action_label") or "").casefold()
            ]
        elif isinstance(draft, RegistryActionDraft):
            post_actions = [dict(item) for item in draft.post_actions if isinstance(item, Mapping)]
            wait_steps = [
                item
                for item in post_actions
                if str(item.get("type") or "").lower() == "delay"
            ]

        if "wait" in normalized_question or "delay" in normalized_question or "skipped" in normalized_question:
            if wait_steps:
                lead = "The pending draft includes the wait step. It has not been executed yet."
            else:
                lead = "I do not see a wait/delay step in the pending draft. It has not been executed."
        else:
            lead = "Here is the pending Simurgh action draft. It has not been executed yet."

        lines = [
            lead,
            "",
            f"- Draft ID: `{draft.draft_id}`",
            f"- Primary action: {action_label}",
        ]
        if isinstance(draft, FlightActionDraft):
            lines.append(f"- Target(s): {targets}")
            if payload.get("takeoff_altitude") is not None:
                lines.append(f"- Takeoff altitude: {payload.get('takeoff_altitude')} m")
        elif isinstance(draft, RegistryActionDraft):
            lines.append(f"- Tool: `{draft.tool_id}`")

        if post_actions:
            lines.append("- Planned sequence:")
            for item in post_actions:
                label = str(item.get("action_label") or item.get("tool_id") or "post-action").strip()
                if str(item.get("type") or "").lower() == "delay":
                    delay = item.get("delay_seconds")
                    lines.append(f"  - {label}: wait {delay:g}s" if isinstance(delay, (int, float)) else f"  - {label}")
                    continue
                arguments = item.get("arguments") if isinstance(item.get("arguments"), Mapping) else {}
                precision_move = arguments.get("precision_move") if isinstance(arguments, Mapping) else {}
                translation = precision_move.get("translation_m") if isinstance(precision_move, Mapping) else None
                if isinstance(translation, Mapping):
                    parts = [
                        f"{axis}={float(value):g}m"
                        for axis, value in translation.items()
                        if isinstance(value, (int, float)) and float(value) != 0.0
                    ]
                    suffix = f" ({', '.join(parts)})" if parts else ""
                    lines.append(f"  - {label}{suffix}")
                else:
                    lines.append(f"  - {label}")
        lines.append("")
        lines.append("No new action was executed.")
        return "\n".join(lines)

    async def _create_previous_action_summary_record(
        _http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        turn_intent_metadata: Mapping[str, Any] | None = None,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> AssistantTurnRecord:
        policy = load_default_policy()
        session = _require_or_create_assistant_session(policy=policy, actor=actor, turn_request=turn_request)
        _, context = _last_submitted_action_context(session.id)
        action = _stored_last_submitted_action(session.id, actor=actor)
        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "tool",
                "state": "complete",
                "label": "Checked previous action sequence",
                "intent": "action_history_summary",
                "tool_id": PREVIOUS_ACTION_EVIDENCE_TOOL_ID,
                "tool_ids": [PREVIOUS_ACTION_EVIDENCE_TOOL_ID],
            },
        )
        content = _previous_action_summary_content(turn_request.message, action, context)
        turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=READ_TOOL_MODEL,
            adapter_version=READ_TOOL_ADAPTER_VERSION,
            content=content,
            context_documents=(),
            blocked_intents=(),
            safety_notes=(
                "Answered from private Simurgh session action context.",
                "No GCS command, SITL operation, or provider tool call was executed.",
            ),
        )
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": "flight",
                "last_intent": "action_history_summary",
                "last_response_mode": "status",
            },
        )
        sessions.update_private_context(
            session.id,
            {
                "last_assistant_content": turn.content,
                "last_assistant_provider": turn.provider,
                "last_assistant_model": turn.model,
                "last_domain": "flight",
                "last_intent": "action_history_summary",
                "last_response_mode": "status",
                "last_user_message": turn_request.message,
                "last_routing_message": normalize_operator_query_text(turn_request.message),
                "last_tool_intent": "action_history_summary",
                "last_read_only_evidence": "",
            },
        )
        event = audit.record(
            "assistant_turn_created",
            session_id=session.id,
            actor=actor,
            tool_id=PREVIOUS_ACTION_EVIDENCE_TOOL_ID,
            decision="read_previous_action_context",
            payload={
                "message": turn_request.message.strip(),
                "has_previous_action": bool(action),
            },
            metadata={
                "provider": turn.provider,
                "model": turn.model,
                "adapter_version": turn.adapter_version,
                "mode": session.mode,
                "context_count": 0,
                "blocked_intent_count": 0,
                "tool_intent": "action_history_summary",
                "tool_id": PREVIOUS_ACTION_EVIDENCE_TOOL_ID,
                "tool_ids": [PREVIOUS_ACTION_EVIDENCE_TOOL_ID],
                "response_mode": "status",
                "query_domain": "flight",
                "query_confidence": 1.0,
                "query_unclear": False,
                "query_reason": "previous_action_history_question",
                "turn_intent": dict(turn_intent_metadata or {}),
                "retrieved_context_count": 0,
                "web_search_enabled": False,
                "action_execution": "previous_action_summary",
                "policy_decision": "read_private_session_context",
                "policy_reasons": [],
                "circuit_breaker_layer": "not applicable; this was a local session-context read",
            },
        )
        return AssistantTurnRecord(session=session, turn=turn, audit_event=event)

    async def _create_pending_action_summary_record(
        _http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        draft: ActionDraft,
        turn_intent_metadata: Mapping[str, Any] | None = None,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> AssistantTurnRecord:
        policy = load_default_policy()
        session = _require_or_create_assistant_session(policy=policy, actor=actor, turn_request=turn_request)
        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "tool",
                "state": "complete",
                "label": "Checked pending action draft",
                "intent": "pending_action_summary",
                "tool_id": _action_draft_tool_id(draft),
                "tool_ids": [_action_draft_tool_id(draft)],
                "draft_id": draft.draft_id,
            },
        )
        content = _pending_action_summary_content(turn_request.message, draft)
        turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=ACTION_MODEL,
            adapter_version=ACTION_ADAPTER_VERSION,
            content=content,
            context_documents=(),
            blocked_intents=(),
            safety_notes=(
                "Answered from private Simurgh session pending-action context.",
                "No GCS command, SITL operation, or provider tool call was executed.",
            ),
        )
        action_domain = "flight" if isinstance(draft, FlightActionDraft) else "sitl"
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": action_domain,
                "last_intent": "pending_action_summary",
                "last_response_mode": "status",
            },
        )
        sessions.update_private_context(
            session.id,
            {
                "last_assistant_content": turn.content,
                "last_assistant_provider": turn.provider,
                "last_assistant_model": turn.model,
                "last_domain": action_domain,
                "last_intent": "pending_action_summary",
                "last_response_mode": "status",
                "last_user_message": turn_request.message,
                "last_routing_message": normalize_operator_query_text(turn_request.message),
                "last_tool_intent": "pending_action_summary",
                "last_read_only_evidence": "",
            },
        )
        event = audit.record(
            "assistant_turn_created",
            session_id=session.id,
            actor=actor,
            tool_id=_action_draft_tool_id(draft),
            decision="read_pending_action_context",
            payload={
                "message": turn_request.message.strip(),
                "action_draft": draft.public_payload(),
            },
            metadata={
                "provider": turn.provider,
                "model": turn.model,
                "adapter_version": turn.adapter_version,
                "mode": session.mode,
                "context_count": 0,
                "blocked_intent_count": 0,
                "tool_intent": "pending_action_summary",
                "tool_id": _action_draft_tool_id(draft),
                "tool_ids": [_action_draft_tool_id(draft)],
                "response_mode": "status",
                "query_domain": action_domain,
                "query_confidence": 1.0,
                "query_unclear": False,
                "query_reason": "pending_action_history_question",
                "turn_intent": dict(turn_intent_metadata or {}),
                "retrieved_context_count": 0,
                "web_search_enabled": False,
                "action_execution": "pending_action_summary",
                "action_draft": draft.public_payload(),
                "policy_decision": "read_private_session_context",
                "policy_reasons": [],
                "circuit_breaker_layer": "not applicable; this was a local session-context read",
            },
        )
        return AssistantTurnRecord(session=session, turn=turn, audit_event=event)

    def _recent_pending_action_drafts_for_actor(
        *,
        actor: str,
        draft_id: str = "",
    ) -> list[tuple[AgentSession, ActionDraft]]:
        now = utc_now()
        matches: list[tuple[AgentSession, ActionDraft]] = []
        for session in reversed(sessions.list_sessions(include_closed=False)):
            if session.actor != actor or session.closed or session.is_expired(now=now):
                continue
            draft = _stored_action_draft(session.id)
            if draft is None:
                continue
            if approval_window_status(draft, now=now)[0] != "valid":
                continue
            if draft_id and draft.draft_id.lower() != draft_id.lower():
                continue
            matches.append((session, draft))
        return matches

    async def _create_semantic_clarification_record(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        question: str,
        semantic_rewrite: Any,
        turn_intent_metadata: Mapping[str, Any] | None = None,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> AssistantTurnRecord:
        """Ask one model-derived clarification without falling through to docs."""

        policy = load_default_policy()
        if not policy.agent_enabled:
            raise PermissionError("Simurgh agent runtime is disabled")
        session = _require_or_create_assistant_session(policy=policy, actor=actor, turn_request=turn_request)
        existing_private_context = sessions.get_private_context(session.id)
        clarification_base = (
            existing_private_context
            if str(existing_private_context.get("last_domain") or "") == "clarification"
            else {}
        )
        clarification_messages = _updated_clarification_operator_messages(
            clarification_base,
            turn_request.message,
        )
        clean_question = " ".join(str(question or "").split()).strip()
        if not clean_question:
            clean_question = "What should I do, and which live target should I use?"
        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "understanding",
                "state": "clarification",
                "label": "Clarification needed",
            },
        )
        turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=str(getattr(semantic_rewrite, "provider", "openai") or "openai"),
            model=str(getattr(semantic_rewrite, "model", "") or "semantic-router"),
            adapter_version=str(
                getattr(semantic_rewrite, "adapter_version", "provider-semantic-rewrite")
                or "provider-semantic-rewrite"
            ),
            content=clean_question,
            context_documents=(),
            blocked_intents=(),
            safety_notes=(
                "The semantic layer found more than one plausible operational interpretation.",
                "No action was drafted or executed.",
            ),
        )
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": "clarification",
                "last_intent": "clarify",
                "last_response_mode": "clarify",
            },
        )
        sessions.update_private_context(
            session.id,
            {
                "last_assistant_content": turn.content,
                "last_assistant_provider": turn.provider,
                "last_assistant_model": turn.model,
                "last_domain": "clarification",
                "last_intent": "clarify",
                "last_response_mode": "clarify",
                "last_user_message": turn_request.message,
                "last_routing_message": normalize_operator_query_text(turn_request.message),
                "last_tool_intent": "clarify",
                "last_read_only_evidence": "",
                "clarification_operator_messages": clarification_messages,
            },
        )
        event = audit.record(
            "assistant_turn_created",
            session_id=session.id,
            actor=actor,
            decision="clarification_required",
            payload={"message": turn_request.message.strip()},
            metadata={
                "provider": turn.provider,
                "model": turn.model,
                "adapter_version": turn.adapter_version,
                "mode": session.mode,
                "context_count": 0,
                "blocked_intent_count": 0,
                "response_mode": "clarify",
                "query_domain": "clarification",
                "query_confidence": float(getattr(semantic_rewrite, "confidence", 0.0) or 0.0),
                "query_unclear": True,
                "query_reason": "provider_semantic_clarification",
                "turn_intent": dict(turn_intent_metadata or {}),
                "retrieved_context_count": 0,
                "web_search_enabled": False,
                "action_execution": "none",
            },
        )
        return AssistantTurnRecord(session=session, turn=turn, audit_event=event)

    async def _create_no_pending_confirmation_record(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        candidate_count: int = 0,
        turn_intent_metadata: Mapping[str, Any] | None = None,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> AssistantTurnRecord:
        policy = load_default_policy()
        if not policy.agent_enabled:
            raise PermissionError("Simurgh agent runtime is disabled")
        try:
            session = _require_or_create_assistant_session(policy=policy, actor=actor, turn_request=turn_request)
        except KeyError:
            session = _require_or_create_assistant_session(
                policy=policy,
                actor=actor,
                turn_request=_turn_request_with_session(turn_request, session_id=None),
            )
        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "safety",
                "state": "complete",
                "label": "No pending action found",
                "intent": ACTION_INTENT,
                "tool_id": ACTION_TOOL_ID,
                "tool_ids": [ACTION_TOOL_ID],
            },
        )
        cb_state = "ON" if policy.action_circuit_breaker_enabled else "OFF"
        confirm_state = "ON" if policy.always_confirm_before_action else "OFF"
        if candidate_count > 1:
            reason = (
                f"I found {candidate_count} recent pending guarded actions for this operator, "
                "so I will not guess which one to approve."
            )
            next_step = "Use the specific draft button or reply with `confirm action <draft_id>`."
        else:
            reason = "I do not have a pending guarded action to confirm for this operator/session."
            next_step = "Ask me to draft the action again, then approve the specific draft."
        content = (
            f"{reason}\n\n"
            "Current Simurgh action posture from the live runtime:\n"
            f"- Runtime mode: `{policy.mode}`\n"
            f"- Circuit breaker: {cb_state}\n"
            f"- Human confirmation: {confirm_state}\n\n"
            f"{next_step}\n"
            "No action was executed."
        )
        turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=ACTION_MODEL,
            adapter_version=ACTION_ADAPTER_VERSION,
            content=content,
            context_documents=(),
            blocked_intents=(),
            safety_notes=(
                "Bare confirmations are handled locally and never composed from stale public context.",
                "No action was executed because no unambiguous pending guarded action was available.",
            ),
        )
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": "safety",
                "last_intent": "action_capability",
                "last_response_mode": "status",
            },
        )
        sessions.update_private_context(
            session.id,
            {
                "last_assistant_content": turn.content,
                "last_assistant_provider": turn.provider,
                "last_assistant_model": turn.model,
                "last_domain": "safety",
                "last_intent": "action_capability",
                "last_response_mode": "status",
                "last_user_message": turn_request.message,
                "last_routing_message": normalize_operator_query_text(turn_request.message),
                "last_tool_intent": "action_capability",
                "last_read_only_evidence": "",
            },
        )
        event = audit.record(
            "assistant_turn_created",
            session_id=session.id,
            actor=actor,
            tool_id=ACTION_TOOL_ID,
            decision="no_pending_action",
            payload={
                "message": turn_request.message.strip(),
                "candidate_count": candidate_count,
            },
            metadata={
                "provider": turn.provider,
                "model": turn.model,
                "adapter_version": turn.adapter_version,
                "mode": session.mode,
                "context_count": 0,
                "blocked_intent_count": 0,
                "tool_intent": "action_capability",
                "tool_id": ACTION_TOOL_ID,
                "tool_ids": [ACTION_TOOL_ID],
                "response_mode": "status",
                "query_domain": "safety",
                "query_confidence": 1.0,
                "query_unclear": False,
                "query_reason": "bare_confirmation_without_unambiguous_pending_action",
                "turn_intent": dict(turn_intent_metadata or {}),
                "retrieved_context_count": 0,
                "web_search_enabled": False,
                "action_execution": "no_pending_confirmation",
                "policy_decision": "no_pending_action",
                "policy_reasons": [],
                "circuit_breaker_layer": "final-action layer; no pending action reached execution",
            },
        )
        return AssistantTurnRecord(session=session, turn=turn, audit_event=event)

    async def _create_rejected_action_record(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        draft: ActionDraft,
        session_id: str,
        turn_intent_metadata: Mapping[str, Any] | None = None,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> AssistantTurnRecord:
        policy = load_default_policy()
        session = sessions.require(session_id)
        if session.actor != actor:
            raise PermissionError("assistant session belongs to a different actor")
        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "safety",
                "state": "complete",
                "label": "Action draft rejected",
                "intent": _action_draft_intent(draft),
                "tool_id": _action_draft_tool_id(draft),
                "tool_ids": [_action_draft_tool_id(draft)],
                "draft_id": draft.draft_id,
            },
        )
        sessions.update_private_context(
            session.id,
            {
                "last_action_draft": "",
                "last_action_draft_id": "",
                "last_action_draft_hash": "",
            },
        )
        content = (
            "Cancelled the pending guarded action draft.\n\n"
            f"Action: {_action_draft_label(draft)}\n"
            f"Tool: `{_action_draft_tool_id(draft)}`\n"
            f"Draft ID: `{draft.draft_id}`\n\n"
            "No action was executed."
        )
        turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=ACTION_MODEL,
            adapter_version=ACTION_ADAPTER_VERSION,
            content=content,
            context_documents=(),
            blocked_intents=(),
            safety_notes=(
                "The operator rejected a pending guarded action draft.",
                "No GCS route, command, or SITL action was executed.",
            ),
        )
        action_domain = "flight" if isinstance(draft, FlightActionDraft) else "sitl"
        action_intent = _action_draft_intent(draft)
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": action_domain,
                "last_intent": action_intent,
                "last_response_mode": "status",
            },
        )
        sessions.update_private_context(
            session.id,
            {
                "last_assistant_content": turn.content,
                "last_assistant_provider": turn.provider,
                "last_assistant_model": turn.model,
                "last_domain": action_domain,
                "last_intent": action_intent,
                "last_response_mode": "status",
                "last_user_message": turn_request.message,
                "last_routing_message": normalize_operator_query_text(turn_request.message),
                "last_tool_intent": action_intent,
                "last_read_only_evidence": "",
            },
        )
        event = audit.record(
            "assistant_turn_created",
            session_id=session.id,
            actor=actor,
            tool_id=_action_draft_tool_id(draft),
            decision="action_draft_rejected",
            payload={
                "message": turn_request.message.strip(),
                "action_draft": draft.public_payload(),
            },
            metadata={
                "provider": turn.provider,
                "model": turn.model,
                "adapter_version": turn.adapter_version,
                "mode": session.mode,
                "context_count": 0,
                "blocked_intent_count": 0,
                "tool_intent": action_intent,
                "tool_id": _action_draft_tool_id(draft),
                "tool_ids": [_action_draft_tool_id(draft)],
                "response_mode": "status",
                "query_domain": action_domain,
                "query_confidence": 1.0,
                "query_unclear": False,
                "query_reason": "guarded_action_rejected_by_operator",
                "turn_intent": dict(turn_intent_metadata or {}),
                "retrieved_context_count": 0,
                "web_search_enabled": False,
                "action_execution": "cancelled_confirmation",
                "action_draft": draft.public_payload(),
                "policy_decision": "operator_rejected",
                "policy_reasons": [],
                "circuit_breaker_layer": "final-action layer; operator rejected before execution",
                "runtime_mode": policy.mode,
            },
        )
        return AssistantTurnRecord(session=session, turn=turn, audit_event=event)

    async def _create_action_run_control_record(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        run: ActionRunSnapshot,
        action: str,
        turn_intent_metadata: Mapping[str, Any] | None = None,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> AssistantTurnRecord:
        """Apply an unambiguous conversational control to one active run."""

        policy = load_default_policy()
        if not policy.agent_enabled:
            raise PermissionError("Simurgh agent runtime is disabled")
        session = sessions.require(run.session_id)
        if session.actor != actor or run.actor != actor:
            raise PermissionError("action run belongs to a different operator")
        updated = await action_run_store_call(
            action_runs.request_control,
            run.run_id,
            actor=actor,
            action=action,
            reason="Operator requested this control in Simurgh chat.",
            control_id=f"ctl-chat-{uuid.uuid4().hex[:16]}",
        )
        labels = {
            "cancel_remaining": "Cancelling remaining steps",
            "pause_after_current_step": "Pausing after current step",
            "resume": "Resuming action run",
        }
        content_by_action = {
            "cancel_remaining": (
                "Cancelling the remaining steps. The currently dispatched step, if any, will finish; "
                "no later step will start."
            ),
            "pause_after_current_step": (
                "Pause requested. The currently dispatched step will finish, then the remaining plan will pause."
            ),
            "resume": "Resuming the remaining approved steps.",
        }
        label = labels.get(action, "Action run control accepted")
        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "action",
                "state": "complete",
                "label": label,
                "sequence_id": run.run_id,
            },
        )
        turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=READ_TOOL_MODEL,
            adapter_version="action-run-control-v1",
            content=(
                f"{content_by_action.get(action, label)}\n\n"
                f"Run: `{run.run_id}`\n"
                f"State: `{updated.state}`"
            ),
            context_documents=(),
            blocked_intents=(),
            safety_notes=(
                "This control applies only to the identified durable action run.",
                "A command already dispatched to the GCS is not recalled mid-step.",
            ),
        )
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": "action_run",
                "last_intent": "action_run_control",
                "last_response_mode": "status",
            },
        )
        sessions.update_private_context(
            session.id,
            {
                "last_assistant_content": turn.content,
                "last_assistant_provider": turn.provider,
                "last_assistant_model": turn.model,
                "last_domain": "action_run",
                "last_intent": "action_run_control",
                "last_response_mode": "status",
                "last_user_message": turn_request.message,
                "last_routing_message": normalize_operator_query_text(turn_request.message),
                "last_tool_intent": "action_run_control",
                "last_action_run_id": run.run_id,
                "last_read_only_evidence": "",
            },
        )
        event = audit.record(
            "assistant_turn_created",
            session_id=session.id,
            actor=actor,
            decision="action_run_control_requested",
            payload={
                "message": turn_request.message.strip(),
                "run_id": run.run_id,
                "control": action,
            },
            metadata={
                "provider": turn.provider,
                "model": turn.model,
                "adapter_version": turn.adapter_version,
                "mode": session.mode,
                "context_count": 0,
                "blocked_intent_count": 0,
                "response_mode": "status",
                "query_domain": "action_run",
                "query_confidence": 1.0,
                "query_unclear": False,
                "query_reason": "unambiguous_active_action_run_control",
                "turn_intent": dict(turn_intent_metadata or {}),
                "retrieved_context_count": 0,
                "web_search_enabled": False,
                "action_execution": "action_run_control",
                "action_run": updated.public_payload(),
                "circuit_breaker_layer": "not applicable; control affects only remaining approved steps",
            },
        )
        return AssistantTurnRecord(session=session, turn=turn, audit_event=event)

    def _session_conversation_topic(session: AgentSession) -> str:
        topic = str(session.metadata.get("last_domain") or "").strip()
        if topic == "simulation":
            return "sitl"
        if topic:
            return topic
        try:
            context = sessions.get_private_context(session.id)
        except KeyError:
            return ""
        context_topic = str(context.get("last_domain") or "").strip()
        return "sitl" if context_topic == "simulation" else context_topic

    def _submitted_registry_target_ids(
        draft: RegistryActionDraft,
        *,
        response_payload: Mapping[str, Any],
        monitor_result: Mapping[str, Any] | None,
    ) -> list[str]:
        if draft.tool_id == SITL_CREATE_TOOL_ID:
            explicit = _coerce_int_like_text(draft.arguments.get("instance_id"))
            if explicit:
                return [explicit]
            parsed = _extract_drone_ids_from_payload(response_payload, monitor_result or {})
            return parsed[:1]
        if draft.tool_id == SITL_RECONCILE_TOOL_ID:
            parsed = _extract_drone_ids_from_payload(response_payload, monitor_result or {})
            if parsed:
                return parsed
            target_count = draft.arguments.get("target_count")
            try:
                count = int(target_count)
            except (TypeError, ValueError):
                return []
            return ["1"] if count == 1 else []
        if draft.tool_id == SITL_BATCH_ACTION_TOOL_ID:
            instance_names = draft.arguments.get("instance_names")
            if not isinstance(instance_names, (list, tuple)):
                return []
            ids: list[str] = []
            for name in instance_names:
                match = re.search(r"\bdrone-(\d+)\b", str(name or "").strip().lower())
                if match and match.group(1) not in ids:
                    ids.append(match.group(1))
            return ids
        return []

    def _extract_drone_ids_from_payload(*payloads: Mapping[str, Any]) -> list[str]:
        values: list[str] = []
        for payload in payloads:
            for text in _payload_text_values(payload):
                for match in re.finditer(r"\bdrone-(\d+)\b", text.lower()):
                    drone_id = match.group(1)
                    if drone_id not in values:
                        values.append(drone_id)
        return values

    def _payload_text_values(value: Any) -> tuple[str, ...]:
        texts: list[str] = []
        if isinstance(value, Mapping):
            for item in value.values():
                texts.extend(_payload_text_values(item))
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                texts.extend(_payload_text_values(item))
        elif isinstance(value, str):
            text = value.strip()
            if text:
                texts.append(text)
        return tuple(texts)

    def _coerce_int_like_text(value: Any) -> str:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return ""
        return str(number) if number > 0 else ""

    def _action_turn_content(
        *,
        draft: ActionDraft,
        action_execution: str,
        pre_action_read_only_content: str = "",
        policy_reasons: tuple[str, ...] = (),
        command_response: Any | None = None,
        monitor_result: Mapping[str, Any] | None = None,
        post_action_results: tuple[Mapping[str, Any], ...] = (),
        rejection_detail: str = "",
        precondition_evaluation: ActionPreconditionEvaluation | None = None,
        circuit_breaker_enabled: bool = True,
        always_confirm_before_action: bool = True,
    ) -> str:
        def with_pre_action_context(body: str) -> str:
            return _pre_action_read_only_context_block(pre_action_read_only_content) + body

        payload = _action_draft_payload(draft)
        action_label = _action_draft_label(draft)
        tool_id = _action_draft_tool_id(draft)
        target_label = (
            _format_drone_targets(draft.target_drone_ids)
            if isinstance(draft, FlightActionDraft)
            else f"`{tool_id}`"
        )
        if action_execution in {"precondition_not_met", "precondition_unavailable"}:
            evaluation = precondition_evaluation or ActionPreconditionEvaluation.not_required()
            condition_label, observed = _precondition_observation_summary(evaluation)
            if action_execution == "precondition_not_met":
                return with_pre_action_context(
                    (
                        "No action is needed because the requested condition is not currently met.\n\n"
                        f"Condition: {condition_label}\n"
                        f"Observed: {observed}\n\n"
                        "No action was executed."
                    )
                )
            return with_pre_action_context(
                (
                    "I could not verify the condition required to run this action.\n\n"
                    f"Condition: {condition_label}\n"
                    f"Observed: {observed}\n\n"
                    "No action was executed. Try the request again after the status source is available."
                )
            )
        if action_execution == "missing_arguments":
            missing = ", ".join(draft.missing_arguments)
            if isinstance(draft, FlightActionDraft) and "sequence_timing" in draft.missing_arguments:
                return with_pre_action_context(
                    "I found a timed step in the mission that I could not map confidently. "
                    "Should that timed step be a stationary wait? No action was executed."
                )
            if isinstance(draft, FlightActionDraft) and "target_drone_ids" in draft.missing_arguments:
                lines = [
                    "I understood the mission, but I need the target drone before I can prepare the guarded draft.",
                    "",
                    "Which drone should I use?",
                ]
                if payload.get("takeoff_altitude") is not None:
                    lines.append(f"- Takeoff altitude: {payload.get('takeoff_altitude')} m")
                if draft.post_actions:
                    lines.append("- Planned sequence:")
                    for item in draft.post_actions:
                        label = str(item.get("action_label") or item.get("tool_id") or "post-action").strip()
                        if str(item.get("type") or "").lower() == "delay":
                            delay = item.get("delay_seconds")
                            lines.append(f"  - {label}: wait {delay:g}s" if isinstance(delay, (int, float)) else f"  - {label}")
                            continue
                        arguments = item.get("arguments") if isinstance(item.get("arguments"), Mapping) else {}
                        precision_move = arguments.get("precision_move") if isinstance(arguments, Mapping) else {}
                        translation = precision_move.get("translation_m") if isinstance(precision_move, Mapping) else None
                        if isinstance(translation, Mapping):
                            parts = [
                                f"{axis}={float(value):g}m"
                                for axis, value in translation.items()
                                if isinstance(value, (int, float)) and float(value) != 0.0
                            ]
                            suffix = f" ({', '.join(parts)})" if parts else ""
                            lines.append(f"  - {label}{suffix}")
                        else:
                            lines.append(f"  - {label}")
                lines.extend(
                    [
                        "",
                        "Reply with the drone ID, for example `drone 1`. No action was executed.",
                    ]
                )
                return with_pre_action_context("\n".join(lines))
            return with_pre_action_context(
                (
                    "I can plan this guarded action, but I need one more detail before any execution path exists.\n\n"
                    f"Missing: {missing}.\n"
                    f"Action detected: {action_label}.\n"
                    "No action was executed."
                )
            )
        if action_execution == "approval_expired":
            return with_pre_action_context(
                (
                    "This action draft is no longer valid for confirmation.\n\n"
                    f"{rejection_detail or 'Its approval window has expired.'}\n"
                    "No action was executed. Please submit the request again so I can refresh "
                    "the live target and safety checks."
                )
            )
        if action_execution == "awaiting_confirmation":
            cb_state = "ON" if circuit_breaker_enabled else "OFF"
            confirm_line = (
                f"Reply `confirm action {draft.draft_id}` to submit this through the guarded GCS action path."
                if always_confirm_before_action
                else "Confirmation is not required by current policy, but this draft was not auto-executed in chat."
            )
            return with_pre_action_context(
                (
                    "Review the guarded action plan below.\n\n"
                    f"{_action_draft_summary_block(draft)}\n\n"
                    f"Draft ID: `{draft.draft_id}`\n\n"
                    f"{confirm_line}\n"
                    f"Circuit breaker: {cb_state}.\n"
                    "No action was executed."
                )
            )
        if action_execution == "blocked_by_circuit_breaker":
            return with_pre_action_context(
                (
                    "Circuit breaker stopped this at the final execution layer.\n\n"
                    f"If the circuit breaker were OFF, I would submit this guarded GCS action for {target_label}:\n\n"
                    f"{_action_draft_summary_block(draft)}\n\n"
                    "No action was executed."
                )
            )
        if action_execution == "policy_denied":
            reasons = "; ".join(policy_reasons) or "policy denied this action"
            return with_pre_action_context(
                (
                    "I prepared the action draft, but policy denied execution before command submission.\n\n"
                    f"Reason: {reasons}.\n"
                    f"{_action_draft_summary_block(draft)}\n\n"
                    "No action was executed."
                )
            )
        if action_execution == "validation_rejected":
            return with_pre_action_context(
                (
                    "The guarded GCS action path rejected this action before dispatch.\n\n"
                    f"Reason: {rejection_detail or 'GCS action validation failed'}.\n"
                    f"{_action_draft_summary_block(draft)}\n\n"
                    "No action was accepted."
                )
            )
        if action_execution == "resource_conflict":
            return with_pre_action_context(
                (
                    "This action overlaps an active operation on the same target.\n\n"
                    f"Reason: {rejection_detail or 'The target is already reserved by another action run'}.\n"
                    "I did not dispatch a second operation. The active run remains the source of truth."
                )
            )

        response_payload = (
            command_response.model_dump(mode="json")
            if hasattr(command_response, "model_dump")
            else dict(command_response or {})
        )
        action_run_id = str(response_payload.get("action_run_id") or "").strip()
        if action_run_id:
            return with_pre_action_context(
                (
                    "Action run started.\n\n"
                    f"Plan: {_action_draft_label(draft)}\n"
                    f"Target: {target_label}\n"
                    f"Run ID: `{action_run_id}`\n\n"
                    "Progress and the terminal result are tracked in the live action card."
                )
            )
        if not isinstance(draft, FlightActionDraft):
            operation_id = response_payload.get("operation_id") or response_payload.get("id") or "unknown"
            status = response_payload.get("status") or "submitted"
            summary = response_payload.get("summary") or response_payload.get("message") or action_label
            final_status = str(status)
            final_summary = str(summary)
            if monitor_result:
                final_status = str(monitor_result.get("status") or final_status)
                final_summary = str(monitor_result.get("summary") or monitor_result.get("message") or final_summary)
            terminal_success = final_status.casefold() in {"completed", "succeeded", "success"}
            heading = "SITL operation complete" if terminal_success else "SITL operation submitted"
            if monitor_result and not terminal_success:
                heading = "SITL operation needs review"
            return with_pre_action_context(
                (
                    f"{heading}.\n\n"
                    f"Result: {final_summary}\n"
                    f"Status: {final_status}\n"
                    + (f"Operation ID: `{operation_id}`" if operation_id != "unknown" else "")
                )
            )
        command_id = response_payload.get("command_id") or "unknown"
        status = response_payload.get("status") or "submitted"
        target_drones = response_payload.get("target_drones") or list(draft.target_drone_ids)
        total_steps = 1 + len(draft.post_actions)
        primary_complete = bool(monitor_result and monitor_result.get("success"))
        completed_steps = (1 if primary_complete else 0) + sum(
            1 for item in post_action_results if not item.get("is_error")
        )
        sequence_state, sequence_label = _submitted_action_progress_outcome(
            draft,
            monitor_result=monitor_result,
            post_action_results=post_action_results,
        )
        if sequence_state == "complete":
            heading = "Command sequence complete"
        elif sequence_state == "timeout":
            heading = "Command sequence monitoring timed out"
        elif sequence_state == "failed":
            heading = "Command sequence stopped"
        elif sequence_state == "warning":
            heading = "Command complete; final state unverified"
        else:
            heading = "Flight command submitted"
        result_line = (
            f"{completed_steps}/{total_steps} planned steps completed."
            if monitor_result or post_action_results
            else sequence_label + "."
        )
        completion_verifications = []
        primary_completion_verification = (
            monitor_result.get("completion_verification")
            if isinstance(monitor_result, Mapping)
            and isinstance(monitor_result.get("completion_verification"), Mapping)
            else None
        )
        if primary_completion_verification:
            completion_verifications.append(primary_completion_verification)
        completion_verifications.extend([
            item.get("completion_verification")
            for item in post_action_results
            if isinstance(item.get("completion_verification"), Mapping)
            and item.get("completion_verification")
        ])
        final_state_line = ""
        if completion_verifications:
            latest_verification = completion_verifications[-1]
            if latest_verification.get("verified"):
                final_state_line = "\nFinal state: live telemetry confirms the target is disarmed."
            else:
                final_state_line = (
                    "\nFinal state: the command sequence ended, but live telemetry did not confirm disarm."
                )
        return with_pre_action_context(
            (
                f"{heading}.\n\n"
                f"Target: {_format_drone_targets(tuple(str(item) for item in target_drones))}\n"
                f"Result: {result_line}\n"
                f"Command ID: `{command_id}`"
                f"{final_state_line}"
            )
        )

    async def _monitor_command_until_terminal(
        request_deps: Any,
        command_id: str,
        *,
        progress_callback: AssistantProgressCallback | None = None,
        action_run_id: str = "",
        timeout_seconds: float = ACTION_MONITOR_TIMEOUT_SECONDS,
        sequence_id: str = "",
        step_index: int | None = None,
        step_count: int | None = None,
        step_label: str = "",
        step_kind: str = "flight_command",
        mission_name: str = "",
        verify_landed_state: bool = False,
    ) -> dict[str, Any]:
        tracker = request_deps.get_command_tracker()
        loop = asyncio.get_running_loop()
        monitor_started_at = loop.time()
        deadline = monitor_started_at + timeout_seconds
        next_heartbeat_at = monitor_started_at + ACTION_MONITOR_HEARTBEAT_SECONDS
        canonical_deadline_loaded = False
        last_status: Mapping[str, Any] | None = None
        last_progress_signature: tuple[Any, ...] | None = None
        cancel_requested = False
        cancel_notice_emitted = False
        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "monitor",
                "state": "running",
                "label": _sequence_progress_label(
                    f"Monitoring command {command_id[:8]}",
                    step_label=step_label,
                    step_index=step_index,
                    step_count=step_count,
                    activity="monitoring command",
                ),
                **_sequence_progress_fields(
                    sequence_id=sequence_id,
                    step_index=step_index,
                    step_count=step_count,
                    step_label=step_label,
                    step_kind=step_kind,
                    command_id=command_id,
                    mission_name=mission_name,
                ),
            },
        )
        while True:
            if await action_run_cancel_requested_async(action_run_id):
                cancel_requested = True
                if not cancel_notice_emitted:
                    cancel_notice_emitted = True
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "monitor",
                            "state": "running",
                            "label": _sequence_progress_label(
                                "Cancellation requested; waiting for current command to finish",
                                step_label=step_label,
                                step_index=step_index,
                                step_count=step_count,
                                activity="draining current command",
                            ),
                            "command_id": command_id,
                            "summary": (
                                "No later sequence step will be dispatched. "
                                "This control does not abort the executing GCS command."
                            ),
                            "control_effect": "cancel_remaining",
                            **_sequence_progress_fields(
                                sequence_id=sequence_id,
                                step_index=step_index,
                                step_count=step_count,
                                step_label=step_label,
                                step_kind=step_kind,
                                command_id=command_id,
                                mission_name=mission_name,
                            ),
                        },
                    )
                    next_heartbeat_at = loop.time() + ACTION_MONITOR_HEARTBEAT_SECONDS
            status = await tracker.get_status(command_id)
            if isinstance(status, Mapping):
                last_status = status
                if not canonical_deadline_loaded:
                    timeout_at = status.get("timeout_at")
                    try:
                        remaining_seconds = (float(timeout_at) - (time.time() * 1000.0)) / 1000.0
                    except (TypeError, ValueError):
                        remaining_seconds = 0.0
                    if remaining_seconds > 0:
                        deadline = loop.time() + remaining_seconds + ACTION_MONITOR_POLL_SECONDS
                        canonical_deadline_loaded = True
                tracker_progress = status.get("progress") if isinstance(status.get("progress"), Mapping) else {}
                tracker_label = str(
                    tracker_progress.get("label")
                    or tracker_progress.get("stage")
                    or status.get("phase")
                    or "Command in progress"
                ).strip()
                tracker_message = str(tracker_progress.get("message") or "").strip()
                progress_signature = (
                    _compact_status_value(status.get("status")),
                    _compact_status_value(status.get("phase")),
                    tracker_label,
                    tracker_message,
                )
                if progress_signature != last_progress_signature and not _command_monitor_terminal(status):
                    last_progress_signature = progress_signature
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "monitor",
                            "state": "running",
                            "label": _sequence_progress_label(
                                tracker_label,
                                step_label=step_label,
                                step_index=step_index,
                                step_count=step_count,
                                activity=tracker_label,
                            ),
                            "summary": tracker_message or _command_monitor_summary(status),
                            **_sequence_progress_fields(
                                sequence_id=sequence_id,
                                step_index=step_index,
                                step_count=step_count,
                                step_label=step_label,
                                step_kind=step_kind,
                                command_id=command_id,
                                mission_name=mission_name,
                            ),
                        },
                    )
                    next_heartbeat_at = loop.time() + ACTION_MONITOR_HEARTBEAT_SECONDS
                if _command_monitor_terminal(status):
                    success = _command_monitor_success(status)
                    verification_pending = bool(success and verify_landed_state)
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "monitor",
                            "state": (
                                "running"
                                if verification_pending
                                else "complete"
                                if success
                                else "failed"
                            ),
                            "label": _sequence_progress_label(
                                (
                                    "Command accepted; verifying final state"
                                    if verification_pending
                                    else "Command completed"
                                    if success
                                    else "Command reached terminal state"
                                ),
                                step_label=step_label,
                                step_index=step_index,
                                step_count=step_count,
                                activity=(
                                    "verifying landed state"
                                    if verification_pending
                                    else "completed"
                                    if success
                                    else "terminal state"
                                ),
                            ),
                            "command_id": command_id,
                            "summary": _command_monitor_summary(status),
                            **_sequence_progress_fields(
                                sequence_id=sequence_id,
                                step_index=step_index,
                                step_count=step_count,
                                step_label=step_label,
                                step_kind=step_kind,
                                command_id=command_id,
                                mission_name=mission_name,
                            ),
                        },
                    )
                    return {
                        "status": "terminal_success" if success else "terminal_non_success",
                        "success": success,
                        "timed_out": False,
                        "cancel_requested": cancel_requested,
                        "command_status": dict(status),
                    }
            observed_at = loop.time()
            if observed_at >= next_heartbeat_at:
                await _emit_assistant_progress(
                    progress_callback,
                    _monitor_heartbeat_progress_payload(
                        started_at=monitor_started_at,
                        observed_at=observed_at,
                        label=_sequence_progress_label(
                            "Command monitoring is active",
                            step_label=step_label,
                            step_index=step_index,
                            step_count=step_count,
                            activity="monitoring",
                        ),
                        latest_evidence={
                            "source": "command_tracker",
                            "command_id": command_id,
                            "status": _compact_status_value((last_status or {}).get("status")),
                            "phase": _compact_status_value((last_status or {}).get("phase")),
                            "outcome": _compact_status_value((last_status or {}).get("outcome")),
                            "summary": _command_monitor_summary(last_status)[:240],
                        },
                        sequence_id=sequence_id,
                        step_index=step_index,
                        step_count=step_count,
                        step_label=step_label,
                        step_kind=step_kind,
                    ),
                )
                next_heartbeat_at = observed_at + ACTION_MONITOR_HEARTBEAT_SECONDS
            if observed_at >= deadline:
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "monitor",
                        "state": "timeout",
                        "label": _sequence_progress_label(
                            "Command still running or not terminal",
                            step_label=step_label,
                            step_index=step_index,
                            step_count=step_count,
                            activity="still running",
                        ),
                        "command_id": command_id,
                        "summary": _command_monitor_summary(last_status),
                        **_sequence_progress_fields(
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=step_label,
                            step_kind=step_kind,
                            command_id=command_id,
                            mission_name=mission_name,
                        ),
                    },
                )
                return {
                    "status": "timeout",
                    "success": False,
                    "timed_out": True,
                    "cancel_requested": cancel_requested,
                    "command_status": dict(last_status or {}),
                }
            await asyncio.sleep(ACTION_MONITOR_POLL_SECONDS)

    async def _execute_post_actions(
        execution_context: InternalToolExecutionContext,
        *,
        post_actions: tuple[Mapping[str, Any], ...],
        registry,
        policy,
        actor_role: str,
        request_deps: Any | None = None,
        progress_callback: AssistantProgressCallback | None = None,
        sequence_id: str = "",
        idempotency_scope: str = "",
        initial_step_index: int = 1,
        step_count: int | None = None,
        action_run_id: str = "",
        action_run_ownership: ActionRunOwnership | None = None,
        initial_previous_step_succeeded: bool = True,
        initial_target_drone_ids: Sequence[str] = (),
    ) -> tuple[Mapping[str, Any], ...]:
        results: list[Mapping[str, Any]] = []
        previous_step_succeeded = initial_previous_step_succeeded
        runtime_target_ids = list(
            dict.fromkeys(
                str(item).strip()
                for item in initial_target_drone_ids
                if str(item).strip()
            )
        )
        for index, item in enumerate(post_actions, start=1):
            action_type = str(item.get("type") or "").strip()
            tool_id = str(item.get("tool_id") or "").strip()
            arguments = (
                dict(item.get("arguments"))
                if isinstance(item.get("arguments"), Mapping)
                else {}
            )
            label = str(item.get("action_label") or tool_id or "post-action")
            step_index = initial_step_index + index
            condition = str(item.get("condition") or "").strip()
            if action_run_id and not await _wait_for_action_run_dispatch(
                action_run_id,
                ownership=action_run_ownership,
            ):
                results.append(
                    {
                        "label": label,
                        "tool_id": tool_id,
                        "status": "cancelled",
                        "summary": "remaining sequence steps cancelled before dispatch",
                        "is_error": True,
                    }
                )
                break
            if condition == "after_command_terminal_success" and not previous_step_succeeded:
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "action",
                        "state": "skipped",
                        "label": _sequence_progress_label(
                            f"Skipped post-action: {label}",
                            step_label=label,
                            step_index=step_index,
                            step_count=step_count,
                            activity="skipped after previous step",
                        ),
                        "tool_id": tool_id,
                        **_sequence_progress_fields(
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=label,
                            step_kind=action_type or "post_action",
                        ),
                    },
                )
                results.append(
                    {
                        "label": label,
                        "tool_id": tool_id,
                        "status": "skipped",
                        "summary": "previous sequence step did not complete successfully",
                        "is_error": True,
                    }
                )
                continue
            if action_type == "delay":
                try:
                    delay_seconds = _validated_post_action_delay_seconds(item.get("delay_seconds"))
                except ValueError as exc:
                    results.append(
                        {
                            "label": label,
                            "type": "delay",
                            "status": "failed",
                            "summary": str(exc),
                            "is_error": True,
                        }
                    )
                    previous_step_succeeded = False
                    continue
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "monitor",
                        "state": "running",
                        "label": _sequence_progress_label(
                            f"Waiting {delay_seconds:g}s before next step",
                            step_label=label,
                            step_index=step_index,
                            step_count=step_count,
                            activity="waiting",
                        ),
                        **_sequence_progress_fields(
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=label,
                            step_kind="delay",
                        ),
                    },
                )

                async def emit_wait_progress(remaining_seconds: float) -> None:
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "monitor",
                            "state": "running",
                            "label": _sequence_progress_label(
                                f"{remaining_seconds:g}s remaining",
                                step_label=label,
                                step_index=step_index,
                                step_count=step_count,
                                activity=f"{remaining_seconds:g}s remaining",
                            ),
                            "remaining_seconds": remaining_seconds,
                            **_sequence_progress_fields(
                                sequence_id=sequence_id,
                                step_index=step_index,
                                step_count=step_count,
                                step_label=label,
                                step_kind="delay",
                            ),
                        },
                    )

                delay_completed = (
                    await _sleep_action_run_delay(
                        action_run_id,
                        delay_seconds,
                        progress_tick=emit_wait_progress,
                        ownership=action_run_ownership,
                    )
                    if action_run_id
                    else await _sleep_post_action_delay(
                        delay_seconds,
                        progress_tick=emit_wait_progress,
                    )
                )
                if delay_completed is False:
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "monitor",
                            "state": "cancelled",
                            "label": _sequence_progress_label(
                                f"Cancelled wait: {label}",
                                step_label=label,
                                step_index=step_index,
                                step_count=step_count,
                                activity="cancelled",
                            ),
                            **_sequence_progress_fields(
                                sequence_id=sequence_id,
                                step_index=step_index,
                                step_count=step_count,
                                step_label=label,
                                step_kind="delay",
                            ),
                        },
                    )
                    results.append(
                        {
                            "label": label,
                            "type": "delay",
                            "status": "cancelled",
                            "summary": "remaining sequence steps cancelled during wait",
                            "is_error": True,
                        }
                    )
                    break
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "monitor",
                        "state": "complete",
                        "label": _sequence_progress_label(
                            f"Completed wait: {label}",
                            step_label=label,
                            step_index=step_index,
                            step_count=step_count,
                            activity="completed",
                        ),
                        **_sequence_progress_fields(
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=label,
                            step_kind="delay",
                        ),
                    },
                )
                results.append(
                    {
                        "label": label,
                        "type": "delay",
                        "status": "completed",
                        "summary": f"waited {delay_seconds:g} second(s)",
                        "is_error": False,
                    }
                )
                continue
            if not tool_id:
                results.append(
                    {
                        "label": label,
                        "status": "skipped",
                        "summary": "post-action has no tool_id",
                        "is_error": True,
                    }
                )
                previous_step_succeeded = False
                continue
            await _emit_assistant_progress(
                progress_callback,
                {
                    "stage": "action",
                    "state": "running",
                    "label": _sequence_progress_label(
                        f"Running post-action: {label}",
                        step_label=label,
                        step_index=step_index,
                        step_count=step_count,
                        activity="submitting",
                    ),
                    "tool_id": tool_id,
                    **_sequence_progress_fields(
                        sequence_id=sequence_id,
                        step_index=step_index,
                        step_count=step_count,
                        step_label=label,
                        step_kind=action_type or "post_action",
                    ),
                },
            )
            if tool_id == ACTION_TOOL_ID:
                if item.get("target_from_previous_result") and not arguments.get("target_drone_ids"):
                    arguments["target_drone_ids"] = list(runtime_target_ids)
                resolved_targets = [
                    str(value).strip()
                    for value in arguments.get("target_drone_ids") or ()
                    if str(value).strip()
                ]
                if not resolved_targets:
                    results.append(
                        {
                            "label": label,
                            "tool_id": tool_id,
                            "status": "failed",
                            "summary": "No target identity was produced by the preceding sequence step.",
                            "is_error": True,
                        }
                    )
                    previous_step_succeeded = False
                    continue
                runtime_target_ids = list(dict.fromkeys(resolved_targets))
                if request_deps is None:
                    results.append(
                        {
                            "label": label,
                            "tool_id": tool_id,
                            "status": "skipped",
                            "summary": "flight post-action has no command tracker context",
                            "is_error": True,
                        }
                    )
                    previous_step_succeeded = False
                    continue
                command_payload = {
                    **dict(arguments),
                    "idempotency_key": f"simurgh:{idempotency_scope or sequence_id}:step:{step_index}",
                }
                try:
                    mission_type = _coerce_int_like_text(arguments.get("mission_type"))
                    command = SubmitCommandRequest.model_validate(command_payload)
                    async with action_policy_dispatch_lock:
                        current_policy = load_default_policy()
                        post_decision = current_policy.evaluate_tool(
                            registry.get(tool_id),
                            channel="agent",
                            approved=True,
                            actor_role=actor_role,
                        )
                        if post_decision.status is not PolicyDecisionStatus.ALLOW:
                            results.append(
                                {
                                    "label": label,
                                    "tool_id": tool_id,
                                    "status": "blocked",
                                    "summary": "; ".join(post_decision.reasons),
                                    "is_error": True,
                                }
                            )
                            previous_step_succeeded = False
                            continue
                        action_response = await submit_tracked_command(request_deps, command)
                    response_payload = (
                        action_response.model_dump(mode="json")
                        if hasattr(action_response, "model_dump")
                        else dict(action_response or {})
                    )
                    command_id = str(response_payload.get("command_id") or "").strip()
                    summary = response_payload.get("results_summary") or response_payload.get("message") or ""
                    final_status = str(response_payload.get("status") or "submitted")
                    monitor_status: Mapping[str, Any] | None = None
                    if command_id:
                        monitor_status = await _monitor_command_until_terminal(
                            request_deps,
                            command_id,
                            progress_callback=progress_callback,
                            action_run_id=action_run_id,
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=label,
                            step_kind="flight_command",
                            mission_name=str(arguments.get("mission_name") or arguments.get("mission_type") or ""),
                            verify_landed_state=mission_type
                            in {
                                str(Mission.LAND.value),
                                str(Mission.RETURN_RTL.value),
                            },
                        )
                        final_status = str(monitor_status.get("status") or final_status)
                        summary = _command_monitor_summary(monitor_status.get("command_status")) or summary
                    completion_verification: Mapping[str, Any] | None = None
                    if (
                        monitor_status is not None
                        and monitor_status.get("success")
                        and mission_type
                        in {str(Mission.LAND.value), str(Mission.RETURN_RTL.value)}
                    ):
                        completion_verification = await _monitor_targets_disarmed(
                            request_deps,
                            target_drone_ids=tuple(str(item) for item in arguments.get("target_drone_ids") or ()),
                            mission_type=int(mission_type),
                            progress_callback=progress_callback,
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=label,
                            command_id=command_id,
                            deadline_epoch_ms=_command_monitor_deadline_epoch_ms(monitor_status),
                        )
                        if not completion_verification.get("verified"):
                            final_status = "completion_unverified"
                            summary = str(completion_verification.get("summary") or summary)
                    is_error = bool(monitor_status is None or not monitor_status.get("success"))
                    if not command_id:
                        final_status = "monitor_error"
                        summary = "GCS accepted the step without a trackable command ID."
                    if completion_verification and not completion_verification.get("verified"):
                        is_error = True
                    results.append(
                        {
                            "label": label,
                            "tool_id": tool_id,
                            "status": final_status,
                            "command_id": command_id,
                            "summary": str(summary)[:500],
                            "is_error": is_error,
                            "monitor_result": dict(monitor_status or {}),
                            "completion_verification": dict(completion_verification or {}),
                            "resolved_target_drone_ids": list(runtime_target_ids),
                        }
                    )
                    previous_step_succeeded = not is_error
                except Exception as exc:
                    results.append(
                        {
                            "label": label,
                            "tool_id": tool_id,
                            "status": "failed",
                            "summary": str(exc)[:500],
                            "is_error": True,
                        }
                    )
                    previous_step_succeeded = False
                continue
            if item.get("target_from_previous_result"):
                binding_argument, bound_values = materialize_target_binding(
                    item.get("target_binding"),
                    runtime_target_ids,
                )
                if not binding_argument or not bound_values:
                    results.append(
                        {
                            "label": label,
                            "tool_id": tool_id,
                            "status": "failed",
                            "summary": "No target identity was produced by the preceding sequence step.",
                            "is_error": True,
                        }
                    )
                    previous_step_succeeded = False
                    continue
                arguments[binding_argument] = bound_values
            try:
                async with action_policy_dispatch_lock:
                    current_policy = load_default_policy()
                    post_decision = current_policy.evaluate_tool(
                        registry.get(tool_id),
                        channel="agent",
                        approved=True,
                        actor_role=actor_role,
                    )
                    if post_decision.status is not PolicyDecisionStatus.ALLOW:
                        results.append(
                            {
                                "label": label,
                                "tool_id": tool_id,
                                "status": "blocked",
                                "summary": "; ".join(post_decision.reasons),
                                "is_error": True,
                            }
                        )
                        previous_step_succeeded = False
                        continue
                    result = await execute_policy_allowed_guarded_route_tool(
                        execution_context,
                        name=tool_id,
                        arguments=dict(arguments),
                        channel="agent",
                        approved=True,
                        actor_role=actor_role,
                        registry=registry,
                        policy=current_policy,
                    )
                structured = result.structured_content if isinstance(result.structured_content, Mapping) else {}
                operation_id = structured.get("operation_id") or structured.get("id") or ""
                summary = structured.get("summary") or result.text
                status_value = structured.get("status") or ("error" if result.is_error else "submitted")
                final_status = status_value
                operation_status: Mapping[str, Any] = {}
                if operation_id:
                    post_tool = registry.require(tool_id)
                    operation_status = await _monitor_sitl_operation(
                        execution_context,
                        operation_id=str(operation_id),
                        monitor_config=post_tool.assistant_action,
                        registry=registry,
                        policy=current_policy,
                        progress_callback=progress_callback,
                        action_run_id=action_run_id,
                        sequence_id=sequence_id,
                        step_index=step_index,
                        step_count=step_count,
                        step_label=label,
                    )
                    final_status = operation_status.get("status") or final_status
                elif bool(item.get("monitor_requested")) and not result.is_error:
                    final_status = "monitor_error"
                    summary = "GCS accepted the step without a trackable operation ID."
                is_error = _post_action_status_is_error(
                    final_status,
                    explicit_error=bool(result.is_error or operation_status.get("success") is False),
                )
                if operation_status:
                    summary = (
                        operation_status.get("detail")
                        if is_error
                        else operation_status.get("summary")
                    ) or operation_status.get("summary") or summary
                results.append(
                    {
                        "label": label,
                        "tool_id": tool_id,
                        "status": str(final_status),
                        "operation_id": str(operation_id),
                        "summary": str(summary)[:500],
                        "is_error": is_error,
                        "completion_verification": dict(
                            operation_status.get("completion_verification")
                            if isinstance(operation_status.get("completion_verification"), Mapping)
                            else {}
                        ),
                    }
                )
                previous_step_succeeded = not is_error
                if (
                    previous_step_succeeded
                    and str(item.get("result_target_source") or "").strip() == "affected_instances"
                ):
                    produced_targets = _extract_drone_ids_from_payload(structured, operation_status)
                    if produced_targets:
                        runtime_target_ids = produced_targets
            except Exception as exc:
                results.append(
                    {
                        "label": label,
                        "tool_id": tool_id,
                        "status": "failed",
                        "summary": str(exc)[:500],
                        "is_error": True,
                    }
                )
                previous_step_succeeded = False
        return tuple(results)

    async def _monitor_targets_disarmed(
        request_deps: Any,
        *,
        target_drone_ids: tuple[str, ...],
        mission_type: int,
        progress_callback: AssistantProgressCallback | None = None,
        timeout_seconds: float = ACTION_MONITOR_TIMEOUT_SECONDS,
        deadline_epoch_ms: float | None = None,
        sequence_id: str = "",
        step_index: int | None = None,
        step_count: int | None = None,
        step_label: str = "",
        command_id: str = "",
    ) -> dict[str, Any]:
        """Verify landed/disarmed state, plus home proximity for RTL, from fresh telemetry."""

        targets = tuple(dict.fromkeys(str(item).strip() for item in target_drone_ids if str(item).strip()))
        if not targets:
            return {
                "status": "unavailable",
                "verified": False,
                "summary": "Final disarm state is unavailable from live telemetry.",
            }

        def target_rows() -> list[Mapping[str, Any]]:
            rows: list[Mapping[str, Any]] = []
            telemetry_snapshot = _mapping_snapshot(
                getattr(request_deps, "telemetry_data_all_drones", {}) or {}
            )
            success_times = _mapping_snapshot(getattr(request_deps, "last_telemetry_time", {}) or {})
            heartbeat_snapshot: Mapping[Any, Any] = {}
            heartbeat_getter = getattr(request_deps, "get_all_heartbeats", None)
            if callable(heartbeat_getter):
                try:
                    heartbeat_snapshot = _mapping_snapshot(heartbeat_getter() or {})
                except Exception:
                    heartbeat_snapshot = {}
            for target in targets:
                row = _lookup_mapping_by_text_key(
                    telemetry_snapshot,
                    target,
                )
                if not isinstance(row, Mapping) or not row or not bool(row.get("telemetry_available", True)):
                    return []
                heartbeat = _lookup_mapping_by_text_key(heartbeat_snapshot, target)
                success_time = _lookup_mapping_by_text_key(success_times, target)
                if not _looks_live_for_action_target(
                    target=target,
                    telemetry_row=row,
                    heartbeat_row=heartbeat if isinstance(heartbeat, Mapping) else {},
                    telemetry_success_time=success_time,
                ):
                    return []
                rows.append(row)
            return rows

        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "verify",
                "state": "running",
                "label": _sequence_progress_label(
                    "Verifying final disarm state",
                    step_label=step_label,
                    step_index=step_index,
                    step_count=step_count,
                    activity="verifying disarm",
                ),
                **_sequence_progress_fields(
                    sequence_id=sequence_id,
                    step_index=step_index,
                    step_count=step_count,
                    step_label=step_label,
                    step_kind="flight_state",
                    command_id=command_id,
                ),
            },
        )
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        if deadline_epoch_ms is not None:
            try:
                remaining_seconds = (float(deadline_epoch_ms) - (time.time() * 1000.0)) / 1000.0
            except (TypeError, ValueError):
                remaining_seconds = 0.0
            if remaining_seconds > 0:
                deadline = asyncio.get_running_loop().time() + remaining_seconds + ACTION_MONITOR_POLL_SECONDS
        last_observations: list[dict[str, Any]] = []
        while True:
            rows = target_rows()
            observations = [
                _terminal_flight_state_observation(row, target=target, mission_type=mission_type)
                for target, row in zip(targets, rows)
            ]
            if observations:
                last_observations = observations
            if observations and all(bool(item.get("verified")) for item in observations):
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "verify",
                        "state": "complete",
                        "label": _sequence_progress_label(
                            "Final landed state verified",
                            step_label=step_label,
                            step_index=step_index,
                            step_count=step_count,
                            activity="landed and disarmed",
                        ),
                        **_sequence_progress_fields(
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=step_label,
                            step_kind="flight_state",
                            command_id=command_id,
                        ),
                    },
                )
                return {
                    "status": "verified",
                    "verified": True,
                    "summary": (
                        "Fresh target telemetry confirms landed and disarmed state"
                        + (" within the configured home threshold." if mission_type == 104 else ".")
                    ),
                    "mission_type": mission_type,
                    "thresholds": _final_state_thresholds(),
                    "targets": observations,
                }
            if asyncio.get_running_loop().time() >= deadline:
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "verify",
                        "state": "timeout",
                        "label": _sequence_progress_label(
                            "Final landed state not confirmed",
                            step_label=step_label,
                            step_index=step_index,
                            step_count=step_count,
                            activity="verification incomplete",
                        ),
                        **_sequence_progress_fields(
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=step_label,
                            step_kind="flight_state",
                            command_id=command_id,
                        ),
                    },
                )
                return {
                    "status": "timeout",
                    "verified": False,
                    "summary": "Final landed/RTL state was not confirmed from fresh telemetry before timeout.",
                    "mission_type": mission_type,
                    "thresholds": _final_state_thresholds(),
                    "targets": last_observations,
                }
            await asyncio.sleep(ACTION_MONITOR_POLL_SECONDS)

    def _post_action_status_is_error(status: Any, *, explicit_error: bool = False) -> bool:
        if explicit_error:
            return True
        normalized = str(status or "").strip().casefold()
        return normalized in {
            "error",
            "failed",
            "failure",
            "partial",
            "rejected",
            "skipped",
            "timeout",
            "timed_out",
            "terminal_non_success",
        }

    def _action_sequence_max_wait_seconds() -> float:
        try:
            value = float(os.getenv("MDS_AGENT_SEQUENCE_MAX_WAIT_SEC", "300"))
        except (TypeError, ValueError):
            return 300.0
        return value if value > 0 else 300.0

    def _validated_post_action_delay_seconds(value: Any) -> float:
        try:
            delay_seconds = float(value)
        except (TypeError, ValueError):
            raise ValueError("Sequence wait must be a number of seconds.")
        if delay_seconds <= 0:
            raise ValueError("Sequence wait must be greater than zero seconds.")
        maximum = _action_sequence_max_wait_seconds()
        if delay_seconds > maximum:
            raise ValueError(
                f"Requested wait is {delay_seconds:g}s; this deployment allows at most {maximum:g}s per sequence step."
            )
        return delay_seconds

    def _post_action_sequence_validation_error(post_actions: tuple[Mapping[str, Any], ...]) -> str:
        for item in post_actions:
            if str(item.get("type") or "").strip().casefold() != "delay":
                continue
            try:
                _validated_post_action_delay_seconds(item.get("delay_seconds"))
            except ValueError as exc:
                return str(exc)
        return ""

    def _command_monitor_deadline_epoch_ms(monitor_result: Mapping[str, Any] | None) -> float | None:
        command_status = monitor_result.get("command_status") if isinstance(monitor_result, Mapping) else None
        if not isinstance(command_status, Mapping):
            return None
        try:
            timeout_at = float(command_status.get("timeout_at"))
        except (TypeError, ValueError):
            return None
        return timeout_at if timeout_at > 0 else None

    async def _sleep_post_action_delay(
        delay_seconds: float,
        *,
        progress_tick: Callable[[float], Awaitable[None]] | None = None,
    ) -> bool:
        return await _sleep_action_run_delay(
            "",
            delay_seconds,
            progress_tick=progress_tick,
        )

    async def _monitor_sitl_operation(
        execution_target: Request | InternalToolExecutionContext,
        *,
        operation_id: str,
        monitor_config: Mapping[str, Any],
        registry: Any,
        policy: Any,
        progress_callback: AssistantProgressCallback | None = None,
        action_run_id: str = "",
        timeout_seconds: float = ACTION_MONITOR_TIMEOUT_SECONDS,
        sequence_id: str = "",
        step_index: int | None = None,
        step_count: int | None = None,
        step_label: str = "",
    ) -> dict[str, Any]:
        execution_context = (
            execution_target
            if isinstance(execution_target, InternalToolExecutionContext)
            else InternalToolExecutionContext.from_request(execution_target)
        )
        loop = asyncio.get_running_loop()
        monitor_started_at = loop.time()
        deadline = monitor_started_at + timeout_seconds
        next_heartbeat_at = monitor_started_at + ACTION_MONITOR_HEARTBEAT_SECONDS
        operation_deadline_loaded = False
        last_status: Mapping[str, Any] = {}
        cancel_requested = False
        cancel_notice_emitted = False
        monitor_tool_id = str(monitor_config.get("monitor_tool_id") or "").strip()
        completion_config = (
            monitor_config.get("completion_evidence")
            if isinstance(monitor_config.get("completion_evidence"), Mapping)
            else {}
        )
        if not monitor_tool_id:
            return {
                "operation_id": operation_id,
                "status": "monitor_error",
                "success": False,
                "timed_out": False,
                "summary": "The tool registry does not declare a SITL operation status tool.",
            }
        sequence_fields = _sequence_progress_fields(
            sequence_id=sequence_id,
            step_index=step_index,
            step_count=step_count,
            step_label=step_label,
            step_kind="registry_action",
        )

        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "monitor",
                "state": "running",
                "label": "Monitoring SITL operation",
                "operation_id": operation_id,
                **sequence_fields,
            },
        )
        last_progress_signature: tuple[Any, ...] | None = None
        while True:
            if await action_run_cancel_requested_async(action_run_id):
                cancel_requested = True
                if not cancel_notice_emitted:
                    cancel_notice_emitted = True
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "monitor",
                            "state": "running",
                            "label": "Cancellation requested; waiting for current SITL operation to finish",
                            "operation_id": operation_id,
                            "summary": (
                                "No later sequence step will be dispatched. "
                                "This control does not abort the executing SITL operation."
                            ),
                            "control_effect": "cancel_remaining",
                            **sequence_fields,
                        },
                    )
                    next_heartbeat_at = loop.time() + ACTION_MONITOR_HEARTBEAT_SECONDS
            result = await execute_policy_allowed_read_only_tool(
                execution_context,
                name=monitor_tool_id,
                arguments={"operation_id": operation_id},
                channel="agent",
                registry=registry,
                policy=policy,
                timeout_seconds=min(20.0, max(2.0, timeout_seconds)),
            )
            structured = result.structured_content if isinstance(result.structured_content, Mapping) else {}
            if result.is_error:
                summary = (
                    structured.get("detail")
                    or structured.get("summary")
                    or result.text
                    or f"SITL operation status tool returned HTTP {result.status_code}."
                )
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "monitor",
                        "state": "failed",
                        "label": "SITL operation status unavailable",
                        "operation_id": operation_id,
                        "summary": str(summary)[:500],
                        **sequence_fields,
                    },
                )
                return {
                    "operation_id": operation_id,
                    "status": "failed",
                    "success": False,
                    "timed_out": False,
                    "summary": str(summary)[:500],
                    "http_status": result.status_code,
                }
            if structured:
                last_status = structured
                if not operation_deadline_loaded:
                    metadata = structured.get("metadata") if isinstance(structured.get("metadata"), Mapping) else {}
                    try:
                        operation_timeout = float(metadata.get("monitor_timeout_seconds"))
                    except (TypeError, ValueError):
                        operation_timeout = 0.0
                    if operation_timeout > 0:
                        deadline = loop.time() + operation_timeout
                        operation_deadline_loaded = True

                operation_status = _compact_status_value(structured.get("status"))
                operation_summary = str(structured.get("summary") or structured.get("detail") or "SITL operation in progress")
                signature = (
                    operation_status.casefold(),
                    operation_summary,
                    tuple(str(item) for item in (structured.get("affected_instances") or [])),
                )
                if signature != last_progress_signature and not _operation_terminal(structured):
                    last_progress_signature = signature
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "monitor",
                            "state": "running",
                            "label": operation_summary[:160],
                            "summary": str(structured.get("detail") or operation_summary)[:500],
                            "operation_id": operation_id,
                            "operation_type": str(structured.get("operation_type") or ""),
                            "affected_instances": list(structured.get("affected_instances") or []),
                            "operation_status": operation_status,
                            **sequence_fields,
                        },
                    )
                    next_heartbeat_at = loop.time() + ACTION_MONITOR_HEARTBEAT_SECONDS
                if _operation_terminal(structured):
                    if not _operation_success(structured):
                        await _emit_assistant_progress(
                            progress_callback,
                            {
                                "stage": "monitor",
                                "state": "failed",
                                "label": operation_summary[:160],
                                "operation_id": operation_id,
                                "operation_status": operation_status,
                                **sequence_fields,
                            },
                        )
                        return {
                            **dict(structured),
                            "success": False,
                            "timed_out": operation_status.casefold() == "timeout",
                            "cancel_requested": cancel_requested,
                        }
                    break
            observed_at = loop.time()
            if observed_at >= next_heartbeat_at:
                await _emit_assistant_progress(
                    progress_callback,
                    _monitor_heartbeat_progress_payload(
                        started_at=monitor_started_at,
                        observed_at=observed_at,
                        label="SITL operation monitoring is active",
                        latest_evidence={
                            "source": "sitl_operation",
                            "operation_id": operation_id,
                            "status": _compact_status_value(last_status.get("status")),
                            "operation_type": str(last_status.get("operation_type") or "")[:80],
                            "summary": str(
                                last_status.get("summary")
                                or last_status.get("detail")
                                or ""
                            )[:240],
                            "affected_instances": [
                                str(item)[:80]
                                for item in (last_status.get("affected_instances") or [])
                            ][:20],
                        },
                        sequence_id=sequence_id,
                        step_index=step_index,
                        step_count=step_count,
                        step_label=step_label,
                        step_kind="registry_action",
                    ),
                )
                next_heartbeat_at = observed_at + ACTION_MONITOR_HEARTBEAT_SECONDS
            if observed_at >= deadline:
                summary = "SITL operation did not reach terminal status during the monitor window."
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "monitor",
                        "state": "timeout",
                        "label": "SITL operation monitoring timed out",
                        "operation_id": operation_id,
                        "summary": summary,
                        **sequence_fields,
                    },
                )
                return {
                    "operation_id": operation_id,
                    "status": "timeout",
                    "success": False,
                    "timed_out": True,
                    "cancel_requested": cancel_requested,
                    "summary": summary,
                    "last_status": dict(last_status),
                }
            await asyncio.sleep(ACTION_MONITOR_POLL_SECONDS)

        if str(completion_config.get("strategy") or "").strip() != "sitl_lifecycle":
            await _emit_assistant_progress(
                progress_callback,
                {
                    "stage": "monitor",
                    "state": "complete",
                    "label": str(last_status.get("summary") or "SITL operation complete")[:160],
                    "operation_id": operation_id,
                    **sequence_fields,
                },
            )
            return {
                **dict(last_status),
                "success": True,
                "timed_out": False,
                "cancel_requested": cancel_requested,
            }

        available_source_ids = {
            role: str(completion_config.get(f"{role}_tool_id") or "").strip()
            for role in ("instances", "heartbeats", "telemetry")
        }
        required_roles = sitl_lifecycle_evidence_roles(last_status)
        source_ids = {
            role: available_source_ids.get(role, "")
            for role in required_roles
        }
        if any(not tool_id for tool_id in source_ids.values()):
            return {
                **dict(last_status),
                "status": "monitor_error",
                "success": False,
                "timed_out": False,
                "summary": "The tool registry has an incomplete SITL completion-evidence declaration.",
            }

        readiness_deadline = loop.time() + _sitl_readiness_timeout_seconds()
        last_verification: Mapping[str, Any] = {}
        last_readiness_signature: tuple[Any, ...] | None = None
        while True:
            if await action_run_cancel_requested_async(action_run_id):
                cancel_requested = True
                if not cancel_notice_emitted:
                    cancel_notice_emitted = True
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "verify",
                            "state": "running",
                            "label": "Cancellation requested; finishing SITL readiness verification",
                            "operation_id": operation_id,
                            "summary": (
                                "The dispatched SITL operation already reached terminal state. "
                                "No later sequence step will be dispatched."
                            ),
                            "control_effect": "cancel_remaining",
                            **sequence_fields,
                        },
                    )
                    next_heartbeat_at = loop.time() + ACTION_MONITOR_HEARTBEAT_SECONDS
            evidence_results = await asyncio.gather(
                *(
                    execute_policy_allowed_read_only_tool(
                        execution_context,
                        name=tool_id,
                        arguments={},
                        channel="agent",
                        registry=registry,
                        policy=policy,
                    )
                    for tool_id in source_ids.values()
                )
            )
            evidence_by_role = dict(zip(source_ids, evidence_results))
            instances_result = evidence_by_role["instances"]
            evidence_errors = [item for item in evidence_results if item.is_error]
            permanent_error = next(
                (
                    item
                    for item in evidence_errors
                    if item.status_code in {400, 401, 403, 404, 405, 422}
                ),
                None,
            )
            if permanent_error is not None:
                failed_result = permanent_error
                summary = str(failed_result.text or "SITL completion evidence is unavailable")[:500]
                verification = {
                    "kind": "sitl_lifecycle",
                    "status": "unavailable",
                    "verified": False,
                    "summary": summary,
                    "evidence_tool_ids": list(source_ids.values()),
                }
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "verify",
                        "state": "failed",
                        "label": "SITL readiness evidence unavailable",
                        "operation_id": operation_id,
                        "summary": summary,
                        **sequence_fields,
                    },
                )
                return {
                    **dict(last_status),
                    "status": "completion_unavailable",
                    "success": False,
                    "timed_out": False,
                    "summary": summary,
                    "completion_verification": verification,
                }

            if evidence_errors:
                summary = str(
                    next(
                        (
                            item.text
                            for item in evidence_errors
                            if str(item.text or "").strip()
                        ),
                        "SITL readiness evidence is temporarily unavailable.",
                    )
                )[:500]
                signature = (
                    "evidence_retry",
                    tuple((item.status_code, str(item.text or "")[:160]) for item in evidence_errors),
                )
                if signature != last_readiness_signature:
                    last_readiness_signature = signature
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "verify",
                            "state": "running",
                            "label": "Waiting for SITL readiness evidence",
                            "operation_id": operation_id,
                            "summary": summary,
                            **sequence_fields,
                        },
                    )
                    next_heartbeat_at = loop.time() + ACTION_MONITOR_HEARTBEAT_SECONDS
                observed_at = loop.time()
                if observed_at >= next_heartbeat_at:
                    await _emit_assistant_progress(
                        progress_callback,
                        _monitor_heartbeat_progress_payload(
                            started_at=monitor_started_at,
                            observed_at=observed_at,
                            label="SITL readiness monitoring is active",
                            latest_evidence={
                                "source": "sitl_readiness",
                                "operation_id": operation_id,
                                "status": "evidence_retry",
                                "summary": summary,
                            },
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=step_label,
                            step_kind="registry_action",
                        ),
                    )
                    next_heartbeat_at = observed_at + ACTION_MONITOR_HEARTBEAT_SECONDS
                if observed_at >= readiness_deadline:
                    verification = {
                        "kind": "sitl_lifecycle",
                        "status": "timeout",
                        "verified": False,
                        "summary": summary,
                        "evidence_tool_ids": list(source_ids.values()),
                    }
                    return {
                        **dict(last_status),
                        "status": "timeout",
                        "success": False,
                        "timed_out": True,
                        "cancel_requested": cancel_requested,
                        "summary": summary,
                        "completion_verification": verification,
                    }
                await asyncio.sleep(ACTION_MONITOR_POLL_SECONDS)
                continue

            verification = evaluate_sitl_lifecycle_completion(
                operation=last_status,
                instances_payload=instances_result.structured_content,
                heartbeats_payload=(
                    evidence_by_role["heartbeats"].structured_content
                    if "heartbeats" in evidence_by_role
                    else None
                ),
                telemetry_payload=(
                    evidence_by_role["telemetry"].structured_content
                    if "telemetry" in evidence_by_role
                    else None
                ),
            )
            verification = {
                **verification,
                "evidence_tool_ids": list(source_ids.values()),
            }
            last_verification = verification
            signature = (
                verification.get("status"),
                verification.get("label"),
                tuple(verification.get("blockers") or []),
            )
            if signature != last_readiness_signature:
                last_readiness_signature = signature
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "verify",
                        "state": "complete" if verification.get("verified") else "running",
                        "label": str(verification.get("label") or "Verifying SITL readiness")[:160],
                        "operation_id": operation_id,
                        "summary": str(verification.get("summary") or "")[:500],
                        "completion_verification": dict(verification),
                        **sequence_fields,
                    },
                )
                next_heartbeat_at = loop.time() + ACTION_MONITOR_HEARTBEAT_SECONDS
            if verification.get("verified"):
                return {
                    **dict(last_status),
                    "status": "succeeded",
                    "success": True,
                    "timed_out": False,
                    "cancel_requested": cancel_requested,
                    "summary": str(verification.get("summary") or last_status.get("summary") or "SITL operation complete"),
                    "completion_verification": dict(verification),
                }
            if verification.get("status") in {"unavailable", "unsupported"}:
                return {
                    **dict(last_status),
                    "status": "completion_unavailable",
                    "success": False,
                    "timed_out": False,
                    "cancel_requested": cancel_requested,
                    "summary": str(verification.get("summary") or "SITL completion evidence is unavailable."),
                    "completion_verification": dict(verification),
                }
            observed_at = loop.time()
            if observed_at >= next_heartbeat_at:
                await _emit_assistant_progress(
                    progress_callback,
                    _monitor_heartbeat_progress_payload(
                        started_at=monitor_started_at,
                        observed_at=observed_at,
                        label="SITL readiness monitoring is active",
                        latest_evidence={
                            "source": "sitl_readiness",
                            "operation_id": operation_id,
                            "status": str(verification.get("status") or "")[:80],
                            "summary": str(verification.get("summary") or "")[:240],
                            "blockers": [
                                str(item)[:160]
                                for item in (verification.get("blockers") or [])
                            ][:20],
                        },
                        sequence_id=sequence_id,
                        step_index=step_index,
                        step_count=step_count,
                        step_label=step_label,
                        step_kind="registry_action",
                    ),
                )
                next_heartbeat_at = observed_at + ACTION_MONITOR_HEARTBEAT_SECONDS
            if observed_at >= readiness_deadline:
                summary = str(
                    last_verification.get("summary")
                    or "SITL operation completed, but readiness was not verified before timeout."
                )
                timeout_verification = {
                    "kind": "sitl_lifecycle",
                    **dict(last_verification),
                    "status": "timeout",
                    "verified": False,
                    "summary": summary,
                }
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "verify",
                        "state": "timeout",
                        "label": "SITL readiness verification timed out",
                        "operation_id": operation_id,
                        "summary": summary,
                        **sequence_fields,
                    },
                )
                return {
                    **dict(last_status),
                    "status": "timeout",
                    "success": False,
                    "timed_out": True,
                    "cancel_requested": cancel_requested,
                    "summary": summary,
                    "completion_verification": timeout_verification,
                }
            await asyncio.sleep(ACTION_MONITOR_POLL_SECONDS)

    async def _wait_for_action_run_dispatch(
        run_id: str,
        *,
        ownership: ActionRunOwnership | None = None,
    ) -> bool:
        """Wait at a safe step boundary; stop on control, terminal, or lost ownership."""

        while True:
            try:
                run = (
                    await action_run_renew_async(ownership)
                    if ownership is not None
                    else await action_run_require_async(run_id)
                )
            except (ActionRunOwnershipError, KeyError):
                return False
            if run.terminal:
                return False
            if run.state in {"cancel_requested", "cancelled"} or run.control_state == "cancel_requested":
                return False
            if run.state in {"pause_requested", "paused"} or run.control_state == "pause_requested":
                if run.state != "paused":
                    await action_run_append_event_async(
                        run_id,
                        event_type="run_paused",
                        payload={
                            "stage": "action",
                            "state": "paused",
                            "label": "Action run paused before the next step",
                        },
                        state="paused",
                        summary="Paused before dispatching the next step.",
                        ownership=ownership,
                    )
                await asyncio.sleep(0.25)
                continue
            return True

    async def _sleep_action_run_delay(
        run_id: str,
        delay_seconds: float,
        *,
        progress_tick: Callable[[float], Awaitable[None]] | None = None,
        ownership: ActionRunOwnership | None = None,
    ) -> bool:
        """Complete an active delay while honoring cancellation and ownership."""

        async def current_step_may_continue() -> bool:
            try:
                run = (
                    await action_run_renew_async(ownership)
                    if ownership is not None
                    else await action_run_require_async(run_id)
                )
            except (ActionRunOwnershipError, KeyError):
                return False
            if run.terminal:
                return False
            return not (
                run.state in {"cancel_requested", "cancelled"}
                or run.control_state == "cancel_requested"
            )

        remaining = delay_seconds
        progress_interval = max(1.0, min(5.0, delay_seconds / 10.0))
        next_progress_at = max(0.0, delay_seconds - progress_interval)
        while remaining > 0:
            if run_id and not await current_step_may_continue():
                return False
            sleep_for = min(0.25, remaining)
            await _sleep_action_sequence_delay(sleep_for)
            remaining = max(0.0, remaining - sleep_for)
            if progress_tick is not None and remaining > 0 and remaining <= next_progress_at:
                await progress_tick(remaining)
                next_progress_at = max(0.0, next_progress_at - progress_interval)
        return True

    async def _record_skipped_post_actions(
        post_actions: tuple[Mapping[str, Any], ...],
        *,
        reason: str,
        progress_callback: AssistantProgressCallback | None,
        sequence_id: str,
        initial_step_index: int,
        step_count: int | None,
    ) -> tuple[Mapping[str, Any], ...]:
        results: list[Mapping[str, Any]] = []
        for index, item in enumerate(post_actions, start=1):
            label = str(item.get("action_label") or item.get("tool_id") or item.get("type") or "post-action")
            step_index = initial_step_index + index
            await _emit_assistant_progress(
                progress_callback,
                {
                    "stage": "action",
                    "state": "skipped",
                    "label": _sequence_progress_label(
                        f"Skipped post-action: {label}",
                        step_label=label,
                        step_index=step_index,
                        step_count=step_count,
                        activity="skipped after incomplete final-state verification",
                    ),
                    "tool_id": str(item.get("tool_id") or ""),
                    **_sequence_progress_fields(
                        sequence_id=sequence_id,
                        step_index=step_index,
                        step_count=step_count,
                        step_label=label,
                        step_kind=str(item.get("type") or "post_action"),
                    ),
                },
            )
            results.append(
                {
                    "label": label,
                    "tool_id": str(item.get("tool_id") or ""),
                    "type": str(item.get("type") or "post_action"),
                    "status": "skipped",
                    "summary": reason,
                    "is_error": True,
                }
            )
        return tuple(results)

    async def _execute_action_draft_now(
        execution_context: InternalToolExecutionContext,
        *,
        draft: ActionDraft,
        registry: Any,
        policy: Any,
        actor_role: str,
        request_deps: Any,
        progress_callback: AssistantProgressCallback | None = None,
        run_id: str = "",
        action_run_ownership: ActionRunOwnership | None = None,
        execution_guard_arguments: Mapping[str, Any] | None = None,
    ) -> ActionExecutionOutcome:
        """Execute one approved typed draft through canonical GCS paths."""

        action_response: Any | None = None
        monitor_result: Mapping[str, Any] | None = None
        post_action_results: tuple[Mapping[str, Any], ...] = ()
        rejection_detail = ""
        action_execution = "validation_rejected"
        try:
            if isinstance(draft, FlightActionDraft):
                command_payload = {
                    **dict(draft.command_payload),
                    "idempotency_key": f"simurgh:{draft.draft_id}",
                }
                command = SubmitCommandRequest.model_validate(command_payload)
                async with action_policy_dispatch_lock:
                    current_policy = load_default_policy()
                    current_decision = current_policy.evaluate_tool(
                        registry.get(ACTION_TOOL_ID),
                        channel="agent",
                        approved=True,
                        actor_role=actor_role,
                    )
                    if current_decision.status is not PolicyDecisionStatus.ALLOW:
                        reasons = tuple(current_decision.reasons)
                        return ActionExecutionOutcome(
                            action_execution=(
                                "blocked_by_circuit_breaker"
                                if any("circuit breaker" in reason for reason in reasons)
                                else "policy_denied"
                            ),
                            rejection_detail="; ".join(reasons),
                        )
                    action_response = await submit_tracked_command(request_deps, command)
                action_execution = "submitted"
                response_payload = (
                    action_response.model_dump(mode="json")
                    if hasattr(action_response, "model_dump")
                    else dict(action_response or {})
                )
                command_id = str(response_payload.get("command_id") or "").strip()
                if command_id:
                    sequence_step_count = (
                        1 + len(draft.post_actions)
                        if draft.post_actions or run_id
                        else None
                    )
                    monitor_result = await _monitor_command_until_terminal(
                        request_deps,
                        command_id,
                        progress_callback=progress_callback,
                        action_run_id=run_id,
                        sequence_id=run_id or (draft.draft_id if draft.post_actions else ""),
                        step_index=1 if sequence_step_count else None,
                        step_count=sequence_step_count,
                        step_label=_action_draft_label(draft) if draft.post_actions else "",
                        step_kind="flight_command",
                        mission_name=draft.mission_name,
                        verify_landed_state=draft.mission_type
                        in {Mission.LAND.value, Mission.RETURN_RTL.value},
                    )
                    final_state_ready = True
                    if (
                        monitor_result.get("success")
                        and draft.mission_type
                        in {Mission.LAND.value, Mission.RETURN_RTL.value}
                    ):
                        completion_verification = await _monitor_targets_disarmed(
                            request_deps,
                            target_drone_ids=draft.target_drone_ids,
                            mission_type=draft.mission_type,
                            progress_callback=progress_callback,
                            sequence_id=run_id or (draft.draft_id if draft.post_actions else ""),
                            step_index=1 if sequence_step_count else None,
                            step_count=sequence_step_count,
                            step_label=_action_draft_label(draft),
                            command_id=command_id,
                            deadline_epoch_ms=_command_monitor_deadline_epoch_ms(monitor_result),
                        )
                        monitor_result = {
                            **dict(monitor_result),
                            "completion_verification": dict(completion_verification),
                        }
                        final_state_ready = bool(completion_verification.get("verified"))
                        if not final_state_ready:
                            monitor_result = {
                                **dict(monitor_result),
                                "command_success": bool(monitor_result.get("success")),
                                "success": False,
                                "status": "completion_unverified",
                                "summary": str(completion_verification.get("summary") or "Final state not verified."),
                            }
                    if draft.post_actions and final_state_ready:
                        post_action_results = await _execute_post_actions(
                            execution_context,
                            post_actions=draft.post_actions,
                            registry=registry,
                            policy=policy,
                            actor_role=actor_role,
                            request_deps=request_deps,
                            progress_callback=progress_callback,
                            sequence_id=run_id or draft.draft_id,
                            idempotency_scope=draft.draft_id,
                            initial_step_index=1,
                            step_count=sequence_step_count,
                            action_run_id=run_id,
                            action_run_ownership=action_run_ownership,
                            initial_previous_step_succeeded=bool(monitor_result.get("success")),
                        )
                    elif draft.post_actions and not final_state_ready:
                        post_action_results = await _record_skipped_post_actions(
                            draft.post_actions,
                            reason="Final landed/RTL state was not verified; dependent steps were not dispatched.",
                            progress_callback=progress_callback,
                            sequence_id=run_id or draft.draft_id,
                            initial_step_index=1,
                            step_count=sequence_step_count,
                        )
                else:
                    monitor_result = {
                        "status": "monitor_error",
                        "success": False,
                        "timed_out": False,
                        "summary": "GCS accepted the command submission without a trackable command ID.",
                    }
            elif isinstance(draft, RegistryActionDraft):
                sequence_step_count = (
                    1 + len(draft.post_actions)
                    if draft.post_actions or run_id
                    else None
                )
                async with action_policy_dispatch_lock:
                    current_policy = load_default_policy()
                    current_decision = current_policy.evaluate_tool(
                        registry.get(draft.tool_id),
                        channel="agent",
                        approved=True,
                        actor_role=actor_role,
                    )
                    if current_decision.status is not PolicyDecisionStatus.ALLOW:
                        reasons = tuple(current_decision.reasons)
                        return ActionExecutionOutcome(
                            action_execution=(
                                "blocked_by_circuit_breaker"
                                if any("circuit breaker" in reason for reason in reasons)
                                else "policy_denied"
                            ),
                            rejection_detail="; ".join(reasons),
                        )
                    result = await execute_policy_allowed_guarded_route_tool(
                        execution_context,
                        name=draft.tool_id,
                        arguments={
                            **dict(draft.arguments),
                            **dict(execution_guard_arguments or {}),
                        },
                        channel="agent",
                        approved=True,
                        actor_role=actor_role,
                        registry=registry,
                        policy=current_policy,
                    )
                action_response = result.structured_content or {
                    "status_code": result.status_code,
                    "response": result.text,
                }
                if result.is_error:
                    rejection_detail = result.text
                else:
                    action_execution = "submitted"
                    structured = result.structured_content if isinstance(result.structured_content, Mapping) else {}
                    operation_id = str(structured.get("operation_id") or structured.get("id") or "").strip()
                    if draft.monitor_requested:
                        if operation_id:
                            action_tool = registry.require(draft.tool_id)
                            monitor_result = await _monitor_sitl_operation(
                                execution_context,
                                operation_id=operation_id,
                                monitor_config=action_tool.assistant_action,
                                registry=registry,
                                policy=policy,
                                progress_callback=progress_callback,
                                action_run_id=run_id,
                                sequence_id=run_id or (draft.draft_id if draft.post_actions else ""),
                                step_index=1 if sequence_step_count else None,
                                step_count=sequence_step_count,
                                step_label=draft.action_label if draft.post_actions else "",
                            )
                        else:
                            monitor_result = {
                                "status": "monitor_error",
                                "success": False,
                                "timed_out": False,
                                "summary": "GCS accepted the operation without a trackable operation ID.",
                            }
                    primary_succeeded = bool(
                        not result.is_error
                        and (
                            not draft.monitor_requested
                            or (monitor_result and monitor_result.get("success"))
                        )
                    )
                    if draft.post_actions and primary_succeeded:
                        post_action_results = await _execute_post_actions(
                            execution_context,
                            post_actions=draft.post_actions,
                            registry=registry,
                            policy=policy,
                            actor_role=actor_role,
                            request_deps=request_deps,
                            progress_callback=progress_callback,
                            sequence_id=run_id or draft.draft_id,
                            idempotency_scope=draft.draft_id,
                            initial_step_index=1,
                            step_count=sequence_step_count,
                            action_run_id=run_id,
                            action_run_ownership=action_run_ownership,
                            initial_previous_step_succeeded=True,
                            initial_target_drone_ids=_submitted_registry_target_ids(
                                draft,
                                response_payload=structured,
                                monitor_result=monitor_result,
                            ),
                        )
                    elif draft.post_actions:
                        post_action_results = await _record_skipped_post_actions(
                            draft.post_actions,
                            reason="The preceding system action did not complete successfully.",
                            progress_callback=progress_callback,
                            sequence_id=run_id or draft.draft_id,
                            initial_step_index=1,
                            step_count=sequence_step_count,
                        )
        except HTTPException as exc:
            rejection_detail = str(exc.detail)
            if action_execution == "submitted":
                monitor_result = {
                    **dict(monitor_result or {}),
                    "status": "monitor_error",
                    "success": False,
                    "timed_out": False,
                    "summary": rejection_detail,
                }
            else:
                action_execution = "validation_rejected"
        except Exception as exc:
            rejection_detail = str(exc)
            if action_execution == "submitted":
                monitor_result = {
                    **dict(monitor_result or {}),
                    "status": "monitor_error",
                    "success": False,
                    "timed_out": False,
                    "summary": rejection_detail,
                }
            else:
                action_execution = "validation_rejected"
        return ActionExecutionOutcome(
            action_execution=action_execution,
            action_response=action_response,
            monitor_result=monitor_result,
            post_action_results=post_action_results,
            rejection_detail=rejection_detail,
        )

    def _action_run_total_steps(draft: ActionDraft) -> int:
        return 1 + len(draft.post_actions)

    def _action_response_payload(value: Any | None) -> dict[str, Any]:
        if value is None:
            return {}
        if hasattr(value, "model_dump"):
            payload = value.model_dump(mode="json")
            return dict(payload) if isinstance(payload, Mapping) else {}
        return dict(value) if isinstance(value, Mapping) else {"summary": str(value)[:500]}

    async def _run_action_run(
        execution_context: InternalToolExecutionContext,
        *,
        run_id: str,
        ownership: ActionRunOwnership,
        actor: str,
        actor_role: str,
        session_id: str,
        draft: ActionDraft,
        request_deps: Any,
    ) -> None:
        """Serialize condition-check and execution for shared SITL lifecycle state."""

        async def execute() -> None:
            if _action_draft_uses_sitl_lifecycle_resource(draft):
                async with sitl_action_run_lock:
                    await _run_action_run_unlocked(
                        execution_context,
                        run_id=run_id,
                        ownership=ownership,
                        actor=actor,
                        actor_role=actor_role,
                        session_id=session_id,
                        draft=draft,
                        request_deps=request_deps,
                    )
                return
            await _run_action_run_unlocked(
                execution_context,
                run_id=run_id,
                ownership=ownership,
                actor=actor,
                actor_role=actor_role,
                session_id=session_id,
                draft=draft,
                request_deps=request_deps,
            )

        await _run_with_action_run_ownership(
            execute(),
            renew_ownership=action_run_renew_async,
            ownership=ownership,
            lease_seconds=action_runner_lease_seconds,
        )

    async def _run_action_run_unlocked(
        execution_context: InternalToolExecutionContext,
        *,
        run_id: str,
        ownership: ActionRunOwnership,
        actor: str,
        actor_role: str,
        session_id: str,
        draft: ActionDraft,
        request_deps: Any,
    ) -> None:
        """Execute a confirmed run independently from its chat transport."""

        try:
            async def append_run_event(**kwargs: Any) -> Any:
                return await action_run_append_event_async(
                    run_id,
                    ownership=ownership,
                    **kwargs,
                )

            await append_run_event(
                event_type="run_started",
                payload={
                    "stage": "action",
                    "state": "running",
                    "label": "Starting approved action run",
                    "sequence_id": run_id,
                    "step_count": _action_run_total_steps(draft),
                },
                state="running",
                summary="Executing the approved action plan.",
            )

            if not await _wait_for_action_run_dispatch(run_id, ownership=ownership):
                summary = "Action run cancelled before the first step was dispatched."
                await append_run_event(
                    event_type="run_cancelled",
                    payload={"stage": "action", "state": "cancelled", "label": summary},
                    state="cancelled",
                    summary=summary,
                    result={"action_execution": "cancelled", "dispatched_steps": 0},
                )
                return

            registry = load_default_tool_registry()
            policy = load_default_policy()
            tool = registry.require(_action_draft_tool_id(draft))
            execution_guard_arguments: dict[str, Any] = {}
            decision = policy.evaluate_tool(
                tool,
                channel="agent",
                approved=True,
                actor_role=actor_role,
            )
            if decision.status is not PolicyDecisionStatus.ALLOW:
                summary = "; ".join(decision.reasons) or "Current Simurgh policy blocked the approved action."
                await append_run_event(
                    event_type="run_blocked",
                    payload={
                        "stage": "safety",
                        "state": "blocked",
                        "label": "Current policy blocked action dispatch",
                        "summary": summary,
                    },
                    state="blocked",
                    summary=summary,
                    result={"action_execution": "policy_denied", "policy_reasons": list(decision.reasons)},
                )
                return

            if draft.preconditions:
                precondition_evaluation = await _evaluate_draft_preconditions(
                    execution_context,
                    draft=draft,
                    registry=registry,
                    policy=policy,
                )
                precondition_payload = precondition_evaluation.public_payload()
                await append_run_event(
                    event_type="precondition_checked",
                    payload={
                        "stage": "condition",
                        "state": (
                            "complete"
                            if precondition_evaluation.status == "met"
                            else "skipped"
                            if precondition_evaluation.status == "not_met"
                            else "blocked"
                        ),
                        "label": {
                            "met": "Action conditions met",
                            "not_met": "Action no longer needed",
                            "unavailable": "Action condition unavailable",
                        }.get(precondition_evaluation.status, "Action condition checked"),
                        "evaluation": precondition_payload,
                    },
                    state="running",
                    summary="Checked current action conditions before dispatch.",
                )
                if precondition_evaluation.status in {"not_met", "unavailable"}:
                    final_state = (
                        "skipped"
                        if precondition_evaluation.status == "not_met"
                        else "blocked"
                    )
                    summary = (
                        "Action skipped because its required condition is no longer met."
                        if final_state == "skipped"
                        else "Action blocked because its required condition could not be verified."
                    )
                    await append_run_event(
                        event_type=f"run_{final_state}",
                        payload={
                            "stage": "condition",
                            "state": final_state,
                            "label": summary,
                            "evaluation": precondition_payload,
                        },
                        state=final_state,
                        summary=summary,
                        result={
                            "action_execution": (
                                "precondition_not_met"
                                if final_state == "skipped"
                                else "precondition_unavailable"
                            ),
                            "action_preconditions": precondition_payload,
                            "dispatched_steps": 0,
                        },
                    )
                    run_snapshot = await action_run_require_async(run_id)
                    audit.record(
                        "action_run_completed",
                        session_id=session_id,
                        actor=actor,
                        tool_id=_action_draft_tool_id(draft),
                        decision=final_state,
                        payload={
                            "run_id": run_id,
                            "draft_id": draft.draft_id,
                            "plan_hash": run_snapshot.plan_hash,
                        },
                        metadata={"state": final_state, "summary": summary},
                    )
                    return
                execution_guard_arguments = _execution_guard_arguments(
                    tool,
                    precondition_evaluation,
                )

            if not await _wait_for_action_run_dispatch(run_id, ownership=ownership):
                summary = "Action run cancelled before the first step was dispatched."
                await append_run_event(
                    event_type="run_cancelled",
                    payload={
                        "stage": "action",
                        "state": "cancelled",
                        "label": summary,
                    },
                    state="cancelled",
                    summary=summary,
                    result={"action_execution": "cancelled", "dispatched_steps": 0},
                )
                return

            async def progress_callback(payload: dict[str, Any]) -> None:
                try:
                    step_index = int(payload.get("step_index") or 0)
                except (TypeError, ValueError):
                    step_index = 0
                await append_run_event(
                    event_type="progress",
                    payload={**dict(payload), "sequence_id": run_id},
                    state="running",
                    current_step=step_index if step_index > 0 else None,
                    summary=str(payload.get("label") or "Action run in progress")[:1000],
                )

            outcome = await _execute_action_draft_now(
                execution_context,
                draft=draft,
                registry=registry,
                policy=policy,
                actor_role=actor_role,
                request_deps=request_deps,
                progress_callback=progress_callback,
                run_id=run_id,
                action_run_ownership=ownership,
                execution_guard_arguments=execution_guard_arguments,
            )
            action_response = _action_response_payload(outcome.action_response)
            result_payload = {
                "action_execution": outcome.action_execution,
                "action_response": action_response,
                "monitor_result": dict(outcome.monitor_result or {}),
                "post_action_results": [dict(item) for item in outcome.post_action_results],
                "rejection_detail": outcome.rejection_detail,
            }
            run_snapshot = await action_run_require_async(run_id)
            cancelled = (
                run_snapshot.state == "cancel_requested"
                or run_snapshot.control_state == "cancel_requested"
                or bool((outcome.monitor_result or {}).get("cancel_requested"))
                or any(str(item.get("status") or "") == "cancelled" for item in outcome.post_action_results)
            )
            final_state, summary = _action_run_terminal_outcome(
                action_execution=outcome.action_execution,
                monitor_result=outcome.monitor_result,
                post_action_results=outcome.post_action_results,
                cancelled=cancelled,
                total_steps=_action_run_total_steps(draft),
                terminal_evidence_required=(
                    isinstance(draft, FlightActionDraft)
                    or (isinstance(draft, RegistryActionDraft) and draft.monitor_requested)
                ),
            )
            if final_state == "failed" and outcome.rejection_detail:
                summary = outcome.rejection_detail
            completed_step = (
                _action_run_total_steps(draft)
                if final_state == "succeeded"
                else (await action_run_require_async(run_id)).current_step
            )
            await append_run_event(
                event_type=f"run_{final_state}",
                payload={
                    "stage": "action",
                    "state": final_state,
                    "label": summary,
                    "sequence_id": run_id,
                    "step_count": _action_run_total_steps(draft),
                },
                state=final_state,
                current_step=completed_step,
                summary=summary,
                result=result_payload,
            )
            submitted_context = {
                "action_run_id": run_id,
                "action_type": "flight_command" if isinstance(draft, FlightActionDraft) else "registry_action",
                "draft_id": draft.draft_id,
                "tool_id": _action_draft_tool_id(draft),
                "target_drone_ids": list(draft.target_drone_ids) if isinstance(draft, FlightActionDraft) else [],
                "mission_name": draft.mission_name if isinstance(draft, FlightActionDraft) else "",
                "mission_type": draft.mission_type if isinstance(draft, FlightActionDraft) else None,
                "post_actions": [dict(item) for item in draft.post_actions],
                "action_label": draft.action_label if isinstance(draft, RegistryActionDraft) else "",
                "inferred_target_drone_ids": _submitted_registry_target_ids(
                    draft,
                    response_payload=action_response,
                    monitor_result=outcome.monitor_result,
                )
                if isinstance(draft, RegistryActionDraft)
                else [],
                "state": final_state,
                "result": result_payload,
            }
            try:
                sessions.update_private_context(
                    session_id,
                    {
                        "last_action_run_id": run_id,
                        "last_submitted_action": json.dumps(
                            submitted_context,
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        ),
                    },
                )
            except (AgentRuntimeError, KeyError):
                pass
            audit.record(
                "action_run_completed",
                session_id=session_id,
                actor=actor,
                tool_id=_action_draft_tool_id(draft),
                decision=final_state,
                payload={"run_id": run_id, "draft_id": draft.draft_id, "plan_hash": run_snapshot.plan_hash},
                metadata={"state": final_state, "summary": summary},
            )
        except Exception as exc:
            logger.exception(
                "Simurgh action-run coordinator failed run_id=%s draft_id=%s",
                run_id,
                draft.draft_id,
            )
            summary = f"Action-run coordinator failed closed: {str(exc)[:500]}"
            try:
                await append_run_event(
                    event_type="run_failed",
                    payload={"stage": "action", "state": "failed", "label": summary},
                    state="failed",
                    summary=summary,
                    result={"action_execution": "coordinator_failed"},
                )
            except Exception:
                pass

    async def _pre_action_read_only_context(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        routing_message: str,
        read_only_plan: Any,
        conversation_topic: str,
        action_draft: ActionDraft | None = None,
        explicit_read_requested: bool = False,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> tuple[str, dict[str, Any], tuple[str, ...]]:
        if (
            action_draft is not None
            and action_draft.preconditions
            and not explicit_read_requested
        ):
            # A source-grounded typed condition is evaluated again at
            # confirmation. Repeating a broad status scan here adds noise and
            # can contradict the exact target-scoped fact.
            return "", {}, ()
        sitl_lifecycle_context = (
            not explicit_read_requested
            and _should_prepend_sitl_lifecycle_read_only_context(
                routing_message,
                action_draft,
            )
        )
        if (
            not explicit_read_requested
            and not sitl_lifecycle_context
            and not _should_prepend_action_read_only_context(
                routing_message,
                read_only_plan,
            )
        ):
            return "", {}, ()

        allowed_tools = list_policy_allowed_read_only_tools(channel="agent")
        direct_tool_ids = (
            ("mds.sitl.instances.read", "mds.sitl.policy.read")
            if sitl_lifecycle_context
            else tuple(
                str(item)
                for item in getattr(read_only_plan, "tool_ids", ()) or ()
            )[:8]
        )
        direct_label = "read-only current state"
        if "mds.config.fleet.read" in direct_tool_ids and "mds.sitl.instances.read" in direct_tool_ids:
            direct_label = "configured fleet and SITL runtime state"
        elif "mds.sitl.instances.read" in direct_tool_ids:
            direct_label = "SITL runtime state"
        elif "mds.config.fleet.read" in direct_tool_ids:
            direct_label = "configured fleet"
        registry_plan = build_registry_read_plan_from_tool_ids(
            direct_tool_ids,
            allowed_tools=allowed_tools,
            label=direct_label,
            domain=str(
                getattr(read_only_plan, "query_domain", "")
                or getattr(read_only_plan, "topic", "")
                or "runtime"
            ),
            selection_source="turn_read_only_plan",
            limit=8,
        )
        if registry_plan is None:
            registry_plan = plan_registry_read_tool_calls(
                routing_message,
                allowed_tools=allowed_tools,
                conversation_topic=conversation_topic,
                local_intent=getattr(read_only_plan, "intent", None),
            )
        if registry_plan is not None:
            policy = load_default_policy()
            registry = load_default_tool_registry()
            try:
                registry_label = registry.path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                registry_label = registry.path.as_posix()

            results: list[RegistryReadToolResult] = []
            await _emit_assistant_progress(progress_callback, _registry_plan_progress_payload(registry_plan))
            for call in registry_plan.tool_calls:
                await _emit_assistant_progress(
                    progress_callback,
                    _registry_tool_call_progress_payload(call, state="running"),
                )
                result = await execute_policy_allowed_read_only_tool(
                    http_request,
                    name=call.tool.id,
                    arguments=dict(call.arguments),
                    channel="agent",
                    registry=registry,
                    policy=policy,
                )
                await _emit_assistant_progress(
                    progress_callback,
                    _registry_tool_call_progress_payload(call, state="complete", result=result),
                )
                results.append(RegistryReadToolResult(tool=call.tool, arguments=dict(call.arguments), result=result))

            evidence_bundle = build_registry_read_evidence_bundle(registry_plan, results, registry_path=registry_label)
            return (
                format_registry_read_results(registry_plan, results, registry_path=registry_label),
                evidence_bundle.public_metadata(),
                tuple(item.tool.id for item in results),
            )

        request_deps = _request_scoped_deps(deps, http_request)
        answer = await asyncio.to_thread(
            answer_mds_read_only_question,
            routing_message,
            deps=request_deps,
            conversation_topic=conversation_topic,
            actor_role=_auth_tool_role(http_request),
        )
        if answer is None:
            return "", {}, ()
        evidence = answer.evidence_metadata() or {
            "summary": f"Read-only {answer.intent.replace('_', ' ')} check before action draft.",
            "tool_ids": list(answer.tool_ids),
        }
        return answer.content, evidence, answer.tool_ids

    async def _create_action_record(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        draft: ActionDraft | None = None,
        confirmed: bool = False,
        pre_action_read_only_content: str = "",
        pre_action_read_only_evidence: Mapping[str, Any] | None = None,
        pre_action_read_only_tool_ids: tuple[str, ...] = (),
        turn_intent_metadata: Mapping[str, Any] | None = None,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> AssistantTurnRecord:
        policy = load_default_policy()
        if not policy.agent_enabled:
            raise PermissionError("Simurgh agent runtime is disabled")
        session = _require_or_create_assistant_session(policy=policy, actor=actor, turn_request=turn_request)
        assistant_config = load_default_assistant_config()
        context_documents = AssistantContextAssembler(config=assistant_config).assemble(
            _bounded_context_resource_ids(turn_request.context_resource_ids)
        )
        registry = load_default_tool_registry()

        if draft is None:
            draft = build_flight_action_draft(
                turn_request.message,
                draft_id=f"act-{uuid.uuid4().hex[:8]}",
                previous_action=_stored_last_submitted_action(session.id, actor=actor),
            )
        if draft is None:
            draft = build_sitl_reconcile_action_draft(
                turn_request.message,
                draft_id=f"act-{uuid.uuid4().hex[:8]}",
                conversation_topic=_session_conversation_topic(session),
            )
        if draft is None:
            raise AgentRuntimeError("Simurgh could not build a guarded action draft")

        if not confirmed:
            draft = with_approval_window(draft, policy.approval_ttl_seconds)
        approval_status, approval_detail = approval_window_status(draft)

        tool = registry.require(_action_draft_tool_id(draft))
        action_intent = _action_draft_intent(draft)
        action_domain = "flight" if isinstance(draft, FlightActionDraft) else "sitl"

        await _emit_assistant_progress(
            progress_callback,
            _action_progress_payload(
                stage="plan",
                state="complete",
                label=f"Drafted guarded {_action_draft_label(draft)} action",
                draft=draft,
            ),
        )

        action_response: Any | None = None
        monitor_result: Mapping[str, Any] | None = None
        post_action_results: tuple[Mapping[str, Any], ...] = ()
        rejection_detail = ""
        action_execution = "awaiting_confirmation"
        action_run_snapshot: ActionRunSnapshot | None = None
        action_run_should_start = False
        action_run_created = False
        approved = confirmed or (not policy.always_confirm_before_action)
        actor_role = _auth_tool_role(http_request)
        decision = policy.evaluate_tool(
            tool,
            channel="agent",
            approved=approved,
            actor_role=actor_role,
        )
        policy_reasons = tuple(decision.reasons)
        sequence_validation_error = (
            _post_action_sequence_validation_error(draft.post_actions)
            if isinstance(draft, FlightActionDraft)
            else ""
        )
        precondition_evaluation = ActionPreconditionEvaluation.not_required()
        if draft.ready and not sequence_validation_error and draft.preconditions:
            await _emit_assistant_progress(
                progress_callback,
                _action_progress_payload(
                    stage="condition",
                    state="running",
                    label="Checking action conditions",
                    draft=draft,
                ),
            )
            precondition_evaluation = await _evaluate_draft_preconditions(
                http_request,
                draft=draft,
                registry=registry,
                policy=policy,
            )
            await _emit_assistant_progress(
                progress_callback,
                _action_progress_payload(
                    stage="condition",
                    state=(
                        "complete"
                        if precondition_evaluation.status == "met"
                        else "skipped"
                        if precondition_evaluation.status == "not_met"
                        else "blocked"
                    ),
                    label={
                        "met": "Action conditions met",
                        "not_met": "Action not needed",
                        "unavailable": "Action condition unavailable",
                    }.get(precondition_evaluation.status, "Action condition checked"),
                    draft=draft,
                ),
            )
        if confirmed and approval_status != "valid":
            action_execution = "approval_expired"
            rejection_detail = approval_detail
        elif not draft.ready:
            action_execution = "missing_arguments"
        elif sequence_validation_error:
            action_execution = "validation_rejected"
            rejection_detail = sequence_validation_error
        elif precondition_evaluation.status == "not_met":
            action_execution = "precondition_not_met"
        elif precondition_evaluation.status == "unavailable":
            action_execution = "precondition_unavailable"
        elif decision.status is PolicyDecisionStatus.REQUIRE_APPROVAL:
            action_execution = "awaiting_confirmation"
        elif decision.status is PolicyDecisionStatus.DENY:
            if any("circuit breaker" in reason for reason in decision.reasons):
                action_execution = "blocked_by_circuit_breaker"
            else:
                action_execution = "policy_denied"
        else:
            await _emit_assistant_progress(
                progress_callback,
                _action_progress_payload(
                    stage="action",
                    state="running",
                    label="Starting approved action run",
                    draft=draft,
                    policy_status=decision.status.value,
                ),
            )
            plan_payload = draft.public_payload()
            plan_payload["display_plan"] = _action_draft_display_plan(draft)
            plan_hash = stable_payload_hash(plan_payload)
            resource_keys = _action_draft_resource_keys(draft, registry=registry)
            try:
                action_run_snapshot, action_run_created = await action_run_store_call(
                    action_runs.create_or_get,
                    actor=actor,
                    session_id=session.id,
                    draft_id=draft.draft_id,
                    plan_hash=plan_hash,
                    plan=plan_payload,
                    total_steps=_action_run_total_steps(draft),
                    resource_keys=resource_keys,
                    runner_owner_id=action_runner_id,
                    runner_lease_seconds=action_runner_lease_seconds,
                )
            except ActionRunResourceConflict as exc:
                action_execution = "resource_conflict"
                rejection_detail = (
                    "Active action run(s) already hold: "
                    + ", ".join(
                        f"{resource} ({run_id})"
                        for resource, run_id in exc.conflicts.items()
                    )
                )
            else:
                action_execution = "submitted"
                action_response = {
                    "action_run_id": action_run_snapshot.run_id,
                    "status": action_run_snapshot.state,
                    "summary": action_run_snapshot.summary or "Approved action run queued.",
                }
                if action_run_created:
                    action_run_should_start = True

        submitted_progress_state, submitted_progress_label = _submitted_action_progress_outcome(
            draft,
            monitor_result=monitor_result,
            post_action_results=post_action_results,
        )
        completion_progress_state = {
            "precondition_not_met": "skipped",
            "precondition_unavailable": "blocked",
        }.get(action_execution, "complete")
        await _emit_assistant_progress(
            progress_callback,
            _action_progress_payload(
                stage="safety" if action_execution != "submitted" else "action",
                state=(
                    submitted_progress_state
                    if action_execution == "submitted"
                    else completion_progress_state
                ),
                label={
                    "missing_arguments": "Action draft needs more details",
                    "awaiting_confirmation": "Waiting for operator confirmation",
                    "precondition_not_met": "Action not needed",
                    "precondition_unavailable": "Action condition unavailable",
                    "blocked_by_circuit_breaker": "Circuit breaker stopped final execution",
                    "policy_denied": "Policy denied action execution",
                    "validation_rejected": "GCS rejected action before dispatch",
                    "resource_conflict": "Target is busy with another action",
                    "submitted": submitted_progress_label,
                }.get(action_execution, "Action gate complete"),
                draft=draft,
                policy_status=decision.status.value,
            ),
        )

        content = _action_turn_content(
            draft=draft,
            action_execution=action_execution,
            pre_action_read_only_content=pre_action_read_only_content,
            policy_reasons=policy_reasons,
            command_response=action_response,
            monitor_result=monitor_result,
            post_action_results=post_action_results,
            rejection_detail=rejection_detail,
            precondition_evaluation=precondition_evaluation,
            circuit_breaker_enabled=policy.action_circuit_breaker_enabled,
            always_confirm_before_action=policy.always_confirm_before_action,
        )
        turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=ACTION_MODEL,
            adapter_version=ACTION_ADAPTER_VERSION,
            content=content,
            context_documents=tuple(context_documents),
            blocked_intents=(),
            safety_notes=(
                "Actions are drafted as typed GCS payloads through curated Simurgh registry tools.",
                "Human confirmation and the final circuit breaker are evaluated before any route can execute.",
            ),
        )
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": action_domain,
                "last_intent": action_intent,
                "last_response_mode": "status",
            },
        )
        draft_context = draft.to_context_json() if action_execution == "awaiting_confirmation" else ""
        submitted_context = ""
        if action_execution == "submitted":
            response_payload = (
                action_response.model_dump(mode="json")
                if hasattr(action_response, "model_dump")
                else dict(action_response or {})
            )
            if isinstance(draft, FlightActionDraft):
                monitor_summary = {}
                if isinstance(monitor_result, Mapping):
                    monitor_summary = {
                        "status": monitor_result.get("status"),
                        "success": monitor_result.get("success"),
                        "timed_out": monitor_result.get("timed_out"),
                        "completion_verification": dict(monitor_result.get("completion_verification") or {}),
                    }
                submitted_context = json.dumps(
                    {
                        "action_type": "flight_command",
                        "action_run_id": response_payload.get("action_run_id"),
                        "draft_id": draft.draft_id,
                        "tool_id": ACTION_TOOL_ID,
                        "mission_name": draft.mission_name,
                        "mission_type": draft.mission_type,
                        "target_drone_ids": list(draft.target_drone_ids),
                        "command_id": response_payload.get("command_id"),
                        "monitor_requested": draft.monitor_requested,
                        "monitor_result": monitor_summary,
                        "post_actions": [dict(item) for item in draft.post_actions],
                        "post_action_results": [dict(item) for item in post_action_results],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            elif isinstance(draft, RegistryActionDraft):
                monitor_summary = {}
                if isinstance(monitor_result, Mapping):
                    monitor_summary = {
                        "status": monitor_result.get("status"),
                        "summary": monitor_result.get("summary") or monitor_result.get("message"),
                    }
                inferred_target_ids = _submitted_registry_target_ids(
                    draft,
                    response_payload=response_payload,
                    monitor_result=monitor_result,
                )
                submitted_context = json.dumps(
                    {
                        "action_type": "registry_action",
                        "action_run_id": response_payload.get("action_run_id"),
                        "draft_id": draft.draft_id,
                        "tool_id": draft.tool_id,
                        "action_label": draft.action_label,
                        "arguments": dict(draft.arguments),
                        "operation_id": response_payload.get("operation_id") or response_payload.get("id"),
                        "monitor_requested": draft.monitor_requested,
                        "monitor_result": monitor_summary,
                        "inferred_target_drone_ids": inferred_target_ids,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
        private_context_update = {
            "last_assistant_content": turn.content,
            "last_assistant_provider": turn.provider,
            "last_assistant_model": turn.model,
            "last_domain": action_domain,
            "last_intent": action_intent,
            "last_response_mode": "status",
            "last_user_message": turn_request.message,
            "last_routing_message": normalize_operator_query_text(turn_request.message),
            "last_tool_intent": action_intent,
            "last_action_draft": draft_context,
            "last_action_draft_id": draft.draft_id if draft_context else "",
            "last_action_draft_hash": stable_payload_hash(draft.public_payload()) if draft_context else "",
            "last_read_only_evidence": json.dumps(
                dict(pre_action_read_only_evidence or {}),
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            if pre_action_read_only_evidence
            else "",
        }
        if action_execution == "awaiting_confirmation":
            private_context_update["last_action_request_message"] = turn_request.message
        if submitted_context:
            private_context_update["last_submitted_action"] = submitted_context
        if action_run_snapshot is not None:
            private_context_update["last_action_run_id"] = action_run_snapshot.run_id
        sessions.update_private_context(session.id, private_context_update)
        event = audit.record(
            "assistant_turn_created",
            session_id=session.id,
            actor=actor,
            tool_id=tool.id,
            decision=decision.status.value,
            payload={
                "message": turn_request.message.strip(),
                "context_resource_ids": [doc.id for doc in context_documents],
                "metadata": dict(turn_request.metadata or {}),
                "action_draft": draft.public_payload(),
            },
            metadata={
                "provider": turn.provider,
                "model": turn.model,
                "adapter_version": turn.adapter_version,
                "mode": session.mode,
                "context_count": len(context_documents),
                "blocked_intent_count": 0,
                "tool_intent": action_intent,
                "tool_id": tool.id,
                "tool_ids": [tool.id],
                "pre_action_read_only_tool_ids": list(pre_action_read_only_tool_ids),
                "pre_action_read_only_evidence": dict(pre_action_read_only_evidence or {}),
                "response_mode": "status",
                "query_domain": action_domain,
                "query_confidence": 1.0,
                "query_unclear": False,
                "query_reason": "guarded_action_draft",
                "turn_intent": dict(turn_intent_metadata or {}),
                "retrieved_context_count": 0,
                "web_search_enabled": False,
                "action_execution": action_execution,
                "action_draft": draft.public_payload(),
                "action_monitor": dict(monitor_result or {}),
                "post_action_results": [dict(item) for item in post_action_results],
                "action_preconditions": precondition_evaluation.public_payload(),
                "action_run": action_run_snapshot.public_payload() if action_run_snapshot is not None else {},
                "policy_decision": decision.status.value,
                "policy_reasons": list(policy_reasons),
                "circuit_breaker_layer": (
                    "final-action layer; command was stopped after planning/approval"
                    if action_execution == "blocked_by_circuit_breaker"
                    else "final-action layer; command path not reached"
                    if action_execution
                    in {
                        "awaiting_confirmation",
                        "missing_arguments",
                        "policy_denied",
                        "precondition_not_met",
                        "precondition_unavailable",
                    }
                    else "final-action layer; circuit breaker was off and canonical GCS command validation handled execution"
                ),
            },
        )
        if action_run_should_start and action_run_snapshot is not None:
            ownership = action_run_snapshot.ownership
            if ownership is None:
                raise AgentRuntimeError("approved action run has no durable runner ownership")
            execution_context = InternalToolExecutionContext.from_request(http_request)
            action_request_deps = _request_scoped_deps(deps, http_request)
            retain_action_run_task(
                asyncio.create_task(
                    _run_action_run(
                        execution_context,
                        run_id=action_run_snapshot.run_id,
                        ownership=ownership,
                        actor=actor,
                        actor_role=actor_role,
                        session_id=session.id,
                        draft=draft,
                        request_deps=action_request_deps,
                    ),
                    name=f"simurgh-action-run:{action_run_snapshot.run_id}",
                )
            )
        return AssistantTurnRecord(session=session, turn=turn, audit_event=event)

    async def _create_registry_read_execution_record(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        plan,
        allow_provider_composition: bool = False,
        turn_intent_metadata: Mapping[str, Any] | None = None,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> AssistantTurnRecord:
        policy = load_default_policy()
        if not policy.agent_enabled:
            raise PermissionError("Simurgh agent runtime is disabled")
        if turn_request.session_id:
            session = sessions.require(turn_request.session_id)
            if session.closed:
                raise AgentRuntimeError("assistant session is closed")
            if session.actor != actor:
                raise PermissionError("assistant session belongs to a different actor")
        else:
            session_mode = turn_request.mode or policy.mode
            if session_mode not in policy.runtime_modes:
                raise AgentRuntimeError(f"unknown Simurgh mode: {session_mode}")
            session = sessions.create(
                actor=actor,
                mode=session_mode,
                metadata=_bounded_metadata(turn_request.metadata),
            )

        assistant_config = load_default_assistant_config()
        language_profile = detect_language_profile(turn_request.message.strip())
        query_adaptation = adapt_operator_query(
            turn_request.message.strip(),
            language_profile=language_profile,
            conversation_topic=_session_conversation_topic(session),
        )
        context_documents = AssistantContextAssembler(config=assistant_config).assemble(
            _bounded_context_resource_ids(turn_request.context_resource_ids)
        )
        registry = load_default_tool_registry()
        try:
            registry_label = registry.path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            registry_label = registry.path.as_posix()

        results: list[RegistryReadToolResult] = []
        await _emit_assistant_progress(progress_callback, _registry_plan_progress_payload(plan))
        for call in plan.tool_calls:
            await _emit_assistant_progress(
                progress_callback,
                _registry_tool_call_progress_payload(call, state="running"),
            )
            result = await execute_policy_allowed_read_only_tool(
                http_request,
                name=call.tool.id,
                arguments=dict(call.arguments),
                channel="agent",
                registry=registry,
                policy=policy,
            )
            await _emit_assistant_progress(
                progress_callback,
                _registry_tool_call_progress_payload(call, state="complete", result=result),
            )
            results.append(RegistryReadToolResult(tool=call.tool, arguments=dict(call.arguments), result=result))

        evidence_bundle = build_registry_read_evidence_bundle(plan, results, registry_path=registry_label)
        read_only_evidence = evidence_bundle.public_metadata()
        content = format_registry_read_results(plan, results, registry_path=registry_label)
        tool_ids = [item.tool.id for item in results]
        resolved_turn_intent_metadata = _turn_intent_metadata_with_read_execution(
            turn_intent_metadata,
            tool_ids,
        )
        local_registry_turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=READ_TOOL_MODEL,
            adapter_version=READ_TOOL_ADAPTER_VERSION,
            content=content,
            context_documents=tuple(context_documents),
            blocked_intents=(),
            safety_notes=(
                "Policy-allowed read-only Simurgh registry tools were executed through the internal MCP-compatible adapter.",
                "No direct drone API, command, config write, upload, or mission mutation was exposed.",
            ),
        )
        turn = local_registry_turn
        retrieved_context_count = 0
        provider_composed_from_tool = False
        provider_composition_error = ""
        if allow_provider_composition:
            await _emit_assistant_progress(
                progress_callback,
                {"stage": "provider", "state": "running", "label": "Composing answer with provider evidence context"},
            )
            composition = await run_blocking_provider_call(
                compose_read_only_tool_turn_with_provider,
                config=assistant_config,
                operator_message=turn_request.message.strip(),
                base_turn=local_registry_turn,
                context_documents=tuple(context_documents),
                tool_intent=REGISTRY_READ_EXECUTION_INTENT,
                tool_ids=tool_ids,
                response_mode="status",
                evidence_metadata=read_only_evidence,
                language_profile=language_profile,
                first_safety_note=(
                    "Policy-allowed read-only Simurgh registry tools were executed before provider composition."
                ),
            )
            turn = composition.turn
            context_documents = composition.context_documents
            retrieved_context_count = composition.retrieved_context_count_delta
            provider_composed_from_tool = composition.provider_composed_from_tool
            provider_composition_error = composition.provider_composition_error
            await _emit_assistant_progress(
                progress_callback,
                {
                    "stage": "provider",
                    "state": "complete" if provider_composed_from_tool else "fallback",
                    "label": "Provider composition ready" if provider_composed_from_tool else "Using deterministic evidence answer",
                },
            )
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": plan.domain,
                "last_intent": REGISTRY_READ_EXECUTION_INTENT,
                "last_response_mode": "status",
            },
        )
        sessions.update_private_context(
            session.id,
            {
                "last_assistant_content": turn.content,
                "last_assistant_provider": turn.provider,
                "last_assistant_model": turn.model,
                "last_domain": plan.domain,
                "last_intent": REGISTRY_READ_EXECUTION_INTENT,
                "last_response_mode": "status",
                "last_user_message": turn_request.message,
                "last_routing_message": normalize_operator_query_text(turn_request.message),
                "last_tool_intent": REGISTRY_READ_EXECUTION_INTENT,
                "last_read_only_evidence": json.dumps(
                    read_only_evidence,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
            },
        )
        event = audit.record(
            "assistant_turn_created",
            session_id=session.id,
            actor=actor,
            tool_id=tool_ids[0] if tool_ids else None,
            decision=PolicyDecisionStatus.ALLOW.value,
            payload={
                "message": turn_request.message.strip(),
                "context_resource_ids": [doc.id for doc in context_documents],
                "metadata": dict(turn_request.metadata or {}),
            },
            metadata={
                "provider": turn.provider,
                "model": turn.model,
                "adapter_version": turn.adapter_version,
                "mode": session.mode,
                "context_count": len(context_documents),
                "blocked_intent_count": 0,
                "tool_intent": REGISTRY_READ_EXECUTION_INTENT,
                "tool_id": tool_ids[0] if tool_ids else None,
                "tool_ids": tool_ids,
                "response_mode": "status",
                "query_domain": plan.domain,
                "query_confidence": 1.0,
                "query_unclear": False,
                "query_reason": "registry_read_tool_plan",
                "turn_intent": resolved_turn_intent_metadata,
                "read_only_plan": plan.public_metadata(),
                "read_only_evidence": read_only_evidence,
                "retrieved_context_count": retrieved_context_count,
                "web_search_enabled": False,
                "provider_composed_from_tool": provider_composed_from_tool,
                "provider_composition_error": provider_composition_error,
                "query_adaptation": query_adaptation.public_metadata(),
                "routing_strategy": query_adaptation.strategy,
                "routing_language": query_adaptation.routing_language,
                "routing_rule_count": len(query_adaptation.applied_rules),
                "language_profile": language_profile.public_metadata(),
                "input_language": language_profile.language,
                "input_script": language_profile.script,
                "input_tone": language_profile.tone,
                "localization_strategy": language_profile.localization_strategy,
            },
        )
        return AssistantTurnRecord(session=session, turn=turn, audit_event=event)

    async def _create_local_read_only_answer_record(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        routing_message: str,
        read_only_plan,
        read_intent_overrides: tuple[str, ...] = (),
        read_target_drone_ids: tuple[str, ...] = (),
        read_options: Mapping[str, Mapping[str, object]] | None = None,
        response_detail: str = "standard",
        turn_intent_metadata: Mapping[str, Any] | None = None,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> AssistantTurnRecord | None:
        policy = load_default_policy()
        if not policy.agent_enabled:
            raise PermissionError("Simurgh agent runtime is disabled")
        session = _require_or_create_assistant_session(policy=policy, actor=actor, turn_request=turn_request)
        request_deps = _request_scoped_deps(deps, http_request)
        conversation_topic = _session_conversation_topic(session)
        selected_intents = tuple(
            dict.fromkeys(
                str(intent).strip()
                for intent in read_intent_overrides
                if str(intent).strip()
            )
        )
        has_previous_action_intent = "previous_action_summary" in selected_intents
        local_intents = tuple(
            intent
            for intent in selected_intents
            if intent != "previous_action_summary" and provider_read_intent_tool_ids(intent) is not None
        )
        subsumed_intents = frozenset(
            subsumed
            for intent in local_intents
            for subsumed in LOCAL_READ_INTENT_SUBSUMPTIONS.get(intent, ())
        )
        local_intents = tuple(intent for intent in local_intents if intent not in subsumed_intents)
        include_previous_action_summary = has_previous_action_intent and (
            not local_intents or _looks_like_previous_action_result_question(turn_request.message)
        )
        include_previous_action_context = has_previous_action_intent
        if not local_intents and not include_previous_action_summary:
            local_intents = (str(read_only_plan.intent or "").strip(),)

        evidence_message = turn_request.message if selected_intents else routing_message
        previous_action_payload: dict[str, Any] = {}
        previous_action_context: dict[str, str] = {}
        previous_action_targets: tuple[str, ...] = tuple(
            dict.fromkeys(str(item).strip() for item in read_target_drone_ids if str(item).strip())
        )
        if include_previous_action_context:
            previous_action_payload, previous_action_context = _last_submitted_action_context(session.id)
            previous_action_payload.update(
                _stored_last_submitted_action(session.id, actor=actor)
            )
            if not previous_action_targets:
                previous_action_targets = tuple(_action_context_target_ids(previous_action_payload))

        answers = []
        for intent in local_intents:
            if not intent:
                continue
            answer = await asyncio.to_thread(
                answer_mds_read_only_question,
                evidence_message,
                deps=request_deps,
                conversation_topic=conversation_topic,
                intent_override=intent,
                target_drone_ids=previous_action_targets,
                action_context=previous_action_payload if include_previous_action_context else None,
                response_detail=response_detail,
                read_options=read_options,
                actor_role=_auth_tool_role(http_request),
            )
            if answer is not None:
                answers.append(answer)
        if not answers and not include_previous_action_summary:
            return None

        tool_ids = list(
            dict.fromkeys(
                tool_id
                for answer in answers
                for tool_id in answer.tool_ids
            )
        )
        if include_previous_action_summary:
            tool_ids.insert(0, PREVIOUS_ACTION_EVIDENCE_TOOL_ID)
            tool_ids = list(dict.fromkeys(tool_ids))
        answer_intent = answers[0].intent if len(answers) == 1 and not include_previous_action_summary else "composite_read"
        response_mode = answers[0].response_mode if len(answers) == 1 else "status"
        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "tool",
                "state": "complete",
                "label": "Evidence ready",
                "intent": answer_intent,
                "tool_id": tool_ids[0] if tool_ids else None,
                "tool_ids": tool_ids,
            },
        )

        assistant_config = load_default_assistant_config()
        context_documents = AssistantContextAssembler(config=assistant_config).assemble(
            _bounded_context_resource_ids(turn_request.context_resource_ids)
        )
        language_profile = detect_language_profile(turn_request.message.strip())
        query_adaptation = adapt_operator_query(
            turn_request.message.strip(),
            language_profile=language_profile,
            conversation_topic=conversation_topic,
        )
        sections: list[tuple[str, str]] = []
        if include_previous_action_summary and previous_action_payload:
            action_summary = _previous_action_summary_content(
                turn_request.message,
                previous_action_payload,
                previous_action_context,
                response_detail=response_detail,
            )
            footer = "\n\nNo new action was executed."
            if action_summary.endswith(footer):
                action_summary = action_summary[: -len(footer)]
            sections.append(("Previous action", action_summary))
        sections.extend(
            (answer.intent.replace("_", " ").title(), answer.content)
            for answer in answers
        )
        if len(sections) == 1 and not include_previous_action_summary:
            answer_content = sections[0][1]
        else:
            answer_content = "\n\n".join(f"{title}\n\n{content}" for title, content in sections)
        safety_notes = tuple(
            dict.fromkeys(
                note
                for answer in answers
                for note in answer.safety_notes
            )
        ) or (
            "Answered from private Simurgh session context and local read-only MDS evidence.",
            "No GCS command, SITL operation, or mutation was executed.",
        )
        evidence_bundle = ReadOnlyEvidenceBundle.from_answer(
            intent=answer_intent,
            response_mode=response_mode,
            tool_ids=tool_ids,
            content=answer_content,
            safety_notes=safety_notes,
        )
        evidence = evidence_bundle.public_metadata()
        turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=READ_TOOL_MODEL,
            adapter_version=READ_TOOL_ADAPTER_VERSION,
            content=answer_content,
            context_documents=tuple(context_documents),
            blocked_intents=(),
            safety_notes=safety_notes,
        )
        next_topic = str(read_only_plan.topic or read_only_plan.query_domain or answer_intent or "").strip()
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": next_topic,
                "last_intent": answer_intent,
                "last_response_mode": response_mode,
            },
        )
        sessions.update_private_context(
            session.id,
            {
                "last_assistant_content": turn.content,
                "last_assistant_provider": turn.provider,
                "last_assistant_model": turn.model,
                "last_domain": next_topic,
                "last_intent": answer_intent,
                "last_response_mode": response_mode,
                "last_user_message": turn_request.message,
                "last_routing_message": normalize_operator_query_text(turn_request.message),
                "last_tool_intent": answer_intent,
                "last_read_only_evidence": json.dumps(
                    evidence or {},
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
            },
        )
        event = audit.record(
            "assistant_turn_created",
            session_id=session.id,
            actor=actor,
            tool_id=tool_ids[0] if tool_ids else None,
            decision=PolicyDecisionStatus.ALLOW.value,
            payload={
                "message": turn_request.message.strip(),
                "context_resource_ids": [doc.id for doc in context_documents],
                "metadata": dict(turn_request.metadata or {}),
            },
            metadata={
                "provider": turn.provider,
                "model": turn.model,
                "adapter_version": turn.adapter_version,
                "mode": session.mode,
                "context_count": len(context_documents),
                "blocked_intent_count": 0,
                "tool_intent": answer_intent,
                "tool_id": tool_ids[0] if tool_ids else None,
                "tool_ids": tool_ids,
                "response_mode": response_mode,
                "query_domain": read_only_plan.query_domain,
                "query_confidence": read_only_plan.confidence,
                "query_unclear": read_only_plan.unclear,
                "query_reason": read_only_plan.reason,
                "turn_intent": dict(turn_intent_metadata or {}),
                "read_only_plan": read_only_plan.public_metadata(),
                "read_only_evidence": evidence or {},
                "retrieved_context_count": 0,
                "web_search_enabled": False,
                "query_adaptation": query_adaptation.public_metadata(),
                "routing_strategy": query_adaptation.strategy,
                "routing_language": query_adaptation.routing_language,
                "routing_rule_count": len(query_adaptation.applied_rules),
                "language_profile": language_profile.public_metadata(),
                "input_language": language_profile.language,
                "input_script": language_profile.script,
                "input_tone": language_profile.tone,
                "localization_strategy": language_profile.localization_strategy,
            },
        )
        return AssistantTurnRecord(session=session, turn=turn, audit_event=event)

    async def _create_assistant_turn_record_for_request_unlocked(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        progress_callback: AssistantProgressCallback | None = None,
    ):
        try:
            actor = _resolve_actor(http_request, turn_request.actor)
            structured_action_intent, structured_action_draft_id = _structured_action_control(
                turn_request
            )
            existing_session = None
            if turn_request.session_id:
                existing_session = sessions.require(turn_request.session_id)
                if existing_session.closed:
                    raise AgentRuntimeError("assistant session is closed")
                if existing_session.actor != actor:
                    raise PermissionError("assistant session belongs to a different actor")

            structured_amendment_draft: ActionDraft | None = None
            if structured_action_intent == "amend":
                current_draft = _stored_action_draft(turn_request.session_id)
                if (
                    current_draft is not None
                    and current_draft.draft_id.lower() == structured_action_draft_id.lower()
                    and approval_window_status(current_draft, now=utc_now())[0] == "valid"
                ):
                    structured_amendment_draft = current_draft
                else:
                    amendment_matches = _recent_pending_action_drafts_for_actor(
                        actor=actor,
                        draft_id=structured_action_draft_id,
                    )
                    if len(amendment_matches) == 1:
                        recovered_session, structured_amendment_draft = amendment_matches[0]
                        if existing_session is None or recovered_session.id != existing_session.id:
                            existing_session = recovered_session
                            turn_request = _turn_request_with_session(
                                turn_request,
                                session_id=recovered_session.id,
                            )

            assistant_config = load_default_assistant_config()
            conversation_topic = None
            previous_context: dict[str, str] = {}
            if existing_session is not None:
                conversation_topic = str(existing_session.metadata.get("last_domain") or "")
                previous_context = sessions.get_private_context(existing_session.id)
                if not conversation_topic:
                    conversation_topic = str(previous_context.get("last_domain") or "")
            previous_action = _stored_last_submitted_action(
                turn_request.session_id,
                actor=actor,
            )
            previous_action_request_message = _stored_last_action_request_message(turn_request.session_id)
            if structured_amendment_draft is not None:
                previous_action = {
                    **structured_amendment_draft.public_payload(),
                    "action_type": "pending_action_draft",
                    "action_label": _action_draft_label(structured_amendment_draft),
                    "amends_draft_id": structured_amendment_draft.draft_id,
                }
                previous_action_request_message = _action_draft_summary_block(
                    structured_amendment_draft
                )
            turn_intent = build_turn_intent_frame(
                turn_request.message,
                conversation_topic=conversation_topic,
                previous_action=previous_action,
                previous_action_request_message=previous_action_request_message,
            )
            if (
                isinstance(turn_intent.action.draft, RegistryActionDraft)
                and turn_intent.action.draft.tool_id == SITL_BATCH_ACTION_TOOL_ID
            ):
                previous_action_for_routing = _previous_action_with_single_listed_sitl_target(
                    http_request,
                    previous_action,
                )
            else:
                previous_action_for_routing = _previous_action_with_live_single_target(
                    http_request,
                    previous_action,
                )
            if previous_action_for_routing != previous_action:
                turn_intent = build_turn_intent_frame(
                    turn_request.message,
                    conversation_topic=conversation_topic,
                    previous_action=previous_action_for_routing,
                    previous_action_request_message=previous_action_request_message,
                )
            resolved_initial_draft = _action_draft_with_inferred_single_sitl_instance(
                http_request,
                turn_intent.action.draft,
            )
            if resolved_initial_draft is not turn_intent.action.draft:
                turn_intent = replace(
                    turn_intent,
                    action=replace(turn_intent.action, draft=resolved_initial_draft),
                )
            initial_typed_intent = turn_intent
            semantic_rewrite = None
            semantic_rewrite_error = ""
            semantic_action_plan_error = ""
            semantic_interpretation_failed = False
            semantic_read_intents: tuple[str, ...] = ()
            semantic_read_options: Mapping[str, Mapping[str, object]] = {}
            semantic_read_target_drone_ids: tuple[str, ...] = ()
            semantic_read_target_resolution: dict[str, list[str]] = {}
            semantic_read_plan_resolution: dict[str, Any] = {}
            grounded_read_registry_plan: RegistryReadPlan | None = None
            semantic_registry_plan_execution = ""
            semantic_previous_action_read = False
            semantic_conversation_transform = False
            semantic_confirmation_request = False
            semantic_rejection_request = False
            semantic_untrusted_control_request = False
            if structured_action_intent == "amend" and structured_amendment_draft is None:
                record = await _create_semantic_clarification_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    question=(
                        "I cannot find that pending plan in this operator session. "
                        "Please draft the action again."
                    ),
                    semantic_rewrite=None,
                    turn_intent_metadata={
                        "route": "semantic_clarification",
                        "amends_action_draft_id": structured_action_draft_id,
                    },
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(
                    record=record,
                    message=turn_request.message,
                )
                return record, history_record
            if structured_action_intent in {"confirm", "reject"}:
                # The UI control is already an explicit operator decision. Keep
                # the transcript for auditability, but do not ask a provider to
                # reinterpret the button click as a new natural-language turn.
                structured_is_confirmation = structured_action_intent == "confirm"
                turn_intent = replace(
                    turn_intent,
                    confirmation_message=structured_is_confirmation,
                    rejection_message=not structured_is_confirmation,
                    explicit_action_draft_id=structured_action_draft_id,
                    action=replace(
                        turn_intent.action,
                        draft=None,
                        direct_flight_request=False,
                        flight_followup_request=False,
                        sitl_lifecycle_request=False,
                        replayed_previous_request=False,
                    ),
                    route=(
                        "action_confirmation"
                        if structured_is_confirmation
                        else "action_rejection"
                    ),
                    reasons=("dashboard-structured-action-control",),
                )
                semantic_confirmation_request = structured_is_confirmation
                semantic_rejection_request = not structured_is_confirmation
            elif structured_action_intent == "amend":
                # Amendments are natural-language requests against one immutable
                # pending plan. The semantic layer must return a complete fresh
                # typed plan; the original draft remains unexecuted unless the
                # replacement is subsequently confirmed.
                turn_intent = replace(
                    turn_intent,
                    confirmation_message=False,
                    rejection_message=False,
                    explicit_action_draft_id="",
                    route="provider_or_registry",
                    reasons=("dashboard-structured-action-amendment",),
                )
            if _semantic_rewrite_is_safe_to_try(
                assistant_config=assistant_config,
                request=http_request,
                original_message=turn_request.message,
                turn_intent=turn_intent,
            ) and structured_action_intent not in {"confirm", "reject"}:
                try:
                    semantic_registry = load_default_tool_registry()
                    semantic_action_contracts = _provider_action_tool_contracts(semantic_registry)
                    semantic_action_contract_map = _provider_action_tool_contract_map(
                        semantic_action_contracts
                    )
                    semantic_fact_contract_map = assistant_fact_map(semantic_registry)
                    semantic_grounding_messages = _semantic_rewrite_grounding_messages(
                        previous_context
                    )
                    semantic_previous_action_summary = _semantic_rewrite_previous_action_summary(
                        previous_action_for_routing
                    )
                    if structured_amendment_draft is not None:
                        amendment_plan = _action_draft_summary_block(
                            structured_amendment_draft
                        )
                        semantic_grounding_messages = tuple(
                            dict.fromkeys(
                                (
                                    amendment_plan,
                                    *semantic_grounding_messages,
                                )
                            )
                        )[:4]
                        semantic_previous_action_summary = (
                            f"Pending reviewed draft {structured_amendment_draft.draft_id} "
                            f"to amend:\n{amendment_plan}"
                        )[:1200]
                    semantic_rewrite = await run_blocking_provider_call(
                        rewrite_operator_message_with_provider,
                        config=assistant_config,
                        message=turn_request.message,
                        conversation_topic=conversation_topic or "",
                        runtime_mode=resolve_runtime_mode().mode,
                        previous_action_summary=semantic_previous_action_summary,
                        clarification_context=_semantic_rewrite_clarification_context(previous_context),
                        grounding_messages=semantic_grounding_messages,
                        allowed_target_ids=_action_context_target_ids(previous_action_for_routing),
                        action_tool_contracts=semantic_action_contracts,
                        action_precondition_fact_contracts=assistant_fact_contracts(
                            semantic_registry
                        ),
                        read_intent_contracts=provider_read_intent_contracts(),
                    )
                    if semantic_rewrite is not None:
                        semantic_rewrite = _resolve_provider_plan_with_unique_runtime_context(
                            semantic_rewrite,
                            original_message=turn_request.message,
                            grounding_messages=semantic_grounding_messages,
                            previous_action=previous_action_for_routing,
                            tool_contracts=semantic_action_contract_map,
                            fact_contracts=semantic_fact_contract_map,
                        )
                except AgentRuntimeError as exc:
                    semantic_rewrite_error = str(exc)[:180]
                    # Local parsing can detect an action, but provider failure
                    # must not promote that parse into an executable draft.
                    language_profile = detect_language_profile(turn_request.message.strip())
                    semantic_interpretation_failed = bool(
                        (
                            turn_intent.is_action_route
                            and turn_intent.action.has_action_request
                            and turn_intent.action.draft is None
                        )
                        or (
                            turn_intent.route == "provider_or_registry"
                            and language_profile.script
                            in {"arabic", "cjk", "cyrillic", "mixed"}
                        )
                    )
                if semantic_rewrite is not None:
                    rewritten_intent = build_turn_intent_frame(
                        turn_request.message,
                        conversation_topic=conversation_topic,
                        previous_action=previous_action_for_routing,
                        previous_action_request_message=previous_action_request_message,
                        semantic_routing_message=semantic_rewrite.normalized_message,
                    )
                    semantic_untrusted_control_request = bool(
                        semantic_rewrite.route_hint
                        in {"confirm_pending_action", "reject_pending_action"}
                        and not semantic_rewrite.usable_for_routing
                    )
                    if semantic_untrusted_control_request:
                        semantic_action_plan_error = (
                            "provider_action_control_requires_source_grounding"
                        )
                    if (
                        semantic_rewrite.route_hint == "confirm_pending_action"
                        and semantic_rewrite.usable_for_routing
                    ):
                        # The authenticated operator's current message is the
                        # approval. The provider only interprets its exact,
                        # source-grounded control phrase; local actor/session
                        # binding and immutable draft lookup remain authoritative.
                        semantic_action_plan_error = (
                            "provider_confirmation_requires_local_resolution"
                        )
                        semantic_confirmation_request = True
                        turn_intent = replace(
                            rewritten_intent,
                            confirmation_message=True,
                            rejection_message=False,
                            explicit_action_draft_id=_extract_action_draft_id(
                                turn_request.message
                            ),
                            action=replace(
                                rewritten_intent.action,
                                draft=None,
                                direct_flight_request=False,
                                flight_followup_request=False,
                                sitl_lifecycle_request=False,
                                replayed_previous_request=False,
                            ),
                            route="action_confirmation",
                            confidence=max(0.62, float(semantic_rewrite.confidence)),
                            reasons=("provider-semantic-confirmation-request",),
                        )
                    elif (
                        semantic_rewrite.route_hint == "reject_pending_action"
                        and semantic_rewrite.usable_for_routing
                    ):
                        # A model may interpret multilingual/typo-heavy stop or
                        # reject language, but it never mutates state itself.
                        # The local session/run resolver below remains the sole
                        # authority for the actual draft rejection or run control.
                        semantic_action_plan_error = "provider_rejection_requires_local_resolution"
                        semantic_rejection_request = True
                        turn_intent = replace(
                            rewritten_intent,
                            confirmation_message=False,
                            rejection_message=True,
                            explicit_action_draft_id=_extract_action_draft_id(
                                turn_request.message
                            ),
                            action=replace(
                                rewritten_intent.action,
                                draft=None,
                                direct_flight_request=False,
                                flight_followup_request=False,
                                sitl_lifecycle_request=False,
                                replayed_previous_request=False,
                            ),
                            route="action_rejection",
                            confidence=max(0.62, float(semantic_rewrite.confidence)),
                            reasons=("provider-semantic-rejection-request",),
                        )
                    elif (
                        semantic_rewrite.route_hint == "transform_previous_answer"
                        and semantic_rewrite.usable_for_routing
                    ):
                        if not str(previous_context.get("last_assistant_content") or "").strip():
                            semantic_rewrite = replace(
                                semantic_rewrite,
                                needs_clarification=True,
                                clarification_reason="missing_runtime_context",
                                clarification_question=(
                                    "There is no previous answer in this conversation to transform. "
                                    "Which result should I rewrite?"
                                ),
                            )
                        else:
                            semantic_conversation_transform = True
                            turn_intent = replace(
                                rewritten_intent,
                                confirmation_message=False,
                                rejection_message=False,
                                explicit_action_draft_id="",
                                action=replace(
                                    rewritten_intent.action,
                                    draft=None,
                                    direct_flight_request=False,
                                    flight_followup_request=False,
                                    sitl_lifecycle_request=False,
                                    replayed_previous_request=False,
                                ),
                                route="provider_transform",
                                confidence=max(0.62, float(semantic_rewrite.confidence)),
                                reasons=("provider-semantic-conversation-transform",),
                            )
                    elif semantic_rewrite.route_hint == "read_status" and semantic_rewrite.usable_for_routing:
                        requested_read_intents = tuple(
                            dict.fromkeys(
                                str(intent).strip()
                                for intent in semantic_rewrite.read_intents
                                if str(intent).strip()
                            )
                        )
                        local_action_draft = turn_intent.action.draft
                        unknown_read_intents = tuple(
                            intent
                            for intent in requested_read_intents
                            if provider_read_intent_tool_ids(intent) is None
                        )
                        if local_action_draft is not None and local_action_draft.ready:
                            semantic_action_plan_error = "provider_read_status_conflicted_with_local_action"
                            semantic_rewrite = replace(
                                semantic_rewrite,
                                needs_clarification=True,
                                clarification_reason="semantic_ambiguity",
                                clarification_question=(
                                    "I can interpret this as either a status check or an action. "
                                    "Should I inspect the current state, or prepare the action for confirmation?"
                                ),
                            )
                        elif unknown_read_intents:
                            semantic_rewrite = replace(
                                semantic_rewrite,
                                needs_clarification=True,
                                clarification_reason="semantic_ambiguity",
                                clarification_question=(
                                    "I could not map every requested evidence source to the available controls. "
                                    "Which status or evidence should I check?"
                                ),
                            )
                        elif requested_read_intents:
                            request_deps = _request_scoped_deps(deps, http_request)
                            (
                                accepted_read_targets,
                                unknown_explicit_read_targets,
                                dropped_ungrounded_read_targets,
                            ) = _resolve_provider_read_targets(
                                request_deps=request_deps,
                                requested_targets=semantic_rewrite.read_target_drone_ids,
                                grounding_messages=(
                                    turn_request.message,
                                    *_semantic_rewrite_grounding_messages(previous_context),
                                ),
                                action_context=previous_action_for_routing,
                            )
                            semantic_read_target_resolution = {
                                "accepted": list(accepted_read_targets),
                                "unknown_explicit": list(unknown_explicit_read_targets),
                                "dropped_ungrounded": list(dropped_ungrounded_read_targets),
                            }
                            if unknown_explicit_read_targets:
                                targets = ", ".join(unknown_explicit_read_targets)
                                semantic_rewrite = replace(
                                    semantic_rewrite,
                                    needs_clarification=True,
                                    clarification_reason="missing_runtime_context",
                                    clarification_question=(
                                        f"I cannot find drone {targets} in the configured or live fleet. "
                                        "Which drone should I check?"
                                    ),
                                )
                            else:
                                semantic_read_intents = requested_read_intents
                                semantic_read_options = {
                                    str(intent): {
                                        str(name): bool(value)
                                        for name, value in options.items()
                                    }
                                    for intent, options in semantic_rewrite.read_options.items()
                                    if isinstance(options, Mapping)
                                }
                                semantic_read_target_drone_ids = accepted_read_targets
                                semantic_previous_action_read = "previous_action_summary" in requested_read_intents
                                local_read_intents = tuple(
                                    intent for intent in requested_read_intents if intent != "previous_action_summary"
                                )
                                primary_read_intent = (
                                    local_read_intents[0] if local_read_intents else "command_summary"
                                )
                                requested_tool_ids = tuple(
                                    dict.fromkeys(
                                        tool_id
                                        for intent in requested_read_intents
                                        for tool_id in (provider_read_intent_tool_ids(intent) or ())
                                    )
                                )
                                initial_read_plan = initial_typed_intent.read_only_plan
                                grounded_tool_ids = tuple(
                                    dict.fromkeys(
                                        str(tool_id).strip()
                                        for tool_id in initial_read_plan.tool_ids
                                        if str(tool_id).strip()
                                    )
                                )
                                missing_grounded_tool_ids = tuple(
                                    tool_id
                                    for tool_id in grounded_tool_ids
                                    if tool_id not in requested_tool_ids
                                )
                                reconciled_read_coverage = reconcile_registry_read_tool_ids(
                                    grounded_tool_ids,
                                    requested_tool_ids,
                                )
                                if (
                                    initial_typed_intent.route == "read_only"
                                    and not initial_read_plan.unclear
                                    and missing_grounded_tool_ids
                                    and not semantic_rewrite.read_target_drone_ids
                                ):
                                    grounded_read_registry_plan = build_registry_read_plan_from_tool_ids(
                                        reconciled_read_coverage.effective_tool_ids,
                                        allowed_tools=list_policy_allowed_read_only_tools(channel="agent"),
                                        label="requested current state",
                                        domain=str(
                                            initial_read_plan.query_domain
                                            or initial_read_plan.topic
                                            or "runtime"
                                        ),
                                        selection_source="grounded_local_read_plan",
                                        limit=8,
                                    )
                                    if grounded_read_registry_plan is not None:
                                        semantic_registry_plan_execution = "grounded_registry_plan"
                                if (
                                    grounded_read_registry_plan is None
                                    and registry_read_tool_ids_have_operator_summary(
                                        requested_tool_ids
                                    )
                                    and not semantic_rewrite.read_target_drone_ids
                                ):
                                    grounded_read_registry_plan = build_registry_read_plan_from_tool_ids(
                                        requested_tool_ids,
                                        allowed_tools=list_policy_allowed_read_only_tools(
                                            channel="agent"
                                        ),
                                        label="requested current state",
                                        domain=str(
                                            rewritten_intent.read_only_plan.query_domain
                                            or rewritten_intent.read_only_plan.topic
                                            or "runtime"
                                        ),
                                        selection_source="provider_structured_read",
                                        limit=8,
                                    )
                                    if grounded_read_registry_plan is not None:
                                        semantic_registry_plan_execution = "provider_registry_plan"
                                effective_tool_ids = (
                                    _registry_plan_tool_ids(grounded_read_registry_plan)
                                    if grounded_read_registry_plan is not None
                                    else reconciled_read_coverage.effective_tool_ids
                                )
                                semantic_read_plan_resolution = {
                                    "provider_tool_ids": list(requested_tool_ids),
                                    "grounded_tool_ids": list(
                                        reconciled_read_coverage.required_tool_ids
                                    ),
                                    "missing_grounded_tool_ids": list(missing_grounded_tool_ids),
                                    "provider_added_tool_ids": list(
                                        reconciled_read_coverage.provider_added_tool_ids
                                    ),
                                    "provider_dropped_tool_ids": list(
                                        reconciled_read_coverage.provider_dropped_tool_ids
                                    ),
                                    "effective_tool_ids": list(
                                        effective_tool_ids
                                    ),
                                    "execution": (
                                        semantic_registry_plan_execution
                                        or "provider_read_intents"
                                    ),
                                }
                                read_topic = infer_mds_read_topic(
                                    turn_request.message,
                                    intent=primary_read_intent,
                                ) or str(rewritten_intent.read_only_plan.topic or "")
                                typed_read_plan = replace(
                                    rewritten_intent.read_only_plan,
                                    intent=primary_read_intent,
                                    topic=read_topic or "general",
                                    query_domain=read_topic or rewritten_intent.read_only_plan.query_domain,
                                    confidence=max(0.62, float(semantic_rewrite.confidence)),
                                    unclear=False,
                                    reason="provider_semantic_read_intent",
                                    tool_ids=requested_tool_ids,
                                    missing_arguments=(),
                                    execution_layer=(
                                        "private_session_context"
                                        if semantic_previous_action_read and not local_read_intents
                                        else "local_advisory"
                                    ),
                                )
                                cleared_action = replace(
                                    rewritten_intent.action,
                                    draft=None,
                                    direct_flight_request=False,
                                    flight_followup_request=False,
                                    sitl_lifecycle_request=False,
                                    replayed_previous_request=False,
                                )
                                turn_intent = replace(
                                    rewritten_intent,
                                    read_only_plan=typed_read_plan,
                                    action=cleared_action,
                                    route="read_only",
                                    confidence=max(0.62, float(semantic_rewrite.confidence)),
                                    reasons=("provider-structured-read-intent",),
                                )
                        else:
                            semantic_rewrite = replace(
                                semantic_rewrite,
                                needs_clarification=True,
                                clarification_reason="semantic_ambiguity",
                                clarification_question="Which live status or evidence should I check?",
                            )
                    elif (
                        getattr(semantic_rewrite, "action_plan", None) is not None
                        and semantic_rewrite.usable_for_routing
                        and _is_authoritative_typed_read_only_intent(initial_typed_intent)
                    ):
                        # A complete local read route is authoritative for
                        # status/readiness questions.  Providers can
                        # over-read an action word such as "takeoff" and
                        # return an action plan for "is drone 1 ready to
                        # takeoff?".  Do not let that reinterpretation turn a
                        # harmless evidence request into a draft or a
                        # clarification; keep the local fleet read path.
                        semantic_action_plan_error = (
                            "provider_action_plan_conflicts_with_local_read_only"
                        )
                        semantic_rewrite = replace(
                            semantic_rewrite,
                            action_plan=None,
                            needs_clarification=False,
                            clarification_reason="none",
                            clarification_question="",
                        )
                    elif (
                        getattr(semantic_rewrite, "action_plan", None) is not None
                        and semantic_rewrite.usable_for_routing
                    ):
                        try:
                            validate_provider_action_plan_source_coverage(
                                semantic_rewrite.action_plan,
                                original_message=turn_request.message,
                                grounding_messages=semantic_grounding_messages,
                                allowed_target_ids=_action_context_target_ids(
                                    previous_action_for_routing
                                ),
                                tool_contracts=_provider_action_tool_contract_map(
                                    semantic_action_contracts
                                ),
                            )
                        except ValueError as exc:
                            semantic_action_plan_error = (
                                "provider_action_plan_incomplete_source_coverage:"
                                + str(exc)
                            )[:180]
                            semantic_rewrite = replace(
                                semantic_rewrite,
                                needs_clarification=True,
                                clarification_reason="semantic_ambiguity",
                                clarification_question=(
                                    "I may be missing part of the requested sequence. "
                                    "Should I keep every step in the same order?"
                                ),
                            )
                            materialized = None
                        else:
                            materialized = build_action_draft_from_provider_plan(
                                semantic_rewrite.action_plan,
                                draft_id=f"act-{uuid.uuid4().hex[:8]}",
                                previous_action=previous_action_for_routing,
                                tool_contracts=_provider_action_tool_contract_map(
                                    semantic_action_contracts
                                ),
                                fact_contracts=assistant_fact_map(semantic_registry),
                            )
                        if materialized is not None and materialized.accepted:
                            action_draft = materialized.draft
                            action_read_only_plan = rewritten_intent.read_only_plan
                            route_plan_matches = bool(
                                (
                                    semantic_rewrite.route_hint == "draft_flight_action"
                                    and isinstance(action_draft, FlightActionDraft)
                                )
                                or (
                                    semantic_rewrite.route_hint == "draft_sitl_lifecycle_action"
                                    and isinstance(action_draft, RegistryActionDraft)
                                )
                            )
                            if not route_plan_matches:
                                semantic_action_plan_error = "provider_action_route_plan_mismatch"
                                semantic_rewrite = replace(
                                    semantic_rewrite,
                                    needs_clarification=True,
                                    clarification_reason="semantic_ambiguity",
                                    clarification_question=(
                                        "I could not match the requested operation to one action type. "
                                        "Please restate the ordered steps."
                                    ),
                                )
                                action_draft = None
                            requested_action_read_intents = tuple(
                                dict.fromkeys(
                                    str(intent).strip()
                                    for intent in semantic_rewrite.read_intents
                                    if str(intent).strip()
                                )
                            )
                            unknown_action_read_intents = tuple(
                                intent
                                for intent in requested_action_read_intents
                                if provider_read_intent_tool_ids(intent) is None
                            )
                            if action_draft is not None and unknown_action_read_intents:
                                semantic_action_plan_error = (
                                    "provider_composite_read_intent_unknown"
                                )
                                semantic_rewrite = replace(
                                    semantic_rewrite,
                                    needs_clarification=True,
                                    clarification_reason="semantic_ambiguity",
                                    clarification_question=(
                                        "I understood the action, but not every status result "
                                        "you want first. Which live status should I include?"
                                    ),
                                )
                                action_draft = None
                            if action_draft is not None and requested_action_read_intents:
                                request_deps = _request_scoped_deps(deps, http_request)
                                (
                                    accepted_read_targets,
                                    unknown_explicit_read_targets,
                                    dropped_ungrounded_read_targets,
                                ) = _resolve_provider_read_targets(
                                    request_deps=request_deps,
                                    requested_targets=semantic_rewrite.read_target_drone_ids,
                                    grounding_messages=(
                                        turn_request.message,
                                        *_semantic_rewrite_grounding_messages(
                                            previous_context
                                        ),
                                    ),
                                    action_context=previous_action_for_routing,
                                )
                                semantic_read_target_resolution = {
                                    "accepted": list(accepted_read_targets),
                                    "unknown_explicit": list(
                                        unknown_explicit_read_targets
                                    ),
                                    "dropped_ungrounded": list(
                                        dropped_ungrounded_read_targets
                                    ),
                                }
                                if unknown_explicit_read_targets:
                                    targets = ", ".join(
                                        unknown_explicit_read_targets
                                    )
                                    semantic_rewrite = replace(
                                        semantic_rewrite,
                                        needs_clarification=True,
                                        clarification_reason="missing_runtime_context",
                                        clarification_question=(
                                            f"I cannot find drone {targets} in the configured "
                                            "or live fleet. Which drone should I check?"
                                        ),
                                    )
                                    action_draft = None
                                else:
                                    semantic_read_intents = (
                                        requested_action_read_intents
                                    )
                                    semantic_read_options = {
                                        str(intent): {
                                            str(name): bool(value)
                                            for name, value in options.items()
                                        }
                                        for intent, options
                                        in semantic_rewrite.read_options.items()
                                        if isinstance(options, Mapping)
                                    }
                                    semantic_read_target_drone_ids = (
                                        accepted_read_targets
                                    )
                                    requested_tool_ids = tuple(
                                        dict.fromkeys(
                                            tool_id
                                            for intent
                                            in requested_action_read_intents
                                            for tool_id in (
                                                provider_read_intent_tool_ids(
                                                    intent
                                                )
                                                or ()
                                            )
                                        )
                                    )
                                    primary_read_intent = (
                                        requested_action_read_intents[0]
                                    )
                                    read_topic = infer_mds_read_topic(
                                        turn_request.message,
                                        intent=primary_read_intent,
                                    ) or str(
                                        action_read_only_plan.topic or ""
                                    )
                                    action_read_only_plan = replace(
                                        action_read_only_plan,
                                        intent=primary_read_intent,
                                        topic=read_topic or "general",
                                        query_domain=(
                                            read_topic
                                            or action_read_only_plan.query_domain
                                        ),
                                        confidence=max(
                                            0.62,
                                            float(semantic_rewrite.confidence),
                                        ),
                                        unclear=False,
                                        reason=(
                                            "provider_semantic_composite_read_intent"
                                        ),
                                        tool_ids=requested_tool_ids,
                                        missing_arguments=(),
                                        execution_layer="local_advisory",
                                    )
                                    semantic_read_plan_resolution = {
                                        "provider_tool_ids": list(
                                            requested_tool_ids
                                        ),
                                        "grounded_tool_ids": [],
                                        "missing_grounded_tool_ids": [],
                                        "provider_added_tool_ids": list(
                                            requested_tool_ids
                                        ),
                                        "provider_dropped_tool_ids": [],
                                        "effective_tool_ids": list(
                                            requested_tool_ids
                                        ),
                                        "execution": (
                                            "provider_composite_read_intents"
                                        ),
                                    }
                            initial_action_draft = getattr(
                                initial_typed_intent.action,
                                "draft",
                                None,
                            )
                            if (
                                action_draft is not None
                                and initial_action_draft is not None
                                and _action_draft_step_count(initial_action_draft) > 1
                                and not _semantic_rewrite_preserves_draft_facts(
                                    initial_action_draft,
                                    action_draft,
                                )
                            ):
                                semantic_action_plan_error = (
                                    "provider_action_plan_conflicts_with_grounded_sequence"
                                )
                                semantic_rewrite = replace(
                                    semantic_rewrite,
                                    needs_clarification=True,
                                    clarification_reason="semantic_ambiguity",
                                    clarification_question=(
                                        "I found two different interpretations of the sequence. "
                                        "Should I keep every requested step in the same order "
                                        "and stop if any step fails?"
                                    ),
                                )
                                action_draft = None
                            if action_draft is not None:
                                rewritten_action = replace(
                                    rewritten_intent.action,
                                    request_message=turn_request.message,
                                    draft=action_draft,
                                    direct_flight_request=isinstance(action_draft, FlightActionDraft),
                                    flight_followup_request=False,
                                    sitl_lifecycle_request=isinstance(action_draft, RegistryActionDraft),
                                    replayed_previous_request=False,
                                )
                                turn_intent = replace(
                                    rewritten_intent,
                                    read_only_plan=action_read_only_plan,
                                    confirmation_message=False,
                                    rejection_message=False,
                                    explicit_action_draft_id="",
                                    action=rewritten_action,
                                    route="action_draft",
                                    confidence=max(0.62, float(semantic_rewrite.confidence)),
                                    reasons=("provider-structured-action-plan",),
                                )
                        elif materialized is not None:
                            semantic_action_plan_error = ":".join(
                                item
                                for item in (materialized.reason, materialized.field_path)
                                if item
                            )[:180]
                            semantic_rewrite = replace(
                                semantic_rewrite,
                                needs_clarification=True,
                                clarification_reason="missing_runtime_context",
                                clarification_question=_provider_action_materialization_question(
                                    materialized,
                                    semantic_rewrite.action_plan,
                                ),
                            )
                    elif (
                        semantic_rewrite.route_hint in SEMANTIC_REWRITE_DRAFT_ACTION_HINTS
                        and not semantic_rewrite.needs_clarification
                    ):
                        semantic_action_plan_error = "provider_action_plan_missing"
                        semantic_rewrite = replace(
                            semantic_rewrite,
                            needs_clarification=True,
                            clarification_question=(
                                "I understood this as an action, but not the complete ordered plan. "
                                "Please restate the target and steps."
                            ),
                        )
                    elif _should_accept_semantic_rewrite(
                        initial_intent=turn_intent,
                        rewritten_intent=rewritten_intent,
                        semantic_rewrite=semantic_rewrite,
                    ):
                        turn_intent = rewritten_intent

            if (
                structured_action_intent not in {"confirm", "reject"}
                and initial_typed_intent.action.has_action_request
                and not (
                    semantic_rewrite is not None
                    and semantic_rewrite.usable_for_routing
                    and semantic_rewrite.route_hint == "read_status"
                    and turn_intent.route == "read_only"
                    and "provider-structured-read-intent" in turn_intent.reasons
                )
                and not (
                    semantic_rewrite is not None
                    and getattr(semantic_rewrite, "action_plan", None) is not None
                    and turn_intent.route == "action_draft"
                    and "provider-structured-action-plan" in turn_intent.reasons
                )
                and not bool(
                    semantic_rewrite is not None
                    and getattr(semantic_rewrite, "needs_clarification", False)
                )
            ):
                # The deterministic parser is useful for intent detection and
                # tests, but it is not authoritative for natural-language
                # execution. Only a source-grounded semantic plan may become a
                # reviewable action draft.
                semantic_interpretation_failed = True
                if not semantic_rewrite_error:
                    semantic_rewrite_error = (
                        "source-grounded semantic action interpretation unavailable"
                    )
            if (
                structured_action_intent == "amend"
                and not (
                    semantic_rewrite is not None
                    and getattr(semantic_rewrite, "action_plan", None) is not None
                    and turn_intent.route == "action_draft"
                    and "provider-structured-action-plan" in turn_intent.reasons
                )
                and not bool(
                    semantic_rewrite is not None
                    and getattr(semantic_rewrite, "needs_clarification", False)
                )
            ):
                semantic_interpretation_failed = True
                if not semantic_rewrite_error:
                    semantic_rewrite_error = (
                        "source-grounded semantic action amendment unavailable"
                    )

            def turn_intent_metadata(
                action_draft_override: ActionDraft | None = None,
                *,
                route_override: str | None = None,
            ) -> dict[str, Any]:
                metadata = turn_intent.public_metadata()
                if route_override:
                    metadata["route"] = route_override
                if action_draft_override is not None:
                    payload = action_draft_override.public_payload()
                    action_metadata = metadata.get("action")
                    if isinstance(action_metadata, dict):
                        action_metadata["draft_ready"] = bool(action_draft_override.ready)
                        action_metadata["draft_type"] = payload.get("draft_type")
                        action_metadata["draft_tool_id"] = payload.get("tool_id")
                        action_metadata["draft_missing_arguments"] = list(payload.get("missing_arguments") or [])
                if semantic_rewrite is not None:
                    metadata["provider_semantic_rewrite"] = semantic_rewrite.public_metadata()
                if semantic_rewrite_error:
                    metadata["provider_semantic_rewrite_error"] = semantic_rewrite_error
                if semantic_action_plan_error:
                    metadata["provider_action_plan_error"] = semantic_action_plan_error
                if semantic_read_target_resolution:
                    metadata["provider_read_target_resolution"] = dict(semantic_read_target_resolution)
                if semantic_read_plan_resolution:
                    metadata["provider_read_plan_resolution"] = dict(semantic_read_plan_resolution)
                if structured_action_intent == "amend":
                    metadata["amends_action_draft_id"] = structured_action_draft_id
                return metadata

            routing_message = turn_intent.routing_message
            previous_evidence_followup = bool(
                not semantic_conversation_transform
                and previous_context.get("last_assistant_content")
                and previous_context.get("last_read_only_evidence")
                and is_previous_evidence_followup_message(routing_message)
            )
            read_only_plan = turn_intent.read_only_plan
            query_plan = turn_intent.query_plan
            await _emit_assistant_progress(
                progress_callback,
                _assistant_understanding_progress_payload(
                    query_plan=query_plan,
                    read_only_plan=read_only_plan,
                    previous_evidence_followup=previous_evidence_followup,
                ),
            )
            if semantic_interpretation_failed:
                record = await _create_semantic_clarification_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    question=(
                        "I could not safely map that request to a complete action plan. "
                        "Please retry, or clarify the target and ordered steps."
                    ),
                    semantic_rewrite=semantic_rewrite,
                    turn_intent_metadata=turn_intent_metadata(
                        route_override="semantic_clarification",
                    ),
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(record=record, message=turn_request.message)
                return record, history_record
            semantic_clarification_required = bool(
                semantic_rewrite is not None
                and bool(getattr(semantic_rewrite, "needs_clarification", False))
                and str(getattr(semantic_rewrite, "clarification_question", "") or "").strip()
            )
            if semantic_clarification_required:
                record = await _create_semantic_clarification_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    question=str(semantic_rewrite.clarification_question),
                    semantic_rewrite=semantic_rewrite,
                    turn_intent_metadata=turn_intent_metadata(
                        route_override="semantic_clarification",
                    ),
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(record=record, message=turn_request.message)
                return record, history_record
            local_intent = None if semantic_conversation_transform else read_only_plan.intent
            stored_draft = _stored_action_draft(turn_request.session_id)
            rejection_message = turn_intent.rejection_message
            if rejection_message:
                explicit_draft_id = turn_intent.explicit_action_draft_id
                if explicit_draft_id:
                    if stored_draft and stored_draft.draft_id.lower() == explicit_draft_id.lower():
                        record = await _create_rejected_action_record(
                            http_request,
                            turn_request,
                            actor=actor,
                            draft=stored_draft,
                            session_id=turn_request.session_id or "",
                            turn_intent_metadata=turn_intent_metadata(),
                            progress_callback=progress_callback,
                        )
                        history_record = history.append_turn(
                            record=record,
                            message=turn_request.message,
                        )
                        return record, history_record
                    explicit_matches = _recent_pending_action_drafts_for_actor(
                        actor=actor,
                        draft_id=explicit_draft_id,
                    )
                    if len(explicit_matches) == 1:
                        recovered_session, recovered_draft = explicit_matches[0]
                        recovered_request = _turn_request_with_session(
                            turn_request,
                            session_id=recovered_session.id,
                        )
                        record = await _create_rejected_action_record(
                            http_request,
                            recovered_request,
                            actor=actor,
                            draft=recovered_draft,
                            session_id=recovered_session.id,
                            turn_intent_metadata=turn_intent_metadata(),
                            progress_callback=progress_callback,
                        )
                        history_record = history.append_turn(
                            record=record,
                            message=turn_request.message,
                        )
                        return record, history_record
                    record = await _create_no_pending_confirmation_record(
                        http_request,
                        turn_request,
                        actor=actor,
                        candidate_count=0,
                        turn_intent_metadata=turn_intent_metadata(),
                        progress_callback=progress_callback,
                    )
                    history_record = history.append_turn(
                        record=record,
                        message=turn_request.message,
                    )
                    return record, history_record
                if stored_draft and (
                    semantic_rejection_request
                    or is_action_rejection_message(routing_message)
                ):
                    record = await _create_rejected_action_record(
                        http_request,
                        turn_request,
                        actor=actor,
                        draft=stored_draft,
                        session_id=turn_request.session_id or "",
                        turn_intent_metadata=turn_intent_metadata(),
                        progress_callback=progress_callback,
                    )
                    history_record = history.append_turn(record=record, message=turn_request.message)
                    return record, history_record
                pending_matches = _recent_pending_action_drafts_for_actor(
                    actor=actor,
                )
                if len(pending_matches) == 1:
                    _, recovered_draft = pending_matches[0]
                    record = await _create_pending_action_summary_record(
                        http_request,
                        turn_request,
                        actor=actor,
                        draft=recovered_draft,
                        turn_intent_metadata={
                            **turn_intent_metadata(),
                            "cross_session_pending_action_represented": True,
                        },
                        progress_callback=progress_callback,
                    )
                    history_record = history.append_turn(record=record, message=turn_request.message)
                    return record, history_record
                active_runs = await action_run_store_call(
                    action_runs.list_runs,
                    actor=actor,
                    session_id=turn_request.session_id or None,
                    active_only=True,
                    limit=20,
                )
                if not active_runs and turn_request.session_id:
                    active_runs = await action_run_store_call(
                        action_runs.list_runs,
                        actor=actor,
                        active_only=True,
                        limit=20,
                    )
                if len(active_runs) == 1:
                    record = await _create_action_run_control_record(
                        http_request,
                        turn_request,
                        actor=actor,
                        run=active_runs[0],
                        action="cancel_remaining",
                        turn_intent_metadata=turn_intent_metadata(),
                        progress_callback=progress_callback,
                    )
                    history_record = history.append_turn(record=record, message=turn_request.message)
                    return record, history_record
                if len(active_runs) > 1:
                    record = await _create_semantic_clarification_record(
                        http_request,
                        turn_request,
                        actor=actor,
                        question=(
                            f"I found {len(active_runs)} active operations. Which one should I cancel?"
                        ),
                        semantic_rewrite=semantic_rewrite,
                        turn_intent_metadata=turn_intent_metadata(),
                        progress_callback=progress_callback,
                    )
                    history_record = history.append_turn(record=record, message=turn_request.message)
                    return record, history_record
                record = await _create_no_pending_confirmation_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    candidate_count=len(pending_matches),
                    turn_intent_metadata=turn_intent_metadata(),
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(record=record, message=turn_request.message)
                return record, history_record

            confirmation_message = turn_intent.confirmation_message
            if confirmation_message:
                explicit_draft_id = turn_intent.explicit_action_draft_id
                if explicit_draft_id:
                    if stored_draft and stored_draft.draft_id.lower() == explicit_draft_id.lower():
                        record = await _create_action_record(
                            http_request,
                            turn_request,
                            actor=actor,
                            draft=stored_draft,
                            confirmed=True,
                            turn_intent_metadata=turn_intent_metadata(),
                            progress_callback=progress_callback,
                        )
                        history_record = history.append_turn(
                            record=record,
                            message=turn_request.message,
                        )
                        return record, history_record
                    explicit_matches = _recent_pending_action_drafts_for_actor(
                        actor=actor,
                        draft_id=explicit_draft_id,
                    )
                    if len(explicit_matches) == 1:
                        recovered_session, recovered_draft = explicit_matches[0]
                        recovered_request = _turn_request_with_session(
                            turn_request,
                            session_id=recovered_session.id,
                        )
                        record = await _create_action_record(
                            http_request,
                            recovered_request,
                            actor=actor,
                            draft=recovered_draft,
                            confirmed=True,
                            turn_intent_metadata=turn_intent_metadata(),
                            progress_callback=progress_callback,
                        )
                        history_record = history.append_turn(
                            record=record,
                            message=turn_request.message,
                        )
                        return record, history_record
                    record = await _create_no_pending_confirmation_record(
                        http_request,
                        turn_request,
                        actor=actor,
                        candidate_count=0,
                        turn_intent_metadata=turn_intent_metadata(),
                        progress_callback=progress_callback,
                    )
                    history_record = history.append_turn(
                        record=record,
                        message=turn_request.message,
                    )
                    return record, history_record
                if stored_draft and (
                    semantic_confirmation_request
                    or is_action_confirmation_message(routing_message)
                ):
                    record = await _create_action_record(
                        http_request,
                        turn_request,
                        actor=actor,
                        draft=stored_draft,
                        confirmed=True,
                        turn_intent_metadata=turn_intent_metadata(),
                        progress_callback=progress_callback,
                    )
                    history_record = history.append_turn(record=record, message=turn_request.message)
                    return record, history_record

                pending_matches = _recent_pending_action_drafts_for_actor(
                    actor=actor,
                )
                if len(pending_matches) == 1:
                    _, recovered_draft = pending_matches[0]
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "safety",
                            "state": "complete",
                            "label": "Found pending action in another conversation",
                            "intent": _action_draft_intent(recovered_draft),
                            "tool_id": _action_draft_tool_id(recovered_draft),
                            "tool_ids": [_action_draft_tool_id(recovered_draft)],
                            "draft_id": recovered_draft.draft_id,
                        },
                    )
                    record = await _create_pending_action_summary_record(
                        http_request,
                        turn_request,
                        actor=actor,
                        draft=recovered_draft,
                        turn_intent_metadata={
                            **turn_intent_metadata(),
                            "cross_session_pending_action_represented": True,
                        },
                        progress_callback=progress_callback,
                    )
                    history_record = history.append_turn(record=record, message=turn_request.message)
                    return record, history_record

                record = await _create_no_pending_confirmation_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    candidate_count=len(pending_matches),
                    turn_intent_metadata=turn_intent_metadata(),
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(record=record, message=turn_request.message)
                return record, history_record

            blocked_matches = tuple(
                sorted(
                    set(
                        blocked_intent_matches(assistant_config, turn_request.message)
                        + blocked_intent_matches(assistant_config, routing_message)
                    )
                )
            )
            sensitive_matches = tuple(
                sorted(
                    set(
                        sensitive_input_matches(assistant_config, turn_request.message)
                        + sensitive_input_matches(assistant_config, routing_message)
                    )
                )
            )
            sensitive_matches = filter_safe_read_only_sensitive_input_matches(
                sensitive_matches,
                message=turn_request.message,
                routing_message=routing_message,
                local_intent=local_intent,
            )
            safe_read_only_blocked_term = (
                _is_authoritative_typed_read_only_intent(initial_typed_intent)
                or is_safe_blocked_term_read_only_intent(routing_message, local_intent)
            )
            semantic_read_only_route = bool(
                semantic_rewrite is not None
                and semantic_rewrite.usable_for_routing
                and semantic_rewrite.route_hint == "read_status"
                and semantic_read_intents
                and turn_intent.route == "read_only"
                and turn_intent.action.draft is None
            )
            semantic_action_route = bool(
                semantic_rewrite is not None
                and semantic_rewrite.usable_for_routing
                and getattr(semantic_rewrite, "action_plan", None) is not None
                and turn_intent.route == "action_draft"
                and "provider-structured-action-plan" in turn_intent.reasons
            )
            if sensitive_matches and (semantic_read_only_route or semantic_action_route):
                # The semantic adapter receives tokenized placeholders and the
                # typed local route remains authoritative. Permit that local
                # evidence/action path without exposing raw values to answer
                # composition or bypassing policy.
                sensitive_matches = ()
            if blocked_matches and (safe_read_only_blocked_term or semantic_read_only_route):
                blocked_matches = ()
            if (
                blocked_matches
                and initial_typed_intent.route == "provider_or_registry"
                and not initial_typed_intent.action.has_action_request
                and not semantic_action_route
            ):
                record = await _create_semantic_clarification_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    question=(
                        "I am not sure whether you want a read-only readiness check "
                        "or a guarded action. Should I check the current readiness, "
                        "or prepare an action plan for confirmation? If it is an action, "
                        "include the drone and intended parameters."
                    ),
                    semantic_rewrite=semantic_rewrite,
                    turn_intent_metadata=turn_intent_metadata(
                        route_override="semantic_clarification",
                    ),
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(
                    record=record,
                    message=turn_request.message,
                )
                return record, history_record
            effective_action_request = (
                _turn_request_with_message(turn_request, message=turn_intent.action.request_message)
                if turn_intent.action.replayed_previous_request
                else turn_request
            )
            previous_action_read_requested = not semantic_conversation_transform and (
                (
                    semantic_previous_action_read
                    and len(semantic_read_intents) == 1
                )
                or (
                    not semantic_read_intents
                    and _looks_like_previous_action_result_question(routing_message)
                )
                or semantic_untrusted_control_request
            )
            if previous_action_read_requested and stored_draft:
                record = await _create_pending_action_summary_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    draft=stored_draft,
                    turn_intent_metadata=turn_intent_metadata(),
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(record=record, message=turn_request.message)
                return record, history_record
            if previous_action_read_requested and (
                semantic_previous_action_read
                or _stored_last_submitted_action(
                    turn_request.session_id,
                    actor=actor,
                )
            ):
                record = await _create_previous_action_summary_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    turn_intent_metadata=turn_intent_metadata(),
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(record=record, message=turn_request.message)
                return record, history_record
            if not sensitive_matches and turn_intent.is_action_route:
                action_draft = _action_draft_with_inferred_single_sitl_instance(
                    http_request,
                    turn_intent.action.draft,
                )
                (
                    pre_action_read_only_content,
                    pre_action_read_only_evidence,
                    pre_action_read_only_tool_ids,
                ) = await _pre_action_read_only_context(
                    http_request,
                    turn_request,
                    routing_message=routing_message,
                    read_only_plan=read_only_plan,
                    conversation_topic=conversation_topic,
                    action_draft=action_draft,
                    explicit_read_requested=bool(semantic_read_intents),
                    progress_callback=progress_callback,
                )
                record = await _create_action_record(
                    http_request,
                    effective_action_request,
                    actor=actor,
                    draft=action_draft,
                    confirmed=False,
                    pre_action_read_only_content=pre_action_read_only_content,
                    pre_action_read_only_evidence=pre_action_read_only_evidence,
                    pre_action_read_only_tool_ids=pre_action_read_only_tool_ids,
                    turn_intent_metadata=turn_intent_metadata(action_draft),
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(record=record, message=turn_request.message)
                return record, history_record
            local_only_turn = bool(local_intent or blocked_matches or sensitive_matches)
            registry_plan = None
            if (
                not semantic_conversation_transform
                and not previous_evidence_followup
                and not blocked_matches
                and not sensitive_matches
            ):
                registry_plan = grounded_read_registry_plan
                if registry_plan is None and not semantic_read_intents:
                    registry_plan = plan_registry_read_tool_calls(
                        routing_message,
                        allowed_tools=list_policy_allowed_read_only_tools(channel="agent"),
                        conversation_topic=conversation_topic,
                        local_intent=local_intent,
                    )
                local_only_turn = local_only_turn or registry_plan is not None
            provider_auth_allowed = assistant_config.provider != "mock" and _has_external_assistant_provider_auth(http_request)
            if not local_only_turn:
                _require_external_assistant_provider_auth(http_request, assistant_config.provider)
                provider_auth_allowed = assistant_config.provider != "mock"
            if registry_plan is not None:
                record = await _create_registry_read_execution_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    plan=registry_plan,
                    allow_provider_composition=(
                        provider_auth_allowed
                        and not _registry_plan_prefers_deterministic_state_summary(registry_plan)
                    ),
                    turn_intent_metadata=turn_intent_metadata(),
                    progress_callback=progress_callback,
                )
            else:
                record = None
                prefer_local_context_answer = bool(semantic_read_intents) or (
                    (
                        _is_authoritative_typed_read_only_intent(initial_typed_intent)
                        or (
                            local_intent in {"fleet_connectivity", "command_summary"}
                            and conversation_topic in {"flight", "sitl", "fleet"}
                        )
                    )
                    and not previous_evidence_followup
                    and not blocked_matches
                    and not sensitive_matches
                )
                if (
                    local_intent
                    and (prefer_local_context_answer or not provider_auth_allowed)
                    and not previous_evidence_followup
                    and not blocked_matches
                    and not sensitive_matches
                ):
                    record = await _create_local_read_only_answer_record(
                        http_request,
                        turn_request,
                        actor=actor,
                        routing_message=routing_message,
                        read_only_plan=read_only_plan,
                        read_intent_overrides=semantic_read_intents,
                        read_target_drone_ids=semantic_read_target_drone_ids,
                        read_options=semantic_read_options,
                        response_detail=(
                            semantic_rewrite.response_detail
                            if semantic_rewrite is not None
                            else "standard"
                        ),
                        turn_intent_metadata=turn_intent_metadata(),
                        progress_callback=progress_callback,
                    )
                if record is None:
                    request_deps = _request_scoped_deps(deps, http_request)
                    record = await run_blocking_provider_call(
                        create_assistant_turn,
                        sessions=sessions,
                        audit=audit,
                        actor=actor,
                        actor_role=_auth_tool_role(http_request),
                        message=turn_request.message,
                        deps=request_deps,
                        session_id=turn_request.session_id,
                        mode=turn_request.mode,
                        context_resource_ids=_bounded_context_resource_ids(turn_request.context_resource_ids),
                        metadata=_bounded_metadata(
                            {
                                **dict(turn_request.metadata or {}),
                                "turn_intent": turn_intent_metadata(),
                                "_semantic_conversation_transform_kind": (
                                    "transform_previous_answer"
                                    if semantic_conversation_transform
                                    else ""
                                ),
                            }
                        ),
                        allow_provider_for_local_tools=(local_only_turn or previous_evidence_followup) and provider_auth_allowed,
                        finish_on_cancel=True,
                    )
            history_record = history.append_turn(record=record, message=turn_request.message)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AgentRuntimeError as exc:
            message = str(exc)
            if "history file" in message:
                status_code = 500
            elif "provider" in message and "not implemented" in message:
                status_code = 501
            else:
                status_code = 400
            raise HTTPException(status_code=status_code, detail=message) from exc
        return record, history_record

    async def _create_assistant_turn_record_for_request(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        progress_callback: AssistantProgressCallback | None = None,
    ):
        """Serialize one actor's turns so retries cannot overlap an action sequence."""

        actor = _resolve_actor(http_request, turn_request.actor)
        actor_lock = assistant_actor_locks.setdefault(actor, asyncio.Lock())
        async with actor_lock:
            return await _create_assistant_turn_record_for_request_unlocked(
                http_request,
                turn_request,
                progress_callback=progress_callback,
            )

    @router.post("/api/v1/simurgh/assistant/turns", response_model=SimurghAssistantTurnResponse)
    async def create_simurgh_assistant_turn(http_request: Request, request: SimurghAssistantTurnRequest):
        record, history_record = await _create_assistant_turn_record_for_request(http_request, request)
        return _assistant_turn_response_model(record, history_record)

    @router.post("/api/v1/simurgh/assistant/turns/stream")
    async def stream_simurgh_assistant_turn(http_request: Request, request: SimurghAssistantTurnRequest):
        async def event_stream():
            turn_task = None
            try:
                yield _assistant_sse_event("progress", {"stage": "understanding", "state": "running", "label": "Understanding request"})
                await asyncio.sleep(0)

                progress_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

                async def progress_callback(payload: dict[str, Any]) -> None:
                    await progress_queue.put(("progress", payload))

                async def run_turn() -> None:
                    try:
                        record, history_record = await _create_assistant_turn_record_for_request(
                            http_request,
                            request,
                            progress_callback=progress_callback,
                        )
                        await progress_queue.put(("final", _assistant_turn_response_payload(record, history_record)))
                    except HTTPException as exc:
                        await progress_queue.put(("error", {"status_code": exc.status_code, "detail": exc.detail}))
                    except Exception:  # pragma: no cover - final guard for streaming clients
                        await progress_queue.put(("error", {"status_code": 500, "detail": "Simurgh stream failed."}))
                    finally:
                        await progress_queue.put(("finished", {}))

                turn_task = retain_assistant_turn_task(
                    asyncio.create_task(run_turn(), name="simurgh-assistant-turn")
                )
                payload: dict[str, Any] | None = None
                saw_tool_progress = False
                while True:
                    event_name, event_payload = await progress_queue.get()
                    if event_name == "finished":
                        break
                    if event_name == "progress":
                        if event_payload.get("stage") == "tool":
                            saw_tool_progress = True
                        yield _assistant_sse_event("progress", event_payload)
                        await asyncio.sleep(0)
                    elif event_name == "final":
                        payload = event_payload
                    elif event_name == "error":
                        yield _assistant_sse_event("error", event_payload)
                        return

                if turn_task is not None:
                    await turn_task
                if payload is None:
                    yield _assistant_sse_event("error", {"status_code": 500, "detail": "Simurgh stream did not produce a final answer."})
                    return
                if not saw_tool_progress:
                    yield _assistant_sse_event("progress", _assistant_tool_progress_payload(payload))
                await asyncio.sleep(0)
                content = str(payload.get("content") or "")
                if content:
                    yield _assistant_sse_event("progress", {"stage": "answer", "state": "running", "label": "Streaming answer"})
                    await asyncio.sleep(0)
                    for chunk in _assistant_content_chunks(content):
                        yield _assistant_sse_event("delta", {"text": chunk})
                        await asyncio.sleep(0)
                yield _assistant_sse_event("final", payload)
                session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
                yield _assistant_sse_event("done", {"id": payload.get("id"), "session_id": session.get("id")})
            except HTTPException as exc:
                yield _assistant_sse_event("error", {"status_code": exc.status_code, "detail": exc.detail})
            except Exception:  # pragma: no cover - final guard for streaming clients
                yield _assistant_sse_event("error", {"status_code": 500, "detail": "Simurgh stream failed."})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/v1/simurgh/assistant/turns", response_model=SimurghAssistantTurnListResponse)
    async def list_simurgh_assistant_turns(
        request: Request,
        session_id: str | None = Query(default=None),
        actor: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=MAX_ASSISTANT_HISTORY_LIMIT),
    ):
        context = _auth_context(request)
        if _auth_enabled(context) and str(context.get("role") or "").lower() != "admin":
            actor_filter = _auth_actor(context)
        else:
            actor_filter = actor.strip() if actor else _resolve_actor(request, "dashboard")
        _require_actor_access(request, actor_filter)
        try:
            records = history.list_records(session_id=session_id, actor=actor_filter, limit=limit)
        except AgentRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return SimurghAssistantTurnListResponse(turns=[_assistant_history_response(record) for record in records])

    @router.post(MCP_ENDPOINT_PATH)
    async def post_simurgh_mcp(request: Request):
        request_id: str | int | None = None
        if not is_mcp_origin_allowed(request.headers.get("origin")):
            return _mcp_json_error(
                request_id,
                code=JSONRPC_SERVER_ERROR,
                message="Origin is not allowed for Simurgh MCP",
                status_code=403,
            )

        try:
            require_mcp_runtime_enabled(load_default_policy())
        except AgentRuntimeError as exc:
            status_code = 403 if "disabled" in str(exc) else 500
            return _mcp_json_error(
                request_id,
                code=JSONRPC_SERVER_ERROR,
                message=str(exc),
                status_code=status_code,
            )

        auth_error = _require_mcp_bearer_scope(request, request_id)
        if auth_error is not None:
            return auth_error

        try:
            message = await request.json()
        except ValueError:
            return _mcp_json_error(
                request_id,
                code=JSONRPC_PARSE_ERROR,
                message="invalid JSON-RPC payload",
                status_code=400,
            )

        request_id = _mcp_request_id(message)
        protocol_header = request.headers.get("mcp-protocol-version")
        if protocol_header and protocol_header != MCP_PROTOCOL_VERSION:
            return _mcp_json_error(
                request_id,
                code=JSONRPC_SERVER_ERROR,
                message=f"unsupported MCP protocol version: {protocol_header}",
                status_code=400,
            )

        response = await _handle_mcp_jsonrpc(message, request=request, resources=mcp_resources)
        if response is None:
            return Response(status_code=202)
        return JSONResponse(content=response)

    return router

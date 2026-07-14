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
from typing import Any, Awaitable, Callable, Mapping

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
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
    is_action_confirmation_message,
    is_action_rejection_message,
)
from agent_runtime.action_runs import (
    ActionRunSnapshot,
    ActionRunStore,
)
from agent_runtime.action_intent import build_action_draft_from_provider_plan
from agent_runtime.mds_read_tools import (
    answer_mds_read_only_question,
    apply_runtime_settings,
    build_provider_credentials_payload,
    build_runtime_settings_payload,
    delete_provider_credentials,
    is_safe_blocked_term_read_only_intent,
    update_provider_credentials,
)
from agent_runtime.language import detect_language_profile
from agent_runtime.models import AgentSession, AuditEvent, ContextResource, ToolDefinition, stable_payload_hash, utc_now
from agent_runtime.query_adaptation import adapt_operator_query, normalize_operator_query_text
from agent_runtime.registry_chat import (
    REGISTRY_READ_EXECUTION_INTENT,
    RegistryReadCall,
    RegistryReadPlan,
    RegistryReadToolResult,
    build_registry_read_evidence_bundle,
    format_registry_read_results,
    plan_registry_read_tool_calls,
)
from agent_runtime.tool_candidates import candidate_review_payload, load_default_tool_candidate_artifact
from agent_runtime.turn_intent import build_turn_intent_frame
from command_submission import submit_tracked_command
from schemas import SubmitCommandRequest
from simurgh_internal_auth import INTERNAL_TOOL_CALL_HEADER, INTERNAL_TOOL_CALL_VALUE


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
PENDING_ACTION_RECOVERY_SECONDS = 600
COMMAND_TERMINAL_PHASE = "terminal"
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
    "confirm_pending_action",
    "reject_pending_action",
}
SEMANTIC_REWRITE_ACTION_CONTROL_ROUTES = {
    "confirm_pending_action": "action_confirmation",
    "reject_pending_action": "action_rejection",
}
SEMANTIC_REWRITE_HELP_INTENTS = {
    "docs_help",
    "sitl_help",
    "operator_help",
    "board_setup_help",
    "companion_setup_help",
}
SEMANTIC_REWRITE_LOCAL_CAPABILITY_INTENTS = {
    "action_capability",
    "capability_catalog",
    "registry_domain_tool_summary",
}
SEMANTIC_REWRITE_INTENT_DOMAINS = {
    "backend_log_summary": {"logs"},
    "command_summary": {"commands", "fleet", "runtime"},
    "drone_log_summary": {"logs", "fleet"},
    "environment_summary": {"runtime"},
    "fleet_connectivity": {"fleet"},
    "fleet_enrollment_summary": {"fleet", "setup"},
    "fleet_summary": {"fleet"},
    "git_status_summary": {"git", "runtime"},
    "node_boot_status": {"fleet", "runtime"},
    "origin_status": {"origin", "fleet"},
    "px4_params_summary": {"px4_params", "safety"},
    "runtime_summary": {"runtime"},
    "sar_summary": {"sar"},
    "sidecar_status": {"fleet", "runtime"},
    "show_summary": {"drone_show"},
    "swarm_readiness": {"swarm", "fleet"},
    "swarm_topology": {"swarm"},
    "system_status": {"runtime", "safety"},
}


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
    if isinstance(action_run, dict) and action_run:
        safety["action_run"] = dict(action_run)
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
            f"Read-only evidence ready: {joined_titles}"
            if len(tool_ids) == 1
            else f"Read-only evidence ready from {len(tool_ids)} sources: {joined_titles}"
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
    label = "Selecting read-only evidence"
    if count == 1:
        label = f"Selected read-only evidence: {plan.tool_calls[0].tool.title}"
    elif count > 1:
        label = f"Selected {count} read-only evidence sources"
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
        return f"Step {step_index}/{step_count}: {label}"
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


def _submitted_action_progress_outcome(
    draft: ActionDraft,
    *,
    monitor_result: Mapping[str, Any] | None = None,
    post_action_results: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, str]:
    if not isinstance(draft, FlightActionDraft):
        return "complete", "GCS accepted action submission"
    if not monitor_result:
        return (
            ("requested", "GCS accepted command sequence")
            if draft.monitor_requested
            else ("complete", "GCS accepted action submission")
        )
    if monitor_result.get("timed_out"):
        return "timeout", "Command sequence monitoring timed out"
    if not monitor_result.get("success"):
        return "failed", "Command sequence stopped after primary command"

    completion_verification = (
        monitor_result.get("completion_verification")
        if isinstance(monitor_result.get("completion_verification"), Mapping)
        else None
    )
    if completion_verification and not completion_verification.get("verified"):
        if str(completion_verification.get("status") or "").casefold() == "timeout":
            return "timeout", "Final disarm verification timed out"
        if draft.post_actions:
            return "failed", "Final disarm was not verified; dependent steps were not run"
        return "warning", "Command completed; final disarm was not verified"

    if not draft.post_actions:
        return "complete", "Command complete"

    results = tuple(post_action_results)
    if len(results) < len(draft.post_actions):
        return "failed", "Command sequence stopped before all steps completed"
    if any(str(item.get("status") or "").casefold() in {"timeout", "timed_out"} for item in results):
        return "timeout", "Command sequence monitoring timed out"
    if any(bool(item.get("is_error")) for item in results):
        return "failed", "Command sequence stopped before all steps completed"
    return "complete", "Command sequence complete"


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
        if draft.wait_condition:
            payload["wait_condition"] = draft.wait_condition
        if draft.post_actions:
            payload["post_actions"] = [dict(item) for item in draft.post_actions]
        return payload
    return dict(draft.arguments)


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
    lines = ["Interpreted command pack:"]
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
            lines.append(f"- Monitor after submission: `{draft.wait_condition or 'command_terminal'}`.")
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
        lines.append("- Monitor after submission: operation status until terminal state.")
    return lines


def _action_draft_display_plan(draft: ActionDraft) -> dict[str, Any]:
    """Return a renderer-neutral operator plan from the canonical action draft."""

    steps: list[dict[str, Any]] = []
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
            "steps": steps,
        }

    registry_label = str(draft.action_label or draft.tool_title or "Run guarded action").strip()
    registry_label = registry_label[:1].upper() + registry_label[1:]
    return {
        "title": "Review system action",
        "target": str(draft.tool_title or "Guarded GCS operation"),
        "steps": [
            {
                "index": 1,
                "kind": "system_action",
                "label": registry_label,
            }
        ],
    }


def _action_draft_summary_block(draft: ActionDraft) -> str:
    return "\n".join(_action_draft_summary_lines(draft))


def _pre_action_read_only_context_block(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    return f"Read-only status checked before drafting:\n{text}\n\n"


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
            "instace",
            "isntance",
            "isntnace",
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
    return outcome in COMMAND_SUCCESS_OUTCOMES or command_status == "completed"


def _operation_terminal(status: Mapping[str, Any] | None) -> bool:
    if not isinstance(status, Mapping):
        return False
    return _compact_status_value(status.get("status")).lower() in SITL_TERMINAL_STATUSES


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
    for key in ("tool_id", "action_label", "operation_id", "command_id"):
        value = previous_action.get(key)
        if value is not None and str(value).strip():
            parts.append(f"{key}={str(value).strip()[:80]}")
    targets = previous_action.get("inferred_target_drone_ids")
    if isinstance(targets, (list, tuple)) and targets:
        clean_targets = [str(item).strip() for item in targets if str(item).strip()]
        if clean_targets:
            parts.append("targets=" + ",".join(clean_targets[:8]))
    return "; ".join(parts)[:240]


def _provider_action_tool_contracts(registry: Any) -> tuple[dict[str, Any], ...]:
    contracts: list[dict[str, Any]] = []
    for tool in registry.list_tools(exposure=ToolExposure.GUARDED):
        if tool.boundary != "gcs" or tool.destructive:
            continue
        contracts.append(
            {
                "id": tool.id,
                "title": tool.title,
                "description": tool.description,
                "input_schema": dict(tool.input_schema or {}),
                "runtime_modes": list(tool.runtime_modes),
                "intent": ACTION_INTENT if tool.id == ACTION_TOOL_ID else "sitl_lifecycle_action",
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
            "required": tuple(str(item) for item in (required or ())),
        }
    return result


def _semantic_rewrite_clarification_context(previous_context: Mapping[str, str]) -> str:
    if str(previous_context.get("last_domain") or "") != "clarification":
        return ""
    original = " ".join(str(previous_context.get("last_user_message") or "").split()).strip()
    question = " ".join(str(previous_context.get("last_assistant_content") or "").split()).strip()
    if not original or not question:
        return ""
    return f"Previous request: {original[:800]}\nClarification asked: {question[:300]}"


def _semantic_rewrite_read_intent_matches_domain(intent: str, query_domain: str) -> bool:
    intent_name = str(intent or "").strip()
    domain = str(query_domain or "").strip()
    if not intent_name or not domain or domain == "general":
        return False
    domains = SEMANTIC_REWRITE_INTENT_DOMAINS.get(intent_name)
    return bool(domains and domain in domains)


def _semantic_rewrite_read_only_needs_provider(turn_intent: Any) -> bool:
    read_plan = getattr(turn_intent, "read_only_plan", None)
    intent = str(getattr(read_plan, "intent", "") or "")
    query_domain = str(getattr(read_plan, "query_domain", "") or "")
    try:
        confidence = float(getattr(read_plan, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if not intent:
        return True
    if intent in SEMANTIC_REWRITE_LOCAL_CAPABILITY_INTENTS:
        return False
    if is_previous_evidence_followup_message(getattr(turn_intent, "routing_message", "")):
        return False
    if intent in SEMANTIC_REWRITE_HELP_INTENTS:
        return True
    if _semantic_rewrite_read_intent_matches_domain(intent, query_domain):
        return False
    if query_domain == "general":
        return False
    return confidence < 0.5


def _registry_plan_tool_ids(plan: Any) -> tuple[str, ...]:
    calls = getattr(plan, "tool_calls", ()) or ()
    return tuple(str(getattr(call.tool, "id", "") or "") for call in calls if str(getattr(call.tool, "id", "") or ""))


def _registry_plan_is_sitl_runtime_state(plan: Any) -> bool:
    tool_ids = set(_registry_plan_tool_ids(plan))
    if "mds.sitl.instances.read" not in tool_ids:
        return False
    selection_source = str(getattr(plan, "selection_source", "") or "")
    if selection_source == "sitl_topic_followup_rules":
        return True
    pure_sitl_runtime_ids = {
        "mds.sitl.host.read",
        "mds.sitl.instances.read",
        "mds.sitl.policy.read",
    }
    return bool(tool_ids) and tool_ids.issubset(pure_sitl_runtime_ids)


def _has_local_sitl_runtime_registry_plan(
    message: str,
    *,
    conversation_topic: str | None,
    local_intent: str | None,
) -> bool:
    try:
        plan = plan_registry_read_tool_calls(
            message,
            allowed_tools=list_policy_allowed_read_only_tools(channel="agent"),
            conversation_topic=conversation_topic,
            local_intent=local_intent,
        )
    except Exception:
        return False
    return _registry_plan_is_sitl_runtime_state(plan)


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
    if route == "read_only":
        if not _semantic_rewrite_read_only_needs_provider(turn_intent):
            return False
    elif route == "action_draft":
        pass
    elif route == "provider_or_registry":
        # This is precisely where semantic interpretation adds value: unknown
        # language, typos, and domain shorthand must not be forced through local
        # word lists before the configured model gets a chance to understand them.
        pass
    else:
        return False
    read_plan = getattr(turn_intent, "read_only_plan", None)
    if _has_local_sitl_runtime_registry_plan(
        str(getattr(turn_intent, "routing_message", "") or ""),
        conversation_topic=str(getattr(turn_intent, "conversation_topic", "") or ""),
        local_intent=str(getattr(read_plan, "intent", "") or ""),
    ):
        return False
    if not _has_external_assistant_provider_auth(request):
        return False
    if sensitive_input_matches(assistant_config, original_message):
        return False
    return True


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


def _semantic_rewrite_draft_facts(draft: ActionDraft) -> tuple[tuple[str, str], ...]:
    """Return typed facts already proven by the local parser, in execution order."""

    facts: list[tuple[str, str]] = []

    def append_flight_payload(payload: Mapping[str, Any]) -> None:
        try:
            mission_type = int(payload.get("mission_type"))
        except (TypeError, ValueError):
            mission_type = 0
        if mission_type > 0:
            facts.append(("mission_type", str(mission_type)))
        altitude = payload.get("takeoff_altitude")
        if isinstance(altitude, (int, float)) and not isinstance(altitude, bool):
            facts.append(("takeoff_altitude", f"{float(altitude):g}"))
        precision_move = payload.get("precision_move")
        translation = precision_move.get("translation_m") if isinstance(precision_move, Mapping) else None
        if isinstance(translation, Mapping):
            for axis in ("north", "east", "up"):
                value = translation.get(axis)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    facts.append((f"translation_{axis}", f"{float(value):g}"))
        yaw = precision_move.get("yaw") if isinstance(precision_move, Mapping) else None
        if isinstance(yaw, Mapping):
            mode = str(yaw.get("mode") or "").strip()
            if mode:
                facts.append(("yaw_mode", mode))
            degrees = yaw.get("degrees")
            if isinstance(degrees, (int, float)) and not isinstance(degrees, bool):
                facts.append(("yaw_degrees", f"{float(degrees):g}"))

    if isinstance(draft, FlightActionDraft):
        append_flight_payload(draft.command_payload)
        for target in draft.target_drone_ids:
            facts.append(("target", str(target)))
        for item in draft.post_actions:
            if str(item.get("type") or "").strip().casefold() == "delay":
                delay = item.get("delay_seconds")
                if isinstance(delay, (int, float)) and not isinstance(delay, bool):
                    facts.append(("delay", f"{float(delay):g}"))
                continue
            arguments = item.get("arguments") if isinstance(item.get("arguments"), Mapping) else {}
            append_flight_payload(arguments)
        return tuple(facts)

    facts.append(("tool_id", draft.tool_id))
    facts.append(
        (
            "arguments",
            json.dumps(dict(draft.arguments), sort_keys=True, separators=(",", ":"), default=str),
        )
    )
    return tuple(facts)


def _semantic_rewrite_preserves_draft_facts(initial: ActionDraft, rewritten: ActionDraft) -> bool:
    """Preserve a complete typed plan exactly; only fill incomplete drafts."""

    expected = _semantic_rewrite_draft_facts(initial)
    actual = _semantic_rewrite_draft_facts(rewritten)
    if initial.ready:
        return expected == actual
    if not expected:
        return True
    cursor = 0
    for fact in actual:
        if fact == expected[cursor]:
            cursor += 1
            if cursor == len(expected):
                return True
    return False


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
    assistant_turn_tasks: set[asyncio.Task[Any]] = set()
    action_run_tasks: set[asyncio.Task[Any]] = set()
    configured_action_run_store = getattr(deps, "simurgh_action_run_store", None)
    action_runs = (
        configured_action_run_store
        if isinstance(configured_action_run_store, ActionRunStore)
        else ActionRunStore.from_env()
    )

    def retain_assistant_turn_task(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        """Keep a turn alive when an SSE subscriber disconnects mid-operation."""

        assistant_turn_tasks.add(task)
        task.add_done_callback(assistant_turn_tasks.discard)
        return task

    def retain_action_run_task(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        """Keep approved execution alive independently of an HTTP/SSE subscriber."""

        action_run_tasks.add(task)
        task.add_done_callback(action_run_tasks.discard)
        return task

    def require_action_run_access(request: Request, run_id: str) -> ActionRunSnapshot:
        try:
            run = action_runs.require(run_id)
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
        runs = action_runs.list_runs(
            actor=actor_filter,
            session_id=session_id,
            active_only=active_only,
            limit=limit,
        )
        return {"runs": [run.public_payload() for run in runs]}

    @router.get("/api/v1/simurgh/action-runs/{run_id}")
    async def get_simurgh_action_run(request: Request, run_id: str):
        return require_action_run_access(request, run_id).public_payload()

    @router.get("/api/v1/simurgh/action-runs/{run_id}/events")
    async def list_simurgh_action_run_events(
        request: Request,
        run_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        require_action_run_access(request, run_id)
        return {
            "run_id": run_id,
            "events": [event.public_payload() for event in action_runs.list_events(run_id, after_id=after, limit=limit)],
        }

    @router.get("/api/v1/simurgh/action-runs/{run_id}/events/stream")
    async def stream_simurgh_action_run_events(
        request: Request,
        run_id: str,
        after: int = Query(default=0, ge=0),
    ):
        require_action_run_access(request, run_id)
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
                events = action_runs.list_events(run_id, after_id=cursor, limit=200)
                for event in events:
                    cursor = event.id
                    yield _action_run_sse_event(event.id, event.event_type, event.public_payload())
                run = action_runs.require(run_id)
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
        run = require_action_run_access(request, run_id)
        actor = _resolve_actor(request, control.actor)
        if actor != run.actor:
            raise HTTPException(status_code=403, detail="action run belongs to a different operator")
        try:
            updated = action_runs.request_control(
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

    def _stored_last_submitted_action(session_id: str | None) -> dict[str, Any]:
        if not session_id:
            return {}
        try:
            context = sessions.get_private_context(session_id)
        except KeyError:
            return {}
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
        if run_id:
            try:
                run = action_runs.require(run_id)
            except KeyError:
                pass
            else:
                payload.update(
                    {
                        "action_run_id": run.run_id,
                        "action_run_state": run.state,
                        "action_run_summary": run.summary,
                        "action_run_result": dict(run.result),
                    }
                )
        return payload

    def _previous_action_with_live_single_target(
        http_request: Request,
        previous_action: Mapping[str, Any],
    ) -> dict[str, Any]:
        base = dict(previous_action or {})
        if _action_context_target_ids(base):
            return base
        live_target = _single_live_action_target_context(http_request)
        if not live_target:
            return base
        return {**base, **live_target}

    def _action_context_target_ids(action_context: Mapping[str, Any]) -> list[str]:
        raw_targets = (
            action_context.get("target_drone_ids")
            or action_context.get("target_drones")
            or action_context.get("inferred_target_drone_ids")
        )
        if not isinstance(raw_targets, (list, tuple)):
            return []
        values: list[str] = []
        for item in raw_targets:
            value = str(item).strip()
            if value and value not in values:
                values.append(value)
        return values

    def _single_live_action_target_context(http_request: Request) -> dict[str, Any]:
        """Return one target from live runtime evidence, never configured inventory alone."""

        request_deps = _request_scoped_deps(deps, http_request)
        candidates: dict[str, set[str]] = {}

        def add_candidate(value: Any, source: str) -> None:
            target = _coerce_int_like_text(value)
            if target:
                candidates.setdefault(target, set()).add(source)

        if resolve_runtime_mode().mode == "sitl":
            for target in _active_sitl_instance_target_ids(request_deps):
                add_candidate(target, "single_active_sitl_instance")

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
            if state and state != "running":
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
        if resolve_runtime_mode().mode != "sitl":
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
            return bool(presence.get("fresh"))
        except Exception:
            pass
        if bool(telemetry_row.get("telemetry_available")):
            return True
        if heartbeat_row:
            return True
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

    def _previous_action_summary_content(_question: str, action: Mapping[str, Any], context: Mapping[str, str]) -> str:
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
        assistant_content = str(context.get("last_assistant_content") or "")
        fallback_lines = [
            line.strip()
            for line in assistant_content.splitlines()
            if line.strip().startswith("Monitor:") or line.strip().startswith("Post-action")
        ]

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
        if wait_results:
            completed_waits = sum(str(item.get("status") or "").casefold() == "completed" for item in wait_results)
            lines.append(f"- Wait steps: {completed_waits}/{len(wait_results)} completed")
        if post_results:
            lines.append("- Sequence steps:")
            for item in post_results:
                label = str(item.get("label") or item.get("tool_id") or "post-action").strip()
                status = str(item.get("status") or "unknown").strip()
                summary = str(item.get("summary") or "").strip()
                suffix = f" ({summary})" if summary else ""
                lines.append(f"  - {label}: {status}{suffix}")
        elif fallback_lines:
            lines.append("- Previous action text evidence:")
            lines.extend(f"  - {line}" for line in fallback_lines[:8])
        else:
            lines.append("- No retained post-action result rows are available for this session.")
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
            post_actions = []

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
        action = _stored_last_submitted_action(session.id)
        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "tool",
                "state": "complete",
                "label": "Checked previous action sequence",
                "intent": "action_history_summary",
                "tool_id": ACTION_TOOL_ID,
                "tool_ids": [ACTION_TOOL_ID],
            },
        )
        content = _previous_action_summary_content(turn_request.message, action, context)
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
            tool_id=ACTION_TOOL_ID,
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
                "tool_id": ACTION_TOOL_ID,
                "tool_ids": [ACTION_TOOL_ID],
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
            if (now - session.created_at).total_seconds() > PENDING_ACTION_RECOVERY_SECONDS:
                continue
            draft = _stored_action_draft(session.id)
            if draft is None:
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
        updated = action_runs.request_control(
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
        mission_name = response_payload.get("mission_name") or draft.mission_name
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
        timeout_seconds: float = ACTION_MONITOR_TIMEOUT_SECONDS,
        sequence_id: str = "",
        step_index: int | None = None,
        step_count: int | None = None,
        step_label: str = "",
        step_kind: str = "flight_command",
        mission_name: str = "",
    ) -> dict[str, Any]:
        tracker = request_deps.get_command_tracker()
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        canonical_deadline_loaded = False
        last_status: Mapping[str, Any] | None = None
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
                        deadline = asyncio.get_running_loop().time() + remaining_seconds + ACTION_MONITOR_POLL_SECONDS
                        canonical_deadline_loaded = True
                if _command_monitor_terminal(status):
                    success = _command_monitor_success(status)
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "monitor",
                            "state": "complete" if success else "failed",
                            "label": _sequence_progress_label(
                                "Command completed" if success else "Command reached terminal state",
                                step_label=step_label,
                                step_index=step_index,
                                step_count=step_count,
                                activity="completed" if success else "terminal state",
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
                        "command_status": dict(status),
                    }
            if asyncio.get_running_loop().time() >= deadline:
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
                    "command_status": dict(last_status or {}),
                }
            await asyncio.sleep(ACTION_MONITOR_POLL_SECONDS)

    async def _execute_post_actions(
        execution_context: InternalToolExecutionContext,
        *,
        post_actions: tuple[Mapping[str, Any], ...],
        registry,
        policy,
        request_deps: Any | None = None,
        progress_callback: AssistantProgressCallback | None = None,
        sequence_id: str = "",
        idempotency_scope: str = "",
        initial_step_index: int = 1,
        step_count: int | None = None,
        action_run_id: str = "",
        initial_previous_step_succeeded: bool = True,
    ) -> tuple[Mapping[str, Any], ...]:
        results: list[Mapping[str, Any]] = []
        previous_step_succeeded = initial_previous_step_succeeded
        for index, item in enumerate(post_actions, start=1):
            action_type = str(item.get("type") or "").strip()
            tool_id = str(item.get("tool_id") or "").strip()
            arguments = item.get("arguments") if isinstance(item.get("arguments"), Mapping) else {}
            label = str(item.get("action_label") or tool_id or "post-action")
            step_index = initial_step_index + index
            condition = str(item.get("condition") or "").strip()
            if action_run_id and not await _wait_for_action_run_dispatch(action_run_id):
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
                delay_completed = (
                    await _sleep_action_run_delay(action_run_id, delay_seconds)
                    if action_run_id
                    else await _sleep_post_action_delay(delay_seconds)
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
            current_policy = load_default_policy()
            if tool_id == ACTION_TOOL_ID:
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
                post_tool = registry.get(tool_id)
                post_decision = current_policy.evaluate_tool(post_tool, channel="agent", approved=True)
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
                command_payload = {
                    **dict(arguments),
                    "idempotency_key": f"simurgh:{idempotency_scope or sequence_id}:step:{step_index}",
                }
                try:
                    command = SubmitCommandRequest.model_validate(command_payload)
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
                    if command_id and bool(item.get("monitor_requested")):
                        monitor_status = await _monitor_command_until_terminal(
                            request_deps,
                            command_id,
                            progress_callback=progress_callback,
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=label,
                            step_kind="flight_command",
                            mission_name=str(arguments.get("mission_name") or arguments.get("mission_type") or ""),
                        )
                        final_status = str(monitor_status.get("status") or final_status)
                        summary = _command_monitor_summary(monitor_status.get("command_status")) or summary
                    completion_verification: Mapping[str, Any] | None = None
                    mission_type = _coerce_int_like_text(arguments.get("mission_type"))
                    if (
                        monitor_status is not None
                        and monitor_status.get("success")
                        and mission_type in {"101", "104"}
                    ):
                        completion_verification = await _monitor_targets_disarmed(
                            request_deps,
                            target_drone_ids=tuple(str(item) for item in arguments.get("target_drone_ids") or ()),
                            progress_callback=progress_callback,
                            sequence_id=sequence_id,
                            step_index=step_index,
                            step_count=step_count,
                            step_label=label,
                            command_id=command_id,
                            deadline_epoch_ms=_command_monitor_deadline_epoch_ms(monitor_status),
                        )
                    is_error = bool(monitor_status is not None and not monitor_status.get("success"))
                    if bool(item.get("monitor_requested")) and not command_id:
                        is_error = True
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
                            "completion_verification": dict(completion_verification or {}),
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
            try:
                result = await execute_policy_allowed_guarded_route_tool(
                    execution_context,
                    name=tool_id,
                    arguments=dict(arguments),
                    channel="agent",
                    approved=True,
                    registry=registry,
                    policy=current_policy,
                )
                structured = result.structured_content if isinstance(result.structured_content, Mapping) else {}
                operation_id = structured.get("operation_id") or structured.get("id") or ""
                summary = structured.get("summary") or result.text
                status_value = structured.get("status") or ("error" if result.is_error else "submitted")
                final_status = status_value
                if operation_id:
                    operation_status = await _monitor_sitl_operation(
                        execution_context,
                        operation_id=str(operation_id),
                        progress_callback=progress_callback,
                    )
                    final_status = operation_status.get("status") or final_status
                    summary = operation_status.get("summary") or summary
                is_error = _post_action_status_is_error(final_status, explicit_error=bool(result.is_error))
                results.append(
                    {
                        "label": label,
                        "tool_id": tool_id,
                        "status": str(final_status),
                        "operation_id": str(operation_id),
                        "summary": str(summary)[:500],
                        "is_error": is_error,
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
        return tuple(results)

    async def _monitor_targets_disarmed(
        request_deps: Any,
        *,
        target_drone_ids: tuple[str, ...],
        progress_callback: AssistantProgressCallback | None = None,
        timeout_seconds: float = ACTION_MONITOR_TIMEOUT_SECONDS,
        deadline_epoch_ms: float | None = None,
        sequence_id: str = "",
        step_index: int | None = None,
        step_count: int | None = None,
        step_label: str = "",
        command_id: str = "",
    ) -> dict[str, Any]:
        """Verify the final landed workflow state without redefining command success."""

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
        while True:
            rows = target_rows()
            if rows and all(not bool(row.get("is_armed", row.get("armed", False))) for row in rows):
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "verify",
                        "state": "complete",
                        "label": _sequence_progress_label(
                            "Final disarm state verified",
                            step_label=step_label,
                            step_index=step_index,
                            step_count=step_count,
                            activity="disarmed",
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
                    "summary": "Target telemetry confirms disarmed state after landing/RTL.",
                }
            if asyncio.get_running_loop().time() >= deadline:
                await _emit_assistant_progress(
                    progress_callback,
                    {
                        "stage": "verify",
                        "state": "timeout",
                        "label": _sequence_progress_label(
                            "Final disarm state not confirmed",
                            step_label=step_label,
                            step_index=step_index,
                            step_count=step_count,
                            activity="still armed",
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
                    "summary": "Target remained armed or final telemetry was not confirmed before timeout.",
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

    async def _sleep_post_action_delay(delay_seconds: float) -> None:
        if delay_seconds > 0:
            await _sleep_action_sequence_delay(delay_seconds)

    async def _monitor_sitl_operation(
        execution_target: Request | InternalToolExecutionContext,
        *,
        operation_id: str,
        progress_callback: AssistantProgressCallback | None = None,
        timeout_seconds: float = ACTION_MONITOR_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        execution_context = (
            execution_target
            if isinstance(execution_target, InternalToolExecutionContext)
            else InternalToolExecutionContext.from_request(execution_target)
        )
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        operation_deadline_loaded = False
        last_status: Mapping[str, Any] = {}
        headers: dict[str, str] = {INTERNAL_TOOL_CALL_HEADER: INTERNAL_TOOL_CALL_VALUE}
        transport = httpx.ASGITransport(app=execution_context.app, client=("simurgh-internal", 0))
        async with httpx.AsyncClient(
            transport=transport,
            base_url=execution_context.base_url,
            timeout=10.0,
        ) as client:
            while True:
                response = await client.get(f"/api/v1/system/sitl/operations/{operation_id}", headers=headers)
                try:
                    structured = response.json()
                except ValueError:
                    structured = {"status": "error", "summary": response.text}
                if response.status_code >= 400:
                    summary = (
                        structured.get("detail")
                        or structured.get("summary")
                        or f"SITL operation status endpoint returned HTTP {response.status_code}."
                    )
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "monitor",
                            "state": "failed",
                            "label": f"SITL operation {operation_id[:8]} status unavailable",
                            "operation_id": operation_id,
                            "summary": str(summary),
                        },
                    )
                    return {
                        "operation_id": operation_id,
                        "status": "failed",
                        "summary": str(summary),
                        "http_status": response.status_code,
                    }
                if isinstance(structured, Mapping):
                    last_status = structured
                    if not operation_deadline_loaded:
                        metadata = structured.get("metadata") if isinstance(structured.get("metadata"), Mapping) else {}
                        try:
                            operation_timeout = float(metadata.get("monitor_timeout_seconds"))
                        except (TypeError, ValueError):
                            operation_timeout = 0.0
                        if operation_timeout > 0:
                            deadline = asyncio.get_running_loop().time() + operation_timeout
                            operation_deadline_loaded = True
                    if _operation_terminal(structured):
                        await _emit_assistant_progress(
                            progress_callback,
                            {
                                "stage": "monitor",
                                "state": "complete" if str(structured.get("status")).lower() in {"completed", "succeeded"} else "failed",
                                "label": f"SITL operation {operation_id[:8]} finished",
                                "operation_id": operation_id,
                            },
                        )
                        return dict(structured)
                if asyncio.get_running_loop().time() >= deadline:
                    return {
                        "operation_id": operation_id,
                        "status": "timeout",
                        "summary": "SITL operation did not reach terminal status during the monitor window.",
                        "last_status": dict(last_status),
                    }
                await asyncio.sleep(ACTION_MONITOR_POLL_SECONDS)

    async def _wait_for_action_run_dispatch(run_id: str) -> bool:
        """Wait at a safe step boundary; return false when remaining work is cancelled."""

        while True:
            run = action_runs.require(run_id)
            if run.state in {"cancel_requested", "cancelled"} or run.control_state == "cancel_requested":
                return False
            if run.state in {"pause_requested", "paused"} or run.control_state == "pause_requested":
                if run.state != "paused":
                    action_runs.append_event(
                        run_id,
                        event_type="run_paused",
                        payload={
                            "stage": "action",
                            "state": "paused",
                            "label": "Action run paused before the next step",
                        },
                        state="paused",
                        summary="Paused before dispatching the next step.",
                    )
                await asyncio.sleep(0.25)
                continue
            return True

    async def _sleep_action_run_delay(run_id: str, delay_seconds: float) -> bool:
        """Sleep a sequence delay while honoring cancel/pause at a safe boundary."""

        remaining = delay_seconds
        while remaining > 0:
            if not await _wait_for_action_run_dispatch(run_id):
                return False
            sleep_for = min(0.25, remaining)
            await _sleep_action_sequence_delay(sleep_for)
            remaining = max(0.0, remaining - sleep_for)
        return True

    async def _execute_action_draft_now(
        execution_context: InternalToolExecutionContext,
        *,
        draft: ActionDraft,
        registry: Any,
        policy: Any,
        request_deps: Any,
        progress_callback: AssistantProgressCallback | None = None,
        run_id: str = "",
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
                action_response = await submit_tracked_command(request_deps, command)
                action_execution = "submitted"
                response_payload = (
                    action_response.model_dump(mode="json")
                    if hasattr(action_response, "model_dump")
                    else dict(action_response or {})
                )
                command_id = str(response_payload.get("command_id") or "").strip()
                if command_id and draft.monitor_requested:
                    sequence_step_count = 1 + len(draft.post_actions) if draft.post_actions else None
                    monitor_result = await _monitor_command_until_terminal(
                        request_deps,
                        command_id,
                        progress_callback=progress_callback,
                        sequence_id=run_id or (draft.draft_id if draft.post_actions else ""),
                        step_index=1 if draft.post_actions else None,
                        step_count=sequence_step_count,
                        step_label=_action_draft_label(draft) if draft.post_actions else "",
                        step_kind="flight_command",
                        mission_name=draft.mission_name,
                    )
                    final_state_ready = True
                    if monitor_result.get("success") and draft.mission_type in {101, 104}:
                        completion_verification = await _monitor_targets_disarmed(
                            request_deps,
                            target_drone_ids=draft.target_drone_ids,
                            progress_callback=progress_callback,
                            sequence_id=run_id or (draft.draft_id if draft.post_actions else ""),
                            step_index=1 if draft.post_actions else None,
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
                    if draft.post_actions and final_state_ready:
                        post_action_results = await _execute_post_actions(
                            execution_context,
                            post_actions=draft.post_actions,
                            registry=registry,
                            policy=policy,
                            request_deps=request_deps,
                            progress_callback=progress_callback,
                            sequence_id=run_id or draft.draft_id,
                            idempotency_scope=draft.draft_id,
                            initial_step_index=1,
                            step_count=sequence_step_count,
                            action_run_id=run_id,
                            initial_previous_step_succeeded=bool(monitor_result.get("success")),
                        )
            elif isinstance(draft, RegistryActionDraft):
                result = await execute_policy_allowed_guarded_route_tool(
                    execution_context,
                    name=draft.tool_id,
                    arguments=dict(draft.arguments),
                    channel="agent",
                    approved=True,
                    registry=registry,
                    policy=policy,
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
                    if operation_id and draft.monitor_requested:
                        monitor_result = await _monitor_sitl_operation(
                            execution_context,
                            operation_id=operation_id,
                            progress_callback=progress_callback,
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
        return 1 + len(draft.post_actions) if isinstance(draft, FlightActionDraft) else 1

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
        actor: str,
        session_id: str,
        draft: ActionDraft,
        request_deps: Any,
    ) -> None:
        """Execute a confirmed run independently from its chat transport."""

        try:
            action_runs.append_event(
                run_id,
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

            if not await _wait_for_action_run_dispatch(run_id):
                summary = "Action run cancelled before the first step was dispatched."
                action_runs.append_event(
                    run_id,
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
            decision = policy.evaluate_tool(tool, channel="agent", approved=True)
            if decision.status is not PolicyDecisionStatus.ALLOW:
                summary = "; ".join(decision.reasons) or "Current Simurgh policy blocked the approved action."
                action_runs.append_event(
                    run_id,
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

            async def progress_callback(payload: dict[str, Any]) -> None:
                try:
                    step_index = int(payload.get("step_index") or 0)
                except (TypeError, ValueError):
                    step_index = 0
                action_runs.append_event(
                    run_id,
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
                request_deps=request_deps,
                progress_callback=progress_callback,
                run_id=run_id,
            )
            action_response = _action_response_payload(outcome.action_response)
            result_payload = {
                "action_execution": outcome.action_execution,
                "action_response": action_response,
                "monitor_result": dict(outcome.monitor_result or {}),
                "post_action_results": [dict(item) for item in outcome.post_action_results],
                "rejection_detail": outcome.rejection_detail,
            }
            run_snapshot = action_runs.require(run_id)
            cancelled = (
                run_snapshot.state == "cancel_requested"
                or any(str(item.get("status") or "") == "cancelled" for item in outcome.post_action_results)
            )
            monitor_status = str((outcome.monitor_result or {}).get("status") or "").strip().casefold()
            monitor_failed = bool(
                isinstance(outcome.monitor_result, Mapping)
                and (
                    outcome.monitor_result.get("success") is False
                    or monitor_status
                    in {
                        "blocked",
                        "cancelled",
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
            post_failed = any(bool(item.get("is_error")) for item in outcome.post_action_results)
            if cancelled:
                final_state = "cancelled"
                summary = "The current step was allowed to finish; remaining steps were cancelled."
            elif outcome.action_execution != "submitted" or monitor_failed or post_failed:
                final_state = "failed"
                summary = outcome.rejection_detail or "The action run stopped before every planned step succeeded."
            else:
                final_state = "succeeded"
                summary = f"Completed {_action_run_total_steps(draft)} of {_action_run_total_steps(draft)} planned steps."
            completed_step = (
                _action_run_total_steps(draft)
                if final_state == "succeeded"
                else action_runs.require(run_id).current_step
            )
            action_runs.append_event(
                run_id,
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
                "post_actions": [dict(item) for item in draft.post_actions]
                if isinstance(draft, FlightActionDraft)
                else [],
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
                action_runs.append_event(
                    run_id,
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
        progress_callback: AssistantProgressCallback | None = None,
    ) -> tuple[str, dict[str, Any], tuple[str, ...]]:
        sitl_lifecycle_context = _should_prepend_sitl_lifecycle_read_only_context(routing_message, action_draft)
        if not sitl_lifecycle_context and not _should_prepend_action_read_only_context(routing_message, read_only_plan):
            return "", {}, ()

        allowed_tools = list_policy_allowed_read_only_tools(channel="agent")
        allowed_by_id = {tool.id: tool for tool in allowed_tools}
        direct_calls: list[RegistryReadCall] = []
        direct_tool_ids = (
            ("mds.sitl.instances.read", "mds.sitl.policy.read")
            if sitl_lifecycle_context
            else tuple(str(item) for item in getattr(read_only_plan, "tool_ids", ()) or ())[:4]
        )
        for tool_id in direct_tool_ids:
            tool = allowed_by_id.get(tool_id)
            if tool is None:
                continue
            schema = tool.input_schema if isinstance(tool.input_schema, Mapping) else {}
            required = schema.get("required") if isinstance(schema, Mapping) else ()
            if required:
                continue
            direct_calls.append(RegistryReadCall(tool=tool, arguments={}))
        direct_label = "read-only current state"
        direct_ids = [call.tool.id for call in direct_calls]
        if "mds.config.fleet.read" in direct_ids and "mds.sitl.instances.read" in direct_ids:
            direct_label = "configured fleet and SITL runtime state"
        elif "mds.sitl.instances.read" in direct_ids:
            direct_label = "SITL runtime state"
        elif "mds.config.fleet.read" in direct_ids:
            direct_label = "configured fleet"
        registry_plan = (
            RegistryReadPlan(
                label=direct_label,
                domain=str(getattr(read_only_plan, "query_domain", "") or getattr(read_only_plan, "topic", "") or "runtime"),
                tool_calls=tuple(direct_calls),
                selection_source="turn_read_only_plan",
            )
            if direct_calls
            else None
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
                previous_action=_stored_last_submitted_action(session.id),
            )
        if draft is None:
            draft = build_sitl_reconcile_action_draft(
                turn_request.message,
                draft_id=f"act-{uuid.uuid4().hex[:8]}",
                conversation_topic=_session_conversation_topic(session),
            )
        if draft is None:
            raise AgentRuntimeError("Simurgh could not build a guarded action draft")

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
        approved = confirmed or (not policy.always_confirm_before_action)
        decision = policy.evaluate_tool(tool, channel="agent", approved=approved)
        policy_reasons = tuple(decision.reasons)
        sequence_validation_error = (
            _post_action_sequence_validation_error(draft.post_actions)
            if isinstance(draft, FlightActionDraft)
            else ""
        )
        if not draft.ready:
            action_execution = "missing_arguments"
        elif sequence_validation_error:
            action_execution = "validation_rejected"
            rejection_detail = sequence_validation_error
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
            action_run_snapshot, action_run_created = action_runs.create_or_get(
                actor=actor,
                session_id=session.id,
                draft_id=draft.draft_id,
                plan_hash=plan_hash,
                plan=plan_payload,
                total_steps=_action_run_total_steps(draft),
            )
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
        await _emit_assistant_progress(
            progress_callback,
            _action_progress_payload(
                stage="safety" if action_execution != "submitted" else "action",
                state=submitted_progress_state if action_execution == "submitted" else "complete",
                label={
                    "missing_arguments": "Action draft needs more details",
                    "awaiting_confirmation": "Waiting for operator confirmation",
                    "blocked_by_circuit_breaker": "Circuit breaker stopped final execution",
                    "policy_denied": "Policy denied action execution",
                    "validation_rejected": "GCS rejected action before dispatch",
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
                "action_run": action_run_snapshot.public_payload() if action_run_snapshot is not None else {},
                "policy_decision": decision.status.value,
                "policy_reasons": list(policy_reasons),
                "circuit_breaker_layer": (
                    "final-action layer; command was stopped after planning/approval"
                    if action_execution == "blocked_by_circuit_breaker"
                    else "final-action layer; command path not reached"
                    if action_execution in {"awaiting_confirmation", "missing_arguments", "policy_denied"}
                    else "final-action layer; circuit breaker was off and canonical GCS command validation handled execution"
                ),
            },
        )
        if action_run_should_start and action_run_snapshot is not None:
            execution_context = InternalToolExecutionContext.from_request(http_request)
            action_request_deps = _request_scoped_deps(deps, http_request)
            retain_action_run_task(
                asyncio.create_task(
                    _run_action_run(
                        execution_context,
                        run_id=action_run_snapshot.run_id,
                        actor=actor,
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
            composition = compose_read_only_tool_turn_with_provider(
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
                "turn_intent": dict(turn_intent_metadata or {}),
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
        turn_intent_metadata: Mapping[str, Any] | None = None,
        progress_callback: AssistantProgressCallback | None = None,
    ) -> AssistantTurnRecord | None:
        policy = load_default_policy()
        if not policy.agent_enabled:
            raise PermissionError("Simurgh agent runtime is disabled")
        session = _require_or_create_assistant_session(policy=policy, actor=actor, turn_request=turn_request)
        request_deps = _request_scoped_deps(deps, http_request)
        conversation_topic = _session_conversation_topic(session)
        answer = await asyncio.to_thread(
            answer_mds_read_only_question,
            routing_message,
            deps=request_deps,
            conversation_topic=conversation_topic,
        )
        if answer is None:
            return None

        await _emit_assistant_progress(
            progress_callback,
            {
                "stage": "tool",
                "state": "complete",
                "label": "Evidence ready",
                "intent": answer.intent,
                "tool_id": answer.tool_ids[0] if answer.tool_ids else None,
                "tool_ids": list(answer.tool_ids),
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
        evidence = answer.evidence_metadata()
        turn = AssistantTurnResult(
            id=f"turn-{uuid.uuid4().hex}",
            created_at=utc_now().isoformat(),
            provider=READ_TOOL_PROVIDER,
            model=READ_TOOL_MODEL,
            adapter_version=READ_TOOL_ADAPTER_VERSION,
            content=answer.content,
            context_documents=tuple(context_documents),
            blocked_intents=(),
            safety_notes=answer.safety_notes,
        )
        next_topic = str(read_only_plan.topic or read_only_plan.query_domain or answer.intent or "").strip()
        session = sessions.update_metadata(
            session.id,
            {
                "last_domain": next_topic,
                "last_intent": answer.intent,
                "last_response_mode": answer.response_mode,
            },
        )
        sessions.update_private_context(
            session.id,
            {
                "last_assistant_content": turn.content,
                "last_assistant_provider": turn.provider,
                "last_assistant_model": turn.model,
                "last_domain": next_topic,
                "last_intent": answer.intent,
                "last_response_mode": answer.response_mode,
                "last_user_message": turn_request.message,
                "last_routing_message": normalize_operator_query_text(turn_request.message),
                "last_tool_intent": answer.intent,
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
            tool_id=answer.tool_ids[0] if answer.tool_ids else None,
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
                "tool_intent": answer.intent,
                "tool_id": answer.tool_ids[0] if answer.tool_ids else None,
                "tool_ids": list(answer.tool_ids),
                "response_mode": answer.response_mode,
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
            assistant_config = load_default_assistant_config()
            conversation_topic = None
            previous_context: dict[str, str] = {}
            if turn_request.session_id:
                try:
                    existing_session = sessions.require(turn_request.session_id)
                    conversation_topic = str(existing_session.metadata.get("last_domain") or "")
                    previous_context = sessions.get_private_context(turn_request.session_id)
                    if not conversation_topic:
                        conversation_topic = str(previous_context.get("last_domain") or "")
                except KeyError:
                    conversation_topic = None
            previous_action = _stored_last_submitted_action(turn_request.session_id)
            previous_action_for_routing = _previous_action_with_live_single_target(http_request, previous_action)
            previous_action_request_message = _stored_last_action_request_message(turn_request.session_id)
            turn_intent = build_turn_intent_frame(
                turn_request.message,
                conversation_topic=conversation_topic,
                previous_action=previous_action_for_routing,
                previous_action_request_message=previous_action_request_message,
            )
            semantic_rewrite = None
            semantic_rewrite_error = ""
            semantic_action_plan_error = ""
            semantic_action_interpretation_failed = False
            if _semantic_rewrite_is_safe_to_try(
                assistant_config=assistant_config,
                request=http_request,
                original_message=turn_request.message,
                turn_intent=turn_intent,
            ):
                try:
                    semantic_registry = load_default_tool_registry()
                    semantic_action_contracts = _provider_action_tool_contracts(semantic_registry)
                    semantic_rewrite = rewrite_operator_message_with_provider(
                        config=assistant_config,
                        message=turn_request.message,
                        conversation_topic=conversation_topic or "",
                        runtime_mode=resolve_runtime_mode().mode,
                        previous_action_summary=_semantic_rewrite_previous_action_summary(previous_action_for_routing),
                        clarification_context=_semantic_rewrite_clarification_context(previous_context),
                        action_tool_contracts=semantic_action_contracts,
                    )
                except AgentRuntimeError as exc:
                    semantic_rewrite_error = str(exc)[:180]
                    semantic_action_interpretation_failed = turn_intent.is_action_route
                if semantic_rewrite is not None:
                    rewritten_intent = build_turn_intent_frame(
                        turn_request.message,
                        conversation_topic=conversation_topic,
                        previous_action=previous_action_for_routing,
                        previous_action_request_message=previous_action_request_message,
                        semantic_routing_message=semantic_rewrite.normalized_message,
                    )
                    semantic_control_route = SEMANTIC_REWRITE_ACTION_CONTROL_ROUTES.get(
                        semantic_rewrite.route_hint
                    )
                    if semantic_control_route and semantic_rewrite.usable_for_routing:
                        is_confirmation = semantic_control_route == "action_confirmation"
                        turn_intent = replace(
                            rewritten_intent,
                            confirmation_message=is_confirmation,
                            rejection_message=not is_confirmation,
                            explicit_action_draft_id=(
                                rewritten_intent.explicit_action_draft_id
                                or turn_intent.explicit_action_draft_id
                            ),
                            route=semantic_control_route,
                            confidence=max(0.62, float(semantic_rewrite.confidence)),
                            reasons=(f"provider-{semantic_rewrite.route_hint}",),
                        )
                    elif (
                        getattr(semantic_rewrite, "action_plan", None) is not None
                        and semantic_rewrite.usable_for_routing
                    ):
                        materialized = build_action_draft_from_provider_plan(
                            semantic_rewrite.action_plan,
                            draft_id=f"act-{uuid.uuid4().hex[:8]}",
                            previous_action=previous_action_for_routing,
                            tool_contracts=_provider_action_tool_contract_map(semantic_action_contracts),
                        )
                        if materialized.accepted:
                            action_draft = materialized.draft
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
                                confirmation_message=False,
                                rejection_message=False,
                                explicit_action_draft_id="",
                                action=rewritten_action,
                                route="action_draft",
                                confidence=max(0.62, float(semantic_rewrite.confidence)),
                                reasons=("provider-structured-action-plan",),
                            )
                        else:
                            semantic_action_plan_error = ":".join(
                                item
                                for item in (materialized.reason, materialized.field_path)
                                if item
                            )[:180]
                            semantic_rewrite = replace(
                                semantic_rewrite,
                                needs_clarification=True,
                                clarification_question=(
                                    "I could not map the complete request to the available controls. "
                                    "Please restate the target and ordered steps."
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

            def turn_intent_metadata(action_draft_override: ActionDraft | None = None) -> dict[str, Any]:
                metadata = turn_intent.public_metadata()
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
                return metadata

            routing_message = turn_intent.routing_message
            previous_evidence_followup = bool(
                previous_context.get("last_assistant_content")
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
            actor = _resolve_actor(http_request, turn_request.actor)
            if semantic_action_interpretation_failed:
                record = await _create_semantic_clarification_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    question=(
                        "I could not safely interpret the complete action sequence. "
                        "Please try the request once more."
                    ),
                    semantic_rewrite=semantic_rewrite,
                    turn_intent_metadata=turn_intent_metadata(),
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(record=record, message=turn_request.message)
                return record, history_record
            if (
                semantic_rewrite is not None
                and bool(getattr(semantic_rewrite, "needs_clarification", False))
                and str(getattr(semantic_rewrite, "clarification_question", "") or "").strip()
            ):
                record = await _create_semantic_clarification_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    question=str(semantic_rewrite.clarification_question),
                    semantic_rewrite=semantic_rewrite,
                    turn_intent_metadata=turn_intent_metadata(),
                    progress_callback=progress_callback,
                )
                history_record = history.append_turn(record=record, message=turn_request.message)
                return record, history_record
            local_intent = read_only_plan.intent
            stored_draft = _stored_action_draft(turn_request.session_id)
            rejection_message = turn_intent.rejection_message
            if rejection_message:
                if stored_draft and is_action_rejection_message(
                    routing_message,
                    draft_id=stored_draft.draft_id,
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
                explicit_draft_id = turn_intent.explicit_action_draft_id
                pending_matches = _recent_pending_action_drafts_for_actor(
                    actor=actor,
                    draft_id=explicit_draft_id,
                )
                if len(pending_matches) == 1:
                    recovered_session, recovered_draft = pending_matches[0]
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
                    history_record = history.append_turn(record=record, message=turn_request.message)
                    return record, history_record
                active_runs = action_runs.list_runs(
                    actor=actor,
                    session_id=turn_request.session_id or None,
                    active_only=True,
                    limit=20,
                )
                if not active_runs and turn_request.session_id:
                    active_runs = action_runs.list_runs(
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
                if stored_draft and is_action_confirmation_message(
                    routing_message,
                    draft_id=stored_draft.draft_id,
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

                explicit_draft_id = turn_intent.explicit_action_draft_id
                pending_matches = _recent_pending_action_drafts_for_actor(
                    actor=actor,
                    draft_id=explicit_draft_id,
                )
                if len(pending_matches) == 1:
                    recovered_session, recovered_draft = pending_matches[0]
                    await _emit_assistant_progress(
                        progress_callback,
                        {
                            "stage": "safety",
                            "state": "complete",
                            "label": "Recovered pending action",
                            "intent": _action_draft_intent(recovered_draft),
                            "tool_id": _action_draft_tool_id(recovered_draft),
                            "tool_ids": [_action_draft_tool_id(recovered_draft)],
                            "draft_id": recovered_draft.draft_id,
                        },
                    )
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
            safe_read_only_blocked_term = is_safe_blocked_term_read_only_intent(routing_message, local_intent)
            if blocked_matches and safe_read_only_blocked_term:
                blocked_matches = ()
            effective_action_request = (
                _turn_request_with_message(turn_request, message=turn_intent.action.request_message)
                if turn_intent.action.replayed_previous_request
                else turn_request
            )
            if _looks_like_previous_action_result_question(routing_message) and stored_draft:
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
            if _looks_like_previous_action_result_question(routing_message) and _stored_last_submitted_action(turn_request.session_id):
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
            if not previous_evidence_followup and not blocked_matches and not sensitive_matches:
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
                        provider_auth_allowed and not _registry_plan_is_sitl_runtime_state(registry_plan)
                    ),
                    turn_intent_metadata=turn_intent_metadata(),
                    progress_callback=progress_callback,
                )
            else:
                record = None
                prefer_local_context_answer = (
                    local_intent in {"fleet_connectivity", "command_summary"}
                    and conversation_topic in {"flight", "sitl", "fleet"}
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
                        turn_intent_metadata=turn_intent_metadata(),
                        progress_callback=progress_callback,
                    )
                if record is None:
                    request_deps = _request_scoped_deps(deps, http_request)
                    record = create_assistant_turn(
                        sessions=sessions,
                        audit=audit,
                        actor=actor,
                        message=turn_request.message,
                        deps=request_deps,
                        session_id=turn_request.session_id,
                        mode=turn_request.mode,
                        context_resource_ids=_bounded_context_resource_ids(turn_request.context_resource_ids),
                        metadata=_bounded_metadata(
                            {
                                **dict(turn_request.metadata or {}),
                                "turn_intent": turn_intent_metadata(),
                            }
                        ),
                        allow_provider_for_local_tools=(local_only_turn or previous_evidence_followup) and provider_auth_allowed,
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

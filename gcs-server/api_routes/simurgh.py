"""Read-only Simurgh Operator GCS routes."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from src.settings.runtime import resolve_runtime_mode
from agent_runtime.tool_executor import (
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
from agent_runtime.mds_read_tools import (
    apply_runtime_settings,
    build_provider_credentials_payload,
    build_runtime_settings_payload,
    delete_provider_credentials,
    update_provider_credentials,
)
from agent_runtime.language import detect_language_profile
from agent_runtime.models import AgentSession, AuditEvent, ContextResource, ToolDefinition, stable_payload_hash, utc_now
from agent_runtime.query_adaptation import adapt_operator_query, normalize_operator_query_text
from agent_runtime.registry_chat import (
    REGISTRY_READ_EXECUTION_INTENT,
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
ACTION_SEQUENCE_MAX_DELAY_SECONDS = 30.0
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
QUERY_RESPONSE_MODE_PROGRESS_LABELS = {
    "capability": "capability answer",
    "clarify": "clarification",
    "compare": "comparison",
    "interpret": "explanation",
    "status": "status check",
    "workflow": "workflow guidance",
}
SEMANTIC_REWRITE_TERMINAL_ROUTES = {
    "action_draft",
    "action_confirmation",
    "action_rejection",
}
SEMANTIC_REWRITE_ACTION_HINTS = {
    "draft_sitl_lifecycle_action",
    "draft_flight_action",
    "confirm_pending_action",
    "reject_pending_action",
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
        safety["action_draft"] = action_draft
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


def _submitted_action_progress_outcome(
    draft: ActionDraft,
    *,
    monitor_result: Mapping[str, Any] | None = None,
    post_action_results: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, str]:
    if not isinstance(draft, FlightActionDraft) or not draft.post_actions:
        return "complete", "GCS accepted action submission"
    if not monitor_result:
        return "requested", "GCS accepted command sequence"
    if monitor_result.get("timed_out"):
        return "timeout", "Command sequence monitoring timed out"
    if not monitor_result.get("success"):
        return "failed", "Command sequence stopped after primary command"

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


def _json_block(payload: Mapping[str, Any]) -> str:
    return "```json\n" + json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n```"


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
    elif route == "provider_or_registry":
        query_plan = getattr(turn_intent, "query_plan", None)
        query_domain = str(getattr(query_plan, "domain", "") or "")
        if query_domain == "general":
            return False
    else:
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
    """Create the non-executing Simurgh GCS metadata router."""

    router = APIRouter(tags=["Simurgh Operator"])
    sessions = AgentSessionStore()
    audit = InMemoryAuditSink()
    history = AssistantHistoryStore.from_env(load_on_init=False)
    mcp_resources = SimurghMcpResourceProvider(sessions=sessions, audit=audit)

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
        raw_action = context.get("last_submitted_action")
        if not raw_action:
            return {}
        try:
            payload = json.loads(raw_action)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

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

    def _previous_action_summary_content(question: str, action: Mapping[str, Any], context: Mapping[str, str]) -> str:
        if not action:
            return (
                "I do not have a retained submitted-action record for this Simurgh session, so I cannot prove whether the prior sequence included a wait step.\n\n"
                "No new action was executed."
            )
        action_type = str(action.get("action_type") or "action").strip()
        mission = str(action.get("mission_name") or action.get("action_label") or action.get("tool_id") or action_type).strip()
        command_id = str(action.get("command_id") or action.get("operation_id") or "").strip()
        targets = action.get("target_drone_ids")
        target_label = ", ".join(str(item) for item in targets or [] if str(item).strip()) or "-"
        monitor = action.get("monitor_result") if isinstance(action.get("monitor_result"), Mapping) else {}
        post_results = [dict(item) for item in action.get("post_action_results") or [] if isinstance(item, Mapping)]
        assistant_content = str(context.get("last_assistant_content") or "")
        fallback_lines = [
            line.strip()
            for line in assistant_content.splitlines()
            if line.strip().startswith("Monitor:") or line.strip().startswith("Post-action")
        ]

        normalized_question = " ".join(str(question or "").casefold().split())
        wait_results = [
            item
            for item in post_results
            if str(item.get("type") or "").lower() == "delay" or "wait" in str(item.get("label") or "").casefold()
        ]
        if "wait" in normalized_question or "delay" in normalized_question or "skipped" in normalized_question:
            if wait_results:
                lead = "Yes — the retained Simurgh action record shows the wait step was executed."
            else:
                lead = "I do not see a retained wait/delay step in the last submitted action record."
        else:
            lead = "Here is the retained Simurgh action record for the last submitted sequence."

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
        action, context = _last_submitted_action_context(session.id)
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
        policy_reasons: tuple[str, ...] = (),
        command_response: Any | None = None,
        monitor_result: Mapping[str, Any] | None = None,
        post_action_results: tuple[Mapping[str, Any], ...] = (),
        rejection_detail: str = "",
        circuit_breaker_enabled: bool = True,
        always_confirm_before_action: bool = True,
    ) -> str:
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
            return (
                "I can plan this guarded action, but I need one more detail before any execution path exists.\n\n"
                f"Missing: {missing}.\n"
                f"Action detected: {action_label}.\n"
                "No action was executed."
            )
        if action_execution == "awaiting_confirmation":
            cb_state = "ON" if circuit_breaker_enabled else "OFF"
            confirm_line = (
                f"Reply `confirm action {draft.draft_id}` to submit this through the guarded GCS action path."
                if always_confirm_before_action
                else "Confirmation is not required by current policy, but this draft was not auto-executed in chat."
            )
            extra_lines: list[str] = []
            if isinstance(draft, FlightActionDraft) and draft.target_inferred_from:
                extra_lines.append(f"Target inferred from: {draft.target_inferred_from}")
            if isinstance(draft, FlightActionDraft) and draft.monitor_requested:
                extra_lines.append(f"After submission: monitor `{draft.wait_condition or 'command_terminal'}`")
            if isinstance(draft, FlightActionDraft) and draft.post_actions:
                extra_lines.append(
                    "Then, if the wait condition succeeds: "
                    + ", ".join(str(item.get("action_label") or item.get("tool_id") or "post-action") for item in draft.post_actions)
                )
            extra = ("\n".join(extra_lines) + "\n") if extra_lines else ""
            return (
                "I prepared a guarded action draft and stopped at the human confirmation gate.\n\n"
                f"Action: {action_label}\n"
                f"Tool: `{tool_id}`\n"
                f"Target: {target_label}\n"
                f"{extra}"
                f"Draft ID: `{draft.draft_id}`\n\n"
                f"{_json_block(payload)}\n\n"
                f"{confirm_line}\n"
                f"Circuit breaker is {cb_state}. If it is ON when confirmed, the final execution layer will stop the command and I will report exactly what would have been sent.\n"
                "No action was executed."
            )
        if action_execution == "blocked_by_circuit_breaker":
            return (
                "Circuit breaker stopped this at the final execution layer.\n\n"
                f"If the circuit breaker were OFF, I would submit this guarded GCS action for {target_label}:\n\n"
                f"{_json_block(payload)}\n\n"
                "No action was executed."
            )
        if action_execution == "policy_denied":
            reasons = "; ".join(policy_reasons) or "policy denied this action"
            return (
                "I prepared the action draft, but policy denied execution before command submission.\n\n"
                f"Reason: {reasons}.\n"
                f"Draft payload:\n\n{_json_block(payload)}\n\n"
                "No action was executed."
            )
        if action_execution == "validation_rejected":
            return (
                "The guarded GCS action path rejected this action before dispatch.\n\n"
                f"Reason: {rejection_detail or 'GCS action validation failed'}.\n"
                f"Draft payload:\n\n{_json_block(payload)}\n\n"
                "No action was accepted."
            )

        response_payload = (
            command_response.model_dump(mode="json")
            if hasattr(command_response, "model_dump")
            else dict(command_response or {})
        )
        if not isinstance(draft, FlightActionDraft):
            operation_id = response_payload.get("operation_id") or response_payload.get("id") or "unknown"
            status = response_payload.get("status") or "submitted"
            summary = response_payload.get("summary") or response_payload.get("message") or action_label
            detail = response_payload.get("detail") or ""
            monitor_lines: list[str] = []
            if monitor_result:
                monitor_status = monitor_result.get("status") or "unknown"
                monitor_summary = monitor_result.get("summary") or monitor_result.get("message") or ""
                monitor_lines.append(f"Monitor: {monitor_status}")
                if monitor_summary:
                    monitor_lines.append(f"Monitor summary: {monitor_summary}")
                if monitor_result.get("timed_out"):
                    monitor_lines.append("Monitor note: timed out before terminal confirmation.")
            monitor_block = ("\n" + "\n".join(monitor_lines) + "\n") if monitor_lines else ""
            track_line = (
                "I monitored this operation in chat until terminal status."
                if monitor_result
                else (
                    f"Follow it in SITL Control with operation ID `{operation_id}`."
                    if operation_id != "unknown"
                    else "Follow it from the matching GCS operation/status view."
                )
            )
            return (
                "Submitted the guarded GCS action.\n\n"
                f"Action: {action_label}\n"
                f"Tool: `{tool_id}`\n"
                f"Operation ID: `{operation_id}`\n"
                f"Status: {status}\n"
                f"Summary: {summary}\n"
                + (f"Detail: {detail}\n" if detail else "")
                + "\n"
                + monitor_block
                + f"{track_line} GCS policy, approval, circuit breaker, and route validation stayed in force."
            )
        command_id = response_payload.get("command_id") or "unknown"
        status = response_payload.get("status") or "submitted"
        mission_name = response_payload.get("mission_name") or draft.mission_name
        target_drones = response_payload.get("target_drones") or list(draft.target_drone_ids)
        summary = response_payload.get("results_summary") or {}
        monitor_lines: list[str] = []
        if monitor_result:
            monitor_status = monitor_result.get("status") or "unknown"
            monitor_lines.append(f"Monitor: {monitor_status}")
            monitor_lines.append(f"Monitor evidence: {_command_monitor_summary(monitor_result.get('command_status'))}")
            if monitor_result.get("timed_out"):
                monitor_lines.append("Monitor note: timed out before terminal confirmation; dependent post-actions were not run.")
        for item in post_action_results:
            label = item.get("label") or item.get("tool_id") or "post-action"
            status_text = item.get("status") or "unknown"
            summary_text = item.get("summary") or ""
            line = f"Post-action `{label}`: {status_text}"
            if summary_text:
                line += f" ({summary_text})"
            monitor_lines.append(line)
        monitor_block = ("\n" + "\n".join(monitor_lines) + "\n") if monitor_lines else ""
        return (
            "Submitted the guarded flight command.\n\n"
            f"Command ID: `{command_id}`\n"
            f"Mission: {mission_name}\n"
            f"Status: {status}\n"
            f"Targets: {_format_drone_targets(tuple(str(item) for item in target_drones))}\n"
            f"Immediate result summary: {json.dumps(summary, sort_keys=True, default=str)}\n\n"
            f"{monitor_block}"
            + (
                "I monitored this command sequence in chat. "
                if monitor_result or post_action_results
                else f"Follow it in Active Commands with command ID `{command_id}`. "
            )
            + "GCS validation, telemetry checks, and command tracking stayed in force."
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
        http_request: Request,
        *,
        post_actions: tuple[Mapping[str, Any], ...],
        registry,
        policy,
        request_deps: Any | None = None,
        progress_callback: AssistantProgressCallback | None = None,
        sequence_id: str = "",
        initial_step_index: int = 1,
        step_count: int | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        results: list[Mapping[str, Any]] = []
        previous_step_succeeded = True
        for index, item in enumerate(post_actions, start=1):
            action_type = str(item.get("type") or "").strip()
            tool_id = str(item.get("tool_id") or "").strip()
            arguments = item.get("arguments") if isinstance(item.get("arguments"), Mapping) else {}
            label = str(item.get("action_label") or tool_id or "post-action")
            step_index = initial_step_index + index
            condition = str(item.get("condition") or "").strip()
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
                delay_seconds = _bounded_post_action_delay_seconds(item.get("delay_seconds"))
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
                await _sleep_post_action_delay(delay_seconds)
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
                    "idempotency_key": f"simurgh:post:{uuid.uuid4().hex[:8]}:{index}",
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
                    is_error = bool(monitor_status is not None and not monitor_status.get("success"))
                    if bool(item.get("monitor_requested")) and not command_id:
                        is_error = True
                    results.append(
                        {
                            "label": label,
                            "tool_id": tool_id,
                            "status": final_status,
                            "command_id": command_id,
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
                continue
            result = await execute_policy_allowed_guarded_route_tool(
                http_request,
                name=tool_id,
                arguments=dict(arguments),
                channel="agent",
                approved=True,
                registry=registry,
                policy=policy,
            )
            structured = result.structured_content if isinstance(result.structured_content, Mapping) else {}
            operation_id = structured.get("operation_id") or structured.get("id") or ""
            summary = structured.get("summary") or result.text
            status_value = structured.get("status") or ("error" if result.is_error else "submitted")
            final_status = status_value
            if operation_id:
                operation_status = await _monitor_sitl_operation(
                    http_request,
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
        return tuple(results)

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

    def _bounded_post_action_delay_seconds(value: Any) -> float:
        try:
            delay_seconds = float(value)
        except (TypeError, ValueError):
            return 0.0
        if delay_seconds <= 0:
            return 0.0
        return min(delay_seconds, ACTION_SEQUENCE_MAX_DELAY_SECONDS)

    async def _sleep_post_action_delay(delay_seconds: float) -> None:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

    async def _monitor_sitl_operation(
        http_request: Request,
        *,
        operation_id: str,
        progress_callback: AssistantProgressCallback | None = None,
        timeout_seconds: float = ACTION_MONITOR_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        last_status: Mapping[str, Any] = {}
        headers: dict[str, str] = {INTERNAL_TOOL_CALL_HEADER: INTERNAL_TOOL_CALL_VALUE}
        transport = httpx.ASGITransport(app=http_request.app, client=("simurgh-internal", 0))
        async with httpx.AsyncClient(
            transport=transport,
            base_url=str(http_request.base_url).rstrip("/"),
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

    async def _create_action_record(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        draft: ActionDraft | None = None,
        confirmed: bool = False,
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
        approved = confirmed or (not policy.always_confirm_before_action)
        decision = policy.evaluate_tool(tool, channel="agent", approved=approved)
        policy_reasons = tuple(decision.reasons)
        if not draft.ready:
            action_execution = "missing_arguments"
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
                    label="Submitting guarded action through GCS",
                    draft=draft,
                    policy_status=decision.status.value,
                ),
            )
            try:
                if isinstance(draft, FlightActionDraft):
                    request_deps = _request_scoped_deps(deps, http_request)
                    command_payload = {
                        **dict(draft.command_payload),
                        "idempotency_key": f"simurgh:{draft.draft_id}",
                    }
                    command = SubmitCommandRequest.model_validate(command_payload)
                    action_response = await submit_tracked_command(
                        request_deps,
                        command,
                    )
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
                            sequence_id=draft.draft_id if draft.post_actions else "",
                            step_index=1 if draft.post_actions else None,
                            step_count=sequence_step_count,
                            step_label=_action_draft_label(draft) if draft.post_actions else "",
                            step_kind="flight_command",
                            mission_name=draft.mission_name,
                        )
                        if draft.post_actions and monitor_result.get("success"):
                            post_action_results = await _execute_post_actions(
                                http_request,
                                post_actions=draft.post_actions,
                                registry=registry,
                                policy=policy,
                                request_deps=request_deps,
                                progress_callback=progress_callback,
                                sequence_id=draft.draft_id,
                                initial_step_index=1,
                                step_count=sequence_step_count,
                            )
                elif isinstance(draft, RegistryActionDraft):
                    result = await execute_policy_allowed_guarded_route_tool(
                        http_request,
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
                        action_execution = "validation_rejected"
                        rejection_detail = result.text
                    else:
                        action_execution = "submitted"
                        structured = result.structured_content if isinstance(result.structured_content, Mapping) else {}
                        operation_id = str(structured.get("operation_id") or structured.get("id") or "").strip()
                        if operation_id and draft.monitor_requested:
                            monitor_result = await _monitor_sitl_operation(
                                http_request,
                                operation_id=operation_id,
                                progress_callback=progress_callback,
                            )
            except HTTPException as exc:
                action_execution = "validation_rejected"
                rejection_detail = str(exc.detail)
            except Exception as exc:
                action_execution = "validation_rejected"
                rejection_detail = str(exc)

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
                    }
                submitted_context = json.dumps(
                    {
                        "action_type": "flight_command",
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
            "last_read_only_evidence": "",
        }
        if action_execution == "awaiting_confirmation":
            private_context_update["last_action_request_message"] = turn_request.message
        if submitted_context:
            private_context_update["last_submitted_action"] = submitted_context
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

    async def _create_assistant_turn_record_for_request(
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
                except KeyError:
                    conversation_topic = None
            previous_action = _stored_last_submitted_action(turn_request.session_id)
            previous_action_request_message = _stored_last_action_request_message(turn_request.session_id)
            turn_intent = build_turn_intent_frame(
                turn_request.message,
                conversation_topic=conversation_topic,
                previous_action=previous_action,
                previous_action_request_message=previous_action_request_message,
            )
            semantic_rewrite = None
            semantic_rewrite_error = ""
            if _semantic_rewrite_is_safe_to_try(
                assistant_config=assistant_config,
                request=http_request,
                original_message=turn_request.message,
                turn_intent=turn_intent,
            ):
                try:
                    semantic_rewrite = rewrite_operator_message_with_provider(
                        config=assistant_config,
                        message=turn_request.message,
                        conversation_topic=conversation_topic or "",
                        runtime_mode=resolve_runtime_mode().mode,
                        previous_action_summary=_semantic_rewrite_previous_action_summary(previous_action),
                    )
                except AgentRuntimeError as exc:
                    semantic_rewrite_error = str(exc)[:180]
                if semantic_rewrite is not None and semantic_rewrite.usable_for_routing:
                    rewritten_intent = build_turn_intent_frame(
                        turn_request.message,
                        conversation_topic=conversation_topic,
                        previous_action=previous_action,
                        previous_action_request_message=previous_action_request_message,
                        semantic_routing_message=semantic_rewrite.normalized_message,
                    )
                    if _should_accept_semantic_rewrite(
                        initial_intent=turn_intent,
                        rewritten_intent=rewritten_intent,
                        semantic_rewrite=semantic_rewrite,
                    ):
                        turn_intent = rewritten_intent

            def turn_intent_metadata() -> dict[str, Any]:
                metadata = turn_intent.public_metadata()
                if semantic_rewrite is not None:
                    metadata["provider_semantic_rewrite"] = semantic_rewrite.public_metadata()
                if semantic_rewrite_error:
                    metadata["provider_semantic_rewrite_error"] = semantic_rewrite_error
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
            effective_action_request = (
                _turn_request_with_message(turn_request, message=turn_intent.action.request_message)
                if turn_intent.action.replayed_previous_request
                else turn_request
            )
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
                record = await _create_action_record(
                    http_request,
                    effective_action_request,
                    actor=actor,
                    draft=turn_intent.action.draft,
                    confirmed=False,
                    turn_intent_metadata=turn_intent_metadata(),
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
                    allow_provider_composition=provider_auth_allowed,
                    turn_intent_metadata=turn_intent_metadata(),
                    progress_callback=progress_callback,
                )
            else:
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

                turn_task = asyncio.create_task(run_turn())
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
            finally:
                if turn_task is not None and not turn_task.done():
                    turn_task.cancel()

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

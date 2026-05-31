"""Read-only Simurgh Operator GCS routes."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from src.settings.runtime import resolve_runtime_mode
from agent_runtime.tool_executor import execute_policy_allowed_read_only_tool, list_policy_allowed_read_only_tools

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
    is_mcp_auth_required,
    is_mcp_origin_allowed,
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
from agent_runtime.assistant import READ_TOOL_ADAPTER_VERSION, READ_TOOL_MODEL, READ_TOOL_PROVIDER
from agent_runtime.mds_read_tools import (
    apply_runtime_settings,
    build_provider_credentials_payload,
    build_runtime_settings_payload,
    classify_mds_read_intent,
    delete_provider_credentials,
    update_provider_credentials,
)
from agent_runtime.models import AgentSession, AuditEvent, ContextResource, ToolDefinition, utc_now
from agent_runtime.query_adaptation import normalize_operator_query_text
from agent_runtime.registry_chat import (
    REGISTRY_READ_EXECUTION_INTENT,
    RegistryReadToolResult,
    format_registry_read_results,
    plan_registry_read_tool_calls,
)
from agent_runtime.tool_candidates import candidate_review_payload, load_default_tool_candidate_artifact


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
EXTERNAL_ASSISTANT_PROVIDER_SESSION_ROLES = {"admin", "operator"}
EXTERNAL_ASSISTANT_PROVIDER_BEARER_SCOPES = {"admin", "agent", "operator"}


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
    language = metadata.get("language_profile") if isinstance(metadata.get("language_profile"), dict) else {}
    adaptation = metadata.get("query_adaptation") if isinstance(metadata.get("query_adaptation"), dict) else {}
    return SimurghAssistantTurnTraceResponse(
        provider=record.turn.provider,
        model=record.turn.model,
        adapter_version=record.turn.adapter_version,
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
        },
        tool={
            "id": metadata.get("tool_id"),
            "intent": metadata.get("tool_intent"),
            "ids": metadata.get("tool_ids") or [],
        },
        context={
            "resource_count": metadata.get("context_count"),
            "retrieved_context_count": metadata.get("retrieved_context_count"),
        },
        safety={
            "blocked_intent_count": metadata.get("blocked_intent_count"),
            "action_execution": "none",
            "circuit_breaker_layer": "final-action layer; no action tool was invoked for this turn",
        },
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
    tool_ids = [str(item).strip() for item in (tool.get("ids") or []) if str(item).strip()]
    tool_intent = str(tool.get("intent") or "").strip()
    provider = str(payload.get("provider") or "").strip()

    if tool_ids:
        titles = _tool_titles_for_progress(tool_ids)
        joined_titles = "; ".join(titles)
        if len(tool_ids) > len(titles):
            joined_titles = f"{joined_titles}; +{len(tool_ids) - len(titles)} more" if joined_titles else f"{len(tool_ids)} tools"
        label = (
            f"Using read-only MDS tool: {joined_titles}"
            if len(tool_ids) == 1
            else f"Using {len(tool_ids)} read-only MDS tools: {joined_titles}"
        )
        return {"stage": "tool", "label": label, "intent": tool_intent, "tool_ids": tool_ids}

    if tool_intent:
        return {"stage": "tool", "label": f"Using {tool_intent.replace('_', ' ')}", "intent": tool_intent}
    if provider == "openai":
        return {"stage": "provider", "label": "Composing with OpenAI provider"}
    return {"stage": "provider", "label": "Composing local response"}


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

    async def _create_registry_read_execution_record(
        http_request: Request,
        turn_request: SimurghAssistantTurnRequest,
        *,
        actor: str,
        plan,
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

        context_documents = AssistantContextAssembler(config=load_default_assistant_config()).assemble(
            _bounded_context_resource_ids(turn_request.context_resource_ids)
        )
        registry = load_default_tool_registry()
        try:
            registry_label = registry.path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            registry_label = registry.path.as_posix()

        results: list[RegistryReadToolResult] = []
        for call in plan.tool_calls:
            result = await execute_policy_allowed_read_only_tool(
                http_request,
                name=call.tool.id,
                arguments=dict(call.arguments),
                channel="agent",
                registry=registry,
                policy=policy,
            )
            results.append(RegistryReadToolResult(tool=call.tool, arguments=dict(call.arguments), result=result))

        content = format_registry_read_results(plan, results, registry_path=registry_label)
        tool_ids = [item.tool.id for item in results]
        turn = AssistantTurnResult(
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
                "retrieved_context_count": 0,
                "web_search_enabled": False,
                "provider_composed_from_tool": False,
                "provider_composition_error": "",
            },
        )
        return AssistantTurnRecord(session=session, turn=turn, audit_event=event)

    async def _create_assistant_turn_record_for_request(http_request: Request, turn_request: SimurghAssistantTurnRequest):
        try:
            assistant_config = load_default_assistant_config()
            conversation_topic = None
            if turn_request.session_id:
                try:
                    conversation_topic = str(sessions.require(turn_request.session_id).metadata.get("last_domain") or "")
                except KeyError:
                    conversation_topic = None
            routing_message = normalize_operator_query_text(turn_request.message)
            local_only_turn = bool(
                classify_mds_read_intent(routing_message, conversation_topic=conversation_topic)
                or blocked_intent_matches(assistant_config, turn_request.message)
                or blocked_intent_matches(assistant_config, routing_message)
                or sensitive_input_matches(assistant_config, turn_request.message)
                or sensitive_input_matches(assistant_config, routing_message)
            )
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
            registry_plan = None
            if not blocked_matches and not sensitive_matches:
                registry_plan = plan_registry_read_tool_calls(
                    routing_message,
                    allowed_tools=list_policy_allowed_read_only_tools(channel="agent"),
                    conversation_topic=conversation_topic,
                )
                local_only_turn = local_only_turn or registry_plan is not None
            provider_auth_allowed = assistant_config.provider != "mock" and _has_external_assistant_provider_auth(http_request)
            if not local_only_turn:
                _require_external_assistant_provider_auth(http_request, assistant_config.provider)
                provider_auth_allowed = assistant_config.provider != "mock"
            actor = _resolve_actor(http_request, turn_request.actor)
            if registry_plan is not None:
                record = await _create_registry_read_execution_record(
                    http_request,
                    turn_request,
                    actor=actor,
                    plan=registry_plan,
                )
            else:
                record = create_assistant_turn(
                    sessions=sessions,
                    audit=audit,
                    actor=actor,
                    message=turn_request.message,
                    deps=deps,
                    session_id=turn_request.session_id,
                    mode=turn_request.mode,
                    context_resource_ids=_bounded_context_resource_ids(turn_request.context_resource_ids),
                    metadata=_bounded_metadata(turn_request.metadata),
                    allow_provider_for_local_tools=local_only_turn and provider_auth_allowed,
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
            try:
                yield _assistant_sse_event("progress", {"stage": "understanding", "label": "Understanding request"})
                await asyncio.sleep(0)
                yield _assistant_sse_event("progress", {"stage": "policy", "label": "Checking safety and access policy"})
                await asyncio.sleep(0)
                yield _assistant_sse_event("progress", {"stage": "context", "label": "Selecting MDS context and tools"})
                await asyncio.sleep(0)
                record, history_record = await _create_assistant_turn_record_for_request(http_request, request)
                payload = _assistant_turn_response_payload(record, history_record)
                yield _assistant_sse_event("progress", _assistant_tool_progress_payload(payload))
                await asyncio.sleep(0)
                content = str(payload.get("content") or "")
                if content:
                    yield _assistant_sse_event("progress", {"stage": "answer", "label": "Streaming answer"})
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

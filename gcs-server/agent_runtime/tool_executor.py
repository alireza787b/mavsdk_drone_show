"""Shared policy-gated Simurgh tool execution helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from fastapi import Request

from simurgh_internal_auth import INTERNAL_TOOL_CALL_HEADER, INTERNAL_TOOL_CALL_VALUE, INTERNAL_TOOL_CLIENT_HOST

from .models import AgentRuntimeError, PolicyDecisionStatus, ToolDefinition, ToolExposure
from .policy import AgentPolicy, load_default_policy
from .tool_registry import ToolRegistry, load_default_tool_registry


DEFAULT_INTERNAL_TOOL_TIMEOUT_SECONDS = 20.0
DEFAULT_TOOL_MAX_RESPONSE_CHARS = 24000
ADVISORY_ANSWER_TOOL_ID = "mds.operator.question.answer"
DOCS_SEARCH_TOOL_ID = "mds.docs.search"
DOCS_CHUNK_READ_TOOL_ID = "mds.docs.chunk.read"
GENERAL_KNOWLEDGE_TOOL_ID = "simurgh.general_knowledge.read"
PUBLIC_PLACES_TOOL_ID = "simurgh.public_places.read"
GEODESY_TOOL_ID = "simurgh.geodesy.calculate"
ADVISORY_TOOL_IDS = frozenset(
    {
        ADVISORY_ANSWER_TOOL_ID,
        GENERAL_KNOWLEDGE_TOOL_ID,
        PUBLIC_PLACES_TOOL_ID,
        GEODESY_TOOL_ID,
    }
)
LOCAL_TOOL_IDS = frozenset(
    {
        ADVISORY_ANSWER_TOOL_ID,
        DOCS_SEARCH_TOOL_ID,
        DOCS_CHUNK_READ_TOOL_ID,
        GENERAL_KNOWLEDGE_TOOL_ID,
        PUBLIC_PLACES_TOOL_ID,
        GEODESY_TOOL_ID,
    }
)
LOCAL_TOOL_INTENT_FILTERS = {
    GENERAL_KNOWLEDGE_TOOL_ID: frozenset({"general_knowledge", "autopilot_support"}),
    PUBLIC_PLACES_TOOL_ID: frozenset({"public_geography"}),
    GEODESY_TOOL_ID: frozenset({"public_geography"}),
}


@dataclass(frozen=True)
class ToolCatalogSummary:
    """Policy-filtered registry summary for MCP and assistant surfaces."""

    registry: ToolRegistry
    policy: AgentPolicy
    allowed_tools: tuple[ToolDefinition, ...]
    guarded_count: int
    excluded_count: int


@dataclass(frozen=True)
class ReadOnlyToolCallResult:
    """Result of one internal read-only GCS route tool call."""

    text: str
    is_error: bool
    structured_content: Any | None = None
    status_code: int | None = None
    truncated: bool = False

    @classmethod
    def error(cls, message: str) -> "ReadOnlyToolCallResult":
        return cls(text=message, is_error=True)

    def as_mcp_result(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "content": [{"type": "text", "text": self.text}],
            "isError": self.is_error,
        }
        if self.structured_content is not None and not self.is_error:
            payload["structuredContent"] = self.structured_content
        if self.truncated:
            payload.setdefault("_meta", {})["ai.mds/truncated"] = True
        if self.status_code is not None:
            payload.setdefault("_meta", {})["ai.mds/http_status"] = self.status_code
        return payload


def is_read_only_route_tool(tool: ToolDefinition) -> bool:
    """Return whether a registry tool is callable by the current read-only adapter."""

    return bool(
        tool.boundary == "gcs"
        and tool.read_only
        and not tool.destructive
        and tool.route_method == "GET"
        and tool.route_path
    )


def is_read_only_advisory_tool(tool: ToolDefinition) -> bool:
    """Return whether a route-less registry tool is handled by Simurgh's local adapter."""

    return bool(
        tool.id in LOCAL_TOOL_IDS
        and tool.boundary == "gcs"
        and tool.read_only
        and not tool.destructive
        and not tool.route_method
        and not tool.route_path
    )


def is_read_only_callable_tool(tool: ToolDefinition) -> bool:
    """Return whether the current adapter can execute a read-only registry tool."""

    return is_read_only_route_tool(tool) or is_read_only_advisory_tool(tool)


def list_policy_allowed_read_only_tools(
    *,
    channel: str,
    registry: ToolRegistry | None = None,
    policy: AgentPolicy | None = None,
) -> tuple[ToolDefinition, ...]:
    """Return policy-allowed read-only callable tools for one channel."""

    active_registry = registry or load_default_tool_registry()
    active_policy = policy or load_default_policy()
    visible: list[ToolDefinition] = []
    for tool in active_registry.list_tools():
        decision = active_policy.evaluate_tool(tool, channel=channel)
        if decision.status is PolicyDecisionStatus.ALLOW and is_read_only_callable_tool(tool):
            visible.append(tool)
    return tuple(visible)


def summarize_read_only_tool_catalog(
    *,
    channel: str,
    registry: ToolRegistry | None = None,
    policy: AgentPolicy | None = None,
) -> ToolCatalogSummary:
    """Return shared registry counts for assistant/MCP capability summaries."""

    active_registry = registry or load_default_tool_registry()
    active_policy = policy or load_default_policy()
    guarded = 0
    excluded = 0
    for tool in active_registry.list_tools():
        if tool.exposure is ToolExposure.EXCLUDE:
            excluded += 1
            continue
        if tool.exposure is ToolExposure.GUARDED or tool.requires_approval or not tool.read_only:
            guarded += 1
    return ToolCatalogSummary(
        registry=active_registry,
        policy=active_policy,
        allowed_tools=list_policy_allowed_read_only_tools(
            channel=channel,
            registry=active_registry,
            policy=active_policy,
        ),
        guarded_count=guarded,
        excluded_count=excluded,
    )


async def execute_policy_allowed_read_only_tool(
    request: Request,
    *,
    name: str,
    arguments: dict[str, Any],
    channel: str,
    registry: ToolRegistry | None = None,
    policy: AgentPolicy | None = None,
    timeout_seconds: float = DEFAULT_INTERNAL_TOOL_TIMEOUT_SECONDS,
    max_response_chars: int = DEFAULT_TOOL_MAX_RESPONSE_CHARS,
) -> ReadOnlyToolCallResult:
    """Execute one approved read-only GCS GET/advisory tool through policy gates."""

    active_registry = registry or load_default_tool_registry()
    tool = active_registry.get(name)
    if tool is None:
        return ReadOnlyToolCallResult.error(f"Unknown Simurgh tool: {name}")
    active_policy = policy or load_default_policy()
    decision = active_policy.evaluate_tool(tool, channel=channel)
    if decision.status is not PolicyDecisionStatus.ALLOW:
        return ReadOnlyToolCallResult.error("Simurgh policy denied this tool call: " + "; ".join(decision.reasons))
    if is_read_only_advisory_tool(tool):
        return execute_policy_allowed_advisory_tool(
            name=name,
            arguments=arguments,
            channel=channel,
            registry=active_registry,
            policy=active_policy,
        )
    if not is_read_only_route_tool(tool):
        return ReadOnlyToolCallResult.error(
            "Only policy-allowed read-only GET tools are callable by this Simurgh adapter."
        )
    route_result = _route_path_with_arguments(tool, arguments)
    if route_result.is_error:
        return route_result
    route_path = route_result.text

    headers: dict[str, str] = {INTERNAL_TOOL_CALL_HEADER: INTERNAL_TOOL_CALL_VALUE}

    transport = httpx.ASGITransport(app=request.app, client=(INTERNAL_TOOL_CLIENT_HOST, 0))
    async with httpx.AsyncClient(
        transport=transport,
        base_url=str(request.base_url).rstrip("/"),
        timeout=timeout_seconds,
    ) as client:
        response = await client.get(route_path, headers=headers)

    content_type = response.headers.get("content-type", "")
    try:
        structured = response.json() if "application/json" in content_type else None
    except ValueError:
        structured = None

    text = json.dumps(structured, indent=2, sort_keys=True, default=str) if structured is not None else response.text
    truncated = False
    if len(text) > max_response_chars:
        text = text[:max_response_chars] + "\n...[truncated by Simurgh response limit]"
        truncated = True

    return ReadOnlyToolCallResult(
        text=text,
        is_error=response.status_code >= 400,
        structured_content=structured,
        status_code=response.status_code,
        truncated=truncated,
    )


_PATH_PARAM_RE = re.compile(r"{([A-Za-z_][A-Za-z0-9_]*)}")


def _route_path_with_arguments(tool: ToolDefinition, arguments: dict[str, Any]) -> ReadOnlyToolCallResult:
    """Return a route path with validated path/query arguments applied."""

    if not tool.route_path:
        return ReadOnlyToolCallResult.error("This Simurgh tool has no route path.")
    schema = dict(tool.input_schema or {})
    if not schema:
        if arguments:
            return ReadOnlyToolCallResult.error("This Simurgh tool does not accept arguments yet.")
        return ReadOnlyToolCallResult(text=tool.route_path, is_error=False)

    validation_error = _validate_tool_arguments(arguments, schema)
    if validation_error:
        return ReadOnlyToolCallResult.error(validation_error)

    path_param_names = tuple(_PATH_PARAM_RE.findall(tool.route_path))
    route_path = tool.route_path
    for name in path_param_names:
        if name not in arguments:
            return ReadOnlyToolCallResult.error(f"Missing required path argument: {name}")
        value = str(arguments[name])
        route_path = route_path.replace("{" + name + "}", quote(value, safe=""))

    query_items = []
    for key, value in sorted(arguments.items()):
        if key in path_param_names or value is None:
            continue
        if isinstance(value, bool):
            encoded_value = "true" if value else "false"
        else:
            encoded_value = str(value)
        query_items.append((key, encoded_value))
    if query_items:
        route_path = route_path + "?" + urlencode(query_items)
    return ReadOnlyToolCallResult(text=route_path, is_error=False)


def _validate_tool_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> str | None:
    if not isinstance(arguments, dict):
        return "Tool arguments must be an object."
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = tuple(str(item) for item in schema.get("required", []) if str(item))
    additional_allowed = bool(schema.get("additionalProperties", True))

    for name in required:
        if name not in arguments or arguments[name] is None or arguments[name] == "":
            return f"Missing required argument: {name}"
    if not additional_allowed:
        extra = sorted(set(arguments) - set(properties))
        if extra:
            return "Unsupported argument(s): " + ", ".join(extra)

    for name, value in arguments.items():
        if value is None:
            continue
        prop = properties.get(name)
        if not isinstance(prop, dict):
            if additional_allowed:
                continue
            return f"Unsupported argument: {name}"
        error = _validate_one_argument(name, value, prop)
        if error:
            return error
    return None


def _validate_one_argument(name: str, value: Any, schema: dict[str, Any]) -> str | None:
    expected_type = schema.get("type")
    if expected_type == "string":
        if not isinstance(value, str):
            return f"Argument {name} must be a string."
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            return f"Argument {name} is shorter than {min_length} characters."
        if isinstance(max_length, int) and len(value) > max_length:
            return f"Argument {name} is longer than {max_length} characters."
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and not re.fullmatch(pattern, value):
            return f"Argument {name} does not match the required pattern."
    elif expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"Argument {name} must be an integer."
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return f"Argument {name} must be >= {minimum}."
        if isinstance(maximum, (int, float)) and value > maximum:
            return f"Argument {name} must be <= {maximum}."
    elif expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return f"Argument {name} must be a number."
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return f"Argument {name} must be >= {minimum}."
        if isinstance(maximum, (int, float)) and value > maximum:
            return f"Argument {name} must be <= {maximum}."
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            return f"Argument {name} must be a boolean."
    enum = schema.get("enum")
    if isinstance(enum, list) and enum and value not in enum:
        return f"Argument {name} must be one of: " + ", ".join(str(item) for item in enum)
    return None


def execute_policy_allowed_advisory_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    channel: str,
    deps: Any | None = None,
    registry: ToolRegistry | None = None,
    policy: AgentPolicy | None = None,
) -> ReadOnlyToolCallResult:
    """Execute one policy-allowed local advisory tool from the shared registry."""

    active_registry = registry or load_default_tool_registry()
    tool = active_registry.get(name)
    if tool is None:
        return ReadOnlyToolCallResult.error(f"Unknown Simurgh tool: {name}")
    active_policy = policy or load_default_policy()
    decision = active_policy.evaluate_tool(tool, channel=channel)
    if decision.status is not PolicyDecisionStatus.ALLOW:
        return ReadOnlyToolCallResult.error("Simurgh policy denied this tool call: " + "; ".join(decision.reasons))
    if not is_read_only_advisory_tool(tool):
        return ReadOnlyToolCallResult.error("This Simurgh tool is not a local advisory tool.")
    return _execute_advisory_tool(tool, arguments, deps=deps)


def _execute_advisory_tool(tool: ToolDefinition, arguments: dict[str, Any], *, deps: Any | None = None) -> ReadOnlyToolCallResult:
    """Execute a route-less local tool from the same registry used by MCP."""

    if tool.id not in LOCAL_TOOL_IDS:
        return ReadOnlyToolCallResult.error(f"Unsupported Simurgh local tool: {tool.id}")
    schema_error = _validate_tool_arguments(arguments, dict(tool.input_schema or {}))
    if schema_error:
        return ReadOnlyToolCallResult.error(schema_error)

    if tool.id == DOCS_SEARCH_TOOL_ID:
        from .docs_index import build_docs_search_payload, format_docs_search_payload

        try:
            payload = build_docs_search_payload(
                str(arguments.get("query") or ""),
                limit=int(arguments.get("limit") or 5),
                tags=str(arguments.get("tags") or ""),
                audience=str(arguments.get("audience") or ""),
            )
        except (AgentRuntimeError, KeyError, ValueError) as exc:
            return ReadOnlyToolCallResult.error(str(exc))
        return ReadOnlyToolCallResult(
            text=format_docs_search_payload(payload),
            is_error=False,
            structured_content=payload,
        )

    if tool.id == DOCS_CHUNK_READ_TOOL_ID:
        from .docs_index import build_docs_chunk_payload, format_docs_chunk_payload

        try:
            payload = build_docs_chunk_payload(
                str(arguments.get("chunk_id") or ""),
                max_chars=int(arguments.get("max_chars") or 4000),
            )
        except (AgentRuntimeError, KeyError, ValueError) as exc:
            return ReadOnlyToolCallResult.error(str(exc))
        return ReadOnlyToolCallResult(
            text=format_docs_chunk_payload(payload),
            is_error=False,
            structured_content=payload,
            truncated=bool(payload.get("truncated")),
        )

    raw_question = arguments.get("question")
    if not isinstance(raw_question, str) or not raw_question.strip():
        return ReadOnlyToolCallResult.error(f"{tool.id} requires a non-empty string argument: question")

    from .assistant import blocked_intent_matches, load_default_assistant_config, sensitive_input_matches
    from .language import detect_language_profile
    from .mds_read_tools import answer_mds_read_only_question, classify_mds_read_intent, is_safe_blocked_term_read_only_intent
    from .query_adaptation import adapt_operator_query

    question = raw_question.strip()
    raw_topic = arguments.get("conversation_topic")
    conversation_topic = raw_topic.strip() if isinstance(raw_topic, str) else None
    language_profile = detect_language_profile(question)
    query_adaptation = adapt_operator_query(
        question,
        language_profile=language_profile,
        conversation_topic=conversation_topic,
    )
    routing_question = query_adaptation.routing_text or question
    config = load_default_assistant_config()
    blocked_matches = tuple(
        sorted(set(blocked_intent_matches(config, question) + blocked_intent_matches(config, routing_question)))
    )
    sensitive_matches = tuple(
        sorted(set(sensitive_input_matches(config, question) + sensitive_input_matches(config, routing_question)))
    )
    intent = classify_mds_read_intent(routing_question, conversation_topic=conversation_topic)
    safe_blocked_term = is_safe_blocked_term_read_only_intent(routing_question, intent)
    if sensitive_matches or (blocked_matches and intent != "action_capability" and not safe_blocked_term):
        blocked = tuple(sorted(set(blocked_matches + sensitive_matches)))
        return ReadOnlyToolCallResult(
            text=(
                "Simurgh blocked this operator-question tool call before execution. "
                "The request matched operational or sensitive-input safety terms: "
                + ", ".join(blocked)
                + ". No provider, GCS mutation, drone API, or command path was called."
            ),
            is_error=True,
            structured_content={
                "blocked": True,
                "blocked_intents": list(blocked),
                "intent": intent,
                "execution": "none",
                "query_adaptation": query_adaptation.public_metadata(),
            },
        )

    answer = answer_mds_read_only_question(routing_question, deps=deps, conversation_topic=conversation_topic)
    if answer is None:
        return ReadOnlyToolCallResult(
            text=(
                "I do not have a deterministic MDS read-only answer for that question yet. "
                "Use MCP resources/list for available docs/context, tools/list for approved read-only GCS tools, "
                "mds.docs.search for indexed public docs, or ask a narrower fleet, show, swarm, logs, SITL, board setup, or capability question."
            ),
            is_error=False,
            structured_content={
                "intent": None,
                "execution": "none",
                "query_adaptation": query_adaptation.public_metadata(),
            },
        )

    allowed_intents = LOCAL_TOOL_INTENT_FILTERS.get(tool.id)
    if allowed_intents and answer.intent not in allowed_intents:
        return ReadOnlyToolCallResult(
            text=(
                f"{tool.id} did not match this question. "
                "Use tools/list to choose the right Simurgh read-only tool, or call "
                f"{ADVISORY_ANSWER_TOOL_ID} for general operator question routing."
            ),
            is_error=False,
            structured_content={
                "intent": answer.intent,
                "matched": False,
                "execution": "none",
                "query_adaptation": query_adaptation.public_metadata(),
            },
        )

    return ReadOnlyToolCallResult(
        text=answer.content,
        is_error=False,
        structured_content={
            "intent": answer.intent,
            "content": answer.content,
            "tool_ids": list(answer.tool_ids),
            "safety_notes": list(answer.safety_notes),
            "response_mode": answer.response_mode,
            "evidence": answer.evidence_metadata(),
            "execution": "read_only_advisory",
            "query_adaptation": query_adaptation.public_metadata(),
        },
    )

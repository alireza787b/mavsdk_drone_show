"""Short-lived Simurgh session store."""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import replace
from datetime import timedelta
from functools import wraps
from typing import Any, Callable, Mapping

from .models import AgentRuntimeError, AgentSession, utc_now


SAFE_SESSION_METADATA_KEYS = {"channel", "source", "last_domain", "last_intent", "last_response_mode"}
SAFE_SESSION_METADATA_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
PRIVATE_CONTEXT_KEYS = {
    "last_assistant_content",
    "last_assistant_provider",
    "last_assistant_model",
    "last_domain",
    "last_intent",
    "last_response_mode",
    "last_user_message",
    "last_routing_message",
    "last_tool_intent",
    "last_read_only_evidence",
    "last_action_draft",
    "last_action_draft_id",
    "last_action_draft_hash",
    "last_action_request_message",
    "last_action_run_id",
    "last_submitted_action",
    "clarification_operator_messages",
    "recent_operator_messages",
}
STRUCTURED_PRIVATE_CONTEXT_KEYS = {
    "last_action_draft",
    "last_submitted_action",
    "last_read_only_evidence",
}
MAX_PRIVATE_CONTEXT_VALUE_CHARS = 6000
# Covers 32 supported action steps with 12,000-character argument payloads,
# including JSON escaping and the surrounding persisted action envelope.
DEFAULT_MAX_STRUCTURED_CONTEXT_BYTES = 4 * 1024 * 1024
MAX_RECENT_OPERATOR_MESSAGES = 4
MAX_RECENT_OPERATOR_CONTEXT_CHARS = 5600
SAFE_SESSION_METADATA_VALUES = {
    "channel": {"assistant", "dashboard"},
    "source": {"simurgh-dashboard", "simurgh-ui"},
    "last_domain": {
        "capabilities",
        "clarification",
        "action_run",
        "docs",
        "drone_show",
        "fleet",
        "flight",
        "general",
        "logs",
        "mcp",
        "public_geography",
        "runtime",
        "sar",
        "safety",
        "setup",
        "sitl",
        "swarm",
        "ui",
    },
    "last_intent": {
        "action_capability",
        "action_run",
        "action_run_control",
        "add_drone_workflow",
        "backend_log_summary",
        "board_setup_help",
        "capability_catalog",
        "companion_setup_help",
        "clarify",
        "docs_help",
        "fleet_connectivity",
        "fleet_summary",
        "flight_action",
        "mission_mode_comparison",
        "operator_help",
        "autopilot_support",
        "conversation_transform",
        "runtime_summary",
        "general_knowledge",
        "public_geography",
        "registry_domain_tool_summary",
        "registry_read_execution",
        "show_modes_help",
        "show_summary",
        "show_upload_help",
        "sitl_help",
        "swarm_topology",
    },
    "last_response_mode": {"status", "interpret", "workflow", "compare", "capability", "clarify", "transform"},
}


def _with_store_lock(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def locked(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return locked


def sanitize_session_metadata(metadata: Mapping[str, object] | None) -> dict[str, object]:
    """Keep only model-safe session metadata fields."""

    safe: dict[str, object] = {}
    for key in SAFE_SESSION_METADATA_KEYS:
        value = str((metadata or {}).get(key) or "").strip()
        if (
            value
            and value in SAFE_SESSION_METADATA_VALUES[key]
            and SAFE_SESSION_METADATA_VALUE_PATTERN.fullmatch(value)
        ):
            safe[key] = value
    return safe


class AgentSessionStore:
    """In-memory session store for operator and MCP adapter sessions."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 3600,
        max_structured_context_bytes: int = DEFAULT_MAX_STRUCTURED_CONTEXT_BYTES,
    ):
        if ttl_seconds <= 0:
            raise AgentRuntimeError("session ttl_seconds must be positive")
        if max_structured_context_bytes <= 0:
            raise AgentRuntimeError("session max_structured_context_bytes must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_structured_context_bytes = max_structured_context_bytes
        self._lock = threading.RLock()
        self._sessions: dict[str, AgentSession] = {}
        self._private_contexts: dict[str, dict[str, str]] = {}

    @_with_store_lock
    def create(self, *, actor: str, mode: str, metadata: Mapping[str, object] | None = None) -> AgentSession:
        actor = actor.strip()
        if not actor:
            raise AgentRuntimeError("session actor is required")
        now = utc_now()
        session = AgentSession(
            id=f"session-{uuid.uuid4().hex}",
            actor=actor,
            mode=mode.strip() or "read_only",
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
            metadata=sanitize_session_metadata(metadata),
        )
        self._sessions[session.id] = session
        self._private_contexts[session.id] = {}
        return session

    @_with_store_lock
    def update_metadata(self, session_id: str, metadata: Mapping[str, object]) -> AgentSession:
        """Merge safe short-lived session metadata into an existing session."""

        session = self.require(session_id)
        if session.closed:
            raise AgentRuntimeError("assistant session is closed")
        merged = {**dict(session.metadata), **sanitize_session_metadata(metadata)}
        updated = replace(session, metadata=merged)
        self._sessions[session_id] = updated
        return updated

    @_with_store_lock
    def require(self, session_id: str) -> AgentSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"unknown session id: {session_id}")
        if session.is_expired() and not session.closed:
            session = replace(session, closed_at=session.expires_at)
            self._sessions[session_id] = session
        return session

    @_with_store_lock
    def close(self, session_id: str) -> AgentSession:
        session = self.require(session_id)
        if session.closed:
            return session
        closed = replace(session, closed_at=utc_now())
        self._sessions[session_id] = closed
        self._private_contexts.pop(session_id, None)
        return closed

    @_with_store_lock
    def get_private_context(self, session_id: str) -> dict[str, str]:
        """Return bounded in-memory context that is never serialized to API/MCP responses."""

        self.require(session_id)
        return dict(self._private_contexts.get(session_id, {}))

    @_with_store_lock
    def update_private_context(self, session_id: str, values: Mapping[str, object]) -> dict[str, str]:
        """Merge private conversation state for follow-up resolution.

        This intentionally bypasses public metadata sanitization because it is
        not exposed by session/list, audit, history, or MCP resources. It is
        still bounded and key-scoped to avoid turning the session store into an
        unreviewed transcript database.
        """

        self.require(session_id)
        current = dict(self._private_contexts.get(session_id, {}))
        normalized_values: dict[str, str] = {}
        for key, raw_value in values.items():
            if key not in PRIVATE_CONTEXT_KEYS:
                continue
            if key in STRUCTURED_PRIVATE_CONTEXT_KEYS:
                if raw_value is None or raw_value == "":
                    normalized_values[key] = ""
                    continue
                if not isinstance(raw_value, str):
                    raise AgentRuntimeError(
                        f"private context {key} must be serialized JSON text"
                    )
                try:
                    serialized_size = len(raw_value.encode("utf-8"))
                except UnicodeEncodeError as exc:
                    raise AgentRuntimeError(
                        f"private context {key} must contain valid UTF-8 JSON"
                    ) from exc
                if serialized_size > self.max_structured_context_bytes:
                    raise AgentRuntimeError(
                        f"private context {key} exceeds the structured JSON limit "
                        f"of {self.max_structured_context_bytes} bytes"
                    )
                try:
                    decoded = json.loads(raw_value)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise AgentRuntimeError(
                        f"private context {key} must contain valid JSON"
                    ) from exc
                if not isinstance(decoded, Mapping):
                    raise AgentRuntimeError(
                        f"private context {key} must contain a JSON object"
                    )
                normalized_values[key] = raw_value
                continue
            value = str(raw_value or "").strip()
            if len(value) > MAX_PRIVATE_CONTEXT_VALUE_CHARS:
                value = value[:MAX_PRIVATE_CONTEXT_VALUE_CHARS].rstrip()
            normalized_values[key] = value

        for key, value in normalized_values.items():
            if value:
                current[key] = value
            else:
                current.pop(key, None)
        latest_message = " ".join(str(values.get("last_user_message") or "").split()).strip()
        if latest_message:
            recent: list[str] = []
            try:
                decoded = json.loads(current.get("recent_operator_messages", "[]"))
            except ValueError:
                decoded = []
            if isinstance(decoded, list):
                recent.extend(
                    " ".join(str(item or "").split()).strip()[:MAX_PRIVATE_CONTEXT_VALUE_CHARS]
                    for item in decoded
                    if str(item or "").strip()
                )
            latest_message = latest_message[:MAX_PRIVATE_CONTEXT_VALUE_CHARS]
            if not recent or recent[-1] != latest_message:
                recent.append(latest_message)
            encoded = json.dumps(recent, ensure_ascii=False, separators=(",", ":"))
            while (
                len(recent) > MAX_RECENT_OPERATOR_MESSAGES
                or len(encoded) > MAX_RECENT_OPERATOR_CONTEXT_CHARS
            ):
                recent.pop(0)
                encoded = json.dumps(recent, ensure_ascii=False, separators=(",", ":"))
            current["recent_operator_messages"] = encoded
        self._private_contexts[session_id] = current
        return dict(current)

    @_with_store_lock
    def list_sessions(self, *, include_closed: bool = True) -> list[AgentSession]:
        values = [self.require(session_id) for session_id in list(self._sessions)]
        if not include_closed:
            values = [session for session in values if not session.closed]
        return sorted(values, key=lambda session: session.created_at)

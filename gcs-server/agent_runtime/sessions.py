"""Short-lived Simurgh session store."""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import timedelta
from typing import Mapping

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
}
MAX_PRIVATE_CONTEXT_VALUE_CHARS = 6000
SAFE_SESSION_METADATA_VALUES = {
    "channel": {"assistant", "dashboard"},
    "source": {"simurgh-dashboard", "simurgh-ui"},
    "last_domain": {
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
        "setup",
        "sitl",
        "swarm",
        "ui",
    },
    "last_intent": {
        "action_capability",
        "add_drone_workflow",
        "backend_log_summary",
        "board_setup_help",
        "capability_catalog",
        "companion_setup_help",
        "docs_help",
        "fleet_connectivity",
        "fleet_summary",
        "mission_mode_comparison",
        "operator_help",
        "autopilot_support",
        "conversation_transform",
        "runtime_summary",
        "general_knowledge",
        "public_geography",
        "show_modes_help",
        "show_summary",
        "show_upload_help",
        "sitl_help",
        "swarm_topology",
    },
    "last_response_mode": {"status", "interpret", "workflow", "compare", "capability", "clarify", "transform"},
}


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

    def __init__(self, *, ttl_seconds: int = 3600):
        if ttl_seconds <= 0:
            raise AgentRuntimeError("session ttl_seconds must be positive")
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, AgentSession] = {}
        self._private_contexts: dict[str, dict[str, str]] = {}

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

    def update_metadata(self, session_id: str, metadata: Mapping[str, object]) -> AgentSession:
        """Merge safe short-lived session metadata into an existing session."""

        session = self.require(session_id)
        if session.closed:
            raise AgentRuntimeError("assistant session is closed")
        merged = {**dict(session.metadata), **sanitize_session_metadata(metadata)}
        updated = replace(session, metadata=merged)
        self._sessions[session_id] = updated
        return updated

    def require(self, session_id: str) -> AgentSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"unknown session id: {session_id}")
        if session.is_expired() and not session.closed:
            session = replace(session, closed_at=session.expires_at)
            self._sessions[session_id] = session
        return session

    def close(self, session_id: str) -> AgentSession:
        session = self.require(session_id)
        if session.closed:
            return session
        closed = replace(session, closed_at=utc_now())
        self._sessions[session_id] = closed
        self._private_contexts.pop(session_id, None)
        return closed

    def get_private_context(self, session_id: str) -> dict[str, str]:
        """Return bounded in-memory context that is never serialized to API/MCP responses."""

        self.require(session_id)
        return dict(self._private_contexts.get(session_id, {}))

    def update_private_context(self, session_id: str, values: Mapping[str, object]) -> dict[str, str]:
        """Merge private conversation state for follow-up resolution.

        This intentionally bypasses public metadata sanitization because it is
        not exposed by session/list, audit, history, or MCP resources. It is
        still bounded and key-scoped to avoid turning the session store into an
        unreviewed transcript database.
        """

        self.require(session_id)
        current = dict(self._private_contexts.get(session_id, {}))
        for key, raw_value in values.items():
            if key not in PRIVATE_CONTEXT_KEYS:
                continue
            value = str(raw_value or "").strip()
            if len(value) > MAX_PRIVATE_CONTEXT_VALUE_CHARS:
                value = value[:MAX_PRIVATE_CONTEXT_VALUE_CHARS].rstrip()
            if value:
                current[key] = value
            else:
                current.pop(key, None)
        self._private_contexts[session_id] = current
        return dict(current)

    def list_sessions(self, *, include_closed: bool = True) -> list[AgentSession]:
        values = [self.require(session_id) for session_id in list(self._sessions)]
        if not include_closed:
            values = [session for session in values if not session.closed]
        return sorted(values, key=lambda session: session.created_at)

"""Short-lived Simurgh session store."""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import timedelta
from typing import Mapping

from .models import AgentRuntimeError, AgentSession, utc_now


SAFE_SESSION_METADATA_KEYS = {"channel", "source"}
SAFE_SESSION_METADATA_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
SAFE_SESSION_METADATA_VALUES = {
    "channel": {"assistant", "dashboard"},
    "source": {"simurgh-dashboard", "simurgh-ui"},
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
        return session

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
        return closed

    def list_sessions(self, *, include_closed: bool = True) -> list[AgentSession]:
        values = [self.require(session_id) for session_id in list(self._sessions)]
        if not include_closed:
            values = [session for session in values if not session.closed]
        return sorted(values, key=lambda session: session.created_at)

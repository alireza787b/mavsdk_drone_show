"""Audit sinks for Simurgh Operator."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Mapping

from .models import AuditEvent, stable_payload_hash, utc_now


class InMemoryAuditSink:
    """Append-only audit sink for tests and future adapters."""

    def __init__(self):
        self._events: list[AuditEvent] = []

    def record(
        self,
        event_type: str,
        *,
        session_id: str | None = None,
        actor: str | None = None,
        tool_id: str | None = None,
        decision: str | None = None,
        payload: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            id=f"audit-{uuid.uuid4().hex}",
            event_type=event_type,
            created_at=utc_now(),
            session_id=session_id,
            actor=actor,
            tool_id=tool_id,
            decision=decision,
            payload_hash=stable_payload_hash(payload),
            metadata=dict(metadata or {}),
        )
        self._events.append(event)
        return event

    def list_events(self, *, session_id: str | None = None) -> list[AuditEvent]:
        values = self._events
        if session_id is not None:
            values = [event for event in values if event.session_id == session_id]
        return list(values)


class JsonlAuditSink(InMemoryAuditSink):
    """JSONL audit sink for local runtime integration tests."""

    def __init__(self, path: str | Path):
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event_type: str, **kwargs) -> AuditEvent:  # type: ignore[override]
        event = super().record(event_type, **kwargs)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_json_dict(), sort_keys=True) + "\n")
        return event

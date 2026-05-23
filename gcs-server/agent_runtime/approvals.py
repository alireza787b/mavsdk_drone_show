"""Human approval primitives for Simurgh Operator."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta
from typing import Mapping

from .models import AgentRuntimeError, ApprovalRecord, ApprovalStatus, stable_payload_hash, utc_now


class InMemoryApprovalBroker:
    """Deterministic approval broker used until a persistent backend is added."""

    def __init__(self, *, ttl_seconds: int = 300):
        if ttl_seconds <= 0:
            raise AgentRuntimeError("approval ttl_seconds must be positive")
        self.ttl_seconds = ttl_seconds
        self._records: dict[str, ApprovalRecord] = {}

    def request(
        self,
        *,
        session_id: str,
        tool_id: str,
        actor: str,
        rationale: str,
        tool_input: Mapping[str, object] | None = None,
    ) -> ApprovalRecord:
        now = utc_now()
        record = ApprovalRecord(
            id=f"approval-{uuid.uuid4().hex}",
            session_id=session_id,
            tool_id=tool_id,
            actor=actor,
            rationale=rationale.strip(),
            input_hash=stable_payload_hash(tool_input),
            status=ApprovalStatus.PENDING,
            requested_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        self._records[record.id] = record
        return record

    def decide(self, approval_id: str, *, approved: bool, decided_by: str, reason: str = "") -> ApprovalRecord:
        record = self.require(approval_id)
        if record.status is not ApprovalStatus.PENDING:
            raise AgentRuntimeError(f"approval {approval_id} is already {record.status.value}")
        now = utc_now()
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        updated = replace(
            record,
            status=status,
            decided_at=now,
            decided_by=decided_by.strip(),
            decision_reason=reason.strip(),
        )
        self._records[approval_id] = updated
        return updated

    def require(self, approval_id: str) -> ApprovalRecord:
        record = self._records.get(approval_id)
        if record is None:
            raise KeyError(f"unknown approval id: {approval_id}")
        if record.status is ApprovalStatus.PENDING and record.is_expired():
            record = replace(record, status=ApprovalStatus.EXPIRED)
            self._records[approval_id] = record
        return record

    def is_approved(
        self,
        approval_id: str,
        *,
        tool_id: str,
        session_id: str,
        tool_input: Mapping[str, object] | None = None,
    ) -> bool:
        record = self.require(approval_id)
        return (
            record.status is ApprovalStatus.APPROVED
            and record.tool_id == tool_id
            and record.session_id == session_id
            and record.input_hash == stable_payload_hash(tool_input)
            and not record.is_expired()
        )

    def list_records(self) -> list[ApprovalRecord]:
        return sorted(self._records.values(), key=lambda record: record.requested_at)

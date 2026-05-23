"""Shared Simurgh Operator data models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class AgentRuntimeError(ValueError):
    """Raised when Simurgh runtime configuration or state is invalid."""


class ToolExposure(str, Enum):
    """How a GCS capability may be exposed to agent/MCP clients."""

    ALLOW = "allow"
    GUARDED = "guarded"
    EXCLUDE = "exclude"


class ToolRiskClass(str, Enum):
    """Safety class for curated tools."""

    OBSERVE = "observe"
    SENSITIVE_OBSERVE = "sensitive_observe"
    PLAN = "plan"
    SIMULATE = "simulate"
    OPERATE = "operate"
    ADMIN = "admin"
    DESTRUCTIVE = "destructive"


class PolicyDecisionStatus(str, Enum):
    """Result of evaluating one tool request against policy."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ApprovalStatus(str, Enum):
    """Lifecycle state for human approval records."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def stable_payload_hash(payload: Mapping[str, Any] | None) -> str:
    """Hash a JSON-compatible payload for audit and approval matching."""

    encoded = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _string_tuple(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise AgentRuntimeError(f"{field_name} must be a list")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise AgentRuntimeError(f"{field_name} must be an object")
    return dict(value)


@dataclass(frozen=True)
class ToolDefinition:
    """Curated GCS tool metadata loaded from `config/agent_tools.yaml`."""

    id: str
    title: str
    description: str
    exposure: ToolExposure
    risk_class: ToolRiskClass
    boundary: str = "gcs"
    read_only: bool = True
    route_method: str | None = None
    route_path: str | None = None
    required_role: str = "viewer"
    requires_approval: bool = False
    destructive: bool = False
    runtime_modes: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    sensitivity: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()
    safety_notes: tuple[str, ...] = ()
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ToolDefinition":
        required = {"id", "title", "description", "exposure", "risk_class"}
        missing = sorted(required - set(payload))
        if missing:
            raise AgentRuntimeError(f"tool is missing required field(s): {', '.join(missing)}")

        route = _mapping(payload.get("route"), field_name=f"{payload.get('id', '<unknown>')}.route")
        tool_id = str(payload["id"]).strip()
        try:
            exposure = ToolExposure(str(payload["exposure"]).strip())
            risk_class = ToolRiskClass(str(payload["risk_class"]).strip())
        except ValueError as exc:
            raise AgentRuntimeError(f"{tool_id or '<unknown>'}: invalid exposure or risk_class") from exc

        tool = cls(
            id=tool_id,
            title=str(payload["title"]).strip(),
            description=str(payload["description"]).strip(),
            exposure=exposure,
            risk_class=risk_class,
            boundary=str(payload.get("boundary") or "gcs").strip(),
            read_only=bool(payload.get("read_only", True)),
            route_method=str(route["method"]).upper().strip() if route.get("method") else None,
            route_path=str(route["path"]).strip() if route.get("path") else None,
            required_role=str(payload.get("required_role") or "viewer").strip(),
            requires_approval=bool(payload.get("requires_approval", False)),
            destructive=bool(payload.get("destructive", False)),
            runtime_modes=_string_tuple(payload.get("runtime_modes"), field_name="runtime_modes"),
            side_effects=_string_tuple(payload.get("side_effects"), field_name="side_effects"),
            sensitivity=_string_tuple(payload.get("sensitivity"), field_name="sensitivity"),
            tags=_string_tuple(payload.get("tags"), field_name="tags"),
            docs=_string_tuple(payload.get("docs"), field_name="docs"),
            safety_notes=_string_tuple(payload.get("safety_notes"), field_name="safety_notes"),
            input_schema=_mapping(payload.get("input_schema"), field_name="input_schema"),
            output_schema=_mapping(payload.get("output_schema"), field_name="output_schema"),
        )
        tool.validate()
        return tool

    def validate(self) -> None:
        if not self.id or any(char.isspace() for char in self.id):
            raise AgentRuntimeError("tool id must be non-empty and whitespace-free")
        if not self.title:
            raise AgentRuntimeError(f"{self.id}: title is required")
        if not self.description:
            raise AgentRuntimeError(f"{self.id}: description is required")
        if self.boundary not in {"gcs", "drone", "external"}:
            raise AgentRuntimeError(f"{self.id}: unsupported boundary {self.boundary!r}")
        if self.route_method and self.route_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise AgentRuntimeError(f"{self.id}: unsupported route method {self.route_method!r}")
        if self.route_path and not self.route_path.startswith("/"):
            raise AgentRuntimeError(f"{self.id}: route path must start with /")
        if bool(self.route_method) != bool(self.route_path):
            raise AgentRuntimeError(f"{self.id}: route method and path must be provided together")
        if self.destructive and self.risk_class is not ToolRiskClass.DESTRUCTIVE:
            raise AgentRuntimeError(f"{self.id}: destructive tools must use destructive risk_class")
        if self.exposure is ToolExposure.ALLOW and self.requires_approval:
            raise AgentRuntimeError(f"{self.id}: approval-required tools must be guarded, not allow")
        if self.boundary != "gcs" and self.exposure is not ToolExposure.EXCLUDE:
            raise AgentRuntimeError(f"{self.id}: non-GCS tools must be excluded in this phase")
        if self.risk_class in {ToolRiskClass.OPERATE, ToolRiskClass.ADMIN, ToolRiskClass.DESTRUCTIVE}:
            if self.exposure is ToolExposure.ALLOW:
                raise AgentRuntimeError(f"{self.id}: high-risk tools cannot be directly allowed")


@dataclass(frozen=True)
class PolicyDecision:
    """Policy result for one tool request."""

    status: PolicyDecisionStatus
    tool_id: str
    reasons: tuple[str, ...] = ()
    approval_required: bool = False
    audit_required: bool = True

    @property
    def allowed(self) -> bool:
        return self.status is PolicyDecisionStatus.ALLOW

    @property
    def denied(self) -> bool:
        return self.status is PolicyDecisionStatus.DENY


@dataclass(frozen=True)
class ApprovalRecord:
    """Human approval request and decision metadata."""

    id: str
    session_id: str
    tool_id: str
    actor: str
    rationale: str
    input_hash: str
    status: ApprovalStatus
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_reason: str = ""

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or utc_now()) >= self.expires_at


@dataclass(frozen=True)
class AuditEvent:
    """Append-only audit event used by Simurgh adapters and tests."""

    id: str
    event_type: str
    created_at: datetime
    session_id: str | None = None
    actor: str | None = None
    tool_id: str | None = None
    decision: str | None = None
    payload_hash: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "created_at": self.created_at.isoformat(),
            "session_id": self.session_id,
            "actor": self.actor,
            "tool_id": self.tool_id,
            "decision": self.decision,
            "payload_hash": self.payload_hash,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AgentSession:
    """Short-lived operator/agent session state."""

    id: str
    actor: str
    mode: str
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def closed(self) -> bool:
        return self.closed_at is not None

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or utc_now()) >= self.expires_at


@dataclass(frozen=True)
class ContextResource:
    """Agent-readable context resource registered in `docs/agent-context`."""

    id: str
    title: str
    path: Path
    mime_type: str = "text/markdown"
    audience: str = "agent"
    sensitivity: str = "public"
    summary: str = ""
    tags: tuple[str, ...] = ()

    def content_hash(self, *, repo_root: Path) -> str:
        resolved_root = repo_root.resolve()
        full_path = (resolved_root / self.path).resolve()
        try:
            full_path.relative_to(resolved_root)
        except ValueError as exc:
            raise AgentRuntimeError(f"context resource escapes repo root: {self.path}") from exc
        return hashlib.sha256(full_path.read_bytes()).hexdigest()

"""Policy evaluation for provider-neutral Simurgh tools."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

from .models import (
    AgentRuntimeError,
    PolicyDecision,
    PolicyDecisionStatus,
    ToolDefinition,
    ToolExposure,
    ToolRiskClass,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "agent_policy.yaml"
VALID_RISK_VALUES = frozenset(risk.value for risk in ToolRiskClass)


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    raise AgentRuntimeError(f"{name} must be boolean")


def _string_set(value: object, *, field_name: str) -> frozenset[str]:
    if value in (None, ""):
        return frozenset()
    if not isinstance(value, list):
        raise AgentRuntimeError(f"{field_name} must be a list")
    return frozenset(str(item).strip() for item in value if str(item).strip())


def _risk_set(value: object, *, field_name: str) -> frozenset[str]:
    risks = _string_set(value, field_name=field_name)
    invalid = sorted(risk for risk in risks if risk not in VALID_RISK_VALUES)
    if invalid:
        raise AgentRuntimeError(f"{field_name} contains invalid risk class(es): {', '.join(invalid)}")
    return risks


@dataclass(frozen=True)
class RuntimeModePolicy:
    """Risk gates for one Simurgh runtime mode."""

    allowed_risks: frozenset[str] = field(default_factory=frozenset)
    denied_risks: frozenset[str] = field(default_factory=frozenset)
    approval_required_risks: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object], *, mode: str) -> "RuntimeModePolicy":
        return cls(
            allowed_risks=_risk_set(payload.get("allowed_risks"), field_name=f"{mode}.allowed_risks"),
            denied_risks=_risk_set(payload.get("denied_risks"), field_name=f"{mode}.denied_risks"),
            approval_required_risks=_risk_set(
                payload.get("approval_required_risks"),
                field_name=f"{mode}.approval_required_risks",
            ),
        )


@dataclass(frozen=True)
class AgentPolicy:
    """Deny-by-default runtime policy loaded from `config/agent_policy.yaml`."""

    version: int
    path: Path
    agent_enabled: bool = False
    mcp_enabled: bool = False
    mode: str = "read_only"
    action_circuit_breaker_enabled: bool = True
    always_confirm_before_action: bool = True
    real_commands_enabled: bool = False
    allow_drone_api_exposure: bool = False
    unknown_tool_policy: str = "deny"
    approval_ttl_seconds: int = 300
    runtime_modes: Mapping[str, RuntimeModePolicy] = field(default_factory=dict)
    approval_required_risks: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_POLICY_PATH, *, apply_env: bool = True) -> "AgentPolicy":
        policy_path = Path(path)
        try:
            payload = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as exc:
            raise AgentRuntimeError(f"agent policy not found: {policy_path}") from exc
        if not isinstance(payload, dict):
            raise AgentRuntimeError("agent policy root must be an object")
        return cls.from_mapping(payload, path=policy_path, apply_env=apply_env)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, object],
        *,
        path: Path | None = None,
        apply_env: bool = False,
    ) -> "AgentPolicy":
        version = int(payload.get("version") or 0)
        if version < 1:
            raise AgentRuntimeError("agent policy version must be >= 1")
        defaults = payload.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise AgentRuntimeError("agent policy defaults must be an object")
        runtime_modes_raw = payload.get("runtime_modes") or {}
        if not isinstance(runtime_modes_raw, dict):
            raise AgentRuntimeError("agent policy runtime_modes must be an object")

        runtime_modes: dict[str, RuntimeModePolicy] = {}
        for mode_key, value in runtime_modes_raw.items():
            mode_name = str(mode_key)
            if not isinstance(value, dict):
                raise AgentRuntimeError(f"agent policy runtime mode {mode_name!r} must be an object")
            runtime_modes[mode_name] = RuntimeModePolicy.from_mapping(value or {}, mode=mode_name)

        mode = str(defaults.get("mode") or "read_only")
        if mode not in runtime_modes:
            raise AgentRuntimeError(f"agent policy mode {mode!r} has no runtime_modes entry")
        unknown_tool_policy = str(defaults.get("unknown_tool_policy") or "deny")
        if unknown_tool_policy != "deny":
            raise AgentRuntimeError("unknown_tool_policy must be deny in this phase")
        approval_ttl_seconds = int(defaults.get("approval_ttl_seconds") or 300)
        if approval_ttl_seconds <= 0:
            raise AgentRuntimeError("approval_ttl_seconds must be positive")

        policy = cls(
            version=version,
            path=path or DEFAULT_POLICY_PATH,
            agent_enabled=bool(defaults.get("agent_enabled", False)),
            mcp_enabled=bool(defaults.get("mcp_enabled", False)),
            mode=mode,
            action_circuit_breaker_enabled=bool(defaults.get("action_circuit_breaker_enabled", True)),
            always_confirm_before_action=bool(defaults.get("always_confirm_before_action", True)),
            real_commands_enabled=bool(defaults.get("real_commands_enabled", False)),
            allow_drone_api_exposure=bool(defaults.get("allow_drone_api_exposure", False)),
            unknown_tool_policy=unknown_tool_policy,
            approval_ttl_seconds=approval_ttl_seconds,
            runtime_modes=runtime_modes,
            approval_required_risks=_risk_set(
                payload.get("approval_required_risks"),
                field_name="approval_required_risks",
            ),
        )
        if not apply_env:
            return policy
        return policy.with_env_overrides()

    def with_env_overrides(self) -> "AgentPolicy":
        """Apply host-local env toggles without changing the policy artifact."""

        mode = os.environ.get("MDS_AGENT_MODE", self.mode).strip() or self.mode
        if mode not in self.runtime_modes:
            raise AgentRuntimeError(f"MDS_AGENT_MODE references unknown Simurgh mode: {mode}")

        return AgentPolicy(
            version=self.version,
            path=self.path,
            agent_enabled=_bool_env("MDS_AGENT_ENABLED", self.agent_enabled),
            mcp_enabled=_bool_env("MDS_MCP_ENABLED", self.mcp_enabled),
            mode=mode,
            action_circuit_breaker_enabled=_bool_env(
                "MDS_AGENT_ACTION_CIRCUIT_BREAKER",
                self.action_circuit_breaker_enabled,
            ),
            always_confirm_before_action=_bool_env(
                "MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION",
                self.always_confirm_before_action,
            ),
            real_commands_enabled=_bool_env("MDS_AGENT_REAL_COMMANDS_ENABLED", self.real_commands_enabled),
            allow_drone_api_exposure=self.allow_drone_api_exposure,
            unknown_tool_policy=self.unknown_tool_policy,
            approval_ttl_seconds=self.approval_ttl_seconds,
            runtime_modes=self.runtime_modes,
            approval_required_risks=self.approval_required_risks,
        )

    def evaluate_tool(
        self,
        tool: ToolDefinition | None,
        *,
        channel: str = "agent",
        approved: bool = False,
    ) -> PolicyDecision:
        """Evaluate a curated tool request against deny-by-default policy."""

        if tool is None:
            return PolicyDecision(
                status=PolicyDecisionStatus.DENY,
                tool_id="<unknown>",
                reasons=("unknown tool",),
            )
        reasons: list[str] = []
        if not self.agent_enabled:
            reasons.append("agent runtime disabled")
        if channel == "mcp" and not self.mcp_enabled:
            reasons.append("MCP runtime disabled")
        if tool.boundary != "gcs" and not self.allow_drone_api_exposure:
            reasons.append("non-GCS tool boundary is disabled")
        if tool.exposure is ToolExposure.EXCLUDE:
            reasons.append("tool is explicitly excluded")
        if self.action_circuit_breaker_enabled and not tool.read_only:
            reasons.append("Simurgh action circuit breaker is enabled")
        if tool.risk_class is ToolRiskClass.OPERATE and not self.real_commands_enabled:
            reasons.append("real-world command tools are disabled")
        if tool.runtime_modes and self.mode not in tool.runtime_modes:
            reasons.append(f"tool is not available in mode {self.mode!r}")
        if self.mode == "read_only" and not tool.read_only:
            reasons.append("non-read-only tool is denied in read_only mode")

        mode_policy = self.runtime_modes.get(self.mode)
        if mode_policy is None:
            reasons.append(f"runtime mode {self.mode!r} is not configured")
        else:
            risk = tool.risk_class.value
            if risk in mode_policy.denied_risks:
                reasons.append(f"risk class {risk!r} is denied in mode {self.mode!r}")
            if mode_policy.allowed_risks and risk not in mode_policy.allowed_risks:
                reasons.append(f"risk class {risk!r} is not allowed in mode {self.mode!r}")

        if reasons:
            return PolicyDecision(
                status=PolicyDecisionStatus.DENY,
                tool_id=tool.id,
                reasons=tuple(reasons),
            )

        risk_value = tool.risk_class.value
        approval_required = (
            tool.exposure is ToolExposure.GUARDED
            or tool.requires_approval
            or tool.destructive
            or (self.always_confirm_before_action and not tool.read_only)
            or risk_value in self.approval_required_risks
            or risk_value in (mode_policy.approval_required_risks if mode_policy else frozenset())
        )
        if approval_required and not approved:
            return PolicyDecision(
                status=PolicyDecisionStatus.REQUIRE_APPROVAL,
                tool_id=tool.id,
                reasons=("human approval required",),
                approval_required=True,
            )

        return PolicyDecision(status=PolicyDecisionStatus.ALLOW, tool_id=tool.id)


def load_default_policy() -> AgentPolicy:
    """Load the repository default Simurgh policy."""

    raw = os.environ.get("MDS_AGENT_POLICY_FILE")
    path = Path(raw) if raw else DEFAULT_POLICY_PATH
    if not path.is_absolute():
        path = REPO_ROOT / path
    return AgentPolicy.from_file(path)

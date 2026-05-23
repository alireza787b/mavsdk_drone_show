"""Metadata-only MCP helpers for Simurgh Operator."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .audit import InMemoryAuditSink
from .assistant import load_default_assistant_config
from .context import AgentContextIndex, load_default_context_index
from .models import AgentRuntimeError, AgentSession, AuditEvent, ContextResource, ToolDefinition, ToolExposure
from .policy import AgentPolicy, load_default_policy
from .sessions import AgentSessionStore
from .tool_registry import ToolRegistry, load_default_tool_registry


MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_ENDPOINT_PATH = "/api/v1/simurgh/mcp"
MCP_RESOURCE_PREFIX = "mds://simurgh"
MCP_ALLOWED_ORIGINS_ENV = "MDS_MCP_ALLOWED_ORIGINS"
MCP_AUTHORIZATION_SERVERS_ENV = "MDS_MCP_AUTHORIZATION_SERVERS"
MCP_REQUIRE_AUTH_ENV = "MDS_MCP_REQUIRE_AUTH"
MCP_REQUIRED_SCOPES_ENV = "MDS_MCP_REQUIRED_SCOPES"
MCP_RESOURCE_URL_ENV = "MDS_MCP_RESOURCE_URL"
REPO_ROOT = Path(__file__).resolve().parents[2]

LOCAL_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_MCP_REQUIRED_SCOPES = ("agent", "admin")
SUPPORTED_MCP_REQUIRED_SCOPES = frozenset(DEFAULT_MCP_REQUIRED_SCOPES)


@dataclass(frozen=True)
class McpResourceContent:
    """Text resource payload returned by `resources/read`."""

    uri: str
    mime_type: str
    text: str

    def as_mcp_content(self) -> dict[str, Any]:
        return {"uri": self.uri, "mimeType": self.mime_type, "text": self.text}


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def _origin_host(origin: str) -> str:
    try:
        return urlparse(origin).hostname or ""
    except ValueError:
        return ""


def _allowed_origin_values() -> tuple[str, ...]:
    raw = os.environ.get(MCP_ALLOWED_ORIGINS_ENV, "")
    return tuple(value.strip().rstrip("/") for value in raw.split(",") if value.strip())


def _csv_env_values(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    return tuple(value.strip() for value in raw.split(",") if value.strip())


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def is_mcp_origin_allowed(origin: str | None) -> bool:
    """Validate Streamable HTTP Origin headers against local/default policy."""

    if not origin:
        return True

    normalized = origin.strip().rstrip("/")
    configured = _allowed_origin_values()
    if configured:
        for allowed in configured:
            if normalized == allowed:
                return True
            if allowed.endswith(":*"):
                allowed_base = allowed[:-2]
                parsed_allowed = urlparse(allowed_base)
                parsed_origin = urlparse(normalized)
                if (
                    parsed_allowed.scheme == parsed_origin.scheme
                    and parsed_allowed.hostname == parsed_origin.hostname
                ):
                    return True
        return False

    return _origin_host(normalized) in LOCAL_ORIGIN_HOSTS


def mcp_required_scopes() -> tuple[str, ...]:
    """Return accepted bearer-token scopes for the MCP endpoint.

    The values are ORed: a token with any one required scope may use the
    metadata-only endpoint. The challenge advertises the least-privilege
    `agent` scope by default even though `admin` tokens are also accepted.
    Weaker scopes such as `drone`, `operator`, or `viewer` are ignored so an
    unsafe environment override cannot widen MCP access.
    """

    configured = tuple(value.lower() for value in _csv_env_values(MCP_REQUIRED_SCOPES_ENV))
    accepted = tuple(
        dict.fromkeys(value for value in configured if value in SUPPORTED_MCP_REQUIRED_SCOPES)
    )
    return accepted or DEFAULT_MCP_REQUIRED_SCOPES


def is_mcp_auth_required() -> bool:
    """Return whether enabled MCP traffic must carry accepted bearer auth."""

    return _bool_env(MCP_REQUIRE_AUTH_ENV, True)


def mcp_challenge_scope() -> str:
    """Return the least-privilege scope advertised in WWW-Authenticate."""

    scopes = mcp_required_scopes()
    if "agent" in scopes:
        return "agent"
    for scope in scopes:
        if scope != "admin":
            return scope
    return scopes[0]


def mcp_resource_url(base_url: str) -> str:
    """Return the canonical MCP protected-resource URL."""

    configured = _configured_mcp_resource_url()
    if configured:
        return configured
    return f"{base_url.rstrip('/')}{MCP_ENDPOINT_PATH}"


def _configured_mcp_resource_url() -> str | None:
    value = os.environ.get(MCP_RESOURCE_URL_ENV, "").strip().rstrip("/")
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentRuntimeError(f"{MCP_RESOURCE_URL_ENV} must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise AgentRuntimeError(f"{MCP_RESOURCE_URL_ENV} must not include query strings or fragments")
    return value


def _canonical_public_base_url(base_url: str) -> str:
    configured = _configured_mcp_resource_url()
    if configured:
        parsed = urlparse(configured)
        return f"{parsed.scheme}://{parsed.netloc}"
    return base_url.rstrip("/")


def _canonical_mcp_resource_path() -> str:
    configured = _configured_mcp_resource_url()
    if not configured:
        return MCP_ENDPOINT_PATH
    return urlparse(configured).path.rstrip("/")


def mcp_resource_metadata_url(base_url: str) -> str:
    """Return the path-specific protected-resource metadata URL."""

    return f"{_canonical_public_base_url(base_url)}/.well-known/oauth-protected-resource{_canonical_mcp_resource_path()}"


def _mcp_authorization_servers(base_url: str) -> tuple[str, ...]:
    configured = _csv_env_values(MCP_AUTHORIZATION_SERVERS_ENV)
    if configured:
        return configured
    if not is_mcp_auth_required():
        return ()
    return (_canonical_public_base_url(base_url),)


def _www_auth_param(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def mcp_bearer_challenge(
    base_url: str,
    *,
    error: str | None = None,
    error_description: str | None = None,
) -> str:
    """Build an MCP OAuth-style bearer challenge for HTTP auth failures."""

    params = [
        f"resource_metadata={_www_auth_param(mcp_resource_metadata_url(base_url))}",
        f"scope={_www_auth_param(mcp_challenge_scope())}",
    ]
    if error:
        params.append(f"error={_www_auth_param(error)}")
    if error_description:
        params.append(f"error_description={_www_auth_param(error_description)}")
    return "Bearer " + ", ".join(params)


def mcp_protected_resource_metadata(base_url: str) -> dict[str, Any]:
    """Return RFC 9728-style metadata for the Simurgh MCP resource server."""

    canonical_base_url = _canonical_public_base_url(base_url)
    payload: dict[str, Any] = {
        "resource": mcp_resource_url(base_url),
        "resource_name": "MDS Simurgh Operator MCP",
        "resource_documentation": f"{canonical_base_url}/docs/guides/simurgh-operator.md",
        "resource_policy_uri": f"{canonical_base_url}/docs/agent-context/safety-policy.md",
        "bearer_methods_supported": ["header"],
        "scopes_supported": sorted(set(mcp_required_scopes())),
        "mds_auth_required": is_mcp_auth_required(),
        "mds_boundary": "gcs-only",
        "mds_execution": "none",
    }
    authorization_servers = _mcp_authorization_servers(base_url)
    if authorization_servers:
        payload["authorization_servers"] = list(authorization_servers)
    return payload


def require_mcp_runtime_enabled(policy: AgentPolicy | None = None) -> AgentPolicy:
    """Require both Simurgh agent and MCP toggles before serving MCP traffic."""

    active_policy = policy or load_default_policy()
    if not active_policy.agent_enabled:
        raise AgentRuntimeError("Simurgh agent runtime is disabled")
    if not active_policy.mcp_enabled:
        raise AgentRuntimeError("Simurgh MCP runtime is disabled")
    return active_policy


def mcp_server_info() -> dict[str, Any]:
    """Return MCP implementation metadata."""

    return {
        "name": "mds-simurgh-operator",
        "title": "MDS Simurgh Operator",
        "version": "0.1.0",
        "description": "Metadata-only MCP surface for GCS-owned Simurgh context and policy.",
    }


def mcp_server_instructions() -> str:
    """Return short model-facing instructions for this metadata-only MCP server."""

    return (
        "This Simurgh MCP endpoint exposes read-only GCS metadata and public "
        "context resources. It exposes no MCP tools and cannot command drones, "
        "submit raw GCS commands, mutate sessions, or perform real-world actions."
    )


class SimurghMcpResourceProvider:
    """Build MCP resource metadata from Simurgh runtime artifacts."""

    def __init__(self, *, sessions: AgentSessionStore, audit: InMemoryAuditSink):
        self.sessions = sessions
        self.audit = audit

    def list_resources(self) -> list[dict[str, Any]]:
        context_index = load_default_context_index()
        resources = [
            self._resource(
                "status",
                title="Simurgh Runtime Status",
                description="Current Simurgh runtime posture and artifact paths.",
            ),
            self._resource(
                "policy",
                title="Simurgh Policy",
                description="Effective deny-by-default policy and runtime risk gates.",
            ),
            self._resource(
                "tool-registry",
                title="Simurgh Tool Registry Metadata",
                description="Curated tool metadata only. This MCP server does not expose callable tools.",
            ),
            self._resource(
                "context-index",
                title="Simurgh Context Index",
                description="Public agent-readable context index metadata.",
            ),
            self._resource(
                "sessions",
                title="Simurgh Sessions",
                description="Session metadata visible to the GCS runtime.",
            ),
            self._resource(
                "audit",
                title="Simurgh Audit Trail",
                description="Audit event metadata with hashed payloads only.",
            ),
        ]

        for resource in sorted(context_index.resources.values(), key=lambda item: item.id):
            if resource.sensitivity != "public":
                continue
            resources.append(
                self._resource(
                    f"context/{resource.id}",
                    display_name=resource.id,
                    title=resource.title,
                    description=resource.summary,
                    mime_type=resource.mime_type,
                    meta={
                        "ai.mds/audience": resource.audience,
                        "ai.mds/sensitivity": resource.sensitivity,
                        "ai.mds/tags": list(resource.tags),
                    },
                )
            )
        return resources

    def read_resource(self, uri: str) -> McpResourceContent:
        name = self._resource_name(uri)
        if name == "status":
            return self._json_resource(uri, self._status_payload())
        if name == "policy":
            return self._json_resource(uri, self._policy_payload(load_default_policy()))
        if name == "tool-registry":
            return self._json_resource(uri, self._tool_registry_payload(load_default_tool_registry()))
        if name == "context-index":
            return self._json_resource(uri, self._context_index_payload(load_default_context_index()))
        if name == "sessions":
            return self._json_resource(uri, self._sessions_payload())
        if name == "audit":
            return self._json_resource(uri, self._audit_payload())
        if name.startswith("context/"):
            resource_id = name.split("/", 1)[1]
            index = load_default_context_index()
            resource = index.require(resource_id)
            if resource.sensitivity != "public":
                raise PermissionError(f"context resource is not public: {resource_id}")
            return McpResourceContent(uri=uri, mime_type=resource.mime_type, text=index.read_text(resource_id))
        raise KeyError(f"unknown Simurgh MCP resource: {uri}")

    def _resource(
        self,
        path: str,
        *,
        title: str,
        description: str,
        mime_type: str = "application/json",
        display_name: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "uri": f"{MCP_RESOURCE_PREFIX}/{path}",
            "name": display_name or path,
            "title": title,
            "description": description,
            "mimeType": mime_type,
            "_meta": {
                "ai.mds/execution": "none",
                "ai.mds/boundary": "gcs",
                **(meta or {}),
            },
        }

    def _resource_name(self, uri: str) -> str:
        prefix = f"{MCP_RESOURCE_PREFIX}/"
        if not uri.startswith(prefix):
            raise KeyError(f"unsupported Simurgh MCP resource URI: {uri}")
        return uri[len(prefix) :]

    def _json_resource(self, uri: str, payload: dict[str, Any]) -> McpResourceContent:
        return McpResourceContent(uri=uri, mime_type="application/json", text=_json_text(payload))

    def _status_payload(self) -> dict[str, Any]:
        policy = load_default_policy()
        registry = load_default_tool_registry()
        context_index = load_default_context_index()
        assistant_config = load_default_assistant_config()
        tools = registry.list_tools()
        return {
            "agent_enabled": policy.agent_enabled,
            "mcp_enabled": policy.mcp_enabled,
            "mode": policy.mode,
            "action_circuit_breaker_enabled": policy.action_circuit_breaker_enabled,
            "always_confirm_before_action": policy.always_confirm_before_action,
            "real_commands_enabled": policy.real_commands_enabled,
            "tool_registry_version": registry.version,
            "tool_count": len(tools),
            "allowed_tool_count": len([tool for tool in tools if tool.exposure.value == "allow"]),
            "guarded_tool_count": len([tool for tool in tools if tool.exposure.value == "guarded"]),
            "excluded_tool_count": len([tool for tool in tools if tool.exposure.value == "exclude"]),
            "context_resource_count": len(context_index.resources),
            "active_session_count": len(self.sessions.list_sessions(include_closed=False)),
            "audit_event_count": len(self.audit.list_events()),
            "assistant_provider": assistant_config.provider,
            "assistant_model": (
                assistant_config.openai.model
                if assistant_config.provider == "openai"
                else "mock-local"
            ),
            "assistant_external_provider": assistant_config.provider != "mock",
            "policy_path": _display_path(policy.path),
            "tool_registry_path": _display_path(registry.path),
            "context_index_path": _display_path(context_index.path),
            "mcp_protocol_version": MCP_PROTOCOL_VERSION,
            "mcp_endpoint_path": MCP_ENDPOINT_PATH,
        }

    def _policy_payload(self, policy: AgentPolicy) -> dict[str, Any]:
        return {
            "version": policy.version,
            "agent_enabled": policy.agent_enabled,
            "mcp_enabled": policy.mcp_enabled,
            "mode": policy.mode,
            "action_circuit_breaker_enabled": policy.action_circuit_breaker_enabled,
            "always_confirm_before_action": policy.always_confirm_before_action,
            "real_commands_enabled": policy.real_commands_enabled,
            "allow_drone_api_exposure": policy.allow_drone_api_exposure,
            "unknown_tool_policy": policy.unknown_tool_policy,
            "approval_ttl_seconds": policy.approval_ttl_seconds,
            "approval_required_risks": sorted(policy.approval_required_risks),
            "runtime_modes": {
                mode: {
                    "allowed_risks": sorted(mode_policy.allowed_risks),
                    "denied_risks": sorted(mode_policy.denied_risks),
                    "approval_required_risks": sorted(mode_policy.approval_required_risks),
                }
                for mode, mode_policy in sorted(policy.runtime_modes.items())
            },
        }

    def _tool_registry_payload(self, registry: ToolRegistry) -> dict[str, Any]:
        tools = registry.list_tools()
        visible_tools = [tool for tool in tools if self._is_mcp_visible_tool(tool)]
        return {
            "version": registry.version,
            "path": _display_path(registry.path),
            "tool_count": len(tools),
            "mcp_metadata_tool_count": len(visible_tools),
            "filtered_tool_count": len(tools) - len(visible_tools),
            "filter": {
                "boundary": "gcs",
                "read_only": True,
                "excluded_exposures": ["exclude"],
                "destructive": False,
            },
            "tools": [self._tool_payload(tool) for tool in visible_tools],
            "execution": "none",
            "note": (
                "This MCP endpoint exposes registry metadata as resources, not callable MCP tools. "
                "Excluded, drone-boundary, destructive, and non-read-only entries are filtered."
            ),
        }

    def _is_mcp_visible_tool(self, tool: ToolDefinition) -> bool:
        return (
            tool.exposure is not ToolExposure.EXCLUDE
            and tool.boundary == "gcs"
            and tool.read_only
            and not tool.destructive
        )

    def _tool_payload(self, tool: ToolDefinition) -> dict[str, Any]:
        return {
            "id": tool.id,
            "title": tool.title,
            "description": tool.description,
            "exposure": tool.exposure.value,
            "risk_class": tool.risk_class.value,
            "boundary": tool.boundary,
            "read_only": tool.read_only,
            "route": {"method": tool.route_method, "path": tool.route_path},
            "required_role": tool.required_role,
            "requires_approval": tool.requires_approval,
            "destructive": tool.destructive,
            "runtime_modes": list(tool.runtime_modes),
            "side_effects": list(tool.side_effects),
            "sensitivity": list(tool.sensitivity),
            "tags": list(tool.tags),
            "docs": list(tool.docs),
            "safety_notes": list(tool.safety_notes),
        }

    def _context_index_payload(self, index: AgentContextIndex) -> dict[str, Any]:
        return {
            "version": index.version,
            "path": _display_path(index.path),
            "resources": [
                self._context_resource_payload(index, resource)
                for resource in sorted(index.resources.values(), key=lambda item: item.id)
                if resource.sensitivity == "public"
            ],
        }

    def _context_resource_payload(self, index: AgentContextIndex, resource: ContextResource) -> dict[str, Any]:
        return {
            "id": resource.id,
            "title": resource.title,
            "uri": f"{MCP_RESOURCE_PREFIX}/context/{resource.id}",
            "path": resource.path.as_posix(),
            "mime_type": resource.mime_type,
            "audience": resource.audience,
            "sensitivity": resource.sensitivity,
            "summary": resource.summary,
            "tags": list(resource.tags),
            "content_hash": resource.content_hash(repo_root=index.repo_root),
        }

    def _sessions_payload(self) -> dict[str, Any]:
        return {
            "sessions": [self._session_payload(session) for session in self.sessions.list_sessions()],
        }

    def _session_payload(self, session: AgentSession) -> dict[str, Any]:
        return {
            "id": session.id,
            "actor": session.actor,
            "mode": session.mode,
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "closed_at": session.closed_at.isoformat() if session.closed_at else None,
            "closed": session.closed,
            "metadata": dict(session.metadata),
        }

    def _audit_payload(self) -> dict[str, Any]:
        return {
            "events": [self._audit_event_payload(event) for event in self.audit.list_events()],
        }

    def _audit_event_payload(self, event: AuditEvent) -> dict[str, Any]:
        return event.to_json_dict()

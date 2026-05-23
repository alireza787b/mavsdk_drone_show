"""Agent-readable context index for Simurgh Operator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from .models import AgentRuntimeError, ContextResource


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTEXT_INDEX_PATH = REPO_ROOT / "docs" / "agent-context" / "context-index.yaml"


def _tags(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise AgentRuntimeError("context resource tags must be a list")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _resolve_repo_resource_path(repo_root: Path, resource_path: Path) -> Path:
    full_path = (repo_root / resource_path).resolve()
    try:
        full_path.relative_to(repo_root)
    except ValueError as exc:
        raise AgentRuntimeError(f"context resource escapes repo root: {resource_path}") from exc
    return full_path


@dataclass(frozen=True)
class AgentContextIndex:
    """Validated index of docs that may be exposed to agent/MCP clients."""

    version: int
    path: Path
    repo_root: Path
    resources: Mapping[str, ContextResource]

    @classmethod
    def from_file(
        cls,
        path: str | Path = DEFAULT_CONTEXT_INDEX_PATH,
        *,
        repo_root: str | Path = REPO_ROOT,
    ) -> "AgentContextIndex":
        index_path = Path(path)
        try:
            payload = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as exc:
            raise AgentRuntimeError(f"agent context index not found: {index_path}") from exc
        if not isinstance(payload, dict):
            raise AgentRuntimeError("agent context index root must be an object")
        return cls.from_mapping(payload, path=index_path, repo_root=Path(repo_root))

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, object],
        *,
        path: Path | None = None,
        repo_root: Path = REPO_ROOT,
    ) -> "AgentContextIndex":
        version = int(payload.get("version") or 0)
        if version < 1:
            raise AgentRuntimeError("agent context index version must be >= 1")
        raw_resources = payload.get("resources")
        if not isinstance(raw_resources, list):
            raise AgentRuntimeError("agent context index must contain a resources list")

        resolved_root = repo_root.resolve()
        resources: dict[str, ContextResource] = {}
        for raw in raw_resources:
            if not isinstance(raw, dict):
                raise AgentRuntimeError("each context resource must be an object")
            resource_path = Path(str(raw.get("path") or ""))
            if resource_path.is_absolute() or ".." in resource_path.parts:
                raise AgentRuntimeError(f"invalid context resource path: {resource_path}")
            full_path = _resolve_repo_resource_path(resolved_root, resource_path)
            if not full_path.exists():
                raise AgentRuntimeError(f"context resource is missing: {resource_path}")
            resource = ContextResource(
                id=str(raw.get("id") or "").strip(),
                title=str(raw.get("title") or "").strip(),
                path=resource_path,
                mime_type=str(raw.get("mime_type") or "text/markdown").strip(),
                audience=str(raw.get("audience") or "agent").strip(),
                sensitivity=str(raw.get("sensitivity") or "public").strip(),
                summary=str(raw.get("summary") or "").strip(),
                tags=_tags(raw.get("tags")),
            )
            if not resource.id:
                raise AgentRuntimeError("context resource id is required")
            if resource.id in resources:
                raise AgentRuntimeError(f"duplicate context resource id: {resource.id}")
            resources[resource.id] = resource
        return cls(
            version=version,
            path=path or DEFAULT_CONTEXT_INDEX_PATH,
            repo_root=resolved_root,
            resources=resources,
        )

    def require(self, resource_id: str) -> ContextResource:
        resource = self.resources.get(resource_id)
        if resource is None:
            raise KeyError(f"unknown context resource id: {resource_id}")
        return resource

    def read_text(self, resource_id: str, *, max_bytes: int = 128_000) -> str:
        resource = self.require(resource_id)
        full_path = _resolve_repo_resource_path(self.repo_root, resource.path)
        data = full_path.read_bytes()
        if len(data) > max_bytes:
            raise AgentRuntimeError(f"context resource {resource_id} exceeds max_bytes")
        return data.decode("utf-8")


def load_default_context_index() -> AgentContextIndex:
    """Load the repository default Simurgh context index."""

    raw = os.environ.get("MDS_AGENT_CONTEXT_INDEX_FILE")
    path = Path(raw) if raw else DEFAULT_CONTEXT_INDEX_PATH
    if not path.is_absolute():
        path = REPO_ROOT / path
    return AgentContextIndex.from_file(path)

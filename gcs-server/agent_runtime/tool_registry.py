"""YAML-backed curated tool registry for Simurgh Operator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import yaml

from .models import AgentRuntimeError, ToolDefinition, ToolExposure


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOL_REGISTRY_PATH = REPO_ROOT / "config" / "agent_tools.yaml"


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True)
class ToolRegistry:
    """Validated tool metadata loaded from a versioned artifact."""

    version: int
    path: Path
    tools: Mapping[str, ToolDefinition]

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_TOOL_REGISTRY_PATH) -> "ToolRegistry":
        registry_path = Path(path)
        try:
            payload = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as exc:
            raise AgentRuntimeError(f"tool registry not found: {registry_path}") from exc
        if not isinstance(payload, dict):
            raise AgentRuntimeError("tool registry root must be an object")
        return cls.from_mapping(payload, path=registry_path)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object], *, path: Path | None = None) -> "ToolRegistry":
        version = int(payload.get("version") or 0)
        if version < 1:
            raise AgentRuntimeError("tool registry version must be >= 1")
        raw_tools = payload.get("tools")
        if not isinstance(raw_tools, list):
            raise AgentRuntimeError("tool registry must contain a tools list")

        tools: dict[str, ToolDefinition] = {}
        for raw_tool in raw_tools:
            if not isinstance(raw_tool, dict):
                raise AgentRuntimeError("each tool registry entry must be an object")
            tool = ToolDefinition.from_mapping(raw_tool)
            if tool.id in tools:
                raise AgentRuntimeError(f"duplicate tool id: {tool.id}")
            tools[tool.id] = tool

        return cls(version=version, path=path or DEFAULT_TOOL_REGISTRY_PATH, tools=tools)

    def require(self, tool_id: str) -> ToolDefinition:
        tool = self.tools.get(tool_id)
        if tool is None:
            raise KeyError(f"unknown Simurgh tool id: {tool_id}")
        return tool

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self.tools.get(tool_id)

    def list_tools(self, *, exposure: ToolExposure | str | None = None) -> list[ToolDefinition]:
        values: Iterable[ToolDefinition] = self.tools.values()
        if exposure is not None:
            normalized = exposure if isinstance(exposure, ToolExposure) else ToolExposure(str(exposure))
            values = [tool for tool in values if tool.exposure is normalized]
        return sorted(values, key=lambda tool: tool.id)


def load_default_tool_registry() -> ToolRegistry:
    """Load the repository default Simurgh tool registry."""

    return ToolRegistry.from_file(_env_path("MDS_AGENT_TOOL_REGISTRY_FILE", DEFAULT_TOOL_REGISTRY_PATH))

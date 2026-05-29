"""Review-only OpenAPI candidate inventory for Simurgh MCP promotion."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import AgentRuntimeError, ToolDefinition
from .tool_registry import ToolRegistry


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOL_CANDIDATE_PATH = (
    REPO_ROOT / "docs" / "agent-context" / "generated" / "simurgh-openapi-tool-candidates.yaml"
)


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def load_default_tool_candidate_artifact() -> tuple[dict[str, Any], Path]:
    """Load the generated non-callable candidate artifact."""

    path = _env_path("MDS_AGENT_TOOL_CANDIDATE_FILE", DEFAULT_TOOL_CANDIDATE_PATH)
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise AgentRuntimeError(f"Simurgh tool candidate artifact not found: {path}") from exc
    if not isinstance(payload, dict):
        raise AgentRuntimeError("Simurgh tool candidate artifact root must be an object")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise AgentRuntimeError("Simurgh tool candidate artifact must contain a candidates list")
    return payload, path


def _candidate_source(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    source = candidate.get("source")
    return source if isinstance(source, Mapping) else {}


def _candidate_classification(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    classification = candidate.get("classification")
    return classification if isinstance(classification, Mapping) else {}


def _source_key(source: Mapping[str, Any]) -> tuple[str, str]:
    return (str(source.get("method") or "").upper(), str(source.get("path") or ""))


def _registry_by_route(registry: ToolRegistry | None) -> dict[tuple[str, str], list[ToolDefinition]]:
    if registry is None:
        return {}
    by_route: dict[tuple[str, str], list[ToolDefinition]] = {}
    for tool in registry.list_tools():
        if not tool.route_method or not tool.route_path:
            continue
        by_route.setdefault((tool.route_method.upper(), tool.route_path), []).append(tool)
    return by_route


def _promoted_tool_payloads(source: Mapping[str, Any], registry_by_route: Mapping[tuple[str, str], list[ToolDefinition]]) -> list[dict[str, Any]]:
    tools = registry_by_route.get(_source_key(source), [])
    return [
        {
            "id": tool.id,
            "title": tool.title,
            "exposure": tool.exposure.value,
            "risk_class": tool.risk_class.value,
            "read_only": tool.read_only,
            "requires_approval": tool.requires_approval,
        }
        for tool in sorted(tools, key=lambda item: item.id)
    ]


def _candidate_group(path: str) -> str:
    """Return a stable dashboard/API group label for coverage summaries."""

    parts = [part for part in str(path or "").split("/") if part]
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "v1":
        return parts[2]
    if len(parts) >= 2 and parts[0] == "api":
        return parts[1]
    return parts[0] if parts else "root"


def _eligible_registry_coverage(
    candidates: list[Mapping[str, Any]],
    *,
    registry_by_route: Mapping[tuple[str, str], list[ToolDefinition]],
) -> dict[str, Any]:
    """Summarize reviewed read-only candidates that still need promotion.

    This is a coverage signal only. It does not make any generated candidate
    callable and it deliberately keeps promotion behind the curated registry.
    """

    eligible_sources: list[Mapping[str, Any]] = []
    promoted = 0
    unpromoted: list[Mapping[str, Any]] = []
    by_group: Counter[str] = Counter()
    for candidate in candidates:
        classification = _candidate_classification(candidate)
        if not bool(classification.get("eligible_read_only_mcp_candidate")):
            continue
        source = _candidate_source(candidate)
        eligible_sources.append(source)
        if _source_key(source) in registry_by_route:
            promoted += 1
            continue
        unpromoted.append(source)
        by_group[_candidate_group(str(source.get("path") or ""))] += 1

    total = len(eligible_sources)
    coverage = round((promoted / total) * 100.0, 1) if total else 100.0
    preview = [
        {
            "method": str(source.get("method") or "").upper(),
            "path": str(source.get("path") or ""),
            "group": _candidate_group(str(source.get("path") or "")),
            "summary": str(source.get("summary") or ""),
        }
        for source in sorted(unpromoted, key=lambda item: (str(item.get("path") or ""), str(item.get("method") or "")))[:20]
    ]
    return {
        "eligible_route_candidates": total,
        "eligible_promoted_route_matches": promoted,
        "eligible_unpromoted_route_count": len(unpromoted),
        "eligible_promotion_coverage_percent": coverage,
        "eligible_unpromoted_by_group": dict(sorted(by_group.items())),
        "eligible_unpromoted_routes_preview": preview,
    }


def summarize_tool_candidates(candidates: list[Mapping[str, Any]], *, registry: ToolRegistry | None = None) -> dict[str, Any]:
    """Return reviewer-focused counts without making any candidate callable."""

    method_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    sensitivity_counts: Counter[str] = Counter()
    review_reason_counts: Counter[str] = Counter()
    eligible_count = 0
    request_body_count = 0
    non_get_count = 0

    registry_route_keys = set(_registry_by_route(registry))
    promoted_route_count = 0
    for candidate in candidates:
        source = _candidate_source(candidate)
        classification = _candidate_classification(candidate)
        method = str(source.get("method") or "unknown").upper()
        method_counts[method] += 1
        if method != "GET":
            non_get_count += 1
        if bool(candidate.get("has_request_body")):
            request_body_count += 1
        if bool(classification.get("eligible_read_only_mcp_candidate")):
            eligible_count += 1
        risk = str(classification.get("inferred_risk_class") or "unknown")
        risk_counts[risk] += 1
        for sensitivity in classification.get("inferred_sensitivity") or []:
            sensitivity_counts[str(sensitivity)] += 1
        for reason in classification.get("review_reasons") or []:
            review_reason_counts[str(reason)] += 1
        if _source_key(source) in registry_route_keys:
            promoted_route_count += 1

    registry_by_route = _registry_by_route(registry)
    return {
        "total": len(candidates),
        "eligible_read_only_mcp_candidates": eligible_count,
        "candidate_exclude_or_guard_after_review": len(candidates) - eligible_count,
        "non_get_candidates": non_get_count,
        "request_body_candidates": request_body_count,
        "promoted_registry_route_matches": promoted_route_count,
        "registry_coverage": _eligible_registry_coverage(
            candidates,
            registry_by_route=registry_by_route,
        ),
        "method_counts": dict(sorted(method_counts.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
        "sensitivity_counts": dict(sorted(sensitivity_counts.items())),
        "top_review_reasons": [
            {"reason": reason, "count": count}
            for reason, count in review_reason_counts.most_common(12)
        ],
    }


def _matches_filters(
    candidate: Mapping[str, Any],
    *,
    eligible_read_only: bool | None,
    risk_class: str | None,
    search: str | None,
) -> bool:
    source = _candidate_source(candidate)
    classification = _candidate_classification(candidate)
    if eligible_read_only is not None and bool(classification.get("eligible_read_only_mcp_candidate")) is not eligible_read_only:
        return False
    if risk_class and str(classification.get("inferred_risk_class") or "") != risk_class:
        return False
    if search:
        haystack = " ".join(
            str(value)
            for value in (
                candidate.get("id"),
                source.get("method"),
                source.get("path"),
                source.get("operation_id"),
                source.get("summary"),
                " ".join(str(tag) for tag in source.get("tags") or []),
            )
        ).lower()
        if search.lower() not in haystack:
            return False
    return True


def candidate_review_payload(
    artifact: Mapping[str, Any],
    *,
    artifact_path: Path,
    registry: ToolRegistry | None = None,
    eligible_read_only: bool | None = None,
    risk_class: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a bounded, review-only view of the generated candidate artifact."""

    raw_candidates = [candidate for candidate in artifact.get("candidates") or [] if isinstance(candidate, Mapping)]
    filtered_candidates = [
        candidate
        for candidate in raw_candidates
        if _matches_filters(candidate, eligible_read_only=eligible_read_only, risk_class=risk_class, search=search)
    ]
    registry_by_route = _registry_by_route(registry)
    safe_offset = max(0, offset)
    safe_limit = max(1, min(limit, 200))
    page = filtered_candidates[safe_offset:safe_offset + safe_limit]
    candidates = []
    for candidate in page:
        source = dict(_candidate_source(candidate))
        classification = dict(_candidate_classification(candidate))
        promoted_tools = _promoted_tool_payloads(source, registry_by_route)
        candidates.append({
            "id": str(candidate.get("id") or ""),
            "review_status": str(candidate.get("review_status") or "needs_review"),
            "callable": False,
            "source": source,
            "classification": classification,
            "has_request_body": bool(candidate.get("has_request_body")),
            "parameter_count": len(candidate.get("parameters") or []),
            "promoted": bool(promoted_tools),
            "promoted_tools": promoted_tools,
        })
    return {
        "schema_version": int(artifact.get("schema_version") or 1),
        "artifact": str(artifact.get("artifact") or "simurgh_openapi_tool_candidates"),
        "artifact_path": display_path(artifact_path),
        "source": dict(artifact.get("source") or {}),
        "policy": dict(artifact.get("policy") or {}),
        "summary": summarize_tool_candidates(raw_candidates, registry=registry),
        "candidate_count": len(raw_candidates),
        "filtered_count": len(filtered_candidates),
        "returned_count": len(candidates),
        "offset": safe_offset,
        "limit": safe_limit,
        "filters": {
            "eligible_read_only": eligible_read_only,
            "risk_class": risk_class or "",
            "search": search or "",
        },
        "candidates": candidates,
    }

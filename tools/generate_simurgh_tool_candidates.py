#!/usr/bin/env python3
"""Generate non-callable Simurgh tool candidates from an OpenAPI schema.

This generator is intentionally advisory. Its output is not loaded by the
runtime registry and must not make routes callable. It gives reviewers a stable,
diff-friendly menu of API capabilities to classify before promotion into
`config/agent_tools.yaml`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

import yaml
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "agent-context" / "generated" / "simurgh-openapi-tool-candidates.yaml"
DEFAULT_REGISTRY = REPO_ROOT / "config" / "agent_tools.yaml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
UNSAFE_PATH_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"/api/v1/drone(?:/|$)", "direct drone route"),
    (r"/api/logs/drone(?:/|$)", "drone-local log route"),
    (r"/api/logs/stream(?:/|$)", "log streaming route"),
    (r"/api/v1/auth(?:/|$)", "auth/admin route"),
    (r"/api/v1/system/env/.*/apply", "environment mutation route"),
    (r"/api/v1/fleet/git-sync/(?:apply|dry-run)", "deployment sync route"),
    (r"/api/v1/system/sitl/instances", "SITL lifecycle route"),
    (r"/api/sar/mission/.*/handoff", "mission handoff route"),
    (r"/api/sar/mission/launch", "mission launch route"),
    (r"/(?:stream|download|downloads|export|plots?|images?)(?:/|$)", "stream/download/binary artifact route"),
    (r"(?:download-kml|/kml(?:/|$)|/content(?:/|$))", "raw artifact content route"),
)
MANUAL_UNSAFE_ROUTE_REASONS: dict[tuple[str, str], tuple[str, ...]] = {
    ("GET", "/api/v1/shows/skybrush/metrics"): (
        "read-through cache refresh can write state",
    ),
    ("GET", "/api/v1/shows/custom/preview"): (
        "stream/download/binary artifact route",
    ),
}
SENSITIVE_TAGS: tuple[tuple[str, str], ...] = (
    ("fleet", "fleet_identity"),
    ("telemetry", "location"),
    ("network", "topology"),
    ("logs", "logs"),
    ("git", "repository"),
    ("auth", "identity"),
    ("env", "configuration"),
    ("config", "configuration"),
    ("show", "mission_state"),
    ("swarm", "mission_state"),
    ("sar", "mission_state"),
    ("origin", "location"),
)


def stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def schema_hash(schema: Mapping[str, Any]) -> str:
    return hashlib.sha256(stable_json(schema).encode("utf-8")).hexdigest()


def tool_id_for(method: str, path: str) -> str:
    stem = path.strip("/") or "root"
    stem = stem.replace("{", "by_").replace("}", "")
    stem = re.sub(r"[^A-Za-z0-9]+", ".", stem).strip(".").lower()
    return f"candidate.gcs.{method.lower()}.{stem}"


def route_key(method: str, path: str) -> tuple[str, str]:
    return (str(method).upper(), str(path))


def area_for_path(path: str, tags: list[str] | None = None) -> str:
    lowered = path.lower()
    if lowered.startswith("/api/sar"):
        return "sar"
    if lowered.startswith("/api/logs"):
        return "logs"
    if lowered.startswith("/api/v1/shows"):
        return "drone_show"
    if lowered.startswith("/api/v1/swarm-trajectories"):
        return "swarm_trajectory"
    if lowered.startswith("/api/v1/system/sitl"):
        return "sitl"
    if lowered.startswith("/api/v1/system/env"):
        return "environment"
    if lowered.startswith("/api/v1/system") or lowered in {"/health", "/ping"}:
        return "system"
    if lowered.startswith("/api/v1/fleet"):
        return "fleet"
    if lowered.startswith("/api/v1/config"):
        return "configuration"
    if lowered.startswith("/api/v1/origin") or lowered.startswith("/api/v1/navigation"):
        return "origin"
    if lowered.startswith("/api/v1/px4-params"):
        return "px4_params"
    if lowered.startswith("/api/v1/simurgh"):
        return "simurgh"
    if lowered.startswith("/api/v1/commands"):
        return "commands"
    if lowered.startswith("/api/v1/auth"):
        return "auth"
    tag_text = " ".join(tags or []).lower()
    for area in ("fleet", "logs", "show", "swarm", "sar", "sitl", "simurgh"):
        if area in tag_text:
            return "drone_show" if area == "show" else ("swarm_trajectory" if area == "swarm" else area)
    return "other"


def normalize_parameter(parameter: Mapping[str, Any]) -> dict[str, Any]:
    schema = parameter.get("schema") if isinstance(parameter.get("schema"), Mapping) else {}
    return {
        "name": str(parameter.get("name") or ""),
        "in": str(parameter.get("in") or ""),
        "required": bool(parameter.get("required", False)),
        "schema": dict(schema),
        "description": str(parameter.get("description") or ""),
    }


def infer_sensitivity(path: str, tags: list[str]) -> list[str]:
    haystack = " ".join([path, *tags]).lower()
    values = []
    for needle, sensitivity in SENSITIVE_TAGS:
        if needle in haystack and sensitivity not in values:
            values.append(sensitivity)
    return values


def response_content_types(operation: Mapping[str, Any]) -> list[str]:
    responses = operation.get("responses") if isinstance(operation.get("responses"), Mapping) else {}
    content_types: list[str] = []
    for response in responses.values():
        if not isinstance(response, Mapping):
            continue
        content = response.get("content") if isinstance(response.get("content"), Mapping) else {}
        for content_type in content:
            value = str(content_type).lower()
            if value not in content_types:
                content_types.append(value)
    return sorted(content_types)


def unsafe_reasons(method: str, path: str, operation: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if method.lower() != "get":
        reasons.append("non_get_method")
        if re.search(r"/api/v1/commands(?:/|$)", path):
            reasons.append("command/control route")
    if "requestBody" in operation:
        reasons.append("request_body_present")
    for pattern, reason in UNSAFE_PATH_PATTERNS:
        if re.search(pattern, path):
            reasons.append(reason)
    reasons.extend(MANUAL_UNSAFE_ROUTE_REASONS.get((method.upper(), path), ()))
    content_types = response_content_types(operation)
    if content_types and "application/json" not in content_types:
        reasons.append("non_json_response")
    if "text/event-stream" in content_types:
        reasons.append("streaming_response")
    operation_id = str(operation.get("operationId") or "").lower()
    summary = str(operation.get("summary") or "").lower()
    combined = f"{path} {operation_id} {summary}".lower()
    for word in ("delete", "erase", "launch", "takeoff", "land", "reboot", "apply", "sync", "token", "login", "stream", "download", "export"):
        if word in combined:
            reasons.append(f"keyword:{word}")
    return sorted(set(reasons))


def infer_risk(method: str, path: str, operation: Mapping[str, Any], reasons: list[str]) -> str:
    if method.lower() != "get":
        return "admin" if any("auth" in reason or "env" in reason for reason in reasons) else "operate"
    if reasons:
        return "sensitive_observe"
    sensitivity = infer_sensitivity(path, [str(tag) for tag in operation.get("tags") or []])
    return "sensitive_observe" if sensitivity else "observe"


def build_candidate(method: str, path: str, operation: Mapping[str, Any]) -> dict[str, Any]:
    tags = [str(tag) for tag in operation.get("tags") or []]
    params = [normalize_parameter(param) for param in operation.get("parameters") or [] if isinstance(param, Mapping)]
    reasons = unsafe_reasons(method, path, operation)
    eligible = method.lower() == "get" and "requestBody" not in operation and not reasons
    response_schema = {}
    responses = operation.get("responses") if isinstance(operation.get("responses"), Mapping) else {}
    ok_response = responses.get("200") or responses.get(200) or {}
    if isinstance(ok_response, Mapping):
        content = ok_response.get("content") if isinstance(ok_response.get("content"), Mapping) else {}
        json_content = content.get("application/json") if isinstance(content.get("application/json"), Mapping) else {}
        if isinstance(json_content.get("schema"), Mapping):
            response_schema = dict(json_content["schema"])

    candidate = {
        "id": tool_id_for(method, path),
        "review_status": "needs_review",
        "callable": False,
        "source": {
            "method": method.upper(),
            "path": path,
            "operation_id": str(operation.get("operationId") or ""),
            "summary": str(operation.get("summary") or ""),
            "tags": tags,
        },
        "classification": {
            "eligible_read_only_mcp_candidate": eligible,
            "recommended_registry_exposure": "candidate_allow_after_review" if eligible else "candidate_exclude_or_guard_after_review",
            "default_registry_exposure": "exclude",
            "inferred_risk_class": infer_risk(method, path, operation, reasons),
            "inferred_sensitivity": infer_sensitivity(path, tags),
            "review_reasons": reasons or ["manual_review_required_before_registry_promotion"],
        },
        "parameters": params,
        "has_request_body": "requestBody" in operation,
        "response_schema": response_schema,
        "registry_candidate": {
            "default_exposure": "exclude",
            "default_callable": False,
            "reviewed_registry_entry_required": True,
        },
        "promotion_contract": {
            "loaded_by_default_registry": False,
            "requires_human_review": True,
            "requires_policy_review": True,
            "requires_tests": True,
            "requires_docs": True,
        },
    }
    return candidate


def load_registry_routes(path: Path = DEFAULT_REGISTRY) -> dict[tuple[str, str], list[dict[str, Any]]]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tools = payload.get("tools") if isinstance(payload, Mapping) else []
    routes: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, Mapping):
            continue
        route = tool.get("route") if isinstance(tool.get("route"), Mapping) else {}
        method = str(route.get("method") or "").upper()
        route_path = str(route.get("path") or "")
        if not method or not route_path:
            continue
        routes.setdefault(route_key(method, route_path), []).append(
            {
                "id": str(tool.get("id") or ""),
                "exposure": str(tool.get("exposure") or ""),
                "read_only": bool(tool.get("read_only", False)),
                "risk_class": str(tool.get("risk_class") or ""),
                "boundary": str(tool.get("boundary") or ""),
            }
        )
    return routes


def registry_coverage_summary(
    candidates: list[dict[str, Any]],
    registry_routes: Mapping[tuple[str, str], list[dict[str, Any]]] | None,
    *,
    registry_path: Path | None = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    registry_routes = registry_routes or {}
    eligible = [item for item in candidates if item["classification"]["eligible_read_only_mcp_candidate"]]
    promoted: list[dict[str, Any]] = []
    unpromoted: list[dict[str, Any]] = []
    for item in eligible:
        source = item["source"]
        key = route_key(source["method"], source["path"])
        tools = [
            tool
            for tool in registry_routes.get(key, [])
            if tool.get("read_only") and tool.get("exposure") in {"allow", "guarded"}
        ]
        row = {
            "method": key[0],
            "path": key[1],
            "area": area_for_path(key[1], source.get("tags") or []),
            "candidate_id": item["id"],
        }
        if tools:
            promoted.append({**row, "tool_ids": sorted(tool["id"] for tool in tools if tool.get("id"))})
        else:
            unpromoted.append(row)

    by_area: dict[str, list[dict[str, Any]]] = {}
    for row in unpromoted:
        by_area.setdefault(row["area"], []).append(row)
    unpromoted_by_area = [
        {
            "area": area,
            "count": len(rows),
            "routes": sorted({f"{row['method']} {row['path']}" for row in rows}),
        }
        for area, rows in sorted(by_area.items())
    ]
    eligible_count = len(eligible)
    promoted_count = len(promoted)
    registry_label = ""
    if registry_path is not None:
        try:
            registry_label = registry_path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            registry_label = registry_path.as_posix()
    return {
        "registry_path": registry_label,
        "registry_route_count": len(registry_routes),
        "eligible_read_only_candidate_count": eligible_count,
        "promoted_eligible_candidate_count": promoted_count,
        "unpromoted_eligible_candidate_count": len(unpromoted),
        "promoted_eligible_ratio": round(promoted_count / eligible_count, 4) if eligible_count else 1.0,
        "unpromoted_eligible_by_area": unpromoted_by_area,
    }


def build_candidates(
    openapi_schema: Mapping[str, Any],
    *,
    registry_routes: Mapping[tuple[str, str], list[dict[str, Any]]] | None = None,
    registry_path: Path | None = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    candidates = []
    paths = openapi_schema.get("paths") if isinstance(openapi_schema.get("paths"), Mapping) else {}
    for path, methods in paths.items():
        if not isinstance(methods, Mapping):
            continue
        for method, operation in methods.items():
            if str(method).lower() not in HTTP_METHODS or not isinstance(operation, Mapping):
                continue
            candidates.append(build_candidate(str(method), str(path), operation))
    candidates.sort(key=lambda item: item["id"])
    schema_info = openapi_schema.get("info") if isinstance(openapi_schema.get("info"), Mapping) else {}
    return {
        "schema_version": 1,
        "artifact": "simurgh_openapi_tool_candidates",
        "summary": {
            "registry_coverage": registry_coverage_summary(candidates, registry_routes, registry_path=registry_path),
        },
        "source": {
            "title": str(schema_info.get("title") or ""),
            "version": str(schema_info.get("version") or ""),
            "openapi": str(openapi_schema.get("openapi") or ""),
            "openapi_sha256": schema_hash(openapi_schema),
        },
        "policy": {
            "runtime_loaded": False,
            "default_callable": False,
            "promotion_path": "candidate -> config/agent_tools.yaml -> config/agent_policy.yaml -> tests -> docs -> reviewer approval",
            "adapter_note": "Generated candidates are independent of FastAPI-MCP/FastMCP/MCPify so the adapter can be swapped without changing MDS policy semantics.",
        },
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def load_openapi_schema(path: Path | None) -> dict[str, Any]:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(REPO_ROOT / "gcs-server"))
    sys.path.insert(0, str(REPO_ROOT / "src"))
    sys.path.insert(0, str(REPO_ROOT))
    from app_fastapi import app  # pylint: disable=import-outside-toplevel

    return app.openapi()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openapi-file", type=Path, default=None, help="Read OpenAPI JSON from a file instead of importing app_fastapi.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output candidate JSON path.")
    parser.add_argument(
        "--registry-file",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Reviewed Simurgh tool registry used only for coverage reporting.",
    )
    parser.add_argument("--check", action="store_true", help="Fail if the output file is not current.")
    args = parser.parse_args(argv)

    schema = load_openapi_schema(args.openapi_file)
    registry_routes = load_registry_routes(args.registry_file)
    artifact = build_candidates(schema, registry_routes=registry_routes, registry_path=args.registry_file)
    if args.output.suffix.lower() in {".yaml", ".yml"}:
        rendered = yaml.safe_dump(artifact, sort_keys=True, allow_unicode=False, width=100)
    else:
        rendered = json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n"

    if args.check:
        existing = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if existing != rendered:
            print(f"{args.output} is not current", file=sys.stderr)
            return 1
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.output} ({artifact['candidate_count']} candidates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

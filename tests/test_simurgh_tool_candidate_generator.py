from __future__ import annotations

import importlib.util

import yaml
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPO_ROOT / "tools" / "generate_simurgh_tool_candidates.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_simurgh_tool_candidates", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _schema() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1"},
        "paths": {
            "/api/v1/system/health": {
                "get": {
                    "operationId": "health",
                    "tags": ["system"],
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
            "/api/logs/sessions/{session_id}": {
                "get": {
                    "operationId": "get_log_session",
                    "tags": ["logs"],
                    "parameters": [
                        {"name": "session_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
                    ],
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
            "/api/v1/commands": {
                "post": {
                    "operationId": "submit_command",
                    "tags": ["commands"],
                    "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/api/logs/stream": {
                "get": {
                    "operationId": "stream_logs",
                    "tags": ["logs"],
                    "responses": {"200": {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
                }
            },
            "/api/v1/swarm-trajectories/download-kml/{drone_id}": {
                "get": {
                    "operationId": "download_kml",
                    "tags": ["swarm"],
                    "responses": {"200": {"content": {"application/vnd.google-earth.kml+xml": {"schema": {"type": "string"}}}}},
                }
            },
            "/api/v1/auth/tokens": {
                "get": {
                    "operationId": "list_tokens",
                    "tags": ["auth"],
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/api/v1/shows/skybrush/metrics": {
                "get": {
                    "operationId": "get_comprehensive_metrics",
                    "tags": ["Show Management"],
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
            "/api/v1/shows/skybrush/metrics/snapshot": {
                "get": {
                    "operationId": "get_metrics_snapshot",
                    "tags": ["Show Management"],
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
            "/api/v1/shows/skybrush/safety-report": {
                "get": {
                    "operationId": "get_safety_report",
                    "tags": ["Show Management"],
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
            "/api/v1/shows/custom/preview": {
                "get": {
                    "operationId": "get_custom_show_image",
                    "tags": ["Show Management"],
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
        },
    }


def test_openapi_candidate_generation_is_deterministic_and_non_callable():
    generator = _load_generator()

    first = generator.build_candidates(_schema())
    second = generator.build_candidates(_schema())

    assert first == second
    assert first["policy"]["runtime_loaded"] is False
    assert first["policy"]["default_callable"] is False
    assert first["candidate_count"] == 10
    assert all(candidate["callable"] is False for candidate in first["candidates"])
    assert all(candidate["review_status"] == "needs_review" for candidate in first["candidates"])


def test_openapi_candidate_generation_classifies_safe_and_unsafe_routes():
    generator = _load_generator()
    artifact = generator.build_candidates(_schema())
    by_path = {candidate["source"]["path"]: candidate for candidate in artifact["candidates"]}

    health = by_path["/api/v1/system/health"]
    assert health["classification"]["eligible_read_only_mcp_candidate"] is True
    assert health["classification"]["recommended_registry_exposure"] == "candidate_allow_after_review"
    assert health["classification"]["default_registry_exposure"] == "exclude"
    assert health["registry_candidate"] == {
        "default_exposure": "exclude",
        "default_callable": False,
        "reviewed_registry_entry_required": True,
    }
    assert health["classification"]["review_reasons"] == ["manual_review_required_before_registry_promotion"]

    logs = by_path["/api/logs/sessions/{session_id}"]
    assert logs["classification"]["eligible_read_only_mcp_candidate"] is True
    assert logs["classification"]["inferred_sensitivity"] == ["logs"]
    assert [(item["name"], item["in"]) for item in logs["parameters"]] == [("session_id", "path"), ("limit", "query")]

    command = by_path["/api/v1/commands"]
    assert command["classification"]["eligible_read_only_mcp_candidate"] is False
    assert "non_get_method" in command["classification"]["review_reasons"]
    assert "request_body_present" in command["classification"]["review_reasons"]
    assert "command/control route" in command["classification"]["review_reasons"]

    stream = by_path["/api/logs/stream"]
    assert stream["classification"]["eligible_read_only_mcp_candidate"] is False
    assert "log streaming route" in stream["classification"]["review_reasons"]
    assert "non_json_response" in stream["classification"]["review_reasons"]

    kml = by_path["/api/v1/swarm-trajectories/download-kml/{drone_id}"]
    assert kml["classification"]["eligible_read_only_mcp_candidate"] is False
    assert "raw artifact content route" in kml["classification"]["review_reasons"]

    auth = by_path["/api/v1/auth/tokens"]
    assert auth["classification"]["eligible_read_only_mcp_candidate"] is False
    assert "auth/admin route" in auth["classification"]["review_reasons"]

    metrics = by_path["/api/v1/shows/skybrush/metrics"]
    assert metrics["classification"]["eligible_read_only_mcp_candidate"] is False
    assert "read-through cache refresh can write state" in metrics["classification"]["review_reasons"]

    metrics_snapshot = by_path["/api/v1/shows/skybrush/metrics/snapshot"]
    assert metrics_snapshot["classification"]["eligible_read_only_mcp_candidate"] is True

    safety_report = by_path["/api/v1/shows/skybrush/safety-report"]
    assert safety_report["classification"]["eligible_read_only_mcp_candidate"] is True

    custom_preview = by_path["/api/v1/shows/custom/preview"]
    assert custom_preview["classification"]["eligible_read_only_mcp_candidate"] is False
    assert "stream/download/binary artifact route" in custom_preview["classification"]["review_reasons"]


def test_openapi_candidate_generation_reports_registry_coverage():
    generator = _load_generator()
    registry_routes = {
        ("GET", "/api/v1/system/health"): [
            {"id": "mds.system.health.read", "exposure": "allow", "read_only": True}
        ],
        ("GET", "/api/v1/shows/skybrush/metrics/snapshot"): [
            {"id": "mds.shows.skybrush.metrics_snapshot.read", "exposure": "allow", "read_only": True}
        ],
        ("GET", "/api/v1/shows/skybrush/safety-report"): [
            {"id": "mds.shows.skybrush.safety_report.read", "exposure": "guarded", "read_only": True}
        ],
    }

    artifact = generator.build_candidates(
        _schema(),
        registry_routes=registry_routes,
        registry_path=Path("config/agent_tools.yaml"),
    )
    coverage = artifact["summary"]["registry_coverage"]

    assert coverage["registry_path"] == "config/agent_tools.yaml"
    assert coverage["registry_route_count"] == 3
    assert coverage["eligible_read_only_candidate_count"] == 4
    assert coverage["promoted_eligible_candidate_count"] == 3
    assert coverage["unpromoted_eligible_candidate_count"] == 1
    assert coverage["promoted_eligible_ratio"] == 0.75
    assert coverage["unpromoted_eligible_by_area"] == [
        {
            "area": "logs",
            "count": 1,
            "routes": ["GET /api/logs/sessions/{session_id}"],
        }
    ]


def test_generated_candidate_artifact_is_review_only_and_current():
    generator = _load_generator()
    artifact_path = REPO_ROOT / "docs" / "agent-context" / "generated" / "simurgh-openapi-tool-candidates.yaml"

    artifact = yaml.safe_load(artifact_path.read_text(encoding="utf-8"))

    assert artifact["policy"]["runtime_loaded"] is False
    assert artifact["policy"]["default_callable"] is False
    assert artifact["candidate_count"] == len(artifact["candidates"])
    assert artifact["candidate_count"] > 100
    coverage = artifact["summary"]["registry_coverage"]
    assert coverage["registry_path"] == "config/agent_tools.yaml"
    assert coverage["eligible_read_only_candidate_count"] > 0
    assert coverage["promoted_eligible_candidate_count"] > 0
    assert coverage["unpromoted_eligible_candidate_count"] >= 0
    assert 0 < coverage["promoted_eligible_ratio"] <= 1
    assert isinstance(coverage["unpromoted_eligible_by_area"], list)
    assert all(candidate["callable"] is False for candidate in artifact["candidates"])
    assert all(candidate["registry_candidate"]["default_exposure"] == "exclude" for candidate in artifact["candidates"])
    assert generator.main(["--check"]) == 0

    by_path = {candidate["source"]["path"]: candidate for candidate in artifact["candidates"]}
    assert by_path["/api/v1/commands"]["classification"]["eligible_read_only_mcp_candidate"] is False
    assert "command/control route" in by_path["/api/v1/commands"]["classification"]["review_reasons"]
    assert by_path["/api/logs/sessions/{session_id}"]["classification"]["eligible_read_only_mcp_candidate"] is True
    assert by_path["/api/logs/stream"]["classification"]["eligible_read_only_mcp_candidate"] is False
    assert by_path["/api/v1/swarm-trajectories/download-kml/{drone_id}"]["classification"]["eligible_read_only_mcp_candidate"] is False
    assert by_path["/api/v1/shows/skybrush/metrics/snapshot"]["classification"]["eligible_read_only_mcp_candidate"] is True
    assert by_path["/api/v1/shows/skybrush/safety-report"]["classification"]["eligible_read_only_mcp_candidate"] is True
    assert by_path["/api/v1/shows/skybrush/validation"]["classification"]["eligible_read_only_mcp_candidate"] is True
    assert by_path["/api/v1/shows/skybrush/metrics"]["classification"]["eligible_read_only_mcp_candidate"] is False
    assert "read-through cache refresh can write state" in by_path["/api/v1/shows/skybrush/metrics"]["classification"]["review_reasons"]
    assert by_path["/api/v1/shows/skybrush/archives/raw"]["classification"]["eligible_read_only_mcp_candidate"] is False
    assert by_path["/api/v1/shows/skybrush/archives/processed"]["classification"]["eligible_read_only_mcp_candidate"] is False
    assert by_path["/api/v1/shows/skybrush/plots"]["classification"]["eligible_read_only_mcp_candidate"] is False
    assert by_path["/api/v1/shows/skybrush/plots/{filename}"]["classification"]["eligible_read_only_mcp_candidate"] is False
    assert by_path["/api/v1/shows/custom/preview"]["classification"]["eligible_read_only_mcp_candidate"] is False

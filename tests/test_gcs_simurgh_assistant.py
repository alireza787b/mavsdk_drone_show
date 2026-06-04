from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_runtime import AgentRuntimeError, OpenAIResponsesAssistantAdapter
from agent_runtime.assistant import _provider_tool_composition_message
from api_routes.simurgh import create_simurgh_router


@pytest.fixture(autouse=True)
def _assistant_history_file(monkeypatch, tmp_path):
    path = tmp_path / "assistant_turns.jsonl"
    monkeypatch.setenv("MDS_AGENT_ASSISTANT_HISTORY_FILE", str(path))
    return path


def _client(auth_context=None) -> TestClient:
    app = FastAPI()
    if auth_context is not None:
        @app.middleware("http")
        async def _inject_auth_context(request, call_next):  # noqa: ANN001
            request.state.mds_auth_context = auth_context
            return await call_next(request)

    app.include_router(create_simurgh_router())
    return TestClient(app)


def _client_with_registry_probe_routes(auth_context=None) -> TestClient:
    app = FastAPI()
    if auth_context is not None:
        @app.middleware("http")
        async def _inject_auth_context(request, call_next):  # noqa: ANN001
            request.state.mds_auth_context = auth_context
            return await call_next(request)

    @app.get("/api/v1/system/sitl/instances")
    def sitl_instances():
        return {"total_instances": 1, "instances": [{"id": "sim-1", "state": "running"}]}

    @app.get("/api/v1/system/sitl/policy")
    def sitl_policy():
        return {"enabled": True, "max_instances": 4}

    @app.get("/api/v1/system/sitl/host")
    def sitl_host():
        return {"host": "test-sitl-host", "available": True}

    @app.get("/api/sar/missions")
    def sar_missions():
        return {"count": 1, "missions": [{"mission_id": "sar-1", "status": "draft", "finding_count": 0}]}

    @app.get("/api/logs/sessions/{session_id}")
    def log_session(session_id: str, limit: int, level: str | None = None):
        return {
            "session_id": session_id,
            "limit": limit,
            "level": level,
            "entries": [
                {"level": level or "WARNING", "component": "api", "message": "probe warning"},
            ],
        }

    @app.get("/api/logs/sessions")
    def log_sessions():
        return {"sessions": [{"session_id": "s_20260527_174402", "line_count": 42, "latest_level": "WARNING"}]}

    @app.get("/api/v1/fleet/sidecars/{sidecar}")
    def sidecar_table(sidecar: str):
        return {"sidecar": sidecar, "nodes": [{"hw_id": "2", "state": "online"}]}

    @app.get("/api/v1/fleet/sidecars")
    def sidecars_summary():
        return {"sidecars": ["smart-wifi-manager", "mavlink-anywhere"], "node_count": 2}

    @app.get("/api/v1/fleet/network-status")
    def fleet_network_status():
        return {"online": 2, "offline": 0}

    @app.get("/api/v1/fleet/network-details")
    def fleet_network_details():
        return {"links": [{"hw_id": "2", "transport": "netbird", "state": "online"}]}

    @app.get("/api/v1/fleet/sidecars/connectivity/profile")
    def sidecar_connectivity_profile():
        return {"profile": "test-overlay-profile", "required_ports": [9070, 9080]}

    @app.get("/api/v1/fleet/sidecars/{sidecar}/nodes/{hw_id}")
    def sidecar_node(sidecar: str, hw_id: str):
        return {"sidecar": sidecar, "hw_id": hw_id, "state": "online", "remote_url": "http://example.invalid"}

    @app.get("/api/v1/origin/elevation")
    def origin_elevation(lat: float, lon: float):
        return {"lat": lat, "lon": lon, "elevation_m": 1234.5}

    @app.get("/api/v1/origin/bootstrap")
    def origin_bootstrap():
        return {"bootstrap_ready": True, "source": "configured"}

    @app.get("/api/v1/swarm-trajectories/policy")
    def swarm_trajectory_policy():
        return {"max_drones": 16, "requires_validation": True}

    @app.get("/api/v1/swarm-trajectories/recommendation")
    def swarm_trajectory_recommendation():
        return {"recommendation": "validate-before-dispatch", "ready": False}

    app.include_router(create_simurgh_router())
    return TestClient(app)


def _write_restricted_key(path, value="test-openai-key\n"):
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def _parse_sse_events(body: str):
    events = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip() or "message"
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        if data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def test_simurgh_assistant_turn_requires_enabled_agent(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "false")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Explain Simurgh status."},
    )

    assert response.status_code == 403
    assert "disabled" in response.json()["detail"]


def test_simurgh_assistant_turn_creates_mock_session_and_audit(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Can you arm drone 1?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mock"
    assert payload["session"]["id"].startswith("session-")
    assert "arm" in payload["blocked_intents"]
    assert payload["context_resources"]
    assert all("content_hash" in resource for resource in payload["context_resources"])
    assert "No provider SDK was called." in payload["safety_notes"]

    sessions = client.get("/api/v1/simurgh/sessions").json()["sessions"]
    assert [session["id"] for session in sessions] == [payload["session"]["id"]]

    audit_events = client.get("/api/v1/simurgh/audit").json()["events"]
    assert [event["event_type"] for event in audit_events] == ["assistant_turn_created"]
    assert audit_events[0]["payload_hash"]
    assert audit_events[0]["metadata"]["provider"] == "mock"
    assert "drone 1" not in str(audit_events[0])

    history = client.get("/api/v1/simurgh/assistant/turns", params={"actor": "operator"}).json()["turns"]
    assert [turn["id"] for turn in history] == [payload["id"]]
    assert history[0]["message"] == ""
    assert history[0]["content"] == ""
    assert history[0]["message_hash"]
    assert history[0]["model"] == "mock-local"
    assert history[0]["adapter_version"] == "mock-v1"


def test_simurgh_assistant_turn_trace_exposes_read_only_plan(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "what is their battery and gps health?"},
    )

    assert response.status_code == 200
    plan = response.json()["trace"]["query"]["read_only_plan"]
    assert plan["intent"] == "fleet_connectivity"
    assert plan["execution_layer"] == "local_advisory"
    assert "mds.fleet.telemetry.read" in plan["tool_ids"]
    assert "message" not in plan
    assert "normalized_message" not in plan


def test_simurgh_assistant_turn_streams_progress_delta_final_and_history(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    with client.stream(
        "POST",
        "/api/v1/simurgh/assistant/turns/stream",
        json={"actor": "operator", "message": "How many drones do we have configured?"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = _parse_sse_events(body)
    event_names = [event for event, _payload in events]
    assert event_names[:3] == ["progress", "progress", "progress"]
    assert "delta" in event_names
    assert "final" in event_names
    assert event_names[-1] == "done"
    progress_labels = [payload["label"] for event, payload in events if event == "progress"]
    assert "Understanding request" in progress_labels
    assert "Streaming answer" in progress_labels
    streamed_content = "".join(payload["text"] for event, payload in events if event == "delta")
    final_payload = next(payload for event, payload in events if event == "final")
    assert final_payload["provider"] == "mds-tools"
    assert "configured drone" in streamed_content.lower()
    assert streamed_content == final_payload["content"]

    history = client.get("/api/v1/simurgh/assistant/turns", params={"actor": "operator"}).json()["turns"]
    assert [turn["id"] for turn in history] == [final_payload["id"]]


def test_simurgh_assistant_stream_reports_specific_registry_tool_progress(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client_with_registry_probe_routes()

    with client.stream(
        "POST",
        "/api/v1/simurgh/assistant/turns/stream",
        json={"actor": "operator", "message": "show mavlink-anywhere sidecar node for drone 2 now"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _parse_sse_events(body)
    tool_progress = [payload for event, payload in events if event == "progress" and payload.get("stage") == "tool"]
    assert tool_progress
    assert tool_progress[-1]["label"] == "Using read-only MDS tool: Read fleet sidecar node"
    assert tool_progress[-1]["tool_ids"] == ["mds.fleet.sidecar.node.read"]
    final_payload = next(payload for event, payload in events if event == "final")
    assert final_payload["trace"]["tool"]["ids"] == ["mds.fleet.sidecar.node.read"]


def test_simurgh_assistant_turn_can_use_existing_session(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    session = client.post("/api/v1/simurgh/sessions", json={"actor": "operator"}).json()
    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": session["id"],
            "message": "Summarize safety policy.",
            "context_resource_ids": ["simurgh.safety_policy"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["id"] == session["id"]
    assert [resource["id"] for resource in payload["context_resources"]] == ["simurgh.safety_policy"]


def test_simurgh_assistant_turn_rejects_cross_actor_session_reuse(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    session = client.post("/api/v1/simurgh/sessions", json={"actor": "operator-a"}).json()
    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator-b",
            "session_id": session["id"],
            "message": "Summarize safety policy.",
        },
    )

    assert response.status_code == 403
    assert "different actor" in response.json()["detail"]


def test_simurgh_assistant_turn_rejects_oversized_metadata(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Summarize safety policy.",
            "metadata": {"blob": "x" * 5000},
        },
    )

    assert response.status_code == 400
    assert "metadata exceeds" in response.json()["detail"]


def test_simurgh_assistant_turn_does_not_reflect_raw_metadata_to_sessions(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Summarize safety policy.",
            "metadata": {
                "source": "simurgh-dashboard",
                "raw_prompt": "CM4-99 stopped streaming on 192.168.1.10",
            },
        },
    )

    assert response.status_code == 200
    sessions = client.get("/api/v1/simurgh/sessions").json()["sessions"]
    assert sessions[0]["metadata"] == {"channel": "assistant", "source": "simurgh-dashboard"}


def test_simurgh_assistant_turn_rejects_sensitive_metadata_source(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Summarize safety policy.",
            "metadata": {
                "source": "CM4-99",
            },
        },
    )

    assert response.status_code == 200
    session = response.json()["session"]
    assert session["metadata"] == {"channel": "assistant"}
    serialized = str(client.get("/api/v1/simurgh/sessions").json())
    assert "CM4-99" not in serialized


def test_simurgh_assistant_history_filters_by_actor(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    client.post("/api/v1/simurgh/assistant/turns", json={"actor": "operator-a", "message": "A question."})
    client.post("/api/v1/simurgh/assistant/turns", json={"actor": "operator-b", "message": "B question."})

    history = client.get("/api/v1/simurgh/assistant/turns", params={"actor": "operator-b"}).json()["turns"]
    assert [turn["actor"] for turn in history] == ["operator-b"]
    assert history[0]["message"] == ""
    assert history[0]["message_hash"]


def test_simurgh_router_startup_survives_corrupt_history_file(monkeypatch, _assistant_history_file):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    _assistant_history_file.write_text("{not json}\n", encoding="utf-8")

    client = _client()

    status = client.get("/api/v1/simurgh/status")
    history = client.get("/api/v1/simurgh/assistant/turns", params={"actor": "operator"})
    assert status.status_code == 200
    assert history.status_code == 500
    assert "invalid record" in history.json()["detail"]


def test_simurgh_assistant_turn_rejects_unknown_context(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Summarize a missing context.",
            "context_resource_ids": ["missing.resource"],
        },
    )

    assert response.status_code == 404


def test_simurgh_assistant_turn_rejects_external_provider_without_auth(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 403
    assert "require MDS auth" in response.json()["detail"]


def test_simurgh_assistant_turn_allows_local_mds_tool_answer_without_external_provider_auth(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "How many drones do we have configured?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["model"] == "local-read-only"
    assert "configured drone" in payload["content"].lower()
    assert "No direct drone API" in payload["safety_notes"][1]
    assert payload["trace"]["query"]["domain"] == "fleet"
    assert payload["trace"]["tool"]["intent"] == "fleet_summary"
    assert payload["trace"]["language"]["language"] == "en"
    assert "How many drones" not in str(payload["trace"])


def test_simurgh_assistant_turn_composes_local_tool_evidence_with_openai_when_authenticated(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        captured["api_key"] = api_key
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "You have 2 configured drones in the GCS fleet. I used the read-only fleet evidence only; no drone command was sent.",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client(auth_context={"kind": "session", "role": "operator", "username": "operator"})

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "How many drones do we have configured?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert payload["trace"]["tool"]["intent"] == "fleet_summary"
    assert payload["trace"]["context"]["retrieved_context_count"] == 1
    assert "2 configured drones" in payload["content"]
    assert "read-only" in payload["safety_notes"][0].lower()
    assert captured["api_key"] == "test-openai-key"
    assert captured["tools"] == []
    assert captured["tool_choice"] == "none"
    assert "session.read_only_mds_evidence" in str(captured["input"])
    assert "Fleet status from GCS configuration" in str(captured["input"])


def test_simurgh_assistant_turn_composes_previous_evidence_followup_when_authenticated(monkeypatch, tmp_path):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools

    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fake_recent_warning_events(self, **_kwargs):  # noqa: ANN001
        return (
            [
                {
                    "ts": "2026-05-26T08:51:00Z",
                    "level": "WARNING",
                    "source": "/var/log/mds-gcs.log",
                    "message": "08:51:00 WARNING [api] API GET /api/v1/commands/active -> 401 (0.001s)",
                }
            ],
            ["/var/log/mds-gcs.log"],
        )

    captured: list[dict[str, object]] = []

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.append({"payload": payload, "api_key": api_key})
        payload_text = str(payload.get("input") or "")
        if "Conversation task: assess_previous_evidence" in payload_text:
            text = "No, that specific previous result does not look like a flight-control fault. It points to API auth polling, so verify dashboard/session auth only if an operator workflow is failing."
        else:
            text = "The recent GCS log scan found one HTTP 401 authorization warning and no drone command was sent."
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}

    monkeypatch.setattr(MdsReadOnlyTools, "_recent_warning_events", fake_recent_warning_events)
    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client(auth_context={"kind": "session", "role": "operator", "username": "operator"})

    first = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "check latest logs tell me whats going on"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["provider"] == "openai"
    assert first_payload["trace"]["tool"]["intent"] == "backend_log_summary"

    followup = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": first_payload["session"]["id"],
            "message": "does this mean something is wrong?",
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["provider"] == "openai"
    assert payload["trace"]["tool"]["intent"] == "evidence_followup"
    assert payload["trace"]["query"]["response_mode"] == "followup"
    assert payload["trace"]["context"]["retrieved_context_count"] == 2
    assert "does not look like a flight-control fault" in payload["content"]
    assert "Backend warning/error summary" not in payload["content"]
    assert len(captured) == 2
    followup_input = str(captured[-1]["payload"]["input"])
    assert captured[-1]["api_key"] == "test-openai-key"
    assert captured[-1]["payload"]["tools"] == []
    assert captured[-1]["payload"]["tool_choice"] == "none"
    assert "session.previous_assistant_answer" in followup_input
    assert "session.previous_read_only_mds_evidence" in followup_input


def test_simurgh_assistant_turn_sources_registry_previous_evidence_when_authenticated(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    captured: list[dict[str, object]] = []

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.append({"payload": payload, "api_key": api_key})
        payload_text = str(payload.get("input") or "")
        if "Conversation task: source_previous_evidence" in payload_text:
            text = "I used the previous read-only registry evidence: `mds.fleet.sidecar.read`, API `GET /api/v1/fleet/sidecars/mavlink-anywhere`, and docs `docs/guides/fleet-ops.md` plus `docs/apis/gcs-api-server.md`. No fresh check was performed."
        else:
            text = "The mavlink-anywhere sidecar table was checked through the read-only registry/MCP adapter."
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client_with_registry_probe_routes(
        auth_context={"kind": "session", "role": "operator", "username": "operator"}
    )

    first = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "show mavlink-anywhere sidecar table now"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["trace"]["tool"]["intent"] == "registry_read_execution"
    assert first_payload["trace"]["tool"]["ids"] == ["mds.fleet.sidecar.read"]

    followup = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": first_payload["session"]["id"],
            "message": "what API/source did you use and where can I check it?",
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["provider"] == "openai"
    assert payload["trace"]["tool"]["intent"] == "evidence_followup"
    assert payload["trace"]["query"]["response_mode"] == "followup"
    assert "mds.fleet.sidecar.read" in payload["content"]
    assert "/api/v1/fleet/sidecars/mavlink-anywhere" in payload["content"]
    evidence = payload["trace"]["tool"]["evidence"]
    assert evidence["source_refs"][0]["tool_id"] == "mds.fleet.sidecar.read"
    assert evidence["source_refs"][0]["route_path"] == "/api/v1/fleet/sidecars/mavlink-anywhere"
    assert "docs/guides/fleet-ops.md" in evidence["source_refs"][0]["docs"]
    assert len(captured) == 2
    followup_input = str(captured[-1]["payload"]["input"])
    assert captured[-1]["api_key"] == "test-openai-key"
    assert "Conversation task: source_previous_evidence" in followup_input
    assert "source_refs" in followup_input
    assert "/api/v1/fleet/sidecars/mavlink-anywhere" in followup_input
    assert "docs/apis/gcs-api-server.md" in followup_input


def test_simurgh_assistant_capability_question_after_evidence_is_not_source_followup(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    captured: list[dict[str, object]] = []

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        if captured:
            raise AssertionError("new capability/menu questions must not be treated as previous-source follow-ups")
        captured.append({"payload": payload, "api_key": api_key})
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "The mavlink-anywhere sidecar table was checked through the read-only registry/MCP adapter.",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client_with_registry_probe_routes(
        auth_context={"kind": "session", "role": "operator", "username": "operator"}
    )

    first = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "show mavlink-anywhere sidecar table now"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["trace"]["tool"]["intent"] == "registry_read_execution"
    assert len(captured) == 1

    followup = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": first_payload["session"]["id"],
            "message": "what read-only APIs/tools can Simurgh use for SITL status?",
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["intent"] == "registry_domain_tool_summary"
    assert payload["trace"]["query"]["response_mode"] == "capability"
    assert "Registry-backed read-only capability summary" in payload["content"]
    assert "mds.sitl.instances.read" in payload["content"]
    assert len(captured) == 1


def test_simurgh_assistant_registry_domain_menu_stays_local_when_authenticated(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fail_post(self, payload, *, api_key):  # noqa: ANN001
        raise AssertionError("registry-domain capability menus should not wait on provider composition")

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fail_post)
    client = _client(auth_context={"kind": "session", "role": "operator", "username": "operator"})

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "what can you inspect about SAR and QuickScout mission status?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["intent"] == "registry_domain_tool_summary"
    assert "mds.sar.mission.status.read" in payload["content"]
    assert "This answer only describes the approved capability surface" in payload["content"]


def test_simurgh_assistant_executes_registry_read_only_sitl_state(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client_with_registry_probe_routes()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "what SITL instances are running now and what policy is configured?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["intent"] == "registry_read_execution"
    assert payload["trace"]["tool"]["ids"] == ["mds.sitl.instances.read", "mds.sitl.policy.read"]
    assert "Read-only registry check for SITL runtime state" in payload["content"]
    assert "mds.sitl.instances.read" in payload["content"]
    assert "total_instances: 1" in payload["content"]
    assert "MCP `tools/call`" in payload["content"]
    assert "| Tool |" not in payload["content"]
    evidence = payload["trace"]["tool"]["evidence"]
    assert evidence["intent"] == "registry_read_execution"
    assert evidence["source"] == "registry_read_only_mds"
    assert "mds.sitl.instances.read" in evidence["tool_ids"]
    assert "SITL runtime state" in evidence["summary"]

    audit_events = client.get("/api/v1/simurgh/audit").json()["events"]
    assert audit_events[0]["metadata"]["read_only_evidence"]["content_hash"] == evidence["content_hash"]


@pytest.mark.parametrize(
    ("message", "expected_ids", "expected_text"),
    [
        (
            "what SITL host is configured now?",
            ["mds.sitl.host.read", "mds.sitl.instances.read", "mds.sitl.policy.read"],
            "host: test-sitl-host",
        ),
        (
            "show fleet network details now",
            ["mds.fleet.network_details.read", "mds.fleet.network_status.read"],
            "transport=netbird",
        ),
        (
            "what sidecar connectivity profile is configured now?",
            ["mds.fleet.sidecars.connectivity_profile.read", "mds.fleet.sidecars.read", "mds.fleet.network_status.read"],
            "profile: test-overlay-profile",
        ),
        (
            "what origin bootstrap status is configured now?",
            ["mds.origin.bootstrap.read", "mds.origin.read", "mds.origin.deviations.read", "mds.navigation.global_origin.read"],
            "bootstrap_ready: True",
        ),
        (
            "what swarm trajectory policy and recommendation are available now?",
            ["mds.swarm_trajectories.policy.read", "mds.swarm_trajectories.recommendation.read", "mds.swarm_trajectories.status.read", "mds.swarm_trajectories.validate.read"],
            "recommendation: validate-before-dispatch",
        ),
    ],
)
def test_simurgh_assistant_metadata_ranker_supplements_registry_domain_tools(
    monkeypatch,
    message,
    expected_ids,
    expected_text,
):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client_with_registry_probe_routes()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["intent"] == "registry_read_execution"
    assert payload["trace"]["tool"]["ids"] == expected_ids
    assert payload["trace"]["query"]["read_only_plan"]["selection_source"] in {
        "metadata_ranker",
        "domain_rules+metadata_ranker",
    }
    assert expected_text in payload["content"]


def test_simurgh_assistant_prefers_docs_workflow_over_registry_state(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client_with_registry_probe_routes()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Can you check the docs for SITL setup?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["intent"] == "sitl_help"
    assert "advanced SITL" in payload["content"]
    assert "Read-only registry check for SITL runtime state" not in payload["content"]


def test_simurgh_assistant_uses_discovery_when_typed_log_session_id_missing(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client_with_registry_probe_routes()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "read log session details"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["intent"] == "registry_read_execution"
    assert payload["trace"]["tool"]["ids"] == ["mds.logs.sessions.read"]
    plan = payload["trace"]["query"]["read_only_plan"]
    assert plan["intent"] == "registry_read_execution"
    assert plan["execution_layer"] == "registry_read_adapter"
    assert plan["tool_ids"] == ["mds.logs.sessions.read"]
    assert plan["missing_arguments"] == ["session_id"]
    assert "message" not in plan
    assert "I need one more identifier" in payload["content"]
    assert "Choose a session_id" in payload["content"]
    assert "s_20260527_174402" in payload["content"]
    assert "Backend warning/error summary" not in payload["content"]


def test_simurgh_assistant_uses_discovery_when_typed_sidecar_node_id_missing(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client_with_registry_probe_routes()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "show smart wifi manager sidecar node now"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["intent"] == "registry_read_execution"
    assert payload["trace"]["tool"]["ids"] == ["mds.fleet.sidecars.read", "mds.fleet.network_status.read"]
    assert "Choose both sidecar and hw_id" in payload["content"]
    assert "sidecars: 2 item(s)" in payload["content"]


def test_simurgh_assistant_executes_registry_read_only_sar_catalog(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client_with_registry_probe_routes()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "what QuickScout SAR missions are available right now?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["session"]["metadata"]["last_domain"] == "sar"
    assert payload["trace"]["tool"]["intent"] == "registry_read_execution"
    assert payload["trace"]["tool"]["ids"] == ["mds.sar.missions.read"]
    assert "Read-only registry check for QuickScout/SAR mission catalog" in payload["content"]
    assert "count: 1" in payload["content"]
    assert "mission_id=sar-1" in payload["content"]
    assert payload["trace"]["tool"]["evidence"]["source"] == "registry_read_only_mds"


def test_simurgh_assistant_executes_registry_read_only_typed_sidecar_node(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client_with_registry_probe_routes()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "show mavlink-anywhere sidecar node for drone 2 now"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["intent"] == "registry_read_execution"
    assert payload["trace"]["tool"]["ids"] == ["mds.fleet.sidecar.node.read"]
    assert "sidecar=mavlink-anywhere" in payload["content"]
    assert "hw_id=2" in payload["content"]
    assert "state: online" in payload["content"]


def test_simurgh_assistant_composes_registry_evidence_with_openai_when_authenticated(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        captured["api_key"] = api_key
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Drone 2 sidecar evidence says mavlink-anywhere is online. No drone command was sent.",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client_with_registry_probe_routes(
        auth_context={"kind": "session", "role": "operator", "username": "operator"}
    )

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "show mavlink-anywhere sidecar node for drone 2 now"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert payload["trace"]["tool"]["intent"] == "registry_read_execution"
    assert payload["trace"]["tool"]["ids"] == ["mds.fleet.sidecar.node.read"]
    assert payload["trace"]["tool"]["evidence"]["source"] == "registry_read_only_mds"
    assert payload["trace"]["context"]["retrieved_context_count"] == 1
    assert "mavlink-anywhere is online" in payload["content"]
    assert captured["api_key"] == "test-openai-key"
    assert captured["tools"] == []
    assert captured["tool_choice"] == "none"
    assert "session.read_only_mds_evidence" in str(captured["input"])
    assert "state: online" in str(captured["input"])


def test_simurgh_assistant_falls_back_to_no_argument_sidecar_tools_when_typed_id_missing(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client_with_registry_probe_routes()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "show fleet sidecars now"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["ids"] == ["mds.fleet.sidecars.read", "mds.fleet.network_status.read"]
    assert "Read-only registry check for fleet sidecar and board connectivity state" in payload["content"]
    assert "one fleet sidecar table" not in payload["content"]
    assert "sidecars: 2 item(s)" in payload["content"]


def test_simurgh_assistant_executes_registry_read_only_typed_log_session(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client_with_registry_probe_routes()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "read log session s_20260527_174402 limit 10 warnings"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["ids"] == ["mds.logs.session.read"]
    assert "session_id=s_20260527_174402" in payload["content"]
    assert "limit=10" in payload["content"]
    assert "level=WARNING" in payload["content"]
    assert "entries: 1 item(s)" in payload["content"]
    assert "level=WARNING" in payload["content"]
    assert "component=api" in payload["content"]
    assert "probe warning" not in payload["content"]


def test_simurgh_assistant_executes_registry_read_only_typed_elevation(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client_with_registry_probe_routes()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "check terrain elevation for lat 35.95 lon 52.11 now"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["tool"]["ids"] == ["mds.origin.elevation.read"]
    assert "lat=35.95" in payload["content"]
    assert "lon=52.11" in payload["content"]
    assert "elevation_m: 1234.5" in payload["content"]


def test_provider_tool_composition_message_has_safe_fallback_labels():
    message = _provider_tool_composition_message(
        operator_message="status?",
        tool_intent="",
        response_mode="",
    )

    assert "Read-only tool intent: unknown." in message
    assert "Response mode: status." in message


def test_simurgh_assistant_turn_uses_adapted_routing_for_local_auth_gate(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client()

    first = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "wat droens are connected?"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["provider"] == "mds-tools"
    assert first_payload["trace"]["tool"]["intent"] == "fleet_connectivity"

    followup = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": first_payload["session"]["id"],
            "message": "can you report any warnign if exist last 30 minutes in gcs?",
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["query"]["domain"] == "logs"
    assert payload["trace"]["tool"]["intent"] == "backend_log_summary"
    assert "Simurgh capabilities" not in payload["content"]


def test_simurgh_assistant_turn_explicit_fleet_prompt_overrides_log_session_topic(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client()

    first = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "check last 1 hour logs is there anything I need to know?"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["trace"]["tool"]["intent"] == "backend_log_summary"

    followup = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": first_payload["session"]["id"],
            "message": "what is the current flee status and info?",
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["query"]["domain"] == "fleet"
    assert payload["trace"]["tool"]["intent"] == "fleet_summary"
    assert "Fleet status from GCS configuration" in payload["content"]
    assert "Backend warning/error summary" not in payload["content"]


def test_simurgh_assistant_turn_answers_general_questions_without_inheriting_fleet_topic(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client()

    first = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "wat droens are connected?"},
    )
    assert first.status_code == 200
    session_id = first.json()["session"]["id"]

    for message, expected, blocked in (
        ("what is a drone?", "unmanned aircraft", "Fleet status from GCS configuration"),
        ("what is mavlink?", "MAVLink", "Connectivity from GCS state"),
        ("how is the weather today?", "do not have a live weather feed", "Fleet status from GCS configuration"),
    ):
        response = client.post(
            "/api/v1/simurgh/assistant/turns",
            json={"actor": "operator", "session_id": session_id, "message": message},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["provider"] == "mds-tools"
        assert payload["trace"]["tool"]["intent"] == "general_knowledge"
        assert expected in payload["content"]
        assert blocked not in payload["content"]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("is there any drone connected?", "Connectivity from GCS state"),
        ("what formation swarm is defined for drones and what are the clusters?", "Configured/planned swarm geometry"),
        ("from where I can edit the swarm offsets?", "/swarm-design"),
        ("what drone show is loaded? what is the length of drone show?", "Loaded show state"),
    ],
)
def test_simurgh_assistant_turn_answers_pm_read_only_prompts(monkeypatch, message, expected):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert expected in payload["content"]
    assert "No direct drone API" in payload["safety_notes"][1]


def test_simurgh_assistant_turn_routes_multilingual_local_prompt_with_adaptation_trace(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Combien de drones sont configurés maintenant ?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["language"]["language"] == "fr"
    assert payload["trace"]["adaptation"]["routing_language"] == "en"
    assert payload["trace"]["adaptation"]["strategy"] == "config-governed-cross-language-routing"
    assert payload["trace"]["query"]["domain"] == "fleet"
    assert payload["trace"]["tool"]["intent"] == "fleet_summary"
    assert "Combien" not in str(payload["trace"])


def test_simurgh_assistant_turn_uses_session_topic_for_local_followup_without_provider_auth(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client()

    first = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "what drone show is planned now?"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["provider"] == "mds-tools"
    assert first_payload["session"]["metadata"]["last_domain"] == "drone_show"

    followup = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": first_payload["session"]["id"],
            "message": "is there any uploaded?",
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["provider"] == "mds-tools"
    assert "Loaded show state" in payload["content"]
    assert "I can’t see uploads from here" not in payload["content"]


def test_simurgh_assistant_turn_interprets_log_followup_without_provider_auth(monkeypatch):
    from agent_runtime.mds_read_tools import MdsReadOnlyTools

    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    def fake_recent_warning_events(self, **_kwargs):  # noqa: ANN001
        return (
            [
                {
                    "ts": "2026-05-26T08:51:00Z",
                    "level": "WARNING",
                    "source": "/var/log/mds-gcs.log",
                    "message": "08:51:00 WARNING [api] API GET /api/v1/commands/active -> 401 (0.001s)",
                }
            ],
            ["/var/log/mds-gcs.log"],
        )

    monkeypatch.setattr(MdsReadOnlyTools, "_recent_warning_events", fake_recent_warning_events)
    client = _client()

    first = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "check backend logs and report anything worth mentioning"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["provider"] == "mds-tools"
    assert first_payload["session"]["metadata"]["last_domain"] == "logs"

    followup = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": first_payload["session"]["id"],
            "message": "what does it mean?",
        },
    )

    assert followup.status_code == 200
    payload = followup.json()
    assert payload["provider"] == "mds-tools"
    assert "Operational interpretation of backend warnings" in payload["content"]
    assert "HTTP authorization warnings" in payload["content"]
    assert "Most recent entries:" not in payload["content"]


@pytest.mark.parametrize(
    "auth_context",
    [
        {"kind": "session", "role": "viewer", "username": "viewer"},
        {"kind": "bearer", "role": "operator", "username": "drone-token", "scopes": ["drone"]},
        {"kind": "bearer", "role": "viewer", "username": "viewer-token", "scopes": ["viewer"]},
    ],
)
def test_simurgh_assistant_turn_rejects_external_provider_without_operator_or_agent_scope(
    monkeypatch,
    tmp_path,
    auth_context,
):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    provider_called = False

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        nonlocal provider_called
        provider_called = True
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Provider answer."}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client(auth_context=auth_context)

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 403
    assert "agent, operator, or admin scope" in response.json()["detail"]
    assert provider_called is False


@pytest.mark.parametrize(
    "auth_context",
    [
        {"kind": "session", "role": "operator", "username": "operator"},
        {"kind": "session", "role": "admin", "username": "admin"},
        {"kind": "bearer", "role": "operator", "username": "agent-token", "scopes": ["agent"]},
        {"kind": "bearer", "role": "operator", "username": "operator-token", "scopes": ["operator"]},
        {"kind": "bearer", "role": "admin", "username": "admin-token", "scopes": ["admin"]},
    ],
)
def test_simurgh_assistant_turn_allows_external_provider_for_operator_or_agent_scope(
    monkeypatch,
    tmp_path,
    auth_context,
):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Provider answer."}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client(auth_context=auth_context)

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "openai"


def test_simurgh_assistant_turn_uses_openai_provider_with_safe_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))
    captured: dict[str, object] = {}

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        captured.update(payload)
        captured["api_key"] = api_key
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Provider answer."}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client(auth_context={"kind": "session", "role": "operator", "username": "operator"})

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-5.5"
    assert payload["adapter_version"] == "openai-responses-v1"
    assert payload["content"] == "Provider answer."
    assert captured["api_key"] == "test-openai-key"
    assert captured["store"] is False
    assert captured["tools"] == []
    assert captured["tool_choice"] == "none"

    audit_event = client.get("/api/v1/simurgh/audit").json()["events"][0]
    assert audit_event["metadata"]["provider"] == "openai"
    assert "test-openai-key" not in str(audit_event)
    assert "Use a provider" not in str(audit_event)

    history = client.get("/api/v1/simurgh/assistant/turns", params={"actor": "operator"}).json()["turns"]
    assert history[0]["model"] == "gpt-5.5"
    assert history[0]["adapter_version"] == "openai-responses-v1"


def test_simurgh_assistant_turn_trace_profiles_non_english_provider_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fake_post(self, payload, *, api_key):  # noqa: ANN001
        assert "Detected language: fr" in str(payload["input"])
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Réponse."}]}]}

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fake_post)
    client = _client(auth_context={"kind": "session", "role": "operator", "username": "operator"})

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Combien de pages Simurgh sont utiles maintenant ?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert payload["trace"]["language"]["language"] == "fr"
    assert payload["trace"]["language"]["localization_strategy"] == "same-language-provider-response"
    assert payload["trace"]["safety"]["action_execution"] == "none"
    assert "Combien de drones" not in str(payload["trace"])


def test_simurgh_assistant_turn_returns_safe_openai_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    api_key_file = _write_restricted_key(tmp_path / "openai_api_key", "test-secret-should-not-leak\n")
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(api_key_file))

    def fail_post(self, payload, *, api_key):  # noqa: ANN001
        raise AgentRuntimeError("OpenAI assistant request failed with HTTP 500")

    monkeypatch.setattr(OpenAIResponsesAssistantAdapter, "_post_response", fail_post)
    client = _client(auth_context={"kind": "session", "role": "operator", "username": "operator"})

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert "could not reach the external assistant provider" in payload["content"].lower()
    assert "HTTP 500" not in payload["content"]
    assert "test-secret" not in str(response.json())


def test_simurgh_assistant_turn_rejects_unsupported_provider(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "anthropic")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Use a provider."},
    )

    assert response.status_code == 501
    assert "not implemented" in response.json()["detail"]

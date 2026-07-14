from __future__ import annotations

import asyncio
import json
import os
import re
import time
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from agent_runtime.action_planner import FlightActionDraft
from agent_runtime.action_intent import ProviderActionPlan, ProviderActionStep
from agent_runtime.action_runs import ActionRunStore
from agent_runtime.assistant import ProviderSemanticRewrite
from agent_runtime.tool_executor import GuardedToolCallResult
from api_routes.simurgh import (
    SimurghAssistantTurnRequest,
    _submitted_action_progress_outcome,
    create_simurgh_router,
)


@pytest.fixture(autouse=True)
def _isolated_action_run_store(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ACTION_RUN_DB", str(tmp_path / "action-runs.sqlite3"))


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_simurgh_router())
    return TestClient(app)


def _provider_step(
    message: str,
    excerpt: str,
    *,
    tool_id: str,
    arguments: dict,
    condition: str = "start",
    label: str = "Action",
    monitor_requested: bool = True,
) -> ProviderActionStep:
    start = message.index(excerpt)
    return ProviderActionStep(
        kind="tool",
        tool_id=tool_id,
        arguments=arguments,
        delay_seconds=None,
        condition=condition,
        monitor_requested=monitor_requested,
        label=label,
        source_start=start,
        source_end=start + len(excerpt),
        source_excerpt=excerpt,
    )


def _provider_delay(message: str, excerpt: str, seconds: float) -> ProviderActionStep:
    start = message.index(excerpt)
    return ProviderActionStep(
        kind="delay",
        tool_id="",
        arguments={},
        delay_seconds=seconds,
        condition="after_command_terminal_success",
        monitor_requested=False,
        label=f"Wait {seconds:g} seconds",
        source_start=start,
        source_end=start + len(excerpt),
        source_excerpt=excerpt,
    )


def _provider_rewrite(
    *,
    normalized_message: str,
    route_hint: str,
    action_plan: ProviderActionPlan | None = None,
    confidence: float = 0.96,
    needs_clarification: bool = False,
    clarification_question: str = "",
) -> ProviderSemanticRewrite:
    return ProviderSemanticRewrite(
        normalized_message=normalized_message,
        language="en",
        route_hint=route_hint,
        confidence=confidence,
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
        action_plan=action_plan,
        model="test",
        adapter_version="test-semantic-rewrite",
    )


def _wait_for_action_run(client: TestClient, response_payload: dict, timeout: float = 3.0) -> dict:
    run_id = response_payload["trace"]["safety"]["action_run"]["run_id"]
    deadline = time.monotonic() + timeout
    latest = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/simurgh/action-runs/{run_id}")
        assert response.status_code == 200
        latest = response.json()
        if latest.get("terminal"):
            return latest
        time.sleep(0.01)
    raise AssertionError(f"action run {run_id} did not reach terminal state: {latest}")


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = "message"
    data_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if data_lines:
                events.append((event_name, json.loads("\n".join(data_lines))))
            event_name = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    if data_lines:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def test_sequence_progress_outcome_reflects_terminal_results():
    draft = FlightActionDraft(
        draft_id="act-sequence",
        mission_name="TAKE_OFF",
        mission_type=10,
        target_drone_ids=("1",),
        command_payload={"mission_type": 10, "target_drone_ids": ["1"]},
        monitor_requested=True,
        post_actions=(
            {"type": "delay", "action_label": "wait"},
            {"type": "flight_command", "action_label": "return rtl"},
        ),
    )

    assert _submitted_action_progress_outcome(
        draft,
        monitor_result={"success": True, "timed_out": False},
        post_action_results=(
            {"status": "completed", "is_error": False},
            {"status": "terminal_success", "is_error": False},
        ),
    ) == ("complete", "Command sequence complete")
    assert _submitted_action_progress_outcome(
        draft,
        monitor_result={"success": False, "timed_out": True},
    ) == ("timeout", "Command sequence monitoring timed out")
    assert _submitted_action_progress_outcome(
        draft,
        monitor_result={"success": False, "timed_out": False},
    ) == ("failed", "Command sequence stopped after primary command")
    assert _submitted_action_progress_outcome(
        draft,
        monitor_result={"success": True, "timed_out": False},
        post_action_results=(
            {"status": "terminal_non_success", "is_error": True},
            {"status": "skipped", "is_error": True},
        ),
    ) == ("failed", "Command sequence stopped before all steps completed")
    assert _submitted_action_progress_outcome(
        draft,
        monitor_result={"success": True, "timed_out": False},
        post_action_results=(
            {"status": "completed", "is_error": False},
            {
                "status": "terminal_success",
                "is_error": True,
                "completion_verification": {"status": "unavailable", "verified": False},
            },
        ),
    ) == ("failed", "Command sequence stopped before all steps completed")


def test_simurgh_status_enables_non_executing_runtime_by_default_and_uses_repo_relative_paths(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "real")
    client = _client()

    response = client.get("/api/v1/simurgh/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_enabled"] is True
    assert payload["mcp_enabled"] is False
    assert payload["gcs_mode"] == "real"
    assert payload["gcs_mode_source"] == "env:MDS_MODE"
    assert payload["mode"] == "real"
    assert payload["actions_blocked"] is True
    assert payload["action_policy_source"] == "circuit_breaker_and_mds_mode"
    assert payload["action_circuit_breaker_enabled"] is True
    assert payload["always_confirm_before_action"] is True
    assert payload["tool_count"] >= 20
    assert payload["allowed_tool_count"] > 0
    assert payload["excluded_tool_count"] > 0
    assert payload["assistant_provider"] == "mock"
    assert payload["assistant_model"] == "mock-local"
    assert payload["assistant_external_provider"] is False
    assert payload["assistant_external_provider_auth_required"] is False
    assert payload["policy_path"] == "config/agent_policy.yaml"
    assert payload["tool_registry_path"] == "config/agent_tools.yaml"
    assert payload["context_index_path"] == "docs/agent-context/context-index.yaml"
    assert payload["warnings"] == []


def test_simurgh_action_run_routes_replay_and_control_actor_owned_runs():
    store = ActionRunStore(os.environ["MDS_AGENT_ACTION_RUN_DB"])
    run, created = store.create_or_get(
        actor="dashboard",
        session_id="sess-action-run",
        draft_id="act-route-test",
        plan_hash="plan-route-test",
        plan={
            "draft_id": "act-route-test",
            "display_plan": {
                "title": "Test flight",
                "target": "Drone 1",
                "steps": [{"index": 1, "kind": "flight_command", "label": "Take off"}],
            },
        },
        total_steps=1,
    )
    assert created is True
    started = store.append_event(
        run.run_id,
        event_type="run_started",
        payload={"state": "running", "label": "Starting", "step_index": 1, "step_count": 1},
        state="running",
        current_step=1,
    )
    app = FastAPI()
    app.include_router(create_simurgh_router(SimpleNamespace(simurgh_action_run_store=store)))
    client = TestClient(app)

    listed = client.get(
        "/api/v1/simurgh/action-runs",
        params={"actor": "dashboard", "active_only": "true"},
    )
    assert listed.status_code == 200
    assert [item["run_id"] for item in listed.json()["runs"]] == [run.run_id]

    replay = client.get(
        f"/api/v1/simurgh/action-runs/{run.run_id}/events",
        params={"after": started.id - 1},
    )
    assert replay.status_code == 200
    assert replay.json()["events"][0]["event_type"] == "run_started"

    paused = client.post(
        f"/api/v1/simurgh/action-runs/{run.run_id}/controls",
        json={
            "actor": "dashboard",
            "action": "pause_after_current_step",
            "control_id": "ctl-route-pause",
        },
    )
    assert paused.status_code == 200
    assert paused.json()["state"] == "pause_requested"

    forbidden = client.post(
        f"/api/v1/simurgh/action-runs/{run.run_id}/controls",
        json={"actor": "other", "action": "cancel_remaining"},
    )
    assert forbidden.status_code == 403


def test_simurgh_action_run_list_uses_authenticated_actor_identity():
    store = ActionRunStore(os.environ["MDS_AGENT_ACTION_RUN_DB"])
    own_run, _ = store.create_or_get(
        actor="alice",
        session_id="sess-alice",
        draft_id="act-alice",
        plan_hash="plan-alice",
        plan={"draft_id": "act-alice"},
        total_steps=1,
    )
    store.create_or_get(
        actor="dashboard",
        session_id="sess-dashboard",
        draft_id="act-dashboard",
        plan_hash="plan-dashboard",
        plan={"draft_id": "act-dashboard"},
        total_steps=1,
    )
    app = FastAPI()

    @app.middleware("http")
    async def authenticated_operator(request: Request, call_next):
        request.state.mds_auth_context = {
            "kind": "session",
            "username": "alice",
            "role": "admin",
        }
        return await call_next(request)

    app.include_router(create_simurgh_router(SimpleNamespace(simurgh_action_run_store=store)))
    client = TestClient(app)

    response = client.get(
        "/api/v1/simurgh/action-runs",
        params={"actor": "dashboard"},
    )

    assert response.status_code == 200
    assert [item["run_id"] for item in response.json()["runs"]] == [own_run.run_id]


def test_simurgh_action_run_stream_replays_terminal_snapshot():
    store = ActionRunStore(os.environ["MDS_AGENT_ACTION_RUN_DB"])
    run, _ = store.create_or_get(
        actor="dashboard",
        session_id="sess-stream-run",
        draft_id="act-stream-test",
        plan_hash="plan-stream-test",
        plan={"draft_id": "act-stream-test"},
        total_steps=1,
    )
    store.append_event(
        run.run_id,
        event_type="run_succeeded",
        payload={"state": "succeeded", "label": "Complete", "step_index": 1, "step_count": 1},
        state="succeeded",
        current_step=1,
        summary="Complete",
    )
    app = FastAPI()
    app.include_router(create_simurgh_router(SimpleNamespace(simurgh_action_run_store=store)))
    client = TestClient(app)

    response = client.get(f"/api/v1/simurgh/action-runs/{run.run_id}/events/stream")

    assert response.status_code == 200
    events = _sse_events(response.text)
    assert any(name == "run_succeeded" for name, _payload in events)
    terminal = [payload for name, payload in events if name == "run_snapshot"][-1]
    assert terminal["replay_complete"] is True
    assert terminal["run"]["state"] == "succeeded"


def test_simurgh_assistant_stream_emits_structured_activity_contract(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns/stream",
        json={"actor": "operator", "message": "what drones are connected right now?"},
    )

    assert response.status_code == 200
    events = _sse_events(response.text)
    progress_payloads = [payload for event, payload in events if event == "progress"]
    understanding = [
        payload
        for payload in progress_payloads
        if payload.get("stage") == "understanding" and payload.get("state") == "complete"
    ]
    assert understanding
    assert understanding[0]["domain"] == "fleet"
    assert understanding[0]["response_mode"] == "status"
    assert understanding[0]["label"].startswith(("Understood:", "Understanding:"))
    assert "fleet" in understanding[0]["label"].lower()
    assert any(payload.get("stage") in {"tool", "provider", "search"} for payload in progress_payloads)
    assert any(event == "delta" and payload.get("text") for event, payload in events)
    assert any(event == "final" and payload.get("trace") for event, payload in events)


@pytest.mark.asyncio
async def test_simurgh_completed_chat_request_does_not_cancel_accepted_sequence(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []
    wait_started = asyncio.Event()
    release_wait = asyncio.Event()

    class FakeTracker:
        async def get_status(self, command_id):
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
            }

    class FakeDeps:
        telemetry_data_all_drones = {
            "1": {
                "telemetry_available": True,
                "is_armed": False,
                "timestamp": int(time.time() * 1000),
            }
        }
        last_telemetry_time = {"1": time.time()}
        data_lock = None

        def get_all_heartbeats(self):
            return {"1": {"timestamp": int(time.time() * 1000)}}

        def get_command_tracker(self):
            return FakeTracker()

    async def fake_submit(_deps, command):
        submitted.append(command)
        return {
            "success": True,
            "command_id": f"cmd-{len(submitted)}",
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": str(command.mission_type),
            "target_drones": command.target_drone_ids,
            "results_summary": {"accepted": 1, "offline": 0, "rejected": 0, "errors": 0},
        }

    async def controlled_wait(_delay_seconds):
        wait_started.set()
        await release_wait.wait()

    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit)
    monkeypatch.setattr("api_routes.simurgh._sleep_action_sequence_delay", controlled_wait)

    app = FastAPI()
    action_run_store = ActionRunStore(os.environ["MDS_AGENT_ACTION_RUN_DB"])
    app.include_router(create_simurgh_router(SimpleNamespace(simurgh_action_run_store=action_run_store)))
    turn_endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/api/v1/simurgh/assistant/turns"
    )
    draft_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/simurgh/assistant/turns",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "root_path": "",
            "app": app,
        }
    )
    draft_response = await turn_endpoint(
        draft_request,
        SimurghAssistantTurnRequest(
            actor="operator",
            message="takeoff drone 1 to 10m, wait 5s, move 5m north, then RTL",
        ),
    )
    draft_payload = draft_response.model_dump(mode="json")
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    confirm_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/simurgh/assistant/turns",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "root_path": "",
            "app": app,
        }
    )
    response = await turn_endpoint(
        confirm_request,
        SimurghAssistantTurnRequest(
            actor="operator",
            session_id=draft_payload["session"]["id"],
            message=f"confirm action {draft_id}",
        ),
    )
    response_payload = response.model_dump(mode="json")
    assert "Action run started" in response_payload["content"]
    await asyncio.wait_for(wait_started.wait(), timeout=5.0)
    assert wait_started.is_set()
    assert [command.mission_type for command in submitted] == [10]

    release_wait.set()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        runs = action_run_store.list_runs(actor="operator")
        if len(submitted) == 3 and runs and runs[0].terminal:
            break
        await asyncio.sleep(0.01)

    assert [command.mission_type for command in submitted] == [10, 112, 104]
    runs = action_run_store.list_runs(actor="operator")
    assert len(runs) == 1
    assert runs[0].state == "succeeded"


@pytest.mark.asyncio
async def test_simurgh_conversational_cancel_targets_the_single_active_action_run(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []
    wait_started = asyncio.Event()
    release_wait = asyncio.Event()

    class FakeTracker:
        async def get_status(self, command_id):
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
            }

    class FakeDeps:
        telemetry_data_all_drones = {
            "1": {
                "telemetry_available": True,
                "is_armed": False,
                "timestamp": int(time.time() * 1000),
            }
        }
        last_telemetry_time = {"1": time.time()}
        data_lock = None

        def get_all_heartbeats(self):
            return {"1": {"timestamp": int(time.time() * 1000)}}

        def get_command_tracker(self):
            return FakeTracker()

    async def fake_submit(_deps, command):
        submitted.append(command)
        return {
            "success": True,
            "command_id": f"cmd-{len(submitted)}",
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": str(command.mission_type),
            "target_drones": command.target_drone_ids,
            "results_summary": {"accepted": 1, "offline": 0, "rejected": 0, "errors": 0},
        }

    async def controlled_wait(_delay_seconds):
        wait_started.set()
        await release_wait.wait()

    operator_request = "take off drone 1 to 10m, wait 5s, move 5m north, then RTL"

    def fake_rewrite_operator_message_with_provider(**kwargs):
        message = kwargs["message"]
        if message == operator_request:
            return _provider_rewrite(
                normalized_message="take off, wait, move north, then RTL",
                route_hint="draft_flight_action",
                action_plan=ProviderActionPlan(
                    summary="Run the requested test flight",
                    steps=(
                        _provider_step(
                            message,
                            "take off drone 1 to 10m",
                            tool_id="mds.flight.command.execute",
                            arguments={"mission_type": 10, "target_drone_ids": ["1"], "takeoff_altitude": 10},
                            label="Take off to 10 m",
                        ),
                        _provider_delay(message, "wait 5s", 5),
                        _provider_step(
                            message,
                            "move 5m north",
                            tool_id="mds.flight.command.execute",
                            arguments={
                                "mission_type": 112,
                                "precision_move": {
                                    "frame": "ned",
                                    "translation_m": {"north": 5, "east": 0, "up": 0},
                                },
                            },
                            condition="after_command_terminal_success",
                            label="Move 5 m north",
                        ),
                        _provider_step(
                            message,
                            "RTL",
                            tool_id="mds.flight.command.execute",
                            arguments={"mission_type": 104},
                            condition="after_command_terminal",
                            label="Return to launch",
                        ),
                    ),
                ),
            )
        if message.startswith("confirm action"):
            return _provider_rewrite(
                normalized_message=message,
                route_hint="confirm_pending_action",
            )
        return _provider_rewrite(
            normalized_message="cancel the active operation",
            route_hint="reject_pending_action",
        )

    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit)
    monkeypatch.setattr("api_routes.simurgh._sleep_action_sequence_delay", controlled_wait)
    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )

    app = FastAPI()
    action_run_store = ActionRunStore(os.environ["MDS_AGENT_ACTION_RUN_DB"])
    app.include_router(create_simurgh_router(SimpleNamespace(simurgh_action_run_store=action_run_store)))
    turn_endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/api/v1/simurgh/assistant/turns"
    )

    def request_scope():
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/simurgh/assistant/turns",
                "headers": [],
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("testclient", 50000),
                "root_path": "",
                "app": app,
            }
        )

    draft_response = await turn_endpoint(
        request_scope(),
        SimurghAssistantTurnRequest(actor="operator", message=operator_request),
    )
    draft_payload = draft_response.model_dump(mode="json")
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)
    confirm_response = await turn_endpoint(
        request_scope(),
        SimurghAssistantTurnRequest(
            actor="operator",
            session_id=draft_payload["session"]["id"],
            message=f"confirm action {draft_id}",
        ),
    )
    await asyncio.wait_for(wait_started.wait(), timeout=5.0)
    run_id = confirm_response.model_dump(mode="json")["trace"]["safety"]["action_run"]["run_id"]

    cancel_response = await turn_endpoint(
        request_scope(),
        SimurghAssistantTurnRequest(
            actor="operator",
            session_id=draft_payload["session"]["id"],
            message="stop the rest of it",
        ),
    )
    cancel_payload = cancel_response.model_dump(mode="json")

    assert "Cancelling the remaining steps" in cancel_payload["content"]
    assert cancel_payload["trace"]["safety"]["action_execution"] == "action_run_control"
    assert cancel_payload["trace"]["safety"]["action_run"]["run_id"] == run_id
    assert cancel_payload["trace"]["safety"]["action_run"]["state"] == "cancel_requested"

    release_wait.set()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if action_run_store.require(run_id).terminal:
            break
        await asyncio.sleep(0.01)
    assert action_run_store.require(run_id).state == "cancelled"
    assert [command.mission_type for command in submitted] == [10]


def test_simurgh_direct_takeoff_request_returns_guarded_action_draft(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Send drone 1 to takeoff to 10m and report when done"},
    )

    assert response.status_code == 200
    payload = response.json()
    content = payload["content"]
    assert "Review the guarded action plan" in content
    assert '"mission_type": 10' not in content
    assert "Circuit breaker: ON" in content
    assert "No action was executed" in content
    assert "Simurgh Operator mock assistant is active" not in content
    assert "Blocked intent signals" not in content
    assert payload["blocked_intents"] == []
    assert payload["trace"]["tool"]["id"] == "mds.flight.command.execute"
    assert payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"
    assert payload["trace"]["safety"]["action_draft"]["mission_name"] == "TAKE_OFF"
    assert payload["trace"]["safety"]["action_draft"]["command_payload"]["mission_type"] == 10
    assert payload["trace"]["safety"]["action_draft"]["command_payload"]["takeoff_altitude"] == 10.0
    assert payload["trace"]["safety"]["action_draft"]["display_plan"]["steps"][0]["label"] == "Take off to 10 m"


def test_simurgh_confirmed_action_stops_at_final_circuit_breaker(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Send drone 1 to takeoff to 10m"},
    )
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert "Circuit breaker stopped this at the final execution layer" in payload["content"]
    assert "would submit this guarded GCS action" in payload["content"]
    assert "No action was executed" in payload["content"]
    assert payload["blocked_intents"] == []
    assert payload["trace"]["safety"]["action_execution"] == "blocked_by_circuit_breaker"
    assert payload["trace"]["safety"]["policy_reasons"]


def test_simurgh_confirmed_action_submits_when_circuit_breaker_off(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_submit_tracked_command(_deps, command):
        submitted.append(command)
        return {
            "success": True,
            "command_id": "cmd-simurgh-1",
            "idempotency_key": command.idempotency_key,
            "replayed": False,
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": "TAKE_OFF",
            "target_drones": command.target_drone_ids,
            "submitted_count": 1,
            "message": "fake command accepted",
            "timestamp": 1,
            "results_summary": {"accepted": 1, "offline": 0, "rejected": 0, "errors": 0},
        }

    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    client = _client()

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Send drone 1 to takeoff to 10m"},
    )
    assert draft_response.status_code == 200
    assert submitted == []
    draft_payload = draft_response.json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert "Action run started" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "submitted"
    run = _wait_for_action_run(client, payload)
    assert run["state"] == "succeeded"
    assert run["result"]["action_response"]["command_id"] == "cmd-simurgh-1"
    assert len(submitted) == 1
    command = submitted[0]
    assert command.mission_type == 10
    assert command.target_drone_ids == ["1"]
    assert command.takeoff_altitude == 10.0
    assert command.idempotency_key == f"simurgh:{draft_id}"


def test_simurgh_sequence_post_actions_are_regated_before_dispatch(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    class FakeTracker:
        async def get_status(self, command_id):
            monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
            }

    class FakeDeps:
        def get_command_tracker(self):
            return FakeTracker()

    async def fake_submit(_deps, command):
        submitted.append(command)
        return {
            "success": True,
            "command_id": f"cmd-{len(submitted)}",
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": "TAKE_OFF",
            "target_drones": command.target_drone_ids,
            "results_summary": {"accepted": 1, "offline": 0, "rejected": 0, "errors": 0},
        }

    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit)
    client = _client()
    draft_payload = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "takeoff drone 1 to 10m then move 5m north"},
    ).json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    run = _wait_for_action_run(client, payload)
    assert len(submitted) == 1
    assert run["result"]["post_action_results"][0]["status"] == "blocked"
    assert run["result"]["post_action_results"][0]["is_error"] is True


def test_simurgh_sequence_post_action_idempotency_is_draft_stable(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    class FakeTracker:
        async def get_status(self, command_id):
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
            }

    class FakeDeps:
        def get_command_tracker(self):
            return FakeTracker()

    async def fake_submit(_deps, command):
        submitted.append(command)
        return {
            "success": True,
            "command_id": f"cmd-{len(submitted)}",
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": "TAKE_OFF" if command.mission_type == 10 else "PRECISION_MOVE",
            "target_drones": command.target_drone_ids,
            "results_summary": {"accepted": 1, "offline": 0, "rejected": 0, "errors": 0},
        }

    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit)
    client = _client()
    draft_payload = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "takeoff drone 1 to 10m then move 5m north"},
    ).json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)
    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert response.status_code == 200
    _wait_for_action_run(client, response.json())
    assert [command.idempotency_key for command in submitted] == [
        f"simurgh:{draft_id}",
        f"simurgh:{draft_id}:step:2",
    ]


def test_simurgh_rejects_oversized_wait_before_dispatch(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    monkeypatch.setenv("MDS_AGENT_SEQUENCE_MAX_WAIT_SEC", "30")
    submitted = []

    async def fake_submit(_deps, command):
        submitted.append(command)
        return {}

    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit)
    client = _client()
    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "takeoff drone 1 to 10m then wait 60s then RTL"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["safety"]["action_execution"] == "validation_rejected"
    assert "allows at most 30s" in payload["content"]
    assert submitted == []


def test_simurgh_bare_confirm_recovers_single_pending_action_after_lost_session(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_submit_tracked_command(_deps, command):
        submitted.append(command)
        return {
            "success": True,
            "command_id": "cmd-recovered-confirm",
            "idempotency_key": command.idempotency_key,
            "replayed": False,
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": "TAKE_OFF",
            "target_drones": command.target_drone_ids,
            "submitted_count": 1,
            "message": "fake command accepted",
            "timestamp": 1,
            "results_summary": {"accepted": 1, "offline": 0, "rejected": 0, "errors": 0},
        }

    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    client = _client()

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Send drone 1 to takeoff to 10m"},
    )
    assert draft_response.status_code == 200

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Confirm"},
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert "Action run started" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "submitted"
    run = _wait_for_action_run(client, payload)
    assert run["result"]["action_response"]["command_id"] == "cmd-recovered-confirm"
    assert len(submitted) == 1
    assert submitted[0].target_drone_ids == ["1"]


def test_simurgh_task_with_go_ahead_does_not_confirm_pending_action(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_submit_tracked_command(_deps, command):
        submitted.append(command)
        return {
            "success": True,
            "command_id": "cmd-should-not-run",
            "status": "submitted",
            "mission_type": command.mission_type,
            "target_drones": command.target_drone_ids,
            "results_summary": {"accepted": 1, "offline": 0, "rejected": 0, "errors": 0},
        }

    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    client = _client()

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Send drone 1 to takeoff to 10m"},
    )
    assert draft_response.status_code == 200
    session_id = draft_response.json()["session"]["id"]
    draft_id = re.search(r"act-[0-9a-f]+", draft_response.json()["content"]).group(0)

    read_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": session_id,
            "message": "go ahead and check SITL instances now",
        },
    )

    assert read_response.status_code == 200
    read_payload = read_response.json()
    assert read_payload["trace"]["safety"]["action_execution"] == "none"
    assert read_payload["trace"]["safety"]["action_execution"] == "none"
    assert read_payload["trace"]["intent"]["route"] == "read_only"
    assert read_payload["trace"]["intent"]["confirmation_message"] is False
    assert submitted == []

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": session_id,
            "message": f"confirm action {draft_id}",
        },
    )

    assert confirm_response.status_code == 200
    _wait_for_action_run(client, confirm_response.json())
    assert len(submitted) == 1


def test_simurgh_motion_status_question_does_not_create_action_draft(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_submit_tracked_command(_deps, command):
        submitted.append(command)
        return {"command_id": "cmd-should-not-run", "status": "submitted", "results_summary": {}}

    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "tell me if drone 1 should land"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "guarded action draft" not in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "none"
    assert payload["trace"]["intent"]["route"] != "action_draft"
    assert submitted == []


def test_simurgh_bare_confirm_without_pending_action_uses_live_policy_not_provider_context(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Confirm"},
    )

    assert response.status_code == 200
    payload = response.json()
    content = payload["content"]
    assert "I do not have a pending guarded action" in content
    assert "Circuit breaker: OFF" in content
    assert "Human confirmation: ON" in content
    assert "OpenAI answer ready" not in content
    assert "External provider calls are text-only" not in content
    assert "No action was executed" in content
    assert payload["provider"] == "mds-tools"
    assert payload["trace"]["safety"]["action_execution"] == "no_pending_confirmation"


def test_simurgh_bare_confirm_refuses_ambiguous_recent_pending_actions(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_submit_tracked_command(_deps, command):
        submitted.append(command)
        return {"command_id": "cmd-should-not-run", "status": "submitted", "results_summary": {}}

    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    client = _client()

    assert client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Send drone 1 to takeoff to 10m"},
    ).status_code == 200
    assert client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Create 1 sitl instance so I can test with"},
    ).status_code == 200

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Confirm"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "I found 2 recent pending guarded actions" in payload["content"]
    assert "confirm action <draft_id>" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "no_pending_confirmation"
    assert submitted == []


def test_simurgh_rejects_pending_action_without_execution(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_submit_tracked_command(_deps, command):
        submitted.append(command)
        return {"command_id": "cmd-should-not-run", "status": "submitted", "results_summary": {}}

    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    client = _client()

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Send drone 1 to takeoff to 10m"},
    )
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    reject_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"cancel action {draft_id}",
        },
    )

    assert reject_response.status_code == 200
    reject_payload = reject_response.json()
    assert "Cancelled the pending guarded action draft" in reject_payload["content"]
    assert reject_payload["trace"]["safety"]["action_execution"] == "cancelled_confirmation"
    assert submitted == []

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )
    assert confirm_response.status_code == 200
    assert "I do not have a pending guarded action" in confirm_response.json()["content"]
    assert submitted == []


def test_simurgh_followup_land_monitors_previous_drone_and_removes_sitl(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []
    post_actions = []

    class FakeTracker:
        async def get_status(self, command_id):
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
                "progress": {
                    "label": "Command completed",
                    "message": "Vehicle reached terminal success.",
                },
            }

    class FakeDeps:
        telemetry_data_all_drones = {
            "1": {
                "telemetry_available": True,
                "is_armed": False,
            }
        }
        last_telemetry_time = {"1": time.time()}

        def get_all_heartbeats(self):
            return {"1": {"timestamp": int(time.time() * 1000)}}

        def get_command_tracker(self):
            return FakeTracker()

    async def fake_submit_tracked_command(_deps, command):
        submitted.append(command)
        mission_name = "TAKE_OFF" if command.mission_type == 10 else "LAND"
        return {
            "success": True,
            "command_id": f"cmd-{mission_name.lower()}-{len(submitted)}",
            "idempotency_key": command.idempotency_key,
            "replayed": False,
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": mission_name,
            "target_drones": command.target_drone_ids,
            "submitted_count": len(command.target_drone_ids),
            "message": "fake command accepted",
            "timestamp": 1,
            "results_summary": {"accepted": len(command.target_drone_ids), "offline": 0, "rejected": 0, "errors": 0},
        }

    async def fake_guarded_route_tool(_request, *, name, arguments, channel, approved, registry, policy):
        post_actions.append(
            {
                "name": name,
                "arguments": arguments,
                "channel": channel,
                "approved": approved,
                "policy_mode": policy.mode,
            }
        )
        return GuardedToolCallResult(
            text="Removed SITL instance(s)",
            is_error=False,
            structured_content={
                "status": "succeeded",
                "summary": "Removed drone-1",
            },
            status_code=200,
        )

    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    client = _client()

    takeoff_draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Send drone 1 to takeoff to 10m and report when done"},
    )
    assert takeoff_draft_response.status_code == 200
    takeoff_draft_payload = takeoff_draft_response.json()
    takeoff_draft_id = re.search(r"act-[0-9a-f]+", takeoff_draft_payload["content"]).group(0)

    takeoff_confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": takeoff_draft_payload["session"]["id"],
            "message": f"confirm action {takeoff_draft_id}",
        },
    )
    assert takeoff_confirm_response.status_code == 200
    takeoff_confirm_payload = takeoff_confirm_response.json()
    assert "Action run started" in takeoff_confirm_payload["content"]
    takeoff_run = _wait_for_action_run(client, takeoff_confirm_payload)
    assert takeoff_run["state"] == "succeeded"
    assert takeoff_run["result"]["action_response"]["command_id"] == "cmd-take_off-1"

    land_draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": takeoff_draft_payload["session"]["id"],
            "message": "Now land the drone and once disarmed, report and remove the sitl instance clean it up",
        },
    )
    assert land_draft_response.status_code == 200
    land_draft_payload = land_draft_response.json()
    land_content = land_draft_payload["content"]
    assert "Review the guarded action plan" in land_content
    assert land_draft_payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"
    action_draft = land_draft_payload["trace"]["safety"]["action_draft"]
    assert action_draft["target_drone_ids"] == ["1"]
    assert action_draft["target_inferred_from"] == "previous_submitted_action"
    assert [step["label"] for step in action_draft["display_plan"]["steps"]] == [
        "Land",
        "Remove SITL instance(s)",
    ]
    assert action_draft["post_actions"][0]["arguments"] == {
        "action": "remove",
        "instance_names": ["drone-1"],
    }
    land_draft_id = re.search(r"act-[0-9a-f]+", land_content).group(0)

    land_confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": takeoff_draft_payload["session"]["id"],
            "message": f"confirm action {land_draft_id}",
        },
    )

    assert land_confirm_response.status_code == 200
    payload = land_confirm_response.json()
    assert "Action run started" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "submitted"
    land_run = _wait_for_action_run(client, payload)
    assert land_run["state"] == "succeeded"
    assert land_run["summary"] == "Completed 2 of 2 planned steps."
    assert land_run["result"]["monitor_result"]["completion_verification"]["verified"] is True
    assert land_run["result"]["post_action_results"][0]["status"] == "succeeded"
    assert [command.mission_type for command in submitted] == [10, 101]
    assert submitted[-1].target_drone_ids == ["1"]
    assert post_actions == [
        {
            "name": "mds.sitl.instances.action",
            "arguments": {
                "action": "remove",
                "instance_names": ["drone-1"],
            },
            "channel": "agent",
            "approved": True,
            "policy_mode": "sitl",
        }
    ]


def test_simurgh_compound_takeoff_wait_move_uses_previous_single_sitl_target(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    guarded_submissions = []
    submitted_commands = []
    terminal_failures = set()
    now = time.time() + 600.0

    async def fake_sleep(_delay_seconds):
        return None

    monkeypatch.setattr("api_routes.simurgh._sleep_action_sequence_delay", fake_sleep)

    class FakeTracker:
        async def get_status(self, command_id):
            if command_id in terminal_failures:
                return {
                    "command_id": command_id,
                    "status": "failed",
                    "phase": "terminal",
                    "outcome": "failed",
                    "progress": {"message": "Command failed."},
                }
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
                "progress": {"message": "Command completed."},
            }

    class FakeDeps:
        telemetry_data_all_drones = {
            "1": {
                "telemetry_available": True,
                "gps_fix_type": 3,
                "satellites_visible": 10,
                "battery_voltage": 16.2,
                "battery_remaining_percent": 0.89,
                "is_armed": False,
                "is_ready_to_arm": True,
                "flight_mode_name": "HOLD",
                "system_status_name": "STANDBY",
                "timestamp": int(now * 1000),
            }
        }
        last_telemetry_time = {"1": now}
        data_lock = None

        def load_config(self):
            return [
                {
                    "hw_id": 1,
                    "pos_id": 1,
                    "callsign": "SCOUT",
                    "ip": "172.18.0.2",
                    "mavlink_port": 14563,
                }
            ]

        def get_all_drone_positions(self):
            return []

        def load_swarm(self):
            return []

        def get_all_heartbeats(self):
            return {"1": {"timestamp": int(now * 1000), "ip": "172.18.0.2"}}

        def get_command_tracker(self):
            return FakeTracker()

    async def fake_guarded_route_tool(_request, *, name, arguments, channel, approved, registry, policy):
        guarded_submissions.append({"name": name, "arguments": arguments, "approved": approved})
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": "sitl-op-create-compound",
                "operation_type": "create_instance",
                "status": "queued",
                "summary": "Creating drone-1",
            },
            status_code=200,
        )

    async def fake_submit_tracked_command(_deps, command):
        submitted_commands.append(command)
        mission_name = {
            10: "TAKE_OFF",
            104: "RETURN_RTL",
            112: "PRECISION_MOVE",
        }.get(command.mission_type, "UNKNOWN")
        return {
            "success": True,
            "command_id": f"cmd-{len(submitted_commands)}",
            "idempotency_key": command.idempotency_key,
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": mission_name,
            "target_drones": command.target_drone_ids,
            "submitted_count": len(command.target_drone_ids),
            "results_summary": {"accepted": len(command.target_drone_ids), "offline": 0, "rejected": 0, "errors": 0},
        }

    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    app = FastAPI()

    @app.get("/api/v1/system/sitl/operations/{operation_id}")
    async def fake_sitl_operation(operation_id):
        return {
            "operation_id": operation_id,
            "status": "succeeded",
            "summary": "Created drone-1",
        }

    app.include_router(create_simurgh_router())
    client = TestClient(app)

    sitl_status = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "is there any sitl instance running?"},
    ).json()
    create_draft = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "create one SITL instance and report when ready",
        },
    ).json()
    create_draft_id = re.search(r"act-[0-9a-f]+", create_draft["content"]).group(0)
    create_confirm = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": f"confirm action {create_draft_id}",
        },
    )
    assert create_confirm.status_code == 200
    create_confirm_payload = create_confirm.json()
    assert "Action run started" in create_confirm_payload["content"]
    create_run = _wait_for_action_run(client, create_confirm_payload)
    assert create_run["state"] == "succeeded"
    assert create_run["result"]["monitor_result"]["summary"] == "Created drone-1"

    conditional_flight_draft = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": (
                "I see its up. if its rady to fly send it to a mission. "
                "lets takeoff 10m then wait 10s, then fly to 20m east, "
                "then wait 30s, then RTL"
            ),
        },
    )
    assert conditional_flight_draft.status_code == 200
    conditional_payload = conditional_flight_draft.json()
    assert "Simurgh Operator mock assistant is active" not in conditional_payload["content"]
    assert "Blocked intent signals" not in conditional_payload["content"]
    assert "Review the guarded action plan" in conditional_payload["content"]
    assert conditional_payload["trace"]["intent"]["route"] == "action_draft"
    conditional_action = conditional_payload["trace"]["safety"]["action_draft"]
    assert conditional_action["target_drone_ids"] == ["1"]
    assert conditional_action["command_payload"]["takeoff_altitude"] == 10.0
    assert [item["type"] for item in conditional_action["post_actions"]] == [
        "delay",
        "flight_command",
        "delay",
        "flight_command",
    ]
    assert conditional_action["post_actions"][0]["delay_seconds"] == 10.0
    assert conditional_action["post_actions"][1]["arguments"]["precision_move"]["translation_m"]["east"] == 20.0
    assert conditional_action["post_actions"][2]["delay_seconds"] == 30.0
    assert conditional_action["post_actions"][3]["arguments"]["mission_type"] == 104

    flight_draft = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "ok send it to test flight. lets takeoff to 10m, then wait 10s, then to 10m north same altitude and then return land",
        },
    )
    assert flight_draft.status_code == 200
    flight_payload = flight_draft.json()
    assert "No pending action found" not in flight_payload["content"]
    assert "Review the guarded action plan" in flight_payload["content"]
    assert flight_payload["trace"]["intent"]["route"] == "action_draft"
    assert flight_payload["trace"]["intent"]["confirmation_message"] is False
    action_draft = flight_payload["trace"]["safety"]["action_draft"]
    assert action_draft["target_drone_ids"] == ["1"]
    assert action_draft["command_payload"]["takeoff_altitude"] == 10.0
    assert [item["type"] for item in action_draft["post_actions"]] == ["delay", "flight_command", "flight_command"]
    assert action_draft["post_actions"][0]["delay_seconds"] == 10.0
    assert action_draft["post_actions"][1]["arguments"]["precision_move"]["translation_m"]["north"] == 10.0
    assert action_draft["post_actions"][2]["arguments"]["mission_type"] == 104

    flight_draft_id = re.search(r"act-[0-9a-f]+", flight_payload["content"]).group(0)
    cancel_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": f"cancel action {flight_draft_id}",
        },
    )
    assert cancel_response.status_code == 200
    assert "Cancelled the pending guarded action draft" in cancel_response.json()["content"]

    replay_draft = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "no there were several commands. read again",
        },
    )
    assert replay_draft.status_code == 200
    replay_payload = replay_draft.json()
    assert "Review the guarded action plan" in replay_payload["content"]
    replay_action_draft = replay_payload["trace"]["safety"]["action_draft"]
    assert replay_action_draft["target_drone_ids"] == ["1"]
    assert [item["type"] for item in replay_action_draft["post_actions"]] == ["delay", "flight_command", "flight_command"]
    assert replay_action_draft["post_actions"][0]["delay_seconds"] == 10.0
    assert replay_action_draft["post_actions"][1]["arguments"]["precision_move"]["translation_m"]["north"] == 10.0
    assert replay_action_draft["post_actions"][2]["arguments"]["mission_type"] == 104

    flight_draft_id = re.search(r"act-[0-9a-f]+", replay_payload["content"]).group(0)
    flight_confirm = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": f"confirm action {flight_draft_id}",
        },
    )
    assert flight_confirm.status_code == 200
    flight_confirm_payload = flight_confirm.json()
    assert "Action run started" in flight_confirm_payload["content"]
    flight_run = _wait_for_action_run(client, flight_confirm_payload)
    assert flight_run["state"] == "succeeded"
    assert flight_run["summary"] == "Completed 4 of 4 planned steps."
    assert flight_run["result"]["post_action_results"][-1]["completion_verification"]["verified"] is True

    status_question = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "Give me a report of status",
        },
    )
    assert status_question.status_code == 200
    status_payload = status_question.json()
    assert status_payload["trace"]["intent"]["route"] == "read_only"
    assert "Drone 1" in status_payload["content"]
    assert "Ready" in status_payload["content"]
    assert "Public web sources" not in status_payload["content"]
    assert "Simurgh assistant runtime" not in status_payload["content"]

    history_question = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "just one question . did you also do teh waits between takeoff and precission move ? or skipped that?",
        },
    )
    assert history_question.status_code == 200
    history_payload = history_question.json()
    assert history_payload["trace"]["safety"]["action_execution"] == "previous_action_summary"
    assert "Wait steps: 1/1 completed" in history_payload["content"]
    assert "wait 10 second(s): completed" in history_payload["content"]
    assert "No new action was executed." in history_payload["content"]
    assert "Action draft" not in history_payload["content"]
    assert [command.mission_type for command in submitted_commands] == [10, 112, 104]
    assert submitted_commands[0].target_drone_ids == ["1"]
    assert submitted_commands[0].takeoff_altitude == 10.0
    assert submitted_commands[1].target_drone_ids == ["1"]
    assert submitted_commands[1].precision_move.translation_m["north"] == 10.0
    assert submitted_commands[2].target_drone_ids == ["1"]
    assert guarded_submissions[0]["name"] == "mds.sitl.instances.create"

    pm_sequence_draft = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": (
                "Ok now lets use drone of for below misison. Takeoff to 14m, "
                "then for 5m south. Then climb 10m again . Then wait 5s . Then return and report"
            ),
        },
    )
    assert pm_sequence_draft.status_code == 200
    pm_payload = pm_sequence_draft.json()
    pm_action_draft = pm_payload["trace"]["safety"]["action_draft"]
    assert pm_action_draft["target_drone_ids"] == ["1"]
    assert pm_action_draft["command_payload"]["takeoff_altitude"] == 14.0
    assert [item["type"] for item in pm_action_draft["post_actions"]] == [
        "flight_command",
        "flight_command",
        "delay",
        "flight_command",
    ]
    assert pm_action_draft["post_actions"][0]["arguments"]["precision_move"]["translation_m"] == {
        "north": -5.0,
        "east": 0.0,
        "up": 0.0,
    }
    assert pm_action_draft["post_actions"][1]["arguments"]["precision_move"]["translation_m"] == {
        "north": 0.0,
        "east": 0.0,
        "up": 10.0,
    }
    assert pm_action_draft["post_actions"][2]["delay_seconds"] == 5.0
    assert pm_action_draft["post_actions"][3]["arguments"]["mission_type"] == 104

    pending_status_question = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "Give me a report of status",
        },
    )
    assert pending_status_question.status_code == 200
    pending_status_payload = pending_status_question.json()
    assert pending_status_payload["trace"]["intent"]["route"] == "read_only"
    assert pending_status_payload["trace"]["tool"]["intent"] == "fleet_connectivity"
    assert "Drone 1" in pending_status_payload["content"]
    assert "Simurgh assistant runtime" not in pending_status_payload["content"]
    assert "Public web sources" not in pending_status_payload["content"]

    pending_wait_question = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "just one question. did you also do the waits between takeoff and precision move? or skipped that?",
        },
    )
    assert pending_wait_question.status_code == 200
    pending_wait_payload = pending_wait_question.json()
    assert pending_wait_payload["trace"]["safety"]["action_execution"] == "pending_action_summary"
    assert "pending draft includes the wait step" in pending_wait_payload["content"]
    assert "wait 5s" in pending_wait_payload["content"]
    assert "No new action was executed." in pending_wait_payload["content"]

    pm_sequence_id = re.search(r"act-[0-9a-f]+", pm_payload["content"]).group(0)
    pm_sequence_confirm = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": f"confirm action {pm_sequence_id}",
        },
    )
    assert pm_sequence_confirm.status_code == 200
    pm_confirm_payload = pm_sequence_confirm.json()
    assert "Action run started" in pm_confirm_payload["content"]
    pm_run = _wait_for_action_run(client, pm_confirm_payload)
    assert pm_run["state"] == "succeeded"
    assert pm_run["summary"] == "Completed 5 of 5 planned steps."
    assert pm_run["result"]["post_action_results"][-1]["completion_verification"]["verified"] is True
    assert [command.mission_type for command in submitted_commands] == [10, 112, 104, 10, 112, 112, 104]
    assert submitted_commands[4].precision_move.translation_m == {"north": -5.0, "east": 0.0, "up": 0.0}
    assert submitted_commands[5].precision_move.translation_m == {"north": 0.0, "east": 0.0, "up": 10.0}

    failed_sequence_draft = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "takeoff drone 1 to 10m, wait 5s, move 10m north, then RTL",
        },
    ).json()
    failed_sequence_id = re.search(r"act-[0-9a-f]+", failed_sequence_draft["content"]).group(0)
    terminal_failures.add("cmd-8")
    failed_confirm = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": f"confirm action {failed_sequence_id}",
        },
    )

    assert failed_confirm.status_code == 200
    failed_run = _wait_for_action_run(client, failed_confirm.json())
    assert failed_run["state"] == "failed"
    assert failed_run["result"]["monitor_result"]["success"] is False
    assert [item["status"] for item in failed_run["result"]["post_action_results"]] == [
        "skipped",
        "skipped",
        "terminal_success",
    ]
    assert [command.mission_type for command in submitted_commands] == [10, 112, 104, 10, 112, 112, 104, 10, 104]

    post_failure_draft = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "takeoff drone 1 to 10m, wait 5s, move 10m north, then RTL",
        },
    ).json()
    post_failure_id = re.search(r"act-[0-9a-f]+", post_failure_draft["content"]).group(0)
    terminal_failures.add("cmd-11")
    post_failure_confirm = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": f"confirm action {post_failure_id}",
        },
    )

    assert post_failure_confirm.status_code == 200
    post_failure_run = _wait_for_action_run(client, post_failure_confirm.json())
    assert post_failure_run["state"] == "failed"
    post_failure_trace = post_failure_run["result"]["post_action_results"]
    assert [item["status"] for item in post_failure_trace] == [
        "completed",
        "terminal_non_success",
        "terminal_success",
    ]
    assert [command.mission_type for command in submitted_commands] == [
        10,
        112,
        104,
        10,
        112,
        112,
        104,
        10,
        104,
        10,
        112,
        104,
    ]


def test_simurgh_conditional_mission_infers_single_active_sitl_target(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    class FakeSitlService:
        def list_instances(self):
            return SimpleNamespace(
                instances=[
                    SimpleNamespace(name="drone-1", state="running", status="running", hw_id="1"),
                ]
            )

    app = FastAPI()
    app.include_router(create_simurgh_router(SimpleNamespace(sitl_control_service=FakeSitlService())))
    client = TestClient(app)

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": (
                "i see one sitl intace is it currect? I see its up. if its rady to fly "
                "send it to a mission. lets takeoff 10m then wait 10s, then fly to 20m east, "
                "then wait 30s, then RTL"
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Review the guarded action plan" in payload["content"]
    assert "Missing: target_drone_ids" not in payload["content"]
    assert "Blocked intent signals" not in payload["content"]
    assert "Simurgh Operator mock assistant is active" not in payload["content"]
    assert payload["trace"]["intent"]["route"] == "action_draft"
    action_draft = payload["trace"]["safety"]["action_draft"]
    assert action_draft["target_drone_ids"] == ["1"]
    assert action_draft["target_inferred_from"] == "single_active_sitl_instance"
    assert action_draft["command_payload"]["takeoff_altitude"] == 10.0
    assert [item["type"] for item in action_draft["post_actions"]] == [
        "delay",
        "flight_command",
        "delay",
        "flight_command",
    ]
    assert action_draft["post_actions"][0]["delay_seconds"] == 10.0
    assert action_draft["post_actions"][1]["arguments"]["precision_move"]["translation_m"]["east"] == 20.0
    assert action_draft["post_actions"][2]["delay_seconds"] == 30.0
    assert action_draft["post_actions"][3]["arguments"]["mission_type"] == 104


def test_simurgh_conditional_mission_asks_conversational_target_when_multiple_live(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    class FakeSitlService:
        def list_instances(self):
            return SimpleNamespace(
                instances=[
                    SimpleNamespace(name="drone-1", state="running", status="running", hw_id="1"),
                    SimpleNamespace(name="drone-2", state="running", status="running", hw_id="2"),
                ]
            )

    app = FastAPI()
    app.include_router(create_simurgh_router(SimpleNamespace(sitl_control_service=FakeSitlService())))
    client = TestClient(app)

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "if it is ready send it to takeoff 10m then wait 10s then RTL",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Which drone should I use?" in payload["content"]
    assert "Reply with the drone ID" in payload["content"]
    assert "Missing: target_drone_ids" not in payload["content"]
    assert "Blocked intent signals" not in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "missing_arguments"


def test_simurgh_direct_sitl_reconcile_request_returns_guarded_action_draft(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Create 4 SITL drones and report progress"},
    )

    assert response.status_code == 200
    payload = response.json()
    content = payload["content"]
    assert "Review the guarded action plan" in content
    assert '"target_count": 4' not in content
    assert "Circuit breaker: ON" in content
    assert "No action was executed" in content
    assert payload["blocked_intents"] == []
    assert payload["trace"]["tool"]["id"] == "mds.sitl.fleet.reconcile"
    assert payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"
    assert payload["trace"]["safety"]["action_draft"]["arguments"]["target_count"] == 4
    assert payload["trace"]["safety"]["action_draft"]["display_plan"]["steps"][0]["label"] == "Reconcile SITL fleet"


def test_simurgh_direct_single_sitl_create_request_returns_guarded_action_draft(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Create 1 sitl instance so I can test with"},
    )

    assert response.status_code == 200
    payload = response.json()
    content = payload["content"]
    assert "Review the guarded action plan" in content
    assert '"git_sync_enabled"' not in content
    assert "advisory-only" not in content
    assert "No action was executed" in content
    assert payload["trace"]["tool"]["id"] == "mds.sitl.instances.create"
    assert payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"
    assert payload["trace"]["safety"]["action_draft"]["arguments"] == {
        "git_sync_enabled": True,
        "requirements_sync_enabled": True,
    }


def test_simurgh_provider_semantic_rewrite_routes_typo_heavy_sitl_create(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    def fake_rewrite_operator_message_with_provider(**kwargs):
        message = kwargs["message"]
        return _provider_rewrite(
            normalized_message="create one SITL instance and report when ready",
            route_hint="draft_sitl_lifecycle_action",
            action_plan=ProviderActionPlan(
                summary="Create one SITL instance",
                steps=(
                    _provider_step(
                        message,
                        message,
                        tool_id="mds.sitl.instances.create",
                        arguments={},
                        label="Create one SITL instance",
                    ),
                ),
            ),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "crete one sitl intstance and report when ready to test and fly with",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    content = payload["content"]
    assert "Review the guarded action plan" in content
    assert "text-only provider" not in content
    assert "I can’t create" not in content
    assert payload["trace"]["tool"]["id"] == "mds.sitl.instances.create"
    assert payload["trace"]["intent"]["route"] == "action_draft"
    assert payload["trace"]["intent"]["provider_semantic_rewrite"]["route_hint"] == "draft_sitl_lifecycle_action"
    assert payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"
    assert payload["trace"]["safety"]["action_draft"]["arguments"] == {}


def test_simurgh_provider_semantic_rewrite_rebuilds_incomplete_flight_sequence(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    def fake_rewrite_operator_message_with_provider(**kwargs):
        message = kwargs["message"]
        return _provider_rewrite(
            normalized_message="take off, wait, move north, wait, climb, then RTL",
            route_hint="draft_flight_action",
            action_plan=ProviderActionPlan(
                summary="Run the requested test sequence",
                steps=(
                    _provider_step(
                        message,
                        "drone 1. takeoff 10m",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 10,
                            "trigger_time": 0,
                            "target_drone_ids": ["1"],
                            "takeoff_altitude": 10,
                        },
                        label="Take off to 10 m",
                    ),
                    _provider_delay(message, "hold 5 sec", 5),
                    _provider_step(
                        message,
                        "fly 25 north",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 112,
                            "trigger_time": 0,
                            "precision_move": {
                                "frame": "ned",
                                "translation_m": {"north": 25, "east": 0, "up": 0},
                            },
                        },
                        condition="after_command_terminal_success",
                        label="Move 25 m north",
                    ),
                    _provider_delay(message, "hold again", 5),
                    _provider_step(
                        message,
                        "climb ten",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 112,
                            "trigger_time": 0,
                            "precision_move": {
                                "frame": "ned",
                                "translation_m": {"north": 0, "east": 0, "up": 10},
                            },
                        },
                        condition="after_command_terminal_success",
                        label="Climb 10 m",
                    ),
                    _provider_step(
                        message,
                        "return",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 104, "trigger_time": 0},
                        condition="after_command_terminal",
                        label="Return to launch",
                    ),
                ),
            ),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": (
                "lets use drone 1. takeoff 10m, hold 5 sec, fly 25 north, "
                "hold again, climb ten and return"
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    draft = payload["trace"]["safety"]["action_draft"]
    assert draft["target_drone_ids"] == ["1"]
    assert draft["command_payload"]["takeoff_altitude"] == 10.0
    assert [item["type"] for item in draft["post_actions"]] == [
        "delay",
        "flight_command",
        "delay",
        "flight_command",
        "flight_command",
    ]


def test_simurgh_provider_semantic_rewrite_cannot_change_typed_flight_facts(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")

    def fake_rewrite_operator_message_with_provider(**kwargs):
        message = kwargs["message"]
        return _provider_rewrite(
            normalized_message="take off drone 1 to 100m then move 5m south",
            route_hint="draft_flight_action",
            action_plan=ProviderActionPlan(
                summary="Take off and move north",
                steps=(
                    _provider_step(
                        message,
                        "takeoff drone 1 to 10m",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 10,
                            "trigger_time": 0,
                            "target_drone_ids": ["1"],
                            "takeoff_altitude": 10,
                        },
                        label="Take off to 10 m",
                    ),
                    _provider_step(
                        message,
                        "move 5m north",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 112,
                            "trigger_time": 0,
                            "precision_move": {
                                "frame": "ned",
                                "translation_m": {"north": 5, "east": 0, "up": 0},
                            },
                        },
                        condition="after_command_terminal_success",
                        label="Move 5 m north",
                    ),
                ),
            ),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()
    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "takeoff drone 1 to 10m then move 5m north"},
    )

    assert response.status_code == 200
    draft = response.json()["trace"]["safety"]["action_draft"]
    assert draft["command_payload"]["takeoff_altitude"] == 10.0
    assert draft["post_actions"][0]["arguments"]["precision_move"]["translation_m"]["north"] == 5.0


def test_simurgh_provider_semantic_rewrite_cannot_add_flight_steps(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")

    def fake_rewrite_operator_message_with_provider(**kwargs):
        message = kwargs["message"]
        return _provider_rewrite(
            normalized_message=(
                "take off drone 1 to 10m, move 5m north, move 100m east, then return to launch"
            ),
            route_hint="draft_flight_action",
            action_plan=ProviderActionPlan(
                summary="Take off, move north, and return",
                steps=(
                    _provider_step(
                        message,
                        "takeoff drone 1 to 10m",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 10,
                            "trigger_time": 0,
                            "target_drone_ids": ["1"],
                            "takeoff_altitude": 10,
                        },
                        label="Take off to 10 m",
                    ),
                    _provider_step(
                        message,
                        "move 5m north",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 112,
                            "trigger_time": 0,
                            "precision_move": {
                                "frame": "ned",
                                "translation_m": {"north": 5, "east": 0, "up": 0},
                            },
                        },
                        condition="after_command_terminal_success",
                        label="Move 5 m north",
                    ),
                    _provider_step(
                        message,
                        "return to launch",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 104, "trigger_time": 0},
                        condition="after_command_terminal",
                        label="Return to launch",
                    ),
                ),
            ),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "takeoff drone 1 to 10m, move 5m north, then return to launch",
        },
    )

    assert response.status_code == 200
    draft = response.json()["trace"]["safety"]["action_draft"]
    assert [item["action_label"] for item in draft["post_actions"]] == ["Move 5 m north", "Return to launch"]
    assert draft["post_actions"][0]["arguments"]["precision_move"]["translation_m"]["east"] == 0.0


def test_simurgh_provider_semantic_rewrite_cannot_change_yaw(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")

    def fake_rewrite_operator_message_with_provider(**kwargs):
        message = kwargs["message"]
        return _provider_rewrite(
            normalized_message="take off drone 1 to 10m, yaw to 10 degrees, then return to launch",
            route_hint="draft_flight_action",
            action_plan=ProviderActionPlan(
                summary="Take off, yaw, and return",
                steps=(
                    _provider_step(
                        message,
                        "takeoff drone 1 to 10m",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 10,
                            "trigger_time": 0,
                            "target_drone_ids": ["1"],
                            "takeoff_altitude": 10,
                        },
                        label="Take off to 10 m",
                    ),
                    _provider_step(
                        message,
                        "yaw to 290 degrees",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 112,
                            "trigger_time": 0,
                            "precision_move": {
                                "frame": "ned",
                                "translation_m": {"north": 0, "east": 0, "up": 0},
                                "yaw": {"mode": "absolute_heading", "degrees": 290},
                            },
                        },
                        condition="after_command_terminal_success",
                        label="Yaw to 290 degrees",
                    ),
                    _provider_step(
                        message,
                        "return to launch",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 104, "trigger_time": 0},
                        condition="after_command_terminal",
                        label="Return to launch",
                    ),
                ),
            ),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "takeoff drone 1 to 10m, yaw to 290 degrees, then return to launch",
        },
    )

    assert response.status_code == 200
    draft = response.json()["trace"]["safety"]["action_draft"]
    yaw = draft["post_actions"][0]["arguments"]["precision_move"]["yaw"]
    assert yaw == {"mode": "absolute_heading", "degrees": 290.0}


def test_simurgh_provider_semantic_ambiguity_asks_one_clarification(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        return _provider_rewrite(
            normalized_message="land or return drone 1",
            route_hint="clarify",
            confidence=0.91,
            needs_clarification=True,
            clarification_question="Should I land Drone 1 here, or return it to launch?",
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "land or rtl drone 1 now"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == "Should I land Drone 1 here, or return it to launch?"
    assert payload["trace"]["tool"]["ids"] == []
    assert payload["trace"]["intent"]["provider_semantic_rewrite"]["needs_clarification"] is True


def test_simurgh_provider_semantic_clarification_preserves_original_request(monkeypatch):
    from api_routes import simurgh as simurgh_routes

    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    calls = []
    safe_calls = []
    original_safe_to_try = simurgh_routes._semantic_rewrite_is_safe_to_try

    def capture_safe_to_try(**kwargs):
        result = original_safe_to_try(**kwargs)
        safe_calls.append(
            (
                kwargs["turn_intent"].route,
                kwargs["turn_intent"].conversation_topic,
                result,
            )
        )
        return result

    def fake_rewrite_operator_message_with_provider(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _provider_rewrite(
                normalized_message="land or return drone 1",
                route_hint="clarify",
                confidence=0.91,
                needs_clarification=True,
                clarification_question="Should I land Drone 1 here, or return it to launch?",
            )
        assert "Previous request: land or rtl drone 1 now" in kwargs["clarification_context"]
        assert "Clarification asked: Should I land Drone 1 here, or return it to launch?" in kwargs["clarification_context"]
        message = kwargs["message"]
        return _provider_rewrite(
            normalized_message="return to launch drone 1",
            route_hint="draft_flight_action",
            confidence=0.97,
            action_plan=ProviderActionPlan(
                summary="Return Drone 1 to launch",
                steps=(
                    _provider_step(
                        message,
                        message,
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 104, "trigger_time": 0, "target_drone_ids": ["1"]},
                        label="Return Drone 1 to launch",
                    ),
                ),
            ),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr("api_routes.simurgh._semantic_rewrite_is_safe_to_try", capture_safe_to_try)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()
    clarification = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "land or rtl drone 1 now"},
    ).json()
    assert clarification["session"]["metadata"]["last_domain"] == "clarification"

    followup = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": clarification["session"]["id"],
            "message": "return it",
        },
    )

    assert followup.status_code == 200, (followup.text, len(calls), safe_calls)
    payload = followup.json()
    assert len(calls) == 2
    assert safe_calls[-1] == ("provider_or_registry", "clarification", True)
    assert payload["trace"]["intent"]["route"] == "action_draft"
    assert payload["trace"]["safety"]["action_draft"]["command_payload"]["mission_type"] == 104
    assert payload["trace"]["safety"]["action_draft"]["target_drone_ids"] == ["1"]


def test_simurgh_bare_singular_sitl_create_language_returns_guarded_action_draft(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Build one sitl so I can do some tests with that"},
    )

    assert response.status_code == 200
    payload = response.json()
    content = payload["content"]
    assert "Review the guarded action plan" in content
    assert "did not build" not in content.lower()
    assert "read-only" not in content.lower()
    assert payload["trace"]["tool"]["id"] == "mds.sitl.instances.create"
    assert payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"
    assert payload["trace"]["safety"]["action_draft"]["arguments"] == {
        "git_sync_enabled": True,
        "requirements_sync_enabled": True,
    }


def test_simurgh_sitl_instructions_do_not_create_action_draft(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "How do I build one SITL instance for testing?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "guarded action draft" not in payload["content"]
    assert payload["trace"].get("safety", {}).get("action_execution") != "awaiting_confirmation"
    assert payload["trace"]["tool"]["intent"] != "sitl_lifecycle_action"


def test_simurgh_streamed_sitl_action_progress_is_not_read_only_evidence(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns/stream",
        json={"actor": "operator", "message": "Build one sitl so I can test with it"},
    )

    assert response.status_code == 200
    events = _sse_events(response.text)
    progress_labels = [
        str(payload.get("label") or "")
        for event, payload in events
        if event == "progress"
    ]
    assert any("Action draft ready" in label for label in progress_labels)
    assert not any("Read-only evidence" in label for label in progress_labels)
    final_payloads = [payload for event, payload in events if event == "final"]
    assert final_payloads
    final_payload = final_payloads[-1]
    assert final_payload["trace"]["tool"]["id"] == "mds.sitl.instances.create"
    assert final_payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"


def test_simurgh_confirmed_single_sitl_create_submits_when_circuit_breaker_off(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_guarded_route_tool(_request, *, name, arguments, channel, approved, registry, policy):
        submitted.append(
            {
                "name": name,
                "arguments": arguments,
                "channel": channel,
                "approved": approved,
                "policy_mode": policy.mode,
            }
        )
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": "sitl-op-1",
                "operation_type": "create_instance",
                "status": "queued",
                "summary": "SITL instance create accepted",
                "detail": "drone-1 will be created.",
            },
            status_code=200,
        )

    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    client = _client()

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Create 1 sitl instance so I can test with"},
    )
    assert draft_response.status_code == 200
    assert submitted == []
    draft_payload = draft_response.json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert "Action run started" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "submitted"
    run = _wait_for_action_run(client, payload)
    assert run["state"] == "succeeded"
    assert run["result"]["action_response"]["operation_id"] == "sitl-op-1"
    assert submitted == [
        {
            "name": "mds.sitl.instances.create",
            "arguments": {
                "git_sync_enabled": True,
                "requirements_sync_enabled": True,
            },
            "channel": "agent",
            "approved": True,
            "policy_mode": "sitl",
        }
    ]


def test_simurgh_direct_sitl_restart_request_returns_guarded_action_draft(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "restart SITL instance 2 and report progress"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Review the guarded action plan" in payload["content"]
    assert '"action": "restart"' not in payload["content"]
    assert payload["trace"]["tool"]["id"] == "mds.sitl.instances.action"
    assert payload["trace"]["safety"]["action_draft"]["arguments"] == {
        "action": "restart",
        "instance_names": ["drone-2"],
    }
    assert payload["trace"]["safety"]["action_draft"]["display_plan"]["steps"][0]["label"] == "Restart SITL instance(s)"


def test_simurgh_direct_sitl_remove_request_needs_named_instances(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "remove the SITL containers"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "I can plan this guarded action" in payload["content"]
    assert "Missing: instance_names" in payload["content"]
    assert "No action was executed" in payload["content"]
    assert payload["trace"]["tool"]["id"] == "mds.sitl.instances.action"
    assert payload["trace"]["safety"]["action_execution"] == "missing_arguments"


def test_simurgh_stale_sitl_remove_checks_state_and_infers_single_listed_instance(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    class FakeSitlService:
        def list_instances(self):
            return SimpleNamespace(
                instances=[
                    SimpleNamespace(name="drone-1", state="exited", status="exited", hw_id="1"),
                ]
            )

    app = FastAPI()

    @app.get("/api/v1/system/sitl/instances")
    def sitl_instances():
        return {
            "total_instances": 1,
            "instances": [{"id": "drone-1", "name": "drone-1", "state": "exited"}],
            "docker": {"daemon_reachable": True, "available": True},
        }

    @app.get("/api/v1/system/sitl/policy")
    def sitl_policy():
        return {"enabled": True, "max_instances": 4}

    app.include_router(create_simurgh_router(SimpleNamespace(sitl_control_service=FakeSitlService())))
    client = TestClient(app)

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "I see a stale sitl isntnace ? If that so delete it"},
    )

    assert response.status_code == 200
    payload = response.json()
    content = payload["content"]
    assert "Read-only status checked before drafting" in content
    assert "Review the guarded action plan" in content
    assert "Missing: instance_names" not in content
    assert "No action was executed" in content
    assert payload["trace"]["tool"]["id"] == "mds.sitl.instances.action"
    assert payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"
    assert payload["trace"]["safety"]["pre_action_read_only_tool_ids"] == [
        "mds.sitl.instances.read",
        "mds.sitl.policy.read",
    ]
    assert payload["trace"]["safety"]["action_draft"]["arguments"] == {
        "action": "remove",
        "instance_names": ["drone-1"],
    }
    assert payload["trace"]["safety"]["action_draft"]["display_plan"]["steps"][0]["label"] == "Remove SITL instance(s)"
    assert payload["trace"]["intent"]["action"]["draft_missing_arguments"] == []


@pytest.mark.parametrize(
    "instances",
    [
        [],
        [
            {"id": "drone-1", "name": "drone-1", "state": "running", "status": "running", "hw_id": "1"},
            {"id": "drone-2", "name": "drone-2", "state": "exited", "status": "exited", "hw_id": "2"},
        ],
    ],
)
def test_simurgh_stale_sitl_remove_keeps_missing_target_when_not_single(monkeypatch, instances):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    class FakeSitlService:
        def list_instances(self):
            return SimpleNamespace(instances=[SimpleNamespace(**item) for item in instances])

    app = FastAPI()

    @app.get("/api/v1/system/sitl/instances")
    def sitl_instances():
        return {
            "total_instances": len(instances),
            "instances": instances,
            "docker": {"daemon_reachable": True, "available": True},
        }

    @app.get("/api/v1/system/sitl/policy")
    def sitl_policy():
        return {"enabled": True, "max_instances": 4}

    app.include_router(create_simurgh_router(SimpleNamespace(sitl_control_service=FakeSitlService())))
    client = TestClient(app)

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "I see a stale sitl instance ? If that so delete it"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Read-only status checked before drafting" in payload["content"]
    assert "Missing: instance_names" in payload["content"]
    assert "No action was executed" in payload["content"]
    assert payload["trace"]["tool"]["id"] == "mds.sitl.instances.action"
    assert payload["trace"]["safety"]["action_execution"] == "missing_arguments"
    assert payload["trace"]["safety"]["pre_action_read_only_tool_ids"] == [
        "mds.sitl.instances.read",
        "mds.sitl.policy.read",
    ]
    assert payload["trace"]["safety"]["action_draft"]["arguments"] == {
        "action": "remove",
        "instance_names": [],
    }


def test_simurgh_confirmed_sitl_reconcile_stops_at_final_circuit_breaker(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Build 4 SITL containers"},
    )
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert "Circuit breaker stopped this at the final execution layer" in payload["content"]
    assert "mds.sitl.fleet.reconcile" in payload["content"]
    assert "Requested fleet target: 4 SITL instance(s)" in payload["content"]
    assert '"target_count": 4' not in payload["content"]
    assert "No action was executed" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "blocked_by_circuit_breaker"


def test_simurgh_confirmed_sitl_reconcile_submits_when_circuit_breaker_off(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_guarded_route_tool(_request, *, name, arguments, channel, approved, registry, policy):
        submitted.append(
            {
                "name": name,
                "arguments": arguments,
                "channel": channel,
                "approved": approved,
                "policy_mode": policy.mode,
            }
        )
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": "sitl-op-4",
                "operation_type": "reconcile_fleet",
                "status": "queued",
                "summary": "SITL fleet reconcile accepted",
                "detail": "4 desired container(s) will be reconciled.",
            },
            status_code=200,
        )

    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    client = _client()

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Create 4 SITL drones"},
    )
    assert draft_response.status_code == 200
    assert submitted == []
    draft_payload = draft_response.json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert "Action run started" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "submitted"
    run = _wait_for_action_run(client, payload)
    assert run["state"] == "succeeded"
    assert run["result"]["action_response"]["operation_id"] == "sitl-op-4"
    assert submitted == [
        {
            "name": "mds.sitl.fleet.reconcile",
            "arguments": {
                "target_count": 4,
                "start_id": 1,
                "start_ip": 2,
                "git_sync_enabled": True,
                "requirements_sync_enabled": True,
            },
            "channel": "agent",
            "approved": True,
            "policy_mode": "sitl",
        }
    ]


def test_simurgh_confirmed_sitl_create_monitors_operation_when_requested(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_guarded_route_tool(_request, *, name, arguments, channel, approved, registry, policy):
        submitted.append(
            {
                "name": name,
                "arguments": arguments,
                "channel": channel,
                "approved": approved,
                "policy_mode": policy.mode,
            }
        )
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": "sitl-op-create-monitored",
                "operation_type": "create_instance",
                "status": "queued",
                "summary": "Creating drone-1",
            },
            status_code=200,
        )

    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    app = FastAPI()

    @app.get("/api/v1/system/sitl/operations/{operation_id}")
    async def fake_sitl_operation(operation_id):
        return {
            "operation_id": operation_id,
            "status": "succeeded",
            "summary": "SITL instance drone-1 is running.",
        }

    app.include_router(create_simurgh_router())
    client = TestClient(app)

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "create a new droen isntance sitl so I can test and try with that . reprot when created and ready",
        },
    )
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)
    assert draft_payload["trace"]["safety"]["action_draft"]["monitor_requested"] is True

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert "Action run started" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "submitted"
    run = _wait_for_action_run(client, payload)
    assert run["state"] == "succeeded"
    assert run["result"]["action_response"]["operation_id"] == "sitl-op-create-monitored"
    assert run["result"]["monitor_result"]["status"] == "succeeded"
    assert run["result"]["monitor_result"]["summary"] == "SITL instance drone-1 is running."
    assert submitted == [
        {
            "name": "mds.sitl.instances.create",
            "arguments": {
                "git_sync_enabled": True,
                "requirements_sync_enabled": True,
            },
            "channel": "agent",
            "approved": True,
            "policy_mode": "sitl",
        }
    ]


def test_simurgh_sitl_create_followup_readiness_uses_live_fleet_telemetry(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    # Keep this fixture independent of pytest runtime duration; the assertion is
    # about routing to live telemetry evidence, not the presence timeout boundary.
    now = time.time() + 600.0
    deps = SimpleNamespace(
        load_config=lambda: [
            {
                "hw_id": 1,
                "pos_id": 1,
                "callsign": "SCOUT",
                "ip": "172.18.0.2",
                "mavlink_port": 14563,
            }
        ],
        get_all_drone_positions=lambda: [],
        load_swarm=lambda: [],
        get_all_heartbeats=lambda: {"1": {"timestamp": int(now * 1000), "ip": "172.18.0.2"}},
        telemetry_data_all_drones={
            "1": {
                "telemetry_available": True,
                "position_lat": 47.397742,
                "position_long": 8.545594,
                "relative_altitude_m": 0.3,
                "global_position_valid": True,
                "gps_fix_type": 3,
                "satellites_visible": 12,
                "battery_voltage": 16.1,
                "battery_remaining_percent": 0.91,
                "is_armed": False,
                "is_ready_to_arm": True,
                "flight_mode_name": "HOLD",
                "system_status_name": "STANDBY",
                "timestamp": int(now * 1000),
            }
        },
        last_telemetry_time={"1": now},
        data_lock=None,
    )

    async def fake_guarded_route_tool(_request, *, name, arguments, channel, approved, registry, policy):
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": "sitl-op-ready-followup",
                "operation_type": "create_instance",
                "status": "queued",
                "summary": "Creating drone-1",
            },
            status_code=200,
        )

    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    app = FastAPI()

    @app.get("/api/v1/system/sitl/operations/{operation_id}")
    async def fake_sitl_operation(operation_id):
        return {
            "operation_id": operation_id,
            "status": "succeeded",
            "summary": "Created drone-1",
        }

    @app.get("/api/v1/system/sitl/instances")
    async def fake_sitl_instances():
        return {
            "total_instances": 1,
            "instances": [{"name": "drone-1", "state": "running"}],
            "docker": {"daemon_reachable": True, "available": True},
            "timestamp": int(now * 1000),
        }

    @app.get("/api/v1/system/sitl/host")
    async def fake_sitl_host():
        return {"host": "test-host", "available": True, "docker": {"daemon_reachable": True}}

    @app.get("/api/v1/fleet/heartbeats")
    async def fake_fleet_heartbeats():
        return {
            "heartbeats": [
                {"hw_id": "1", "online": True, "presence_state": "live", "ip": "172.18.0.2"},
            ],
            "total_drones": 1,
            "online_count": 1,
            "timestamp": int(now * 1000),
        }

    @app.get("/api/v1/fleet/telemetry")
    async def fake_fleet_telemetry():
        return {
            "telemetry": deps.telemetry_data_all_drones,
            "total_drones": 1,
            "online_drones": 1,
            "timestamp": int(now * 1000),
        }

    app.include_router(create_simurgh_router(deps))
    client = TestClient(app)

    sitl_status = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "is there any sitl instance running?"},
    ).json()
    create_draft = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "create one SITL instance and report when ready",
        },
    ).json()
    create_draft_id = re.search(r"act-[0-9a-f]+", create_draft["content"]).group(0)
    create_confirm = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": f"confirm action {create_draft_id}",
        },
    )
    assert create_confirm.status_code == 200

    readiness = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "give me a summary of the drone sitl we created and if its ready for flight or not ?",
        },
    )
    assert readiness.status_code == 200
    payload = readiness.json()
    content = payload["content"]
    assert "Verdict: ready for a SITL test" in content
    assert "Docker/SITL: 1 instance(s), 1 active; Docker reachable: Yes." in content
    assert "Drone 1" in content
    assert "Preflight" in content
    assert "Battery" in content
    assert "16.10 V / 91%" in content
    assert "SITL should be started" not in content
    assert "Registry-backed read-only capability summary" not in content
    assert "Active commands" not in content
    assert payload["trace"]["tool"]["intent"] == "registry_read_execution"
    assert payload["trace"]["tool"]["ids"] == [
        "mds.sitl.instances.read",
        "mds.sitl.host.read",
        "mds.fleet.heartbeats.read",
        "mds.fleet.telemetry.read",
    ]
    assert payload["trace"]["intent"]["route"] == "read_only"

    check_again = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "Check again if its up now?",
        },
    )
    assert check_again.status_code == 200
    check_payload = check_again.json()
    assert "Verdict: ready for a SITL test" in check_payload["content"]
    assert "Docker/SITL: 1 instance(s), 1 active; Docker reachable: Yes." in check_payload["content"]
    assert "Drone 1" in check_payload["content"]
    assert "Public web sources" not in check_payload["content"]
    assert "SITL should be started" not in check_payload["content"]
    assert check_payload["trace"]["tool"]["ids"] == [
        "mds.sitl.instances.read",
        "mds.sitl.host.read",
        "mds.fleet.heartbeats.read",
        "mds.fleet.telemetry.read",
    ]
    assert check_payload["trace"]["intent"]["route"] in {"read_only", "provider_or_registry"}


def test_simurgh_sitl_monitor_fails_fast_when_operation_status_is_unavailable(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    async def fake_guarded_route_tool(_request, *, name, arguments, channel, approved, registry, policy):
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": "sitl-op-missing",
                "operation_type": "create_instance",
                "status": "queued",
                "summary": "Creating drone-1",
            },
            status_code=200,
        )

    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    app = FastAPI()
    app.include_router(create_simurgh_router())
    client = TestClient(app)

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Create 1 sitl instance and report progress"},
    )
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert "Action run started" in payload["content"]
    run = _wait_for_action_run(client, payload)
    assert run["state"] == "failed"
    assert run["result"]["monitor_result"]["status"] == "failed"
    assert run["result"]["monitor_result"]["http_status"] == 404


def test_simurgh_confirmed_sitl_create_submits_when_circuit_breaker_off(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_guarded_route_tool(_request, *, name, arguments, channel, approved, registry, policy):
        submitted.append(
            {
                "name": name,
                "arguments": arguments,
                "channel": channel,
                "approved": approved,
                "policy_mode": policy.mode,
            }
        )
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": "sitl-op-create-1",
                "operation_type": "create_instance",
                "status": "queued",
                "summary": "Creating drone-1",
            },
            status_code=200,
        )

    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    client = _client()

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Create 1 sitl instance so I can test with"},
    )
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    confirm_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert "Action run started" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "submitted"
    run = _wait_for_action_run(client, payload)
    assert run["state"] == "succeeded"
    assert run["result"]["action_response"]["operation_id"] == "sitl-op-create-1"
    assert submitted == [
        {
            "name": "mds.sitl.instances.create",
            "arguments": {
                "git_sync_enabled": True,
                "requirements_sync_enabled": True,
            },
            "channel": "agent",
            "approved": True,
            "policy_mode": "sitl",
        }
    ]


def test_simurgh_tools_expose_registry_metadata_without_executing_tools():
    client = _client()

    response = client.get("/api/v1/simurgh/tools", params={"include_excluded": "false"})

    assert response.status_code == 200
    tools = response.json()["tools"]
    assert any(tool["id"] == "mds.system.health.read" for tool in tools)
    assert all(tool["exposure"] != "exclude" for tool in tools)
    assert not any(tool["boundary"] != "gcs" for tool in tools)

    raw_response = client.get("/api/v1/simurgh/tools/mds.commands.raw_submit")
    assert raw_response.status_code == 200
    assert raw_response.json()["exposure"] == "exclude"

    missing_response = client.get("/api/v1/simurgh/tools/not-a-tool")
    assert missing_response.status_code == 404


def test_simurgh_tool_candidates_are_review_only_and_filterable():
    client = _client()

    response = client.get(
        "/api/v1/simurgh/tool-candidates",
        params={"eligible_read_only": "true", "limit": "5"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact"] == "simurgh_openapi_tool_candidates"
    assert payload["artifact_path"] == "docs/agent-context/generated/simurgh-openapi-tool-candidates.yaml"
    assert payload["policy"]["runtime_loaded"] is False
    assert payload["policy"]["default_callable"] is False
    assert payload["candidate_count"] > 100
    assert payload["filtered_count"] >= payload["returned_count"]
    assert payload["returned_count"] <= 5
    assert payload["summary"]["eligible_read_only_mcp_candidates"] > 0
    assert "promoted_registry_route_matches" in payload["summary"]
    coverage = payload["summary"]["registry_coverage"]
    assert coverage["eligible_route_candidates"] == payload["summary"]["eligible_read_only_mcp_candidates"]
    assert coverage["eligible_promoted_route_matches"] > 0
    assert coverage["eligible_unpromoted_route_count"] == 0
    assert coverage["eligible_promotion_coverage_percent"] == 100.0
    assert coverage["eligible_unpromoted_by_group"] == {}
    assert coverage["eligible_read_only_candidate_count"] == coverage["eligible_route_candidates"]
    assert coverage["promoted_eligible_candidate_count"] == coverage["eligible_promoted_route_matches"]
    assert coverage["unpromoted_eligible_candidate_count"] == coverage["eligible_unpromoted_route_count"]
    assert coverage["promoted_eligible_ratio"] == 1.0
    assert coverage["unpromoted_eligible_by_area"] == []
    assert all(
        set(item) == {"method", "path", "group", "summary"}
        for item in coverage["eligible_unpromoted_routes_preview"]
    )
    assert all(candidate["callable"] is False for candidate in payload["candidates"])
    assert all(candidate["classification"]["eligible_read_only_mcp_candidate"] is True for candidate in payload["candidates"])

    command_response = client.get(
        "/api/v1/simurgh/tool-candidates",
        params={"search": "/api/v1/commands", "limit": "20"},
    )
    assert command_response.status_code == 200
    command_payload = command_response.json()
    assert any(
        "command/control route" in candidate["classification"]["review_reasons"]
        for candidate in command_payload["candidates"]
    )


def test_simurgh_context_lists_and_reads_public_context():
    client = _client()

    list_response = client.get("/api/v1/simurgh/context")

    assert list_response.status_code == 200
    resources = list_response.json()["resources"]
    assert any(resource["id"] == "simurgh.safety_policy" for resource in resources)
    assert all(resource["content_hash"] for resource in resources)

    content_response = client.get("/api/v1/simurgh/context/simurgh.safety_policy")
    assert content_response.status_code == 200
    assert "Raw GCS command submission" in content_response.json()["content"]

    markdown_response = client.get("/api/v1/simurgh/context/mds.init_setup/markdown")
    assert markdown_response.status_code == 200
    assert "companion" in markdown_response.text.lower()
    assert markdown_response.headers["content-type"].startswith("text/markdown")

    missing_response = client.get("/api/v1/simurgh/context/not-a-resource")
    assert missing_response.status_code == 404


def test_simurgh_context_list_and_read_hide_private_resources(monkeypatch, tmp_path):
    context_file = tmp_path / "context-index.yaml"
    context_file.write_text(
        """version: 1
resources:
  - id: public.fixture
    title: Public Fixture
    path: docs/agent-context/system-guidelines.md
    mime_type: text/markdown
    audience: agent
    sensitivity: public
    summary: Public fixture.
    tags: [test]
  - id: private.fixture
    title: Private Fixture
    path: docs/agent-context/system-guidelines.md
    mime_type: text/markdown
    audience: agent
    sensitivity: private
    summary: Private fixture.
    tags: [test]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MDS_AGENT_CONTEXT_INDEX_FILE", str(context_file))
    client = _client()

    list_response = client.get("/api/v1/simurgh/context")

    assert list_response.status_code == 200
    ids = {resource["id"] for resource in list_response.json()["resources"]}
    assert "public.fixture" in ids
    assert "private.fixture" not in ids

    public_response = client.get("/api/v1/simurgh/context/public.fixture")
    assert public_response.status_code == 200

    private_response = client.get("/api/v1/simurgh/context/private.fixture")
    assert private_response.status_code == 403

    private_markdown_response = client.get("/api/v1/simurgh/context/private.fixture/markdown")
    assert private_markdown_response.status_code == 403


def test_simurgh_session_lifecycle_records_audit_events(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    create_response = client.post(
        "/api/v1/simurgh/sessions",
        json={"actor": "operator", "metadata": {"channel": "dashboard"}},
    )

    assert create_response.status_code == 200
    session = create_response.json()
    assert session["actor"] == "operator"
    assert session["mode"] == "sitl"
    assert session["closed"] is False

    list_response = client.get("/api/v1/simurgh/sessions", params={"include_closed": "false"})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["sessions"]] == [session["id"]]

    close_response = client.delete(f"/api/v1/simurgh/sessions/{session['id']}")
    assert close_response.status_code == 200
    assert close_response.json()["closed"] is True

    filtered_response = client.get("/api/v1/simurgh/sessions", params={"include_closed": "false"})
    assert filtered_response.status_code == 200
    assert filtered_response.json()["sessions"] == []

    audit_response = client.get("/api/v1/simurgh/audit", params={"session_id": session["id"]})
    assert audit_response.status_code == 200
    event_types = [event["event_type"] for event in audit_response.json()["events"]]
    assert event_types == ["session_created", "session_closed"]
    assert all(event["payload_hash"] for event in audit_response.json()["events"])


def test_simurgh_session_creation_sanitizes_metadata(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    create_response = client.post(
        "/api/v1/simurgh/sessions",
        json={
            "actor": "operator",
            "metadata": {
                "channel": "dashboard",
                "source": "simurgh-ui",
                "raw_prompt": "CM4-99 stopped streaming on 192.0.2.33",
                "notes": "customer field evidence",
            },
        },
    )

    assert create_response.status_code == 200
    session = create_response.json()
    assert session["metadata"] == {"channel": "dashboard", "source": "simurgh-ui"}

    list_response = client.get("/api/v1/simurgh/sessions")
    assert list_response.status_code == 200
    serialized = str(list_response.json())
    assert "raw_prompt" not in serialized
    assert "CM4-99" not in serialized
    assert "192.0.2.33" not in serialized


def test_simurgh_session_metadata_rejects_sensitive_allowed_key_values(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    create_response = client.post(
        "/api/v1/simurgh/sessions",
        json={
            "actor": "operator",
            "metadata": {
                "channel": "CM4-99",
                "source": "192.0.2.33",
            },
        },
    )

    assert create_response.status_code == 200
    assert create_response.json()["metadata"] == {}
    list_response = client.get("/api/v1/simurgh/sessions")
    serialized = str(list_response.json())
    assert "CM4-99" not in serialized
    assert "192.0.2.33" not in serialized


def test_simurgh_status_reports_external_assistant_provider(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    client = _client()

    response = client.get("/api/v1/simurgh/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_provider"] == "openai"
    assert payload["assistant_model"] == "gpt-5.6"
    assert payload["assistant_external_provider"] is True
    assert payload["assistant_external_provider_auth_required"] is True


def test_simurgh_runtime_settings_hot_apply_and_persist(monkeypatch, tmp_path):
    env_file = tmp_path / "gcs.env"
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(env_file))
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_OPENAI_MODEL", "gpt-5.5")
    monkeypatch.setenv("MDS_MCP_ENABLED", "false")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    client = _client()

    response = client.put(
        "/api/v1/simurgh/runtime-settings",
        json={
            "provider": "openai",
            "model": "gpt-5.4-nano",
            "mcp_enabled": True,
            "action_circuit_breaker_enabled": True,
            "always_confirm_before_action": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert payload["openai_model"] == "gpt-5.4-nano"
    assert payload["mcp_enabled"] is True
    assert payload["restart_required"] is False
    assert payload["restart_would_have_been_required"] is True
    assert os.environ["MDS_AGENT_PROVIDER"] == "openai"
    assert "MDS_AGENT_PROVIDER=openai" in env_file.read_text(encoding="utf-8")



def test_simurgh_provider_credentials_store_secret_server_side(monkeypatch, tmp_path):
    env_file = tmp_path / "gcs.env"
    key_file = tmp_path / "openai_api_key"
    fake_openai_key = "-".join(("sk", "test", "123456789012345678901234"))
    monkeypatch.setenv("MDS_GCS_SYSTEM_CONFIG", str(env_file))
    monkeypatch.setenv("MDS_AGENT_OPENAI_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    client = _client()

    response = client.put(
        "/api/v1/simurgh/provider-credentials",
        json={
            "openai_api_key": fake_openai_key,
            "set_provider_openai": True,
            "openai_model": "gpt-5.5",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    serialized = str(payload)
    assert "sk-test" not in serialized
    assert payload["credentials"]["openai"]["ready"] is True
    assert payload["credentials"]["openai"]["fingerprint"]
    assert key_file.read_text(encoding="utf-8").strip() == fake_openai_key
    assert key_file.stat().st_mode & 0o777 == 0o600
    env_text = env_file.read_text(encoding="utf-8")
    assert "MDS_AGENT_OPENAI_API_KEY_FILE=" in env_text
    assert "MDS_AGENT_PROVIDER=openai" in env_text
    assert "sk-test" not in env_text

    status_response = client.get("/api/v1/simurgh/provider-credentials")
    assert status_response.status_code == 200
    assert status_response.json()["openai"]["ready"] is True


def test_simurgh_status_warns_when_real_gcs_circuit_breaker_is_off(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "real")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    client = _client()

    response = client.get("/api/v1/simurgh/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "real"
    assert payload["actions_blocked"] is False
    warnings = payload["warnings"]
    assert any("circuit breaker is off" in warning for warning in warnings)
    assert not any("policy profile" in warning for warning in warnings)


def test_simurgh_session_creation_requires_enabled_runtime(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "false")
    client = _client()

    response = client.post("/api/v1/simurgh/sessions", json={"actor": "operator"})

    assert response.status_code == 403


def test_simurgh_session_rejects_unknown_mode(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    client = _client()

    response = client.post("/api/v1/simurgh/sessions", json={"actor": "operator", "mode": "unsafe"})

    assert response.status_code == 400


def test_simurgh_status_uses_canonical_mds_mode(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    client = _client()

    response = client.get("/api/v1/simurgh/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["gcs_mode"] == "sitl"
    assert payload["mode"] == "sitl"
    assert payload["warnings"] == []

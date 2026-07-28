from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

import api_routes.simurgh as simurgh_routes
from agent_runtime import AgentRuntimeError, load_default_tool_registry
from agent_runtime.action_planner import FlightActionDraft, RegistryActionDraft
from agent_runtime.action_intent import (
    ProviderActionPrecondition,
    ProviderActionPlan,
    ProviderActionStep,
    ProviderActionTargetReference,
    build_action_draft_from_provider_plan,
    parse_provider_action_plan,
)
from agent_runtime.action_runs import ActionRunStore
from agent_runtime.assistant import ProviderSemanticRewrite, _semantic_rewrite_from_payload
from agent_runtime.mds_read_tools import MdsReadToolAnswer
from agent_runtime.tool_executor import GuardedToolCallResult, ReadOnlyToolCallResult
from agent_runtime.turn_intent import build_turn_intent_frame
from api_routes.simurgh import (
    SimurghAssistantTurnRequest,
    _action_run_terminal_outcome,
    _action_runner_lease_renewal_interval,
    _command_monitor_success,
    _maintain_action_run_ownership,
    _provider_action_tool_contracts,
    _provider_plan_has_exact_missing_target_binding,
    _structured_action_control,
    _semantic_rewrite_grounding_messages,
    _semantic_rewrite_preserves_draft_facts,
    _submitted_action_progress_outcome,
    _terminal_flight_state_observation,
    _updated_clarification_operator_messages,
    _run_with_action_run_ownership,
    create_simurgh_router,
)

_BaseTestClient = TestClient


@pytest.mark.asyncio
async def test_action_runner_keepalive_renews_during_quiet_work():
    ownership = SimpleNamespace(run_id="run-quiet")
    stop_event = asyncio.Event()
    renewals = []

    async def renew(current):
        renewals.append((current.run_id, time.monotonic()))
        return SimpleNamespace()

    task = asyncio.create_task(
        _maintain_action_run_ownership(
            renew,
            ownership,
            stop_event,
            lease_seconds=0.75,
        )
    )
    await asyncio.sleep(0.8)
    stop_event.set()
    await task

    assert len(renewals) >= 3
    assert _action_runner_lease_renewal_interval(5) < 5


@pytest.mark.asyncio
async def test_action_runner_keepalive_failure_cancels_orchestration():
    ownership = SimpleNamespace(run_id="run-lost")
    operation_started = asyncio.Event()
    operation_cancelled = asyncio.Event()

    async def renew(_current):
        raise simurgh_routes.ActionRunOwnershipError("lease lost")

    async def operation():
        operation_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            operation_cancelled.set()

    with pytest.raises(simurgh_routes.ActionRunOwnershipError, match="ownership was lost"):
        await _run_with_action_run_ownership(
            operation(),
            renew_ownership=renew,
            ownership=ownership,
            lease_seconds=0.75,
        )

    assert operation_started.is_set()
    assert operation_cancelled.is_set()


@pytest.fixture(autouse=True)
def _isolated_action_run_store(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_AGENT_ACTION_RUN_DB", str(tmp_path / "action-runs.sqlite3"))
    original_safe_to_try = simurgh_routes._semantic_rewrite_is_safe_to_try
    original_rewrite = simurgh_routes.rewrite_operator_message_with_provider

    def semantic_test_safe_to_try(**kwargs):
        config = kwargs["assistant_config"]
        turn_intent = kwargs["turn_intent"]
        if config.provider == "mock" and turn_intent.action.has_action_request:
            return True
        return original_safe_to_try(**kwargs)

    def semantic_test_rewrite(**kwargs):
        config = kwargs["config"]
        if config.provider != "mock":
            return original_rewrite(**kwargs)
        allowed_targets = tuple(str(item) for item in kwargs.get("allowed_target_ids") or ())
        previous_action = (
            {
                "target_drone_ids": list(allowed_targets),
                "inferred_target_drone_ids": list(allowed_targets),
            }
            if allowed_targets
            else None
        )
        intent = build_turn_intent_frame(
            kwargs["message"],
            conversation_topic=kwargs.get("conversation_topic") or "",
            previous_action=previous_action,
        )
        draft = intent.action.draft
        if draft is None:
            for prior_message in reversed(tuple(kwargs.get("grounding_messages") or ())):
                prior_intent = build_turn_intent_frame(
                    str(prior_message),
                    conversation_topic=kwargs.get("conversation_topic") or "",
                    previous_action=previous_action,
                )
                if prior_intent.action.draft is not None:
                    draft = prior_intent.action.draft
                    break
        if draft is None:
            return None
        route_hint = (
            "draft_flight_action"
            if isinstance(draft, FlightActionDraft)
            else "draft_sitl_lifecycle_action"
        )
        return _provider_rewrite(
            normalized_message=kwargs["message"],
            route_hint=route_hint,
            action_plan=_provider_plan_from_typed_draft(kwargs["message"], draft),
        )

    # These shims isolate executor/monitor route tests from semantic-model
    # availability. Dedicated semantic tests below provide explicit model
    # outputs and still exercise source grounding and ambiguity handling.
    monkeypatch.setattr(
        simurgh_routes,
        "_semantic_rewrite_is_safe_to_try",
        semantic_test_safe_to_try,
    )
    monkeypatch.setattr(
        simurgh_routes,
        "rewrite_operator_message_with_provider",
        semantic_test_rewrite,
    )


@pytest.fixture(autouse=True)
def _managed_test_client_lifecycle(monkeypatch):
    """Keep detached action runs on the application lifespan during route tests.

    Starlette only starts an application's lifespan when ``TestClient`` is used
    as a context manager. Simurgh action runs intentionally outlive the request
    and therefore need the same persistent loop that production ASGI servers
    provide. The wrapper makes that contract explicit for the many small route
    tests that use a client inline, and closes every client at test teardown.
    """

    clients: list[_BaseTestClient] = []

    class ManagedTestClient(_BaseTestClient):
        _simurgh_lifecycle_entered = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            clients.append(self)
            self.__enter__()

        def __enter__(self):
            if not self._simurgh_lifecycle_entered:
                super().__enter__()
                self._simurgh_lifecycle_entered = True
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            if not self._simurgh_lifecycle_entered:
                return False
            self._simurgh_lifecycle_entered = False
            return super().__exit__(exc_type, exc_value, traceback)

    monkeypatch.setattr(sys.modules[__name__], "TestClient", ManagedTestClient)
    yield
    for client in reversed(clients):
        client.__exit__(None, None, None)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_simurgh_router())
    return TestClient(app)


def _client_with_auth_role(role: str) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def authenticated_actor(request: Request, call_next):
        request.state.mds_auth_context = {
            "kind": "session",
            "username": f"{role}-user",
            "role": role,
        }
        return await call_next(request)

    app.include_router(create_simurgh_router())
    return TestClient(app)


@pytest.mark.parametrize("role", ["agent", "viewer"])
def test_simurgh_action_draft_enforces_authenticated_operator_role(monkeypatch, role):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")

    response = _client_with_auth_role(role).post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "ignored", "message": "Take off drone 1 to 10m"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["safety"]["action_execution"] == "policy_denied"
    assert "required role 'operator'" in " ".join(
        payload["trace"]["safety"]["policy_reasons"]
    )


@pytest.mark.parametrize(
    ("role", "expected_execution"),
    [
        ("operator", "policy_denied"),
        ("admin", "awaiting_confirmation"),
    ],
)
def test_simurgh_sitl_draft_requires_authenticated_admin_role(
    monkeypatch,
    role,
    expected_execution,
):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    response = _client_with_auth_role(role).post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "ignored", "message": "Create one SITL instance"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["safety"]["action_execution"] == expected_execution
    if role == "operator":
        assert "required role 'admin'" in " ".join(
            payload["trace"]["safety"]["policy_reasons"]
        )


def _add_sitl_completion_evidence_routes(
    app: FastAPI,
    *,
    drone_ids: tuple[str, ...] = (),
    ready: bool = True,
    live_drone_ids: set[str] | None = None,
) -> None:
    def current_drone_ids() -> tuple[str, ...]:
        if live_drone_ids is None:
            return drone_ids
        return tuple(sorted(live_drone_ids))

    @app.get("/api/v1/system/sitl/instances")
    async def fake_sitl_completion_instances():
        instance_rows = [
            {
                "container_id": f"container-{drone_id}",
                "name": f"drone-{drone_id}",
                "status": "Up",
                "state": "running",
                "health_status": "healthy",
                "hw_id": drone_id,
            }
            for drone_id in current_drone_ids()
        ]
        return {
            "instances": instance_rows,
            "total_instances": len(instance_rows),
            "docker": {
                "available": True,
                "socket_path": "/var/run/docker.sock",
                "socket_exists": True,
                "daemon_reachable": True,
            },
            "timestamp": int(time.time() * 1000),
        }

    @app.get("/api/v1/fleet/heartbeats")
    async def fake_sitl_completion_heartbeats():
        current_ids = current_drone_ids()
        return {
            "heartbeats": [
                {
                    "hw_id": drone_id,
                    "online": True,
                    "presence_state": "live",
                    "presence": {"fresh": True, "telemetry_recent": True},
                }
                for drone_id in current_ids
            ],
            "total_drones": len(current_ids),
            "online_count": len(current_ids),
            "timestamp": int(time.time() * 1000),
        }

    @app.get("/api/v1/fleet/telemetry")
    async def fake_sitl_completion_telemetry():
        current_ids = current_drone_ids()
        return {
            "telemetry": {
                drone_id: {
                    "telemetry_available": True,
                    "is_ready_to_arm": ready,
                    "is_armed": False,
                    "flight_mode_name": "HOLD",
                    "gps_fix_type": 3,
                    "satellites_visible": 10,
                    "battery_voltage": 16.2,
                }
                for drone_id in current_ids
            },
            "total_drones": len(current_ids),
            "online_drones": len(current_ids),
            "timestamp": int(time.time() * 1000),
        }


def _provider_step(
    message: str,
    excerpt: str,
    *,
    tool_id: str,
    arguments: dict,
    condition: str = "start",
    label: str = "Action",
    monitor_requested: bool = True,
    source_message_index: int = 0,
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
        source_message_index=source_message_index,
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


def _provider_precondition(
    message: str,
    excerpt: str,
    *,
    fact_id: str = "sitl.running_instance_count",
    arguments: dict | None = None,
    expected: object = 0,
    label: str = "No SITL instance is running",
) -> ProviderActionPrecondition:
    start = message.index(excerpt)
    return ProviderActionPrecondition(
        fact_id=fact_id,
        arguments_json=json.dumps(arguments or {}),
        operator="eq",
        expected_json=json.dumps(expected),
        label=label,
        source_start=start,
        source_end=start + len(excerpt),
        source_excerpt=excerpt,
    )


def _conditional_sitl_read_payload(name: str, *, running_count: int) -> dict:
    drone_ids = [str(index) for index in range(1, running_count + 1)]
    if name == "mds.sitl.instances.read":
        return {
            "instances": [
                {
                    "name": f"drone-{drone_id}",
                    "state": "running",
                    "health_status": "healthy",
                    "hw_id": drone_id,
                }
                for drone_id in drone_ids
            ],
            "total_instances": running_count,
            "running_instance_count": running_count,
            "docker": {"available": True, "daemon_reachable": True},
        }
    if name == "mds.sitl.policy.read":
        return {"sim_mode": True, "read_only": False}
    if name == "mds.fleet.heartbeats.read":
        return {
            "heartbeats": [
                {
                    "hw_id": drone_id,
                    "online": True,
                    "presence_state": "live",
                    "presence": {"fresh": True, "telemetry_recent": True},
                }
                for drone_id in drone_ids
            ],
            "total_drones": running_count,
            "online_count": running_count,
        }
    if name == "mds.fleet.telemetry.read":
        return {
            "telemetry": {
                drone_id: {
                    "telemetry_available": True,
                    "is_ready_to_arm": True,
                    "is_armed": False,
                }
                for drone_id in drone_ids
            },
            "total_drones": running_count,
            "online_drones": running_count,
        }
    if name == "mds.fleet.network_status.read":
        return {
            "drones": [
                {"hw_id": drone_id, "reachable": True}
                for drone_id in drone_ids
            ],
            "total_drones": running_count,
            "reachable_count": running_count,
        }
    raise AssertionError(f"unexpected read tool: {name}")


def _provider_rewrite(
    *,
    normalized_message: str,
    route_hint: str,
    action_plan: ProviderActionPlan | None = None,
    read_intents: tuple[str, ...] = (),
    read_options: dict[str, dict[str, bool]] | None = None,
    read_target_drone_ids: tuple[str, ...] = (),
    confidence: float = 0.96,
    response_detail: str = "standard",
    needs_clarification: bool = False,
    clarification_question: str = "",
    clarification_reason: str = "none",
    action_control_explicit: bool = False,
    action_control_source_start: int | None = None,
    action_control_source_end: int | None = None,
    action_control_source_excerpt: str = "",
) -> ProviderSemanticRewrite:
    return ProviderSemanticRewrite(
        normalized_message=normalized_message,
        language="en",
        route_hint=route_hint,
        read_intents=read_intents,
        read_options=read_options or {},
        read_target_drone_ids=read_target_drone_ids,
        confidence=confidence,
        response_detail=response_detail,
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
        clarification_reason=clarification_reason,
        action_control_explicit=action_control_explicit,
        action_control_source_start=action_control_source_start,
        action_control_source_end=action_control_source_end,
        action_control_source_excerpt=action_control_source_excerpt,
        action_plan=action_plan,
        model="test",
        adapter_version="test-semantic-rewrite",
    )


def _provider_plan_from_typed_draft(
    message: str,
    draft: FlightActionDraft | RegistryActionDraft,
) -> ProviderActionPlan:
    """Adapt a typed local draft into fake model output for route isolation."""

    source_end = len(message)

    def tool_step(
        *,
        tool_id: str,
        arguments: dict,
        condition: str,
        monitor_requested: bool,
        label: str,
    ) -> ProviderActionStep:
        clean_arguments = dict(arguments)
        clean_arguments.pop("operator_label", None)
        clean_arguments.pop("idempotency_key", None)
        return ProviderActionStep(
            kind="tool",
            tool_id=tool_id,
            arguments=clean_arguments,
            delay_seconds=None,
            condition=condition,
            monitor_requested=monitor_requested,
            label=label,
            source_start=0,
            source_end=source_end,
            source_excerpt=message,
        )

    if isinstance(draft, FlightActionDraft):
        primary_arguments = dict(draft.command_payload)
        if draft.target_inferred_from:
            primary_arguments.pop("target_drone_ids", None)
        steps = [
            tool_step(
                tool_id="mds.flight.command.execute",
                arguments=primary_arguments,
                condition="start",
                monitor_requested=draft.monitor_requested,
                label=draft.mission_name.replace("_", " ").title(),
            )
        ]
        summary = f"Run {draft.mission_name.replace('_', ' ').lower()}"
    else:
        steps = [
            tool_step(
                tool_id=draft.tool_id,
                arguments=dict(draft.arguments),
                condition="start",
                monitor_requested=draft.monitor_requested,
                label=draft.action_label,
            )
        ]
        summary = draft.action_label

    for item in draft.post_actions:
        item_type = str(item.get("type") or "")
        if item_type == "delay":
            steps.append(
                ProviderActionStep(
                    kind="delay",
                    tool_id="",
                    arguments={},
                    delay_seconds=float(item["delay_seconds"]),
                    condition=str(item.get("condition") or "after_command_terminal_success"),
                    monitor_requested=False,
                    label=str(item.get("action_label") or "Wait"),
                    source_start=0,
                    source_end=source_end,
                    source_excerpt=message,
                )
            )
            continue
        steps.append(
            tool_step(
                tool_id=str(item.get("tool_id") or ""),
                arguments=dict(item.get("arguments") or {}),
                condition=str(item.get("condition") or "after_command_terminal_success"),
                monitor_requested=bool(item.get("monitor_requested")),
                label=str(item.get("action_label") or "Action"),
            )
        )

    preconditions = tuple(
        ProviderActionPrecondition(
            fact_id=item.fact_id,
            arguments_json=json.dumps(dict(item.arguments)),
            operator=item.operator,
            expected_json=json.dumps(item.expected),
            label=item.label,
            source_start=0,
            source_end=source_end,
            source_excerpt=message,
        )
        for item in draft.preconditions
    )
    return ProviderActionPlan(
        summary=summary,
        steps=tuple(steps),
        preconditions=preconditions,
        coverage_complete=True,
    )


def test_provider_action_contracts_require_explicit_registry_orchestration_metadata():
    contracts = _provider_action_tool_contracts(load_default_tool_registry())

    assert {str(item["id"]) for item in contracts} == {
        "mds.flight.command.execute",
        "mds.sitl.fleet.reconcile",
        "mds.sitl.instances.action",
        "mds.sitl.instances.create",
    }
    assert all(str(item.get("monitor_kind") or "") for item in contracts)
    create_contract = next(item for item in contracts if item["id"] == "mds.sitl.instances.create")
    assert create_contract["fixed_cardinality"] == 1
    assert create_contract["result_target_source"] == "affected_instances"
    assert "expected_running_instance_count" not in create_contract["input_schema"]["properties"]
    flight_contract = next(item for item in contracts if item["id"] == "mds.flight.command.execute")
    assert flight_contract["target_binding"] == {
        "argument": "target_drone_ids",
        "value_template": "{id}",
    }
    precision_schema = flight_contract["input_schema"]["properties"]["precision_move"]
    assert precision_schema["additionalProperties"] is False
    assert precision_schema["required"] == ["frame", "translation_m"]
    assert set(precision_schema["properties"]["translation_m"]["properties"]) == {
        "north",
        "east",
        "forward",
        "right",
        "up",
    }
    action_contract = next(item for item in contracts if item["id"] == "mds.sitl.instances.action")
    assert action_contract["target_binding"] == {
        "argument": "instance_names",
        "value_template": "drone-{id}",
    }


@pytest.mark.parametrize(
    "status",
    (
        {"status": "completed", "outcome": "failed"},
        {"status": "failed", "outcome": "completed"},
    ),
)
def test_command_monitor_rejects_contradictory_terminal_success(status):
    assert _command_monitor_success(status) is False


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


def test_action_run_never_succeeds_when_final_landed_state_is_unverified():
    draft = FlightActionDraft(
        draft_id="act-final-state",
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
    state, summary = _action_run_terminal_outcome(
        action_execution="submitted",
        monitor_result={
            "status": "completion_unverified",
            "success": False,
            "command_success": True,
            "completion_verification": {
                "status": "timeout",
                "verified": False,
                "summary": "Final landed/RTL state was not confirmed from fresh telemetry before timeout.",
            },
        },
        post_action_results=(
            {
                "label": "Remove SITL instance(s)",
                "status": "skipped",
                "is_error": True,
            },
        ),
        cancelled=False,
        total_steps=2,
        terminal_evidence_required=True,
    )

    assert state == "failed"
    assert "not confirmed" in summary
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


def test_action_run_requires_terminal_evidence_when_monitoring_is_required():
    state, summary = _action_run_terminal_outcome(
        action_execution="submitted",
        monitor_result=None,
        post_action_results=(),
        cancelled=False,
        total_steps=1,
        terminal_evidence_required=True,
    )

    assert state == "failed"
    assert "no terminal completion evidence" in summary


def test_action_run_surfaces_actionable_sitl_step_failure_detail():
    state, summary = _action_run_terminal_outcome(
        action_execution="submitted",
        monitor_result={"status": "succeeded", "success": True},
        post_action_results=(
            {
                "label": "Create a fresh SITL instance",
                "status": "failed",
                "summary": (
                    "create_dockers.sh exited with code 1: "
                    "docker: pull access denied for private-sitl"
                ),
                "is_error": True,
            },
        ),
        cancelled=False,
        total_steps=2,
        terminal_evidence_required=True,
    )

    assert state == "failed"
    assert summary == (
        "Create a fresh SITL instance: create_dockers.sh exited with code 1: "
        "docker: pull access denied for private-sitl"
    )


@pytest.mark.parametrize(
    ("mission_type", "telemetry", "verified", "reason_fragment"),
    [
        (101, {"is_armed": False, "is_landed": True}, True, ""),
        (101, {"is_armed": False, "landed_state": 1}, True, ""),
        (
            101,
            {"is_armed": False, "landed_state": 2, "relative_altitude_m": 0.1, "velocity_down": 0.0},
            False,
            "land detector",
        ),
        (
            101,
            {"is_armed": False, "relative_altitude_m": 0.2, "velocity_down": 0.1},
            True,
            "",
        ),
        (
            101,
            {"is_armed": False, "relative_altitude_m": 8.0, "velocity_down": 0.0},
            False,
            "relative altitude",
        ),
        (
            104,
            {
                "is_armed": False,
                "is_landed": True,
                "distance_to_home_m": 3.0,
            },
            True,
            "",
        ),
        (
            104,
            {
                "is_armed": False,
                "is_landed": True,
                "distance_to_home_m": 30.0,
            },
            False,
            "home-distance",
        ),
        (
            104,
            {"is_armed": False, "is_landed": True},
            False,
            "distance-to-home",
        ),
        (
            104,
            {"is_armed": False, "is_landed": True, "distance_to_home_m": -1.0},
            False,
            "invalid",
        ),
        (
            104,
            {
                "is_armed": False,
                "state": 0,
                "mission": 0,
                "velocity_down": 0.0,
                "distance_to_home_m": 0.1,
            },
            True,
            "",
        ),
        (
            104,
            {
                "is_armed": False,
                "state": 0,
                "mission": 0,
                "velocity_down": 0.0,
            },
            False,
            "distance-to-home",
        ),
    ],
)
def test_terminal_flight_state_observation_requires_landed_and_rtl_home_evidence(
    mission_type,
    telemetry,
    verified,
    reason_fragment,
):
    observation = _terminal_flight_state_observation(
        telemetry,
        target="1",
        mission_type=mission_type,
    )

    assert observation["verified"] is verified
    if reason_fragment:
        assert any(reason_fragment in reason for reason in observation["reasons"])
    else:
        assert observation["reasons"] == []


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
    listed_run = listed.json()["runs"][0]
    assert listed_run["run_id"] == run.run_id
    assert listed_run["revision"] == 2
    assert listed_run["last_event_id"] == started.id

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
    assert paused.json()["revision"] == 3
    assert paused.json()["last_event_id"] > started.id

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


def test_command_monitor_emits_changed_tracker_activity(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    monkeypatch.setattr("api_routes.simurgh.ACTION_MONITOR_POLL_SECONDS", 0.001)
    tracker_calls = 0

    class FakeTracker:
        async def get_status(self, command_id):
            nonlocal tracker_calls
            tracker_calls += 1
            if tracker_calls == 1:
                return {
                    "command_id": command_id,
                    "status": "executing",
                    "phase": "running",
                    "progress": {
                        "stage": "takeoff",
                        "label": "Climbing to target altitude",
                        "message": "Altitude target is still in progress.",
                    },
                }
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
                "progress": {"label": "Target altitude reached"},
            }

    class FakeDeps:
        telemetry_data_all_drones = {
            "1": {
                "telemetry_available": True,
                "is_ready_to_arm": True,
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
        return {
            "success": True,
            "command_id": "cmd-progress",
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": "TAKE_OFF",
            "target_drones": command.target_drone_ids,
            "results_summary": {"accepted": 1, "offline": 0, "rejected": 0, "errors": 0},
        }

    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit)
    app = FastAPI()
    app.include_router(create_simurgh_router())
    with TestClient(app) as client:
        draft = client.post(
            "/api/v1/simurgh/assistant/turns",
            json={"actor": "operator", "message": "Send drone 1 to takeoff to 10m and report when done"},
        ).json()
        draft_id = re.search(r"act-[0-9a-f]+", draft["content"]).group(0)
        confirmed = client.post(
            "/api/v1/simurgh/assistant/turns",
            json={
                "actor": "operator",
                "session_id": draft["session"]["id"],
                "message": "Confirm",
                "metadata": {
                    "source": "simurgh-dashboard",
                    "action_intent": "confirm",
                    "draft_id": draft_id,
                },
            },
        ).json()
        run = _wait_for_action_run(client, confirmed)
        run_id = confirmed["trace"]["safety"]["action_run"]["run_id"]
        events = client.get(f"/api/v1/simurgh/action-runs/{run_id}/events").json()["events"]

    assert run["state"] == "succeeded"
    labels = [str(event.get("payload", {}).get("label") or "") for event in events]
    assert "Climbing to target altitude" in labels
    assert any("Command completed" in label for label in labels)


def test_structured_dashboard_action_control_requires_a_valid_draft_id():
    request = SimurghAssistantTurnRequest(
        actor="operator",
        message="Confirm",
        metadata={
            "source": "simurgh-dashboard",
            "action_intent": "confirm",
            "draft_id": "act-12345678",
        },
    )

    assert _structured_action_control(request) == ("confirm", "act-12345678")
    assert _structured_action_control(
        request.model_copy(
            update={
                "message": "Make the wait 10 seconds.",
                "metadata": {
                    **request.metadata,
                    "action_intent": "amend",
                },
            }
        )
    ) == ("amend", "act-12345678")
    assert _structured_action_control(
        request.model_copy(update={"metadata": {**request.metadata, "draft_id": "not-a-draft"}})
    ) == ("", "")


def test_structured_dashboard_amendment_replaces_pending_plan_without_execution(
    monkeypatch,
):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    initial_message = "Take off drone 1 to 10m, wait 5s, then RTL."
    amendment_message = "Make the wait 10 seconds instead."
    calls = []

    def fake_rewrite_operator_message_with_provider(**kwargs):
        calls.append(kwargs)
        if kwargs["message"] == initial_message:
            return _provider_rewrite(
                normalized_message="take off drone 1 to 10 m, wait 5 seconds, then RTL",
                route_hint="draft_flight_action",
                action_plan=ProviderActionPlan(
                    summary="Take off Drone 1, wait, then return",
                    steps=(
                        _provider_step(
                            initial_message,
                            "Take off drone 1 to 10m",
                            tool_id="mds.flight.command.execute",
                            arguments={
                                "mission_type": 10,
                                "target_drone_ids": ["1"],
                                "takeoff_altitude": 10,
                            },
                            label="Take off Drone 1 to 10 m",
                        ),
                        ProviderActionStep(
                            kind="delay",
                            tool_id="",
                            arguments={},
                            delay_seconds=5,
                            condition="after_command_terminal_success",
                            monitor_requested=False,
                            label="Wait 5 seconds",
                            source_start=initial_message.index("wait 5s"),
                            source_end=initial_message.index("wait 5s") + len("wait 5s"),
                            source_excerpt="wait 5s",
                        ),
                        _provider_step(
                            initial_message,
                            "RTL",
                            tool_id="mds.flight.command.execute",
                            arguments={
                                "mission_type": 104,
                                "target_drone_ids": ["1"],
                            },
                            condition="after_command_terminal_success",
                            label="Return to launch",
                        ),
                    ),
                    target_references=(
                        ProviderActionTargetReference(
                            target_id="1",
                            source_message_index=0,
                            source_start=initial_message.index("drone 1"),
                            source_end=initial_message.index("drone 1") + len("drone 1"),
                            source_excerpt="drone 1",
                        ),
                    ),
                ),
            )

        pending_plan = kwargs["grounding_messages"][0]
        assert "Mission plan:" in pending_plan
        assert "Take off to 10 m" in pending_plan
        assert "Wait 5 second(s)" in pending_plan
        assert "Return to launch" in pending_plan
        assert "Pending reviewed draft" in kwargs["previous_action_summary"]
        assert kwargs["allowed_target_ids"] == ["1"]
        return _provider_rewrite(
            normalized_message="keep the pending plan but wait 10 seconds",
            route_hint="draft_flight_action",
            action_plan=ProviderActionPlan(
                summary="Take off Drone 1, wait 10 seconds, then return",
                steps=(
                    _provider_step(
                        pending_plan,
                        "Take off to 10 m",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 10,
                            "takeoff_altitude": 10,
                        },
                        label="Take off Drone 1 to 10 m",
                        source_message_index=1,
                    ),
                    ProviderActionStep(
                        kind="delay",
                        tool_id="",
                        arguments={},
                        delay_seconds=10,
                        condition="after_command_terminal_success",
                        monitor_requested=False,
                        label="Wait 10 seconds",
                        source_start=amendment_message.index("wait 10 seconds"),
                        source_end=(
                            amendment_message.index("wait 10 seconds")
                            + len("wait 10 seconds")
                        ),
                        source_excerpt="wait 10 seconds",
                    ),
                    _provider_step(
                        pending_plan,
                        "Return to launch",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 104},
                        condition="after_command_terminal_success",
                        label="Return to launch",
                        source_message_index=1,
                    ),
                ),
            ),
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()
    initial = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": initial_message},
    )
    assert initial.status_code == 200
    initial_payload = initial.json()
    original_draft = initial_payload["trace"]["safety"]["action_draft"]

    amended = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": initial_payload["session"]["id"],
            "message": amendment_message,
            "metadata": {
                "source": "simurgh-dashboard",
                "action_intent": "amend",
                "draft_id": original_draft["draft_id"],
            },
        },
    )

    assert amended.status_code == 200, amended.text
    payload = amended.json()
    assert "action_draft" in payload["trace"]["safety"], json.dumps(
        payload,
        indent=2,
        sort_keys=True,
    )
    replacement = payload["trace"]["safety"]["action_draft"]
    assert len(calls) == 2
    assert replacement["draft_id"] != original_draft["draft_id"]
    assert replacement["post_actions"][0]["delay_seconds"] == 10
    assert replacement["post_actions"][1]["arguments"]["mission_type"] == 104
    assert payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"
    assert payload["trace"]["intent"]["amends_action_draft_id"] == original_draft["draft_id"]


@pytest.mark.asyncio
async def test_simurgh_pause_during_delay_applies_before_following_step(monkeypatch):
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
                "is_landed": True,
                "relative_altitude_m": 0.1,
                "velocity_down": 0.0,
                "distance_to_home_m": 0.5,
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

    run_id = response_payload["trace"]["safety"]["action_run"]["run_id"]
    pause_requested = action_run_store.request_control(
        run_id,
        actor="operator",
        action="pause_after_current_step",
    )
    assert pause_requested.state == "pause_requested"
    release_wait.set()
    pause_deadline = time.monotonic() + 5.0
    while time.monotonic() < pause_deadline:
        if action_run_store.require(run_id).state == "paused":
            break
        await asyncio.sleep(0.01)

    assert action_run_store.require(run_id).state == "paused"
    assert [command.mission_type for command in submitted] == [10]
    action_run_store.request_control(
        run_id,
        actor="operator",
        action="resume",
    )
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
                "is_landed": True,
                "relative_altitude_m": 0.1,
                "velocity_down": 0.0,
                "distance_to_home_m": 0.5,
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
                            condition="after_command_terminal_success",
                            label="Return to launch",
                        ),
                    ),
                ),
            )
        if message.startswith("confirm action"):
            return _provider_rewrite(
                normalized_message=message,
                route_hint="confirm_pending_action",
                action_control_explicit=True,
                action_control_source_start=0,
                action_control_source_end=len(message),
                action_control_source_excerpt=message,
            )
        return _provider_rewrite(
            normalized_message="cancel the active operation",
            route_hint="reject_pending_action",
            action_control_explicit=True,
            action_control_source_start=0,
            action_control_source_end=len(message),
            action_control_source_excerpt=message,
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


@pytest.mark.asyncio
async def test_cancel_remaining_drains_active_flight_command_before_terminal(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    monkeypatch.setattr("api_routes.simurgh.ACTION_MONITOR_POLL_SECONDS", 0.001)
    monkeypatch.setattr("api_routes.simurgh.ACTION_MONITOR_HEARTBEAT_SECONDS", 0.003)
    command_monitor_started = asyncio.Event()
    release_command = asyncio.Event()
    submitted = []
    tracker_calls = 0

    class FakeTracker:
        async def get_status(self, command_id):
            nonlocal tracker_calls
            tracker_calls += 1
            command_monitor_started.set()
            if not release_command.is_set():
                return {
                    "command_id": command_id,
                    "status": "executing",
                    "phase": "running",
                    "progress": {
                        "stage": "takeoff",
                        "label": "Climbing to target altitude",
                    },
                }
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
            }

    tracker = FakeTracker()

    class FakeDeps:
        telemetry_data_all_drones = {
            "1": {
                "telemetry_available": True,
                "is_ready_to_arm": True,
                "timestamp": int(time.time() * 1000),
            }
        }
        last_telemetry_time = {"1": time.time()}
        data_lock = None

        def get_all_heartbeats(self):
            return {"1": {"timestamp": int(time.time() * 1000)}}

        def get_command_tracker(self):
            return tracker

    async def fake_submit(_deps, command):
        submitted.append(command)
        return {
            "success": True,
            "command_id": f"cmd-{len(submitted)}",
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": str(command.mission_type),
            "target_drones": command.target_drone_ids,
            "results_summary": {
                "accepted": 1,
                "offline": 0,
                "rejected": 0,
                "errors": 0,
            },
        }

    monkeypatch.setattr(
        "api_routes.simurgh._request_scoped_deps",
        lambda _base, _request: FakeDeps(),
    )
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit)

    app = FastAPI()
    action_run_store = ActionRunStore(os.environ["MDS_AGENT_ACTION_RUN_DB"])
    app.include_router(
        create_simurgh_router(
            SimpleNamespace(simurgh_action_run_store=action_run_store)
        )
    )
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
        SimurghAssistantTurnRequest(
            actor="operator",
            message="takeoff drone 1 to 10m, wait 5s, move 5m north, then RTL",
        ),
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
    run_id = confirm_response.model_dump(mode="json")["trace"]["safety"]["action_run"]["run_id"]
    await asyncio.wait_for(command_monitor_started.wait(), timeout=5.0)

    cancelled = action_run_store.request_control(
        run_id,
        actor="operator",
        action="cancel_remaining",
    )
    assert cancelled.state == "cancel_requested"
    heartbeat_deadline = time.monotonic() + 5.0
    while time.monotonic() < heartbeat_deadline:
        events = action_run_store.list_events(run_id)
        if any(
            event.payload.get("progress_kind") == "heartbeat"
            for event in events
        ):
            break
        await asyncio.sleep(0.005)

    draining = action_run_store.require(run_id)
    assert draining.state == "cancel_requested"
    assert draining.terminal is False
    assert [command.mission_type for command in submitted] == [10]
    assert tracker_calls > 1

    release_command.set()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if action_run_store.require(run_id).terminal:
            break
        await asyncio.sleep(0.01)

    terminal = action_run_store.require(run_id)
    assert terminal.state == "cancelled"
    assert [command.mission_type for command in submitted] == [10]
    assert terminal.result["monitor_result"]["status"] == "terminal_success"
    assert terminal.result["monitor_result"]["cancel_requested"] is True
    assert terminal.result["post_action_results"][0]["status"] == "cancelled"
    events = action_run_store.list_events(run_id)
    labels = [str(event.payload.get("label") or "") for event in events]
    drain_index = next(
        index
        for index, label in enumerate(labels)
        if "draining current command" in label
    )
    terminal_index = next(
        index
        for index, event in enumerate(events)
        if event.payload.get("stage") == "monitor"
        and event.payload.get("state") == "complete"
        and event.payload.get("command_id") == "cmd-1"
    )
    cancelled_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "run_cancelled"
    )
    assert drain_index < terminal_index < cancelled_index
    heartbeats = [
        event.payload
        for event in action_run_store.list_events(run_id)
        if event.payload.get("progress_kind") == "heartbeat"
    ]
    assert heartbeats
    assert all(item["current_step"]["index"] == 1 for item in heartbeats)
    assert all(item["latest_evidence"]["source"] == "command_tracker" for item in heartbeats)
    assert all(item["elapsed_seconds"] >= 0 for item in heartbeats)


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


def test_flight_plan_interpretation_is_runtime_mode_neutral(monkeypatch):
    plans = []
    for runtime_mode in ("sitl", "real"):
        monkeypatch.setenv("MDS_MODE", runtime_mode)
        monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
        monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
        monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
        response = _client().post(
            "/api/v1/simurgh/assistant/turns",
            json={
                "actor": "operator",
                "message": "takeoff drone 1 to 10m, wait 5s, move 10m east, then RTL",
            },
        )
        assert response.status_code == 200
        draft = response.json()["trace"]["safety"]["action_draft"]
        plans.append(
            {
                "mission_name": draft["mission_name"],
                "targets": draft["target_drone_ids"],
                "takeoff_altitude": draft["command_payload"]["takeoff_altitude"],
                "post_types": [item["type"] for item in draft["post_actions"]],
                "post_missions": [
                    item.get("arguments", {}).get("mission_type")
                    for item in draft["post_actions"]
                    if item["type"] == "flight_command"
                ],
                "display_labels": [item["label"] for item in draft["display_plan"]["steps"]],
            }
        )

    assert plans[0] == plans[1]


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

    class FakeTracker:
        async def get_status(self, command_id):
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
                "progress": "Completed",
            }

    class FakeDeps:
        def get_command_tracker(self):
            return FakeTracker()

    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
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


def test_simurgh_rechecks_circuit_breaker_immediately_before_flight_dispatch(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []
    original_validate = simurgh_routes.SubmitCommandRequest.model_validate

    def flip_circuit_breaker(_model, payload):
        command = original_validate(payload)
        monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
        return command

    async def fake_submit_tracked_command(_deps, command):
        submitted.append(command)
        return {"command_id": "must-not-dispatch"}

    monkeypatch.setattr(
        simurgh_routes.SubmitCommandRequest,
        "model_validate",
        classmethod(flip_circuit_breaker),
    )
    monkeypatch.setattr(
        "api_routes.simurgh.submit_tracked_command",
        fake_submit_tracked_command,
    )
    client = _client()
    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Take off drone 1 to 10m"},
    )
    draft_payload = draft_response.json()
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)

    confirmed = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_payload["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )

    assert confirmed.status_code == 200
    run = _wait_for_action_run(client, confirmed.json())
    assert run["state"] == "failed"
    assert run["result"]["action_execution"] == "blocked_by_circuit_breaker"
    assert "circuit breaker" in run["result"]["rejection_detail"].lower()
    assert submitted == []


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


@pytest.mark.parametrize("control_message", ["Confirm", "Cancel action"])
def test_simurgh_bare_control_represents_cross_session_pending_action_without_execution(
    monkeypatch,
    control_message,
):
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

    control_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": control_message},
    )

    assert control_response.status_code == 200
    payload = control_response.json()
    assert "Here is the pending Simurgh action draft" in payload["content"]
    assert "It has not been executed yet" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "pending_action_summary"
    assert payload["trace"]["safety"]["action_draft"]["draft_id"].startswith("act-")
    assert submitted == []


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


def test_source_grounded_multilingual_rejection_preserves_explicit_draft_id(
    monkeypatch,
):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    def fake_rewrite_operator_message_with_provider(**kwargs):
        message = kwargs["message"]
        if message.startswith("takeoff drone"):
            target_id = "1" if "drone 1" in message else "2"
            return _provider_rewrite(
                normalized_message=message,
                route_hint="draft_flight_action",
                action_plan=ProviderActionPlan(
                    summary=f"Take off Drone {target_id}",
                    steps=(
                        _provider_step(
                            message,
                            message,
                            tool_id="mds.flight.command.execute",
                            arguments={
                                "mission_type": 10,
                                "target_drone_ids": [target_id],
                                "takeoff_altitude": 10,
                            },
                            label=f"Take off Drone {target_id}",
                        ),
                    ),
                ),
            )
        route_hint = (
            "reject_pending_action"
            if "لغو" in message
            else "confirm_pending_action"
        )
        return _provider_rewrite(
            normalized_message=message,
            route_hint=route_hint,
            action_control_explicit=True,
            action_control_source_start=0,
            action_control_source_end=len(message),
            action_control_source_excerpt=message,
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()
    first = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "takeoff drone 1 to 10m"},
    ).json()
    second = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "takeoff drone 2 to 10m"},
    ).json()
    first_draft_id = first["trace"]["safety"]["action_draft"]["draft_id"]
    second_draft_id = second["trace"]["safety"]["action_draft"]["draft_id"]

    rejected = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": f"این پیش‌نویس را لغو کن {first_draft_id}",
        },
    )

    assert rejected.status_code == 200
    rejected_payload = rejected.json()
    assert rejected_payload["trace"]["safety"]["action_draft"]["draft_id"] == first_draft_id
    assert rejected_payload["trace"]["safety"]["action_execution"] == "cancelled_confirmation"

    still_pending = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": f"confirm action {second_draft_id}",
        },
    )
    assert still_pending.status_code == 200
    assert still_pending.json()["trace"]["safety"]["action_execution"] == (
        "blocked_by_circuit_breaker"
    )


@pytest.mark.parametrize(
    (
        "completion_request",
        "completion_mission_type",
        "completion_mission_name",
        "completion_display_label",
        "completion_progress_label",
    ),
    (
        (
            "Now land the drone and once disarmed, report and remove the sitl instance clean it up",
            101,
            "LAND",
            "Land",
            "land",
        ),
        (
            "Now RTL the drone and once landed and disarmed, report and remove the sitl instance clean it up",
            104,
            "RETURN_RTL",
            "Return to launch",
            "return rtl",
        ),
    ),
)
def test_simurgh_followup_landing_command_monitors_previous_drone_and_removes_sitl(
    monkeypatch,
    request,
    completion_request,
    completion_mission_type,
    completion_mission_name,
    completion_display_label,
    completion_progress_label,
):
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
                "is_landed": True,
                "relative_altitude_m": 0.1,
                "velocity_down": 0.0,
                "home_distance_m": 0.2,
            }
        }
        last_telemetry_time = {"1": time.time()}

        def get_all_heartbeats(self):
            return {"1": {"timestamp": int(time.time() * 1000)}}

        def get_command_tracker(self):
            return FakeTracker()

    async def fake_submit_tracked_command(_deps, command):
        submitted.append(command)
        mission_name = (
            "TAKE_OFF"
            if command.mission_type == 10
            else completion_mission_name
        )
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

    async def fake_guarded_route_tool(
        _request, *, name, arguments, channel, approved, registry, policy, **_kwargs
    ):
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
                "operation_id": "sitl-op-remove-1",
                "status": "accepted",
                "summary": "Removing drone-1",
            },
            status_code=200,
        )

    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    app = FastAPI()

    @app.get("/api/v1/system/sitl/operations/{operation_id}")
    async def fake_sitl_operation_status(operation_id: str):
        return {
            "operation_id": operation_id,
            "operation_type": "remove_instances",
            "status": "succeeded",
            "summary": "Removed drone-1",
            "affected_instances": ["drone-1"],
        }

    @app.get("/api/v1/system/sitl/instances")
    async def fake_removed_sitl_inventory():
        return {
            "instances": [],
            "total_instances": 0,
            "docker": {"available": True, "daemon_reachable": True},
        }

    app.include_router(create_simurgh_router())
    client_context = TestClient(app)
    client = client_context.__enter__()
    request.addfinalizer(lambda: client_context.__exit__(None, None, None))

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
            "message": completion_request,
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
        completion_display_label,
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
    assert [command.mission_type for command in submitted] == [
        10,
        completion_mission_type,
    ]
    assert submitted[-1].target_drone_ids == ["1"]
    land_events = client.get(
        f"/api/v1/simurgh/action-runs/{land_run['run_id']}/events"
    ).json()["events"]
    completion_labels = [
        str(event.get("payload", {}).get("label") or "") for event in land_events
    ]
    normalized_completion_labels = [
        label.casefold() for label in completion_labels
    ]
    assert any(
        f"{completion_progress_label} - verifying landed state" in label
        for label in normalized_completion_labels
    )
    assert any(
        f"{completion_progress_label} - landed and disarmed" in label
        for label in normalized_completion_labels
    )
    assert not any(
        f"{completion_progress_label} - completed" in label
        for label in normalized_completion_labels
    )
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
                "is_landed": True,
                "relative_altitude_m": 0.1,
                "velocity_down": 0.0,
                "distance_to_home_m": 0.5,
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

    async def fake_guarded_route_tool(
        _request, *, name, arguments, channel, approved, registry, policy, **_kwargs
    ):
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
            "operation_type": "create_instance",
            "status": "succeeded",
            "summary": "Created drone-1",
            "affected_instances": ["drone-1"],
        }

    _add_sitl_completion_evidence_routes(app, drone_ids=("1",))

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
    assert create_run["result"]["monitor_result"]["completion_verification"]["verified"] is True

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
    flight_run_id = flight_confirm_payload["trace"]["safety"]["action_run"]["run_id"]
    flight_events = client.get(f"/api/v1/simurgh/action-runs/{flight_run_id}/events").json()["events"]
    flight_progress_labels = [
        str(event.get("payload", {}).get("label") or "")
        for event in flight_events
        if event.get("event_type") == "progress"
    ]
    assert any("Step 2/4: wait 10 second(s) - 9s remaining" in label for label in flight_progress_labels)
    assert any("Step 3/4: precision move" in label for label in flight_progress_labels)
    assert any("Step 4/4: return rtl" in label for label in flight_progress_labels)

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
    assert "simurgh.session.previous_action.read" in history_payload["trace"]["tool"]["ids"]
    assert "mds.flight.command.execute" not in history_payload["trace"]["tool"]["ids"]
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
        "skipped",
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
    ]

    post_failure_draft = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": sitl_status["session"]["id"],
            "message": "takeoff drone 1 to 10m, wait 5s, move 10m north, then RTL",
        },
    ).json()
    post_failure_id = re.search(r"act-[0-9a-f]+", post_failure_draft["content"]).group(0)
    terminal_failures.add("cmd-10")
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
        "skipped",
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
        10,
        112,
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

    now = time.time()
    deps = SimpleNamespace(
        sitl_control_service=FakeSitlService(),
        telemetry_data_all_drones={
            "1": {
                "hw_id": "1",
                "telemetry_available": True,
                "is_ready_to_arm": True,
            }
        },
        last_telemetry_time={"1": now},
        get_all_heartbeats=lambda: {
            "1": {"hw_id": "1", "timestamp": int(now * 1000)}
        },
    )
    app = FastAPI()
    app.include_router(create_simurgh_router(deps))
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
    assert action_draft["target_inferred_from"] == "single_live_fleet_presence"
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


def test_simurgh_provider_plan_resolves_unique_structured_runtime_target(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    message = (
        "Use the active drone: takeoff 10m, wait 10s, fly 20m east, "
        "wait 30s, then RTL."
    )

    class FakeSitlService:
        def list_instances(self):
            return SimpleNamespace(
                instances=[
                    SimpleNamespace(
                        name="drone-1",
                        state="running",
                        status="running",
                        hw_id="1",
                    ),
                ]
            )

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        return _provider_rewrite(
            normalized_message=message,
            route_hint="draft_flight_action",
            confidence=0.97,
            needs_clarification=True,
            clarification_question="Which drone should I use?",
            clarification_reason="missing_runtime_context",
            action_plan=ProviderActionPlan(
                summary="Run the requested mission with the active drone",
                steps=(
                    _provider_step(
                        message,
                        "takeoff 10m",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 10, "takeoff_altitude": 10},
                        label="Take off to 10 m",
                    ),
                    _provider_delay(message, "wait 10s", 10),
                    _provider_step(
                        message,
                        "fly 20m east",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 112,
                            "precision_move": {
                                "frame": "ned",
                                "translation_m": {
                                    "north": 0,
                                    "east": 20,
                                    "up": 0,
                                },
                            },
                        },
                        condition="after_command_terminal_success",
                        label="Move 20 m east",
                    ),
                    _provider_delay(message, "wait 30s", 30),
                    _provider_step(
                        message,
                        "RTL",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 104},
                        condition="after_command_terminal_success",
                        label="Return to launch",
                    ),
                ),
            ),
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    now = time.time()
    deps = SimpleNamespace(
        sitl_control_service=FakeSitlService(),
        telemetry_data_all_drones={
            "1": {
                "hw_id": "1",
                "telemetry_available": True,
                "is_ready_to_arm": True,
            }
        },
        last_telemetry_time={"1": now},
        get_all_heartbeats=lambda: {
            "1": {"hw_id": "1", "timestamp": int(now * 1000)}
        },
    )
    app = FastAPI()
    app.include_router(
        create_simurgh_router(deps)
    )
    response = TestClient(app).post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["intent"]["route"] == "action_draft"
    semantic = payload["trace"]["intent"]["provider_semantic_rewrite"]
    assert semantic["usable_for_routing"] is True
    assert semantic["needs_clarification"] is False
    assert "unique_structured_runtime_target_resolved_locally" in semantic["notes"]
    draft = payload["trace"]["safety"]["action_draft"]
    assert draft["target_drone_ids"] == ["1"]
    assert draft["target_inferred_from"] == "single_live_fleet_presence"
    assert [item["type"] for item in draft["post_actions"]] == [
        "delay",
        "flight_command",
        "delay",
        "flight_command",
    ]


def test_runtime_target_resolver_rejects_different_or_already_bound_target():
    message = "take off to 10 m"
    contracts = _provider_action_tool_contracts(load_default_tool_registry())
    contract_map = {
        item["id"]: {
            **item,
            "required": tuple(item["input_schema"].get("required") or ()),
        }
        for item in contracts
    }
    facts = {
        item.id: item
        for item in simurgh_routes.assistant_fact_map(load_default_tool_registry()).values()
    }

    different = ProviderActionPlan(
        summary="Take off",
        steps=(
            _provider_step(
                message,
                message,
                tool_id="mds.flight.command.execute",
                arguments={
                    "mission_type": 10,
                    "takeoff_altitude": 10,
                    "target_drone_ids": ["2"],
                },
                label="Take off",
            ),
        ),
    )
    already_bound = ProviderActionPlan(
        summary="Take off",
        steps=(
            _provider_step(
                message,
                message,
                tool_id="mds.flight.command.execute",
                arguments={
                    "mission_type": 10,
                    "takeoff_altitude": 10,
                    "target_drone_ids": ["1"],
                },
                label="Take off",
            ),
        ),
    )

    assert not _provider_plan_has_exact_missing_target_binding(
        different,
        runtime_targets=("1",),
        tool_contracts=contract_map,
        fact_contracts=facts,
    )
    assert not _provider_plan_has_exact_missing_target_binding(
        already_bound,
        runtime_targets=("1",),
        tool_contracts=contract_map,
        fact_contracts=facts,
    )


def test_simurgh_conditional_flight_binds_readiness_fact_to_same_live_target(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    message = (
        "If the active drone is ready to fly, take off to 10m, wait 10s, "
        "fly 20m east, wait 30s, then RTL."
    )

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        return _provider_rewrite(
            normalized_message="Run the requested conditional flight",
            route_hint="draft_flight_action",
            confidence=0.98,
            action_plan=ProviderActionPlan(
                summary="Run the mission only when the active drone is ready",
                preconditions=(
                    _provider_precondition(
                        message,
                        "If the active drone is ready to fly",
                        fact_id="fleet.targets_ready_to_arm",
                        expected=True,
                        label="The selected drone is ready to arm",
                    ),
                ),
                steps=(
                    _provider_step(
                        message,
                        "take off to 10m",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 10, "takeoff_altitude": 10},
                        label="Take off to 10 m",
                    ),
                    _provider_delay(message, "wait 10s", 10),
                    _provider_step(
                        message,
                        "fly 20m east",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 112,
                            "precision_move": {
                                "frame": "ned",
                                "translation_m": {
                                    "north": 0,
                                    "east": 20,
                                    "up": 0,
                                },
                            },
                        },
                        condition="after_command_terminal_success",
                        label="Move 20 m east",
                    ),
                    _provider_delay(message, "wait 30s", 30),
                    _provider_step(
                        message,
                        "RTL",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 104},
                        condition="after_command_terminal_success",
                        label="Return to launch",
                    ),
                ),
            ),
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    now = time.time()
    deps = SimpleNamespace(
        telemetry_data_all_drones={
            "1": {
                "hw_id": "1",
                "telemetry_available": True,
                "is_ready_to_arm": True,
            }
        },
        last_telemetry_time={"1": now},
        get_all_heartbeats=lambda: {
            "1": {"hw_id": "1", "timestamp": int(now * 1000)}
        },
    )
    app = FastAPI()
    app.include_router(create_simurgh_router(deps))

    response = TestClient(app).post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["intent"]["route"] == "action_draft"
    assert "Read-only status checked before drafting" not in payload["content"]
    draft = payload["trace"]["safety"]["action_draft"]
    assert draft["target_drone_ids"] == ["1"]
    assert draft["preconditions"] == [
        {
            "fact_id": "fleet.targets_ready_to_arm",
            "arguments": {"target_drone_ids": ["1"]},
            "operator": "eq",
            "expected": True,
            "label": "The selected drone is ready to arm",
        }
    ]


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
    assert payload["trace"]["safety"]["action_draft"]["arguments"] == {}


@pytest.mark.parametrize(
    "provider_error",
    (
        "OpenAI semantic rewrite did not return valid JSON",
        "OpenAI assistant request failed with HTTP 500",
    ),
)
def test_simurgh_provider_failure_does_not_execute_local_flight_parse(monkeypatch, provider_error):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    def fail_semantic_rewrite(**_kwargs):
        raise AgentRuntimeError(provider_error)

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fail_semantic_rewrite,
    )

    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": (
                "takeoff drone 1 to 10m, wait 5s, move 10m east at the same altitude, "
                "then RTL and report"
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Review the guarded action plan below." in payload["content"]
    assert "Take off to 10 m for drone 1." in payload["content"]
    assert "Precision move: 10 m east for drone 1." in payload["content"]
    assert "No action was executed." in payload["content"]
    assert payload["trace"]["intent"]["route"] == "action_draft"
    assert payload["trace"]["intent"]["provider_semantic_rewrite_error"] == provider_error
    assert payload["trace"]["tool"]["ids"] == ["mds.flight.command.execute"]
    assert payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"


def test_simurgh_provider_failure_does_not_execute_local_sitl_parse(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")

    def fail_semantic_rewrite(**_kwargs):
        raise AgentRuntimeError("semantic provider unavailable")

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fail_semantic_rewrite,
    )

    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "create one SITL instance and report when ready"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Review the guarded action plan below." in payload["content"]
    assert "create SITL instance" in payload["content"]
    assert "No action was executed." in payload["content"]
    assert payload["trace"]["intent"]["provider_semantic_rewrite_error"] == (
        "semantic provider unavailable"
    )
    assert payload["trace"]["intent"]["route"] == "action_draft"
    assert payload["trace"]["tool"]["id"] == "mds.sitl.instances.create"
    assert payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"


def test_simurgh_provider_failure_does_not_use_local_missing_detail_gate(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")

    def fail_semantic_rewrite(**_kwargs):
        raise AgentRuntimeError("semantic provider unavailable")

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fail_semantic_rewrite,
    )

    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "takeoff to 10m"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "I understood the mission, but I need the target drone" in payload["content"]
    assert "Which drone should I use?" in payload["content"]
    assert "No action was executed." in payload["content"]
    assert payload["trace"]["intent"]["provider_semantic_rewrite_error"] == (
        "semantic provider unavailable"
    )
    assert payload["trace"]["intent"]["route"] == "action_draft"
    assert payload["trace"]["tool"]["ids"] == ["mds.flight.command.execute"]
    assert payload["trace"]["safety"]["action_execution"] == "missing_arguments"


def test_simurgh_exact_conditional_sitl_create_keeps_guarded_precondition_on_provider_outage(
    monkeypatch,
):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    def fail_semantic_rewrite(**_kwargs):
        raise AgentRuntimeError("OpenAI assistant request failed with HTTP 429")

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fail_semantic_rewrite,
    )

    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "If no SITL instance is running, create one and report when ready.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["intent"]["route"] == "action_draft"
    assert payload["trace"]["tool"]["id"] == "mds.sitl.instances.create"
    assert payload["trace"]["safety"]["action_execution"] == "precondition_unavailable"
    preconditions = payload["trace"]["safety"]["action_draft"]["preconditions"]
    assert preconditions[0]["fact_id"] == "sitl.running_instance_count"
    assert preconditions[0]["operator"] == "eq"
    assert preconditions[0]["expected"] == 0
    assert "No SITL instance is running" in payload["content"]
    assert "No action was executed." in payload["content"]


def test_simurgh_readiness_question_with_action_word_stays_local_read_only(monkeypatch):
    """A readiness check must not be blocked as a direct takeoff command."""

    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)

    def fail_semantic_rewrite(**_kwargs):
        raise AgentRuntimeError("semantic provider unavailable")

    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fail_semantic_rewrite,
    )

    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Drone 1 i mena is it ready to takeoff?",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["intent"]["route"] == "read_only"
    assert payload["trace"]["tool"]["intent"] == "fleet_connectivity"
    assert payload["blocked_intents"] == []
    assert "I could not complete that request" not in payload["content"]
    assert "Drone 1" in payload["content"]
    assert "Ready" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "none"


def test_simurgh_provider_cannot_promote_typed_readiness_to_action(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    message = "Drone 1 i mena is it ready to takeoff?"

    def unexpected_provider_call(**_kwargs):
        raise AssertionError("authoritative local readiness read must not call the provider")

    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        unexpected_provider_call,
    )

    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["intent"]["route"] == "read_only"
    assert payload["trace"]["tool"]["intent"] == "fleet_connectivity"
    assert payload["trace"]["intent"]["route_commitment"] == {
        "kind": "read",
        "authoritative": True,
        "provider_refinement_needed": False,
        "fallback_allowed": True,
        "reason": "typed-local-read-complete",
    }
    assert "provider_action_plan_error" not in payload["trace"]["intent"]
    assert payload["trace"]["safety"].get("action_draft") is None
    assert payload["trace"]["safety"]["action_execution"] == "none"


def test_simurgh_ambiguous_action_word_asks_status_or_action_clarification(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        lambda **_kwargs: (_ for _ in ()).throw(
            AgentRuntimeError("semantic provider unavailable")
        ),
    )

    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Takeoff?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["intent"]["route"] == "semantic_clarification"
    assert payload["blocked_intents"] == []
    assert "read-only readiness check or a guarded action" in payload["content"]
    assert "current readiness" in payload["content"]
    assert "action plan for confirmation" in payload["content"]
    assert payload["trace"]["safety"]["action_execution"] == "none"


def test_simurgh_semantic_only_request_provider_failure_asks_concise_clarification(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        lambda **_kwargs: (_ for _ in ()).throw(AgentRuntimeError("semantic provider unavailable")),
    )

    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "حالا آن را ده متر بالا ببر"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == (
        "The semantic planning service is temporarily unavailable, and the local "
        "typed route is incomplete. Please retry, or state the target and ordered steps."
    )
    assert payload["trace"]["intent"]["route"] == "semantic_clarification"
    assert payload["trace"]["tool"]["ids"] == []
    assert "mock assistant" not in payload["content"].lower()


def test_provider_structured_read_keeps_original_target_and_time_scope(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    original = "analyse le vol du drone 2 pendant les 30 dernières minutes"
    captured_calls = []

    monkeypatch.setattr("api_routes.simurgh._semantic_rewrite_is_safe_to_try", lambda **_kwargs: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        lambda **_kwargs: _provider_rewrite(
            normalized_message="analyze the latest drone log",
            route_hint="read_status",
            read_intents=("drone_log_summary",),
            read_options={
                "drone_log_summary": {
                    "verify_operation": True,
                    "include_unified_logs": True,
                    "analyze_latest_ulog": True,
                }
            },
        ),
    )

    def fake_read_answer(message, **kwargs):
        captured_calls.append((message, kwargs.get("read_options")))
        return MdsReadToolAnswer(
            intent="drone_log_summary",
            content="Scoped log evidence ready.",
            tool_ids=("mds.logs.drone_sessions.read",),
            safety_notes=("Read-only test evidence.",),
        )

    monkeypatch.setattr("api_routes.simurgh.answer_mds_read_only_question", fake_read_answer)
    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": original},
    )

    assert response.status_code == 200
    assert captured_calls == [
        (
            original,
            {
                "drone_log_summary": {
                    "verify_operation": True,
                    "include_unified_logs": True,
                    "analyze_latest_ulog": True,
                }
            },
        )
    ]
    assert response.json()["content"] == "Scoped log evidence ready."


def test_provider_structured_read_cannot_drop_grounded_state_evidence(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    message = "How many drones do we have configured? how about SITL instances, any active?"
    executed_tools = []

    monkeypatch.setattr("api_routes.simurgh._semantic_rewrite_is_safe_to_try", lambda **_kwargs: True)
    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        lambda **_kwargs: _provider_rewrite(
            normalized_message="read fleet configuration and runtime status",
            route_hint="read_status",
            read_intents=("fleet_summary", "runtime_summary"),
        ),
    )

    async def fake_read_only_tool(
        _request,
        *,
        name,
        arguments,
        channel,
        registry,
        policy,
        **_kwargs,
    ):
        assert arguments == {}
        assert channel == "agent"
        executed_tools.append(name)
        payload = {
            "mds.config.fleet.read": [
                {"hw_id": 1, "callsign": "SITL-01"},
                {"hw_id": 2, "callsign": "FIELD-02"},
            ],
            "mds.sitl.instances.read": {
                "instances": [{"name": "drone-1", "state": "running"}],
                "total_instances": 1,
                "docker": {"daemon_reachable": True},
            },
            "mds.sitl.policy.read": {"sim_mode": True, "read_only": False},
            "mds.config.positions.read": [],
            "mds.config.swarm.read": [],
            "mds.system.runtime_status.read": {"mode": "sitl"},
        }[name]
        return ReadOnlyToolCallResult(
            text=json.dumps(payload),
            is_error=False,
            structured_content=payload,
            status_code=200,
        )

    monkeypatch.setattr(
        "api_routes.simurgh.execute_policy_allowed_read_only_tool",
        fake_read_only_tool,
    )
    app = FastAPI()
    app.include_router(
        create_simurgh_router(
            SimpleNamespace(
                load_config=lambda: [
                    {"hw_id": 1, "callsign": "SITL-01"},
                    {"hw_id": 2, "callsign": "FIELD-02"},
                ]
            )
        )
    )

    response = TestClient(app).post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    assert executed_tools == [
        "mds.config.fleet.read",
        "mds.sitl.instances.read",
        "mds.sitl.policy.read",
        "mds.config.positions.read",
        "mds.config.swarm.read",
        "mds.system.runtime_status.read",
    ]
    assert "Configured fleet: 2 drone(s)." in payload["content"]
    assert "SITL instances: 1 total, 1 active." in payload["content"]
    assert "configured drone matching" not in payload["content"]
    assert payload["trace"]["tool"]["intent"] == "registry_read_execution"
    resolution = payload["trace"]["intent"]["provider_read_plan_resolution"]
    assert resolution["execution"] == "grounded_registry_plan"
    assert resolution["missing_grounded_tool_ids"] == [
        "mds.sitl.instances.read",
        "mds.sitl.policy.read",
    ]
    assert resolution["provider_added_tool_ids"] == [
        "mds.config.positions.read",
        "mds.config.swarm.read",
        "mds.system.runtime_status.read",
    ]
    assert resolution["executed_tool_ids"] == executed_tools
    assert resolution["missing_required_tool_ids"] == []


@pytest.mark.parametrize(
    "message",
    (
        "Combien de simulateurs sont actifs maintenant ?",
        "do we have any sitl instace runnign now?",
    ),
)
def test_provider_sitl_status_intent_executes_concise_registry_evidence(monkeypatch, message):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    executed_tools = []

    monkeypatch.setattr("api_routes.simurgh._semantic_rewrite_is_safe_to_try", lambda **_kwargs: True)
    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        lambda **_kwargs: _provider_rewrite(
            normalized_message="read current SITL instance status",
            route_hint="read_status",
            read_intents=("sitl_status",),
        ),
    )

    async def fake_read_only_tool(
        _request,
        *,
        name,
        arguments,
        channel,
        registry,
        policy,
        **_kwargs,
    ):
        executed_tools.append(name)
        payload = {
            "mds.sitl.instances.read": {
                "instances": [{"name": "drone-1", "state": "running"}],
                "total_instances": 1,
                "docker": {"daemon_reachable": True},
            },
            "mds.sitl.policy.read": {"sim_mode": True, "read_only": False},
        }[name]
        return ReadOnlyToolCallResult(
            text=json.dumps(payload),
            is_error=False,
            structured_content=payload,
            status_code=200,
        )

    monkeypatch.setattr(
        "api_routes.simurgh.execute_policy_allowed_read_only_tool",
        fake_read_only_tool,
    )
    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "mds-tools"
    assert executed_tools == ["mds.sitl.instances.read", "mds.sitl.policy.read"]
    assert "SITL instances: 1 total, 1 active; Docker reachable: Yes." in payload["content"]
    assert "Active container(s): drone-1=running." in payload["content"]
    resolution = payload["trace"]["intent"]["provider_read_plan_resolution"]
    assert resolution["execution"] == "provider_registry_plan"
    assert resolution["executed_tool_ids"] == executed_tools
    assert resolution["missing_required_tool_ids"] == []


@pytest.mark.parametrize(
    ("message", "provider_target", "expected_targets", "expected_dropped"),
    [
        ("Show the whole fleet status", "9", (), ("9",)),
        ("Show drone 1 status", "1", ("1",), ()),
        ("Muestra el estado del dron 1", "1", ("1",), ()),
    ],
)
def test_provider_structured_read_targets_require_local_grounding(
    monkeypatch,
    message,
    provider_target,
    expected_targets,
    expected_dropped,
):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    captured_targets = []

    monkeypatch.setattr("api_routes.simurgh._semantic_rewrite_is_safe_to_try", lambda **_kwargs: True)
    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        lambda **_kwargs: _provider_rewrite(
            normalized_message="read current fleet telemetry",
            route_hint="read_status",
            read_intents=("fleet_status",),
            read_target_drone_ids=(provider_target,),
        ),
    )

    def fake_read_answer(_message, **kwargs):
        captured_targets.append(tuple(kwargs.get("target_drone_ids") or ()))
        return MdsReadToolAnswer(
            intent="fleet_status",
            content="Fleet evidence ready.",
            tool_ids=("mds.fleet.telemetry.read",),
            safety_notes=("Read-only test evidence.",),
        )

    monkeypatch.setattr("api_routes.simurgh.answer_mds_read_only_question", fake_read_answer)
    app = FastAPI()
    app.include_router(
        create_simurgh_router(SimpleNamespace(load_config=lambda: [{"hw_id": 1}]))
    )

    response = TestClient(app).post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    assert captured_targets == [expected_targets]
    resolution = payload["trace"]["intent"]["provider_read_target_resolution"]
    assert tuple(resolution["accepted"]) == expected_targets
    assert tuple(resolution["dropped_ungrounded"]) == expected_dropped
    assert resolution["unknown_explicit"] == []


def test_provider_structured_read_unknown_explicit_target_asks_once(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    read_calls = []

    monkeypatch.setattr("api_routes.simurgh._semantic_rewrite_is_safe_to_try", lambda **_kwargs: True)
    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        lambda **_kwargs: _provider_rewrite(
            normalized_message="read current telemetry for drone 9",
            route_hint="read_status",
            read_intents=("fleet_status",),
            read_target_drone_ids=("9",),
        ),
    )
    monkeypatch.setattr(
        "api_routes.simurgh.answer_mds_read_only_question",
        lambda *_args, **_kwargs: read_calls.append(True),
    )
    app = FastAPI()
    app.include_router(
        create_simurgh_router(SimpleNamespace(load_config=lambda: [{"hw_id": 1}]))
    )

    response = TestClient(app).post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Show drone 9 status"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert read_calls == []
    assert payload["content"] == (
        "I cannot find drone 9 in the configured or live fleet. Which drone should I check?"
    )
    resolution = payload["trace"]["intent"]["provider_read_target_resolution"]
    assert resolution["accepted"] == []
    assert resolution["unknown_explicit"] == ["9"]
    assert resolution["dropped_ungrounded"] == []


def test_simurgh_provider_structured_reads_override_false_action_followups(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    now = time.time()
    submitted = []

    async def fake_sleep(_delay_seconds):
        return None

    class FakeTracker:
        async def get_status(self, command_id):
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
                "progress": {"label": "Completed", "message": "Command completed."},
            }

    class FakeDeps:
        telemetry_data_all_drones = {
            "1": {
                "telemetry_available": True,
                "is_ready_to_arm": True,
                "is_armed": False,
                "is_landed": True,
                "relative_altitude_m": 0.1,
                "velocity_down": 0.0,
                "distance_to_home_m": 0.5,
                "gps_fix_type": 3,
                "satellites_visible": 10,
                "battery_voltage": 16.2,
                "flight_mode_name": "HOLD",
                "system_status_name": "STANDBY",
                "timestamp": int(now * 1000),
            }
        }
        last_telemetry_time = {"1": now}
        data_lock = None

        def load_config(self):
            return [{"hw_id": 1, "pos_id": 1, "callsign": "SCOUT", "ip": "172.18.0.2"}]

        def get_all_heartbeats(self):
            return {"1": {"timestamp": int(now * 1000)}}

        def get_command_tracker(self):
            return FakeTracker()

    async def fake_submit_tracked_command(_deps, command):
        submitted.append(command)
        return {
            "success": True,
            "command_id": f"cmd-{len(submitted)}",
            "idempotency_key": command.idempotency_key,
            "status": "submitted",
            "mission_type": command.mission_type,
            "mission_name": {10: "TAKE_OFF", 104: "RETURN_RTL", 112: "PRECISION_MOVE"}[command.mission_type],
            "target_drones": command.target_drone_ids,
            "submitted_count": len(command.target_drone_ids),
            "results_summary": {"accepted": 1, "offline": 0, "rejected": 0, "errors": 0},
        }

    monkeypatch.setattr("api_routes.simurgh._sleep_action_sequence_delay", fake_sleep)
    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)
    client = _client()

    draft = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "takeoff drone 1 to 10m, wait 5s, move 10m east, then RTL and report",
        },
    ).json()
    draft_id = re.search(r"act-[0-9a-f]+", draft["content"]).group(0)
    confirmed = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft["session"]["id"],
            "message": f"confirm action {draft_id}",
        },
    )
    run = _wait_for_action_run(client, confirmed.json())
    assert run["state"] == "succeeded"

    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    def fake_semantic_rewrite(**kwargs):
        if kwargs["message"].startswith("Did the requested"):
            assert "action_run_state=succeeded" in kwargs["previous_action_summary"]
            return _provider_rewrite(
                normalized_message="verify the previous action sequence",
                route_hint="read_status",
                read_intents=("previous_action_summary",),
            )
        if kwargs["message"].startswith("Review this completed mission"):
            return _provider_rewrite(
                normalized_message="review the completed mission with command logs and newest ULog",
                route_hint="read_status",
                read_intents=(
                    "previous_action_summary",
                    "command_summary",
                    "backend_log_summary",
                    "drone_log_summary",
                ),
                read_target_drone_ids=("1",),
            )
        if kwargs["message"].startswith("Did the wait actually happen"):
            return _provider_rewrite(
                normalized_message="verify the previous wait and current landed state",
                route_hint="read_status",
                read_intents=("previous_action_summary", "fleet_status"),
                read_target_drone_ids=("1",),
                response_detail="brief",
            )
        if kwargs["message"].startswith("Show the whole fleet"):
            return _provider_rewrite(
                normalized_message="read current telemetry for the whole fleet",
                route_hint="read_status",
                read_intents=("fleet_status",),
            )
        return _provider_rewrite(
            normalized_message="read current telemetry for drone 1",
            route_hint="read_status",
            read_intents=("fleet_status",),
            read_target_drone_ids=("1",),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr("api_routes.simurgh.rewrite_operator_message_with_provider", fake_semantic_rewrite)

    wait_check = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft["session"]["id"],
            "message": "Did the requested 5 second wait actually run between takeoff and the eastward move?",
        },
    )
    assert wait_check.status_code == 200
    wait_payload = wait_check.json()
    assert wait_payload["trace"]["safety"]["action_execution"] == "previous_action_summary"
    assert "Wait steps: 1/1 completed" in wait_payload["content"]
    assert "Action draft" not in wait_payload["content"]

    combined_check = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft["session"]["id"],
            "message": (
                "Did the wait actually happen, and did the drone return, land, "
                "and disarm? Give me only the concise evidence from that mission."
            ),
        },
    )
    assert combined_check.status_code == 200
    combined_payload = combined_check.json()
    assert combined_payload["blocked_intents"] == []
    assert combined_payload["trace"]["tool"]["intent"] == "composite_read"
    assert "simurgh.session.previous_action.read" in combined_payload["trace"]["tool"]["ids"]
    assert "mds.fleet.telemetry.read" in combined_payload["trace"]["tool"]["ids"]
    assert "Wait steps: 1/1 completed" in combined_payload["content"]
    assert "Scope: Drone 1." in combined_payload["content"]
    assert "Sequence steps:" not in combined_payload["content"]
    assert "Action draft" not in combined_payload["content"]

    status_check = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft["session"]["id"],
            "message": (
                "Give me the current status of the test drone now that the mission finished. "
                "Is it back, landed, disarmed, and still reporting fresh telemetry?"
            ),
        },
    )
    assert status_check.status_code == 200
    status_payload = status_check.json()
    assert status_payload["trace"]["tool"]["intent"] == "fleet_connectivity"
    assert "mds.fleet.telemetry.read" in status_payload["trace"]["tool"]["ids"]
    assert "Scope: Drone 1." in status_payload["content"]
    assert "Drone 1" in status_payload["content"]
    assert "Armed" in status_payload["content"]
    assert "Simurgh Operator mock assistant" not in status_payload["content"]

    fleet_check = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft["session"]["id"],
            "message": "Show the whole fleet status, not only the previous mission target.",
        },
    )
    assert fleet_check.status_code == 200
    assert "Scope: Drone 1." not in fleet_check.json()["content"]

    from agent_runtime.mds_read_tools import MdsReadOnlyTools

    def fake_fetch(self, drone_ip, path, *, params=None, timeout=0):  # noqa: ANN001
        assert drone_ip == "172.18.0.2"
        if path == "/api/logs/sessions":
            return {"sessions": [{"session_id": "s_drone_1"}]}, ""
        if path == "/api/logs/sessions/s_drone_1":
            return {"lines": [{"level": "INFO", "message": "mission complete"}]}, ""
        if path == "/api/v1/ulog/files":
            return {"files": [{"id": 9, "date_utc": "2026-07-14T10:00:00Z", "size_bytes": 2048}]}, ""
        if path == "/api/v1/ulog/files/9/summary":
            return {
                "parsed": True,
                "duration_sec": 25.0,
                "parser": {"status": "ok"},
                "local_position": {
                    "max_horizontal_distance_from_start_m": 10.0,
                    "relative_altitude_range_m": {"min": 0.0, "max": 10.0, "final": 0.0},
                },
                "battery": {"voltage_v": {"min": 16.0, "max": 16.2, "final": 16.1}},
                "commands": {
                    "vehicle_command": {"samples": 3},
                    "vehicle_command_ack": {"samples": 3, "result_counts": {"0": 3}},
                },
            }, ""
        raise AssertionError(path)

    monkeypatch.setattr(MdsReadOnlyTools, "_fetch_drone_json", fake_fetch)
    evidence_check = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft["session"]["id"],
            "message": (
                "Review this completed mission using the command tracker, unified MDS logs, "
                "and the newest onboard ULog. Confirm whether the planned steps completed "
                "and summarize any warnings, errors, or unavailable evidence."
            ),
        },
    )
    assert evidence_check.status_code == 200
    evidence_payload = evidence_check.json()
    assert evidence_payload["trace"]["tool"]["intent"] == "composite_read"
    assert "Previous action" in evidence_payload["content"]
    assert "Wait steps: 1/1 completed" in evidence_payload["content"]
    assert "Unified GCS log evidence" in evidence_payload["content"]
    assert "Parsed latest ULog summary" in evidence_payload["content"]
    assert "\n\nCommand Summary\n\n" not in evidence_payload["content"]
    assert "\n\nBackend Log Summary\n\n" not in evidence_payload["content"]


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


def test_explicit_action_draft_id_is_authoritative_and_actor_bound(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    def semantic_create(**kwargs):
        message = kwargs["message"]
        control_word = message.split(maxsplit=1)[0].lower() if message.strip() else ""
        if control_word in {"confirm", "cancel"}:
            return _provider_rewrite(
                normalized_message=message,
                route_hint=(
                    "confirm_pending_action"
                    if control_word == "confirm"
                    else "reject_pending_action"
                ),
                action_control_explicit=True,
                action_control_source_start=0,
                action_control_source_end=len(control_word),
                action_control_source_excerpt=message[:len(control_word)],
            )
        return _provider_rewrite(
            normalized_message="create one SITL instance",
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
        semantic_create,
    )
    client = _client()
    draft_payload = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "create one SITL instance"},
    ).json()
    session_id = draft_payload["session"]["id"]
    draft_id = re.search(r"act-[0-9a-f]+", draft_payload["content"]).group(0)
    wrong_id = "act-deadbeef"

    wrong_button = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": session_id,
            "message": "Confirm",
            "metadata": {
                "source": "simurgh-dashboard",
                "action_intent": "confirm",
                "draft_id": wrong_id,
            },
        },
    ).json()
    assert wrong_button["trace"]["safety"]["action_execution"] == "no_pending_confirmation"

    wrong_text = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": session_id,
            "message": f"confirm action {wrong_id}",
        },
    ).json()
    assert wrong_text["trace"]["safety"]["action_execution"] == "no_pending_confirmation"

    cross_session = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": f"cancel action {draft_id}"},
    ).json()
    assert cross_session["trace"]["safety"]["action_execution"] == "cancelled_confirmation"
    assert cross_session["trace"]["safety"]["action_draft"]["draft_id"] == draft_id

    correct_rejection = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": session_id,
            "message": f"cancel action {draft_id}",
        },
    ).json()
    assert correct_rejection["trace"]["safety"]["action_execution"] == "no_pending_confirmation"


def test_conditional_sitl_create_skips_confirmation_when_instance_is_running(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    message = "If no SITL instance is running, create one and report when ready."
    guarded_calls = []

    def fake_rewrite_operator_message_with_provider(**kwargs):
        fact_ids = {item["id"] for item in kwargs["action_precondition_fact_contracts"]}
        assert "sitl.running_instance_count" in fact_ids
        return _provider_rewrite(
            normalized_message=message,
            route_hint="draft_sitl_lifecycle_action",
            action_plan=ProviderActionPlan(
                summary="Create one SITL instance only when none is running",
                preconditions=(
                    _provider_precondition(message, "no SITL instance is running"),
                ),
                steps=(
                    _provider_step(
                        message,
                        "create one",
                        tool_id="mds.sitl.instances.create",
                        arguments={},
                        label="Create one SITL instance",
                    ),
                ),
            ),
        )

    async def fake_read_only_tool(
        _request,
        *,
        name,
        arguments,
        channel,
        registry,
        policy,
        **_kwargs,
    ):
        assert arguments == {}
        assert channel == "agent"
        payload = _conditional_sitl_read_payload(name, running_count=1)
        return ReadOnlyToolCallResult(
            text=json.dumps(payload),
            is_error=False,
            structured_content=payload,
            status_code=200,
        )

    async def fail_guarded_tool(*args, **kwargs):
        guarded_calls.append((args, kwargs))
        raise AssertionError("guarded mutation must not run when the condition is false")

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_read_only_tool", fake_read_only_tool)
    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fail_guarded_tool)
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["safety"]["action_execution"] == "precondition_not_met"
    assert payload["trace"]["safety"]["action_preconditions"]["status"] == "not_met"
    assert payload["trace"]["safety"]["action_run"] == {}
    assert "No action is needed" in payload["content"]
    assert "Observed: 1" in payload["content"]
    assert guarded_calls == []


def test_composite_status_and_conditional_sitl_action_preserves_both_requests(
    monkeypatch,
):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    message = (
        "How many drones are configured? If no SITL instance is running, "
        "create one."
    )
    executed_tools: list[str] = []

    def semantic_composite(**_kwargs):
        return _provider_rewrite(
            normalized_message=message,
            route_hint="draft_sitl_lifecycle_action",
            read_intents=("fleet_summary", "sitl_status"),
            action_plan=ProviderActionPlan(
                summary="Create one SITL instance only when none is running",
                preconditions=(
                    _provider_precondition(
                        message,
                        "no SITL instance is running",
                    ),
                ),
                steps=(
                    _provider_step(
                        message,
                        "create one",
                        tool_id="mds.sitl.instances.create",
                        arguments={},
                        label="Create one SITL instance",
                    ),
                ),
            ),
        )

    async def fake_read_only_tool(
        _request,
        *,
        name,
        arguments,
        channel,
        registry,
        policy,
        **_kwargs,
    ):
        del registry, policy
        assert arguments == {}
        assert channel == "agent"
        executed_tools.append(name)
        payload = {
            "mds.config.fleet.read": [
                {"hw_id": index, "callsign": f"DRONE-{index}"}
                for index in range(1, 5)
            ],
            "mds.config.positions.read": [],
            "mds.config.swarm.read": [],
            "mds.sitl.instances.read": {
                "instances": [],
                "total_instances": 0,
                "running_instance_count": 0,
                "docker": {
                    "available": True,
                    "daemon_reachable": True,
                },
            },
            "mds.sitl.policy.read": {
                "sim_mode": True,
                "read_only": False,
            },
        }[name]
        return ReadOnlyToolCallResult(
            text=json.dumps(payload),
            is_error=False,
            structured_content=payload,
            status_code=200,
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        semantic_composite,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.execute_policy_allowed_read_only_tool",
        fake_read_only_tool,
    )

    payload = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    ).json()

    assert "trace" in payload, payload
    assert payload["trace"]["safety"]["action_execution"] == (
        "awaiting_confirmation"
    )
    assert "Current status checked before drafting" in payload["content"]
    assert "Review the guarded action plan" in payload["content"]
    assert set(payload["trace"]["safety"]["pre_action_read_only_tool_ids"]) == {
        "mds.config.fleet.read",
        "mds.config.positions.read",
        "mds.config.swarm.read",
        "mds.sitl.instances.read",
        "mds.sitl.policy.read",
    }
    assert payload["trace"]["intent"]["provider_semantic_rewrite"][
        "read_intents"
    ] == ["fleet_summary", "sitl_status"]
    assert payload["trace"]["safety"]["action_preconditions"]["status"] == "met"
    assert "mds.config.fleet.read" in executed_tools
    assert "mds.sitl.instances.read" in executed_tools
    assert "mds.fleet.sidecars.read" not in executed_tools


def test_conditional_sitl_create_rechecks_and_skips_if_state_changes_before_dispatch(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    message = "If no SITL instance is running, create one and report when ready."
    run_created = False
    guarded_calls = []

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        return _provider_rewrite(
            normalized_message=message,
            route_hint="draft_sitl_lifecycle_action",
            action_plan=ProviderActionPlan(
                summary="Create one SITL instance only when none is running",
                preconditions=(
                    _provider_precondition(message, "no SITL instance is running"),
                ),
                steps=(
                    _provider_step(
                        message,
                        "create one",
                        tool_id="mds.sitl.instances.create",
                        arguments={},
                        label="Create one SITL instance",
                    ),
                ),
            ),
        )

    async def fake_read_only_tool(
        _request,
        *,
        name,
        arguments,
        channel,
        registry,
        policy,
        **_kwargs,
    ):
        assert arguments == {}
        payload = _conditional_sitl_read_payload(
            name,
            running_count=1 if run_created else 0,
        )
        return ReadOnlyToolCallResult(
            text=json.dumps(payload),
            is_error=False,
            structured_content=payload,
            status_code=200,
        )

    original_create_or_get = ActionRunStore.create_or_get

    def create_or_get_and_change_runtime(self, *args, **kwargs):
        nonlocal run_created
        result = original_create_or_get(self, *args, **kwargs)
        run_created = True
        return result

    async def fail_guarded_tool(*args, **kwargs):
        guarded_calls.append((args, kwargs))
        raise AssertionError("guarded mutation must not run after the condition changes")

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_read_only_tool", fake_read_only_tool)
    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fail_guarded_tool)
    monkeypatch.setattr(ActionRunStore, "create_or_get", create_or_get_and_change_runtime)
    client = _client()

    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    assert draft_payload["trace"]["safety"]["action_execution"] == "awaiting_confirmation"
    conditions = draft_payload["trace"]["safety"]["action_draft"]["display_plan"]["conditions"]
    assert conditions[0]["label"] == "No SITL instance is running"
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
    run = _wait_for_action_run(client, confirm_response.json())
    assert run["state"] == "skipped"
    assert run["result"]["action_execution"] == "precondition_not_met"
    assert run["result"]["dispatched_steps"] == 0
    assert guarded_calls == []


def test_conditional_sitl_create_carries_observed_inventory_guard_to_service(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    message = "If no SITL instance is running, create one and report when ready."
    guarded_arguments = []

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        return _provider_rewrite(
            normalized_message=message,
            route_hint="draft_sitl_lifecycle_action",
            action_plan=ProviderActionPlan(
                summary="Create one SITL instance only when none is running",
                preconditions=(
                    _provider_precondition(message, "no SITL instance is running"),
                ),
                steps=(
                    _provider_step(
                        message,
                        "create one",
                        tool_id="mds.sitl.instances.create",
                        arguments={},
                        label="Create one SITL instance",
                    ),
                ),
            ),
        )

    async def fake_read_only_tool(
        _request,
        *,
        name,
        arguments,
        **_kwargs,
    ):
        payload = _conditional_sitl_read_payload(name, running_count=0)
        return ReadOnlyToolCallResult(
            text=json.dumps(payload),
            is_error=False,
            structured_content=payload,
            status_code=200,
        )

    async def fake_guarded_tool(_request, *, name, arguments, **_kwargs):
        assert name == "mds.sitl.instances.create"
        guarded_arguments.append(dict(arguments))
        return GuardedToolCallResult(
            text="simulated service stop",
            is_error=True,
            structured_content={},
            status_code=409,
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.execute_policy_allowed_read_only_tool",
        fake_read_only_tool,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.execute_policy_allowed_guarded_route_tool",
        fake_guarded_tool,
    )
    client = _client()
    drafted = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    ).json()

    confirmed = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": drafted["session"]["id"],
            "message": (
                "confirm action "
                + drafted["trace"]["safety"]["action_draft"]["draft_id"]
            ),
        },
    )

    assert confirmed.status_code == 200
    run = _wait_for_action_run(client, confirmed.json())
    assert run["state"] == "failed"
    assert guarded_arguments == [{"expected_running_instance_count": 0}]


def test_provider_semantics_can_promote_non_english_local_read_guess_to_action(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    message = "haz despegar el dron 1 a 10 metros, espera 5 segundos y vuelve al punto de origen"

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        return _provider_rewrite(
            normalized_message="take off drone 1 to 10 m, wait 5 seconds, then return to launch",
            route_hint="draft_flight_action",
            action_plan=ProviderActionPlan(
                summary="Take off, wait, and return",
                steps=(
                    _provider_step(
                        message,
                        "despegar el dron 1 a 10 metros",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 10,
                            "trigger_time": 0,
                            "target_drone_ids": ["1"],
                            "takeoff_altitude": 10,
                        },
                        label="Take off to 10 m",
                    ),
                    _provider_delay(message, "espera 5 segundos", 5),
                    _provider_step(
                        message,
                        "vuelve al punto de origen",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 104,
                            "trigger_time": 0,
                            "target_drone_ids": ["1"],
                        },
                        condition="after_command_terminal_success",
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
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    draft = payload["trace"]["safety"]["action_draft"]
    assert payload["trace"]["intent"]["route"] == "action_draft"
    assert draft["command_payload"]["takeoff_altitude"] == 10.0
    assert [step["type"] for step in draft["post_actions"]] == ["delay", "flight_command"]
    assert [step["label"] for step in draft["display_plan"]["steps"]] == [
        "Take off to 10 m",
        "Wait 5 seconds",
        "Return to launch",
    ]


def test_provider_sequence_can_create_ready_sitl_then_fly_the_created_target(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    message = "create one SITL instance, then take off to 10m"
    submitted_commands = []

    class FakeTracker:
        async def get_status(self, command_id):
            return {
                "command_id": command_id,
                "status": "completed",
                "phase": "terminal",
                "outcome": "completed",
                "progress": {"label": "Takeoff complete"},
            }

    class FakeDeps:
        def get_command_tracker(self):
            return FakeTracker()

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        return _provider_rewrite(
            normalized_message=message,
            route_hint="draft_sitl_lifecycle_action",
            action_plan=ProviderActionPlan(
                summary="Create one simulator and take off",
                steps=(
                    _provider_step(
                        message,
                        "create one SITL instance",
                        tool_id="mds.sitl.instances.create",
                        arguments={},
                        label="Create one SITL instance",
                    ),
                    _provider_step(
                        message,
                        "take off to 10m",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 10,
                            "trigger_time": 0,
                            "takeoff_altitude": 10,
                        },
                        condition="after_command_terminal_success",
                        label="Take off to 10 m",
                    ),
                ),
            ),
        )

    async def fake_guarded_route_tool(_request, *, name, arguments, **_kwargs):
        assert name == "mds.sitl.instances.create"
        assert arguments == {}
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": "sitl-op-create-and-fly",
                "operation_type": "create_instance",
                "status": "queued",
                "summary": "Creating drone-1",
            },
            status_code=200,
        )

    async def fake_submit_tracked_command(_deps, command):
        submitted_commands.append(command)
        return {
            "command_id": "cmd-created-drone-takeoff",
            "status": "submitted",
            "mission_type": command.mission_type,
            "target_drones": command.target_drone_ids,
            "results_summary": {
                "accepted": len(command.target_drone_ids),
                "offline": 0,
                "rejected": 0,
                "errors": 0,
            },
        }

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    monkeypatch.setattr("api_routes.simurgh._request_scoped_deps", lambda _base, _request: FakeDeps())
    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    monkeypatch.setattr("api_routes.simurgh.submit_tracked_command", fake_submit_tracked_command)

    app = FastAPI()

    @app.get("/api/v1/system/sitl/operations/{operation_id}")
    async def fake_sitl_operation(operation_id: str):
        return {
            "operation_id": operation_id,
            "operation_type": "create_instance",
            "status": "succeeded",
            "summary": "Created drone-1",
            "affected_instances": ["drone-1"],
        }

    _add_sitl_completion_evidence_routes(app, drone_ids=("1",), ready=True)
    app.include_router(create_simurgh_router())

    with TestClient(app) as client:
        draft_response = client.post(
            "/api/v1/simurgh/assistant/turns",
            json={"actor": "operator", "message": message},
        )
        assert draft_response.status_code == 200
        draft_payload = draft_response.json()
        draft = draft_payload["trace"]["safety"]["action_draft"]
        assert [step["label"] for step in draft["display_plan"]["steps"]] == [
            "Create one SITL instance",
            "Take off to 10 m",
        ]
        assert draft["post_actions"][0]["target_from_previous_result"] is True
        draft_id = draft["draft_id"]

        confirm_response = client.post(
            "/api/v1/simurgh/assistant/turns",
            json={
                "actor": "operator",
                "session_id": draft_payload["session"]["id"],
                "message": f"confirm action {draft_id}",
            },
        )
        assert confirm_response.status_code == 200
        run = _wait_for_action_run(client, confirm_response.json(), timeout=8.0)

    assert run["state"] == "succeeded"
    assert run["total_steps"] == 2
    assert run["result"]["monitor_result"]["completion_verification"]["verified"] is True
    assert run["result"]["post_action_results"][0]["resolved_target_drone_ids"] == ["1"]
    assert len(submitted_commands) == 1
    assert submitted_commands[0].target_drone_ids == ["1"]
    assert submitted_commands[0].takeoff_altitude == 10


@pytest.mark.parametrize(
    ("lifecycle_action", "operation_type"),
    (
        ("restart", "restart_instances"),
        ("remove", "remove_instances"),
    ),
)
def test_provider_sequence_materializes_the_instance_created_at_runtime(
    monkeypatch,
    lifecycle_action,
    operation_type,
):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    message = f"create one SITL instance, then {lifecycle_action} it"
    guarded_calls = []
    live_drone_ids = {"1"}

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        return _provider_rewrite(
            normalized_message=message,
            route_hint="draft_sitl_lifecycle_action",
            action_plan=ProviderActionPlan(
                summary=f"Create and {lifecycle_action} one simulator",
                steps=(
                    _provider_step(
                        message,
                        "create one SITL instance",
                        tool_id="mds.sitl.instances.create",
                        arguments={},
                        label="Create one SITL instance",
                    ),
                    _provider_step(
                        message,
                        f"{lifecycle_action} it",
                        tool_id="mds.sitl.instances.action",
                        arguments={"action": lifecycle_action},
                        condition="after_command_terminal_success",
                        label=f"{lifecycle_action.title()} the created instance",
                    ),
                ),
            ),
        )

    async def fake_guarded_route_tool(_request, *, name, arguments, **_kwargs):
        guarded_calls.append((name, dict(arguments)))
        is_create = name == "mds.sitl.instances.create"
        operation_id = "sitl-op-created" if is_create else f"sitl-op-{lifecycle_action}d"
        if not is_create and lifecycle_action == "remove":
            live_drone_ids.clear()
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": operation_id,
                "operation_type": "create_instance" if is_create else operation_type,
                "status": "accepted",
                "summary": "SITL lifecycle accepted",
                "affected_instances": ["drone-1"],
            },
            status_code=200,
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.execute_policy_allowed_guarded_route_tool",
        fake_guarded_route_tool,
    )

    app = FastAPI()

    @app.get("/api/v1/system/sitl/operations/{operation_id}")
    async def fake_sitl_operation(operation_id: str):
        return {
            "operation_id": operation_id,
            "operation_type": (
                "create_instance"
                if operation_id == "sitl-op-created"
                else operation_type
            ),
            "status": "succeeded",
            "summary": "SITL lifecycle complete",
            "affected_instances": ["drone-1"],
        }

    _add_sitl_completion_evidence_routes(
        app,
        drone_ids=("1",),
        ready=True,
        live_drone_ids=live_drone_ids,
    )
    app.include_router(create_simurgh_router())

    with TestClient(app) as client:
        drafted = client.post(
            "/api/v1/simurgh/assistant/turns",
            json={"actor": "operator", "message": message},
        )
        assert drafted.status_code == 200
        draft_payload = drafted.json()
        post_action = draft_payload["trace"]["safety"]["action_draft"]["post_actions"][0]
        assert post_action["target_from_previous_result"] is True
        assert "instance_names" not in post_action["arguments"]

        confirmed = client.post(
            "/api/v1/simurgh/assistant/turns",
            json={
                "actor": "operator",
                "session_id": draft_payload["session"]["id"],
                "message": (
                    "confirm action "
                    + draft_payload["trace"]["safety"]["action_draft"]["draft_id"]
                ),
            },
        )
        assert confirmed.status_code == 200
        run = _wait_for_action_run(client, confirmed.json(), timeout=8.0)

    assert run["state"] == "succeeded"
    assert guarded_calls == [
        ("mds.sitl.instances.create", {}),
        (
            "mds.sitl.instances.action",
            {"action": lifecycle_action, "instance_names": ["drone-1"]},
        ),
    ]


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
                        condition="after_command_terminal_success",
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
                        condition="after_command_terminal_success",
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
    display_labels = [item["label"] for item in draft["display_plan"]["steps"]]
    assert len(display_labels) == 3
    assert display_labels[0] == "Take off to 10 m"
    assert "5 m north" in display_labels[1]
    assert display_labels[2] == "Return to launch"
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
                        condition="after_command_terminal_success",
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


@pytest.mark.parametrize("read_intents", [("fleet_status",), ()])
def test_simurgh_provider_read_action_disagreement_asks_for_clarification(monkeypatch, read_intents):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        lambda **_kwargs: _provider_rewrite(
            normalized_message="read current fleet status",
            route_hint="read_status",
            read_intents=read_intents,
        ),
    )
    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "takeoff drone 1 to 10m, wait 5s, move 10m east, then RTL",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == (
        "I can interpret this as either a status check or an action. "
        "Should I inspect the current state, or prepare the action for confirmation?"
    )
    assert payload["trace"]["intent"]["provider_action_plan_error"] == (
        "provider_read_status_conflicted_with_local_action"
    )
    assert payload["trace"]["tool"]["ids"] == []
    assert payload["trace"]["intent"]["provider_semantic_rewrite"]["needs_clarification"] is True


def test_simurgh_truncated_provider_plan_asks_from_source_coverage(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    message = "takeoff drone 1 to 10m, wait 5s, move 10m east, then RTL"

    def truncated_rewrite(**_kwargs):
        return _provider_rewrite(
            normalized_message="return drone 1 to launch",
            route_hint="draft_flight_action",
            action_plan=ProviderActionPlan(
                summary="Return to launch",
                steps=(
                    _provider_step(
                        message,
                        "drone 1 to 10m, wait 5s, move 10m east, then RTL",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 104,
                            "trigger_time": 0,
                            "target_drone_ids": ["1"],
                        },
                        label="Return to launch",
                    ),
                ),
            ),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr("api_routes.simurgh.rewrite_operator_message_with_provider", truncated_rewrite)
    response = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["intent"]["provider_action_plan_error"].startswith(
        "provider_action_plan_incomplete_source_coverage:"
    )
    assert payload["content"] == (
        "I may be missing part of the requested sequence. "
        "Should I keep every step in the same order?"
    )
    assert payload["trace"]["tool"]["ids"] == []
    assert payload["trace"]["intent"]["provider_semantic_rewrite"]["needs_clarification"] is True


def test_provider_semantics_asks_when_negation_conflicts_with_typed_fallback(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    message = "take off drone 1 to 10m; do not wait 5s; then RTL"

    def semantic_plan(**_kwargs):
        return _provider_rewrite(
            normalized_message="take off drone 1 to 10m, then RTL without waiting",
            route_hint="draft_flight_action",
            action_plan=ProviderActionPlan(
                summary="Take off, then return without waiting",
                steps=(
                    _provider_step(
                        message,
                        "take off drone 1 to 10m",
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
                        "then RTL",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 104, "trigger_time": 0},
                        condition="after_command_terminal_success",
                        label="Return to launch",
                    ),
                ),
            ),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        semantic_plan,
    )
    payload = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    ).json()

    assert payload["trace"]["intent"]["route"] == "semantic_clarification"
    assert payload["trace"]["intent"]["provider_action_plan_error"] == (
        "provider_action_plan_conflicts_with_grounded_sequence"
    )
    assert payload["content"] == (
        "I found two different interpretations of the sequence. "
        "Should I keep every requested step in the same order and stop if any step fails?"
    )
    assert payload["trace"]["safety"].get("action_draft") is None


def test_provider_plan_cannot_silently_omit_grounded_sequence_steps(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    message = "takeoff drone 1 to 10m, wait 5s, move 10m east, wait 30s, then RTL"

    def incomplete_plan(**_kwargs):
        return _provider_rewrite(
            normalized_message="take off drone 1, move east, then finish",
            route_hint="draft_flight_action",
            action_plan=ProviderActionPlan(
                summary="Take off and move east",
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
                        "move 10m east",
                        tool_id="mds.flight.command.execute",
                        arguments={
                            "mission_type": 112,
                            "trigger_time": 0,
                            "precision_move": {
                                "frame": "ned",
                                "translation_m": {
                                    "north": 0,
                                    "east": 10,
                                    "up": 0,
                                },
                            },
                        },
                        condition="after_command_terminal_success",
                        label="Move 10 m east",
                    ),
                ),
            ),
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        incomplete_plan,
    )

    payload = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    ).json()

    assert payload["trace"]["intent"]["route"] == "semantic_clarification"
    assert payload["trace"]["intent"]["provider_action_plan_error"] == (
        "provider_action_plan_conflicts_with_grounded_sequence"
    )
    assert payload["trace"]["safety"].get("action_draft") is None


def test_provider_plan_cannot_change_ordinary_step_to_run_after_failure(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    message = "takeoff drone 1 to 10m, then RTL"

    def changed_failure_policy(**_kwargs):
        return _provider_rewrite(
            normalized_message="take off drone 1 to 10 m, then return to launch",
            route_hint="draft_flight_action",
            action_plan=ProviderActionPlan(
                summary="Take off, then return",
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
                        "then RTL",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 104, "trigger_time": 0},
                        condition="after_command_terminal",
                        label="Return to launch",
                    ),
                ),
            ),
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        changed_failure_policy,
    )

    payload = _client().post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": message},
    ).json()

    assert payload["trace"]["intent"]["route"] == "semantic_clarification"
    assert payload["trace"]["intent"]["provider_action_plan_error"] == (
        "provider_action_plan_conflicts_with_grounded_sequence"
    )
    assert payload["trace"]["safety"].get("action_draft") is None


def test_provider_action_plan_can_ground_clarified_fact_in_prior_request():
    prior = "Take off to 10m, then move 5m north."
    current = "Use drone 1."
    payload = {
        "summary": "Take off and move north",
        "target_references": [
            {
                "target_id": "1",
                "source_message_index": 0,
                "source_start": current.index("drone 1"),
                "source_end": current.index("drone 1") + len("drone 1"),
                "source_excerpt": "drone 1",
            }
        ],
        "steps": [
            {
                "kind": "tool",
                "tool_id": "mds.flight.command.execute",
                "arguments_json": json.dumps(
                    {
                        "mission_type": 10,
                        "trigger_time": 0,
                        "target_drone_ids": ["1"],
                        "takeoff_altitude": 10,
                    }
                ),
                "delay_seconds": None,
                "condition": "start",
                "monitor_requested": True,
                "label": "Take off to 10 m",
                "source_message_index": 1,
                "source_start": prior.index("Take off to 10m"),
                "source_end": prior.index("Take off to 10m") + len("Take off to 10m"),
                "source_excerpt": "Take off to 10m",
            },
            {
                "kind": "tool",
                "tool_id": "mds.flight.command.execute",
                "arguments_json": json.dumps(
                    {
                        "mission_type": 112,
                        "trigger_time": 0,
                        "precision_move": {
                            "frame": "ned",
                            "translation_m": {"north": 5, "east": 0, "up": 0},
                        },
                    }
                ),
                "delay_seconds": None,
                "condition": "after_command_terminal_success",
                "monitor_requested": True,
                "label": "Move 5 m north",
                "source_message_index": 1,
                "source_start": prior.index("move 5m north"),
                "source_end": prior.index("move 5m north") + len("move 5m north"),
                "source_excerpt": "move 5m north",
            },
        ],
    }

    plan = parse_provider_action_plan(
        payload,
        original_message=current,
        grounding_messages=(prior,),
    )

    assert plan is not None
    assert len(plan.steps) == 2
    assert plan.steps[0].arguments["target_drone_ids"] == ["1"]
    assert plan.steps[0].arguments["takeoff_altitude"] == 10


def test_provider_action_plan_rejects_numbers_reassigned_between_steps():
    message = "take off to 10m, then wait 5s"
    payload = {
        "summary": "Invalid swapped sequence",
        "steps": [
            {
                "kind": "tool",
                "tool_id": "mds.flight.command.execute",
                "arguments_json": json.dumps({"mission_type": 10, "takeoff_altitude": 5}),
                "delay_seconds": None,
                "condition": "start",
                "monitor_requested": False,
                "label": "Take off",
                "source_message_index": 0,
                "source_start": message.index("take off to 10m"),
                "source_end": message.index("take off to 10m") + len("take off to 10m"),
                "source_excerpt": "take off to 10m",
            },
            {
                "kind": "delay",
                "tool_id": None,
                "arguments_json": "{}",
                "delay_seconds": 10,
                "condition": "after_command_terminal_success",
                "monitor_requested": False,
                "label": "Wait",
                "source_message_index": 0,
                "source_start": message.index("wait 5s"),
                "source_end": message.index("wait 5s") + len("wait 5s"),
                "source_excerpt": "wait 5s",
            },
        ],
    }

    with pytest.raises(ValueError, match="not grounded in the cited operator text"):
        parse_provider_action_plan(payload, original_message=message)


def test_provider_flight_plan_cannot_disable_runtime_monitoring():
    plan = ProviderActionPlan(
        summary="Take off then return",
        steps=(
            ProviderActionStep(
                kind="tool",
                tool_id="mds.flight.command.execute",
                arguments={"mission_type": 10, "target_drone_ids": ["1"], "takeoff_altitude": 10},
                delay_seconds=None,
                condition="start",
                monitor_requested=False,
                label="Take off",
                source_start=0,
                source_end=7,
                source_excerpt="takeoff",
            ),
            ProviderActionStep(
                kind="tool",
                tool_id="mds.flight.command.execute",
                arguments={"mission_type": 104},
                delay_seconds=None,
                condition="after_command_terminal_success",
                monitor_requested=False,
                label="Return",
                source_start=8,
                source_end=14,
                source_excerpt="return",
            ),
        ),
    )

    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-monitor",
        previous_action=None,
        tool_contracts={
            "mds.flight.command.execute": {
                "title": "Execute curated flight command",
                "intent": "flight_action",
                "monitor_kind": "command",
                "required": (),
            }
        },
    )

    assert result.accepted is True
    assert isinstance(result.draft, FlightActionDraft)
    assert result.draft.monitor_requested is True
    assert result.draft.post_actions[0]["monitor_requested"] is True


def test_semantic_plan_preservation_compares_frame_target_and_dependency_condition():
    initial = FlightActionDraft(
        draft_id="act-initial",
        mission_name="TAKE_OFF",
        mission_type=10,
        target_drone_ids=("1",),
        command_payload={"mission_type": 10, "target_drone_ids": ["1"], "takeoff_altitude": 10},
        wait_condition="command_terminal_success",
        post_actions=(
            {
                "type": "flight_command",
                "tool_id": "mds.flight.command.execute",
                "condition": "after_command_terminal_success",
                "wait_condition": "command_terminal_success",
                "arguments": {
                    "mission_type": 112,
                    "target_drone_ids": ["1"],
                    "precision_move": {
                        "frame": "ned",
                        "translation_m": {"north": 5, "east": 0, "up": 0},
                    },
                },
            },
        ),
    )
    changed = FlightActionDraft(
        draft_id="act-changed",
        mission_name="TAKE_OFF",
        mission_type=10,
        target_drone_ids=("1",),
        command_payload={"mission_type": 10, "target_drone_ids": ["1"], "takeoff_altitude": 10},
        wait_condition="command_terminal_success",
        post_actions=(
            {
                "type": "flight_command",
                "tool_id": "mds.flight.command.execute",
                "condition": "after_command_terminal",
                "wait_condition": "command_terminal",
                "arguments": {
                    "mission_type": 112,
                    "target_drone_ids": ["2"],
                    "precision_move": {
                        "frame": "body",
                        "translation_m": {"north": 5, "east": 0, "up": 0},
                    },
                },
            },
        ),
    )

    assert _semantic_rewrite_preserves_draft_facts(initial, changed) is False


def test_incomplete_typed_sequence_allows_source_grounded_intervening_steps():
    initial = FlightActionDraft(
        draft_id="act-incomplete",
        mission_name="TAKE_OFF",
        mission_type=10,
        target_drone_ids=("1",),
        command_payload={
            "mission_type": 10,
            "target_drone_ids": ["1"],
            "takeoff_altitude": 10,
        },
        missing_arguments=("sequence_timing",),
        wait_condition="command_terminal_success",
        post_actions=(
            {
                "type": "delay",
                "condition": "after_command_terminal_success",
                "delay_seconds": 5,
            },
            {
                "type": "flight_command",
                "tool_id": "mds.flight.command.execute",
                "condition": "after_command_terminal_success",
                "wait_condition": "command_terminal_success",
                "arguments": {
                    "mission_type": 112,
                    "target_drone_ids": ["1"],
                    "precision_move": {
                        "frame": "ned",
                        "translation_m": {"north": 25, "east": 0, "up": 0},
                    },
                },
            },
            {
                "type": "flight_command",
                "tool_id": "mds.flight.command.execute",
                "condition": "after_command_terminal_success",
                "wait_condition": "command_terminal_success",
                "arguments": {
                    "mission_type": 112,
                    "target_drone_ids": ["1"],
                    "precision_move": {
                        "frame": "ned",
                        "translation_m": {"north": 0, "east": 0, "up": 10},
                    },
                },
            },
            {
                "type": "flight_command",
                "tool_id": "mds.flight.command.execute",
                "condition": "after_command_terminal_success",
                "wait_condition": "command_terminal_success",
                "arguments": {"mission_type": 104, "target_drone_ids": ["1"]},
            },
        ),
    )
    expanded = FlightActionDraft(
        draft_id="act-expanded",
        mission_name="TAKE_OFF",
        mission_type=10,
        target_drone_ids=("1",),
        command_payload=dict(initial.command_payload),
        wait_condition="command_terminal_success",
        post_actions=(
            initial.post_actions[0],
            initial.post_actions[1],
            {
                "type": "delay",
                "condition": "after_command_terminal_success",
                "delay_seconds": 5,
            },
            initial.post_actions[2],
            initial.post_actions[3],
        ),
    )

    assert _semantic_rewrite_preserves_draft_facts(initial, expanded) is True

    complete = FlightActionDraft(
        draft_id="act-complete",
        mission_name=initial.mission_name,
        mission_type=initial.mission_type,
        target_drone_ids=initial.target_drone_ids,
        command_payload=dict(initial.command_payload),
        wait_condition=initial.wait_condition,
        post_actions=initial.post_actions,
    )
    assert _semantic_rewrite_preserves_draft_facts(complete, expanded) is False


def test_provider_flight_plan_supports_guarded_cleanup_after_terminal_flight_step():
    plan = ProviderActionPlan(
        summary="Land then remove the simulator",
        steps=(
            ProviderActionStep(
                kind="tool",
                tool_id="mds.flight.command.execute",
                arguments={"mission_type": 101, "target_drone_ids": ["1"]},
                delay_seconds=None,
                condition="start",
                monitor_requested=False,
                label="Land drone 1",
                source_start=0,
                source_end=12,
                source_excerpt="land drone 1",
            ),
            ProviderActionStep(
                kind="tool",
                tool_id="mds.sitl.instances.action",
                arguments={"action": "remove", "instance_names": ["drone-1"]},
                delay_seconds=None,
                condition="after_command_terminal_success",
                monitor_requested=False,
                label="Remove drone-1",
                source_start=18,
                source_end=32,
                source_excerpt="remove drone-1",
            ),
        ),
    )

    result = build_action_draft_from_provider_plan(
        plan,
        draft_id="act-cleanup",
        previous_action=None,
        tool_contracts={
            "mds.flight.command.execute": {
                "title": "Execute curated flight command",
                "intent": "flight_action",
                "monitor_kind": "command",
                "required": (),
            },
            "mds.sitl.instances.action": {
                "title": "Manage SITL instances",
                "intent": "sitl_lifecycle_action",
                "monitor_kind": "sitl_operation",
                "required": ("action", "instance_names"),
            },
        },
    )

    assert result.accepted is True
    assert isinstance(result.draft, FlightActionDraft)
    assert result.draft.post_actions == (
        {
            "type": "registry_action",
            "tool_id": "mds.sitl.instances.action",
            "tool_title": "Manage SITL instances",
            "action_label": "Remove drone-1",
            "condition": "after_command_terminal_success",
            "arguments": {"action": "remove", "instance_names": ["drone-1"]},
            "monitor_requested": True,
            "wait_condition": "operation_terminal_success",
        },
    )


@pytest.mark.parametrize(
    ("needs", "reason", "question", "expected_needs", "expected_reason", "question_present"),
    [
        (False, "semantic_ambiguity", "", True, "semantic_ambiguity", True),
        (True, "none", "", True, "semantic_ambiguity", True),
        (False, "none", "stale question", False, "none", False),
    ],
)
def test_provider_semantic_clarification_fields_are_consistent(
    needs,
    reason,
    question,
    expected_needs,
    expected_reason,
    question_present,
):
    rewrite = _semantic_rewrite_from_payload(
        {
            "normalized_message": "operator request",
            "language": "en",
            "route_hint": "general_question",
            "confidence": 0.9,
            "read_intents": [],
            "needs_clarification": needs,
            "clarification_question": question,
            "clarification_reason": reason,
            "notes": [],
            "action_plan": None,
        },
        config=SimpleNamespace(openai=SimpleNamespace(model="test")),
        original_message="operator request",
    )

    assert rewrite.needs_clarification is expected_needs
    assert rewrite.clarification_reason == expected_reason
    assert bool(rewrite.clarification_question) is question_present


def test_provider_semantic_non_action_route_rejects_action_payload():
    message = "show the current fleet status"
    payload = {
        "normalized_message": message,
        "language": "en",
        "route_hint": "general_question",
        "confidence": 0.9,
        "read_intents": [],
        "read_target_drone_ids": [],
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_reason": "none",
        "notes": [],
        "action_plan": {
            "summary": "Incorrect action payload",
            "steps": [
                {
                    "kind": "tool",
                    "tool_id": "mds.flight.command.execute",
                    "arguments_json": json.dumps({"mission_type": 104}),
                    "delay_seconds": None,
                    "condition": "start",
                    "monitor_requested": False,
                    "label": "RTL",
                    "source_message_index": 0,
                    "source_start": 0,
                    "source_end": len(message),
                    "source_excerpt": message,
                }
            ],
        },
    }

    with pytest.raises(AgentRuntimeError, match="conflicts with the selected non-action route"):
        _semantic_rewrite_from_payload(
            payload,
            config=SimpleNamespace(openai=SimpleNamespace(model="test")),
            original_message=message,
        )


def test_clarification_grounding_retains_root_request_across_multiple_rounds():
    first = _updated_clarification_operator_messages({}, "Take off to 10m, then move east.")
    second_context = {
        "last_domain": "clarification",
        "last_user_message": "Take off to 10m, then move east.",
        "clarification_operator_messages": first,
    }
    second = _updated_clarification_operator_messages(second_context, "Use drone 1.")
    third_context = {
        "last_domain": "clarification",
        "last_user_message": "Use drone 1.",
        "clarification_operator_messages": second,
    }

    assert _semantic_rewrite_grounding_messages(third_context) == (
        "Take off to 10m, then move east.",
        "Use drone 1.",
    )


def test_semantic_grounding_uses_recent_operator_messages_outside_clarification():
    context = {
        "last_domain": "flight",
        "last_user_message": "What happened?",
        "recent_operator_messages": json.dumps(
            [
                "Take off Drone 1, wait 5 seconds, then RTL.",
                "Confirm it.",
                "What happened?",
            ]
        ),
    }

    assert _semantic_rewrite_grounding_messages(context) == (
        "Take off Drone 1, wait 5 seconds, then RTL.",
        "Confirm it.",
        "What happened?",
    )


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
            clarification_reason="semantic_ambiguity",
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


def test_simurgh_provider_semantic_call_runs_off_request_event_loop(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        return _provider_rewrite(
            normalized_message="report fleet status",
            route_hint="read_status",
            read_intents=("fleet_summary",),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "How many drones are configured?"},
    )

    assert response.status_code == 200


def test_simurgh_general_turn_runs_blocking_assistant_adapter_off_event_loop(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    original_create_turn = simurgh_routes.create_assistant_turn

    def checked_create_assistant_turn(**kwargs):
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        return original_create_turn(**kwargs)

    monkeypatch.setattr(
        "api_routes.simurgh._semantic_rewrite_is_safe_to_try",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.create_assistant_turn",
        checked_create_assistant_turn,
    )
    client = _client()

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "Hello Simurgh."},
    )

    assert response.status_code == 200


def test_previous_action_followup_uses_durable_actor_journal_in_new_session(monkeypatch):
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    action_run_store = ActionRunStore(os.environ["MDS_AGENT_ACTION_RUN_DB"])
    run, created = action_run_store.create_or_get(
        actor="operator",
        session_id="session-before-restart",
        draft_id="act-durable123",
        plan={
            "draft_id": "act-durable123",
            "draft_type": "flight_action",
            "mission_name": "TAKE_OFF",
            "target_drone_ids": ["1"],
            "post_actions": [
                {
                    "type": "delay",
                    "action_label": "Wait 5 seconds",
                    "delay_seconds": 5.0,
                },
                {
                    "type": "flight_command",
                    "action_label": "Return to launch",
                    "arguments": {
                        "mission_type": 104,
                        "target_drone_ids": ["1"],
                    },
                },
            ],
        },
        plan_hash="durable-plan-hash",
        total_steps=3,
    )
    assert created is True
    action_run_store.append_event(
        run.run_id,
        event_type="run_completed",
        payload={"label": "Action run complete"},
        state="succeeded",
        current_step=3,
        summary="Completed 3 of 3 planned steps.",
        result={
            "action_response": {
                "command_id": "cmd-takeoff",
                "mission_name": "TAKE_OFF",
                "target_drones": ["1"],
            },
            "monitor_result": {"status": "terminal_success", "success": True},
            "post_action_results": [
                {
                    "type": "delay",
                    "label": "Wait 5 seconds",
                    "status": "completed",
                    "summary": "waited 5 second(s)",
                },
                {
                    "type": "flight_command",
                    "label": "Return to launch",
                    "status": "terminal_success",
                    "command_id": "cmd-rtl",
                },
            ],
        },
    )
    monkeypatch.setattr(
        "api_routes.simurgh._semantic_rewrite_is_safe_to_try",
        lambda **_kwargs: False,
    )
    app = FastAPI()
    app.include_router(
        create_simurgh_router(
            SimpleNamespace(simurgh_action_run_store=action_run_store)
        )
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Did the 5 second wait run, or was it skipped in the previous action?",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["safety"]["action_execution"] == "previous_action_summary"
    assert "Last action run: succeeded" in payload["content"]
    assert "Wait steps: 1/1 completed" in payload["content"]
    assert "Wait 5 seconds: completed" in payload["content"]
    assert "No new action was executed." in payload["content"]


def test_ungrounded_provider_control_classification_cannot_confirm_pending_action(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    action_message = "takeoff drone 1 to 10m"

    def fake_rewrite_operator_message_with_provider(**kwargs):
        message = kwargs["message"]
        if message == action_message:
            return _provider_rewrite(
                normalized_message=action_message,
                route_hint="draft_flight_action",
                action_plan=ProviderActionPlan(
                    summary="Take off Drone 1",
                    steps=(
                        _provider_step(
                            action_message,
                            action_message,
                            tool_id="mds.flight.command.execute",
                            arguments={
                                "mission_type": 10,
                                "target_drone_ids": ["1"],
                                "takeoff_altitude": 10,
                            },
                            label="Take off Drone 1 to 10 m",
                        ),
                    ),
                ),
            )
        return _provider_rewrite(
            normalized_message="confirm the pending action",
            route_hint="confirm_pending_action",
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()
    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": action_message},
    )
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    session_id = draft_payload["session"]["id"]

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "session_id": session_id, "message": "show me the pending plan"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "pending Simurgh action draft" in payload["content"]
    assert draft_payload["trace"]["safety"]["action_draft"]["draft_id"] in payload["content"]
    assert payload["trace"]["tool"]["ids"] == ["mds.flight.command.execute"]
    assert payload["trace"]["safety"]["action_execution"] == "pending_action_summary"


def test_source_grounded_multilingual_confirmation_resolves_one_pending_actor_draft(
    monkeypatch,
):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    action_message = "takeoff drone 1 to 10m"
    confirmation_message = "این عملیات را تایید می‌کنم"

    def fake_rewrite_operator_message_with_provider(**kwargs):
        message = kwargs["message"]
        if message == action_message:
            return _provider_rewrite(
                normalized_message=action_message,
                route_hint="draft_flight_action",
                action_plan=ProviderActionPlan(
                    summary="Take off Drone 1",
                    steps=(
                        _provider_step(
                            action_message,
                            action_message,
                            tool_id="mds.flight.command.execute",
                            arguments={
                                "mission_type": 10,
                                "target_drone_ids": ["1"],
                                "takeoff_altitude": 10,
                            },
                            label="Take off Drone 1 to 10 m",
                        ),
                    ),
                ),
            )
        return _provider_rewrite(
            normalized_message="confirm the pending action",
            route_hint="confirm_pending_action",
            action_control_explicit=True,
            action_control_source_start=0,
            action_control_source_end=len(confirmation_message),
            action_control_source_excerpt=confirmation_message,
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()
    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": action_message},
    )
    assert draft_response.status_code == 200
    session_id = draft_response.json()["session"]["id"]

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": session_id,
            "message": confirmation_message,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["intent"]["provider_action_plan_error"] == (
        "provider_confirmation_requires_local_resolution"
    )
    assert payload["trace"]["safety"]["action_execution"] == (
        "blocked_by_circuit_breaker"
    )


def test_ungrounded_provider_control_reaches_route_as_non_routable_evidence(
    monkeypatch,
):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    action_message = "takeoff drone 1 to 10m"
    control_message = "تاییدش کن"

    def fake_rewrite_operator_message_with_provider(**kwargs):
        message = kwargs["message"]
        if message == action_message:
            return _provider_rewrite(
                normalized_message=action_message,
                route_hint="draft_flight_action",
                action_plan=ProviderActionPlan(
                    summary="Take off Drone 1",
                    steps=(
                        _provider_step(
                            action_message,
                            action_message,
                            tool_id="mds.flight.command.execute",
                            arguments={
                                "mission_type": 10,
                                "target_drone_ids": ["1"],
                                "takeoff_altitude": 10,
                            },
                            label="Take off Drone 1 to 10 m",
                        ),
                    ),
                ),
            )
        return _semantic_rewrite_from_payload(
            {
                "normalized_message": "confirm pending action",
                "language": "en",
                "route_hint": "confirm_pending_action",
                "confidence": 0.99,
                "needs_clarification": False,
                "clarification_reason": "none",
                "action_control_explicit": True,
                "action_control_source_start": 0,
                "action_control_source_end": 7,
                "action_control_source_excerpt": "approve",
                "action_plan": None,
            },
            config=SimpleNamespace(openai=SimpleNamespace(model="test")),
            original_message=message,
        )

    monkeypatch.setattr(
        "api_routes.simurgh._has_external_assistant_provider_auth",
        lambda _request: True,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    client = _client()
    draft_response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": action_message},
    )
    assert draft_response.status_code == 200

    response = client.post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "session_id": draft_response.json()["session"]["id"],
            "message": control_message,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["intent"]["provider_action_plan_error"] == (
        "provider_action_control_requires_source_grounding"
    )
    semantic = payload["trace"]["intent"]["provider_semantic_rewrite"]
    assert semantic["usable_for_routing"] is False
    assert semantic["action_control_grounding_error"] == "source_span_mismatch"
    assert payload["trace"]["safety"]["action_execution"] == "pending_action_summary"


@pytest.mark.parametrize("runtime_mode", ["sitl", "real"])
def test_simurgh_provider_missing_runtime_name_without_plan_stays_clarification(
    monkeypatch,
    runtime_mode,
):
    monkeypatch.setenv("MDS_MODE", runtime_mode)
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    class FakeSitlService:
        def list_instances(self):
            return SimpleNamespace(
                instances=[SimpleNamespace(name="drone-1", state="running", status="running", hw_id="1")]
            )

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        return _provider_rewrite(
            normalized_message="remove the current SITL instance and report when complete",
            route_hint="clarify",
            confidence=0.94,
            needs_clarification=True,
            clarification_question="Which SITL instance should I remove?",
            clarification_reason="missing_runtime_context",
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    app = FastAPI()
    app.include_router(create_simurgh_router(SimpleNamespace(sitl_control_service=FakeSitlService())))
    response = TestClient(app).post(
        "/api/v1/simurgh/assistant/turns",
        json={
            "actor": "operator",
            "message": "Remove the one running SITL instance and report when cleanup is complete.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Which SITL instance" in payload["content"]
    assert payload["trace"]["intent"]["route"] == "semantic_clarification"
    assert "action_draft" not in payload["trace"]["safety"]


def test_simurgh_unknown_sitl_state_is_not_a_live_action_target(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "true")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")

    class FakeSitlService:
        def list_instances(self):
            return SimpleNamespace(
                instances=[SimpleNamespace(name="drone-1", state="", status="", hw_id="1")]
            )

    def fake_rewrite_operator_message_with_provider(**_kwargs):
        return _provider_rewrite(
            normalized_message="take off to 10 m",
            route_hint="draft_flight_action",
            confidence=0.95,
            action_plan=ProviderActionPlan(
                summary="Take off the current drone",
                steps=(
                    _provider_step(
                        "take off to 10 m",
                        "take off to 10 m",
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 10, "takeoff_altitude": 10},
                        label="Take off to 10 m",
                    ),
                ),
            ),
        )

    monkeypatch.setattr("api_routes.simurgh._has_external_assistant_provider_auth", lambda _request: True)
    monkeypatch.setattr(
        "api_routes.simurgh.rewrite_operator_message_with_provider",
        fake_rewrite_operator_message_with_provider,
    )
    app = FastAPI()
    app.include_router(create_simurgh_router(SimpleNamespace(sitl_control_service=FakeSitlService())))

    response = TestClient(app).post(
        "/api/v1/simurgh/assistant/turns",
        json={"actor": "operator", "message": "take off to 10 m"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace"]["safety"]["action_execution"] == "missing_arguments"
    assert payload["trace"]["safety"]["action_draft"]["target_drone_ids"] == []
    assert "target_drone_ids" in payload["trace"]["safety"]["action_draft"]["missing_arguments"]


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
                clarification_reason="semantic_ambiguity",
            )
        assert "Operator message 1: land or rtl drone 1 now" in kwargs["clarification_context"]
        assert "Clarification asked: Should I land Drone 1 here, or return it to launch?" in kwargs["clarification_context"]
        assert kwargs["grounding_messages"] == ("land or rtl drone 1 now",)
        target_source = "land or rtl drone 1 now"
        return _provider_rewrite(
            normalized_message="return to launch drone 1",
            route_hint="draft_flight_action",
            confidence=0.97,
            action_plan=ProviderActionPlan(
                summary="Return Drone 1 to launch",
                steps=(
                    _provider_step(
                        target_source,
                        target_source,
                        tool_id="mds.flight.command.execute",
                        arguments={"mission_type": 104, "trigger_time": 0, "target_drone_ids": ["1"]},
                        label="Return Drone 1 to launch",
                        source_message_index=1,
                    ),
                ),
                target_references=(
                    ProviderActionTargetReference(
                        target_id="1",
                        source_message_index=1,
                        source_start=target_source.index("drone 1"),
                        source_end=target_source.index("drone 1") + len("drone 1"),
                        source_excerpt="drone 1",
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
    assert payload["trace"]["safety"]["action_draft"]["arguments"] == {}


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

    async def fake_guarded_route_tool(
        _request, *, name, arguments, channel, approved, registry, policy, **_kwargs
    ):
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
    app = FastAPI()

    @app.get("/api/v1/system/sitl/operations/{operation_id}")
    async def fake_sitl_operation_status(operation_id: str):
        return {
            "operation_id": operation_id,
            "operation_type": "create_instance",
            "status": "succeeded",
            "summary": "SITL instance drone-1 is running.",
            "affected_instances": ["drone-1"],
        }

    _add_sitl_completion_evidence_routes(app, drone_ids=("1",))

    app.include_router(create_simurgh_router())
    client = TestClient(app)

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
            "arguments": {},
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
    assert payload["content"] == (
        'Which target should I use for the "remove SITL instance(s)" step?'
    )
    assert payload["trace"]["intent"]["route"] == "semantic_clarification"
    assert payload["trace"]["safety"]["action_execution"] == "none"


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
    assert "Current status checked before drafting" in content
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
    assert payload["content"] == (
        'Which target should I use for the "remove SITL instance(s)" step?'
    )
    assert payload["trace"]["intent"]["route"] == "semantic_clarification"
    assert payload["trace"]["safety"]["action_execution"] == "none"


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

    async def fake_guarded_route_tool(
        _request, *, name, arguments, channel, approved, registry, policy, **_kwargs
    ):
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
    app = FastAPI()

    @app.get("/api/v1/system/sitl/operations/{operation_id}")
    async def fake_sitl_operation_status(operation_id: str):
        return {
            "operation_id": operation_id,
            "operation_type": "reconcile_fleet",
            "status": "succeeded",
            "summary": "Reconciled 4 SITL instances.",
            "affected_instances": ["drone-1", "drone-2", "drone-3", "drone-4"],
            "metadata": {"target_count": 4},
        }

    _add_sitl_completion_evidence_routes(app, drone_ids=("1", "2", "3", "4"))

    app.include_router(create_simurgh_router())
    client = TestClient(app)

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

    async def fake_guarded_route_tool(
        _request, *, name, arguments, channel, approved, registry, policy, **_kwargs
    ):
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
            "operation_type": "create_instance",
            "status": "succeeded",
            "summary": "SITL instance drone-1 is running.",
            "affected_instances": ["drone-1"],
        }

    _add_sitl_completion_evidence_routes(app, drone_ids=("1",))

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
    assert "running container" in run["result"]["monitor_result"]["summary"]
    assert run["result"]["monitor_result"]["completion_verification"]["verified"] is True
    assert submitted == [
        {
            "name": "mds.sitl.instances.create",
            "arguments": {},
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

    async def fake_guarded_route_tool(
        _request, *, name, arguments, channel, approved, registry, policy, **_kwargs
    ):
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
            "operation_type": "create_instance",
            "status": "succeeded",
            "summary": "Created drone-1",
            "affected_instances": ["drone-1"],
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
                {
                    "hw_id": "1",
                    "online": True,
                    "presence_state": "live",
                    "presence": {"fresh": True, "telemetry_recent": True},
                    "ip": "172.18.0.2",
                },
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

    async def fake_guarded_route_tool(
        _request, *, name, arguments, channel, approved, registry, policy, **_kwargs
    ):
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


@pytest.mark.asyncio
async def test_cancel_remaining_drains_sitl_operation_and_readiness_with_heartbeats(
    monkeypatch,
):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    monkeypatch.setattr("api_routes.simurgh.ACTION_MONITOR_POLL_SECONDS", 0.001)
    monkeypatch.setattr("api_routes.simurgh.ACTION_MONITOR_HEARTBEAT_SECONDS", 0.003)
    operation_monitor_started = asyncio.Event()
    release_operation = asyncio.Event()
    readiness_monitor_started = asyncio.Event()
    release_readiness = asyncio.Event()
    operation_reads = 0
    readiness_reads = 0

    async def fake_guarded_route_tool(
        _request,
        *,
        name,
        arguments,
        channel,
        approved,
        registry,
        policy,
        **_kwargs,
    ):
        assert name == "mds.sitl.instances.create"
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": "sitl-op-drain",
                "operation_type": "create_instance",
                "status": "queued",
                "summary": "Creating drone-1",
            },
            status_code=200,
        )

    async def fake_read_only_tool(
        _request,
        *,
        name,
        arguments,
        channel,
        registry,
        policy,
        **_kwargs,
    ):
        nonlocal operation_reads, readiness_reads
        assert channel == "agent"
        if name == "mds.sitl.operation.read":
            operation_reads += 1
            operation_monitor_started.set()
            complete = release_operation.is_set()
            payload = {
                "operation_id": "sitl-op-drain",
                "operation_type": "create_instance",
                "status": "succeeded" if complete else "running",
                "summary": "Created drone-1" if complete else "Creating drone-1",
                "affected_instances": ["drone-1"] if complete else [],
            }
        elif name == "mds.sitl.instances.read":
            readiness_reads += 1
            readiness_monitor_started.set()
            ready = release_readiness.is_set()
            payload = {
                "instances": (
                    [
                        {
                            "name": "drone-1",
                            "state": "running",
                            "health_status": "healthy",
                            "hw_id": "1",
                        }
                    ]
                    if ready
                    else []
                ),
                "total_instances": 1 if ready else 0,
                "docker": {"available": True, "daemon_reachable": True},
            }
        elif name == "mds.fleet.heartbeats.read":
            ready = release_readiness.is_set()
            payload = {
                "heartbeats": (
                    [
                        {
                            "hw_id": "1",
                            "online": True,
                            "presence_state": "live",
                            "presence": {"fresh": True, "telemetry_recent": True},
                        }
                    ]
                    if ready
                    else []
                ),
                "total_drones": 1 if ready else 0,
                "online_count": 1 if ready else 0,
            }
        elif name == "mds.fleet.telemetry.read":
            ready = release_readiness.is_set()
            payload = {
                "telemetry": (
                    {
                        "1": {
                            "telemetry_available": True,
                            "is_ready_to_arm": True,
                            "is_armed": False,
                        }
                    }
                    if ready
                    else {}
                ),
                "total_drones": 1 if ready else 0,
                "online_drones": 1 if ready else 0,
            }
        else:
            raise AssertionError(f"Unexpected read-only tool: {name}")
        return ReadOnlyToolCallResult(
            text=json.dumps(payload),
            is_error=False,
            structured_content=payload,
            status_code=200,
        )

    monkeypatch.setattr(
        "api_routes.simurgh.execute_policy_allowed_guarded_route_tool",
        fake_guarded_route_tool,
    )
    monkeypatch.setattr(
        "api_routes.simurgh.execute_policy_allowed_read_only_tool",
        fake_read_only_tool,
    )

    app = FastAPI()
    action_run_store = ActionRunStore(os.environ["MDS_AGENT_ACTION_RUN_DB"])
    app.include_router(
        create_simurgh_router(
            SimpleNamespace(simurgh_action_run_store=action_run_store)
        )
    )
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
        SimurghAssistantTurnRequest(
            actor="operator",
            message="Create one SITL instance and report when ready",
        ),
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
    run_id = confirm_response.model_dump(mode="json")["trace"]["safety"]["action_run"]["run_id"]
    await asyncio.wait_for(operation_monitor_started.wait(), timeout=5.0)

    async def wait_for_monitor_heartbeat(source: str) -> None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if any(
                event.payload.get("progress_kind") == "heartbeat"
                and event.payload.get("latest_evidence", {}).get("source") == source
                for event in action_run_store.list_events(run_id)
            ):
                return
            await asyncio.sleep(0.005)
        raise AssertionError(f"Timed out waiting for {source} monitor heartbeat")

    action_run_store.request_control(
        run_id,
        actor="operator",
        action="cancel_remaining",
    )
    await wait_for_monitor_heartbeat("sitl_operation")
    assert action_run_store.require(run_id).terminal is False
    assert operation_reads > 1

    release_operation.set()
    await asyncio.wait_for(readiness_monitor_started.wait(), timeout=5.0)
    await wait_for_monitor_heartbeat("sitl_readiness")
    assert action_run_store.require(run_id).terminal is False
    assert readiness_reads > 1

    release_readiness.set()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if action_run_store.require(run_id).terminal:
            break
        await asyncio.sleep(0.01)

    terminal = action_run_store.require(run_id)
    assert terminal.state == "cancelled"
    assert terminal.result["monitor_result"]["success"] is True
    assert terminal.result["monitor_result"]["cancel_requested"] is True
    assert "reached terminal state" in terminal.summary
    heartbeat_sources = {
        event.payload["latest_evidence"]["source"]
        for event in action_run_store.list_events(run_id)
        if event.payload.get("progress_kind") == "heartbeat"
    }
    assert heartbeat_sources == {"sitl_operation", "sitl_readiness"}


def test_simurgh_sitl_monitor_retries_transient_readiness_evidence(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    monkeypatch.setattr("api_routes.simurgh.ACTION_MONITOR_POLL_SECONDS", 0.01)
    instance_reads = 0

    async def fake_guarded_route_tool(
        _request, *, name, arguments, channel, approved, registry, policy, **_kwargs
    ):
        return GuardedToolCallResult(
            text="{}",
            is_error=False,
            structured_content={
                "operation_id": "sitl-op-transient-evidence",
                "operation_type": "create_instance",
                "status": "queued",
                "summary": "Creating drone-1",
            },
            status_code=200,
        )

    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_guarded_route_tool", fake_guarded_route_tool)
    async def fake_read_only_tool(
        _request,
        *,
        name,
        arguments,
        channel,
        registry,
        policy,
        **_kwargs,
    ):
        nonlocal instance_reads
        assert channel == "agent"
        if name == "mds.sitl.operation.read":
            assert arguments == {"operation_id": "sitl-op-transient-evidence"}
            payload = {
                "operation_id": "sitl-op-transient-evidence",
                "operation_type": "create_instance",
                "status": "succeeded",
                "summary": "Created drone-1",
                "affected_instances": ["drone-1"],
            }
        elif name == "mds.sitl.instances.read":
            instance_reads += 1
            if instance_reads == 1:
                return ReadOnlyToolCallResult(
                    text="Docker inventory is warming up",
                    is_error=True,
                    status_code=503,
                )
            payload = {
                "instances": [
                    {
                        "name": "drone-1",
                        "state": "running",
                        "health_status": "healthy",
                        "hw_id": "1",
                    }
                ],
                "total_instances": 1,
                "docker": {"available": True, "daemon_reachable": True},
            }
        elif name == "mds.fleet.heartbeats.read":
            payload = {
                "heartbeats": [
                    {
                        "hw_id": "1",
                        "online": True,
                        "presence_state": "live",
                        "presence": {"fresh": True, "telemetry_recent": True},
                    }
                ],
                "total_drones": 1,
                "online_count": 1,
            }
        elif name == "mds.fleet.telemetry.read":
            payload = {
                "telemetry": {
                    "1": {
                        "telemetry_available": True,
                        "is_ready_to_arm": True,
                        "is_armed": False,
                    }
                },
                "total_drones": 1,
                "online_drones": 1,
            }
        else:
            raise AssertionError(f"Unexpected read-only tool: {name}")
        return ReadOnlyToolCallResult(
            text=json.dumps(payload),
            is_error=False,
            structured_content=payload,
            status_code=200,
        )

    monkeypatch.setattr("api_routes.simurgh.execute_policy_allowed_read_only_tool", fake_read_only_tool)
    app = FastAPI()
    app.include_router(create_simurgh_router())
    with TestClient(app) as client:
        draft_response = client.post(
            "/api/v1/simurgh/assistant/turns",
            json={"actor": "operator", "message": "Create one SITL instance and report when ready"},
        )
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
        run = _wait_for_action_run(client, confirm_response.json(), timeout=8.0)
    assert run["state"] == "succeeded"
    assert run["result"]["monitor_result"]["completion_verification"]["verified"] is True
    assert instance_reads >= 2


def test_simurgh_confirmed_sitl_create_submits_when_circuit_breaker_off(monkeypatch):
    monkeypatch.setenv("MDS_MODE", "sitl")
    monkeypatch.setenv("MDS_AGENT_ENABLED", "true")
    monkeypatch.setenv("MDS_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("MDS_AGENT_ACTION_CIRCUIT_BREAKER", "false")
    monkeypatch.setenv("MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION", "true")
    submitted = []

    async def fake_guarded_route_tool(
        _request, *, name, arguments, channel, approved, registry, policy, **_kwargs
    ):
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
    app = FastAPI()

    @app.get("/api/v1/system/sitl/operations/{operation_id}")
    async def fake_sitl_operation_status(operation_id: str):
        return {
            "operation_id": operation_id,
            "operation_type": "create_instance",
            "status": "succeeded",
            "summary": "SITL instance drone-1 is running.",
            "affected_instances": ["drone-1"],
        }

    _add_sitl_completion_evidence_routes(app, drone_ids=("1",))

    app.include_router(create_simurgh_router())
    client = TestClient(app)

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
            "arguments": {},
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
    assert payload["assistant_model"] == "gpt-5.6-sol"
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

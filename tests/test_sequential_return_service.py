import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

import sequential_return_service as module
from api_routes.swarm_runtime import create_swarm_runtime_router
from sequential_return_service import SequentialReturnRequest, SequentialReturnService


def make_service(tmp_path, monkeypatch, *, fail_hold=False):
    calls = []
    statuses = {}

    async def submit(deps, command):
        command_id = f"cmd-{len(calls)}"
        calls.append((command, asyncio.get_running_loop().time()))
        statuses[command_id] = {
            "status": "failed" if fail_hold and command.mission_type == 102 else "completed",
            "phase": "terminal",
            "error_summary": "Hold rejected" if fail_hold else None,
        }
        return SimpleNamespace(command_id=command_id)

    monkeypatch.setattr(module, "submit_tracked_command", submit)
    tracker = SimpleNamespace(get_status=AsyncMock(side_effect=lambda key: statuses[key]))
    deps = SimpleNamespace(
        Params=SimpleNamespace(GCS_COMMAND_STATE_DIR=str(tmp_path)),
        load_config=lambda: [{"hw_id": "1"}, {"hw_id": "2"}],
        get_command_tracker=lambda: tracker,
        telemetry_lock=threading.Lock(),
        telemetry_data_all_drones={
            key: dict(is_armed=True, flight_mode=(4 << 16) | (3 << 24),
                      telemetry_timestamp_ms=int(time.time() * 1000))
            for key in ("1", "2")
        },
    )
    service = SequentialReturnService(deps)
    deps.sequential_return_service = service
    return service, calls, deps


def request(**overrides):
    return SequentialReturnRequest(**{
        "target_drone_ids": ["2", "1"], "delay_sec": 1, "idempotency_key": "test-return",
        **overrides,
    })


@pytest.mark.asyncio
async def test_hold_then_ordered_rtl_with_minimum_interval(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch)
    job = await service.start(request())
    await service.task
    assert [(c.mission_type, c.target_drone_ids) for c, _ in calls] == [
        (102, ["2", "1"]), (104, ["2"]), (104, ["1"]),
    ]
    assert calls[2][1] - calls[1][1] >= 1
    assert service.get(job["return_id"])["state"] == "dispatched"
    assert service.latest()["commands"][0]["hw_id"] == "2"


@pytest.mark.asyncio
async def test_rejection_stops_queue_before_any_rtl(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch, fail_hold=True)
    await service.start(request())
    await service.task
    assert len(calls) == 1
    assert service.latest()["state"] == "failed"
    assert service.latest()["message"] == "Hold rejected"


@pytest.mark.asyncio
async def test_first_rtl_failure_stops_remaining_aircraft(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch)
    original_wait = service._wait_command

    async def wait_command(command_id, **kwargs):
        if kwargs.get("hw_id") == "2":
            raise RuntimeError("PX4 rejected Return")
        return await original_wait(command_id, **kwargs)

    service._wait_command = wait_command
    await service.start(request())
    await service.task
    assert [(c.mission_type, c.target_drone_ids) for c, _ in calls] == [(102, ["2", "1"]), (104, ["2"])]
    assert service.latest()["state"] == "failed"
    assert service.latest()["message"] == "PX4 rejected Return"


@pytest.mark.asyncio
async def test_cancel_pending_preserves_issued_command(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch)
    job = await service.start(request(delay_sec=10))
    while service.latest()["state"] != "waiting":
        await asyncio.sleep(0)
    await service.cancel(job["return_id"])
    assert [c.mission_type for c, _ in calls] == [102, 104]
    assert service.latest()["state"] == "cancelled"
    assert len(service.latest()["commands"]) == 1


@pytest.mark.asyncio
async def test_retry_and_refresh_do_not_duplicate_and_restart_does_not_resume(tmp_path, monkeypatch):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    job = await service.start(request(delay_sec=10))
    assert (await service.start(request(delay_sec=10)))["return_id"] == job["return_id"]
    with pytest.raises(HTTPException) as conflict:
        await service.start(request(delay_sec=20))
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException):
        await service.start(request(idempotency_key="another"))
    while service.latest()["state"] != "waiting":
        await asyncio.sleep(0)
    restored = SequentialReturnService(deps)
    assert restored.latest()["state"] == "interrupted"
    assert restored.task is None
    await service.close()
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["pilot", "disarm", "stale"])
async def test_waiting_aircraft_takeover_or_link_loss_stops_remaining(tmp_path, monkeypatch, change):
    service, calls, deps = make_service(tmp_path, monkeypatch)
    original_command = service._command

    async def command(job, mission, targets, suffix):
        command_id = await original_command(job, mission, targets, suffix)
        if mission.value == 104:
            if change == "pilot":
                deps.telemetry_data_all_drones["1"]["flight_mode"] = 3 << 16
            elif change == "disarm":
                deps.telemetry_data_all_drones["1"]["is_armed"] = False
            else:
                deps.telemetry_data_all_drones["1"]["telemetry_timestamp_ms"] = 1
        return command_id

    service._command = command
    await service.start(request())
    await service.task
    assert len(calls) == 2
    assert service.latest()["state"] == "failed"


@pytest.mark.asyncio
async def test_new_operator_command_cancels_pending_return(tmp_path, monkeypatch):
    service, calls, _ = make_service(tmp_path, monkeypatch)
    await service.start(request(delay_sec=10))
    while service.latest()["state"] != "waiting":
        await asyncio.sleep(0)
    await service.supersede(["99"])
    assert service.latest()["state"] == "waiting"
    await service.supersede(["1"])
    assert service.latest()["state"] == "cancelled"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_routes_default_interval_and_retry(tmp_path, monkeypatch):
    service, _, deps = make_service(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(create_swarm_runtime_router(deps))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        route = "/api/v1/swarm/runtime/sequential-return"
        assert (await client.get(route)).json() is None
        response = await client.post(route, json={"target_drone_ids": ["2", "1"], "idempotency_key": "api"})
        assert response.status_code == 202
        job = response.json()
        assert job["delay_sec"] == 10
        assert (await client.get(f"{route}/{job['return_id']}")).json()["target_drone_ids"] == ["2", "1"]
        assert (await client.post(f"{route}/{job['return_id']}/cancel")).json()["state"] == "cancelled"


@pytest.mark.parametrize("changes", [
    {"target_drone_ids": []}, {"target_drone_ids": ["1", "01"]},
    {"target_drone_ids": ["0"]}, {"delay_sec": 0}, {"delay_sec": float("nan")},
    {"delay_sec": 301},
])
def test_invalid_requests(changes):
    with pytest.raises(ValidationError):
        request(**changes)

import asyncio
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from src.enums import Mission
from src.launch_preparation_protocol import (
    LAUNCH_PREPARATION_TOKEN_HEADER,
    LaunchPreparationStore,
    calculate_launch_preparation_token_ttl_sec,
)


def _command(**overrides):
    command = {
        "mission_type": Mission.TAKE_OFF.value,
        "trigger_time": 0,
        "command_id": "launch-http-one",
        "target_hw_id": "1",
        "command_report_capability": "cap-" + ("x" * 39),
        "takeoff_altitude": 10.0,
    }
    command.update(overrides)
    return command


def _probe(*, ready=True):
    now_ms = int(time.time() * 1_000)
    blockers = [] if ready else ["PX4 armability"]
    return {
        "hw_id": "1",
        "success": True,
        "ready": ready,
        "summary": "ready for mission startup" if ready else "waiting for PX4 armability",
        "observation": {
            "schema_version": 1,
            "observation_id": f"http-probe-{now_ms}",
            "source": "test.health+battery",
            "observed_at_ms": now_ms,
            "valid_until_ms": now_ms + 2_000 if ready else 0,
            "require_global_position": True,
            "ready": ready,
            "blockers": blockers,
            "checks": {"armable": ready},
            "battery": {"remaining_percent": 80.0},
        },
        "remaining_valid_ms": 2_000 if ready else 0,
        "server_processing_ms": 1,
        "blockers": blockers,
        "armable": ready,
        "global_position_ok": ready,
        "home_position_ok": ready,
        "local_position_ok": True,
        "gyro_ok": True,
        "accel_ok": True,
        "mag_ok": True,
        "health_ready": ready,
        "health_age_ms": 0,
        "battery": {"remaining_percent": 80.0},
        "timed_out": False,
        "elapsed_sec": 0.01,
        "require_global_position": True,
        "timestamp": now_ms,
    }


def _prepare(test_client, api_server, command, *, ready=True):
    api_server._probe_live_armability = AsyncMock(return_value=_probe(ready=ready))
    return test_client.post(
        "/api/v1/preflight/launch-preparations",
        json={
            "schema_version": 1,
            "command": command,
            "require_global_position": True,
        },
    )


def test_lost_launch_response_retry_returns_authoritative_idempotent_ack(
    test_client,
    api_server,
    mock_drone_communicator,
):
    command = _command()
    prepared = _prepare(test_client, api_server, command)

    assert prepared.status_code == 200
    preparation = prepared.json()
    assert preparation["status"] == "prepared"
    assert preparation["command_id"] == command["command_id"]
    assert preparation["target_hw_id"] == "1"
    assert preparation["ready"] is True
    assert preparation["token_ttl_ms"] > 0
    token = preparation["preparation_token"]

    committed = test_client.post(
        "/api/v1/drone/commands",
        json=command,
        headers={LAUNCH_PREPARATION_TOKEN_HEADER: token},
    )
    replay = test_client.post(
        "/api/v1/drone/commands",
        json=command,
    )

    assert committed.status_code == 200
    assert committed.json()["status"] == "accepted"
    assert replay.status_code == 200
    assert replay.json()["status"] == "accepted"
    assert replay.json()["replayed"] is True
    assert replay.json()["command_id"] == command["command_id"]
    # One probe prepared the token and one fresh probe admitted the first
    # commit. The exact retry used authoritative command history only.
    assert api_server._probe_live_armability.await_count == 2
    mock_drone_communicator.process_command.assert_called_once()


def test_launch_without_preparation_fails_before_mutation(
    test_client,
    mock_drone_communicator,
):
    response = test_client.post("/api/v1/drone/commands", json=_command())

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert "required" in response.json()["error_detail"]
    mock_drone_communicator.process_command.assert_not_called()


def test_changed_payload_consumes_token_and_original_cannot_retry(
    test_client,
    api_server,
    mock_drone_communicator,
):
    command = _command()
    token = _prepare(test_client, api_server, command).json()["preparation_token"]

    changed = test_client.post(
        "/api/v1/drone/commands",
        json={**command, "takeoff_altitude": 20.0},
        headers={LAUNCH_PREPARATION_TOKEN_HEADER: token},
    )
    original = test_client.post(
        "/api/v1/drone/commands",
        json=command,
        headers={LAUNCH_PREPARATION_TOKEN_HEADER: token},
    )

    assert changed.json()["status"] == "rejected"
    assert "does not match" in changed.json()["error_detail"]
    assert original.json()["status"] == "rejected"
    assert original.json()["error_code"] == "E109"
    mock_drone_communicator.process_command.assert_not_called()


def test_commit_revalidates_ready_to_blocked_transition_before_installation(
    test_client,
    api_server,
    mock_drone_communicator,
):
    command = _command(command_id="ready-then-blocked")
    token = _prepare(test_client, api_server, command).json()["preparation_token"]
    api_server._probe_live_armability = AsyncMock(return_value=_probe(ready=False))

    response = test_client.post(
        "/api/v1/drone/commands",
        json=command,
        headers={LAUNCH_PREPARATION_TOKEN_HEADER: token},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["error_code"] == "E401"
    assert "PX4 armability" in response.json()["error_detail"]
    api_server._probe_live_armability.assert_awaited_once()
    mock_drone_communicator.process_command.assert_not_called()


def test_node_restart_invalidates_uncommitted_launch_token(
    test_client,
    api_server,
    mock_drone_communicator,
):
    command = _command()
    token = _prepare(test_client, api_server, command).json()["preparation_token"]
    api_server._launch_preparation_store = LaunchPreparationStore(
        ttl_sec=calculate_launch_preparation_token_ttl_sec(params=api_server.params),
    )

    response = test_client.post(
        "/api/v1/drone/commands",
        json=command,
        headers={LAUNCH_PREPARATION_TOKEN_HEADER: token},
    )

    assert response.json()["status"] == "rejected"
    assert "unknown to this node process" in response.json()["error_detail"]
    mock_drone_communicator.process_command.assert_not_called()


def test_blocked_readiness_never_issues_token(
    test_client,
    api_server,
    mock_drone_communicator,
):
    response = _prepare(test_client, api_server, _command(), ready=False)

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["preparation_token"] is None
    assert response.json()["token_ttl_ms"] == 0
    mock_drone_communicator.process_command.assert_not_called()


def test_recovery_command_remains_available_without_launch_token(
    test_client,
    mock_drone_communicator,
):
    response = test_client.post(
        "/api/v1/drone/commands",
        json={"mission_type": Mission.LAND.value, "trigger_time": 0},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    mock_drone_communicator.process_command.assert_called_once()


def test_non_launch_command_rejects_stray_launch_authority(
    test_client,
    mock_drone_communicator,
):
    response = test_client.post(
        "/api/v1/drone/commands",
        json={"mission_type": Mission.LAND.value, "trigger_time": 0},
        headers={LAUNCH_PREPARATION_TOKEN_HEADER: "x" * 43},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    mock_drone_communicator.process_command.assert_not_called()


@pytest.mark.asyncio
async def test_slow_launch_revalidation_does_not_hold_recovery_transaction_lock(
    api_server,
):
    command = _command(command_id="slow-revalidation")
    api_server._probe_live_armability = AsyncMock(return_value=_probe(ready=True))
    transport = httpx.ASGITransport(app=api_server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://node") as client:
        prepared = await client.post(
            "/api/v1/preflight/launch-preparations",
            json={"schema_version": 1, "command": command},
        )
        token = prepared.json()["preparation_token"]

        probe_started = asyncio.Event()
        release_probe = asyncio.Event()

        async def blocked_probe(*, require_global_position=True):
            probe_started.set()
            await release_probe.wait()
            return _probe(ready=True)

        api_server._probe_live_armability = blocked_probe
        launch_task = asyncio.create_task(
            client.post(
                "/api/v1/drone/commands",
                json=command,
                headers={LAUNCH_PREPARATION_TOKEN_HEADER: token},
            )
        )
        await asyncio.wait_for(probe_started.wait(), timeout=0.5)

        recovery = await asyncio.wait_for(
            client.post(
                "/api/v1/drone/commands",
                json={"mission_type": Mission.LAND.value, "trigger_time": 0},
            ),
            timeout=0.25,
        )
        assert recovery.json()["status"] == "accepted"
        assert launch_task.done() is False

        release_probe.set()
        await launch_task

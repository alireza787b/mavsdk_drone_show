import asyncio
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from src.enums import Mission
from src.launch_preparation_protocol import (
    LAUNCH_PREPARATION_TOKEN_HEADER,
    LaunchPreparationBinding,
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


def _probe(
    *,
    ready=True,
    require_global_position=True,
    hw_id="1",
    validity_ms=2_000,
    remaining_valid_ms=None,
):
    now_ms = int(time.time() * 1_000)
    blockers = [] if ready else ["PX4 armability"]
    remaining_valid_ms = (
        validity_ms if remaining_valid_ms is None else remaining_valid_ms
    )
    return {
        "hw_id": hw_id,
        "success": True,
        "ready": ready,
        "summary": "ready for mission startup" if ready else "waiting for PX4 armability",
        "observation": {
            "schema_version": 1,
            "observation_id": f"http-probe-{now_ms}",
            "source": "test.health+battery",
            "observed_at_ms": now_ms,
            "valid_until_ms": now_ms + validity_ms if ready else 0,
            "require_global_position": require_global_position,
            "ready": ready,
            "blockers": blockers,
            "checks": {"armable": ready},
            "battery": {"remaining_percent": 80.0},
        },
        "remaining_valid_ms": remaining_valid_ms if ready else 0,
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
        "require_global_position": require_global_position,
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
    # The commit reused the preparation observation only inside its short
    # node-local readiness lease. The exact retry then used authoritative
    # command history without probing or mutating again.
    assert api_server._probe_live_armability.await_count == 1
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


def test_commit_revalidates_when_preparation_readiness_lease_is_unavailable(
    test_client,
    api_server,
    mock_drone_communicator,
):
    command = _command(command_id="ready-then-blocked")
    token, _ = api_server._launch_preparation_store.issue(
        LaunchPreparationBinding.from_command(command)
    )
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


def test_relaxed_preparation_cannot_bypass_strict_commit_readiness(
    test_client,
    api_server,
    mock_drone_communicator,
):
    command = _command(command_id="relaxed-prepare-strict-commit")
    api_server._probe_live_armability = AsyncMock(
        return_value=_probe(ready=True, require_global_position=False)
    )
    prepared = test_client.post(
        "/api/v1/preflight/launch-preparations",
        json={
            "schema_version": 1,
            "command": command,
            "require_global_position": False,
        },
    )
    assert prepared.status_code == 200
    token = prepared.json()["preparation_token"]

    api_server._probe_live_armability = AsyncMock(return_value=_probe(ready=False))
    committed = test_client.post(
        "/api/v1/drone/commands",
        json=command,
        headers={LAUNCH_PREPARATION_TOKEN_HEADER: token},
    )

    assert committed.json()["status"] == "rejected"
    assert committed.json()["error_code"] == "E401"
    assert "PX4 armability" in committed.json()["error_detail"]
    api_server._probe_live_armability.assert_awaited_once_with(
        require_global_position=True
    )
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


def test_preparation_rejects_readiness_from_different_hardware_identity(
    test_client,
    api_server,
    mock_drone_communicator,
):
    command = _command(command_id="wrong-probe-identity")
    api_server._probe_live_armability = AsyncMock(
        return_value=_probe(ready=True, hw_id="2")
    )

    response = test_client.post(
        "/api/v1/preflight/launch-preparations",
        json={"schema_version": 1, "command": command},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["error_code"] == "E108"
    assert response.json()["preparation_token"] is None
    mock_drone_communicator.process_command.assert_not_called()


def test_preparation_caps_reusable_readiness_to_safety_evidence_window(
    test_client,
    api_server,
):
    command = _command(command_id="bounded-readiness-lease")
    api_server._probe_live_armability = AsyncMock(
        return_value=_probe(
            ready=True,
            validity_ms=90_000,
            remaining_valid_ms=90_000,
        )
    )

    prepared = test_client.post(
        "/api/v1/preflight/launch-preparations",
        json={"schema_version": 1, "command": command},
    )
    token = prepared.json()["preparation_token"]
    consumed = api_server._launch_preparation_store.consume(token, command)

    assert consumed.consumed is True
    assert consumed.readiness_valid_until_monotonic is not None
    remaining = consumed.readiness_valid_until_monotonic - time.monotonic()
    assert 0 < remaining <= 2.0


@pytest.mark.asyncio
async def test_prepared_readiness_expiring_behind_scheduler_lock_is_rejected(
    api_server,
    mock_drone_communicator,
):
    command = _command(command_id="lease-expires-behind-lock")
    api_server._probe_live_armability = AsyncMock(
        return_value=_probe(ready=True, validity_ms=100, remaining_valid_ms=100)
    )
    transport = httpx.ASGITransport(app=api_server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://node") as client:
        prepared = await client.post(
            "/api/v1/preflight/launch-preparations",
            json={"schema_version": 1, "command": command},
        )
        token = prepared.json()["preparation_token"]

        shared_lock = api_server._command_state_transaction_lock
        assert shared_lock.acquire(blocking=False)
        try:
            launch_task = asyncio.create_task(
                client.post(
                    "/api/v1/drone/commands",
                    json=command,
                    headers={LAUNCH_PREPARATION_TOKEN_HEADER: token},
                )
            )
            for _ in range(100):
                if api_server._command_transaction_lock.locked():
                    break
                await asyncio.sleep(0.005)
            assert api_server._command_transaction_lock.locked()
            await asyncio.sleep(0.15)
        finally:
            shared_lock.release()

        response = await asyncio.wait_for(launch_task, timeout=1.0)

    assert response.json()["status"] == "rejected"
    assert response.json()["message"] == (
        "Commit-time launch readiness expired before command installation"
    )
    assert api_server._probe_live_armability.await_count == 1
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
        token, _ = api_server._launch_preparation_store.issue(
            LaunchPreparationBinding.from_command(command)
        )

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

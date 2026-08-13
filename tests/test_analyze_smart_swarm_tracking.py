import asyncio
import copy
import time

import pytest

from tools.analyze_smart_swarm_tracking import (
    FieldRehearsalClient,
    build_precision_move_payload,
    build_staging_move,
    build_temporary_swarm_resource,
    build_two_drone_ned_assignments,
    canonical_assignment,
    compute_tracking_sample,
    fresh_stream_state,
    land_armed_targets_and_wait_idle,
    restore_swarm_resource,
    wait_for_advancing_fresh_streams,
)


def test_two_drone_assignments_are_exact_h1_h2_ned_topology():
    assignments = build_two_drone_ned_assignments(1, 2, 6.0)

    assert assignments == {
        1: {
            "follow": 0,
            "offset_x": 0.0,
            "offset_y": 0.0,
            "offset_z": 0.0,
            "frame": "ned",
        },
        2: {
            "follow": 1,
            "offset_x": 6.0,
            "offset_y": 0.0,
            "offset_z": 0.0,
            "frame": "ned",
        },
    }


def test_temporary_swarm_resource_preserves_full_resource_and_input():
    original = {
        "version": 1,
        "assignments": [
            {"hw_id": 1, "follow": 3, "offset_x": 9.0, "frame": "body"},
            {"hw_id": 3, "follow": 0, "offset_x": 0.0, "frame": "ned"},
        ],
    }
    snapshot = copy.deepcopy(original)

    temporary = build_temporary_swarm_resource(
        original,
        build_two_drone_ned_assignments(1, 2, 6.0),
    )

    assert original == snapshot
    assert temporary["version"] == 1
    assert [entry["hw_id"] for entry in temporary["assignments"]] == [1, 3, 2]
    assert temporary["assignments"][0] == {
        "hw_id": 1,
        "follow": 0,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "offset_z": 0.0,
        "frame": "ned",
    }
    assert temporary["assignments"][1] == original["assignments"][1]
    assert temporary["assignments"][2]["offset_x"] == 6.0


def test_canonical_assignment_fills_only_runtime_defaults():
    assert canonical_assignment({"follow": 1, "offset_x": 6.0, "frame": "ned"}) == {
        "follow": 1,
        "offset_x": 6.0,
        "offset_y": 0.0,
        "offset_z": 0.0,
        "frame": "ned",
    }


def test_build_precision_move_payload_supports_ned_and_body_frames():
    ned_payload = build_precision_move_payload("ned", north=4.0, east=2.0)
    body_payload = build_precision_move_payload("body", forward=3.0, right=1.0)

    assert ned_payload["precision_move"]["translation_m"] == {
        "north": 4.0,
        "east": 2.0,
        "up": 0.0,
    }
    assert body_payload["precision_move"]["translation_m"] == {
        "forward": 3.0,
        "right": 1.0,
        "up": 0.0,
    }


def test_staging_move_uses_live_geometry_to_enter_capture():
    leader = {"position_lat": 35.0, "position_long": 51.0, "position_alt": 100.0}
    follower = {"position_lat": 35.0, "position_long": 51.0, "position_alt": 100.4}
    assignment = {"follow": 1, "offset_x": 6.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"}

    geometry, payload = build_staging_move(
        leader,
        follower,
        assignment,
        max_horizontal_m=10.0,
        max_vertical_m=1.0,
    )

    assert geometry["actual_n"] == pytest.approx(0.0)
    assert payload["precision_move"]["translation_m"] == pytest.approx(
        {"north": 6.0, "east": 0.0, "up": -0.4}
    )


def test_staging_move_refuses_large_unreviewed_translation():
    leader = {"position_lat": 35.0, "position_long": 51.0, "position_alt": 100.0}
    follower = {"position_lat": 35.0, "position_long": 51.0, "position_alt": 100.0}
    assignment = {"follow": 1, "offset_x": 20.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"}

    with pytest.raises(RuntimeError, match="Refusing unsafe follower staging move"):
        build_staging_move(
            leader,
            follower,
            assignment,
            max_horizontal_m=15.0,
            max_vertical_m=2.0,
        )


def test_field_client_puts_swarm_with_commit_false():
    class RecordingClient(FieldRehearsalClient):
        def __init__(self):
            self.calls = []

        def require_sitl_runtime(self):
            return {"mode": "sitl"}

        def put_json(self, path, payload, *, timeout_sec=None):
            self.calls.append((path, payload))
            return {"status": "success"}

    client = RecordingClient()
    resource = {"version": 1, "assignments": []}

    client.put_swarm_resource(resource)

    assert client.calls == [("/api/v1/config/swarm?commit=false", resource)]


def test_restore_swarm_resource_restores_full_shape_without_commit():
    original = {
        "version": 1,
        "assignments": [
            {"hw_id": 1, "follow": 0, "offset_x": 0.0, "frame": "ned"},
            {"hw_id": 3, "follow": 1, "offset_x": -8.5, "frame": "body"},
        ],
    }

    class FakeClient:
        def __init__(self):
            self.current = None
            self.calls = []

        def put_swarm_resource(self, payload):
            self.calls.append(payload)
            self.current = payload
            return {"status": "success"}

        def get_swarm_resource(self):
            return self.current

    client = FakeClient()

    assert restore_swarm_resource(client, original, timeout=1) == [1, 3]
    assert client.calls == [original]
    assert "offset_z" not in client.current["assignments"][1]


def test_fresh_stream_state_rejects_empty_stale_and_invalid_samples():
    now_ms = int(time.time() * 1000)
    base = {
        "stream_seq": 9,
        "emitted_at_ms": now_ms - 10,
        "global_position_valid": True,
        "position_lat": 35.0,
        "position_long": 51.0,
        "position_alt": 100.0,
    }

    assert fresh_stream_state(base, now_ms=now_ms, max_age_ms=1000) == (True, "fresh")
    assert fresh_stream_state({}, now_ms=now_ms, max_age_ms=1000)[0] is False
    stale = {**base, "emitted_at_ms": now_ms - 2000}
    assert fresh_stream_state(stale, now_ms=now_ms, max_age_ms=1000)[0] is False
    invalid = {**base, "global_position_valid": False}
    assert fresh_stream_state(invalid, now_ms=now_ms, max_age_ms=1000)[0] is False


@pytest.mark.asyncio
async def test_advancing_stream_gate_requires_both_independent_sequences():
    latest = {}
    stop = asyncio.Event()

    async def producer(key):
        for seq in range(1, 5):
            now_ms = int(time.time() * 1000)
            latest[key] = {
                "stream_seq": seq,
                "emitted_at_ms": now_ms,
                "sample_age_ms": 0,
                "global_position_valid": True,
                "position_lat": 35.0,
                "position_long": 51.0,
                "position_alt": 100.0,
            }
            await asyncio.sleep(0.03)
        await stop.wait()

    tasks = {
        "leader": asyncio.create_task(producer("leader")),
        "follower": asyncio.create_task(producer("follower")),
    }
    evidence = await wait_for_advancing_fresh_streams(
        latest,
        tasks,
        ["leader", "follower"],
        min_advances=2,
        max_age_ms=500,
        timeout_sec=1,
    )
    stop.set()
    await asyncio.gather(*tasks.values())

    assert evidence["leader"]["advances"] >= 2
    assert evidence["follower"]["advances"] >= 2


def test_safety_cleanup_lands_only_armed_targets_then_waits_idle():
    class FakeClient:
        def __init__(self):
            self.submissions = []
            self.sitl_checks = 0

        def require_sitl_runtime(self):
            self.sitl_checks += 1
            return {"mode": "sitl"}

        def get_telemetry(self):
            return {"1": {"is_armed": True}, "2": {"is_armed": False}}

        def submit_command(self, mission, ids, label):
            self.submissions.append((mission, ids, label))
            return {"command_id": "land-1"}

    client = FakeClient()
    order = []

    def wait_command(_client, command_id, *, terminal, timeout):
        order.append(("command", command_id, terminal, timeout))
        return {
            "status": "completed",
            "acks": {"accepted": 1},
            "executions": {"succeeded": 1},
        }

    def wait_idle(_client, ids, timeout):
        order.append(("idle", ids, timeout))
        return {"1": {"is_armed": False}, "2": {"is_armed": False}}

    result = land_armed_targets_and_wait_idle(
        client,
        [1, 2],
        wait_for_command=wait_command,
        wait_idle_reset=wait_idle,
        require_full_acceptance=lambda status, expected, label: None,
        require_full_execution=lambda status, expected, label: None,
        timeout=30,
    )

    assert client.submissions[0][1] == [1]
    assert client.sitl_checks == 1
    assert order[0][0] == "command"
    assert order[1][0] == "idle"
    assert result["grounded_verified"] is True


def test_compute_tracking_sample_reports_zero_error_at_ned_offset():
    leader = {
        "position_lat": 35.0,
        "position_long": 51.0,
        "position_alt": 1200.0,
        "yaw": 0.0,
        "yaw_deg": 0.0,
        "stream_seq": 10,
        "sample_age_ms": 15,
    }
    follower = {
        "position_lat": 35.0000539,
        "position_long": 51.0,
        "position_alt": 1200.0,
        "stream_seq": 22,
        "sample_age_ms": 20,
    }
    assignment = {
        "hw_id": 2,
        "follow": 1,
        "offset_x": 6.0,
        "offset_y": 0.0,
        "offset_z": 0.0,
        "frame": "ned",
    }

    sample = compute_tracking_sample(
        "steady",
        leader,
        follower,
        assignment,
        sample_time_s=10.0,
        reference_origin={"lat": 35.0, "lon": 51.0, "alt": 1200.0},
    )

    assert sample.stage == "steady"
    assert sample.horizontal_error < 0.1
    assert sample.altitude_error == 0.0
    assert sample.leader_world_n == 0.0

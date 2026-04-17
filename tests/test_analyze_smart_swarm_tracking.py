from tools.analyze_smart_swarm_tracking import (
    build_demo_swarm_assignments,
    build_live_jog_sequence,
    build_precision_move_payload,
    compute_tracking_sample,
)


def test_build_demo_swarm_assignments_creates_single_leader_body_followers():
    assignments = build_demo_swarm_assignments([1, 2, 3, 4], spacing_m=6.0)

    assert assignments[1]["follow"] == 0
    assert assignments[2] == {
        "follow": 1,
        "offset_x": 0.0,
        "offset_y": 6.0,
        "offset_z": 0.0,
        "frame": "body",
    }
    assert assignments[3]["follow"] == 1
    assert assignments[4]["follow"] == 1


def test_build_precision_move_payload_supports_ned_and_body_frames():
    ned_payload = build_precision_move_payload("ned", north=4.0, east=2.0)
    body_payload = build_precision_move_payload("body", forward=3.0, right=1.0)

    assert ned_payload["precision_move"]["translation_m"] == {"north": 4.0, "east": 2.0, "up": 0.0}
    assert body_payload["precision_move"]["translation_m"] == {"forward": 3.0, "right": 1.0, "up": 0.0}


def test_build_live_jog_sequence_uses_small_precision_move_steps():
    sequence = build_live_jog_sequence(1.0)

    assert [stage for stage, _payload in sequence] == [
        "jog_body_forward_1",
        "jog_body_forward_2",
        "jog_body_right_1",
        "jog_ned_north_1",
        "jog_ned_east_1",
    ]
    assert sequence[0][1]["precision_move"]["frame"] == "body"
    assert sequence[-1][1]["precision_move"]["translation_m"] == {"north": 0.0, "east": 1.0, "up": 0.0}


def test_compute_tracking_sample_reports_zero_error_when_follower_matches_body_offset():
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
        "position_lat": 35.0,
        "position_long": 51.000054,
        "position_alt": 1200.0,
        "stream_seq": 22,
        "sample_age_ms": 20,
    }
    assignment = {"hw_id": 2, "follow": 1, "offset_x": 0.0, "offset_y": 4.92, "offset_z": 0.0, "frame": "body"}

    sample = compute_tracking_sample(
        "steady",
        leader,
        follower,
        assignment,
        sample_time_s=10.0,
        reference_origin={"lat": 35.0, "lon": 51.0, "alt": 1200.0},
    )

    assert sample.stage == "steady"
    assert sample.horizontal_error < 0.3
    assert sample.altitude_error == 0.0
    assert sample.leader_world_n == 0.0

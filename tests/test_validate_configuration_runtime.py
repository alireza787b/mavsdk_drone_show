from tools.validate_configuration_runtime import (
    build_collision_validation_payload,
    build_fleet_metadata_update,
    build_swarm_patch_update,
    build_swarm_put_update,
    select_origin_compute_source,
    select_swarm_target,
)


def test_build_collision_validation_payload_duplicates_second_selected_pos_id():
    entries = [
        {"hw_id": 1, "pos_id": 1},
        {"hw_id": 2, "pos_id": 2},
        {"hw_id": 3, "pos_id": 3},
    ]

    payload = build_collision_validation_payload(entries, [1, 2, 3])

    assert payload is not None
    assert payload[0]["pos_id"] == 1
    assert payload[1]["pos_id"] == 1
    assert entries[1]["pos_id"] == 2


def test_build_fleet_metadata_update_preserves_original_and_tracks_expected_fields():
    entries = [
        {"hw_id": 1, "pos_id": 1, "callsign": "SITL-01"},
        {"hw_id": 2, "pos_id": 2},
    ]

    payload, expected = build_fleet_metadata_update(entries, [1, 2], suffix="-CFG")

    assert payload[0]["callsign"] == "SITL-01-CFG"
    assert payload[0]["notes"] == "sitl-config-validator:1"
    assert payload[0]["maintenance_tag"] == "sitl-1-config"
    assert payload[1]["callsign"] == "SITL-02-CFG"
    assert expected[2]["maintenance_tag"] == "sitl-2-config"
    assert "notes" not in entries[0]


def test_select_swarm_target_prefers_followers_in_selected_set():
    assignments = {
        1: {"hw_id": 1, "follow": 0},
        2: {"hw_id": 2, "follow": 1},
        3: {"hw_id": 3, "follow": 1},
    }

    assert select_swarm_target(assignments, [1, 2, 3]) == 2
    assert select_swarm_target(assignments, [1]) == 1


def test_swarm_put_and_patch_updates_return_expected_assignment_shapes():
    payload = {
        "version": 1,
        "assignments": [
            {"hw_id": 1, "follow": 0, "offset_x": 0.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "body"},
            {"hw_id": 2, "follow": 1, "offset_x": 5.0, "offset_y": 50.0, "offset_z": 5.0, "frame": "ned"},
        ],
    }

    updated_payload, expected_put = build_swarm_put_update(payload, target_hw_id=2, offset_delta=1.25)
    assert expected_put["offset_x"] == 6.25
    assert expected_put["offset_z"] == 5.25
    assert payload["assignments"][1]["offset_x"] == 5.0

    patch_payload, expected_patch = build_swarm_patch_update(expected_put, patch_delta=2.0)
    assert patch_payload == {"offset_y": 52.0, "offset_z": 5.25}
    assert expected_patch["offset_y"] == 52.0


def test_select_origin_compute_source_uses_selected_fleet_and_live_telemetry():
    fleet_entries = [
        {"hw_id": 1, "pos_id": 11},
        {"hw_id": 2, "pos_id": 22},
    ]
    telemetry = {
        "2": {"position_lat": 35.1, "position_long": 51.2},
    }

    source = select_origin_compute_source(selected_ids=[1, 2], fleet_entries=fleet_entries, telemetry=telemetry)

    assert source == {
        "hw_id": 2,
        "pos_id": 22,
        "current_lat": 35.1,
        "current_lon": 51.2,
    }

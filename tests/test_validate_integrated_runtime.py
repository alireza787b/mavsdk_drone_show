import argparse

from tools.validate_integrated_runtime import (
    build_demo_swarm_assignments,
    build_reassignment_patch,
    resolve_selected_ids,
)


def test_build_demo_swarm_assignments_uses_first_drone_as_leader():
    assignments = build_demo_swarm_assignments([1, 2, 3], spacing_m=8.0)

    assert assignments[1] == {
        "follow": 0,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "offset_z": 0.0,
        "frame": "body",
    }
    assert assignments[2]["follow"] == 1
    assert assignments[3]["follow"] == 1


def test_build_demo_swarm_assignments_spreads_followers_across_unique_offsets():
    assignments = build_demo_swarm_assignments([1, 2, 3, 4], spacing_m=8.0)
    follower_offsets = {
        (entry["offset_x"], entry["offset_y"])
        for hw_id, entry in assignments.items()
        if hw_id != 1
    }

    assert len(follower_offsets) == 3
    assert (0.0, 8.0) in follower_offsets
    assert (0.0, -8.0) in follower_offsets


def test_build_reassignment_patch_targets_last_follower_with_ned_offset():
    target_hw_id, patch = build_reassignment_patch([1, 2, 3], reassign_offset_m=6.0)

    assert target_hw_id == 3
    assert patch == {
        "follow": 1,
        "offset_x": 6.0,
        "offset_y": 6.0,
        "offset_z": 0.0,
        "frame": "ned",
    }


def test_resolve_selected_ids_prefers_space_separated_drone_ids():
    args = argparse.Namespace(drone_ids=[3, 2, 2, 1], drones="9,8,7")
    assert resolve_selected_ids(args) == [1, 2, 3]


def test_resolve_selected_ids_falls_back_to_csv_argument_and_default():
    csv_args = argparse.Namespace(drone_ids=None, drones="3, 1,2")
    default_args = argparse.Namespace(drone_ids=None, drones=None)

    assert resolve_selected_ids(csv_args) == [1, 2, 3]
    assert resolve_selected_ids(default_args) == [1, 2, 3]

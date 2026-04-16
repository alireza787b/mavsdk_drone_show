from src.swarm_runtime_state import (
    build_runtime_swarm_assignment,
    read_runtime_swarm_assignment,
    write_runtime_swarm_assignment,
)


def test_runtime_swarm_assignment_round_trip(monkeypatch, tmp_path):
    path = tmp_path / "smart_swarm_assignment.json"
    monkeypatch.setenv("MDS_SWARM_RUNTIME_ASSIGNMENT_PATH", str(path))

    assignment = {
        "hw_id": 3,
        "follow": 2,
        "offset_x": 8.0,
        "offset_y": 6.0,
        "offset_z": 0.0,
        "frame": "body",
    }

    write_runtime_swarm_assignment(assignment)

    assert read_runtime_swarm_assignment() == assignment


def test_runtime_swarm_assignment_empty_payload_returns_none(monkeypatch, tmp_path):
    path = tmp_path / "smart_swarm_assignment.json"
    monkeypatch.setenv("MDS_SWARM_RUNTIME_ASSIGNMENT_PATH", str(path))

    write_runtime_swarm_assignment(None)

    assert read_runtime_swarm_assignment() is None


def test_build_runtime_swarm_assignment_canonicalizes_types():
    assignment = build_runtime_swarm_assignment(
        "3",
        {
            "follow": "2",
            "offset_x": "8.5",
            "offset_y": 6,
            "offset_z": None,
            "frame": "BODY",
        },
    )

    assert assignment == {
        "hw_id": 3,
        "follow": 2,
        "offset_x": 8.5,
        "offset_y": 6.0,
        "offset_z": 0.0,
        "frame": "body",
    }


def test_build_runtime_swarm_assignment_force_follow_overrides_source():
    assignment = build_runtime_swarm_assignment(
        3,
        {
            "follow": 1,
            "offset_x": 25.0,
            "offset_y": 0.0,
            "offset_z": 15.0,
            "frame": "body",
        },
        force_follow=0,
    )

    assert assignment["follow"] == 0
    assert assignment["offset_x"] == 25.0

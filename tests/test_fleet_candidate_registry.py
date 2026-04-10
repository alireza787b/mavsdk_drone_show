from pathlib import Path

from fleet_candidates import FleetCandidateRegistry
from schemas import (
    FleetCandidateAcceptRequest,
    FleetCandidateAnnounceRequest,
    FleetCandidateRecoverRequest,
    FleetCandidateReplaceRequest,
    FleetCandidateState,
)


def _validate_stub(config_rows, sim_mode=None):
    del sim_mode
    hw_ids = {}
    pos_ids = {}
    for row in config_rows:
        hw_ids.setdefault(int(row["hw_id"]), 0)
        hw_ids[int(row["hw_id"])] += 1
        pos_ids.setdefault(int(row["pos_id"]), 0)
        pos_ids[int(row["pos_id"])] += 1
    return {
        "updated_config": config_rows,
        "summary": {
            "duplicate_hw_ids_count": sum(1 for count in hw_ids.values() if count > 1),
            "duplicates_count": sum(1 for count in pos_ids.values() if count > 1),
            "missing_trajectories_count": 0,
            "role_swaps_count": 0,
        },
    }


def test_observe_heartbeat_creates_pending_candidate_for_unknown_hw_id(tmp_path: Path):
    registry = FleetCandidateRegistry(
        state_path=str(tmp_path / "fleet_candidates.json"),
        events_path=str(tmp_path / "fleet_candidate_events.jsonl"),
    )

    candidate = registry.observe_heartbeat(
        {
            "hw_id": "101",
            "pos_id": 0,
            "detected_pos_id": 12,
            "ip": "10.0.0.101",
            "timestamp": 1_700_000_000_000,
        },
        load_config=lambda: [{"hw_id": 12, "pos_id": 12, "ip": "10.0.0.12"}],
    )

    assert candidate is not None
    assert candidate.candidate_id == "hw-101"
    assert candidate.registration_state == FleetCandidateState.PENDING_OPERATOR_REVIEW
    assert candidate.detected_pos_id == "12"
    assert candidate.primary_control_ip == "10.0.0.101"


def test_announce_marks_conflict_when_hw_id_matches_existing_fleet_member(tmp_path: Path):
    registry = FleetCandidateRegistry(
        state_path=str(tmp_path / "fleet_candidates.json"),
        events_path=str(tmp_path / "fleet_candidate_events.jsonl"),
    )

    candidate = registry.announce_candidate(
        FleetCandidateAnnounceRequest(
            node_uuid="node-12b",
            hw_id="12",
            hostname="drone12b",
            primary_control_ip="10.0.0.112",
            branch="main-candidate",
        ),
        load_config=lambda: [{"hw_id": 12, "pos_id": 12, "ip": "10.0.0.12"}],
    )

    assert candidate.registration_state == FleetCandidateState.CONFLICT
    assert "hw_id_already_in_fleet" in candidate.conflict_reasons
    assert candidate.node_uuid == "node-12b"


def test_accept_candidate_appends_new_fleet_member(tmp_path: Path):
    registry = FleetCandidateRegistry(
        state_path=str(tmp_path / "fleet_candidates.json"),
        events_path=str(tmp_path / "fleet_candidate_events.jsonl"),
    )
    saved_config = []

    registry.observe_heartbeat(
        {"hw_id": "101", "ip": "10.0.0.101", "timestamp": 1_700_000_000_000},
        load_config=lambda: [],
    )

    def _save_config(updated):
        saved_config[:] = updated

    candidate, warnings = registry.accept_candidate(
        "hw-101",
        FleetCandidateAcceptRequest(
            pos_id=12,
            mavlink_port=14550,
            serial_port="",
            baudrate=0,
            notes="Accepted spare",
        ),
        load_config=lambda: list(saved_config),
        save_config=_save_config,
        validate_and_process_config=_validate_stub,
    )

    assert candidate.registration_state == FleetCandidateState.ACCEPTED
    assert candidate.resolution == "accepted_as_new"
    assert warnings == []
    assert saved_config == [
        {
            "hw_id": 101,
            "pos_id": 12,
            "ip": "10.0.0.101",
            "mavlink_port": 14550,
            "serial_port": "",
            "baudrate": 0,
            "notes": "Accepted spare",
        }
    ]


def test_replace_candidate_rewrites_config_and_swarm_follow_references(tmp_path: Path):
    registry = FleetCandidateRegistry(
        state_path=str(tmp_path / "fleet_candidates.json"),
        events_path=str(tmp_path / "fleet_candidate_events.jsonl"),
    )

    config_rows = [
        {"hw_id": 12, "pos_id": 12, "ip": "10.0.0.12", "mavlink_port": 14550, "serial_port": "", "baudrate": 0},
        {"hw_id": 20, "pos_id": 20, "ip": "10.0.0.20", "mavlink_port": 14550, "serial_port": "", "baudrate": 0},
    ]
    swarm_rows = [
        {"hw_id": 12, "follow": 0, "offset_x": 0.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "body"},
        {"hw_id": 20, "follow": 12, "offset_x": 3.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "body"},
    ]

    registry.observe_heartbeat(
        {"hw_id": "101", "ip": "10.0.0.101", "timestamp": 1_700_000_000_000},
        load_config=lambda: list(config_rows),
    )

    candidate, warnings = registry.replace_candidate(
        "hw-101",
        FleetCandidateReplaceRequest(target_hw_id=12, notes="Field spare swap"),
        load_config=lambda: list(config_rows),
        save_config=lambda updated: config_rows.__setitem__(slice(None), updated),
        load_swarm=lambda: list(swarm_rows),
        save_swarm=lambda updated: swarm_rows.__setitem__(slice(None), updated),
        validate_and_process_config=_validate_stub,
    )

    assert candidate.registration_state == FleetCandidateState.ACCEPTED
    assert candidate.resolution == "replaced_existing"
    assert candidate.replacement_target_hw_id == "12"
    assert candidate.replacement_target_pos_id == "12"
    assert warnings == []
    assert config_rows[0]["hw_id"] == 101
    assert config_rows[0]["pos_id"] == 12
    assert swarm_rows[0]["hw_id"] == 101
    assert swarm_rows[1]["follow"] == 101


def test_recover_candidate_updates_existing_config_for_same_hw_id(tmp_path: Path):
    registry = FleetCandidateRegistry(
        state_path=str(tmp_path / "fleet_candidates.json"),
        events_path=str(tmp_path / "fleet_candidate_events.jsonl"),
    )

    config_rows = [
        {"hw_id": 12, "pos_id": 12, "ip": "10.0.0.12", "mavlink_port": 14550, "serial_port": "", "baudrate": 0},
    ]

    registry.announce_candidate(
        FleetCandidateAnnounceRequest(
            node_uuid="node-12b",
            hw_id="12",
            hostname="drone12b",
            primary_control_ip="10.0.0.212",
        ),
        load_config=lambda: list(config_rows),
    )

    candidate, warnings = registry.recover_candidate(
        "node-12b",
        FleetCandidateRecoverRequest(
            mavlink_port=14620,
            notes="Recovered same airframe with new companion",
        ),
        load_config=lambda: list(config_rows),
        save_config=lambda updated: config_rows.__setitem__(slice(None), updated),
        validate_and_process_config=_validate_stub,
    )

    assert candidate.registration_state == FleetCandidateState.ACCEPTED
    assert candidate.resolution == "recovered_existing"
    assert candidate.replacement_target_hw_id == "12"
    assert candidate.replacement_target_pos_id == "12"
    assert warnings == []
    assert config_rows[0]["hw_id"] == 12
    assert config_rows[0]["ip"] == "10.0.0.212"
    assert config_rows[0]["mavlink_port"] == 14620
    assert config_rows[0]["notes"] == "Recovered same airframe with new companion"

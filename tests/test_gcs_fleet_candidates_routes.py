from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.fleet_candidates import create_fleet_candidates_router
from schemas import FleetCandidateRecord, FleetCandidateState


def _candidate_record(**overrides):
    payload = {
        "candidate_id": "hw-101",
        "node_uuid": None,
        "hw_id": "101",
        "hostname": "drone101",
        "reported_pos_id": None,
        "detected_pos_id": "12",
        "first_seen": 1_700_000_000_000,
        "last_seen": 1_700_000_000_100,
        "last_heartbeat": 1_700_000_000_100,
        "last_announce": None,
        "heartbeat_age_sec": 1,
        "heartbeat_status": "online",
        "ip_addresses": ["10.0.0.101"],
        "primary_control_ip": "10.0.0.101",
        "network_mode": None,
        "netbird_ip": None,
        "repo_url": None,
        "branch": None,
        "commit": None,
        "bootstrap_version": None,
        "bootstrap_status": None,
        "role_hint": None,
        "mavlink_routing_mode": None,
        "mavlink_input_type": None,
        "mavlink_input_device": None,
        "autopilot_link_state": None,
        "registration_state": FleetCandidateState.PENDING_OPERATOR_REVIEW,
        "conflict_reasons": [],
        "resolution": None,
        "replacement_target_hw_id": None,
        "replacement_target_pos_id": None,
        "notes": None,
    }
    payload.update(overrides)
    return FleetCandidateRecord.model_validate(payload)


def _make_deps():
    return SimpleNamespace(
        Params=SimpleNamespace(GIT_AUTO_PUSH=False),
        BASE_DIR="/tmp/mds",
        git_operations=lambda *args, **kwargs: {"status": "skipped"},
        list_fleet_candidates=lambda include_inactive=False: [_candidate_record()] if not include_inactive else [_candidate_record()],
        get_fleet_candidate=lambda candidate_id: _candidate_record(candidate_id=candidate_id),
        announce_fleet_candidate=lambda payload: _candidate_record(node_uuid=payload.node_uuid or "node-101"),
        accept_fleet_candidate=lambda candidate_id, payload: (
            _candidate_record(candidate_id=candidate_id, registration_state=FleetCandidateState.ACCEPTED, resolution="accepted_as_new", replacement_target_pos_id=str(payload.pos_id)),
            [],
        ),
        replace_fleet_candidate=lambda candidate_id, payload: (
            _candidate_record(candidate_id=candidate_id, registration_state=FleetCandidateState.ACCEPTED, resolution="replaced_existing", replacement_target_hw_id=str(payload.target_hw_id), replacement_target_pos_id="12"),
            [],
        ),
        recover_fleet_candidate=lambda candidate_id, payload: (
            _candidate_record(candidate_id=candidate_id, registration_state=FleetCandidateState.ACCEPTED, resolution="recovered_existing", replacement_target_hw_id="12", replacement_target_pos_id="12"),
            [],
        ),
        set_fleet_candidate_state=lambda candidate_id, state, reason=None: _candidate_record(candidate_id=candidate_id, registration_state=state, notes=reason),
        log_system_error=lambda *args, **kwargs: None,
    )


def test_fleet_candidates_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_fleet_candidates_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/fleet/candidates" in routes
    assert "/api/v1/fleet/candidates/{candidate_id}" in routes
    assert "/api/v1/fleet/candidates/announce" in routes
    assert "/api/v1/fleet/candidates/{candidate_id}/accept" in routes
    assert "/api/v1/fleet/candidates/{candidate_id}/replace" in routes
    assert "/api/v1/fleet/candidates/{candidate_id}/recover" in routes
    assert "/api/v1/fleet/candidates/{candidate_id}/reject" in routes
    assert "/api/v1/fleet/candidates/{candidate_id}/ignore" in routes


def test_fleet_candidates_router_lists_candidates():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_fleet_candidates_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/v1/fleet/candidates")

    assert response.status_code == 200
    body = response.json()
    assert body["total_candidates"] == 1
    assert body["candidates"][0]["candidate_id"] == "hw-101"
    assert body["state_counts"]["pending_operator_review"] == 1


def test_fleet_candidates_router_accepts_candidate():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_fleet_candidates_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/fleet/candidates/hw-101/accept",
            json={
                "pos_id": 12,
                "mavlink_port": 14550,
                "serial_port": "",
                "baudrate": 0,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["candidate"]["registration_state"] == "accepted"
    assert body["candidate"]["resolution"] == "accepted_as_new"
    assert body["candidate"]["replacement_target_pos_id"] == "12"


def test_fleet_candidates_router_replaces_candidate():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_fleet_candidates_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/fleet/candidates/hw-101/replace",
            json={"target_hw_id": 12},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["candidate"]["resolution"] == "replaced_existing"
    assert body["candidate"]["replacement_target_hw_id"] == "12"


def test_fleet_candidates_router_recovers_candidate():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_fleet_candidates_router(deps))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/fleet/candidates/node-12b/recover",
            json={"mavlink_port": 14620},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["candidate"]["resolution"] == "recovered_existing"
    assert body["candidate"]["replacement_target_hw_id"] == "12"

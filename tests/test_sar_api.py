"""
Tests for QuickScout SAR API endpoints.
Uses FastAPI TestClient with mocked dependencies.
"""

import os
import sys
import signal
import pytest
from unittest.mock import patch, Mock

# Safe signal handling for test threads
_original_signal = signal.signal
def _safe_signal(sig, handler):
    try:
        return _original_signal(sig, handler)
    except ValueError:
        return None
signal.signal = _safe_signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gcs-server'))

from fastapi.testclient import TestClient
from sar.schemas import SurveyState
from sar.coverage_planner import SHAPELY_AVAILABLE

# Skip all tests if shapely not installed
pytestmark = pytest.mark.skipif(not SHAPELY_AVAILABLE, reason="shapely not installed")

MOCK_CONFIG = [
    {'pos_id': 0, 'hw_id': '1', 'ip': '127.0.0.1', 'mavlink_port': 14540},
    {'pos_id': 1, 'hw_id': '2', 'ip': '127.0.0.1', 'mavlink_port': 14541},
]

MOCK_TELEMETRY = {
    '1': {
        'pos_id': 0, 'hw_id': '1', 'state': 'idle',
        'position_lat': 47.0, 'position_long': 8.0, 'position_alt': 500.0,
        'battery_voltage': 12.6, 'gps_fix_type': 3,
    },
    '2': {
        'pos_id': 1, 'hw_id': '2', 'state': 'idle',
        'position_lat': 47.001, 'position_long': 8.001, 'position_alt': 500.0,
        'battery_voltage': 12.4, 'gps_fix_type': 3,
    },
}


@pytest.fixture(autouse=True)
def mock_background_services():
    with patch('app_fastapi.BackgroundServices') as mock_svc:
        mock_instance = Mock()
        mock_instance.start = Mock()
        mock_instance.stop = Mock()
        mock_svc.return_value = mock_instance
        yield mock_svc


@pytest.fixture
def client():
    """Create TestClient with mocked telemetry and config."""
    with patch('app_fastapi.load_config', return_value=MOCK_CONFIG):
        with patch('app_fastapi.telemetry_data_all_drones', MOCK_TELEMETRY):
            from app_fastapi import app
            yield TestClient(app)


@pytest.fixture(autouse=True)
def reset_managers(tmp_path, monkeypatch):
    """Reset QuickScout singletons and isolate durable state between tests."""
    monkeypatch.setenv("MDS_QUICKSCOUT_DB_PATH", str(tmp_path / "quickscout.sqlite3"))
    import sar.mission_manager as mm
    import sar.service as svc
    import sar.store as store
    mm._manager_instance = None
    svc._service_instance = None
    store._store_instance = None
    yield
    mm._manager_instance = None
    svc._service_instance = None
    store._store_instance = None


def make_plan_request(pos_ids=None):
    """Build a valid plan request body."""
    req = {
        "search_area": {
            "type": "polygon",
            "points": [
                {"lat": 47.0, "lng": 8.0},
                {"lat": 47.002, "lng": 8.0},
                {"lat": 47.002, "lng": 8.002},
                {"lat": 47.0, "lng": 8.002},
            ],
        },
        "survey_config": {
            "sweep_width_m": 30,
            "overlap_percent": 10,
            "cruise_altitude_msl": 50,
            "survey_altitude_agl": 40,
            "cruise_speed_ms": 10,
            "survey_speed_ms": 5,
            "use_terrain_following": False,
        },
        "mission_label": "Harbor sweep",
        "mission_profile": "rapid_search",
        "mission_brief": "Search quay perimeter",
    }
    if pos_ids is not None:
        req["pos_ids"] = pos_ids
    return req


class TestPlanMission:
    def test_plan_success(self, client):
        """POST /api/sar/mission/plan with valid polygon should return plan."""
        resp = client.post("/api/sar/mission/plan", json=make_plan_request(pos_ids=[0]))
        assert resp.status_code == 200
        data = resp.json()
        assert "mission_id" in data
        assert "plans" in data
        assert len(data["plans"]) >= 1
        assert data["total_area_sq_m"] > 0
        assert data["algorithm_used"] == "boustrophedon"

    def test_plan_two_drones(self, client):
        """Planning with 2 drones should produce 2 plans."""
        resp = client.post("/api/sar/mission/plan", json=make_plan_request(pos_ids=[0, 1]))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["plans"]) == 2

    def test_plan_invalid_polygon(self, client):
        """Polygon with <3 points should fail validation."""
        req = {
            "search_area": {
                "type": "polygon",
                "points": [
                    {"lat": 47.0, "lng": 8.0},
                    {"lat": 47.001, "lng": 8.0},
                ],
            },
        }
        resp = client.post("/api/sar/mission/plan", json=req)
        assert resp.status_code == 422  # Pydantic validation error

    def test_plan_waypoints_structure(self, client):
        """Each plan should have waypoints with valid coordinates."""
        resp = client.post("/api/sar/mission/plan", json=make_plan_request(pos_ids=[0]))
        data = resp.json()
        for plan in data["plans"]:
            assert len(plan["waypoints"]) > 0
            for wp in plan["waypoints"]:
                assert -90 <= wp["lat"] <= 90
                assert -180 <= wp["lng"] <= 180
                assert wp["alt_msl"] > 0
                assert wp["speed_ms"] > 0

    def test_plan_persists_operator_metadata_for_recovery(self, client):
        resp = client.post("/api/sar/mission/plan", json=make_plan_request(pos_ids=[0]))
        mission_id = resp.json()["mission_id"]

        workspace = client.get(f"/api/sar/mission/{mission_id}/workspace")
        assert workspace.status_code == 200
        operation = workspace.json()["operation"]
        assert operation["mission_label"] == "Harbor sweep"
        assert operation["mission_profile"] == "rapid_search"
        assert operation["mission_brief"] == "Search quay perimeter"

    def test_plan_last_known_point_template(self, client):
        request = {
            "mission_template": "last_known_point",
            "search_area": {
                "type": "point",
                "center": {"lat": 47.0, "lng": 8.0},
                "radius_m": 120,
            },
            "survey_config": {
                "sweep_width_m": 30,
                "overlap_percent": 10,
                "cruise_altitude_msl": 50,
                "survey_altitude_agl": 40,
                "cruise_speed_ms": 10,
                "survey_speed_ms": 5,
                "use_terrain_following": False,
            },
            "pos_ids": [0],
        }

        resp = client.post("/api/sar/mission/plan", json=request)
        assert resp.status_code == 200
        mission_id = resp.json()["mission_id"]

        workspace = client.get(f"/api/sar/mission/{mission_id}/workspace")
        assert workspace.status_code == 200
        operation = workspace.json()["operation"]
        assert operation["mission_template"] == "last_known_point"
        assert operation["search_area"]["type"] == "point"
        assert operation["search_area"]["center"]["lat"] == 47.0
        assert operation["search_area"]["radius_m"] == 120
        assert len(operation["search_area"]["points"]) >= 6

    def test_plan_corridor_search_template(self, client):
        request = {
            "mission_template": "corridor_search",
            "search_area": {
                "type": "line",
                "path": [
                    {"lat": 47.0, "lng": 8.0},
                    {"lat": 47.001, "lng": 8.001},
                    {"lat": 47.003, "lng": 8.002},
                ],
                "corridor_width_m": 80,
            },
            "survey_config": {
                "sweep_width_m": 30,
                "overlap_percent": 10,
                "cruise_altitude_msl": 50,
                "survey_altitude_agl": 40,
                "cruise_speed_ms": 10,
                "survey_speed_ms": 5,
                "use_terrain_following": False,
            },
            "pos_ids": [0],
        }

        resp = client.post("/api/sar/mission/plan", json=request)
        assert resp.status_code == 200
        mission_id = resp.json()["mission_id"]

        workspace = client.get(f"/api/sar/mission/{mission_id}/workspace")
        assert workspace.status_code == 200
        operation = workspace.json()["operation"]
        assert operation["mission_template"] == "corridor_search"
        assert operation["search_area"]["type"] == "line"
        assert operation["search_area"]["corridor_width_m"] == 80
        assert len(operation["search_area"]["path"]) == 3
        assert operation["search_area"]["area_sq_m"] > 0

    def test_plan_corridor_search_template(self, client):
        request = {
            "mission_template": "corridor_search",
            "search_area": {
                "type": "line",
                "path": [
                    {"lat": 47.0, "lng": 8.0},
                    {"lat": 47.002, "lng": 8.002},
                    {"lat": 47.004, "lng": 8.004},
                ],
                "corridor_width_m": 90,
            },
            "survey_config": {
                "sweep_width_m": 30,
                "overlap_percent": 10,
                "cruise_altitude_msl": 50,
                "survey_altitude_agl": 40,
                "cruise_speed_ms": 10,
                "survey_speed_ms": 5,
                "use_terrain_following": False,
            },
            "pos_ids": [0],
        }

        resp = client.post("/api/sar/mission/plan", json=request)
        assert resp.status_code == 200
        mission_id = resp.json()["mission_id"]

        workspace = client.get(f"/api/sar/mission/{mission_id}/workspace")
        assert workspace.status_code == 200
        operation = workspace.json()["operation"]
        assert operation["mission_template"] == "corridor_search"
        assert operation["search_area"]["type"] == "line"
        assert len(operation["search_area"]["path"]) == 3
        assert operation["search_area"]["corridor_width_m"] == 90
        assert len(operation["search_area"]["points"]) >= 6


class TestMissionStatus:
    def test_status_after_plan(self, client):
        """GET /status should return mission state after planning."""
        plan_resp = client.post("/api/sar/mission/plan", json=make_plan_request(pos_ids=[0]))
        mission_id = plan_resp.json()["mission_id"]

        resp = client.get(f"/api/sar/mission/{mission_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mission_id"] == mission_id
        assert data["state"] == SurveyState.READY.value
        assert data["operation_phase"] == "ready_to_launch"
        assert data["control_availability"]["pause_enabled"] is False

    def test_status_not_found(self, client):
        """GET /status for unknown mission should return 404."""
        resp = client.get("/api/sar/mission/nonexistent/status")
        assert resp.status_code == 404
        payload = resp.json()
        assert payload["error"] == "Not found"
        assert payload["detail"] == "Mission nonexistent not found"


class TestMissionLifecycle:
    def _plan_and_get_id(self, client):
        resp = client.post("/api/sar/mission/plan", json=make_plan_request(pos_ids=[0]))
        return resp.json()["mission_id"]

    def test_pause_mission(self, client):
        """POST /pause should succeed for existing mission."""
        mid = self._plan_and_get_id(client)
        # Start mission first (via manager directly since launch needs real drones)
        from sar.mission_manager import get_mission_manager
        get_mission_manager().start_mission(mid)

        resp = client.post(f"/api/sar/mission/{mid}/pause")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["effect"] in {"command_accepted", "command_rejected"}
        assert isinstance(payload["state_changed"], bool)

    def test_resume_mission(self, client):
        """POST /resume should return replan guidance for paused mission."""
        mid = self._plan_and_get_id(client)
        mgr = __import__('sar.mission_manager', fromlist=['get_mission_manager']).get_mission_manager()
        mgr.start_mission(mid)
        mgr.pause_mission(mid)

        resp = client.post(f"/api/sar/mission/{mid}/resume")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["success"] is False
        assert payload["effect"] == "replan_required"
        assert payload["state_changed"] is False
        assert "follow-up package" in payload["operator_guidance"].lower()
        status = client.get(f"/api/sar/mission/{mid}/status").json()
        assert status["state"] == SurveyState.PAUSED.value
        assert status["operation_phase"] == "holding"

    def test_abort_mission(self, client):
        """POST /abort should succeed for existing mission."""
        mid = self._plan_and_get_id(client)
        resp = client.post(f"/api/sar/mission/{mid}/abort")
        assert resp.status_code == 200
        data = resp.json()
        assert data["return_behavior"] == "return_home"
        assert data["effect"] in {"command_accepted", "command_rejected"}

    def test_pause_not_found(self, client):
        """POST /pause for unknown mission should return 404."""
        resp = client.post("/api/sar/mission/nonexistent/pause")
        assert resp.status_code == 404
        payload = resp.json()
        assert payload["error"] == "Not found"
        assert payload["detail"] == "Mission nonexistent not found"

    def test_progress_report(self, client):
        """POST /progress should update drone state."""
        mid = self._plan_and_get_id(client)

        report = {
            "hw_id": "1",
            "current_waypoint_index": 5,
            "total_waypoints": 20,
            "distance_covered_m": 150.0,
        }
        resp = client.post(f"/api/sar/mission/{mid}/progress", json=report)
        assert resp.status_code == 200

        # Check status reflects progress
        status = client.get(f"/api/sar/mission/{mid}/status").json()
        drone_state = status["drone_states"].get("1")
        if drone_state:
            assert drone_state["pos_id"] == 0
            assert drone_state["current_waypoint_index"] == 5
            assert drone_state["coverage_percent"] == 25.0
            assert drone_state["status_note"] == "Executing assigned search track"


class TestFindingEndpoints:
    def _plan_and_get_id(self, client):
        resp = client.post("/api/sar/mission/plan", json=make_plan_request(pos_ids=[0]))
        assert resp.status_code == 200
        return resp.json()["mission_id"]

    def test_create_and_list_findings(self, client):
        """POST /findings + GET /findings lifecycle."""
        mission_id = self._plan_and_get_id(client)
        finding_data = {
            "lat": 47.001, "lng": 8.001,
            "type": "person", "priority": "high",
            "summary": "Possible survivor",
            "notes": "Test finding",
        }
        resp = client.post("/api/sar/findings", json=finding_data, params={"mission_id": mission_id})
        assert resp.status_code == 200
        finding = resp.json()
        assert finding["lat"] == 47.001
        assert finding["type"] == "person"
        assert finding["summary"] == "Possible survivor"
        assert finding["id"] is not None

        resp = client.get("/api/sar/findings", params={"mission_id": mission_id})
        assert resp.status_code == 200
        findings = resp.json()
        assert len(findings) == 1
        assert findings[0]["id"] == finding["id"]

    def test_update_finding(self, client):
        """PATCH /findings/{id} should update fields."""
        mission_id = self._plan_and_get_id(client)
        finding_data = {"lat": 47.0, "lng": 8.0}
        resp = client.post("/api/sar/findings", json=finding_data, params={"mission_id": mission_id})
        finding_id = resp.json()["id"]

        resp = client.patch(f"/api/sar/findings/{finding_id}", json={"notes": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["notes"] == "Updated"

    def test_update_finding_rejects_unknown_fields(self, client):
        mission_id = self._plan_and_get_id(client)
        finding_data = {"lat": 47.0, "lng": 8.0}
        resp = client.post("/api/sar/findings", json=finding_data, params={"mission_id": mission_id})
        finding_id = resp.json()["id"]

        resp = client.patch(f"/api/sar/findings/{finding_id}", json={"unknown_field": "x"})
        assert resp.status_code == 422

    def test_delete_finding(self, client):
        """DELETE /findings/{id} should remove a finding."""
        mission_id = self._plan_and_get_id(client)
        finding_data = {"lat": 47.0, "lng": 8.0}
        resp = client.post("/api/sar/findings", json=finding_data, params={"mission_id": mission_id})
        finding_id = resp.json()["id"]

        resp = client.delete(f"/api/sar/findings/{finding_id}")
        assert resp.status_code == 200

        # Verify it's gone
        resp = client.get("/api/sar/findings", params={"mission_id": mission_id})
        assert len(resp.json()) == 0

    def test_delete_finding_not_found(self, client):
        """DELETE /findings/{id} for unknown finding should return 404."""
        resp = client.delete("/api/sar/findings/nonexistent")
        assert resp.status_code == 404

    def test_list_findings_empty(self, client):
        """GET /findings for mission with no findings should return empty list."""
        resp = client.get("/api/sar/findings", params={"mission_id": "empty-mission"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_mission_handoff(self, client):
        mission_id = self._plan_and_get_id(client)

        first = client.post(
            "/api/sar/findings",
            json={
                "lat": 47.001,
                "lng": 8.001,
                "summary": "Possible survivor",
                "type": "person",
                "priority": "critical",
                "evidence_refs": ["img://capture-1"],
            },
            params={"mission_id": mission_id},
        )
        assert first.status_code == 200
        first_id = first.json()["id"]

        second = client.post(
            "/api/sar/findings",
            json={
                "lat": 47.002,
                "lng": 8.002,
                "summary": "Floating debris",
                "type": "clue",
                "priority": "medium",
                "status": "under_review",
                "evidence_refs": ["img://capture-2", "radio://report-1"],
            },
            params={"mission_id": mission_id},
        )
        assert second.status_code == 200

        updated = client.patch(
            f"/api/sar/findings/{first_id}",
            json={"status": "confirmed", "notes": "Thermal plus visual correlation"},
        )
        assert updated.status_code == 200

        handoff = client.get(f"/api/sar/mission/{mission_id}/handoff")
        assert handoff.status_code == 200
        payload = handoff.json()

        assert payload["mission_id"] == mission_id
        assert payload["finding_count"] == 2
        assert payload["confirmed_finding_count"] == 1
        assert payload["unresolved_finding_count"] == 1
        assert payload["evidence_ref_count"] == 3
        assert payload["findings"][0]["summary"] == "Possible survivor"
        assert "Possible survivor" in payload["brief_text"]

    def test_get_mission_handoff_not_found(self, client):
        resp = client.get("/api/sar/mission/nonexistent/handoff")
        assert resp.status_code == 404

class TestElevationBatch:
    def test_batch_elevation(self, client):
        """POST /elevation/batch should return elevations."""
        with patch('sar.routes.batch_get_elevations', return_value=[500.0, 501.0]):
            points = [{"lat": 47.0, "lng": 8.0}, {"lat": 47.001, "lng": 8.001}]
            resp = client.post("/api/sar/elevation/batch", json=points)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["elevations"]) == 2

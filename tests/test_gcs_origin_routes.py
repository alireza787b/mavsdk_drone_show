import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.origin import create_origin_router
from origin import build_desired_launch_positions_report


def _fresh_reference_telemetry(**overrides):
    telemetry = {
        "hw_id": "1",
        # Deliberately different from the configured assignment. The server
        # must resolve the trajectory slot from fleet config, not telemetry or
        # a client-supplied value.
        "pos_id": 99,
        "telemetry_available": True,
        "telemetry_error": None,
        "is_armed": False,
        "gps_fix_type": 3,
        "global_position_valid": True,
        "position_source": "global_position_int",
        "position_lat": 35.1,
        "position_long": -120.1,
        "position_alt": 488.25,
        "global_position_timestamp_ms": int(time.time() * 1000) - 100,
    }
    telemetry.update(overrides)
    return telemetry


def _make_deps():
    return SimpleNamespace(
        Params=SimpleNamespace(
            sim_mode=False,
            LOCAL_MAVLINK_STALE_TIMEOUT_SEC=15,
        ),
        load_origin=Mock(return_value={
            "lat": 35.0,
            "lon": -120.0,
            "alt": 12.0,
            "alt_source": "manual",
            "timestamp": "2026-04-03T00:00:00",
        }),
        save_origin=Mock(),
        get_elevation=Mock(return_value={"elevation": 24.5, "source": "backend"}),
        load_config=Mock(return_value=[{"hw_id": "1", "pos_id": 1}]),
        telemetry_data_all_drones={"1": _fresh_reference_telemetry()},
        telemetry_lock=threading.Lock(),
        get_expected_position_from_trajectory=Mock(return_value=(10.0, 0.0)),
        compute_origin_from_drone=Mock(return_value=(35.001, -120.002)),
        build_position_deviation_report=Mock(return_value={
            "status": "success",
            "origin": {"lat": 35.0, "lon": -120.0, "alt": 12.0},
            "deviations": {},
            "summary": {
                "total_drones": 1,
                "online": 0,
                "within_threshold": 0,
                "warnings": 0,
                "errors": 0,
                "no_telemetry": 1,
                "best_deviation": 0,
                "worst_deviation": 0,
                "average_deviation": 0,
            },
        }),
        build_desired_launch_positions_report=Mock(return_value={
            "origin": {"lat": 35.0, "lon": -120.0, "alt": 12.0},
            "positions": [{
                "pos_id": 1,
                "hw_id": "1",
                "latitude": 35.0,
                "longitude": -120.0,
                "altitude": 12.0,
                "north": 10.0,
                "east": 0.0,
                "trajectory_north": 10.0,
                "trajectory_east": 0.0,
            }],
            "total_drones": 1,
            "heading": 0.0,
        }),
        log_system_error=lambda *args, **kwargs: None,
    )


def test_origin_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_origin_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/origin" in routes
    assert "/api/v1/navigation/global-origin" in routes
    assert "/api/v1/origin/elevation" in routes
    assert "/api/v1/origin/bootstrap" in routes
    assert "/api/v1/origin/deviations" in routes
    assert "/api/v1/origin/compute" in routes
    assert "/api/v1/origin/launch-positions" in routes
    assert "/get-origin" not in routes
    assert "/set-origin" not in routes
    assert "/get-gps-global-origin" not in routes
    assert "/elevation" not in routes
    assert "/get-origin-for-drone" not in routes
    assert "/get-position-deviations" not in routes
    assert "/compute-origin" not in routes
    assert "/get-desired-launch-positions" not in routes


def test_origin_router_uses_live_load_origin_dependency_after_router_creation():
    deps = _make_deps()
    initial_load_origin = deps.load_origin

    app = FastAPI()
    app.include_router(create_origin_router(deps))

    replacement_load_origin = Mock(return_value={
        "lat": 36.5,
        "lon": -121.5,
        "alt": 50.0,
        "alt_source": "manual",
        "timestamp": "2026-04-03T01:00:00",
    })
    deps.load_origin = replacement_load_origin

    with TestClient(app) as client:
        response = client.get("/api/v1/origin")

    assert response.status_code == 200
    initial_load_origin.assert_not_called()
    replacement_load_origin.assert_called_once()
    assert response.json()["lat"] == 36.5


def test_origin_router_compute_origin_uses_live_dependency_after_router_creation():
    deps = _make_deps()
    deps.load_config.return_value = [{"hw_id": "1", "pos_id": 7}]
    deps.get_expected_position_from_trajectory.return_value = (10.0, 5.0)
    initial_compute = deps.compute_origin_from_drone

    app = FastAPI()
    app.include_router(create_origin_router(deps))

    replacement_compute = Mock(return_value=(10.0, 20.0))
    deps.compute_origin_from_drone = replacement_compute

    with TestClient(app) as client:
        response = client.post("/api/v1/origin/compute", json={"hw_id": "1"})

    assert response.status_code == 200
    initial_compute.assert_not_called()
    replacement_compute.assert_called_once_with(35.1, -120.1, 10.0, 5.0)
    deps.get_expected_position_from_trajectory.assert_called_once_with(7, False)
    response_data = response.json()
    assert 0 <= response_data["reference"]["position_age_ms"] <= 15_000
    response_data["reference"].pop("position_age_ms")
    assert response_data == {
        "status": "success",
        "origin": {
            "lat": 10.0,
            "lon": 20.0,
            "alt": 488.25,
            "source": "drone_global_position_msl",
        },
        "reference": {
            "hw_id": "1",
            "pos_id": 7,
            "latitude": 35.1,
            "longitude": -120.1,
            "altitude_msl": 488.25,
            "position_source": "global_position_int",
            "position_timestamp_ms": deps.telemetry_data_all_drones["1"]["global_position_timestamp_ms"],
            "gps_fix_type": 3,
        },
        "intended_offset": {"north_m": 10.0, "east_m": 5.0},
    }
    deps.save_origin.assert_not_called()


def test_origin_router_compute_rejects_client_coordinates_and_slot_without_persisting():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/origin/compute", json={
            "hw_id": "1",
            "current_lat": 1.0,
            "current_lon": 2.0,
            "pos_id": 42,
        })

    assert response.status_code == 422
    deps.compute_origin_from_drone.assert_not_called()
    deps.save_origin.assert_not_called()


def test_origin_router_compute_reports_raw_3d_fix_without_global_position():
    deps = _make_deps()
    deps.telemetry_data_all_drones["1"] = _fresh_reference_telemetry(
        global_position_valid=False,
        position_source="unavailable",
        position_lat=0.0,
        position_long=0.0,
        position_alt=0.0,
        position_unavailable_reason="GPS fix present, waiting for valid PX4 global position.",
    )
    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/origin/compute", json={"hw_id": "1"})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORIGIN_REFERENCE_GLOBAL_POSITION_UNAVAILABLE"
    deps.get_expected_position_from_trajectory.assert_not_called()
    deps.compute_origin_from_drone.assert_not_called()
    deps.save_origin.assert_not_called()


def test_origin_router_compute_reports_missing_trajectory_without_persisting():
    deps = _make_deps()
    deps.get_expected_position_from_trajectory.return_value = (None, None)
    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/origin/compute", json={"hw_id": "1"})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ORIGIN_REFERENCE_TRAJECTORY_MISSING"
    deps.compute_origin_from_drone.assert_not_called()
    deps.save_origin.assert_not_called()


@pytest.mark.parametrize("altitude", ["NaN", "Infinity", "-Infinity"])
def test_origin_router_manual_write_rejects_non_finite_altitude(altitude):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        response = client.put("/api/v1/origin", json={
            "method": "manual",
            "lat": 0,
            "lon": 0,
            "alt": altitude,
        })

    assert response.status_code == 422
    deps.save_origin.assert_not_called()


def test_origin_router_rejects_non_finite_trajectory_offset_without_persisting():
    deps = _make_deps()
    deps.get_expected_position_from_trajectory.return_value = (float("nan"), 0.0)
    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/origin/compute", json={"hw_id": "1"})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORIGIN_REFERENCE_TRAJECTORY_INVALID"
    deps.compute_origin_from_drone.assert_not_called()
    deps.save_origin.assert_not_called()


def test_origin_router_rejects_non_finite_computed_candidate_without_persisting():
    deps = _make_deps()
    deps.compute_origin_from_drone.return_value = (float("inf"), -120.0)
    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        response = client.post("/api/v1/origin/compute", json={"hw_id": "1"})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ORIGIN_REFERENCE_COMPUTATION_INVALID"
    deps.save_origin.assert_not_called()


def test_origin_router_drone_reference_put_recomputes_then_persists_once():
    deps = _make_deps()
    deps.load_config.return_value = [{"hw_id": "1", "pos_id": 7}]
    deps.get_expected_position_from_trajectory.return_value = (10.0, 5.0)
    deps.compute_origin_from_drone.return_value = (35.25, -120.25)
    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        response = client.put("/api/v1/origin", json={
            "method": "drone_reference",
            "hw_id": "1",
        })

    assert response.status_code == 200
    assert response.json()["lat"] == 35.25
    assert response.json()["lon"] == -120.25
    assert response.json()["alt"] == 488.25
    assert response.json()["source"] == "drone_global_position_msl"
    deps.get_expected_position_from_trajectory.assert_called_once_with(7, False)
    deps.compute_origin_from_drone.assert_called_once_with(35.1, -120.1, 10.0, 5.0)
    deps.save_origin.assert_called_once()
    saved_origin = deps.save_origin.call_args.args[0]
    assert saved_origin["lat"] == 35.25
    assert saved_origin["lon"] == -120.25
    assert saved_origin["alt"] == 488.25
    assert saved_origin["alt_source"] == "drone_global_position_msl"
    assert saved_origin["reference_hw_id"] == "1"
    assert saved_origin["reference_pos_id"] == 7
    assert saved_origin["reference_position_timestamp_ms"] == (
        deps.telemetry_data_all_drones["1"]["global_position_timestamp_ms"]
    )
    assert saved_origin["version"] == 2


def test_origin_router_drone_reference_put_is_atomic_when_candidate_fails():
    deps = _make_deps()
    deps.get_expected_position_from_trajectory.return_value = (None, None)
    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        response = client.put("/api/v1/origin", json={
            "method": "drone_reference",
            "hw_id": "1",
        })

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ORIGIN_REFERENCE_TRAJECTORY_MISSING"
    deps.compute_origin_from_drone.assert_not_called()
    deps.save_origin.assert_not_called()


def test_origin_router_bootstrap_origin_returns_canonical_payload():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/v1/origin/bootstrap")

    assert response.status_code == 200
    data = response.json()
    assert data["lat"] == 35.0
    assert data["lon"] == -120.0
    assert data["alt"] == 12.0
    assert data["source"] == "manual"
    assert isinstance(data["timestamp"], int)


def test_origin_router_desired_launch_positions_applies_heading_rotation():
    deps = _make_deps()
    deps.build_desired_launch_positions_report = build_desired_launch_positions_report

    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/v1/origin/launch-positions?heading=90")

    assert response.status_code == 200
    data = response.json()
    assert data["heading"] == 90.0
    assert data["total_drones"] == 1
    position = data["positions"][0]
    assert position["north"] == pytest.approx(0.0, abs=1e-6)
    assert position["east"] == pytest.approx(10.0, abs=1e-6)
    assert position["trajectory_north"] == pytest.approx(10.0, abs=1e-6)
    assert position["trajectory_east"] == pytest.approx(0.0, abs=1e-6)


def test_origin_router_desired_launch_positions_supports_csv_and_kml_formats():
    deps = _make_deps()
    deps.build_desired_launch_positions_report = build_desired_launch_positions_report

    app = FastAPI()
    app.include_router(create_origin_router(deps))

    with TestClient(app) as client:
        csv_response = client.get("/api/v1/origin/launch-positions?format=csv")
        kml_response = client.get("/api/v1/origin/launch-positions?format=kml")

    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert "trajectory_north" in csv_response.text
    assert "attachment; filename=desired_launch_positions.csv" == csv_response.headers["content-disposition"]

    assert kml_response.status_code == 200
    assert "application/vnd.google-earth.kml+xml" in kml_response.headers["content-type"]
    assert "<Placemark>" in kml_response.text
    assert "attachment; filename=desired_launch_positions.kml" == kml_response.headers["content-disposition"]

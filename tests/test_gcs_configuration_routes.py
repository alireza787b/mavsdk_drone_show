from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.configuration import create_configuration_router


def _make_deps():
    return SimpleNamespace(
        BASE_DIR="/tmp/mds-test",
        Params=SimpleNamespace(sim_mode=False, GIT_AUTO_PUSH=False),
        load_config=lambda: [{"pos_id": 1, "hw_id": "1"}],
        validate_and_process_config=Mock(return_value={"updated_config": [{"pos_id": 1, "hw_id": "1"}]}),
        save_config=Mock(),
        get_all_drone_positions=lambda: [{"hw_id": "1", "pos_id": 1, "x": 0.0, "y": 0.0}],
        get_expected_position_from_trajectory=lambda pos_id, sim_mode: (1.25, -2.5),
        git_operations=Mock(return_value={"success": True}),
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def test_configuration_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_configuration_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/config/fleet" in routes
    assert "/api/v1/config/fleet/validation" in routes
    assert "/api/v1/config/fleet/trajectory-start-positions" in routes
    assert "/api/v1/config/fleet/trajectory-start-positions/{pos_id}" in routes
    assert "/get-config-data" in routes
    assert "/save-config-data" in routes
    assert "/validate-config" in routes
    assert "/get-drone-positions" in routes
    assert "/get-trajectory-first-row" in routes


def test_configuration_router_uses_live_dependency_attributes_after_router_creation():
    deps = _make_deps()
    initial_validate = deps.validate_and_process_config

    app = FastAPI()
    app.include_router(create_configuration_router(deps))

    replacement_validate = Mock(return_value={"updated_config": [{"pos_id": 9, "hw_id": "9"}]})
    deps.validate_and_process_config = replacement_validate

    with TestClient(app) as client:
        response = client.post("/api/v1/config/fleet/validation", json=[{"pos_id": 9, "hw_id": "9"}])

    assert response.status_code == 200
    initial_validate.assert_not_called()
    replacement_validate.assert_called_once()


def test_configuration_router_preserves_client_error_status_for_invalid_payload():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_configuration_router(deps))

    with TestClient(app) as client:
        response = client.put("/api/v1/config/fleet", json={"not": "a-list"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid configuration data format"


def test_configuration_router_get_drone_positions_uses_live_dependency_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_configuration_router(deps))

    deps.get_all_drone_positions = Mock(return_value=[{"hw_id": "9", "pos_id": 9, "x": 10.0, "y": 20.0}])

    with TestClient(app) as client:
        response = client.get("/api/v1/config/fleet/trajectory-start-positions")

    assert response.status_code == 200
    deps.get_all_drone_positions.assert_called_once()
    assert response.json()[0]["hw_id"] == "9"


def test_configuration_router_get_trajectory_first_row_returns_404_when_missing():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_configuration_router(deps))

    deps.get_expected_position_from_trajectory = Mock(return_value=(None, None))

    with TestClient(app) as client:
        response = client.get("/api/v1/config/fleet/trajectory-start-positions/42")

    assert response.status_code == 404
    assert response.json()["detail"] == "Trajectory file not found for pos_id=42"


def test_configuration_router_canonical_trajectory_start_position_uses_xy_fields():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_configuration_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/v1/config/fleet/trajectory-start-positions/7")

    assert response.status_code == 200
    assert response.json() == {
        "pos_id": 7,
        "x": 1.25,
        "y": -2.5,
        "source": "Drone 7.csv (first waypoint)",
    }

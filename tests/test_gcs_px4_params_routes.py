from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.px4_params import create_px4_params_router


def _make_deps():
    return SimpleNamespace(
        Params=SimpleNamespace(
            PX4_PARAMETER_DOCS_VERSION="main",
            PX4_PARAMETER_DOCS_BASE_TEMPLATE="https://docs.px4.io/{version}/en/advanced_config/parameter_reference.html",
            PX4_PARAMETER_MUTATION_REQUIRE_DISARMED=True,
            PX4_PARAMETER_DEFAULT_COMPONENT_ID=1,
            drone_api_port=7070,
            PX4_PARAMETER_HTTP_TIMEOUT_SEC=20.0,
        ),
        load_config=lambda: [
            {"hw_id": 1, "ip": "127.0.0.1"},
            {"hw_id": 2, "ip": "127.0.0.2"},
        ],
        log_system_error=lambda *args, **kwargs: None,
    )


def test_px4_params_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_px4_params_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/px4-params/policy" in routes
    assert "/api/v1/px4-params/profiles" in routes
    assert "/api/v1/px4-params/profiles/{profile_id}" in routes
    assert "/api/v1/px4-params/snapshots" in routes
    assert "/api/v1/px4-params/snapshots/{snapshot_id}" in routes
    assert "/api/v1/px4-params/snapshots/{snapshot_id}/rows" in routes
    assert "/api/v1/px4-params/diff" in routes
    assert "/api/v1/px4-params/imports/qgc" in routes
    assert "/api/v1/px4-params/imports/mds" in routes
    assert "/api/v1/px4-params/patch-jobs" in routes
    assert "/api/v1/px4-params/patch-jobs/{job_id}" in routes


def test_px4_params_router_policy_uses_runtime_params():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_px4_params_router(deps))

    deps.Params.PX4_PARAMETER_DOCS_VERSION = "v1.16"

    with TestClient(app) as client:
        response = client.get("/api/v1/px4-params/policy")

    assert response.status_code == 200
    body = response.json()
    assert body["docs"]["version"] == "v1.16"
    assert body["docs"]["base_url"] == "https://docs.px4.io/v1.16/en/advanced_config/parameter_reference.html"
    assert body["mutations"]["require_disarmed"] is True


def test_px4_params_router_profile_routes_use_repo_store(monkeypatch):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_px4_params_router(deps))

    profile_list_payload = {
        "profiles": [
            {
                "profile_id": "fleet_guard",
                "name": "Fleet Guard",
                "description": "Starter profile",
                "source": "repo",
                "recommended_scope": "fleet",
                "tags": ["starter"],
                "entry_count": 1,
                "updated_at": 5,
            }
        ],
        "total_profiles": 1,
        "timestamp": 6,
    }
    profile_payload = {
        "profile_id": "fleet_guard",
        "name": "Fleet Guard",
        "description": "Starter profile",
        "source": "repo",
        "recommended_scope": "fleet",
        "tags": ["starter"],
        "entries": [
            {
                "component_id": 1,
                "name": "GF_ACTION",
                "value_type": "int",
                "value": 3,
            }
        ],
        "updated_at": 5,
    }

    monkeypatch.setattr("api_routes.px4_params.list_repo_profiles", lambda params: profile_list_payload)
    monkeypatch.setattr(
        "api_routes.px4_params.get_repo_profile",
        lambda params, profile_id: profile_payload if profile_id == "fleet_guard" else None,
    )

    with TestClient(app) as client:
        list_response = client.get("/api/v1/px4-params/profiles")
        profile_response = client.get("/api/v1/px4-params/profiles/fleet_guard")

    assert list_response.status_code == 200
    assert list_response.json()["profiles"][0]["profile_id"] == "fleet_guard"
    assert profile_response.status_code == 200
    assert profile_response.json()["entries"][0]["name"] == "GF_ACTION"


def test_px4_params_router_snapshot_routes_use_live_store(monkeypatch):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_px4_params_router(deps))

    snapshot_payload = {
        "snapshot": {
            "snapshot_id": "snap-1",
            "hw_id": "1",
            "component_id": 1,
            "px4_docs_version": "main",
            "total_params": 1,
            "created_at": 1,
            "stale_after_ms": 60000,
        },
        "rows": [
            {
                "component_id": 1,
                "name": "MAV_SYS_ID",
                "value_type": "int",
                "value": 1,
                "writable": True,
                "docs_url": "https://docs.px4.io/main/en/advanced_config/parameter_reference.html#MAV_SYS_ID",
                "short_description": None,
                "long_description": None,
                "unit": None,
                "decimal_places": None,
                "default_value": None,
                "min_value": None,
                "max_value": None,
                "reboot_required": None,
                "metadata_sources": ["vehicle", "px4_docs"],
            }
        ],
    }

    def fake_fetch(deps_arg, request):
        del deps_arg
        assert request.hw_ids == ["1"]
        return {
            "snapshots": [snapshot_payload],
            "errors": [],
            "total_targets": 1,
            "timestamp": 2,
        }

    monkeypatch.setattr("api_routes.px4_params.fetch_snapshots_for_targets", fake_fetch)
    monkeypatch.setattr("api_routes.px4_params.get_snapshot", lambda snapshot_id: snapshot_payload if snapshot_id == "snap-1" else None)
    monkeypatch.setattr(
        "api_routes.px4_params.build_snapshot_rows_response",
        lambda snapshot_id: {
            "snapshot_id": snapshot_id,
            "rows": snapshot_payload["rows"],
            "total_rows": 1,
            "timestamp": 3,
        } if snapshot_id == "snap-1" else None,
    )

    with TestClient(app) as client:
        create_response = client.post("/api/v1/px4-params/snapshots", json={"hw_ids": ["1"], "component_id": 1})
        snapshot_response = client.get("/api/v1/px4-params/snapshots/snap-1")
        rows_response = client.get("/api/v1/px4-params/snapshots/snap-1/rows")

    assert create_response.status_code == 200
    assert create_response.json()["snapshots"][0]["snapshot"]["snapshot_id"] == "snap-1"
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["snapshot"]["snapshot_id"] == "snap-1"
    assert rows_response.status_code == 200
    assert rows_response.json()["total_rows"] == 1


def test_px4_params_router_patch_job_routes_use_live_store(monkeypatch):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_px4_params_router(deps))

    patch_job_payload = {
        "job_id": "job-1",
        "source": "manual",
        "status": "completed",
        "verify_readback": True,
        "total_targets": 1,
        "completed_targets": 1,
        "failed_targets": 0,
        "results": [
            {
                "hw_id": "1",
                "applied": True,
                "verified": True,
                "result": {
                    "source": "manual",
                    "applied_count": 1,
                    "failed_count": 0,
                    "verified_count": 1,
                    "results": [
                        {
                            "name": "MPC_XY_VEL_MAX",
                            "value_type": "float",
                            "requested_value": 12.0,
                            "applied": True,
                            "verified": True,
                            "actual_value": 12.0,
                            "error": None,
                        }
                    ],
                    "timestamp": 4,
                },
                "error": None,
            }
        ],
        "created_at": 2,
        "completed_at": 3,
    }

    def fake_run_patch_job(deps_arg, request):
        del deps_arg
        assert request.hw_ids == ["1"]
        assert request.entries[0].name == "MPC_XY_VEL_MAX"
        return patch_job_payload

    monkeypatch.setattr("api_routes.px4_params.run_patch_job_for_targets", fake_run_patch_job)
    monkeypatch.setattr("api_routes.px4_params.get_patch_job", lambda job_id: patch_job_payload if job_id == "job-1" else None)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/px4-params/patch-jobs",
            json={
                "hw_ids": ["1"],
                "source": "manual",
                "verify_readback": True,
                "entries": [
                    {
                        "component_id": 1,
                        "name": "MPC_XY_VEL_MAX",
                        "value_type": "float",
                        "value": 12.0,
                    }
                ],
            },
        )
        status_response = client.get("/api/v1/px4-params/patch-jobs/job-1")

    assert create_response.status_code == 200
    assert create_response.json()["job_id"] == "job-1"
    assert status_response.status_code == 200
    assert status_response.json()["results"][0]["result"]["results"][0]["name"] == "MPC_XY_VEL_MAX"


def test_px4_params_router_import_and_diff_routes(monkeypatch):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_px4_params_router(deps))

    qgc_import_payload = {
        "source": "qgc",
        "entries": [
            {
                "component_id": 1,
                "name": "MPC_XY_VEL_MAX",
                "value_type": "float",
                "value": 12.0,
            }
        ],
        "warnings": [],
        "skipped_count": 0,
        "total_entries": 1,
        "timestamp": 4,
    }
    mds_import_payload = {**qgc_import_payload, "source": "mds"}
    diff_payload = {
        "differences": [
            {
                "name": "MPC_XY_VEL_MAX",
                "component_id": 1,
                "value_type": "float",
                "current_value": 10.0,
                "desired_value": 12.0,
                "changed": True,
            }
        ],
        "total_changed": 1,
        "timestamp": 5,
    }

    monkeypatch.setattr("api_routes.px4_params.import_qgc_parameter_file", lambda request: qgc_import_payload)
    monkeypatch.setattr("api_routes.px4_params.import_mds_patch", lambda request: mds_import_payload)
    monkeypatch.setattr("api_routes.px4_params.build_param_diff_response", lambda request: diff_payload)

    with TestClient(app) as client:
        qgc_response = client.post(
            "/api/v1/px4-params/imports/qgc",
            json={"content": "# QGC\n1\t1\tMPC_XY_VEL_MAX\t12\t9\n"},
        )
        mds_response = client.post(
            "/api/v1/px4-params/imports/mds",
            json={"content": "{\"entries\": [{\"component_id\": 1, \"name\": \"MPC_XY_VEL_MAX\", \"value_type\": \"float\", \"value\": 12.0}]}"},
        )
        diff_response = client.post(
            "/api/v1/px4-params/diff",
            json={
                "snapshot_id": "snap-1",
                "desired_entries": [
                    {
                        "component_id": 1,
                        "name": "MPC_XY_VEL_MAX",
                        "value_type": "float",
                        "value": 12.0,
                    }
                ],
                "include_unchanged": False,
            },
        )

    assert qgc_response.status_code == 200
    assert qgc_response.json()["source"] == "qgc"
    assert mds_response.status_code == 200
    assert mds_response.json()["source"] == "mds"
    assert diff_response.status_code == 200
    assert diff_response.json()["total_changed"] == 1


def test_px4_params_router_import_and_diff_routes_use_store_helpers(monkeypatch):
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_px4_params_router(deps))

    monkeypatch.setattr(
        "api_routes.px4_params.import_qgc_parameter_file",
        lambda request: {
            "source": "qgc",
            "entries": [
                {
                    "component_id": 1,
                    "name": "MPC_XY_VEL_MAX",
                    "value_type": "float",
                    "value": 12.0,
                }
            ],
            "warnings": [],
            "skipped_count": 0,
            "total_entries": 1,
            "timestamp": 5,
        },
    )
    monkeypatch.setattr(
        "api_routes.px4_params.import_mds_patch",
        lambda request: {
            "source": "mds",
            "entries": [
                {
                    "component_id": 1,
                    "name": "MPC_XY_VEL_MAX",
                    "value_type": "float",
                    "value": 12.0,
                }
            ],
            "warnings": [],
            "skipped_count": 0,
            "total_entries": 1,
            "timestamp": 6,
        },
    )
    monkeypatch.setattr(
        "api_routes.px4_params.build_param_diff_response",
        lambda request: {
            "differences": [
                {
                    "name": "MPC_XY_VEL_MAX",
                    "component_id": 1,
                    "value_type": "float",
                    "current_value": 10.0,
                    "desired_value": 12.0,
                    "changed": True,
                }
            ],
            "total_changed": 1,
            "timestamp": 7,
        },
    )

    with TestClient(app) as client:
        qgc_response = client.post("/api/v1/px4-params/imports/qgc", json={"content": "# file\n1\t1\tMPC_XY_VEL_MAX\t12.0\t9"})
        mds_response = client.post(
            "/api/v1/px4-params/imports/mds",
            json={"content": "{\"entries\":[{\"component_id\":1,\"name\":\"MPC_XY_VEL_MAX\",\"value_type\":\"float\",\"value\":12.0}]}"},
        )
        diff_response = client.post(
            "/api/v1/px4-params/diff",
            json={
                "snapshot_id": "snap-1",
                "desired_entries": [
                    {
                        "component_id": 1,
                        "name": "MPC_XY_VEL_MAX",
                        "value_type": "float",
                        "value": 12.0,
                    }
                ],
            },
        )

    assert qgc_response.status_code == 200
    assert qgc_response.json()["source"] == "qgc"
    assert mds_response.status_code == 200
    assert mds_response.json()["source"] == "mds"
    assert diff_response.status_code == 200
    assert diff_response.json()["total_changed"] == 1

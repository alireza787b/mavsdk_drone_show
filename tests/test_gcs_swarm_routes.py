from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_routes.swarm import create_swarm_router
from src.smart_swarm_contract import topology_revision


def _make_deps():
    return SimpleNamespace(
        load_swarm=lambda: [
            {"hw_id": 1, "follow": 0, "offset_x": 0.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"},
            {"hw_id": 2, "follow": 1, "offset_x": 1.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"},
        ],
        save_swarm=Mock(),
        log_system_event=lambda *args, **kwargs: None,
        Params=SimpleNamespace(GIT_AUTO_PUSH=False),
        git_operations=Mock(return_value={"status": "skipped"}),
        BASE_DIR="/tmp/test-base",
    )


def test_swarm_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/config/swarm" in routes
    assert "/api/v1/config/swarm/assignments/{hw_id}" in routes
    assert "/get-swarm-data" not in routes
    assert "/save-swarm-data" not in routes
    assert "/request-new-leader" not in routes


def test_swarm_router_uses_live_dependency_attributes_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    replacement_load = Mock(return_value=[
        {"hw_id": 1, "follow": 0, "offset_x": 0.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"},
        {"hw_id": 2, "follow": 0, "offset_x": 1.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"},
    ])
    replacement_save = Mock()
    deps.load_swarm = replacement_load
    deps.save_swarm = replacement_save

    with TestClient(app) as client:
        response = client.patch("/api/v1/config/swarm/assignments/2", json={"follow": 1})

    assert response.status_code == 200
    replacement_load.assert_called_once()
    replacement_save.assert_called_once()
    assert response.json()["assignment"]["follow"] == 1


def test_offset_only_assignment_patch_preserves_existing_follow_relationship():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/config/swarm/assignments/2",
            json={"offset_x": 4.0},
        )

    assert response.status_code == 200
    assignment = response.json()["assignment"]
    assert assignment["follow"] == 1
    assert assignment["offset_x"] == 4.0


def test_swarm_router_save_swarm_commit_false_skips_git_operations():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/config/swarm?commit=false",
            json={"version": 1, "assignments": [{"hw_id": 1, "follow": 0}, {"hw_id": 2, "follow": 1}]},
        )

    assert response.status_code == 200
    deps.save_swarm.assert_called_once()
    deps.git_operations.assert_not_called()
    assert response.json()["config"]["assignments"][1]["follow"] == 1


def test_swarm_router_rejects_stale_revision_before_writing():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/config/swarm?commit=false",
            json={"version": 1, "revision": "stale", "assignments": [
                {"hw_id": 1, "follow": 0}, {"hw_id": 2, "follow": 1},
            ]},
        )

    assert response.status_code == 409
    deps.save_swarm.assert_not_called()


def test_revision_apply_requires_explicit_unavailable_confirmation():
    deps = _make_deps()
    before = deps.load_swarm()
    after = [dict(m) for m in before]
    after[1]['offset_x'] = 4
    app = FastAPI()
    app.include_router(create_swarm_router(deps))
    payload = {'version': 1, 'revision': topology_revision(before), 'assignments': after}
    with TestClient(app) as client:
        rejected = client.put('/api/v1/config/swarm?commit=false', json=payload)
        assert rejected.status_code == 409
        assert rejected.json()['detail']['unavailable_hw_ids'] == ['2']
        deps.save_swarm.assert_not_called()
        payload['acknowledged_unavailable_hw_ids'] = ['2']
        accepted = client.put('/api/v1/config/swarm?commit=false', json=payload)
    assert accepted.status_code == 200
    assert accepted.json()['application']['nodes'][1]['status'] == 'not_reachable'
    deps.save_swarm.assert_called_once()


def test_publish_never_installs_a_draft():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))
    with TestClient(app) as client:
        invalid = client.post('/api/v1/config/swarm/publish', json={'revision': '0' * 64})
        assert invalid.status_code == 409
        valid = client.post('/api/v1/config/swarm/publish', json={'revision': topology_revision(deps.load_swarm())})
    assert valid.status_code == 200
    deps.save_swarm.assert_not_called()
    deps.git_operations.assert_called_once()


def test_application_status_requires_effective_revision_not_just_fetched_revision():
    deps = _make_deps()
    now = int(time.time() * 1000)
    revision = topology_revision(deps.load_swarm())
    deps.telemetry_data_all_drones = {str(i): {'telemetry_timestamp_ms': now} for i in (1, 2)}
    tracker = SimpleNamespace(get_active_commands=AsyncMock(return_value=[{
        'target_drones': ['1', '2'], 'swarm_runtime': {'nodes': {
            '1': {'follow': '0', 'revision': revision, 'received_at_ms': now, 'phase': 'active'},
            '2': {'follow': '1', 'revision': revision, 'applied_revision': revision, 'received_at_ms': now, 'phase': 'tracking'},
        }},
    }]))
    deps.get_command_tracker = lambda: tracker
    app = FastAPI()
    app.include_router(create_swarm_router(deps))
    with TestClient(app) as client:
        status = client.get('/api/v1/config/swarm/status').json()
        assert [n['status'] for n in status['nodes']] == ['pending', 'applied']
        after = [dict(m) for m in deps.load_swarm()]
        after[1]['offset_x'] = 4
        result = client.put('/api/v1/config/swarm?commit=false', json={
            'revision': revision, 'assignments': after,
        })
        assert result.status_code == 409
        assert result.json()['detail']['code'] == 'formation_apply_pending'
    deps.save_swarm.assert_not_called()


def test_legacy_node_can_accept_first_apply_without_false_applied_status():
    deps = _make_deps()
    now = int(time.time() * 1000)
    revision = topology_revision(deps.load_swarm())
    deps.telemetry_data_all_drones = {str(i): {'telemetry_timestamp_ms': now} for i in (1, 2)}
    tracker = SimpleNamespace(get_active_commands=AsyncMock(return_value=[{
        'target_drones': ['1', '2'], 'params': {'smart_swarm': {'revision': revision}},
        'swarm_runtime': {'nodes': {
            str(i): {'follow': str(i - 1), 'revision': revision, 'received_at_ms': now, 'phase': 'active'}
            for i in (1, 2)
        }},
    }]))
    deps.get_command_tracker = lambda: tracker
    app = FastAPI()
    app.include_router(create_swarm_router(deps))
    with TestClient(app) as client:
        observed = client.get('/api/v1/config/swarm/status').json()
        assert all(n['status'] == 'pending' and not n['update_pending'] for n in observed['nodes'])
        after = [dict(m) for m in deps.load_swarm()]
        after[1]['offset_x'] = 4
        result = client.put('/api/v1/config/swarm?commit=false', json={'revision': revision, 'assignments': after})
    assert result.status_code == 200
    deps.save_swarm.assert_called_once()
    assert all(n['status'] == 'pending' and n['update_pending'] for n in result.json()['application']['nodes'])


def test_duplicate_assignments_never_reach_storage():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))
    with TestClient(app) as client:
        result = client.put('/api/v1/config/swarm?commit=false', json={'assignments': [
            {'hw_id': 1}, {'hw_id': 1},
        ]})
    assert result.status_code == 400
    deps.save_swarm.assert_not_called()


def test_swarm_router_commit_true_reports_git_failure_after_local_save():
    deps = _make_deps()
    deps.git_operations = Mock(return_value={
        "success": False,
        "message": "Git push failed: authenticated write access is required",
    })
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/config/swarm?commit=true",
            json={"version": 1, "assignments": [{"hw_id": 1, "follow": 0}, {"hw_id": 2, "follow": 1}]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "git_failed"
    assert "saved locally" in body["message"]
    assert "authenticated write access" in body["message"]
    assert body["git_result"]["success"] is False
    deps.save_swarm.assert_called_once()
    deps.git_operations.assert_called_once()


def test_swarm_router_commit_true_reports_local_commit_when_remote_push_is_disabled():
    deps = _make_deps()
    deps.git_operations = Mock(return_value={
        "success": True,
        "message": "Changes committed locally. Auto-push is disabled on this GCS.",
        "commit_hash": "abc12345",
        "auto_push_enabled": False,
        "pushed": False,
    })
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/config/swarm?commit=true",
            json={"version": 1, "assignments": [{"hw_id": 1, "follow": 0}, {"hw_id": 2, "follow": 1}]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "git_not_pushed"
    assert body["git_result"]["pushed"] is False
    assert body["git_result"]["commit_hash"] == "abc12345"
    deps.save_swarm.assert_called_once()
    deps.git_operations.assert_called_once()


def test_swarm_router_canonical_get_returns_enveloped_assignments():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_swarm_router(deps))

    with TestClient(app) as client:
        response = client.get("/api/v1/config/swarm")

    assert response.status_code == 200
    expected_assignments = [
        {"hw_id": 1, "follow": 0, "offset_x": 0.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"},
        {"hw_id": 2, "follow": 1, "offset_x": 1.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "ned"},
    ]
    assert response.json() == {
        "version": 1,
        "assignments": expected_assignments,
        "revision": topology_revision(expected_assignments),
    }

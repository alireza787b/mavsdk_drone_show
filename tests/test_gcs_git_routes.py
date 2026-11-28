import asyncio
import threading
import time
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI

from api_routes.git_status import create_git_router
import api_routes.git_status as git_routes
import api_routes.fleet_git_sync as update_routes
from tests.conftest import SyncASGITestClient

MUTATION_HEADERS = {"x-fleet-ops-token": "test-token"}


def _make_deps(state_dir=None):
    tracker = SimpleNamespace(
        get_callback_capabilities=AsyncMock(
            return_value={"1": "x" * 43}
        ),
        record_authoritative_completion=AsyncMock(return_value=True),
    )
    return SimpleNamespace(
        Params=SimpleNamespace(GIT_BRANCH="main-candidate", GCS_COMMAND_STATE_DIR=state_dir),
        GitStatus=None,
        load_config=lambda: [{"hw_id": "1", "pos_id": 1, "ip": "10.0.0.1"}],
        get_gcs_git_report=lambda: {"branch": "main-candidate", "commit": "abc12345"},
        git_status_data_all_drones={
            "1": {"status": "clean", "branch": "main-candidate", "commit": "abc12345", "uncommitted_changes": []}
        },
        data_lock_git_status=threading.Lock(),
        _sync_state={"active": False, "started_at": None, "results": None},
        _sync_lock=asyncio.Lock(),
        _select_sync_target_drones=lambda drones_config, pos_ids: (drones_config, []),
        _verify_sync_targets=AsyncMock(return_value=(["1"], [])),
        get_command_tracker=lambda: tracker,
        send_commands_to_all=Mock(return_value={"results": {"1": {"category": "accepted"}}}),
        send_commands_to_selected=Mock(return_value={"results": {"1": {"category": "accepted"}}}),
        log_system_event=lambda *args, **kwargs: None,
        log_system_error=lambda *args, **kwargs: None,
    )


def _patch_tracked_submission(monkeypatch):
    submit = AsyncMock(return_value=SimpleNamespace(command_id="cmd-git-sync"))
    wait = AsyncMock(return_value={"phase": "pending_execution"})
    monkeypatch.setattr(update_routes, "submit_tracked_command", submit)
    monkeypatch.setattr(update_routes, "_wait_for_tracked_dispatch", wait)
    return submit, wait


def test_git_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_git_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/git/status" in routes
    assert "/api/v1/git/sync-operations" not in routes
    assert "/api/v1/fleet/git-sync" in routes
    assert "/api/v1/fleet/git-sync/dry-run" in routes
    assert "/api/v1/fleet/git-sync/apply" in routes
    assert "/ws/git-status" in routes


def test_unavailable_git_report_is_unknown_not_a_confirmed_mismatch():
    deps = _make_deps()
    deps.git_status_data_all_drones['1'] = {'status': 'unknown'}
    result = git_routes._build_git_status_response(deps)
    assert result.unknown_count == 1
    assert result.needs_sync_count == 0
    assert result.synced_count == 0
    assert result.git_status['1'].last_check == 0


def test_matching_commit_with_unknown_worktree_is_not_counted_twice():
    deps = _make_deps()
    deps.git_status_data_all_drones['1']['status'] = 'unknown'
    result = git_routes._build_git_status_response(deps)
    assert result.unknown_count == 1
    assert result.needs_sync_count == 0
    assert result.synced_count == 0
    assert result.git_status['1'].in_sync_with_gcs is False


def test_software_attention_survives_brief_loss_without_allowing_stale_sync():
    deps = _make_deps()
    deps.git_status_data_all_drones['1']['commit'] = 'older-source'
    for age, expected in [(0, 1), (25, 1), (61, 0), (0, 1)]:
        deps.get_all_heartbeats = lambda: {'1': {'timestamp': int((time.time()-age)*1000), 'hw_id':'1'}}
        assert git_routes._build_git_status_response(deps).needs_sync_count == expected
        if age == 25:
            table = git_routes._build_fleet_git_sync_table(deps)
            assert table['rows'][0]['presence']['fresh'] is False
            assert table['needs_sync_count'] == 0


def test_git_review_distinguishes_matching_revision_on_another_branch():
    deps = _make_deps()
    row = deps.git_status_data_all_drones["1"]
    row["branch"] = "alternate"
    result = git_routes._build_git_status_response(deps)
    assert (result.needs_sync_count, result.branch_only_count) == (0, 1)
    row["uncommitted_changes"] = [" M local.py"]
    assert git_routes._build_git_status_response(deps).branch_only_count == 0
    row.update(commit="01234567", uncommitted_changes=[])
    assert git_routes._build_git_status_response(deps).branch_only_count == 0


def test_software_attention_reuses_configured_available_window():
    deps = _make_deps()
    deps.Params.PRESENCE_STALE_SEC = 120
    deps.git_status_data_all_drones['1']['commit'] = 'older-source'
    deps.get_all_heartbeats = lambda: {'1': {'timestamp': int((time.time()-80)*1000), 'hw_id':'1'}}
    assert git_routes._build_git_status_response(deps).needs_sync_count == 1


def test_brief_loss_of_matching_aircraft_does_not_create_software_noise():
    deps = _make_deps()
    deps.get_all_heartbeats = lambda: {'1': {'timestamp': int((time.time()-25)*1000), 'hw_id':'1'}}
    result = git_routes._build_git_status_response(deps)
    assert result.needs_sync_count == result.unknown_count == 0


def test_presence_refresh_failure_is_unavailable_not_a_false_all_clear():
    deps = _make_deps()
    deps.get_all_heartbeats = Mock(side_effect=RuntimeError('temporary outage'))
    app = FastAPI()
    app.include_router(create_git_router(deps))
    response = SyncASGITestClient(app).get('/api/v1/git/status')
    assert response.status_code == 503


@pytest.mark.parametrize('payload', [None, []])
def test_invalid_presence_snapshot_is_not_treated_as_an_empty_fleet(payload):
    deps = _make_deps()
    deps.get_all_heartbeats = lambda: payload
    app = FastAPI()
    app.include_router(create_git_router(deps))
    assert SyncASGITestClient(app).get('/api/v1/git/status').status_code == 503


def test_fleet_git_sync_apply_uses_live_verify_dependency_after_router_creation(monkeypatch, tmp_path):
    deps = _make_deps(tmp_path)
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": int(time.time() * 1000), "hw_id": "1"}}
    monkeypatch.setenv("MDS_FLEET_OPS_MUTATION_TOKEN", "test-token")
    initial_verify = deps._verify_sync_targets
    submit, wait = _patch_tracked_submission(monkeypatch)

    app = FastAPI()
    app.include_router(create_git_router(deps))

    replacement_verify = AsyncMock(return_value=(["1"], []))
    deps._verify_sync_targets = replacement_verify

    client = SyncASGITestClient(app)
    dry_run = client.post("/api/v1/fleet/git-sync/dry-run", headers=MUTATION_HEADERS, json={"pos_ids": [1]})
    assert dry_run.status_code == 200
    response = client.post(
        "/api/v1/fleet/git-sync/apply",
        headers=MUTATION_HEADERS,
        json={
            "dry_run_id": dry_run.json()["job_id"],
            "confirmation": {
                "acknowledged_risks": True,
                "confirmation_token": dry_run.json()["confirmation_token"],
            },
        },
    )

    assert response.status_code == 200
    initial_verify.assert_not_called()
    replacement_verify.assert_awaited_once()
    submit.assert_awaited_once()
    wait.assert_awaited_once_with(deps, "cmd-git-sync")


def test_selected_git_sync_keeps_routing_ids_out_of_drone_command_payload(monkeypatch, tmp_path):
    deps = _make_deps(tmp_path)
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": int(time.time() * 1000), "hw_id": "1"}}
    monkeypatch.setenv("MDS_FLEET_OPS_MUTATION_TOKEN", "test-token")
    submit, _wait = _patch_tracked_submission(monkeypatch)
    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    dry_run = client.post("/api/v1/fleet/git-sync/dry-run", headers=MUTATION_HEADERS, json={"pos_ids": [1]})
    response = client.post(
        "/api/v1/fleet/git-sync/apply",
        headers=MUTATION_HEADERS,
        json={
            "dry_run_id": dry_run.json()["job_id"],
            "confirmation": {
                "acknowledged_risks": True,
                "confirmation_token": dry_run.json()["confirmation_token"],
            },
        },
    )

    assert response.status_code == 200
    submit.assert_awaited_once()
    command = submit.await_args.args[1]
    assert command.target_drone_ids == ["1"]
    assert command.mission_type == update_routes.Mission.UPDATE_CODE.value
    assert command.update_branch == "main-candidate"
    assert "pos_ids" not in command.model_dump()
    deps.send_commands_to_selected.assert_not_called()


def test_fleet_git_sync_maps_verified_position_back_to_exact_hardware_target(monkeypatch, tmp_path):
    deps = _make_deps(tmp_path)
    deps.load_config = lambda: [
        {"hw_id": "42", "pos_id": 7, "ip": "10.0.0.42"}
    ]
    deps._select_sync_target_drones = lambda drones_config, _pos_ids: (
        drones_config,
        [],
    )
    deps.get_all_heartbeats = lambda: {
        "42": {"timestamp": int(time.time() * 1000), "hw_id": "42"}
    }
    deps.git_status_data_all_drones["42"] = deps.git_status_data_all_drones["1"]
    deps._verify_sync_targets = AsyncMock(return_value=(["42"], []))
    tracker = SimpleNamespace(
        get_callback_capabilities=AsyncMock(
            return_value={"42": "x" * 43}
        ),
        record_authoritative_completion=AsyncMock(return_value=True),
    )
    deps.get_command_tracker = lambda: tracker
    monkeypatch.setenv("MDS_FLEET_OPS_MUTATION_TOKEN", "test-token")
    _patch_tracked_submission(monkeypatch)
    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    dry_run = client.post(
        "/api/v1/fleet/git-sync/dry-run",
        headers=MUTATION_HEADERS,
        json={"pos_ids": [7]},
    )
    response = client.post(
        "/api/v1/fleet/git-sync/apply",
        headers=MUTATION_HEADERS,
        json={
            "dry_run_id": dry_run.json()["job_id"],
            "confirmation": {
                "acknowledged_risks": True,
                "confirmation_token": dry_run.json()["confirmation_token"],
            },
        },
    )

    assert response.status_code == 200
    completion_results = tracker.record_authoritative_completion.await_args.args[1]
    assert completion_results == {"42": {"success": True, "error_message": None}}


def test_fleet_git_sync_never_aliases_duplicate_position_ids_to_hardware(monkeypatch, tmp_path):
    deps = _make_deps(tmp_path)
    targets = [
        {"hw_id": "41", "pos_id": 7, "ip": "10.0.0.41"},
        {"hw_id": "42", "pos_id": 7, "ip": "10.0.0.42"},
    ]
    deps.load_config = lambda: targets
    deps._select_sync_target_drones = lambda drones_config, _pos_ids: (
        drones_config,
        [],
    )
    deps.get_all_heartbeats = lambda: {
        hw_id: {"timestamp": int(time.time() * 1000), "hw_id": hw_id}
        for hw_id in ("41", "42")
    }
    deps.git_status_data_all_drones = {hw: deps.git_status_data_all_drones["1"] for hw in ("41", "42")}
    deps._verify_sync_targets = AsyncMock(return_value=(["41"], ["42"]))
    tracker = SimpleNamespace(
        get_callback_capabilities=AsyncMock(
            return_value={"41": "a" * 43, "42": "b" * 43}
        ),
        record_authoritative_completion=AsyncMock(return_value=True),
    )
    deps.get_command_tracker = lambda: tracker
    monkeypatch.setenv("MDS_FLEET_OPS_MUTATION_TOKEN", "test-token")
    _patch_tracked_submission(monkeypatch)
    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    dry_run = client.post(
        "/api/v1/fleet/git-sync/dry-run",
        headers=MUTATION_HEADERS,
        json={"pos_ids": [7]},
    )
    response = client.post(
        "/api/v1/fleet/git-sync/apply",
        headers=MUTATION_HEADERS,
        json={
            "dry_run_id": dry_run.json()["job_id"],
            "confirmation": {
                "acknowledged_risks": True,
                "confirmation_token": dry_run.json()["confirmation_token"],
            },
        },
    )

    assert response.status_code == 200
    completion_results = tracker.record_authoritative_completion.await_args.args[1]
    assert completion_results["41"]["success"] is True
    assert completion_results["42"]["success"] is False


def test_fleet_git_sync_dry_run_requires_operator_token(monkeypatch):
    deps = _make_deps()
    monkeypatch.setenv("MDS_FLEET_OPS_MUTATION_TOKEN", "test-token")
    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    response = client.post("/api/v1/fleet/git-sync/dry-run", json={"pos_ids": [1]})

    assert response.status_code == 403


def test_git_router_get_gcs_status_uses_live_dependency_after_router_creation():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_git_router(deps))

    replacement_report = Mock(return_value={"branch": "release", "commit": "def67890"})
    deps.get_gcs_git_report = replacement_report

    client = SyncASGITestClient(app)
    response = client.get("/api/v1/git/status")

    assert response.status_code == 200
    replacement_report.assert_called_once()
    assert response.json()["gcs_status"]["branch"] == "release"


def test_git_status_exposes_read_only_node_env_posture():
    deps = _make_deps()
    deps.git_status_data_all_drones = {
        "1": {
            "status": "clean",
            "branch": "main-candidate",
            "commit": "abc12345",
            "uncommitted_changes": [],
            "env_runtime": {
                "status_source": "registry",
                "registry_version": 1,
                "registry_hash": "abc123",
                "local_env_path": "/etc/mds/local.env",
                "local_env_present": True,
                "node_identity_path": "/etc/mds/node_identity.json",
                "node_identity_present": True,
                "runtime_mode": "real",
                "runtime_mode_source": "env:MDS_MODE",
                "hw_id": 1,
                "hw_id_source": "env:MDS_HW_ID",
                "configured_key_count": 7,
                "configured_node_key_count": 5,
                "registered_node_key_count": 20,
                "unknown_keys": ["OLD_KEY"],
                "deprecated_keys": [],
                "warnings": ["Node local.env contains unregistered keys."],
            },
        },
    }

    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    response = client.get("/api/v1/git/status")

    assert response.status_code == 200
    env_runtime = response.json()["git_status"]["1"]["env_runtime"]
    assert env_runtime["registry_hash"] == "abc123"
    assert env_runtime["runtime_mode"] == "real"
    assert env_runtime["unknown_keys"] == ["OLD_KEY"]


def test_git_status_keeps_stale_offline_drift_out_of_global_sync_warning():
    deps = _make_deps()
    deps.Params.TELEMETRY_POLLING_TIMEOUT = 5
    deps.get_gcs_git_report = lambda: {"branch": "main-candidate", "commit": "new67890"}
    deps.git_status_data_all_drones = {
        "1": {
            "status": "clean",
            "branch": "main-candidate",
            "commit": "old12345",
            "uncommitted_changes": [],
        },
    }
    deps.get_all_heartbeats = lambda: {
        "1": {
            "timestamp": int((time.time() - 60) * 1000),
            "hw_id": "1",
        },
    }

    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    response = client.get("/api/v1/git/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["git_status"]["1"]["in_sync_with_gcs"] is False
    assert payload["total_drones"] == 1
    assert payload["needs_sync_count"] == 0


def test_git_status_empty_heartbeat_set_suppresses_global_sync_warning():
    deps = _make_deps()
    deps.get_gcs_git_report = lambda: {"branch": "main-candidate", "commit": "new67890"}
    deps.git_status_data_all_drones = {
        "1": {
            "status": "clean",
            "branch": "main-candidate",
            "commit": "old12345",
            "uncommitted_changes": [],
        },
    }
    deps.get_all_heartbeats = lambda: {}

    app = FastAPI()
    app.include_router(create_git_router(deps))

    client = SyncASGITestClient(app)
    response = client.get("/api/v1/git/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["git_status"]["1"]["in_sync_with_gcs"] is False
    assert payload["total_drones"] == 1
    assert payload["needs_sync_count"] == 0


def _fleet_client(deps):
    app = FastAPI()
    app.include_router(create_git_router(deps))
    return SyncASGITestClient(app)


def _confirmed(preview):
    return {"dry_run_id": preview["job_id"],
            "confirmation": {"acknowledged_risks": True, "confirmation_token": preview["confirmation_token"]}}


def test_preview_excludes_unknown_and_offline_and_preserves_empty_scope(tmp_path):
    deps = _make_deps(tmp_path)
    deps.load_config = lambda: [{"hw_id": str(i), "pos_id": 10 + i, "ip": f"10.0.0.{i}"} for i in (1, 2, 3)]
    deps.get_all_heartbeats = lambda: {hw: {"timestamp": time.time()} for hw in ("1", "2")}
    client = _fleet_client(deps)
    preview = client.post("/api/v1/fleet/git-sync/dry-run", json={}).json()
    assert preview["target_counts"] == dict(total=3, ready=1, blocked=2, verified=0, unconfirmed=0)
    assert preview["results"]["2"]["error_code"] == "version_unknown"
    assert preview["results"]["3"]["error_code"] == "offline"
    assert [t["hw_id"] for t in preview["targets"]] == ["1"]
    for scope in ({"hw_ids": []}, {"pos_ids": []}):
        assert client.post("/api/v1/fleet/git-sync/dry-run", json=scope).json()["targets"] == []
    assert client.post("/api/v1/fleet/git-sync/dry-run", json={"hw_ids": ["999"]}).status_code == 409


@pytest.mark.parametrize("change", ["identity", "revision", "offline", "unknown", "endpoint"])
def test_review_fences_changes_before_dispatch(monkeypatch, tmp_path, change):
    deps = _make_deps(tmp_path)
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": time.time()}}
    submit, _ = _patch_tracked_submission(monkeypatch)
    client = _fleet_client(deps)
    preview = client.post("/api/v1/fleet/git-sync/dry-run", json={"hw_ids": ["1"]}).json()
    if change == "identity":
        deps.load_config = lambda: [{"hw_id": "2", "pos_id": 1, "ip": "10.0.0.1"}]
    elif change == "revision":
        deps.get_gcs_git_report = lambda: {"branch": "main", "commit": "moved"}
    elif change == "offline":
        deps.get_all_heartbeats = lambda: {}
    elif change == "unknown":
        deps.git_status_data_all_drones = {}
    else:
        deps.load_config = lambda: [{"hw_id": "1", "pos_id": 1, "ip": "10.0.0.99"}]
    assert client.post("/api/v1/fleet/git-sync/apply", json=_confirmed(preview)).status_code == 409
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_update_progress_reconnect_and_replay(monkeypatch, tmp_path):
    import httpx
    deps = _make_deps(tmp_path)
    deps.get_all_heartbeats = lambda: {hw: {"timestamp": time.time()} for hw in ("1", "2")}
    deps.load_config = lambda: [{"hw_id": str(i), "pos_id": 10 + i, "ip": f"10.0.0.{i}"} for i in (1, 2)]
    deps.git_status_data_all_drones["2"] = dict(deps.git_status_data_all_drones["1"])
    submit, _ = _patch_tracked_submission(monkeypatch)
    first_seen, finish = asyncio.Event(), asyncio.Event()

    async def verify(targets, *, expected_branch, expected_commit, on_verified):
        await on_verified(["1"])
        first_seen.set()
        await finish.wait()
        return ["1"], ["2"]

    deps._verify_sync_targets = verify
    app = FastAPI()
    app.include_router(create_git_router(deps))
    base = "/api/v1/fleet/git-sync"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        preview = (await client.post(base+"/dry-run", json={"hw_ids": ["1", "2"]})).json()
        op = base+"/operations/"+preview["operation_id"]
        assert "confirmation_token" not in (await client.get(op)).json()
        body = _confirmed(preview)
        replies = await asyncio.gather(*(client.post(base+"/apply?background=true", json=body) for _ in range(2)))
        assert all(r.status_code == 202 for r in replies)
        await asyncio.wait_for(first_seen.wait(), timeout=2)
        running = (await client.get(op)).json()
        assert running["phase"] == "verifying"
        assert running["target_counts"]["verified"] == 1
        assert running["per_aircraft_state"]["2"]["state"] == "verifying"
        other = (await client.post(base+"/dry-run", json={"hw_ids": ["1"]})).json()
        assert (await client.post(base+"/apply", json=_confirmed(other))).status_code == 409
        finish.set()
        receipt = (await client.post(base+"/apply", json=body)).json()
        assert receipt["synced_drones"] == [11] and receipt["failed_drones"] == [12]
    # A fresh router uses only the journal, without a live browser or task.
    client = _fleet_client(deps)
    terminal = (await client._request("GET", op)).json()
    assert terminal["phase"] == "partial"
    assert terminal["completed_at"] >= terminal["started_at"]
    assert terminal["per_aircraft_state"]["2"]["error_code"] == "verification_timeout"
    assert (await client._request("POST", base+"/apply", json=body)).json() == receipt
    submit.assert_awaited_once()


def test_orphaned_apply_is_recoverable_without_replay(monkeypatch, tmp_path):
    from fleet_git_operations import GitOperationStore, update_phase
    deps = _make_deps(tmp_path)
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": time.time()}}
    client = _fleet_client(deps)
    preview = client.post("/api/v1/fleet/git-sync/dry-run", json={"hw_ids": ["1"]}).json()
    store = GitOperationStore(deps.Params)
    record = store.read(preview["operation_id"])
    update_phase(record, "applying", "Updating")
    store.save(record)  # Simulates a process exit after the durable claim.
    submit, _ = _patch_tracked_submission(monkeypatch)
    status = client.get("/api/v1/fleet/git-sync/operations/" + preview["operation_id"]).json()
    assert status["phase"] == "interrupted" and status["target_counts"]["unconfirmed"] == 1
    assert client.post("/api/v1/fleet/git-sync/apply", json=_confirmed(preview)).json()["success"] is False
    submit.assert_not_awaited()


def test_worker_failure_sanitizes_operation_errors(monkeypatch, tmp_path):
    deps = _make_deps(tmp_path)
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": time.time()}}
    submit, _ = _patch_tracked_submission(monkeypatch)
    submit.side_effect = RuntimeError("test-private-payload")
    client = _fleet_client(deps)
    preview = client.post("/api/v1/fleet/git-sync/dry-run", json={}).json()
    receipt = client.post("/api/v1/fleet/git-sync/apply", json=_confirmed(preview))
    assert receipt.status_code == 200
    assert "test-private-payload" not in receipt.text
    status = client.get("/api/v1/fleet/git-sync/operations/" + preview["operation_id"]).json()
    assert status["phase"] == "failed"
    assert status["error_code"] == "update_unconfirmed"

@pytest.mark.parametrize("report, target, status, matches", [
    ({"status": "clean", "branch": "field", "commit": "abc12345"}, "abc12345", "synced", True),
    ({"status": "clean", "commit": "abc12345", "commits_behind": 1}, "abc12345", "behind", False),
    ({"status": "clean", "commit": "abc12345", "uncommitted_changes": ["modified"]}, "abc12345", "dirty", False),
    ({"status": "clean", "commit": "abc12345"}, None, "unknown", False),
    ({"status": "clean", "commit": "abc12345", "last_check": 1}, "abc12345", "unknown", False),
])
def test_status_table_and_global_notice_share_revision_policy(report, target, status, matches):
    deps = _make_deps()
    deps.git_status_data_all_drones = {1: report}
    deps.get_gcs_git_report = lambda: {"branch": "main", "commit": target}
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": int(time.time() * 1000)}}
    aggregate = git_routes._build_git_status_response(deps)
    table = git_routes._build_fleet_git_sync_table(deps)
    row = aggregate.git_status["1"]
    assert row.status == table["rows"][0]["status"] == status
    assert row.in_sync_with_gcs == table["rows"][0]["in_sync_with_gcs"] == matches
    assert aggregate.unknown_count == table["unknown_count"] == int(status == "unknown")


def test_current_software_and_mismatched_service_count_one_aircraft():
    deps = _make_deps()
    deps.git_status_data_all_drones["1"]["mavlink_runtime"] = {"management_mode": "fleet-merge", "config_hash_match": False}
    status = git_routes._build_git_status_response(deps)
    assert status.synced_count == status.maintenance_count == status.attention_count == 1
    assert status.needs_sync_count == 0
    deps.git_status_data_all_drones["1"]["status"] = "dirty"
    status = git_routes._build_git_status_response(deps)
    assert status.attention_count == status.maintenance_count == status.needs_sync_count == 1


def test_live_aircraft_waiting_for_first_git_read_is_unknown():
    deps = _make_deps()
    deps.git_status_data_all_drones.clear()
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": int(time.time() * 1000)}}
    status = git_routes._build_git_status_response(deps)
    assert status.attention_count == status.unknown_count == 1
    assert status.needs_sync_count == 0

def test_git_operation_lookup_respects_session_read_policy(monkeypatch, tmp_path):
    import auth_runtime
    deps = _make_deps(tmp_path)
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": time.time()}}
    preview = _fleet_client(deps).post("/api/v1/fleet/git-sync/dry-run", json={}).json()
    service = Mock()
    service.settings = SimpleNamespace(any_auth_enabled=True, api_auth_enabled=True, dashboard_auth_enabled=True)
    service.authenticate_bearer.return_value = None
    service.verify_session.side_effect = lambda cookie: {"kind": "session", "role": cookie} if cookie else None
    monkeypatch.setattr(auth_runtime, "build_auth_service", lambda: service)
    app = FastAPI()
    app.add_middleware(auth_runtime.MDSAuthMiddleware)
    app.include_router(create_git_router(deps))
    client = SyncASGITestClient(app)
    url = "/api/v1/fleet/git-sync/operations/" + preview["operation_id"]
    assert client.get(url).status_code == 401
    for role in ["viewer", "operator"]:
        response = client.get(url, headers={"cookie": f"{auth_runtime.SESSION_COOKIE_NAME}={role}"})
        assert response.status_code == 200 and response.json()["phase"] == "review"
        assert "confirmation_token" not in response.text and "proof" not in response.text


def test_expired_preview_never_dispatches(monkeypatch, tmp_path):
    import fleet_git_operations as operations
    deps = _make_deps(tmp_path)
    deps.get_all_heartbeats = lambda: {"1": {"timestamp": time.time()}}
    submit, _ = _patch_tracked_submission(monkeypatch)
    client = _fleet_client(deps)
    preview = client.post("/api/v1/fleet/git-sync/dry-run", json={}).json()
    monkeypatch.setattr(operations, "now_ms", lambda: preview["created_at"] + operations.REVIEW_TTL_MS)
    assert client.get("/api/v1/fleet/git-sync/operations/" + preview["operation_id"]).json()["phase"] == "expired"
    assert client.post("/api/v1/fleet/git-sync/apply", json=_confirmed(preview)).status_code == 409
    submit.assert_not_awaited()

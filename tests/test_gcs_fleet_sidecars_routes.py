import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI

import api_routes.fleet_sidecars as fleet_sidecars
from api_routes.fleet_sidecars import create_fleet_sidecars_router
from tests.conftest import SyncASGITestClient

MUTATION_HEADERS = {"x-fleet-ops-token": "test-token"}


def _make_deps(tmp_path, runtime=None):
    runtime = runtime or {
        "tool": "smart-wifi-manager",
        "service_state": "active",
        "mode": "fleet-merge",
        "drift_state": "in_sync",
        "installed_ref": "v2.1.10",
        "profile_source": "node-local",
        "desired_hash": "desiredhash",
        "local_hash": "localhash",
        "profile_summary": {
            "network_count": 2,
            "profiles": [
                {"id": "field", "ssid": "Demo Field", "priority": 90, "secret_status": "stored"},
                {"id": "backup", "ssid": "Demo Backup", "priority": 10, "secret_status": "external file"},
            ],
        },
        "dashboard_access_mode": "direct",
        "dashboard_url": "http://198.51.100.11:9080/",
        "dashboard_listen": "0.0.0.0:9080",
    }
    return SimpleNamespace(
        BASE_DIR=str(tmp_path),
        Params=SimpleNamespace(TELEMETRY_POLLING_TIMEOUT=5),
        load_config=lambda: [{"hw_id": "1", "pos_id": 1, "ip": "198.51.100.11"}],
        get_all_heartbeats=lambda: {"1": {"timestamp": int(time.time() * 1000)}},
        git_status_data_all_drones={"1": {"connectivity_runtime": runtime}},
        data_lock_git_status=threading.Lock(),
    )


def _client(deps, monkeypatch):
    monkeypatch.setenv("MDS_FLEET_OPS_MUTATION_TOKEN", "test-token")
    fleet_sidecars._jobs.clear()
    app = FastAPI()
    app.include_router(create_fleet_sidecars_router(deps))
    return SyncASGITestClient(app)


def test_fleet_sidecar_table_uses_last_known_runtime(monkeypatch, tmp_path):
    client = _client(_make_deps(tmp_path), monkeypatch)

    response = client.get("/api/v1/fleet/sidecars/smart-wifi-manager")

    assert response.status_code == 200
    row = response.json()["rows"][0]
    assert row["hw_id"] == "1"
    assert row["service_state"] == "active"
    assert row["mode"] == "fleet-merge"
    assert row["desired_hash"] == "desiredhash"
    assert row["local_hash"] == "localhash"
    assert row["drift_state"] == "in_sync"
    assert row["profile_count"] == 2
    assert [profile["ssid"] for profile in row["profiles"]] == ["Demo Field", "Demo Backup"]
    assert row["presence"]["state"] == "online"


def test_fleet_sidecar_baseline_is_redacted(monkeypatch, tmp_path):
    baseline = tmp_path / "deployment/connectivity/smart-wifi-manager/profile.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        '{"profiles":[{"id":"field","ssid":"DemoField","priority":100,"password":"redacted-demo-value"}]}',
        encoding="utf-8",
    )
    client = _client(_make_deps(tmp_path), monkeypatch)

    response = client.get("/api/v1/fleet/sidecars/smart-wifi-manager/baseline")

    assert response.status_code == 200
    data = response.json()
    assert data["present"] is True
    assert data["profile_count"] == 1
    assert data["profiles"][0]["secret_status"] == "stored"
    assert "redacted-demo-value" not in response.text


def test_preferred_config_fleet_baseline_wins_over_legacy_path(monkeypatch, tmp_path):
    preferred = tmp_path / "config/fleet-profiles/smart-wifi-manager/config.json"
    legacy = tmp_path / "deployment/connectivity/smart-wifi-manager/profile.json"
    preferred.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    preferred.write_text(
        '{"profiles":[{"id":"preferred","ssid":"PreferredDemo","priority":100,"password":"redacted-demo-value"}]}',
        encoding="utf-8",
    )
    legacy.write_text(
        '{"profiles":[{"id":"legacy","ssid":"LegacyDemo","priority":10,"password":"redacted-demo-value"}]}',
        encoding="utf-8",
    )
    client = _client(_make_deps(tmp_path), monkeypatch)

    response = client.get("/api/v1/fleet/sidecars/smart-wifi-manager/baseline")

    assert response.status_code == 200
    data = response.json()
    assert data["path"] == "config/fleet-profiles/smart-wifi-manager/config.json"
    assert data["profiles"][0]["id"] == "preferred"
    assert "redacted-demo-value" not in response.text


def test_policy_apply_rejects_fleet_strict_without_advanced_ack(monkeypatch, tmp_path):
    client = _client(_make_deps(tmp_path), monkeypatch)
    dry_run = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/policy/dry-run",
        headers=MUTATION_HEADERS,
        json={"node_ids": ["1"], "mode": "fleet-strict"},
    )
    assert dry_run.status_code == 200

    response = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/policy/apply",
        headers=MUTATION_HEADERS,
        json={
            "dry_run_id": dry_run.json()["job_id"],
            "confirmation": {
                "acknowledged_risks": True,
                "advanced_strict_ack": False,
                "confirmation_token": dry_run.json()["confirmation_token"],
            },
        },
    )

    assert response.status_code == 400
    assert "advanced confirmation" in response.text


def test_mutating_routes_require_operator_token(monkeypatch, tmp_path):
    client = _client(_make_deps(tmp_path), monkeypatch)

    response = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/policy/dry-run",
        json={"node_ids": ["1"], "mode": "fleet-merge"},
    )

    assert response.status_code == 403


def test_reconcile_requires_explicit_selected_nodes(monkeypatch, tmp_path):
    baseline = tmp_path / "config/fleet-profiles/smart-wifi-manager/config.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text('{"profiles":[{"id":"field","ssid":"DemoField"}]}', encoding="utf-8")
    client = _client(_make_deps(tmp_path), monkeypatch)

    response = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/reconcile/dry-run",
        headers=MUTATION_HEADERS,
        json={"mode": "fleet-merge"},
    )

    assert response.status_code == 400
    assert "select at least one node" in response.text


def test_reconcile_rejects_observe_and_local_modes(monkeypatch, tmp_path):
    baseline = tmp_path / "config/fleet-profiles/smart-wifi-manager/config.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text('{"profiles":[{"id":"field","ssid":"DemoField"}]}', encoding="utf-8")
    client = _client(_make_deps(tmp_path), monkeypatch)

    for mode in ("observe", "local"):
        response = client.post(
            "/api/v1/fleet/sidecars/smart-wifi-manager/reconcile/dry-run",
            headers=MUTATION_HEADERS,
            json={"node_ids": ["1"], "mode": mode},
        )

        assert response.status_code == 400
        assert "inspect-only" in response.text


def test_policy_requires_explicit_selected_nodes(monkeypatch, tmp_path):
    client = _client(_make_deps(tmp_path), monkeypatch)

    response = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/policy/dry-run",
        headers=MUTATION_HEADERS,
        json={"mode": "observe"},
    )

    assert response.status_code == 400
    assert "select at least one node" in response.text


def test_policy_apply_persists_selected_mode(monkeypatch, tmp_path):
    client = _client(_make_deps(tmp_path), monkeypatch)
    dry_run = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/policy/dry-run",
        headers=MUTATION_HEADERS,
        json={"node_ids": ["1"], "mode": "observe"},
    )
    assert dry_run.status_code == 200

    response = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/policy/apply",
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

    table = client.get("/api/v1/fleet/sidecars/smart-wifi-manager")
    assert table.status_code == 200
    assert table.json()["rows"][0]["mode"] == "observe"


def test_reconcile_dry_run_rejects_caller_supplied_baseline(monkeypatch, tmp_path):
    baseline = tmp_path / "config/fleet-profiles/smart-wifi-manager/config.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text('{"profiles":[{"id":"field","ssid":"DemoField"}]}', encoding="utf-8")
    client = _client(_make_deps(tmp_path), monkeypatch)

    response = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/reconcile/dry-run",
        headers=MUTATION_HEADERS,
        json={
            "node_ids": ["1"],
            "mode": "fleet-merge",
            "baseline": {"profiles": [{"id": "rogue", "ssid": "Rogue"}]},
        },
    )

    assert response.status_code == 422


def test_reconcile_apply_rejects_expired_dry_run(monkeypatch, tmp_path):
    baseline = tmp_path / "config/fleet-profiles/smart-wifi-manager/config.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text('{"profiles":[{"id":"field","ssid":"DemoField"}]}', encoding="utf-8")
    client = _client(_make_deps(tmp_path), monkeypatch)
    dry_run = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/reconcile/dry-run",
        headers=MUTATION_HEADERS,
        json={"node_ids": ["missing"], "mode": "fleet-merge"},
    )
    assert dry_run.status_code == 200
    fleet_sidecars._jobs[dry_run.json()["job_id"]]["created_at"] = int(time.time() * 1000) - fleet_sidecars.JOB_TTL_MS - 1

    response = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/reconcile/apply",
        headers=MUTATION_HEADERS,
        json={
            "dry_run_id": dry_run.json()["job_id"],
            "confirmation": {
                "acknowledged_risks": True,
                "confirmation_token": dry_run.json()["confirmation_token"],
            },
        },
    )

    assert response.status_code == 409
    assert "expired" in response.text


def test_reconcile_apply_rejects_changed_baseline(monkeypatch, tmp_path):
    baseline = tmp_path / "config/fleet-profiles/smart-wifi-manager/config.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text('{"profiles":[{"id":"field","ssid":"DemoField"}]}', encoding="utf-8")
    client = _client(_make_deps(tmp_path), monkeypatch)
    dry_run = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/reconcile/dry-run",
        headers=MUTATION_HEADERS,
        json={"node_ids": ["missing"], "mode": "fleet-merge"},
    )
    assert dry_run.status_code == 200
    baseline.write_text('{"profiles":[{"id":"field","ssid":"ChangedDemo"}]}', encoding="utf-8")

    response = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/reconcile/apply",
        headers=MUTATION_HEADERS,
        json={
            "dry_run_id": dry_run.json()["job_id"],
            "confirmation": {
                "acknowledged_risks": True,
                "confirmation_token": dry_run.json()["confirmation_token"],
            },
        },
    )

    assert response.status_code == 409
    assert "baseline changed" in response.text


def test_table_and_job_responses_redact_runtime_secret_fields(monkeypatch, tmp_path):
    runtime = {
        "tool": "smart-wifi-manager",
        "service_state": "active",
        "mode": "fleet-merge",
        "drift_state": "in_sync",
        "profile_summary": {
            "network_count": 1,
            "profiles": [{"id": "field", "ssid": "Demo Field", "password": "redacted-demo-value"}],
            "password": "redacted-demo-value",
            "password_file": "/root/secret",
        },
        "operator_state": {"summary": "ok", "token": "redacted-demo-value"},
        "last_apply_result": {"status": "success", "confirmation_token": "redacted-demo-value"},
    }
    client = _client(_make_deps(tmp_path, runtime=runtime), monkeypatch)

    table = client.get("/api/v1/fleet/sidecars/smart-wifi-manager")

    assert table.status_code == 200
    body = table.text
    assert "redacted-demo-value" not in body
    assert "/root/secret" not in body
    row = table.json()["rows"][0]
    assert row["profile_summary"]["password"] == "redacted"
    assert row["profile_summary"]["password_file"] == "external file"
    assert row["profiles"][0]["password"] == "redacted"
    assert row["operator_state"]["token"] == "redacted"
    assert row["last_apply_result"]["confirmation_token"] == "redacted"


def test_mavlink_node_table_exposes_sanitized_sources_and_endpoints(monkeypatch, tmp_path):
    deps = _make_deps(tmp_path)
    deps.git_status_data_all_drones = {
        "1": {
            "mavlink_runtime": {
                "tool": "mavlink-anywhere",
                "service_state": "active",
                "mode": "local",
                "drift_state": "unmanaged",
                "dashboard_access_mode": "direct",
                "dashboard_listen": "0.0.0.0:9070",
                "profile_summary": {
                    "source_count": 1,
                    "endpoint_count": 1,
                    "sources": [
                        {"name": "px4", "type": "UartEndpoint", "device": "/dev/ttyS0", "baud": 921600, "role": "source"},
                    ],
                    "endpoints": [
                        {
                            "name": "gcs_vpn",
                            "type": "UdpEndpoint",
                            "mode": "normal",
                            "address": "192.0.2.10",
                            "port": 24550,
                            "token": "redacted-demo-value",
                        },
                    ],
                },
            }
        }
    }
    client = _client(deps, monkeypatch)

    response = client.get("/api/v1/fleet/sidecars/mavlink-anywhere")

    assert response.status_code == 200
    assert "redacted-demo-value" not in response.text
    row = response.json()["rows"][0]
    assert row["profile_count"] == 1
    assert row["sources"][0]["name"] == "px4"
    assert row["endpoints"][0]["name"] == "gcs_vpn"
    assert row["endpoints"][0]["token"] == "redacted"


def test_sidecar_error_details_are_sanitized(monkeypatch, tmp_path):
    baseline = tmp_path / "config/fleet-profiles/smart-wifi-manager/config.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text('{"profiles":[{"id":"field","ssid":"DemoField"}]}', encoding="utf-8")
    client = _client(_make_deps(tmp_path), monkeypatch)

    class FakeResponse:
        status_code = 400
        text = '{"password":"redacted-demo-value"}'

        def json(self):
            return {"error": "bad profile", "password": "redacted-demo-value"}

    monkeypatch.setattr(fleet_sidecars.requests, "post", lambda *args, **kwargs: FakeResponse())

    response = client.post(
        "/api/v1/fleet/sidecars/smart-wifi-manager/reconcile/dry-run",
        headers=MUTATION_HEADERS,
        json={"node_ids": ["1"], "mode": "fleet-merge"},
    )

    assert response.status_code == 200
    assert "redacted-demo-value" not in response.text
    assert response.json()["results"]["1"]["error"]["password"] == "redacted"


def test_mavlink_baseline_ignores_hardware_input_overlay_for_hash(monkeypatch, tmp_path):
    baseline = tmp_path / "deployment/mavlink-anywhere/profile.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        """
        {
          "kind": "mavlink-anywhere-profile",
          "general": {"tcpServerPort": 5760, "reportStats": false},
          "endpoints": [
            {"name":"input","type":"UdpEndpoint","mode":"server","address":"0.0.0.0","port":14550,"enabled":true},
            {"name":"gcs_vpn","type":"UdpEndpoint","mode":"normal","address":"192.0.2.10","port":24550,"category":"gcs","enabled":true}
          ],
          "auth": {"token": "redacted-demo-value"}
        }
        """,
        encoding="utf-8",
    )
    deps = _make_deps(tmp_path)
    deps.git_status_data_all_drones = {
        "1": {
            "mavlink_runtime": {
                "tool": "mavlink-anywhere",
                "service_state": "active",
                "mode": "local",
                "drift_state": "in_sync",
                "dashboard_access_mode": "direct",
                "dashboard_listen": "0.0.0.0:9070",
            }
        }
    }
    client = _client(deps, monkeypatch)

    response = client.get("/api/v1/fleet/sidecars/mavlink-anywhere/baseline")

    assert response.status_code == 200
    data = response.json()
    assert data["present"] is True
    assert data["profile_count"] == 1
    assert [endpoint["name"] for endpoint in data["endpoints"]] == ["gcs_vpn"]
    assert "redacted-demo-value" not in response.text

    first_hash = data["hash"]
    baseline.write_text(
        baseline.read_text(encoding="utf-8").replace('"address":"0.0.0.0","port":14550', '"address":"127.0.0.1","port":14551'),
        encoding="utf-8",
    )
    second = client.get("/api/v1/fleet/sidecars/mavlink-anywhere/baseline")
    assert second.status_code == 200
    assert second.json()["hash"] == first_hash

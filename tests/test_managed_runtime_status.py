from src.managed_runtime_status import (
    build_connectivity_runtime_summary,
    build_mavlink_runtime_summary,
    read_git_sync_runtime_summary,
    resolve_dashboard_access,
)


def test_read_git_sync_runtime_summary_defaults_to_home_state_path(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    state_file = home_dir / ".local" / "state" / "mds" / "git-sync" / "last_result.env"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("status=success\nmessage=ok\ntimestamp_ms=1770000000000\n", encoding="utf-8")
    monkeypatch.delenv("MDS_GIT_SYNC_STATE_FILE", raising=False)
    monkeypatch.setenv("HOME", str(home_dir))

    result = read_git_sync_runtime_summary()

    assert result["status"] == "success"
    assert result["summary"] == "ok"


def test_resolve_dashboard_access_for_wildcard_listener_uses_node_ip():
    result = resolve_dashboard_access("10.0.0.21", "0.0.0.0:9070")

    assert result == {
        "dashboard_access_mode": "direct",
        "dashboard_url": "http://10.0.0.21:9070",
    }


def test_resolve_dashboard_access_for_loopback_listener_stays_local_only():
    result = resolve_dashboard_access("10.0.0.21", "127.0.0.1:9080")

    assert result == {
        "dashboard_access_mode": "local_only",
        "dashboard_url": None,
    }


def test_resolve_dashboard_access_for_explicit_remote_host_keeps_host():
    result = resolve_dashboard_access("10.0.0.21", "100.82.7.9:9070")

    assert result == {
        "dashboard_access_mode": "direct",
        "dashboard_url": "http://100.82.7.9:9070",
    }


def test_build_connectivity_runtime_summary_prefers_reconcile_dashboard_listen(monkeypatch, tmp_path):
    monkeypatch.delenv("MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN", raising=False)
    monkeypatch.setattr(
        "src.managed_runtime_status.read_reconcile_status",
        lambda repo_root, script_relative_path: {
            "status_source": "script",
            "backend": "smart-wifi-manager",
            "dashboard_listen": "0.0.0.0:9080",
            "service_status": "active",
        },
    )

    result = build_connectivity_runtime_summary(tmp_path)

    assert result["dashboard_listen"] == "0.0.0.0:9080"
    assert result["tool"] == "smart-wifi-manager"
    assert result["service_state"] == "active"
    assert result["drift_state"] in {"in_sync", "missing_fleet_baseline", "unmanaged"}


def test_build_mavlink_runtime_summary_reports_sidecar_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.managed_runtime_status.read_reconcile_status",
        lambda repo_root, script_relative_path: {
            "status_source": "script",
            "mode": "managed",
            "ref": "v3.0.8",
            "router_service": "active",
            "dashboard_service": "active",
            "desired_config_hash": "abc123",
            "applied_config_hash": "abc123",
            "config_hash_match": "true",
        },
    )

    result = build_mavlink_runtime_summary(tmp_path)

    assert result["tool"] == "mavlink-anywhere"
    assert result["mode"] == "managed"
    assert result["service_state"] == "active"
    assert result["drift_state"] == "in_sync"


def test_read_git_sync_runtime_summary_reads_local_state(monkeypatch, tmp_path):
    state_file = tmp_path / "last_result.env"
    state_file.write_text(
        "\n".join(
            [
                "status=success",
                "message=Git synchronization completed successfully",
                "timestamp_ms=1770000000000",
                "updated_units=coordinator.service,git_sync_mds.service",
                "service_reload_status=updated",
                "service_reload_message=Systemd unit updates were applied successfully.",
                "deferred_unit_actions=git_sync_mds.service:next_invocation,coordinator.service:manual_restart_required",
                "coordinator_restart_scheduled=true",
                "connectivity_reconcile_status=success",
                "mavlink_runtime_reconcile_status=warning",
                "requirements_update_status=updated",
                "recovery_action=clean_reclone",
                f"recovery_backup_path={tmp_path}/backup",
                "disk_available_status=ok",
                "disk_free_kb=424242",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MDS_GIT_SYNC_STATE_FILE", str(state_file))

    result = read_git_sync_runtime_summary()

    assert result["status"] == "success"
    assert result["service_reload_status"] == "updated"
    assert result["coordinator_restart_scheduled"] is True
    assert result["updated_units"] == ["coordinator.service", "git_sync_mds.service"]
    assert result["deferred_unit_actions"] == [
        "git_sync_mds.service:next_invocation",
        "coordinator.service:manual_restart_required",
    ]
    assert result["recovery_action"] == "clean_reclone"
    assert result["recovery_backup_path"] == f"{tmp_path}/backup"
    assert result["disk_available_status"] == "ok"
    assert result["disk_free_kb"] == 424242
    assert "Coordinator restart scheduled" in result["summary"]
    assert "Recovery: clean_reclone" in result["summary"]
    assert "Deferred apply: git_sync_mds.service:next_invocation, coordinator.service:manual_restart_required" in result["summary"]

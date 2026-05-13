from src.managed_runtime_status import (
    build_connectivity_runtime_summary,
    build_mavlink_runtime_summary,
    read_git_sync_runtime_summary,
    resolve_dashboard_access,
    smart_wifi_profile_payload_hash,
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
    result = resolve_dashboard_access("10.0.0.21", "198.51.100.20:9070")

    assert result == {
        "dashboard_access_mode": "direct",
        "dashboard_url": "http://198.51.100.20:9070",
    }


def test_build_connectivity_runtime_summary_prefers_reconcile_dashboard_listen(monkeypatch, tmp_path):
    profile = tmp_path / "wifi-profile.json"
    profile.write_text(
        '{"profiles":[{"id":"field","ssid":"Demo Field","priority":90,"password":"redacted-demo-value"}]}',
        encoding="utf-8",
    )
    monkeypatch.delenv("MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN", raising=False)
    monkeypatch.setattr(
        "src.managed_runtime_status.read_reconcile_status",
        lambda repo_root, script_relative_path: {
            "status_source": "script",
            "backend": "smart-wifi-manager",
            "dashboard_listen": "0.0.0.0:9080",
            "service_status": "active",
            "profile_path": str(profile),
        },
    )

    result = build_connectivity_runtime_summary(tmp_path)

    assert result["dashboard_listen"] == "0.0.0.0:9080"
    assert result["tool"] == "smart-wifi-manager"
    assert result["service_state"] == "active"
    assert result["drift_state"] in {"in_sync", "missing_fleet_baseline", "unmanaged"}
    assert result["profile_summary"]["network_count"] == 1
    assert result["profile_summary"]["profiles"][0]["ssid"] == "Demo Field"
    assert result["profile_summary"]["profiles"][0]["secret_status"] == "stored"
    assert "redacted-demo-value" not in str(result["profile_summary"])


def test_smart_wifi_profile_payload_hash_ignores_secret_values(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(
        '{"mode":"fleet-merge","profiles":[{"id":"field","ssid":"Demo Field","priority":90,"password":"one"}]}',
        encoding="utf-8",
    )
    second.write_text(
        '{"mode":"fleet-merge","profiles":[{"id":"field","ssid":"Demo Field","priority":90,"password":"two"}]}',
        encoding="utf-8",
    )

    assert smart_wifi_profile_payload_hash(first) == smart_wifi_profile_payload_hash(second)


def test_smart_wifi_profile_payload_hash_treats_service_mode_as_fleet_merge(tmp_path):
    fleet_profile = tmp_path / "fleet.json"
    service_profile = tmp_path / "service.json"
    fleet_profile.write_text(
        '{"mode":"fleet-merge","profiles":[{"id":"field","ssid":"Demo Field","priority":90,"password":"one"}]}',
        encoding="utf-8",
    )
    service_profile.write_text(
        '{"mode":"manage","profiles":[{"id":"field","ssid":"Demo Field","priority":90,"password":"two"}]}',
        encoding="utf-8",
    )

    assert smart_wifi_profile_payload_hash(fleet_profile) == smart_wifi_profile_payload_hash(service_profile)


def test_build_connectivity_runtime_summary_reports_outdated_not_local_extra_for_stale_apply(monkeypatch, tmp_path):
    profile = tmp_path / "wifi-profile.json"
    install_dir = tmp_path / "smart-wifi-manager"
    install_dir.mkdir()
    profile.write_text(
        '{"mode":"fleet-merge","profiles":[{"id":"field","ssid":"Demo Field","priority":90,"password":"redacted-demo-value"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.managed_runtime_status.read_reconcile_status",
        lambda repo_root, script_relative_path: {
            "status_source": "script",
            "backend": "smart-wifi-manager",
            "service_status": "active",
            "install_dir": str(install_dir),
            "profile_path": str(profile),
            "mode": "fleet-merge",
            "desired_config_hash": "desired-control",
            "applied_config_hash": "old-control",
            "config_hash_match": "false",
        },
    )

    result = build_connectivity_runtime_summary(tmp_path)

    assert result["drift_state"] == "outdated"
    assert result["desired_hash"] == result["local_hash"]
    assert result["applied_hash"] is None
    assert "redacted-demo-value" not in str(result)


def test_build_mavlink_runtime_summary_reports_sidecar_contract(monkeypatch, tmp_path):
    router_config = tmp_path / "main.conf"
    router_config.write_text(
        """
[UdpEndpoint input]
Mode = Server
Address = 0.0.0.0
Port = 14550

[UartEndpoint px4]
Device = /dev/ttyS0
Baud = 921600

[UdpEndpoint gcs_vpn]
Mode = Normal
Address = 192.0.2.10
Port = 24550
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("MAVLINK_ROUTER_CONFIG", str(router_config))
    monkeypatch.setattr(
        "src.managed_runtime_status.read_reconcile_status",
        lambda repo_root, script_relative_path: {
            "status_source": "script",
            "mode": "fleet-merge",
            "ref": "v3.0.9",
            "router_service": "active",
            "dashboard_service": "active",
            "desired_config_hash": "abc123",
            "applied_config_hash": "abc123",
            "config_hash_match": "true",
        },
    )

    result = build_mavlink_runtime_summary(tmp_path)

    assert result["tool"] == "mavlink-anywhere"
    assert result["mode"] == "fleet-merge"
    assert result["service_state"] == "active"
    assert result["drift_state"] == "in_sync"
    assert result["profile_summary"]["source_count"] == 2
    assert result["profile_summary"]["endpoint_count"] == 1
    assert [item["name"] for item in result["profile_summary"]["sources"]] == ["input", "px4"]
    assert result["profile_summary"]["endpoints"][0]["name"] == "gcs_vpn"


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
                "mavsdk_runtime_status=provisioned",
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
    assert result["mavsdk_runtime_status"] == "provisioned"
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
    assert "MAVSDK runtime: provisioned" in result["summary"]
    assert "Deferred apply: git_sync_mds.service:next_invocation, coordinator.service:manual_restart_required" in result["summary"]

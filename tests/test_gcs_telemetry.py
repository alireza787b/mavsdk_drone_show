from telemetry import _build_telemetry_unavailable_record, telemetry_data_all_drones


def test_build_telemetry_unavailable_record_marks_link_loss():
    telemetry_data_all_drones.clear()
    telemetry_data_all_drones["1"] = {
        "hw_id": "1",
        "pos_id": 1,
        "position_alt": 1234.5,
        "timestamp": 1700000000000,
        "update_time": 1700000000,
        "is_ready_to_arm": True,
        "readiness_status": "ready",
        "readiness_summary": "Ready to fly",
    }

    degraded = _build_telemetry_unavailable_record("1", "172.18.0.2", "Connection failed")

    assert degraded["hw_id"] == "1"
    assert degraded["pos_id"] == 1
    assert degraded["position_alt"] == 1234.5
    assert degraded["telemetry_available"] is False
    assert degraded["telemetry_error"] == "Connection failed"
    assert degraded["is_ready_to_arm"] is False
    assert degraded["readiness_status"] == "unknown"
    assert "Telemetry link is stale or lost" in degraded["readiness_summary"]
    assert degraded["preflight_blockers"]

from telemetry import _build_telemetry_unavailable_record, telemetry_data_all_drones


def test_gcs_telemetry_contract_preserves_native_landed_facts():
    from schemas import DroneTelemetry
    row = DroneTelemetry.model_validate({
        'pos_id': 1, 'hw_id': '1', 'state': 0, 'mission': 0, 'last_mission': 0,
        'position_lat': 48, 'position_long': 2, 'position_alt': 120,
        'velocity_north': 0, 'velocity_east': 0, 'velocity_down': 0, 'yaw': 0,
        'battery_voltage': 16, 'follow_mode': 0, 'update_time': 1000, 'timestamp': 1000,
        'flight_mode': 50593792, 'base_mode': 128, 'system_status': 4,
        'is_armed': True, 'is_ready_to_arm': True,
        'hdop': 0.7, 'vdop': 1.1, 'gps_fix_type': 3, 'satellites_visible': 10,
        'ip': '172.18.0.2',
        'landed_state': 2, 'landed_state_timestamp_ms': 999, 'landed_state_age_ms': 1,
    }).model_dump()
    assert row['landed_state'] == 2
    assert row['landed_state_timestamp_ms'] == 999
    assert row['landed_state_age_ms'] == 1


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

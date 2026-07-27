from agent_runtime.sitl_lifecycle import (
    evaluate_sitl_lifecycle_completion,
    sitl_lifecycle_evidence_roles,
)


def _operation(operation_type="create_instance", affected=None, metadata=None):
    return {
        "operation_id": "sitl-test",
        "operation_type": operation_type,
        "status": "succeeded",
        "affected_instances": affected if affected is not None else ["drone-1"],
        "metadata": metadata or {},
    }


def _instances(rows, *, reachable=True):
    return {
        "instances": rows,
        "total_instances": len(rows),
        "docker": {"daemon_reachable": reachable, "available": reachable},
    }


def _heartbeats(*ids, fresh=True, telemetry_recent=True):
    return {
        "heartbeats": [
            {
                "hw_id": drone_id,
                "online": True,
                "presence_state": "live",
                "presence": {
                    "fresh": fresh,
                    "telemetry_recent": telemetry_recent,
                },
            }
            for drone_id in ids
        ]
    }


def _telemetry(*ids, ready=True):
    return {
        "telemetry": {
            drone_id: {
                "telemetry_available": True,
                "is_ready_to_arm": ready,
                "is_armed": False,
                "flight_mode_name": "HOLD",
                "gps_fix_type": 3,
                "satellites_visible": 10,
                "battery_voltage": 16.2,
            }
            for drone_id in ids
        }
    }


def test_sitl_create_completion_requires_container_mavlink_and_preflight():
    result = evaluate_sitl_lifecycle_completion(
        operation=_operation(),
        instances_payload=_instances(
            [{"name": "drone-1", "state": "running", "health_status": "healthy", "hw_id": "1"}]
        ),
        heartbeats_payload=_heartbeats("1"),
        telemetry_payload=_telemetry("1"),
    )

    assert result["verified"] is True
    assert result["status"] == "verified"
    assert result["blockers"] == []
    assert result["instances"][0]["mavlink_live"] is True
    assert result["instances"][0]["preflight_ready"] is True


def test_sitl_create_completion_reports_the_current_readiness_stage():
    result = evaluate_sitl_lifecycle_completion(
        operation=_operation(),
        instances_payload=_instances([{"name": "drone-1", "state": "running", "hw_id": "1"}]),
        heartbeats_payload=_heartbeats("1"),
        telemetry_payload=_telemetry("1", ready=False),
    )

    assert result["verified"] is False
    assert result["label"] == "Preflight ready 0/1"
    assert result["blockers"] == ["preflight_not_ready"]


def test_sitl_create_completion_rejects_stale_presence_even_when_online_flag_is_true():
    result = evaluate_sitl_lifecycle_completion(
        operation=_operation(),
        instances_payload=_instances([{"name": "drone-1", "state": "running", "hw_id": "1"}]),
        heartbeats_payload=_heartbeats("1", fresh=False),
        telemetry_payload=_telemetry("1"),
    )

    assert result["verified"] is False
    assert result["instances"][0]["mavlink_live"] is False
    assert "mavlink_not_live" in result["blockers"]


def test_sitl_create_completion_rejects_stale_vehicle_telemetry():
    result = evaluate_sitl_lifecycle_completion(
        operation=_operation(),
        instances_payload=_instances([{"name": "drone-1", "state": "running", "hw_id": "1"}]),
        heartbeats_payload=_heartbeats("1", telemetry_recent=False),
        telemetry_payload=_telemetry("1"),
    )

    assert result["verified"] is False
    assert result["instances"][0]["mavlink_live"] is False
    assert "mavlink_not_live" in result["blockers"]


def test_sitl_remove_completion_uses_absence_from_managed_inventory():
    result = evaluate_sitl_lifecycle_completion(
        operation=_operation("remove_instances", affected=["drone-1"]),
        instances_payload=_instances([]),
    )

    assert result["verified"] is True
    assert result["status"] == "verified"
    assert "absent" in result["summary"]


def test_sitl_remove_completion_requires_only_instance_inventory():
    roles = sitl_lifecycle_evidence_roles(
        _operation("remove_instances", affected=["drone-1"])
    )

    assert roles == ("instances",)


def test_sitl_create_completion_requires_runtime_and_vehicle_evidence():
    assert sitl_lifecycle_evidence_roles(_operation()) == (
        "instances",
        "heartbeats",
        "telemetry",
    )


def test_sitl_reconcile_zero_verifies_empty_inventory():
    result = evaluate_sitl_lifecycle_completion(
        operation=_operation("reconcile_fleet", affected=[], metadata={"target_count": 0}),
        instances_payload=_instances([]),
    )

    assert result["verified"] is True
    assert result["label"] == "SITL fleet is empty"


def test_sitl_completion_fails_closed_without_affected_instance_identity():
    result = evaluate_sitl_lifecycle_completion(
        operation=_operation(affected=[]),
        instances_payload=_instances([]),
    )

    assert result["verified"] is False
    assert result["status"] == "unavailable"
    assert result["blockers"] == ["affected_instances_missing"]

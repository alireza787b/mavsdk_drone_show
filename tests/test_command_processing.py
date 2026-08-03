"""Drone-side command installation and telemetry truth tests.

Command envelope validation belongs to :mod:`src.command_contract`; fleet
admission and fan-out belong to the GCS submission tests.  This module stays
focused on the node transaction that installs an already validated command.
"""

import os
import time
from unittest.mock import Mock

import pytest

from src.drone_config import DroneConfig
from src.drone_communicator import DroneCommunicator
from src.enums import Mission, State


def create_mock_drone_config():
    """Return the smallest state object accepted by ``DroneCommunicator``."""
    drone_config = Mock(spec=DroneConfig)
    drone_config.state = State.IDLE.value
    drone_config.mission = Mission.NONE.value
    drone_config.last_mission = Mission.NONE.value
    drone_config.trigger_time = 0
    drone_config.config = {"pos_id": 1, "hw_id": "1"}
    drone_config.hw_id = "1"
    drone_config.is_armed = False
    drone_config.is_ready_to_arm = True
    drone_config.global_position_valid = False
    drone_config.global_position_timestamp_ms = 0
    drone_config.gps_raw_timestamp_ms = 0
    drone_config.position_source = "unavailable"
    return drone_config


def communicator_params(**overrides):
    values = {
        "enable_udp_telemetry": False,
        "enable_default_subscriptions": False,
        "default_takeoff_alt": 10.0,
        "max_takeoff_alt": 50.0,
        "command_runtime_dir": None,
    }
    values.update(overrides)
    return Mock(**values)


@pytest.mark.unit
@pytest.mark.command
class TestDroneCommandEndpoint:
    def test_empty_payload_is_rejected_by_typed_boundary(self, test_client):
        response = test_client.post("/api/v1/drone/commands", json={})
        assert response.status_code == 422

    def test_legacy_camel_case_envelope_is_rejected(self, test_client):
        response = test_client.post(
            "/api/v1/drone/commands",
            json={"missionType": Mission.LAND.value, "triggerTime": 0},
        )
        assert response.status_code == 422


@pytest.mark.unit
@pytest.mark.command
class TestDroneCommandInstallation:
    def test_update_code_preserves_runtime_branch(self):
        drone_config = create_mock_drone_config()
        drone_config.update_branch = None
        communicator = DroneCommunicator(drone_config, communicator_params(), {})

        result = communicator.process_command(
            {
                "mission_type": Mission.UPDATE_CODE.value,
                "trigger_time": 0,
                "update_branch": "main-candidate",
            }
        )

        assert result.committed is True
        assert drone_config.update_branch == "main-candidate"
        assert drone_config.mission == Mission.UPDATE_CODE.value
        assert drone_config.state == State.MISSION_READY.value

    def test_takeoff_installs_canonical_payload_atomically(self):
        drone_config = create_mock_drone_config()
        communicator = DroneCommunicator(drone_config, communicator_params(), {})

        result = communicator.process_command(
            {
                "mission_type": Mission.TAKE_OFF.value,
                "trigger_time": 0,
                "takeoff_altitude": 12.5,
                "command_id": "cmd-takeoff-1",
            }
        )

        assert result.committed is True
        assert result.command_id == "cmd-takeoff-1"
        assert drone_config.mission == Mission.TAKE_OFF.value
        assert drone_config.trigger_time == 0
        assert drone_config.takeoff_altitude == 12.5
        assert drone_config.current_command_id == "cmd-takeoff-1"
        assert drone_config.state == State.MISSION_READY.value

    def test_precision_move_writes_normalized_runtime_payload(self):
        drone_config = create_mock_drone_config()
        communicator = DroneCommunicator(drone_config, communicator_params(), {})

        result = communicator.process_command(
            {
                "mission_type": Mission.PRECISION_MOVE.value,
                "trigger_time": 0,
                "precision_move": {
                    "frame": "body",
                    "translation_m": {"forward": 2.0, "right": 0.5, "up": 1.0},
                    "yaw": {"mode": "relative_delta", "degrees": 30.0},
                    "speed_m_s": 1.0,
                    "position_tolerance_m": 0.15,
                    "yaw_tolerance_deg": 5.0,
                    "settle_time_sec": 1.0,
                    "timeout_sec": 30.0,
                    "hold_mode": "px4_hold",
                },
            }
        )

        assert result.committed is True
        assert drone_config.mission == Mission.PRECISION_MOVE.value
        assert drone_config.state == State.MISSION_READY.value
        assert os.path.isfile(drone_config.precision_move_request_file)


def _populate_fresh_telemetry(drone_config):
    drone_config.home_position = {"lat": 35.0, "long": 51.0, "alt": 1278.0}
    drone_config.pos_id = 1
    drone_config.detected_pos_id = 1
    drone_config.position = {"lat": 35.0, "long": 51.0, "alt": 1278.0}
    drone_config.velocity = {"north": 0.0, "east": 0.0, "down": 0.0}
    drone_config.yaw = 0.0
    drone_config.battery = 16.2
    drone_config.last_update_timestamp = int(time.time())
    drone_config.custom_mode = 262147
    drone_config.base_mode = 81
    drone_config.system_status = 4
    drone_config.readiness_checks = []
    drone_config.preflight_blockers = []
    drone_config.preflight_warnings = []
    drone_config.status_messages = []
    drone_config.preflight_last_update = int(time.time() * 1000)
    drone_config.hdop = 0.8
    drone_config.vdop = 1.1
    drone_config.gps_fix_type = 3
    drone_config.satellites_visible = 12


@pytest.mark.unit
@pytest.mark.command
class TestDroneTelemetryTruth:
    def test_home_status_reports_px4_truth_not_fallback_cache(self):
        drone_config = create_mock_drone_config()
        _populate_fresh_telemetry(drone_config)
        drone_config.px4_home_position_set = False
        drone_config.home_position_source = "fallback_position"
        communicator = DroneCommunicator(drone_config, communicator_params(), {})

        drone_state = communicator.get_drone_state()

        assert drone_state["home_position_set"] is False
        assert drone_state["home_position_source"] == "fallback_position"

    def test_stale_local_mavlink_cannot_remain_operator_ready(self):
        drone_config = create_mock_drone_config()
        _populate_fresh_telemetry(drone_config)
        drone_config.px4_home_position_set = True
        drone_config.home_position_source = "px4"
        drone_config.last_update_timestamp = int(time.time()) - 60
        communicator = DroneCommunicator(
            drone_config,
            communicator_params(LOCAL_MAVLINK_STALE_TIMEOUT_SEC=15),
            {},
        )

        drone_state = communicator.get_drone_state()

        assert drone_state["telemetry_available"] is False
        assert "stale" in drone_state["telemetry_error"].lower()
        assert drone_state["is_ready_to_arm"] is False
        assert drone_state["readiness_status"] == "unknown"
        assert drone_state["preflight_blockers"]

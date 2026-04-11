import asyncio
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import quickscout_mission as qsm


def _stream_once(item):
    async def _gen():
        yield item

    return _gen()


def _stream_many(items):
    async def _gen():
        for item in items:
            yield item

    return _gen()


def _never_stream():
    async def _gen():
        while True:
            await asyncio.sleep(3600)
            yield None  # pragma: no cover - defensive only

    return _gen()


class _FakeMissionItem:
    class CameraAction:
        NONE = "none"
        START_PHOTO_INTERVAL = "start"
        STOP_PHOTO_INTERVAL = "stop"

    class VehicleAction:
        NONE = "none"
        TAKEOFF = "takeoff"

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeMissionPlan:
    def __init__(self, items):
        self.items = items


class _FakeDrone:
    def __init__(self):
        self.connect = AsyncMock()
        self.core = SimpleNamespace(
            connection_state=lambda: _stream_once(SimpleNamespace(is_connected=True))
        )
        self.telemetry = SimpleNamespace(
            health=lambda: _stream_once(
                SimpleNamespace(
                    is_armable=True,
                    is_global_position_ok=True,
                    is_home_position_ok=True,
                    is_local_position_ok=True,
                    is_gyrometer_calibration_ok=True,
                    is_accelerometer_calibration_ok=True,
                    is_magnetometer_calibration_ok=True,
                )
            ),
            home=lambda: _stream_once(
                SimpleNamespace(
                    latitude_deg=35.7243906,
                    longitude_deg=51.2756090,
                    absolute_altitude_m=1278.238,
                )
            ),
            position=lambda: _stream_many(
                [
                    SimpleNamespace(
                        latitude_deg=35.7243906,
                        longitude_deg=51.2756090,
                        absolute_altitude_m=1278.238,
                        relative_altitude_m=0.0,
                    ),
                    SimpleNamespace(
                        latitude_deg=35.7244000,
                        longitude_deg=51.2756200,
                        absolute_altitude_m=1281.238,
                        relative_altitude_m=3.0,
                    ),
                    SimpleNamespace(
                        latitude_deg=35.7244500,
                        longitude_deg=51.2756700,
                        absolute_altitude_m=1281.538,
                        relative_altitude_m=3.3,
                    ),
                ]
            ),
        )
        self.mission = SimpleNamespace(
            upload_mission=AsyncMock(),
            start_mission=AsyncMock(),
            mission_progress=lambda: _stream_once(SimpleNamespace(current=0, total=1)),
            is_mission_finished=AsyncMock(side_effect=[True]),
        )
        self.action = SimpleNamespace(
            arm=AsyncMock(),
            return_to_launch=AsyncMock(),
            land=AsyncMock(),
            disarm=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_run_mission_bootstraps_canonical_mavsdk_server_and_stops_it(monkeypatch):
    args = SimpleNamespace(
        waypoints_file="/tmp/quickscout.json",
        mission_id="mission-1",
        hw_id="1",
        return_behavior="hold_position",
        gcs_url="http://127.0.0.1:5000",
    )
    fake_server = MagicMock()
    fake_led = MagicMock()
    fake_drone = _FakeDrone()

    monkeypatch.setattr(qsm, "load_waypoints", MagicMock(return_value=[{
        "lat": 35.7233,
        "lng": 51.2754,
        "alt_msl": 1298.0,
        "is_survey_leg": False,
        "speed_ms": 4.0,
        "yaw_deg": None,
    }]))
    monkeypatch.setattr(qsm, "start_mavsdk_server", MagicMock(return_value=fake_server))
    monkeypatch.setattr(qsm, "stop_mavsdk_server", MagicMock())
    monkeypatch.setattr(qsm, "System", MagicMock(return_value=fake_drone))
    monkeypatch.setattr(qsm, "MissionItem", _FakeMissionItem)
    monkeypatch.setattr(qsm, "MissionPlan", _FakeMissionPlan)
    monkeypatch.setattr(qsm, "report_progress", MagicMock())
    monkeypatch.setattr(qsm.LEDController, "get_instance", MagicMock(return_value=fake_led))
    monkeypatch.setattr(qsm, "wait_for_local_startup_ready", AsyncMock(return_value={"readiness_status": "ready"}))
    monkeypatch.setattr(qsm.Params, "QUICKSCOUT_PROGRESS_REPORT_INTERVAL_SEC", 0.01, raising=False)
    monkeypatch.setattr(qsm.Params, "QUICKSCOUT_PROGRESS_STREAM_TIMEOUT_SEC", 0.01, raising=False)
    monkeypatch.setattr(qsm.Params, "QUICKSCOUT_FINISHED_CHECK_TIMEOUT_SEC", 0.05, raising=False)
    monkeypatch.setattr(qsm.Params, "COMMAND_TRACKING_QUICKSCOUT_TIMEOUT_SEC", 30, raising=False)
    monkeypatch.setattr(
        qsm,
        "get_local_home_position",
        MagicMock(return_value={"latitude": 35.7243906, "longitude": 51.2756090, "altitude": 1278.238}),
    )

    result = await qsm.run_mission(args)

    assert result == 0
    qsm.start_mavsdk_server.assert_called_once_with(
        qsm.Params.DEFAULT_GRPC_PORT,
        qsm.Params.mavsdk_port,
    )
    fake_drone.connect.assert_awaited_once_with(system_address=f"udp://:{qsm.Params.mavsdk_port}")
    fake_drone.mission.upload_mission.assert_awaited_once()
    uploaded_plan = fake_drone.mission.upload_mission.await_args.args[0]
    assert math.isnan(uploaded_plan.items[0].kwargs["yaw_deg"])
    assert uploaded_plan.items[0].kwargs["vehicle_action"] == _FakeMissionItem.VehicleAction.TAKEOFF
    fake_drone.action.arm.assert_awaited_once()
    fake_drone.mission.start_mission.assert_awaited_once()
    fake_drone.mission.is_mission_finished.assert_awaited()
    qsm.stop_mavsdk_server.assert_called_once_with(fake_server)


@pytest.mark.asyncio
async def test_run_mission_fails_fast_when_connection_confirmation_times_out(monkeypatch):
    args = SimpleNamespace(
        waypoints_file="/tmp/quickscout.json",
        mission_id="mission-2",
        hw_id="1",
        return_behavior="hold_position",
        gcs_url="http://127.0.0.1:5000",
    )
    fake_server = MagicMock()
    fake_led = MagicMock()
    fake_drone = _FakeDrone()

    monkeypatch.setattr(qsm, "load_waypoints", MagicMock(return_value=[{
        "lat": 35.7233,
        "lng": 51.2754,
        "alt_msl": 1298.0,
        "is_survey_leg": False,
        "speed_ms": 4.0,
    }]))
    monkeypatch.setattr(qsm, "start_mavsdk_server", MagicMock(return_value=fake_server))
    monkeypatch.setattr(qsm, "stop_mavsdk_server", MagicMock())
    monkeypatch.setattr(qsm, "System", MagicMock(return_value=fake_drone))
    monkeypatch.setattr(qsm, "MissionItem", _FakeMissionItem)
    monkeypatch.setattr(qsm, "MissionPlan", _FakeMissionPlan)
    monkeypatch.setattr(qsm, "report_progress", MagicMock())
    monkeypatch.setattr(qsm.LEDController, "get_instance", MagicMock(return_value=fake_led))
    monkeypatch.setattr(qsm, "wait_for_drone_connection", AsyncMock(side_effect=TimeoutError("no connection")))
    monkeypatch.setattr(qsm, "wait_for_local_startup_ready", AsyncMock(return_value={"readiness_status": "ready"}))
    monkeypatch.setattr(
        qsm,
        "get_local_home_position",
        MagicMock(return_value={"latitude": 35.7243906, "longitude": 51.2756090, "altitude": 1278.238}),
    )

    result = await qsm.run_mission(args)

    assert result == 1
    fake_drone.connect.assert_awaited_once_with(system_address=f"udp://:{qsm.Params.mavsdk_port}")
    qsm.stop_mavsdk_server.assert_called_once_with(fake_server)


@pytest.mark.asyncio
async def test_monitor_active_mission_finishes_without_progress_callbacks(monkeypatch):
    report_progress = MagicMock()
    fake_drone = _FakeDrone()
    fake_drone.mission.mission_progress = lambda: _never_stream()
    fake_drone.mission.is_mission_finished = AsyncMock(side_effect=[False, True])
    fake_drone.telemetry.position = lambda: _stream_many(
        [
            SimpleNamespace(
                latitude_deg=35.7244000,
                longitude_deg=51.2756200,
                absolute_altitude_m=1281.238,
                relative_altitude_m=3.0,
            ),
            SimpleNamespace(
                latitude_deg=35.7244500,
                longitude_deg=51.2756700,
                absolute_altitude_m=1281.538,
                relative_altitude_m=3.3,
            ),
        ]
    )

    monkeypatch.setattr(qsm, "report_progress", report_progress)
    monkeypatch.setattr(qsm.Params, "QUICKSCOUT_PROGRESS_REPORT_INTERVAL_SEC", 0.01, raising=False)
    monkeypatch.setattr(qsm.Params, "QUICKSCOUT_PROGRESS_STREAM_TIMEOUT_SEC", 0.01, raising=False)
    monkeypatch.setattr(qsm.Params, "QUICKSCOUT_FINISHED_CHECK_TIMEOUT_SEC", 0.05, raising=False)
    monkeypatch.setattr(qsm.Params, "COMMAND_TRACKING_QUICKSCOUT_TIMEOUT_SEC", 30, raising=False)

    result = await qsm._monitor_active_mission(
        fake_drone,
        gcs_url="http://127.0.0.1:5000",
        mission_id="mission-3",
        hw_id="1",
        total_waypoints=4,
        startup_position=SimpleNamespace(
            latitude_deg=35.7243906,
            longitude_deg=51.2756090,
            absolute_altitude_m=1281.238,
            relative_altitude_m=3.0,
        ),
    )

    assert result["current"] == 4
    assert result["total"] == 4
    assert result["distance_covered_m"] > 0
    fake_drone.mission.is_mission_finished.assert_awaited()
    assert report_progress.call_count >= 1

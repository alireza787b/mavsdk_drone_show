from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import quickscout_mission as qsm


def _stream_once(item):
    async def _gen():
        yield item

    return _gen()


class _FakeMissionItem:
    class CameraAction:
        NONE = "none"
        START_PHOTO_INTERVAL = "start"
        STOP_PHOTO_INTERVAL = "stop"

    class VehicleAction:
        NONE = "none"

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
                SimpleNamespace(is_global_position_ok=True, is_home_position_ok=True)
            ),
            home=lambda: _stream_once(
                SimpleNamespace(
                    latitude_deg=35.7243906,
                    longitude_deg=51.2756090,
                    absolute_altitude_m=1278.238,
                )
            ),
        )
        self.mission = SimpleNamespace(
            upload_mission=AsyncMock(),
            start_mission=AsyncMock(),
            mission_progress=lambda: _stream_once(SimpleNamespace(current=0, total=1)),
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
    }]))
    monkeypatch.setattr(qsm, "start_mavsdk_server", MagicMock(return_value=fake_server))
    monkeypatch.setattr(qsm, "stop_mavsdk_server", MagicMock())
    monkeypatch.setattr(qsm, "System", MagicMock(return_value=fake_drone))
    monkeypatch.setattr(qsm, "MissionItem", _FakeMissionItem)
    monkeypatch.setattr(qsm, "MissionPlan", _FakeMissionPlan)
    monkeypatch.setattr(qsm, "report_progress", MagicMock())
    monkeypatch.setattr(qsm.LEDController, "get_instance", MagicMock(return_value=fake_led))

    result = await qsm.run_mission(args)

    assert result == 0
    qsm.start_mavsdk_server.assert_called_once_with(
        qsm.Params.DEFAULT_GRPC_PORT,
        qsm.Params.mavsdk_port,
    )
    fake_drone.connect.assert_awaited_once_with(system_address=f"udp://:{qsm.Params.mavsdk_port}")
    fake_drone.mission.upload_mission.assert_awaited_once()
    fake_drone.action.arm.assert_awaited_once()
    fake_drone.mission.start_mission.assert_awaited_once()
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

    result = await qsm.run_mission(args)

    assert result == 1
    fake_drone.connect.assert_awaited_once_with(system_address=f"udp://:{qsm.Params.mavsdk_port}")
    qsm.stop_mavsdk_server.assert_called_once_with(fake_server)

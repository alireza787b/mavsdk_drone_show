import sys
import types
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

for module_name in ("aiogrpc", "psutil", "requests"):
    sys.modules.setdefault(module_name, MagicMock())
sys.modules.setdefault(
    "tenacity",
    types.SimpleNamespace(
        retry=lambda *args, **kwargs: (lambda func: func),
        stop_after_attempt=lambda *args, **kwargs: None,
        wait_fixed=lambda *args, **kwargs: None,
    ),
)

import swarm_trajectory_mission as stm


async def _stream_once(value):
    yield value


async def _stream_once_position(relative_altitude_m):
    yield types.SimpleNamespace(relative_altitude_m=relative_altitude_m)


async def _stream_once_position_full(relative_altitude_m, absolute_altitude_m):
    yield types.SimpleNamespace(
        relative_altitude_m=relative_altitude_m,
        absolute_altitude_m=absolute_altitude_m,
    )


def _stream_side_effect(values):
    iterator = iter(values)

    def _factory():
        async def _stream():
            yield next(iterator)

        return _stream()

    return _factory


@pytest.mark.asyncio
async def test_pre_flight_checks_prefers_px4_global_origin_reference(monkeypatch):
    drone = MagicMock()
    health_ok = types.SimpleNamespace(
        is_global_position_ok=True,
        is_home_position_ok=True,
    )
    drone.telemetry.health.return_value = _stream_once(health_ok)
    drone.telemetry.get_gps_global_origin = AsyncMock(
        return_value=types.SimpleNamespace(
            latitude_deg=35.7001,
            longitude_deg=51.3999,
            altitude_m=1278.4,
        )
    )

    led_controller = MagicMock()
    monkeypatch.setattr(stm.LEDController, "get_instance", MagicMock(return_value=led_controller))
    monkeypatch.setattr(stm.Params, "REQUIRE_GLOBAL_POSITION", True)
    monkeypatch.setattr(stm.Params, "PRE_FLIGHT_TIMEOUT", 5)

    reference = await stm.pre_flight_checks(drone)

    assert reference == {
        "latitude": 35.7001,
        "longitude": 51.3999,
        "altitude": 1278.4,
        "source": "gps_global_origin",
    }


@pytest.mark.asyncio
async def test_pre_flight_checks_falls_back_to_current_position_reference(monkeypatch):
    drone = MagicMock()
    health_ok = types.SimpleNamespace(
        is_global_position_ok=True,
        is_home_position_ok=True,
    )
    drone.telemetry.health.return_value = _stream_once(health_ok)
    drone.telemetry.get_gps_global_origin = AsyncMock(
        side_effect=stm.mavsdk.telemetry.TelemetryError(
            types.SimpleNamespace(result="FAILED", result_str="origin unavailable"),
            "get_gps_global_origin()",
        )
    )
    drone.telemetry.position.return_value = _stream_once(
        types.SimpleNamespace(
            latitude_deg=35.701,
            longitude_deg=51.401,
            absolute_altitude_m=1280.25,
        )
    )

    led_controller = MagicMock()
    monkeypatch.setattr(stm.LEDController, "get_instance", MagicMock(return_value=led_controller))
    monkeypatch.setattr(stm.Params, "REQUIRE_GLOBAL_POSITION", True)
    monkeypatch.setattr(stm.Params, "PRE_FLIGHT_TIMEOUT", 5)

    reference = await stm.pre_flight_checks(drone)

    assert reference == {
        "latitude": 35.701,
        "longitude": 51.401,
        "altitude": 1280.25,
        "source": "fallback_position",
    }


def test_read_config_uses_swarm_trajectory_processed_folder(monkeypatch):
    config_json = """
    {
      "drones": [
        {"hw_id": 1, "pos_id": 1, "ip": "127.0.0.1", "mavlink_port": 14540}
      ]
    }
    """
    trajectory_csv = "t,px,py\n0,1.5,2.5\n"
    opened_paths = []

    monkeypatch.setattr(stm, "HW_ID", 1)

    def fake_exists(path):
        return path.endswith("config.json") or path.endswith("swarm_trajectory/processed/Drone 1.csv")

    def fake_open(path, *args, **kwargs):
        opened_paths.append(path)
        if path.endswith("config.json"):
            return StringIO(config_json)
        if path.endswith("swarm_trajectory/processed/Drone 1.csv"):
            return StringIO(trajectory_csv)
        raise FileNotFoundError(path)

    monkeypatch.setattr(stm.os.path, "exists", fake_exists)
    with patch("builtins.open", side_effect=fake_open):
        drone = stm.read_config("config.json")

    assert drone is not None
    assert drone.pos_id == 1
    assert any(path.endswith("swarm_trajectory/processed/Drone 1.csv") for path in opened_paths)
    assert not any("/swarm/processed/" in path for path in opened_paths)


@pytest.mark.asyncio
async def test_wait_for_rtl_completion_returns_after_touchdown_and_disarm():
    drone = MagicMock()
    drone.telemetry.landed_state.return_value = _stream_once(stm.LandedState.ON_GROUND)
    drone.telemetry.armed.return_value = _stream_once(False)

    await stm.wait_for_rtl_completion(drone)


@pytest.mark.asyncio
async def test_has_reached_initial_climb_altitude_requires_real_height_when_available():
    drone = MagicMock()
    drone.telemetry.position.return_value = _stream_once_position(1.0)

    assert await stm._has_reached_initial_climb_altitude(drone, 4.0) is False


@pytest.mark.asyncio
async def test_has_reached_initial_climb_altitude_accepts_launch_referenced_absolute_gain():
    drone = MagicMock()
    drone.telemetry.position.return_value = _stream_once_position_full(None, 1285.5)

    assert await stm._has_reached_initial_climb_altitude(
        drone,
        4.0,
        launch_altitude_m=1280.0,
    ) is True


@pytest.mark.asyncio
async def test_has_reached_initial_climb_altitude_accepts_missing_telemetry():
    drone = MagicMock()

    async def _broken_stream():
        raise RuntimeError("telemetry unavailable")
        yield  # pragma: no cover

    drone.telemetry.position.return_value = _broken_stream()

    assert await stm._has_reached_initial_climb_altitude(drone, 4.0) is True


@pytest.mark.asyncio
async def test_perform_swarm_trajectory_raises_when_initial_climb_stalls(monkeypatch):
    drone = MagicMock()
    drone.offboard.set_velocity_ned = AsyncMock()
    drone.offboard.set_velocity_body = AsyncMock()
    drone.offboard.set_position_global = AsyncMock()

    led_controller = MagicMock()
    monkeypatch.setattr(stm.LEDController, "get_instance", MagicMock(return_value=led_controller))
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_INITIAL_CLIMB_TIME", 0.0)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_INITIAL_CLIMB_SPEED", 1.0)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_INITIAL_CLIMB_HEIGHT", 5.0)
    monkeypatch.setattr(stm.Params, "TAKEOFF_ALTITUDE_CONFIRM_TIMEOUT_SEC", 0.2)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_VERBOSE_LOGGING", False)

    fake_now = {"value": 100.0}

    def _fake_time():
        fake_now["value"] += 0.1
        return fake_now["value"]

    waypoints = [
        (0.0, 35.0, 51.0, 1280.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 90.0, 0, 255, 255, 255),
        (1.0, 35.0, 51.0, 1281.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 90.0, 0, 255, 255, 255),
    ]

    with patch.object(stm.time, "time", side_effect=_fake_time):
        with patch.object(
            stm,
            "_get_initial_climb_altitude_sample",
            new=AsyncMock(return_value={"relative_altitude_m": 0.0, "absolute_altitude_gain_m": 0.0}),
        ) as climb_sample_mock:
            with patch.object(stm.asyncio, "sleep", new=AsyncMock()):
                with patch.object(stm, "execute_end_behavior", new=AsyncMock()) as execute_end_behavior:
                    with pytest.raises(RuntimeError, match="Initial climb did not achieve the required altitude gain"):
                        await stm.perform_swarm_trajectory(
                            drone,
                            waypoints,
                            global_reference=None,
                            start_time=100.0,
                            launch_lat=35.0,
                            launch_lon=51.0,
                            launch_alt=1280.0,
                            end_behavior="return_home",
                        )

    assert climb_sample_mock.await_count >= 1
    drone.offboard.set_position_global.assert_not_awaited()
    execute_end_behavior.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_end_behavior_return_home_waits_for_rtl_completion():
    drone = MagicMock()

    with patch.object(stm, "stop_offboard_mode", new=AsyncMock()) as stop_offboard_mode:
        with patch.object(stm, "engage_rtl", new=AsyncMock(return_value=True)) as engage_rtl:
            with patch.object(stm.asyncio, "sleep", new=AsyncMock()):
                with patch.object(stm, "wait_for_rtl_completion", new=AsyncMock()) as wait_for_rtl_completion:
                    await stm.execute_end_behavior(
                        drone,
                        "return_home",
                        launch_lat=35.0,
                        launch_lon=51.0,
                        launch_alt=1200.0,
                    )

    stop_offboard_mode.assert_awaited_once()
    engage_rtl.assert_awaited_once_with(drone)
    wait_for_rtl_completion.assert_awaited_once_with(drone, home_lat=35.0, home_lon=51.0)


@pytest.mark.asyncio
async def test_execute_end_behavior_return_home_falls_back_to_land_when_rtl_never_engages(monkeypatch):
    drone = MagicMock()
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_ENGAGE_MAX_ATTEMPTS", 2)

    with patch.object(stm, "stop_offboard_mode", new=AsyncMock()) as stop_offboard_mode:
        with patch.object(stm, "engage_rtl", new=AsyncMock(side_effect=[False, False])) as engage_rtl:
            with patch.object(stm.asyncio, "sleep", new=AsyncMock()):
                with patch.object(stm, "perform_landing", new=AsyncMock()) as perform_landing:
                    with patch.object(stm, "wait_for_rtl_completion", new=AsyncMock()) as wait_for_rtl_completion:
                        await stm.execute_end_behavior(
                            drone,
                            "return_home",
                            launch_lat=35.0,
                            launch_lon=51.0,
                            launch_alt=1200.0,
                        )

    stop_offboard_mode.assert_awaited_once()
    assert engage_rtl.await_count == 2
    perform_landing.assert_awaited_once_with(drone)
    wait_for_rtl_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_end_behavior_raises_when_all_recoveries_fail():
    drone = MagicMock()

    with patch.object(stm, "stop_offboard_mode", new=AsyncMock(side_effect=RuntimeError("offboard stop failed"))):
        with patch.object(stm, "controlled_landing", new=AsyncMock(side_effect=RuntimeError("land failed"))) as controlled_landing:
            with patch.object(stm, "emergency_rtl_sequence", new=AsyncMock(side_effect=RuntimeError("rtl failed"))) as emergency_rtl:
                with patch.object(stm, "emergency_land_sequence", new=AsyncMock(side_effect=RuntimeError("emergency land failed"))) as emergency_land:
                    with pytest.raises(
                        RuntimeError,
                        match="all recovery attempts were exhausted",
                    ):
                        await stm.execute_end_behavior(
                            drone,
                            "return_home",
                            launch_lat=35.0,
                            launch_lon=51.0,
                            launch_alt=1200.0,
                        )

    controlled_landing.assert_awaited_once_with(drone)
    emergency_rtl.assert_awaited_once_with(drone)
    emergency_land.assert_awaited_once_with(drone)


@pytest.mark.asyncio
async def test_arming_and_starting_offboard_mode_uses_shared_prearm_gate(monkeypatch):
    drone = MagicMock()
    drone.action.hold = AsyncMock()
    drone.offboard.set_velocity_body = AsyncMock()
    drone.offboard.start = AsyncMock()

    led_controller = MagicMock()
    monkeypatch.setattr(stm.LEDController, "get_instance", MagicMock(return_value=led_controller))
    monkeypatch.setattr(stm.Params, "REQUIRE_GLOBAL_POSITION", False)

    with patch.object(stm, "arm_with_preflight_gate", new=AsyncMock()) as arm_with_preflight_gate:
        await stm.arming_and_starting_offboard_mode(drone, global_reference=None)

    drone.action.hold.assert_awaited_once()
    arm_with_preflight_gate.assert_awaited_once()
    assert arm_with_preflight_gate.await_args.kwargs["require_global_position"] is False
    drone.offboard.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_arming_and_starting_offboard_mode_skips_drift_for_fallback_reference(monkeypatch):
    drone = MagicMock()
    drone.action.hold = AsyncMock()
    drone.offboard.set_velocity_body = AsyncMock()
    drone.offboard.start = AsyncMock()

    led_controller = MagicMock()
    monkeypatch.setattr(stm.LEDController, "get_instance", MagicMock(return_value=led_controller))
    monkeypatch.setattr(stm.Params, "REQUIRE_GLOBAL_POSITION", True)
    stm.initial_position_drift = stm.PositionNedYaw(9.0, 9.0, 9.0, 0.0)

    with patch.object(stm, "compute_position_drift", new=AsyncMock()) as compute_position_drift:
        with patch.object(stm, "arm_with_preflight_gate", new=AsyncMock()) as arm_with_preflight_gate:
            await stm.arming_and_starting_offboard_mode(
                drone,
                global_reference={"source": "fallback_position"},
            )

    compute_position_drift.assert_not_awaited()
    arm_with_preflight_gate.assert_awaited_once()
    assert stm.initial_position_drift is None


@pytest.mark.asyncio
async def test_compute_position_drift_uses_threaded_http(monkeypatch):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"x": 1.5, "y": -2.0, "z": 0.25}

    async def fake_to_thread(func, *args, **kwargs):
        assert func is stm.requests.get
        assert args[0] == f"http://localhost:{stm.Params.drone_api_port}/api/v1/telemetry/local-position"
        assert kwargs["timeout"] == 2
        return response

    monkeypatch.setattr(stm.asyncio, "to_thread", fake_to_thread)

    drift = await stm.compute_position_drift()

    assert drift.north_m == pytest.approx(1.5)
    assert drift.east_m == pytest.approx(-2.0)
    assert drift.down_m == pytest.approx(0.25)
    assert drift.yaw_deg == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_run_swarm_trajectory_mission_exits_failure_when_mission_runtime_raises():
    drone = MagicMock()
    drone.telemetry.position.return_value = _stream_once(
        types.SimpleNamespace(
            latitude_deg=35.0,
            longitude_deg=51.0,
            absolute_altitude_m=1280.0,
        )
    )

    waypoints = [
        (float(index), 35.0, 51.0, 1280.0 + index, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 90.0, 0, 255, 255, 255)
        for index in range(11)
    ]
    mavsdk_server = object()

    with patch.object(stm, "start_mavsdk_server", return_value=mavsdk_server):
        with patch.object(stm.asyncio, "sleep", new=AsyncMock()):
            with patch.object(stm, "initial_setup_and_connection", new=AsyncMock(return_value=drone)):
                with patch.object(stm, "pre_flight_checks", new=AsyncMock(return_value=MagicMock())):
                    with patch.object(stm, "arming_and_starting_offboard_mode", new=AsyncMock()):
                        with patch.object(stm, "read_swarm_trajectory_file", return_value=waypoints):
                            with patch.object(
                                stm,
                                "perform_swarm_trajectory",
                                new=AsyncMock(side_effect=RuntimeError("end behavior exhausted")),
                            ):
                                with patch.object(stm, "stop_offboard_mode", new=AsyncMock()) as stop_offboard_mode:
                                    with patch.object(stm, "_get_current_armed_state", new=AsyncMock(return_value=False)):
                                        with patch.object(stm, "perform_landing", new=AsyncMock()) as perform_landing:
                                            with patch.object(stm, "stop_mavsdk_server") as stop_mavsdk_server:
                                                with pytest.raises(SystemExit) as exc:
                                                    await stm.run_swarm_trajectory_mission(
                                                        synchronized_start_time=None,
                                                        position_id_override=1,
                                                        end_behavior_override="return_home",
                                                    )

    assert exc.value.code == 1
    stop_offboard_mode.assert_awaited_once_with(drone)
    perform_landing.assert_not_awaited()
    stop_mavsdk_server.assert_called_once_with(mavsdk_server)


def test_main_defers_immediate_start_until_local_startup_gate(monkeypatch):
    args = SimpleNamespace(
        start_time=None,
        position_id=None,
        end_behavior=None,
    )
    logger = MagicMock()
    mission_mock = MagicMock(return_value="fake-coro")
    asyncio_run = MagicMock()

    monkeypatch.setattr(stm.argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(stm, "apply_log_args", lambda parsed: None)
    monkeypatch.setattr(stm, "register_component", lambda *a, **k: None)
    monkeypatch.setattr(stm, "init_drone_logging", lambda: None)
    monkeypatch.setattr(stm, "get_logger", lambda name: logger)
    monkeypatch.setattr(stm, "run_swarm_trajectory_mission", mission_mock)
    monkeypatch.setattr(stm.asyncio, "run", asyncio_run)

    stm.main()

    mission_mock.assert_called_once_with(
        None,
        position_id_override=None,
        end_behavior_override=None,
    )
    asyncio_run.assert_called_once_with("fake-coro")


@pytest.mark.asyncio
async def test_engage_rtl_confirms_return_mode_after_action_ack():
    drone = MagicMock()
    drone.action.return_to_launch = AsyncMock()

    with patch.object(stm, "wait_for_flight_mode", new=AsyncMock(return_value=stm.FlightMode.RETURN_TO_LAUNCH)) as wait_for_flight_mode:
        engaged = await stm.engage_rtl(drone)

    assert engaged is True
    drone.action.return_to_launch.assert_awaited_once()
    wait_for_flight_mode.assert_awaited_once_with(
        drone,
        stm.FlightMode.RETURN_TO_LAUNCH,
        timeout=stm.Params.SWARM_TRAJECTORY_RTL_MODE_TRANSITION_TIMEOUT_SEC,
    )


@pytest.mark.asyncio
async def test_engage_rtl_returns_false_when_mode_never_changes():
    drone = MagicMock()
    drone.action.return_to_launch = AsyncMock()

    with patch.object(stm, "wait_for_flight_mode", new=AsyncMock(side_effect=TimeoutError("no rtl"))):
        with patch.object(stm, "_get_local_drone_state_snapshot", return_value={"flight_mode": 50593792}):
            engaged = await stm.engage_rtl(drone)

    assert engaged is False


@pytest.mark.asyncio
async def test_wait_for_rtl_completion_issues_explicit_disarm_after_touchdown_grace(monkeypatch):
    drone = MagicMock()
    drone.telemetry.landed_state.side_effect = _stream_side_effect(
        [stm.LandedState.ON_GROUND, stm.LandedState.ON_GROUND]
    )
    drone.telemetry.armed.side_effect = _stream_side_effect([True, False])

    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_DISARM_GRACE_SEC", 0)
    monkeypatch.setattr(stm, "calculate_swarm_rtl_completion_timeout", lambda altitude: 30)
    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(return_value=25.0)):
        with patch.object(stm, "disarm_drone", new=AsyncMock()) as disarm_drone:
            await stm.wait_for_rtl_completion(drone)

    disarm_drone.assert_awaited_once_with(drone)


@pytest.mark.asyncio
async def test_wait_for_rtl_completion_forces_land_when_stalled_over_home(monkeypatch):
    drone = MagicMock()
    drone.telemetry.landed_state.side_effect = _stream_side_effect([object(), object()])
    drone.telemetry.armed.side_effect = _stream_side_effect([True, True])

    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_HOME_STALL_TRIGGER_SEC", 0)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_HOME_STALL_RADIUS_M", 25.0)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_STALL_DESCENT_EPS_MPS", 0.3)
    monkeypatch.setattr(stm, "calculate_swarm_rtl_completion_timeout", lambda altitude: 1200)

    local_state = {
        "position_lat": 35.0,
        "position_long": 51.0,
        "velocity_down": 0.0,
    }

    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(return_value=1200.0)):
        with patch.object(stm, "_get_local_drone_state_snapshot", return_value=local_state):
            with patch.object(stm, "perform_landing", new=AsyncMock()) as perform_landing:
                await stm.wait_for_rtl_completion(drone, home_lat=35.0, home_lon=51.0)

    perform_landing.assert_awaited_once_with(drone)


@pytest.mark.asyncio
async def test_wait_for_rtl_completion_forces_land_when_near_ground_without_touchdown(monkeypatch):
    drone = MagicMock()
    drone.telemetry.landed_state.side_effect = _stream_side_effect([object(), object()])
    drone.telemetry.armed.side_effect = _stream_side_effect([True, True])

    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_HOME_STALL_TRIGGER_SEC", 999)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_NEAR_GROUND_STALL_TRIGGER_SEC", 0)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_NEAR_GROUND_ALTITUDE_M", 0.75)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_NEAR_GROUND_SPEED_EPS_MPS", 0.5)
    monkeypatch.setattr(stm.Params, "SWARM_TRAJECTORY_RTL_STALL_DESCENT_EPS_MPS", 0.3)
    monkeypatch.setattr(stm, "calculate_swarm_rtl_completion_timeout", lambda altitude: 1200)

    local_state = {
        "position_lat": 35.001,
        "position_long": 51.001,
        "velocity_north": 0.1,
        "velocity_east": 0.1,
        "velocity_down": 0.0,
    }

    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(side_effect=[0.1, 0.1])):
        with patch.object(stm, "_get_local_drone_state_snapshot", return_value=local_state):
            with patch.object(stm, "perform_landing", new=AsyncMock()) as perform_landing:
                await stm.wait_for_rtl_completion(drone, home_lat=35.0, home_lon=51.0)

    perform_landing.assert_awaited_once_with(drone)


def test_update_rtl_near_ground_timer_keeps_timer_during_small_ground_motion(monkeypatch):
    monkeypatch.setattr(stm.time, "monotonic", lambda: 42.0)

    started = stm._update_rtl_near_ground_timer(
        stm.logging.getLogger(__name__),
        {
            "velocity_north": 0.2,
            "velocity_east": 0.1,
            "velocity_down": 0.0,
        },
        relative_altitude_m=0.2,
        stall_since=None,
        near_ground_altitude_m=0.75,
        horizontal_speed_eps_mps=0.5,
        descent_eps_mps=0.3,
        release_altitude_m=1.5,
        release_horizontal_speed_eps_mps=2.5,
        release_descent_eps_mps=0.6,
    )

    sustained = stm._update_rtl_near_ground_timer(
        stm.logging.getLogger(__name__),
        {
            "velocity_north": 1.2,
            "velocity_east": 0.1,
            "velocity_down": 0.04,
        },
        relative_altitude_m=0.3,
        stall_since=started,
        near_ground_altitude_m=0.75,
        horizontal_speed_eps_mps=0.5,
        descent_eps_mps=0.3,
        release_altitude_m=1.5,
        release_horizontal_speed_eps_mps=2.5,
        release_descent_eps_mps=0.6,
    )

    assert started == 42.0
    assert sustained == 42.0


@pytest.mark.asyncio
async def test_controlled_landing_delegates_to_native_land_when_above_precision_window(monkeypatch):
    drone = MagicMock()
    monkeypatch.setattr(stm.Params, "CONTROLLED_LANDING_ALTITUDE", 2.0)

    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(return_value=15.0)):
        with patch.object(stm, "stop_offboard_mode", new=AsyncMock()) as stop_offboard_mode:
            with patch.object(stm, "perform_landing", new=AsyncMock()) as perform_landing:
                await stm.controlled_landing(drone)

    stop_offboard_mode.assert_awaited_once_with(drone)
    perform_landing.assert_awaited_once_with(drone)


@pytest.mark.asyncio
async def test_perform_landing_requires_disarm_before_returning(monkeypatch):
    drone = MagicMock()
    drone.action.land = AsyncMock()
    drone.telemetry.landed_state.side_effect = _stream_side_effect(
        [stm.LandedState.ON_GROUND, stm.LandedState.ON_GROUND]
    )
    drone.telemetry.armed.side_effect = _stream_side_effect([True, False])

    monkeypatch.setattr(stm.Params, "LAND_ACTION_TOUCHDOWN_DISARM_GRACE_SEC", 0)
    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(return_value=12.0)):
        with patch.object(stm, "disarm_drone", new=AsyncMock()) as disarm_drone:
            await stm.perform_landing(drone)

    drone.action.land.assert_awaited_once()
    disarm_drone.assert_awaited_once_with(drone)


@pytest.mark.asyncio
async def test_perform_landing_continues_when_land_ack_times_out_but_landing_starts(monkeypatch):
    drone = MagicMock()
    drone.telemetry.landed_state.side_effect = _stream_side_effect(
        [stm.LandedState.LANDING, stm.LandedState.ON_GROUND, stm.LandedState.ON_GROUND]
    )
    drone.telemetry.armed.side_effect = _stream_side_effect([True, True, False])

    monkeypatch.setattr(stm.Params, "LAND_ACTION_TOUCHDOWN_DISARM_GRACE_SEC", 0)
    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(return_value=12.0)):
        with patch.object(stm, "invoke_action_with_timeout", new=AsyncMock(side_effect=TimeoutError("land ack timeout"))):
            with patch.object(stm, "disarm_drone", new=AsyncMock()) as disarm_drone:
                with patch.object(stm, "_wait_until_disarmed", new=AsyncMock()) as wait_until_disarmed:
                    await stm.perform_landing(drone)

    disarm_drone.assert_awaited_once_with(drone)
    wait_until_disarmed.assert_awaited_once()


@pytest.mark.asyncio
async def test_perform_landing_requires_landing_transition():
    drone = MagicMock()
    drone.action.land = AsyncMock()

    with patch.object(stm, "_get_current_relative_altitude", new=AsyncMock(return_value=12.0)):
        with patch.object(stm, "wait_for_landed_state_transition", new=AsyncMock(side_effect=TimeoutError("no transition"))):
            with pytest.raises(TimeoutError, match="no transition"):
                await stm.perform_landing(drone)


@pytest.mark.asyncio
async def test_wait_for_flight_mode_raises_when_expected_mode_missing():
    drone = MagicMock()
    drone.telemetry.flight_mode.return_value = _stream_once(stm.FlightMode.HOLD)

    with pytest.raises(TimeoutError, match="RETURN_TO_LAUNCH"):
        await stm.wait_for_flight_mode(drone, stm.FlightMode.RETURN_TO_LAUNCH, timeout=0.01)

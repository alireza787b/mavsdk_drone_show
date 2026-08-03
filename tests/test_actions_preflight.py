import asyncio
import inspect
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("psutil", MagicMock())

mavsdk_module = types.ModuleType("mavsdk")
mavsdk_module.System = MagicMock()
mavsdk_system_module = types.ModuleType("mavsdk.system")
mavsdk_system_module.System = MagicMock()
mavsdk_telemetry_module = types.ModuleType("mavsdk.telemetry")
mavsdk_telemetry_module.FlightMode = types.SimpleNamespace(
    HOLD=types.SimpleNamespace(name="HOLD"),
    RETURN_TO_LAUNCH=types.SimpleNamespace(name="RETURN_TO_LAUNCH"),
)
mavsdk_telemetry_module.LandedState = types.SimpleNamespace(
    TAKING_OFF="TAKING_OFF",
    IN_AIR="IN_AIR",
    LANDING="LANDING",
    ON_GROUND="ON_GROUND",
)
mavsdk_module.telemetry = mavsdk_telemetry_module
mavsdk_module.action = MagicMock()
mavsdk_offboard_module = types.ModuleType("mavsdk.offboard")
for name in (
    "PositionNedYaw",
    "VelocityBodyYawspeed",
    "PositionGlobalYaw",
    "VelocityNedYaw",
    "AccelerationNed",
):
    setattr(mavsdk_offboard_module, name, MagicMock())
mavsdk_offboard_module.OffboardError = Exception
sys.modules.setdefault("mavsdk", mavsdk_module)
sys.modules.setdefault("mavsdk.system", mavsdk_system_module)
sys.modules.setdefault("mavsdk.telemetry", mavsdk_telemetry_module)
sys.modules.setdefault("mavsdk.offboard", mavsdk_offboard_module)
sys.modules.setdefault("mavsdk.action", types.SimpleNamespace(ActionError=Exception))

import actions  # noqa: E402


def test_action_contract_has_no_parallel_px4_parameter_mutation_authority():
    assert actions.get_action_spec("init_sysid") is None
    assert actions.get_action_spec("apply_common_params") is None
    assert not hasattr(actions, "set_parameters")

    perform_parameters = inspect.signature(actions.perform_action).parameters
    assert "parameters" not in perform_parameters
    assert "reboot_after" not in perform_parameters


@pytest.fixture(autouse=True)
def _reset_action_result_state():
    original_return_code = actions.RETURN_CODE
    original_failure = actions._LAST_ACTION_FAILURE
    original_action = actions._CURRENT_ACTION_NAME
    original_final_state = actions._LAST_FINAL_VEHICLE_STATE
    original_cleanup_evidence = actions._LAST_ACTION_CLEANUP_EVIDENCE
    original_signal = actions._REQUESTED_PROCESS_SIGNAL
    original_led_feedback_disabled = actions._LED_FEEDBACK_DISABLED
    original_sim_mode = actions.Params.sim_mode
    actions.RETURN_CODE = 0
    actions._LAST_ACTION_FAILURE = None
    actions._CURRENT_ACTION_NAME = None
    actions._LAST_FINAL_VEHICLE_STATE = None
    actions._LAST_ACTION_CLEANUP_EVIDENCE = None
    actions._REQUESTED_PROCESS_SIGNAL = None
    actions._LED_FEEDBACK_DISABLED = False
    actions.Params.sim_mode = False
    try:
        yield
    finally:
        actions.RETURN_CODE = original_return_code
        actions._LAST_ACTION_FAILURE = original_failure
        actions._CURRENT_ACTION_NAME = original_action
        actions._LAST_FINAL_VEHICLE_STATE = original_final_state
        actions._LAST_ACTION_CLEANUP_EVIDENCE = original_cleanup_evidence
        actions._REQUESTED_PROCESS_SIGNAL = original_signal
        actions._LED_FEEDBACK_DISABLED = original_led_feedback_disabled
        actions.Params.sim_mode = original_sim_mode


def _real_ground_test_request():
    return {
        "ground_test_safety": {
            "mode": "operator_acknowledged",
            "props_removed": True,
            "airframe_secured": True,
            "area_clear": True,
        }
    }


def _vehicle_state(
    *,
    armed=False,
    landed_state="ON_GROUND",
    relative_altitude_m=0.0,
    field_errors=None,
):
    receipt_ages = {
        name: None
        for name in (field_errors or {})
    }
    return actions.VehicleStateObservation.from_values(
        observed_at_ms=1_785_000_000_000,
        armed=armed,
        landed_state=landed_state,
        relative_altitude_m=relative_altitude_m,
        receipt_ages_ms=receipt_ages,
        errors=dict(field_errors or {}),
    )


class _DummyTelemetry:
    def __init__(self, samples):
        self._samples = samples

    async def health(self):
        for sample in self._samples:
            yield sample


class _DummyDrone:
    def __init__(self, samples):
        self.telemetry = _DummyTelemetry(samples)


class _NeverYieldingStream:
    """Async iterator that stays silent until the consumer cancels it."""

    def __init__(self):
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


class _BlockingCloseStream:
    """One-sample stream whose normal close remains pending for cancellation."""

    def __init__(self):
        self.close_started = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return SimpleNamespace(ready=True)

    async def aclose(self):
        self.close_started.set()
        await asyncio.Event().wait()


async def _live_connection_stream():
    yield SimpleNamespace(is_connected=True)
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_wait_for_telemetry_condition_has_wall_clock_timeout_and_closes_stream():
    stream = _NeverYieldingStream()

    with pytest.raises(TimeoutError, match="Timed out waiting for silent telemetry"):
        await actions.wait_for_telemetry_condition(
            lambda: stream,
            lambda _sample: False,
            "silent telemetry",
            timeout=0.02,
        )

    assert stream.closed is True


@pytest.mark.asyncio
async def test_wait_for_drone_connection_has_wall_clock_timeout_and_closes_stream():
    stream = _NeverYieldingStream()
    drone = SimpleNamespace(
        core=SimpleNamespace(connection_state=lambda: stream),
    )

    assert await actions.wait_for_drone_connection(drone, timeout=0.02) is False
    assert stream.closed is True


@pytest.mark.asyncio
async def test_external_cancellation_during_stream_close_is_not_swallowed():
    stream = _BlockingCloseStream()
    task = asyncio.create_task(
        actions.wait_for_telemetry_condition(
            lambda: stream,
            lambda sample: sample.ready,
            "ready telemetry",
            timeout=1.0,
        )
    )
    await asyncio.wait_for(stream.close_started.wait(), timeout=0.2)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_authoritative_state_observation_closes_silent_streams_at_shared_deadline():
    streams = [_NeverYieldingStream() for _ in range(3)]
    drone = SimpleNamespace(
        core=SimpleNamespace(connection_state=_live_connection_stream),
        telemetry=SimpleNamespace(
            armed=lambda: streams[0],
            landed_state=lambda: streams[1],
            position=lambda: streams[2],
        )
    )

    observation = await actions.observe_authoritative_vehicle_state(drone, timeout=0.02)

    assert observation.complete is False
    assert set(observation.field_errors) == {
        "armed",
        "landed_state",
        "relative_altitude_m",
    }
    assert all(stream.closed for stream in streams)


@pytest.mark.asyncio
async def test_safe_action_preserves_px4_denial_as_structured_root_cause(monkeypatch):
    class FakeActionError(Exception):
        pass

    monkeypatch.setattr(actions, "ActionError", FakeActionError)

    async def denied_action():
        raise actions.ActionError("COMMAND_DENIED: Resolve system health failures first")

    original_return_code = actions.RETURN_CODE
    original_failure = actions._LAST_ACTION_FAILURE
    original_action = actions._CURRENT_ACTION_NAME
    actions.RETURN_CODE = 0
    actions._LAST_ACTION_FAILURE = None
    actions._CURRENT_ACTION_NAME = "test"
    try:
        assert await actions.safe_action(denied_action) is False
        result = actions._build_terminal_result("test")
    finally:
        actions.RETURN_CODE = original_return_code
        actions._LAST_ACTION_FAILURE = original_failure
        actions._CURRENT_ACTION_NAME = original_action

    assert result.success is False
    assert result.code == "PX4_COMMAND_DENIED"
    assert result.phase == "vehicle_command"
    assert "Resolve system health failures first" in result.operator_message


@pytest.mark.asyncio
async def test_safe_action_preserves_typed_launch_readiness_evidence():
    from src.mission_startup import LaunchReadinessError

    readiness_error = LaunchReadinessError({
        "summary": "waiting for battery reserve 12.0% below minimum 30.0%",
        "blockers": ["battery reserve 12.0% below minimum 30.0%"],
        "timed_out": False,
        "battery": {
            "remaining_percent": 12.0,
            "minimum_remaining_percent": 30.0,
            "sample_received": True,
            "fresh": True,
            "reserve_ok": False,
        },
        "observation": {"schema_version": 1, "ready": False},
    })

    async def blocked_action():
        raise readiness_error

    original_return_code = actions.RETURN_CODE
    original_failure = actions._LAST_ACTION_FAILURE
    original_action = actions._CURRENT_ACTION_NAME
    actions.RETURN_CODE = 0
    actions._LAST_ACTION_FAILURE = None
    actions._CURRENT_ACTION_NAME = "takeoff"
    try:
        assert await actions.safe_action(blocked_action) is False
        result = actions._build_terminal_result("takeoff")
    finally:
        actions.RETURN_CODE = original_return_code
        actions._LAST_ACTION_FAILURE = original_failure
        actions._CURRENT_ACTION_NAME = original_action

    assert result.success is False
    assert result.code == "BATTERY_RESERVE_LOW"
    assert result.phase == "preflight"
    assert result.evidence["battery"]["remaining_percent"] == 12.0
    assert result.evidence["observation"]["ready"] is False


@pytest.mark.asyncio
async def test_ensure_ready_for_flight_uses_local_home_fallback(mocker):
    mocker.patch(
        "actions._get_local_drone_state_snapshot",
        return_value={"home_position_set": True},
    )

    drone = _DummyDrone([
        SimpleNamespace(is_global_position_ok=True, is_home_position_ok=False),
    ])

    assert await actions.ensure_ready_for_flight(drone, timeout=1) is True


@pytest.mark.asyncio
async def test_wait_until_relative_altitude_uses_local_fallback_after_mavsdk_timeout(mocker):
    wait_mock = mocker.patch(
        "actions.wait_for_telemetry_condition",
        new=mocker.AsyncMock(side_effect=TimeoutError("mavsdk timeout")),
    )
    mocker.patch("actions._get_local_relative_altitude_snapshot", return_value=8.6)
    drone = SimpleNamespace(telemetry=SimpleNamespace(position=MagicMock()))

    result = await actions.wait_until_relative_altitude(drone, 8.0, timeout=1)

    wait_mock.assert_awaited_once()
    assert result == 8.6


@pytest.mark.asyncio
async def test_wait_until_relative_altitude_raises_when_fallback_is_still_below_target(mocker):
    mocker.patch(
        "actions.wait_for_telemetry_condition",
        new=mocker.AsyncMock(side_effect=TimeoutError("mavsdk timeout")),
    )
    mocker.patch("actions._get_local_relative_altitude_snapshot", return_value=4.2)
    drone = SimpleNamespace(telemetry=SimpleNamespace(position=MagicMock()))

    with pytest.raises(TimeoutError, match="mavsdk timeout"):
        await actions.wait_until_relative_altitude(drone, 8.0, timeout=1)


@pytest.mark.asyncio
async def test_takeoff_uses_shared_armability_gate_after_preflight(mocker):
    led_instance = MagicMock()
    mocker.patch("actions.LEDController.get_instance", return_value=led_instance)
    mocker.patch("actions.ensure_ready_for_flight", new=mocker.AsyncMock(return_value=True))
    arm_gate = mocker.patch("actions.arm_with_preflight_gate", new=mocker.AsyncMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            side_effect=[
                _vehicle_state(),
                _vehicle_state(
                    armed=True,
                    landed_state="IN_AIR",
                    relative_altitude_m=10.0,
                ),
            ]
        ),
    )
    wait_armed = mocker.patch("actions.wait_until_armed_state", new=mocker.AsyncMock())
    wait_landed = mocker.patch(
        "actions.wait_until_landed_state",
        new=mocker.AsyncMock(return_value="IN_AIR"),
    )
    wait_altitude = mocker.patch(
        "actions.wait_until_relative_altitude",
        new=mocker.AsyncMock(return_value=SimpleNamespace(relative_altitude_m=10.0)),
    )
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch.object(
        actions.telemetry,
        "LandedState",
        SimpleNamespace(TAKING_OFF="TAKING_OFF", IN_AIR="IN_AIR"),
    )

    drone = SimpleNamespace(
        action=SimpleNamespace(
            set_takeoff_altitude=mocker.AsyncMock(),
            takeoff=mocker.AsyncMock(),
        )
    )

    await actions.takeoff(drone, 12.0)

    arm_gate.assert_awaited_once_with(
        drone,
        require_global_position=False,
        logger=actions.logger,
    )
    wait_armed.assert_awaited_once_with(
        drone,
        True,
        timeout=actions.Params.TAKEOFF_ARMED_CONFIRM_TIMEOUT_SEC,
    )
    wait_landed.assert_awaited_once_with(
        drone,
        {
            actions.telemetry.LandedState.TAKING_OFF,
            actions.telemetry.LandedState.IN_AIR,
        },
        "takeoff state transition",
        timeout=actions.Params.TAKEOFF_STATE_TRANSITION_TIMEOUT_SEC,
    )
    wait_altitude.assert_awaited_once()
    drone.action.set_takeoff_altitude.assert_awaited_once_with(12.0)
    drone.action.takeoff.assert_awaited_once()


def test_calculate_land_disarm_timeout_defaults_to_minimum_when_altitude_unknown():
    assert actions.calculate_land_disarm_timeout(None) == actions.Params.LAND_ACTION_MIN_DISARM_WAIT_SEC


def test_calculate_land_disarm_timeout_scales_with_altitude_and_respects_cap():
    timeout = actions.calculate_land_disarm_timeout(1200.0)

    assert timeout > actions.Params.LAND_ACTION_MIN_DISARM_WAIT_SEC
    assert timeout <= actions.Params.LAND_ACTION_MAX_DISARM_WAIT_SEC


@pytest.mark.asyncio
async def test_return_rtl_waits_for_full_disarm_confirmation(mocker):
    led_instance = MagicMock()
    mocker.patch("actions.LEDController.get_instance", return_value=led_instance)
    mocker.patch("actions.calculate_rtl_completion_timeout", return_value=222)
    wait_mode = mocker.patch("actions.wait_until_flight_mode", new=mocker.AsyncMock())
    wait_armed = mocker.patch("actions.wait_until_armed_state", new=mocker.AsyncMock())
    mocker.patch("actions._get_current_relative_altitude", new=mocker.AsyncMock(return_value=18.5))

    drone = SimpleNamespace(
        action=SimpleNamespace(
            return_to_launch=mocker.AsyncMock(),
        )
    )

    await actions.return_rtl(drone)

    wait_mode.assert_awaited_once_with(
        drone,
        actions.telemetry.FlightMode.RETURN_TO_LAUNCH,
        timeout=15,
    )
    drone.action.return_to_launch.assert_awaited_once()
    wait_armed.assert_awaited_once_with(drone, False, timeout=222)


@pytest.mark.asyncio
async def test_land_attempts_primary_recovery_without_hold_prerequisite(mocker):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    wait_landed = mocker.patch("actions.wait_until_landed_state", new=mocker.AsyncMock())
    wait_armed = mocker.patch("actions.wait_until_armed_state", new=mocker.AsyncMock())
    mocker.patch("actions._get_current_relative_altitude", new=mocker.AsyncMock(return_value=2.0))
    drone = SimpleNamespace(action=SimpleNamespace(land=mocker.AsyncMock()))

    await actions.land(drone)

    drone.action.land.assert_awaited_once()
    wait_landed.assert_awaited_once_with(
        drone,
        {actions.telemetry.LandedState.LANDING, actions.telemetry.LandedState.ON_GROUND},
        "landing state transition",
        timeout=15,
    )
    wait_armed.assert_awaited_once()
    assert not hasattr(drone.action, "hold")


@pytest.mark.asyncio
async def test_land_rpc_precedes_led_initialization_and_led_failure_cannot_mask_recovery(mocker):
    events = []

    async def land_rpc():
        events.append("land_rpc")

    def broken_led():
        events.append("led_init")
        raise RuntimeError("SPI unavailable")

    mocker.patch("actions.LEDController.get_instance", side_effect=broken_led)
    sleep = mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch("actions.wait_until_landed_state", new=mocker.AsyncMock())
    mocker.patch("actions.wait_until_armed_state", new=mocker.AsyncMock())
    mocker.patch(
        "actions._get_current_relative_altitude",
        new=mocker.AsyncMock(return_value=2.0),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(land=mocker.AsyncMock(side_effect=land_rpc))
    )

    await actions.land(drone)

    assert events == ["land_rpc", "led_init"]
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_rtl_rpc_precedes_led_initialization_and_led_failure_cannot_mask_recovery(mocker):
    events = []

    async def rtl_rpc():
        events.append("rtl_rpc")

    def broken_led():
        events.append("led_init")
        raise RuntimeError("SPI unavailable")

    mocker.patch("actions.LEDController.get_instance", side_effect=broken_led)
    sleep = mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch("actions.wait_until_flight_mode", new=mocker.AsyncMock())
    mocker.patch("actions.wait_until_armed_state", new=mocker.AsyncMock())
    mocker.patch(
        "actions._get_current_relative_altitude",
        new=mocker.AsyncMock(return_value=2.0),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(return_to_launch=mocker.AsyncMock(side_effect=rtl_rpc))
    )

    await actions.return_rtl(drone)

    assert events == ["rtl_rpc", "led_init"]
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_kill_rpc_precedes_led_initialization_and_led_failure_cannot_mask_termination(mocker):
    events = []

    async def terminate_rpc():
        events.append("terminate_rpc")

    def broken_led():
        events.append("led_init")
        raise RuntimeError("SPI unavailable")

    mocker.patch("actions.LEDController.get_instance", side_effect=broken_led)
    sleep = mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    wait_armed = mocker.patch(
        "actions.wait_until_armed_state",
        new=mocker.AsyncMock(),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(terminate=mocker.AsyncMock(side_effect=terminate_rpc))
    )

    await actions.kill_terminate(drone)

    assert events == ["terminate_rpc", "led_init"]
    wait_armed.assert_awaited_once_with(drone, False, timeout=10)
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_ground_arm_disarm_test_confirms_both_observed_states(mocker):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            side_effect=[
                _vehicle_state(),
                _vehicle_state(),
            ]
        ),
    )
    wait_armed = mocker.patch("actions.wait_until_armed_state", new=mocker.AsyncMock())
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(),
            disarm=mocker.AsyncMock(),
        )
    )

    await actions.test(drone, request_payload=_real_ground_test_request())

    assert wait_armed.await_args_list == [
        mocker.call(drone, True, timeout=10),
        mocker.call(drone, False, timeout=10),
    ]


@pytest.mark.asyncio
async def test_ground_test_missing_acknowledgement_fails_before_telemetry_or_arm(mocker):
    observe = mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(),
    )
    led = mocker.patch("actions.LEDController.get_instance")
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(),
            disarm=mocker.AsyncMock(),
        )
    )

    with pytest.raises(actions.ActionSafetyError) as failure:
        await actions.test(drone)

    assert failure.value.code == "GROUND_TEST_SAFETY_ACK_REQUIRED"
    assert failure.value.phase == "precondition"
    assert "No arm command was sent" in str(failure.value)
    observe.assert_not_awaited()
    led.assert_not_called()
    drone.action.arm.assert_not_awaited()


@pytest.mark.asyncio
async def test_ground_test_sitl_exemption_is_bound_to_actual_runtime(mocker):
    actions.Params.sim_mode = False
    observe = mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(),
            disarm=mocker.AsyncMock(),
        )
    )

    with pytest.raises(actions.ActionSafetyError) as failure:
        await actions.test(
            drone,
            request_payload={
                "ground_test_safety": {"mode": "sitl_not_applicable"},
            },
        )

    assert failure.value.code == "GROUND_TEST_SAFETY_ACK_REQUIRED"
    assert failure.value.evidence == {
        "runtime_mode": "real",
        "acknowledgement_mode": "sitl_not_applicable",
    }
    observe.assert_not_awaited()
    drone.action.arm.assert_not_awaited()


@pytest.mark.asyncio
async def test_ground_test_action_runner_preserves_structured_request_payload(mocker):
    runner = mocker.patch("actions.test", new=mocker.AsyncMock())
    invocation = actions.ActionInvocation(
        action="test",
        request_payload=_real_ground_test_request(),
    )
    context = actions.ActionExecutionContext(
        drone=SimpleNamespace(),
        hw_id="1",
        logger=MagicMock(),
    )

    assert await actions._run_test(context, invocation) is True

    runner.assert_awaited_once_with(
        context.drone,
        request_payload=_real_ground_test_request(),
    )


def _prepare_takeoff(
    mocker,
    *,
    observations=None,
    wait_armed_side_effect=None,
    takeoff_side_effect=None,
    landed_side_effect=None,
    altitude_side_effect=None,
):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    ensure_ready = mocker.patch(
        "actions.ensure_ready_for_flight",
        new=mocker.AsyncMock(return_value=True),
    )
    arm_gate = mocker.patch(
        "actions.arm_with_preflight_gate",
        new=mocker.AsyncMock(),
    )
    if observations is None:
        completion_altitude = 9.0
        if isinstance(altitude_side_effect, list) and altitude_side_effect:
            completion_altitude = getattr(
                altitude_side_effect[0],
                "relative_altitude_m",
                completion_altitude,
            )
        observations = [
            _vehicle_state(),
            _vehicle_state(
                armed=True,
                landed_state="IN_AIR",
                relative_altitude_m=completion_altitude,
            ),
        ]
    observe = mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            side_effect=list(observations),
        ),
    )
    wait_armed = mocker.patch(
        "actions.wait_until_armed_state",
        new=mocker.AsyncMock(side_effect=wait_armed_side_effect),
    )
    wait_landed = mocker.patch(
        "actions.wait_until_landed_state",
        new=mocker.AsyncMock(
            side_effect=(
                landed_side_effect
                if landed_side_effect is not None
                else ["TAKING_OFF"]
            ),
        ),
    )
    wait_altitude = mocker.patch(
        "actions.wait_until_relative_altitude",
        new=mocker.AsyncMock(
            side_effect=(
                altitude_side_effect
                if altitude_side_effect is not None
                else [SimpleNamespace(relative_altitude_m=9.0)]
            ),
        ),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(
            set_takeoff_altitude=mocker.AsyncMock(),
            takeoff=mocker.AsyncMock(side_effect=takeoff_side_effect),
            land=mocker.AsyncMock(),
            disarm=mocker.AsyncMock(),
        )
    )
    return SimpleNamespace(
        drone=drone,
        ensure_ready=ensure_ready,
        arm_gate=arm_gate,
        observe=observe,
        wait_armed=wait_armed,
        wait_landed=wait_landed,
        wait_altitude=wait_altitude,
    )


def test_one_meter_takeoff_confirmation_threshold_is_attainable():
    assert actions._takeoff_confirmation_altitude_m(1.0) == pytest.approx(0.5)
    assert actions._takeoff_confirmation_altitude_m(1.0) <= 1.0
    assert actions._takeoff_confirmation_altitude_m(12.0) == pytest.approx(9.6)


@pytest.mark.asyncio
async def test_authoritative_airborne_wait_retries_until_one_coherent_snapshot(mocker):
    observations = [
        _vehicle_state(
            armed=True,
            landed_state="TAKING_OFF",
            relative_altitude_m=8.1,
            field_errors={"landed_state": "sample was stale"},
        ),
        _vehicle_state(
            armed=True,
            landed_state="TAKING_OFF",
            relative_altitude_m=8.4,
        ),
        _vehicle_state(
            armed=True,
            landed_state="IN_AIR",
            relative_altitude_m=9.0,
        ),
    ]
    observe = mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(side_effect=observations),
    )
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())

    result = await actions.wait_for_authoritative_airborne_state(
        SimpleNamespace(),
        8.0,
        timeout=1,
    )

    assert result is observations[-1]
    assert result.airborne is True
    assert observe.await_count == 3


@pytest.mark.asyncio
async def test_authoritative_airborne_wait_returns_last_snapshot_at_deadline(mocker):
    transition_state = _vehicle_state(
        armed=True,
        landed_state="TAKING_OFF",
        relative_altitude_m=8.4,
    )
    observe = mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(return_value=transition_state),
    )
    sleep = mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch("actions.monotonic_deadline", return_value=1.0)
    mocker.patch.object(
        actions,
        "time",
        SimpleNamespace(monotonic=mocker.Mock(side_effect=[0.0, 1.0])),
    )

    result = await actions.wait_for_authoritative_airborne_state(
        SimpleNamespace(),
        8.0,
        timeout=1,
    )

    assert result is transition_state
    observe.assert_awaited_once()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_authoritative_state_observation_samples_direct_mavsdk_streams():
    async def once(value):
        yield value

    drone = SimpleNamespace(
        core=SimpleNamespace(connection_state=_live_connection_stream),
        telemetry=SimpleNamespace(
            armed=lambda: once(True),
            landed_state=lambda: once(SimpleNamespace(name="IN_AIR")),
            position=lambda: once(SimpleNamespace(relative_altitude_m=4.2)),
        )
    )

    observation = await actions.observe_authoritative_vehicle_state(drone, timeout=1)

    assert observation.complete is True
    assert observation.airborne is True
    assert observation.as_dict()["source"] == "mavsdk.telemetry"


@pytest.mark.asyncio
async def test_hold_requires_complete_fresh_airborne_evidence(mocker):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    observe = mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            return_value=_vehicle_state(
                armed=False,
                landed_state="ON_GROUND",
                relative_altitude_m=0.0,
            )
        ),
    )
    drone = SimpleNamespace(action=SimpleNamespace(hold=mocker.AsyncMock()))

    with pytest.raises(actions.ActionSafetyError) as failure:
        await actions.hold(drone)

    assert failure.value.code == "HOLD_REQUIRES_AIRBORNE_STATE"
    assert failure.value.phase == "precondition"
    observe.assert_awaited_once_with(drone)
    drone.action.hold.assert_not_awaited()


@pytest.mark.asyncio
async def test_hold_rejects_partial_authoritative_state(mocker):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            return_value=_vehicle_state(
                armed=True,
                landed_state="IN_AIR",
                relative_altitude_m=None,
                field_errors={"relative_altitude_m": "timeout"},
            )
        ),
    )
    drone = SimpleNamespace(action=SimpleNamespace(hold=mocker.AsyncMock()))

    with pytest.raises(actions.ActionSafetyError) as failure:
        await actions.hold(drone)

    assert failure.value.code == "HOLD_STATE_UNAVAILABLE"
    drone.action.hold.assert_not_awaited()


@pytest.mark.asyncio
async def test_hold_changes_mode_only_after_fresh_airborne_gate(mocker):
    led = MagicMock()
    led.set_color.side_effect = RuntimeError("optional SPI unavailable")
    mocker.patch("actions.LEDController.get_instance", return_value=led)
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    admission = _vehicle_state(
        armed=True,
        landed_state="IN_AIR",
        relative_altitude_m=6.0,
    )
    observe = mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(side_effect=[admission, admission]),
    )
    wait_mode = mocker.patch(
        "actions.wait_until_flight_mode",
        new=mocker.AsyncMock(),
    )
    drone = SimpleNamespace(action=SimpleNamespace(hold=mocker.AsyncMock()))

    await actions.hold(drone)

    assert observe.await_count == 2
    drone.action.hold.assert_awaited_once()
    wait_mode.assert_awaited_once_with(
        drone,
        actions.telemetry.FlightMode.HOLD,
        timeout=10,
    )
    assert actions._LAST_FINAL_VEHICLE_STATE["flight_mode"] == "HOLD"


@pytest.mark.asyncio
async def test_ground_test_rejects_airborne_start_without_disarming(mocker):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            return_value=_vehicle_state(
                armed=True,
                landed_state="IN_AIR",
                relative_altitude_m=8.0,
            )
        ),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(),
            disarm=mocker.AsyncMock(),
        )
    )

    with pytest.raises(actions.ActionSafetyError) as failure:
        await actions.test(drone, request_payload=_real_ground_test_request())

    assert failure.value.code == "GROUND_TEST_REQUIRES_SAFE_GROUND_STATE"
    drone.action.arm.assert_not_awaited()
    drone.action.disarm.assert_not_awaited()


@pytest.mark.asyncio
async def test_ground_test_arm_rpc_failure_still_verifies_disarm(mocker):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            side_effect=[
                _vehicle_state(),
                _vehicle_state(armed=True),
                _vehicle_state(),
            ]
        ),
    )
    wait_armed = mocker.patch(
        "actions.wait_until_armed_state",
        new=mocker.AsyncMock(),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(side_effect=RuntimeError("arm transport uncertain")),
            disarm=mocker.AsyncMock(),
        )
    )

    with pytest.raises(actions._ActionTransactionError) as failure:
        await actions.test(drone, request_payload=_real_ground_test_request())

    assert str(failure.value.primary_error) == "arm transport uncertain"
    drone.action.disarm.assert_awaited_once()
    wait_armed.assert_awaited_once_with(drone, False, timeout=10)
    assert failure.value.final_vehicle_state["armed"] is False
    assert failure.value.evidence["cleanup_confirmed"] is True


@pytest.mark.asyncio
async def test_ground_test_armed_confirmation_failure_still_disarms(mocker):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            side_effect=[
                _vehicle_state(),
                _vehicle_state(armed=True),
                _vehicle_state(),
            ]
        ),
    )
    wait_armed = mocker.patch(
        "actions.wait_until_armed_state",
        new=mocker.AsyncMock(side_effect=[TimeoutError("arm not observed"), False]),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(),
            disarm=mocker.AsyncMock(),
        )
    )

    with pytest.raises(actions._ActionTransactionError):
        await actions.test(drone, request_payload=_real_ground_test_request())

    drone.action.disarm.assert_awaited_once()
    assert wait_armed.await_args_list == [
        mocker.call(drone, True, timeout=10),
        mocker.call(drone, False, timeout=10),
    ]


@pytest.mark.asyncio
async def test_ground_test_never_disarms_an_unexpected_airborne_state(mocker):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            side_effect=[
                _vehicle_state(),
                _vehicle_state(armed=True, landed_state="IN_AIR", relative_altitude_m=1.0),
                _vehicle_state(armed=True, landed_state="IN_AIR", relative_altitude_m=1.0),
                _vehicle_state(armed=True, landed_state="LANDING", relative_altitude_m=0.8),
            ]
        ),
    )
    mocker.patch(
        "actions.wait_until_armed_state",
        new=mocker.AsyncMock(side_effect=TimeoutError("armed transition uncertain")),
    )
    wait_landed = mocker.patch(
        "actions.wait_until_landed_state",
        new=mocker.AsyncMock(return_value="LANDING"),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(),
            disarm=mocker.AsyncMock(),
            land=mocker.AsyncMock(),
        )
    )

    with pytest.raises(actions._ActionTransactionError) as failure:
        await actions.test(drone, request_payload=_real_ground_test_request())

    drone.action.disarm.assert_not_awaited()
    drone.action.land.assert_awaited_once()
    wait_landed.assert_awaited_once()
    assert failure.value.final_vehicle_state["recovery_status"] == "land_recovery_started"


@pytest.mark.asyncio
async def test_ground_test_cancellation_is_propagated_after_disarm_cleanup(mocker):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            side_effect=[
                _vehicle_state(),
                _vehicle_state(armed=True),
                _vehicle_state(),
            ]
        ),
    )
    mocker.patch(
        "actions.asyncio.sleep",
        new=mocker.AsyncMock(side_effect=asyncio.CancelledError()),
    )
    wait_armed = mocker.patch(
        "actions.wait_until_armed_state",
        new=mocker.AsyncMock(),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(),
            disarm=mocker.AsyncMock(),
        )
    )

    with pytest.raises(asyncio.CancelledError):
        await actions.test(drone, request_payload=_real_ground_test_request())

    drone.action.disarm.assert_awaited_once()
    assert actions._LAST_ACTION_CLEANUP_EVIDENCE["cleanup_confirmed"] is True
    assert wait_armed.await_args_list[-1] == mocker.call(drone, False, timeout=10)
    assert actions._LAST_FINAL_VEHICLE_STATE["armed"] is False


@pytest.mark.asyncio
async def test_ground_test_retries_disarm_when_primary_disarm_rpc_fails(mocker):
    mocker.patch("actions.LEDController.get_instance", return_value=MagicMock())
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            side_effect=[
                _vehicle_state(),
                _vehicle_state(armed=True),
                _vehicle_state(),
            ]
        ),
    )
    wait_armed = mocker.patch(
        "actions.wait_until_armed_state",
        new=mocker.AsyncMock(),
    )
    disarm = mocker.AsyncMock(side_effect=[RuntimeError("first disarm failed"), None])
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(),
            disarm=disarm,
        )
    )

    with pytest.raises(actions._ActionTransactionError) as failure:
        await actions.test(drone, request_payload=_real_ground_test_request())

    assert disarm.await_count == 2
    assert failure.value.evidence["cleanup_confirmed"] is True
    assert wait_armed.await_args_list[-1] == mocker.call(drone, False, timeout=10)


@pytest.mark.asyncio
async def test_ground_test_reports_unconfirmed_cleanup_without_led_masking(mocker):
    led = MagicMock()
    led.turn_off.side_effect = RuntimeError("SPI failed")
    mocker.patch("actions.LEDController.get_instance", return_value=led)
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(
            side_effect=[
                _vehicle_state(),
                _vehicle_state(armed=True),
                _vehicle_state(armed=True),
            ]
        ),
    )
    mocker.patch(
        "actions.wait_until_armed_state",
        new=mocker.AsyncMock(
            side_effect=[None, TimeoutError("disarm state unavailable")]
        ),
    )
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(),
            disarm=mocker.AsyncMock(
                side_effect=[RuntimeError("primary disarm failed"), RuntimeError("cleanup disarm failed")]
            ),
        )
    )

    assert await actions.safe_action(
        actions.test,
        drone,
        request_payload=_real_ground_test_request(),
    ) is False
    result = actions._build_terminal_result("test")

    assert result.success is False
    assert result.final_vehicle_state["armed"] is True
    assert result.final_vehicle_state["recovery_status"] == "disarm_unconfirmed"
    assert "Safety cleanup could not be confirmed" in result.operator_message


@pytest.mark.asyncio
async def test_ground_test_led_failure_does_not_mask_success(mocker):
    led = MagicMock()
    led.set_color.side_effect = RuntimeError("no LED device")
    led.turn_off.side_effect = RuntimeError("no LED device")
    mocker.patch("actions.LEDController.get_instance", return_value=led)
    mocker.patch("actions.asyncio.sleep", new=mocker.AsyncMock())
    mocker.patch(
        "actions.observe_authoritative_vehicle_state",
        new=mocker.AsyncMock(side_effect=[_vehicle_state(), _vehicle_state()]),
    )
    mocker.patch("actions.wait_until_armed_state", new=mocker.AsyncMock())
    drone = SimpleNamespace(
        action=SimpleNamespace(
            arm=mocker.AsyncMock(),
            disarm=mocker.AsyncMock(),
        )
    )

    await actions.test(drone, request_payload=_real_ground_test_request())

    assert actions._LAST_FINAL_VEHICLE_STATE["armed"] is False


@pytest.mark.asyncio
async def test_takeoff_preflight_failure_sends_no_arm_or_cleanup_command(mocker):
    setup = _prepare_takeoff(mocker)
    setup.ensure_ready.return_value = False

    with pytest.raises(actions.ActionSafetyError) as failure:
        await actions.takeoff(setup.drone, 10.0)

    assert failure.value.code == "TAKEOFF_PREFLIGHT_NOT_READY"
    setup.arm_gate.assert_not_awaited()
    setup.drone.action.disarm.assert_not_awaited()
    setup.drone.action.land.assert_not_awaited()


@pytest.mark.asyncio
async def test_takeoff_altitude_configuration_failure_is_pre_arm(mocker):
    setup = _prepare_takeoff(mocker)
    setup.drone.action.set_takeoff_altitude.side_effect = RuntimeError("parameter RPC failed")

    with pytest.raises(RuntimeError, match="parameter RPC failed"):
        await actions.takeoff(setup.drone, 10.0)

    setup.arm_gate.assert_not_awaited()
    setup.drone.action.disarm.assert_not_awaited()
    setup.drone.action.land.assert_not_awaited()


@pytest.mark.asyncio
async def test_takeoff_arm_gate_failure_performs_verified_ground_disarm(mocker):
    setup = _prepare_takeoff(
        mocker,
        observations=[
            _vehicle_state(),
            _vehicle_state(armed=True),
            _vehicle_state(),
        ],
    )
    setup.arm_gate.side_effect = TimeoutError("arm result uncertain")

    with pytest.raises(actions._ActionTransactionError) as failure:
        await actions.takeoff(setup.drone, 10.0)

    setup.drone.action.disarm.assert_awaited_once()
    setup.drone.action.land.assert_not_awaited()
    assert failure.value.final_vehicle_state["armed"] is False
    assert failure.value.evidence["cleanup_confirmed"] is True


@pytest.mark.asyncio
async def test_takeoff_armed_confirmation_failure_performs_verified_disarm(mocker):
    setup = _prepare_takeoff(
        mocker,
        observations=[
            _vehicle_state(),
            _vehicle_state(armed=True),
            _vehicle_state(),
        ],
        wait_armed_side_effect=[TimeoutError("armed state not observed"), False],
    )

    with pytest.raises(actions._ActionTransactionError):
        await actions.takeoff(setup.drone, 10.0)

    setup.drone.action.disarm.assert_awaited_once()
    setup.drone.action.land.assert_not_awaited()


@pytest.mark.asyncio
async def test_takeoff_rpc_failure_starts_primary_land_recovery(mocker):
    setup = _prepare_takeoff(
        mocker,
        observations=[
            _vehicle_state(),
            _vehicle_state(armed=True, landed_state="IN_AIR", relative_altitude_m=1.2),
            _vehicle_state(armed=True, landed_state="LANDING", relative_altitude_m=1.0),
        ],
        takeoff_side_effect=RuntimeError("takeoff RPC uncertain"),
        landed_side_effect=["LANDING"],
    )

    with pytest.raises(actions._ActionTransactionError) as failure:
        await actions.takeoff(setup.drone, 10.0)

    setup.drone.action.land.assert_awaited_once()
    setup.drone.action.disarm.assert_not_awaited()
    assert failure.value.final_vehicle_state["recovery_action"] == "land"
    assert failure.value.final_vehicle_state["recovery_status"] == "land_recovery_started"
    assert failure.value.evidence["cleanup_confirmed"] is True


@pytest.mark.asyncio
async def test_takeoff_transition_timeout_starts_land_recovery(mocker):
    setup = _prepare_takeoff(
        mocker,
        observations=[
            _vehicle_state(),
            _vehicle_state(armed=True, landed_state="IN_AIR", relative_altitude_m=2.0),
            _vehicle_state(armed=True, landed_state="LANDING", relative_altitude_m=1.7),
        ],
        landed_side_effect=[TimeoutError("no takeoff transition"), "LANDING"],
    )

    with pytest.raises(actions._ActionTransactionError):
        await actions.takeoff(setup.drone, 10.0)

    setup.drone.action.land.assert_awaited_once()
    assert setup.wait_landed.await_count == 2


@pytest.mark.asyncio
async def test_takeoff_altitude_timeout_starts_land_recovery(mocker):
    setup = _prepare_takeoff(
        mocker,
        observations=[
            _vehicle_state(),
            _vehicle_state(armed=True, landed_state="IN_AIR", relative_altitude_m=3.0),
            _vehicle_state(armed=True, landed_state="LANDING", relative_altitude_m=2.5),
        ],
        landed_side_effect=["IN_AIR", "LANDING"],
        altitude_side_effect=[TimeoutError("altitude not confirmed")],
    )

    with pytest.raises(actions._ActionTransactionError) as failure:
        await actions.takeoff(setup.drone, 10.0)

    setup.drone.action.land.assert_awaited_once()
    assert isinstance(failure.value.primary_error, TimeoutError)
    assert failure.value.final_vehicle_state["landed_state"] == "LANDING"


@pytest.mark.asyncio
async def test_takeoff_cancellation_after_command_waits_for_land_recovery(mocker):
    setup = _prepare_takeoff(
        mocker,
        observations=[
            _vehicle_state(),
            _vehicle_state(armed=True, landed_state="IN_AIR", relative_altitude_m=3.0),
            _vehicle_state(armed=True, landed_state="LANDING", relative_altitude_m=2.5),
        ],
        landed_side_effect=[asyncio.CancelledError(), "LANDING"],
    )

    with pytest.raises(asyncio.CancelledError):
        await actions.takeoff(setup.drone, 10.0)

    setup.drone.action.land.assert_awaited_once()
    assert actions._LAST_FINAL_VEHICLE_STATE["recovery_status"] == "land_recovery_started"
    assert actions._LAST_ACTION_CLEANUP_EVIDENCE["cleanup_confirmed"] is True


@pytest.mark.asyncio
async def test_takeoff_reports_unconfirmed_land_recovery_truthfully(mocker):
    setup = _prepare_takeoff(
        mocker,
        observations=[
            _vehicle_state(),
            _vehicle_state(armed=True, landed_state="IN_AIR", relative_altitude_m=3.0),
            _vehicle_state(armed=True, landed_state="IN_AIR", relative_altitude_m=3.0),
        ],
        takeoff_side_effect=RuntimeError("takeoff RPC uncertain"),
    )
    setup.drone.action.land.side_effect = RuntimeError("land RPC failed")

    assert await actions.safe_action(actions.takeoff, setup.drone, 10.0) is False
    result = actions._build_terminal_result("takeoff")

    assert result.final_vehicle_state["armed"] is True
    assert result.final_vehicle_state["recovery_status"] == "land_recovery_unconfirmed"
    assert "Safety cleanup could not be confirmed" in result.operator_message


@pytest.mark.asyncio
async def test_one_meter_takeoff_returns_truthful_terminal_state(mocker):
    setup = _prepare_takeoff(
        mocker,
        landed_side_effect=["TAKING_OFF"],
        altitude_side_effect=[SimpleNamespace(relative_altitude_m=0.6)],
    )

    await actions.takeoff(setup.drone, 1.0)
    result = actions._build_terminal_result("takeoff")

    assert result.success is True
    assert result.final_vehicle_state["armed"] is True
    assert result.final_vehicle_state["landed_state"] == "IN_AIR"
    assert result.final_vehicle_state["relative_altitude_m"] == pytest.approx(0.6)
    assert result.final_vehicle_state["minimum_confirmed_altitude_m"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_takeoff_waits_through_transition_before_terminal_success(mocker):
    setup = _prepare_takeoff(
        mocker,
        observations=[
            _vehicle_state(),
            _vehicle_state(
                armed=True,
                landed_state="TAKING_OFF",
                relative_altitude_m=8.1,
            ),
            _vehicle_state(
                armed=True,
                landed_state="IN_AIR",
                relative_altitude_m=9.0,
            ),
        ],
        landed_side_effect=["TAKING_OFF"],
        altitude_side_effect=[SimpleNamespace(relative_altitude_m=8.1)],
    )

    await actions.takeoff(setup.drone, 10.0)

    assert setup.observe.await_count == 3
    setup.drone.action.land.assert_not_awaited()
    assert actions._LAST_FINAL_VEHICLE_STATE["landed_state"] == "IN_AIR"
    assert actions._LAST_FINAL_VEHICLE_STATE["recovery_status"] == "not_required"


@pytest.mark.asyncio
async def test_takeoff_unconfirmed_final_state_is_typed_and_starts_land_recovery(mocker):
    transition_state = _vehicle_state(
        armed=True,
        landed_state="TAKING_OFF",
        relative_altitude_m=8.4,
    )
    setup = _prepare_takeoff(
        mocker,
        observations=[
            _vehicle_state(),
            transition_state,
            _vehicle_state(
                armed=True,
                landed_state="LANDING",
                relative_altitude_m=7.9,
            ),
        ],
        landed_side_effect=["TAKING_OFF", "LANDING"],
        altitude_side_effect=[SimpleNamespace(relative_altitude_m=8.1)],
    )
    wait_final = mocker.patch(
        "actions.wait_for_authoritative_airborne_state",
        new=mocker.AsyncMock(return_value=transition_state),
    )

    with pytest.raises(actions._ActionTransactionError) as failure:
        await actions.takeoff(setup.drone, 10.0)

    wait_final.assert_awaited_once_with(setup.drone, 8.0)
    assert isinstance(failure.value.primary_error, actions.ActionSafetyError)
    assert failure.value.primary_error.code == "TAKEOFF_FINAL_STATE_UNAVAILABLE"
    setup.drone.action.land.assert_awaited_once()
    assert failure.value.evidence["cleanup_confirmed"] is True
    assert failure.value.final_vehicle_state["recovery_status"] == "land_recovery_started"

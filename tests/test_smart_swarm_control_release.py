"""Release acknowledgement precedes non-flight teardown and reporting."""
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from smart_swarm_src.runtime_shutdown import SmartSwarmRuntimeLifecycle, VehicleHandoffResult


@pytest.mark.asyncio
async def test_release_precedes_helper_teardown_and_is_emitted_once():
    events = []
    def release(**facts):
        events.append(("release", facts))
    async def stop_producers(_logger):
        events.append(("producers", None))
    async def handoff(_drone, **_kwargs):
        events.append(("hold.accepted", None))
        return VehicleHandoffResult(True, True, observed_mode="OFFBOARD")
    def stop_helper(_server, **_kwargs):
        events.append(("helper.stop", None))
        raise RuntimeError("non-flight helper teardown failed")
    lifecycle = SmartSwarmRuntimeLifecycle(
        logging.getLogger(__name__), cancel_follower_tasks=stop_producers,
        vehicle_handoff=handoff, stop_mavsdk_server=stop_helper,
        shutdown_budget_sec=0.18, report_control_release=release)
    lifecycle.drone = object()
    lifecycle.mavsdk_server = object()
    assert not await lifecycle.shutdown("SIGTERM")
    assert not await lifecycle.shutdown("duplicate")
    assert [event for event, _facts in events] == ["producers", "hold.accepted", "release", "helper.stop"]
    facts = events[2][1]
    assert facts == {"producers_stopped": True, "offboard_stop_completed": True,
                     "hold_accepted": True, "observed_mode": "OFFBOARD",
                     "external_control_preserved": False}


@pytest.mark.asyncio
async def test_shutdown_before_control_established_releases_without_hold():
    release = Mock()
    handoff = AsyncMock()
    lifecycle = SmartSwarmRuntimeLifecycle(
        logging.getLogger(__name__), cancel_follower_tasks=AsyncMock(),
        vehicle_handoff=handoff, stop_mavsdk_server=Mock(),
        shutdown_budget_sec=0.18, report_control_release=release)
    assert await lifecycle.shutdown("startup interrupted")
    handoff.assert_not_awaited()
    release.assert_called_once_with(producers_stopped=True, offboard_stop_completed=False,
                                    hold_accepted=False, observed_mode=None,
                                    external_control_preserved=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("producer_failure,handoff", [
    (True, VehicleHandoffResult(True, True)),
    (False, VehicleHandoffResult(True, False)),
    (False, VehicleHandoffResult(False, False)),
])
async def test_incomplete_release_remains_unconfirmed(producer_failure, handoff):
    release = Mock()
    cancel = AsyncMock(side_effect=RuntimeError("producer cancellation failed") if producer_failure else None)
    lifecycle = SmartSwarmRuntimeLifecycle(
        logging.getLogger(__name__), cancel_follower_tasks=cancel,
        vehicle_handoff=AsyncMock(return_value=handoff), stop_mavsdk_server=Mock(),
        shutdown_budget_sec=0.18, report_control_release=release)
    lifecycle.drone = object()
    assert not await lifecycle.shutdown("SIGTERM")
    facts = release.call_args.kwargs
    assert not (facts["producers_stopped"] and (
        facts["hold_accepted"] or facts["external_control_preserved"]))


@pytest.mark.asyncio
async def test_external_pilot_control_preserved_is_not_hold_acceptance():
    release = Mock()
    lifecycle = SmartSwarmRuntimeLifecycle(
        logging.getLogger(__name__), cancel_follower_tasks=AsyncMock(),
        vehicle_handoff=AsyncMock(return_value=VehicleHandoffResult(
            False, False, control_preserved=True, observed_mode="RETURN_TO_LAUNCH")),
        stop_mavsdk_server=Mock(), shutdown_budget_sec=0.18,
        report_control_release=release)
    lifecycle.drone = object()
    assert await lifecycle.shutdown("pilot takeover")
    assert release.call_args.kwargs["external_control_preserved"]
    assert not release.call_args.kwargs["hold_accepted"]
    assert release.call_args.kwargs["observed_mode"] == "RETURN_TO_LAUNCH"

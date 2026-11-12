import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import postflight_mode


def state(*, armed=False, landed='ON_GROUND', mode='OFFBOARD', complete=True):
    return SimpleNamespace(complete=complete, armed=armed, landed_state=landed,
        field_value=lambda _: mode,
        as_dict=lambda: {'complete': complete, 'armed': armed, 'landed_state': landed,
                         'fields': {'flight_mode': {'value': mode}}})


@pytest.mark.asyncio
async def test_confirmed_residual_offboard_is_changed_once_and_verified(monkeypatch):
    observe = AsyncMock(side_effect=[state(), state(mode='HOLD')])
    monkeypatch.setattr(postflight_mode, 'observe_authoritative_vehicle_state', observe)
    drone = SimpleNamespace(action=SimpleNamespace(hold=AsyncMock()))
    result = await postflight_mode.finish_grounded_offboard(drone)
    assert result['status'] == 'hold_confirmed'
    drone.action.hold.assert_awaited_once()
    assert observe.await_count == 2


@pytest.mark.parametrize('before', [state(armed=True), state(armed=None),
    state(landed='IN_AIR'), state(landed=None), state(complete=False),
    state(mode='MANUAL'), state(mode='POSCTL'), state(mode='HOLD'), state(mode=None)])
@pytest.mark.asyncio
async def test_never_overrides_flight_manual_unknown_or_already_idle(monkeypatch, before):
    observe = AsyncMock(return_value=before)
    monkeypatch.setattr(postflight_mode, 'observe_authoritative_vehicle_state', observe)
    drone = SimpleNamespace(action=SimpleNamespace(hold=AsyncMock()))
    result = await postflight_mode.finish_grounded_offboard(drone)
    drone.action.hold.assert_not_awaited()
    assert not result['hold_requested']


@pytest.mark.asyncio
async def test_mode_ack_without_fresh_confirmation_is_not_success_or_replayed(monkeypatch):
    monkeypatch.setattr(postflight_mode, 'observe_authoritative_vehicle_state',
                        AsyncMock(side_effect=[state(), state(complete=False)]))
    drone = SimpleNamespace(action=SimpleNamespace(hold=AsyncMock()))
    result = await postflight_mode.finish_grounded_offboard(drone)
    assert result['status'] == 'hold_unconfirmed'
    drone.action.hold.assert_awaited_once()


@pytest.mark.parametrize('error', [TimeoutError(), RuntimeError('transport failed')])
@pytest.mark.asyncio
async def test_failed_mode_request_does_not_undo_landing_or_replay(monkeypatch, error):
    monkeypatch.setattr(postflight_mode, 'observe_authoritative_vehicle_state', AsyncMock(return_value=state()))
    drone = SimpleNamespace(action=SimpleNamespace(hold=AsyncMock(side_effect=error)))
    result = await postflight_mode.finish_grounded_offboard(drone)
    assert result['status'] == 'hold_unconfirmed'
    drone.action.hold.assert_awaited_once()


@pytest.mark.asyncio
async def test_superseding_cancellation_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(postflight_mode, 'observe_authoritative_vehicle_state',
                        AsyncMock(side_effect=asyncio.CancelledError()))
    drone = SimpleNamespace(action=SimpleNamespace(hold=AsyncMock()))
    with pytest.raises(asyncio.CancelledError):
        await postflight_mode.finish_grounded_offboard(drone)
    drone.action.hold.assert_not_awaited()

"""Fail-closed finite checks on DroneCommunicator timestamp helpers."""

from __future__ import annotations

from types import SimpleNamespace

from src.drone_communicator import DroneCommunicator


def _communicator_with_params(**params) -> DroneCommunicator:
    drone_config = SimpleNamespace(
        hw_id=1,
        pos_id=1,
        config={"ip": "127.0.0.1", "mavlink_port": 14540},
    )
    base = {
        "enable_udp_telemetry": False,
        "enable_default_subscriptions": False,
        "LOCAL_MAVLINK_TIMEOUT_SEC": 5,
        "LOCAL_MAVLINK_RECONNECT_AFTER_TIMEOUTS": 3,
    }
    base.update(params)
    return DroneCommunicator(
        drone_config=drone_config,
        params=SimpleNamespace(**base),
        drones={},
    )


def test_normalize_update_time_ms_rejects_non_finite():
    assert DroneCommunicator._normalize_update_time_ms(float("nan")) == 0
    assert DroneCommunicator._normalize_update_time_ms(float("inf")) == 0
    assert DroneCommunicator._normalize_update_time_ms(float("-inf")) == 0
    assert DroneCommunicator._normalize_update_time_ms("nan") == 0
    assert DroneCommunicator._normalize_update_time_ms("inf") == 0


def test_normalize_update_time_ms_happy_paths():
    # Seconds-scale timestamp scaled to ms
    assert DroneCommunicator._normalize_update_time_ms(1_700_000_000) == 1_700_000_000_000
    # Already-ms timestamp left alone
    assert DroneCommunicator._normalize_update_time_ms(1_700_000_000_000) == 1_700_000_000_000
    assert DroneCommunicator._normalize_update_time_ms(0) == 0
    assert DroneCommunicator._normalize_update_time_ms(-5) == 0
    assert DroneCommunicator._normalize_update_time_ms(None) == 0
    assert DroneCommunicator._normalize_update_time_ms("bogus") == 0


def test_local_mavlink_stale_threshold_rejects_non_finite_override():
    # Finite override wins
    comm = _communicator_with_params(LOCAL_MAVLINK_STALE_TIMEOUT_SEC=2.5)
    assert comm._local_mavlink_stale_threshold_ms() == 2500

    # Non-finite override falls back to timeout * reconnect (5 * 3 = 15s → 15000 ms)
    for poisoned in (float("nan"), float("inf"), float("-inf"), "nan", "inf"):
        comm = _communicator_with_params(LOCAL_MAVLINK_STALE_TIMEOUT_SEC=poisoned)
        assert comm._local_mavlink_stale_threshold_ms() == 15_000

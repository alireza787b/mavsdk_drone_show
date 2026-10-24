"""Action-specific cached admission never substitutes altitude for PX4 land state."""
from types import SimpleNamespace

import pytest

from src.command_admission import evaluate_cached_airborne_admission, evaluate_cached_hold_admission


def aircraft(**changes):
    fields = dict(is_armed=True, heartbeat_timestamp_ms=10000, landed_state=2,
                  landed_state_timestamp_ms=10000, px4_home_position_set=True,
                  global_position_timestamp_ms=10000, relative_altitude_m=-10)
    fields.update(changes)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize("state,accepted", [(0, False), (1, False), (2, True), (3, False), (4, False), (None, False)])
def test_start_requires_native_in_air_not_home_height(state, accepted):
    assert evaluate_cached_airborne_admission(aircraft(landed_state=state), max_age_sec=2, now_ms=10001).accepted is accepted


@pytest.mark.parametrize("changes", [{"landed_state_timestamp_ms": 0}, {"landed_state_timestamp_ms": 1},
    {"heartbeat_timestamp_ms": 0}, {"is_armed": False}, {"px4_home_position_set": False},
    {"global_position_timestamp_ms": 0}])
def test_start_fails_closed_on_missing_required_native_or_guidance_evidence(changes):
    assert not evaluate_cached_airborne_admission(aircraft(**changes), max_age_sec=2, now_ms=10001).accepted


@pytest.mark.parametrize("armed", [False, True])
def test_hold_has_no_home_altitude_or_landed_gate(armed):
    node = aircraft(is_armed=armed, landed_state=None, landed_state_timestamp_ms=0,
                    px4_home_position_set=False, relative_altitude_m=None, global_position_timestamp_ms=0)
    assert evaluate_cached_hold_admission(node, max_age_sec=2, now_ms=10001).accepted

from types import SimpleNamespace

import pytest

from src.smart_swarm_admission import evaluate_smart_swarm_start_admission
from src.enums import Mission, State


def aircraft(**overrides):
    return SimpleNamespace(**dict(dict(hw_id=1, state=State.IDLE.value, mission=0,
        is_armed=True, px4_home_position_set=True, heartbeat_timestamp_ms=10000,
        global_position_timestamp_ms=10000, relative_altitude_m=5,
        landed_state=2, landed_state_timestamp_ms=10000,
        custom_mode=(4 << 16) | (3 << 24)), **overrides))


def test_takeoff_only_becomes_ready_after_exact_owner_retires():
    node = aircraft(state=State.MISSION_EXECUTING.value, mission=Mission.TAKE_OFF.value)
    decision = evaluate_smart_swarm_start_admission(node, max_age_sec=15, now_ms=10001)
    assert decision.status == 'waiting' and decision.reason_code == 'finishing_takeoff'
    node.state, node.mission = State.IDLE.value, 0
    decision = evaluate_smart_swarm_start_admission(node, max_age_sec=15, now_ms=10001)
    assert decision.status == 'ready' and decision.valid_for_ms == 14999


@pytest.mark.parametrize('mode,status', [((4 << 16) | (2 << 24), 'waiting'),
    ((4 << 16) | (5 << 24), 'blocked'), ((4 << 16) | (6 << 24), 'blocked'),
    (0, 'unknown'), (3 << 16, 'ready')])
def test_manual_takeoff_supported_but_native_recovery_not_preempted(mode, status):
    assert evaluate_smart_swarm_start_admission(aircraft(custom_mode=mode), max_age_sec=15, now_ms=10001).status == status


@pytest.mark.parametrize('overrides,status', [({'is_armed':False}, 'blocked'),
    ({'heartbeat_timestamp_ms':0}, 'unknown'), ({'global_position_timestamp_ms':0}, 'unknown'),
    ({'state':2,'mission':112}, 'blocked'), ({'landed_state':1}, 'blocked'),
    ({'landed_state':3}, 'blocked'), ({'landed_state_timestamp_ms':0}, 'unknown')])
def test_unknown_or_ineligible_is_never_ready(overrides, status):
    assert evaluate_smart_swarm_start_admission(aircraft(**overrides), max_age_sec=15, now_ms=10001).status == status


@pytest.mark.parametrize('height', [-20, 0, 0.1, 100])
def test_native_in_air_not_home_height_is_authoritative(height):
    assert evaluate_smart_swarm_start_admission(aircraft(relative_altitude_m=height), max_age_sec=15, now_ms=10001).status == 'ready'

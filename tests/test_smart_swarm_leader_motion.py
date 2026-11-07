import pytest
import math
from smart_swarm_src.leader_motion import (
    leader_heading_rate_deg_s,
    project_leader_heading,
    project_leader_motion,
)
from smart_swarm_src.utils import transform_body_to_nea


def sample(**kwargs):
    return dict(pos_n=8., pos_e=0., pos_d=-10., vel_n=0., vel_e=0., vel_d=0., update_time=10., **kwargs)


def test_prediction_is_bounded_and_does_not_accumulate_or_modify_measurement():
    state = sample()
    state['vel_n'] = 2.
    assert project_leader_motion(state, now_s=10.1, max_prediction_s=1)[0] == pytest.approx(8.2)
    assert project_leader_motion(state, now_s=10.2, max_prediction_s=1)[0] == pytest.approx(8.4)
    assert project_leader_motion(state, now_s=30, max_prediction_s=1)[0] == pytest.approx(10.)
    assert state['pos_n'] == 8.
    assert state['update_time'] == 10.


def test_measured_stop_has_no_phantom_speed_from_previous_manoeuvre():
    state = sample()
    for i in range(60):
        moving = {**state, 'vel_n': 4., 'update_time': 9 + i / 60}
        project_leader_motion(moving, now_s=10, max_prediction_s=1)
    stopped = project_leader_motion(state, now_s=10.05, max_prediction_s=1)
    assert list(stopped) == [8., 0., -10., 0., 0., 0.]


@pytest.mark.parametrize('field', ['pos_n', 'vel_e', 'update_time'])
def test_invalid_projection_never_reaches_command_shaper(field):
    state = sample()
    state[field] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        project_leader_motion(state, now_s=10, max_prediction_s=1)


def test_heading_projects_from_attitude_time_not_position_or_receipt_time():
    state = sample(yaw=10.0, yaw_rate_deg_s=20.0, attitude_update_time=10.3,
                   received_monotonic=10.45)
    state['vel_n'] = 2.0
    assert project_leader_motion(state, now_s=10.5, max_prediction_s=1)[0] == pytest.approx(9.0)
    assert project_leader_heading(state, now_s=10.5, max_prediction_s=1) == pytest.approx(14.0)


def test_heading_prediction_wraps_bounds_and_does_not_accumulate():
    state = sample(yaw=359.0, yaw_rate_deg_s=20.0, attitude_update_time=10.0)
    assert project_leader_heading(state, now_s=10.1, max_prediction_s=1) == pytest.approx(1.0)
    assert project_leader_heading(state, now_s=10.2, max_prediction_s=1) == pytest.approx(3.0)
    assert project_leader_heading(state, now_s=30.0, max_prediction_s=1) == pytest.approx(19.0)
    assert project_leader_heading(state, now_s=9.0, max_prediction_s=1) == pytest.approx(359.0)
    assert state['yaw'] == 359.0
    assert state['attitude_update_time'] == 10.0


@pytest.mark.parametrize('rate', [None, float('nan'), float('inf')])
def test_heading_without_a_usable_rate_is_not_rotated(rate):
    state = sample(yaw=25.0, yaw_rate_deg_s=rate, attitude_update_time=10.0)
    assert project_leader_heading(state, now_s=10.5, max_prediction_s=1) == 25.0


@pytest.mark.parametrize('field', ['yaw', 'attitude_update_time'])
def test_heading_rejects_nonfinite_state_or_clock(field):
    state = sample(yaw=25.0, yaw_rate_deg_s=2.0, attitude_update_time=10.0)
    state[field] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        project_leader_heading(state, now_s=10.5, max_prediction_s=1)


def test_heading_rate_fallback_wraps_and_uses_source_attitude_interval():
    previous = dict(yaw=359.0, attitude_timestamp_ms=1000, received_monotonic=5.0)
    current = dict(yaw_deg=1.0, attitude_timestamp_ms=1200, received_monotonic=50.0)
    assert leader_heading_rate_deg_s(current, previous, max_sample_interval_s=0.75) == pytest.approx(10.0)


@pytest.mark.parametrize('timestamp', [1000, 999, 2000, float('nan'), 1000.5])
def test_heading_rate_fallback_rejects_repeated_reversed_old_or_invalid_clock(timestamp):
    previous = dict(yaw=0.0, attitude_timestamp_ms=1000)
    current = dict(yaw_deg=10.0, attitude_timestamp_ms=timestamp)
    assert leader_heading_rate_deg_s(current, previous, max_sample_interval_s=0.75) == 0.0


def test_heading_rate_fallback_does_not_reject_rates_above_follower_yaw_limit():
    previous = dict(yaw=0.0, attitude_timestamp_ms=1000)
    current = dict(yaw_deg=18.0, attitude_timestamp_ms=1200)
    assert leader_heading_rate_deg_s(current, previous, max_sample_interval_s=0.75) == pytest.approx(90.0)
    current['yaw_rate_deg_s'] = 120.0
    assert leader_heading_rate_deg_s(current, previous, max_sample_interval_s=0.75) == 120.0


def test_rotating_body_offset_position_and_tangential_velocity_use_same_heading_time():
    state = sample(yaw=0.0, yaw_rate_deg_s=20.0, attitude_update_time=10.0)
    now_s = 10.4
    yaw = project_leader_heading(state, now_s=now_s, max_prediction_s=1.0)
    north, east = transform_body_to_nea(6.0, -2.0, yaw)
    rate_rad_s = math.radians(state['yaw_rate_deg_s'])
    tangent = (-east * rate_rad_s, north * rate_rad_s)
    step_s = 1e-5
    next_yaw = project_leader_heading(state, now_s=now_s + step_s, max_prediction_s=1.0)
    next_north, next_east = transform_body_to_nea(6.0, -2.0, next_yaw)
    assert (next_north - north) / step_s == pytest.approx(tangent[0], abs=1e-5)
    assert (next_east - east) / step_s == pytest.approx(tangent[1], abs=1e-5)

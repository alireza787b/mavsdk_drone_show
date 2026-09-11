import pytest
from smart_swarm_src.leader_motion import project_leader_motion


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

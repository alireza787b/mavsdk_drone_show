import math
import pytest
from src.trajectory_clock import ClockState, TrajectoryClockRamp, retime_kinematics


@pytest.mark.parametrize('action,initial,final', [('pause',1,0), ('resume',0,1)])
def test_clock_ramp_is_continuous_monotone_and_smooth_at_boundaries(action, initial, final):
    ramp = TrajectoryClockRamp(action, 100, 20, 4)
    before = ramp.sample(100)
    after = ramp.sample(104)
    assert before == ClockState(20, initial, 0, 0)
    assert after == ClockState(22, final, 0, 0)
    samples = [ramp.sample(100+i*.004) for i in range(1001)]
    assert all(b.route_time_s >= a.route_time_s for a,b in zip(samples, samples[1:]))
    assert all(0 <= s.rate <= 1 for s in samples)
    assert samples[1].rate == pytest.approx(initial, abs=1e-7)
    assert samples[-2].rate == pytest.approx(final, abs=1e-7)
    assert ramp.sample(105).route_time_s == 22+final


def test_resume_does_not_spend_paused_wall_time():
    pause = TrajectoryClockRamp('pause',100,20,4)
    anchor = pause.sample(200).route_time_s
    assert anchor == 22
    resume = TrajectoryClockRamp('resume',200,anchor,4)
    assert resume.sample(200).route_time_s == anchor
    assert resume.sample(202).route_time_s < anchor+1
    assert resume.sample(204).route_time_s == anchor+2


@pytest.mark.parametrize('action', ['pause','resume'])
def test_chain_rule_matches_finite_difference_for_cubic_path(action):
    ramp = TrajectoryClockRamp(action,0,1,5)
    t,h = 2.0,1e-3
    clock = ramp.sample(t)
    s = clock.route_time_s
    v,a,j = retime_kinematics((3*s*s,0,0), (6*s,0,0), (6,0,0), clock)
    path = lambda time: ramp.sample(time).route_time_s**3
    assert v[0] == pytest.approx((path(t+h)-path(t-h))/(2*h), rel=1e-5)
    assert a[0] == pytest.approx((path(t+h)-2*path(t)+path(t-h))/(h*h), rel=1e-5)
    # Differentiate acceleration rather than unstable third position differences.
    def acceleration(time):
        c = ramp.sample(time); s = c.route_time_s
        return retime_kinematics((3*s*s,0,0),(6*s,0,0),(6,0,0),c)[1][0]
    assert j[0] == pytest.approx((acceleration(t+h)-acceleration(t-h))/(2*h), rel=1e-5)


@pytest.mark.parametrize('field,value', [('duration_s',0),('duration_s',-1),('start_time_s',math.nan),
    ('route_time_s',math.inf),('route_time_s',-1),('duration_s',True)])
def test_invalid_clock_inputs_are_rejected(field,value):
    values = dict(action='pause',start_time_s=0,route_time_s=0,duration_s=2)
    values[field] = value
    with pytest.raises(ValueError):
        TrajectoryClockRamp(**values)


def test_paused_clock_commands_zero_kinematics():
    stopped = TrajectoryClockRamp('pause',0,10,2).sample(3)
    assert retime_kinematics((5,2,1),(3,1,1),(1,1,1),stopped) == ((0,0,0),(0,0,0),(0,0,0))

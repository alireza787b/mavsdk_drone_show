import numpy as np


def test_optional_total_speed_envelope_preserves_derivative_limits_on_diagonal_turns():
    from smart_swarm_src.velocity_command_shaper import NedVelocityCommandShaper
    shaper = NedVelocityCommandShaper(max_horizontal_speed_m_s=5, max_vertical_speed_m_s=5,
                                     max_total_speed_m_s=5, max_acceleration_m_s2=2,
                                     max_jerk_m_s3=4, max_dt_s=.1)
    previous = np.zeros(3)
    previous_acc = np.zeros(3)
    for target in [(8, 8, 8), (-8, 0, 8), (0, -8, -8), (0, 0, 0)]:
        for _ in range(150):
            command = shaper.shape(target, .1)
            acc = (command-previous)/.1
            assert np.linalg.norm(command) <= 5+1e-8
            assert np.linalg.norm(acc) <= 2+1e-8
            assert np.linalg.norm(acc-previous_acc)/.1 <= 4+1e-8
            previous, previous_acc = command, acc
import pytest

from smart_swarm_src.velocity_command_shaper import (
    NedVelocityCommandShaper,
    VelocityCommandShapeError,
)


def _shaper(**overrides):
    values = {
        "max_horizontal_speed_m_s": 3.0,
        "max_vertical_speed_m_s": 1.0,
        "max_acceleration_m_s2": 2.0,
        "max_jerk_m_s3": 4.0,
        "max_dt_s": 0.1,
    }
    values.update(overrides)
    return NedVelocityCommandShaper(**values)


def test_default_seed_matches_zero_offboard_command_and_acceleration():
    shaper = _shaper()

    assert np.array_equal(shaper.velocity_ned, np.zeros(3))
    assert np.array_equal(shaper.acceleration_ned, np.zeros(3))
    assert shaper.limiting_factors == ()


def test_limiter_diagnostics_are_bounded_and_preserve_last_good_state():
    shaper = _shaper()
    shaper.shape([100, 0, 100], 1)
    assert {'horizontal_speed', 'vertical_speed', 'dt', 'jerk'} <= set(shaper.limiting_factors)
    before = shaper.limiting_factors
    with pytest.raises(VelocityCommandShapeError):
        shaper.shape([np.nan, 0, 0], .1)
    assert shaper.limiting_factors == before
    shaper.reset()
    assert shaper.limiting_factors == ()


@pytest.mark.parametrize('speed', [1.0, 3.0, 5.0])
def test_responsive_profile_brakes_faster_without_discontinuities(speed):
    def brake(accel_limit, jerk_limit):
        shaper = _shaper(max_horizontal_speed_m_s=6,
                         max_vertical_speed_m_s=1.25,
                         max_acceleration_m_s2=accel_limit,
                         max_jerk_m_s3=jerk_limit,
                         seed_velocity_ned=(speed, 0, 0))
        previous = shaper.velocity_ned
        acceleration = shaper.acceleration_ned
        travel = 0.0
        for i in range(300):
            command = shaper.shape((0, 0, 0), 1/15)
            next_acceleration = (command-previous)*15
            assert np.linalg.norm(next_acceleration) <= accel_limit+1e-8
            assert np.linalg.norm(next_acceleration-acceleration)*15 <= jerk_limit+1e-7
            assert command[0] >= -1e-8
            travel += command[0]/15
            if np.linalg.norm(command) < .05:
                return (i+1)/15, travel
            previous, acceleration = command, next_acceleration
        pytest.fail('Shaper did not settle')

    conservative = brake(1, 2)
    responsive = brake(3, 6)
    assert responsive[0] < conservative[0]
    assert responsive[1] < conservative[1]


def test_first_large_request_is_jerk_and_acceleration_limited_from_zero():
    shaper = _shaper()
    dt = 1.0 / 15.0

    command = shaper.shape([100.0, 0.0, 100.0], dt)

    jerk_limited_acceleration = shaper.max_jerk_m_s3 * dt
    assert np.linalg.norm(shaper.acceleration_ned) == pytest.approx(
        jerk_limited_acceleration
    )
    assert np.linalg.norm(command) == pytest.approx(jerk_limited_acceleration * dt)
    assert np.linalg.norm(command) < 0.02


@pytest.mark.parametrize(
    ("command", "dt"),
    [
        ([np.nan, 0.0, 0.0], 0.05),
        ([0.0, np.inf, 0.0], 0.05),
        ([0.0, 0.0, -np.inf], 0.05),
        ([0.0, 0.0, 0.0], np.nan),
        ([0.0, 0.0, 0.0], np.inf),
        ([0.0, 0.0, 0.0], 0.0),
    ],
)
def test_non_finite_or_non_positive_input_fails_without_mutating_state(command, dt):
    shaper = _shaper()
    shaper.shape([1.0, 0.0, 0.0], 0.05)
    velocity_before = shaper.velocity_ned
    acceleration_before = shaper.acceleration_ned

    with pytest.raises(VelocityCommandShapeError):
        shaper.shape(command, dt)

    assert np.array_equal(shaper.velocity_ned, velocity_before)
    assert np.array_equal(shaper.acceleration_ned, acceleration_before)


def test_horizontal_and_vertical_speed_caps_are_independent():
    shaper = _shaper(
        max_horizontal_speed_m_s=2.0,
        max_vertical_speed_m_s=0.5,
    )

    commands = [shaper.shape([20.0, 20.0, 20.0], 0.05) for _ in range(300)]
    final = commands[-1]

    assert np.linalg.norm(final[:2]) <= 2.0 + 1e-9
    assert abs(final[2]) <= 0.5 + 1e-9
    assert final[:2] == pytest.approx([np.sqrt(2.0), np.sqrt(2.0)], abs=1e-6)
    assert final[2] == pytest.approx(0.5, abs=1e-6)


def test_acceleration_and_jerk_hold_across_direction_changes():
    shaper = _shaper(max_horizontal_speed_m_s=2.5, max_vertical_speed_m_s=0.6)
    dt = 0.05
    previous_velocity = shaper.velocity_ned
    previous_acceleration = shaper.acceleration_ned
    requests = (
        [[4.0, 0.0, 1.0]] * 80
        + [[-4.0, 3.0, -1.0]] * 160
        + [[0.0, 0.0, 0.0]] * 120
    )

    for request in requests:
        command = shaper.shape(request, dt)
        acceleration = (command - previous_velocity) / dt
        jerk = (acceleration - previous_acceleration) / dt

        assert np.linalg.norm(command[:2]) <= 2.5 + 1e-9
        assert abs(command[2]) <= 0.6 + 1e-9
        assert np.linalg.norm(acceleration) <= 2.0 + 1e-9
        assert np.linalg.norm(jerk) <= 4.0 + 1e-8

        previous_velocity = command
        previous_acceleration = acceleration


def test_dt_is_capped_so_a_stall_cannot_authorize_a_larger_step():
    stalled = _shaper(max_dt_s=0.05)
    on_time = _shaper(max_dt_s=0.05)

    delayed_command = stalled.shape([3.0, 0.0, 0.0], 5.0)
    on_time_command = on_time.shape([3.0, 0.0, 0.0], 0.05)

    assert delayed_command == pytest.approx(on_time_command)
    assert delayed_command[0] == pytest.approx(4.0 * 0.05 * 0.05)


def test_explicit_reset_preserves_supplied_continuity_seed_exactly():
    shaper = _shaper()
    seed_velocity = np.array([0.4, -0.2, 0.1])
    seed_acceleration = np.array([0.1, 0.0, -0.1])

    shaper.reset(
        seed_velocity_ned=seed_velocity,
        seed_acceleration_ned=seed_acceleration,
    )

    assert np.array_equal(shaper.velocity_ned, seed_velocity)
    assert np.array_equal(shaper.acceleration_ned, seed_acceleration)

    command = shaper.shape([3.0, 0.0, 0.0], 0.05)
    acceleration = (command - seed_velocity) / 0.05
    jerk = (acceleration - seed_acceleration) / 0.05
    assert np.linalg.norm(acceleration) <= 2.0 + 1e-9
    assert np.linalg.norm(jerk) <= 4.0 + 1e-8


def test_invalid_reset_seed_preserves_previous_state():
    shaper = _shaper()
    shaper.shape([1.0, 0.0, 0.0], 0.05)
    velocity_before = shaper.velocity_ned
    acceleration_before = shaper.acceleration_ned

    with pytest.raises(VelocityCommandShapeError):
        shaper.reset(
            seed_velocity_ned=[4.0, 0.0, 0.0],
            seed_acceleration_ned=[0.0, 0.0, 0.0],
        )

    assert np.array_equal(shaper.velocity_ned, velocity_before)
    assert np.array_equal(shaper.acceleration_ned, acceleration_before)


def test_reset_without_seed_returns_to_exact_zero_state():
    shaper = _shaper()
    for _ in range(10):
        shaper.shape([2.0, 0.0, 0.0], 0.05)

    shaper.reset()

    assert np.array_equal(shaper.velocity_ned, np.zeros(3))
    assert np.array_equal(shaper.acceleration_ned, np.zeros(3))


def test_reset_rejects_outward_acceleration_without_braking_reserve():
    shaper = _shaper()
    with pytest.raises(VelocityCommandShapeError, match="braking reserve"):
        shaper.reset(seed_velocity_ned=(3, 0, 0), seed_acceleration_ned=(1, 0, 0))
    assert np.array_equal(shaper.velocity_ned, np.zeros(3))


def test_field_limits_sustained_saturation_turns_and_jitter():
    shaper = _shaper(max_horizontal_speed_m_s=2.0, max_vertical_speed_m_s=0.75,
                     max_acceleration_m_s2=1.0, max_jerk_m_s3=2.0)
    rng = np.random.default_rng(911)
    for i in range(5000):
        dt = float(rng.uniform(0.02, 0.1))
        angle = 0.08 * i if i > 1500 else 0.17
        request = [5 * np.cos(angle), 5 * np.sin(angle), np.sin(i * 0.02)]
        previous = shaper.velocity_ned
        previous_a = shaper.acceleration_ned
        command = shaper.shape(request, dt)
        a = (command - previous) / dt
        assert np.linalg.norm(command[:2]) <= 2 + 1e-9
        assert abs(command[2]) <= 0.75 + 1e-9
        assert np.linalg.norm(a) <= 1 + 1e-9
        assert np.linalg.norm(a - previous_a) / dt <= 2 + 1e-7

import math

import pytest

from src.trajectory_reentry import ReentryLimits, ReentrySeparationError, plan_reentry


LIMITS = ReentryLimits(speed_m_s=5, acceleration_m_s2=2, jerk_m_s3=4)


def test_one_shared_duration_and_zero_endpoint_velocity_acceleration():
    held = {'1': (0, 0, -10), '2': (0, 10, -10)}
    target = {'1': (10, 0, -12), '2': (20, 10, -15)}
    plan = plan_reentry(held, target, LIMITS, minimum_separation_m=5)
    assert plan.duration_s > 1
    assert plan.closest_approach.distance_m >= 10
    for elapsed, expected in [(0, held), (plan.duration_s, target)]:
        for sample in plan.sample(elapsed):
            assert sample.position_ned_m == pytest.approx(expected[sample.aircraft_id])
            assert sample.velocity_ned_m_s == (0, 0, 0)
            assert sample.acceleration_ned_m_s2 == (0, 0, 0)


@pytest.mark.parametrize('distance', [0.001, 1, 100, 10000])
@pytest.mark.parametrize('limits', [LIMITS, ReentryLimits(0.2, 100, 100),
                                   ReentryLimits(100, 0.1, 100), ReentryLimits(100, 100, 0.05)])
def test_all_kinematic_bounds_hold_at_analytic_extrema(distance, limits):
    plan = plan_reentry({'1': (0, 0, 0)}, {'1': (distance / 3, distance * 2 / 3, distance * 2 / 3)},
                       limits, minimum_separation_m=0)
    fractions = [0, 0.5, 1, (3 - math.sqrt(3)) / 6, (3 + math.sqrt(3)) / 6]
    for fraction in fractions:
        point = plan.sample(plan.duration_s * fraction)[0]
        assert math.hypot(*point.velocity_ned_m_s) <= limits.speed_m_s * (1 + 1e-12)
        assert math.hypot(*point.acceleration_ned_m_s2) <= limits.acceleration_m_s2 * (1 + 1e-12)
        assert math.hypot(*point.jerk_ned_m_s3) <= limits.jerk_m_s3 * (1 + 1e-12)


def test_crossing_is_detected_between_samples_analytically():
    with pytest.raises(ReentrySeparationError) as error:
        plan_reentry({'1': (0, 0, 0), '2': (1, 0, 0)},
                     {'1': (8, 0, 0), '2': (2, 0, 0)}, LIMITS, minimum_separation_m=0.1)
    assert error.value.evidence.progress == pytest.approx(1 / 7)
    assert error.value.evidence.distance_m == pytest.approx(0, abs=1e-14)
    assert error.value.evidence.aircraft_ids == ('1', '2')


@pytest.mark.parametrize('held,target,progress', [
    ({'1': (0, 0, 0), '2': (1, 0, 0)}, {'1': (0, 0, 0), '2': (10, 0, 0)}, 0),
    ({'1': (0, 0, 0), '2': (10, 0, 0)}, {'1': (0, 0, 0), '2': (1, 0, 0)}, 1),
])
def test_initial_and_final_separation_are_not_ignored(held, target, progress):
    with pytest.raises(ReentrySeparationError) as error:
        plan_reentry(held, target, LIMITS, minimum_separation_m=2)
    assert error.value.evidence.progress == progress
    assert error.value.evidence.distance_m == 1


def test_stationary_fleet_has_explicit_positive_duration_and_no_motion():
    positions = {'1': (10, 20, -30), '2': (10, 26, -30)}
    plan = plan_reentry(positions, positions, LIMITS, minimum_separation_m=6)
    assert plan.duration_s == 1
    assert plan.closest_approach.distance_m == 6
    for sample in plan.sample(0.5):
        assert sample.position_ned_m == positions[sample.aircraft_id]
        assert sample.velocity_ned_m_s == (0, 0, 0)


def test_one_aircraft_has_no_invented_pair_evidence():
    plan = plan_reentry({'1': (0, 0, 0)}, {'1': (1, 2, 3)}, LIMITS, minimum_separation_m=2)
    assert plan.closest_approach is None


@pytest.mark.parametrize('held,target', [({}, {}), ({'1': (0, 0, 0)}, {}),
    ({'1': (0, 0, 0)}, {'2': (1, 1, 1)}), ({'': (0, 0, 0)}, {'': (1, 1, 1)}),
    ({1: (0, 0, 0)}, {1: (1, 1, 1)}), ({'1': (0, 0)}, {'1': (1, 1, 1)}),
    ({'1': (0, float('nan'), 0)}, {'1': (1, 1, 1)}),
    ({'1': (0, 0, 0)}, {'1': (1, float('inf'), 1)}),
    ({'1': (False, 0, 0)}, {'1': (1, 1, 1)}),
    ({'1': ('0', 0, 0)}, {'1': (1, 1, 1)}),
    ({'1': None}, {'1': (1, 1, 1)}),
    ({'1': (0, 0, 0)}, None),
    (None, {'1': (1, 1, 1)}),
])
def test_invalid_aircraft_geometry_is_rejected(held, target):
    with pytest.raises(ValueError):
        plan_reentry(held, target, LIMITS, minimum_separation_m=2)


@pytest.mark.parametrize('field', ['speed_m_s', 'acceleration_m_s2', 'jerk_m_s3', 'minimum_duration_s'])
@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), True, '1'])
def test_invalid_limits_are_rejected(field, value):
    settings = dict(speed_m_s=5, acceleration_m_s2=2, jerk_m_s3=4, minimum_duration_s=1)
    settings[field] = value
    with pytest.raises(ValueError):
        ReentryLimits(**settings)


@pytest.mark.parametrize('separation', [-1, float('inf'), float('nan'), True])
def test_invalid_separation_is_rejected(separation):
    with pytest.raises(ValueError):
        plan_reentry({'1': (0, 0, 0)}, {'1': (1, 1, 1)}, LIMITS, minimum_separation_m=separation)


@pytest.mark.parametrize('time', [-1, float('inf'), float('nan'), True])
def test_invalid_sample_time_is_rejected(time):
    plan = plan_reentry({'1': (0, 0, 0)}, {'1': (1, 1, 1)}, LIMITS, minimum_separation_m=0)
    with pytest.raises(ValueError):
        plan.sample(time)


def test_plan_copies_input_and_is_deterministic():
    first = [0, 0, 0]
    held = {'2': (0, 10, 0), '1': first}
    target = {'1': (10, 0, 0), '2': (10, 10, 0)}
    plan = plan_reentry(held, target, LIMITS, minimum_separation_m=5)
    first[0] = 100
    target['1'] = (200, 0, 0)
    assert plan.paths[0].aircraft_id == '1'
    assert plan.sample(0)[0].position_ned_m == (0, 0, 0)
    assert plan.sample(plan.duration_s)[0].position_ned_m == (10, 0, 0)


def test_finite_values_whose_displacement_overflows_are_rejected():
    with pytest.raises(ValueError, match='finite numeric range'):
        plan_reentry({'1': (-1e308, 0, 0)}, {'1': (1e308, 0, 0)},
                     LIMITS, minimum_separation_m=0)

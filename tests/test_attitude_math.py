import math

import pytest

from src.attitude_math import body_rates_to_heading_rate_deg_s


def test_level_body_z_rate_is_heading_rate():
    assert body_rates_to_heading_rate_deg_s(0.0, 0.0, 0.2, 0.5) == pytest.approx(
        math.degrees(0.5)
    )


def test_tilted_heading_rate_uses_pitch_and_body_z_rates():
    roll, pitch, pitch_rate, body_z_rate = math.radians(30), math.radians(40), 0.4, 0.5
    expected = math.degrees(
        (pitch_rate * math.sin(roll) + body_z_rate * math.cos(roll)) / math.cos(pitch)
    )
    actual = body_rates_to_heading_rate_deg_s(roll, pitch, pitch_rate, body_z_rate)
    assert actual == pytest.approx(expected)
    assert actual != pytest.approx(math.degrees(body_z_rate))


def test_roll_can_turn_pitch_rate_into_heading_change_without_body_z_rotation():
    assert body_rates_to_heading_rate_deg_s(math.pi / 2, 0.0, -0.5, 0.0) == pytest.approx(
        math.degrees(-0.5)
    )


@pytest.mark.parametrize('pitch', [math.pi / 2, -math.pi / 2, math.pi / 2 - 1e-8])
def test_pitch_singularity_has_no_heading_rate_instead_of_body_z_substitution(pitch):
    assert body_rates_to_heading_rate_deg_s(0.0, pitch, 0.2, 0.5) is None


@pytest.mark.parametrize('index', range(4))
@pytest.mark.parametrize('invalid', [None, float('nan'), float('inf'), True])
def test_incomplete_or_nonfinite_attitude_has_no_rate(index, invalid):
    values = [0.2, 0.3, 0.4, 0.5]
    values[index] = invalid
    assert body_rates_to_heading_rate_deg_s(*values) is None


def test_measured_heading_rate_is_not_clipped_to_a_follower_command_limit():
    assert body_rates_to_heading_rate_deg_s(0.0, 0.0, 0.0, math.pi) == pytest.approx(180.0)

import pytest

from src.params import Params, _positive_env_float


@pytest.mark.parametrize('value', ['nan', 'inf', '-inf', '0', '-1', 'invalid'])
def test_invalid_motion_override_keeps_finite_positive_default(monkeypatch, value):
    monkeypatch.setenv('MDS_TEST_MOTION_LIMIT', value)
    assert _positive_env_float('MDS_TEST_MOTION_LIMIT', 5.0) == 5.0


def test_valid_motion_override(monkeypatch):
    monkeypatch.setenv('MDS_TEST_MOTION_LIMIT', '3.5')
    assert _positive_env_float('MDS_TEST_MOTION_LIMIT', 5.0) == 3.5


def test_default_motion_profile():
    assert Params.SMART_SWARM_MAX_HORIZONTAL_SPEED_M_S == 5.0
    assert Params.SMART_SWARM_MAX_ACCELERATION_M_S2 == 1.0
    assert Params.SMART_SWARM_MAX_JERK_M_S3 == 2.0

import navpy
import pytest

from functions.swarm_global_calculator import (
    calculate_follower_global_position,
    calculate_follower_yaw,
)


def _leader_relative_ned(follower_lla, leader_lla):
    return navpy.lla2ned(
        follower_lla[0],
        follower_lla[1],
        follower_lla[2],
        leader_lla[0],
        leader_lla[1],
        leader_lla[2],
        latlon_unit='deg',
        alt_unit='m',
        model='wgs84',
    )


def test_ned_offsets_use_leader_local_reference_and_up_positive_altitude():
    leader = (35.7000, 51.4000, 1200.0)
    far_origin = {'lat': 34.0000, 'lon': 49.0000, 'alt': 500.0}
    near_origin = {'lat': 35.6990, 'lon': 51.3990, 'alt': 1190.0}
    offset_config = {
        'offset_x': 15.0,
        'offset_y': -5.0,
        'offset_z': 3.0,
        'frame': 'ned',
    }

    far_result = calculate_follower_global_position(*leader, 0.0, offset_config, far_origin)
    near_result = calculate_follower_global_position(*leader, 0.0, offset_config, near_origin)

    assert far_result == pytest.approx(near_result, abs=1e-12)

    north, east, down = _leader_relative_ned(far_result, leader)
    assert north == pytest.approx(15.0, abs=0.05)
    assert east == pytest.approx(-5.0, abs=0.05)
    assert down == pytest.approx(-3.0, abs=0.05)


def test_body_offsets_follow_leader_heading_with_up_positive_altitude():
    leader = (35.7000, 51.4000, 1200.0)
    offset_config = {
        'offset_x': 10.0,
        'offset_y': 2.0,
        'offset_z': 4.0,
        'frame': 'body',
    }

    follower = calculate_follower_global_position(
        *leader,
        90.0,
        offset_config,
        {'lat': 0.0, 'lon': 0.0, 'alt': 0.0},
    )

    north, east, down = _leader_relative_ned(follower, leader)
    assert north == pytest.approx(-2.0, abs=0.05)
    assert east == pytest.approx(10.0, abs=0.05)
    assert down == pytest.approx(-4.0, abs=0.05)


def test_follower_yaw_defaults_to_leader_yaw():
    assert calculate_follower_yaw(137.5, {'frame': 'body'}) == pytest.approx(137.5)

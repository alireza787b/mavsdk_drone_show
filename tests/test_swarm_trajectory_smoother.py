import math

import pandas as pd
import pytest

from functions import swarm_trajectory_smoother as sts


def _meters_to_lon_delta(meters, latitude_deg):
    return meters / (111320.0 * math.cos(math.radians(latitude_deg)))


def test_smooth_trajectory_with_waypoints_outputs_ned_metric_velocities():
    origin_lat = 35.0
    origin_lon = 51.0
    east_delta_deg = _meters_to_lon_delta(10.0, origin_lat)

    waypoints = pd.DataFrame(
        [
            {
                "Name": "WP1",
                "Latitude": origin_lat,
                "Longitude": origin_lon,
                "Altitude_MSL_m": 100.0,
                "TimeFromStart_s": 0.0,
                "EstimatedSpeed_ms": 0.0,
                "Heading_deg": 90.0,
                "HeadingMode": "manual",
            },
            {
                "Name": "WP2",
                "Latitude": origin_lat,
                "Longitude": origin_lon + east_delta_deg,
                "Altitude_MSL_m": 110.0,
                "TimeFromStart_s": 10.0,
                "EstimatedSpeed_ms": 0.0,
                "Heading_deg": 90.0,
                "HeadingMode": "manual",
            },
        ]
    )

    trajectory = sts.smooth_trajectory_with_waypoints(waypoints, dt=5.0)
    middle = trajectory.iloc[1]

    assert middle["vx"] == pytest.approx(0.0, abs=0.05)
    assert middle["vy"] == pytest.approx(1.0, abs=0.08)
    assert middle["vz"] == pytest.approx(-1.0, abs=0.05)
    assert middle["ax"] == pytest.approx(0.0, abs=0.05)
    assert middle["ay"] == pytest.approx(0.0, abs=0.05)
    assert middle["az"] == pytest.approx(0.0, abs=0.05)

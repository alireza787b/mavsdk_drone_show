from smart_swarm_src.utils import lla_to_ned, transform_body_to_nea


def test_transform_body_to_nea_rotates_right_offset_at_90_deg_yaw():
    north, east = transform_body_to_nea(0.0, 5.0, 90.0)
    assert north == -5.0
    assert round(east, 6) == 0.0


def test_lla_to_ned_preserves_down_positive_convention():
    north, east, down = lla_to_ned(
        lat=47.397742,
        lon=8.545594,
        alt=498.0,
        lat_ref=47.397742,
        lon_ref=8.545594,
        alt_ref=488.0,
    )

    assert abs(north) < 1e-6
    assert abs(east) < 1e-6
    assert down < 0.0
    assert abs(abs(down) - 10.0) < 0.1

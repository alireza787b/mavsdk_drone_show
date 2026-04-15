import numpy as np

from smart_swarm_src.pd_controller import PDController
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


def test_pd_controller_applies_feedforward_and_velocity_error():
    controller = PDController(kp=0.5, kd=0.25, max_velocity=10.0)
    position_error = np.array([2.0, 0.0, 0.0])
    velocity_error = np.array([1.0, 0.0, 0.0])
    feedforward = np.array([3.0, 0.0, 0.0])

    command = controller.compute(
        position_error,
        dt=0.1,
        velocity_error=velocity_error,
        feedforward_velocity=feedforward,
    )

    assert np.allclose(command, np.array([4.25, 0.0, 0.0]))


def test_pd_controller_limits_acceleration_between_steps():
    controller = PDController(
        kp=1.0,
        kd=0.0,
        max_velocity=20.0,
        max_acceleration=1.0,
    )

    first = controller.compute(
        np.array([0.0, 0.0, 0.0]),
        dt=1.0,
        feedforward_velocity=np.array([0.0, 0.0, 0.0]),
    )
    second = controller.compute(
        np.array([10.0, 0.0, 0.0]),
        dt=1.0,
        feedforward_velocity=np.array([0.0, 0.0, 0.0]),
    )

    assert np.allclose(first, np.zeros(3))
    assert np.allclose(second, np.array([1.0, 0.0, 0.0]))


def test_pd_controller_reset_clears_history():
    controller = PDController(kp=1.0, kd=1.0, max_velocity=5.0)
    controller.compute(np.array([1.0, 0.0, 0.0]), dt=0.5)
    controller.reset()

    command = controller.compute(np.array([1.0, 0.0, 0.0]), dt=0.5)
    assert np.allclose(command, np.array([1.0, 0.0, 0.0]))

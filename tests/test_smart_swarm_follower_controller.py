import numpy as np
import pytest

from smart_swarm_src.follower_controller import FollowerMotionController
from smart_swarm_src.formation_guard import FormationGuard
from smart_swarm_src.velocity_command_shaper import NedVelocityCommandShaper


DT = 1.0 / 15.0


def _controller() -> FollowerMotionController:
    return FollowerMotionController(
        position_gain=0.5,
        velocity_gain=0.35,
        leader_velocity_feedforward=1.0,
        max_yaw_rate_deg_s=30.0,
        max_dt_s=0.1,
        seed_yaw_deg=10.0,
        formation_guard=FormationGuard(
            capture_horizontal_m=2.0,
            capture_vertical_m=1.5,
            capture_stable_sec=1.0,
            tracking_horizontal_m=6.0,
            tracking_vertical_m=3.0,
            target_step_horizontal_m=2.0,
            target_step_vertical_m=1.5,
        ),
        velocity_shaper=NedVelocityCommandShaper(
            max_horizontal_speed_m_s=2.0,
            max_vertical_speed_m_s=0.75,
            max_acceleration_m_s2=1.0,
            max_jerk_m_s3=2.0,
            max_dt_s=0.1,
        ),
    )


def _step(controller, *, desired=(6, 0, -10), own=(6, 0, -10), leader_velocity=(0, 0, 0), own_velocity=(0, 0, 0), confidence=1.0, now=10.0, yaw=10.0):
    return controller.compute(
        desired_position_ned=desired,
        own_position_ned=own,
        leader_velocity_ned=leader_velocity,
        own_velocity_ned=own_velocity,
        target_yaw_deg=yaw,
        confidence=confidence,
        dt_s=DT,
        now_s=now,
    )


def _capture(controller) -> None:
    _step(controller, now=10.0)
    decision = _step(controller, now=11.0)
    assert decision.tracking_allowed


@pytest.mark.parametrize("own", [(0, 0, -10), (-6, 0, -10), (6, 0, -6)])
def test_bad_initial_geometry_commands_exact_zero(own) -> None:
    decision = _step(_controller(), own=own)

    assert decision.tracking_allowed is False
    assert np.array_equal(decision.requested_velocity_ned, np.zeros(3))
    assert np.array_equal(decision.velocity_ned, np.zeros(3))


def test_first_motion_after_capture_is_jerk_limited() -> None:
    controller = _controller()
    _capture(controller)

    decision = _step(
        controller,
        desired=(7.0, 0.0, -10.0),
        own=(6.0, 0.0, -10.0),
        now=11.0 + DT,
    )

    assert 0 < decision.velocity_ned[0] < 0.01
    assert np.linalg.norm(controller.velocity_ned) <= 2.0


def test_stale_confidence_scales_feedforward_and_feedback_together() -> None:
    controller = _controller()
    _capture(controller)

    full = _step(
        controller,
        leader_velocity=(1.0, 0.0, 0.0),
        confidence=1.0,
        now=11.0 + DT,
    )
    zero = _step(
        controller,
        leader_velocity=(1.0, 0.0, 0.0),
        confidence=0.0,
        now=11.0 + 2 * DT,
    )

    assert full.requested_velocity_ned[0] > 0
    assert np.array_equal(zero.requested_velocity_ned, np.zeros(3))
    assert zero.velocity_ned[0] >= 0
    assert zero.velocity_ned[0] <= full.velocity_ned[0] + 0.01


def test_reconfiguration_suspends_and_brakes_without_command_jump() -> None:
    controller = _controller()
    _capture(controller)
    for index in range(20):
        _step(
            controller,
            desired=(7.0, 0.0, -10.0),
            own=(6.0, 0.0, -10.0),
            now=11.0 + (index + 1) * DT,
        )
    before = controller.velocity_ned

    controller.require_new_capture()
    decision = _step(
        controller,
        desired=(8.0, 0.0, -10.0),
        own=(6.0, 0.0, -10.0),
        now=13.0,
    )

    assert decision.tracking_allowed is False
    assert np.linalg.norm(decision.velocity_ned - before) <= 1.0 * DT + 1e-9


def test_suspension_brakes_and_reacquisition_requires_new_dwell() -> None:
    controller = _controller()
    _capture(controller)
    for index in range(25):
        _step(
            controller,
            leader_velocity=(1.0, 0.0, 0.0),
            now=11.0 + (index + 1) * DT,
        )

    suspended = controller.suspend(dt_s=DT, reason="leader state stale")
    reacquired = _step(controller, now=14.0)

    assert suspended.status == "suspended"
    assert reacquired.status == "settling"
    assert reacquired.tracking_allowed is False


def test_yaw_is_rate_limited_from_measured_seed() -> None:
    controller = _controller()
    _capture(controller)

    decision = _step(controller, yaw=190.0, now=11.0 + DT)

    assert decision.yaw_deg == pytest.approx(8.0)


def test_control_loop_stall_does_not_expand_velocity_or_yaw_step() -> None:
    controller = _controller()
    _capture(controller)
    normal = controller.compute(
        desired_position_ned=(7, 0, -10),
        own_position_ned=(6, 0, -10),
        leader_velocity_ned=(0, 0, 0),
        own_velocity_ned=(0, 0, 0),
        target_yaw_deg=90,
        confidence=1,
        dt_s=0.1,
        now_s=11.1,
    )

    other = _controller()
    _capture(other)
    stalled = other.compute(
        desired_position_ned=(7, 0, -10),
        own_position_ned=(6, 0, -10),
        leader_velocity_ned=(0, 0, 0),
        own_velocity_ned=(0, 0, 0),
        target_yaw_deg=90,
        confidence=1,
        dt_s=5.0,
        now_s=16.0,
    )

    assert stalled.velocity_ned == pytest.approx(normal.velocity_ned)
    assert stalled.yaw_deg == pytest.approx(normal.yaw_deg)

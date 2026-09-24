import numpy as np
import pytest

from smart_swarm_src.follower_controller import FollowerMotionController
from smart_swarm_src.formation_guard import FormationGuard
from smart_swarm_src.velocity_command_shaper import NedVelocityCommandShaper
from smart_swarm_src.utils import transform_body_to_nea


DT = 1.0 / 15.0


def test_five_metre_profile_accelerates_brakes_and_reverses_continuously():
    controller = _controller(max_horizontal_speed=5.0)
    velocity = np.zeros(3)
    acceleration = np.zeros(3)
    peak = 0.0
    for i in range(900):
        target = (1000, 0, -10) if i < 250 else ((6, 0, -10) if i < 550 else (-1000, 0, -10))
        leader_velocity = (5, 0, 0) if i < 250 else ((0, 0, 0) if i < 550 else (-5, 0, 0))
        decision = _step(controller, desired=target, leader_velocity=leader_velocity,
                         own_velocity=velocity, now=10+i*DT)
        new_velocity = decision.velocity_ned
        new_acceleration = (new_velocity - velocity) / DT
        assert np.linalg.norm(new_velocity[:2]) <= 5.0 + 1e-8
        assert abs(new_velocity[2]) <= 0.75 + 1e-8
        assert np.linalg.norm(new_acceleration) <= 1.0 + 1e-8
        assert np.linalg.norm(new_acceleration - acceleration) / DT <= 2.0 + 1e-7
        assert decision.tracking_allowed  # Distance never aborts acquisition.
        if i == 549:
            assert np.linalg.norm(new_velocity) < 0.05
        peak = max(peak, new_velocity[0])
        velocity, acceleration = new_velocity.copy(), new_acceleration
    assert peak > 4.5
    assert velocity[0] < -4.5


def test_five_metre_profile_tracks_field_leader_speed_without_speed_saturation():
    controller = _controller(max_horizontal_speed=5.0)
    velocity = np.zeros(3)
    for i in range(300):
        decision = _step(controller, leader_velocity=(3.71, 0, 0),
                         own_velocity=velocity, now=10+i*DT)
        velocity = decision.velocity_ned
    assert velocity[0] == pytest.approx(3.71, abs=0.02)


def test_five_metre_profile_keeps_noisy_hover_quiet():
    controller = _controller(max_horizontal_speed=5.0)
    for i in range(300):
        noise = 0.08 * np.sin(i * 1.7)
        decision = _step(controller, desired=(6+noise, noise, -10+noise), now=10+i*DT)
        assert np.linalg.norm(decision.velocity_ned) < 1e-8


def test_body_offset_turns_share_translation_envelope_without_command_jumps():
    controller = _controller(max_horizontal_speed=5.0)
    velocity = np.zeros(3)
    acceleration = np.zeros(3)
    own = np.array([6.0, 0.0, -10.0])
    for i in range(600):
        yaw = i * DT * 5.0  # Slow first-test yaw; six-metre body offset.
        north, east = transform_body_to_nea(6.0, 0.0, yaw)
        omega = np.deg2rad(5.0)
        desired = np.array([3.71*i*DT+north, east, -10.0])
        decision = _step(controller, desired=desired, own=own,
                         leader_velocity=(3.71-east*omega, north*omega, 0.0),
                         own_velocity=velocity, yaw=yaw, now=10+i*DT)
        new_velocity = decision.velocity_ned
        new_acceleration = (new_velocity-velocity) / DT
        assert np.linalg.norm(new_velocity[:2]) <= 5.0 + 1e-8
        assert np.linalg.norm(new_acceleration) <= 1.0 + 1e-8
        assert np.linalg.norm(new_acceleration-acceleration)/DT <= 2.0 + 1e-7
        assert decision.tracking_allowed
        own += new_velocity*DT
        velocity, acceleration = new_velocity.copy(), new_acceleration


def _controller(max_horizontal_speed=2.0) -> FollowerMotionController:
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
            max_horizontal_speed_m_s=max_horizontal_speed,
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
def test_distant_initial_geometry_is_smoothly_acquired(own) -> None:
    decision = _step(_controller(), own=own)

    assert decision.tracking_allowed is True
    assert np.linalg.norm(decision.requested_velocity_ned) > 0.0
    assert np.linalg.norm(decision.velocity_ned) > 0.0


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

    assert decision.tracking_allowed is True
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
    assert reacquired.status in {"settling", "acquiring"}
    assert reacquired.tracking_allowed is True


def test_small_position_noise_is_inside_deadband() -> None:
    controller = _controller()
    _capture(controller)
    decision = _step(
        controller,
        desired=(6.08, 0.04, -10.05),
        own=(6.0, 0.0, -10.0),
        now=11.0 + DT,
    )
    assert np.linalg.norm(decision.requested_velocity_ned) < 0.05


def test_large_error_is_bounded_by_smooth_feedback() -> None:
    controller = _controller()
    decision = _step(
        controller,
        desired=(106.0, 0.0, -10.0),
        own=(0.0, 0.0, -10.0),
        now=10.0,
    )
    assert decision.status == "acquiring"
    assert decision.requested_velocity_ned[0] < 3.0
    assert np.linalg.norm(decision.velocity_ned) <= 2.0


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


@pytest.mark.parametrize("initial_distance", [0.0, 0.3, 100.0, 600.0])
def test_noisy_closed_loop_acquires_and_settles_without_hover_oscillation(initial_distance):
    """Lagged velocity plant, not an assertion about arbitrary real aircraft."""
    controller = _controller()
    rng = np.random.default_rng(481)
    position = np.array([-initial_distance, 0.0, 0.0])
    velocity = np.zeros(3)
    positions, velocities = [], []
    for index in range(int((initial_distance / 1.4 + 60.0) / DT)):
        decision = _step(
            controller,
            desired=rng.normal(0.0, 0.025, 3),
            own=position,
            leader_velocity=rng.normal(0.0, 0.01, 3),
            own_velocity=velocity + rng.normal(0.0, 0.01, 3),
            now=index * DT,
        )
        assert decision.tracking_allowed
        velocity += (decision.velocity_ned - velocity) * (DT / 0.25)
        position += velocity * DT
        positions.append(position.copy())
        velocities.append(velocity.copy())
    assert np.linalg.norm(position) < 0.25
    assert np.max(np.ptp(np.array(positions[-300:]), axis=0)) < 0.15
    assert np.max(np.linalg.norm(velocities[-300:], axis=1)) < 0.1


@pytest.mark.parametrize("plant_lag", [0.15, 0.5])
def test_turns_reversals_and_tiny_moves_use_one_continuous_controller(plant_lag):
    controller = _controller()
    rng = np.random.default_rng(912)
    position, velocity, target = np.zeros(3), np.zeros(3), np.zeros(3)
    previous_command, previous_acceleration = np.zeros(3), np.zeros(3)
    # Abrupt leader velocity changes intentionally stress feedforward shaping.
    stages = [(20, (1, 0, 0)), (15, (0, 1, -0.2)),
              (20, (-1, -1, 0.2)), (35, (0, 0, 0)),
              (4, (0.1, 0, 0)), (40, (0, 0, 0))]
    now = 0.0
    for duration, leader_velocity in stages:
        for _ in range(int(duration / DT)):
            now += DT
            target += np.array(leader_velocity) * DT
            decision = _step(controller, desired=target + rng.normal(0, 0.05, 3),
                             own=position, own_velocity=velocity + rng.normal(0, 0.02, 3),
                             leader_velocity=np.array(leader_velocity) + rng.normal(0, 0.02, 3),
                             now=now)
            acceleration = (decision.velocity_ned - previous_command) / DT
            assert np.linalg.norm(acceleration) <= 1.0 + 1e-8
            assert np.linalg.norm(acceleration - previous_acceleration) / DT <= 2.0 + 1e-7
            assert np.linalg.norm(decision.velocity_ned[:2]) <= 2.0 + 1e-9
            assert abs(decision.velocity_ned[2]) <= 0.75 + 1e-9
            previous_command, previous_acceleration = decision.velocity_ned, acceleration
            velocity += (decision.velocity_ned - velocity) * (DT / plant_lag)
            position += velocity * DT
        if leader_velocity == (0, 0, 0):
            assert np.linalg.norm(position - target) < 0.3
            assert np.linalg.norm(velocity) < 0.1

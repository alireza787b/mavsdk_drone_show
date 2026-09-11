from smart_swarm_src.formation_guard import FormationGuard


def _guard() -> FormationGuard:
    return FormationGuard(
        capture_horizontal_m=2.0,
        capture_vertical_m=1.0,
        capture_stable_sec=1.0,
        tracking_horizontal_m=6.0,
        tracking_vertical_m=2.0,
        target_step_horizontal_m=2.0,
        target_step_vertical_m=1.0,
        acquisition_horizontal_m=500.0,
        acquisition_vertical_m=100.0,
    )


def test_correct_staging_must_settle_before_tracking() -> None:
    guard = _guard()

    first = guard.evaluate((6.0, 0.0, -10.0), (6.2, 0.1, -9.9), now_s=10.0)
    settled = guard.evaluate((6.0, 0.0, -10.0), (6.2, 0.1, -9.9), now_s=11.0)

    assert first.status == "settling"
    assert first.tracking_allowed is True
    assert settled.status == "tracking"
    assert settled.tracking_allowed is True


def test_distant_follower_enters_smooth_acquisition() -> None:
    guard = _guard()

    decision = guard.evaluate((6.0, 0.0, -10.0), (-6.0, 0.0, -10.0), now_s=10.0)

    assert decision.status == "acquiring"
    assert decision.tracking_allowed is True
    assert decision.horizontal_error_m == 12.0


def test_large_vertical_error_enters_smooth_acquisition() -> None:
    guard = _guard()

    decision = guard.evaluate((6.0, 0.0, -10.0), (6.0, 0.0, -7.0), now_s=10.0)

    assert decision.status == "acquiring"
    assert decision.tracking_allowed is True
    assert decision.vertical_error_m == 3.0


def test_target_jump_is_shaped_without_resetting_control() -> None:
    guard = _guard()
    guard.evaluate((6.0, 0.0, -10.0), (6.0, 0.0, -10.0), now_s=10.0)
    assert guard.evaluate(
        (6.0, 0.0, -10.0),
        (6.0, 0.0, -10.0),
        now_s=11.0,
    ).tracking_allowed

    jump = guard.evaluate((9.0, 0.0, -10.0), (6.0, 0.0, -10.0), now_s=11.1)
    reacquire = guard.evaluate((6.0, 0.0, -10.0), (6.0, 0.0, -10.0), now_s=11.2)

    assert jump.tracking_allowed is True
    assert jump.status in {"acquiring", "tracking", "settling"}
    assert reacquire.tracking_allowed is True


def test_tracking_divergence_returns_to_acquisition() -> None:
    guard = _guard()
    guard.evaluate((6.0, 0.0, -10.0), (6.0, 0.0, -10.0), now_s=10.0)
    guard.evaluate((6.0, 0.0, -10.0), (6.0, 0.0, -10.0), now_s=11.0)

    decision = guard.evaluate((6.2, 0.0, -10.0), (-1.0, 0.0, -10.0), now_s=11.1)

    assert decision.status == "acquiring"
    assert decision.tracking_allowed is True


def test_legacy_distance_limit_does_not_reject_finite_geometry() -> None:
    guard = FormationGuard(
        capture_horizontal_m=2.0,
        capture_vertical_m=1.0,
        capture_stable_sec=1.0,
        tracking_horizontal_m=6.0,
        tracking_vertical_m=2.0,
        target_step_horizontal_m=2.0,
        target_step_vertical_m=1.0,
        acquisition_horizontal_m=20.0,
        acquisition_vertical_m=10.0,
    )
    decision = guard.evaluate((30000.0, 0.0, 2000.0), (0.0, 0.0, 0.0), now_s=1.0)
    assert decision.status == "acquiring"
    assert decision.tracking_allowed is True


def test_non_finite_target_fails_closed() -> None:
    decision = _guard().evaluate((float("nan"), 0.0, 0.0), (0.0, 0.0, 0.0), now_s=1.0)

    assert decision.status == "invalid"
    assert decision.tracking_allowed is False

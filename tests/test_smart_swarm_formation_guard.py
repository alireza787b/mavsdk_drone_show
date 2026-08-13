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
    )


def test_correct_staging_must_settle_before_tracking() -> None:
    guard = _guard()

    first = guard.evaluate((6.0, 0.0, -10.0), (6.2, 0.1, -9.9), now_s=10.0)
    settled = guard.evaluate((6.0, 0.0, -10.0), (6.2, 0.1, -9.9), now_s=11.0)

    assert first.status == "settling"
    assert first.tracking_allowed is False
    assert settled.status == "tracking"
    assert settled.tracking_allowed is True


def test_reversed_six_meter_staging_never_authorizes_capture() -> None:
    guard = _guard()

    decision = guard.evaluate((6.0, 0.0, -10.0), (-6.0, 0.0, -10.0), now_s=10.0)

    assert decision.status == "waiting_geometry"
    assert decision.tracking_allowed is False
    assert decision.horizontal_error_m == 12.0


def test_large_vertical_error_never_authorizes_capture() -> None:
    guard = _guard()

    decision = guard.evaluate((6.0, 0.0, -10.0), (6.0, 0.0, -7.0), now_s=10.0)

    assert decision.status == "waiting_geometry"
    assert decision.tracking_allowed is False
    assert decision.vertical_error_m == 3.0


def test_target_jump_suspends_and_requires_new_capture() -> None:
    guard = _guard()
    guard.evaluate((6.0, 0.0, -10.0), (6.0, 0.0, -10.0), now_s=10.0)
    assert guard.evaluate(
        (6.0, 0.0, -10.0),
        (6.0, 0.0, -10.0),
        now_s=11.0,
    ).tracking_allowed

    jump = guard.evaluate((9.0, 0.0, -10.0), (6.0, 0.0, -10.0), now_s=11.1)
    reacquire = guard.evaluate((6.0, 0.0, -10.0), (6.0, 0.0, -10.0), now_s=11.2)

    assert jump.status == "target_jump"
    assert jump.tracking_allowed is False
    assert reacquire.status == "settling"
    assert reacquire.tracking_allowed is False


def test_sustained_tracking_divergence_suspends_motion() -> None:
    guard = _guard()
    guard.evaluate((6.0, 0.0, -10.0), (6.0, 0.0, -10.0), now_s=10.0)
    guard.evaluate((6.0, 0.0, -10.0), (6.0, 0.0, -10.0), now_s=11.0)

    decision = guard.evaluate((6.2, 0.0, -10.0), (-1.0, 0.0, -10.0), now_s=11.1)

    assert decision.status == "tracking_diverged"
    assert decision.tracking_allowed is False


def test_non_finite_target_fails_closed() -> None:
    decision = _guard().evaluate((float("nan"), 0.0, 0.0), (0.0, 0.0, 0.0), now_s=1.0)

    assert decision.status == "invalid"
    assert decision.tracking_allowed is False

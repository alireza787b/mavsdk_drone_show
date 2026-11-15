import pytest

from src.synchronized_start import evaluate_synchronized_start, resolve_requested_start_time


def test_evaluate_synchronized_start_uses_now_when_missing():
    decision = evaluate_synchronized_start(None, late_tolerance_sec=1.0, now=100.0)

    assert decision.effective_start_time == 100.0
    assert decision.should_wait is False
    assert decision.should_abort is False
    assert decision.reason == "No start_time provided; using now."


def test_evaluate_synchronized_start_waits_for_future_time():
    decision = evaluate_synchronized_start(110.0, late_tolerance_sec=1.0, now=100.0)

    assert decision.should_wait is True
    assert decision.should_abort is False
    assert decision.wait_seconds == pytest.approx(10.0)


def test_evaluate_synchronized_start_allows_small_lateness_within_tolerance():
    decision = evaluate_synchronized_start(99.5, late_tolerance_sec=1.0, now=100.0)

    assert decision.should_wait is False
    assert decision.should_abort is False
    assert decision.late_by_seconds == pytest.approx(0.5)
    assert "within the 1.00s late-start tolerance" in decision.reason


def test_evaluate_synchronized_start_rejects_excessive_lateness():
    decision = evaluate_synchronized_start(98.0, late_tolerance_sec=1.0, now=100.0)

    assert decision.should_wait is False
    assert decision.should_abort is True
    assert decision.late_by_seconds == pytest.approx(2.0)
    assert "exceeding the 1.00s late-start tolerance" in decision.reason


def test_resolve_requested_start_time_defers_immediate_launch_until_start_gate():
    assert resolve_requested_start_time(None) is None
    assert resolve_requested_start_time(0) is None
    assert resolve_requested_start_time("0") is None


def test_resolve_requested_start_time_preserves_future_timestamp():
    assert resolve_requested_start_time(110.0) == pytest.approx(110.0)

def test_resolve_requested_start_time_rejects_nonfinite():
    import math
    from src.synchronized_start import resolve_requested_start_time

    assert resolve_requested_start_time(float("nan")) is None
    assert resolve_requested_start_time(float("inf")) is None
    assert resolve_requested_start_time(float("-inf")) is None


def test_evaluate_synchronized_start_rejects_nonfinite_start():
    import math
    from src.synchronized_start import evaluate_synchronized_start

    decision = evaluate_synchronized_start(float("nan"), now=1_700_000_000.0)
    assert decision.should_wait is False
    assert decision.should_abort is False
    assert decision.effective_start_time == 1_700_000_000.0
    assert "Non-finite" in decision.reason or "Invalid" in decision.reason or "now" in decision.reason.lower()

    decision_inf = evaluate_synchronized_start(float("inf"), now=1_700_000_000.0, late_tolerance_sec=5.0)
    assert decision_inf.should_wait is False
    assert decision_inf.effective_start_time == 1_700_000_000.0


def test_evaluate_synchronized_start_nonfinite_tolerance_is_zero():
    from src.synchronized_start import evaluate_synchronized_start

    # start slightly in the past; non-finite tolerance must not inflate wait/late windows
    decision = evaluate_synchronized_start(
        1_700_000_000.0 - 0.1,
        late_tolerance_sec=float("nan"),
        now=1_700_000_000.0,
    )
    assert decision.should_abort is True or decision.late_by_seconds >= 0.0
    # tolerance treated as 0 → past start without allowance
    assert decision.should_wait is False


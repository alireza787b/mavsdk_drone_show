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

import pytest

from smart_swarm_src.leader_recovery import LeaderRecoveryWindow


def window():
    return LeaderRecoveryWindow(started_at=100, wait_sec=10, stable_sec=1)


def test_recovery_needs_continuous_good_evidence():
    w = window()
    assert w.observe(now=102, ready=True) == 'waiting'
    assert w.observe(now=102.9, ready=False) == 'waiting'
    assert w.observe(now=103, ready=True) == 'waiting'
    assert w.observe(now=103.9, ready=True) == 'waiting'
    assert w.observe(now=104.01, ready=True) == 'recovered'


def test_late_packets_do_not_restart_expired_window():
    w = window()
    assert w.observe(now=110, ready=True) == 'expired'
    assert w.observe(now=112, ready=True) == 'expired'


def test_takeover_wins_over_simultaneous_recovery():
    w = window()
    w.observe(now=101, ready=True)
    assert w.observe(now=102.1, ready=True, cancelled=True) == 'cancelled'
    assert w.observe(now=103, ready=True) == 'cancelled'


@pytest.mark.parametrize('wait,stable', [(0, 1), (1, 1), (10, 0), (float('nan'), 1), (10, float('inf'))])
def test_invalid_timing_is_rejected(wait, stable):
    with pytest.raises(ValueError):
        LeaderRecoveryWindow(started_at=100, wait_sec=wait, stable_sec=stable)

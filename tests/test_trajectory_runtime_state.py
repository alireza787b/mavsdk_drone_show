import pytest
from src import trajectory_runtime_state as runtime


def test_progress_is_bounded_fresh_and_command_scoped(tmp_path, monkeypatch):
    path = tmp_path / 'progress.json'
    clock = [10.0]
    monkeypatch.setattr(runtime, 'state_path', lambda: path)
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: clock[0])
    recorder = runtime.TrajectoryProgressRecorder('cmd-1', 'a' * 64)
    recorder.report('trajectory', trajectory_time_s=2, duration_s=10, sample_index=20, sample_count=100)
    first = path.read_text()
    recorder.report('trajectory', trajectory_time_s=3, duration_s=10)
    assert path.read_text() == first
    assert runtime.read_trajectory_runtime('cmd-1')['fresh'] is True
    assert runtime.read_trajectory_runtime('cmd-2') is None
    clock[0] = 14
    assert runtime.read_trajectory_runtime('cmd-1')['fresh'] is False
    recorder.report('finishing', trajectory_time_s=10, duration_s=10)
    assert runtime.read_trajectory_runtime('cmd-1')['phase'] == 'finishing'
    assert runtime.read_trajectory_runtime('cmd-1')['progress_kind'] == 'commanded_trajectory'
    recorder.report('completed')
    assert runtime.read_trajectory_runtime('cmd-1')['trajectory_time_s'] == 10


def test_progress_io_failure_cannot_interrupt_flight(tmp_path, monkeypatch):
    occupied = tmp_path / 'not-a-directory'
    occupied.write_text('occupied')
    monkeypatch.setattr(runtime, 'state_path', lambda: occupied / 'state.json')
    recorder = runtime.TrajectoryProgressRecorder('cmd', 'a' * 64)
    recorder.report('trajectory')
    assert recorder.warned is True


def test_unmanaged_execution_does_not_write_state(tmp_path, monkeypatch):
    path = tmp_path / 'state.json'
    monkeypatch.setattr(runtime, 'state_path', lambda: path)
    runtime.TrajectoryProgressRecorder(None, None).report('starting')
    assert not path.exists()

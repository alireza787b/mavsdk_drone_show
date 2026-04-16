from pathlib import Path


def test_smart_swarm_versions_leader_stream_target_changes():
    content = Path("smart_swarm.py").read_text()

    assert "LEADER_STREAM_TARGET_VERSION = 0" in content
    assert "def current_leader_stream_target()" in content
    assert "def leader_stream_target_changed(" in content
    assert "LEADER_STREAM_TARGET_VERSION += 1" in content
    assert "Leader stream target changed from %s@%s to %s@%s; reconnecting." in content

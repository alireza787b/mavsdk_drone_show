from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_smart_swarm_versions_leader_stream_target_changes():
    content = (REPO_ROOT / "smart_swarm.py").read_text()

    assert "LEADER_STREAM_TARGET_VERSION = 0" in content
    assert "def current_leader_stream_target()" in content
    assert "def leader_stream_target_changed(" in content
    assert "LEADER_STREAM_TARGET_VERSION += 1" in content
    assert "Leader stream target changed from %s@%s to %s@%s; reconnecting." in content

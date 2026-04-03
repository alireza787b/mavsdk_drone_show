"""Tests for mds_logging.session — session lifecycle management."""
import json
import os
import time
import pytest
from mds_logging.session import (
    create_session, get_session_id, get_session_filepath,
    list_sessions, cleanup_sessions, read_session_lines,
)


@pytest.fixture
def tmp_log_dir(tmp_path):
    log_dir = tmp_path / "sessions"
    log_dir.mkdir()
    return str(log_dir)


class TestCreateSession:
    def test_returns_session_id_with_correct_format(self, tmp_log_dir):
        sid = create_session(tmp_log_dir)
        assert sid.startswith("s_")
        assert len(sid) == 17  # s_YYYYMMDD_HHMMSS = 2+8+1+6

    def test_creates_jsonl_file(self, tmp_log_dir):
        sid = create_session(tmp_log_dir)
        filepath = os.path.join(tmp_log_dir, f"{sid}.jsonl")
        assert os.path.exists(filepath)

    def test_duplicate_second_gets_suffix(self, tmp_log_dir):
        sid1 = create_session(tmp_log_dir)
        # Create a file with the same name to force collision
        sid2_expected = sid1 + "_2"
        sid2 = create_session(tmp_log_dir)
        assert sid2 == sid2_expected


class TestListSessions:
    def test_lists_sessions_newest_first(self, tmp_log_dir):
        # Create two session files with different timestamps
        open(os.path.join(tmp_log_dir, "s_20260318_100000.jsonl"), "w").close()
        time.sleep(0.01)
        open(os.path.join(tmp_log_dir, "s_20260319_100000.jsonl"), "w").close()
        sessions = list_sessions(tmp_log_dir)
        assert len(sessions) == 2
        assert sessions[0]["session_id"] == "s_20260319_100000"

    def test_empty_dir_returns_empty_list(self, tmp_log_dir):
        assert list_sessions(tmp_log_dir) == []


class TestCleanupSessions:
    def test_cleanup_by_count(self, tmp_log_dir):
        # Create 12 session files
        for i in range(12):
            fname = f"s_20260301_{i:06d}.jsonl"
            with open(os.path.join(tmp_log_dir, fname), "w") as f:
                f.write('{"test": true}\n')
        cleanup_sessions(tmp_log_dir, max_sessions=10, max_size_mb=1000)
        remaining = os.listdir(tmp_log_dir)
        assert len(remaining) == 10

    def test_cleanup_by_size(self, tmp_log_dir):
        # Create files that exceed size limit
        for i in range(5):
            fname = f"s_20260301_{i:06d}.jsonl"
            with open(os.path.join(tmp_log_dir, fname), "w") as f:
                f.write("x" * (1024 * 1024))  # 1MB each = 5MB total
        # Limit to 3MB — should remove oldest 2
        cleanup_sessions(tmp_log_dir, max_sessions=100, max_size_mb=3)
        remaining = os.listdir(tmp_log_dir)
        assert len(remaining) == 3

    def test_keeps_newest_files(self, tmp_log_dir):
        for i in range(5):
            fname = f"s_20260301_{i:06d}.jsonl"
            with open(os.path.join(tmp_log_dir, fname), "w") as f:
                f.write("data\n")
        cleanup_sessions(tmp_log_dir, max_sessions=3, max_size_mb=1000)
        remaining = sorted(os.listdir(tmp_log_dir))
        assert remaining[0] == "s_20260301_000002.jsonl"  # oldest surviving


class TestReadSessionLines:
    def test_reads_all_lines(self, tmp_log_dir):
        fpath = os.path.join(tmp_log_dir, "s_20260319_100000.jsonl")
        with open(fpath, "w") as f:
            f.write(json.dumps({"level": "INFO", "msg": "one"}) + "\n")
            f.write(json.dumps({"level": "ERROR", "msg": "two"}) + "\n")
        lines = read_session_lines(tmp_log_dir, "s_20260319_100000")
        assert len(lines) == 2
        assert lines[0]["msg"] == "one"

    def test_filter_by_level(self, tmp_log_dir):
        fpath = os.path.join(tmp_log_dir, "s_20260319_100000.jsonl")
        with open(fpath, "w") as f:
            f.write(json.dumps({"level": "DEBUG", "msg": "skip"}) + "\n")
            f.write(json.dumps({"level": "WARNING", "msg": "keep"}) + "\n")
            f.write(json.dumps({"level": "ERROR", "msg": "also_keep"}) + "\n")
        lines = read_session_lines(tmp_log_dir, "s_20260319_100000", level="WARNING")
        assert len(lines) == 2
        assert lines[0]["msg"] == "keep"

    def test_filter_by_component(self, tmp_log_dir):
        fpath = os.path.join(tmp_log_dir, "s_20260319_100000.jsonl")
        with open(fpath, "w") as f:
            f.write(json.dumps({"level": "INFO", "component": "gcs", "msg": "a"}) + "\n")
            f.write(json.dumps({"level": "INFO", "component": "coord", "msg": "b"}) + "\n")
        lines = read_session_lines(tmp_log_dir, "s_20260319_100000", component="coord")
        assert len(lines) == 1
        assert lines[0]["msg"] == "b"

    def test_limit_and_offset(self, tmp_log_dir):
        fpath = os.path.join(tmp_log_dir, "s_20260319_100000.jsonl")
        with open(fpath, "w") as f:
            for i in range(10):
                f.write(json.dumps({"level": "INFO", "msg": f"line_{i}"}) + "\n")
        lines = read_session_lines(tmp_log_dir, "s_20260319_100000", limit=3, offset=2)
        assert len(lines) == 3
        assert lines[0]["msg"] == "line_2"

    def test_missing_session_returns_none(self, tmp_log_dir):
        result = read_session_lines(tmp_log_dir, "s_nonexistent")
        assert result is None

    def test_skips_malformed_lines(self, tmp_log_dir):
        fpath = os.path.join(tmp_log_dir, "s_20260319_100000.jsonl")
        with open(fpath, "w") as f:
            f.write(json.dumps({"level": "INFO", "msg": "good"}) + "\n")
            f.write("not json\n")
            f.write(json.dumps({"level": "INFO", "msg": "also_good"}) + "\n")
        lines = read_session_lines(tmp_log_dir, "s_20260319_100000")
        assert len(lines) == 2

    def test_since_filter(self, tmp_log_dir):
        fpath = os.path.join(tmp_log_dir, "s_20260319_100000.jsonl")
        with open(fpath, "w") as f:
            f.write(json.dumps({"ts": "2026-03-19T10:00:00.000Z", "level": "INFO", "msg": "old"}) + "\n")
            f.write(json.dumps({"ts": "2026-03-19T10:00:01.000Z", "level": "INFO", "msg": "boundary"}) + "\n")
            f.write(json.dumps({"ts": "2026-03-19T10:00:02.000Z", "level": "INFO", "msg": "new"}) + "\n")
        # since is exclusive: entries with ts > since are included
        lines = read_session_lines(tmp_log_dir, "s_20260319_100000", since="2026-03-19T10:00:01.000Z")
        assert len(lines) == 1
        assert lines[0]["msg"] == "new"

    def test_get_session_filepath_rejects_invalid_session_id(self, tmp_log_dir):
        with pytest.raises(ValueError):
            get_session_filepath(tmp_log_dir, "../escape")

    def test_read_session_lines_rejects_path_traversal_session_id(self, tmp_log_dir):
        outside = os.path.join(os.path.dirname(tmp_log_dir), "escape.jsonl")
        with open(outside, "w") as f:
            f.write(json.dumps({"level": "INFO", "msg": "outside"}) + "\n")

        result = read_session_lines(tmp_log_dir, "../escape")
        assert result is None

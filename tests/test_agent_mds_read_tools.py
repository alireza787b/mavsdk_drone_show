from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from agent_runtime import mds_read_tools
from agent_runtime.mds_read_tools import MdsReadOnlyTools, _parse_recent_log_window_seconds


def test_recent_log_window_parser_handles_operator_language():
    assert _parse_recent_log_window_seconds("report warnings last 30 minutes") == 1800
    assert _parse_recent_log_window_seconds("anything in the past hour?") == 3600
    assert _parse_recent_log_window_seconds("latest backend warnings") is None


def test_jsonl_log_parser_uses_timestamp_aliases_and_embedded_clock(tmp_path):
    log_path = tmp_path / "session.jsonl"
    log_path.write_text(
        "\n".join(
            (
                json.dumps({"level": "WARNING", "time": "2026-05-27T07:01:02Z", "message": "warning with time alias"}),
                json.dumps({"level": "WARNING", "message": "03:17:15.633 WARNING [api] API GET /x -> 401"}),
            )
        ),
        encoding="utf-8",
    )

    events = mds_read_tools._warning_events_from_jsonl(log_path, source="test")

    assert events[0]["ts"] == "2026-05-27T07:01:02Z"
    assert events[1]["ts"] == "03:17:15.633"


def test_backend_log_summary_filters_to_requested_time_window(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    log_path = tmp_path / "session.jsonl"
    log_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "level": "WARNING",
                        "ts": (now - timedelta(hours=2)).isoformat(),
                        "message": "old warning outside requested window",
                    }
                ),
                json.dumps(
                    {
                        "level": "WARNING",
                        "ts": (now - timedelta(minutes=10)).isoformat(),
                        "message": "recent warning inside requested window",
                    }
                ),
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mds_read_tools, "_log_file_candidates", lambda: [log_path])

    answer = MdsReadOnlyTools().backend_log_summary(message="can you report warnings from last 30 minutes in gcs?")

    assert "last 30 minutes" in answer.content
    assert "recent warning inside requested window" in answer.content
    assert "old warning outside requested window" not in answer.content
    assert "time unavailable" not in answer.content

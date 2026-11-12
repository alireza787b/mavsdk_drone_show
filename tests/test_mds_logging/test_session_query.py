"""Pages preserve source/query identity without loading whole session files."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

import mds_logging.session as sessions
from mds_logging.session_query import LogQueryError, read_session_page

SID = "s_20261112_120000"


def write(tmp_path, rows):
    path = tmp_path / f"{SID}.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_same_second_and_concurrent_sessions_never_reuse_identity(tmp_path, monkeypatch):
    class Clock:
        @staticmethod
        def now(_tz):
            return datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(sessions, "datetime", Clock)
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: sessions.create_session(str(tmp_path)), range(25)))
    assert len(set(ids)) == 25


def test_pages_pin_append_boundary_and_visit_every_record(tmp_path):
    path = write(tmp_path, [{"msg": str(i), "level": "INFO"} for i in range(1105)])
    page = read_session_page(tmp_path, SID)
    assert len(page["lines"]) == 500 and page["has_more"]
    snapshot = page["snapshot_id"]
    with path.open("a") as handle:
        handle.write(json.dumps({"msg": "newer append", "level": "INFO"}) + "\n")
    result = list(page["lines"])
    offsets = list(page["entry_offsets"])
    while page["next_cursor"]:
        page = read_session_page(tmp_path, SID, cursor=page["next_cursor"])
        assert page["snapshot_id"] == snapshot
        result.extend(page["lines"])
        offsets.extend(page["entry_offsets"])
    assert [row["msg"] for row in result] == [str(i) for i in range(1105)]
    assert len(set(offsets)) == len(result)


@pytest.mark.parametrize("limit", [0, -1, 2001, True, 2.5])
def test_invalid_limits_rejected(tmp_path, limit):
    with pytest.raises(LogQueryError):
        read_session_page(tmp_path, SID, limit=limit)


def test_malformed_shapes_and_trailing_partial_line_do_not_crash(tmp_path):
    path = write(tmp_path, [[], {"level": []}, {"msg": "keep", "level": "WARNING"}])
    with path.open("a") as handle:
        handle.write('{"msg":')
    page = read_session_page(tmp_path, SID, level="WARNING")
    assert [row["msg"] for row in page["lines"]] == ["keep"]
    assert page["coverage"]["malformed_records"] == 2
    assert page["coverage"]["incomplete_records"] == 1


def test_all_filters_apply_before_page_limit_and_times_are_normalized(tmp_path):
    write(tmp_path, [
        {"level": "DEBUG", "msg": "needle", "component": "test", "ts": "2026-11-12T12:00:01Z"},
        {"level": "INFO", "msg": "needle", "component": "test", "ts": "2026-11-12T13:00:02+01:00"},
        {"level": "INFO", "msg": "other", "component": "test", "ts": "2026-11-12T12:00:03Z"},
    ])
    page = read_session_page(tmp_path, SID, level="INFO", component="test", search="NEEDLE",
                             since="2026-11-12T12:00:01Z", until="2026-11-12T12:00:02Z", limit=1)
    assert len(page["lines"]) == 1 and page["lines"][0]["ts"].endswith("+01:00")


def test_cursor_cannot_be_reused_for_another_filter_or_rotated_file(tmp_path):
    path = write(tmp_path, [{"msg": str(i)} for i in range(3)])
    cursor = read_session_page(tmp_path, SID, limit=1)["next_cursor"]
    with pytest.raises(LogQueryError, match="filters changed"):
        read_session_page(tmp_path, SID, limit=1, cursor=cursor, search="new")
    replacement = tmp_path / "replacement"
    replacement.write_text(path.read_text())
    replacement.replace(path)
    with pytest.raises(LogQueryError, match="rotated"):
        read_session_page(tmp_path, SID, limit=1, cursor=cursor)


def test_cursor_rejects_rewrite_and_tampering(tmp_path):
    path = write(tmp_path, [{"msg": "a"}, {"msg": "b"}])
    cursor = read_session_page(tmp_path, SID, limit=1)["next_cursor"]
    path.write_text(path.read_text().replace('"a"', '"z"'))
    with pytest.raises(LogQueryError, match="contents changed"):
        read_session_page(tmp_path, SID, cursor=cursor)
    with pytest.raises(LogQueryError):
        read_session_page(tmp_path, SID, cursor="broken")


def test_response_byte_budget_and_oversized_record_coverage(tmp_path):
    write(tmp_path, [{"msg": "x" * 300000}] + [{"msg": "x" * 120000} for _ in range(30)])
    page = read_session_page(tmp_path, SID)
    assert page["coverage"]["oversized_records"] == 1
    assert 1 <= len(page["lines"]) < 30 and page["has_more"]
    assert len(json.dumps(page["lines"]).encode()) < 2 * 1024 * 1024


def test_invalid_time_range_is_not_a_successful_empty_page(tmp_path):
    with pytest.raises(LogQueryError, match="End time"):
        read_session_page(tmp_path, SID, since="2026-11-12T13:00Z", until="2026-11-12T12:00Z")


def test_non_finite_json_record_is_reported_without_breaking_the_page(tmp_path):
    (tmp_path / "s_nonfinite.jsonl").write_text(
        '{"msg":"invalid","extra":{"value":NaN}}\n'
        '{"msg":"valid","level":"INFO"}\n', encoding="utf-8")
    result = read_session_page(str(tmp_path), "s_nonfinite")
    assert result["lines"] == [{"msg": "valid", "level": "INFO"}]
    assert result["coverage"]["malformed_records"] == 1

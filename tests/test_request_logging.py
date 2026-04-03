from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gcs-server'))

from request_logging import get_request_log_level, is_routine_success_path


def test_routine_success_paths_are_classified_as_debug():
    assert is_routine_success_path("/api/v1/git/status") is True
    assert is_routine_success_path("/get-origin") is True
    assert is_routine_success_path("/drone-heartbeat") is True
    assert is_routine_success_path("/command/123e4567-e89b-12d3-a456-426614174000") is True
    assert is_routine_success_path("/command/execution-result") is True
    assert is_routine_success_path("/api/v1/commands/recent") is True
    assert is_routine_success_path("/api/v1/commands/cmd-123") is True
    assert is_routine_success_path("/api/v1/command-reports/execution-result") is True
    assert is_routine_success_path("/api/logs/stream") is True
    assert is_routine_success_path("/api/logs/drone/1/stream") is True
    assert get_request_log_level("/get-origin", 200) == "DEBUG"
    assert get_request_log_level("/api/v1/git/status", 200) == "DEBUG"
    assert get_request_log_level("/command/123e4567-e89b-12d3-a456-426614174000", 200) == "DEBUG"
    assert get_request_log_level("/command/execution-result", 200) == "DEBUG"
    assert get_request_log_level("/api/v1/commands/cmd-123", 200) == "DEBUG"
    assert get_request_log_level("/api/v1/command-reports/execution-result", 200) == "DEBUG"
    assert get_request_log_level("/api/logs/drone/1/stream", 200) == "DEBUG"


def test_non_routine_success_paths_remain_info():
    assert is_routine_success_path("/submit_command") is False
    assert is_routine_success_path("/api/v1/commands/cmd-123/cancel") is False
    assert is_routine_success_path("/api/v1/commands/statistics") is False
    assert get_request_log_level("/submit_command", 200) == "INFO"


def test_failures_override_routine_classification():
    assert get_request_log_level("/get-origin", 404) == "WARNING"
    assert get_request_log_level("/drone-heartbeat", 500) == "ERROR"

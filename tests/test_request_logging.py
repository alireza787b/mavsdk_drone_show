from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gcs-server'))

from request_logging import get_request_log_level, is_routine_auth_noise_path, is_routine_success_path


def test_routine_success_paths_are_classified_as_debug():
    assert is_routine_success_path("/api/v1/git/status") is True
    assert is_routine_success_path("/api/v1/origin") is True
    assert is_routine_success_path("/api/v1/fleet/heartbeats") is True
    assert is_routine_success_path("/api/v1/commands/recent") is True
    assert is_routine_success_path("/api/v1/system/runtime-status") is True
    assert is_routine_success_path("/api/v1/simurgh/status") is True
    assert is_routine_success_path("/api/v1/commands/cmd-123") is True
    assert is_routine_success_path("/api/v1/command-reports/execution-result") is True
    assert is_routine_success_path("/api/logs/stream") is True
    assert is_routine_success_path("/api/logs/drone/1/stream") is True
    assert get_request_log_level("/api/v1/origin", 200) == "DEBUG"
    assert get_request_log_level("/api/v1/git/status", 200) == "DEBUG"
    assert get_request_log_level("/api/v1/system/runtime-status", 200) == "DEBUG"
    assert get_request_log_level("/api/v1/simurgh/status", 200) == "DEBUG"
    assert get_request_log_level("/api/v1/commands/cmd-123", 200) == "DEBUG"
    assert get_request_log_level("/api/v1/command-reports/execution-result", 200) == "DEBUG"
    assert get_request_log_level("/api/logs/drone/1/stream", 200) == "DEBUG"


def test_non_routine_success_paths_remain_info():
    assert is_routine_success_path("/api/v1/commands") is False
    assert is_routine_success_path("/api/v1/commands/statistics") is False
    assert get_request_log_level("/api/v1/commands", 200) == "INFO"


def test_routine_dashboard_auth_noise_is_debug_without_weakening_auth():
    assert is_routine_auth_noise_path("/api/v1/git/status", method="GET") is True
    assert is_routine_auth_noise_path("/api/v1/commands/active", method="HEAD") is True
    assert is_routine_auth_noise_path("/api/health", method="GET") is True
    assert is_routine_auth_noise_path("/", method="GET") is True
    assert is_routine_auth_noise_path("/api/v1/system/runtime-status", method="GET") is True
    assert get_request_log_level("/api/v1/git/status", 401, method="GET") == "DEBUG"
    assert get_request_log_level("/api/v1/commands/active", 403, method="GET") == "DEBUG"
    assert get_request_log_level("/api/health", 401, method="GET") == "DEBUG"
    assert get_request_log_level("/", 401, method="GET") == "DEBUG"
    assert get_request_log_level("/api/v1/system/runtime-status", 401, method="GET") == "DEBUG"
    assert get_request_log_level("/api/v1/simurgh/status", 401, method="GET") == "DEBUG"


def test_mutating_or_non_routine_auth_failures_remain_warning():
    assert is_routine_auth_noise_path("/api/v1/simurgh/assistant/turns", method="POST") is False
    assert get_request_log_level("/api/v1/simurgh/assistant/turns", 401, method="POST") == "WARNING"
    assert get_request_log_level("/api/v1/system/env/gcs", 401, method="GET") == "WARNING"
    assert get_request_log_level("/api/v1/commands", 403, method="POST") == "WARNING"


def test_failures_override_routine_classification_except_auth_noise():
    assert get_request_log_level("/api/v1/origin", 404, method="GET") == "WARNING"
    assert get_request_log_level("/api/v1/fleet/heartbeats", 500) == "ERROR"

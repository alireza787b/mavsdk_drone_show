from __future__ import annotations

import json
import subprocess
import sys

from agent_runtime.dashboard_prompt_evals import (
    DashboardPromptEvalSuite,
    run_dashboard_prompt_eval_suite,
)


def test_dashboard_prompt_eval_suite_passes_runtime_router_scenarios():
    suite = DashboardPromptEvalSuite.from_file()

    report = run_dashboard_prompt_eval_suite(suite)

    assert report.passed, report.to_text()
    assert report.passed_count >= 16
    seen = {(result.conversation_id, result.turn_index) for result in report.results}
    assert ("logs_status_then_interpretation", 2) in seen
    assert ("public_geography_and_distance", 2) in seen
    assert ("general_questions_do_not_inherit_fleet", 3) in seen


def test_dashboard_prompt_eval_cli_json_report_is_machine_readable():
    completed = subprocess.run(
        [sys.executable, "tools/run_simurgh_dashboard_prompt_evals.py", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert payload["passed"] is True
    assert payload["failed_count"] == 0
    assert payload["passed_count"] >= 16

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tests" / "helpers" / "action_signal_harness.py"


@pytest.mark.parametrize(
    ("action_name", "signal_number"),
    [("takeoff", signal.SIGTERM), ("test", signal.SIGINT)],
)
def test_real_process_signal_reaches_bounded_action_cleanup(
    tmp_path,
    action_name,
    signal_number,
):
    marker_dir = tmp_path / action_name
    process = subprocess.Popen(
        [sys.executable, str(HARNESS), action_name, str(marker_dir)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    deadline = time.monotonic() + 5.0
    while not (marker_dir / "started").exists() and time.monotonic() < deadline:
        if process.poll() is not None:
            break
        time.sleep(0.01)

    assert (marker_dir / "started").exists(), process.communicate(timeout=1)
    process.send_signal(signal_number)
    stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 1, (stdout, stderr)
    assert (marker_dir / "cleanup").read_text(encoding="utf-8") == action_name
    result = json.loads((marker_dir / "result.json").read_text(encoding="utf-8"))
    assert result["success"] is False
    assert result["code"] == "ACTION_INTERRUPTED"
    assert result["evidence"]["signal"] == signal.Signals(signal_number).name
    assert result["evidence"]["cleanup"]["cleanup_confirmed"] is True
    assert result["final_vehicle_state"]["recovery_status"] == "safe_disarmed_confirmed"

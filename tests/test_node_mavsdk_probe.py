"""MAVSDK installer probes must not start a vehicle connection or hang."""

import hashlib
import subprocess
from pathlib import Path

import pytest


LIBS = Path(__file__).resolve().parents[1] / "tools/mds_init_lib"


def run_probe(tmp_path, executable, check, *, version="", recorded_hash=""):
    binary = tmp_path / "mavsdk_server"
    binary.write_text("#!/bin/bash\n" + executable)
    binary.chmod(0o755)
    return subprocess.run(
        ["bash", "-c", f"""
set -euo pipefail
MDS_INSTALL_DIR='{tmp_path}'
source '{LIBS / "mavsdk.sh"}'
source '{LIBS / "verify.sh"}'
log_step() {{ :; }}
log_success() {{ :; }}
log_error() {{ :; }}
state_get_value() {{
    case "$1" in
        mavsdk_version) printf '%s' '{version}';;
        mavsdk_sha256) printf '%s' '{recorded_hash}';;
    esac
}}
{check}
"""],
        capture_output=True, text=True, timeout=10, check=False,
    )


def test_help_probe_does_not_invoke_unsupported_version_or_open_transport(tmp_path):
    result = run_probe(tmp_path,
        '[[ "$#" == 1 && "$1" == --help ]] || exit 99\nexit 0\n',
        'verify_mavsdk_binary\nverify_mavsdk\n[[ "$(verify_get_result mavsdk)" == "PASS:CLI verified; version unrecorded" ]]')
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("body", ['echo "loader error"; exit 1\n', 'sleep 20\n'])
def test_failure_or_hanging_probe_is_not_a_success(tmp_path, body):
    result = run_probe(tmp_path, body,
        'if verify_mavsdk; then exit 99; fi\n[[ "$(verify_get_result mavsdk)" == "FAIL:Executable CLI check failed" ]]')
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("matches", [False, True])
def test_installed_version_is_reported_only_for_matching_binary_hash(tmp_path, matches):
    body = 'exit 99\n'  # A version lookup must not execute the binary at all.
    digest = hashlib.sha256(("#!/bin/bash\n" + body).encode()).hexdigest()
    expected = "v3.15.0" if matches else ""
    result = run_probe(tmp_path, body,
        f'[[ "$(get_installed_version)" == "{expected}" ]]',
        version="v3.15.0", recorded_hash=digest if matches else "wrong-hash")
    assert result.returncode == 0, result.stderr

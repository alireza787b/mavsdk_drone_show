"""Runtime ownership and transport intent survive companion setup phases."""

import subprocess
from pathlib import Path

import pytest


LIBS = Path(__file__).resolve().parents[1] / "tools/mds_init_lib"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o600])
def test_remove_env_key_preserves_access_metadata_and_unrelated_values(tmp_path, mode):
    env = tmp_path / "local.env"
    env.write_text("MDS_MODE=real\nREMOVE_ME=old\nMDS_GCS_IP=192.0.2.10\n")
    env.chmod(mode)
    previous = env.stat()
    result = subprocess.run(["bash", "-c", f"""
set -euo pipefail
source '{LIBS / "identity.sh"}'
MDS_LOCAL_ENV='{env}'
remove_local_env_value REMOVE_ME
remove_local_env_value ABSENT_KEY
"""], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert env.read_text() == "MDS_MODE=real\nMDS_GCS_IP=192.0.2.10\n"
    assert env.stat().st_mode & 0o777 == mode
    assert (env.stat().st_uid, env.stat().st_gid) == (previous.st_uid, previous.st_gid)


@pytest.mark.parametrize("input_type", ["uart", "udp"])
def test_mavlink_auto_preserves_explicit_transport_and_endpoints(tmp_path, input_type):
    args = tmp_path / "configure-args"
    result = subprocess.run(["bash", "-c", f"""
set -euo pipefail
source '{LIBS / "mavlink_setup.sh"}'
log_step() {{ :; }}
log_info() {{ :; }}
log_success() {{ :; }}
is_raspberry_pi() {{ return 1; }}
clone_mavlink_anywhere() {{ :; }}
check_mavlink_router_installed() {{ return 0; }}
verify_mavlink_service() {{ :; }}
detect_uart_device() {{ echo unexpected-detection >&2; return 99; }}
run_mavlink_configure_headless() {{ printf '%s\\n' "$@" > '{args}'; }}
MAVLINK_UART=/dev/ttyTEST
MAVLINK_BAUD=921600
MAVLINK_ENDPOINTS=127.0.0.1:14540,127.0.0.1:12550
MAVLINK_INPUT_TYPE={input_type}
MAVLINK_INPUT_PORT=14600
run_mavlink_auto_config
"""], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert args.read_text().splitlines() == [
        "/dev/ttyTEST" if input_type == "uart" else "", "921600",
        "127.0.0.1:14540,127.0.0.1:12550", input_type, "14600",
    ]

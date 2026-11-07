"""Real-mode identity rendering must use the file-only credential contract."""

import subprocess
from pathlib import Path

import pytest


IDENTITY_LIB = Path(__file__).resolve().parents[1] / "tools/mds_init_lib/identity.sh"


@pytest.mark.parametrize("configured", [False, True])
def test_local_env_renders_under_strict_shell_without_inline_token(tmp_path, configured):
    token = tmp_path / "machine-token"
    token.write_text("test-only-credential\n")
    token.chmod(0o600)
    output = tmp_path / "local.env"
    result = subprocess.run(
        ["bash", "-c", f"""
set -euo pipefail
unset gcs_api_token
source '{IDENTITY_LIB}'
log_step() {{ :; }}
log_success() {{ :; }}
log_warn() {{ :; }}
is_dry_run() {{ return 1; }}
MDS_VERSION=test
MDS_CONFIG_DIR='{tmp_path}'
MDS_LOCAL_ENV='{output}'
GCS_API_TOKEN_FILE='{"" if not configured else token}'
setup_local_env 9 192.0.2.10 https://github.com/example/aircraft.git main http://192.0.2.10:5030
"""],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    rendered = output.read_text()
    assert "MDS_HW_ID=9\n" in rendered
    if configured:
        assert f"MDS_GCS_API_TOKEN_FILE={token}\n" in rendered
    else:
        assert "MDS_GCS_API_TOKEN_FILE=" not in rendered
    assert "test-only-credential" not in rendered + result.stdout + result.stderr
    assert token.read_text() == "test-only-credential\n"
    assert token.stat().st_mode & 0o777 == 0o600

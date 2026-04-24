import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NODE_INSTALLER = REPO_ROOT / "tools" / "install_mds_node.sh"
GCS_INSTALLER = REPO_ROOT / "tools" / "install_gcs.sh"
COMMON_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "common.sh"
NETWORK_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "network.sh"
REPO_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "repo.sh"
GCS_COMMON_LIB = REPO_ROOT / "tools" / "mds_gcs_init_lib" / "gcs_common.sh"
GCS_REPO_LIB = REPO_ROOT / "tools" / "mds_gcs_init_lib" / "gcs_repo.sh"
MAVLINK_SETUP_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "mavlink_setup.sh"
MAVSDK_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "mavsdk.sh"
SERVICES_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "services.sh"
PYTHON_ENV_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "python_env.sh"
GIT_SYNC_SCRIPT = REPO_ROOT / "tools" / "update_repo_ssh.sh"
RECONCILE_CONNECTIVITY_SCRIPT = REPO_ROOT / "tools" / "reconcile_connectivity.sh"
RECONCILE_MAVLINK_SCRIPT = REPO_ROOT / "tools" / "reconcile_mavlink_runtime.sh"


def run_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_node_bootstrap_wrapper_can_be_sourced_and_resolves_repo_urls():
    result = run_bash(
        f"""
        source "{NODE_INSTALLER}"
        [[ "$(resolve_target_repo_url '' 'demo/customer-mds' false)" == "git@github.com:demo/customer-mds.git" ]]
        [[ "$(resolve_target_repo_url '' 'demo/customer-mds' true)" == "https://github.com/demo/customer-mds.git" ]]
        [[ "$(resolve_target_repo_url 'git@github.com:demo/explicit.git' '' false)" == "git@github.com:demo/explicit.git" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_bootstrap_wrapper_can_be_sourced_and_resolves_repo_urls():
    result = run_bash(
        f"""
        source "{GCS_INSTALLER}"
        [[ "$(resolve_target_repo_url '' 'demo/customer-mds' false)" == "git@github.com:demo/customer-mds.git" ]]
        [[ "$(resolve_target_repo_url '' 'demo/customer-mds' true)" == "https://github.com/demo/customer-mds.git" ]]
        [[ "$(resolve_target_repo_url 'git@github.com:demo/explicit.git' '' false)" == "git@github.com:demo/explicit.git" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_node_bootstrap_wrapper_uses_local_deployment_profile_defaults_when_available():
    result = run_bash(
        f"""
        profile_file="$(mktemp)"
        cat >"$profile_file" <<'EOF'
MDS_DEFAULT_REPO_SLUG=demo/customer-mds
MDS_DEFAULT_REPO_URL_HTTPS=https://github.com/demo/customer-mds.git
MDS_DEFAULT_REPO_URL_SSH=git@github.com:demo/customer-mds.git
MDS_DEFAULT_BRANCH=release-candidate
EOF
        export MDS_DEPLOYMENT_PROFILE_FILE="$profile_file"
        source "{NODE_INSTALLER}"
        [[ "$REPO_URL" == "https://github.com/demo/customer-mds.git" ]]
        [[ "$BRANCH" == "release-candidate" ]]
        [[ "$INSTALL_DIR" == "/home/droneshow/customer-mds" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_bootstrap_wrapper_uses_local_deployment_profile_defaults_when_available():
    result = run_bash(
        f"""
        profile_file="$(mktemp)"
        cat >"$profile_file" <<'EOF'
MDS_DEFAULT_REPO_SLUG=demo/customer-mds
MDS_DEFAULT_REPO_URL_HTTPS=https://github.com/demo/customer-mds.git
MDS_DEFAULT_REPO_URL_SSH=git@github.com:demo/customer-mds.git
MDS_DEFAULT_BRANCH=release-candidate
EOF
        export MDS_DEPLOYMENT_PROFILE_FILE="$profile_file"
        source "{GCS_INSTALLER}"
        [[ "$REPO_URL" == "https://github.com/demo/customer-mds.git" ]]
        [[ "$BRANCH" == "release-candidate" ]]
        [[ "$INSTALL_DIR" == "$HOME/customer-mds" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_node_bootstrap_wrapper_respects_runtime_user_and_install_dir_env_overrides():
    result = run_bash(
        f"""
        profile_file="$(mktemp)"
        cat >"$profile_file" <<'EOF'
MDS_DEFAULT_REPO_SLUG=demo/customer-mds
MDS_DEFAULT_REPO_URL_HTTPS=https://github.com/demo/customer-mds.git
MDS_DEFAULT_REPO_URL_SSH=git@github.com:demo/customer-mds.git
MDS_DEFAULT_BRANCH=release-candidate
EOF
        export MDS_DEPLOYMENT_PROFILE_FILE="$profile_file"
        export MDS_USER="companion"
        export MDS_INSTALL_DIR="/srv/customer-stack"
        source "{NODE_INSTALLER}"
        [[ "$INSTALL_DIR" == "/srv/customer-stack" ]]
        grep -q "MDS_USER            Runtime user created for the companion node (default: companion)" <(show_help)
        grep -q "MDS_INSTALL_DIR     Installation directory for the repo checkout (default: /srv/customer-stack)" <(show_help)
        """
    )

    assert result.returncode == 0, result.stderr


def test_node_bootstrap_wrapper_supports_piped_help_execution():
    result = run_bash(
        f"""
        cat "{NODE_INSTALLER}" | bash -s -- --help >/tmp/node_wrapper_help.txt
        grep -q "Companion Node Bootstrap Installer" /tmp/node_wrapper_help.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_bootstrap_wrapper_supports_piped_help_execution():
    result = run_bash(
        f"""
        cat "{GCS_INSTALLER}" | bash -s -- --help >/tmp/gcs_wrapper_help.txt
        grep -q "MDS GCS Bootstrap Installer" /tmp/gcs_wrapper_help.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_bootstrap_wrapper_help_mentions_private_https_token_file():
    result = run_bash(
        f"""
        cat "{GCS_INSTALLER}" | bash -s -- --help >/tmp/gcs_wrapper_help.txt
        grep -q -- "--git-auth-token-file" /tmp/gcs_wrapper_help.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_bootstrap_wrapper_help_mentions_private_ssh_key_file():
    result = run_bash(
        f"""
        cat "{GCS_INSTALLER}" | bash -s -- --help >/tmp/gcs_wrapper_help.txt
        grep -q -- "--git-ssh-key-file" /tmp/gcs_wrapper_help.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_node_bootstrap_wrapper_help_mentions_private_https_token_file():
    result = run_bash(
        f"""
        cat "{NODE_INSTALLER}" | bash -s -- --help >/tmp/node_wrapper_help.txt
        grep -q -- "--git-auth-token-file" /tmp/node_wrapper_help.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_node_bootstrap_wrapper_help_mentions_private_ssh_key_file():
    result = run_bash(
        f"""
        cat "{NODE_INSTALLER}" | bash -s -- --help >/tmp/node_wrapper_help.txt
        grep -q -- "--git-ssh-key-file" /tmp/node_wrapper_help.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_identity_setup_local_env_persists_node_git_auth_file_paths():
    identity_lib = REPO_ROOT / "tools" / "mds_init_lib" / "identity.sh"

    result = run_bash(
        f"""
        source "{identity_lib}"
        log_step() {{ :; }}
        log_success() {{ :; }}
        log_info() {{ :; }}
        is_dry_run() {{ return 1; }}
        get_repo_origin_url() {{ printf '%s\\n' 'https://github.com/demo/private.git'; }}
        get_repo_branch() {{ printf '%s\\n' 'main-candidate'; }}
        MDS_VERSION="test"
        MDS_CONNECTIVITY_BACKEND="none"
        MDS_DEFAULT_CONNECTIVITY_BACKEND="none"
        MDS_CONFIG_DIR="$(mktemp -d)"
        MDS_LOCAL_ENV="$MDS_CONFIG_DIR/local.env"
        GIT_AUTH_TOKEN_FILE="/home/droneshow/.mds_git_read_token"
        GIT_SSH_KEY_FILE="/home/droneshow/.ssh/customer_read_key"
        setup_local_env 2 "100.82.207.49" "https://github.com/Catch-A-Drone/mavsdk_drone_show.git" "main-candidate" "http://100.82.207.49:5000"
        grep -q '^MDS_GIT_AUTH_TOKEN_FILE=/home/droneshow/.mds_git_read_token$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_GIT_SSH_KEY_FILE=/home/droneshow/.ssh/customer_read_key$' "$MDS_LOCAL_ENV"
        """
    )

    assert result.returncode == 0, result.stderr


def test_node_bootstrap_help_mentions_connectivity_backend_options():
    result = run_bash(
        f"""
        cat "{NODE_INSTALLER}" | bash -s -- --help >/tmp/node_wrapper_help.txt
        grep -q -- "--connectivity-backend" /tmp/node_wrapper_help.txt
        grep -q -- "--smart-wifi-mode" /tmp/node_wrapper_help.txt
        grep -q -- "--smart-wifi-config" /tmp/node_wrapper_help.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_wrapper_private_https_auth_uses_askpass_token_file():
    result = run_bash(
        f"""
        source "{GCS_INSTALLER}"
        fakebin="$(mktemp -d)"
        token_file="$(mktemp)"
        printf 'demo-token' > "$token_file"
        cat >"$fakebin/git" <<'EOF'
#!/bin/sh
printf '%s|%s|%s\\n' "$GIT_ASKPASS" "$GIT_TERMINAL_PROMPT" "$MDS_GIT_AUTH_TOKEN_FILE"
EOF
        chmod +x "$fakebin/git"
        PATH="$fakebin:$PATH"
        GIT_AUTH_TOKEN_FILE="$token_file"
        run_git_as_root "https://github.com/demo/private.git" status >/tmp/gcs_wrapper_auth.txt
        grep -Eq '.*/\\.cache/mds-runtime/mds_gcs_git_askpass\\.sh\\|0\\|' /tmp/gcs_wrapper_auth.txt
        grep -q "$token_file" /tmp/gcs_wrapper_auth.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_wrapper_private_ssh_auth_uses_configured_key_file():
    result = run_bash(
        f"""
        source "{GCS_INSTALLER}"
        fakebin="$(mktemp -d)"
        GIT_SSH_KEY_FILE="/tmp/customer_gcs_key"
        set_wrapper_ssh_key_path
        cat >"$fakebin/git" <<'EOF'
#!/bin/sh
printf '%s\n' "$GIT_SSH_COMMAND"
EOF
        chmod +x "$fakebin/git"
        PATH="$fakebin:$PATH"
        run_git_as_root "git@github.com:demo/private.git" status >/tmp/gcs_wrapper_ssh.txt
        grep -q '/tmp/customer_gcs_key' /tmp/gcs_wrapper_ssh.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_repo_phase_prefers_https_for_noninteractive_private_https_repo_with_token_file():
    result = run_bash(
        f"""
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_common.sh'}"
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_repo.sh'}"
        token_file="$(mktemp)"
        printf 'demo-token' > "$token_file"
        REPO_URL="https://github.com/demo/private.git"
        USE_HTTPS="false"
        MDS_GIT_AUTH_TOKEN_FILE="$token_file"
        gcs_should_use_https_access "$REPO_URL"
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_repo_phase_keeps_ssh_for_noninteractive_explicit_ssh_repo():
    result = run_bash(
        f"""
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_common.sh'}"
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_repo.sh'}"
        token_file="$(mktemp)"
        printf 'demo-token' > "$token_file"
        REPO_URL="git@github.com:demo/private.git"
        USE_HTTPS="false"
        MDS_GIT_AUTH_TOKEN_FILE="$token_file"
        ! gcs_should_use_https_access "$REPO_URL"
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_repo_phase_uses_configured_ssh_key_file_for_runtime_git_commands():
    result = run_bash(
        f"""
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_common.sh'}"
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_repo.sh'}"
        fakebin="$(mktemp -d)"
        MDS_GIT_SSH_KEY_FILE="/tmp/customer_gcs_runtime_key"
        cat >"$fakebin/git" <<'EOF'
#!/bin/sh
printf '%s\n' "$GIT_SSH_COMMAND"
EOF
        chmod +x "$fakebin/git"
        PATH="$fakebin:$PATH"
        run_gcs_git_command "git@github.com:demo/private.git" status >/tmp/gcs_repo_runtime_ssh.txt
        grep -q '/tmp/customer_gcs_runtime_key' /tmp/gcs_repo_runtime_ssh.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_node_wrapper_private_https_auth_uses_askpass_token_file():
    result = run_bash(
        f"""
        source "{NODE_INSTALLER}"
        sudo() {{
            if [[ "$1" == "-u" ]]; then
                shift 2
            fi
            "$@"
        }}
        fakebin="$(mktemp -d)"
        token_file="$(mktemp)"
        printf 'demo-token' > "$token_file"
        cat >"$fakebin/git" <<'EOF'
#!/bin/sh
printf '%s|%s|%s\\n' "$GIT_ASKPASS" "$GIT_TERMINAL_PROMPT" "$MDS_GIT_AUTH_TOKEN_FILE"
EOF
        chmod +x "$fakebin/git"
        PATH="$fakebin:$PATH"
        GIT_AUTH_TOKEN_FILE="$token_file"
        run_git_as_mds_user "https://github.com/demo/private.git" status >/tmp/node_wrapper_auth.txt
        grep -Eq '.*/\\.cache/mds-runtime/mds_node_git_askpass\\.sh\\|0\\|' /tmp/node_wrapper_auth.txt
        grep -q "$token_file" /tmp/node_wrapper_auth.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_node_wrapper_private_ssh_auth_uses_configured_key_file():
    result = run_bash(
        f"""
        source "{NODE_INSTALLER}"
        sudo() {{
            if [[ "$1" == "-u" ]]; then
                shift 2
            fi
            "$@"
        }}
        fakebin="$(mktemp -d)"
        GIT_SSH_KEY_FILE="/tmp/customer_node_key"
        set_wrapper_ssh_key_path
        cat >"$fakebin/git" <<'EOF'
#!/bin/sh
printf '%s\n' "$GIT_SSH_COMMAND"
EOF
        chmod +x "$fakebin/git"
        PATH="$fakebin:$PATH"
        run_git_as_mds_user "git@github.com:demo/private.git" status >/tmp/node_wrapper_ssh.txt
        grep -q '/tmp/customer_node_key' /tmp/node_wrapper_ssh.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_runtime_git_sync_prefers_explicit_https_repo_when_token_file_is_present():
    result = run_bash(
        f"""
        source "{GIT_SYNC_SCRIPT}"
        token_file="$(mktemp)"
        printf 'demo-token' > "$token_file"
        MDS_GIT_AUTH_TOKEN_FILE="$token_file"
        [[ "$(determine_git_url "https://github.com/demo/private.git")" == "https://github.com/demo/private.git" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_runtime_git_sync_https_auth_uses_askpass_token_file():
    result = run_bash(
        f"""
        source "{GIT_SYNC_SCRIPT}"
        fakebin="$(mktemp -d)"
        token_file="$(mktemp)"
        printf 'demo-token' > "$token_file"
        cat >"$fakebin/git" <<'EOF'
#!/bin/sh
printf '%s|%s|%s\\n' "$GIT_ASKPASS" "$GIT_TERMINAL_PROMPT" "$MDS_GIT_AUTH_TOKEN_FILE"
EOF
        chmod +x "$fakebin/git"
        PATH="$fakebin:$PATH"
        MDS_GIT_AUTH_TOKEN_FILE="$token_file"
        run_git_command "https://github.com/demo/private.git" status >/tmp/runtime_git_sync_auth.txt
        grep -Eq '.*/\\.cache/mds-runtime/mds_git_sync_askpass\\.sh\\|0\\|' /tmp/runtime_git_sync_auth.txt
        grep -q "$token_file" /tmp/runtime_git_sync_auth.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_dashboard_start_uses_canonical_runtime_mode_and_health_path():
    start_script = REPO_ROOT / "app" / "linux_dashboard_start.sh"
    verify_script = REPO_ROOT / "tools" / "mds_gcs_init_lib" / "gcs_verify.sh"

    start_text = start_script.read_text(encoding="utf-8")
    verify_text = verify_script.read_text(encoding="utf-8")

    assert '--status) STATUS_ONLY=true; shift ;;' in start_text
    assert "resolve_current_runtime_mode() {" in start_text
    assert "persist_runtime_mode_in_gcs_config() {" in start_text
    assert "Mode Source:" in start_text
    assert "Configured Repo:" in start_text
    assert "Origin Remote:" in start_text
    assert "Repo Authority:" in start_text
    assert "Repo Access:" in start_text
    assert "Git Auto Push:" in start_text
    assert "repo_authority_status() {" in start_text
    assert "get_repo_access_mode() {" in start_text
    assert 'get_react_build_marker() {' in start_text
    assert '$BUILD_DIR/asset-manifest.json' in start_text
    assert 'Build marker is up-to-date. Skipping rebuild.' in start_text
    assert "sync_runtime_compatibility_marker" not in start_text
    assert start_text.index("load_gcs_system_config") < start_text.index('if [[ "$STATUS_ONLY" == "true" ]]')
    assert "/api/v1/system/health" in start_text
    assert "/api/v1/system/health" in verify_text
    assert "Configured Repo:" in verify_text
    assert "Origin Remote:" in verify_text
    assert "Repo Authority:" in verify_text
    assert "MDS_DOCKER_IMAGE" in start_text
    assert "MDS_SITL_GIT_SYNC" in start_text
    assert "MDS_SITL_REQUIREMENTS_SYNC" in start_text


def test_dashboard_start_build_check_skips_rebuild_when_marker_is_newer_than_sources():
    start_script = REPO_ROOT / "app" / "linux_dashboard_start.sh"

    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        mkdir -p "$tmpdir/app/dashboard/drone-dashboard/src" \
                 "$tmpdir/app/dashboard/drone-dashboard/build" \
                 "$tmpdir/gcs-server"
        python3 - <<'PY' "$tmpdir" "{start_script}"
from pathlib import Path
import sys

tmpdir = Path(sys.argv[1])
start_script = Path(sys.argv[2])
script_text = start_script.read_text(encoding="utf-8")
prefix = script_text.split("# MAIN EXECUTION", 1)[0]
(tmpdir / "app" / "linux_dashboard_start.sh").write_text(prefix, encoding="utf-8")
PY
        cat >"$tmpdir/app/dashboard/drone-dashboard/package.json" <<'EOF'
{{"name":"demo-dashboard","version":"1.0.0"}}
EOF
        cat >"$tmpdir/app/dashboard/drone-dashboard/src/App.js" <<'EOF'
console.log('demo');
EOF
        cat >"$tmpdir/app/dashboard/drone-dashboard/build/asset-manifest.json" <<'EOF'
{{"files":{{}}}}
EOF
        python3 - <<'PY' "$tmpdir"
from pathlib import Path
import os
import sys
import time

tmpdir = Path(sys.argv[1])
older = time.time() - 120
newer = time.time()
for relative in (
    "app/dashboard/drone-dashboard/package.json",
    "app/dashboard/drone-dashboard/src/App.js",
):
    path = tmpdir / relative
    os.utime(path, (older, older))
marker = tmpdir / "app/dashboard/drone-dashboard/build/asset-manifest.json"
os.utime(marker, (newer, newer))
PY
        source "$tmpdir/app/linux_dashboard_start.sh"
        if check_build_needed; then
            echo "unexpected rebuild"
            exit 1
        fi
        """
    )

    assert result.returncode == 0, result.stderr


def test_dashboard_start_build_check_detects_newer_source_than_marker():
    start_script = REPO_ROOT / "app" / "linux_dashboard_start.sh"

    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        mkdir -p "$tmpdir/app/dashboard/drone-dashboard/src" \
                 "$tmpdir/app/dashboard/drone-dashboard/build" \
                 "$tmpdir/gcs-server"
        python3 - <<'PY' "$tmpdir" "{start_script}"
from pathlib import Path
import sys

tmpdir = Path(sys.argv[1])
start_script = Path(sys.argv[2])
script_text = start_script.read_text(encoding="utf-8")
prefix = script_text.split("# MAIN EXECUTION", 1)[0]
(tmpdir / "app" / "linux_dashboard_start.sh").write_text(prefix, encoding="utf-8")
PY
        cat >"$tmpdir/app/dashboard/drone-dashboard/package.json" <<'EOF'
{{"name":"demo-dashboard","version":"1.0.0"}}
EOF
        cat >"$tmpdir/app/dashboard/drone-dashboard/src/App.js" <<'EOF'
console.log('demo');
EOF
        cat >"$tmpdir/app/dashboard/drone-dashboard/build/asset-manifest.json" <<'EOF'
{{"files":{{}}}}
EOF
        python3 - <<'PY' "$tmpdir"
from pathlib import Path
import os
import sys
import time

tmpdir = Path(sys.argv[1])
older = time.time() - 120
newer = time.time()
marker = tmpdir / "app/dashboard/drone-dashboard/build/asset-manifest.json"
os.utime(marker, (older, older))
for relative in (
    "app/dashboard/drone-dashboard/package.json",
    "app/dashboard/drone-dashboard/src/App.js",
):
    path = tmpdir / relative
    os.utime(path, (newer, newer))
PY
        source "$tmpdir/app/linux_dashboard_start.sh"
        check_build_needed
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_server_launcher_exports_sitl_runtime_env_from_system_config():
    launcher_script = REPO_ROOT / "gcs-server" / "start_gcs_server.sh"
    launcher_text = launcher_script.read_text(encoding="utf-8")

    assert "MDS_MODE" in launcher_text
    assert "MDS_DOCKER_IMAGE" in launcher_text
    assert "MDS_SITL_GIT_SYNC" in launcher_text
    assert "MDS_SITL_REQUIREMENTS_SYNC" in launcher_text


def test_netbird_detail_parsers_extract_primary_identity_fields():
    result = run_bash(
        f"""
        source "{COMMON_LIB}"
        source "{NETWORK_LIB}"
        get_netbird_detail_output() {{
            cat <<'EOF'
Management: Connected to https://api.netbird.io:443
FQDN: node-101.netbird.example
NetBird IP: 100.64.10.101/16
EOF
        }}
        [[ "$(get_netbird_primary_ip)" == "100.64.10.101" ]]
        [[ "$(get_netbird_management_url)" == "https://api.netbird.io:443" ]]
        [[ "$(get_netbird_fqdn)" == "node-101.netbird.example" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_repo_structure_validation_accepts_current_led_indicator_layout():
    result = run_bash(
        f"""
        MDS_INSTALL_DIR="{REPO_ROOT}"
        MDS_USER="droneshow"
        log_step() {{ :; }}
        log_error() {{ :; }}
        is_dry_run() {{ return 1; }}
        source "{REPO_LIB}"
        validate_repo_structure
        """
    )

    assert result.returncode == 0, result.stderr


def test_mavlink_setup_phase_returns_auto_config_status_in_non_interactive_mode():
    result = run_bash(
        f"""
        source "{COMMON_LIB}"
        source "{MAVLINK_SETUP_LIB}"
        print_phase_header() {{ :; }}
        print_section() {{ :; }}
        set_led_state() {{ :; }}
        display_mavlink_status() {{ :; }}
        check_mavlink_router_installed() {{ return 1; }}
        check_mavlink_router_running() {{ return 1; }}
        run_mavlink_auto_config() {{ return 7; }}
        NON_INTERACTIVE=true
        MAVLINK_SKIP=false
        MAVLINK_AUTO=false
        MAVLINK_UART=""
        MAVLINK_ENDPOINTS=""
        run_mavlink_setup_phase
        [[ "$?" -eq 7 ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_mavlink_auto_config_applies_serial_fix_on_raspberry_pi():
    result = run_bash(
        f"""
        source "{COMMON_LIB}"
        source "{MAVLINK_SETUP_LIB}"
        log_step() {{ :; }}
        log_info() {{ echo "$1"; }}
        log_success() {{ :; }}
        is_raspberry_pi() {{ return 0; }}
        check_serial_console_enabled() {{ return 0; }}
        check_uart_enabled() {{ return 1; }}
        auto_fix_uart_config() {{ echo "serial-fix"; return 0; }}
        check_mavlink_router_installed() {{ return 0; }}
        detect_uart_device() {{ echo "/dev/ttyS0"; }}
        run_mavlink_configure_headless() {{ return 0; }}
        verify_mavlink_service() {{ return 0; }}
        GCS_IP="100.64.20.10"
        run_mavlink_auto_config >/tmp/mavlink_auto_fix_output.txt
        grep -q "serial-fix" /tmp/mavlink_auto_fix_output.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_mavsdk_binary_name_resolution_supports_arm64_without_array_errors():
    result = run_bash(
        f"""
        source "{COMMON_LIB}"
        source "{MAVSDK_LIB}"
        get_architecture() {{ echo arm64; }}
        [[ "$(get_mavsdk_binary_name)" == "mavsdk_server_linux-arm64-musl" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_fetch_latest_mavsdk_version_keeps_stdout_machine_readable():
    result = run_bash(
        f"""
        source "{COMMON_LIB}"
        source "{MAVSDK_LIB}"
        log_step() {{ echo "$1" >&2; }}
        log_success() {{ echo "$1" >&2; }}
        log_warn() {{ echo "$1" >&2; }}
        curl() {{ printf '%s' '{{"tag_name":"v9.9.9"}}'; }}
        jq() {{ sed -n 's/.*"tag_name":"\\([^"]*\\)".*/\\1/p'; }}
        [[ "$(fetch_latest_version)" == "v9.9.9" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_service_source_path_maps_known_units_without_associative_array_lookup():
    result = run_bash(
        f"""
        source "{COMMON_LIB}"
        source "{SERVICES_LIB}"
        [[ "$(service_source_path led_indicator.service)" == "tools/led_indicator/led_indicator.service" ]]
        [[ "$(service_source_path coordinator.service)" == "tools/coordinator.service" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_common_lib_respects_runtime_user_and_install_dir_overrides():
    result = run_bash(
        f"""
        MDS_USER="skyfleet"
        MDS_HOME="/srv/skyfleet"
        MDS_INSTALL_DIR="/srv/skyfleet/mds"
        source "{COMMON_LIB}"
        [[ "$MDS_USER" == "skyfleet" ]]
        [[ "$MDS_HOME" == "/srv/skyfleet" ]]
        [[ "$MDS_INSTALL_DIR" == "/srv/skyfleet/mds" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_common_lib_loads_git_tracked_deployment_profile_defaults():
    common_text = COMMON_LIB.read_text()
    loader_text = (REPO_ROOT / "tools" / "load_deployment_profile.sh").read_text()

    assert 'DEPLOYMENT_PROFILE_LOADER="${MDS_REPO_ROOT}/tools/load_deployment_profile.sh"' in common_text
    assert 'source "${MDS_DEPLOYMENT_PROFILE_FILE}"' in loader_text
    assert 'MDS_DEFAULT_REPO_URL_HTTPS' in loader_text
    assert 'MDS_DEFAULT_REPO_URL_SSH' in loader_text
    assert 'MDS_DEFAULT_BRANCH' in loader_text
    assert 'MDS_DEFAULT_CONNECTIVITY_BACKEND' in loader_text
    assert 'MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_URL_HTTPS' in loader_text
    assert 'MDS_DEFAULT_SMART_WIFI_MANAGER_REF' in loader_text
    assert 'MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE' in loader_text
    assert 'MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_URL_HTTPS' in loader_text
    assert 'MDS_DEFAULT_MAVLINK_ANYWHERE_REF' in loader_text


def test_node_repo_reconcile_updates_remote_to_requested_runtime_repo():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        git init -q "$repo_dir"
        git -C "$repo_dir" remote add origin git@github.com:demo/old-mds.git
        sudo() {{
            if [[ "$1" == "-u" ]]; then
                shift 2
            fi
            "$@"
        }}
        log_info() {{ :; }}
        log_error() {{ echo "$1" >&2; }}
        MDS_USER="$(whoami)"
        MDS_HOME="$tmpdir/home"
        MDS_INSTALL_DIR="$repo_dir"
        MDS_DEFAULT_REPO_SLUG="demo/customer-mds"
        MDS_DEFAULT_REPO_URL_SSH="git@github.com:demo/customer-mds.git"
        MDS_DEFAULT_REPO_URL_HTTPS="https://github.com/demo/customer-mds.git"
        MDS_DEFAULT_BRANCH="main"
        source "{COMMON_LIB}"
        source "{REPO_LIB}"
        reconcile_repo_checkout_remote "https://github.com/demo/customer-mds.git"
        [[ "$(git -C "$repo_dir" remote get-url origin)" == "https://github.com/demo/customer-mds.git" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_node_repo_runtime_uses_configured_ssh_key_file():
    result = run_bash(
        f"""
        sudo() {{
            if [[ "$1" == "-u" ]]; then
                shift 2
            fi
            "$@"
        }}
        fakebin="$(mktemp -d)"
        cat >"$fakebin/git" <<'EOF'
#!/bin/sh
printf '%s\n' "$GIT_SSH_COMMAND"
EOF
        chmod +x "$fakebin/git"
        PATH="$fakebin:$PATH"
        MDS_USER="$(whoami)"
        MDS_HOME="$(mktemp -d)"
        MDS_INSTALL_DIR="$MDS_HOME/repo"
        MDS_DEFAULT_REPO_SLUG="demo/customer-mds"
        MDS_DEFAULT_REPO_URL_SSH="git@github.com:demo/customer-mds.git"
        MDS_DEFAULT_REPO_URL_HTTPS="https://github.com/demo/customer-mds.git"
        MDS_DEFAULT_BRANCH="main"
        MDS_GIT_SSH_KEY_FILE="/tmp/customer_node_runtime_key"
        source "{COMMON_LIB}"
        source "{REPO_LIB}"
        run_git_as_mds_user_for_repo "git@github.com:demo/private.git" status >/tmp/node_repo_runtime_ssh.txt
        grep -q '/tmp/customer_node_runtime_key' /tmp/node_repo_runtime_ssh.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_repo_reconcile_updates_remote_to_requested_runtime_repo():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        home_dir="$tmpdir/home"
        mkdir -p "$home_dir"
        git init -q "$repo_dir"
        git -C "$repo_dir" remote add origin git@github.com:demo/old-mds.git
        HOME="$home_dir"
        log_info() {{ :; }}
        log_error() {{ echo "$1" >&2; }}
        log_success() {{ :; }}
        MDS_DEFAULT_REPO_SLUG="demo/customer-mds"
        MDS_DEFAULT_REPO_URL_HTTPS="https://github.com/demo/customer-mds.git"
        MDS_DEFAULT_REPO_URL_SSH="git@github.com:demo/customer-mds.git"
        MDS_DEFAULT_BRANCH="main"
        source "{GCS_COMMON_LIB}"
        source "{GCS_REPO_LIB}"
        reconcile_gcs_repo_checkout_remote "$repo_dir" "https://github.com/demo/customer-mds.git"
        [[ "$(git -C "$repo_dir" remote get-url origin)" == "https://github.com/demo/customer-mds.git" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_install_service_renders_runtime_user_and_install_dir():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        MDS_USER="skyfleet"
        MDS_HOME="/srv/skyfleet"
        MDS_INSTALL_DIR="{REPO_ROOT}"
        MDS_SYSTEMD_DIR="$tmpdir/systemd"
        mkdir -p "$MDS_SYSTEMD_DIR"
        log_step() {{ :; }}
        log_info() {{ :; }}
        log_warn() {{ echo "$1" >&2; }}
        log_success() {{ :; }}
        backup_file() {{ :; }}
        is_dry_run() {{ return 1; }}
        source "{COMMON_LIB}"
        source "{SERVICES_LIB}"
        install_service coordinator.service tools/coordinator.service
        service_file="$MDS_SYSTEMD_DIR/coordinator.service"
        test -f "$service_file"
        grep -q '^User=skyfleet$' "$service_file"
        grep -q '^Group=skyfleet$' "$service_file"
        grep -q '^WorkingDirectory={REPO_ROOT}$' "$service_file"
        grep -q '__MDS_' "$service_file" && exit 1 || true
        """
    )

    assert result.returncode == 0, result.stderr


def test_repo_verification_uses_deployment_profile_defaults_not_params_file():
    gcs_repo_text = (REPO_ROOT / "tools" / "mds_gcs_init_lib" / "gcs_repo.sh").read_text()
    node_repo_text = REPO_LIB.read_text()

    assert "deployment/defaults.env is the repo-owned default layer" in gcs_repo_text
    assert "src/params.py fallback repo settings" not in gcs_repo_text
    assert "deployment/defaults.env repo URL" in node_repo_text
    assert "params.py GIT_REPO_URL" not in node_repo_text


def test_run_services_phase_reconciles_runtime_services_after_enable():
    result = run_bash(
        f"""
        source "{COMMON_LIB}"
        source "{SERVICES_LIB}"
        mkdir -p "${{MDS_INSTALL_DIR}}"
        SKIP_SERVICES="false"
        print_phase_header() {{ :; }}
        print_section() {{ :; }}
        set_led_state() {{ :; }}
        log_step() {{ :; }}
        log_info() {{ :; }}
        log_warn() {{ :; }}
        log_success() {{ :; }}
        is_dry_run() {{ return 1; }}
        configure_sudoers() {{ :; }}
        configure_polkit() {{ :; }}
        configure_gpio_access() {{ :; }}
        install_all_services() {{ echo install; }}
        reload_systemd() {{ echo reload; }}
        enable_all_services() {{ echo enable; }}
        reconcile_runtime_services() {{ echo reconcile; }}
        verify_services() {{ echo verify; }}
        run_services_phase
        """
    )

    assert result.returncode == 0, result.stderr
    assert "install" in result.stdout
    assert "reload" in result.stdout
    assert "enable" in result.stdout
    assert "reconcile" in result.stdout
    assert "verify" in result.stdout


def test_git_sync_service_updates_reenable_previously_enabled_units():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        systemd_dir="$tmpdir/systemd"
        bin_dir="$tmpdir/bin"
        home_dir="$tmpdir/home/companion"
        mkdir -p "$repo_dir/tools/git_sync_mds" "$repo_dir/tools/led_indicator" "$systemd_dir" "$bin_dir" "$home_dir/logs"
        cp "{REPO_ROOT / 'tools' / 'coordinator.service'}" "$repo_dir/tools/coordinator.service"
        cp "{REPO_ROOT / 'tools' / 'git_sync_mds' / 'git_sync_mds.service'}" "$repo_dir/tools/git_sync_mds/git_sync_mds.service"
        cp "{REPO_ROOT / 'tools' / 'led_indicator' / 'led_indicator.service'}" "$repo_dir/tools/led_indicator/led_indicator.service"

        cat > "$systemd_dir/coordinator.service" <<'EOF'
[Service]
ExecStart=/old/path/coordinator.py
EOF

        cat > "$bin_dir/sudo" <<'EOF'
#!/bin/bash
exec "$@"
EOF
        cat > "$bin_dir/systemd-analyze" <<'EOF'
#!/bin/bash
exit 0
EOF
        cat > "$bin_dir/systemctl" <<'EOF'
#!/bin/bash
printf '%s\\n' "$*" >> "$TMPDIR/systemctl.log"
case "$*" in
  "is-enabled --quiet coordinator.service") exit 0 ;;
  "daemon-reload") exit 0 ;;
  "reenable coordinator.service") exit 0 ;;
esac
exit 1
EOF
        chmod +x "$bin_dir/sudo" "$bin_dir/systemd-analyze" "$bin_dir/systemctl"

        PATH="$bin_dir:$PATH" \
        TMPDIR="$tmpdir" \
        HOME="$home_dir" \
        USER="companion" \
        REPO_USER="companion" \
        REPO_DIR="$repo_dir" \
        MDS_USER="companion" \
        MDS_HOME="$home_dir" \
        MDS_INSTALL_DIR="$repo_dir" \
        MDS_SYSTEMD_DIR="$systemd_dir" \
        bash -lc 'source "{GIT_SYNC_SCRIPT}"; check_service_updates; service_file="$MDS_SYSTEMD_DIR/coordinator.service"; grep -q "^User=companion$" "$service_file"; grep -q "^WorkingDirectory=$REPO_DIR$" "$service_file"; grep -q "^ExecStart=$REPO_DIR/venv/bin/python $REPO_DIR/coordinator.py$" "$service_file"; printf "%s\\n" "${{UPDATED_SYSTEMD_UNITS[@]}}" | grep -qx "coordinator.service"'

        grep -q "^daemon-reload$" "$tmpdir/systemctl.log"
        grep -q "^reenable coordinator.service$" "$tmpdir/systemctl.log"
        """
    )

    assert result.returncode == 0, result.stderr


def test_git_sync_service_updates_restore_previous_units_when_daemon_reload_fails():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        systemd_dir="$tmpdir/systemd"
        bin_dir="$tmpdir/bin"
        home_dir="$tmpdir/home/companion"
        mkdir -p "$repo_dir/tools/git_sync_mds" "$repo_dir/tools/led_indicator" "$systemd_dir" "$bin_dir" "$home_dir/logs"
        cp "{REPO_ROOT / 'tools' / 'coordinator.service'}" "$repo_dir/tools/coordinator.service"
        cp "{REPO_ROOT / 'tools' / 'git_sync_mds' / 'git_sync_mds.service'}" "$repo_dir/tools/git_sync_mds/git_sync_mds.service"
        cp "{REPO_ROOT / 'tools' / 'led_indicator' / 'led_indicator.service'}" "$repo_dir/tools/led_indicator/led_indicator.service"

        cat > "$systemd_dir/coordinator.service" <<'EOF'
[Service]
ExecStart=/old/path/coordinator.py
EOF

        cat > "$bin_dir/sudo" <<'EOF'
#!/bin/bash
exec "$@"
EOF
        cat > "$bin_dir/systemd-analyze" <<'EOF'
#!/bin/bash
exit 0
EOF
        cat > "$bin_dir/systemctl" <<'EOF'
#!/bin/bash
printf '%s\\n' "$*" >> "$TMPDIR/systemctl.log"
case "$*" in
  "is-enabled --quiet coordinator.service")
    exit 0
    ;;
  "daemon-reload")
    count=0
    if [[ -f "$TMPDIR/daemon-reload.count" ]]; then
      count=$(cat "$TMPDIR/daemon-reload.count")
    fi
    count=$((count + 1))
    printf '%s\\n' "$count" > "$TMPDIR/daemon-reload.count"
    if [[ "$count" -eq 1 ]]; then
      exit 1
    fi
    exit 0
    ;;
esac
exit 1
EOF
        chmod +x "$bin_dir/sudo" "$bin_dir/systemd-analyze" "$bin_dir/systemctl"

        PATH="$bin_dir:$PATH" \
        TMPDIR="$tmpdir" \
        HOME="$home_dir" \
        USER="companion" \
        REPO_USER="companion" \
        REPO_DIR="$repo_dir" \
        MDS_USER="companion" \
        MDS_HOME="$home_dir" \
        MDS_INSTALL_DIR="$repo_dir" \
        MDS_SYSTEMD_DIR="$systemd_dir" \
        bash -lc 'source "{GIT_SYNC_SCRIPT}"; check_service_updates; service_file="$MDS_SYSTEMD_DIR/coordinator.service"; grep -q "^ExecStart=/old/path/coordinator.py$" "$service_file"; [[ "${{#UPDATED_SYSTEMD_UNITS[@]}}" -eq 0 ]]'

        [[ "$(grep -c "^daemon-reload$" "$tmpdir/systemctl.log")" -eq 2 ]]
        ! grep -q "^reenable coordinator.service$" "$tmpdir/systemctl.log"
        """
    )

    assert result.returncode == 0, result.stderr


def test_git_sync_service_unit_updates_do_not_restart_running_sync():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        systemd_dir="$tmpdir/systemd"
        bin_dir="$tmpdir/bin"
        home_dir="$tmpdir/home/companion"
        mkdir -p "$repo_dir/tools/git_sync_mds" "$systemd_dir" "$bin_dir" "$home_dir/logs"
        cp "{REPO_ROOT / 'tools' / 'git_sync_mds' / 'git_sync_mds.service'}" "$repo_dir/tools/git_sync_mds/git_sync_mds.service"

        cat > "$systemd_dir/git_sync_mds.service" <<'EOF'
[Service]
ExecStart=/old/path/update_repo_ssh.sh
EOF

        cat > "$bin_dir/sudo" <<'EOF'
#!/bin/bash
exec "$@"
EOF
        cat > "$bin_dir/systemd-analyze" <<'EOF'
#!/bin/bash
exit 0
EOF
        cat > "$bin_dir/systemctl" <<'EOF'
#!/bin/bash
printf '%s\\n' "$*" >> "$TMPDIR/systemctl.log"
case "$*" in
  "is-enabled --quiet git_sync_mds.service") exit 0 ;;
  "daemon-reload") exit 0 ;;
  "reenable git_sync_mds.service") exit 0 ;;
esac
exit 1
EOF
        chmod +x "$bin_dir/sudo" "$bin_dir/systemd-analyze" "$bin_dir/systemctl"

        PATH="$bin_dir:$PATH" \
        TMPDIR="$tmpdir" \
        HOME="$home_dir" \
        USER="companion" \
        REPO_USER="companion" \
        REPO_DIR="$repo_dir" \
        MDS_USER="companion" \
        MDS_HOME="$home_dir" \
        MDS_INSTALL_DIR="$repo_dir" \
        MDS_SYSTEMD_DIR="$systemd_dir" \
        bash -lc 'source "{GIT_SYNC_SCRIPT}"; check_service_updates; service_file="$MDS_SYSTEMD_DIR/git_sync_mds.service"; grep -q "^User=companion$" "$service_file"; grep -q "^WorkingDirectory=$REPO_DIR$" "$service_file"; grep -q "^ExecStart=$REPO_DIR/tools/update_repo_ssh.sh$" "$service_file"; printf "%s\\n" "${{UPDATED_SYSTEMD_UNITS[@]}}" | grep -qx "git_sync_mds.service"'

        grep -q "^daemon-reload$" "$tmpdir/systemctl.log"
        grep -q "^reenable git_sync_mds.service$" "$tmpdir/systemctl.log"
        ! grep -q "restart git_sync_mds.service" "$tmpdir/systemctl.log"
        """
    )

    assert result.returncode == 0, result.stderr


def test_post_sync_runtime_restart_schedules_coordinator_when_active():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        bin_dir="$tmpdir/bin"
        home_dir="$tmpdir/home/companion"
        mkdir -p "$repo_dir" "$bin_dir" "$home_dir/logs"

        cat > "$bin_dir/sudo" <<'EOF'
#!/bin/bash
exec "$@"
EOF
        cat > "$bin_dir/systemctl" <<'EOF'
#!/bin/bash
printf '%s\\n' "$*" >> "$TMPDIR/systemctl.log"
case "$*" in
  "is-active --quiet coordinator.service") exit 0 ;;
  "is-failed --quiet coordinator.service") exit 1 ;;
esac
exit 1
EOF
        cat > "$bin_dir/systemd-run" <<'EOF'
#!/bin/bash
printf '%s\\n' "$*" >> "$TMPDIR/systemd-run.log"
exit 0
EOF
        chmod +x "$bin_dir/sudo" "$bin_dir/systemctl" "$bin_dir/systemd-run"

        PATH="$bin_dir:$PATH" \
        TMPDIR="$tmpdir" \
        HOME="$home_dir" \
        USER="companion" \
        REPO_USER="companion" \
        REPO_DIR="$repo_dir" \
        bash -lc 'source "{GIT_SYNC_SCRIPT}"; mark_coordinator_restart_needed "runtime files changed"; apply_post_sync_service_actions'

        grep -q "is-active --quiet coordinator.service" "$tmpdir/systemctl.log"
        grep -q "restart coordinator.service" "$tmpdir/systemd-run.log"
        """
    )

    assert result.returncode == 0, result.stderr


def test_post_sync_runtime_restart_keeps_inactive_coordinator_stopped():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        bin_dir="$tmpdir/bin"
        home_dir="$tmpdir/home/companion"
        mkdir -p "$repo_dir" "$bin_dir" "$home_dir/logs"

        cat > "$bin_dir/sudo" <<'EOF'
#!/bin/bash
exec "$@"
EOF
        cat > "$bin_dir/systemctl" <<'EOF'
#!/bin/bash
printf '%s\\n' "$*" >> "$TMPDIR/systemctl.log"
case "$*" in
  "is-active --quiet coordinator.service") exit 1 ;;
  "is-failed --quiet coordinator.service") exit 1 ;;
esac
exit 1
EOF
        cat > "$bin_dir/systemd-run" <<'EOF'
#!/bin/bash
printf '%s\\n' "$*" >> "$TMPDIR/systemd-run.log"
exit 0
EOF
        chmod +x "$bin_dir/sudo" "$bin_dir/systemctl" "$bin_dir/systemd-run"

        PATH="$bin_dir:$PATH" \
        TMPDIR="$tmpdir" \
        HOME="$home_dir" \
        USER="companion" \
        REPO_USER="companion" \
        REPO_DIR="$repo_dir" \
        bash -lc 'source "{GIT_SYNC_SCRIPT}"; mark_coordinator_restart_needed "runtime files changed"; apply_post_sync_service_actions; [[ ! -f "$TMPDIR/systemd-run.log" ]]'

        grep -q "is-active --quiet coordinator.service" "$tmpdir/systemctl.log"
        grep -q "is-failed --quiet coordinator.service" "$tmpdir/systemctl.log"
        """
    )

    assert result.returncode == 0, result.stderr


def test_post_sync_service_actions_record_deferred_unit_apply_paths():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        bin_dir="$tmpdir/bin"
        home_dir="$tmpdir/home/companion"
        mkdir -p "$repo_dir" "$bin_dir" "$home_dir/logs"

        cat > "$bin_dir/sudo" <<'EOF'
#!/bin/bash
exec "$@"
EOF
        cat > "$bin_dir/systemctl" <<'EOF'
#!/bin/bash
case "$*" in
  "is-active --quiet coordinator.service") exit 1 ;;
  "is-failed --quiet coordinator.service") exit 1 ;;
esac
exit 1
EOF
        chmod +x "$bin_dir/sudo" "$bin_dir/systemctl"

        PATH="$bin_dir:$PATH" \
        TMPDIR="$tmpdir" \
        HOME="$home_dir" \
        USER="companion" \
        REPO_USER="companion" \
        REPO_DIR="$repo_dir" \
        bash -lc 'source "{GIT_SYNC_SCRIPT}"; SERVICE_RELOAD_REQUIRED=true; UPDATED_SYSTEMD_UNITS=("git_sync_mds.service" "led_indicator.service"); mark_coordinator_restart_needed "runtime files changed"; apply_post_sync_service_actions; printf "%s\\n" "${{DEFERRED_UNIT_ACTIONS[@]}}" | grep -qx "git_sync_mds.service:next_invocation"; printf "%s\\n" "${{DEFERRED_UNIT_ACTIONS[@]}}" | grep -qx "led_indicator.service:next_boot"; printf "%s\\n" "${{DEFERRED_UNIT_ACTIONS[@]}}" | grep -qx "coordinator.service:inactive_left_stopped"'
        """
    )

    assert result.returncode == 0, result.stderr


def test_git_sync_runtime_state_persists_post_sync_summary():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        mkdir -p "$tmpdir/home/logs" "$tmpdir/repo/.git"
        HOME="$tmpdir/home"
        REPO_DIR="$tmpdir/repo"
        MDS_GIT_SYNC_STATE_FILE="$tmpdir/last_result.env"
        BRANCH_NAME="main-candidate"
        source "{GIT_SYNC_SCRIPT}"
        UPDATED_SYSTEMD_UNITS=("coordinator.service" "git_sync_mds.service")
        DEFERRED_UNIT_ACTIONS=("git_sync_mds.service:next_invocation")
        SERVICE_RELOAD_STATUS="updated"
        SERVICE_RELOAD_MESSAGE="Systemd unit updates were applied successfully."
        COORDINATOR_RESTART_REASONS=("runtime files changed")
        COORDINATOR_RESTART_SCHEDULED=true
        CONNECTIVITY_RECONCILE_STATUS="success"
        MAVLINK_RUNTIME_RECONCILE_STATUS="warning"
        REQUIREMENTS_UPDATE_STATUS="updated"
        persist_git_sync_state "success" "Git synchronization completed successfully"
        grep -q '^status=success$' "$tmpdir/last_result.env"
        grep -q '^updated_units=coordinator.service,git_sync_mds.service$' "$tmpdir/last_result.env"
        grep -q '^service_reload_status=updated$' "$tmpdir/last_result.env"
        grep -q '^service_reload_message=Systemd unit updates were applied successfully.$' "$tmpdir/last_result.env"
        grep -q '^deferred_unit_actions=git_sync_mds.service:next_invocation$' "$tmpdir/last_result.env"
        grep -q '^coordinator_restart_scheduled=true$' "$tmpdir/last_result.env"
        grep -q '^connectivity_reconcile_status=success$' "$tmpdir/last_result.env"
        grep -q '^mavlink_runtime_reconcile_status=warning$' "$tmpdir/last_result.env"
        grep -q '^requirements_update_status=updated$' "$tmpdir/last_result.env"
        """
    )

    assert result.returncode == 0, result.stderr


def test_git_sync_runtime_state_defaults_to_user_home_state_dir():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        mkdir -p "$tmpdir/home/logs" "$tmpdir/repo/.git"
        HOME="$tmpdir/home"
        REPO_DIR="$tmpdir/repo"
        BRANCH_NAME="main-candidate"
        source "{GIT_SYNC_SCRIPT}"
        persist_git_sync_state "success" "ok"
        test -f "$tmpdir/home/.local/state/mds/git-sync/last_result.env"
        """
    )

    assert result.returncode == 0, result.stderr


def test_git_sync_service_template_omits_no_new_privileges():
    service_text = (REPO_ROOT / "tools" / "git_sync_mds" / "git_sync_mds.service").read_text(encoding="utf-8")

    assert "NoNewPrivileges=yes" not in service_text


def test_git_sync_service_template_sources_gcs_env_before_local_env():
    service_text = (REPO_ROOT / "tools" / "git_sync_mds" / "git_sync_mds.service").read_text(encoding="utf-8")

    assert "EnvironmentFile=-/etc/mds/gcs.env" in service_text
    assert service_text.index("EnvironmentFile=-/etc/mds/gcs.env") < service_text.index("EnvironmentFile=-/etc/mds/local.env")


def test_git_sync_service_template_validation_uses_service_suffix():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        bin_dir="$tmpdir/bin"
        home_dir="$tmpdir/home/companion"
        mkdir -p "$repo_dir/tools/git_sync_mds" "$bin_dir" "$home_dir/logs"
        cp "{REPO_ROOT / 'tools' / 'git_sync_mds' / 'git_sync_mds.service'}" "$repo_dir/tools/git_sync_mds/git_sync_mds.service"

        cat > "$bin_dir/systemd-analyze" <<'EOF'
#!/bin/bash
[[ "$1" == "verify" ]] || exit 1
[[ "$2" == *.service ]] || exit 1
exit 0
EOF
        chmod +x "$bin_dir/systemd-analyze"

        PATH="$bin_dir:$PATH" \
        HOME="$home_dir" \
        USER="companion" \
        REPO_USER="companion" \
        REPO_DIR="$repo_dir" \
        MDS_USER="companion" \
        MDS_HOME="$home_dir" \
        MDS_INSTALL_DIR="$repo_dir" \
        bash -lc 'source "{GIT_SYNC_SCRIPT}"; validate_post_sync_service_template "tools/git_sync_mds/git_sync_mds.service"'
        """
    )

    assert result.returncode == 0, result.stderr


def test_git_sync_runtime_env_prefers_local_over_gcs_and_user_env():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        config_dir="$tmpdir/config"
        user_env_dir="$tmpdir/home/.config/mds"
        mkdir -p "$repo_dir/.git" "$config_dir" "$user_env_dir" "$tmpdir/home/logs"

        cat > "$config_dir/gcs.env" <<'EOF'
MDS_REPO_URL=git@github.com:example-org/gcs.git
MDS_BRANCH=ops
MDS_INSTALL_DIR=/srv/gcs
EOF

        cat > "$config_dir/local.env" <<'EOF'
MDS_REPO_URL=git@github.com:example-org/node.git
MDS_BRANCH=field
EOF

        cat > "$user_env_dir/env" <<'EOF'
MDS_BRANCH=user
MDS_GIT_AUTO_PUSH=false
EOF

        HOME="$tmpdir/home" \
        USER="companion" \
        REPO_USER="companion" \
        REPO_DIR="$repo_dir" \
        MDS_GCS_ENV_FILE="$config_dir/gcs.env" \
        MDS_LOCAL_ENV_FILE="$config_dir/local.env" \
        MDS_USER_ENV_FILE="$user_env_dir/env" \
        bash -lc 'source "{GIT_SYNC_SCRIPT}"; load_runtime_env_files; refresh_derived_runtime_paths; [[ "$MDS_REPO_URL" == "git@github.com:example-org/node.git" ]]; [[ "$MDS_BRANCH" == "user" ]]; [[ "$MDS_INSTALL_DIR" == "/srv/gcs" ]]; [[ "$MDS_GIT_AUTO_PUSH" == "false" ]]; [[ "$REPO_DIR" == "/srv/gcs" ]]; [[ "$LED_CMD" == "/srv/gcs/venv/bin/python /srv/gcs/led_indicator.py" ]]'
        """
    )

    assert result.returncode == 0, result.stderr


def test_python_env_prefers_node_requirements_when_present():
    result = run_bash(
        f"""
        MDS_INSTALL_DIR="{REPO_ROOT}"
        MDS_USER="droneshow"
        log_step() {{ :; }}
        log_info() {{ echo "$1"; }}
        log_error() {{ echo "$1" >&2; }}
        is_dry_run() {{ return 0; }}
        source "{PYTHON_ENV_LIB}"
        install_requirements
        """
    )

    assert result.returncode == 0, result.stderr
    assert "requirements-node.txt" in result.stdout


def test_setup_local_env_writes_clean_override_lines():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        MDS_CONFIG_DIR="$tmpdir"
        MDS_LOCAL_ENV="$tmpdir/local.env"
        MDS_VERSION="4.5.0"
        MDS_GIT_AUTH_TOKEN_FILE="/home/droneshow/.mds_git_read_token"
        MDS_GIT_SSH_KEY_FILE="/home/droneshow/.ssh/customer_git_read_key"
        log_step() {{ :; }}
        log_success() {{ :; }}
        is_dry_run() {{ return 1; }}
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'identity.sh'}"
        setup_local_env 101 100.64.20.10 git@github.com:example-org/private-mds.git main http://100.64.20.10:5000
        grep -q '^MDS_HW_ID=101$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_CONNECTIVITY_BACKEND=none$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_MAVLINK_MANAGEMENT_MODE=managed$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_MAVLINK_ANYWHERE_INSTALL_DIR=/opt/mavlink-anywhere$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_MAVLINK_ANYWHERE_DASHBOARD_LISTEN=127.0.0.1:9070$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_MAVLINK_ANYWHERE_SKIP_DASHBOARD=false$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_GCS_IP=100.64.20.10$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_GCS_API_BASE_URL=http://100.64.20.10:5000$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_REPO_URL=git@github.com:example-org/private-mds.git$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_BRANCH=main$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_GIT_AUTH_TOKEN_FILE=/home/droneshow/.mds_git_read_token$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_GIT_SSH_KEY_FILE=/home/droneshow/.ssh/customer_git_read_key$' "$MDS_LOCAL_ENV"
        ! grep -q '^MDS_HW_ID=.*#' "$MDS_LOCAL_ENV"
        """
    )

    assert result.returncode == 0, result.stderr


def test_reconcile_connectivity_uses_repo_profile_when_backend_is_smart_wifi_manager():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        mkdir -p "$repo_dir/deployment/connectivity/smart-wifi-manager"
        mkdir -p "$repo_dir/tools"
        cp "{RECONCILE_CONNECTIVITY_SCRIPT}" "$repo_dir/tools/reconcile_connectivity.sh"
        cp "{REPO_ROOT / 'tools' / 'load_deployment_profile.sh'}" "$repo_dir/tools/load_deployment_profile.sh"
        cat > "$repo_dir/deployment/defaults.env" <<'EOF'
MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_URL_HTTPS=https://github.com/demo/smart-wifi-manager.git
MDS_DEFAULT_SMART_WIFI_MANAGER_REF=v9.9.9
EOF
        cat > "$repo_dir/deployment/connectivity/smart-wifi-manager/profile.json" <<'EOF'
{{"mode":"manage","profiles":[]}}
EOF
        config_dir="$tmpdir/etc-mds"
        mkdir -p "$config_dir"
        cat > "$config_dir/local.env" <<'EOF'
MDS_CONNECTIVITY_BACKEND=smart-wifi-manager
MDS_SMART_WIFI_MANAGER_INSTALL_DIR=TMPDIR_REPLACE/swm
MDS_SMART_WIFI_MANAGER_MODE=manage
MDS_SMART_WIFI_MANAGER_IMPORT_MODE=replace
MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN=0.0.0.0:9080
EOF
        sed -i "s|TMPDIR_REPLACE|$tmpdir|g" "$config_dir/local.env"
        fakebin="$tmpdir/fakebin"
        mkdir -p "$fakebin"
        cat > "$fakebin/git" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$TMPDIR/git_args.txt"
if [[ "$1" == "clone" ]]; then
    target="${{@: -1}}"
    mkdir -p "$target/.git"
    cat > "$target/install.sh" <<'EOS'
#!/bin/bash
printf '%s\n' "$*" > "$TMPDIR/install_args.txt"
EOS
    chmod +x "$target/install.sh"
    cat > "$target/configure_smart_wifi_manager.sh" <<'EOS'
#!/bin/bash
printf '%s\n' "$*" > "$TMPDIR/configure_args.txt"
EOS
    chmod +x "$target/configure_smart_wifi_manager.sh"
fi
exit 0
EOF
        chmod +x "$fakebin/git"
        cat > "$fakebin/systemctl" <<'EOF'
#!/bin/sh
exit 0
EOF
        chmod +x "$fakebin/systemctl"
        TMPDIR="$tmpdir" PATH="$fakebin:$PATH" MDS_CONNECTIVITY_STATE_DIR="$tmpdir/state" MDS_LOCAL_ENV_FILE="$config_dir/local.env" bash "$repo_dir/tools/reconcile_connectivity.sh" apply --force
        grep -q -- 'clone --depth 1 --branch v9.9.9 https://github.com/demo/smart-wifi-manager.git' "$tmpdir/git_args.txt"
        grep -q -- '--dashboard-version v9.9.9' "$tmpdir/install_args.txt"
        grep -q -- '--import '"$repo_dir"'/deployment/connectivity/smart-wifi-manager/profile.json' "$tmpdir/configure_args.txt"
        grep -q -- '--mode manage' "$tmpdir/configure_args.txt"
        """
    )

    assert result.returncode == 0, result.stderr


def test_connectivity_persistence_keeps_repo_ref_in_defaults_layer_unless_explicit():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        MDS_DEFAULT_CONNECTIVITY_BACKEND=none
        MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_URL_HTTPS=https://github.com/demo/smart-wifi-manager.git
        MDS_DEFAULT_SMART_WIFI_MANAGER_REF=v9.9.9
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'connectivity.sh'}"
        update_local_env_value() {{ printf 'set:%s=%s\\n' "$1" "$2" >> "$tmpdir/out.txt"; }}
        remove_local_env_value() {{ printf 'remove:%s\\n' "$1" >> "$tmpdir/out.txt"; }}
        MDS_CONNECTIVITY_BACKEND="smart-wifi-manager"
        SMART_WIFI_MANAGER_MODE="observe"
        SMART_WIFI_MANAGER_IMPORT_MODE="replace"
        SMART_WIFI_MANAGER_REPO_URL_EXPLICIT="false"
        SMART_WIFI_MANAGER_REF_EXPLICIT="false"
        persist_connectivity_local_env
        grep -q '^remove:MDS_SMART_WIFI_MANAGER_REPO_URL$' "$tmpdir/out.txt"
        grep -q '^remove:MDS_SMART_WIFI_MANAGER_REF$' "$tmpdir/out.txt"
        ! grep -q '^set:MDS_SMART_WIFI_MANAGER_REPO_URL=' "$tmpdir/out.txt"
        ! grep -q '^set:MDS_SMART_WIFI_MANAGER_REF=' "$tmpdir/out.txt"
        """
    )

    assert result.returncode == 0, result.stderr


def test_mavlink_persistence_keeps_repo_ref_in_defaults_layer_unless_explicit():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        source "{COMMON_LIB}"
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'identity.sh'}"
        source "{MAVLINK_SETUP_LIB}"
        update_local_env_value() {{ printf 'set:%s=%s\\n' "$1" "$2" >> "$tmpdir/out.txt"; }}
        remove_local_env_value() {{ printf 'remove:%s\\n' "$1" >> "$tmpdir/out.txt"; }}
        MAVLINK_MANAGEMENT_MODE="managed"
        MAVLINK_ANYWHERE_REPO_URL="https://github.com/demo/mavlink-anywhere.git"
        MAVLINK_ANYWHERE_REF="v9.9.9"
        MAVLINK_ANYWHERE_DIR="/opt/demo-mavlink"
        MAVLINK_ANYWHERE_DASHBOARD_LISTEN="127.0.0.1:9070"
        MAVLINK_ANYWHERE_SKIP_DASHBOARD="false"
        MAVLINK_ANYWHERE_REPO_URL_EXPLICIT="false"
        MAVLINK_ANYWHERE_REF_EXPLICIT="false"
        persist_mavlink_local_env
        grep -q '^set:MDS_MAVLINK_MANAGEMENT_MODE=managed$' "$tmpdir/out.txt"
        grep -q '^remove:MDS_MAVLINK_ANYWHERE_REPO_URL$' "$tmpdir/out.txt"
        grep -q '^remove:MDS_MAVLINK_ANYWHERE_REF$' "$tmpdir/out.txt"
        grep -q '^set:MDS_MAVLINK_ANYWHERE_INSTALL_DIR=/opt/demo-mavlink$' "$tmpdir/out.txt"
        grep -q '^set:MDS_MAVLINK_ANYWHERE_DASHBOARD_LISTEN=127.0.0.1:9070$' "$tmpdir/out.txt"
        grep -q '^set:MDS_MAVLINK_ANYWHERE_SKIP_DASHBOARD=false$' "$tmpdir/out.txt"
        ! grep -q '^set:MDS_MAVLINK_ANYWHERE_REPO_URL=' "$tmpdir/out.txt"
        ! grep -q '^set:MDS_MAVLINK_ANYWHERE_REF=' "$tmpdir/out.txt"
        """
    )

    assert result.returncode == 0, result.stderr


def test_reconcile_mavlink_runtime_uses_repo_ref_when_managed():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        mkdir -p "$repo_dir/tools"
        cp "{RECONCILE_MAVLINK_SCRIPT}" "$repo_dir/tools/reconcile_mavlink_runtime.sh"
        cp "{REPO_ROOT / 'tools' / 'load_deployment_profile.sh'}" "$repo_dir/tools/load_deployment_profile.sh"
        cat > "$repo_dir/deployment.defaults" <<'EOF'
MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE=managed
MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_URL_HTTPS=https://github.com/demo/mavlink-anywhere.git
MDS_DEFAULT_MAVLINK_ANYWHERE_REF=v9.9.9
MDS_DEFAULT_MAVLINK_ANYWHERE_INSTALL_DIR=TMPDIR_REPLACE/ma
MDS_DEFAULT_MAVLINK_ANYWHERE_DASHBOARD_LISTEN=0.0.0.0:9070
MDS_DEFAULT_MAVLINK_ANYWHERE_SKIP_DASHBOARD=false
EOF
        sed -i "s|TMPDIR_REPLACE|$tmpdir|g" "$repo_dir/deployment.defaults"
        config_dir="$tmpdir/etc-mds"
        mkdir -p "$config_dir"
        cat > "$config_dir/local.env" <<'EOF'
MDS_MAVLINK_MANAGEMENT_MODE=managed
EOF
        fakebin="$tmpdir/fakebin"
        mkdir -p "$fakebin"
        cat > "$fakebin/git" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" >> "$TMPDIR/git_args.txt"
if [[ "$1" == "clone" ]]; then
    target="${{@: -1}}"
    mkdir -p "$target/.git" "$target/lib"
    cat > "$target/install_mavlink_router.sh" <<'EOS'
#!/bin/bash
printf '%s\n' "$*" > "$TMPDIR/install_args.txt"
EOS
    chmod +x "$target/install_mavlink_router.sh"
    cat > "$target/configure_mavlink_router.sh" <<'EOS'
#!/bin/bash
printf '%s\n' "$*" > "$TMPDIR/configure_args.txt"
EOS
    chmod +x "$target/configure_mavlink_router.sh"
    cat > "$target/lib/dashboard.sh" <<'EOS'
#!/bin/bash
install_dashboard_binary() {{
    printf '%s\n' "$1" > "$TMPDIR/dashboard_version.txt"
}}
setup_dashboard_service() {{
    printf '%s\n' "$1" > "$TMPDIR/dashboard_listen.txt"
}}
EOS
fi
exit 0
EOF
        chmod +x "$fakebin/git"
        cat > "$fakebin/systemctl" <<'EOF'
#!/bin/sh
exit 0
EOF
        chmod +x "$fakebin/systemctl"
        cat > "$fakebin/mavlink-routerd" <<'EOF'
#!/bin/sh
exit 0
EOF
        chmod +x "$fakebin/mavlink-routerd"
        mkdir -p "$tmpdir/etc/mavlink-router"
        : > "$tmpdir/etc/mavlink-router/main.conf"
        TMPDIR="$tmpdir" PATH="$fakebin:$PATH" MDS_DEPLOYMENT_PROFILE_FILE="$repo_dir/deployment.defaults" MDS_LOCAL_ENV_FILE="$config_dir/local.env" MAVLINK_ROUTER_CONFIG="$tmpdir/etc/mavlink-router/main.conf" MDS_MAVLINK_STATE_DIR="$tmpdir/state" bash "$repo_dir/tools/reconcile_mavlink_runtime.sh" apply --force
        grep -q -- 'clone --depth 1 --branch v9.9.9 https://github.com/demo/mavlink-anywhere.git' "$tmpdir/git_args.txt"
        grep -q '^v9.9.9$' "$tmpdir/dashboard_version.txt"
        grep -q '^0.0.0.0:9070$' "$tmpdir/dashboard_listen.txt"
        """
    )

    assert result.returncode == 0, result.stderr


def test_reconcile_mavlink_runtime_warns_but_succeeds_without_router_config():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        mkdir -p "$repo_dir/tools"
        cp "{RECONCILE_MAVLINK_SCRIPT}" "$repo_dir/tools/reconcile_mavlink_runtime.sh"
        cp "{REPO_ROOT / 'tools' / 'load_deployment_profile.sh'}" "$repo_dir/tools/load_deployment_profile.sh"
        cat > "$repo_dir/deployment.defaults" <<'EOF'
MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE=managed
MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_URL_HTTPS=https://github.com/demo/mavlink-anywhere.git
MDS_DEFAULT_MAVLINK_ANYWHERE_REF=v9.9.9
MDS_DEFAULT_MAVLINK_ANYWHERE_INSTALL_DIR=TMPDIR_REPLACE/ma
MDS_DEFAULT_MAVLINK_ANYWHERE_DASHBOARD_LISTEN=127.0.0.1:9070
MDS_DEFAULT_MAVLINK_ANYWHERE_SKIP_DASHBOARD=false
EOF
        sed -i "s|TMPDIR_REPLACE|$tmpdir|g" "$repo_dir/deployment.defaults"
        config_dir="$tmpdir/etc-mds"
        mkdir -p "$config_dir"
        cat > "$config_dir/local.env" <<'EOF'
MDS_MAVLINK_MANAGEMENT_MODE=managed
EOF
        fakebin="$tmpdir/fakebin"
        mkdir -p "$fakebin"
        cat > "$fakebin/git" <<'EOF'
#!/bin/bash
if [[ "$1" == "clone" ]]; then
    target="${{@: -1}}"
    mkdir -p "$target/.git" "$target/lib"
    cat > "$target/lib/dashboard.sh" <<'EOS'
#!/bin/bash
install_dashboard_binary() {{ :; }}
setup_dashboard_service() {{ :; }}
EOS
    chmod +x "$target/lib/dashboard.sh"
fi
exit 0
EOF
        chmod +x "$fakebin/git"
        cat > "$fakebin/systemctl" <<'EOF'
#!/bin/sh
exit 0
EOF
        chmod +x "$fakebin/systemctl"
        cat > "$fakebin/mavlink-routerd" <<'EOF'
#!/bin/sh
exit 0
EOF
        chmod +x "$fakebin/mavlink-routerd"
        TMPDIR="$tmpdir" PATH="$fakebin:$PATH" MDS_DEPLOYMENT_PROFILE_FILE="$repo_dir/deployment.defaults" MDS_LOCAL_ENV_FILE="$config_dir/local.env" MAVLINK_ROUTER_CONFIG="$tmpdir/etc/mavlink-router/main.conf" MDS_MAVLINK_STATE_DIR="$tmpdir/state" bash "$repo_dir/tools/reconcile_mavlink_runtime.sh" apply --force >/tmp/reconcile.out 2>/tmp/reconcile.err
        grep -q 'missing' /tmp/reconcile.err
        test -f "$tmpdir/state/mavlink_anywhere_runtime.sha256"
        """
    )

    assert result.returncode == 0, result.stderr


def test_runtime_git_sync_reconciles_optional_connectivity_backend():
    git_sync_text = GIT_SYNC_SCRIPT.read_text(encoding="utf-8")

    assert "check_connectivity_updates()" in git_sync_text
    assert 'sudo "${reconcile_script}" apply --quiet' in git_sync_text
    assert '"wifi-manager"' not in git_sync_text


def test_runtime_git_sync_reconciles_managed_mavlink_runtime():
    git_sync_text = GIT_SYNC_SCRIPT.read_text(encoding="utf-8")

    assert "check_mavlink_runtime_updates()" in git_sync_text
    assert '/tools/reconcile_mavlink_runtime.sh' in git_sync_text
    assert "MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE" in git_sync_text


def test_git_sync_reexecs_updated_sync_script_once_to_apply_new_logic():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        home_dir="$tmpdir/home/companion"
        mkdir -p "$repo_dir/tools" "$home_dir/logs"

        cat > "$repo_dir/tools/update_repo_ssh.sh" <<'EOF'
#!/bin/bash
printf 'reexec_count=%s\\n' "${{MDS_GIT_SYNC_REEXEC_COUNT:-}}"
printf 'previous_head=%s\\n' "${{MDS_GIT_SYNC_PREVIOUS_HEAD:-}}"
EOF
        chmod +x "$repo_dir/tools/update_repo_ssh.sh"

        export HOME="$home_dir"
        export USER="companion"
        export REPO_USER="companion"
        export REPO_DIR="$repo_dir"

        source "{GIT_SYNC_SCRIPT}"
        git() {{
            if [[ "$1" == "-C" && "$2" == "$REPO_DIR" && "$3" == "diff" && "$4" == "--name-only" ]]; then
                printf 'tools/update_repo_ssh.sh\\n'
                return 0
            fi
            command git "$@"
        }}
        maybe_reexec_updated_sync_script "old123" "new456"
        """
    )

    assert result.returncode == 0, result.stderr
    assert "reexec_count=1" in result.stdout
    assert "previous_head=old123" in result.stdout


def test_git_sync_self_reexec_records_next_invocation_after_max_attempt():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        home_dir="$tmpdir/home/companion"
        mkdir -p "$repo_dir/tools" "$home_dir/logs"

        cat > "$repo_dir/tools/update_repo_ssh.sh" <<'EOF'
#!/bin/bash
touch "$REEXEC_MARKER"
EOF
        chmod +x "$repo_dir/tools/update_repo_ssh.sh"

        export HOME="$home_dir"
        export USER="companion"
        export REPO_USER="companion"
        export REPO_DIR="$repo_dir"
        export REEXEC_MARKER="$tmpdir/reexec-marker"
        export MDS_GIT_SYNC_REEXEC_COUNT=1

        source "{GIT_SYNC_SCRIPT}"
        git() {{
            if [[ "$1" == "-C" && "$2" == "$REPO_DIR" && "$3" == "diff" && "$4" == "--name-only" ]]; then
                printf 'tools/update_repo_ssh.sh\\n'
                return 0
            fi
            command git "$@"
        }}
        maybe_reexec_updated_sync_script "old123" "new456"
        [[ ! -f "$REEXEC_MARKER" ]]
        printf '%s\\n' "${{DEFERRED_UNIT_ACTIONS[@]}}" | grep -qx 'git_sync_mds.service:next_invocation'
        """
    )

    assert result.returncode == 0, result.stderr


def test_post_sync_validation_rejects_invalid_shell_helper_and_rolls_back():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        mkdir -p "$repo_dir/tools" "$tmpdir/home/logs"
        cp "{GIT_SYNC_SCRIPT}" "$repo_dir/tools/update_repo_ssh.sh"
        git -C "$repo_dir" init -q
        git -C "$repo_dir" config user.email test@example.com
        git -C "$repo_dir" config user.name test
        cat > "$repo_dir/tools/reconcile_mavlink_runtime.sh" <<'EOF'
#!/bin/bash
echo ok
EOF
        chmod +x "$repo_dir/tools/reconcile_mavlink_runtime.sh"
        git -C "$repo_dir" add tools/reconcile_mavlink_runtime.sh
        git -C "$repo_dir" commit -q -m "baseline"
        old_head="$(git -C "$repo_dir" rev-parse HEAD)"
        cat > "$repo_dir/tools/reconcile_mavlink_runtime.sh" <<'EOF'
#!/bin/bash
if then
EOF
        git -C "$repo_dir" add tools/reconcile_mavlink_runtime.sh
        git -C "$repo_dir" commit -q -m "broken helper"
        new_head="$(git -C "$repo_dir" rev-parse HEAD)"
        HOME="$tmpdir/home"
        REPO_DIR="$repo_dir"
        source "{GIT_SYNC_SCRIPT}"
        ! preflight_validate_post_sync_runtime_changes "$old_head" "$new_head"
        git -C "$repo_dir" reset --hard "$new_head" >/dev/null
        rollback_repository_to_previous_head "$old_head" test
        [[ "$(git -C "$repo_dir" rev-parse HEAD)" == "$old_head" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_post_sync_validation_rejects_invalid_runtime_python_file():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        mkdir -p "$repo_dir/src" "$tmpdir/home/logs"
        cp "{GIT_SYNC_SCRIPT}" "$repo_dir/tools_update_repo_ssh.sh"
        git -C "$repo_dir" init -q
        git -C "$repo_dir" config user.email test@example.com
        git -C "$repo_dir" config user.name test
        cat > "$repo_dir/src/runtime_check.py" <<'EOF'
value = 1
EOF
        git -C "$repo_dir" add src/runtime_check.py
        git -C "$repo_dir" commit -q -m "baseline"
        old_head="$(git -C "$repo_dir" rev-parse HEAD)"
        cat > "$repo_dir/src/runtime_check.py" <<'EOF'
def broken(:
    pass
EOF
        git -C "$repo_dir" add src/runtime_check.py
        git -C "$repo_dir" commit -q -m "broken python"
        new_head="$(git -C "$repo_dir" rev-parse HEAD)"
        HOME="$tmpdir/home"
        REPO_DIR="$repo_dir"
        source "{GIT_SYNC_SCRIPT}"
        ! preflight_validate_post_sync_runtime_changes "$old_head" "$new_head"
        """
    )

    assert result.returncode == 0, result.stderr


def test_post_sync_validation_rejects_invalid_rendered_service_template():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        mkdir -p "$repo_dir/tools" "$tmpdir/home/logs"
        cp "{GIT_SYNC_SCRIPT}" "$repo_dir/tools/update_repo_ssh.sh"
        git -C "$repo_dir" init -q
        git -C "$repo_dir" config user.email test@example.com
        git -C "$repo_dir" config user.name test
        cat > "$repo_dir/tools/coordinator.service" <<'EOF'
[Unit]
Description=Coordinator
[Service]
ExecStart=python3 coordinator.py
EOF
        git -C "$repo_dir" add tools/coordinator.service
        git -C "$repo_dir" commit -q -m "baseline"
        old_head="$(git -C "$repo_dir" rev-parse HEAD)"
        cat > "$repo_dir/tools/coordinator.service" <<'EOF'
[Unit]
Description=Coordinator
[Service]
ExecStart=
EOF
        git -C "$repo_dir" add tools/coordinator.service
        git -C "$repo_dir" commit -q -m "broken service"
        new_head="$(git -C "$repo_dir" rev-parse HEAD)"
        HOME="$tmpdir/home"
        REPO_DIR="$repo_dir"
        MDS_USER=droneshow
        MDS_HOME="$tmpdir/home"
        MDS_INSTALL_DIR="$repo_dir"
        source "{GIT_SYNC_SCRIPT}"
        ! preflight_validate_post_sync_runtime_changes "$old_head" "$new_head"
        """
    )

    assert result.returncode == 0, result.stderr


def test_exit_with_failure_result_can_preserve_noncritical_led_state():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        mkdir -p "$tmpdir/home/logs" "$tmpdir/repo/.git"
        HOME="$tmpdir/home"
        REPO_DIR="$tmpdir/repo"
        source "{GIT_SYNC_SCRIPT}"
        set_led_status() {{
            printf '%s\\n' "$1" > "$tmpdir/led_state"
        }}
        cleanup_on_exit() {{
            :
        }}
        set +e
        output="$(
            exit_with_failure_result "POST-SYNC-VALIDATION" "rolled back safely" 1 "GIT_FAILED_CONTINUING"
        )"
        status=$?
        [[ $status -eq 1 ]]
        grep -qx "GIT_FAILED_CONTINUING" "$tmpdir/led_state"
        grep -q '"success":false' <<<"$output"
        grep -q '"error":"POST-SYNC-VALIDATION"' <<<"$output"
        grep -q '"message":"rolled back safely"' <<<"$output"
        """
    )

    assert result.returncode == 0, result.stderr


def test_services_lib_core_service_order_excludes_embedded_wifi_manager():
    services_text = SERVICES_LIB.read_text(encoding="utf-8")

    assert '"wifi-manager.service"' not in services_text
    assert '/bin/systemctl restart smart-wifi-manager' in services_text
    assert '/tools/reconcile_connectivity.sh' in services_text


def test_configure_gcs_env_persists_private_https_token_file():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        GCS_CONFIG_FILE="$tmpdir/gcs.env"
        GCS_INSTALL_DIR="/opt/mds"
        GCS_DEFAULT_REPO_SSH="git@github.com:alireza787b/mavsdk_drone_show.git"
        GCS_DEFAULT_BRANCH="main-candidate"
        MDS_GIT_AUTH_TOKEN_FILE="/root/.mds_git_read_token"
        log_step() {{ :; }}
        log_info() {{ :; }}
        log_success() {{ :; }}
        backup_file() {{ :; }}
        confirm() {{ return 1; }}
        is_dry_run() {{ return 1; }}
        gcs_state_get_value() {{
            case "$1" in
                repo_url) echo "https://github.com/example-org/private-mds.git" ;;
                repo_branch) echo "customer-demo" ;;
                access_method) echo "https" ;;
                *) echo "$2" ;;
            esac
        }}
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_common.sh'}"
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_env_config.sh'}"
        configure_gcs_env
        grep -q '^MDS_REPO_URL=https://github.com/example-org/private-mds.git$' "$GCS_CONFIG_FILE"
        grep -q '^MDS_BRANCH=customer-demo$' "$GCS_CONFIG_FILE"
        grep -q '^MDS_GIT_AUTO_PUSH=false$' "$GCS_CONFIG_FILE"
        grep -q '^MDS_GIT_AUTH_TOKEN_FILE=/root/.mds_git_read_token$' "$GCS_CONFIG_FILE"
        """
    )

    assert result.returncode == 0, result.stderr


def test_configure_gcs_env_persists_private_ssh_key_file():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        GCS_CONFIG_FILE="$tmpdir/gcs.env"
        GCS_INSTALL_DIR="/opt/mds"
        GCS_DEFAULT_REPO_SSH="git@github.com:alireza787b/mavsdk_drone_show.git"
        GCS_DEFAULT_BRANCH="main-candidate"
        MDS_GIT_SSH_KEY_FILE="/root/.ssh/customer_gcs_write_key"
        log_step() {{ :; }}
        log_info() {{ :; }}
        log_success() {{ :; }}
        backup_file() {{ :; }}
        confirm() {{ return 1; }}
        is_dry_run() {{ return 1; }}
        gcs_state_get_value() {{
            case "$1" in
                repo_url) echo "git@github.com:example-org/private-mds.git" ;;
                repo_branch) echo "customer-demo" ;;
                access_method) echo "ssh" ;;
                *) echo "$2" ;;
            esac
        }}
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_common.sh'}"
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_env_config.sh'}"
        configure_gcs_env
        grep -q '^MDS_REPO_URL=git@github.com:example-org/private-mds.git$' "$GCS_CONFIG_FILE"
        grep -q '^MDS_BRANCH=customer-demo$' "$GCS_CONFIG_FILE"
        grep -q '^MDS_GIT_AUTO_PUSH=true$' "$GCS_CONFIG_FILE"
        grep -q '^MDS_GIT_SSH_KEY_FILE=/root/.ssh/customer_gcs_write_key$' "$GCS_CONFIG_FILE"
        """
    )

    assert result.returncode == 0, result.stderr


def test_gcs_common_phase_list_includes_services_before_verify():
    common_text = (REPO_ROOT / "tools" / "mds_gcs_init_lib" / "gcs_common.sh").read_text(encoding="utf-8")

    services_index = common_text.index('"services"')
    verify_index = common_text.index('"verify"')

    assert services_index < verify_index


def test_gcs_init_help_mentions_services_phase_and_skip_flag():
    result = run_bash(
        f"""
        bash "{REPO_ROOT / 'tools' / 'mds_gcs_init.sh'}" --help > /tmp/gcs_init_help.txt
        grep -q -- "--skip-services" /tmp/gcs_init_help.txt
        grep -q "services     - git_sync_mds.service reconciliation" /tmp/gcs_init_help.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_run_gcs_services_phase_installs_git_sync_service_with_runtime_paths():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        install_dir="$tmpdir/mds"
        mkdir -p "$install_dir/tools/git_sync_mds"
        cat > "$install_dir/tools/git_sync_mds/install_git_sync_mds.sh" <<'EOF'
#!/bin/bash
printf 'user=%s\\n' "$1" > "$TMPDIR/install.out"
printf 'MDS_USER=%s\\n' "${{MDS_USER}}" >> "$TMPDIR/install.out"
printf 'MDS_HOME=%s\\n' "${{MDS_HOME}}" >> "$TMPDIR/install.out"
printf 'MDS_INSTALL_DIR=%s\\n' "${{MDS_INSTALL_DIR}}" >> "$TMPDIR/install.out"
EOF
        chmod +x "$install_dir/tools/git_sync_mds/install_git_sync_mds.sh"
        export TMPDIR="$tmpdir"
        GCS_INSTALL_DIR="$install_dir"
        MDS_GCS_RUNTIME_USER="root"
        MDS_GCS_RUNTIME_HOME="/root"
        SKIP_SERVICES="false"
        log_step() {{ :; }}
        log_info() {{ :; }}
        log_success() {{ :; }}
        log_error() {{ echo "$1" >&2; }}
        is_dry_run() {{ return 1; }}
        print_phase_header() {{ :; }}
        print_section() {{ :; }}
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_common.sh'}"
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_services.sh'}"
        run_services_phase
        grep -q '^user=root$' "$tmpdir/install.out"
        grep -q '^MDS_USER=root$' "$tmpdir/install.out"
        grep -q '^MDS_HOME=/root$' "$tmpdir/install.out"
        grep -q "^MDS_INSTALL_DIR=$install_dir$" "$tmpdir/install.out"
        """
    )

    assert result.returncode == 0, result.stderr


def test_verify_gcs_git_sync_service_reports_enabled_and_active():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        bin_dir="$tmpdir/bin"
        mkdir -p "$bin_dir"
        cat > "$bin_dir/systemctl" <<'EOF'
#!/bin/bash
case "$*" in
  "is-enabled --quiet git_sync_mds.service") exit 0 ;;
  "is-active git_sync_mds.service") printf 'active\\n'; exit 0 ;;
esac
exit 1
EOF
        chmod +x "$bin_dir/systemctl"
        PATH="$bin_dir:$PATH"
        SKIP_SERVICES="false"
        log_step() {{ :; }}
        log_warn() {{ :; }}
        log_success() {{ :; }}
        is_dry_run() {{ return 1; }}
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_common.sh'}"
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_verify.sh'}"
        verify_git_sync_service > "$tmpdir/verify.out"
        grep -q '^    Enabled: ' "$tmpdir/verify.out"
        grep -q '^    Active:  ' "$tmpdir/verify.out"
        grep -q 'enabled' "$tmpdir/verify.out"
        grep -q 'active' "$tmpdir/verify.out"
        """
    )

    assert result.returncode == 0, result.stderr


def test_install_git_sync_service_restarts_active_oneshot_unit():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        install_dir="$tmpdir/mds"
        bin_dir="$tmpdir/bin"
        systemd_dir="$tmpdir/systemd"
        mkdir -p "$install_dir/tools/git_sync_mds" "$install_dir/tools" "$bin_dir" "$systemd_dir"
        cp "{REPO_ROOT / 'tools' / 'git_sync_mds' / 'git_sync_mds.service'}" "$install_dir/tools/git_sync_mds/git_sync_mds.service"
        printf '#!/bin/bash\\nexit 0\\n' > "$install_dir/tools/update_repo_ssh.sh"
        chmod +x "$install_dir/tools/update_repo_ssh.sh"

        cat > "$bin_dir/systemctl" <<'EOF'
#!/bin/bash
printf '%s\\n' "$*" >> "$TMPDIR/systemctl.log"
case "$*" in
  "daemon-reload") exit 0 ;;
  "enable git_sync_mds.service") exit 0 ;;
  "restart git_sync_mds.service") exit 0 ;;
  "status git_sync_mds.service --no-pager") exit 0 ;;
esac
exit 1
EOF
        chmod +x "$bin_dir/systemctl"

        PATH="$bin_dir:$PATH" \
        TMPDIR="$tmpdir" \
        MDS_HOME="/root" \
        MDS_INSTALL_DIR="$install_dir" \
        MDS_SYSTEMD_DIR="$systemd_dir" \
        bash "{REPO_ROOT / 'tools' / 'git_sync_mds' / 'install_git_sync_mds.sh'}" root

        grep -q '^daemon-reload$' "$tmpdir/systemctl.log"
        grep -q '^enable git_sync_mds.service$' "$tmpdir/systemctl.log"
        grep -q '^restart git_sync_mds.service$' "$tmpdir/systemctl.log"
        ! grep -q '^start git_sync_mds.service$' "$tmpdir/systemctl.log"
        """
    )

    assert result.returncode == 0, result.stderr


def test_identity_manifest_uses_live_netbird_probe_when_state_is_empty():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        MDS_CONFIG_DIR="$tmpdir"
        MDS_LOCAL_ENV="$tmpdir/local.env"
        MDS_NODE_IDENTITY_FILE="$tmpdir/node_identity.json"
        MDS_VERSION="4.5.0"
        DRONE_ID=101
        REPO_URL="git@github.com:example-org/private-mds.git"
        BRANCH="main-candidate"
        MAVLINK_INPUT_TYPE="uart"
        log_warn() {{ :; }}
        log_success() {{ :; }}
        is_dry_run() {{ return 1; }}
        state_get_value() {{ echo ""; }}
        state_set_value() {{ :; }}
        get_or_create_node_uuid() {{ echo "uuid-101"; }}
        get_local_env_value() {{ echo ""; }}
        get_netbird_primary_ip() {{ echo "100.64.10.101"; }}
        detect_network_interface() {{ echo ""; }}
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'identity.sh'}"
        write_node_identity_manifest 101 identity_configured
        jq -e '.netbird_enabled == true and .network_mode == "netbird" and .primary_control_ip == "100.64.10.101"' "$MDS_NODE_IDENTITY_FILE" >/dev/null
        """
    )

    assert result.returncode == 0, result.stderr


def test_verify_hw_id_stays_safe_under_nounset():
    result = run_bash(
        f"""
        set -u
        tmpdir="$(mktemp -d)"
        MDS_CONFIG_DIR="$tmpdir/etc-mds"
        MDS_LOCAL_ENV="$tmpdir/etc-mds/local.env"
        DRONE_ID=101
        mkdir -p "$MDS_CONFIG_DIR"
        printf 'MDS_HW_ID=101\\n' > "$MDS_LOCAL_ENV"
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'verify.sh'}"
        verify_hw_id
        [[ "$(verify_get_result hw_id)" == "PASS:Drone 101" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_sitl_launchers_use_canonical_mds_hw_id_without_runtime_hwid_files():
    create_text = (REPO_ROOT / "multiple_sitl" / "create_dockers.sh").read_text(encoding="utf-8")
    startup_text = (REPO_ROOT / "multiple_sitl" / "startup_sitl.sh").read_text(encoding="utf-8")

    assert '-e "MDS_HW_ID=${drone_id}"' in create_text
    assert "resolve_runtime_hwid()" in startup_text
    assert "MDS_HW_ID is required for SITL container startup." in startup_text
    assert "wait_for_hwid()" not in startup_text
    assert "cp '$RUNTIME_FILES_CONTAINER'/*.hwID" not in create_text


def test_verify_netbird_parses_detail_output_and_extracts_primary_ip():
    result = run_bash(
        f"""
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'verify.sh'}"
        command_exists() {{ [[ "$1" == "netbird" ]]; }}
        netbird() {{
            cat <<'EOF'
Management: Connected to https://api.netbird.io:443
FQDN: node-101.netbird.example
NetBird IP: 100.64.10.101/16
EOF
        }}
        verify_netbird
        [[ "$(verify_get_result netbird)" == "PASS:Connected (100.64.10.101)" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_generate_summary_report_lists_component_rows():
    result = run_bash(
        f"""
        IFS=$'\\n\\t'
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'verify.sh'}"
        MDS_VERSION="4.5.0"
        verify_set_result hw_id "PASS:Drone 101"
        output="$(generate_summary_report)"
        [[ "$output" == *"hw_id"* ]]
        [[ "$output" == *"Drone 101"* ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_join_ntp_servers_is_stable_when_ifs_is_newline_tab():
    result = run_bash(
        f"""
        IFS=$'\\n\\t'
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'network.sh'}"
        [[ "$(join_ntp_servers)" == "0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org 3.pool.ntp.org" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_update_service_renders_coordinator_template_for_custom_runtime_paths():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        systemd_dir="$tmpdir/systemd"
        bin_dir="$tmpdir/bin"
        mkdir -p "$repo_dir/tools" "$systemd_dir" "$bin_dir" "$tmpdir/home/companion"
        cp "{REPO_ROOT / 'tools' / 'coordinator.service'}" "$repo_dir/tools/coordinator.service"

        cat > "$bin_dir/sudo" <<'EOF'
#!/bin/bash
exec "$@"
EOF
        cat > "$bin_dir/systemctl" <<'EOF'
#!/bin/bash
printf '%s\\n' "$*" >> "$TMPDIR/systemctl.log"
EOF
        chmod +x "$bin_dir/sudo" "$bin_dir/systemctl"

        PATH="$bin_dir:$PATH" \
        TMPDIR="$tmpdir" \
        MDS_USER="companion" \
        MDS_HOME="$tmpdir/home/companion" \
        MDS_INSTALL_DIR="$repo_dir" \
        MDS_SYSTEMD_DIR="$systemd_dir" \
        bash "{REPO_ROOT / 'tools' / 'update_service.sh'}"

        service_file="$systemd_dir/coordinator.service"
        [[ -f "$service_file" ]]
        grep -q "^User=companion$" "$service_file"
        grep -q "^Group=companion$" "$service_file"
        grep -q "^WorkingDirectory=$repo_dir$" "$service_file"
        grep -q "^ExecStart=$repo_dir/venv/bin/python $repo_dir/coordinator.py$" "$service_file"
        ! grep -q "__MDS_" "$service_file"
        grep -q "daemon-reload" "$tmpdir/systemctl.log"
        grep -q "restart coordinator.service" "$tmpdir/systemctl.log"
        """
    )

    assert result.returncode == 0, result.stderr


def test_check_and_update_service_wraps_safe_renderer():
    result = run_bash(
        f"""
        tmpdir="$(mktemp -d)"
        repo_dir="$tmpdir/repo"
        systemd_dir="$tmpdir/systemd"
        bin_dir="$tmpdir/bin"
        mkdir -p "$repo_dir/tools" "$systemd_dir" "$bin_dir" "$tmpdir/home/companion"
        cp "{REPO_ROOT / 'tools' / 'coordinator.service'}" "$repo_dir/tools/coordinator.service"

        cat > "$bin_dir/sudo" <<'EOF'
#!/bin/bash
exec "$@"
EOF
        cat > "$bin_dir/systemctl" <<'EOF'
#!/bin/bash
printf '%s\\n' "$*" >> "$TMPDIR/systemctl.log"
EOF
        chmod +x "$bin_dir/sudo" "$bin_dir/systemctl"

        PATH="$bin_dir:$PATH" \
        TMPDIR="$tmpdir" \
        MDS_USER="companion" \
        MDS_HOME="$tmpdir/home/companion" \
        MDS_INSTALL_DIR="$repo_dir" \
        MDS_SYSTEMD_DIR="$systemd_dir" \
        bash "{REPO_ROOT / 'tools' / 'check_and_update_service.sh'}"

        service_file="$systemd_dir/coordinator.service"
        [[ -f "$service_file" ]]
        grep -q "^User=companion$" "$service_file"
        ! grep -q "__MDS_" "$service_file"
        """
    )

    assert result.returncode == 0, result.stderr

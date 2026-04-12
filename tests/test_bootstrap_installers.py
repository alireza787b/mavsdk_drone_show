import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NODE_INSTALLER = REPO_ROOT / "tools" / "install_mds_node.sh"
GCS_INSTALLER = REPO_ROOT / "tools" / "install_gcs.sh"
COMMON_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "common.sh"
NETWORK_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "network.sh"
REPO_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "repo.sh"
MAVLINK_SETUP_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "mavlink_setup.sh"
MAVSDK_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "mavsdk.sh"
SERVICES_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "services.sh"
PYTHON_ENV_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "python_env.sh"


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


def test_node_bootstrap_wrapper_help_mentions_private_https_token_file():
    result = run_bash(
        f"""
        cat "{NODE_INSTALLER}" | bash -s -- --help >/tmp/node_wrapper_help.txt
        grep -q -- "--git-auth-token-file" /tmp/node_wrapper_help.txt
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
        grep -q '/tmp/mds_gcs_git_askpass.sh|0|' /tmp/gcs_wrapper_auth.txt
        grep -q "$token_file" /tmp/gcs_wrapper_auth.txt
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
        grep -q '/tmp/mds_node_git_askpass.sh|0|' /tmp/node_wrapper_auth.txt
        grep -q "$token_file" /tmp/node_wrapper_auth.txt
        """
    )

    assert result.returncode == 0, result.stderr


def test_netbird_detail_parsers_extract_primary_identity_fields():
    result = run_bash(
        f"""
        source "{COMMON_LIB}"
        source "{NETWORK_LIB}"
        get_netbird_detail_output() {{
            cat <<'EOF'
Management: Connected to https://api.netbird.io:443
FQDN: px4-cm4-01.netbird.cloud
NetBird IP: 100.82.72.33/16
EOF
        }}
        [[ "$(get_netbird_primary_ip)" == "100.82.72.33" ]]
        [[ "$(get_netbird_management_url)" == "https://api.netbird.io:443" ]]
        [[ "$(get_netbird_fqdn)" == "px4-cm4-01.netbird.cloud" ]]
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
        GCS_IP="100.82.107.61"
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
        log_step() {{ :; }}
        log_success() {{ :; }}
        is_dry_run() {{ return 1; }}
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'identity.sh'}"
        setup_local_env 101 100.82.107.61 git@github.com:demo/customer.git main http://100.82.107.61:5000
        grep -q '^MDS_HW_ID=101$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_GCS_IP=100.82.107.61$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_GCS_API_BASE_URL=http://100.82.107.61:5000$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_REPO_URL=git@github.com:demo/customer.git$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_BRANCH=main$' "$MDS_LOCAL_ENV"
        grep -q '^MDS_GIT_AUTH_TOKEN_FILE=/home/droneshow/.mds_git_read_token$' "$MDS_LOCAL_ENV"
        ! grep -q '^MDS_HW_ID=.*#' "$MDS_LOCAL_ENV"
        """
    )

    assert result.returncode == 0, result.stderr


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
                repo_url) echo "https://github.com/demo/customer-mds.git" ;;
                repo_branch) echo "customer-demo" ;;
                access_method) echo "https" ;;
                *) echo "$2" ;;
            esac
        }}
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_common.sh'}"
        source "{REPO_ROOT / 'tools' / 'mds_gcs_init_lib' / 'gcs_env_config.sh'}"
        configure_gcs_env
        grep -q '^MDS_REPO_URL=https://github.com/demo/customer-mds.git$' "$GCS_CONFIG_FILE"
        grep -q '^MDS_BRANCH=customer-demo$' "$GCS_CONFIG_FILE"
        grep -q '^MDS_GIT_AUTO_PUSH=false$' "$GCS_CONFIG_FILE"
        grep -q '^MDS_GIT_AUTH_TOKEN_FILE=/root/.mds_git_read_token$' "$GCS_CONFIG_FILE"
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
        REPO_URL="git@github.com:demo/customer.git"
        BRANCH="main-candidate"
        MAVLINK_INPUT_TYPE="uart"
        log_warn() {{ :; }}
        log_success() {{ :; }}
        is_dry_run() {{ return 1; }}
        state_get_value() {{ echo ""; }}
        state_set_value() {{ :; }}
        get_or_create_node_uuid() {{ echo "uuid-101"; }}
        get_local_env_value() {{ echo ""; }}
        get_netbird_primary_ip() {{ echo "100.82.72.33"; }}
        detect_network_interface() {{ echo ""; }}
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'identity.sh'}"
        write_node_identity_manifest 101 identity_configured
        jq -e '.netbird_enabled == true and .network_mode == "netbird" and .primary_control_ip == "100.82.72.33"' "$MDS_NODE_IDENTITY_FILE" >/dev/null
        """
    )

    assert result.returncode == 0, result.stderr


def test_verify_hw_id_stays_safe_under_nounset():
    result = run_bash(
        f"""
        set -u
        tmpdir="$(mktemp -d)"
        MDS_INSTALL_DIR="$tmpdir"
        DRONE_ID=101
        touch "$tmpdir/101.hwID"
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'verify.sh'}"
        verify_hw_id
        [[ "$(verify_get_result hw_id)" == "PASS:Drone 101" ]]
        """
    )

    assert result.returncode == 0, result.stderr


def test_verify_netbird_parses_detail_output_and_extracts_primary_ip():
    result = run_bash(
        f"""
        source "{REPO_ROOT / 'tools' / 'mds_init_lib' / 'verify.sh'}"
        command_exists() {{ [[ "$1" == "netbird" ]]; }}
        netbird() {{
            cat <<'EOF'
Management: Connected to https://api.netbird.io:443
FQDN: px4-cm4-01.netbird.cloud
NetBird IP: 100.82.72.33/16
EOF
        }}
        verify_netbird
        [[ "$(verify_get_result netbird)" == "PASS:Connected (100.82.72.33)" ]]
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

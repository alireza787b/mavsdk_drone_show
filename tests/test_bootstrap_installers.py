import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NODE_INSTALLER = REPO_ROOT / "tools" / "install_mds_node.sh"
GCS_INSTALLER = REPO_ROOT / "tools" / "install_gcs.sh"
COMMON_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "common.sh"
NETWORK_LIB = REPO_ROOT / "tools" / "mds_init_lib" / "network.sh"


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

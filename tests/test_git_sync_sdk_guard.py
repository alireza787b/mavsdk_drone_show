"""Unattended SDK admission is read-only; a breaking tuple needs maintenance."""
import os
from pathlib import Path
import shlex
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/update_repo_ssh.sh'


def run_shell(repo, body, **extra):
    env = {key: value for key, value in os.environ.items() if not key.startswith('MDS_')}
    env.update(extra)
    result = subprocess.run(['bash', '-c', f'''
        source {shlex.quote(str(SCRIPT))}
        REPO_DIR={shlex.quote(str(repo))}
        RESOLVED_HOME={shlex.quote(str(repo / 'state-home'))}
        log_info() {{ :; }}; log_warn() {{ :; }}; log_debug() {{ :; }}
        {body}
    '''], env=env, capture_output=True, text=True, timeout=15)
    return result


@pytest.fixture
def deployment(tmp_path):
    repo = tmp_path / 'deployment'
    (repo / 'config').mkdir(parents=True)
    (repo / 'config/mavsdk-runtime.json').write_text('{}')
    (repo / 'tools').mkdir()
    (repo / 'tools/mavsdk_runtime.py').write_text('# interpreter fixture handles requests\n')
    (repo / 'requirements.txt').write_text('example==1\n')
    return repo


def make_python(directory, *, compatible=True):
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / 'python3'
    executable.write_text('#!/bin/bash\n'
        'printf "%s\\n" "$*" >> "${0%/*}/calls"\n'
        f'if [[ "${{*: -1}}" == python-check ]]; then exit {0 if compatible else 1}; fi\n'
        'exit 0\n')
    executable.chmod(0o755)
    return executable


def test_default_matching_environment_is_read_only(deployment):
    python = make_python(deployment / 'venv/bin')
    result = run_shell(deployment, 'preflight_validate_mavsdk_sync_environment')
    assert result.returncode == 0, result.stderr
    calls = python.with_name('calls').read_text().splitlines()
    assert len(calls) == 1 and calls[0].endswith(' python-check')


def test_mismatching_pair_never_tries_pip(deployment):
    python = make_python(deployment / 'venv/bin', compatible=False)
    result = run_shell(deployment, '''
        ! preflight_validate_mavsdk_sync_environment
        [[ "$MAVSDK_RUNTIME_STATUS" == maintenance_required ]]
        ! check_requirements_update
        [[ "$REQUIREMENTS_UPDATE_STATUS" == maintenance_required ]]
    ''')
    assert result.returncode == 0, result.stderr
    assert all(line.endswith(' python-check') for line in python.with_name('calls').read_text().splitlines())


def test_explicit_python_wins_over_venv(deployment):
    selected = make_python(deployment / 'selected/bin')
    ignored = make_python(deployment / 'ignored/bin', compatible=False)
    result = run_shell(deployment, 'preflight_validate_mavsdk_sync_environment',
                       MDS_PYTHON_BIN=str(selected), MDS_VENV_PATH=str(ignored.parent.parent))
    assert result.returncode == 0, result.stderr
    assert selected.with_name('calls').exists() and not ignored.with_name('calls').exists()


def test_explicit_venv_used_for_guard_and_pip(deployment):
    selected = make_python(deployment / 'external/bin')
    ignored = make_python(deployment / 'venv/bin', compatible=False)
    marker = deployment / 'state-home/.mds/requirements.sha256'
    marker.parent.mkdir(parents=True)
    marker.write_text('old\n')
    result = run_shell(deployment, '''
        set_led_status() { :; }; mark_coordinator_restart_needed() { :; }
        preflight_validate_mavsdk_sync_environment
        check_requirements_update
        [[ "$REQUIREMENTS_UPDATE_STATUS" == updated ]]
    ''', MDS_VENV_PATH=str(selected.parent.parent))
    assert result.returncode == 0, result.stderr
    assert '-m pip install' in selected.with_name('calls').read_text()
    assert not ignored.with_name('calls').exists()


@pytest.mark.parametrize('selection', ['MDS_PYTHON_BIN', 'MDS_VENV_PATH'])
def test_invalid_explicit_selection_never_falls_back(deployment, selection):
    ignored = make_python(deployment / 'venv/bin')
    result = run_shell(deployment, '''
        ! preflight_validate_mavsdk_sync_environment
        [[ "$MAVSDK_RUNTIME_STATUS" == maintenance_required ]]
    ''', **{selection: str(deployment / 'absent')})
    assert result.returncode == 0, result.stderr
    assert not ignored.with_name('calls').exists()


def test_source_only_bootstrap_defers_environment_creation(deployment):
    result = run_shell(deployment, '''
        preflight_validate_mavsdk_sync_environment
        [[ "$MAVSDK_RUNTIME_STATUS" == bootstrap_pending ]]
        check_requirements_update
        [[ "$REQUIREMENTS_UPDATE_STATUS" == bootstrap_pending ]]
    ''')
    assert result.returncode == 0, result.stderr
    assert not (deployment / 'state-home/.mds/requirements.sha256').exists()


def test_existing_binary_without_environment_is_not_fresh_bootstrap(deployment):
    (deployment / 'mavsdk_server').write_bytes(b'known-working-server')
    result = run_shell(deployment, '''
        ! preflight_validate_mavsdk_sync_environment
        [[ "$MAVSDK_RUNTIME_STATUS" == maintenance_required ]]
    ''')
    assert result.returncode == 0, result.stderr
    assert (deployment / 'mavsdk_server').read_bytes() == b'known-working-server'


def test_main_admission_precedes_all_runtime_mutations():
    main = SCRIPT.read_text().split('main() {', 1)[1]
    admission = main.index('! preflight_validate_mavsdk_sync_environment')
    for mutation in ('if ! check_service_updates', 'if ! ensure_mavsdk_runtime_artifact',
                     '\n    check_connectivity_updates', '\n    check_mavlink_runtime_updates',
                     'if ! check_requirements_update', '\n    apply_post_sync_service_actions'):
        assert admission < main.index(mutation)
    refusal = main[admission:main.index('if ! check_service_updates')]
    assert 'rollback_repository_to_previous_head "$previous_head"' in refusal
    assert 'exit_with_failure_result "SDK-MAINTENANCE"' in refusal


def test_real_source_sync_rolls_back_before_sdk_or_service_writes(deployment):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(deployment), *args], text=True).strip()
    git('init', '-b', 'main')
    git('config', 'user.name', 'SDK fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    (deployment / '.gitignore').write_text('venv/\nstate-home/\n')
    (deployment / 'mavsdk_server').write_bytes(b'known-working-server')
    (deployment / 'revision.txt').write_text('working')
    git('add', '.')
    git('commit', '-m', 'working source')
    previous = git('rev-parse', 'HEAD')
    library = deployment / 'tools/git_sync_mds/sdk_runtime_guard.sh'
    library.parent.mkdir()
    library.write_text((ROOT / 'tools/git_sync_mds/sdk_runtime_guard.sh').read_text())
    (deployment / 'revision.txt').write_text('incompatible new source')
    git('add', '.')
    git('commit', '-m', 'SDK migration')
    target = git('rev-parse', 'HEAD')
    git('reset', '--hard', previous)
    git('remote', 'add', 'origin', str(deployment))
    git('update-ref', 'refs/remotes/origin/main', target)
    python = make_python(deployment / 'venv/bin', compatible=False)
    result = run_shell(deployment, f'''
        LOG_FILE=/dev/null
        load_runtime_env_files() {{ :; }}; refresh_derived_runtime_paths() {{ :; }}
        parse_arguments() {{ BRANCH_NAME=main; REPO_URL={shlex.quote(str(deployment))}; }}
        configure_git_ssh_auth() {{ :; }}; acquire_lock() {{ :; }}
        report_git_sync_phase() {{ :; }}; set_led_status() {{ :; }}
        cleanup_git_locks() {{ :; }}; check_network_connectivity() {{ :; }}
        determine_git_url() {{ printf '%s' "$REPO_DIR"; }}
        perform_git_fetch() {{ :; }}; maybe_reexec_updated_sync_script() {{ :; }}
        check_runtime_process_updates() {{ :; }}; check_repo_update_restart_policy() {{ :; }}
        preflight_validate_post_sync_runtime_changes() {{ :; }}
        persist_git_sync_state() {{ :; }}; cleanup_on_exit() {{ :; }}
        retry_with_backoff() {{ shift 2; "$@"; }}
        check_service_updates() {{ printf 'unexpected write' > "$REPO_DIR/mutated"; exit 92; }}
        main
    ''')
    assert result.returncode == 1, result.stderr
    assert 'SDK-MAINTENANCE' in result.stdout
    assert git('rev-parse', 'HEAD') == previous
    assert (deployment / 'revision.txt').read_text() == 'working'
    assert (deployment / 'mavsdk_server').read_bytes() == b'known-working-server'
    assert not (deployment / 'mutated').exists()
    assert all(line.endswith(' python-check') for line in python.with_name('calls').read_text().splitlines())

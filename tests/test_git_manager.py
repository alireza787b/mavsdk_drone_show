# tests/test_git_manager.py
"""
Git Manager Tests
=================
Tests for the shared Git operations in functions/git_manager.py.
"""

import pytest
import subprocess
from unittest.mock import patch, MagicMock


class TestExecuteGitCommand:
    """Test git command execution"""

    @patch('subprocess.check_output')
    def test_execute_git_command_success(self, mock_output):
        """Test successful git command execution"""
        from functions.git_manager import execute_git_command

        mock_output.return_value = b'main\n'

        result = execute_git_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])

        assert result == 'main'
        mock_output.assert_called_once()

    @patch('subprocess.check_output')
    def test_execute_git_command_failure(self, mock_output):
        """Test git command failure returns None"""
        from functions.git_manager import execute_git_command

        mock_output.side_effect = subprocess.CalledProcessError(1, 'git')

        result = execute_git_command(['git', 'invalid-command'])

        assert result is None

    @patch('subprocess.check_output')
    def test_execute_git_command_with_cwd(self, mock_output):
        """Test git command with working directory"""
        from functions.git_manager import execute_git_command

        mock_output.return_value = b'abc123\n'

        result = execute_git_command(['git', 'rev-parse', 'HEAD'], cwd='/some/path')

        assert result == 'abc123'
        mock_output.assert_called_with(
            ['git', 'rev-parse', 'HEAD'],
            cwd='/some/path',
            stderr=subprocess.DEVNULL
        )


class TestGetLocalGitReport:
    """Test local git status reporting"""

    @patch('functions.git_manager.execute_git_command')
    def test_get_local_git_report_success(self, mock_exec):
        """Test successful local git report"""
        from functions.git_manager import get_local_git_report

        # Mock all git commands
        def mock_git_cmd(cmd, cwd=None):
            if 'rev-parse' in cmd and '--abbrev-ref' in cmd and 'HEAD' in cmd:
                return 'main'
            elif 'rev-parse' in cmd and 'HEAD' in cmd:
                return 'abc123def456789'
            elif '--format=%an' in cmd:
                return 'Test Author'
            elif '--format=%ae' in cmd:
                return 'test@example.com'
            elif '--format=%cd' in cmd:
                return '2025-11-22T10:00:00+00:00'
            elif '--format=%B' in cmd:
                return 'Test commit message'
            elif 'remote.origin.url' in cmd:
                return 'git@github.com:test/repo.git'
            elif '@{u}' in cmd:
                return 'origin/main'
            elif '--porcelain' in cmd:
                return ''  # Clean status
            return ''

        mock_exec.side_effect = mock_git_cmd

        result = get_local_git_report()

        assert result['branch'] == 'main'
        assert result['commit'] == 'abc123def456789'
        assert result['author_name'] == 'Test Author'
        assert result['author_email'] == 'test@example.com'
        assert result['status'] == 'clean'
        assert result['uncommitted_changes'] == []
        assert result['commits_ahead'] == 0
        assert result['commits_behind'] == 0

    @patch('functions.git_manager.execute_git_command')
    def test_get_local_git_report_dirty(self, mock_exec):
        """Test local git report with uncommitted changes"""
        from functions.git_manager import get_local_git_report

        def mock_git_cmd(cmd, cwd=None):
            if 'rev-parse' in cmd and '--abbrev-ref' in cmd and 'HEAD' in cmd:
                return 'feature-branch'
            elif 'rev-parse' in cmd and 'HEAD' in cmd:
                return 'def456789'
            elif '--porcelain' in cmd:
                return ' M src/file.py\n?? new_file.txt'
            return 'test'

        mock_exec.side_effect = mock_git_cmd

        result = get_local_git_report()

        assert result['branch'] == 'feature-branch'
        assert result['status'] == 'dirty'
        assert len(result['uncommitted_changes']) == 2
        assert ' M src/file.py' in result['uncommitted_changes']

    @patch('functions.git_manager.execute_git_command')
    def test_get_local_git_report_ignores_generated_sitl_metadata(self, mock_exec):
        """Generated SITL provenance files should not make the repo appear dirty."""
        from functions.git_manager import get_local_git_report

        def mock_git_cmd(cmd, cwd=None):
            if 'rev-parse' in cmd and '--abbrev-ref' in cmd and 'HEAD' in cmd:
                return 'main-candidate'
            elif 'rev-parse' in cmd and 'HEAD' in cmd:
                return 'abc123def456789'
            elif '--format=%an' in cmd:
                return 'Test Author'
            elif '--format=%ae' in cmd:
                return 'test@example.com'
            elif '--format=%cd' in cmd:
                return '2026-03-27T10:00:00+00:00'
            elif '--format=%B' in cmd:
                return 'Test commit message'
            elif 'remote.origin.url' in cmd:
                return 'git@github.com:test/repo.git'
            elif '@{u}' in cmd:
                return 'origin/main-candidate'
            elif '--porcelain' in cmd:
                return '\n'.join([
                    '?? .mds_px4_source_provenance.env',
                    '?? .mds_px4_submodules.txt',
                    '?? .mds_sitl_image_build.env',
                ])
            return ''

        mock_exec.side_effect = mock_git_cmd

        result = get_local_git_report()

        assert result['status'] == 'clean'
        assert result['uncommitted_changes'] == []

    @patch('functions.git_manager.execute_git_command')
    def test_get_local_git_report_no_branch(self, mock_exec):
        """Test error when branch can't be determined"""
        from functions.git_manager import get_local_git_report

        mock_exec.return_value = None

        result = get_local_git_report()

        assert 'error' in result

    @patch('functions.git_manager.execute_git_command')
    def test_get_local_git_report_resolves_detached_head_from_remote_ref(self, mock_exec):
        """Detached worktrees should still resolve a useful branch name."""
        from functions.git_manager import get_local_git_report

        def mock_git_cmd(cmd, cwd=None):
            if cmd == ['git', 'rev-parse', '--abbrev-ref', 'HEAD']:
                return 'HEAD'
            if cmd == ['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}']:
                return None
            if cmd == ['git', 'for-each-ref', '--format=%(refname:short)', '--contains', 'HEAD', 'refs/remotes']:
                return 'origin/HEAD\norigin/main-candidate'
            if cmd == ['git', 'rev-parse', 'HEAD']:
                return 'abc123def456789'
            if '--format=%an' in cmd:
                return 'Test Author'
            if '--format=%ae' in cmd:
                return 'test@example.com'
            if '--format=%cd' in cmd:
                return '2026-04-10T10:00:00+00:00'
            if '--format=%B' in cmd:
                return 'Detached commit'
            if 'remote.origin.url' in cmd:
                return 'git@github.com:test/repo.git'
            if '--porcelain' in cmd:
                return ''
            return ''

        mock_exec.side_effect = mock_git_cmd

        result = get_local_git_report()

        assert result['branch'] == 'main-candidate'

    @patch('functions.git_manager.execute_git_command')
    def test_get_local_git_report_without_tracking_branch_is_not_an_error(self, mock_exec):
        """Custom branches without upstream should still return a clean git report."""
        from functions.git_manager import get_local_git_report

        def mock_git_cmd(cmd, cwd=None):
            if cmd == ['git', 'rev-parse', '--abbrev-ref', 'HEAD']:
                return 'smart-swarm-runtime-phase1-20260415'
            if cmd == ['git', 'rev-parse', 'HEAD']:
                return 'abc123def456789'
            if '--format=%an' in cmd:
                return 'Test Author'
            if '--format=%ae' in cmd:
                return 'test@example.com'
            if '--format=%cd' in cmd:
                return '2026-04-16T10:00:00+00:00'
            if '--format=%B' in cmd:
                return 'Custom branch commit'
            if 'remote.origin.url' in cmd:
                return 'git@github.com:test/repo.git'
            if cmd == ['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}']:
                return None
            if cmd == ['git', 'status', '--porcelain']:
                return ''
            if cmd == ['git', 'rev-list', '--left-right', '--count', '...HEAD']:
                pytest.fail("rev-list should not run when there is no tracking branch")
            return ''

        mock_exec.side_effect = mock_git_cmd

        result = get_local_git_report()

        assert result['branch'] == 'smart-swarm-runtime-phase1-20260415'
        assert result['tracking_branch'] == ''
        assert result['commits_ahead'] == 0
        assert result['commits_behind'] == 0

    @patch('functions.git_manager.execute_git_command')
    def test_get_local_git_report_reports_healthy_https_token_file_access(self, mock_exec, monkeypatch):
        """Node git reports should surface healthy HTTPS token-file posture without exposing paths."""
        from functions.git_manager import get_local_git_report
        from src.settings.runtime import reset_preloaded_local_env_state

        token_path = '/tmp/test-node-token'
        monkeypatch.setenv('MDS_LOCAL_ENV_FILE', '/tmp/mds-tests-no-local.env')
        monkeypatch.setenv('MDS_GIT_AUTH_TOKEN_FILE', token_path)
        monkeypatch.delenv('MDS_GIT_SSH_KEY_FILE', raising=False)

        def mock_git_cmd(cmd, cwd=None):
            if cmd == ['git', 'rev-parse', '--abbrev-ref', 'HEAD']:
                return 'main-candidate'
            if cmd == ['git', 'rev-parse', 'HEAD']:
                return 'abc123def456789'
            if '--format=%an' in cmd:
                return 'Test Author'
            if '--format=%ae' in cmd:
                return 'test@example.com'
            if '--format=%cd' in cmd:
                return '2026-04-23T10:00:00+00:00'
            if '--format=%B' in cmd:
                return 'Healthy token-file commit'
            if 'remote.origin.url' in cmd:
                return 'https://github.com/test/repo.git'
            if cmd == ['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}']:
                return 'origin/main-candidate'
            if cmd == ['git', 'status', '--porcelain']:
                return ''
            if cmd == ['git', 'rev-list', '--left-right', '--count', 'origin/main-candidate...HEAD']:
                return '0 0'
            return ''

        mock_exec.side_effect = mock_git_cmd

        reset_preloaded_local_env_state()
        try:
            with patch('os.path.isfile', side_effect=lambda path: path == token_path):
                result = get_local_git_report()
        finally:
            reset_preloaded_local_env_state()

        assert result['repo_access_mode'] == 'https_token_file'
        assert result['git_auth_health_status'] == 'healthy'
        assert result['git_auth_health_issues'] == []
        assert 'token-file access is configured and readable' in result['git_auth_health_summary']

    @patch('functions.git_manager.execute_git_command')
    def test_get_local_git_report_reports_broken_ssh_key_access(self, mock_exec, monkeypatch):
        """Node git reports should flag missing SSH credentials as an auth error."""
        from functions.git_manager import get_local_git_report
        from src.settings.runtime import reset_preloaded_local_env_state

        monkeypatch.setenv('MDS_LOCAL_ENV_FILE', '/tmp/mds-tests-no-local.env')
        monkeypatch.delenv('MDS_GIT_AUTH_TOKEN_FILE', raising=False)
        monkeypatch.setenv('MDS_GIT_SSH_KEY_FILE', '/tmp/test-node-ssh-key')

        def mock_git_cmd(cmd, cwd=None):
            if cmd == ['git', 'rev-parse', '--abbrev-ref', 'HEAD']:
                return 'main-candidate'
            if cmd == ['git', 'rev-parse', 'HEAD']:
                return 'abc123def456789'
            if '--format=%an' in cmd:
                return 'Test Author'
            if '--format=%ae' in cmd:
                return 'test@example.com'
            if '--format=%cd' in cmd:
                return '2026-04-23T10:00:00+00:00'
            if '--format=%B' in cmd:
                return 'Broken ssh commit'
            if 'remote.origin.url' in cmd:
                return 'git@github.com:test/repo.git'
            if cmd == ['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}']:
                return 'origin/main-candidate'
            if cmd == ['git', 'status', '--porcelain']:
                return ''
            if cmd == ['git', 'rev-list', '--left-right', '--count', 'origin/main-candidate...HEAD']:
                return '0 0'
            return ''

        mock_exec.side_effect = mock_git_cmd

        reset_preloaded_local_env_state()
        try:
            with patch('os.path.isfile', return_value=False):
                result = get_local_git_report()
        finally:
            reset_preloaded_local_env_state()

        assert result['repo_access_mode'] == 'ssh_key'
        assert result['git_auth_health_status'] == 'error'
        assert result['git_auth_health_issues'] == [
            'SSH-key mode is selected but the configured SSH key file is missing or unreadable.'
        ]


class TestGetLocalGitShortStatus:
    """Test abbreviated git status"""

    @patch('functions.git_manager.execute_git_command')
    def test_get_short_status_clean(self, mock_exec):
        """Test short status for clean repo"""
        from functions.git_manager import get_local_git_short_status

        def mock_git_cmd(cmd, cwd=None):
            if '--abbrev-ref' in cmd:
                return 'main'
            elif '--short' in cmd:
                return 'abc123'
            elif '--porcelain' in cmd:
                return ''
            return ''

        mock_exec.side_effect = mock_git_cmd

        result = get_local_git_short_status()

        assert result['branch'] == 'main'
        assert result['commit_short'] == 'abc123'
        assert result['status'] == 'clean'

    @patch('functions.git_manager.execute_git_command')
    def test_get_short_status_dirty(self, mock_exec):
        """Test short status for dirty repo"""
        from functions.git_manager import get_local_git_short_status

        def mock_git_cmd(cmd, cwd=None):
            if '--abbrev-ref' in cmd:
                return 'dev'
            elif '--short' in cmd:
                return 'xyz789'
            elif '--porcelain' in cmd:
                return ' M file.py'
            return ''

        mock_exec.side_effect = mock_git_cmd

        result = get_local_git_short_status()

        assert result['status'] == 'dirty'

    @patch('functions.git_manager.execute_git_command')
    def test_get_short_status_ignores_generated_sitl_metadata(self, mock_exec):
        """Short git status should also ignore generated SITL metadata files."""
        from functions.git_manager import get_local_git_short_status

        def mock_git_cmd(cmd, cwd=None):
            if '--abbrev-ref' in cmd:
                return 'main-candidate'
            elif '--short' in cmd:
                return 'abc1234'
            elif '--porcelain' in cmd:
                return '?? .mds_sitl_image_build.env'
            return ''

        mock_exec.side_effect = mock_git_cmd

        result = get_local_git_short_status()

        assert result['status'] == 'clean'

    @patch('functions.git_manager.execute_git_command')
    def test_get_short_status_resolves_detached_head_from_tracking_branch(self, mock_exec):
        """Short status should resolve a detached head via upstream when available."""
        from functions.git_manager import get_local_git_short_status

        def mock_git_cmd(cmd, cwd=None):
            if cmd == ['git', 'rev-parse', '--abbrev-ref', 'HEAD']:
                return 'HEAD'
            if cmd == ['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}']:
                return 'origin/main-candidate'
            if cmd == ['git', 'rev-parse', '--short', 'HEAD']:
                return 'abc1234'
            if cmd == ['git', 'status', '--porcelain']:
                return ''
            return ''

        mock_exec.side_effect = mock_git_cmd

        result = get_local_git_short_status()

        assert result['branch'] == 'main-candidate'


class TestGetRemoteGitStatus:
    """Test remote git status fetching"""

    @patch('requests.get')
    def test_get_remote_git_status_success(self, mock_get):
        """Test successful remote git status fetch"""
        from functions.git_manager import get_remote_git_status

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'branch': 'main',
            'commit': 'abc123',
            'status': 'clean'
        }
        mock_get.return_value = mock_response

        result = get_remote_git_status('http://192.168.1.100:7070')

        assert result['branch'] == 'main'
        assert result['commit'] == 'abc123'
        mock_get.assert_called_with(
            'http://192.168.1.100:7070/api/v1/git/status',
            timeout=5.0
        )

    @patch('requests.get')
    def test_get_remote_git_status_http_error(self, mock_get):
        """Test remote git status with HTTP error"""
        from functions.git_manager import get_remote_git_status

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        result = get_remote_git_status('http://192.168.1.100:7070')

        assert 'error' in result
        assert '500' in result['error']

    @patch('requests.get')
    def test_get_remote_git_status_timeout(self, mock_get):
        """Test remote git status with timeout"""
        from functions.git_manager import get_remote_git_status
        import requests

        mock_get.side_effect = requests.Timeout()

        result = get_remote_git_status('http://192.168.1.100:7070')

        assert 'error' in result
        assert 'Timeout' in result['error']

    @patch('requests.get')
    def test_get_remote_git_status_connection_error(self, mock_get):
        """Test remote git status with connection error"""
        from functions.git_manager import get_remote_git_status
        import requests

        mock_get.side_effect = requests.ConnectionError()

        result = get_remote_git_status('http://192.168.1.100:7070')

        assert 'error' in result
        assert 'Connection error' in result['error']


class TestCompareGitStatus:
    """Test git status comparison"""

    def test_compare_git_status_synced(self):
        """Test comparison when repos are synced"""
        from functions.git_manager import compare_git_status

        local = {'commit': 'abc123def456', 'branch': 'main'}
        remote = {'commit': 'abc123def456', 'branch': 'main'}

        result = compare_git_status(local, remote)

        assert result['synced'] == True
        assert result['branch_match'] == True
        assert result['local_commit'] == 'abc123d'
        assert result['remote_commit'] == 'abc123d'

    def test_compare_git_status_not_synced(self):
        """Test comparison when repos are not synced"""
        from functions.git_manager import compare_git_status

        local = {'commit': 'abc123def456', 'branch': 'main'}
        remote = {'commit': 'xyz789000111', 'branch': 'main'}

        result = compare_git_status(local, remote)

        assert result['synced'] == False
        assert result['branch_match'] == True

    def test_compare_git_status_different_branches(self):
        """Test comparison with different branches"""
        from functions.git_manager import compare_git_status

        local = {'commit': 'abc123def456', 'branch': 'main'}
        remote = {'commit': 'abc123def456', 'branch': 'develop'}

        result = compare_git_status(local, remote)

        assert result['synced'] == True  # Same commit
        assert result['branch_match'] == False

    def test_compare_git_status_empty_commits(self):
        """Test comparison with missing commit info"""
        from functions.git_manager import compare_git_status

        local = {'commit': '', 'branch': 'main'}
        remote = {'commit': '', 'branch': 'main'}

        result = compare_git_status(local, remote)

        assert result['synced'] == False  # Empty commits don't match


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

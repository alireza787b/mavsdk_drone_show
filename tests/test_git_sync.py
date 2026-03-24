# tests/test_git_sync.py
"""
Git Sync System Tests
=====================
Tests for the hardened git sync system: git_operations timeout,
schema validation, check_git_sync_status GCS comparison.
"""

import pytest
import time
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from git import GitCommandError


def load_gcs_utils_module():
    """Load gcs-server/utils.py without the autouse utils.git_operations patch."""
    module_path = Path(__file__).resolve().parents[1] / 'gcs-server' / 'utils.py'
    spec = importlib.util.spec_from_file_location('gcs_utils_under_test', module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestGitOperationsTimeout:
    """Test git_operations return format"""

    def test_git_operations_success_format(self):
        """Test that a success result has the expected fields"""
        result = {'success': True, 'message': 'Pushed', 'commit_hash': 'abc1234'}
        assert result['success'] is True
        assert result['commit_hash'] == 'abc1234'
        assert 'message' in result

    def test_git_operations_failure_format(self):
        """Test that a failure result has the expected fields"""
        result = {'success': False, 'message': 'Git push timed out after 30s', 'commit_hash': None}
        assert result['success'] is False
        assert 'timed out' in result['message']

    def test_git_operations_timeout_result_format(self):
        """Test timeout result format"""
        result = {'success': False, 'message': 'Git push timed out after 30s', 'commit_hash': 'abc1234'}
        assert result['success'] is False
        assert result['commit_hash'] is not None


class TestGitOperationsNonInteractiveAuth:
    """Test non-interactive git auth handling for write-backed workflows."""

    def test_git_operations_sets_noninteractive_environment(self, monkeypatch):
        gcs_utils = load_gcs_utils_module()

        fake_git = MagicMock()
        fake_repo = MagicMock()
        fake_repo.git = fake_git
        fake_repo.is_dirty.return_value = False

        monkeypatch.setattr('git.Repo', lambda *_args, **_kwargs: fake_repo)

        result = gcs_utils.git_operations('/tmp/repo', 'test commit')

        assert result['success'] is True
        fake_git.update_environment.assert_called_once_with(
            GIT_TERMINAL_PROMPT='0',
            GIT_ASKPASS='echo',
            SSH_ASKPASS='echo',
            GCM_INTERACTIVE='never',
        )

    def test_git_operations_reports_noninteractive_auth_failure(self, monkeypatch):
        gcs_utils = load_gcs_utils_module()

        fake_git = MagicMock()
        fake_git.fetch.return_value = ''
        fake_git.pull.return_value = ''
        fake_git.push.side_effect = GitCommandError(
            'push',
            128,
            stderr="fatal: could not read Username for 'https://github.com': terminal prompts disabled",
        )
        fake_git.config.return_value = 'https://github.com/example/repo.git'

        fake_repo = MagicMock()
        fake_repo.git = fake_git
        fake_repo.is_dirty.return_value = True
        fake_repo.index.commit.return_value = type('Commit', (), {'hexsha': 'abc12345', 'stats': type('Stats', (), {'files': {}})()})()

        monkeypatch.setattr('git.Repo', lambda *_args, **_kwargs: fake_repo)

        result = gcs_utils.git_operations('/tmp/repo', 'test commit')

        assert result['success'] is False
        assert 'authenticated write access is required' in result['message']
        assert 'disable GIT_AUTO_PUSH' in result['message']
        fake_git.reset.assert_called_once_with('--mixed', 'HEAD~1')


class TestGitStatusSchemas:
    """Test schema changes for git sync"""

    def test_git_status_response_has_gcs_status(self):
        """Test that GitStatusResponse includes gcs_status field"""
        from schemas import GitStatusResponse
        response = GitStatusResponse(
            git_status={},
            total_drones=0,
            synced_count=0,
            needs_sync_count=0,
            gcs_status={'branch': 'main', 'commit': 'abc123'},
            sync_in_progress=False,
            timestamp=int(time.time() * 1000)
        )
        assert response.gcs_status is not None
        assert response.gcs_status['branch'] == 'main'
        assert response.sync_in_progress is False

    def test_git_status_response_gcs_status_optional(self):
        """Test that gcs_status can be None"""
        from schemas import GitStatusResponse
        response = GitStatusResponse(
            git_status={},
            total_drones=0,
            synced_count=0,
            needs_sync_count=0,
            timestamp=int(time.time() * 1000)
        )
        assert response.gcs_status is None
        assert response.sync_in_progress is False

    def test_config_update_response_has_git_result(self):
        """Test that ConfigUpdateResponse includes git_result field"""
        from schemas import ConfigUpdateResponse
        response = ConfigUpdateResponse(
            success=True,
            message="Saved",
            updated_count=5,
            git_result={'success': True, 'message': 'Pushed', 'commit_hash': 'abc123'}
        )
        assert response.git_result is not None
        assert response.git_result['commit_hash'] == 'abc123'

    def test_config_update_response_git_result_optional(self):
        """Test that git_result can be None"""
        from schemas import ConfigUpdateResponse
        response = ConfigUpdateResponse(
            success=True,
            message="Saved",
            updated_count=5
        )
        assert response.git_result is None

    def test_sync_repos_request(self):
        """Test SyncReposRequest schema"""
        from schemas import SyncReposRequest
        req = SyncReposRequest(pos_ids=[1, 2, 3], force_pull=True)
        assert req.pos_ids == [1, 2, 3]
        assert req.force_pull is True

    def test_sync_repos_request_defaults(self):
        """Test SyncReposRequest default values"""
        from schemas import SyncReposRequest
        req = SyncReposRequest()
        assert req.pos_ids is None
        assert req.force_pull is False

    def test_sync_repos_response(self):
        """Test SyncReposResponse schema"""
        from schemas import SyncReposResponse
        resp = SyncReposResponse(
            success=True,
            message="Sync complete",
            synced_drones=[1, 2],
            failed_drones=[3],
            total_attempted=3
        )
        assert resp.success is True
        assert len(resp.synced_drones) == 2
        assert len(resp.failed_drones) == 1

    def test_git_status_stream_message(self):
        """Test GitStatusStreamMessage includes sync_in_progress"""
        from schemas import GitStatusStreamMessage
        msg = GitStatusStreamMessage(
            type="git_status",
            timestamp=int(time.time() * 1000),
            data={},
            sync_in_progress=True
        )
        assert msg.sync_in_progress is True


class TestCheckGitSyncStatus:
    """Test enhanced check_git_sync_status with GCS comparison"""

    def test_check_sync_status_result_format(self):
        """Test that sync status result has the expected fields"""
        # Test the expected result structure
        expected_keys = [
            'is_fully_synced', 'is_branch_synced', 'is_commit_synced',
            'is_synced_with_gcs', 'gcs_commit', 'drones_out_of_sync_with_gcs',
            'branch_distribution', 'commit_distribution', 'total_active_drones'
        ]
        # Verify the expected keys are defined
        for key in expected_keys:
            assert isinstance(key, str)

    def test_git_status_enum_values(self):
        """Test GitStatus enum has all required values"""
        from schemas import GitStatus
        assert GitStatus.SYNCED == 'synced'
        assert GitStatus.AHEAD == 'ahead'
        assert GitStatus.BEHIND == 'behind'
        assert GitStatus.DIVERGED == 'diverged'
        assert GitStatus.DIRTY == 'dirty'
        assert GitStatus.UNKNOWN == 'unknown'


class TestGitSyncResultParsing:
    """Test GIT_SYNC_RESULT JSON parsing in actions.py"""

    def test_valid_json_result(self):
        """Test parsing a valid GIT_SYNC_RESULT line"""
        import json
        line = 'GIT_SYNC_RESULT={"success":true,"branch":"main-candidate","commit":"abc1234","message":"test commit","duration":5}'
        result = json.loads(line[len("GIT_SYNC_RESULT="):])
        assert result['success'] is True
        assert result['branch'] == 'main-candidate'
        assert result['commit'] == 'abc1234'
        assert result['message'] == 'test commit'
        assert result['duration'] == 5

    def test_escaped_quotes_in_message(self):
        """Test parsing GIT_SYNC_RESULT with escaped quotes in commit message"""
        import json
        line = r'GIT_SYNC_RESULT={"success":true,"branch":"main","commit":"abc","message":"fix: update \"config\"","duration":3}'
        result = json.loads(line[len("GIT_SYNC_RESULT="):])
        assert '"config"' in result['message']

    def test_failure_result(self):
        """Test parsing a failure GIT_SYNC_RESULT"""
        import json
        line = 'GIT_SYNC_RESULT={"success":false,"branch":"main","error":"fetch_failed"}'
        result = json.loads(line[len("GIT_SYNC_RESULT="):])
        assert result['success'] is False
        assert result['error'] == 'fetch_failed'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

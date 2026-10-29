from pathlib import Path
from types import SimpleNamespace

import pytest

from functions import swarm_trajectory_package as package
from functions import swarm_trajectory_processor as processor
from functions.swarm_session_manager import SwarmSessionManager


def _workspace(tmp_path):
    folders = {name: str(tmp_path / name) for name in ('raw', 'processed', 'plots')}
    folders['base'] = str(tmp_path)
    for name in ('raw', 'processed', 'plots'):
        Path(folders[name]).mkdir()
    Path(folders['processed'], 'Drone 1.csv').write_text('old trajectory')
    Path(folders['plots'], 'combined.jpg').write_text('old plot')
    session = tmp_path / '.trajectory_session.json'
    session.write_text('old session')
    return folders, session


def _candidate(staged):
    Path(staged.folders['processed'], 'Drone 1.csv').write_text('new trajectory')
    Path(staged.folders['plots'], 'combined.jpg').write_text('new plot')


def _assert_old(folders, session):
    assert Path(folders['processed'], 'Drone 1.csv').read_text() == 'old trajectory'
    assert Path(folders['plots'], 'combined.jpg').read_text() == 'old plot'
    assert session.read_text() == 'old session'


def test_candidate_is_invisible_until_publication(tmp_path):
    folders, session = _workspace(tmp_path)
    with package.StagedTrajectoryPackage(folders, str(session)) as staged:
        _candidate(staged)
        _assert_old(folders, session)
    _assert_old(folders, session)
    assert not list(tmp_path.glob('.trajectory-stage-*'))


def test_publish_writes_session_last_and_replaces_complete_directories(tmp_path):
    folders, session = _workspace(tmp_path)
    Path(folders['processed'], 'Drone 99.csv').write_text('obsolete')
    with package.StagedTrajectoryPackage(folders, str(session)) as staged:
        _candidate(staged)
        def save():
            assert not session.exists()
            assert Path(folders['processed'], 'Drone 1.csv').read_text() == 'new trajectory'
            assert Path(folders['plots'], 'combined.jpg').read_text() == 'new plot'
            session.write_text('new session')
            return 'published'
        assert staged.publish(save) == 'published'
    assert session.read_text() == 'new session'
    assert not Path(folders['processed'], 'Drone 99.csv').exists()
    assert not list(tmp_path.glob('.trajectory-stage-*'))


def test_session_save_failure_restores_previous_package(tmp_path):
    folders, session = _workspace(tmp_path)
    with package.StagedTrajectoryPackage(folders, str(session)) as staged:
        _candidate(staged)
        def failed_save():
            session.write_text('incomplete session')
            raise OSError('disk full')
        with pytest.raises(OSError, match='disk full'):
            staged.publish(failed_save)
    _assert_old(folders, session)
    assert not list(tmp_path.glob('.trajectory-stage-*'))


def test_second_directory_failure_restores_first_directory(tmp_path, monkeypatch):
    folders, session = _workspace(tmp_path)
    with package.StagedTrajectoryPackage(folders, str(session)) as staged:
        _candidate(staged)
        replace = package.os.replace
        def fail_once(source, target):
            if str(source) == staged.folders['plots']:
                raise OSError('cannot install plots')
            return replace(source, target)
        monkeypatch.setattr(package.os, 'replace', fail_once)
        with pytest.raises(OSError, match='cannot install plots'):
            staged.publish(lambda: None)
    _assert_old(folders, session)


def test_rollback_failure_preserves_recovery_files(tmp_path, monkeypatch):
    folders, session = _workspace(tmp_path)
    recovery = None
    with package.StagedTrajectoryPackage(folders, str(session)) as staged:
        recovery = staged.root
        _candidate(staged)
        replace = package.os.replace
        def fail_restore(source, target):
            if Path(source).name == 'previous-processed':
                raise OSError('filesystem unavailable')
            return replace(source, target)
        monkeypatch.setattr(package.os, 'replace', fail_restore)
        def failed_save():
            raise OSError('disk full')
        with pytest.raises(RuntimeError, match='recovery files retained'):
            staged.publish(failed_save)
    assert (recovery / 'previous-processed' / 'Drone 1.csv').read_text() == 'old trajectory'
    assert (recovery / 'previous-session.json').read_text() == 'old session'
    assert not session.exists()


@pytest.mark.parametrize('outcome', ['partial', 'failed'])
def test_processor_preserves_previous_package_when_candidate_is_incomplete(tmp_path, monkeypatch, outcome):
    folders, session = _workspace(tmp_path)
    monkeypatch.setattr(processor, 'get_swarm_trajectory_folders', lambda: folders)
    def generate(_leaders, _recommendation, staged_folders, _reloaded):
        Path(staged_folders['processed'], 'Drone 1.csv').write_text('partial candidate')
        return {'success': outcome == 'partial', 'outcome': outcome}
    monkeypatch.setattr(processor, '_generate_trajectory_processing', generate)
    def no_session(*_args):
        pytest.fail('An incomplete candidate must not create a session')
    result = processor._execute_trajectory_processing(
        [1], SimpleNamespace(create_processing_session=no_session, input_identity=lambda: {}), {},
    )
    assert result['success'] is False
    assert result['published'] is False
    _assert_old(folders, session)
    assert not list(tmp_path.glob('.trajectory-stage-*'))


def test_force_regenerate_does_not_clear_active_package_before_generation(monkeypatch):
    manager = SimpleNamespace(
        get_processing_recommendation=lambda: {'action': 'mandatory_full_reprocess'},
        get_uploaded_leaders=lambda: [1],
    )
    monkeypatch.setattr(processor, 'SwarmSessionManager', lambda: manager)
    monkeypatch.setattr(processor, 'ensure_formation_snapshot', lambda: None)
    monkeypatch.setattr(processor, 'clear_processed_data', lambda: pytest.fail('must not clear active outputs'))
    monkeypatch.setattr(processor, '_execute_trajectory_processing', lambda *_args, **_kwargs: {'success': False})
    assert processor.process_swarm_trajectories(force_clear=True)['success'] is False


def test_input_change_during_generation_rolls_back_publication(tmp_path, monkeypatch):
    folders, session = _workspace(tmp_path)
    monkeypatch.setattr(processor, 'get_swarm_trajectory_folders', lambda: folders)
    monkeypatch.setattr('functions.swarm_session_manager.get_swarm_trajectory_folders', lambda: folders)
    manager = SwarmSessionManager()
    monkeypatch.setattr(manager, 'generate_swarm_fingerprint', lambda: 'formation')
    monkeypatch.setattr(manager, 'generate_parameters_hash', lambda: 'parameters')
    raw = Path(folders['raw'], 'Drone 1.csv')
    raw.write_text('original input')
    def generate(_leaders, _recommendation, staged_folders, _reloaded):
        Path(staged_folders['processed'], 'Drone 1.csv').write_text('candidate from old input')
        raw.write_text('edited while generation was running')
        return {'success': True, 'outcome': 'success', 'processed_leaders': [1], 'processed_drones': 1}
    monkeypatch.setattr(processor, '_generate_trajectory_processing', generate)
    result = processor._execute_trajectory_processing([1], manager, {})
    assert result['success'] is False
    assert 'inputs changed' in result['error']
    _assert_old(folders, session)

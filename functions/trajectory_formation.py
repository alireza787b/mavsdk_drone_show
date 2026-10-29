"""Mission-owned formation snapshots; never writes the live swarm configuration."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile

from functions.swarm_analyzer import fetch_swarm_data as fetch_live_formation
from functions.swarm_trajectory_utils import get_swarm_trajectory_folders
from src.smart_swarm_contract import normalize_topology, topology_revision


def _path(base=None):
    return Path(base or get_swarm_trajectory_folders()['base']) / 'formation.json'


def read_formation(base=None, fallback=None):
    path = _path(base)
    if path.exists():
        payload = json.loads(path.read_text())
        assignments = normalize_topology(payload['assignments'])
        if not assignments or topology_revision(assignments) != payload['revision']:
            raise ValueError('Mission formation snapshot is invalid')
        return {'assignments': assignments, 'revision': payload['revision'], 'saved': True}
    assignments = normalize_topology((fallback or fetch_live_formation)())
    return {'assignments': assignments, 'revision': topology_revision(assignments), 'saved': False}


def fetch_swarm_data():
    return read_formation()['assignments']


@contextmanager
def _formation_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / '.formation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def save_formation(assignments, expected_revision, base=None, fallback=None):
    path = _path(base)
    normalized = normalize_topology(assignments)
    if not normalized:
        raise ValueError('Choose at least one aircraft for the mission formation')
    with _formation_lock(path):
        current = read_formation(base, fallback)
        if current['revision'] != expected_revision:
            raise ValueError('Mission formation changed; refresh before saving')
        payload = {'assignments': normalized, 'revision': topology_revision(normalized)}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.formation-', delete=False) as output:
                temporary = output.name
                json.dump(payload, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    return {**payload, 'saved': True}


def ensure_formation_snapshot():
    current = read_formation()
    if not current['saved']:
        return save_formation(current['assignments'], current['revision'])
    return current

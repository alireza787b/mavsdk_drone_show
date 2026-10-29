"""Staged generation and rollback publication of trajectory artifacts.

Publication spans multiple paths, so it is deliberately NOT described as atomic.
The session is removed first and written last: readers must require a valid
session/output hash before dispatch. Immutable run pinning is a separate concern.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable, TypeVar

T = TypeVar("T")


class StagedTrajectoryPackage:
    """Build away from active files, then publish with failure rollback."""

    def __init__(self, folders: dict[str, str], session_file: str):
        self.active = {name: Path(folders[name]) for name in ("processed", "plots")}
        self.session_file = Path(session_file)
        parent = self.active["processed"].parent
        parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix=".trajectory-stage-", dir=parent))
        self.folders = dict(folders)
        for name in self.active:
            directory = self.root / name
            directory.mkdir()
            self.folders[name] = str(directory)
        self.preserve_recovery = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if not self.preserve_recovery:
            shutil.rmtree(self.root)

    def publish(self, save_session: Callable[[], T]) -> T:
        """Publish complete artifacts; session callback must propagate failures."""
        backups: dict[str, Path] = {}
        installed: list[str] = []
        old_session = self.root / "previous-session.json"
        had_session = self.session_file.exists()
        session_removed = False
        try:
            if had_session:
                os.replace(self.session_file, old_session)
                session_removed = True
            for name, destination in self.active.items():
                if destination.exists():
                    backup = self.root / f"previous-{name}"
                    os.replace(destination, backup)
                    backups[name] = backup
                os.replace(self.folders[name], destination)
                installed.append(name)
            return save_session()
        except BaseException:
            # If rollback fails, leave the stage/backup directory for recovery.
            self.preserve_recovery = True
            try:
                # A callback may have written the new session before failing.
                if session_removed or not had_session:
                    self.session_file.unlink(missing_ok=True)
                for name in reversed(tuple(self.active)):
                    destination = self.active[name]
                    if name in installed:
                        shutil.rmtree(destination)
                    if name in backups:
                        os.replace(backups[name], destination)
                if session_removed:
                    os.replace(old_session, self.session_file)
            except BaseException as rollback_error:
                raise RuntimeError(
                    f"Trajectory publication rollback failed; recovery files retained at {self.root}"
                ) from rollback_error
            self.preserve_recovery = False
            raise

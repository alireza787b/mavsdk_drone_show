"""Transactional primitives for installing one drone command.

Command payload files are prepared off to the side and published with atomic
renames.  The caller owns the in-memory configuration transaction, but this
module gives it a reversible artifact transaction with an explicit distinction
between a definite rejection and an outcome whose rollback could not be
verified.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple


class CommandInstallationRejected(ValueError):
    """The command was not installed and the previous installation is intact."""

    def __init__(self, message: str, *, phase: str, cause: Optional[BaseException] = None):
        super().__init__(message)
        self.phase = phase
        self.cause = cause


class CommandInstallationUncertain(RuntimeError):
    """Installation failed and at least one rollback step could not be verified."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        rollback_errors: Sequence[BaseException],
        cause: Optional[BaseException] = None,
    ):
        super().__init__(message)
        self.phase = phase
        self.rollback_errors = tuple(rollback_errors)
        self.cause = cause


def _validate_regular_target(target: Path) -> bool:
    """Return whether *target* exists, rejecting links and special files."""
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        return False

    if stat.S_ISLNK(target_stat.st_mode):
        raise ValueError(f"Refusing command artifact symlink: {target}")
    if not stat.S_ISREG(target_stat.st_mode):
        raise ValueError(f"Command artifact target is not a regular file: {target}")
    return True


def _validate_directory(directory: Path) -> None:
    try:
        directory_stat = directory.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"Command artifact directory does not exist: {directory}") from exc
    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        raise ValueError(f"Command artifact parent is not a real directory: {directory}")


def ensure_private_directory(directory: Path) -> None:
    """Create a service-private artifact directory and reject path substitution."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    _validate_directory(directory)
    directory_stat = directory.stat()
    if directory_stat.st_uid != os.geteuid():
        raise ValueError(
            f"Command artifact directory is owned by uid {directory_stat.st_uid}, "
            f"expected {os.geteuid()}: {directory}"
        )
    # Newly created directories already use this mode. Tighten an existing
    # service-owned directory so payloads never inherit a world-readable path.
    os.chmod(directory, 0o700)


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(directory, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _unique_auxiliary_path(target: Path, kind: str) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{target.name}.{kind}-",
        dir=str(target.parent),
    )
    os.close(fd)
    auxiliary = Path(raw_path)
    auxiliary.unlink()
    return auxiliary


@dataclass
class StagedJsonArtifact:
    """A JSON target staged for reversible replacement or removal."""

    target: Path
    staged_path: Optional[Path]
    purpose: str
    remove_target: bool = False
    backup_path: Optional[Path] = None
    target_existed: bool = False
    installed: bool = False

    def commit(self) -> None:
        """Publish this artifact atomically, preserving the prior file."""
        if self.staged_path is None and not self.remove_target:
            raise RuntimeError(f"Artifact {self.purpose} has no staged payload")

        _validate_directory(self.target.parent)
        self.target_existed = _validate_regular_target(self.target)
        if self.target_existed:
            self.backup_path = _unique_auxiliary_path(self.target, "backup")
            # The hard link is a same-filesystem snapshot of the old inode.
            # It avoids a window where a running reader sees no target.
            os.link(self.target, self.backup_path, follow_symlinks=False)

        if self.remove_target:
            if self.target_existed:
                self.target.unlink()
        else:
            staged_path = self.staged_path
            if staged_path is None:  # defensive narrowing for type checkers
                raise RuntimeError(f"Artifact {self.purpose} has no staged payload")
            os.replace(staged_path, self.target)
            self.staged_path = None
        self.installed = True
        _fsync_directory(self.target.parent)

    def rollback(self) -> None:
        """Restore the exact pre-commit target and remove temporary files."""
        errors: list[BaseException] = []

        if self.installed:
            try:
                if self.target_existed:
                    if self.backup_path is None:
                        raise RuntimeError(f"Missing rollback backup for {self.target}")
                    os.replace(self.backup_path, self.target)
                    self.backup_path = None
                else:
                    self.target.unlink(missing_ok=True)
                _fsync_directory(self.target.parent)
                self.installed = False
            except BaseException as exc:  # preserve every rollback failure for the caller
                errors.append(exc)

        for attribute in ("staged_path", "backup_path"):
            auxiliary = getattr(self, attribute)
            if auxiliary is None:
                continue
            try:
                auxiliary.unlink(missing_ok=True)
                setattr(self, attribute, None)
            except BaseException as exc:
                errors.append(exc)

        if errors:
            detail = "; ".join(str(error) or type(error).__name__ for error in errors)
            raise RuntimeError(f"Artifact rollback failed for {self.purpose}: {detail}")

    def discard(self) -> None:
        """Remove unpublished staging/backup files without touching the target."""
        errors: list[BaseException] = []
        for attribute in ("staged_path", "backup_path"):
            auxiliary = getattr(self, attribute)
            if auxiliary is None:
                continue
            try:
                auxiliary.unlink(missing_ok=True)
                setattr(self, attribute, None)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            detail = "; ".join(str(error) or type(error).__name__ for error in errors)
            raise RuntimeError(f"Artifact cleanup failed for {self.purpose}: {detail}")

    def finalize(self) -> None:
        """Retire rollback material after the surrounding transaction commits."""
        self.discard()


def stage_json_artifact(*, target: Path, payload: Any, purpose: str) -> StagedJsonArtifact:
    """Serialize and fsync JSON without changing the published target."""
    # Serialize first so invalid/non-finite payloads cannot create even a
    # staging file. ``allow_nan=False`` keeps runtime contracts portable.
    serialized = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _validate_directory(target.parent)
    _validate_regular_target(target)

    file_descriptor: Optional[int] = None
    staged_path: Optional[Path] = None
    try:
        file_descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{target.name}.stage-",
            dir=str(target.parent),
        )
        staged_path = Path(raw_path)
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            file_descriptor = None
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        return StagedJsonArtifact(
            target=target,
            staged_path=staged_path,
            purpose=purpose,
        )
    except BaseException:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
        raise


def stage_json_target_removal(*, target: Path, purpose: str) -> StagedJsonArtifact:
    """Prepare a reversible removal without changing the published target."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _validate_directory(target.parent)
    _validate_regular_target(target)
    return StagedJsonArtifact(
        target=target,
        staged_path=None,
        purpose=purpose,
        remove_target=True,
    )


@dataclass
class PreparedCommandInstallation:
    """Pure command plan plus staged, not-yet-visible runtime artifacts."""

    mission: int
    trigger_time: int
    hw_id: str | int
    command_id: Optional[str]
    config_updates: Tuple[Tuple[str, Any], ...]
    artifacts: Tuple[StagedJsonArtifact, ...] = field(default_factory=tuple)
    committed: bool = False

    @property
    def artifact_paths(self) -> Tuple[str, ...]:
        return tuple(str(artifact.target) for artifact in self.artifacts)

    def discard(self) -> None:
        errors: list[BaseException] = []
        for artifact in reversed(self.artifacts):
            try:
                artifact.discard()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            detail = "; ".join(str(error) or type(error).__name__ for error in errors)
            raise RuntimeError(f"Prepared command cleanup failed: {detail}")


@dataclass(frozen=True)
class CommandInstallationResult:
    """Proof returned only after every artifact/config commit step succeeds."""

    committed: bool
    mission: int
    trigger_time: int
    state: int
    command_id: Optional[str]
    artifact_paths: Tuple[str, ...]


def semantic_payload_digest(payload: Any) -> str:
    """Stable short digest used only to isolate runtime artifact filenames."""
    import hashlib

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

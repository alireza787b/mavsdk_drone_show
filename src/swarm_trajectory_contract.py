"""Package identity shared by mission review, dispatch and aircraft execution."""

from pydantic import BaseModel, ConfigDict, Field, field_validator
import hashlib
from pathlib import Path


class SwarmTrajectoryPackage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    revision: str = Field(min_length=1, max_length=128)
    # Generated trajectories are keyed by hardware identity, not show slots.
    files: dict[str, str] = Field(min_length=1)

    @field_validator('files')
    @classmethod
    def validate_files(cls, files):
        for aircraft, digest in files.items():
            if not aircraft.isdecimal() or str(int(aircraft)) != aircraft or int(aircraft) < 1:
                raise ValueError('Trajectory aircraft identities must be positive canonical integers')
            if len(digest) != 64 or any(character not in '0123456789abcdef' for character in digest):
                raise ValueError('Trajectory file identity must be a lowercase SHA-256 digest')
        return files


def verify_local_package(package, hardware_id, trajectory_path):
    """Prove file presence/identity during node prepare/commit, without arming."""
    parsed = SwarmTrajectoryPackage.model_validate(package)
    expected = parsed.files.get(str(hardware_id))
    if expected is None:
        raise ValueError('This aircraft is missing from the reviewed trajectory package')
    try:
        with Path(trajectory_path).open('rb') as source:
            actual = hashlib.file_digest(source, 'sha256').hexdigest()
    except OSError as exc:
        raise ValueError('Reviewed trajectory file is unavailable; synchronize this aircraft') from exc
    if actual != expected:
        raise ValueError('Trajectory file differs from the reviewed package; synchronize and review again')

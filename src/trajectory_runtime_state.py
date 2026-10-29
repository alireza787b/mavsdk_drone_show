"""Bounded observational trajectory progress; never a flight-control channel."""
import json
import logging
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from src.swarm_runtime_state import get_runtime_assignment_path


class TrajectoryRuntimeState(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    command_id: str = Field(min_length=1, max_length=256)
    trajectory_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    phase: Literal['starting', 'takeoff', 'trajectory', 'finishing', 'completed', 'failed']
    trajectory_time_s: float = Field(default=0, ge=0)
    duration_s: float = Field(default=0, ge=0)
    sample_index: int = Field(default=0, ge=0)
    sample_count: int = Field(default=0, ge=0)
    updated_at_ms: int
    updated_monotonic: float
    owner_pid: int
    fresh: bool = False
    progress_kind: Literal['commanded_trajectory'] = 'commanded_trajectory'


def state_path() -> Path:
    return get_runtime_assignment_path().with_name('swarm_trajectory_execution.json')


def read_trajectory_runtime(command_id=None, max_age_s=3):
    try:
        state = TrajectoryRuntimeState.model_validate_json(state_path().read_text())
        if command_id is not None and state.command_id != command_id:
            return None
        age = time.monotonic() - state.updated_monotonic
        state.fresh = 0 <= age <= max_age_s
        return state.model_dump()
    except (OSError, ValueError):
        return None


class TrajectoryProgressRecorder:
    def __init__(self, command_id, digest):
        self.command_id, self.digest = command_id, digest
        self.last_write = -float('inf')
        self.last_phase = None
        self.warned = False
        self.last_values = dict(trajectory_time_s=0, duration_s=0, sample_index=0, sample_count=0)

    def report(self, phase, *, trajectory_time_s=None, duration_s=None, sample_index=None, sample_count=None):
        if not self.command_id or not self.digest:
            return
        now = time.monotonic()
        if phase == self.last_phase and now - self.last_write < 1:
            return
        temporary = None
        try:
            values = {**self.last_values, **{key: value for key, value in dict(
                trajectory_time_s=trajectory_time_s, duration_s=duration_s,
                sample_index=sample_index, sample_count=sample_count).items() if value is not None}}
            state = TrajectoryRuntimeState(
                command_id=self.command_id, trajectory_sha256=self.digest, phase=phase,
                **values,
                updated_at_ms=int(time.time() * 1000), updated_monotonic=now, owner_pid=os.getpid())
            path = state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile('w', dir=path.parent, prefix='.trajectory-progress-', delete=False) as output:
                temporary = output.name
                output.write(state.model_dump_json())
            os.replace(temporary, path)
            self.last_write, self.last_phase = now, phase
            self.last_values = values
        except (OSError, ValueError):
            if not self.warned:
                logging.getLogger(__name__).warning('Trajectory progress reporting unavailable; flight control is unaffected')
                self.warned = True
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

#!/usr/bin/env python3
# src/drone_setup.py

import asyncio
import os
import signal
import shlex
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from typing import Optional, Union

import aiohttp

from mds_logging import get_logger
from src.action_safety import ACTION_PROCESS_CLEANUP_GRACE_SEC
from src.action_result_protocol import (
    ACTION_RESULT_FD_ENV,
    extract_terminal_result,
    format_legacy_diagnostics,
    read_bounded_result_fd,
)
from src.command_execution_contract import (
    DroneExecutionOutcome,
    format_superseded_execution_error,
    is_legacy_schema_outcome_rejection,
    validate_execution_outcome,
)
from src.enums import Mission, State  # Ensure this import contains the necessary Mission and State enums
from src.gcs_api_routes import (
    GCS_COMMAND_REPORT_CAPABILITY_HEADER,
    GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE,
    GCS_COMMAND_REPORT_EXECUTION_START_ROUTE,
)
from src.gcs_auth_client import gcs_auth_headers

logger = get_logger("drone_setup")

ManagedProcess = Union[asyncio.subprocess.Process, subprocess.Popen]


@dataclass
class RunningMissionProcess:
    """Track a launched mission process and its execution-report context."""
    process_key: str
    script_name: str
    process: ManagedProcess
    command_id: Optional[str] = None
    mission_type: Optional[int] = None
    trigger_time: int = 0
    superseded: bool = False
    # Mission children are launched in their own POSIX session.  Owning the
    # process group lets an override stop helper processes as well as the
    # Python parent, instead of leaving a stale setpoint publisher behind.
    process_group_owned: bool = False
    action_result_read_fd: Optional[int] = None
    forced_kill_cleanup_unconfirmed: bool = False
    forced_stop_mode: Optional[str] = None
    # A process key is intentionally human-readable and may be reused by a
    # duplicate command delivery.  State ownership therefore uses a separate
    # opaque token so a late monitor can never mistake a replacement record
    # with the same key for the process it originally launched.
    ownership_token: str = dataclass_field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class AcceptedCommandClaim:
    """Exact accepted-command identity owned by one scheduler handler tick."""

    command_id: Optional[str]
    mission_type: int
    trigger_time: int = 0
    ground_test_request_file: Optional[str] = None


@dataclass
class PendingCommandReport:
    """Queued drone -> GCS callback that can be retried safely."""
    endpoint: str
    payload: dict
    description: str
    first_queued_monotonic: float
    next_attempt_monotonic: float
    # Kept outside the JSON payload so it cannot be rendered or accidentally
    # persisted with operator-visible execution details.
    capability: Optional[str] = dataclass_field(default=None, repr=False)
    attempt_count: int = 0


class PermanentCommandReportRejection(RuntimeError):
    """A callback response that retrying with the same identity cannot repair."""

    def __init__(self, status: int):
        self.status = int(status)
        super().__init__(f"GCS rejected command callback with HTTP {self.status}")


@dataclass
class RecentCommandRecord:
    """Recent terminal command metadata for idempotent duplicate delivery."""
    command_id: str
    mission_type: int
    trigger_time: int
    phase: str
    state: int
    recorded_at_monotonic: float


class ProcessStopMode(str, Enum):
    """How aggressively a replacement command must stop the active controller."""

    NORMAL = "normal"
    RECOVERY = "recovery"
    EMERGENCY = "emergency"


@dataclass
class ProcessStopSummary:
    """Observed outcome of stopping the node's currently registered controllers."""

    attempted: int = 0
    graceful: int = 0
    killed: int = 0
    already_stopped: int = 0
    unresolved: int = 0
    cleanup_unconfirmed: int = 0


class DroneSetup:
    """
    DroneSetup manages execution of drone missions (drone shows, takeoff, landing, etc.) via mission scripts.
    - Only one mission runs at a time.
    - Can override/interrupt an existing mission if needed.
    - Logs success/failure with detailed info.
    """

    def __init__(self, params, drone_config):
        """
        Args:
            params: Configuration parameters (must include 'trigger_sooner_seconds', etc.).
            drone_config: Object holding current mission, state, and related config.
        """
        self.params = params
        self.drone_config = drone_config

        # For preventing repeated logs about the same mission/state changes:
        self.last_logged_mission = None
        self.last_logged_state = None

        # Track currently running processes {process_key: RunningMissionProcess}
        self.running_processes = {}
        self.process_lock = asyncio.Lock()  # Ensures concurrency safety around process operations
        self.pending_command_reports = []
        self.command_report_lock = asyncio.Lock()
        self.command_report_retry_task = None
        self.recent_command_history = {}
        self.recent_command_history_lock = threading.RLock()
        self._command_report_capabilities = {}
        self._active_mission_owner_token: Optional[str] = None
        self._active_mission_command_id: Optional[str] = None
        self._active_scheduler_claim: Optional[AcceptedCommandClaim] = None
        shared_state_lock = getattr(drone_config, "command_state_transaction_lock", None)
        if not (
            callable(getattr(shared_state_lock, "acquire", None))
            and callable(getattr(shared_state_lock, "release", None))
        ):
            shared_state_lock = threading.Lock()
            setattr(drone_config, "command_state_transaction_lock", shared_state_lock)
        self.command_state_transaction_lock = shared_state_lock

        self._validate_params()
        self._validate_drone_config()

        # Map mission codes to handler functions
        self.mission_handlers = {
            Mission.NONE.value: self._handle_no_mission,
            Mission.DRONE_SHOW_FROM_CSV.value: self._execute_standard_drone_show,
            Mission.CUSTOM_CSV_DRONE_SHOW.value: self._execute_custom_drone_show,
            Mission.HOVER_TEST.value: self._execute_hover_test,
            Mission.SMART_SWARM.value: self._execute_smart_swarm,
            Mission.SWARM_TRAJECTORY.value: self._execute_swarm_trajectory,
            Mission.QUICKSCOUT.value: self._execute_quickscout,
            Mission.TAKE_OFF.value: self._execute_takeoff,
            Mission.LAND.value: self._execute_land,
            Mission.RETURN_RTL.value: self._execute_return_rtl,
            Mission.KILL_TERMINATE.value: self._execute_kill_terminate,
            Mission.HOLD.value: self._execute_hold,
            Mission.TEST.value: self._execute_test,
            Mission.REBOOT_FC.value: self._execute_reboot_fc,
            Mission.REBOOT_SYS.value: self._execute_reboot_sys,
            Mission.TEST_LED.value: self._execute_test_led,
            Mission.UPDATE_CODE.value: self._execute_update_code,
            Mission.PRECISION_MOVE.value: self._execute_precision_move,
        }

    def _validate_params(self):
        """
        Validate that required parameters exist and have correct types.

        Checks for 'trigger_sooner_seconds' and converts string values to numeric.

        Raises:
            AttributeError: If required parameter is missing.
            TypeError: If parameter has invalid type.
        """
        required_attrs = {
            'trigger_sooner_seconds': (int, float, str)
        }

        for attr, expected_types in required_attrs.items():
            if not hasattr(self.params, attr):
                logger.error(f"Missing required attribute '{attr}' in params.")
                raise AttributeError(f"params object must have '{attr}'")

            attr_value = getattr(self.params, attr)

            if isinstance(attr_value, str):
                try:
                    converted_value = float(attr_value) if '.' in attr_value else int(attr_value)
                    setattr(self.params, attr, converted_value)
                    logger.info(f"Converted params.{attr} from str to {type(converted_value).__name__}.")
                except ValueError:
                    logger.error(f"Attribute '{attr}' must be numeric, got '{attr_value}'.")
                    raise TypeError(f"'{attr}' must be numeric.")
            elif not isinstance(attr_value, expected_types[:-1]):
                logger.error(f"'{attr}' must be int or float, got {type(attr_value).__name__}.")
                raise TypeError(f"'{attr}' must be int or float.")

    def _validate_drone_config(self):
        """
        Validate that drone_config has required attributes with correct types.

        Checks for 'trigger_time' and mission-specific attributes.
        Converts string values to numeric types as needed.

        Raises:
            AttributeError: If required attribute is missing.
            TypeError: If attribute has invalid type.
        """
        required_attrs = {
            'trigger_time': (int, float, str)
        }

        # Additional validation for UPDATE_CODE mission
        if self.drone_config.mission == Mission.UPDATE_CODE.value:
            required_attrs['update_branch'] = (str,)

        for attr, expected_types in required_attrs.items():
            if not hasattr(self.drone_config, attr):
                logger.error(f"Missing required attribute '{attr}' in drone_config.")
                raise AttributeError(f"drone_config must have '{attr}'")

            attr_value = getattr(self.drone_config, attr)

            if isinstance(attr_value, str) and expected_types != (str,):
                try:
                    converted_value = float(attr_value) if '.' in attr_value else int(attr_value)
                    setattr(self.drone_config, attr, converted_value)
                    logger.info(f"Converted drone_config.{attr} from str to {type(converted_value).__name__}.")
                except ValueError:
                    logger.error(f"Attribute '{attr}' must be numeric, got '{attr_value}'.")
                    raise TypeError(f"'{attr}' must be numeric.")
            elif not isinstance(attr_value, expected_types):
                logger.error(f"'{attr}' must be of type {expected_types}, got {type(attr_value).__name__}.")
                raise TypeError(f"'{attr}' must be {expected_types}.")

    def _get_python_exec_path(self) -> str:
        """
        Get the path to the Python executable in the project's virtual environment.

        Returns:
            str: Absolute path to the Python interpreter.
        """
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'venv', 'bin', 'python')

    def _get_script_path(self, script_name: str) -> str:
        """
        Get the absolute path to a mission script.

        Args:
            script_name: Relative path to the script from project root.

        Returns:
            str: Absolute path to the script file.
        """
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', script_name)

    @staticmethod
    def _is_asyncio_process(process: ManagedProcess) -> bool:
        wait_method = getattr(process, "wait", None)
        communicate_method = getattr(process, "communicate", None)
        return (
            isinstance(process, asyncio.subprocess.Process)
            or asyncio.iscoroutinefunction(wait_method)
            or asyncio.iscoroutinefunction(communicate_method)
        )

    async def _wait_for_process(self, process: ManagedProcess, timeout: Optional[float] = None):
        if self._is_asyncio_process(process):
            wait_coro = process.wait()
            if timeout is None:
                return await wait_coro
            return await asyncio.wait_for(wait_coro, timeout=timeout)

        def _wait_blocking():
            return process.wait(timeout=timeout)

        try:
            return await asyncio.to_thread(_wait_blocking)
        except subprocess.TimeoutExpired as exc:
            raise asyncio.TimeoutError from exc

    async def _communicate_with_process(self, process: ManagedProcess):
        if self._is_asyncio_process(process):
            return await process.communicate()
        return await asyncio.to_thread(process.communicate)

    def _process_stop_grace_seconds(
        self,
        mode: ProcessStopMode,
        record: RunningMissionProcess | None = None,
    ) -> float:
        """Return a bounded, action-aware grace period.

        TAKE_OFF and TEST own post-arm safety cleanup. A routine or recovery
        replacement lets their cooperative signal handler finish that fixed
        cleanup budget; an emergency override remains immediate by definition.
        """
        policy = {
            ProcessStopMode.NORMAL: ("MISSION_PROCESS_STOP_GRACE_SEC", 5.0, 30.0),
            ProcessStopMode.RECOVERY: ("RECOVERY_PROCESS_STOP_GRACE_SEC", 0.20, 1.0),
            ProcessStopMode.EMERGENCY: ("EMERGENCY_PROCESS_STOP_GRACE_SEC", 0.0, 0.0),
        }
        attribute, default, maximum = policy[mode]
        try:
            configured = float(getattr(self.params, attribute, default))
        except (TypeError, ValueError):
            configured = default
        configured_grace = max(0.0, min(configured, maximum))
        safety_cleanup_action = bool(
            record is not None
            and record.mission_type in {Mission.TAKE_OFF.value, Mission.TEST.value}
        )
        if safety_cleanup_action and mode is not ProcessStopMode.EMERGENCY:
            return max(configured_grace, ACTION_PROCESS_CLEANUP_GRACE_SEC)
        return configured_grace

    @staticmethod
    def _coerce_process_record(process_key: str, value) -> RunningMissionProcess:
        """Adapt legacy registry values without weakening new ownership metadata."""
        if isinstance(value, RunningMissionProcess):
            return value
        # Older integrations stored record-like objects without using the
        # dataclass. Preserve their identity so setting ``superseded`` is
        # visible to their monitor. A raw subprocess/mock does not have stable
        # string record metadata and is wrapped below.
        if (
            isinstance(getattr(value, "process_key", None), str)
            and isinstance(getattr(value, "script_name", None), str)
            and getattr(value, "process", None) is not None
        ):
            return value
        return RunningMissionProcess(
            process_key=process_key,
            script_name=str(getattr(value, "script_name", process_key)),
            process=getattr(value, "process", value),
        )

    @staticmethod
    def _signal_process(record: RunningMissionProcess, *, force: bool) -> bool:
        """Signal one owned process group, falling back to its direct child."""
        process = record.process
        signal_number = signal.SIGKILL if force else signal.SIGTERM
        if getattr(record, "process_group_owned", False) is True and getattr(process, "pid", None):
            try:
                os.killpg(int(process.pid), signal_number)
                return True
            except ProcessLookupError:
                return True
            except (OSError, TypeError, ValueError) as exc:
                logger.warning(
                    "Could not signal mission process group for '%s'; falling back to child: %s",
                    record.script_name,
                    exc,
                )

        try:
            if force:
                process.kill()
            else:
                process.terminate()
            return True
        except ProcessLookupError:
            return True
        except Exception as exc:
            logger.error(
                "Could not %s mission process '%s' (PID %s): %s",
                "kill" if force else "terminate",
                record.script_name,
                getattr(process, "pid", "unknown"),
                exc,
            )
            return False

    async def terminate_all_running_processes(
        self,
        *,
        reset_state: bool = True,
        mode: ProcessStopMode = ProcessStopMode.NORMAL,
    ) -> ProcessStopSummary:
        """
        Stop all currently running mission process groups under a bounded policy.

        Normal replacement keeps the historical graceful-shutdown budget.
        Recovery commands wait only a short bounded grace period before
        SIGKILL, and emergency termination skips the grace period entirely.
        This prevents LAND/RTL/HOLD/KILL from waiting behind a five-second
        mission-script shutdown while still ensuring the old controller has
        been signalled before a replacement controller starts.

        When a newer mission has already been staged on drone_config, callers
        can pass reset_state=False so the superseded process is terminated
        without clobbering the replacement mission metadata.
        """
        if not isinstance(mode, ProcessStopMode):
            mode = ProcessStopMode(mode)

        summary = ProcessStopSummary()
        should_reset_owned_state = False
        async with self.process_lock:
            for process_key, registry_value in list(self.running_processes.items()):
                record = self._coerce_process_record(process_key, registry_value)
                script_name = record.script_name
                process = record.process
                record.superseded = True
                summary.attempted += 1
                grace_seconds = self._process_stop_grace_seconds(mode, record)
                if process.returncode is None:
                    stopped = False
                    if grace_seconds > 0:
                        logger.warning(
                            "Stopping mission controller '%s' (key=%s, PID=%s, mode=%s, grace=%.2fs)",
                            script_name,
                            process_key,
                            getattr(process, "pid", "unknown"),
                            mode.value,
                            grace_seconds,
                        )
                        terminate_sent = self._signal_process(record, force=False)
                        if terminate_sent:
                            try:
                                await self._wait_for_process(process, timeout=grace_seconds)
                                stopped = True
                                summary.graceful += 1
                                logger.info("Mission controller '%s' stopped gracefully.", script_name)
                            except asyncio.TimeoutError:
                                logger.warning(
                                    "Mission controller '%s' exceeded the %.2fs %s grace period.",
                                    script_name,
                                    grace_seconds,
                                    mode.value,
                                )

                    if not stopped:
                        kill_sent = self._signal_process(record, force=True)
                        if kill_sent:
                            # SIGKILL prevents further userspace control immediately.
                            # The existing process monitor owns pipe draining/reaping;
                            # recovery dispatch must not wait for that bookkeeping.
                            summary.killed += 1
                            if record.mission_type in {
                                Mission.TAKE_OFF.value,
                                Mission.TEST.value,
                            }:
                                record.forced_kill_cleanup_unconfirmed = True
                                record.forced_stop_mode = mode.value
                                summary.cleanup_unconfirmed += 1
                            logger.warning(
                                "Mission controller '%s' was force-stopped for %s override.",
                                script_name,
                                mode.value,
                            )
                        else:
                            summary.unresolved += 1
                            logger.critical(
                                "Mission controller '%s' could not be stopped; a competing controller may remain active.",
                                script_name,
                            )

                else:
                    summary.already_stopped += 1
                    logger.debug(f"Process '{script_name}' already ended.")

                # Re-check after the awaited termination. A replacement may
                # have been registered by a future caller that does not honor
                # process_lock; a stale pre-wait boolean must never clear it.
                still_owns_mission_state = (
                    self._active_mission_owner_token == getattr(record, "ownership_token", None)
                )
                current_command_id = self._normalize_command_id(
                    getattr(self.drone_config, "current_command_id", None)
                )
                has_newer_pending_command = bool(
                    current_command_id
                    and current_command_id != getattr(record, "command_id", None)
                )
                try:
                    has_newer_pending_state = (
                        int(getattr(self.drone_config, "state", State.IDLE.value))
                        == State.MISSION_READY.value
                    )
                except (TypeError, ValueError):
                    has_newer_pending_state = False
                if (
                    reset_state
                    and still_owns_mission_state
                    and not has_newer_pending_command
                    and not has_newer_pending_state
                ):
                    # Reset once after every exact record has been detached.
                    # A cancel/override command staged under the shared
                    # transaction lock is a newer owner and must survive.
                    should_reset_owned_state = True
                if still_owns_mission_state:
                    self._active_mission_owner_token = None
                    self._active_mission_command_id = None
                # Never clear the whole registry: a replacement with a reused
                # human-readable key may have been installed while an awaited
                # process termination completed. Only detach this exact record.
                if self.running_processes.get(process_key) is registry_value:
                    self.running_processes.pop(process_key, None)

        if should_reset_owned_state:
            self._reset_mission_state(success=False)
        return summary

    @staticmethod
    def _normalize_command_id(command_id: Optional[str]) -> Optional[str]:
        if command_id is None:
            return None
        normalized = str(command_id).strip()
        return normalized or None

    def _capture_current_command_claim(self) -> AcceptedCommandClaim:
        """Snapshot the exact command identity currently visible to the scheduler."""
        return AcceptedCommandClaim(
            command_id=self._normalize_command_id(
                getattr(self.drone_config, "current_command_id", None)
            ),
            mission_type=int(getattr(self.drone_config, "mission", Mission.NONE.value)),
            trigger_time=int(getattr(self.drone_config, "trigger_time", 0) or 0),
            ground_test_request_file=getattr(
                self.drone_config,
                "ground_test_request_file",
                None,
            ),
        )

    def _claim_still_current(self, claim: AcceptedCommandClaim) -> bool:
        """Compare a handler claim with current shared command state."""
        return (
            self._normalize_command_id(
                getattr(self.drone_config, "current_command_id", None)
            )
            == claim.command_id
            and int(getattr(self.drone_config, "mission", Mission.NONE.value))
            == claim.mission_type
            and getattr(self.drone_config, "ground_test_request_file", None)
            == claim.ground_test_request_file
        )

    def _claim_for_current_work(self) -> AcceptedCommandClaim:
        """Use the scheduler's original claim, or capture direct-call state."""
        return self._active_scheduler_claim or self._capture_current_command_claim()

    def _detach_current_command_id(
        self,
        expected_claim: Optional[AcceptedCommandClaim] = None,
    ) -> Optional[str]:
        """CAS-detach only the command ID owned by this handler.

        The scheduler normally supplies its claim through
        ``_active_scheduler_claim``.  Keeping the comparison here prevents an
        old handler from detaching a replacement command even if it is invoked
        directly by a future integration outside ``schedule_mission``.
        """
        claim = expected_claim or self._claim_for_current_work()
        if not self._claim_still_current(claim):
            logger.warning(
                "Refusing to detach command ownership because scheduler claim changed "
                "(claimed_command_id=%s, claimed_mission=%s, current_command_id=%s, current_mission=%s).",
                claim.command_id,
                claim.mission_type,
                getattr(self.drone_config, "current_command_id", None),
                getattr(self.drone_config, "mission", None),
            )
            return None

        command_id = getattr(self.drone_config, 'current_command_id', None)
        if command_id is not None:
            self.drone_config.current_command_id = None
        return self._normalize_command_id(command_id)

    def _build_process_key(self, script_name: str, command_id: Optional[str]) -> str:
        suffix = command_id or str(time.time_ns())
        return f"{script_name}:{suffix}"

    def register_command_report_capability(
        self,
        command_id: Optional[str],
        capability: Optional[str],
    ) -> None:
        """Bind one opaque GCS callback capability to an accepted command.

        The node keeps this only in memory and never returns it through ACK,
        status, or log payloads.  Missing values remain compatible with the
        first, nodes-only stage of a rolling upgrade; once the GCS is upgraded,
        every newly dispatched command contains a capability.
        """
        normalized_command_id = self._normalize_command_id(command_id)
        if normalized_command_id is None or capability is None:
            return
        if (
            type(capability) is not str
            or capability != capability.strip()
            or not 43 <= len(capability) <= 200
        ):
            raise ValueError("Invalid command report capability")

        with self.recent_command_history_lock:
            self._command_report_capabilities[normalized_command_id] = (
                capability,
                time.monotonic(),
            )
            self._prune_command_report_capabilities_locked()

    def _prune_command_report_capabilities_locked(self) -> None:
        """Bound secret retention while preserving current process owners."""
        try:
            max_age_sec = max(
                60.0,
                float(getattr(self.params, "COMMAND_REPORT_RETRY_MAX_AGE_SEC", 1800)),
            )
        except (TypeError, ValueError):
            max_age_sec = 1800.0
        try:
            max_records = max(
                32,
                int(getattr(self.params, "COMMAND_IDEMPOTENCY_MAX_HISTORY", 256)),
            )
        except (TypeError, ValueError):
            max_records = 256

        protected_ids = {
            self._normalize_command_id(getattr(self.drone_config, "current_command_id", None)),
            self._normalize_command_id(self._active_mission_command_id),
        }
        protected_ids.discard(None)
        now_monotonic = time.monotonic()
        expired_ids = [
            command_id
            for command_id, (_capability, registered_at) in self._command_report_capabilities.items()
            if command_id not in protected_ids
            and now_monotonic - registered_at > max_age_sec
        ]
        for command_id in expired_ids:
            self._command_report_capabilities.pop(command_id, None)

        while len(self._command_report_capabilities) > max_records:
            oldest_unprotected = next(
                (
                    command_id
                    for command_id in self._command_report_capabilities
                    if command_id not in protected_ids
                ),
                None,
            )
            if oldest_unprotected is None:
                break
            self._command_report_capabilities.pop(oldest_unprotected, None)

    def _get_command_report_capability(self, command_id: Optional[str]) -> Optional[str]:
        normalized_command_id = self._normalize_command_id(command_id)
        if normalized_command_id is None:
            return None
        with self.recent_command_history_lock:
            # Read and refresh before pruning. A legitimate mission may run
            # longer than the retry retention window; its terminal callback
            # still needs the capability issued at dispatch. Moving the entry
            # to the end also makes the bounded-cap eviction least-recently-used
            # without ever placing the secret in callback JSON or logs.
            entry = self._command_report_capabilities.pop(
                normalized_command_id,
                None,
            )
            if entry is not None:
                self._command_report_capabilities[normalized_command_id] = (
                    entry[0],
                    time.monotonic(),
                )
            self._prune_command_report_capabilities_locked()
            return entry[0] if entry else None

    def _prune_recent_command_history(self, now_monotonic: Optional[float] = None):
        """Prune bounded lifecycle history while retaining active owners.

        Callers hold ``recent_command_history_lock``.  Active records are few
        because the runtime permits one mission owner, and are never evicted to
        satisfy the history cap while they are needed for replay safety.
        """
        now_monotonic = now_monotonic if now_monotonic is not None else time.monotonic()
        try:
            ttl_sec = max(
                60.0,
                float(getattr(self.params, "COMMAND_IDEMPOTENCY_HISTORY_SEC", 1800)),
            )
        except (TypeError, ValueError):
            ttl_sec = 1800.0
        try:
            max_records = max(
                32,
                int(getattr(self.params, "COMMAND_IDEMPOTENCY_MAX_HISTORY", 256)),
            )
        except (TypeError, ValueError):
            max_records = 256

        protected_command_ids = {
            self._normalize_command_id(getattr(self.drone_config, "current_command_id", None)),
            self._normalize_command_id(self._active_mission_command_id),
        }
        protected_command_ids.discard(None)

        expired_ids = [
            command_id
            for command_id, record in self.recent_command_history.items()
            if command_id not in protected_command_ids
            and (now_monotonic - record.recorded_at_monotonic) > ttl_sec
        ]
        for command_id in expired_ids:
            self.recent_command_history.pop(command_id, None)

        while len(self.recent_command_history) > max_records:
            oldest_command_id = next(
                (
                    command_id
                    for command_id in self.recent_command_history
                    if command_id not in protected_command_ids
                ),
                None,
            )
            if oldest_command_id is None:
                break
            self.recent_command_history.pop(oldest_command_id, None)

    def _remember_recent_command(
        self,
        command_id: Optional[str],
        *,
        mission_type: Optional[int],
        trigger_time: int = 0,
        phase: str,
        state: int = State.IDLE.value,
    ):
        if not command_id or mission_type is None:
            return

        now_monotonic = time.monotonic()
        normalized_command_id = self._normalize_command_id(command_id)
        if normalized_command_id is None:
            return
        with self.recent_command_history_lock:
            self._prune_recent_command_history(now_monotonic)
            self.recent_command_history[normalized_command_id] = RecentCommandRecord(
                command_id=normalized_command_id,
                mission_type=int(mission_type),
                trigger_time=int(trigger_time or 0),
                phase=phase,
                state=int(state),
                recorded_at_monotonic=now_monotonic,
            )
            self._prune_recent_command_history(now_monotonic)

    def get_recent_command_record(self, command_id: Optional[str]) -> Optional[dict]:
        if not command_id:
            return None

        normalized_command_id = self._normalize_command_id(command_id)
        if normalized_command_id is None:
            return None
        now_monotonic = time.monotonic()
        with self.recent_command_history_lock:
            self._prune_recent_command_history(now_monotonic)
            record = self.recent_command_history.get(normalized_command_id)
            if record is None:
                return None

            return {
                'mission_type': int(record.mission_type),
                'trigger_time': int(record.trigger_time),
                'state': int(record.state),
                'phase': str(record.phase),
            }

    async def execute_mission_script(self, script_name: str, action: str) -> tuple:
        """
        Launches a mission script asynchronously (so it won't block new commands).
        A background task `_monitor_script_process` will watch its completion.
        """
        async with self.process_lock:
            if self._active_mission_owner_token is not None:
                message = (
                    "Another mission process still owns execution state; "
                    "the new subprocess was not launched."
                )
                logger.error(message)
                return (False, message)

            python_exec_path = self._get_python_exec_path()
            script_path = self._get_script_path(script_name)
            command_claim = self._claim_for_current_work()
            if not self._claim_still_current(command_claim):
                message = (
                    "Mission ownership changed before the subprocess could be launched; "
                    "the stale handler was not executed."
                )
                logger.warning(message)
                return (False, message)

            command_id = self._detach_current_command_id(command_claim)
            mission_type = command_claim.mission_type
            self._remember_recent_command(
                command_id,
                mission_type=mission_type,
                trigger_time=command_claim.trigger_time,
                phase="launching",
                state=State.MISSION_EXECUTING.value,
            )

            if not os.path.isfile(script_path):
                logger.error(f"Mission script '{script_name}' not found at '{script_path}'.")
                self._reset_mission_state(success=False)
                await self._report_execution_to_gcs(
                    command_id=command_id,
                    success=False,
                    error_message=f"Script '{script_name}' not found."
                )
                self._remember_recent_command(
                    command_id,
                    mission_type=mission_type,
                    trigger_time=command_claim.trigger_time,
                    phase="failed",
                )
                return (False, f"Script '{script_name}' not found.")

            raw_args = action if isinstance(action, list) else action.split()
            command = [str(python_exec_path), str(script_path), *[str(arg) for arg in raw_args]]
            logger.info(f"Executing mission script asynchronously: {shlex.join(command)}")

            action_result_read_fd = None
            action_result_write_fd = None
            try:
                process_kwargs = {
                    "stdout": asyncio.subprocess.PIPE,
                    "stderr": asyncio.subprocess.PIPE,
                    # Own the complete mission process group so a recovery
                    # override cannot leave helper children publishing stale
                    # setpoints after the Python parent exits.
                    "start_new_session": True,
                }
                # actions.py owns a versioned terminal-result contract.  Keep
                # it separate from human/logging stdout and stderr so native
                # LED/SPI diagnostics cannot mask a PX4 command result.
                if os.path.basename(script_path) == "actions.py":
                    action_result_read_fd, action_result_write_fd = os.pipe()
                    child_env = os.environ.copy()
                    child_env[ACTION_RESULT_FD_ENV] = str(action_result_write_fd)
                    process_kwargs.update(
                        env=child_env,
                        pass_fds=(action_result_write_fd,),
                    )
                try:
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        **process_kwargs,
                    )
                except NotImplementedError:
                    logger.warning(
                        f"Async subprocess execution is unavailable. Falling back to subprocess.Popen for '{script_name}'."
                    )
                    popen_kwargs = dict(process_kwargs)
                    popen_kwargs["stdout"] = subprocess.PIPE
                    popen_kwargs["stderr"] = subprocess.PIPE
                    process = subprocess.Popen(
                        command,
                        **popen_kwargs,
                    )
                if action_result_write_fd is not None:
                    os.close(action_result_write_fd)
                    action_result_write_fd = None
                process_key = self._build_process_key(script_name, command_id)
                process_record = RunningMissionProcess(
                    process_key=process_key,
                    script_name=script_name,
                    process=process,
                    command_id=command_id,
                    mission_type=mission_type,
                    trigger_time=command_claim.trigger_time,
                    process_group_owned=True,
                    action_result_read_fd=action_result_read_fd,
                )
                self.running_processes[process_key] = process_record
                self._active_mission_owner_token = process_record.ownership_token
                self._active_mission_command_id = command_id
                self._remember_recent_command(
                    command_id,
                    mission_type=mission_type,
                    trigger_time=command_claim.trigger_time,
                    phase="executing",
                    state=State.MISSION_EXECUTING.value,
                )
            except Exception as e:
                for result_fd in (action_result_write_fd, action_result_read_fd):
                    if result_fd is not None:
                        try:
                            os.close(result_fd)
                        except OSError:
                            pass
                logger.error(f"Exception running '{script_name}': {e}", exc_info=True)
                self._reset_mission_state(success=False)
                await self._report_execution_to_gcs(
                    command_id=command_id,
                    success=False,
                    error_message=f"Exception: {str(e)}"
                )
                self._remember_recent_command(
                    command_id,
                    mission_type=mission_type,
                    trigger_time=command_claim.trigger_time,
                    phase="failed",
                )
                return (False, f"Exception: {str(e)}")

        # Do not hold the scheduler/API state transaction while waiting on a
        # GCS callback. A slow or unavailable GCS must never delay a safety
        # override. Start reporting and pipe draining concurrently; the
        # monitor waits for the start-report attempt before publishing a
        # terminal result, preserving callback order for very short actions.
        execution_start_task = asyncio.create_task(
            self._report_execution_start_to_gcs(
                command_id=command_id,
                script_name=script_name,
            )
        )
        asyncio.create_task(
            self._monitor_script_process(
                process_record,
                execution_start_task=execution_start_task,
            )
        )

        # Return immediately - do NOT block on process.communicate()
        return (True, f"Started mission script '{script_name}' asynchronously.")

    async def _acquire_command_state_transaction_lock(self) -> None:
        """Acquire the cross-thread state lock without orphaning a waiter.

        Cancelling ``asyncio.to_thread(lock.acquire)`` does not stop its worker.
        Shielding and then releasing on cancellation prevents that worker from
        acquiring the lock later and permanently blocking future commands.
        """
        acquire_task = asyncio.create_task(
            asyncio.to_thread(self.command_state_transaction_lock.acquire)
        )
        try:
            acquired = await asyncio.shield(acquire_task)
        except asyncio.CancelledError:
            acquired = await acquire_task
            if acquired:
                self.command_state_transaction_lock.release()
            raise
        if not acquired:
            raise RuntimeError("Failed to acquire command-state transaction lock")

    async def _retire_process_and_update_state(
        self,
        process_record: RunningMissionProcess,
        *,
        reset_success: Optional[bool],
    ) -> tuple[bool, str]:
        """Detach one exact process and CAS-reset state only for its owner.

        Both HTTP acceptance and scheduling use the same transaction lock, so
        ownership comparison plus reset is indivisible. The opaque process
        token protects against key reuse; ``current_command_id`` protects a
        replacement accepted before its subprocess is launched.
        """
        await self._acquire_command_state_transaction_lock()
        try:
            async with self.process_lock:
                registered_record = self.running_processes.get(process_record.process_key)
                exact_record_registered = registered_record is process_record
                if exact_record_registered:
                    self.running_processes.pop(process_record.process_key, None)

                owns_execution_state = (
                    self._active_mission_owner_token == process_record.ownership_token
                )
                current_command_id = self._normalize_command_id(
                    getattr(self.drone_config, "current_command_id", None)
                )
                has_newer_pending_command = bool(
                    current_command_id
                    and current_command_id != process_record.command_id
                )
                try:
                    current_state = int(getattr(self.drone_config, "state", State.IDLE.value))
                except (TypeError, ValueError):
                    current_state = State.IDLE.value
                has_newer_pending_state = current_state == State.MISSION_READY.value

                mission_still_matches = True
                if process_record.mission_type is not None:
                    try:
                        mission_still_matches = (
                            int(getattr(self.drone_config, "mission", Mission.NONE.value))
                            == int(process_record.mission_type)
                        )
                    except (TypeError, ValueError):
                        mission_still_matches = False

                if owns_execution_state:
                    self._active_mission_owner_token = None
                    self._active_mission_command_id = None

                if process_record.superseded:
                    return False, "process was explicitly superseded"
                if not exact_record_registered:
                    return False, "process registry now contains a different owner"
                if not owns_execution_state:
                    return False, "a different process owns mission state"
                if has_newer_pending_command:
                    return False, "a newer accepted command owns pending state"
                if has_newer_pending_state:
                    return False, "mission state contains pending work not owned by this process"
                if not mission_still_matches:
                    return False, "mission state belongs to a different mission"
                if reset_success is None:
                    return False, "caller requested detach without state reset"

                self._reset_mission_state(success=reset_success)
                return True, "exact process owner retired and reset mission state"
        finally:
            self.command_state_transaction_lock.release()

    @staticmethod
    async def _await_execution_start_report_task(
        execution_start_task: Optional[asyncio.Task],
        script_name: str,
    ) -> None:
        """Preserve callback ordering without turning reporting faults into flight faults."""
        if execution_start_task is None:
            return
        try:
            await execution_start_task
        except Exception as exc:
            # The reporting coroutine already handles expected network errors.
            # An unexpected task failure is still evidence-worthy, but cannot
            # rewrite the independently observed child-process result.
            logger.error(
                "Execution-start reporting task failed unexpectedly for '%s': %s",
                script_name,
                exc,
                exc_info=True,
            )

    async def _monitor_script_process(
        self,
        process_record: RunningMissionProcess,
        *,
        execution_start_task: Optional[asyncio.Task] = None,
    ):
        """
        Monitors the lifetime of the subprocess for a given script.
        Cleans up upon completion, sets mission state accordingly.
        Reports execution result to GCS if command_id is available.
        """
        script_name = process_record.script_name
        process = process_record.process
        start_time = time.time()
        result_reader_task = None
        try:
            if process_record.action_result_read_fd is not None:
                result_reader_task = asyncio.create_task(
                    asyncio.to_thread(
                        read_bounded_result_fd,
                        process_record.action_result_read_fd,
                    )
                )
            stdout, stderr = await self._communicate_with_process(process)
            dedicated_result_payload = (
                await result_reader_task if result_reader_task is not None else b""
            )
            await self._await_execution_start_report_task(
                execution_start_task,
                script_name,
            )
            process_record.action_result_read_fd = None
            return_code = process.returncode
            action_result = extract_terminal_result(
                dedicated_payload=dedicated_result_payload,
                stdout=stdout,
            )
            legacy_diagnostics = format_legacy_diagnostics(
                stdout=stdout,
                stderr=stderr,
                limit=500,
            )
            protocol_expected = os.path.basename(script_name) == "actions.py"
            if action_result is not None:
                diagnostic_output = (
                    f"Structured action result: code={action_result.code}; "
                    f"phase={action_result.phase}; {action_result.operator_message}"
                )[:500]
                result_success = action_result.success
                error_message = action_result.operator_message
                exit_success = return_code == 0
                if result_success != exit_success:
                    logger.error(
                        "Mission script '%s' returned inconsistent terminal state "
                        "(exit_code=%s, result_success=%s, result_code=%s).",
                        script_name,
                        return_code,
                        result_success,
                        action_result.code,
                    )
                    result_success = False
                    error_message = (
                        "The action process returned inconsistent terminal status; "
                        "the command is treated as failed."
                    )
                    diagnostic_output = (
                        f"Structured action result mismatch: exit_code={return_code}; "
                        f"code={action_result.code}; phase={action_result.phase}"
                    )[:500]
            else:
                result_success = return_code == 0
                diagnostic_output = legacy_diagnostics
                if protocol_expected:
                    error_message = (
                        f"Mission script exited with code {return_code} without a valid "
                        "structured terminal result."
                    )
                    logger.warning(
                        "Action process '%s' returned no valid structured terminal result; "
                        "using labelled legacy diagnostics for compatibility.",
                        script_name,
                    )
                else:
                    # Legacy mission runners do not yet implement the dedicated
                    # action-result protocol.  Preserve their bounded diagnostics
                    # as the operator-facing failure instead of replacing the
                    # concrete reason with a misleading protocol error.
                    error_message = legacy_diagnostics or (
                        f"Mission script exited with code {return_code}."
                    )
            duration_ms = int((time.time() - start_time) * 1000)

            state_reset, ownership_reason = await self._retire_process_and_update_state(
                process_record,
                reset_success=result_success,
            )
            # Read superseded only after locked retirement. If an override won
            # the transaction race, it set this flag before retirement; once
            # retirement removes the exact record, no later override can mark
            # it. This makes the reported terminal outcome deterministic.
            if process_record.superseded:
                if process_record.forced_kill_cleanup_unconfirmed:
                    superseded_error = (
                        "A newer command replaced this action, but the process was force-killed "
                        "before TAKE_OFF/TEST safety cleanup could be confirmed. Keep clear of "
                        "the vehicle and use the primary recovery controls."
                    )
                    diagnostic_output = (
                        "Safety cleanup unconfirmed after forced process stop "
                        f"(mode={process_record.forced_stop_mode or 'unknown'}; "
                        f"exit_code={return_code})."
                    )
                    superseded_phase = "superseded_cleanup_unconfirmed"
                else:
                    superseded_error = format_superseded_execution_error(
                        action_result.operator_message
                        if action_result is not None and not action_result.success
                        else None
                    )
                    superseded_phase = "superseded"
                logger.info(
                    f"Mission script '{script_name}' ended after being superseded by a newer command. "
                    "Skipping duplicate mission-state reset but reporting the superseded execution. "
                    f"Ownership result: {ownership_reason}."
                )
                await self._report_execution_to_gcs(
                    command_id=process_record.command_id,
                    success=False,
                    error_message=superseded_error,
                    exit_code=return_code,
                    script_output=diagnostic_output,
                    duration_ms=duration_ms,
                    outcome=(
                        DroneExecutionOutcome.FAILED
                        if process_record.forced_kill_cleanup_unconfirmed
                        else DroneExecutionOutcome.SUPERSEDED
                    ),
                )
                self._remember_recent_command(
                    process_record.command_id,
                    mission_type=process_record.mission_type,
                    trigger_time=process_record.trigger_time,
                    phase=superseded_phase,
                )
                return

            preserve_newer_state = not state_reset
            if result_success:
                logger.info(
                    "Mission script '%s' completed successfully. %s",
                    script_name,
                    diagnostic_output or "No child diagnostics.",
                )
                if preserve_newer_state:
                    logger.info(
                        f"Mission script '{script_name}' did not own current mission state at completion. "
                        f"Preserving mission state: {ownership_reason}."
                    )
                # Report success to GCS
                await self._report_execution_to_gcs(
                    command_id=process_record.command_id,
                    success=True,
                    exit_code=return_code,
                    script_output=diagnostic_output,
                    duration_ms=duration_ms
                )
                self._remember_recent_command(
                    process_record.command_id,
                    mission_type=process_record.mission_type,
                    trigger_time=process_record.trigger_time,
                    phase="completed",
                )
            else:
                logger.error(
                    "Mission script '%s' failed with return code %s. %s",
                    script_name,
                    return_code,
                    diagnostic_output or "No child diagnostics.",
                )
                if preserve_newer_state:
                    logger.info(
                        f"Mission script '{script_name}' did not own current mission state at failure. "
                        f"Preserving mission state: {ownership_reason}."
                    )
                # Report failure to GCS
                await self._report_execution_to_gcs(
                    command_id=process_record.command_id,
                    success=False,
                    error_message=error_message[:500],
                    exit_code=return_code,
                    script_output=diagnostic_output,
                    duration_ms=duration_ms
                )
                self._remember_recent_command(
                    process_record.command_id,
                    mission_type=process_record.mission_type,
                    trigger_time=process_record.trigger_time,
                    phase="failed",
                )

        except Exception as e:
            if execution_start_task is not None and not execution_start_task.done():
                await self._await_execution_start_report_task(
                    execution_start_task,
                    script_name,
                )
            if result_reader_task is not None and not result_reader_task.done():
                result_reader_task.cancel()
            if process_record.action_result_read_fd is not None:
                try:
                    os.close(process_record.action_result_read_fd)
                except OSError:
                    pass
                process_record.action_result_read_fd = None
            logger.error(f"Exception in _monitor_script_process for '{script_name}': {e}", exc_info=True)
            state_reset, ownership_reason = await self._retire_process_and_update_state(
                process_record,
                reset_success=False,
            )
            if process_record.superseded:
                superseded_error = (
                    "Superseded and force-killed before TAKE_OFF/TEST safety cleanup "
                    "could be confirmed. Keep clear of the vehicle and use the primary "
                    "recovery controls."
                    if process_record.forced_kill_cleanup_unconfirmed
                    else "Superseded by a newer command before completion"
                )
                await self._report_execution_to_gcs(
                    command_id=process_record.command_id,
                    success=False,
                    error_message=superseded_error,
                    duration_ms=int((time.time() - start_time) * 1000),
                    outcome=(
                        DroneExecutionOutcome.FAILED
                        if process_record.forced_kill_cleanup_unconfirmed
                        else DroneExecutionOutcome.SUPERSEDED
                    ),
                )
                self._remember_recent_command(
                    process_record.command_id,
                    mission_type=process_record.mission_type,
                    trigger_time=process_record.trigger_time,
                    phase=(
                        "superseded_cleanup_unconfirmed"
                        if process_record.forced_kill_cleanup_unconfirmed
                        else "superseded"
                    ),
                )
                return
            if not state_reset:
                logger.info(
                    f"Mission script '{script_name}' monitor did not own current mission state. "
                    f"Preserving mission state: {ownership_reason}."
                )
            # Report exception to GCS
            await self._report_execution_to_gcs(
                command_id=process_record.command_id,
                success=False,
                error_message=f"Exception: {str(e)[:200]}",
                duration_ms=int((time.time() - start_time) * 1000)
            )
            self._remember_recent_command(
                process_record.command_id,
                mission_type=process_record.mission_type,
                trigger_time=process_record.trigger_time,
                phase="failed",
            )

    def _build_command_report_url(self, endpoint: str) -> Optional[str]:
        gcs_ip = self.params.GCS_IP
        gcs_port = self.params.gcs_api_port

        if not isinstance(gcs_ip, str) or not gcs_ip:
            return None

        return f"http://{gcs_ip}:{gcs_port}{endpoint}"

    async def _post_command_report(
        self,
        endpoint: str,
        payload: dict,
        capability: Optional[str],
    ) -> bool:
        """Post a callback, with one bounded fallback for old result schemas."""
        url = self._build_command_report_url(endpoint)
        if not url:
            logger.warning("GCS_IP not configured, cannot report command callback")
            return False

        timeout_sec = max(1, int(getattr(self.params, "COMMAND_REPORT_HTTP_TIMEOUT_SEC", 5)))
        headers = gcs_auth_headers()
        if capability:
            headers[GCS_COMMAND_REPORT_CAPABILITY_HEADER] = capability
        async with aiohttp.ClientSession() as session:
            async def post_once(report_payload: dict) -> tuple[int, object]:
                async with session.post(
                    url,
                    json=report_payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout_sec),
                ) as response:
                    response_payload = None
                    if response.status == 422:
                        try:
                            response_payload = await response.json(content_type=None)
                        except (aiohttp.ClientError, ValueError, TypeError):
                            pass
                    return response.status, response_payload

            status, response_payload = await post_once(payload)
            if (
                endpoint == GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE
                and "outcome" in payload
                and is_legacy_schema_outcome_rejection(
                    status_code=status,
                    response_payload=response_payload,
                )
            ):
                legacy_payload = dict(payload)
                legacy_payload.pop("outcome", None)
                logger.info(
                    "GCS rejected the typed execution outcome; retrying once with the "
                    "legacy result envelope for rolling-upgrade compatibility."
                )
                status, _ = await post_once(legacy_payload)

            if 200 <= status < 300:
                return True
            if status in {408, 425, 429} or status >= 500:
                return False
            raise PermanentCommandReportRejection(status)

    async def _ensure_command_report_retry_worker(self):
        if self.command_report_retry_task and not self.command_report_retry_task.done():
            return

        self.command_report_retry_task = asyncio.create_task(self._command_report_retry_loop())

    @staticmethod
    def _command_report_identity(endpoint: str, payload: dict) -> tuple:
        return (
            endpoint,
            payload.get("command_id"),
            payload.get("hw_id"),
        )

    async def _queue_command_report_retry(
        self,
        endpoint: str,
        payload: dict,
        description: str,
        capability: Optional[str] = None,
    ):
        now_monotonic = time.monotonic()
        base_delay = max(1.0, float(getattr(self.params, "COMMAND_REPORT_RETRY_BASE_DELAY_SEC", 2)))
        report_identity = self._command_report_identity(endpoint, payload)
        async with self.command_report_lock:
            for pending in self.pending_command_reports:
                if self._command_report_identity(pending.endpoint, pending.payload) != report_identity:
                    continue
                pending.payload = dict(payload)
                pending.capability = capability
                pending.description = description
                queued_count = len(self.pending_command_reports)
                logger.debug("Updated queued command callback retry: %s", description)
                break
            else:
                self.pending_command_reports.append(
                    PendingCommandReport(
                        endpoint=endpoint,
                        payload=dict(payload),
                        capability=capability,
                        description=description,
                        first_queued_monotonic=now_monotonic,
                        next_attempt_monotonic=now_monotonic + base_delay,
                    )
                )
                queued_count = len(self.pending_command_reports)

        logger.warning(
            "Queued %s for retry because GCS was unavailable. Pending callbacks: %d",
            description,
            queued_count,
        )
        await self._ensure_command_report_retry_worker()

    async def _retry_pending_command_reports_once(self, now_monotonic: Optional[float] = None) -> int:
        now_monotonic = now_monotonic if now_monotonic is not None else time.monotonic()
        base_delay = max(1.0, float(getattr(self.params, "COMMAND_REPORT_RETRY_BASE_DELAY_SEC", 2)))
        max_delay = max(base_delay, float(getattr(self.params, "COMMAND_REPORT_RETRY_MAX_DELAY_SEC", 60)))
        max_age = max(60.0, float(getattr(self.params, "COMMAND_REPORT_RETRY_MAX_AGE_SEC", 1800)))

        async with self.command_report_lock:
            pending = list(self.pending_command_reports)

        still_pending = []
        delivered = 0

        for report in pending:
            if report.next_attempt_monotonic > now_monotonic:
                still_pending.append(report)
                continue

            try:
                delivered_now = await self._post_command_report(
                    report.endpoint,
                    report.payload,
                    report.capability,
                )
            except PermanentCommandReportRejection as exc:
                logger.error(
                    "Dropping %s because GCS rejected its bound callback (HTTP %d). "
                    "Check node-first rollout and command-report authentication.",
                    report.description,
                    exc.status,
                )
                continue
            except asyncio.TimeoutError:
                delivered_now = False
            except aiohttp.ClientError:
                delivered_now = False
            except Exception as exc:
                logger.error("Unexpected error retrying %s: %s", report.description, exc, exc_info=True)
                delivered_now = False

            if delivered_now:
                delivered += 1
                logger.info("Retried command callback successfully: %s", report.description)
                continue

            age_sec = max(0.0, now_monotonic - report.first_queued_monotonic)
            if age_sec >= max_age:
                logger.error(
                    "Dropping queued command callback after %.0fs without GCS recovery: %s",
                    age_sec,
                    report.description,
                )
                continue

            report.attempt_count += 1
            retry_delay = min(max_delay, base_delay * (2 ** max(0, report.attempt_count - 1)))
            report.next_attempt_monotonic = now_monotonic + retry_delay
            still_pending.append(report)

        async with self.command_report_lock:
            self.pending_command_reports = still_pending

        return delivered

    async def _command_report_retry_loop(self):
        interval_sec = max(
            0.5,
            float(getattr(self.params, "COMMAND_REPORT_RETRY_LOOP_INTERVAL_SEC", 1.0)),
        )

        try:
            while True:
                await self._retry_pending_command_reports_once()

                async with self.command_report_lock:
                    if not self.pending_command_reports:
                        return

                await asyncio.sleep(interval_sec)
        finally:
            self.command_report_retry_task = None

    async def _report_execution_start_to_gcs(
        self,
        command_id: Optional[str],
        script_name: Optional[str] = None,
    ):
        """Report to GCS that execution has actually started."""
        if not command_id:
            logger.debug("No command_id available for execution-start report")
            return
        if not self._build_command_report_url(GCS_COMMAND_REPORT_EXECUTION_START_ROUTE):
            logger.warning("GCS_IP not configured, cannot report execution start")
            return

        report_data = {
            'command_id': command_id,
            'hw_id': str(self.drone_config.hw_id),
            'script_name': script_name,
        }
        description = f"execution-start for command {command_id[:8]}"
        capability = self._get_command_report_capability(command_id)

        try:
            delivered = await self._post_command_report(
                GCS_COMMAND_REPORT_EXECUTION_START_ROUTE,
                report_data,
                capability,
            )
            if delivered:
                logger.info("Execution start reported to GCS for command %s...", command_id[:8])
                return
            await self._queue_command_report_retry(
                GCS_COMMAND_REPORT_EXECUTION_START_ROUTE,
                report_data,
                description,
                capability,
            )
        except PermanentCommandReportRejection as exc:
            logger.error(
                "GCS permanently rejected %s (HTTP %d); not retrying the same callback. "
                "Check node-first rollout and command-report authentication.",
                description,
                exc.status,
            )
        except Exception as e:
            logger.error(f"Unexpected error reporting execution start to GCS: {e}", exc_info=True)
            await self._queue_command_report_retry(
                GCS_COMMAND_REPORT_EXECUTION_START_ROUTE,
                report_data,
                description,
                capability,
            )

    async def _report_execution_to_gcs(
        self,
        command_id: Optional[str],
        success: bool,
        error_message: Optional[str] = None,
        exit_code: Optional[int] = None,
        script_output: Optional[str] = None,
        duration_ms: Optional[int] = None,
        outcome: DroneExecutionOutcome | str | None = None,
    ):
        """
        Report command execution result to the GCS command tracker.

        This allows the GCS to track whether the mission script actually
        completed successfully, not just whether the command was received.
        """
        if not command_id:
            logger.debug("No command_id available for execution report")
            return
        if not self._build_command_report_url(GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE):
            logger.warning("GCS_IP not configured, cannot report execution result")
            return

        normalized_outcome = validate_execution_outcome(
            success=success,
            outcome=(
                outcome
                if outcome is not None
                else (
                    DroneExecutionOutcome.COMPLETED
                    if success
                    else DroneExecutionOutcome.FAILED
                )
            ),
        )
        report_data = {
            'command_id': command_id,
            'hw_id': str(self.drone_config.hw_id),
            'success': success,
            'error_message': error_message,
            'exit_code': exit_code,
            'script_output': script_output,
            'duration_ms': duration_ms,
            'outcome': normalized_outcome.value,
        }
        description = f"execution-result for command {command_id[:8]}"
        capability = self._get_command_report_capability(command_id)

        try:
            delivered = await self._post_command_report(
                GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE,
                report_data,
                capability,
            )
            if delivered:
                logger.info("Execution result reported to GCS for command %s...", command_id[:8])
                return
            await self._queue_command_report_retry(
                GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE,
                report_data,
                description,
                capability,
            )
        except PermanentCommandReportRejection as exc:
            logger.error(
                "GCS permanently rejected %s (HTTP %d); not retrying the same callback. "
                "Check node-first rollout and command-report authentication.",
                description,
                exc.status,
            )
        except Exception as e:
            logger.error(f"Unexpected error reporting execution to GCS: {e}", exc_info=True)
            await self._queue_command_report_retry(
                GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE,
                report_data,
                description,
                capability,
            )

    async def _fail_pending_command(self, error_message: str) -> tuple:
        """Reset local mission state and report a terminal failure for the pending command."""
        command_claim = self._claim_for_current_work()
        if not self._claim_still_current(command_claim):
            logger.warning(
                "Stale handler failure ignored because command ownership changed: %s",
                error_message,
            )
            return (False, "Command ownership changed; stale handler did not alter mission state.")
        command_id = self._detach_current_command_id(command_claim)
        mission_type = command_claim.mission_type
        self._reset_mission_state(False)
        await self._report_execution_to_gcs(
            command_id=command_id,
            success=False,
            error_message=error_message,
        )
        self._remember_recent_command(
            command_id,
            mission_type=mission_type,
            trigger_time=command_claim.trigger_time,
            phase="failed",
        )
        return (False, error_message)

    async def _complete_pending_command_without_process(self, message: str) -> tuple:
        """Report a successful command that completed without launching a subprocess."""
        command_claim = self._claim_for_current_work()
        if not self._claim_still_current(command_claim):
            logger.warning(
                "Stale no-process completion ignored because command ownership changed."
            )
            return (False, "Command ownership changed; stale handler did not alter mission state.")
        command_id = self._detach_current_command_id(command_claim)
        mission_type = command_claim.mission_type
        await self._report_execution_start_to_gcs(command_id=command_id)
        self._reset_mission_state(True)
        await self._report_execution_to_gcs(
            command_id=command_id,
            success=True,
            script_output=message[:500],
            duration_ms=0,
        )
        self._remember_recent_command(
            command_id,
            mission_type=mission_type,
            trigger_time=command_claim.trigger_time,
            phase="completed",
        )
        return (True, message)

    async def cancel_active_command(self, message: str = "Cancel command completed.") -> tuple:
        """
        Complete a cancel/clear command without launching a subprocess.

        If another mission script is running it is terminated first; otherwise
        this simply clears the queued mission state and reports a successful
        no-process completion for the cancel command itself.
        """
        if self.running_processes:
            await self.terminate_all_running_processes()

        self.drone_config.mission = Mission.NONE.value
        self.drone_config.state = State.IDLE.value
        self.drone_config.trigger_time = 0
        return await self._complete_pending_command_without_process(message)

    def _reset_mission_state(self, success: bool):
        """
        Reset the mission and state after script completion or forced kill.
        Both success and failure lead to mission=NONE and state=IDLE.
        Also clears runtime overrides like takeoff_altitude.
        """
        logger.info(f"Resetting mission state. Success={success}")
        self.drone_config.mission = Mission.NONE.value
        self.drone_config.state = State.IDLE.value
        self.drone_config.runtime_takeoff_altitude = None  # Clear runtime override
        self._log_mission_result(success, "Mission finished." if success else "Mission failed.")

    # --------------------- MISSION HANDLER HELPERS ---------------------
    # Extracted common logic to reduce duplication in mission handlers

    def _check_mission_conditions(self, current_time: int, earlier_trigger_time: int) -> bool:
        """
        Check if conditions are met to execute a mission.

        Common pre-condition check used by mission handlers:
        - State must be MISSION_READY
        - Current time must be >= earlier_trigger_time

        Args:
            current_time: Current timestamp in milliseconds
            earlier_trigger_time: Adjusted trigger time

        Returns:
            True if conditions are met, False otherwise
        """
        return (
            self.drone_config.state == State.MISSION_READY.value
            and current_time >= earlier_trigger_time
        )

    async def _execute_immediate_script_mission(
        self,
        mission_name: str,
        script_name: str,
        action: Union[str, list],
        current_time: Optional[int] = None,
        earlier_trigger_time: Optional[int] = None,
        interrupt_mode: Optional[ProcessStopMode] = None,
    ) -> tuple:
        """
        Execute an immediate mission/action exactly once.

        These handlers must transition to MISSION_EXECUTING before launching
        the subprocess, otherwise the scheduler can retrigger them on every tick.
        """
        if current_time is None:
            current_time = int(time.time())
        if earlier_trigger_time is None:
            earlier_trigger_time = 0

        if not self._check_mission_conditions(current_time, earlier_trigger_time):
            logger.debug(f"Conditions NOT met for {mission_name}.")
            return (False, f"Conditions not met for {mission_name}.")

        if interrupt_mode is not None and self.running_processes:
            logger.info(
                "%s requested while another mission is running; applying %s preemption.",
                mission_name,
                interrupt_mode.value,
            )
            stop_summary = await self.terminate_all_running_processes(
                reset_state=False,
                mode=interrupt_mode,
            )
            if stop_summary.unresolved and interrupt_mode is not ProcessStopMode.EMERGENCY:
                return await self._fail_pending_command(
                    "Recovery command was not started because an existing local mission "
                    "controller could not be stopped safely. Use Emergency Stop if required."
                )

        logger.info(f"Starting {mission_name}")
        self._prepare_mission_start(mission_name)
        return await self.execute_mission_script(script_name, action)

    def _prepare_mission_start(self, mission_name: str) -> int:
        """
        Prepare for mission execution by transitioning state.

        Common state transition used at the start of mission execution:
        - Logs conditions met
        - Sets state to MISSION_EXECUTING
        - Captures and clears trigger_time

        Args:
            mission_name: Name of the mission for logging

        Returns:
            The original trigger_time value (for use in action string)
        """
        logger.debug(f"Conditions met for {mission_name}; transitioning to TRIGGERED.")
        self.drone_config.state = State.MISSION_EXECUTING.value
        real_trigger_time = self.drone_config.trigger_time
        self.drone_config.trigger_time = 0
        return real_trigger_time

    def _get_phase2_flags(self) -> tuple:
        """
        Get Phase 2 flags from drone_config or Params defaults.

        Returns:
            Tuple of (auto_global_origin, use_global_setpoints)
        """
        auto_global_origin = self.drone_config.auto_global_origin
        if auto_global_origin is None:
            auto_global_origin = getattr(self.params, 'AUTO_GLOBAL_ORIGIN_MODE', True)

        use_global_setpoints = self.drone_config.use_global_setpoints
        if use_global_setpoints is None:
            use_global_setpoints = getattr(self.params, 'USE_GLOBAL_SETPOINTS', True)

        return (auto_global_origin, use_global_setpoints)

    def _build_offboard_action(
        self,
        trigger_time: int,
        mission_type: int,
        custom_csv: str = None
    ) -> str:
        """
        Build action string for offboard executor with Phase 2 flags.

        Args:
            trigger_time: The trigger time for --start_time
            mission_type: Mission type code for --mission_type
            custom_csv: Optional custom CSV filename

        Returns:
            Action string with all flags
        """
        auto_global_origin, use_global_setpoints = self._get_phase2_flags()

        # Custom CSV mode is a per-drone local-frame workflow by design.
        # Keep it explicit so hidden UI state or stale API flags cannot silently
        # switch it into a global/origin-corrected launch path.
        if mission_type == Mission.CUSTOM_CSV_DRONE_SHOW.value:
            auto_global_origin = False
            use_global_setpoints = False

        action = f"--start_time={trigger_time}"
        if custom_csv:
            action += f" --custom_csv={custom_csv}"
        action += f" --auto_global_origin {auto_global_origin}"
        action += f" --use_global_setpoints {use_global_setpoints}"
        action += f" --mission_type {mission_type}"

        logger.info(f"Phase 2 flags: auto_global_origin={auto_global_origin}, "
                   f"use_global_setpoints={use_global_setpoints}")

        return action

    def check_running_processes(self):
        """
        Debug helper to see if any processes ended unexpectedly.
        If a process ended, remove it from the dictionary.
        """
        for process_key, record in list(self.running_processes.items()):
            script_name = record.script_name
            process = record.process
            if process.returncode is not None:
                logger.warning(
                    f"Process '{script_name}' (key: {process_key}) ended unexpectedly "
                    f"with code {process.returncode}."
                )
                del self.running_processes[process_key]
            else:
                logger.debug(f"Process '{script_name}' still running.")

    def synchronize_time(self):
        """
        Synchronize system time using the time sync script.

        Runs tools/sync_time_linux.sh to synchronize the drone's system clock.
        This is important for coordinated show timing across multiple drones.
        """
        if getattr(self.params, 'sim_mode', False):
            logger.info("Simulation mode active. Skipping time synchronization.")
            return

        script_path = self._get_script_path('tools/sync_time_linux.sh')
        if not os.path.isfile(script_path):
            logger.warning("Time sync script not found, skipping time synchronization.")
            return

        try:
            result = subprocess.run([script_path], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                logger.info(f"Time synchronization successful: {result.stdout.strip()}")
            else:
                logger.error(f"Time synchronization failed: {result.stderr.strip()}")
        except Exception as e:
            logger.error(f"Error during time synchronization: {e}")

    async def schedule_mission(self):
        """
        Periodically called (e.g., by the coordinator) to see if we should start or handle a mission.
        """
        # The API server uses this same cross-thread lock for its complete
        # validate/prepare/commit transaction. Holding it until this scheduler
        # tick has either launched/registered the subprocess or declined the
        # mission prevents an override from changing mission/current_command_id
        # between handler selection and execute_mission_script's ownership
        # capture. The long-running child process is monitored after this
        # method returns and therefore never holds the lock for its flight.
        await self._acquire_command_state_transaction_lock()
        try:
            # Guard: if already triggered, skip to avoid double triggers
            if self.drone_config.state == State.MISSION_EXECUTING.value:
                logger.debug("schedule_mission: Drone is already in TRIGGERED state, skipping.")
                return

            current_time = int(time.time())
            try:
                trigger_time = int(self.drone_config.trigger_time)
                trigger_sooner = int(self.params.trigger_sooner_seconds)
                earlier_trigger_time = trigger_time - trigger_sooner
            except (AttributeError, ValueError, TypeError) as e:
                logger.error(f"Error calculating trigger time: {e}")
                return

            # DEBUG level for routine scheduler checks (file only, not console)
            # State changes are logged at INFO level by coordinator.py
            logger.debug(
                f"Scheduler tick: Mission={self.drone_config.mission}, "
                f"State={self.drone_config.state}, Trigger={trigger_time}, Now={current_time}"
            )

            scheduler_claim = None
            try:
                scheduler_claim = self._capture_current_command_claim()
                self._active_scheduler_claim = scheduler_claim
                handler = self.mission_handlers.get(
                    scheduler_claim.mission_type,
                    self._handle_unknown_mission,
                )
                success, message = await handler(current_time, earlier_trigger_time)
                # Only log at INFO level when something actually happened
                if success:
                    logger.info(f"Mission executed: {message}")
                else:
                    # Routine "no mission" cases logged at DEBUG (file only)
                    logger.debug(f"Mission check: {message}")
            except Exception as e:
                logger.error(f"Exception in schedule_mission: {e}", exc_info=True)
            finally:
                if scheduler_claim is not None and self._active_scheduler_claim is scheduler_claim:
                    self._active_scheduler_claim = None
        finally:
            self.command_state_transaction_lock.release()

    # --------------------- MISSION HANDLERS ---------------------

    async def _handle_no_mission(self, current_time: int, earlier_trigger_time: int) -> tuple:
        logger.debug("No mission scheduled (Mission.NONE).")
        return (False, "No mission to execute.")

    async def _handle_unknown_mission(self, current_time: int, earlier_trigger_time: int) -> tuple:
        logger.error(f"Unknown mission code: {self.drone_config.mission}")
        return (False, "Unknown mission code.")

    async def _execute_standard_drone_show(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """Handler for Mission.DRONE_SHOW_FROM_CSV."""
        if not self._check_mission_conditions(current_time, earlier_trigger_time):
            logger.debug("Conditions NOT met for Standard Drone Show.")
            return (False, "Conditions not met for Standard Drone Show.")

        if self.running_processes:
            logger.info("Standard Drone Show requested while another mission is running. Interrupting active mission scripts.")
            await self.terminate_all_running_processes(reset_state=False)

        real_trigger_time = self._prepare_mission_start("Standard Drone Show")

        main_offboard_executer = getattr(self.params, 'main_offboard_executer', None)
        if not main_offboard_executer:
            logger.error("No 'main_offboard_executer' specified for standard drone show.")
            return await self._fail_pending_command("No executer script specified.")

        action = self._build_offboard_action(real_trigger_time, Mission.DRONE_SHOW_FROM_CSV.value)
        logger.info(f"Starting Standard Drone Show using '{main_offboard_executer}'.")
        return await self.execute_mission_script(main_offboard_executer, action)

    async def _execute_custom_drone_show(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """Handler for Mission.CUSTOM_CSV_DRONE_SHOW."""
        if not self._check_mission_conditions(current_time, earlier_trigger_time):
            logger.debug("Conditions NOT met for Custom CSV Drone Show.")
            return (False, "Conditions not met for Custom CSV Drone Show.")

        if self.running_processes:
            logger.info("Custom Drone Show requested while another mission is running. Interrupting active mission scripts.")
            await self.terminate_all_running_processes(reset_state=False)

        real_trigger_time = self._prepare_mission_start("Custom Drone Show")

        main_offboard_executer = getattr(self.params, 'main_offboard_executer', None)
        custom_csv_file_name = getattr(self.params, 'custom_csv_file_name', None)

        if not main_offboard_executer:
            logger.error("No 'main_offboard_executer' specified for custom drone show.")
            return await self._fail_pending_command("No executer script specified.")

        if not custom_csv_file_name:
            logger.error("No custom CSV file specified for Custom Drone Show.")
            return await self._fail_pending_command("No custom CSV file specified.")

        action = self._build_offboard_action(
            real_trigger_time,
            Mission.CUSTOM_CSV_DRONE_SHOW.value,
            custom_csv=custom_csv_file_name
        )
        logger.info(f"Starting Custom Drone Show with '{custom_csv_file_name}' using '{main_offboard_executer}'.")
        return await self.execute_mission_script(main_offboard_executer, action)

    async def _execute_hover_test(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """Handler for Mission.HOVER_TEST."""
        if not self._check_mission_conditions(current_time, earlier_trigger_time):
            logger.debug("Conditions not met for Automated Hover Flight.")
            return (False, "Conditions not met for Automated Hover Flight.")

        real_trigger_time = self._prepare_mission_start("Automated Hover Flight")

        main_offboard_executer = getattr(self.params, 'main_offboard_executer', None)
        hover_test_csv_file_name = getattr(self.params, 'hover_test_csv_file_name', None)

        if not main_offboard_executer:
            logger.error("No 'main_offboard_executer' specified for hover test.")
            return await self._fail_pending_command("No executer script specified.")

        if not hover_test_csv_file_name:
            logger.error("No trajectory CSV file is configured for Automated Hover Flight.")
            return await self._fail_pending_command("No hover test CSV file specified.")

        action = self._build_offboard_action(
            real_trigger_time,
            Mission.HOVER_TEST.value,
            custom_csv=hover_test_csv_file_name
        )
        logger.info(
            "Starting Automated Hover Flight with '%s' using '%s'.",
            hover_test_csv_file_name,
            main_offboard_executer,
        )
        return await self.execute_mission_script(main_offboard_executer, action)

    async def _execute_smart_swarm(self, current_time: int, earlier_trigger_time: int) -> tuple:
        """Handler for Mission.SMART_SWARM."""
        if (
            self.drone_config.state == State.MISSION_READY.value
            and current_time >= earlier_trigger_time
        ):
            logger.debug("Conditions met for Smart Swarm; transitioning to TRIGGERED.")
            self.drone_config.state = State.MISSION_EXECUTING.value
            self.drone_config.trigger_time = 0

            smart_swarm_executer = getattr(self.params, 'smart_swarm_executer', None)
            if not smart_swarm_executer:
                logger.error("No 'smart_swarm_executer' specified for smart swarm mission.")
                return await self._fail_pending_command("No executer script specified.")

            logger.info("Starting Smart Swarm mission runtime.")
            return await self.execute_mission_script(smart_swarm_executer, "")

        logger.debug("Conditions NOT met for Smart Swarm.")
        return (False, "Conditions not met for Smart Swarm.")

    async def _execute_swarm_trajectory(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.SWARM_TRAJECTORY."""
        return await self._execute_immediate_script_mission(
            "Swarm Trajectory Mission",
            "swarm_trajectory_mission.py",
            "",
            current_time,
            earlier_trigger_time,
            interrupt_mode=ProcessStopMode.NORMAL,
        )

    async def _execute_quickscout(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.QUICKSCOUT."""
        if current_time is None:
            current_time = int(time.time())
        if earlier_trigger_time is None:
            earlier_trigger_time = 0

        if not (
            self.drone_config.state == State.MISSION_READY.value
            and current_time >= earlier_trigger_time
        ):
            logger.debug("Conditions NOT met for QuickScout (state or trigger time).")
            return (False, "Conditions not met for QuickScout.")

        mission_id = getattr(self.drone_config, 'quickscout_mission_id', '')
        waypoints_file = getattr(self.drone_config, 'quickscout_waypoints_file', '')
        return_behavior = getattr(self.drone_config, 'quickscout_return_behavior', 'return_home')
        hw_id = self.drone_config.hw_id

        if not waypoints_file or not os.path.isfile(waypoints_file):
            logger.error(f"QuickScout waypoints file not found: {waypoints_file}")
            return await self._fail_pending_command("Waypoints file not found")

        self.drone_config.state = State.MISSION_EXECUTING.value
        self.drone_config.trigger_time = 0

        args = ["--waypoints-file", waypoints_file, "--mission-id", mission_id,
                "--hw-id", hw_id, "--return-behavior", return_behavior]
        logger.info(f"Starting QuickScout mission {mission_id}")
        return await self.execute_mission_script("quickscout_mission.py", args)

    async def _execute_takeoff(self, current_time: int = 0, earlier_trigger_time: int = 0) -> tuple:
        """Handler for Mission.TAKE_OFF."""
        if current_time == 0:
            current_time = int(time.time())

        if (
            self.drone_config.state == State.MISSION_READY.value
            and current_time >= earlier_trigger_time
        ):
            logger.debug("Conditions met for Takeoff; transitioning to TRIGGERED.")
            try:
                altitude = float(self.drone_config.takeoff_altitude)
            except (AttributeError, ValueError, TypeError) as e:
                logger.error(f"Invalid takeoff altitude: {e}")
                return await self._fail_pending_command(f"Invalid takeoff altitude: {e}")

            logger.info(f"Starting Takeoff to altitude: {altitude}m")
            self.drone_config.state = State.MISSION_EXECUTING.value
            self.drone_config.trigger_time = 0
            return await self.execute_mission_script("actions.py", f"--action=takeoff --altitude={altitude}")

        logger.debug("Conditions NOT met for Takeoff.")
        return (False, "Conditions not met for Takeoff.")

    async def _execute_land(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.LAND."""
        return await self._execute_immediate_script_mission(
            "Land Mission",
            "actions.py",
            "--action=land",
            current_time,
            earlier_trigger_time,
            interrupt_mode=ProcessStopMode.RECOVERY,
        )

    async def _execute_return_rtl(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.RETURN_RTL."""
        return await self._execute_immediate_script_mission(
            "Return RTL Mission",
            "actions.py",
            "--action=return_rtl",
            current_time,
            earlier_trigger_time,
            interrupt_mode=ProcessStopMode.RECOVERY,
        )

    async def _execute_kill_terminate(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.KILL_TERMINATE."""
        logger.warning("Kill and Terminate Mission requested (Emergency Stop).")
        return await self._execute_immediate_script_mission(
            "Kill and Terminate Mission",
            "actions.py",
            "--action=kill_terminate",
            current_time,
            earlier_trigger_time,
            interrupt_mode=ProcessStopMode.EMERGENCY,
        )

    async def _execute_hold(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.HOLD."""
        return await self._execute_immediate_script_mission(
            "Hold Position Mission",
            "actions.py",
            "--action=hold",
            current_time,
            earlier_trigger_time,
            interrupt_mode=ProcessStopMode.RECOVERY,
        )

    async def _execute_test(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.TEST."""
        command_claim = self._claim_for_current_work()
        request_file = command_claim.ground_test_request_file
        if not request_file or not os.path.isfile(request_file):
            logger.error("Arm/Disarm Ground Test safety request file not found.")
            return await self._fail_pending_command(
                "Arm/Disarm Ground Test safety acknowledgement file not found. No arm command was sent."
            )

        return await self._execute_immediate_script_mission(
            "Arm/Disarm Ground Test",
            "actions.py",
            ["--action=test", f"--request-file={request_file}"],
            current_time,
            earlier_trigger_time,
        )

    async def _execute_reboot_fc(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.REBOOT_FC."""
        logger.warning("Flight Control Reboot Mission requested.")
        return await self._execute_immediate_script_mission(
            "Flight Control Reboot Mission",
            "actions.py",
            "--action=reboot_fc",
            current_time,
            earlier_trigger_time,
        )

    async def _execute_reboot_sys(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.REBOOT_SYS."""
        logger.warning("System Reboot Mission requested.")
        return await self._execute_immediate_script_mission(
            "System Reboot Mission",
            "actions.py",
            "--action=reboot_sys",
            current_time,
            earlier_trigger_time,
        )

    async def _execute_test_led(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.TEST_LED."""
        return await self._execute_immediate_script_mission(
            "LED Test Mission",
            "test_led_controller.py",
            "--action=start",
            current_time,
            earlier_trigger_time,
        )

    async def _execute_update_code(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.UPDATE_CODE."""
        branch_name = getattr(self.drone_config, 'update_branch', None)
        if not branch_name:
            logger.error("Branch name not specified for UPDATE_CODE mission.")
            return await self._fail_pending_command("Branch name not specified.")

        action_command = f"--action=update_code --branch={branch_name}"
        return await self._execute_immediate_script_mission(
            f"Update Code Mission with branch '{branch_name}'",
            "actions.py",
            action_command,
            current_time,
            earlier_trigger_time,
        )

    async def _execute_precision_move(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.PRECISION_MOVE."""
        request_file = getattr(self.drone_config, "precision_move_request_file", None)
        if not request_file or not os.path.isfile(request_file):
            logger.error("Precision Move request payload file not found.")
            return await self._fail_pending_command("Precision Move payload file not found.")

        action_args = f"--action=precision_move --request-file={request_file}"
        return await self._execute_immediate_script_mission(
            "Precision Move Mission",
            "actions.py",
            action_args,
            current_time,
            earlier_trigger_time,
            interrupt_mode=ProcessStopMode.RECOVERY,
        )

    # --------------------- LOGGING HELPERS ----------------------
    def _log_mission_result(self, success: bool, message: str):
        """
        Avoid spamming logs with repeated mission/state changes.
        Only log if mission or state differs from the last time we logged.
        """
        current_mission = self.drone_config.mission
        current_state = self.drone_config.state

        if (self.last_logged_mission != current_mission) or (self.last_logged_state != current_state):
            if message:
                if success:
                    logger.info(f"Mission result: Success - {message}")
                else:
                    logger.error(f"Mission result: Failure - {message}")

            self.last_logged_mission = current_mission
            self.last_logged_state = current_state

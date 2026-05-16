#!/usr/bin/env python3
# src/drone_setup.py

import asyncio
import datetime
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

import aiohttp

from mds_logging import get_logger
from src.enums import Mission, State  # Ensure this import contains the necessary Mission and State enums
from src.gcs_api_routes import (
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
    superseded: bool = False


@dataclass
class PendingCommandReport:
    """Queued drone -> GCS callback that can be retried safely."""
    endpoint: str
    payload: dict
    description: str
    first_queued_monotonic: float
    next_attempt_monotonic: float
    attempt_count: int = 0


@dataclass
class RecentCommandRecord:
    """Recent terminal command metadata for idempotent duplicate delivery."""
    command_id: str
    mission_type: int
    trigger_time: int
    phase: str
    state: int
    recorded_at_monotonic: float


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
            Mission.INIT_SYSID.value: self._execute_init_sysid,
            Mission.APPLY_COMMON_PARAMS.value: self._execute_apply_common_params,
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

    async def terminate_all_running_processes(self, *, reset_state: bool = True):
        """
        Forcibly stops all currently running mission scripts.
        Useful for emergency overrides (e.g., new land command).

        When a newer mission has already been staged on drone_config, callers
        can pass reset_state=False so the superseded process is terminated
        without clobbering the replacement mission metadata.
        """
        async with self.process_lock:
            for process_key, record in list(self.running_processes.items()):
                script_name = record.script_name
                process = record.process
                record.superseded = True
                if process.returncode is None:
                    logger.warning(
                        f"Terminating mission script: {script_name} "
                        f"(key: {process_key}, PID: {process.pid})"
                    )
                    process.terminate()
                    try:
                        await self._wait_for_process(process, timeout=5)
                        logger.info(f"Process '{script_name}' terminated gracefully.")
                    except asyncio.TimeoutError:
                        logger.warning(f"Process '{script_name}' did not terminate in time. Killing it.")
                        process.kill()
                        await self._wait_for_process(process)
                        logger.info(f"Process '{script_name}' killed forcefully.")

                    if reset_state:
                        # Standalone termination requests should leave the
                        # vehicle in a safe cleared state. Override paths skip
                        # this because a newer mission is already staged.
                        self._reset_mission_state(success=False)
                else:
                    logger.debug(f"Process '{script_name}' already ended.")
            self.running_processes.clear()

    def _detach_current_command_id(self) -> Optional[str]:
        """Capture the pending command_id so execution reporting is process-local."""
        command_id = getattr(self.drone_config, 'current_command_id', None)
        if command_id is not None:
            self.drone_config.current_command_id = None
        return command_id

    def _build_process_key(self, script_name: str, command_id: Optional[str]) -> str:
        suffix = command_id or str(time.time_ns())
        return f"{script_name}:{suffix}"

    def _prune_recent_command_history(self, now_monotonic: Optional[float] = None):
        now_monotonic = now_monotonic if now_monotonic is not None else time.monotonic()
        ttl_sec = max(60.0, float(getattr(self.params, "COMMAND_IDEMPOTENCY_HISTORY_SEC", 1800)))
        max_records = max(32, int(getattr(self.params, "COMMAND_IDEMPOTENCY_MAX_HISTORY", 256)))

        expired_ids = [
            command_id
            for command_id, record in self.recent_command_history.items()
            if (now_monotonic - record.recorded_at_monotonic) > ttl_sec
        ]
        for command_id in expired_ids:
            self.recent_command_history.pop(command_id, None)

        while len(self.recent_command_history) > max_records:
            oldest_command_id = next(iter(self.recent_command_history))
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
        self._prune_recent_command_history(now_monotonic)
        self.recent_command_history[command_id] = RecentCommandRecord(
            command_id=command_id,
            mission_type=int(mission_type),
            trigger_time=int(trigger_time or 0),
            phase=phase,
            state=int(state),
            recorded_at_monotonic=now_monotonic,
        )

    def get_recent_command_record(self, command_id: Optional[str]) -> Optional[dict]:
        if not command_id:
            return None

        now_monotonic = time.monotonic()
        self._prune_recent_command_history(now_monotonic)
        record = self.recent_command_history.get(command_id)
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
            python_exec_path = self._get_python_exec_path()
            script_path = self._get_script_path(script_name)
            command_id = self._detach_current_command_id()
            mission_type = int(self.drone_config.mission)

            if not os.path.isfile(script_path):
                logger.error(f"Mission script '{script_name}' not found at '{script_path}'.")
                self._reset_mission_state(success=False)
                await self._report_execution_to_gcs(
                    command_id=command_id,
                    success=False,
                    error_message=f"Script '{script_name}' not found."
                )
                return (False, f"Script '{script_name}' not found.")

            raw_args = action if isinstance(action, list) else action.split()
            command = [str(python_exec_path), str(script_path), *[str(arg) for arg in raw_args]]
            logger.info(f"Executing mission script asynchronously: {shlex.join(command)}")

            try:
                try:
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                except NotImplementedError:
                    logger.warning(
                        f"Async subprocess execution is unavailable. Falling back to subprocess.Popen for '{script_name}'."
                    )
                    process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                process_key = self._build_process_key(script_name, command_id)
                process_record = RunningMissionProcess(
                    process_key=process_key,
                    script_name=script_name,
                    process=process,
                    command_id=command_id,
                    mission_type=mission_type,
                )
                self.running_processes[process_key] = process_record
            except Exception as e:
                logger.error(f"Exception running '{script_name}': {e}", exc_info=True)
                self._reset_mission_state(success=False)
                await self._report_execution_to_gcs(
                    command_id=command_id,
                    success=False,
                    error_message=f"Exception: {str(e)}"
                )
                return (False, f"Exception: {str(e)}")

        await self._report_execution_start_to_gcs(
            command_id=command_id,
            script_name=script_name,
        )

        # Create a background task that monitors this script's completion
        asyncio.create_task(self._monitor_script_process(process_record))

        # Return immediately - do NOT block on process.communicate()
        return (True, f"Started mission script '{script_name}' asynchronously.")

    async def _monitor_script_process(self, process_record: RunningMissionProcess):
        """
        Monitors the lifetime of the subprocess for a given script.
        Cleans up upon completion, sets mission state accordingly.
        Reports execution result to GCS if command_id is available.
        """
        script_name = process_record.script_name
        process = process_record.process
        start_time = time.time()
        try:
            stdout, stderr = await self._communicate_with_process(process)
            return_code = process.returncode
            stdout_str = stdout.decode().strip() if stdout else ""
            stderr_str = stderr.decode().strip() if stderr else ""
            diagnostic_output = stderr_str or stdout_str
            duration_ms = int((time.time() - start_time) * 1000)

            async with self.process_lock:
                if process_record.process_key in self.running_processes:
                    del self.running_processes[process_record.process_key]

            if process_record.superseded:
                logger.info(
                    f"Mission script '{script_name}' ended after being superseded by a newer command. "
                    "Skipping duplicate mission-state reset but reporting the superseded execution."
                )
                await self._report_execution_to_gcs(
                    command_id=process_record.command_id,
                    success=False,
                    error_message="Superseded by a newer command before completion",
                    exit_code=return_code,
                    script_output=diagnostic_output[:500],
                    duration_ms=duration_ms
                )
                self._remember_recent_command(
                    process_record.command_id,
                    mission_type=process_record.mission_type,
                    phase="superseded",
                )
                return

            preserve_newer_state = self._should_preserve_newer_mission_state(process_record)
            if return_code == 0:
                logger.info(f"Mission script '{script_name}' completed successfully. Output: {stdout_str}")
                if preserve_newer_state:
                    logger.info(
                        f"Mission script '{script_name}' completed after a newer command was staged. "
                        "Preserving the newer mission state."
                    )
                else:
                    self._reset_mission_state(success=True)
                # Report success to GCS
                await self._report_execution_to_gcs(
                    command_id=process_record.command_id,
                    success=True,
                    exit_code=return_code,
                    script_output=stdout_str[:500],  # Truncate output
                    duration_ms=duration_ms
                )
                self._remember_recent_command(
                    process_record.command_id,
                    mission_type=process_record.mission_type,
                    phase="completed",
                )
            else:
                logger.error(
                    f"Mission script '{script_name}' failed with return code {return_code}. "
                    f"Output: {diagnostic_output}"
                )
                if preserve_newer_state:
                    logger.info(
                        f"Mission script '{script_name}' failed after a newer command was staged. "
                        "Preserving the newer mission state."
                    )
                else:
                    self._reset_mission_state(success=False)
                # Report failure to GCS
                await self._report_execution_to_gcs(
                    command_id=process_record.command_id,
                    success=False,
                    error_message=diagnostic_output[:200] or f"Script failed with code {return_code}",
                    exit_code=return_code,
                    script_output=diagnostic_output[:500],
                    duration_ms=duration_ms
                )
                self._remember_recent_command(
                    process_record.command_id,
                    mission_type=process_record.mission_type,
                    phase="failed",
                )

        except Exception as e:
            logger.error(f"Exception in _monitor_script_process for '{script_name}': {e}", exc_info=True)
            if self._should_preserve_newer_mission_state(process_record):
                logger.info(
                    f"Mission script '{script_name}' monitor failed after a newer command was staged. "
                    "Preserving the newer mission state."
                )
            else:
                self._reset_mission_state(success=False)
            async with self.process_lock:
                if process_record.process_key in self.running_processes:
                    del self.running_processes[process_record.process_key]
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
                phase="failed",
            )

    def _should_preserve_newer_mission_state(self, process_record: RunningMissionProcess) -> bool:
        """Avoid letting an older process completion clobber a newer accepted command."""
        current_command_id = getattr(self.drone_config, 'current_command_id', None)
        if current_command_id and current_command_id != process_record.command_id:
            return True

        process_mission_type = process_record.mission_type
        if process_mission_type is None:
            return False

        try:
            current_mission = int(getattr(self.drone_config, 'mission', Mission.NONE.value))
            completed_mission = int(process_mission_type)
        except (TypeError, ValueError):
            return False

        return current_mission != completed_mission

    def _build_command_report_url(self, endpoint: str) -> Optional[str]:
        gcs_ip = self.params.GCS_IP
        gcs_port = self.params.gcs_api_port

        if not isinstance(gcs_ip, str) or not gcs_ip:
            return None

        return f"http://{gcs_ip}:{gcs_port}{endpoint}"

    async def _post_command_report(self, endpoint: str, payload: dict) -> bool:
        """Best-effort single HTTP POST for a drone execution callback."""
        url = self._build_command_report_url(endpoint)
        if not url:
            logger.warning("GCS_IP not configured, cannot report command callback")
            return False

        timeout_sec = max(1, int(getattr(self.params, "COMMAND_REPORT_HTTP_TIMEOUT_SEC", 5)))
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=gcs_auth_headers(),
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            ) as response:
                return response.status == 200

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

    async def _queue_command_report_retry(self, endpoint: str, payload: dict, description: str):
        now_monotonic = time.monotonic()
        base_delay = max(1.0, float(getattr(self.params, "COMMAND_REPORT_RETRY_BASE_DELAY_SEC", 2)))
        report_identity = self._command_report_identity(endpoint, payload)
        async with self.command_report_lock:
            for pending in self.pending_command_reports:
                if self._command_report_identity(pending.endpoint, pending.payload) != report_identity:
                    continue
                pending.payload = dict(payload)
                pending.description = description
                queued_count = len(self.pending_command_reports)
                logger.debug("Updated queued command callback retry: %s", description)
                break
            else:
                self.pending_command_reports.append(
                    PendingCommandReport(
                        endpoint=endpoint,
                        payload=dict(payload),
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
                delivered_now = await self._post_command_report(report.endpoint, report.payload)
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

        try:
            delivered = await self._post_command_report(GCS_COMMAND_REPORT_EXECUTION_START_ROUTE, report_data)
            if delivered:
                logger.info("Execution start reported to GCS for command %s...", command_id[:8])
                return
            await self._queue_command_report_retry(GCS_COMMAND_REPORT_EXECUTION_START_ROUTE, report_data, description)
        except Exception as e:
            logger.error(f"Unexpected error reporting execution start to GCS: {e}", exc_info=True)
            await self._queue_command_report_retry(GCS_COMMAND_REPORT_EXECUTION_START_ROUTE, report_data, description)

    async def _report_execution_to_gcs(
        self,
        command_id: Optional[str],
        success: bool,
        error_message: Optional[str] = None,
        exit_code: Optional[int] = None,
        script_output: Optional[str] = None,
        duration_ms: Optional[int] = None
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

        report_data = {
            'command_id': command_id,
            'hw_id': str(self.drone_config.hw_id),
            'success': success,
            'error_message': error_message,
            'exit_code': exit_code,
            'script_output': script_output,
            'duration_ms': duration_ms
        }
        description = f"execution-result for command {command_id[:8]}"

        try:
            delivered = await self._post_command_report(GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE, report_data)
            if delivered:
                logger.info("Execution result reported to GCS for command %s...", command_id[:8])
                return
            await self._queue_command_report_retry(GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE, report_data, description)
        except Exception as e:
            logger.error(f"Unexpected error reporting execution to GCS: {e}", exc_info=True)
            await self._queue_command_report_retry(GCS_COMMAND_REPORT_EXECUTION_RESULT_ROUTE, report_data, description)

    async def _fail_pending_command(self, error_message: str) -> tuple:
        """Reset local mission state and report a terminal failure for the pending command."""
        command_id = self._detach_current_command_id()
        mission_type = int(self.drone_config.mission)
        self._reset_mission_state(False)
        await self._report_execution_to_gcs(
            command_id=command_id,
            success=False,
            error_message=error_message,
        )
        self._remember_recent_command(command_id, mission_type=mission_type, phase="failed")
        return (False, error_message)

    async def _complete_pending_command_without_process(self, message: str) -> tuple:
        """Report a successful command that completed without launching a subprocess."""
        command_id = self._detach_current_command_id()
        mission_type = int(self.drone_config.mission)
        await self._report_execution_start_to_gcs(command_id=command_id)
        self._reset_mission_state(True)
        await self._report_execution_to_gcs(
            command_id=command_id,
            success=True,
            script_output=message[:500],
            duration_ms=0,
        )
        self._remember_recent_command(command_id, mission_type=mission_type, phase="completed")
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
        interrupt_running: bool = False,
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

        if interrupt_running and self.running_processes:
            logger.info(f"{mission_name} requested while another mission is running. Interrupting active mission scripts.")
            await self.terminate_all_running_processes(reset_state=False)

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

        try:
            handler = self.mission_handlers.get(self.drone_config.mission, self._handle_unknown_mission)
            success, message = await handler(current_time, earlier_trigger_time)
            # Only log at INFO level when something actually happened
            if success:
                logger.info(f"Mission executed: {message}")
            else:
                # Routine "no mission" cases logged at DEBUG (file only)
                logger.debug(f"Mission check: {message}")
        except Exception as e:
            logger.error(f"Exception in schedule_mission: {e}", exc_info=True)

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
            logger.debug("Conditions NOT met for Hover Test CSV Drone Show.")
            return (False, "Conditions not met for Hover Test CSV Drone Show.")

        real_trigger_time = self._prepare_mission_start("Hover Test")

        main_offboard_executer = getattr(self.params, 'main_offboard_executer', None)
        hover_test_csv_file_name = getattr(self.params, 'hover_test_csv_file_name', None)

        if not main_offboard_executer:
            logger.error("No 'main_offboard_executer' specified for hover test.")
            return await self._fail_pending_command("No executer script specified.")

        if not hover_test_csv_file_name:
            logger.error("No hover test CSV file specified for Hover Test Drone Show.")
            return await self._fail_pending_command("No hover test CSV file specified.")

        action = self._build_offboard_action(
            real_trigger_time,
            Mission.HOVER_TEST.value,
            custom_csv=hover_test_csv_file_name
        )
        logger.info(f"Starting Hover Test with '{hover_test_csv_file_name}' using '{main_offboard_executer}'.")
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
            interrupt_running=True,
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
            interrupt_running=True,
        )

    async def _execute_return_rtl(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.RETURN_RTL."""
        return await self._execute_immediate_script_mission(
            "Return RTL Mission",
            "actions.py",
            "--action=return_rtl",
            current_time,
            earlier_trigger_time,
            interrupt_running=True,
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
            interrupt_running=True,
        )

    async def _execute_hold(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.HOLD."""
        return await self._execute_immediate_script_mission(
            "Hold Position Mission",
            "actions.py",
            "--action=hold",
            current_time,
            earlier_trigger_time,
            interrupt_running=True,
        )

    async def _execute_test(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.TEST."""
        return await self._execute_immediate_script_mission(
            "Test Mission",
            "actions.py",
            "--action=test",
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

    async def _execute_init_sysid(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.INIT_SYSID."""
        return await self._execute_immediate_script_mission(
            "Init SysID Mission",
            "actions.py",
            "--action=init_sysid",
            current_time,
            earlier_trigger_time,
        )

    async def _execute_apply_common_params(self, current_time: int = None, earlier_trigger_time: int = None) -> tuple:
        """Handler for Mission.APPLY_COMMON_PARAMS."""
        reboot_after = getattr(self.drone_config, "reboot_after_params", False)
        action_args = "--action=apply_common_params"
        if reboot_after:
            action_args += " --reboot_after"

        mission_name = "Apply Common Params Mission"
        if reboot_after:
            mission_name += " with reboot"

        return await self._execute_immediate_script_mission(
            mission_name,
            "actions.py",
            action_args,
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
            interrupt_running=True,
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

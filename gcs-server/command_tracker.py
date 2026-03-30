# gcs-server/command_tracker.py
"""
Command Tracker - Enterprise-Grade Command Lifecycle Management
===============================================================

Thread-safe command tracking from submission through execution.

Features:
- UUID-based command identification
- Per-drone acknowledgment tracking
- Execution result recording
- Command history with configurable retention
- Statistics and metrics
- Thread-safe operations using asyncio locks

Command Lifecycle:
1. CREATED   - Command created, pending drone ACKs
2. SUBMITTED - Sent to drones, collecting acknowledgments
3. EXECUTING - Legacy status once ACK collection finishes
4. COMPLETED - All drones reported execution success
5. PARTIAL   - Some drones succeeded, some failed
6. FAILED    - All drones failed or timeout occurred
7. CANCELLED - Command was cancelled

Operator-facing lifecycle should use:
- phase=awaiting_ack        while delivery/ACKs are still pending
- phase=pending_execution   once ACKs are done but execution has not started
- phase=in_progress         once at least one drone reports execution start
- phase=terminal            once a terminal outcome has been reached

Usage:
    tracker = CommandTracker()

    # Create a new command
    command_id = tracker.create_command(
        mission_type=10,  # TAKE_OFF
        target_drones=[1, 2, 3],
        params={'takeoff_altitude': 10}
    )

    # Record acknowledgments from drones
    tracker.record_ack(command_id, hw_id='1', status='accepted')
    tracker.record_ack(command_id, hw_id='2', status='rejected', error_code='E202')

    # Record execution results
    tracker.record_execution(command_id, hw_id='1', success=True)

    # Query status
    status = tracker.get_status(command_id)
"""

import asyncio
import os
import sys
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Import shared enums from src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from enums import CommandOutcome, CommandPhase, CommandStatus, Mission
from mds_logging import get_logger

logger = get_logger("command_tracker")


@dataclass
class DroneAck:
    """Acknowledgment from a single drone"""
    hw_id: str
    status: str  # 'accepted', 'offline', 'rejected', or 'error'
    category: str = "accepted"  # Result category for UI styling
    message: Optional[str] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class DroneExecution:
    """Execution result from a single drone"""
    hw_id: str
    success: bool
    error_message: Optional[str] = None
    exit_code: Optional[int] = None
    script_output: Optional[str] = None
    duration_ms: Optional[int] = None
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class TrackedCommand:
    """Complete command tracking record"""
    command_id: str
    mission_type: int
    mission_name: str
    target_drones: List[str]
    params: Dict[str, Any]
    status: CommandStatus
    phase: CommandPhase
    outcome: Optional[CommandOutcome]
    created_at: int
    updated_at: int

    # Acknowledgment tracking
    acks: Dict[str, DroneAck] = field(default_factory=dict)
    acks_expected: int = 0
    acks_received: int = 0
    acks_accepted: int = 0
    acks_offline: int = 0  # Drones that were unreachable (neutral - not an error)
    acks_rejected: int = 0  # Drones that actively refused
    acks_errors: int = 0  # Unexpected errors

    # Execution tracking
    execution_starts: Dict[str, int] = field(default_factory=dict)
    executions: Dict[str, DroneExecution] = field(default_factory=dict)
    executions_expected: int = 0
    executions_received: int = 0
    executions_succeeded: int = 0
    executions_failed: int = 0

    # Timing
    submitted_at: Optional[int] = None
    execution_started_at: Optional[int] = None
    completed_at: Optional[int] = None
    timeout_at: Optional[int] = None

    # Error summary
    error_summary: Optional[str] = None


class CommandTracker:
    """
    Thread-safe command lifecycle tracker.

    Maintains command history with configurable maximum size.
    Older commands are automatically removed when limit is reached.
    """

    def __init__(
        self,
        max_commands: int = 1000,
        default_timeout_ms: int = 60000,
        mission_enum: Optional[type] = Mission
    ):
        """
        Initialize command tracker.

        Args:
            max_commands: Maximum number of commands to retain
            default_timeout_ms: Default command timeout in milliseconds
            mission_enum: Mission enum for name resolution (optional)
        """
        self.max_commands = max_commands
        self.default_timeout_ms = default_timeout_ms
        self.mission_enum = mission_enum

        # Thread-safe storage using OrderedDict for FIFO eviction
        self._commands: OrderedDict[str, TrackedCommand] = OrderedDict()
        self._lock = asyncio.Lock()

        # Statistics
        self._stats = {
            'total_commands': 0,
            'successful_commands': 0,
            'failed_commands': 0,
            'partial_commands': 0,
            'timeout_commands': 0,
            'cancelled_commands': 0
        }

        logger.info(f"CommandTracker initialized (max_commands={max_commands})")

    @staticmethod
    def _all_execution_failures_superseded(command: TrackedCommand) -> bool:
        """Return True when every recorded execution ended because it was superseded."""
        if command.executions_failed == 0 or command.executions_received == 0:
            return False

        for execution in command.executions.values():
            if execution.success:
                return False
            message = (execution.error_message or "").strip().lower()
            if "superseded by a newer command" not in message:
                return False

        return True

    def _get_mission_name(self, mission_type: int) -> str:
        """Get human-readable mission name"""
        if self.mission_enum:
            try:
                return self.mission_enum(mission_type).name
            except ValueError:
                pass
        return f"MISSION_{mission_type}"

    async def create_command(
        self,
        mission_type: int,
        target_drones: List[str],
        params: Optional[Dict[str, Any]] = None,
        timeout_ms: Optional[int] = None
    ) -> str:
        """
        Create a new tracked command.

        Args:
            mission_type: Mission type code
            target_drones: List of hardware IDs to receive command
            params: Command parameters (trigger_time, altitude, etc.)
            timeout_ms: Command timeout in milliseconds

        Returns:
            Command ID (UUID)
        """
        command_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)
        timeout = timeout_ms or self.default_timeout_ms

        command = TrackedCommand(
            command_id=command_id,
            mission_type=mission_type,
            mission_name=self._get_mission_name(mission_type),
            target_drones=list(target_drones),
            params=params or {},
            status=CommandStatus.CREATED,
            phase=CommandPhase.AWAITING_ACK,
            outcome=None,
            created_at=timestamp,
            updated_at=timestamp,
            acks_expected=len(target_drones),
            executions_expected=len(target_drones),
            timeout_at=timestamp + timeout
        )

        async with self._lock:
            # Evict oldest if at capacity
            while len(self._commands) >= self.max_commands:
                oldest_id = next(iter(self._commands))
                del self._commands[oldest_id]
                logger.debug(f"Evicted old command: {oldest_id}")

            self._commands[command_id] = command
            self._stats['total_commands'] += 1

        logger.info(
            f"Command created: {command_id[:8]}... "
            f"({command.mission_name}, {len(target_drones)} drones)"
        )

        return command_id

    async def mark_submitted(self, command_id: str) -> bool:
        """Mark command as submitted to drones"""
        async with self._lock:
            if command_id not in self._commands:
                logger.warning(f"Unknown command ID: {command_id}")
                return False

            command = self._commands[command_id]
            command.status = CommandStatus.SUBMITTED
            command.phase = CommandPhase.AWAITING_ACK
            command.outcome = None
            command.submitted_at = int(time.time() * 1000)
            command.updated_at = command.submitted_at

        logger.info(f"Command submitted: {command_id[:8]}...")
        return True

    async def record_ack(
        self,
        command_id: str,
        hw_id: str,
        category: str = "accepted",
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None
    ) -> bool:
        """
        Record drone acknowledgment for a command.

        Args:
            command_id: Command UUID
            hw_id: Drone hardware ID
            category: Result category ('accepted', 'offline', 'rejected', 'error')
            message: Optional status message
            error_code: Error code if rejected/error
            error_detail: Detailed error information

        Returns:
            True if recorded successfully
        """
        async with self._lock:
            if command_id not in self._commands:
                logger.warning(f"ACK for unknown command: {command_id}")
                return False

            command = self._commands[command_id]
            timestamp = int(time.time() * 1000)

            # Don't record duplicate ACKs
            if hw_id in command.acks:
                logger.debug(f"Duplicate ACK from {hw_id} for {command_id[:8]}")
                return True

            # Use category as both status and category (they were always identical)
            ack = DroneAck(
                hw_id=hw_id,
                status=category,  # Derive status from category
                category=category,
                message=message,
                error_code=error_code,
                error_detail=error_detail,
                timestamp=timestamp
            )

            command.acks[hw_id] = ack
            command.acks_received += 1
            command.updated_at = timestamp

            # Track by category
            if category == 'accepted':
                command.acks_accepted += 1
            elif category == 'offline':
                command.acks_offline += 1
            elif category == 'rejected':
                command.acks_rejected += 1
            else:  # 'error' or unknown
                command.acks_errors += 1

            # Update command status if all ACKs received
            if command.acks_received >= command.acks_expected:
                # Calculate actual problems (rejected + errors, NOT offline)
                actual_problems = command.acks_rejected + command.acks_errors

                if actual_problems == 0 and command.acks_accepted > 0:
                    # Legacy status becomes EXECUTING here, but the phase remains
                    # pending_execution until a drone reports an actual start.
                    command.status = CommandStatus.EXECUTING
                    command.phase = CommandPhase.PENDING_EXECUTION
                    command.outcome = None
                elif command.acks_accepted == 0 and actual_problems == 0:
                    # All drones offline - this is informational, not a failure
                    command.status = CommandStatus.FAILED
                    command.phase = CommandPhase.TERMINAL
                    command.outcome = CommandOutcome.FAILED
                    command.completed_at = timestamp
                    command.error_summary = f"All {command.acks_offline} drones offline"
                    self._stats['failed_commands'] += 1
                elif command.acks_accepted == 0:
                    # All drones rejected/errored
                    command.status = CommandStatus.FAILED
                    command.phase = CommandPhase.TERMINAL
                    command.outcome = CommandOutcome.FAILED
                    command.completed_at = timestamp
                    command.error_summary = f"All reachable drones failed ({command.acks_rejected} rejected, {command.acks_errors} errors)"
                    self._stats['failed_commands'] += 1
                else:
                    # Some drones accepted while others were unavailable or rejected.
                    # Execution has still not started yet.
                    command.status = CommandStatus.EXECUTING
                    command.phase = CommandPhase.PENDING_EXECUTION
                    command.outcome = None
                    parts = []
                    if command.acks_accepted > 0:
                        parts.append(f"{command.acks_accepted} accepted")
                    if command.acks_offline > 0:
                        parts.append(f"{command.acks_offline} offline")
                    if command.acks_rejected > 0:
                        parts.append(f"{command.acks_rejected} rejected")
                    if command.acks_errors > 0:
                        parts.append(f"{command.acks_errors} errors")
                    command.error_summary = ", ".join(parts)

        logger.info(
            f"ACK recorded: {hw_id} -> {category} for {command_id[:8]}... "
            f"({command.acks_received}/{command.acks_expected})"
        )

        return True

    def _mark_execution_started_locked(
        self,
        command: TrackedCommand,
        hw_id: str,
        timestamp: int,
    ) -> bool:
        """Mark a command as actively executing from a specific drone.

        Returns True when this call recorded a new start event, False when it
        was already known.
        """
        if hw_id in command.execution_starts:
            return False

        command.execution_starts[hw_id] = timestamp
        command.updated_at = timestamp
        command.status = CommandStatus.EXECUTING
        command.phase = CommandPhase.IN_PROGRESS
        command.outcome = None

        if command.execution_started_at is None:
            command.execution_started_at = timestamp

        return True

    async def record_execution_start(
        self,
        command_id: str,
        hw_id: str,
    ) -> bool:
        """Record that a drone has started executing a previously accepted command."""
        async with self._lock:
            if command_id not in self._commands:
                logger.warning(f"Execution start for unknown command: {command_id}")
                return False

            command = self._commands[command_id]
            timestamp = int(time.time() * 1000)
            is_new_start = self._mark_execution_started_locked(command, hw_id, timestamp)

        if is_new_start:
            logger.info(f"Execution started: {hw_id} for {command_id[:8]}...")

        return True

    async def record_execution(
        self,
        command_id: str,
        hw_id: str,
        success: bool,
        error_message: Optional[str] = None,
        exit_code: Optional[int] = None,
        script_output: Optional[str] = None,
        duration_ms: Optional[int] = None
    ) -> bool:
        """
        Record drone execution result for a command.

        Args:
            command_id: Command UUID
            hw_id: Drone hardware ID
            success: Whether execution succeeded
            error_message: Error message if failed
            exit_code: Script exit code
            script_output: Script output/logs
            duration_ms: Execution duration

        Returns:
            True if recorded successfully
        """
        async with self._lock:
            if command_id not in self._commands:
                logger.warning(f"Execution result for unknown command: {command_id}")
                return False

            command = self._commands[command_id]
            timestamp = int(time.time() * 1000)

            # Don't record duplicate results
            if hw_id in command.executions:
                logger.debug(f"Duplicate execution from {hw_id} for {command_id[:8]}")
                return True

            self._mark_execution_started_locked(command, hw_id, timestamp)

            execution = DroneExecution(
                hw_id=hw_id,
                success=success,
                error_message=error_message,
                exit_code=exit_code,
                script_output=script_output,
                duration_ms=duration_ms,
                timestamp=timestamp
            )

            command.executions[hw_id] = execution
            command.executions_received += 1
            command.updated_at = timestamp

            if success:
                command.executions_succeeded += 1
            else:
                command.executions_failed += 1

            # Update command status if all executions received
            # Only count drones that accepted the command
            expected_executions = command.acks_accepted
            ack_shortfall = max(0, command.acks_expected - command.acks_accepted)
            if command.executions_received >= expected_executions and expected_executions > 0:
                if command.executions_failed == 0:
                    if ack_shortfall > 0:
                        command.status = CommandStatus.PARTIAL
                        command.phase = CommandPhase.TERMINAL
                        command.outcome = CommandOutcome.PARTIAL
                        command.error_summary = (
                            f"Only {command.acks_accepted}/{command.acks_expected} targets accepted the command"
                        )
                        self._stats['partial_commands'] += 1
                    else:
                        command.status = CommandStatus.COMPLETED
                        command.phase = CommandPhase.TERMINAL
                        command.outcome = CommandOutcome.COMPLETED
                        self._stats['successful_commands'] += 1
                elif command.executions_succeeded == 0:
                    if self._all_execution_failures_superseded(command):
                        command.status = CommandStatus.CANCELLED
                        command.phase = CommandPhase.TERMINAL
                        command.outcome = CommandOutcome.SUPERSEDED
                        command.error_summary = (
                            f"Superseded by newer command on all {command.executions_failed} drones"
                        )
                        self._stats['cancelled_commands'] += 1
                    else:
                        command.status = CommandStatus.FAILED
                        command.phase = CommandPhase.TERMINAL
                        command.outcome = CommandOutcome.FAILED
                        command.error_summary = (
                            f"All {command.executions_failed} executions failed"
                        )
                        self._stats['failed_commands'] += 1
                else:
                    command.status = CommandStatus.PARTIAL
                    command.phase = CommandPhase.TERMINAL
                    command.outcome = CommandOutcome.PARTIAL
                    error_parts = [f"{command.executions_failed}/{expected_executions} executions failed"]
                    if ack_shortfall > 0:
                        error_parts.append(f"{ack_shortfall} targets never accepted")
                    command.error_summary = ", ".join(error_parts)
                    self._stats['partial_commands'] += 1

                command.completed_at = timestamp

        logger.info(
            f"Execution recorded: {hw_id} -> {'success' if success else 'failed'} "
            f"for {command_id[:8]}... ({command.executions_received}/{command.acks_accepted})"
        )

        return True

    async def cancel_command(self, command_id: str, reason: str = "User cancelled") -> bool:
        """Cancel a command"""
        async with self._lock:
            if command_id not in self._commands:
                return False

            command = self._commands[command_id]
            if command.status in [CommandStatus.COMPLETED, CommandStatus.FAILED]:
                return False

            command.status = CommandStatus.CANCELLED
            command.phase = CommandPhase.TERMINAL
            command.outcome = CommandOutcome.CANCELLED
            command.error_summary = reason
            command.completed_at = int(time.time() * 1000)
            command.updated_at = command.completed_at
            self._stats['cancelled_commands'] += 1

        logger.info(f"Command cancelled: {command_id[:8]}... ({reason})")
        return True

    async def check_timeouts(self) -> List[str]:
        """
        Check for timed out commands.

        Returns:
            List of command IDs that timed out
        """
        timed_out = []
        timestamp = int(time.time() * 1000)

        async with self._lock:
            # Snapshot to list to avoid modification during iteration
            commands_snapshot = list(self._commands.items())
            for command_id, command in commands_snapshot:
                if command.phase != CommandPhase.TERMINAL:
                    if command.timeout_at and timestamp > command.timeout_at:
                        previous_phase = command.phase
                        command.status = CommandStatus.TIMEOUT
                        command.phase = CommandPhase.TERMINAL
                        command.outcome = CommandOutcome.TIMEOUT
                        command.completed_at = timestamp
                        command.updated_at = timestamp
                        timeout_age_s = (timestamp - command.created_at) / 1000
                        if previous_phase == CommandPhase.IN_PROGRESS:
                            command.error_summary = (
                                f"Tracking timed out after {timeout_age_s:.1f}s after execution started "
                                f"(results: {command.executions_received}/{command.acks_accepted}). Final outcome unknown."
                            )
                        elif command.acks_accepted > 0:
                            command.error_summary = (
                                f"Tracking timed out after {timeout_age_s:.1f}s after "
                                f"{command.acks_accepted}/{command.acks_expected} drones accepted the command. "
                                f"Execution start was not confirmed."
                            )
                        else:
                            command.error_summary = (
                                f"Timeout after {timeout_age_s:.1f}s "
                                f"(ACKs: {command.acks_received}/{command.acks_expected}, "
                                f"Exec: {command.executions_received}/{command.acks_accepted})"
                            )
                        self._stats['timeout_commands'] += 1
                        timed_out.append(command_id)

        for cid in timed_out:
            logger.warning(f"Command timed out: {cid[:8]}...")

        return timed_out

    async def get_status(self, command_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed status of a command.

        Returns:
            Command status dict or None if not found
        """
        async with self._lock:
            if command_id not in self._commands:
                return None

            command = self._commands[command_id]
            return self._command_to_dict(command)

    async def get_recent(
        self,
        limit: int = 50,
        status_filter: Optional[List[CommandStatus]] = None,
        mission_filter: Optional[List[int]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent commands with optional filtering.

        Args:
            limit: Maximum number of commands to return
            status_filter: Only include these statuses
            mission_filter: Only include these mission types

        Returns:
            List of command status dicts (newest first)
        """
        async with self._lock:
            commands = list(self._commands.values())

        # Apply filters
        if status_filter:
            commands = [c for c in commands if c.status in status_filter]
        if mission_filter:
            commands = [c for c in commands if c.mission_type in mission_filter]

        # Sort by creation time (newest first) and limit
        commands.sort(key=lambda c: c.created_at, reverse=True)
        commands = commands[:limit]

        return [self._command_to_dict(c) for c in commands]

    async def get_statistics(self) -> Dict[str, Any]:
        """Get command statistics"""
        async with self._lock:
            stats = dict(self._stats)
            stats['active_commands'] = len([
                c for c in self._commands.values()
                if c.phase != CommandPhase.TERMINAL
            ])
            stats['tracked_commands'] = len(self._commands)

            # Calculate success rate
            completed = stats['successful_commands'] + stats['failed_commands'] + \
                       stats['partial_commands'] + stats['timeout_commands']
            if completed > 0:
                stats['success_rate'] = round(
                    stats['successful_commands'] / completed * 100, 1
                )
            else:
                stats['success_rate'] = 0.0

        return stats

    async def get_active_commands(self) -> List[Dict[str, Any]]:
        """Get all currently active (non-terminal) commands"""
        async with self._lock:
            active = [
                c for c in self._commands.values()
                if c.phase != CommandPhase.TERMINAL
            ]

        return [self._command_to_dict(c) for c in active]

    def _build_result_summary(self, command: TrackedCommand) -> str:
        """Build human-readable result summary like '1 accepted, 4 offline'"""
        parts = []
        if command.acks_accepted > 0:
            parts.append(f"{command.acks_accepted} accepted")
        if command.acks_offline > 0:
            parts.append(f"{command.acks_offline} offline")
        if command.acks_rejected > 0:
            parts.append(f"{command.acks_rejected} rejected")
        if command.acks_errors > 0:
            parts.append(f"{command.acks_errors} errors")
        return ", ".join(parts) if parts else "pending"

    @staticmethod
    def _extract_trigger_time_ms(params: Optional[Dict[str, Any]]) -> Optional[int]:
        """Return the command trigger time in Unix ms when available."""
        if not isinstance(params, dict):
            return None

        for key in ("triggerTime", "trigger_time"):
            raw_value = params.get(key)
            if raw_value in (None, "", 0, "0"):
                continue
            try:
                numeric = int(float(raw_value))
            except (TypeError, ValueError):
                continue

            if numeric <= 0:
                continue

            # Command APIs use epoch seconds, but be tolerant if ms are already supplied.
            return numeric if numeric >= 10_000_000_000 else numeric * 1000

        return None

    def _build_progress_summary(self, command: TrackedCommand) -> Dict[str, Any]:
        """Build an operator-facing progress snapshot for the current lifecycle."""
        now_ms = int(time.time() * 1000)
        accepted = command.acks_accepted
        started = len(command.execution_starts)
        completed = command.executions_received
        active = max(0, started - completed)
        remaining = max(0, accepted - completed)
        ack_pending = max(0, command.acks_expected - command.acks_received)
        execution_pending = max(0, accepted - started)
        scheduled_trigger_time = self._extract_trigger_time_ms(command.params)
        waiting_for_future_trigger = (
            command.phase == CommandPhase.PENDING_EXECUTION
            and scheduled_trigger_time is not None
            and scheduled_trigger_time > now_ms
        )

        if command.phase == CommandPhase.AWAITING_ACK:
            if command.acks_received == 0:
                stage = "awaiting_ack"
                label = "Dispatching to target drones"
                message = f"Waiting for acknowledgments from {command.acks_expected} targeted drone(s)."
            else:
                stage = "awaiting_ack"
                label = "Collecting acknowledgments"
                message = (
                    f"Received {command.acks_received}/{command.acks_expected} acknowledgments so far."
                )
        elif command.phase == CommandPhase.PENDING_EXECUTION:
            if waiting_for_future_trigger:
                stage = "scheduled"
                label = "Scheduled, waiting for trigger time"
                message = (
                    f"{accepted}/{command.acks_expected} targeted drone(s) accepted the command. "
                    "Waiting for the scheduled trigger time."
                )
            else:
                stage = "pending_execution"
                label = "Accepted, waiting for execution start"
                waiting_count = max(1, execution_pending or accepted)
                message = (
                    f"{accepted}/{command.acks_expected} targeted drone(s) accepted the command. "
                    f"Waiting for execution start reports from {waiting_count} drone(s)."
                )
        elif command.phase == CommandPhase.IN_PROGRESS:
            if completed > 0 and remaining > 0:
                stage = "finishing"
                label = "Finishing on remaining drones"
                message = (
                    f"{completed}/{accepted} accepted drone(s) have reported completion. "
                    f"Waiting for {remaining} remaining drone(s)."
                )
            else:
                stage = "executing"
                label = "Execution in progress"
                active_count = max(1, active or accepted)
                message = f"Execution is active on {active_count} drone(s)."
        else:
            outcome = command.outcome.value if command.outcome else command.status.value
            terminal_defaults = {
                CommandOutcome.COMPLETED.value: (
                    "Completed",
                    f"Completed successfully on {command.executions_succeeded}/{max(accepted, 1)} accepted drone(s).",
                ),
                CommandOutcome.PARTIAL.value: (
                    "Completed with partial coverage",
                    command.error_summary or "Command completed with partial coverage.",
                ),
                CommandOutcome.FAILED.value: (
                    "Failed",
                    command.error_summary or "Command failed before reaching a clean terminal success state.",
                ),
                CommandOutcome.CANCELLED.value: (
                    "Cancelled",
                    command.error_summary or "Command was cancelled before completion.",
                ),
                CommandOutcome.TIMEOUT.value: (
                    "Tracking timed out",
                    command.error_summary or "Command tracking timed out before the final outcome was confirmed.",
                ),
                CommandOutcome.SUPERSEDED.value: (
                    "Superseded",
                    command.error_summary or "Command was superseded by a newer command.",
                ),
            }
            label, message = terminal_defaults.get(
                outcome,
                ("Terminal", command.error_summary or "Command reached a terminal state."),
            )
            stage = outcome

        return {
            "stage": stage,
            "label": label,
            "message": message,
            "ack_pending": ack_pending,
            "accepted": accepted,
            "execution_pending": execution_pending,
            "active": active,
            "completed": completed,
            "remaining": remaining,
            "scheduled_trigger_time": scheduled_trigger_time,
        }

    def _command_to_dict(self, command: TrackedCommand) -> Dict[str, Any]:
        """Convert TrackedCommand to dictionary.

        Note: Makes copies of mutable collections to avoid race conditions
        when called outside the lock context.
        """
        # Copy mutable dicts to prevent race conditions during iteration
        acks_snapshot = dict(command.acks)
        executions_snapshot = dict(command.executions)

        return {
            'command_id': command.command_id,
            'mission_type': command.mission_type,
            'mission_name': command.mission_name,
            'target_drones': list(command.target_drones),  # Copy list too
            'params': dict(command.params),  # Copy dict
            'status': command.status.value,
            'phase': command.phase.value,
            'outcome': command.outcome.value if command.outcome else None,

            # Timing
            'created_at': command.created_at,
            'submitted_at': command.submitted_at,
            'execution_started_at': command.execution_started_at,
            'completed_at': command.completed_at,
            'updated_at': command.updated_at,

            # ACK summary
            'acks': {
                'expected': command.acks_expected,
                'received': command.acks_received,
                'accepted': command.acks_accepted,
                'offline': command.acks_offline,
                'rejected': command.acks_rejected,
                'errors': command.acks_errors,
                'result_summary': self._build_result_summary(command),
                'details': {
                    hw_id: {
                        'status': ack.status,
                        'category': ack.category,
                        'message': ack.message,
                        'error_code': ack.error_code,
                        'timestamp': ack.timestamp
                    }
                    for hw_id, ack in acks_snapshot.items()  # Use snapshot
                }
            },

            # Execution summary
            'executions': {
                'expected': command.acks_accepted,  # Only those that accepted
                'started': len(command.execution_starts),
                'active': max(0, len(command.execution_starts) - command.executions_received),
                'received': command.executions_received,
                'succeeded': command.executions_succeeded,
                'failed': command.executions_failed,
                'details': {
                    hw_id: {
                        'success': exe.success,
                        'error': exe.error_message,
                        'exit_code': exe.exit_code,
                        'duration_ms': exe.duration_ms,
                        'timestamp': exe.timestamp
                    }
                    for hw_id, exe in executions_snapshot.items()  # Use snapshot
                }
            },

            'progress': self._build_progress_summary(command),
            'error_summary': command.error_summary
        }


# Singleton instance for global access
_tracker_instance: Optional[CommandTracker] = None


def get_command_tracker() -> CommandTracker:
    """Get or create the global CommandTracker instance"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = CommandTracker()
    return _tracker_instance


def init_command_tracker(mission_enum: Optional[type] = None, **kwargs) -> CommandTracker:
    """Initialize the global CommandTracker with configuration"""
    global _tracker_instance
    _tracker_instance = CommandTracker(mission_enum=mission_enum, **kwargs)
    return _tracker_instance

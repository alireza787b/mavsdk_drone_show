# gcs-server/command_tracker.py
"""
Command Tracker - Enterprise-Grade Command Lifecycle Management
===============================================================

Thread-safe command tracking from submission through execution, with an
optional SQLite/WAL journal used by the production GCS for restart recovery.

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
    capability = tracker.get_callback_capabilities(command_id)['1']
    tracker.record_execution(
        command_id,
        hw_id='1',
        success=True,
        callback_capability=capability,
    )

    # Query status
    status = tracker.get_status(command_id)
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# Import shared enums from src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from src.command_execution_contract import (
    DroneExecutionOutcome,
    is_legacy_superseded_execution_error,
    validate_execution_outcome,
)
from src.enums import CommandErrorCode, CommandOutcome, CommandPhase, CommandStatus, Mission
from mds_logging import get_logger
from command_journal import CommandJournal, CommandJournalError

logger = get_logger("command_tracker")


class CommandIdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused with a different command payload."""


class CommandTrackerCapacityError(RuntimeError):
    """Raised when history capacity is occupied entirely by active commands."""


class CommandCallbackAuthenticationError(PermissionError):
    """Raised when a callback cannot prove its exact command/target authority.

    Unknown commands, unexpected hardware IDs, missing capabilities, and wrong
    capabilities intentionally share one error.  Callers must not turn this
    boundary into an existence oracle.
    """


class CommandCompletionAuthority(str, Enum):
    """Single owner allowed to terminalize a tracked command.

    Normal missions are completed by capability-authenticated node callbacks.
    Fleet code updates are different: restarting the node can interrupt that
    callback, while the Fleet Ops route can directly verify the required Git
    and runtime postcondition.  Keeping this choice in the tracked record
    prevents whichever signal happens to arrive first from becoming truth.
    """

    NODE_CALLBACK = "node_callback"
    FLEET_GIT_POSTCONDITION = "fleet_git_postcondition"


@dataclass(frozen=True)
class CommandCreationResult:
    """Result of an idempotent command-create attempt."""

    command_id: str
    replayed: bool


@dataclass
class DroneAck:
    """Acknowledgment from a single drone"""
    hw_id: str
    status: str  # 'accepted', 'offline', 'rejected', or 'error'
    category: str = "accepted"  # Result category for UI styling
    message: Optional[str] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    delivery_state: Optional[str] = None
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class DronePreparation:
    """Current-operation launch-readiness evidence for one target."""

    hw_id: str
    state: str  # ready, blocked, or unavailable
    message: Optional[str] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    observation: Optional[Dict[str, Any]] = None
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class DroneExecution:
    """Execution result from a single drone"""
    hw_id: str
    success: bool
    outcome: Optional[str] = None
    error_message: Optional[str] = None
    exit_code: Optional[int] = None
    script_output: Optional[str] = None
    duration_ms: Optional[int] = None
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class TrackedCommand:
    """Complete command tracking record"""
    command_id: str
    idempotency_key: Optional[str]
    request_fingerprint: Optional[str]
    mission_type: int
    mission_name: str
    target_drones: List[str]
    params: Dict[str, Any]
    status: CommandStatus
    phase: CommandPhase
    outcome: Optional[CommandOutcome]
    created_at: int
    updated_at: int
    completion_authority: CommandCompletionAuthority = CommandCompletionAuthority.NODE_CALLBACK

    # Optional all-required preparation for launch-style commands. Preparation
    # is not a delivery ACK and is never presented as command acceptance.
    preparations: Dict[str, DronePreparation] = field(default_factory=dict)
    preparations_expected: int = 0
    preparations_received: int = 0
    preparations_ready: int = 0
    preparations_blocked: int = 0
    preparations_unavailable: int = 0

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
    late_acks: Dict[str, DroneAck] = field(default_factory=dict)
    late_execution_starts: Dict[str, int] = field(default_factory=dict)
    late_executions: Dict[str, DroneExecution] = field(default_factory=dict)
    node_execution_starts: Dict[str, int] = field(default_factory=dict)
    node_execution_reports: Dict[str, DroneExecution] = field(default_factory=dict)
    completion_discrepancies: Dict[str, str] = field(default_factory=dict)

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
        mission_enum: Optional[type] = Mission,
        *,
        state_dir: Optional[str] = None,
        journal: Optional[CommandJournal] = None,
    ):
        """
        Initialize command tracker.

        Args:
            max_commands: Maximum number of commands to retain
            default_timeout_ms: Default command timeout in milliseconds
            mission_enum: Mission enum for name resolution (optional)
            state_dir: Absolute host-local journal directory. Omit only for
                isolated/in-memory test trackers.
            journal: Prebuilt journal used by focused tests or integration
                wiring. Mutually exclusive with ``state_dir``.
        """
        self.max_commands = max_commands
        if self.max_commands < 1:
            raise ValueError("max_commands must be at least 1")
        self.default_timeout_ms = default_timeout_ms
        self.mission_enum = mission_enum
        if state_dir is not None and journal is not None:
            raise ValueError("state_dir and journal are mutually exclusive")
        self._journal = journal or (CommandJournal(state_dir) if state_dir is not None else None)

        # Thread-safe storage using OrderedDict for FIFO eviction
        self._commands: OrderedDict[str, TrackedCommand] = OrderedDict()
        self._idempotency_index: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        # Durable runtimes derive capabilities from a versioned host-local key
        # owned by CommandJournal. Isolated in-memory trackers retain an
        # ephemeral key so direct unit tests do not write host state.
        self._callback_capability_key = (
            self._journal.callback_key
            if self._journal is not None
            else secrets.token_bytes(32)
        )

        # Statistics
        self._stats = {
            'total_commands': 0,
            'successful_commands': 0,
            'failed_commands': 0,
            'partial_commands': 0,
            'timeout_commands': 0,
            'cancelled_commands': 0
        }

        if self._journal is not None:
            persisted_commands, persisted_stats = self._journal.load()
            for key in self._stats:
                if key in persisted_stats:
                    self._stats[key] = max(0, int(persisted_stats[key]))
            for payload in persisted_commands:
                command = self._tracked_command_from_journal(payload)
                self._commands[command.command_id] = command
                if command.idempotency_key:
                    if command.idempotency_key in self._idempotency_index:
                        raise CommandJournalError(
                            "Command journal contains a duplicate idempotency binding"
                        )
                    self._idempotency_index[command.idempotency_key] = command.command_id
            while len(self._commands) > self.max_commands:
                if not self._evict_oldest_terminal_command_locked():
                    raise CommandTrackerCapacityError(
                        "Durable command history contains more active commands than configured capacity"
                    )

        logger.info(
            "CommandTracker initialized (max_commands=%s, durable=%s, restored=%s)",
            max_commands,
            self._journal is not None,
            len(self._commands),
        )

    @staticmethod
    def _restore_dataclass(cls: type, payload: Any) -> Any:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise CommandJournalError("Command target state is not an object")
        try:
            return cls(**payload)
        except TypeError as exc:
            raise CommandJournalError(
                f"Command target state does not match {cls.__name__}"
            ) from exc

    def _tracked_command_from_journal(self, payload: Dict[str, Any]) -> TrackedCommand:
        """Validate and rebuild one in-memory projection from durable rows."""

        try:
            target_drones = [str(value) for value in payload["target_drones"]]
            target_payloads = payload.get("targets") or {}
            if (
                not target_drones
                or len(set(target_drones)) != len(target_drones)
                or set(target_payloads) != set(target_drones)
            ):
                raise CommandJournalError("Command journal target set is incomplete or invalid")

            preparations: Dict[str, DronePreparation] = {}
            acks: Dict[str, DroneAck] = {}
            execution_starts: Dict[str, int] = {}
            executions: Dict[str, DroneExecution] = {}
            late_acks: Dict[str, DroneAck] = {}
            late_execution_starts: Dict[str, int] = {}
            late_executions: Dict[str, DroneExecution] = {}
            node_execution_starts: Dict[str, int] = {}
            node_execution_reports: Dict[str, DroneExecution] = {}
            for hw_id in target_drones:
                target = target_payloads[hw_id]
                if not isinstance(target, dict):
                    raise CommandJournalError("Command journal target state is not an object")
                if target.get("preparation") is not None:
                    preparations[hw_id] = self._restore_dataclass(
                        DronePreparation, target["preparation"]
                    )
                if target.get("ack") is not None:
                    acks[hw_id] = self._restore_dataclass(DroneAck, target["ack"])
                if target.get("execution_started_at") is not None:
                    execution_starts[hw_id] = int(target["execution_started_at"])
                if target.get("execution") is not None:
                    executions[hw_id] = self._restore_dataclass(
                        DroneExecution, target["execution"]
                    )
                if target.get("late_ack") is not None:
                    late_acks[hw_id] = self._restore_dataclass(DroneAck, target["late_ack"])
                if target.get("late_execution_started_at") is not None:
                    late_execution_starts[hw_id] = int(target["late_execution_started_at"])
                if target.get("late_execution") is not None:
                    late_executions[hw_id] = self._restore_dataclass(
                        DroneExecution, target["late_execution"]
                    )
                if target.get("node_execution_started_at") is not None:
                    node_execution_starts[hw_id] = int(
                        target["node_execution_started_at"]
                    )
                if target.get("node_execution_report") is not None:
                    node_execution_reports[hw_id] = self._restore_dataclass(
                        DroneExecution, target["node_execution_report"]
                    )

            preparation_states = [item.state for item in preparations.values()]
            ack_categories = [item.category for item in acks.values()]
            command = TrackedCommand(
                command_id=str(payload["command_id"]),
                idempotency_key=payload.get("idempotency_key"),
                request_fingerprint=payload.get("request_fingerprint"),
                mission_type=int(payload["mission_type"]),
                mission_name=str(payload["mission_name"]),
                target_drones=target_drones,
                params=dict(payload.get("params") or {}),
                status=CommandStatus(payload["status"]),
                phase=CommandPhase(payload["phase"]),
                outcome=(
                    CommandOutcome(payload["outcome"])
                    if payload.get("outcome") is not None
                    else None
                ),
                completion_authority=CommandCompletionAuthority(
                    payload.get(
                        "completion_authority",
                        CommandCompletionAuthority.NODE_CALLBACK.value,
                    )
                ),
                created_at=int(payload["created_at"]),
                updated_at=int(payload["updated_at"]),
                preparations=preparations,
                preparations_expected=int(payload.get("preparations_expected", 0)),
                preparations_received=len(preparations),
                preparations_ready=preparation_states.count("ready"),
                preparations_blocked=preparation_states.count("blocked"),
                preparations_unavailable=preparation_states.count("unavailable"),
                acks=acks,
                acks_expected=int(payload.get("acks_expected", len(target_drones))),
                acks_received=len(acks),
                acks_accepted=ack_categories.count("accepted"),
                acks_offline=ack_categories.count("offline"),
                acks_rejected=ack_categories.count("rejected"),
                acks_errors=sum(
                    category not in {"accepted", "offline", "rejected"}
                    for category in ack_categories
                ),
                execution_starts=execution_starts,
                executions=executions,
                executions_expected=int(payload.get("executions_expected", len(target_drones))),
                executions_received=len(executions),
                executions_succeeded=sum(item.success for item in executions.values()),
                executions_failed=sum(not item.success for item in executions.values()),
                late_acks=late_acks,
                late_execution_starts=late_execution_starts,
                late_executions=late_executions,
                node_execution_starts=node_execution_starts,
                node_execution_reports=node_execution_reports,
                completion_discrepancies={
                    str(key): str(value)
                    for key, value in dict(
                        payload.get("completion_discrepancies") or {}
                    ).items()
                },
                submitted_at=payload.get("submitted_at"),
                execution_started_at=payload.get("execution_started_at"),
                completed_at=payload.get("completed_at"),
                timeout_at=payload.get("timeout_at"),
                error_summary=payload.get("error_summary"),
            )
        except CommandJournalError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise CommandJournalError("Command journal contains an invalid command record") from exc

        if command.acks_expected != len(command.target_drones):
            raise CommandJournalError("Command journal ACK target count is inconsistent")
        return command

    async def _persist_command_locked(
        self,
        command: TrackedCommand,
        *,
        event_type: str,
        hw_ids: Optional[List[str]] = None,
        event_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._journal is None:
            return
        await asyncio.to_thread(
            self._journal.save_command,
            command,
            stats=self._stats,
            event_type=event_type,
            hw_ids=hw_ids,
            event_data=event_data,
        )

    @staticmethod
    def _all_execution_failures_superseded(command: TrackedCommand) -> bool:
        """Return True when every recorded execution ended because it was superseded."""
        if command.executions_failed == 0 or command.executions_received == 0:
            return False

        for execution in command.executions.values():
            if execution.success:
                return False
            if execution.outcome is not None:
                if execution.outcome != DroneExecutionOutcome.SUPERSEDED.value:
                    return False
                continue
            if not is_legacy_superseded_execution_error(execution.error_message):
                return False

        return True

    @staticmethod
    def _is_terminal(command: TrackedCommand) -> bool:
        """Return True when the command has already reached a terminal lifecycle phase."""
        return command.phase == CommandPhase.TERMINAL

    @staticmethod
    def _compact_execution_reason(value: Optional[str], max_length: int = 180) -> str:
        """Return a single-line operator-facing execution failure reason."""
        if not value:
            return ""

        compacted = " ".join(str(value).split())
        if len(compacted) <= max_length:
            return compacted
        return f"{compacted[: max_length - 1].rstrip()}..."

    def _build_execution_failure_detail(self, command: TrackedCommand) -> str:
        """Summarize concrete per-drone failure details for operator feedback."""
        details: List[str] = []
        for hw_id in sorted(command.executions.keys(), key=lambda value: str(value)):
            execution = command.executions[hw_id]
            if execution.success:
                continue

            reason = self._compact_execution_reason(execution.error_message)
            if not reason and execution.exit_code is not None:
                reason = f"exit code {execution.exit_code}"
            if not reason:
                reason = "no failure detail reported"
            details.append(f"drone {hw_id}: {reason}")

        return "; ".join(details[:3])

    @staticmethod
    def _is_expected_target(command: TrackedCommand, hw_id: str) -> bool:
        return hw_id in command.target_drones

    @staticmethod
    def _is_delivery_unknown_ack(ack: DroneAck) -> bool:
        return ack.delivery_state == "delivery_unknown"

    def _maybe_finalize_execution_locked(
        self,
        command: TrackedCommand,
        timestamp: int,
    ) -> bool:
        """Finalize only after ACK classification and every accepted execution.

        Execution callbacks can race ahead of the GCS fan-out response. Waiting
        for all target ACK classifications prevents a fast callback from
        terminalizing a fleet command while other targets are still in flight.
        """
        if (
            command.completion_authority
            is not CommandCompletionAuthority.NODE_CALLBACK
            or self._is_terminal(command)
            or command.acks_received < command.acks_expected
        ):
            return False

        if any(
            ack.category == "offline" or self._is_delivery_unknown_ack(ack)
            for ack in command.acks.values()
        ):
            # An unreachable target or a response-lost target can still prove
            # execution with its command-bound callback capability.  Do not
            # terminalize while that admissible evidence window is open;
            # otherwise the immutable terminal boundary would race the callback.
            return False

        accepted_ids = {
            hw_id for hw_id, ack in command.acks.items()
            if ack.category == "accepted"
        }
        if not accepted_ids or not accepted_ids.issubset(command.executions):
            return False

        expected_executions = len(accepted_ids)
        accepted_executions = [command.executions[hw_id] for hw_id in accepted_ids]
        succeeded = sum(execution.success for execution in accepted_executions)
        failed = expected_executions - succeeded
        ack_shortfall = max(0, command.acks_expected - expected_executions)
        command.executions_expected = expected_executions

        if failed == 0:
            if ack_shortfall > 0:
                command.status = CommandStatus.PARTIAL
                command.outcome = CommandOutcome.PARTIAL
                command.error_summary = (
                    f"Only {expected_executions}/{command.acks_expected} targets accepted the command"
                )
                self._stats['partial_commands'] += 1
            else:
                command.status = CommandStatus.COMPLETED
                command.outcome = CommandOutcome.COMPLETED
                command.error_summary = None
                self._stats['successful_commands'] += 1
        elif succeeded == 0:
            if self._all_execution_failures_superseded(command):
                command.status = CommandStatus.CANCELLED
                command.outcome = CommandOutcome.SUPERSEDED
                command.error_summary = f"Superseded by newer command on all {failed} drones"
                self._stats['cancelled_commands'] += 1
            else:
                command.status = CommandStatus.FAILED
                command.outcome = CommandOutcome.FAILED
                failure_detail = self._build_execution_failure_detail(command)
                command.error_summary = (
                    f"All {failed} execution(s) failed ({failure_detail})"
                    if failure_detail
                    else f"All {failed} execution(s) failed"
                )
                self._stats['failed_commands'] += 1
        else:
            command.status = CommandStatus.PARTIAL
            command.outcome = CommandOutcome.PARTIAL
            error_parts = [f"{failed}/{expected_executions} executions failed"]
            failure_detail = self._build_execution_failure_detail(command)
            if failure_detail:
                error_parts.append(failure_detail)
            if ack_shortfall > 0:
                error_parts.append(f"{ack_shortfall} targets never accepted")
            command.error_summary = ", ".join(error_parts)
            self._stats['partial_commands'] += 1

        command.phase = CommandPhase.TERMINAL
        command.completed_at = timestamp
        command.updated_at = timestamp
        return True

    def _get_mission_name(self, mission_type: int) -> str:
        """Get human-readable mission name"""
        if self.mission_enum:
            try:
                return self.mission_enum(mission_type).name
            except ValueError:
                pass
        return f"MISSION_{mission_type}"

    @staticmethod
    def build_request_fingerprint(payload: Dict[str, Any]) -> str:
        """Build a stable fingerprint for an idempotent command request."""
        normalized = dict(payload)
        normalized.pop("idempotency_key", None)

        if isinstance(normalized.get("target_drone_ids"), list):
            normalized["target_drone_ids"] = sorted(
                str(value).strip()
                for value in normalized["target_drone_ids"]
                if value not in (None, "")
            )

        encoded = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_replay_fingerprint(
        command: TrackedCommand,
        *,
        idempotency_key: str,
        request_fingerprint: Optional[str],
    ) -> None:
        if (
            request_fingerprint
            and command.request_fingerprint
            and command.request_fingerprint != request_fingerprint
        ):
            raise CommandIdempotencyConflictError(
                f"idempotency_key '{idempotency_key}' is already bound to a different command payload"
            )

    def _evict_oldest_terminal_command_locked(self) -> bool:
        """Evict one terminal history record without ever dropping active work."""
        oldest_id = next(
            (
                command_id
                for command_id, command in self._commands.items()
                if self._is_terminal(command)
            ),
            None,
        )
        if oldest_id is None:
            return False

        command = self._commands[oldest_id]
        if self._journal is not None:
            self._journal.delete_command(oldest_id)
        self._commands.pop(oldest_id)
        if command.idempotency_key:
            self._idempotency_index.pop(command.idempotency_key, None)
        logger.debug(f"Evicted old command: {oldest_id}")
        return True

    def _derive_callback_capability(self, command_id: str, hw_id: str) -> str:
        """Derive an opaque capability bound to one exact command and target."""
        binding = f"mds-command-report-v2\0{command_id}\0{hw_id}".encode("utf-8")
        digest = hmac.digest(self._callback_capability_key, binding, "sha256")
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def _callback_capability_matches_locked(
        self,
        command: TrackedCommand,
        hw_id: str,
        supplied_capability: Optional[str],
    ) -> bool:
        """Verify callback authority without exposing command/target existence."""
        if (
            type(supplied_capability) is not str
            or not supplied_capability
            or supplied_capability != supplied_capability.strip()
            or not self._is_expected_target(command, hw_id)
        ):
            return False
        expected = self._derive_callback_capability(command.command_id, hw_id)
        return hmac.compare_digest(expected, supplied_capability)

    async def get_callback_capabilities(self, command_id: str) -> Dict[str, str]:
        """Return per-target dispatch capabilities for a tracked command.

        This is an internal transport hand-off.  Callers must place each value
        only in that target's command request and must never serialize the
        mapping into command status, logs, or operator responses.
        """
        async with self._lock:
            command = self._commands.get(command_id)
            if command is None:
                raise KeyError(f"Command {command_id} not found")
            if self._is_terminal(command):
                raise RuntimeError(
                    "Callback capabilities are unavailable after command terminalization"
                )
            return {
                hw_id: self._derive_callback_capability(command_id, hw_id)
                for hw_id in command.target_drones
            }

    async def lookup_command_by_idempotency_key(
        self,
        idempotency_key: Optional[str],
        *,
        request_fingerprint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return an existing command snapshot for a replay-safe idempotency key."""
        if not idempotency_key:
            return None

        async with self._lock:
            command_id = self._idempotency_index.get(idempotency_key)
            if not command_id:
                return None

            command = self._commands.get(command_id)
            if command is None:
                self._idempotency_index.pop(idempotency_key, None)
                return None

            self._validate_replay_fingerprint(
                command,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
            return self._command_to_dict(command)

    async def create_or_replay_command(
        self,
        mission_type: int,
        target_drones: List[str],
        params: Optional[Dict[str, Any]] = None,
        timeout_ms: Optional[int] = None,
        *,
        idempotency_key: Optional[str] = None,
        request_fingerprint: Optional[str] = None,
        preparation_required: bool = False,
        start_preparing: bool = False,
        completion_authority: CommandCompletionAuthority = CommandCompletionAuthority.NODE_CALLBACK,
    ) -> CommandCreationResult:
        """Create a command or return an existing replay-safe command for the same idempotency key."""
        timestamp = int(time.time() * 1000)
        timeout = timeout_ms or self.default_timeout_ms
        normalized_targets = [str(target).strip() for target in target_drones]
        if not normalized_targets or any(not target for target in normalized_targets):
            raise ValueError("target_drones must contain at least one non-blank hardware ID")
        if len(set(normalized_targets)) != len(normalized_targets):
            raise ValueError("target_drones must contain unique hardware IDs")
        if not isinstance(completion_authority, CommandCompletionAuthority):
            raise TypeError("completion_authority must be a CommandCompletionAuthority")

        async with self._lock:
            if idempotency_key:
                existing_command_id = self._idempotency_index.get(idempotency_key)
                if existing_command_id:
                    existing_command = self._commands.get(existing_command_id)
                    if existing_command is None:
                        self._idempotency_index.pop(idempotency_key, None)
                    else:
                        self._validate_replay_fingerprint(
                            existing_command,
                            idempotency_key=idempotency_key,
                            request_fingerprint=request_fingerprint,
                        )
                        if existing_command.completion_authority is not completion_authority:
                            raise CommandIdempotencyConflictError(
                                f"idempotency_key '{idempotency_key}' is already bound "
                                "to a different completion authority"
                            )
                        return CommandCreationResult(command_id=existing_command_id, replayed=True)

            command_id = str(uuid.uuid4())
            command = TrackedCommand(
                command_id=command_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                mission_type=mission_type,
                mission_name=self._get_mission_name(mission_type),
                target_drones=normalized_targets,
                params=params or {},
                status=CommandStatus.CREATED,
                phase=(
                    CommandPhase.PREPARING
                    if preparation_required or start_preparing
                    else CommandPhase.AWAITING_ACK
                ),
                outcome=None,
                created_at=timestamp,
                updated_at=timestamp,
                completion_authority=completion_authority,
                preparations_expected=(len(normalized_targets) if preparation_required else 0),
                acks_expected=len(normalized_targets),
                executions_expected=len(normalized_targets),
                timeout_at=timestamp + timeout
            )

            while len(self._commands) >= self.max_commands:
                if not self._evict_oldest_terminal_command_locked():
                    raise CommandTrackerCapacityError(
                        "Command tracker capacity is occupied by active commands; "
                        "no active command was evicted and no new command was created"
                    )

            self._stats['total_commands'] += 1
            try:
                await self._persist_command_locked(
                    command,
                    event_type="created",
                    event_data={"preparation_required": preparation_required},
                )
            except Exception:
                self._stats['total_commands'] -= 1
                raise
            self._commands[command_id] = command
            if idempotency_key:
                self._idempotency_index[idempotency_key] = command_id

        logger.info(
            f"Command created: {command_id[:8]}... "
            f"({command.mission_name}, {len(normalized_targets)} drones, timeout={timeout / 1000:.1f}s)"
        )

        return CommandCreationResult(command_id=command_id, replayed=False)

    async def record_preparation(
        self,
        command_id: str,
        hw_id: str,
        *,
        state: str,
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None,
        observation: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record one launch target's prepare result and close failed commits.

        The current launch policy is all-required: after every target has a
        result, any blocked or unavailable target terminates the command before
        dispatch. A fully ready set remains in PREPARING until mark_submitted().
        """

        normalized_state = str(state).strip().lower()
        if normalized_state not in {"ready", "blocked", "unavailable"}:
            raise ValueError(f"Invalid preparation state: {state}")

        async with self._lock:
            command = self._commands.get(command_id)
            if command is None:
                logger.warning(f"Preparation for unknown command: {command_id}")
                return False
            hw_id = str(hw_id).strip()
            if not self._is_expected_target(command, hw_id):
                logger.warning("Ignoring preparation from unexpected drone %s for %s", hw_id, command_id)
                return False
            if self._is_terminal(command) or hw_id in command.preparations:
                return True
            if command.preparations_expected <= 0:
                logger.warning(f"Unexpected preparation result for command: {command_id}")
                return False

            timestamp = int(time.time() * 1000)
            command.preparations[hw_id] = DronePreparation(
                hw_id=hw_id,
                state=normalized_state,
                message=message,
                error_code=error_code,
                error_detail=error_detail,
                observation=dict(observation) if isinstance(observation, dict) else None,
                timestamp=timestamp,
            )
            command.preparations_received += 1
            command.updated_at = timestamp
            if normalized_state == "ready":
                command.preparations_ready += 1
            elif normalized_state == "blocked":
                command.preparations_blocked += 1
            else:
                command.preparations_unavailable += 1

            if command.preparations_received >= command.preparations_expected:
                failed = command.preparations_blocked + command.preparations_unavailable
                if failed:
                    command.status = CommandStatus.FAILED
                    command.phase = CommandPhase.TERMINAL
                    command.outcome = CommandOutcome.FAILED
                    command.completed_at = timestamp
                    parts = []
                    if command.preparations_blocked:
                        parts.append(f"{command.preparations_blocked} not ready")
                    if command.preparations_unavailable:
                        parts.append(f"{command.preparations_unavailable} readiness unavailable")
                    command.error_summary = (
                        "Launch was not dispatched under all-required policy: " + ", ".join(parts)
                    )
                    self._stats["failed_commands"] += 1

            await self._persist_command_locked(
                command,
                event_type="preparation_recorded",
                hw_ids=[hw_id],
                event_data={"state": normalized_state},
            )

        return True

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
        result = await self.create_or_replay_command(
            mission_type=mission_type,
            target_drones=target_drones,
            params=params,
            timeout_ms=timeout_ms,
        )
        return result.command_id

    async def mark_submitted(self, command_id: str) -> bool:
        """Mark command as submitted to drones"""
        async with self._lock:
            if command_id not in self._commands:
                logger.warning(f"Unknown command ID: {command_id}")
                return False

            command = self._commands[command_id]
            if self._is_terminal(command):
                logger.warning(f"Refusing to resubmit terminal command: {command_id}")
                return False
            if command.submitted_at is not None:
                # Idempotent replay after the delivery boundary must not move a
                # pending/executing command backwards to awaiting_ack or reset
                # its original submission timestamp.
                return True
            if command.preparations_expected and (
                command.preparations_received < command.preparations_expected
                or command.preparations_blocked
                or command.preparations_unavailable
            ):
                logger.warning(f"Refusing to submit command with incomplete/failed preparation: {command_id}")
                return False
            command.status = CommandStatus.SUBMITTED
            command.phase = CommandPhase.AWAITING_ACK
            command.outcome = None
            command.submitted_at = int(time.time() * 1000)
            command.updated_at = command.submitted_at
            await self._persist_command_locked(
                command,
                event_type="dispatch_boundary_committed",
            )

        logger.info(f"Command submitted: {command_id[:8]}...")
        return True

    async def fail_command_before_dispatch(self, command_id: str, reason: str) -> bool:
        """Terminalize a command only while delivery is provably unattempted.

        The coordinator may use this when preparation or pre-dispatch setup
        fails.  Once ``mark_submitted`` has established the delivery boundary,
        or any ACK/execution evidence exists, this method refuses to invent a
        definite failure: the dispatcher must classify each target or allow the
        existing uncertainty timeout to close the record.

        Returns ``True`` only when this call created the terminal failure.
        Existing terminal records and commands at/after the delivery boundary
        remain immutable and return ``False``.
        """
        normalized_reason = " ".join(str(reason).split())
        if not normalized_reason:
            raise ValueError("reason must be a non-blank string")
        normalized_reason = normalized_reason[:500]

        async with self._lock:
            command = self._commands.get(command_id)
            if command is None or self._is_terminal(command):
                return False
            if (
                command.phase not in {CommandPhase.PREPARING, CommandPhase.AWAITING_ACK}
                or command.submitted_at is not None
                or command.acks_received
                or command.execution_starts
                or command.executions_received
            ):
                logger.warning(
                    "Refusing definite pre-dispatch failure after the delivery boundary for %s",
                    command_id,
                )
                return False

            timestamp = int(time.time() * 1000)
            command.status = CommandStatus.FAILED
            command.phase = CommandPhase.TERMINAL
            command.outcome = CommandOutcome.FAILED
            command.completed_at = timestamp
            command.updated_at = timestamp
            command.error_summary = normalized_reason
            self._stats["failed_commands"] += 1
            await self._persist_command_locked(
                command,
                event_type="failed_before_dispatch",
                event_data={"reason": normalized_reason},
            )

        logger.error(
            "Command failed before dispatch: %s... (%s)",
            command_id[:8],
            normalized_reason,
        )
        return True

    async def update_deadline_before_dispatch(self, command_id: str, timeout_at_ms: int) -> bool:
        """Replace a provisional deadline while delivery is provably unattempted.

        The estimator owns remaining lifecycle duration; the submission
        pipeline converts it to this absolute deadline only after readiness and
        any deferred trigger have been finalized. This avoids anchoring a
        post-preparation estimate to the earlier creation timestamp.
        """
        if isinstance(timeout_at_ms, bool):
            raise ValueError("timeout_at_ms must be a future Unix-millisecond integer")
        try:
            normalized_timeout_at_ms = int(timeout_at_ms)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_at_ms must be a future Unix-millisecond integer") from exc
        if normalized_timeout_at_ms <= int(time.time() * 1000):
            raise ValueError("timeout_at_ms must be a future Unix-millisecond integer")

        async with self._lock:
            command = self._commands.get(command_id)
            if command is None or self._is_terminal(command):
                return False
            if (
                command.phase not in {CommandPhase.PREPARING, CommandPhase.AWAITING_ACK}
                or command.submitted_at is not None
                or command.acks_received
                or command.execution_starts
                or command.executions_received
            ):
                return False

            command.timeout_at = normalized_timeout_at_ms
            command.updated_at = int(time.time() * 1000)
            await self._persist_command_locked(
                command,
                event_type="deadline_updated",
                event_data={"timeout_at": normalized_timeout_at_ms},
            )
            return True

    async def update_params_before_dispatch(
        self,
        command_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Atomically update scheduler parameters before the delivery boundary.

        This is intentionally narrow: a coordinator may choose a shared
        trigger only after an all-required readiness barrier completes. No
        parameter may change after submission or after any ACK/execution
        evidence exists.
        """
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty mapping")
        if any(not isinstance(key, str) or not key for key in updates):
            raise ValueError("parameter update keys must be non-blank strings")

        async with self._lock:
            command = self._commands.get(command_id)
            if command is None or self._is_terminal(command):
                return False
            if (
                command.phase != CommandPhase.PREPARING
                or command.submitted_at is not None
                or command.acks_received
                or command.execution_starts
                or command.executions_received
            ):
                return False

            command.params.update(updates)
            command.updated_at = int(time.time() * 1000)
            await self._persist_command_locked(
                command,
                event_type="parameters_committed",
                event_data={"keys": sorted(updates)},
            )
            return True

    async def record_ack(
        self,
        command_id: str,
        hw_id: str,
        category: str = "accepted",
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None,
        delivery_state: Optional[str] = None,
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
            delivery_state: Transport state such as accepted, rejected,
                dispatch_unreachable, or delivery_unknown

        Returns:
            True if recorded successfully
        """
        async with self._lock:
            if command_id not in self._commands:
                logger.warning(f"ACK for unknown command: {command_id}")
                return False

            command = self._commands[command_id]
            timestamp = int(time.time() * 1000)
            hw_id = str(hw_id).strip()
            if not self._is_expected_target(command, hw_id):
                logger.warning("Ignoring ACK from unexpected drone %s for %s", hw_id, command_id)
                return False

            if self._is_terminal(command):
                recorded_late_ack = self._record_late_ack_locked(
                    command,
                    hw_id,
                    timestamp,
                    category=category,
                    message=message,
                    error_code=error_code,
                    error_detail=error_detail,
                    delivery_state=delivery_state,
                )
                duplicate_ack = not recorded_late_ack
            else:
                recorded_late_ack = False
                duplicate_ack = False

            # Don't record duplicate ACKs
            if duplicate_ack or hw_id in command.acks:
                logger.debug(f"Duplicate ACK from {hw_id} for {command_id[:8]}")
                return True

            if recorded_late_ack:
                pass
            else:
                # Use category as both status and category (they were always identical)
                ack = DroneAck(
                    hw_id=hw_id,
                    status=category,  # Derive status from category
                    category=category,
                    message=message,
                    error_code=error_code,
                    error_detail=error_detail,
                    delivery_state=delivery_state,
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
                if (
                    command.acks_received >= command.acks_expected
                    and command.completion_authority
                    is CommandCompletionAuthority.NODE_CALLBACK
                ):
                    # Calculate actual problems (rejected + errors, NOT offline)
                    actual_problems = command.acks_rejected + command.acks_errors
                    has_delivery_unknown = any(
                        self._is_delivery_unknown_ack(ack)
                        for ack in command.acks.values()
                    )

                    if command.acks_accepted == 0 and has_delivery_unknown:
                        # A POST response was lost after dispatch may have
                        # started. Keep tracking open for execution callbacks or
                        # the normal command timeout; do not claim definite
                        # failure and do not send a new command ID.
                        command.status = CommandStatus.SUBMITTED
                        command.phase = CommandPhase.PENDING_EXECUTION
                        command.outcome = None
                        command.error_summary = (
                            "Command delivery remains unknown for one or more targets; "
                            "waiting for execution evidence or tracker timeout"
                        )
                    elif actual_problems == 0 and command.acks_accepted > 0:
                        # Legacy status becomes EXECUTING here, but the phase remains
                        # pending_execution until a drone reports an actual start.
                        command.status = CommandStatus.EXECUTING
                        command.phase = CommandPhase.PENDING_EXECUTION
                        command.outcome = None
                    elif command.acks_accepted == 0 and actual_problems == 0:
                        # Connection-level unreachability does not prove the
                        # node failed to receive this idempotent command through
                        # every path. Keep the bounded tracker window open for a
                        # capability-authenticated callback, then time out if no
                        # stronger evidence arrives.
                        command.status = CommandStatus.SUBMITTED
                        command.phase = CommandPhase.PENDING_EXECUTION
                        command.outcome = None
                        command.error_summary = (
                            f"All {command.acks_offline} targets were unreachable during dispatch; "
                            "waiting for authenticated execution evidence or tracker timeout"
                        )
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

                    self._maybe_finalize_execution_locked(command, timestamp)
                elif command.acks_received >= command.acks_expected:
                    # UPDATE_CODE completion belongs to the Fleet Ops
                    # postcondition verifier.  Transport ACKs remain visible,
                    # but even an all-rejected response must not race the
                    # authoritative branch/commit/clean-tree observation.
                    command.status = (
                        CommandStatus.EXECUTING
                        if command.acks_accepted > 0
                        else CommandStatus.SUBMITTED
                    )
                    command.phase = CommandPhase.PENDING_EXECUTION
                    command.outcome = None
                    command.error_summary = (
                        "Command delivery has been classified; waiting for Fleet Ops "
                        "Git/runtime postcondition verification"
                    )

            await self._persist_command_locked(
                command,
                event_type="late_ack_recorded" if recorded_late_ack else "ack_recorded",
                hw_ids=[hw_id],
                event_data={
                    "category": category,
                    "delivery_state": delivery_state,
                },
            )

        if recorded_late_ack:
            logger.info(
                f"Late ACK recorded without lifecycle mutation: {hw_id} -> {category} "
                f"for {command_id[:8]}..."
            )
        else:
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

    def _record_late_ack_locked(
        self,
        command: TrackedCommand,
        hw_id: str,
        timestamp: int,
        *,
        category: str,
        message: Optional[str],
        error_code: Optional[str],
        error_detail: Optional[str],
        delivery_state: Optional[str],
    ) -> bool:
        """Persist post-terminal ACK evidence without mutating the lifecycle outcome."""
        if hw_id in command.acks or hw_id in command.late_acks:
            return False

        command.late_acks[hw_id] = DroneAck(
            hw_id=hw_id,
            status=category,
            category=category,
            message=message,
            error_code=error_code,
            error_detail=error_detail,
            delivery_state=delivery_state,
            timestamp=timestamp,
        )
        command.updated_at = timestamp
        return True

    def _record_late_execution_start_locked(
        self,
        command: TrackedCommand,
        hw_id: str,
        timestamp: int,
    ) -> bool:
        """Persist post-terminal execution-start evidence without mutating lifecycle outcome."""
        if (
            hw_id in command.execution_starts
            or hw_id in command.late_execution_starts
            or hw_id in command.executions
            or hw_id in command.late_executions
        ):
            return False

        command.late_execution_starts[hw_id] = timestamp
        command.updated_at = timestamp
        return True

    def _record_late_execution_locked(
        self,
        command: TrackedCommand,
        hw_id: str,
        timestamp: int,
        *,
        success: bool,
        outcome: DroneExecutionOutcome | str | None,
        error_message: Optional[str],
        exit_code: Optional[int],
        script_output: Optional[str],
        duration_ms: Optional[int],
    ) -> bool:
        """Persist post-terminal execution evidence without mutating lifecycle outcome."""
        if hw_id in command.executions or hw_id in command.late_executions:
            return False

        if hw_id not in command.execution_starts and hw_id not in command.late_execution_starts:
            command.late_execution_starts[hw_id] = timestamp

        command.late_executions[hw_id] = DroneExecution(
            hw_id=hw_id,
            success=success,
            outcome=(outcome.value if isinstance(outcome, DroneExecutionOutcome) else outcome),
            error_message=error_message,
            exit_code=exit_code,
            script_output=script_output,
            duration_ms=duration_ms,
            timestamp=timestamp,
        )
        command.updated_at = timestamp
        return True

    def _promote_execution_evidence_to_accepted_locked(
        self,
        command: TrackedCommand,
        hw_id: str,
        timestamp: int,
        *,
        evidence_source: str,
    ) -> bool:
        """Treat execution evidence as authoritative acceptance proof.

        Slow or lossy links can drop the GCS->drone HTTP ACK while the drone still
        executes the command. When a drone later reports execution-start or a
        terminal execution result, that evidence is stronger than the missing or
        stale ACK classification and should count toward accepted targets.
        """
        existing_ack = command.acks.get(hw_id)
        if existing_ack and existing_ack.category == 'accepted':
            return False

        # Only absence, connection-level unreachability, or an explicitly
        # response-uncertain transport classification can be superseded by a
        # capability-authenticated execution callback.  A definite node
        # rejection or a protocol/validation error remains authoritative.
        if existing_ack is not None and not (
            existing_ack.category == 'offline'
            or self._is_delivery_unknown_ack(existing_ack)
        ):
            return False

        message = f"Acceptance inferred from {evidence_source}"
        if existing_ack is None:
            command.acks[hw_id] = DroneAck(
                hw_id=hw_id,
                status='accepted',
                category='accepted',
                message=message,
                delivery_state='accepted_via_execution',
                timestamp=timestamp,
            )
            command.acks_received += 1
        else:
            if existing_ack.category == 'offline':
                command.acks_offline = max(0, command.acks_offline - 1)
            elif existing_ack.category == 'rejected':
                command.acks_rejected = max(0, command.acks_rejected - 1)
            elif existing_ack.category == 'error':
                command.acks_errors = max(0, command.acks_errors - 1)

            existing_ack.status = 'accepted'
            existing_ack.category = 'accepted'
            existing_ack.message = message
            existing_ack.error_code = None
            existing_ack.error_detail = None
            existing_ack.delivery_state = "accepted_via_execution"
            existing_ack.timestamp = timestamp

        command.acks_accepted += 1
        command.updated_at = timestamp
        return True

    async def record_execution_start(
        self,
        command_id: str,
        hw_id: str,
        callback_capability: Optional[str] = None,
    ) -> bool:
        """Record that a drone has started executing a previously accepted command."""
        async with self._lock:
            command = self._commands.get(command_id)
            timestamp = int(time.time() * 1000)
            hw_id = str(hw_id).strip()
            if command is None or not self._callback_capability_matches_locked(
                command,
                hw_id,
                callback_capability,
            ):
                logger.warning(
                    "Rejected unauthenticated command execution-start callback",
                )
                raise CommandCallbackAuthenticationError(
                    "Command callback authentication failed"
                )
            if (
                command.completion_authority
                is CommandCompletionAuthority.FLEET_GIT_POSTCONDITION
            ):
                if hw_id not in command.node_execution_starts:
                    command.node_execution_starts[hw_id] = timestamp
                    command.updated_at = timestamp
                    await self._persist_command_locked(
                        command,
                        event_type="node_execution_started_advisory",
                        hw_ids=[hw_id],
                    )
                logger.info(
                    "Authenticated advisory execution-start recorded for Fleet Ops "
                    "command %s target %s",
                    command_id[:8],
                    hw_id,
                )
                return True
            if self._is_terminal(command):
                recorded_late_start = self._record_late_execution_start_locked(
                    command,
                    hw_id,
                    timestamp,
                )
                is_new_start = False
                terminal_callback = True
            else:
                recorded_late_start = False
                terminal_callback = False
            promoted = False

            if terminal_callback:
                is_new_start = False
            else:
                promoted = self._promote_execution_evidence_to_accepted_locked(
                    command,
                    hw_id,
                    timestamp,
                    evidence_source='execution-start callback',
                )
                existing_ack = command.acks.get(hw_id)
                if not promoted and (
                    existing_ack is None or existing_ack.category != 'accepted'
                ):
                    logger.error(
                        "Authenticated execution-start contradicted a definite ACK classification "
                        "for drone %s and command %s",
                        hw_id,
                        command_id,
                    )
                    return False
                is_new_start = self._mark_execution_started_locked(command, hw_id, timestamp)

            if recorded_late_start or is_new_start or promoted:
                await self._persist_command_locked(
                    command,
                    event_type=(
                        "late_execution_started"
                        if recorded_late_start
                        else "execution_started"
                    ),
                    hw_ids=[hw_id],
                    event_data={"acceptance_inferred": promoted},
                )

        if recorded_late_start:
            logger.info(
                f"Late execution-start recorded without lifecycle mutation: {hw_id} "
                f"for {command_id[:8]}..."
            )
        elif is_new_start:
            logger.info(f"Execution started: {hw_id} for {command_id[:8]}...")

        return True

    async def record_execution(
        self,
        command_id: str,
        hw_id: str,
        success: bool,
        outcome: DroneExecutionOutcome | str | None = None,
        error_message: Optional[str] = None,
        exit_code: Optional[int] = None,
        script_output: Optional[str] = None,
        duration_ms: Optional[int] = None,
        callback_capability: Optional[str] = None,
    ) -> bool:
        """
        Record drone execution result for a command.

        Args:
            command_id: Command UUID
            hw_id: Drone hardware ID
            success: Whether execution succeeded
            outcome: Typed per-drone outcome, or omitted for legacy callbacks
            error_message: Error message if failed
            exit_code: Script exit code
            script_output: Script output/logs
            duration_ms: Execution duration

        Returns:
            True if recorded successfully
        """
        async with self._lock:
            command = self._commands.get(command_id)
            timestamp = int(time.time() * 1000)
            hw_id = str(hw_id).strip()
            if command is None or not self._callback_capability_matches_locked(
                command,
                hw_id,
                callback_capability,
            ):
                logger.warning(
                    "Rejected unauthenticated command execution-result callback",
                )
                raise CommandCallbackAuthenticationError(
                    "Command callback authentication failed"
                )

            normalized_outcome = validate_execution_outcome(
                success=success,
                outcome=outcome,
            )

            if (
                command.completion_authority
                is CommandCompletionAuthority.FLEET_GIT_POSTCONDITION
            ):
                if hw_id not in command.node_execution_starts:
                    command.node_execution_starts[hw_id] = timestamp
                existing_report = command.node_execution_reports.get(hw_id)
                if existing_report is None:
                    command.node_execution_reports[hw_id] = DroneExecution(
                        hw_id=hw_id,
                        success=success,
                        outcome=(
                            normalized_outcome.value
                            if normalized_outcome is not None
                            else None
                        ),
                        error_message=error_message,
                        exit_code=exit_code,
                        script_output=script_output,
                        duration_ms=duration_ms,
                        timestamp=timestamp,
                    )
                elif existing_report.success != success:
                    command.completion_discrepancies[hw_id] = (
                        "Authenticated node callbacks reported conflicting completion results"
                    )

                verified_result = command.executions.get(hw_id)
                if verified_result is not None and verified_result.success != success:
                    command.completion_discrepancies[hw_id] = (
                        "Node callback result differs from the Fleet Ops Git/runtime postcondition"
                    )
                command.updated_at = timestamp
                await self._persist_command_locked(
                    command,
                    event_type="node_execution_reported_advisory",
                    hw_ids=[hw_id],
                    event_data={"success": bool(success)},
                )
                logger.info(
                    "Authenticated advisory execution result recorded for Fleet Ops "
                    "command %s target %s",
                    command_id[:8],
                    hw_id,
                )
                return True

            if self._is_terminal(command):
                recorded_late_execution = self._record_late_execution_locked(
                    command,
                    hw_id,
                    timestamp,
                    success=success,
                    outcome=normalized_outcome,
                    error_message=error_message,
                    exit_code=exit_code,
                    script_output=script_output,
                    duration_ms=duration_ms,
                )
                duplicate_execution = not recorded_late_execution
            else:
                recorded_late_execution = False
                duplicate_execution = False

            # Don't record duplicate results
            if duplicate_execution or hw_id in command.executions:
                logger.debug(f"Duplicate execution from {hw_id} for {command_id[:8]}")
                return True

            if recorded_late_execution:
                pass
            else:
                promoted = self._promote_execution_evidence_to_accepted_locked(
                    command,
                    hw_id,
                    timestamp,
                    evidence_source='execution-result callback',
                )
                existing_ack = command.acks.get(hw_id)
                if not promoted and (
                    existing_ack is None or existing_ack.category != 'accepted'
                ):
                    logger.error(
                        "Authenticated execution-result contradicted a definite ACK classification "
                        "for drone %s and command %s",
                        hw_id,
                        command_id,
                    )
                    return False
                self._mark_execution_started_locked(command, hw_id, timestamp)

                execution = DroneExecution(
                    hw_id=hw_id,
                    success=success,
                    outcome=(
                        normalized_outcome.value
                        if normalized_outcome is not None
                        else None
                    ),
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

                self._maybe_finalize_execution_locked(command, timestamp)

            await self._persist_command_locked(
                command,
                event_type=(
                    "late_execution_recorded"
                    if recorded_late_execution
                    else "execution_recorded"
                ),
                hw_ids=[hw_id],
                event_data={"success": bool(success)},
            )

        if recorded_late_execution:
            logger.info(
                f"Late execution recorded without lifecycle mutation: {hw_id} -> "
                f"{'success' if success else 'failed'} for {command_id[:8]}..."
            )
        else:
            logger.info(
                f"Execution recorded: {hw_id} -> {'success' if success else 'failed'} "
                f"for {command_id[:8]}... ({command.executions_received}/{command.acks_accepted})"
            )
            if not success:
                reason = self._compact_execution_reason(error_message)
                if not reason and exit_code is not None:
                    reason = f"exit code {exit_code}"
                logger.warning(
                    f"Execution failure detail: drone {hw_id} for {command_id[:8]}... "
                    f"{reason or 'no failure detail reported'}"
                )

        return True

    async def record_authoritative_completion(
        self,
        command_id: str,
        results: Dict[str, Dict[str, Any]],
        *,
        completion_authority: CommandCompletionAuthority,
        callback_capabilities: Dict[str, str],
    ) -> bool:
        """Atomically terminalize a verifier-owned command from exact targets.

        This is an internal coordination boundary, not an HTTP callback.  The
        caller must prove that it still owns every target using the same opaque
        capabilities issued for dispatch.  All inputs are validated before any
        mutation, and the capabilities are never persisted or returned.
        """

        if (
            completion_authority
            is not CommandCompletionAuthority.FLEET_GIT_POSTCONDITION
        ):
            raise ValueError("unsupported authoritative completion source")
        if not isinstance(results, dict) or not isinstance(
            callback_capabilities, dict
        ):
            raise ValueError("results and callback_capabilities must be mappings")

        async with self._lock:
            command = self._commands.get(command_id)
            if command is None:
                raise KeyError(f"Command {command_id} not found")
            if (
                command.completion_authority is not completion_authority
                or command.mission_type != Mission.UPDATE_CODE.value
            ):
                raise ValueError(
                    "command is not owned by Fleet Ops Git/runtime verification"
                )

            expected_targets = set(command.target_drones)
            if set(results) != expected_targets:
                raise ValueError("authoritative results must match the exact target set")
            if set(callback_capabilities) != expected_targets or any(
                not self._callback_capability_matches_locked(
                    command,
                    hw_id,
                    callback_capabilities.get(hw_id),
                )
                for hw_id in command.target_drones
            ):
                raise CommandCallbackAuthenticationError(
                    "Command callback authentication failed"
                )

            normalized_results: Dict[str, tuple[bool, Optional[str]]] = {}
            for hw_id in command.target_drones:
                result = results[hw_id]
                if not isinstance(result, dict) or type(result.get("success")) is not bool:
                    raise ValueError(
                        "each authoritative result must contain an exact boolean success"
                    )
                error_message = result.get("error_message")
                if error_message is not None:
                    if not isinstance(error_message, str):
                        raise ValueError("authoritative error_message must be a string")
                    error_message = " ".join(error_message.split())[:500] or None
                normalized_results[hw_id] = (result["success"], error_message)

            if self._is_terminal(command):
                same_results = (
                    set(command.executions) == expected_targets
                    and all(
                        command.executions[hw_id].success
                        == normalized_results[hw_id][0]
                        for hw_id in command.target_drones
                    )
                )
                if same_results:
                    return True
                raise RuntimeError(
                    "command already has a different immutable terminal outcome"
                )
            if command.submitted_at is None:
                raise RuntimeError(
                    "authoritative completion cannot precede the dispatch boundary"
                )

            timestamp = int(time.time() * 1000)
            command.executions = {
                hw_id: DroneExecution(
                    hw_id=hw_id,
                    success=success,
                    error_message=error_message,
                    timestamp=timestamp,
                )
                for hw_id, (success, error_message) in normalized_results.items()
            }
            command.executions_expected = len(command.target_drones)
            command.executions_received = len(command.target_drones)
            command.executions_succeeded = sum(
                success for success, _error in normalized_results.values()
            )
            command.executions_failed = (
                command.executions_expected - command.executions_succeeded
            )

            for hw_id, report in command.node_execution_reports.items():
                verified = command.executions.get(hw_id)
                if verified is not None and report.success != verified.success:
                    command.completion_discrepancies[hw_id] = (
                        "Node callback result differs from the Fleet Ops Git/runtime postcondition"
                    )

            if command.executions_failed == 0:
                command.status = CommandStatus.COMPLETED
                command.outcome = CommandOutcome.COMPLETED
                command.error_summary = None
                self._stats["successful_commands"] += 1
            elif command.executions_succeeded == 0:
                command.status = CommandStatus.FAILED
                command.outcome = CommandOutcome.FAILED
                details = self._build_execution_failure_detail(command)
                command.error_summary = (
                    "Fleet Ops could not verify the requested Git/runtime "
                    f"postcondition on any of {command.executions_expected} target(s)"
                    + (f" ({details})" if details else "")
                )
                self._stats["failed_commands"] += 1
            else:
                command.status = CommandStatus.PARTIAL
                command.outcome = CommandOutcome.PARTIAL
                command.error_summary = (
                    "Fleet Ops verified the requested Git/runtime postcondition on "
                    f"{command.executions_succeeded}/{command.executions_expected} target(s)"
                )
                self._stats["partial_commands"] += 1

            command.phase = CommandPhase.TERMINAL
            command.completed_at = timestamp
            command.updated_at = timestamp
            await self._persist_command_locked(
                command,
                event_type="authoritative_completion_recorded",
                hw_ids=list(command.target_drones),
                event_data={
                    "completion_authority": completion_authority.value,
                    "succeeded": command.executions_succeeded,
                    "failed": command.executions_failed,
                },
            )

        logger.info(
            "Fleet Ops postcondition recorded for %s... (%s/%s verified)",
            command_id[:8],
            command.executions_succeeded,
            command.executions_expected,
        )
        return True

    async def cancel_command(self, command_id: str, reason: str = "User cancelled") -> bool:
        """Cancel a command"""
        async with self._lock:
            if command_id not in self._commands:
                return False

            command = self._commands[command_id]
            if self._is_terminal(command):
                return False

            command.status = CommandStatus.CANCELLED
            command.phase = CommandPhase.TERMINAL
            command.outcome = CommandOutcome.CANCELLED
            command.error_summary = reason
            command.completed_at = int(time.time() * 1000)
            command.updated_at = command.completed_at
            self._stats['cancelled_commands'] += 1
            await self._persist_command_locked(
                command,
                event_type="cancelled",
                event_data={"reason": reason},
            )

        logger.info(f"Command cancelled: {command_id[:8]}... ({reason})")
        return True

    async def reconcile_after_restart(self) -> Dict[str, int]:
        """Reconcile restored non-terminal work without ever redispatching it.

        A durable record before ``submitted_at`` proves that the GCS never
        crossed its dispatch boundary, so the lost preparation task becomes a
        definite terminal failure.  At or after that boundary, every target
        without durable delivery evidence is classified ``delivery_unknown``.
        The original command ID and callback capability remain valid until the
        original deadline so delayed node evidence can still resolve it.
        """

        summary = {
            "restored_commands": 0,
            "failed_before_dispatch": 0,
            "delivery_unknown_targets": 0,
        }
        async with self._lock:
            summary["restored_commands"] = len(self._commands)
            for command in self._commands.values():
                if self._is_terminal(command):
                    continue

                timestamp = int(time.time() * 1000)
                if command.submitted_at is None:
                    command.status = CommandStatus.FAILED
                    command.phase = CommandPhase.TERMINAL
                    command.outcome = CommandOutcome.FAILED
                    command.completed_at = timestamp
                    command.updated_at = timestamp
                    command.error_summary = (
                        "GCS restarted while preparing this command; durable state proves "
                        "dispatch had not begun. Create a new command after rechecking state."
                    )
                    self._stats["failed_commands"] += 1
                    await self._persist_command_locked(
                        command,
                        event_type="restart_before_dispatch",
                    )
                    summary["failed_before_dispatch"] += 1
                    continue

                missing_targets = [
                    hw_id for hw_id in command.target_drones if hw_id not in command.acks
                ]
                if not missing_targets:
                    continue

                for hw_id in missing_targets:
                    command.acks[hw_id] = DroneAck(
                        hw_id=hw_id,
                        status="error",
                        category="error",
                        message=(
                            "GCS restarted after dispatch may have begun; delivery is unknown"
                        ),
                        error_code=CommandErrorCode.INTERNAL_ERROR.value,
                        error_detail=(
                            "Do not create a replacement solely because of this state; "
                            "wait for authenticated execution evidence or the tracker deadline"
                        ),
                        delivery_state="delivery_unknown",
                        timestamp=timestamp,
                    )
                    command.acks_received += 1
                    command.acks_errors += 1

                command.updated_at = timestamp
                if command.phase != CommandPhase.IN_PROGRESS:
                    command.phase = CommandPhase.PENDING_EXECUTION
                    command.status = (
                        CommandStatus.EXECUTING
                        if command.acks_accepted > 0
                        else CommandStatus.SUBMITTED
                    )
                command.outcome = None
                command.error_summary = (
                    f"GCS restarted with unknown delivery state for {len(missing_targets)} "
                    "target(s); waiting for authenticated execution evidence or tracker timeout"
                )
                await self._persist_command_locked(
                    command,
                    event_type="restart_delivery_reconciled",
                    hw_ids=missing_targets,
                    event_data={"delivery_unknown_targets": len(missing_targets)},
                )
                summary["delivery_unknown_targets"] += len(missing_targets)

        if summary["failed_before_dispatch"] or summary["delivery_unknown_targets"]:
            logger.warning(
                "Reconciled durable command state after restart: %s pre-dispatch failures, "
                "%s delivery-unknown targets",
                summary["failed_before_dispatch"],
                summary["delivery_unknown_targets"],
            )
        return summary

    def close(self) -> None:
        """Close the optional durable journal during controlled teardown/tests."""

        if self._journal is not None:
            self._journal.close()

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
                        if (
                            command.completion_authority
                            is CommandCompletionAuthority.FLEET_GIT_POSTCONDITION
                        ):
                            command.error_summary = (
                                "Fleet Ops Git/runtime postcondition verification did not "
                                f"finish within the {timeout_age_s:.1f}s tracking window."
                            )
                        elif previous_phase == CommandPhase.IN_PROGRESS:
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
                        await self._persist_command_locked(
                            command,
                            event_type="timed_out",
                            event_data={"previous_phase": previous_phase.value},
                        )
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

        raw_value = params.get("trigger_time")
        if type(raw_value) is not int or raw_value <= 0:
            return None
        return raw_value * 1000

    def _build_progress_summary(self, command: TrackedCommand) -> Dict[str, Any]:
        """Build an operator-facing progress snapshot for the current lifecycle."""
        now_ms = int(time.time() * 1000)
        accepted = command.acks_accepted
        externally_verified = (
            command.completion_authority
            is CommandCompletionAuthority.FLEET_GIT_POSTCONDITION
        )
        completion_expected = (
            len(command.target_drones) if externally_verified else accepted
        )
        started = len(
            command.node_execution_starts
            if externally_verified
            else command.execution_starts
        )
        completed = command.executions_received
        active = max(0, started - completed)
        remaining = max(0, completion_expected - completed)
        ack_pending = max(0, command.acks_expected - command.acks_received)
        execution_pending = max(0, completion_expected - started)
        scheduled_trigger_time = self._extract_trigger_time_ms(command.params)
        persistent_smart_swarm = command.mission_type == Mission.SMART_SWARM.value
        waiting_for_future_trigger = (
            command.phase == CommandPhase.PENDING_EXECUTION
            and scheduled_trigger_time is not None
            and scheduled_trigger_time > now_ms
        )

        if command.phase == CommandPhase.PREPARING:
            stage = "preparing"
            if command.preparations_expected:
                label = "Checking launch readiness"
                pending = max(0, command.preparations_expected - command.preparations_received)
                if command.preparations_received:
                    message = (
                        f"Checked {command.preparations_received}/{command.preparations_expected} target drone(s); "
                        f"{pending} remaining. No launch command has been sent."
                    )
                else:
                    message = (
                        f"Checking current PX4 launch readiness on {command.preparations_expected} target drone(s). "
                        "No launch command has been sent."
                    )
            else:
                label = "Preparing dispatch"
                message = (
                    f"Preparing the command for {command.acks_expected} target drone(s). "
                    "No command has been sent."
                )
        elif command.phase == CommandPhase.AWAITING_ACK:
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
            if externally_verified:
                stage = "verifying_postcondition"
                label = "Verifying node code state"
                message = (
                    f"Delivery is classified for {command.acks_received}/{command.acks_expected} "
                    "target drone(s). Fleet Ops is verifying branch, commit, and clean runtime state."
                )
            elif waiting_for_future_trigger:
                stage = "scheduled"
                label = "Scheduled, waiting for trigger time"
                message = (
                    f"{accepted}/{command.acks_expected} targeted drone(s) accepted the command. "
                    "Waiting for the scheduled trigger time."
                )
            elif persistent_smart_swarm:
                stage = "pending_execution"
                label = "Live follow mode"
                waiting_count = max(1, execution_pending or accepted)
                message = (
                    f"{accepted}/{command.acks_expected} targeted drone(s) accepted Smart Swarm. "
                    f"Waiting for live follow-loop confirmation from {waiting_count} drone(s)."
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
            if persistent_smart_swarm:
                stage = "executing"
                label = "Live follow mode"
                active_count = max(1, active or accepted)
                message = f"Smart Swarm is active on {active_count} drone(s)."
            elif completed > 0 and remaining > 0:
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
                    f"Completed successfully on {command.executions_succeeded}/{max(completion_expected, 1)} target drone(s).",
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
            "preparation_pending": max(
                0,
                command.preparations_expected - command.preparations_received,
            ),
            "preparation_ready": command.preparations_ready,
            "preparation_blocked": command.preparations_blocked,
            "preparation_unavailable": command.preparations_unavailable,
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
        preparations_snapshot = dict(command.preparations)
        acks_snapshot = dict(command.acks)
        executions_snapshot = dict(command.executions)
        node_execution_starts_snapshot = dict(command.node_execution_starts)
        node_execution_reports_snapshot = dict(command.node_execution_reports)
        late_acks_snapshot = dict(command.late_acks)
        late_execution_starts_snapshot = dict(command.late_execution_starts)
        late_executions_snapshot = dict(command.late_executions)

        return {
            'command_id': command.command_id,
            'idempotency_key': command.idempotency_key,
            'mission_type': command.mission_type,
            'mission_name': command.mission_name,
            'target_drones': list(command.target_drones),  # Copy list too
            'params': dict(command.params),  # Copy dict
            'status': command.status.value,
            'phase': command.phase.value,
            'outcome': command.outcome.value if command.outcome else None,
            'completion_authority': command.completion_authority.value,
            'completion_discrepancies': dict(command.completion_discrepancies),

            # Timing
            'created_at': command.created_at,
            'submitted_at': command.submitted_at,
            'execution_started_at': command.execution_started_at,
            'completed_at': command.completed_at,
            'timeout_at': command.timeout_at,
            'updated_at': command.updated_at,
            'observed_at': int(time.time() * 1000),

            'preparations': {
                'expected': command.preparations_expected,
                'received': command.preparations_received,
                'ready': command.preparations_ready,
                'blocked': command.preparations_blocked,
                'unavailable': command.preparations_unavailable,
                'policy': 'all_required' if command.preparations_expected else None,
                'details': {
                    hw_id: {
                        'state': preparation.state,
                        'message': preparation.message,
                        'error_code': preparation.error_code,
                        'error_detail': preparation.error_detail,
                        'observation': dict(preparation.observation) if preparation.observation else None,
                        'timestamp': preparation.timestamp,
                    }
                    for hw_id, preparation in preparations_snapshot.items()
                },
            },

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
                        'error_detail': ack.error_detail,
                        'delivery_state': ack.delivery_state,
                        'timestamp': ack.timestamp
                    }
                    for hw_id, ack in acks_snapshot.items()  # Use snapshot
                }
            },

            # Execution summary
            'executions': {
                'expected': (
                    len(command.target_drones)
                    if command.completion_authority
                    is CommandCompletionAuthority.FLEET_GIT_POSTCONDITION
                    else command.acks_accepted
                ),
                'started': len(command.execution_starts),
                'started_hw_ids': sorted(command.execution_starts),
                'active': max(0, len(command.execution_starts) - command.executions_received),
                'active_hw_ids': sorted(
                    hw_id
                    for hw_id in command.execution_starts
                    if hw_id not in command.executions
                ),
                'received': command.executions_received,
                'succeeded': command.executions_succeeded,
                'failed': command.executions_failed,
                'details': {
                    hw_id: {
                        'success': exe.success,
                        'outcome': exe.outcome,
                        'error': exe.error_message,
                        'exit_code': exe.exit_code,
                        'duration_ms': exe.duration_ms,
                        'timestamp': exe.timestamp
                    }
                    for hw_id, exe in executions_snapshot.items()  # Use snapshot
                }
            },

            # Authenticated node callbacks are diagnostic only when Fleet Ops
            # owns completion. They are deliberately separate from the
            # postcondition results above and cannot race the terminal outcome.
            'node_execution_reports': {
                'started': len(node_execution_starts_snapshot),
                'started_hw_ids': sorted(node_execution_starts_snapshot),
                'received': len(node_execution_reports_snapshot),
                'succeeded': sum(
                    report.success for report in node_execution_reports_snapshot.values()
                ),
                'failed': sum(
                    not report.success for report in node_execution_reports_snapshot.values()
                ),
                'details': {
                    hw_id: {
                        'success': report.success,
                        'outcome': report.outcome,
                        'error': report.error_message,
                        'exit_code': report.exit_code,
                        'duration_ms': report.duration_ms,
                        'timestamp': report.timestamp,
                    }
                    for hw_id, report in node_execution_reports_snapshot.items()
                },
            },

            'late_reports': {
                'acks': {
                    'received': len(late_acks_snapshot),
                    'accepted': sum(1 for ack in late_acks_snapshot.values() if ack.category == 'accepted'),
                    'offline': sum(1 for ack in late_acks_snapshot.values() if ack.category == 'offline'),
                    'rejected': sum(1 for ack in late_acks_snapshot.values() if ack.category == 'rejected'),
                    'errors': sum(1 for ack in late_acks_snapshot.values() if ack.category not in {'accepted', 'offline', 'rejected'}),
                    'details': {
                        hw_id: {
                            'status': ack.status,
                            'category': ack.category,
                            'message': ack.message,
                            'error_code': ack.error_code,
                            'error_detail': ack.error_detail,
                            'delivery_state': ack.delivery_state,
                            'timestamp': ack.timestamp,
                        }
                        for hw_id, ack in late_acks_snapshot.items()
                    },
                },
                'execution_starts': {
                    'received': len(late_execution_starts_snapshot),
                    'details': dict(late_execution_starts_snapshot),
                },
                'executions': {
                    'received': len(late_executions_snapshot),
                    'succeeded': sum(1 for exe in late_executions_snapshot.values() if exe.success),
                    'failed': sum(1 for exe in late_executions_snapshot.values() if not exe.success),
                    'details': {
                        hw_id: {
                            'success': exe.success,
                            'outcome': exe.outcome,
                            'error': exe.error_message,
                            'exit_code': exe.exit_code,
                            'duration_ms': exe.duration_ms,
                            'timestamp': exe.timestamp,
                        }
                        for hw_id, exe in late_executions_snapshot.items()
                    },
                },
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

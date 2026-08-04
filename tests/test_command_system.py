# tests/test_command_system.py
"""
Command System Tests - Enterprise-Grade Validation
===================================================
Comprehensive test suite for the command tracking and validation system.

Tests cover:
- CommandErrorCode enum
- Command validation in drone_api_server
- CommandTracker lifecycle management
- GCS command endpoints
- Schemas validation

Author: MAVSDK Drone Show Test Team
Last Updated: 2026-01-05
"""

import pytest
import asyncio
import time
import json
from unittest.mock import Mock

from src.enums import Mission

# Path configuration is handled by conftest.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gcs-server'))


class _AuthenticatedTrackerHarness:
    """Exercise tracker lifecycle methods as an authenticated node callback."""

    def __init__(self, tracker):
        self.raw = tracker

    def __getattr__(self, name):
        return getattr(self.raw, name)

    async def _capability(self, command_id, hw_id):
        capabilities = await self.raw.get_callback_capabilities(command_id)
        return capabilities.get(str(hw_id).strip(), "invalid-callback-capability")

    async def record_execution_start(self, command_id, hw_id, **kwargs):
        if "callback_capability" not in kwargs:
            kwargs["callback_capability"] = await self._capability(command_id, hw_id)
        return await self.raw.record_execution_start(command_id, hw_id, **kwargs)

    async def record_execution(self, command_id, hw_id, success, **kwargs):
        if "callback_capability" not in kwargs:
            kwargs["callback_capability"] = await self._capability(command_id, hw_id)
        return await self.raw.record_execution(command_id, hw_id, success, **kwargs)


# ============================================================================
# CommandErrorCode Tests
# ============================================================================

class TestCommandErrorCode:
    """Test CommandErrorCode enum and descriptions"""

    def test_error_code_values(self):
        """Test that error codes have expected values"""
        from src.enums import CommandErrorCode

        # Validation errors (E1xx)
        assert CommandErrorCode.MISSING_MISSION_TYPE.value == "E100"
        assert CommandErrorCode.INVALID_MISSION_TYPE.value == "E101"
        assert CommandErrorCode.MISSING_TRIGGER_TIME.value == "E102"
        assert CommandErrorCode.INVALID_TRIGGER_TIME.value == "E103"
        assert CommandErrorCode.INVALID_ALTITUDE.value == "E104"

        # State errors (E2xx)
        assert CommandErrorCode.INVALID_STATE.value == "E200"
        assert CommandErrorCode.ALREADY_EXECUTING.value == "E203"
        assert CommandErrorCode.NOT_READY_TO_ARM.value == "E202"

        # Communication errors (E3xx)
        assert CommandErrorCode.TIMEOUT.value == "E300"
        assert CommandErrorCode.HTTP_ERROR.value == "E303"

        # Execution errors (E4xx)
        assert CommandErrorCode.MAVSDK_ERROR.value == "E400"

        # System errors (E5xx)
        assert CommandErrorCode.INTERNAL_ERROR.value == "E500"

    def test_error_descriptions(self):
        """Test that error codes have human-readable descriptions"""
        from src.enums import CommandErrorCode

        desc = CommandErrorCode.get_description("E100")
        assert "mission" in desc.lower()

        desc = CommandErrorCode.get_description("E200")
        assert "state" in desc.lower()

        desc = CommandErrorCode.get_description("E300")
        assert "timed out" in desc.lower() or "timeout" in desc.lower()

        # Unknown code
        desc = CommandErrorCode.get_description("UNKNOWN")
        assert "unknown" in desc.lower()


class TestGcsCommandExecutionPolicy:
    """Keep mission identity and admission policy at its canonical boundary."""

    def test_launch_missions_require_live_armability_probe(self):
        from command_execution_policy import mission_requires_launch_armability_probe
        from src.enums import Mission

        assert mission_requires_launch_armability_probe(Mission.TAKE_OFF) is True
        assert mission_requires_launch_armability_probe(Mission.SWARM_TRAJECTORY) is True
        assert mission_requires_launch_armability_probe(Mission.SMART_SWARM) is False

    @pytest.mark.parametrize("value", [123, 999, 10.0, True, "RTL", "take off"])
    def test_resolver_rejects_unknown_status_only_or_untyped_identities(self, value):
        from command_execution_policy import resolve_mission_type

        assert resolve_mission_type(value) is None

    def test_resolver_accepts_numeric_or_canonical_mission_identities(self):
        from command_execution_policy import resolve_mission_type
        from src.enums import Mission

        assert resolve_mission_type(Mission.LAND.value) is Mission.LAND
        assert resolve_mission_type("LAND") is Mission.LAND


# ============================================================================
# CommandTracker Tests
# ============================================================================

class TestCommandTracker:
    """Test CommandTracker lifecycle management"""

    @pytest.fixture
    def tracker(self):
        """Create a fresh CommandTracker for each test"""
        from command_tracker import CommandTracker
        return _AuthenticatedTrackerHarness(CommandTracker(max_commands=100))

    @pytest.mark.asyncio
    async def test_create_command(self, tracker):
        """Test command creation"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2', '3'],
            params={'takeoff_altitude': 10}
        )

        assert command_id is not None
        assert len(command_id) == 36  # UUID format

        status = await tracker.get_status(command_id)
        assert status is not None
        assert status['mission_type'] == 10
        assert status['mission_name'] == 'TAKE_OFF'
        assert status['target_drones'] == ['1', '2', '3']
        assert status['status'] == 'created'
        assert status['phase'] == 'awaiting_ack'
        assert status['outcome'] is None
        assert status['acks']['expected'] == 3

    @pytest.mark.asyncio
    async def test_launch_preparation_is_distinct_from_delivery_ack(self, tracker):
        from src.enums import Mission

        creation = await tracker.create_or_replay_command(
            mission_type=Mission.TAKE_OFF.value,
            target_drones=["1", "2"],
            preparation_required=True,
        )

        initial = await tracker.get_status(creation.command_id)
        assert initial["phase"] == "preparing"
        assert initial["acks"]["received"] == 0

        await tracker.record_preparation(
            creation.command_id,
            "1",
            state="ready",
            message="Ready for launch",
        )
        await tracker.record_preparation(
            creation.command_id,
            "2",
            state="blocked",
            message="Battery warning is active",
            error_code="E401",
        )

        status = await tracker.get_status(creation.command_id)
        assert status["phase"] == "terminal"
        assert status["outcome"] == "failed"
        assert status["preparations"]["ready"] == 1
        assert status["preparations"]["blocked"] == 1
        assert status["acks"]["received"] == 0
        assert await tracker.mark_submitted(creation.command_id) is False

    @pytest.mark.asyncio
    async def test_non_launch_command_can_start_in_truthful_preparing_phase(self):
        from command_tracker import CommandTracker
        from src.enums import Mission

        tracker = CommandTracker(max_commands=10)
        creation = await tracker.create_or_replay_command(
            mission_type=Mission.LAND.value,
            target_drones=["1", "2"],
            start_preparing=True,
        )

        preparing = await tracker.get_status(creation.command_id)
        assert preparing["phase"] == "preparing"
        assert preparing["preparations"]["expected"] == 0
        assert preparing["progress"]["label"] == "Preparing dispatch"
        assert preparing["progress"]["message"] == (
            "Preparing the command for 2 target drone(s). No command has been sent."
        )

        assert await tracker.mark_submitted(creation.command_id) is True
        submitted = await tracker.get_status(creation.command_id)
        assert submitted["phase"] == "awaiting_ack"

    @pytest.mark.asyncio
    async def test_update_deadline_before_dispatch_is_post_preparation_and_guarded(self):
        from command_tracker import CommandTracker
        from src.enums import Mission

        tracker = CommandTracker(max_commands=10)
        creation = await tracker.create_or_replay_command(
            mission_type=Mission.LAND.value,
            target_drones=["1"],
            timeout_ms=60_000,
            start_preparing=True,
        )
        committed_deadline_ms = int(time.time() * 1000) + 120_000
        assert await tracker.update_deadline_before_dispatch(
            creation.command_id,
            committed_deadline_ms,
        ) is True
        updated = await tracker.get_status(creation.command_id)
        assert updated["timeout_at"] == committed_deadline_ms

        assert await tracker.mark_submitted(creation.command_id) is True
        assert await tracker.update_deadline_before_dispatch(
            creation.command_id,
            committed_deadline_ms + 60_000,
        ) is False
        unchanged = await tracker.get_status(creation.command_id)
        assert unchanged["timeout_at"] == updated["timeout_at"]

    @pytest.mark.asyncio
    async def test_repeated_mark_submitted_never_regresses_active_lifecycle(self):
        from command_tracker import CommandTracker

        tracker = _AuthenticatedTrackerHarness(CommandTracker(max_commands=10))
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=["1"],
        )
        assert await tracker.mark_submitted(command_id) is True
        first = await tracker.get_status(command_id)
        await tracker.record_ack(command_id, "1", category="accepted")
        await tracker.record_execution_start(command_id, "1")
        active = await tracker.get_status(command_id)
        assert active["phase"] == "in_progress"

        assert await tracker.mark_submitted(command_id) is True
        replayed = await tracker.get_status(command_id)
        assert replayed["phase"] == "in_progress"
        assert replayed["submitted_at"] == first["submitted_at"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("preparation_required", [False, True])
    async def test_fail_command_before_dispatch_closes_only_unattempted_work(
        self,
        preparation_required,
    ):
        from command_tracker import CommandTracker

        tracker = CommandTracker(max_commands=10)
        creation = await tracker.create_or_replay_command(
            mission_type=10,
            target_drones=["1"],
            preparation_required=preparation_required,
        )

        assert await tracker.fail_command_before_dispatch(
            creation.command_id,
            "  readiness coordinator stopped unexpectedly  ",
        ) is True
        terminal = await tracker.get_status(creation.command_id)
        assert terminal["phase"] == "terminal"
        assert terminal["outcome"] == "failed"
        assert terminal["error_summary"] == "readiness coordinator stopped unexpectedly"

        assert await tracker.fail_command_before_dispatch(
            creation.command_id,
            "must not resurrect or recount",
        ) is False
        stats = await tracker.get_statistics()
        assert stats["failed_commands"] == 1

    @pytest.mark.asyncio
    async def test_fail_command_before_dispatch_refuses_after_delivery_boundary(self):
        from command_tracker import CommandTracker

        tracker = CommandTracker(max_commands=10)
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=["1"],
        )

        assert await tracker.mark_submitted(command_id) is True
        assert await tracker.fail_command_before_dispatch(
            command_id,
            "dispatch worker raised after submission",
        ) is False
        status = await tracker.get_status(command_id)
        assert status["phase"] == "awaiting_ack"
        assert status["outcome"] is None

    @pytest.mark.asyncio
    async def test_fast_execution_callback_waits_for_all_target_ack_classifications(self, tracker):
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=["1", "2"],
        )

        await tracker.record_ack(command_id, hw_id="1", category="accepted")
        await tracker.record_execution(command_id, hw_id="1", success=True)

        early = await tracker.get_status(command_id)
        assert early["phase"] != "terminal"
        assert early["acks"]["received"] == 1

        await tracker.record_ack(command_id, hw_id="2", category="accepted")
        after_second_ack = await tracker.get_status(command_id)
        assert after_second_ack["phase"] != "terminal"

        await tracker.record_execution(command_id, hw_id="2", success=True)
        complete = await tracker.get_status(command_id)
        assert complete["phase"] == "terminal"
        assert complete["outcome"] == "completed"

    @pytest.mark.asyncio
    async def test_fast_execution_finalizes_only_after_remaining_target_is_rejected(self, tracker):
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=["1", "2"],
        )

        await tracker.record_ack(command_id, hw_id="1", category="accepted")
        await tracker.record_execution(command_id, hw_id="1", success=True)
        await tracker.record_ack(
            command_id,
            hw_id="2",
            category="rejected",
            error_code="E202",
        )

        status = await tracker.get_status(command_id)
        assert status["phase"] == "terminal"
        assert status["outcome"] == "partial"
        assert status["executions"]["succeeded"] == 1

    @pytest.mark.asyncio
    async def test_delivery_unknown_stays_open_and_later_execution_evidence_completes(self, tracker):
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=["1"],
        )

        await tracker.record_ack(
            command_id,
            hw_id="1",
            category="error",
            message="Response timed out",
            error_code="E300",
            delivery_state="delivery_unknown",
        )
        uncertain = await tracker.get_status(command_id)
        assert uncertain["phase"] == "pending_execution"
        assert uncertain["outcome"] is None
        assert uncertain["acks"]["details"]["1"]["delivery_state"] == "delivery_unknown"

        await tracker.record_execution(command_id, hw_id="1", success=True)
        complete = await tracker.get_status(command_id)
        assert complete["phase"] == "terminal"
        assert complete["outcome"] == "completed"
        assert complete["acks"]["details"]["1"]["delivery_state"] == "accepted_via_execution"

    @pytest.mark.asyncio
    async def test_delivery_unknown_target_prevents_premature_partial_terminal(self, tracker):
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=["1", "2"],
        )

        await tracker.record_ack(command_id, hw_id="1", category="accepted")
        await tracker.record_ack(
            command_id,
            hw_id="2",
            category="error",
            error_code="E300",
            delivery_state="delivery_unknown",
        )
        await tracker.record_execution(command_id, hw_id="1", success=True)

        uncertain = await tracker.get_status(command_id)
        assert uncertain["phase"] != "terminal"
        assert uncertain["outcome"] is None

        await tracker.record_execution(command_id, hw_id="2", success=True)
        complete = await tracker.get_status(command_id)
        assert complete["phase"] == "terminal"
        assert complete["outcome"] == "completed"

    @pytest.mark.asyncio
    async def test_unexpected_drone_callbacks_cannot_mutate_target_counts(self, tracker):
        from command_tracker import CommandCallbackAuthenticationError

        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=["1"],
        )

        assert await tracker.record_ack(command_id, hw_id="99", category="accepted") is False
        with pytest.raises(CommandCallbackAuthenticationError):
            await tracker.record_execution_start(command_id, hw_id="99")
        with pytest.raises(CommandCallbackAuthenticationError):
            await tracker.record_execution(command_id, hw_id="99", success=True)

        status = await tracker.get_status(command_id)
        assert status["acks"]["received"] == 0
        assert status["executions"]["received"] == 0

    @pytest.mark.asyncio
    async def test_tracker_rejects_duplicate_target_hardware_ids(self, tracker):
        with pytest.raises(ValueError, match="unique hardware IDs"):
            await tracker.create_or_replay_command(
                mission_type=10,
                target_drones=["1", "1"],
            )

    @pytest.mark.asyncio
    async def test_create_or_replay_command_reuses_existing_command_for_same_idempotency_key(self, tracker):
        from command_tracker import CommandTracker

        fingerprint = CommandTracker.build_request_fingerprint(
            {
                "mission_type": 10,
                "trigger_time": 0,
                "target_drone_ids": ["2", "1"],
            }
        )
        first = await tracker.create_or_replay_command(
            mission_type=10,
            target_drones=["1", "2"],
            params={"trigger_time": 0},
            idempotency_key="retry-123",
            request_fingerprint=fingerprint,
        )
        second = await tracker.create_or_replay_command(
            mission_type=10,
            target_drones=["1", "2"],
            params={"trigger_time": 0},
            idempotency_key="retry-123",
            request_fingerprint=fingerprint,
        )

        assert first.replayed is False
        assert second.replayed is True
        assert second.command_id == first.command_id

        status = await tracker.get_status(first.command_id)
        assert status["idempotency_key"] == "retry-123"

    @pytest.mark.asyncio
    async def test_create_or_replay_command_rejects_conflicting_payload_for_same_idempotency_key(self, tracker):
        from command_tracker import CommandIdempotencyConflictError, CommandTracker

        await tracker.create_or_replay_command(
            mission_type=10,
            target_drones=["1"],
            params={"trigger_time": 0},
            idempotency_key="retry-123",
            request_fingerprint=CommandTracker.build_request_fingerprint(
                {"mission_type": 10, "trigger_time": 0}
            ),
        )

        with pytest.raises(CommandIdempotencyConflictError):
            await tracker.create_or_replay_command(
                mission_type=101,
                target_drones=["1"],
                params={"trigger_time": 0},
                idempotency_key="retry-123",
                request_fingerprint=CommandTracker.build_request_fingerprint(
                    {"mission_type": 101, "trigger_time": 0}
                ),
            )

    @pytest.mark.asyncio
    async def test_record_ack_accepted(self, tracker):
        """Test recording accepted acknowledgments"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2']
        )

        # Record ACK from drone 1
        success = await tracker.record_ack(
            command_id, hw_id='1', category='accepted', message='OK'
        )
        assert success

        status = await tracker.get_status(command_id)
        assert status['acks']['received'] == 1
        assert status['acks']['accepted'] == 1
        assert '1' in status['acks']['details']

        # Record ACK from drone 2
        await tracker.record_ack(
            command_id, hw_id='2', category='accepted'
        )

        status = await tracker.get_status(command_id)
        assert status['acks']['received'] == 2
        assert status['acks']['accepted'] == 2
        assert status['status'] == 'executing'  # All ACKs received
        assert status['phase'] == 'pending_execution'

    @pytest.mark.asyncio
    async def test_record_ack_rejected(self, tracker):
        """Test recording rejected acknowledgments"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2']
        )

        # Both drones reject
        await tracker.record_ack(
            command_id, hw_id='1',
            category='rejected',
            error_code='E202', message='Not ready to arm'
        )
        await tracker.record_ack(
            command_id, hw_id='2',
            category='rejected',
            error_code='E202'
        )

        status = await tracker.get_status(command_id)
        assert status['acks']['rejected'] == 2
        assert status['status'] == 'failed'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'failed'
        assert 'E202' in status['acks']['details']['1']['error_code']

    @pytest.mark.asyncio
    async def test_record_execution(self, tracker):
        """Test recording execution results"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1']
        )

        # ACK first
        await tracker.record_ack(command_id, hw_id='1', category='accepted')

        # Record execution
        success = await tracker.record_execution(
            command_id, hw_id='1', success=True,
            duration_ms=5000
        )
        assert success

        status = await tracker.get_status(command_id)
        assert status['executions']['started'] == 1
        assert status['executions']['succeeded'] == 1
        assert status['status'] == 'completed'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'completed'
        assert status['progress']['stage'] == 'completed'

    @pytest.mark.asyncio
    async def test_progress_stage_marks_future_trigger_as_scheduled(self, tracker):
        """Pending execution with a future trigger should report a scheduled stage."""
        future_trigger = int(time.time()) + 120
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2'],
            params={'trigger_time': future_trigger},
        )

        await tracker.record_ack(command_id, hw_id='1', category='accepted')
        await tracker.record_ack(command_id, hw_id='2', category='accepted')

        status = await tracker.get_status(command_id)
        assert status['phase'] == 'pending_execution'
        assert status['progress']['stage'] == 'scheduled'
        assert status['progress']['scheduled_trigger_time'] == future_trigger * 1000

    @pytest.mark.asyncio
    async def test_progress_stage_marks_finishing_when_some_drones_complete(self, tracker):
        """In-progress commands should surface a finishing stage once some drones complete."""
        command_id = await tracker.create_command(
            mission_type=4,
            target_drones=['1', '2'],
        )

        await tracker.record_ack(command_id, hw_id='1', category='accepted')
        await tracker.record_ack(command_id, hw_id='2', category='accepted')
        await tracker.record_execution_start(command_id, hw_id='1')
        await tracker.record_execution_start(command_id, hw_id='2')
        await tracker.record_execution(command_id, hw_id='1', success=True, duration_ms=5000)

        status = await tracker.get_status(command_id)
        assert status['phase'] == 'in_progress'
        assert status['progress']['stage'] == 'finishing'
        assert status['progress']['completed'] == 1
        assert status['progress']['remaining'] == 1

    @pytest.mark.asyncio
    async def test_execution_start_promotes_missing_ack_to_accepted(self, tracker):
        """Execution-start should count as acceptance proof if the HTTP ACK was lost."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1'],
        )

        await tracker.record_execution_start(command_id, hw_id='1')

        status = await tracker.get_status(command_id)
        assert status['acks']['received'] == 1
        assert status['acks']['accepted'] == 1
        assert status['acks']['details']['1']['category'] == 'accepted'
        assert 'execution-start' in status['acks']['details']['1']['message']
        assert status['phase'] == 'in_progress'
        assert status['progress']['active'] == 1

    @pytest.mark.asyncio
    async def test_execution_result_upgrades_offline_ack_to_accepted(self, tracker):
        """Execution-result must override an earlier offline ACK classification."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1'],
        )

        await tracker.record_ack(command_id, hw_id='1', category='offline', message='Timed out')
        await tracker.record_execution(command_id, hw_id='1', success=True, duration_ms=5000)

        status = await tracker.get_status(command_id)
        assert status['acks']['offline'] == 0
        assert status['acks']['accepted'] == 1
        assert status['acks']['details']['1']['category'] == 'accepted'
        assert 'execution-result' in status['acks']['details']['1']['message']
        assert status['status'] == 'completed'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'completed'

        stats = await tracker.get_statistics()
        assert stats['failed_commands'] == 0
        assert stats['successful_commands'] == 1

    @pytest.mark.asyncio
    async def test_partial_success(self, tracker):
        """Test partial success scenario"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2', '3']
        )

        # All accept
        for hw_id in ['1', '2', '3']:
            await tracker.record_ack(command_id, hw_id=hw_id, category='accepted')

        # 2 succeed, 1 fails
        await tracker.record_execution(command_id, hw_id='1', success=True)
        await tracker.record_execution(command_id, hw_id='2', success=True)
        await tracker.record_execution(
            command_id, hw_id='3', success=False,
            error_message='Script crashed'
        )

        status = await tracker.get_status(command_id)
        assert status['executions']['succeeded'] == 2
        assert status['executions']['failed'] == 1
        assert status['status'] == 'partial'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'partial'
        assert 'drone 3: Script crashed' in status['error_summary']

    @pytest.mark.asyncio
    async def test_all_execution_failures_include_first_drone_reason(self, tracker):
        """All-failed outcomes should preserve the concrete execution failure reason."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1']
        )

        await tracker.record_ack(command_id, hw_id='1', category='accepted')
        await tracker.record_execution(
            command_id,
            hw_id='1',
            success=False,
            error_message='precision_move requires fresh local telemetry',
            exit_code=1,
        )

        status = await tracker.get_status(command_id)
        assert status['status'] == 'failed'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'failed'
        assert 'drone 1: precision_move requires fresh local telemetry' in status['error_summary']

    @pytest.mark.asyncio
    async def test_partial_success_when_some_targets_never_accept(self, tracker):
        """Commands that only reach part of the target set should not count as full success."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2', '3', '4']
        )

        await tracker.record_ack(command_id, hw_id='1', category='accepted')
        await tracker.record_ack(command_id, hw_id='2', category='accepted')
        await tracker.record_ack(command_id, hw_id='3', category='rejected')
        await tracker.record_ack(command_id, hw_id='4', category='rejected')

        await tracker.record_execution(command_id, hw_id='1', success=True)
        await tracker.record_execution(command_id, hw_id='2', success=True)

        status = await tracker.get_status(command_id)
        assert status['status'] == 'partial'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'partial'
        assert 'Only 2/4 targets accepted' in status['error_summary']

    @pytest.mark.asyncio
    async def test_superseded_execution_results_surface_superseded_outcome(self, tracker):
        """Typed and legacy nodes compose into one superseded fleet outcome."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2']
        )

        for hw_id in ['1', '2']:
            await tracker.record_ack(command_id, hw_id=hw_id, category='accepted')

        await tracker.record_execution(
            command_id,
            hw_id='1',
            success=False,
            outcome='superseded',
            error_message='Precision move stopped after SIGTERM.',
        )
        await tracker.record_execution(
            command_id,
            hw_id='2',
            success=False,
            error_message='Superseded by a newer command before completion',
        )

        status = await tracker.get_status(command_id)
        assert status['status'] == 'cancelled'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'superseded'
        assert status['error_summary'] == 'Superseded by newer command on all 2 drones'
        assert status['executions']['details']['1']['outcome'] == 'superseded'
        assert status['executions']['details']['2']['outcome'] is None

    @pytest.mark.asyncio
    async def test_explicit_failed_outcome_overrides_supersede_text(self, tracker):
        """Typed failure authority must beat misleading compatibility text."""
        command_id = await tracker.create_command(mission_type=10, target_drones=['1'])
        await tracker.record_ack(command_id, hw_id='1', category='accepted')
        await tracker.record_execution(
            command_id,
            hw_id='1',
            success=False,
            outcome='failed',
            error_message='Superseded by a newer command before completion',
        )

        status = await tracker.get_status(command_id)
        assert status['status'] == 'failed'
        assert status['outcome'] == 'failed'

    @pytest.mark.asyncio
    async def test_legacy_cleanup_unconfirmed_message_is_not_safe_supersede(self, tracker):
        """Broad legacy text matching must not hide an unconfirmed cleanup."""
        command_id = await tracker.create_command(mission_type=10, target_drones=['1'])
        await tracker.record_ack(command_id, hw_id='1', category='accepted')
        await tracker.record_execution(
            command_id,
            hw_id='1',
            success=False,
            error_message=(
                'Superseded by a newer command and force-killed before TAKE_OFF/TEST '
                'safety cleanup could be confirmed.'
            ),
        )

        status = await tracker.get_status(command_id)
        assert status['status'] == 'failed'
        assert status['outcome'] == 'failed'

    @pytest.mark.asyncio
    async def test_late_execution_after_timeout_does_not_mutate_terminal_outcome(self, tracker):
        """Late execution evidence should be stored without resurrecting a timed-out command."""
        from schemas import CommandStatusResponse

        command_id = await tracker.create_command(
            mission_type=4,
            target_drones=['1'],
            timeout_ms=1,
        )
        callback_capability = await tracker._capability(command_id, '1')

        await tracker.record_ack(command_id, hw_id='1', category='accepted')
        await asyncio.sleep(0.01)
        timed_out = await tracker.check_timeouts()

        assert command_id in timed_out

        await tracker.record_execution(
            command_id,
            hw_id='1',
            success=True,
            outcome='completed',
            duration_ms=5000,
            callback_capability=callback_capability,
        )

        status = await tracker.get_status(command_id)
        validated = CommandStatusResponse.model_validate(status)

        assert validated.status.value == 'timeout'
        assert validated.phase.value == 'terminal'
        assert validated.outcome.value == 'timeout'
        assert validated.executions.received == 0
        assert validated.executions.succeeded == 0
        assert validated.late_reports.executions.received == 1
        assert validated.late_reports.executions.succeeded == 1
        assert validated.late_reports.execution_starts.received == 1
        assert validated.late_reports.executions.details['1'].duration_ms == 5000
        assert validated.late_reports.executions.details['1'].outcome.value == 'completed'

    @pytest.mark.asyncio
    async def test_late_ack_after_timeout_does_not_change_terminal_counts(self, tracker):
        """Late ACKs should remain diagnostic evidence only once a command is terminal."""
        command_id = await tracker.create_command(
            mission_type=4,
            target_drones=['1'],
            timeout_ms=1,
        )

        await asyncio.sleep(0.01)
        timed_out = await tracker.check_timeouts()

        assert command_id in timed_out

        await tracker.record_ack(
            command_id,
            hw_id='1',
            category='accepted',
            message='Late ACK after timeout',
        )

        status = await tracker.get_status(command_id)

        assert status['status'] == 'timeout'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'timeout'
        assert status['acks']['received'] == 0
        assert status['acks']['accepted'] == 0
        assert status['late_reports']['acks']['received'] == 1
        assert status['late_reports']['acks']['accepted'] == 1
        assert status['late_reports']['acks']['details']['1']['message'] == 'Late ACK after timeout'

    @pytest.mark.asyncio
    async def test_cancel_command(self, tracker):
        """Test command cancellation"""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1']
        )

        success = await tracker.cancel_command(command_id, "Test cancel")
        assert success

        status = await tracker.get_status(command_id)
        assert status['status'] == 'cancelled'
        assert status['phase'] == 'terminal'
        assert status['outcome'] == 'cancelled'

    @pytest.mark.asyncio
    async def test_get_recent_commands(self, tracker):
        """Test retrieving recent commands"""
        # Create multiple commands with explicit pauses for timestamp ordering
        created_ids = []
        for i in range(5):
            cmd_id = await tracker.create_command(
                mission_type=10 + i,
                target_drones=['1']
            )
            created_ids.append(cmd_id)

        commands = await tracker.get_recent(limit=3)
        assert len(commands) == 3

        # Verify we got 3 commands (order may vary with same timestamps)
        command_ids = [c['command_id'] for c in commands]
        assert len(set(command_ids)) == 3  # All unique

    @pytest.mark.asyncio
    async def test_statistics(self, tracker):
        """Test command statistics"""
        # Create and complete a command
        cmd1 = await tracker.create_command(mission_type=10, target_drones=['1'])
        await tracker.record_ack(cmd1, '1', category='accepted')
        await tracker.record_execution(cmd1, '1', True)

        # Create a failed command
        cmd2 = await tracker.create_command(mission_type=10, target_drones=['2'])
        await tracker.record_ack(cmd2, '2', category='rejected', error_code='E200')

        stats = await tracker.get_statistics()
        assert stats['total_commands'] == 2
        assert stats['successful_commands'] == 1
        assert stats['failed_commands'] == 1

    @pytest.mark.asyncio
    async def test_statistics_count_partial_target_shortfall(self, tracker):
        """ACK shortfalls should contribute to partial command stats, not full success."""
        command_id = await tracker.create_command(
            mission_type=10,
            target_drones=['1', '2', '3']
        )
        await tracker.record_ack(command_id, '1', category='accepted')
        await tracker.record_ack(command_id, '2', category='accepted')
        await tracker.record_ack(command_id, '3', category='rejected')
        await tracker.record_execution(command_id, '1', True)
        await tracker.record_execution(command_id, '2', True)

        stats = await tracker.get_statistics()
        assert stats['partial_commands'] == 1
        assert stats['successful_commands'] == 0
        assert stats['success_rate'] == 0.0

    @pytest.mark.asyncio
    async def test_command_eviction(self):
        """Test that oldest terminal history is evicted when limit is reached."""
        from command_tracker import CommandTracker
        tracker = CommandTracker(max_commands=3)

        # Create 4 commands
        ids = []
        for i in range(4):
            cmd_id = await tracker.create_command(
                mission_type=10,
                target_drones=['1']
            )
            ids.append(cmd_id)
            if i < 3:
                assert await tracker.cancel_command(cmd_id, "terminal history fixture")

        # First command should be evicted
        status = await tracker.get_status(ids[0])
        assert status is None

        # Last 3 should still exist
        for cmd_id in ids[1:]:
            status = await tracker.get_status(cmd_id)
            assert status is not None

    @pytest.mark.asyncio
    async def test_active_commands_are_never_capacity_evicted(self):
        from command_tracker import CommandTracker, CommandTrackerCapacityError

        tracker = CommandTracker(max_commands=2)
        first = await tracker.create_command(mission_type=10, target_drones=['1'])
        second = await tracker.create_command(mission_type=10, target_drones=['2'])

        with pytest.raises(CommandTrackerCapacityError, match="occupied by active commands"):
            await tracker.create_command(mission_type=10, target_drones=['3'])

        assert await tracker.get_status(first) is not None
        assert await tracker.get_status(second) is not None

    @pytest.mark.asyncio
    async def test_terminal_command_cannot_be_resurrected_by_submit_ack_or_execution(self):
        from command_tracker import CommandTracker

        tracker = CommandTracker(max_commands=10)
        command_id = await tracker.create_command(mission_type=10, target_drones=['1'])
        capability = (await tracker.get_callback_capabilities(command_id))['1']
        await tracker.record_ack(command_id, '1', category='rejected', error_code='E202')
        terminal_before = await tracker.get_status(command_id)

        assert await tracker.mark_submitted(command_id) is False
        assert await tracker.record_ack(command_id, '1', category='accepted') is True
        assert await tracker.record_execution(
            command_id,
            '1',
            True,
            callback_capability=capability,
        ) is True

        terminal_after = await tracker.get_status(command_id)
        assert terminal_after['status'] == terminal_before['status'] == 'failed'
        assert terminal_after['phase'] == terminal_before['phase'] == 'terminal'
        assert terminal_after['outcome'] == terminal_before['outcome'] == 'failed'
        assert terminal_after['acks']['accepted'] == 0
        assert terminal_after['executions']['received'] == 0
        assert terminal_after['late_reports']['executions']['received'] == 1

        with pytest.raises(RuntimeError, match="unavailable after command terminalization"):
            await tracker.get_callback_capabilities(command_id)

    @pytest.mark.asyncio
    async def test_callback_capability_is_bound_to_exact_command_and_target_and_not_exposed(self):
        from command_tracker import CommandCallbackAuthenticationError, CommandTracker

        tracker = CommandTracker(max_commands=10)
        first = await tracker.create_command(mission_type=10, target_drones=['1', '2'])
        second = await tracker.create_command(mission_type=10, target_drones=['1'])
        first_caps = await tracker.get_callback_capabilities(first)
        second_caps = await tracker.get_callback_capabilities(second)

        assert first_caps['1'] != first_caps['2']
        assert first_caps['1'] != second_caps['1']
        with pytest.raises(CommandCallbackAuthenticationError):
            await tracker.record_execution_start(first, '1')
        with pytest.raises(CommandCallbackAuthenticationError):
            await tracker.record_execution_start(
                first,
                '1',
                callback_capability=first_caps['2'],
            )
        with pytest.raises(CommandCallbackAuthenticationError):
            await tracker.record_execution_start(
                first,
                '1',
                callback_capability=second_caps['1'],
            )

        status = await tracker.get_status(first)
        serialized = json.dumps(status)
        assert first_caps['1'] not in serialized
        assert first_caps['2'] not in serialized
        assert 'callback_capability' not in serialized

    @pytest.mark.asyncio
    async def test_authenticated_execution_cannot_override_definite_rejection_or_protocol_error(self):
        from command_tracker import CommandTracker

        for category, delivery_state in (
            ('rejected', 'rejected'),
            ('error', 'protocol_error'),
        ):
            tracker = CommandTracker(max_commands=10)
            command_id = await tracker.create_command(
                mission_type=10,
                target_drones=['1', '2'],
            )
            capability = (await tracker.get_callback_capabilities(command_id))['2']
            await tracker.record_ack(command_id, '1', category='accepted')
            await tracker.record_ack(
                command_id,
                '2',
                category=category,
                delivery_state=delivery_state,
            )

            assert await tracker.record_execution_start(
                command_id,
                '2',
                callback_capability=capability,
            ) is False
            status = await tracker.get_status(command_id)
            assert status['acks']['accepted'] == 1
            assert status['acks']['details']['2']['category'] == category
            assert status['executions']['started'] == 0

    @pytest.mark.asyncio
    async def test_authenticated_callback_replay_is_idempotent(self):
        from command_tracker import CommandTracker

        tracker = CommandTracker(max_commands=10)
        command_id = await tracker.create_command(mission_type=10, target_drones=['1'])
        capability = (await tracker.get_callback_capabilities(command_id))['1']
        await tracker.record_ack(command_id, '1', category='accepted')

        for _ in range(2):
            assert await tracker.record_execution_start(
                command_id,
                '1',
                callback_capability=capability,
            ) is True
        for _ in range(2):
            assert await tracker.record_execution(
                command_id,
                '1',
                True,
                duration_ms=50,
                callback_capability=capability,
            ) is True

        status = await tracker.get_status(command_id)
        assert status['executions']['started'] == 1
        assert status['executions']['received'] == 1
        assert status['outcome'] == 'completed'


class TestFleetGitPostconditionCompletion:
    """Keep Fleet Ops Git verification separate from transport callbacks.

    UPDATE_CODE can restart an old node before that node reports execution.
    These tests define the tracker boundary: the Fleet Git postcondition is the
    only terminal authority, while capability-authenticated node reports remain
    durable diagnostic evidence.
    """

    @staticmethod
    async def _create(targets=("1", "2")):
        from command_tracker import CommandCompletionAuthority, CommandTracker

        tracker = CommandTracker(max_commands=20)
        creation = await tracker.create_or_replay_command(
            mission_type=Mission.UPDATE_CODE.value,
            target_drones=list(targets),
            completion_authority=CommandCompletionAuthority.FLEET_GIT_POSTCONDITION,
        )
        capabilities = await tracker.get_callback_capabilities(creation.command_id)
        assert await tracker.mark_submitted(creation.command_id) is True
        return tracker, creation.command_id, capabilities

    @pytest.mark.asyncio
    async def test_authoritative_batch_requires_exact_targets_capabilities_and_authority(self):
        from command_tracker import (
            CommandCallbackAuthenticationError,
            CommandCompletionAuthority,
        )

        tracker, command_id, capabilities = await self._create()
        before = await tracker.get_status(command_id)

        invalid_batches = (
            ({"1": {"success": True}}, capabilities, ValueError),
            (
                {
                    "1": {"success": True},
                    "2": {"success": True},
                    "3": {"success": True},
                },
                capabilities,
                ValueError,
            ),
            (
                {"1": {"success": True}, "2": {"success": True}},
                {"1": capabilities["1"]},
                CommandCallbackAuthenticationError,
            ),
            (
                {"1": {"success": True}, "2": {"success": True}},
                {**capabilities, "3": capabilities["1"]},
                CommandCallbackAuthenticationError,
            ),
            (
                {"1": {"success": True}, "2": {"success": True}},
                {"1": capabilities["2"], "2": capabilities["1"]},
                CommandCallbackAuthenticationError,
            ),
        )
        for results, supplied_capabilities, expected_error in invalid_batches:
            with pytest.raises(expected_error):
                await tracker.record_authoritative_completion(
                    command_id,
                    results,
                    completion_authority=(
                        CommandCompletionAuthority.FLEET_GIT_POSTCONDITION
                    ),
                    callback_capabilities=supplied_capabilities,
                )

        with pytest.raises(ValueError):
            await tracker.record_authoritative_completion(
                command_id,
                {"1": {"success": True}, "2": {"success": True}},
                completion_authority=CommandCompletionAuthority.NODE_CALLBACK,
                callback_capabilities=capabilities,
            )

        after = await tracker.get_status(command_id)
        assert after["status"] == before["status"]
        assert after["phase"] == before["phase"]
        assert after["outcome"] is None
        assert after["executions"]["received"] == 0
        assert after["node_execution_reports"]["received"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("results", "expected_status", "expected_outcome", "succeeded", "failed"),
        (
            (
                {"1": {"success": True}, "2": {"success": True}},
                "completed",
                "completed",
                2,
                0,
            ),
            (
                {
                    "1": {"success": False, "error_message": "commit mismatch"},
                    "2": {"success": False, "error_message": "dirty worktree"},
                },
                "failed",
                "failed",
                0,
                2,
            ),
            (
                {
                    "1": {"success": True},
                    "2": {"success": False, "error_message": "runtime still old"},
                },
                "partial",
                "partial",
                1,
                1,
            ),
        ),
    )
    async def test_postcondition_is_terminal_truth_for_all_result_combinations(
        self,
        results,
        expected_status,
        expected_outcome,
        succeeded,
        failed,
    ):
        from command_tracker import CommandCompletionAuthority

        tracker, command_id, capabilities = await self._create()
        for hw_id in ("1", "2"):
            await tracker.record_ack(command_id, hw_id, category="accepted")

        assert await tracker.record_authoritative_completion(
            command_id,
            results,
            completion_authority=CommandCompletionAuthority.FLEET_GIT_POSTCONDITION,
            callback_capabilities=capabilities,
        ) is True

        status = await tracker.get_status(command_id)
        assert status["completion_authority"] == "fleet_git_postcondition"
        assert status["status"] == expected_status
        assert status["phase"] == "terminal"
        assert status["outcome"] == expected_outcome
        assert status["executions"]["received"] == 2
        assert status["executions"]["succeeded"] == succeeded
        assert status["executions"]["failed"] == failed
        for hw_id, result in results.items():
            assert status["executions"]["details"][hw_id]["success"] is result["success"]
            assert status["executions"]["details"][hw_id]["error"] == result.get(
                "error_message"
            )

    @pytest.mark.asyncio
    async def test_postcondition_completion_does_not_rewrite_missing_or_failed_acks(self):
        from command_tracker import CommandCompletionAuthority

        tracker, command_id, capabilities = await self._create(("1", "2", "3", "4"))
        await tracker.record_ack(command_id, "1", category="accepted")
        await tracker.record_ack(
            command_id,
            "2",
            category="offline",
            delivery_state="delivery_unknown",
        )
        await tracker.record_ack(
            command_id,
            "3",
            category="rejected",
            delivery_state="rejected",
            error_code="E202",
        )

        assert await tracker.record_authoritative_completion(
            command_id,
            {hw_id: {"success": True} for hw_id in ("1", "2", "3", "4")},
            completion_authority=CommandCompletionAuthority.FLEET_GIT_POSTCONDITION,
            callback_capabilities=capabilities,
        ) is True

        status = await tracker.get_status(command_id)
        assert status["outcome"] == "completed"
        assert status["acks"]["expected"] == 4
        assert status["acks"]["received"] == 3
        assert status["acks"]["accepted"] == 1
        assert status["acks"]["offline"] == 1
        assert status["acks"]["rejected"] == 1
        assert status["acks"]["details"]["2"]["delivery_state"] == "delivery_unknown"
        assert status["acks"]["details"]["3"]["error_code"] == "E202"
        assert "4" not in status["acks"]["details"]

    @pytest.mark.asyncio
    async def test_node_callback_before_verifier_is_diagnostic_and_non_terminal(self):
        tracker, command_id, capabilities = await self._create(("1",))
        await tracker.record_ack(command_id, "1", category="accepted")

        assert await tracker.record_execution_start(
            command_id,
            "1",
            callback_capability=capabilities["1"],
        ) is True
        assert await tracker.record_execution(
            command_id,
            "1",
            True,
            duration_ms=123,
            callback_capability=capabilities["1"],
        ) is True

        status = await tracker.get_status(command_id)
        assert status["phase"] != "terminal"
        assert status["outcome"] is None
        assert status["executions"]["received"] == 0
        assert status["node_execution_reports"]["started"] == 1
        assert status["node_execution_reports"]["received"] == 1
        assert status["node_execution_reports"]["details"]["1"]["success"] is True
        assert status["node_execution_reports"]["details"]["1"]["duration_ms"] == 123

    @pytest.mark.asyncio
    async def test_node_callback_after_verifier_cannot_change_outcome_and_surfaces_discrepancy(self):
        from command_tracker import CommandCompletionAuthority

        tracker, command_id, capabilities = await self._create(("1",))
        await tracker.record_ack(command_id, "1", category="accepted")
        await tracker.record_authoritative_completion(
            command_id,
            {"1": {"success": True}},
            completion_authority=CommandCompletionAuthority.FLEET_GIT_POSTCONDITION,
            callback_capabilities=capabilities,
        )
        completed = await tracker.get_status(command_id)

        assert await tracker.record_execution(
            command_id,
            "1",
            False,
            error_message="node callback reported script failure",
            callback_capability=capabilities["1"],
        ) is True

        status = await tracker.get_status(command_id)
        assert status["status"] == "completed"
        assert status["outcome"] == "completed"
        assert status["completed_at"] == completed["completed_at"]
        assert status["executions"]["details"]["1"]["success"] is True
        assert status["node_execution_reports"]["details"]["1"]["success"] is False
        assert "1" in status["completion_discrepancies"]
        assert "script failure" in status["node_execution_reports"]["details"]["1"]["error"]

    @pytest.mark.asyncio
    async def test_authoritative_completion_batch_is_idempotent(self):
        from command_tracker import CommandCompletionAuthority

        tracker, command_id, capabilities = await self._create()
        for hw_id in ("1", "2"):
            await tracker.record_ack(command_id, hw_id, category="accepted")
        results = {"1": {"success": True}, "2": {"success": True}}

        for _ in range(2):
            assert await tracker.record_authoritative_completion(
                command_id,
                results,
                completion_authority=CommandCompletionAuthority.FLEET_GIT_POSTCONDITION,
                callback_capabilities=capabilities,
            ) is True

        status = await tracker.get_status(command_id)
        stats = await tracker.get_statistics()
        assert status["outcome"] == "completed"
        assert status["executions"]["received"] == 2
        assert stats["successful_commands"] == 1

    @pytest.mark.asyncio
    async def test_status_exposes_authority_and_diagnostics_but_never_capabilities(self):
        from schemas import CommandStatusResponse

        tracker, command_id, capabilities = await self._create(("1",))
        await tracker.record_ack(command_id, "1", category="accepted")
        await tracker.record_execution(
            command_id,
            "1",
            True,
            callback_capability=capabilities["1"],
        )

        status = await tracker.get_status(command_id)
        public_status = CommandStatusResponse.model_validate(status).model_dump(mode="json")
        serialized = json.dumps(public_status)
        assert status["completion_authority"] == "fleet_git_postcondition"
        assert "node_execution_reports" in status
        assert public_status["completion_authority"] == "fleet_git_postcondition"
        assert public_status["node_execution_reports"]["received"] == 1
        assert capabilities["1"] not in serialized
        assert "callback_capability" not in serialized
        assert "callback_capabilities" not in serialized


# ============================================================================
# Command Validation Tests
# ============================================================================

class TestCommandValidation:
    """Test command validation in drone_api_server"""

    @pytest.fixture
    def mock_drone_config(self):
        """Create mock drone config"""
        config = Mock()
        config.hw_id = '1'
        config.pos_id = 0
        config.state = 0  # IDLE
        config.mission = 0  # NONE
        config.is_ready_to_arm = True
        config.is_armed = False
        config.heartbeat_timestamp_ms = 0
        config.global_position_timestamp_ms = 0
        config.relative_altitude_m = None
        config.current_command_id = None
        return config

    @pytest.fixture
    def mock_params(self):
        """Create mock params"""
        params = Mock()
        params.max_takeoff_alt = 50
        params.drone_api_port = 7070
        params.LOCAL_MAVLINK_STALE_TIMEOUT_SEC = 15
        return params

    @pytest.fixture
    def api_server(self, mock_params, mock_drone_config):
        """Create DroneAPIServer instance"""
        from src.drone_api_server import DroneAPIServer
        server = DroneAPIServer(mock_params, mock_drone_config)
        return server

    def test_validate_missing_mission_type(self, api_server):
        """Test validation fails for missing mission_type."""
        result = api_server._validate_command({
            'trigger_time': 0
        })
        assert not result['valid']
        assert 'E100' in result['error_code']

    def test_validate_missing_trigger_time(self, api_server):
        """Test validation fails for missing trigger_time."""
        result = api_server._validate_command({
            'mission_type': Mission.TAKE_OFF.value
        })
        assert not result['valid']
        assert 'E102' in result['error_code']

    def test_validate_invalid_mission_type(self, api_server):
        """Test validation fails for unknown mission type"""
        result = api_server._validate_command({
            'mission_type': 9999,
            'trigger_time': 0
        })
        assert not result['valid']
        assert 'E101' in result['error_code']

    def test_validate_invalid_mission_type_format(self, api_server):
        """Test validation fails for non-numeric mission type"""
        result = api_server._validate_command({
            'mission_type': 'not_a_number',
            'trigger_time': 0
        })
        assert not result['valid']
        assert 'E107' in result['error_code']

    def test_validate_negative_trigger_time(self, api_server):
        """Test validation fails for negative trigger time"""
        result = api_server._validate_command({
            'mission_type': Mission.TAKE_OFF.value,
            'trigger_time': -1
        })
        assert not result['valid']
        assert 'E103' in result['error_code']

    def test_validate_invalid_altitude(self, api_server):
        """Test validation fails for invalid takeoff altitude"""
        result = api_server._validate_command({
            'mission_type': Mission.TAKE_OFF.value,
            'trigger_time': 0,
            'takeoff_altitude': -5
        })
        assert not result['valid']
        assert 'E104' in result['error_code']

    def test_validate_altitude_exceeds_max(self, api_server):
        """Test validation fails for altitude exceeding maximum"""
        result = api_server._validate_command({
            'mission_type': Mission.TAKE_OFF.value,
            'trigger_time': 0,
            'takeoff_altitude': 100  # Exceeds max of 50
        })
        assert not result['valid']
        assert 'E104' in result['error_code']

    def test_validate_success(self, api_server):
        """Test validation succeeds for valid command"""
        result = api_server._validate_command({
            'mission_type': Mission.TAKE_OFF.value,
            'trigger_time': 0,
            'takeoff_altitude': 10
        })
        assert result['valid']

    def test_validate_precision_move_requires_payload(self, api_server):
        from src.enums import Mission, CommandErrorCode

        result = api_server._validate_command({
            'mission_type': Mission.PRECISION_MOVE.value,
            'trigger_time': 0,
        })
        assert not result['valid']
        assert result['error_code'] == CommandErrorCode.INVALID_FORMAT.value

    def test_validate_precision_move_requires_immediate_trigger(self, api_server):
        from src.enums import Mission, CommandErrorCode

        result = api_server._validate_command({
            'mission_type': Mission.PRECISION_MOVE.value,
            'trigger_time': 5,
            'precision_move': {'frame': 'body', 'translation_m': {'forward': 1.0}},
        })
        assert not result['valid']
        assert result['error_code'] == CommandErrorCode.INVALID_TRIGGER_TIME.value

    def test_check_state_executing(self, api_server):
        """Test state check fails during execution"""
        api_server.drone_config.state = 2  # MISSION_EXECUTING

        result = api_server._check_state_preconditions(mission_type=10)  # TAKE_OFF
        assert not result['valid']
        assert 'E203' in result['error_code']

    def test_check_state_emergency_allowed(self, api_server):
        """Test emergency commands allowed during execution"""
        api_server.drone_config.state = 2  # MISSION_EXECUTING

        result = api_server._check_state_preconditions(mission_type=105)  # KILL_TERMINATE
        assert result['valid']

    def test_check_state_precision_move_allowed_as_override(self, api_server):
        from src.enums import Mission

        api_server.drone_config.state = 2  # MISSION_EXECUTING
        api_server.drone_config.is_armed = True
        now_ms = time.time_ns() // 1_000_000
        api_server.drone_config.heartbeat_timestamp_ms = now_ms
        api_server.drone_config.global_position_timestamp_ms = now_ms
        api_server.drone_config.relative_altitude_m = 5.0
        result = api_server._check_state_preconditions(mission_type=Mission.PRECISION_MOVE.value)
        assert result['valid']

    def test_check_state_hold_requires_armed_airborne(self, api_server):
        from src.enums import Mission, CommandErrorCode

        api_server.drone_config.is_armed = False

        result = api_server._check_state_preconditions(mission_type=Mission.HOLD.value)

        assert not result['valid']
        assert result['error_code'] == CommandErrorCode.NOT_ARMED.value
        assert 'HOLD requires fresh evidence of an armed airborne drone' in result['message']

    def test_check_state_swarm_trajectory_allowed_as_override(self, api_server):
        from src.enums import Mission

        api_server.drone_config.state = 2  # MISSION_EXECUTING
        result = api_server._check_state_preconditions(mission_type=Mission.SWARM_TRAJECTORY.value)
        assert result['valid']

    def test_custom_show_allowed_to_replace_smart_swarm_leader(self, api_server):
        from src.enums import Mission, State

        api_server.drone_config.state = State.MISSION_EXECUTING.value
        api_server.drone_config.mission = Mission.SMART_SWARM.value

        result = api_server._check_state_preconditions(mission_type=Mission.CUSTOM_CSV_DRONE_SHOW.value)

        assert result['valid']

    def test_standard_show_allowed_to_replace_smart_swarm_leader(self, api_server):
        from src.enums import Mission, State

        api_server.drone_config.state = State.MISSION_EXECUTING.value
        api_server.drone_config.mission = Mission.SMART_SWARM.value

        result = api_server._check_state_preconditions(mission_type=Mission.DRONE_SHOW_FROM_CSV.value)

        assert result['valid']

    def test_check_state_takeoff_does_not_treat_cached_readiness_as_command_authority(self, api_server):
        """Cached telemetry remains advisory; mission startup performs the live gate."""
        api_server.drone_config.is_ready_to_arm = False

        result = api_server._check_state_preconditions(mission_type=10)  # TAKE_OFF
        assert result['valid']
        assert result['message'] == 'State preconditions met'


# ============================================================================
# Schema Validation Tests
# ============================================================================

class TestSchemas:
    """Test Pydantic schema validation"""

    def test_submit_command_request(self):
        """Test SubmitCommandRequest schema"""
        from schemas import SubmitCommandRequest
        from src.enums import Mission

        # Valid request
        request = SubmitCommandRequest(
            mission_type=10,
            trigger_time=0,
            target_drone_ids=["1"],
            takeoff_altitude=10.0
        )
        assert request.mission_type == 10
        assert request.model_dump()["mission_type"] == 10
        assert request.model_dump()["trigger_time"] == 0

        with pytest.raises(Exception, match="Unsupported command-submit field"):
            SubmitCommandRequest(
                missionType="TAKE_OFF",
                triggerTime=0,
                target_drones=["1", "2"],
                operatorLabel="Launch now",
                clientCommandId="retry-123",
            )

        all_fleet_request = SubmitCommandRequest(
            mission_type=10,
            trigger_time=0,
            target_scope="all",
        )
        assert all_fleet_request.target_drone_ids is None
        assert all_fleet_request.target_scope == "all"

        with pytest.raises(Exception, match="at least one"):
            SubmitCommandRequest(mission_type=10, target_drone_ids=[])

        with pytest.raises(Exception, match="target_scope"):
            SubmitCommandRequest(mission_type=10)

        with pytest.raises(Exception, match="not both"):
            SubmitCommandRequest(
                mission_type=10,
                target_drone_ids=["1"],
                target_scope="all",
            )

        with pytest.raises(Exception):
            SubmitCommandRequest(
                mission_type=10,
                target_drone_ids=["1", "1"],
            )

        with pytest.raises(Exception):
            SubmitCommandRequest(
                mission_type=10,
                target_drone_ids=["1", " "],
            )

        # Invalid altitude (negative)
        with pytest.raises(Exception):
            SubmitCommandRequest(
                mission_type=10,
                target_drone_ids=["1"],
                takeoff_altitude=-5.0
            )

        precision_request = SubmitCommandRequest(
            mission_type=Mission.PRECISION_MOVE.value,
            trigger_time=0,
            target_drone_ids=["1"],
            precision_move={
                "frame": "body",
                "translation_m": {"forward": 1.0},
                "yaw": {"mode": "hold_current"},
            },
        )
        assert precision_request.precision_move is not None
        assert precision_request.precision_move.translation_m["forward"] == 1.0

        with pytest.raises(Exception):
            SubmitCommandRequest(
                mission_type=Mission.PRECISION_MOVE.value,
                trigger_time=5,
                target_drone_ids=["1"],
                precision_move={"frame": "body", "translation_m": {"forward": 1.0}},
            )

    def test_command_submission_receipt_contains_only_stable_tracking_identity(self):
        """Submission receipts must not duplicate mutable tracker state."""
        from schemas import CommandSubmissionReceipt

        response = CommandSubmissionReceipt(
            accepted_for_tracking=True,
            command_id="abc-123",
            idempotency_key="retry-123",
            replayed=False,
            mission_type=10,
            mission_name="TAKE_OFF",
            target_drones=["1", "2"],
            tracking_url="/api/v1/commands/abc-123",
            message="Command accepted for tracked preparation.",
            timestamp=int(time.time() * 1000),
        )
        assert response.accepted_for_tracking is True
        assert response.command_id == "abc-123"
        assert set(response.model_dump()) == {
            "accepted_for_tracking",
            "command_id",
            "idempotency_key",
            "replayed",
            "mission_type",
            "mission_name",
            "target_drones",
            "tracking_url",
            "message",
            "timestamp",
        }

    def test_command_status_response(self):
        """Test CommandStatusResponse schema"""
        from schemas import (
            AckSummary,
            CommandOutcome,
            CommandPhase,
            CommandProgressSummary,
            CommandStatus,
            CommandStatusResponse,
            ExecutionSummary,
        )

        now_ms = int(time.time() * 1000)
        response = CommandStatusResponse(
            command_id="abc-123",
            mission_type=10,
            mission_name="TAKE_OFF",
            target_drones=["1"],
            status=CommandStatus.COMPLETED,
            phase=CommandPhase.TERMINAL,
            outcome=CommandOutcome.COMPLETED,
            created_at=now_ms,
            timeout_at=now_ms + 90_000,
            updated_at=now_ms,
            observed_at=now_ms,
            acks=AckSummary(
                expected=1, received=1, accepted=1, rejected=0
            ),
            executions=ExecutionSummary(
                expected=1, started=1, active=0, received=1, succeeded=1, failed=0
            ),
            progress=CommandProgressSummary(
                stage="completed",
                label="Completed",
                message="Completed successfully on 1/1 accepted drone.",
                ack_pending=0,
                accepted=1,
                execution_pending=0,
                active=0,
                completed=1,
                remaining=0,
            ),
        )
        assert response.status == CommandStatus.COMPLETED
        assert response.phase == CommandPhase.TERMINAL
        assert response.timeout_at == now_ms + 90_000
        assert response.observed_at == now_ms

    def test_execution_report_request(self):
        """Test ExecutionReportRequest schema"""
        from schemas import ExecutionReportRequest

        report = ExecutionReportRequest(
            command_id="abc-123",
            hw_id="1",
            success=False,
            error_message="Script failed",
            exit_code=1,
            duration_ms=5000
        )
        assert report.success is False
        assert report.exit_code == 1


# ============================================================================
# Integration Tests (require mock server)
# ============================================================================

class TestCommandEndpointIntegration:
    """Integration tests for command endpoints"""

    @pytest.fixture
    def mock_config_data(self):
        """Mock drone configuration"""
        return [
            {'pos_id': 0, 'hw_id': '1', 'ip': '192.168.1.101'},
            {'pos_id': 1, 'hw_id': '2', 'ip': '192.168.1.102'},
        ]

    @pytest.mark.skip(reason="Requires full server setup - run manually")
    @pytest.mark.asyncio
    async def test_submit_and_track_command(self, mock_config_data):
        """Test full command submission and tracking flow"""
        # This would test:
        # 1. POST /api/v1/commands
        # 2. GET /api/v1/commands/{id}
        # 3. Wait for ACKs
        # 4. Verify status progression
        pass


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])

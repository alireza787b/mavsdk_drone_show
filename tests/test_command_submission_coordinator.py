import asyncio
from types import SimpleNamespace

import pytest

from command_submission_coordinator import (
    CommandSubmissionCapacityError,
    CommandSubmissionCoordinator,
    CommandSubmissionUnavailableError,
)


def _params(**overrides):
    values = {
        "GCS_COMMAND_SUBMISSION_CONCURRENCY": 1,
        "GCS_COMMAND_RECOVERY_SUBMISSION_CONCURRENCY": 1,
        "GCS_COMMAND_SUBMISSION_SHUTDOWN_GRACE_SEC": 0.01,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_coordinator_requires_lifespan_start():
    coordinator = CommandSubmissionCoordinator(_params())

    with pytest.raises(CommandSubmissionUnavailableError):
        await coordinator.reserve(recovery=False)


@pytest.mark.asyncio
async def test_routine_saturation_does_not_consume_recovery_reserve():
    coordinator = CommandSubmissionCoordinator(_params())
    await coordinator.start()
    routine = await coordinator.reserve(recovery=False)

    with pytest.raises(CommandSubmissionCapacityError):
        await coordinator.reserve(recovery=False)

    recovery = await coordinator.reserve(recovery=True)
    await coordinator.release(routine)
    await coordinator.release(recovery)
    await coordinator.stop()


@pytest.mark.asyncio
async def test_owned_operation_releases_capacity_after_completion():
    coordinator = CommandSubmissionCoordinator(_params())
    await coordinator.start()
    reservation = await coordinator.reserve(recovery=False)
    started = asyncio.Event()
    finish = asyncio.Event()
    failures = []

    async def operation():
        started.set()
        await finish.wait()

    async def on_failure(reason):
        failures.append(reason)

    await coordinator.launch(
        reservation,
        command_id="command-1",
        operation_factory=operation,
        on_failure=on_failure,
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    assert (await coordinator.counts())["routine_active"] == 1

    finish.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert (await coordinator.counts())["routine_active"] == 0
    assert failures == []
    await coordinator.stop()


@pytest.mark.asyncio
async def test_operation_failure_is_terminalized_by_owned_failure_handler():
    coordinator = CommandSubmissionCoordinator(_params())
    await coordinator.start()
    reservation = await coordinator.reserve(recovery=False)
    failed = asyncio.Event()
    reasons = []

    async def operation():
        raise RuntimeError("readiness transport failed")

    async def on_failure(reason):
        reasons.append(reason)
        failed.set()

    await coordinator.launch(
        reservation,
        command_id="command-2",
        operation_factory=operation,
        on_failure=on_failure,
    )
    await asyncio.wait_for(failed.wait(), timeout=1)

    assert len(reasons) == 1
    assert "readiness transport failed" in reasons[0]
    await coordinator.stop()


@pytest.mark.asyncio
async def test_shutdown_cancels_and_terminalizes_undrained_operation():
    coordinator = CommandSubmissionCoordinator(
        _params(GCS_COMMAND_SUBMISSION_SHUTDOWN_GRACE_SEC=0.0)
    )
    await coordinator.start()
    reservation = await coordinator.reserve(recovery=True)
    started = asyncio.Event()
    reasons = []

    async def operation():
        started.set()
        await asyncio.Event().wait()

    async def on_failure(reason):
        reasons.append(reason)

    await coordinator.launch(
        reservation,
        command_id="command-3",
        operation_factory=operation,
        on_failure=on_failure,
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    await coordinator.stop()

    assert len(reasons) == 1
    assert "shutdown interrupted" in reasons[0].lower()
    assert await coordinator.counts() == {
        "routine_active": 0,
        "recovery_active": 0,
        "reserved": 0,
    }

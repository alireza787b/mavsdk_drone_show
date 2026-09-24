"""Cross-thread cancellation must stay on the subprocess owner's asyncio loop."""

import asyncio
from concurrent.futures import Future
from threading import Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.drone_setup import DroneSetup, RunningMissionProcess
from src.enums import Mission, State


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exit_code, expected_success, cancel_request",
    [(0, True, False), (2, False, False), (0, True, True)],
)
async def test_cancel_from_api_loop_waits_on_scheduler_loop(
    exit_code, expected_success, cancel_request
):
    config = SimpleNamespace(
        mission=Mission.SMART_SWARM.value,
        state=State.MISSION_EXECUTING.value,
        trigger_time=0,
        current_command_id="cancel-command",
        hw_id="test-drone",
    )
    setup = DroneSetup(SimpleNamespace(trigger_sooner_seconds=4), config)
    setup._report_execution_start_to_gcs = AsyncMock()
    setup._report_execution_to_gcs = AsyncMock()
    ready = Future()
    stopped = Future()

    def run_scheduler_loop():
        async def own_process():
            setup.bind_mission_event_loop()
            loop = asyncio.get_running_loop()
            process_exited = loop.create_future()
            process = Mock(pid=None, returncode=None)

            def finish_process():
                process.returncode = exit_code
                process_exited.set_result(exit_code)

            def terminate():
                # A real asyncio subprocess resolves its exit future on this
                # same loop. Awaiting it from the API loop raises RuntimeError.
                assert asyncio.get_running_loop() is loop
                stopped.set_result(True)
                if not cancel_request:
                    finish_process()

            async def wait():
                assert asyncio.get_running_loop() is loop
                return await process_exited

            process.terminate.side_effect = terminate
            process.wait = wait
            record = RunningMissionProcess(
                process_key="smart_swarm.py:old",
                script_name="smart_swarm.py",
                process=process,
                command_id="old-command",
                mission_type=Mission.SMART_SWARM.value,
            )
            setup.running_processes[record.process_key] = record
            setup._active_mission_owner_token = record.ownership_token
            release = asyncio.Event()
            ready.set_result((loop, release, finish_process))
            await release.wait()

        try:
            asyncio.run(own_process())
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                raise

    thread = Thread(target=run_scheduler_loop, daemon=True)
    thread.start()
    try:
        owner_loop, _, finish_process = await asyncio.wait_for(
            asyncio.wrap_future(ready), timeout=2
        )
        # Match the API route: it holds this cross-thread transaction through
        # cancellation, while the scheduler loop remains free to stop its child.
        async def submit_cancel():
            await asyncio.to_thread(setup.command_state_transaction_lock.acquire)
            try:
                return await setup.cancel_active_command()
            finally:
                setup.command_state_transaction_lock.release()

        cancel_task = asyncio.create_task(submit_cancel())
        if cancel_request:
            await asyncio.wait_for(asyncio.wrap_future(stopped), timeout=2)
            cancel_task.cancel()
            await asyncio.sleep(0)
            assert setup.command_state_transaction_lock.locked()
            owner_loop.call_soon_threadsafe(finish_process)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(cancel_task, timeout=2)
        else:
            success, message = await asyncio.wait_for(cancel_task, timeout=2)
            assert success is expected_success
            assert ("handoff was not confirmed" in message) is not expected_success

        assert stopped.result(timeout=1)
        assert not setup.command_state_transaction_lock.locked()
        assert setup.running_processes == {}
        assert config.mission == Mission.NONE.value
        assert config.state == State.IDLE.value
        assert config.current_command_id is None
        assert setup.get_recent_command_record("cancel-command")["phase"] == (
            "completed" if expected_success else "failed"
        )
        assert setup._report_execution_to_gcs.await_args.kwargs["success"] is expected_success
    finally:
        if ready.done() and not ready.exception():
            owner_loop, release, _ = ready.result()
            owner_loop.call_soon_threadsafe(release.set)
        await asyncio.to_thread(thread.join, 2)
        assert not thread.is_alive()

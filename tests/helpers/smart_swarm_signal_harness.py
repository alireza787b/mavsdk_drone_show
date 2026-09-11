"""Subprocess harness for Smart Swarm's cooperative signal shutdown."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import MagicMock

# The runtime boundary does not use process discovery, retry decoration, or the
# numerical estimator. Keep this subprocess test independent of optional node
# packages just like the focused unit-test fixture.
psutil_stub = ModuleType("psutil")
tenacity_stub = ModuleType("tenacity")
tenacity_stub.retry = lambda *_args, **_kwargs: lambda function: function
tenacity_stub.stop_after_attempt = lambda *_args, **_kwargs: object()
tenacity_stub.wait_fixed = lambda *_args, **_kwargs: object()
mavsdk_stub = ModuleType("mavsdk")
mavsdk_stub.System = MagicMock()
offboard_stub = ModuleType("mavsdk.offboard")
offboard_stub.VelocityBodyYawspeed = MagicMock()
offboard_stub.VelocityNedYaw = MagicMock()
offboard_stub.OffboardError = Exception
action_stub = ModuleType("mavsdk.action")
action_stub.ActionError = Exception
sys.modules["psutil"] = psutil_stub
sys.modules["tenacity"] = tenacity_stub
sys.modules["mavsdk"] = mavsdk_stub
sys.modules["mavsdk.offboard"] = offboard_stub
sys.modules["mavsdk.action"] = action_stub

import smart_swarm  # noqa: E402  (dependency stubs must be installed first)


async def run(marker_dir: Path) -> None:
    events: list[str] = []
    control_started = asyncio.Event()

    class _Offboard:
        async def stop(self):
            events.append("offboard.stop")

    class _Action:
        async def hold(self):
            events.append("action.hold")

    class _Led:
        def set_color(self, *_args):
            return None

    async def control_task():
        try:
            control_started.set()
            await asyncio.Event().wait()
        finally:
            events.append("control.cancelled")

    async def fake_runtime(lifecycle):
        lifecycle.drone = SimpleNamespace(offboard=_Offboard(), action=_Action())
        task = asyncio.create_task(control_task())
        smart_swarm.FOLLOWER_TASKS["control_task"] = task
        await control_started.wait()
        (marker_dir / "started").touch()
        await asyncio.Event().wait()

    smart_swarm.LEDController.get_instance = staticmethod(lambda: _Led())
    smart_swarm.run_smart_swarm = fake_runtime

    logger = logging.getLogger("smart_swarm_signal_harness")
    await smart_swarm.run_smart_swarm_process(logger)
    (marker_dir / "result.json").write_text(
        json.dumps({"events": events}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    destination = Path(sys.argv[1])
    destination.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(destination))

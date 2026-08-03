"""Executable test harness for actions.py's real POSIX signal boundary."""

import asyncio
import json
import sys
import types
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock


def _install_dependency_stubs() -> None:
    sys.modules["psutil"] = MagicMock()
    mavsdk = types.ModuleType("mavsdk")
    mavsdk.System = MagicMock()
    telemetry = types.ModuleType("mavsdk.telemetry")
    telemetry.FlightMode = types.SimpleNamespace(
        HOLD=types.SimpleNamespace(name="HOLD"),
        RETURN_TO_LAUNCH=types.SimpleNamespace(name="RETURN_TO_LAUNCH"),
    )
    telemetry.LandedState = types.SimpleNamespace(
        TAKING_OFF="TAKING_OFF",
        IN_AIR="IN_AIR",
        LANDING="LANDING",
        ON_GROUND="ON_GROUND",
    )
    mavsdk.telemetry = telemetry
    action = types.ModuleType("mavsdk.action")
    action.ActionError = Exception
    offboard = types.ModuleType("mavsdk.offboard")
    for name in (
        "PositionNedYaw",
        "VelocityBodyYawspeed",
        "PositionGlobalYaw",
        "VelocityNedYaw",
        "AccelerationNed",
    ):
        setattr(offboard, name, MagicMock())
    offboard.OffboardError = Exception
    sys.modules["mavsdk"] = mavsdk
    sys.modules["mavsdk.telemetry"] = telemetry
    sys.modules["mavsdk.action"] = action
    sys.modules["mavsdk.offboard"] = offboard
    sys.modules["mavsdk.system"] = types.SimpleNamespace(System=MagicMock())


async def _run(action_name: str, marker_dir: Path) -> int:
    import actions

    async def action_at_cleanup_boundary(**_kwargs):
        actions._CURRENT_ACTION_NAME = action_name
        (marker_dir / "started").write_text(action_name, encoding="utf-8")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # This delay proves the OS signal did not terminate the process at
            # the default boundary and that shieldable cleanup was reached.
            await asyncio.sleep(0.05)
            actions._set_action_cleanup_evidence(
                {"cleanup": "test_harness", "cleanup_confirmed": True}
            )
            actions._set_final_vehicle_state(
                {
                    "fresh": True,
                    "complete": True,
                    "armed": False,
                    "landed_state": "ON_GROUND",
                    "relative_altitude_m": 0.0,
                    "recovery_status": "safe_disarmed_confirmed",
                }
            )
            (marker_dir / "cleanup").write_text(action_name, encoding="utf-8")
            raise

    actions.perform_action = action_at_cleanup_boundary
    await actions.run_action_process(
        action=action_name,
        altitude=10.0,
        branch=None,
        request_payload=None,
    )
    result = actions._build_terminal_result(action_name)
    (marker_dir / "result.json").write_text(
        json.dumps(asdict(result), sort_keys=True),
        encoding="utf-8",
    )
    return actions.RETURN_CODE


def main() -> int:
    _install_dependency_stubs()
    action_name = sys.argv[1]
    marker_dir = Path(sys.argv[2])
    marker_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_run(action_name, marker_dir))


if __name__ == "__main__":
    raise SystemExit(main())

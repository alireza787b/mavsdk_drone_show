# QuickScout Runtime Validation

Date: 2026-04-08
Commit: `e909916b`

## Summary

QuickScout now launches and validates end to end on fresh Hetzner SITL instead of stalling in `executing/searching` with the target drone still disarmed.

Validated live on a fresh `3`-drone restage:
- plan `last_known_point` QuickScout mission from live telemetry
- tracked launch submission
- target drone airborne with `+6.0m` gain
- non-target drones remain idle
- pause to `HOLD`
- direct resume returns `replan_required`
- abort with return-home behavior
- fleet returns to idle/disarmed baseline
- active commands clear

## Root Causes Fixed

The live debugging chain uncovered several separate runtime defects:

1. `DroneSetup.execute_mission_script()` accepted list args containing non-strings, which broke QuickScout launch logging and prevented the mission script from starting.
2. QuickScout used a stale MAVSDK assumption:
   - no explicit `mavsdk_server` bootstrap
   - wrong default gRPC port (`50051`) instead of `Params.DEFAULT_GRPC_PORT`
3. QuickScout mission-item construction lagged behind the vendored MAVSDK signature:
   - missing `vehicle_action`
   - optional `yaw_deg=None` passed through without normalization
4. QuickScout startup used a weaker MAVSDK health/home wait than the rest of the system actually trusted in live SITL. The local drone API already showed the vehicle as ready while the mission executor remained blocked.

## Final Runtime Shape

`quickscout_mission.py` now:
- starts a dedicated `mavsdk_server` on the canonical gRPC port
- drains server stdout/stderr
- confirms MAVSDK connection with bounded timeout
- gates launch readiness on local drone API state plus local home-position snapshot
- normalizes optional mission-item numerics
- marks the first mission item as `VehicleAction.TAKEOFF`
- arms with bounded retries
- still reports progress and teardown through the existing tracked command path

## Validation

Local:
- `python3 -m py_compile quickscout_mission.py tests/test_quickscout_mission.py`
- `python3 -m pytest tests/test_quickscout_mission.py tests/test_validate_quickscout_runtime.py tests/test_sar_schemas.py -q`
- result: `37 passed`

Earlier local regression slices also stayed green while fixing the launch path:
- `66 passed` on the focused QuickScout/SAR subset after MAVSDK payload alignment
- `144` focused assertions reached `100%` in the broader QuickScout/drone setup batch during the first runtime-bootstrap slice

Hetzner:
- fresh sync to `e909916b`
- fresh `drone-1/2/3` recreate via `multiple_sitl/create_dockers.sh 3`
- fresh GCS restart
- `tools/validate_quickscout_runtime.py`
- result: `QuickScout runtime validation passed.`

Post-validation live state:
- `GET /api/v1/system/health` -> `ok`
- `GET /api/v1/commands/active` -> `0`
- drones `1/2/3` idle, disarmed, ready

## Next QuickScout Slices

Runtime launch is now proven. The next meaningful QuickScout work is no longer executor bring-up:
- multi-drone QuickScout launch validation
- richer search monitoring and progress semantics
- image / POI / evidence workflow
- template expansion beyond point and corridor
- broader SITL mission-package drills integrated into the reusable validation platform

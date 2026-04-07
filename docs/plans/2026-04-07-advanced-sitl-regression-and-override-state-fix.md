# 2026-04-07 Advanced SITL Regression And Override-State Fix

## Scope

Close the advanced mixed-mode SITL gap exposed by the new checked-in operator
scenarios, then rerun the full reusable regression flow on Hetzner.

## Root Cause

The first `integrated_mixed_mode` run exposed two real issues:

1. `SWARM_TRAJECTORY` was not allowed as an in-flight override while another
   mission was active on the drone.
2. After allowing the override, the leader still failed the validator because
   interrupting the prior mission called `terminate_all_running_processes()`,
   which reset `drone_config.mission` back to `Mission.NONE` before the
   replacement `SWARM_TRAJECTORY` script launched.

That second bug made the leader telemetry report `state=MISSION_EXECUTING` with
`mission=NONE`, so the mixed-mode validator could not prove the intended
operator state even though the command tracker accepted and completed the
trajectory command.

## Changes

- allowed `Mission.SWARM_TRAJECTORY` in the drone-side override set in
  `src/drone_api_server.py`
- switched `_execute_swarm_trajectory()` onto the same interrupting immediate
  mission path as other override-capable actions in `src/drone_setup.py`
- taught `terminate_all_running_processes()` to preserve staged replacement
  mission metadata when called from an override path
- added/updated targeted unit coverage in:
  - `tests/test_drone_setup.py`
  - `tests/test_command_system.py`
- promoted the checked-in advanced plan documentation:
  - `tools/sitl_plans/README.md`
  - `docs/guides/sitl-validation-platform.md`
  - `docs/guides/sitl-comprehensive.md`
  - `docs/TODO_deferred.md`

## Validation

Local:

- `python3 -m pytest tests/test_drone_setup.py tests/test_command_system.py`
  - `133 passed, 1 skipped`

Hetzner:

- clean runtime clone fast-forwarded to `f9399ab6`
- `integrated_mixed_mode`
  - `passed`
  - artifact dir: `/tmp/mds_integrated_phase5_run_fix3`
- `advanced_operator_regression`
  - `passed`
  - artifact dir: `/tmp/mds_advanced_operator_regression_phase5`

## Observed Runtime Result

The advanced mixed-mode telemetry contract is now correct:

- leader enters `SWARM_TRAJECTORY` while followers remain in `SMART_SWARM`
- `HOLD` supersedes the leader trajectory cleanly
- `PRECISION_MOVE` can then displace the leader while followers keep reforming
- the reusable advanced regression finishes with a clean fleet reset

## Remaining Deferred Work

- QuickScout SITL validator/template
- harder simultaneous mixed-mode drills
- precision-move-to-precision-move override stress drill
- bounded fault-injection scenarios once they are deterministic enough

# 2026-04-04 SITL Plan Library

## Summary

This checkpoint adds a checked-in SITL scenario library on top of the reusable
validation platform so maintainers, operators, CI jobs, and AI agents can run
stable named scenarios without rebuilding plan JSON from memory.

## What Changed

- added `tools/sitl_plans/`
- added a bundled-plan README with usage and scenario boundaries
- added suite CLI support for:
  - `--list-bundled-plans`
  - `--plan-name <name>`
- updated the suite summary payload to include `plan_name`
- documented the stable library boundary versus deferred advanced combined-mode
  and fault-injection drills

## Current Bundled Plans

- `config_roundtrip`
- `config_then_drone_show`
- `drone_show_matrix`
- `actions_core`
- `smart_swarm_runtime`
- `swarm_trajectory_short_profile`
- `mission_regression`
- `operator_regression`

## Current Validated Runtime Coverage

The current live-validated operator regression still covers:

- Mission Config / swarm / origin round-trip safety
- Drone Show:
  - global auto
  - global manual
  - local delayed
  - custom CSV
  - override drill
- Actions:
  - TAKEOFF
  - HOLD
  - targeted RTL override
  - LAND remaining drones
- Smart Swarm:
  - takeoff
  - formation settle
  - reassignment
  - leader RTL
  - follower HOLD
  - LAND
  - assignment restore
- Swarm Trajectory:
  - short-profile preparation
  - processing
  - launch
  - climb gate
  - follower geometry
  - cleanup restore

## Deferred Advanced Scenarios

Not promoted into the stable library yet:

- simultaneous mixed-mode missions on one live fleet
- harder supersession and delayed-trigger stress cases
- bounded fault-injection drills

Those remain tracked in `docs/TODO_deferred.md` until they are deterministic
enough for routine acceptance use.

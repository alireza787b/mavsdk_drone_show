# Bundled SITL Plan Library

This directory contains checked-in JSON plans for the reusable SITL validation
suite.

Use them when you want stable named scenarios instead of ad hoc temporary JSON
files.

## How To Run

List bundled plans:

```bash
python3 tools/run_sitl_validation_suite.py --list-bundled-plans
```

Run a bundled plan by name:

```bash
python3 tools/run_sitl_validation_suite.py \
  --plan-name operator_regression \
  --base-url http://127.0.0.1:5000 \
  --validator-root ~/mavsdk_drone_show \
  --repo-root ~/mavsdk_drone_show \
  --drone-ids 1 2 3
```

The current plan library is split into three classes:

- stable acceptance plans
  - deterministic enough for routine operator, maintainer, and AI-agent use
- validated advanced plans
  - higher-cost mixed-mode operator drills that are now deterministic enough to
    keep checked in and rerun on demand
- deferred advanced scenarios
  - still intentionally outside the checked-in acceptance set until they stay
    repeatable across more releases

## Current Stable Plans

- `config_roundtrip`
  - Mission Config / swarm / origin round-trip safety gate
- `config_then_drone_show`
  - configuration gate followed by Drone Show acceptance
- `drone_show_matrix`
  - full Drone Show matrix validator
- `actions_core`
  - TAKEOFF, HOLD, targeted RTL override, LAND remaining drones
- `smart_swarm_runtime`
  - takeoff, formation settle, reassignment, leader RTL, follower hold, land
- `swarm_trajectory_short_profile`
  - short-profile process, launch, formation, cleanup
- `quickscout_runtime`
  - stable single-drone QuickScout last-known-point launch, finding/handoff exercise, hold, resume rejection, abort, and cleanup
- `mission_regression`
  - Drone Show, Smart Swarm, Swarm Trajectory, QuickScout
- `operator_regression`
  - configuration, Drone Show, actions, Smart Swarm, Swarm Trajectory, QuickScout

## Current Validated Advanced Plans

- `integrated_mixed_mode`
  - Smart Swarm cluster, in-flight reassignment, leader Swarm Trajectory
    override, HOLD supersession, leader Precision Move, and clean land/restore
- `quickscout_multi_runtime`
  - two-drone QuickScout launch, finding/handoff exercise, hold, resume rejection, abort, and non-target idle scope check
- `advanced_operator_regression`
  - configuration, Drone Show, standalone actions, and the integrated
    mixed-mode override drill

## Deferred Advanced Scenarios

The following are intentionally tracked outside the stable plan set for now:

- simultaneous mixed-mode missions on one live fleet
- harder command supersession / late-trigger stress drills
- precision-move-to-precision-move override drills from each drone's current local state
- deliberate fault-injection plans

Those are tracked in `docs/TODO_deferred.md` and will be promoted into this
library only after they stay deterministic enough for repeated acceptance use.

## Operational Notes

- These plans assume the GCS command tracker is clean at plan start. Recreating
  the drone fleet does not clear out-of-band manual debug commands that were
  submitted directly to the live GCS between plan runs.
- If you manually debug launch flows outside the suite, restart the GCS service
  before treating the next plan run as a fair acceptance result.
- When the runtime repo head is newer than the currently published SITL image,
  recreate the fleet with `MDS_SITL_GIT_SYNC=true` so the containers do not
  silently remain on the older baked commit.

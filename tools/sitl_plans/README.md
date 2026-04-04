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

The current plan library is split into two classes:

- stable acceptance plans
  - deterministic enough for routine operator, maintainer, and AI-agent use
- advanced scenarios
  - not yet promoted here unless they stay deterministic across repeated runs

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
- `mission_regression`
  - Drone Show, Smart Swarm, Swarm Trajectory
- `operator_regression`
  - configuration, Drone Show, actions, Smart Swarm, Swarm Trajectory

## Deferred Advanced Scenarios

The following are intentionally tracked outside the stable plan set for now:

- simultaneous mixed-mode missions on one live fleet
- harder command supersession / late-trigger stress drills
- deliberate fault-injection plans

Those are tracked in `docs/TODO_deferred.md` and will be promoted into this
library only after they stay deterministic enough for repeated acceptance use.

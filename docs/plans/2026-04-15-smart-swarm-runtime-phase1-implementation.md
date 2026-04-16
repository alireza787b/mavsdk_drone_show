# 2026-04-15 Smart Swarm Runtime Phase 1 Implementation

## Scope

This checkpoint implements the first Smart Swarm runtime redesign slice from
the audit brief:

- repair leader-state freshness and timestamp semantics
- add a dedicated Smart Swarm leader-state transport surface
- keep HTTP fallback instead of forcing a websocket-only design
- improve follower control behavior for moving leaders and live topology edits
- close exposed command-runtime compatibility gaps found during the regression gate

## What Changed

### Realtime leader-state contract

- added dedicated drone HTTP endpoint: `GET /api/v1/swarm/state`
- added dedicated drone websocket endpoint: `WS /ws/swarm-state`
- added millisecond telemetry timestamps and stream sequence tracking to the
  drone runtime
- leader-state freshness is no longer keyed only off coarse second-resolution
  `update_time`

### Follower runtime

- Smart Swarm now prefers the dedicated websocket stream for leader-state
  updates
- bounded HTTP fallback remains in place
- follower prediction now uses the repaired measurement timing path
- follower control now includes:
  - leader-velocity feedforward
  - body-frame yaw-rate offset compensation
  - controller/filter reset on live topology or offset changes
  - predictive-grace blending before hard failover

### Runtime assignment and failover support

- live runtime assignment file is now preferred only when it matches the local
  `hw_id`, so stale or unrelated runtime assignments do not leak into the wrong
  node
- failover timing is tightened against stale leader state instead of waiting on
  overly loose windows

### Shared runtime contract changes

These were required to make the Smart Swarm transport/controller slice work on
the current official branch tip without regressing newer runtime behavior:

- drone runtime now publishes:
  - `telemetry_timestamp_ms`
  - `telemetry_sequence`
  - `yaw_rate_deg_s`
- local MAVLink ingestion marks telemetry updates at millisecond resolution
- `DroneCommunicator` exposes a dedicated Smart Swarm payload builder through
  `get_swarm_state()`
- canonical Smart Swarm routes are now:
  - `GET /api/v1/swarm/state`
  - `WS /ws/swarm-state`
- non-dict or unrelated runtime swarm assignments are ignored safely instead of
  contaminating follower state

## Files Changed

Runtime/control:

- `smart_swarm.py`
- `smart_swarm_src/pd_controller.py`
- `smart_swarm_src/low_pass_filter.py`
- `smart_swarm_src/utils.py`
- `src/local_mavlink_controller.py`
- `src/drone_communicator.py`
- `src/drone_api_server.py`
- `src/drone_api_routes.py`
- `src/params.py`

Runtime state surface:

- `src/drone_config/drone_state.py`
- `src/drone_config/__init__.py`

Tests:

- `tests/test_smart_swarm_runtime_math.py`
- `tests/test_drone_api_http.py`
- `tests/test_drone_api_websocket.py`
- `tests/test_drone_communicator.py`
- `tests/test_local_mavlink_controller.py`

## Validation

### Broad regression ring

Passed on the current official clean worktree:

```bash
python3 -m pytest \
  tests/test_smart_swarm_runtime_math.py \
  tests/test_drone_api_http.py \
  tests/test_drone_api_websocket.py \
  tests/test_drone_communicator.py \
  tests/test_local_mavlink_controller.py \
  tests/test_drone_setup.py \
  tests/test_drone_config_components.py \
  tests/test_gcs_api_http.py \
  tests/test_gcs_api_websocket.py \
  tests/test_command_processing.py
```

Result:

- `346 passed`

### Smart Swarm-focused unit ring

Passed:

```bash
python3 -m pytest \
  tests/test_smart_swarm_kalman.py \
  tests/test_smart_swarm_failover.py \
  tests/test_smart_swarm_pd_controller.py \
  tests/test_smart_swarm_runtime_math.py \
  tests/test_validate_smart_swarm_runtime.py \
  tests/test_swarm_runtime_state.py \
  tests/test_drone_communicator_runtime_swarm.py
```

Result:

- `23 passed`
- `1 skipped`

## Remaining Planned Work

This checkpoint is not the end of the Smart Swarm redesign.

Remaining acceptance work before client convergence:

1. run live SITL Smart Swarm validation on the official branch
2. inspect telemetry/ULog evidence for lag, settle time, and failover behavior
3. induce degraded-network cases where practical and confirm fallback behavior
4. only after official runtime acceptance, sync the approved result into the
   private client repo and rebuild the contract demo package

## Explicit Deferred Item

- browser/admin exec terminal remains deferred and unrelated to this Smart
  Swarm slice

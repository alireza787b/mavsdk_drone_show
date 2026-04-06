# Precision Move Final Recap

Date: 2026-04-05
Base checkpoint reviewed: `3ba4a1f1`
Scope: final research recap and implementation recommendation before coding

## Executive Decision

I recommend proceeding, but with one prerequisite cleanup slice first:

- keep the current drone-side subprocess execution model for now
- do not rewrite `DroneSetup` end to end first
- refactor `actions.py` into a thin CLI adapter over a modular typed action-runner layer
- then implement `PRECISION_MOVE` on top of that new runner layer

This is the best balance of:

- future cleanliness
- MCP / AI friendliness
- CLI friendliness
- minimal risk to the current command tracker and supersede behavior

## Direct Answers To The Design Questions

## 1. Should we first clean up how `actions.py` works?

Yes, but in a scoped way.

I do **not** recommend a big-bang rewrite of all action execution paths before the feature. That would create unnecessary risk and delay.

I **do** recommend a small foundational refactor first:

- `actions.py` stays as the process entrypoint
- the real logic moves into reusable typed runner modules
- `DroneSetup` can keep launching `actions.py` as a subprocess
- the same typed runner code can later be called from:
  - UI-triggered commands
  - drone setup
  - future MCP tools
  - future in-process APIs
  - manual CLI execution

This keeps a single source of truth while preserving the current cancellation and tracker flow.

### Recommended runtime shape

- `actions.py`
  - CLI parsing only
  - legacy flag compatibility
  - optional structured request loading
  - dispatch into runner registry
- `src/action_runners/base.py`
  - runner interfaces
  - shared result model
  - shared context model
- `src/action_runners/common.py`
  - MAVSDK session startup/teardown helpers
  - offboard start/stop helpers
  - local-position/yaw helpers
  - timeout/tolerance helpers
- `src/action_runners/flight_basic.py`
  - takeoff
  - hold
  - land
  - rtl
- `src/action_runners/precision_move.py`
  - the new feature

### Why this is the right prerequisite

Because `actions.py` today is still:

- one big `if/elif` executor
- tightly coupled to CLI parsing
- awkward to reuse from future MCP / automation layers

The new feature is complex enough that adding it directly into the current monolith would make the system worse.

## 2. Is there a MAVSDK local-relative `goto` that avoids Offboard?

No equivalent high-level MAVSDK action surface exists in this repo for the required operator contract.

What exists:

- `Action.goto_location(...)`
  - global WGS84 latitude/longitude
  - altitude AMSL
  - yaw in NED heading degrees

What does **not** exist:

- a high-level local-relative “go 2 m forward / 1 m north from here” action API
- a high-level body-frame reposition action API

So for this feature, the clean standard path is Offboard with local setpoints.

### Why Offboard is still the correct choice

Because PX4 and MAVSDK already support the exact primitives we need:

- local NED position setpoint
- local NED velocity setpoint
- position + velocity feed-forward setpoint
- body-frame velocity setpoint

And this repo already uses offboard successfully in real mission executors.

### Complexity concern

Yes, Offboard is more complex than a simple action command.

But in this project the complexity is already paid for:

- shared pre-arm gate exists
- initial setpoint before `offboard.start()` already exists
- retry logic exists
- stop-to-hold behavior already exists

So the practical complexity increase is moderate, not a greenfield risk.

## 3. Should this support multiple selected drones?

### System-level answer

Yes, the **backend and API should support multiple targets**.

Each drone can receive the same typed `precision_move` payload and interpret it **relative to its own current local state**.

That means batch semantics are well-defined:

- the same command is applied
- each drone computes its own local target from its own local position and yaw

This is technically coherent and useful.

### UI-level answer

The UI must make this explicit.

The right wording is:

- `Applied independently to each selected drone from its own current local position and heading.`

This is **not** the same as:

- move the whole formation rigidly as one planned object

That second behavior is a different feature and should not be implied.

### Final recommendation

I recommend:

- API / backend: support one or many targets from day one
- UI: support the current selected scope, including multiple drones
- when more than one drone is targeted:
  - show a clear batch-mode banner
  - list or summarize the affected drones
  - require explicit confirmation

This is better than artificially blocking multi-target use at the system level.

## 4. Will the controller really converge and hold, or oscillate / drift?

There is no honest way to promise mathematically exact zero-error hold in all real-world conditions.

The correct guarantee is:

- converge to within configured tolerance
- remain within tolerance for a configured settle window
- then hand over to a stable hold behavior

That is the right industrial contract.

### Recommended control strategy

Use a two-stage offboard target loop:

1. **Approach phase**
   - send `set_position_velocity_ned(target_position, feedforward_velocity)`
   - feed-forward velocity is bounded by the requested speed
   - velocity magnitude tapers down near the target

2. **Settle phase**
   - once close enough, send:
     - `set_position_ned(target_position)` or
     - `set_position_velocity_ned(target_position, zero_velocity)`
   - maintain this for a short settle window

3. **Hold handoff**
   - after the settle window, stop offboard intentionally
   - PX4 enters Hold mode

This avoids “keep blasting velocity forever” behavior.

### Why this is better than pure velocity control

Pure velocity control alone is not a good match for “move exactly there and hold”.

Position + velocity feed-forward gives:

- exact target semantics
- smooth bounded approach
- cleaner slowdown near the target

### What about 0.1 m commands?

Very small moves are possible, but not equally meaningful in all estimator conditions.

Reality:

- very small commands may be close to estimator noise, controller deadband, or position jitter
- success must still be judged by tolerance, not perfect zero error

Recommendation:

- API accepts them
- UI defaults to more realistic steps like `0.25 m`, `0.5 m`, `1 m`
- advanced numeric entry can still allow smaller moves
- docs must state that sub-decimeter precision depends on estimator quality

### What about 100 m commands?

They are possible in principle, but this is not what this feature should optimize for.

Recommendation:

- configurable max translation per action
- moderate default cap
- larger moves should generally be handled by mission/planning tools, not ad hoc manual reposition

Suggested default policy:

- per-axis cap and/or total translation cap
- operator can raise via config if needed

## 5. Will it still work if GCS networking drops?

Yes, if the command has already been accepted and dispatched.

That is exactly why the move must execute on the drone companion, not as a live GCS control stream.

The drone-side runner continues:

- sending local setpoints to PX4
- monitoring convergence locally
- reporting progress/result best-effort when network is available

If the companion process itself dies, PX4 offboard-loss handling applies, which is safer than a GCS-held joystick tunnel.

## 6. What is the final recommended command contract?

### New mission/action code

- `Mission.PRECISION_MOVE = 112`

### New nested typed payload

Top-level canonical field:

- `precision_move`

Recommended shape:

```json
{
  "mission_type": 112,
  "trigger_time": 0,
  "target_drone_ids": ["1", "2"],
  "operator_label": "Precision Move",
  "precision_move": {
    "frame": "body",
    "translation_m": {
      "forward": 2.0,
      "right": 4.0,
      "up": 1.0
    },
    "yaw": {
      "mode": "relative_delta",
      "degrees": 30.0
    },
    "speed_m_s": 1.0,
    "position_tolerance_m": 0.15,
    "yaw_tolerance_deg": 5.0,
    "settle_time_sec": 1.0,
    "timeout_sec": 30.0,
    "hold_mode": "px4_hold"
  }
}
```

Frames:

- `body`
- `ned`

For `body` translation:

- `forward`
- `right`
- `up`

For `ned` translation:

- `north`
- `east`
- `up`

Yaw modes:

- `hold_current`
- `absolute_heading`
- `relative_delta`

## 7. What is the final recommended CLI / MCP / API interaction model?

This is the main cleanup I recommend before the feature lands.

### Shared truth

The typed request model should be the real source of truth.

### CLI recommendation

Keep legacy action flags, but add a structured path:

- `python3 actions.py --runner precision_move --request-file /path/to/request.json`

or

- `python3 actions.py --runner precision_move --request-json '{...}'`

`--request-file` is safer and cleaner for automation.

### DroneSetup recommendation

For now:

- keep launching `actions.py` as subprocess
- pass structured request via file or serialized JSON argument

### MCP recommendation

Later, MCP should call the same typed command contract, not a special side channel.

That means:

- MCP submits the normal command
- tracker/progress routes expose status
- no separate “AI-only” execution path

## 8. Progress reporting recommendation

Current system already has:

- execution-start
- execution-result

I recommend adding:

- `POST /api/v1/command-reports/execution-progress`

That should be used for:

- `preparing`
- `starting_offboard`
- `moving`
- `settling`
- `holding`

Optional fields:

- `remaining_distance_m`
- `yaw_error_deg`
- `target_reached`

This is worth doing now because it improves:

- operator UI
- debugging
- future MCP observability

## 9. Final UI recommendation

Add a dedicated `Precision Move` action button in the Flight section.

On click, open a dialog with:

- current target scope
- drone readiness strip
- frame toggle: `Body` / `NED`
- quick movement pad
- advanced numeric fields
- movement summary
- progress/result section

### If multiple drones are selected

Show:

- selected targets
- batch warning
- explicit statement that the move is relative per drone, not formation-global

### Recommended default interaction

- quick step buttons for speed
- advanced mode for exact values
- no scheduling in v1

## 10. Final implementation order

## Slice 1. Action runtime seam

- add runner registry
- add typed runner context and result
- keep `actions.py` as adapter
- migrate basic flight actions onto the new shared helpers as needed

## Slice 2. Contract + enums

- add `PRECISION_MOVE = 112`
- add typed payload models
- update frontend constants
- update docs

## Slice 3. Drone executor

- implement `precision_move` runner
- local state validation
- offboard startup
- target loop
- settle and hold handoff

## Slice 4. Tracker progress

- add progress report route and schemas
- wire into command tracker

## Slice 5. UI dialog

- add new action card
- add precision move dialog
- batch-scope handling
- confirmation and progress UX

## Slice 6. Tests + SITL

- unit tests
- API tests
- frontend tests
- Hetzner SITL validation

## 11. Final recommendation on the design itself

I recommend we move forward with this exact high-level approach:

- prerequisite modular action-runner seam
- no big DroneSetup rewrite
- no `goto_location()` primary path
- use offboard local NED position + velocity feed-forward
- support one or many drones at the system level
- make batch semantics explicit in UI
- define success by tolerance and settle, not mythical zero error
- hand off to PX4 Hold after convergence

## 12. Evidence Used

Repo-grounded evidence:

- `actions.py` is still the monolithic action executor
- `DroneSetup` still launches action scripts as subprocesses
- current command contract is typed at the API edge
- existing show and trajectory executors already use offboard startup / stop discipline
- local MAVLink telemetry already tracks yaw and `LOCAL_POSITION_NED`

Official control references:

- PX4 Offboard mode:
  - `https://docs.px4.io/main/en/flight_modes/offboard.html`
  - offboard needs continuous proof-of-life and exits if the stream stops
  - PX4 supports local NED position, velocity, and position+velocity feed-forward on `SET_POSITION_TARGET_LOCAL_NED`
- MAVSDK Action API:
  - `https://mavsdk.mavlink.io/v2.0/en/cpp/api_reference/classmavsdk_1_1_action.html`
  - `goto_location()` is global WGS84 + AMSL
- MAVSDK Offboard API:
  - `https://mavsdk.mavlink.io/v2.0/en/cpp/api_reference/classmavsdk_1_1_offboard.html`
  - `set_position_ned()`
  - `set_velocity_ned()`
  - `set_position_velocity_ned()`
  - offboard requires a setpoint before `start()`
  - `stop()` hands back to Hold

## 13. What I Need From You

If you approve, I will implement according to this order:

1. action-runner seam
2. typed precision move contract
3. drone executor
4. progress reporting
5. UI dialog
6. tests + Hetzner SITL validation

That is the cleanest path with the least future regret.

# Precision Move Action Design Brief

Date: 2026-04-05
Checkpoint: `3ba4a1f1` (`main`, `main-candidate`, tag `v5.0.33-sitl-release-refresh`)
Authoring scope: research, architecture, API/UI design, phased implementation plan only

## 1. Current Context

This brief is based on the clean recovery repo at `/tmp/mavsdk_drone_show_resume`.

Relevant current state:

- API modernization and SITL-platform work are closed at the current stable checkpoint.
- Command submission is now typed at the API edge via `SubmitCommandRequest` and `DroneCommandRequest`.
- Drone command execution is still script-driven after acceptance.
- Immediate actions like `TAKE_OFF`, `LAND`, `HOLD`, and `RETURN_RTL` are routed through `DroneSetup` into `actions.py`.
- Existing offboard-heavy missions already use MAVSDK offboard startup gates, retries, and local/global setpoint logic.

Current files that matter most for this feature:

- `src/command_contract.py`
- `src/enums.py`
- `src/drone_setup.py`
- `src/drone_api_server.py`
- `src/local_mavlink_controller.py`
- `src/mission_startup.py`
- `actions.py`
- `app/dashboard/drone-dashboard/src/components/DroneActions.js`
- `app/dashboard/drone-dashboard/src/components/CommandSender.js`

## 2. Requested Feature

Add a precise manual movement action that lets an operator command a drone relative to its current position and hold at the new point.

Examples:

- Local/NED style:
  - move `1 m north`, `3 m east`, `2 m up`
  - yaw to `30 deg`
  - move at `1 m/s`
  - then hold
- Body-frame style:
  - move `2 m forward`, `4 m right`, `1 m up`
  - yaw `30 deg` right
  - move at `1 m/s`
  - then hold

The user intent is broader than a single action button:

- safe and precise in real operations
- robust to temporary GCS network loss after command dispatch
- usable for SITL operator testing
- future MCP / AI-agent friendly
- clean typed API and clean UI, not an ad hoc side channel

## 3. What The Current System Already Gives Us

### 3.1 Typed command edge

`src/command_contract.py` already enforces a typed command contract. This is the right place to add a new nested payload for precision movement. The new feature should not use loose extra JSON fields.

### 3.2 Drone-local execution after dispatch

The GCS sends a command once, then the drone executes it locally. This is good for resilience:

- if the GCS link drops after acceptance, the drone can still complete the action
- the companion computer can keep feeding PX4 locally
- the command tracker can be updated best-effort using the existing start/result reporting path

### 3.3 Existing offboard discipline already proven in missions

The repo already uses the correct MAVSDK/PX4 startup pattern for offboard missions:

- pre-arm health gate
- explicit initial setpoint before starting offboard
- bounded retries on `offboard.start()`
- controlled stop of offboard at mission end

That means this feature does not need a speculative control method. It should reuse the same discipline in a smaller reusable executor.

### 3.4 Local position and yaw are already available

The drone API already exposes:

- `GET /api/v1/telemetry/local-position`

The local MAVLink listener already tracks:

- `LOCAL_POSITION_NED`
- yaw from `ATTITUDE`

That is enough to build a reliable relative move feature around local NED coordinates.

## 4. Control-Method Decision

## 4.1 Options considered

### Option A: `Action.goto_location(...)`

Pros:

- simple high-level action API
- built-in vehicle guidance

Cons:

- global WGS84 + AMSL only
- not relative-to-current-position
- not body-frame friendly
- not a good fit for no-GPS / local-estimate workflows
- awkward for operator “move 1 m forward/right/up from here” semantics

Conclusion:

- not recommended as the primary method

### Option B: Offboard body or NED velocity only

Pros:

- good for jog-style control
- body frame is intuitive
- can work without GPS if local estimate exists

Cons:

- velocity-only control is poor for exact terminal position semantics
- harder to guarantee “move exactly this far and hold there”
- more operator ambiguity around timing and stop conditions

Conclusion:

- useful as an internal feed-forward tool
- not recommended as the primary operator contract

### Option C: Offboard local position only

Pros:

- natural fit for exact relative movement
- good for hold-at-target behavior
- local-frame friendly

Cons:

- speed control is less explicit if we only send target position

Conclusion:

- better than A or B
- acceptable, but not the best final choice

### Option D: Offboard local position plus velocity feed-forward

Pros:

- exact target semantics
- explicit bounded translational speed
- local NED frame
- body-frame input can be transformed internally
- compatible with existing MAVSDK surface in this repo
- good basis for progress reporting

Cons:

- slightly more implementation work than pure position or pure velocity

Conclusion:

- recommended

## 4.2 Final recommendation

Use a drone-local offboard executor built around:

- `set_position_velocity_ned(...)` as the primary control primitive
- local NED target computation from current local position
- body-frame inputs converted into local NED targets using current yaw
- bounded tolerances and settle time
- explicit handoff to hold behavior at the end

This is the cleanest fit for:

- precise relative movement
- body and NED operator modes
- local-position operation
- future MCP / AI-agent control

## 5. Why `goto_location()` Is Not The Right Default

The vendored MAVSDK Python binding in this repo defines `goto_location()` as:

- latitude/longitude in WGS84
- altitude in meters AMSL
- yaw in NED heading degrees

That is the wrong operator abstraction for “move 1 m north/east/up from where I am now”.

Official references:

- PX4 Offboard Mode: `https://docs.px4.io/main/en/flight_modes/offboard.html`
- MAVSDK Offboard API: `https://mavsdk.mavlink.io/v2.0/en/cpp/api_reference/classmavsdk_1_1_offboard.html`
- MAVSDK Action API: `https://mavsdk.mavlink.io/v2.0/en/cpp/api_reference/classmavsdk_1_1_action.html`

Important operational note from PX4 Offboard:

- offboard requires a continuous proof-of-life stream of setpoints or equivalent offboard control messages
- if the offboard stream stops, PX4 leaves offboard according to its configured failsafe behavior

That is another reason the command must execute on the drone companion, not through a live GCS joystick loop.

## 6. Recommended v1 Scope

I recommend a disciplined first release:

- single-drone only
- immediate execution only
- airborne only
- local-position-estimate required
- no mission auto-resume after completion
- action ends in hold
- body and NED frames both supported

I do not recommend these in v1:

- scheduled precision move
- multi-drone precision move from the normal action UI
- queued choreography-style manual-move sequences
- resume previous mission after the move

Those can be added later after the primitive is proven.

## 7. Safety / Operational Rules

The action should only start when all of these are true:

- target scope resolves to exactly one drone
- drone is online
- drone is armed
- drone is airborne
- no hard preflight blocker is active
- local position data is available and fresh
- yaw is available and fresh

Recommended behavior on failure:

- if preconditions fail before offboard starts, reject the command cleanly
- if offboard starts but target is never reached, fail with a timeout and hand back to hold
- if command is superseded by another action, report superseded and stop the move loop
- if offboard setpoint streaming breaks, rely on PX4 offboard-loss behavior and report failure

Important real-world truth:

- “works without GPS” must mean “works with a valid local position estimate”, not “works with no position estimate at all”
- that local estimate may come from GPS-derived EKF, flow, VIO, mocap, or other estimator inputs

## 8. Proposed API Contract

## 8.1 New mission / action code

Recommended enum addition:

- `Mission.PRECISION_MOVE = 112`

Reason:

- sequentially follows the action-family extension pattern already used by `INIT_SYSID = 110` and `APPLY_COMMON_PARAMS = 111`

## 8.2 Canonical command payload

Add a typed nested payload to `DroneCommandRequest` / `SubmitCommandRequest`.

Recommended top-level shape:

```json
{
  "mission_type": 112,
  "trigger_time": 0,
  "target_drone_ids": ["1"],
  "operator_label": "Precision Move",
  "precision_move": {
    "frame": "body",
    "translation_m": {
      "forward": 2.0,
      "right": 4.0,
      "up": 1.0
    },
    "yaw": {
      "mode": "relative",
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

Recommended typed model split:

- `PrecisionMoveRequest`
- `PrecisionMoveTranslationBody`
- `PrecisionMoveTranslationNed`
- `PrecisionMoveYawRequest`

Recommended `frame` values:

- `body`
- `ned`

Recommended yaw modes:

- `hold_current`
- `absolute_heading`
- `relative_delta`

Recommended hold modes:

- `px4_hold`

I do not recommend adding multiple hold modes in v1.

## 8.3 Operator-friendly component semantics

For `frame=body`:

- `forward`
- `right`
- `up`

For `frame=ned`:

- `north`
- `east`
- `up`

Do not expose `down` as the primary operator input in the UI.

Internally:

- NED target uses `down = -up`

## 8.4 Coordinate conversion

Given current yaw heading degrees where:

- `0 deg = North`
- positive yaw rotates clockwise

Body-frame translation converts to NED as:

- `north = forward * cos(yaw) - right * sin(yaw)`
- `east = forward * sin(yaw) + right * cos(yaw)`
- `down = -up`

Target local position becomes:

- `target_n = current_x + north`
- `target_e = current_y + east`
- `target_d = current_z + down`

## 9. Drone-Side Architecture Recommendation

## 9.1 Do not keep growing `actions.py` as a monolith

The current `actions.py` path is still acceptable as the CLI entrypoint, but it should stop being the only place where action logic lives.

Recommended change:

- keep `actions.py` as the process entrypoint and compatibility adapter
- move real action logic into reusable modules

Recommended structure:

- `src/action_runners/__init__.py`
- `src/action_runners/base.py`
- `src/action_runners/common.py`
- `src/action_runners/precision_move.py`

Then `actions.py` becomes:

- argument parsing
- MAVSDK session setup
- action registry dispatch
- standardized exit/log/report wiring

This is a worthwhile refactor now because the new feature is materially more complex than `hold()` or `land()`.

## 9.2 Precision move executor behavior

Recommended execution flow:

1. Validate request payload.
2. Validate live state:
   - armed
   - airborne
   - local position fresh
   - yaw fresh
3. Connect MAVSDK and establish offboard startup discipline:
   - `action.hold()`
   - shared armability/offboard guard only where relevant
   - set neutral initial offboard setpoint
   - `offboard.start()`
4. Capture current local position and current yaw.
5. Convert body or NED operator request into a target NED position and target yaw.
6. Run a fixed-rate control loop:
   - compute position error vector
   - compute bounded feed-forward velocity toward the target
   - send `set_position_velocity_ned(target_position, feedforward_velocity)`
7. Consider the target reached only after:
   - position error <= tolerance
   - yaw error <= tolerance
   - settle time passes continuously
8. Stop offboard and hand over to hold.
9. Report success or failure to the GCS tracker.

## 9.3 Why `set_position_velocity_ned()` is the right primitive

It matches the operator contract better than either of these alone:

- pure position setpoint
- pure velocity setpoint

It lets us express:

- exact destination
- bounded speed
- deterministic settle behavior

without turning the feature into a full joystick system.

## 9.4 Preconditions and state model

Recommended rule:

- precision move is an immediate override action

That means:

- it should supersede an existing active mission the same way other immediate actions do
- it should not pretend to be compatible with synchronized queued mission execution

## 10. GCS / Tracker Changes Recommended

## 10.1 Keep current start/result reporting

Current paths already exist:

- `POST /api/v1/command-reports/execution-start`
- `POST /api/v1/command-reports/execution-result`

These should still be used.

## 10.2 Add optional execution-progress reporting

Recommended new route:

- `POST /api/v1/command-reports/execution-progress`

Recommended payload:

```json
{
  "command_id": "uuid",
  "hw_id": "1",
  "stage": "moving",
  "message": "Closing on target",
  "remaining_distance_m": 0.42,
  "yaw_error_deg": 3.1,
  "target_reached": false
}
```

Recommended stages:

- `preparing`
- `starting_offboard`
- `moving`
- `settling`
- `holding`

This is valuable beyond this feature:

- better operator UI
- better AI-agent / MCP observability
- reusable for future long-running actions

## 10.3 MCP / AI friendliness

This feature should be designed as a clean command contract, not a UI-only tool.

That means:

- typed payload
- typed success/failure surface
- stable route naming
- deterministic machine-readable fields
- no hidden UI-only parameters

That will make a future MCP layer straightforward:

- the MCP tool can call the same canonical command-submit contract
- the tool can monitor the same command tracker and progress reports

## 11. UI / UX Recommendation

## 11.1 Placement

Place the new action in the existing Flight section of `DroneActions`.

Recommended label:

- `Precision Move`

Recommended icon direction:

- crosshair / move / navigation style icon

Do not overload the normal action button with inline numeric fields.

## 11.2 Interaction model

Recommended UX:

- click `Precision Move`
- open a dedicated dialog

Why:

- body vs NED frame needs explicit clarity
- the action has more parameters than simple actions
- a modal/dialog gives room for clean validation and a safe confirmation step

## 11.3 Dialog layout

Recommended layout:

### Header

- title: `Precision Move`
- short note: `Move one airborne drone relative to its current local position, then hold.`

### Scope strip

- selected drone identity
- armed / airborne / local-position readiness
- disable submit if not safe

### Frame toggle

- `Body`
- `NED`

### Quick movement pad

For `Body`:

- Forward / Back
- Left / Right
- Up / Down
- Yaw Left / Yaw Right

For `NED`:

- North / South
- East / West
- Up / Down
- Yaw Left / Yaw Right or heading field

### Step selectors

- translation step: `0.25`, `0.5`, `1`, `2` m
- yaw step: `5`, `10`, `15`, `30` deg

### Advanced section

- exact numeric fields
- speed
- tolerances
- timeout
- yaw mode

### Summary strip

Example:

- `Move 2.0 m forward, 4.0 m right, 1.0 m up, yaw +30 deg, speed 1.0 m/s, then hold.`

### Result / progress strip

- status badge
- current progress message
- remaining distance if available

## 11.4 v1 targeting rule

I strongly recommend:

- single-drone only in the action dialog

If the operator currently has multiple drones targeted:

- disable the action
- explain why

Recommended UI message:

- `Precision Move is limited to one airborne drone at a time in the current release.`

This avoids unsafe batch misuse and keeps the mental model clean.

## 12. Recommended Implementation Slices

## Slice 0: design approval

- confirm v1 scope
- confirm naming
- confirm action code `112`

## Slice 1: contract and enum

- add `Mission.PRECISION_MOVE = 112`
- add typed payload models in `src/command_contract.py`
- thread those models through GCS schemas and docs
- update frontend constants

## Slice 2: drone-side executor seam

- create `src/action_runners/`
- convert `actions.py` into a thin dispatcher for the new modular path
- implement `precision_move.py`

## Slice 3: GCS tracker progress

- add optional `execution-progress` report contract
- update tracker and response schemas
- keep start/result compatibility

## Slice 4: frontend dialog

- add `Precision Move` action card
- add modal dialog
- add validation and operator summary
- wire into the existing command submit path

## Slice 5: tests and SITL

- unit tests
- API tests
- frontend interaction tests
- SITL action tests

## 13. Test Plan

### Unit tests

- body-to-NED transform
- yaw normalization
- target-position calculation
- timeout / settle logic
- payload validation

### API tests

- reject multi-target requests in v1
- reject missing `precision_move` payload
- reject grounded / no-local-position conditions
- accept valid body and NED requests

### Frontend tests

- dialog opens from action card
- correct fields for body vs NED
- summary text updates correctly
- submission disabled when multiple drones are targeted

### SITL tests

- move `1 m north`
- move `1 m east`
- move `1 m up`
- move body-frame forward/right
- move with relative yaw
- move while airborne from `HOLD`
- override from a simple active mission
- network-loss tolerance after acceptance

### Deferred advanced SITL

- follower-leader perturbation scenarios
- combined mode challenges
- repeated sequential precision moves

These should be added after the primitive is stable.

## 14. Docs Required When Implemented

- API docs
- action/operator guide
- AI-agent / MCP usage note
- SITL recipe entry for precision move
- changelog and recovery note

## 15. What I Recommend You Approve

If you approve this direction, I recommend implementing exactly this scope first:

- new action code `112`
- canonical typed payload name `precision_move`
- offboard local-NED target executor using `set_position_velocity_ned()`
- single-drone, immediate-only, airborne-only v1
- new operator dialog in Actions
- optional but recommended progress-report route

## 16. Main Risks To Watch During Implementation

- promising “no GPS” too broadly instead of correctly requiring a local position estimate
- letting this become a batch multi-drone feature too early
- adding it as another large `actions.py` branch without creating a reusable executor seam
- trying to drive it from the GCS instead of executing locally on the drone
- using raw velocity-only control and then calling it “precise”

## 17. Bottom Line

The right design is not `goto_location()`.

The right design is a typed `PRECISION_MOVE` action that:

- accepts body or NED relative movement
- runs locally on the drone
- uses offboard local-NED control
- computes a target from current local position
- feeds PX4 a deterministic position-plus-velocity target loop
- finishes in hold
- exposes clean status to the GCS and future MCP tooling

That gives the operator the precise, safe, reusable manual move primitive you asked for without turning the platform into a fragile joystick tunnel.

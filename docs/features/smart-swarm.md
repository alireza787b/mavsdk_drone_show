# Smart Swarm Guide

**Mission Type:** `2` (`SMART_SWARM`)  
**Primary UI Surface:** `Swarm Design` page  
**Runtime Model:** live leader-follower formation with saved follow chains and in-flight reassignment

## Overview

Smart Swarm is the live, cooperative formation mode in MDS. Each drone uses a saved swarm assignment file:

- real hardware: `swarm.json`
- SITL: `swarm_sitl.json`

- `hw_id` identifies the physical drone
- `follow` identifies the drone it should follow by **hardware ID**
- `offset_x`, `offset_y`, `offset_z` define the relative formation offset
- `frame` controls whether offsets are interpreted in `ned` or `body`

Unlike the time-synchronized **Swarm Trajectory** mode, Smart Swarm is designed for live clustered operations where operators may change leaders, offsets, frames, or relay roles while drones are airborne.

Identity rule:

- Mission Config slot reassignment changes show-slot ownership only
- Smart Swarm follow chains stay `hw_id`-anchored
- true spare replacement belongs in Fleet Enrollment, which is where follow references are rewritten for the new hardware identity

The current Smart Swarm inner loop is a hybrid model:

- leader telemetry arrives as global `lat/lon/alt`
- when available, leader local `LOCAL_POSITION_NED` also rides along the dedicated swarm-state stream
- the follower runtime converts that into a shared local NED frame
- offsets are applied in either `ned` or leader-`body` coordinates
- PX4 receives local offboard `VelocityNedYaw` setpoints

That is intentional. Smart Swarm is a relative-control problem, so local offboard control is the primary path; global telemetry is only the outer reference.

## First SITL Run

For a clean first Smart Swarm demo in SITL:

1. launch the fleet:
   ```bash
   bash multiple_sitl/create_dockers.sh 5
   ```
2. start the dashboard:
   ```bash
   bash app/linux_dashboard_start.sh --sitl
   ```
3. open `Overview` and wait until the target drones show `READY` with live telemetry
4. open `Swarm Design` and verify the saved SITL assignments from `swarm_sitl.json`
5. use `Formation Analysis` to preview the intended cluster
6. use `Smart Swarm Runtime` to review `Formation Preview` and the live readiness snapshot for either the selected drone or selected cluster
7. start Smart Swarm for the intended scope
8. if you want the full branch acceptance run from the command line, use:
   ```bash
   python3 tools/validate_smart_swarm_runtime.py
   ```
9. if you plan to chain Drone Show or Swarm Trajectory validation immediately afterward on the same SITL fleet, recreate the containers or manually restage the aircraft onto the next mode's launch geometry before the next run

The shipped 5-drone SITL demo layout currently contains two clusters and mixed `ned` / `body` offsets, so formation settle time is not instantaneous after takeoff.

Validator note:

- the Smart Swarm validator restores the selected saved swarm assignments after a successful reassignment drill, so a temporary runtime reassignment does not become the new saved SITL baseline
- it does **not** magically put landed aircraft back onto Drone Show staging slots; cross-mode launch validation still needs a deliberate launch-geometry reset between mission families

## Operator Model

Smart Swarm now has two clean command scopes:

### 1. Single-drone commands

Use the normal drone action controls when you want to affect only one aircraft.

Examples:
- send `RTL` to one drone
- send `LAND` to one drone
- send a new mission to one drone

These commands stay scoped to that drone. They do **not** automatically cancel Smart Swarm on unrelated drones.

Important caveat:

- if the addressed drone is a leader or relay leader, its followers may still react through normal leader-loss logic
- that can mean continued following, upstream reassignment, or self-hold, depending on topology and live health
- so command scope stays local, but topology side effects can still propagate through the follow chain

### 2. Swarm runtime commands

Use the `Smart Swarm Runtime` panel on the `Swarm Design` page when the intent is live Smart Swarm control:

- `Start Smart Swarm`
- `Stop Swarm (Hold)`
- `Land Swarm`
- `RTL Swarm`

The runtime panel supports:

- `Selected Drone`
- `Selected Cluster`

Specific cluster selections in `Formation Analysis` also drive the cluster-scoped runtime target. The `All executable clusters` option is analysis-only and does not issue one command across the full fleet.

This keeps swarm intent explicit instead of overloading the generic command sender with swarm-only controls, and it preserves mixed-mission operations when only part of the fleet is flying Smart Swarm.

These runtime commands now publish into the same shared command lifecycle stream as `Command Control` and per-drone airborne overrides. That means the backend-backed live/recent command monitor can recover command context after refresh/navigation instead of keeping Smart Swarm runtime actions as toast-only events.

Mixed-mission leader rule:

- a Smart Swarm leader can be selected alone and reassigned into Standard Drone
  Show or Custom CSV Drone Show without cancelling Smart Swarm on unrelated
  followers
- the addressed leader interrupts its own Smart Swarm runtime script before the
  new show mission starts; follower drones keep their current Smart Swarm
  mission and continue tracking the leader as long as usable leader telemetry is
  still published
- use `Cancel Mission`, `Hold`, `RTL`, or `Land` on the addressed drone when you
  want to explicitly stop or recover the leader-side mission
- if the leader changes, update the saved/runtime follow chain deliberately in
  Swarm Design instead of relying on implicit mission side effects

### Formation preview and live readiness

The `Smart Swarm Runtime` panel intentionally separates:

- saved formation preview
- live readiness snapshot

The preview shows the saved follow chain, roles, and offsets for the current runtime target. The live readiness snapshot is based on current telemetry/readiness state for the targeted drones.

Important operator rule:

- formation plots are not live flight views
- runtime start still performs final gating at command dispatch time
- if a target drone is not ready, fix that on `Overview` or `Mission Config` before start

## Slot Reassignment vs Spare Replacement

These scenarios are intentionally not the same workflow.

### Slot reassignment

Example:

- `H5` is reassigned from `P5` to `P6`
- `H6` is reassigned from `P6` to `P5`

Use:

- `Mission Config`

Effect:

- Drone Show / Swarm Trajectory slot ownership changes
- launch plots and `Drone {pos_id}.csv` mapping change
- Smart Swarm follow chains do **not** change automatically

Why:

- Smart Swarm topology is about which physical aircraft follows which physical
  leader, so `follow` remains `hw_id`-anchored

### Spare replacement

Example:

- failed fleet member `H12`
- spare airframe `H101` must take over slot `P12`

Use:

- `Fleet Enrollment` → `Replace existing slot`

Effect:

- slot `P12` is preserved
- the new physical drone takes over that fleet slot
- replacement rewrites the affected Smart Swarm `hw_id` / `follow`
  references so the spared-in aircraft becomes the new physical leader target
  where needed

### Same airframe, new companion image

Use:

- `Fleet Enrollment` → `Recover existing node`

Effect:

- same `hw_id`
- same `pos_id`
- refreshed IP / companion metadata only

## Runtime Behavior

### Leader transport and latency model

Smart Swarm now uses a dedicated leader-state contract instead of the old
generic drone-state HTTP poll path:

- primary transport: leader drone `WS /ws/swarm-state`
- fallback transport: leader drone `GET /api/v1/swarm/state`
- assignment source of truth: GCS swarm config routes
- follower-side live assignment cache: persisted runtime assignment file

The dedicated swarm-state payload exists so Smart Swarm timing can evolve
without coupling itself to the broader operator dashboard snapshot. The
transport now carries:

- millisecond telemetry timestamps
- monotonic stream sequence numbers
- leader global position/velocity
- leader local NED position/velocity when available
- yaw and yaw-rate

Follower freshness is no longer keyed off a coarse second-resolution
`update_time`. Runtime freshness now depends on the dedicated stream contract,
with HTTP fallback only when the realtime stream is unavailable.

The current transport timing knobs are centralized in [params.py](../../src/params.py), including:

- `SMART_SWARM_LEADER_STATE_TIMEOUT_SEC`
- `SMART_SWARM_GCS_CONFIG_TIMEOUT_SEC`
- `SMART_SWARM_GCS_NOTIFY_TIMEOUT_SEC`
- `SMART_SWARM_USE_REALTIME_STREAM`
- `SMART_SWARM_ENABLE_HTTP_FALLBACK`
- `SMART_SWARM_STATE_STREAM_RATE_HZ`
- `SMART_SWARM_STREAM_CONNECT_TIMEOUT_SEC`
- `SMART_SWARM_STREAM_BACKOFF_INITIAL_SEC`
- `SMART_SWARM_STREAM_BACKOFF_MAX_SEC`
- `SMART_SWARM_STREAM_PREDICT_GRACE_SEC`
- `SMART_SWARM_RECONFIG_TRANSITION_SEC`
- `SMART_SWARM_USE_LOCAL_NED_WHEN_VALID`
- `SMART_SWARM_KV`
- `SMART_SWARM_MAX_ACCELERATION`
- `SMART_SWARM_MAX_JERK`
- `MAX_LEADER_UNREACHABLE_ATTEMPTS`
- `LEADER_ELECTION_COOLDOWN`
- `MAX_STALE_DURATION`
- `LEADER_UPDATE_FREQUENCY` (legacy HTTP fallback cadence)
- `DATA_FRESHNESS_THRESHOLD`
- `CONFIG_UPDATE_INTERVAL`

That keeps Smart Swarm timing policy in one place instead of scattering literals across runtime tasks.

### Tracking proof workflow

If you need to prove that a follower is tracking the leader on the current
runtime path, use the dedicated tracking-analysis guide:

- [Smart Swarm Tracking Analysis](../guides/smart-swarm-tracking-analysis.md)

That workflow captures:

- expected follower `N/E/D` from leader state plus offsets
- actual follower `N/E/D`
- repeated jog-sized leader moves
- mixed `body` and `ned` frame commands
- JSON, CSV, and plot artifacts for later review

### Current transport behavior and next-step roadmap

What is true in the current validated branch:

- follower-to-leader state is websocket-primary with bounded reconnect/backoff
- follower-to-leader HTTP fallback is still available and intentionally kept
- follower-to-GCS assignment refresh remains periodic HTTP polling
- follower-to-GCS leader-change notify remains HTTP POST
- stale-data and transport-loss handling share the same failover path

Why this is the correct current design:

- realtime leader updates no longer wait on second-resolution timestamps
- the websocket stream cuts avoidable polling delay without removing the known-good HTTP path
- reconnect, stale-data grace, and failover remain explicit instead of hidden inside transport-specific side effects
- command scope and assignment scope stay loosely coupled

Why it is still not the final large-scale architecture:

- GCS-side live telemetry views are still a mix of polling and streams
- assignment refresh is still HTTP polling rather than push-driven
- real-world degraded networks can still benefit from transport metrics, confidence scoring, and richer outage analytics

Recommended next industrial path:

1. keep the websocket + HTTP dual path
2. validate degraded-network behavior under induced delay/loss/partitions
3. add richer operator-visible leader-state confidence and transport metrics
4. only then consider payload compression or more aggressive transport optimization

Real-world network considerations to keep in mind:

- short disconnects must not immediately cause unsafe topology churn
- stale but reachable links are often more dangerous than hard failures
- leader election should stay topology-safe even when GCS is slow or briefly unavailable
- reconnect behavior must avoid synchronized thundering-herd retries
- operator logs must distinguish transport loss, stale data, and actual flight-mode failover
- transport changes must not hide command scope; a leader-only override should stay leader-only unless explicit swarm logic says otherwise

### Mission start

When Smart Swarm starts, each drone:

1. loads the local fleet config
2. refreshes the latest swarm assignment from GCS
3. decides whether it is a top leader or follower
4. starts follower tasks only if it is configured as a follower

This avoids stale local `swarm_sitl.json` assignments at startup.

### Dynamic reassignment

During flight, the runtime periodically refreshes assignments from GCS. Supported live changes include:

- changing the followed leader
- changing offsets
- switching between `ned` and `body`
- switching a drone between leader and follower roles

When a drone transitions back into follower mode, the runtime now explicitly re-establishes offboard control and restarts any missing follower tasks instead of assuming the previous follower runtime is still healthy.

Leader-only failover notifications also now update only the `follow` field in GCS, so a runtime leader change does not overwrite fresher operator-edited offsets or frame settings.

### Follower control behavior

Follower control now does more than basic position-error chasing:

- leader-velocity feedforward is included in the target velocity command
- leader body-frame offsets include yaw-rate-induced offset velocity
- controller/filter state resets and blends when topology or offset config changes live
- stale leader samples degrade through a predictive-grace ramp before hard failover

That makes the controller better suited for:

- leaders moving under mission scripts
- live jog/manual leader motion
- in-flight role changes and offset edits
- mixed-quality links where short jitter bursts should not immediately create a topology event

### Leader-loss handling

Current default policy: `upstream_or_hold`

If a follower loses its direct leader:

- if the failed leader was itself following another leader, the follower adopts that upstream leader
- if no safe upstream leader exists, the drone self-promotes to an independent leader and enters `HOLD`

Leader-loss handling now treats both cases as degraded leader health:

- outright leader API fetch failures
- leader telemetry that still responds but stops advancing `update_time`

This is safer than the older global “next numeric hw_id” fallback because it stays within the active follow chain instead of jumping across unrelated drones.

Available policy values in [params.py](/opt/mavsdk_drone_show/src/params.py):

- `upstream_or_hold` - default, cluster-safe fallback
- `hold` - always self-promote and hold
- `next_hw_id` - legacy deterministic behavior, kept only for controlled compatibility

Cycle protection is enforced in two places:

- dashboard assignment validation before save
- GCS backend validation for canonical `PUT /api/v1/config/swarm` and `PATCH /api/v1/config/swarm/assignments/{hw_id}` updates

That prevents live leader changes from silently introducing a loop into the follow chain.

## Runtime Guarantees Added In This Audit

- dedicated leader-state stream at `WS /ws/swarm-state` with `GET /api/v1/swarm/state` fallback
- millisecond telemetry freshness and stream sequence tracking instead of second-only `update_time`
- follower control waits for both own-state and leader-state lock before sending formation setpoints
- leader-state prediction no longer double-counts elapsed time between measurements
- follower commands include leader-velocity feedforward before saturation, reducing steady-state lag against moving leaders
- body-frame offsets include leader yaw-rate compensation
- controller/filter state resets and blend ramps apply on live topology/offset/frame changes
- follower re-entry restarts offboard mode cleanly after leader-to-follower transitions
- failed follower re-entry now retries instead of getting stuck half-switched
- stale leader telemetry now participates in the same failover path as explicit request failures
- runtime controls default to `Selected Drone`; cluster scope is opt-in
- cluster-scoped start blockers now apply only to the targeted drones instead of unrelated unsaved edits elsewhere in the design page

## Files That Matter

### Runtime and failover

- [smart_swarm.py](../../smart_swarm.py)
- [failover.py](../../smart_swarm_src/failover.py)
- [pd_controller.py](../../smart_swarm_src/pd_controller.py)
- [params.py](../../src/params.py)
- [local_mavlink_controller.py](../../src/local_mavlink_controller.py)
- [drone_communicator.py](../../src/drone_communicator.py)
- [drone_api_server.py](../../src/drone_api_server.py)
- [swarm_runtime_state.py](../../src/swarm_runtime_state.py)

### GCS persistence and live updates

- [swarm.py](../../gcs-server/api_routes/swarm.py)
  - `GET /api/v1/config/swarm`
  - `PUT /api/v1/config/swarm`
  - `PATCH /api/v1/config/swarm/assignments/{hw_id}`

### Frontend control surfaces

- [SwarmDesign.js](../../app/dashboard/drone-dashboard/src/pages/SwarmDesign.js)
- [SwarmRuntimeControls.js](../../app/dashboard/drone-dashboard/src/components/SwarmRuntimeControls.js)
- [swarmDesignUtils.js](../../app/dashboard/drone-dashboard/src/utilities/swarmDesignUtils.js)
- [swarmRuntimeUtils.js](../../app/dashboard/drone-dashboard/src/utilities/swarmRuntimeUtils.js)

## Operational Notes

- Smart Swarm follow links use `hw_id`, not `pos_id`.
- Slot swaps change the show slot, not the follow chain.
- Start Smart Swarm only after saving the intended assignments.
- In SITL, the default demo file is `swarm_sitl.json`; it currently defines 5 drones across two clusters.
- Use swarm runtime controls when you want either a selected-drone override or an explicit cluster-level intent.
- Use single-drone controls when you want a scoped override.

## Recommended SITL Validation

For each Smart Swarm release, validate at minimum:

1. takeoff with 4-5 drones
2. start Smart Swarm on a cluster
3. change offsets and frame in flight
4. reassign one follower to a different leader
5. send a single-drone override to confirm other followers remain in Smart Swarm
6. run `Land Swarm` or `RTL Swarm`
7. verify all drones disarm cleanly

The reusable validation tool for this flow is:

```bash
python3 tools/validate_smart_swarm_runtime.py
```

For stricter acceptance or degraded-network/failover checks, also run:

```bash
python3 tools/validate_smart_swarm_runtime.py \
  --horizontal-tolerance 1.5 \
  --altitude-tolerance 0.6

python3 tools/validate_smart_swarm_runtime.py \
  --simulate-leader-dropout
```

The leader-dropout drill is SITL-oriented. It pauses the active leader
container, validates promotion / continued follower tracking, then confirms the
paused leader resumes telemetry after unpause.

## Known Next-Step Opportunities

- richer operator-facing swarm stop/hold state reporting
- smarter cluster-level leader election policies
- transport optimization beyond HTTP polling if very large swarms require it
- UI playback and incident review tied to unified logging

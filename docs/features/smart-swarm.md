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

The current Smart Swarm inner loop is a hybrid model:

- leader telemetry arrives as global `lat/lon/alt`
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

The shipped 5-drone SITL demo layout currently contains two clusters and mixed `ned` / `body` offsets, so formation settle time is not instantaneous after takeoff.

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

### Formation preview and live readiness

The `Smart Swarm Runtime` panel intentionally separates:

- saved formation preview
- live readiness snapshot

The preview shows the saved follow chain, roles, and offsets for the current runtime target. The live readiness snapshot is based on current telemetry/readiness state for the targeted drones.

Important operator rule:

- formation plots are not live flight views
- runtime start still performs final gating at command dispatch time
- if a target drone is not ready, fix that on `Overview` or `Mission Config` before start

## Runtime Behavior

### Leader transport and latency model

Today, Smart Swarm follower-to-leader state exchange uses short HTTP polls:

- follower drones poll the leader drone API for state
- GCS remains the source of truth for saved swarm assignments
- followers also refresh assignment changes from GCS during flight

That is intentionally conservative for this phase:

- HTTP polling is simple to inspect and debug
- failures are explicit and already feed the current leader-loss logic
- it keeps command scope, assignment storage, and follower control loosely coupled

WebSocket transport can reduce polling overhead in larger swarms, but it should be added later behind a transport abstraction with HTTP fallback. For the current validated 4-5 drone clustered flow, the main reliability issues were not transport-related.

The current transport timing knobs are centralized in [params.py](../../src/params.py), including:

- `SMART_SWARM_LEADER_STATE_TIMEOUT_SEC`
- `SMART_SWARM_GCS_CONFIG_TIMEOUT_SEC`
- `SMART_SWARM_GCS_NOTIFY_TIMEOUT_SEC`
- `MAX_LEADER_UNREACHABLE_ATTEMPTS`
- `LEADER_ELECTION_COOLDOWN`
- `MAX_STALE_DURATION`
- `LEADER_UPDATE_FREQUENCY`
- `DATA_FRESHNESS_THRESHOLD`
- `CONFIG_UPDATE_INTERVAL`

That keeps Smart Swarm timing policy in one place instead of scattering literals across runtime tasks.

### Transport roadmap and engineering note

This section is the intended starting point for the next transport-focused Smart Swarm audit. Re-check the live codebase at that time before implementing it, because surrounding runtime, GCS, and dashboard behavior may have changed.

What is true in the current validated branch:

- follower to leader state is short HTTP polling
- follower to GCS assignment refresh is short HTTP polling
- follower to GCS leader-change notify is HTTP POST
- GCS exposes WebSocket streams for browser telemetry, heartbeat, and git-status consumers
- the current React dashboard still mostly uses REST polling, while the Log Viewer uses SSE

Why the current design is acceptable right now:

- the validated 4-5 drone Smart Swarm flow is working on the HTTP path
- failures are easy to inspect in logs and easy to reproduce in SITL
- stale-data detection and leader-loss failover already depend on explicit request outcomes and advancing `update_time`
- command scope and assignment scope remain loosely coupled instead of being hidden inside a bidirectional streaming layer

Why it is not yet the final large-scale architecture:

- GCS still performs a meaningful amount of REST polling
- current browser pages do not fully consume the existing backend WebSocket streams
- leader/follower transport is implemented directly in runtime tasks instead of behind a pluggable interface
- real-world degraded networks can introduce jitter, head-of-line delay, short partitions, asymmetric loss, and reconnect storms that deserve transport-specific controls

Recommended industrial path for the next transport phase:

1. keep HTTP polling as the known-good fallback path
2. add a transport abstraction for leader-state delivery
3. move dashboard live telemetry and heartbeat views onto the already-existing GCS WebSocket streams
4. if swarm scale or bandwidth pressure justifies it, add a follower leader subscription mode with:
   - bounded reconnect/backoff
   - stale-data timers independent of transport
   - explicit fallback to HTTP polling
   - identical failover semantics across both transports
5. only after those foundations are in place, consider higher-performance optimizations such as delta/state compression or binary payloads

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
- GCS backend validation for `save-swarm-data` and `request-new-leader`

That prevents live leader changes from silently introducing a loop into the follow chain.

## Runtime Guarantees Added In This Audit

- follower control waits for both own-state and leader-state lock before sending formation setpoints
- leader-state prediction no longer double-counts elapsed time between measurements
- follower commands include leader-velocity feedforward before saturation, reducing steady-state lag against moving leaders
- follower re-entry restarts offboard mode cleanly after leader-to-follower transitions
- failed follower re-entry now retries instead of getting stuck half-switched
- stale leader telemetry now participates in the same failover path as explicit request failures
- runtime controls default to `Selected Drone`; cluster scope is opt-in
- cluster-scoped start blockers now apply only to the targeted drones instead of unrelated unsaved edits elsewhere in the design page

## Files That Matter

### Runtime and failover

- [smart_swarm.py](../../smart_swarm.py)
- [failover.py](../../smart_swarm_src/failover.py)
- [params.py](../../src/params.py)

### GCS persistence and live updates

- [app_fastapi.py](../../gcs-server/app_fastapi.py)
  - `GET /get-swarm-data`
  - `POST /save-swarm-data`
  - `POST /request-new-leader`

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

## Known Next-Step Opportunities

- richer operator-facing swarm stop/hold state reporting
- smarter cluster-level leader election policies
- transport optimization beyond HTTP polling if very large swarms require it
- UI playback and incident review tied to unified logging

# PX4 Parameters

## Overview

The `PX4 Parameters` subsystem gives operators a GCS-managed way to inspect,
edit, diff, import, export, and batch-apply PX4 parameters without leaving the
MDS dashboard.

Design rules:

- dashboard talks only to GCS
- GCS orchestrates snapshots, diffs, imports, and tracked patch jobs
- drone-local vehicle access stays drone-owned: targeted read/write operations
  use MAVSDK, while bulk snapshot enumeration may fall back to the local
  MAVLink parameter microservice when MAVSDK bulk listing is unavailable in the
  runtime
- QGroundControl `.params` interoperability is supported, but MDS keeps a typed
  internal patch format for automation and future MCP workflows
- repo-backed parameter profiles live under `resources/px4_param_profiles/` so
  fleet baselines follow the same repo-managed asset model as other operator
  configuration artifacts

## Current v1 Capabilities

### Single-Drone Workspace

- refresh a live PX4 snapshot for one drone
- search and filter parameters
- inspect current/default/min/max metadata when available
- edit one parameter with readback verification
- open the exact official PX4 parameter-reference page anchor for that
  parameter
- export the current snapshot as a QGC-compatible `.params` file
- import a QGC `.params` file, diff it against the current snapshot, and apply
  the reviewed changes

### Batch Workspace

- reuse the shared MDS fleet/cluster/selected-drone scope model
- batch scope defaults to `None` until the operator explicitly selects a target
- dispatch one typed parameter patch to:
  - all drones
  - one Smart Swarm cluster
  - an explicit selected subset
- track per-drone apply/verify outcomes through one GCS patch-job response
- prefer saved profile bundles for repeatable fleet baselines; keep manual
  single-parameter entry for one-off overrides only

### Profiles Workspace

- browse repo-backed PX4 parameter profiles from `resources/px4_param_profiles/`
- review entry count, scope guidance, tags, and per-entry target values
- export a selected profile as typed MDS JSON for automation or repo reuse
- preview a saved profile against the currently selected drone snapshot
- load the selected profile directly into the Batch workspace for tracked apply
- use this workspace as the operator-facing home for repeatable fleet baselines
  instead of the older one-off `Apply Common Params` action path

## Metadata Source Rules

MDS does not hardcode parameter metadata to one firmware snapshot.

- live single-parameter reads/writes come from the drone through MAVSDK param
  APIs
- bulk snapshot refresh prefers MAVSDK bulk listing and falls back to the local
  MAVLink parameter protocol on the routed `14569` endpoint when the runtime
  does not implement MAVSDK `GetAllParams`
- defaults, ranges, decimal hints, and reboot-required flags come from the
  vehicle/component-information path when PX4 exposes them
- official docs links are generated from the configured docs version plus the
  parameter anchor, for example:
  - `https://docs.px4.io/main/en/advanced_config/parameter_reference.html#GF_MAX_HOR_DIST`

If PX4 does not provide a metadata field, MDS leaves it empty instead of
inventing one.

## Safety Policy

- writes are blocked while the target drone is explicitly armed when
  `PX4_PARAMETER_MUTATION_REQUIRE_DISARMED` is enabled
- telemetry delay alone does not block writes if a fresh snapshot/write path is
  otherwise available
- single writes and batch writes both default to readback verification

## Operator Notes

- use `Single Drone` for QGC-style inspection and targeted tuning
- use `Profiles` to review approved fleet baselines before applying them
- use `Batch` for deliberate fleet-wide or cluster-wide settings
- refresh a snapshot before making decisions from stale values
- treat reboot-required flags as advisory from PX4 metadata; they are shown
  when the vehicle reports them
- keep repeatable fleet policies in repo-backed profiles instead of relying on
  ad hoc CSVs or one-off manual batch entry

## Deferred Follow-Up

- richer grouped/category views if PX4 metadata quality proves strong enough
- tracked long-running patch jobs if real fleets need asynchronous apply flows
- migration or retirement of the older `APPLY_COMMON_PARAMS` workflow after the
  action-pipeline audit
- advanced SITL drills beyond the validated single-drone plus two-drone
  snapshot/apply/restore gate

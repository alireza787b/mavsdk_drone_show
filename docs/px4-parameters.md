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
- the older common-params CSV compatibility path defaults to
  `resources/common_params.csv`, not an ad hoc project-root file

## Current v1 Capabilities

### Single-Drone Workspace

- refresh a live PX4 snapshot for one drone
- search and filter parameters
- use a scan-first list/table plus one consistent detail dialog across phone,
  tablet, and desktop widths
- inspect current/default/min/max metadata when available
- display numeric values with PX4 decimal hints when available, otherwise use a
  trimmed operator-readable precision instead of raw full-float output
- edit one parameter with readback verification
- open the exact official PX4 parameter-reference page anchor for that
  parameter
- export the current snapshot as a QGC-compatible `.params` file
- import a QGC `.params` file, diff it against the current snapshot, and apply
  the reviewed changes
- dispatch a single-drone `Reboot PX4` action through the normal tracked
  command path when the target drone is online, disarmed, and on the ground
- show compact inline status notices for snapshot refresh, import, write,
  verification, and reboot tracking instead of burying feedback in toasts only

### Batch Workspace

- reuse the shared MDS fleet/cluster/selected-drone scope model
- batch scope defaults to `None` until the operator explicitly selects a target
- dispatch one typed parameter patch to:
  - all drones
  - one Smart Swarm cluster
  - an explicit selected subset
- if the chosen scope includes offline drones, require explicit operator
  confirmation before applying only to the online subset
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
- rich parameter metadata prefers the generated PX4 parameter catalog
  (`parameters.json`) when it is present in the runtime, because that carries
  defaults, min/max, reboot flags, units, descriptions, and enum values across
  more than just float parameters
- if the generated catalog is not available, MDS falls back to the older
  vehicle/component-information path for float-parameter hints that PX4
  exposes through MAVSDK
- official docs links are generated from the configured docs version plus the
  parameter anchor, for example:
  - `https://docs.px4.io/main/en/advanced_config/parameter_reference.html#GF_MAX_HOR_DIST`

If PX4 does not provide a metadata field, MDS leaves it empty instead of
inventing one.

### Recommended Source Order

For a production-grade fleet, the intended metadata source order is:

1. live parameter values from the vehicle
2. vehicle-served PX4 parameter metadata if the firmware exposes it through the
   MAVLink Component Metadata / MAVLink FTP path
3. a local generated PX4 catalog available on the companion/runtime host
   (`parameters.json`) for SITL or tightly managed embedded deployments
4. MAVSDK component-information float hints as a weaker fallback
5. official PX4 docs links for operator reference only

The important rule is that online docs should not become the authority for
runtime parameter semantics. They are useful as a human-readable reference and
can be cached for convenience, but the authoritative machine-readable metadata
should come from the connected PX4 firmware or its shipped metadata bundle.

### Caching Guidance

- cache static parameter metadata by firmware identity or metadata CRC, not by
  parameter name alone
- do not refetch static metadata on every snapshot refresh; only live values
  need frequent reads
- treat metadata as effectively invariant for one boot / firmware build unless
  the vehicle advertises a changed metadata file or firmware version
- keep online docs caching optional and read-only; stale docs must not block
  parameter inspection or mutation

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
- tap or click a parameter row/card to open the detail dialog; keep the main
  list/table for scanning, not for reading every metadata field inline
- touch devices in browser “desktop mode” still stay on the compact card +
  dialog workflow to avoid forcing a cramped pseudo-desktop inspector onto a
  phone
- refresh a snapshot before making decisions from stale values
- treat reboot-required flags as advisory from PX4 metadata; they are shown
  when the generated PX4 catalog or vehicle metadata reports them
- keep repeatable fleet policies in repo-backed profiles instead of relying on
  ad hoc CSVs or one-off manual batch entry
- profile creation/edit/save-new remains repo-managed in v1; the browser is
  currently for review, diff, apply, export, and tracked runtime operations

## Storage Layout

- live fleet config remains in root `config*.json` / `swarm*.json`
- reviewed PX4 parameter profiles live in `resources/px4_param_profiles/`
- the legacy `APPLY_COMMON_PARAMS` action reads `resources/common_params.csv`
  by default until the action pipeline is fully converged
- generated mission outputs belong under `shapes/` or `shapes_sitl/`, not in
  the PX4 profile library

See [Repo Asset Layout](guides/repo-asset-layout.md) for the full storage
doctrine.

## Deferred Follow-Up

- richer grouped/category views if PX4 metadata quality proves strong enough
- tracked long-running patch jobs if real fleets need asynchronous apply flows
- migration or retirement of the older `APPLY_COMMON_PARAMS` workflow after the
  action-pipeline audit
- convergence of the older `INIT_SYSID` action onto the same shared PX4
  parameter write path, while keeping it a maintenance control rather than
  duplicating it inside the main runtime parameter workspace
- optional firmware/build identity reporting only after there is one clean
  vehicle-served source for PX4 version data; do not invent or hardcode it in
  the page
- hardware-grade metadata discovery and caching via PX4 Component Metadata /
  MAVLink FTP, keyed by firmware identity or metadata CRC instead of relying on
  local build artifacts alone
- advanced SITL drills beyond the validated single-drone plus two-drone
  snapshot/apply/restore gate

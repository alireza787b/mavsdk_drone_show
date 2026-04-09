# PX4 Parameter Management Design Brief

Date: 2026-04-09
Status: Design only, not implemented
Scope: Dashboard-native PX4 parameter management for single-drone and batch workflows

## Executive Summary

The current product does **not** have real onboard PX4 parameter management. It has:

- raw MAVSDK param capability in the vendored SDK
- one narrow write-only action, `APPLY_COMMON_PARAMS`
- a CLI path that can set params opportunistically before an action

That is not sufficient for QGC-like browse/edit/import/export/compare workflows, and it is not a good foundation for future MCP / AI-agent control.

The recommended direction is a **new dedicated `PX4 Parameters` subsystem**, not an extension of the existing action button:

- drone-local parameter access via MAVSDK
- GCS-side snapshot, diff, compare, and batch orchestration
- dashboard page that talks only to GCS
- a shared normalized patch model for UI, CLI, tests, and future MCP

## Current State Audit

What exists:

- MAVSDK param support already exists in `mavsdk/param.py`:
  - get int / float / custom
  - set int / float / custom
  - get all params
  - component selection support
- product code currently only uses `set_param_int()` / `set_param_float()` in `actions.py`
- `APPLY_COMMON_PARAMS = 111` reads a local CSV on each drone and applies it independently
- the dashboard exposes only a generic `Apply Params` action

What does not exist:

- no dedicated GCS or drone HTTP API for parameter list/read/write/import/export/compare
- no dashboard page for PX4 parameter management
- no diff workflow across drones
- no read-after-write verification path
- no param metadata/catalog strategy
- no batch patch job model

Current debt that should **not** be extended:

- `APPLY_COMMON_PARAMS` is CSV-driven, loosely typed, and not true sync
- `common_params.csv` pathing is inconsistent
- parameter typing is partially guessed
- reboot policy is hardcoded in the current UI
- app config and onboard PX4 params are easy to confuse today

## Standards / Research Findings

### MAVSDK / MAVLink reality

- MAVSDK supports direct parameter reads, writes, and full-list retrieval.
- MAVLink parameter protocol supports:
  - read all: `PARAM_REQUEST_LIST`
  - read one: `PARAM_REQUEST_READ`
  - set one: `PARAM_SET`
  - update stream: `PARAM_VALUE`
- The MAVLink guide states PX4 supports only `INT32` and `FLOAT` in normal parameter use.
- MAVLink also explicitly recommends GCS-side caching, but notes cache synchronisation is not guaranteed.
- MAVLink parameter requests can target specific components, and QGroundControl typically queries `MAV_COMP_ID_ALL`.

### PX4 / QGC behavior worth copying

- QGC parameter UX supports:
  - search
  - show modified only
  - grouped browsing
  - single-row edit dialog
  - refresh
  - reset/default tools
  - load/save parameter files
- QGC parameter file format is simple and stable:
  - `Vehicle-Id`
  - `Component-Id`
  - `Name`
  - `Value`
  - `Type`
- PX4 docs warn that while some parameters can be changed in flight, this is generally not recommended.
- PX4’s parameter reference is the canonical public doc source for:
  - type
  - reboot required
  - min / max
  - default
  - unit
  - description

### What not to copy blindly

- Do not expose raw MAVLink parameter traffic as the operator-facing mission API.
- Do not make dashboard clients talk directly to drone APIs.
- Do not keep `APPLY_COMMON_PARAMS` as a parallel second subsystem.
- Do not depend on live doc scraping during operations.
- Do not promise perfectly fresh param caches without explicit refresh; MAVLink itself does not guarantee that.

## Design Principles

1. One clean subsystem, not action-by-action growth.
2. GCS is the only dashboard-facing entrypoint.
3. Drone-local MAVSDK remains the only writer/reader of PX4 parameters.
4. Use explicit snapshots, diffs, and patch jobs.
5. Batch mutations must be audited and tracked.
6. Reuse existing MDS selector/search/identity primitives.
7. Prefer explicit refresh and verification over silent assumptions.
8. Keep the design MCP-friendly by using typed app-level contracts above MAVLink.
9. No new legacy compatibility layer unless it materially reduces rollout risk.

## Recommended Product Shape

Add a new top-level dashboard page:

- `PX4 Parameters`

Recommended operator layout:

- top bar:
  - scope summary
  - selected drone / cluster / all
  - snapshot freshness
  - firmware/version mismatch warnings
  - refresh controls
- workspace tabs:
  - `Single Drone`
  - `Batch`
  - `Profiles`
  - `Activity`

### Single Drone

Goal: QGC-like inspection/editing for one target drone.

Behavior:

- select exactly one drone using the shared MDS selector model
- fetch or reuse a GCS-managed snapshot
- browse/search the parameter table
- filter by:
  - name/description search
  - modified only
  - changed in current session
  - reboot required
  - component
- click a row to open a side inspector/editor
- edit, save, verify readback, show result
- export current snapshot
- compare current snapshot against:
  - import file
  - saved profile
  - another drone snapshot

### Batch

Goal: safe, auditable parameter patching across selected drones.

Behavior:

- reuse existing `all / cluster / selected` scope model
- show explicit target count and identity summary
- support:
  - single-parameter batch set
  - multi-parameter profile patch
  - import-file diff then selective apply
- show per-drone compatibility warnings before apply:
  - offline drone
  - firmware mismatch
  - missing parameter
  - value already matches
  - reboot required
- execute as a tracked patch job
- show per-drone results and readback verification

### Profiles

Goal: replace the current `common_params.csv` idea with a first-class, typed workflow.

Recommended formats:

- Interop format:
  - QGC parameter file import/export
- Native MDS format:
  - typed JSON patch/profile for MCP, CI, automation, and clean audit history

Why both:

- QGC format is useful for interoperability
- MDS format is better for machine-generated batch operations, validation policy, and future automation

### Activity

Goal: give operators and future MCP clients a clear execution history.

Show:

- snapshot refresh jobs
- patch apply jobs
- import diff jobs
- verification failures
- reboot-required outcomes

## Architecture Recommendation

## 1. Drone-side: local PX4 param facade

Add a dedicated drone-local service layer, for example:

- `src/px4_params/service.py`

Responsibilities:

- read all parameters via MAVSDK
- read single parameter
- write single parameter
- write a patch set
- verify readback
- expose a normalized row model
- optionally keep a small local cache with timestamp

Add dedicated drone API routes, for example:

- `GET /api/v1/px4-params/policy`
- `POST /api/v1/px4-params/snapshots/refresh`
- `GET /api/v1/px4-params/snapshots/current`
- `GET /api/v1/px4-params/values/{name}`
- `PATCH /api/v1/px4-params/values/{name}`
- `POST /api/v1/px4-params/patches/apply`

Recommendation:

- v1 defaults to the autopilot component
- keep component targeting in the model, but do not expose a noisy multi-component UI yet

## 2. GCS-side: fleet param orchestration

Add a GCS-side subsystem, for example:

- `gcs-server/px4_params.py`
- `gcs-server/api_routes/px4_params.py`

Responsibilities:

- request per-drone snapshots from drone APIs
- normalize/store snapshots in GCS memory or lightweight persistence
- serve paginated/search-filtered rows to dashboard
- generate diffs
- parse import files
- create and track batch patch jobs
- keep operator-facing results consistent with the existing MDS command/monitor discipline

Recommended GCS routes:

- `GET /api/v1/px4-params/policy`
- `POST /api/v1/px4-params/snapshots`
- `GET /api/v1/px4-params/snapshots/{snapshot_id}`
- `GET /api/v1/px4-params/snapshots/{snapshot_id}/rows`
- `POST /api/v1/px4-params/diff`
- `POST /api/v1/px4-params/imports/qgc`
- `POST /api/v1/px4-params/imports/mds`
- `POST /api/v1/px4-params/patch-jobs`
- `GET /api/v1/px4-params/patch-jobs/{job_id}`

## 3. Dashboard-side: one page, shared selector primitives

Do not invent a new selector system.

Reuse:

- `CommandSender` scope model
- `dronePresentation.js` search grammar
- `missionIdentityUtils.js` `Pn|Hm` identity formatting
- `ClusterScopeBar`
- explicit “visible != mutation scope” rule from Overview

UI implementation recommendation:

- use existing `@mui/x-data-grid`
- do not add a new table dependency
- use existing file tooling (`papaparse` already exists) for import parsing where helpful

## Data Model Recommendation

Core models:

- `Px4ParamRow`
  - component_id
  - name
  - type
  - value
  - default_value
  - min_value
  - max_value
  - unit
  - reboot_required
  - short_description
  - docs_url
  - source
- `Px4ParamSnapshot`
  - snapshot_id
  - hw_id
  - px4_version
  - component_scope
  - created_at
  - stale
  - rows
- `Px4ParamPatchEntry`
  - component_id
  - name
  - target_value
  - type
- `Px4ParamPatchJob`
  - job_id
  - scope
  - source
  - status
  - started_at
  - completed_at
  - per_drone_results

Important distinction:

- app config is not PX4 params
- route/domain names should use `px4-params`, not bare `params`

That avoids confusion with `src/params.py` and current GCS configuration editing.

## Metadata Strategy

Recommended v1:

- do **not** scrape docs live during operations
- do **not** depend on MAVSDK component information as the only source; current support is incomplete for this use case
- provide:
  - live name/type/value from vehicle
  - optional default/min/max/unit if available from a metadata provider
  - stable link to official PX4 parameter docs/reference

Recommended v2:

- add a generated offline PX4 parameter metadata catalog keyed by PX4 version

## Safety / Ops Policy

Recommended v1 mutation policy:

- reads allowed whenever link is healthy
- writes default to:
  - disarmed
  - on-ground
  - single-drone or explicitly confirmed batch scope
- batch writes require an explicit confirmation review
- rows that imply reboot should be clearly marked
- do not silently reboot; make reboot an explicit operator action

Rationale:

- PX4 documentation explicitly warns that in-flight parameter changes are generally not recommended
- this is a safer default for production-facing operations

## Low-Bandwidth / Reliability Strategy

- full parameter fetch happens between GCS and drone, not dashboard and drone
- dashboard consumes paginated/search-filtered snapshot views from GCS
- every snapshot carries freshness/staleness metadata
- every write performs read-after-write verification
- if verification cannot complete, state must be:
  - `applied_unverified`
  - not silently `success`
- batch jobs must tolerate partial completion and report per-drone outcome

## Existing Feature Migration

`APPLY_COMMON_PARAMS` should not survive as a separate long-term workflow.

Recommended migration:

- phase out `APPLY_COMMON_PARAMS`
- migrate `common_params.csv` usage into:
  - MDS parameter profiles
  - optionally importable QGC-style files
- keep one parameter subsystem and one audit trail

## Recommended Implementation Phases

### Phase 1: foundation

- add normalized `px4-params` schemas
- add drone-local param facade
- add drone param routes
- add GCS param routes and snapshot store
- add route constants and typed service layer

### Phase 2: single-drone page

- add `PX4 Parameters` page
- reuse shared drone scope/search primitives
- add snapshot refresh + searchable table + row inspector
- add single-row edit + readback verification

### Phase 3: import/export/compare

- support QGC file import/export
- support MDS patch import/export
- add diff view:
  - current vs import
  - drone vs drone
  - scope variance

### Phase 4: batch patch jobs

- add batch review/apply workflow
- add tracked job execution and activity view
- migrate `APPLY_COMMON_PARAMS` to the new subsystem

### Phase 5: SITL and operator validation

- add deterministic validators for:
  - snapshot refresh
  - single param edit
  - batch patch apply
  - import diff
  - reboot-required path
  - partial failure handling

## 3rd-Party Tool Recommendation

Do not add a new major dependency first.

Existing stack is already sufficient:

- `@mui/x-data-grid` for large param tables
- `papaparse` for file parsing if needed
- existing MDS service layer and command/status patterns for operator feedback

## Open Questions

No blocker questions are required before implementation starts.

My recommended assumptions are:

- v1 is autopilot-component-first
- v1 mutations are disarmed/on-ground by default
- v1 docs use stable external PX4 links, not embedded live doc scraping
- v1 removes long-term dependence on `APPLY_COMMON_PARAMS`

## Recommended Next Step

If approved, implement in this order:

1. foundation + route/schema layer
2. single-drone workspace
3. import/export/compare
4. batch patch jobs
5. SITL validation + docs + migration cleanup

## Reference Basis

Primary external references used for this brief:

- MAVLink Parameter Protocol:
  - https://mavlink.io/en/services/parameter.html
- PX4 parameter UI / operational guidance:
  - https://docs.px4.io/main/en/advanced_config/parameters
- PX4 parameter reference:
  - https://docs.px4.io/main/en/advanced_config/parameter_reference
- QGroundControl parameter file format:
  - https://docs.qgroundcontrol.com/Stable_V4.4/en/qgc-dev-guide/file_formats/parameters.html
- MAVSDK Param API reference:
  - https://mavsdk.mavlink.io/v1.0/en/cpp/api_reference/classmavsdk_1_1_param.html

Relevant current repo evidence:

- `mavsdk/param.py`
- `actions.py`
- `src/drone_api_server.py`
- `src/command_contract.py`
- `app/dashboard/drone-dashboard/src/components/CommandSender.js`
- `app/dashboard/drone-dashboard/src/utilities/dronePresentation.js`

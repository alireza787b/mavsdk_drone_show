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
- all reusable baselines use the same typed profile contract; there is no
  parallel CSV/action mutation path

## Operator Workspace

See the [illustrated operator workflow](guides/px4-parameter-operator.md) for the
step-by-step guide and original-resolution screenshots.

The page has two tabs: **Parameters** and **Profiles**. Inspection and writing
are separate actions. Opening a parameter, loading a file, choosing a profile or
changing the aircraft being inspected never writes to PX4.

### Parameters

- refresh a live PX4 snapshot for one drone
- search and filter parameters
- use a scan-first list/table plus one consistent detail dialog across phone,
  tablet, and desktop widths
- choose List or collapsible Groups at every screen width; both use a
  virtualized scrolling surface, with matching rows revealed during search
- inspect current/default/min/max metadata when available
- display numeric values with PX4 decimal hints when available, otherwise use a
  trimmed operator-readable precision instead of raw full-float output
- explicitly edit a value, review its before/after difference and apply with
  readback verification
- open the exact official PX4 parameter-reference page anchor for that
  parameter
- export the current snapshot as a QGC-compatible `.params` file
- import a QGC `.params` file, diff it against the current snapshot, and apply
  the reviewed changes
- dispatch a single-drone `Reboot PX4` action through the normal tracked
  command path; the native action freshly confirms disarm and, when available,
  PX4 ON_GROUND detection immediately before reboot. Unknown/stale native
  state blocks, and force flags cannot bypass this guard
- show compact inline status notices for snapshot refresh, import, write,
  verification, and reboot tracking instead of burying feedback in toasts only

### Reviewed Fleet Application

- reuse the shared MDS fleet/cluster/selected-drone scope model
- a single-aircraft edit starts with its originating aircraft; wider fleet scope
  requires an explicit choice and never follows the online filter automatically
- dispatch one typed parameter patch to:
  - all drones
  - one Smart Swarm cluster
  - an explicit selected subset
- list unavailable targets and require deliberate exclusion followed by a new
  review; reconnects do not add targets to an already reviewed operation
- compare each target's actual current values and apply only the exact reviewed
  differences, not unchanged entries from the source file/profile
- retain per-aircraft/per-parameter apply and readback outcomes in a recoverable
  GCS receipt, independently of subsequent snapshot refresh
- prefer saved profile bundles for repeatable fleet baselines; keep manual
  single-parameter entry for one-off overrides only

### Profiles

- browse repo-backed PX4 parameter profiles from `resources/px4_param_profiles/`
- review entry count, scope guidance, tags, and per-entry target values
- export a selected profile as typed MDS JSON for automation or repo reuse
- preview a saved profile against the currently selected drone snapshot
- prepare the selected profile for the same target/difference review as manual
  edits and imported files
- use this workspace as the operator-facing home for repeatable fleet baselines
  and keep all parameter mutations on this single typed, reviewed path

## Read, Review, Apply And Recover

1. Choose the aircraft and refresh its values. The identity strip distinguishes
   connection, snapshot age and write eligibility; a cached snapshot is not a
   continuously live stream.
2. Find a parameter by name/group or select a saved profile. Inspect details,
   then explicitly edit. Importing a QGC file parses and compares; it does not
   submit a parameter write.
3. Prepare the review. Check the exact aircraft identities, every proposed
   current → desired value, unavailable/missing entries and source information.
   All differences remain accessible, even for large files/fleets.
4. Confirm **Apply & verify** once. Targets, source and expected current values
   are fixed by the review. Native execution rechecks its expected values and
   configured mutation policy. A relevant conflict requires a refreshed review.
5. Observe the receipt. **Verified**, **Written—not verified**, **Failed**,
   **Skipped** and **Outcome unknown** have different meanings. A successful HTTP
   response alone does not establish readback or reboot activation.
6. After a lost response, use receipt lookup. Do not submit a new operation to
   discover whether the previous one ran. The same idempotency identity retrieves
   the original receipt; an uncertain native operation is not replayed.

Aircraft/component/snapshot identity stays attached to observations and drafts.
Switching aircraft or receiving a late read response cannot retarget a prepared
write. Refresh preserves deliberate edits and does not replace an important
write outcome with a generic “snapshot ready” message.

Fleet parameter changes are not atomic transactions. Partial results remain
visible. A restore is a separately reviewed operation against actual current
values, not an automatic or guaranteed rollback. No automatic disarm, reboot or
flight-mode change is part of profile application.

Float comparison follows the actual IEEE-754 binary32 parameter transport:
ordinary decimal representation rounding is accepted, but a different wire value
is never called verified. Overflow and nonzero values that underflow to zero are
rejected before writing. The legacy `PX4_PARAMETER_FLOAT_VERIFY_TOLERANCE`
attribute is deprecated and no longer widens verification or expected-value
checks; a global absolute epsilon could hide significant differences in small
gains. Review, readback and restore checks use the same typed comparison.

## Metadata Source Rules

MDS does not hardcode parameter metadata to one firmware snapshot.

- live single-parameter reads/writes come from the drone through MAVSDK param
  APIs
- bulk snapshot refresh prefers MAVSDK bulk listing and falls back to the local
  MAVLink parameter protocol on the routed `14569` endpoint when the runtime
  does not implement MAVSDK `GetAllParams`
- vehicle/component-information fields exposed through MAVSDK take precedence
  for float-parameter hints; their confirmed field authority is recorded
- a generated PX4 parameter catalog (`parameters.json`) supplies additional
  reference labels, ranges, reboot hints and enum choices across types. A local
  file alone does not prove a match to the connected firmware, so its fields
  do not silently become write constraints
- official docs links are generated from the configured docs version plus the
  parameter anchor, for example:
  - `https://docs.px4.io/main/en/advanced_config/parameter_reference.html#GF_MAX_HOR_DIST`
- when neither vehicle-served metadata nor a matching local catalog is
  available, MDS can optionally fetch the official PX4 parameter-reference page,
  parse it into a read-only local cache, and use that as operator reference
  metadata

If PX4 does not provide a metadata field, MDS leaves it empty instead of
inventing one. Reference-only catalog/documentation fields do not become native
authorization for a range, default or enum. Values, metadata origin and confirmed
metadata authority are separate evidence.

### Recommended Source Order

For a production-grade fleet, the intended metadata source order is:

1. live parameter values from the vehicle
2. vehicle-served PX4 parameter metadata if the firmware exposes it through the
   MAVLink Component Metadata / MAVLink FTP path
3. a local generated PX4 catalog available on the companion/runtime host
   (`parameters.json`) for SITL or tightly managed embedded deployments
4. MAVSDK component-information float hints as a weaker fallback
5. cached official PX4 docs metadata for operator reference only
6. official PX4 docs links for operator reference only

The important rule is that online docs should not become the authority for
runtime parameter semantics. They are useful as a human-readable reference and
can be cached for convenience, but the authoritative machine-readable metadata
should come from the connected PX4 firmware or its shipped metadata bundle.

### Online Docs Cache Fallback

The official PX4 docs cache is a bounded fallback for hardware that returns live
parameter values but no rich metadata. It is useful for labels, groups,
defaults, units, reboot hints, and descriptions when the firmware is close to
the configured PX4 docs version.

It is not a replacement for firmware-matched metadata. Custom PX4 builds should
prefer either vehicle-served Component Metadata or the generated build
`parameters.json` from that exact firmware build.

Configuration:

- `MDS_PX4_PARAMETER_METADATA_CATALOG_PATHS`: comma-separated paths to local
  PX4 `parameters.json` files; this takes priority over the online docs cache
- `MDS_PX4_PARAMETER_ONLINE_DOCS_METADATA_ENABLED`: enables the online fallback
  when no local catalog is found; default `true`
- `MDS_PX4_PARAMETER_METADATA_CACHE_DIR`: local cache directory; default
  `~/.cache/mds/px4-param-docs`
- `MDS_PX4_PARAMETER_METADATA_CACHE_TTL_DAYS`: fresh-cache window; default `14`
- `MDS_PX4_PARAMETER_METADATA_FETCH_TIMEOUT_SEC`: fetch timeout; default `2.5`
- `MDS_PX4_PARAMETER_METADATA_CACHE_MAX_ENTRIES`: maximum retained docs-cache
  files; default `4`

### Caching Guidance

- cache static parameter metadata by firmware identity or metadata CRC, not by
  parameter name alone
- do not refetch static metadata on every snapshot refresh; only live values
  need frequent reads
- treat metadata as effectively invariant for one boot / firmware build unless
  the vehicle advertises a changed metadata file or firmware version
- keep online docs caching optional and read-only; stale docs must not block
  parameter inspection or mutation
- prune stale online docs cache files so old PX4 releases do not accumulate or
  silently override the configured docs version

## Safety Policy

- writes are blocked while the target drone is armed when
  `PX4_PARAMETER_MUTATION_REQUIRE_DISARMED` is enabled
- the native operation confirms the configured disarmed requirement from a
  bounded live PX4 state sample under its operation lock; a cached initial false
  or missing state is not confirmed disarm
- read-only browsing does not acquire new GPS, position or flight-readiness
  gates; full metadata is not required simply to inspect actual values
- single writes and batch writes both default to readback verification
- the reviewed multidrone field profile uses `COM_OF_LOSS_T=1.0` with
  `COM_OBL_RC_ACT=3` (RTL): if the companion stops producing Offboard
  setpoints, PX4 starts the configured RTL response after one second instead of
  remaining in Offboard for the former 20-second loss window
- never assume a repo profile is already active on an aircraft; while grounded
  and disarmed, snapshot and diff each vehicle, review firmware-matched PX4
  metadata, apply deliberately, and verify the readback before flight
- `COM_RCL_EXCEPT`, `COM_RC_OVERRIDE`, `COM_ARM_WO_GPS`, and the Offboard-loss
  pair are operational policy, not generic tuning values. Review their actual
  values with the field operator; do not silently apply or relax them to make a
  readiness error disappear
- the multidrone profile's `COM_RCL_EXCEPT=7` intentionally exempts Mission,
  Hold, and Offboard from the RC-loss failsafe. That may fit an autonomous
  fleet, but it is not a universal first-flight policy: obtain explicit
  operator acceptance and review RTL path separation before applying the whole
  profile. For the two-aircraft field check, prefer a targeted, verified
  Offboard-loss edit if that is the only approved difference.

## Operator Notes

- use **Parameters** for inspection, deliberate edits and reviewed application
- use `Profiles` to review approved fleet baselines before applying them
- use the review's aircraft selection for deliberate fleet/cluster/subset scope
- tap or click a parameter row/card to open the detail dialog; keep the main
  list/table for scanning, not for reading every metadata field inline
- on compact/touch layouts, treat PX4 groups as the primary browsing surface
  and keep inline rows minimal: name, current value, and a few safety/reference
  icons
- touch devices in browser “desktop mode” still stay on the compact card +
  dialog workflow to avoid forcing a cramped pseudo-desktop inspector onto a
  phone
- refresh a snapshot before making decisions from stale values
- distinguish **reboot-sensitive** metadata from an actual changed setting
  awaiting reboot; never infer that every parameter carrying the flag was edited
- reboot remains a separately reviewed tracked command; reconnect and fresh
  observations, not command acceptance, establish its follow-up state
- keep repeatable fleet policies in repo-backed profiles instead of relying on
  ad hoc CSVs or one-off manual batch entry
- profile creation/edit/save-new remains repo-managed; the browser is
  currently for review, diff, apply, export, and tracked runtime operations

## Storage Layout

- live fleet config remains in root `config*.json` / `swarm*.json`
- reviewed PX4 parameter profiles live in `resources/px4_param_profiles/`
- `mds_multidrone_field_baseline.json` is the reviewed multidrone field profile
  with diff/readback/audit semantics
- generated mission outputs belong under `shapes/` or `shapes_sitl/`, not in
  the PX4 profile library

See [Repo Asset Layout](guides/repo-asset-layout.md) for the full storage
doctrine.

## Validation And Deployment

Use the existing `tools/validate_px4_params_runtime.py` drill only against an
isolated SITL GCS. It checks review/receipt identity, readback, idempotent receipt
replay and explicit baseline restoration. Restoration is attempted for every
target even if an earlier target fails; inability to verify restoration fails
the drill. This is not a real-aircraft tuning or flight-acceptance procedure.

The dashboard talks only to GCS. Native companion updates are required for
expected-value checks and native replay protection; a new portal build alone
does not prove that connected boards run those contracts. Keep the existing
MCP read-only boundary: this UI work does not enable parameter-write tools.
Review-by-ID and browser request-key lookup remain dashboard-scoped; the
existing patch-job ID read tool retrieves operation evidence without replay.

### Receipt Storage And Limits

GCS receipts use a host-local `px4-parameters.sqlite3` journal under the existing
`MDS_GCS_COMMAND_STATE_DIR`. The runtime/deployment binding keeps real and
simulated reviews separate. `MDS_PX4_PARAMETER_STATE_MAX_BYTES` defaults to 64 MiB;
new operations reserve space before acceptance. Existing receipts remain
readable if capacity is reached. A restart fences interrupted work rather than
automatically sending it again.

Prepared reviews have a configurable operator window:
`MDS_PX4_PARAMETER_REVIEW_MAX_AGE_SEC` defaults to 300 seconds after preparation.
This is separate from snapshot display freshness. Native expected-value checks
still run immediately before each reviewed write.

Each companion keeps native operation receipts under
`runtime_data/px4_params/native-<identity-hash>.sqlite3` by default. Overrides:

- `MDS_PX4_PARAMETER_OPERATION_STATE_DIR`: host-local receipt directory.
- `MDS_PX4_PARAMETER_OPERATION_MAX_RECORDS`: default 4,096 operation identities.
- `MDS_PX4_PARAMETER_OPERATION_MAX_BYTES`: default 64 MiB main-database budget.

Byte/record admission limits fail closed before a new write; existing operation
lookups remain available. Keep free disk headroom for SQLite transaction files.
Receipts are not automatically evicted or expired: deleting a journal removes
its replay protection and is not a routine way to dismiss an operation. Resolve
capacity through deliberate maintenance while grounded; preserve the journal
and its audit evidence when relocating/expanding storage.

## Deferred Follow-Up

- optional firmware/build identity reporting only after there is one clean
  vehicle-served source for PX4 version data; do not invent or hardcode it in
  the page
- hardware-grade metadata discovery and caching via PX4 Component Metadata /
  MAVLink FTP, keyed by firmware identity or metadata CRC instead of relying on
  local build artifacts alone
- advanced SITL drills beyond the validated single-drone plus two-drone
  snapshot/apply/restore gate

# PX4 parameter workspace modernization

Status: implemented; source, targeted safety/API checks, built UI and isolated
two-aircraft parameter workflow validated. This is not a flight clearance or a
validated pinned-image release.

## Accepted scope

Replace the separate Single/Batch/Profile UI workflows with two operator tabs,
**Parameters** and **Profiles**, backed by one identity-bound review and apply
pipeline. Keep the existing dashboard → GCS → vehicle-local PX4 ownership.
Activity is a compact recoverable receipt panel, not another dashboard.

The default surface contains an aircraft identity/read-state strip, search,
group/filter controls and a scan-first parameter browser. An explicit inspector
and edit action expose exact current/proposed values, units, metadata and source
quality. Desktop uses the available width; phone/tablet use accessible sheets
without a tall permanent fleet/status sidebar. Technical parameter names remain
visible because they identify the actual setting.

Manual edits, QGC imports and saved profiles all follow:

`Inspect → prepare exact changes → review targets/differences → apply/readback → results`

## Required correctness work

1. Bind observations and drafts to aircraft/component/snapshot identity. Reject
   superseded responses and preserve deliberate draft values through refresh.
2. Use complete finite numeric parsing, correct optional decimal metadata and
   shared display helpers. Reject duplicates and unsupported component targeting.
3. Review every changed entry, not a truncated sample. Freeze target membership,
   source identity and expected current values. Do not silently skip offline
   aircraft or write unchanged/unreviewed import rows.
4. Persist accepted job identity and idempotency before mutation. Perform bounded
   background work outside the API event loop; retain native phase evidence and
   reconcile unknown outcomes without automatic replay.
5. Distinguish written, verified, mismatched, rejected and unknown results.
   Snapshot refresh failure must not erase an already known write/readback.
6. Keep documentation fallback metadata advisory and its provenance explicit.
   Reboot-sensitive metadata is not evidence of a pending reboot or flight safety.
7. Enforce the configured native mutation policy using actual state evidence;
   missing telemetry is never confirmed disarm. Do not add GPS/preflight gates to
   read-only inspection or change aircraft tuning to make this page work.

Fleet writes are not atomic MAVLink transactions. Any restore is separately
reviewed against actual current values, never advertised as guaranteed rollback.
Profiles remain repo-managed; this phase does not add browser profile authoring
or callable MCP parameter mutation tools.

## Slices and acceptance

1. Shared native types, validation, metadata and operation preconditions.
2. GCS immutable reviews, durable receipts, bounded execution and lookup.
3. Flat Parameters browser, accessible inspector and draft/review/results state.
4. Profiles/import/export/fleet integration and retirement of duplicate paths.
5. Targeted model/service/API/UI regressions, responsive browser checks and an
   isolated SITL snapshot/apply/readback/restore drill with failure-safe cleanup.
6. Update guides, APIs, MCP read contracts and generated indexes, then publish
   reviewed generic changes and integrate the private deployment without fleet
   configuration changes.

All builds and tests run on the designated remote validation host. Development
and SITL services remain isolated from production. Deployment requires aircraft
to be off or grounded/disarmed with no test running. Keep a rollback artifact,
archive evidence and remove only owned temporary workspaces after resolving
dependency symlinks and running-process working directories.

## Validation and handoff

- 436 targeted Python checks passed across native values/policy/receipts,
  HTTP/GCS contracts, imports, reboot safety and agent/environment tooling.
- The complete dashboard suite passed: 168 suites / 1,265 tests. Final compact
  review changes also passed the four-suite / 43-test focused gate.
- The release dashboard compiled successfully on the designated validation
  host. Six built-browser cases cover 1440/900/390 widths in light/dark themes,
  2,049 parameters, frozen targets, a lost apply response recovered by GET-only
  lookup, profiles and a 1,200-row import with the last difference accessible.
- Two isolated PX4 SITL instances passed snapshot → single/fleet reviewed
  write → targeted readback, same-key receipt replay and stale-review rejection.
  Both original values were independently restored and verified. No flight or
  real-aircraft parameter command was sent.
- A native reboot gap found during review was fixed at the action boundary:
  fresh disarm evidence is required, plus ON_GROUND when available. Missing,
  stale or unsafe evidence blocks even direct/force invocations.
- The operator guide and original-resolution screenshots use synthetic aircraft.
  API documentation, non-callable tool candidates, public docs search and the
  existing read-only MCP receipt contract are aligned. No parameter-write tool
  was enabled.

The SITL evidence used the existing lab image with an explicit current-source
overlay and startup Git sync disabled. A clean pinned-image rebuild/export is
still required for distribution and is deferred for disk headroom. Do not call
this a refreshed image. At the next aircraft power-on, verify companion source
revisions and identities before using new native write/reboot contracts; a new
portal alone cannot establish board software parity.

See the [illustrated workflow](../guides/px4-parameter-operator.md). Raw runtime
logs and deployment reports stay in private host evidence; only a whitelisted
[SITL summary](../assets/px4-parameters/sitl-validation.json) is public.

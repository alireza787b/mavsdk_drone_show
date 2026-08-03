# Field Launch Readiness Release Gate

**Date:** 2026-08-03  
**Branch:** `incident/field-launch-readiness-20260802`  
**Status:** P0 gates and the bounded fresh-SITL acceptance pass are complete; release promotion and props-off field retest remain
**Related evidence:** [2026-08-02 field incident](2026-08-02-field-launch-readiness-incident.md)

This file is the finite completion contract for the incident checkpoint. It
prevents both unsafe early promotion and an open-ended perfection loop.

## Priority policy

- **P0 — release blocker:** can arm or move unexpectedly, prevent a recovery
  command, lose/contradict command truth, corrupt control of an active mission,
  or materially mislead the operator about current execution.
- **P1 — scheduled hardening:** important reliability or maintainability work
  with a safe documented current boundary. It does not expand this checkpoint
  unless validation proves it is also P0.
- **P2 — product improvement:** performance, scale, cleanup, or polish that is
  useful but not required for the bounded client retest.

The implementation receives one P0 closure pass, one consolidated automated
validation pass, and one fresh SITL operator pass. New P1/P2 findings go to the
backlog with evidence and acceptance criteria instead of reopening the release.

## P0 release blockers

| Gate | Required result | State |
|---|---|---|
| Typed launch prepare/commit | command/target/payload-bound one-use authority; commit-time live armability; bounded synchronized trigger; exact lost-response retry cannot execute twice | Implemented; action/command owner suites passed |
| Truthful vehicle safety evidence | one connection-aware typed snapshot; stale/unknown data cannot authorize Take Off, Hold, or Ground Test | Implemented; 179-action-suite consolidation passed |
| Cooperative action termination | SIGTERM/SIGINT reaches bounded cleanup; a forced kill is reported as cleanup unconfirmed | Implemented; real SIGTERM/SIGINT subprocess tests passed |
| Durable generic command truth | HTTP 202 record, targets, events, deadline, idempotency, and callback authority survive GCS restart; uncertain mid-delivery is explicit | Implemented; 150-command/QuickScout consolidation passed |
| QuickScout active-mission integrity | target sets survive persistence regardless of lexical key order; mixed delivery keeps the slot; concurrent controls cannot overwrite; late reports do not rewrite terminal truth | Implemented; 150-command/QuickScout consolidation passed |
| Operator lifecycle UI | refresh preserves mission identity; terminal history is never the live primary card; dismissed failures do not reappear during the provider session | Implemented; all 119 dashboard suites / 667 tests passed |
| Recovery availability | LAND/RTL/HOLD/KILL retain an independent bounded dispatch lane; Hold accepts a freshly confirmed clear-of-ground vehicle during `TAKING_OFF`, `IN_AIR`, or `LANDING` without weakening strict Take Off completion; optional LED failures cannot redefine flight/recovery success | Implemented; owner suites and fresh QuickScout pause/abort passed |

Any row still marked in progress or failing its acceptance test blocks tagging,
private-repository promotion, and field handoff.

## Automated validation evidence

- The one full backend pass collected 2,558 tests: 2,548 passed, two skipped,
  and nine failed. Every failure was then isolated as a stale route/message
  expectation or a legacy fixture that bypassed application lifespan; no
  production fail-open change was required.
- The corrected owning files passed 219 tests. After the final typed-outcome
  and recovery-Hold changes, the combined command, journal, API, action,
  safety, and runtime-validator gate passed **453 tests with one skip**. This
  includes real-process `SIGTERM` and `SIGINT` cleanup cases.
- The complete dashboard run passed all 119 suites and 667 tests. Existing
  React 18 test-helper deprecation warnings remain P2 toolchain maintenance;
  they did not hide a test failure.
- Environment/reference, mission-catalog, Simurgh tool/docs-index generation,
  Python compilation, and diff-hygiene checks pass.
- The earlier 957 MiB host build was stopped after exhausting swap; that
  capacity result was superseded by a successful optimized production build
  on the 8 GiB validation VPS at 2026-08-03 06:23 UTC. The built main asset was
  `main.64d5e9cf.js` (SHA-256
  `1225d084e4717e36e113057bf0740e5542cd49c7bde53b0591481a9239690287`).

## Fresh SITL acceptance evidence

Validation used the isolated GCS at `127.0.0.1:5111`; the real production GCS
at port 5030 remained healthy and was not sent a command. Runtime git sync,
dependency sync, and the host startup override were enabled against the
private validation branch. The private candidate `97c340e1a` contains the same
shared runtime changes as official candidate `42bbc8f8`, while retaining the
reviewed customer overlay. The current custom SITL image was reused as the
bootstrap layer; the public stock image refresh remains deliberately deferred.

- `actions_core` passed once from 05:57:56 to 06:00:34 UTC. Evidence:
  `/root/mds-validation-evidence/20260803T055900Z/actions-core`. Fresh reset,
  Take Off, Hold, precision movement, a movement interrupted by Hold, RTL, and
  final reset all passed. The interrupted command closed as typed
  `cancelled`/`superseded`; cleanup did not rely on message substring matching.
  Final telemetry was idle, disarmed, ready, and approximately -0.024 m
  relative-home altitude.
- The first QuickScout pass exposed one real P0: at +6 m, PX4 could still
  report `TAKING_OFF`, while Hold reused the stricter `IN_AIR` predicate that
  belongs to Take Off terminal completion. Automatic failure cleanup passed.
  Evidence: `/root/mds-validation-evidence/20260803T060100Z/quickscout-runtime`.
  The fix introduced a separate fail-closed recovery predicate; it did not
  broaden Take Off completion or admit grounded, disarmed, stale, unknown, or
  sub-0.5 m state.
- The single post-fix QuickScout rerun passed from 06:17:59 to 06:20:09 UTC.
  Evidence: `/root/mds-validation-evidence/20260803T061759Z/quickscout-runtime`.
  A fresh node synced to `97c340e1a`, launched, reached `searching` and +6 m,
  completed Hold command `e615d952-72b8-4147-899f-448daea79846`, entered
  `holding`, completed abort/RTL command
  `6c51bb24-9326-4a58-ae65-9df0cd1b0ece`, and returned idle/disarmed/ready.
  Both commands reported one accepted and one typed `completed` execution;
  active commands and executing QuickScout missions were zero. The mandatory
  final reset recreated one clean ready node on the same candidate.

The fresh acceptance artifacts preserve tracker, telemetry, reset, and unified
runtime logs. The separately preserved parsed ULog that proved the earlier
false command-failure behavior predates the final candidate and is documented
in the incident checkpoint; it is regression evidence, not falsely attributed
to this acceptance run.

## Completed bounded validation sequence

The sequence below is complete. It was not expanded into another general
review: the one defect observed in QuickScout received focused automated
coverage and one scenario rerun, then the gate closed.

1. Run targeted tests for every P0 row, including process restart, transport
   loss, stale telemetry, real subprocess signals, QuickScout concurrency, and
   frontend refresh/dismissal.
2. Run the consolidated Python and dashboard suites, static compilation,
   generated-artifact checks, environment-registry checks, and diff hygiene.
3. Start a **new** production-style SITL GCS and a **new** SITL node from the
   release candidate. Do not reuse the five-day-old container as evidence.
4. Exercise readiness, Take Off, altitude/status reporting, precision movement,
   Hold eligibility, RTL/Land, lifecycle monitoring, QuickScout launch/control,
   duplicate submission, GCS restart reconciliation, node disconnect, and
   container removal/recreation.
5. Promote only after terminal state is unambiguous, the node is disarmed and
   landed, logs/ULog evidence is captured, and no P0 regression remains.

## Deliberately deferred after the client retest

These items remain visible but do not silently become claims of current
capability:

- **Large-fleet transport architecture (P1):** current direct bounded fan-out
  is suitable for the validated test profile, not proof of deterministic
  thousand-node launch timing. Acceptance requires a reproducible load/fault
  harness and likely hierarchical or staged distribution.
- **Mixed-version compatibility retirement (P1):** remove the temporary
  nodes-first optional envelope only after Fleet Ops proves every node is on
  the capability-bearing release and rollback has been rehearsed.
- **Node-process restart idempotency (P1):** the GCS journal is durable and
  never redispatches uncertain work after a GCS restart, while exact lost-HTTP-
  response retries are idempotent inside the current node process. Persist the
  node's bounded command replay ledger before claiming command replay safety
  across a companion-process or host restart.
- **Mission identity generation completion (P2):** migrate remaining numeric
  UI/runtime display constants when their owning modules are next changed.
- **Frontend toolchain replacement (P2):** replace Create React App in its own
  migration; do not mix that broad dependency change into flight readiness.
- **Public stock SITL image refresh (P2 for this checkpoint):** explicitly
  deferred by the project owner. The private validation path may use runtime
  git sync; public image provenance will be refreshed in the next phase.

## Promotion and field boundary

Promotion order is nodes first, capability/version convergence verified second,
GCS last. A new GCS must not be placed in front of old nodes that lack launch
preparation support. Production refresh may restart services and verify health,
but it must not send an arming or flight command to real aircraft.

Arnaude's retest begins props-off on one vehicle, then both vehicles only after
version, readiness, QGC arming report, telemetry freshness, and command history
all agree. The exact **Take Off** action must be used; Hover Demo and PX4 Hold
are separate operations.

# Field Launch Readiness Release Gate

**Date:** 2026-08-03  
**Branch:** `incident/field-launch-readiness-20260802`  
**Status:** P0 implementation and consolidated automated validation complete; release build and fresh-SITL validation pending
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
| Recovery availability | LAND/RTL/HOLD/KILL retain an independent bounded dispatch lane and optional LED failures cannot redefine flight/recovery success | Implemented; action/command owner suites passed |

Any row still marked in progress or failing its acceptance test blocks tagging,
private-repository promotion, and field handoff.

## Automated validation evidence

- The one full backend pass collected 2,558 tests: 2,548 passed, two skipped,
  and nine failed. Every failure was then isolated as a stale route/message
  expectation or a legacy fixture that bypassed application lifespan; no
  production fail-open change was required.
- The corrected owning files passed 219 tests. The command/QuickScout
  consolidation passed 150 tests with one skip, and the action/safety
  consolidation passed 179 tests, including real-process `SIGTERM` and
  `SIGINT` cleanup cases.
- The complete dashboard run passed all 119 suites and 667 tests. Existing
  React 18 test-helper deprecation warnings remain P2 toolchain maintenance;
  they did not hide a test failure.
- Environment/reference, mission-catalog, Simurgh tool/docs-index generation,
  Python compilation, and diff-hygiene checks pass.
- The local production build was stopped after the 957 MiB validation host
  exhausted 2.5 GiB of swap. The same release build is a required gate on the
  8 GiB validation VPS; this is a host-capacity result, not a code failure.

## Bounded validation sequence

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

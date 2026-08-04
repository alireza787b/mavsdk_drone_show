# Field Node Sync Recovery and Props-Off Gate

**Date:** 2026-08-04

**Scope:** Catch-A-Drone two-node field deployment

**Status:** both nodes converged and the one-drone props-off admission check
completed safely; bounded lifecycle corrections are locally validated and final
integrated validation/release publication remain pending

**Prior gate:** [Field Launch Readiness Release Gate](2026-08-03-field-launch-readiness-release-gate.md)

This is the durable evidence record for the field activation problem observed
after `v5.5.115-field-launch-readiness`. It keeps deployment repair separate
from the later MDS vNext modernization work and from the independent landing-
quality investigation.

## Operator report

Arnaude powered both aircraft on indoors with propellers removed. The dashboard
showed both nodes as not synchronized and displayed boot errors. This report was
correct, not a UI false positive.

No arming, flight, mission, parameter-write, or recovery command was sent while
investigating this state.

## Live evidence before repair

Read-only evidence was collected from the authenticated production GCS and
direct read-only node APIs. The temporary GCS diagnostic token was revoked
after collection.

- Production GCS:
  - private checkout `/root/catchadrone_gcs`
  - branch `main`, clean
  - commit `2d6260d9069b3a77d5d6eaf324d8d0cb0213ddc7`
  - real mode, dashboard/API auth enabled, Simurgh action circuit breaker on
- Drone 1:
  - hardware ID 1, position ID 1, NetBird IP `100.82.72.33`
  - live heartbeat
  - branch `main`, clean, commit
    `2f8cefd556f9bd7adb47c6f5af020be41f0e717e`
  - 305 commits behind the GCS
- Drone 2:
  - hardware ID 2, position ID 2, NetBird IP `100.82.47.7`
  - live heartbeat
  - branch `main`, clean, same old commit `2f8cefd556f9bd7adb47c6f5af020be41f0e717e`
  - 305 commits behind the GCS
- Both boot records reported:
  - phase/status `error`
  - `POST-SYNC-VALIDATION: Pulled runtime changes failed validation and were rolled back to the previous commit`
  - Drone 1 rollback report: 2026-08-04 10:07:14 UTC
  - Drone 2 rollback report: 2026-08-04 10:10:06 UTC
- Git credentials, disk headroom, Smart Wi-Fi Manager, MAVLink Anywhere, and
  node heartbeats were healthy. The failure was after a successful fetch/reset,
  not a connectivity or repository-authentication failure.
- The GCS durable command tracker contained zero active and zero recent commands
  for this freshly restarted production process.

Both vehicles were disarmed, but Take Off was not eligible indoors. Fresh
telemetry reported no 3D GPS fix and no PX4 home position. Those are legitimate
launch blockers; Bench/Ground Test connectivity does not override them.

## Root cause 1: target deletions misclassified as invalid files

`tools/update_repo_ssh.sh` enumerated every changed path between the old and new
revision and syntax-checked any path ending in `.py` or `.sh`. It did not
distinguish a deleted path from a file present in the target revision.

The old-node-to-current-private delta intentionally deletes these seven retired
client-demo Python tools:

- `tools/build_catchadrone_phase1a_demo_01_assets.py`
- `tools/build_catchadrone_phase1a_demo_assets.py`
- `tools/fetch_catchadrone_demo_ulogs.py`
- `tools/package_catchadrone_phase1a_demo_01.py`
- `tools/package_catchadrone_phase1a_demo_02.py`
- `tools/run_catchadrone_phase1a_demo_01.py`
- `tools/validate_catchadrone_phase1a_demo.py`

After reset, those files correctly no longer existed. The validator attempted
to read each one, classified the resulting missing-file errors as seven Python
syntax failures, and invoked the designed rollback. Both nodes therefore stayed
healthy but on their old runtime and could not exercise the new launch-command
protocol.

## Correction 1: target-present, NUL-safe validation

Post-sync validation now reads a NUL-delimited Git path stream and excludes
deletions. It continues to validate additions, copies, modifications, renames,
type changes, unresolved paths, and rewrites that exist in the target revision.
Rollback behavior for an actually invalid target shell file, Python file, or
rendered systemd unit is unchanged.

The existing self-reexecution boundary is important for recovery: after an old
node resets to the target revision, it immediately reexecutes the updated sync
script before post-sync validation. Therefore the currently deployed old
updater can adopt this correction in the same invocation; no ad hoc manual Git
reset or validator bypass is required.

## Root cause 2: no reverse bridge for the new command envelope

After the validator correction reached the GCS, the first guarded Fleet Ops
apply still made no progress. The tracked `UPDATE_CODE` transaction
`219ead0a-26f0-45b8-af4a-0b027434f39d` received HTTP 422 from both nodes before
either update handler ran.

The current GCS correctly binds every command to `target_hw_id` and an opaque
`command_report_capability`. The old `2f8cefd5` node request model uses
Pydantic `extra="forbid"` and predates exactly those two fields. FastAPI
therefore rejected the new envelope at schema validation. The existing
forward-compatibility work let a new node understand an older GCS, but there
was no bounded reverse bootstrap for a new GCS to update an older node. This
was a rolling-upgrade design gap, not an intermittent network or PX4 failure.

There was a second truth problem in the same workflow. Fleet Ops already
verified the actual branch, exact commit, clean worktree, and zero ahead/behind
drift after update, but that result was not written to the generic command
tracker. An old node cannot authenticate a new-style completion callback, and
its coordinator restart can interrupt even a current callback. The maintenance
card could therefore remain active and later time out despite successful Git
convergence.

## Correction 2: bounded bootstrap and postcondition-owned completion

The reverse bridge is explicit and fail-closed:

1. only the typed Fleet Ops Git Sync authority can enable it;
2. only mission `UPDATE_CODE` is eligible;
3. the first request always uses the current target-bound envelope;
4. retry is considered only for HTTP 422 containing exactly the two top-level
   Pydantic extra-field errors for `target_hw_id` and
   `command_report_capability`, with no additional validation error;
5. before dropping those unsupported fields, the GCS reads the same host's
   `/api/v1/swarm/state` and requires its typed hardware ID to match the exact
   intended target;
6. it retries once with the same command ID and functional payload, removing
   only the two unsupported envelope fields; and
7. every other status, identity problem, timeout, malformed response, mission,
   or second-attempt failure follows the normal strict transport result with no
   third request.

No raw 422 body is logged or returned because Pydantic may echo the opaque
callback capability inside validation input. Flight, recovery, parameter, and
ordinary operator commands remain current-envelope-only.

`UPDATE_CODE` now has an explicit `fleet_git_postcondition` completion owner.
Transport ACKs remain transport evidence. Capability-authenticated node
callbacks are retained separately as diagnostic evidence and cannot win a
race against the verifier. Fleet Ops atomically records an exact hardware-ID
result set after checking branch, commit, clean worktree, and ahead/behind
state, producing completed, partial, or failed terminal truth. Its deadline is
derived from the dispatch, per-request, verification, and safety-buffer
budgets, rather than the former generic 60-second fallback.

This bridge is temporary by protocol capability, not by private or official
commit SHA. It can be removed only after supported physical, customer,
rollback, and stock-SITL artifacts all advertise the current command envelope
and legacy bridge use remains zero for a full supported release window.

## Concurrent origin-reference finding

Mission Config also produced a false “no drone position telemetry” error while
the fleet view showed Drone 2 with a 3D GPS fix. Two independent facts were
involved:

1. Mission Config passed the complete typed fleet response
   (`{telemetry, total_drones, ...}`) to a modal that indexed it as the inner
   per-hardware map. This made valid rows invisible to that modal.
2. Live read-only evidence showed Drone 2 had a fresh raw receiver fix with
   13–14 satellites, but `global_position_valid=false`, zero current global
   coordinates/absolute altitude, and `GPS fix present, waiting for valid PX4
   global position.` A raw 3D fix is not an estimator-approved current
   position and cannot safely define formation origin.

The corrected workflow uses normalized fleet telemetry for operator labels but
makes the GCS authoritative for both preview and persistence. The client sends
only hardware identity. The GCS resolves the configured slot, validates a
fresh disarmed `GLOBAL_POSITION_INT` sample and same-sample MSL altitude, reads
the trajectory start, computes the candidate, and repeats this atomically on
save. Raw GPS, PX4 home, local NED, relative altitude, and barometric display
altitude are never silent fallbacks.

The same slice fixes two latent truth hazards: changing drone selection can no
longer reuse or race an older preview, and a failed `PUT /api/v1/origin` no
longer closes the modal or marks origin ready. The unused second KML origin
modal and obsolete `BriefingExport` component were removed so Mission Config
has one origin owner. Position-deviation review now rejects unavailable,
invalid, or stale global samples through the same validator.

## Validation before deployment

- `bash -n tools/update_repo_ssh.sh`: passed.
- `tests/test_bootstrap_installers.py`: 107 passed with coverage disabled for
  this shell/integration-only owning suite.
- Git-sync Python/static suites: 22 passed.
- Focused post-sync validation cases cover:
  - invalid shell rejection and rollback;
  - invalid Python rejection;
  - intentional Python deletion acceptance;
  - renamed invalid Python path containing a newline, proving NUL-safe path
    handling;
  - no Python bytecode side effect;
  - invalid rendered service rejection.
- Exact old node commit `2f8cefd5` to official release commit `c62f254d`
  validation: passed with the corrected validator.
- Diff hygiene and Python tool compilation: passed.
- The exact old node request schema was reproduced with FastAPI/Pydantic:
  HTTP 422 contained only `extra_forbidden` for `target_hw_id` and
  `command_report_capability`.
- Fleet RPC coverage proves the current-first request, same-host typed identity
  check, one same-ID legacy retry, strict ACK correlation, deadline handling,
  no bridge on non-update missions, and no capability disclosure.
- Tracker coverage proves exact-target/capability atomic verification, all-
  success/all-failure/mixed outcomes, callback-before/after-verifier races,
  discrepancy reporting, idempotency, durable restart restoration, and
  response-model preservation.
- Combined focused correction suites: 171 passed and 1 intentionally skipped.
- Origin-reference and deviation coverage proves server-resolved identity/slot,
  read-only preview, atomic persistence, raw-3D/global-invalid rejection,
  stale/unavailable/armed/invalid-position rejection, in-flight deviation
  observation, and no persistence after failed validation.

## Live deployment and node convergence evidence

The validated correction was published first to official `main` at
`b037e446`, then cherry-picked to Catch-A-Drone private `main` as
`1ada356b2be2bb5cab2d596ddf9a693de68da3dc`. The private checkout was clean
before production deployment.

The canonical production restart exposed an independent launcher defect:
production mode exported `NODE_ENV=production` before dependency installation,
so a clean `npm ci` omitted the build-time `react-scripts` dependency and the
optimized dashboard build stopped after the old services had been terminated.
Production was recovered without changing runtime policy by installing the
locked dependency set with development/build dependencies included and rerunning
the documented real-mode production launcher. The optimized build completed,
the GCS and static dashboard returned healthy, real mode remained active,
authentication remained enabled, and the Simurgh action circuit breaker
remained on. The launcher correction is covered by the release described below.

One authenticated Fleet Ops preview and one apply targeted exactly hardware 1
and hardware 2 on private branch `main` at commit `1ada356b2`. The tracker was
created at 11:52:36.878 UTC. The operation card reached a failed terminal result
at 11:53:24.605 after its 45-second verification window, but the node boot
stream then recorded the complete deferred-restart lifecycle as successful:
hardware 1 at 11:54:18.831 and hardware 2 at 11:54:27.686. The slower target
therefore required approximately 110.8 seconds from tracker creation. This was
a verifier-window false negative, not an update rollback and not permission to
retry the update.

After restart, each node independently proved:

- healthy `/ping` and coherent hardware identity (`hw_id=1` and `hw_id=2`);
- branch `main`, exact commit `1ada356b2`, clean worktree, and zero commits
  ahead or behind;
- terminal Git-sync runtime status `success`; and
- disarmed, idle ground state with zero active GCS commands.

The real deployment therefore satisfied the convergence gate. One shared
policy now gives the verifier a 150-second default, accepts only finite
30–900-second deployment overrides, and derives the UPDATE_CODE tracker budget
from that same value. This covers the observed 110.8-second lifecycle plus
transport/poll margin without multiplying the deadline by fleet size.
Completion truth remains the exact hardware/branch/commit/clean/ahead-behind
postcondition; a longer wait cannot turn a wrong node or revision into success.

## Live props-off admission evidence

With both aircraft confirmed propeller-free, one exact Drone 1 **Take Off to
2 m** request was submitted with one idempotency key. Its durable command ID was
`36c57f67-9fe8-4bfd-b672-a943ccecbabb`.

The request reached one clean failed terminal result before dispatch:

- preparation blocked: 1 target;
- transport/execution ACKs: 0;
- expected executions: 0; and
- operator summary: launch not dispatched under the all-required policy because
  Drone 1 was not ready.

The typed blockers were unavailable PX4 armability, global position, home
position, and battery telemetry. After terminalization the GCS again reported
zero active commands and both nodes remained disarmed and idle. This proves the
correct fail-closed real-node admission, idempotency, tracking, reporting, and
cleanup behavior for the observed indoor state. It does not claim an airborne
or landing acceptance.

## ULog smoke and bounded limitation

The existing field ULogs remain Drone 1 IDs `103` and `104` and Drone 2 ID
`60`. After node convergence, a GCS-proxied derived-summary smoke request for
the approximately 45 MB Drone 1 log `103` reached HTTP 504 in only 5.902 seconds
with `ulog_summary_timeout` and the bare message `TimeoutError`. The configured
isolated-parser deadline was 90 seconds, so this was not evidence that the
large log exhausted its parser budget. The failure happened during bounded
node-local MAVSDK/PX4 ULog transport setup and was misclassified by a generic
`TimeoutError` handler.

The corrected contract gives MAVSDK server startup, MAVSDK RPC-channel setup,
and PX4 connection wait explicit typed stages. Transport setup failures are
retryable `ulog_transport_unavailable` or `ulog_transport_timeout`; only the
resource-bounded parser can return `ulog_summary_timeout`. The GCS preserves the
node's structured stage/detail while Simurgh renders concise text. No parser or
download timeout was made unbounded, and the request did not expose raw content
or leave a flight command active. A live retry belongs in the next props-off
window because both nodes are now powered down.

Deferred architecture note: a synchronous summary may include a node transfer
whose independent ceiling is longer than the GCS summary and Simurgh evidence
budgets. The clean future solution for guaranteed large-hardware-log completion
is an asynchronous summary job/cache with explicit progress and terminal
evidence, not a per-byte timeout guess. This mismatch did not cause the observed
5.902-second setup failure and is not expanded in this field checkpoint.

## Required node convergence gate

Before any command is tested, both nodes must independently prove all of the
following:

1. sync result is terminal `success`, not merely a live heartbeat;
2. branch and exact private target commit match the GCS;
3. coordinator restarted after the runtime update and `/ping` is healthy;
4. the new launch-preparation endpoint and response schema are present;
5. hardware ID, position ID, source IP, and callback identity agree;
6. expected MAVSDK process owns the configured gRPC port;
7. fresh telemetry and heartbeat agree on disarmed/ground state;
8. the GCS command tracker contains zero active commands.

If one node fails, keep that node excluded and do not weaken validation, edit
its worktree by hand, or suppress the dashboard warning.

## Bounded props-off acceptance

The first check uses one drone only and the exact **Take Off** action once.
Do not use Hover Demo, Hold, or repeated button clicks as substitutes or
retries.

With propellers removed and current indoor GPS/home blockers, a successful
airborne outcome would be false. Acceptable behavior is:

1. a current launch-preparation result identifies the explicit blocker;
2. no unsafe dispatch occurs when preparation is blocked; or, if PX4 receives
   the request after all live inputs become ready, PX4 rejects/no climb is
   reported truthfully;
3. the transaction reaches one concrete terminal result without operator
   retry-clicks;
4. QGroundControl, fresh telemetry, and logs agree that the vehicle is
   disarmed and on the ground;
5. GCS active command count returns to zero.

A props-off check proves routing, admission, idempotency, tracking, error
reporting, and cleanup on real hardware. It cannot prove climb, airborne Hold,
RTL, altitude tracking, or landing quality. Those require the later controlled
props-on flight gate.

## Landing-quality boundary

The reported rough last metre is not part of this sync/command incident and no
PX4 parameter was changed here. The matching August 1 ULogs are Drone 1 IDs
`103` and `104`, and Drone 2 ID `60`. Acceleration evidence supports one harder
Drone 1 touchdown: filtered peaks were approximately `2.70 g`, `1.28 g`, and
`1.55 g`, respectively. All three subsequently reached PX4 land detection and
normal two-second post-land disarm. Drone 1's second landing was the smoothest,
so the evidence does not support a repeatable fleet-wide landing defect.

Current defaults are `MPC_LAND_SPEED=0.7 m/s`, `MPC_LAND_CRWL=0.3 m/s`, and
`MPC_LAND_ALT3=1 m`. No downward range sensor was configured in any of the
three logs, so reliable crawl-rate behavior in the last metre cannot depend on
distance-to-bottom evidence. The current logger also omitted vertical
position/speed setpoints, range validity, and detailed land-detector topics;
descent-rate causality is therefore not proven.

The higher-priority finding is Drone 1 power health. Log `103` records low
battery warnings and failsafe before Land. Log `104` escalates through low,
critical, and emergency battery levels. Drone 2 log `60` contains no matching
battery warning. Resolve Drone 1 battery condition, calibration, and threshold
behavior before the next props-on flight. If a richer controlled log later
shows repeatably excessive descent, a one-drone `MPC_LAND_SPEED` trial from
`0.7` to `0.6 m/s` may be evaluated; it is not justified by the present data.

Arnaude must also identify the exact rough-landing workflow: standalone Land,
RTL, Drone Show/Swarm completion, or QuickScout. They do not all enter descent
through the same operator path.

## Release record

The final official commit/tag, private commit/tag, final production runtime
commit, integrated validation, and release URLs must be appended here before
this gate is marked complete. The node convergence, props-off command result,
and ULog identifiers are recorded above and must not be replaced by an
uncorrelated retry.

# Field Node Sync Recovery and Props-Off Gate

**Date:** 2026-08-04

**Scope:** Catch-A-Drone two-node field deployment

**Status:** updater correction reproduced and locally validated; production node convergence and props-off acceptance remain pending

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

## Root cause

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

## Systematic correction

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
PX4 parameter was changed here. Existing evidence shows native PX4 Land reached
land detection and normal two-second post-land disarm, but it does not measure
touchdown impact.

Current defaults are `MPC_LAND_SPEED=0.7 m/s`, `MPC_LAND_CRWL=0.3 m/s`, and
`MPC_LAND_ALT3=1 m`. PX4 uses the crawl rate only when finite distance-to-bottom
evidence is available. The leading hypothesis is missing/invalid downward range
near the ground, but raw ULog evidence must confirm it. First retrieve the
current ULogs after node convergence, then inspect vertical position/speed,
descent setpoints, distance-sensor validity, estimator range-aid state,
land-detector timing, thrust, and acceleration. Do not tune land-detector
thresholds or replace native PX4 Land as a speculative softness fix.

Arnaude must also identify the exact rough-landing workflow: standalone Land,
RTL, Drone Show/Swarm completion, or QuickScout. They do not all enter descent
through the same operator path.

## Release record

The final official commit/tag, private commit/tag, node sync timestamps,
runtime checks, props-off result, and any retrieved ULog identifiers must be
appended here before this gate is marked complete.

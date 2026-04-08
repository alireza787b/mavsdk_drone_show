# QuickScout Runtime Multi-Validation Follow-up

Date: 2026-04-08
Validated runtime head: `487819f0`

## Summary

QuickScout runtime is now validated on Hetzner SITL for both:

- `quickscout_runtime`
  - single-drone `last_known_point` plan, launch, hold, resume rejection,
    abort, cleanup
- `quickscout_multi_runtime`
  - two-drone `last_known_point` plan, launch, hold, resume rejection, abort,
    cleanup, and non-target idle verification

The earlier execution blocker turned out to be an operational stale-image issue:
fresh containers created with `MDS_SITL_GIT_SYNC=false` stayed on the older
baked image commit and kept the pre-fix QuickScout launch path. Fresh restaging
with `MDS_SITL_GIT_SYNC=true` moved the containers onto the live runtime repo
head and removed that blocker.

## What Was Verified

Single-drone runtime plan:

- artifact dir:
  - `/root/mavsdk_drone_show_quickscout_validator_sync/artifacts/sitl-validation/20260408T090527Z`
- result:
  - passed

Multi-drone runtime plan:

- artifact dir:
  - `/root/mavsdk_drone_show_quickscout_validator_sync/artifacts/sitl-validation/20260408T091224Z`
- result:
  - passed

Validated live behavior:

- GCS health reachable
- selected drones pass the live launch probe
- QuickScout mission package planning persists the intended target `pos_ids`
  and `hw_ids`
- launched target drones climb and enter `searching`
- non-target drones remain idle
- pause drives the operation into `holding`
- direct resume still returns the intended `replan_required` doctrine
- abort transitions to `return_commanded` / `aborted`
- fleet returns to disarmed idle
- active commands drain back to zero

## Important Findings

1. Fresh SITL restages are only meaningful if the container startup path is
   aligned with the code under test.

   - current public image still bakes an older repo commit than this runtime
     checkpoint
   - for unreleased QuickScout validation on Hetzner, `MDS_SITL_GIT_SYNC=true`
     is required

2. One first-run multi-drone launch anomaly was observed but did not reproduce
   on a fair rerun.

   - failed artifact:
     - `/root/mavsdk_drone_show_quickscout_validator_sync/artifacts/sitl-validation/20260408T090748Z`
   - symptom:
     - launch response reported only one accepted `hw_id`
   - outcome:
     - the same plan and code path passed on a clean rerun after a fresh GCS
       state reset

3. One later multi-drone failure was debug contamination, not a product defect.

   - failed artifact:
     - `/root/mavsdk_drone_show_quickscout_validator_sync/artifacts/sitl-validation/20260408T091050Z`
   - root cause:
     - out-of-band manual QuickScout debug launches left active commands in the
       GCS command tracker
     - drone-only resets recreated the fleet but did not clear that in-memory
       GCS command state
   - fix:
     - restart GCS before the next fair validator run

## Current Operational Rule

For QuickScout acceptance validation on unpublished runtime commits:

1. recreate the fleet
2. use `MDS_SITL_GIT_SYNC=true`
3. keep manual debug launches out of band from validator runs, or restart GCS
   before rerunning a plan
4. only treat a run as authoritative if the fleet reset and GCS state are both
   clean

## Next Recommended Slice

QuickScout runtime validation is strong enough now to checkpoint and continue.
The next practical QuickScout work is:

- broader QuickScout workspace / UI implementation slices
- evidence / camera workflow planning
- later promotion of QuickScout into heavier integrated operator gates once the
  surrounding subsystem matures further

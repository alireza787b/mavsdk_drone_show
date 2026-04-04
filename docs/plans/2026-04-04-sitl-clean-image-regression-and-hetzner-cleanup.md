# 2026-04-04 SITL Clean-Image Regression And Hetzner Cleanup

## Goal

Determine whether the stale follower telemetry problem on Hetzner was a real
runtime/code defect or an artifact of long-lived mixed SITL state, then lock in
the validated operator-regression workflow and clean the host afterward.

## What Happened

- the older Hetzner 3-drone fleet reproduced the stale-local-telemetry symptom
  on `drone-2`
  - `LocalMavlinkController` kept logging repeated timeout/reinitialize loops
  - `mavlink-routerd` itself stayed up
  - PX4 showed a receive backlog on its UDP side, so the failure was not proven
    to be inside the local controller alone
- those containers were running a mixed state
  - baked image commit: `4cfbae9`
  - runtime repo synced at boot: `d7922c82`
- a fresh image was rebuilt directly from current `main-candidate`
  - image tag: `mavsdk-drone-show-sitl:debug-d7922c82`
- a new clean 3-drone fleet was recreated from that image with:
  - `MDS_SITL_GIT_SYNC=false`
  - `MDS_SITL_REQUIREMENTS_SYNC=false`

## Result

The stale telemetry problem did not reproduce on the clean rebuilt-image fleet.

The full reusable operator-regression suite passed end to end on Hetzner:

- Drone Show
- Actions
- Smart Swarm
- Swarm Trajectory
- reset before and after suite

Suite summary:

- status: `passed`
- artifact dir: `/tmp/mds_sitl_suite_validation/clean-image-fullsuite`
- runtime image: `mavsdk-drone-show-sitl:debug-d7922c82`
- runtime repo head: `d7922c8219fa096756b64a5dd241949181345992`

## Conclusion

No controller rewrite is justified from this incident alone.

The strongest confirmed root cause is environment drift plus long-lived stale
container state:

- old baked image content
- newer repo synced at container boot
- long-lived SITL containers reused across many validation cycles

The validated deterministic mode is now:

- rebuild the image from the target commit
- recreate the fleet from that image
- run with `MDS_SITL_GIT_SYNC=false`
- run with `MDS_SITL_REQUIREMENTS_SYNC=false`

Use mutable latest-on-boot mode only for intentional rapid-debug workflows, not
for promotion-grade regression gates.

## Hetzner Cleanup

After the clean-image suite passed, the host was cleaned safely:

- removed obsolete image tags backed by old image `63ac4821b431`
  - `mavsdk-drone-show-sitl:4cfbae9`
  - `mavsdk-drone-show-sitl:v5`
- removed the unused old checkout:
  - `/root/mavsdk_drone_show_main_candidate_runtime_https`
- removed tiny obsolete temporary validation dirs:
  - `/tmp/mds_sitl_suite_validation/debug-d7922`
  - `/tmp/mds_sitl_suite_validation/live-d7922`

Disk space improved from about `3.8G` free to about `12G` free.

## Follow-Up

- keep using the reusable suite as the default all-mode regression gate
- document the pinned-image regression mode as the standard validated path
- only revisit deep `LocalMavlinkController` surgery if the stale-telemetry
  symptom reappears on a clean rebuilt-image fleet

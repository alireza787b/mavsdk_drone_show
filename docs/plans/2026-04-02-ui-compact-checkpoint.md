# 2026-04-02 UI Compact Checkpoint

## Scope

This checkpoint resumes from the recovered operator UI state on `7a5279e7` and applies the next requested compactness / clarity slice before the next desktop review.

## Commits

- `18eb57c8` `Compact mission slot status and cluster scope cues`
- `4cfbae9c` `Align swarm runtime scope labels`

`origin/main-candidate` now points to `4cfbae9c`.

## Implemented

### Cluster scope cues

- `ClusterScopeBar` now renders counts as a discrete badge instead of inline `(n)` suffix text.
- This applies to the reusable scope rail used across Dashboard, Mission Config, Swarm Design, and Command Control.

### Mission Config slot-state compaction

- Added `src/utilities/missionSlotStatus.js` to centralize slot-state interpretation.
- Replaced the verbose `Configured Slot / Heartbeat Slot / Auto-detected Slot` prose block with:
  - a compact state headline (`verified`, `pending`, `review`)
  - short source chips (`Cfg`, `HB`, `Auto`)
  - explicit accept actions only when a live source actually differs from mission config
- `auto_pos_id=0` is now treated as unavailable, not as a bogus `P0` value.
- Mission Config top-card spacing was tightened to reduce wasted vertical space on handheld layouts.

### Swarm graph guidance

- Kept the graph direction as leader -> follower.
- Updated the Swarm Design graph copy/legend to state that explicitly so operators do not misread the follow chain.
- Rationale: for command-and-control review, propagation from cluster root outward is the clearer topology than inverting the edge direction to mean “follows”.

### Runtime scope labels

- Smart Swarm runtime scope labels now use the compact operator style:
  - `Drone 3 · 1 drone`
  - `P1|H1 cluster · 3 drones`

## Hetzner Validation

Host: `203.0.113.10`

Runtime repo:
- `/root/mavsdk_drone_show_main_candidate_runtime_https`

Validated on Hetzner after pull to `4cfbae9c`:

- Targeted frontend tests passed:
  - `src/utilities/missionSlotStatus.test.js`
  - `src/utilities/swarmDesignUtils.test.js`
  - `src/utilities/swarmRuntimeUtils.test.js`
- Production frontend build passed:
  - main JS bundle served: `./static/js/main.c8c72e9b.js`
  - main CSS bundle served: `./static/css/main.13fac98c.css`
- Runtime health:
  - `GET /health` => `ok`
  - `GET /git-status` => GCS + drones `1,2,3` synced on `4cfbae9c`
  - `GET /api/telemetry` => `3/3` online, ready, disarmed
- Operator sync path used:
  - `POST /sync-repos`
  - result: `Sync verified: 3 of 3 drones now match GCS`

## Notes

- The active SITL fleet remains ready for browser review.
- `last_mission` on the drones shows `103` because the repo sync used the normal `UPDATE_CODE` mission path.
- A small CRA build warning remains about bundle size; it is advisory, not a build failure.

## Next Requested Phases

1. Refresh the SITL Docker image from current `main-candidate` on Hetzner.
2. Flatten/export/compress the new image and replace the older distributable artifact.
3. Upload the refreshed artifact to MEGA and update the download instructions/docs.
4. Continue the remaining operator audit on desktop:
   - Mission Config
   - Swarm Design
   - Drone Show
   - Swarm Trajectory
   - Logs
   - QuickScout remains explicitly deferred

## Deferred / Todo Backlog

- additional frontend polish after desktop review
- full end-to-end SITL rerun across Drone Show, Smart Swarm, Swarm Trajectory after the next UI slice
- further QuickScout implementation
- API audit / contract cleanup pass
- MCP-assisted workflows where useful
- automatic ULog download workflow
- onboard parameter editing for single-drone and batch operations
- broader frontend hygiene sweep for remaining hardcoded layout/color/token bypasses and dependency/lint/deprecation cleanup

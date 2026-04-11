# QuickScout Runtime Acceptance Closeout

Date: 2026-04-11
Commit: `ff519535`
Branch: `main-candidate`

## Summary

This checkpoint closes the active QuickScout runtime hardening slice and
revalidates the broader all-mode SITL acceptance gate on top of the cleaned
runtime/validator split.

The main runtime fixes were:

- QuickScout mission execution no longer treats MAVSDK mission-progress
  callbacks as the sole completion signal.
- upload/start/airborne/post-action waits are explicitly bounded.
- the shared mission-startup seam now bounds arm RPC calls instead of allowing
  an unbounded wait during degraded live conditions.
- QuickScout operator monitor identity keeps both slot and hardware context
  visible so the fleet-enrollment doctrine remains visible during live search
  operations.

## Why This Was Needed

The previous failing multi-drone QuickScout runtime gate was not a planner
problem. The real issues were:

- fresh containers were booting from the old baked image commit while the fix
  only existed in a local detached worktree
- QuickScout mission completion was still too dependent on progress callbacks
  from MAVSDK
- live arm and post-action waits were not bounded cleanly enough for degraded
  runtime conditions

The closeout work fixed the runtime semantics and then proved the clean
deployment path by validating only against synced Hetzner runtime/validator
repos on the same commit.

## Validation

Focused validation on Hetzner clean-sync clone:

- backend: `75 passed, 1 warning`
- frontend: `2 passed`
- production build: rerun on the clean-sync clone for release proof

Live SITL validation on Hetzner:

- `quickscout_multi_runtime`: passed
- full `operator_regression` suite: passed

Operator regression artifact:

- `/root/mavsdk_drone_show_main_candidate_clean_sync/artifacts/sitl-validation/20260411T061150Z`

The full all-mode operator regression that passed on `ff519535` included:

- Configuration
- Drone Show
- Actions
- Smart Swarm
- Swarm Trajectory
- QuickScout

## Operational Notes

- authoritative validation came from Hetzner because Linode root storage was
  pressure-bound during this slice
- the clean validation repo on Hetzner was recreated from scratch after the
  older worktree state became untrustworthy
- the live runtime repo may still contain generated Swarm Trajectory SITL
  outputs after successful runs; that is runtime-only state, not a source
  change

## Remaining Explicit Debt

- broader dashboard dependency modernization beyond the minimal clean-sync
  install needed for validation
- advanced QuickScout retask / fault-injection SITL drills
- future hardware-grade PX4 metadata caching from component metadata instead of
  relying on local SITL build catalogs where appropriate

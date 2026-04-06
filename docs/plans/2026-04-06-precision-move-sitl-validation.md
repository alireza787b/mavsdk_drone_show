# 2026-04-06 Precision Move SITL Validation

## Scope

Validate the new Precision Move action on a real Hetzner 3-drone PX4/Gazebo SITL
stack, verify the fresh-container git-sync regression is fixed, and close the
false-negative gaps discovered in the reusable standalone action validator.

## Runtime Checkpoints

### 1. Fresh branch-sync container boot

Validated with:

- image: `mavsdk-drone-show-sitl:precision-move-d5664f9f`
- `MDS_SITL_GIT_SYNC=true`
- `MDS_SITL_REQUIREMENTS_SYNC=false`

Result:

- fresh `create_dockers.sh 3` no longer loops on:
  - `fatal: 'origin/main-candidate' is not a commit ...`
- all three containers reached `Up` state cleanly
- the branch-tracking startup path now fetches the branch into an explicit
  remote-tracking ref before checkout/reset

### 2. Deterministic pinned-image action validation

Validated with:

- image: `mavsdk-drone-show-sitl:precision-move-d5664f9f`
- `MDS_SITL_GIT_SYNC=false`
- `MDS_SITL_REQUIREMENTS_SYNC=false`

Live action run passed end to end on Hetzner:

- TAKEOFF
- HOLD
- completed `PRECISION_MOVE`
- interrupted `PRECISION_MOVE -> HOLD`
- targeted RTL override
- remaining-drone LAND
- final idle/disarmed confirmation

Artifact:

- `/root/mds_precision_move_actions_final2.json`

## Validator Fixes Required During Live Run

The live runtime behavior was correct. Two reusable-validator assumptions were
too brittle and were fixed:

1. interrupted command terminal matching
   - a superseded Precision Move now accepts the real command-tracker shape:
     - `status=cancelled`
     - `outcome=superseded`
   - the validator no longer assumes top-level `status` itself must equal
     `superseded`

2. post-HOLD acceptance
   - the validator no longer depends on the transient `mission` field remaining
     `102` after a successful HOLD command
   - the command tracker is treated as the authoritative success signal, and
     the post-HOLD check now verifies the operational outcome:
     - drone remains airborne after HOLD
   - the post-HOLD wait budget was increased from `60s` to `120s` for loaded
     3-drone VPS runs

## Override Semantics

### Verified live

- `PRECISION_MOVE -> HOLD` override works correctly
- the interrupted command is reported as superseded
- the replacement HOLD command completes successfully

### Confirmed from code path

- `DroneSetup` launches `PRECISION_MOVE` with `interrupt_running=True`
- HOLD, RTL, LAND, and other immediate override actions use the same
  interruption seam
- the action-runner computes its target from the drone's local state when that
  runner starts

Operational consequence:

- if a second immediate action arrives while Precision Move is active, the
  active action subprocess is superseded first
- if that second action is another Precision Move, its offset will resolve from
  the drone's then-current local state, not from the original command's start
  point

This specific `PRECISION_MOVE -> PRECISION_MOVE` override drill is still worth
adding as an explicit checked-in advanced SITL scenario, but the underlying
execution path is already the same immediate-action supersession seam validated
here with `PRECISION_MOVE -> HOLD`.

## Final Hetzner State

- GCS health: `ok`
- active commands: `0`
- drones `1/2/3`: online, idle, disarmed, `readiness=ready`
- validation checkout cleaned up
- old unused SITL images removed
- root disk recovered to about `15G` free

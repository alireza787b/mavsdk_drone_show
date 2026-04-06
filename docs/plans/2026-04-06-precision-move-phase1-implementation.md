# 2026-04-06 Precision Move Phase 1 Implementation

## Scope

Implement the approved v1 `PRECISION_MOVE` action end to end without rewriting the broader mission pipeline:

- canonical action code `112`
- typed GCS/drone command contract
- drone-local offboard executor using local NED position + velocity feed-forward
- airborne-only, immediate-only execution
- multi-drone support where each target resolves the same requested move relative to its own current local state
- one dedicated dashboard dialog as the single operator confirmation surface

## What Landed

### Backend / Drone

- Added `Mission.PRECISION_MOVE = 112`.
- Added typed precision-move request models in `src/command_contract.py`:
  - frame: `body | ned`
  - translation payload
  - yaw modes
  - optional convergence controls
  - `px4_hold` end behavior
- Added precision-move timeout defaults and bounds in `src/params.py`.
- Extended the drone command contract, GCS submit path, and drone API validation to require:
  - `precision_move`
  - `trigger_time == 0`
  - armed / airborne action preconditions
- Added runtime payload persistence and mission routing in:
  - `src/drone_communicator.py`
  - `src/drone_setup.py`
  - `src/drone_api_server.py`
  - `gcs-server/command.py`
  - `gcs-server/command_timeout_policy.py`
- Added the offboard executor in `src/action_runners/precision_move.py`.
- Preserved the broader cleanup direction by keeping `actions.py` as a thin action-runner adapter instead of expanding legacy branching further.

### Dashboard / Frontend

- Added `DRONE_ACTION_TYPES.PRECISION_MOVE = 112`.
- Added a dedicated Precision Move action card in the Actions tab.
- Implemented a dedicated `PrecisionMoveDialog` instead of forcing operators through:
  - parameter dialog
  - then a second generic confirmation modal
- The dialog is now the single confirmation surface for this action and submits directly through the existing lifecycle tracking pipeline.
- Added explicit operator guidance in the dialog for:
  - immediate-only dispatch
  - airborne + local-position requirement
  - per-target relative interpretation
  - body vs NED frame selection
- Refined the dialog with two operator layers instead of one dense form:
  - quick-step nudge controls for common movement and yaw adjustments
  - exact numeric fields for advanced/manual edits
- Added a direct `Dispatch Hold` override inside the dialog so operators can interrupt an in-progress move without closing the precision-move surface first.

### SITL / Validation

- Extended the reusable standalone action validator to cover:
  - a completed `PRECISION_MOVE` verified through per-drone local-position telemetry
  - a second longer `PRECISION_MOVE` interrupted by `HOLD`
  - safe post-interrupt airborne hold confirmation
- Fixed fresh SITL container branch-tracking boots by fetching the target branch into an explicit remote-tracking ref before checkout/reset. Fresh `main-candidate` boots no longer depend on `origin/<branch>` existing implicitly after a branch-name fetch.

## Validation

### Local

- Focused backend/drone batch:
  - `255 passed, 1 skipped`
- This covered:
  - action-runner runtime
  - precision-move runner
  - command processing / command system
  - drone API HTTP
  - drone setup
  - timeout policy

### Hetzner

- Frontend targeted React suite:
  - `39 passed`
- Production build:
  - passed

## Important Notes

- Precision Move is intentionally **not schedulable** in v1.
- Precision Move is intentionally **not added to the per-drone critical-command card surface** in v1.
- The action currently uses the same command lifecycle tracking as other commands, but it does **not yet** have a dedicated execution-progress stream/report channel.
- Remote backend pytest was not re-run in the Hetzner scratch copy because that scratch environment did not have the Python test toolchain preinstalled. Backend proof for this slice remains the green focused local batch.

## Deferred Follow-Ups

- Audit and normalize the broader `DroneSetup` -> `actions.py` -> runner pipeline after precision move is stable.
- Add a dedicated execution-progress report channel for parameterized long-running actions if operators need live convergence telemetry.
- Decide later whether to expose precision move in `DroneCriticalCommands` or keep it only in the centralized Command Control flow.
- Audit and modernize the dashboard dependency stack:
  - `npm ci` on Hetzner still surfaces CRA-era deprecations
  - the dashboard dependency tree still reports known vulnerabilities

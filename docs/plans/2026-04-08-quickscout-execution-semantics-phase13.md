# QuickScout Execution Semantics Phase 13

Date: 2026-04-08  
Branch: `main-candidate`  
Checkpoint target: post-`d403f453`

## Goal

Make QuickScout mission state and control behavior operationally honest before
adding deeper live-runtime validation:

- stop presenting paused coverage packages as directly resumable
- expose operator-facing mission phase and control availability in one live status contract
- surface compact runtime notes in monitor mode so launch/control outcomes are recoverable

## What Changed

### Backend contract

- Added typed QuickScout mission phases:
  - `planning`
  - `ready_to_launch`
  - `launch_partial`
  - `searching`
  - `holding`
  - `return_commanded`
  - `completed`
  - `aborted`
- Added typed control effects:
  - `command_accepted`
  - `command_rejected`
  - `replan_required`
- Extended `MissionStatus` with:
  - `operation_phase`
  - `status_summary`
  - `recommended_operator_action`
  - `control_availability`
  - `launch_summary`
  - `last_command_summary`
- Extended `DroneSurveyState` with:
  - `status_note`
  - `last_update_at`

### Control semantics

- `pause` remains a real HOLD-backed control path.
- `abort` remains a real command path and now carries explicit effect/state-change metadata.
- `resume` no longer mutates GCS mission state or pretends FC-backed continuation exists.
  - It now returns a typed `replan_required` response.
  - Operator guidance explicitly directs follow-up planning from current state.

### Monitor/UI

- Mission stats now show the derived mission phase plus compact status/guidance text.
- Mission monitor sidebar now shows:
  - operator-facing phase
  - operational status summary
  - recommended next action
  - last control outcome
- Per-drone monitor cards now show compact runtime notes.
- Monitor action bar now prioritizes follow-up planning instead of a fake resume action.

## Validation

### Local

- `python3 -m pytest --no-cov -q tests/test_sar_schemas.py tests/test_sar_api.py tests/test_gcs_sar_routes.py`
- Result: `56 passed`

### Hetzner

- Backend:
  - `/root/mavsdk_drone_show_phase5_live/.venv/bin/python -m pytest --no-cov -q tests/test_sar_schemas.py tests/test_sar_api.py tests/test_gcs_sar_routes.py`
  - Result: `56 passed`
- Frontend:
  - `CI=true npm test -- --runInBand --watch=false src/components/sar/MissionActionBar.test.js src/components/sar/MissionMonitorSidebar.test.js src/components/sar/MissionStatsBar.test.js src/pages/QuickScoutPage.test.js src/utilities/quickScoutPlanningSignature.test.js src/utilities/quickScoutSearchGeometry.test.js`
  - Result: `6 suites passed`, `19 tests passed`
- Production build:
  - `npm run build`
  - Result: passed

## Operational Note

I intentionally did **not** claim a reusable QuickScout SITL validator in this
checkpoint. The live Hetzner fleet currently needs a fresh runtime restage
before any meaningful QuickScout mission drill, and the existing QuickScout
TODO remains valid until the next execution slice lands.

## Next Recommended Slice

Build the first targeted QuickScout live validation path:

- restage a fresh Hetzner runtime on the clean checkpoint
- run a minimal QuickScout launch / hold / abort drill
- only then decide whether QuickScout is mature enough for a checked-in
  reusable SITL validator

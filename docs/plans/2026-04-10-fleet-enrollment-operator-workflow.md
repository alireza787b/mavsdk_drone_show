# Fleet Enrollment Operator Workflow

Date: 2026-04-10
Baseline: `ba711fdb`
Checkpoint: `pending commit`
Status: implemented and validated

## Summary

This slice turns fleet enrollment into a first-class operator workflow instead
of a Mission Config side effect.

The main changes are:

- added a dedicated dashboard page at `/fleet-enrollment`
- added a same-hardware recovery action for reimaged / reprovisioned nodes
- retired the old `ReplaceDroneWizard`
- routed Mission Config replacement and pending-candidate review into the new
  enrollment page

## Backend

Canonical fleet-candidate routes now include:

- `POST /api/v1/fleet/candidates/{candidate_id}/recover`

The recovery contract is for the same physical drone / same `hw_id` case:

- preserve the existing fleet slot
- preserve the existing `pos_id`
- update network / transport details in place
- mark the candidate as accepted with resolution `recovered_existing`

This keeps the operational meanings separate:

- `accept`: brand-new fleet member
- `replace`: spare drone / new `hw_id` takes over an existing slot
- `recover`: same `hw_id`, new companion image or reprovisioned node resumes its
  existing slot

## Frontend

`Mission Config` no longer owns replacement logic directly.

It now links operators into the dedicated `Fleet Enrollment` page for:

- reviewing the active candidate queue
- opening a specific candidate
- starting a replacement flow for a configured slot

The new page provides:

- candidate list with search and state filtering
- summary counts
- candidate identity and conflict review
- action dialogs for accept / replace / recover / ignore / reject
- explicit `commit` control on mutating actions
- replacement banner when launched from Mission Config with a target slot

## Retired Surface

Removed:

- `app/dashboard/drone-dashboard/src/components/ReplaceDroneWizard.js`
- `app/dashboard/drone-dashboard/src/styles/ReplaceDroneWizard.css`

## Validation

Local:

- `python3 -m pytest tests/test_fleet_candidate_registry.py tests/test_gcs_fleet_candidates_routes.py tests/test_gcs_api_http.py::TestAPIV1Aliases::test_route_inventory_includes_current_core_surfaces -q`
  - `11 passed`

Hetzner clean sync:

- backend fleet-candidate batch
  - `11 passed`
- frontend Jest batch
  - `5 suites passed`
  - `42 tests passed`
- focused Fleet Enrollment page Jest rerun after warning cleanup
  - `1 suite passed`
  - `3 tests passed`
- production build
  - passed

## Notes

- Recovery still requires an explicit candidate announce; heartbeat alone does
  not implicitly authorize same-hardware recovery.
- This slice does not yet wire node bootstrap directly into canonical announce.
  That is the next phase.

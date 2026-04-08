# QuickScout Recovery Phase 3

Date: 2026-04-08
Repo baseline: `c9f305e9`
Status: complete, local and Hetzner validation green

## Goal

Add durable QuickScout recovery surfaces so operators and future UI flows can list persisted missions and reopen a combined workspace payload instead of assuming a single in-memory `missionId` still exists in the browser.

## What Changed

- added compact persisted mission catalog models in [sar/schemas.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/schemas.py)
- added a combined workspace-recovery response in [sar/schemas.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/schemas.py)
- added `list_operation_summaries(...)` and `get_workspace(...)` in [sar/service.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/service.py)
- added:
  - `GET /api/sar/missions`
  - `GET /api/sar/mission/{mission_id}/workspace`
  in [sar/routes.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/routes.py)
- added matching dashboard service hooks in [sarApiService.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/services/sarApiService.js):
  - `listMissions(...)`
  - `getMissionWorkspace(...)`
- expanded backend route coverage in [test_gcs_sar_routes.py](/tmp/mavsdk_drone_show_resume/tests/test_gcs_sar_routes.py)
- expanded frontend service coverage in [sarApiService.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/services/sarApiService.test.js)
- updated route inventory expectations in [test_api_route_inventory.py](/tmp/mavsdk_drone_show_resume/tests/test_api_route_inventory.py)

## Why This Slice Matters

QuickScout phase 2 made launch/control durable and tracked, but the frontend still only knew about the current mission through local React state. That meant the subsystem still had no clean operator recovery path after:

- browser refresh
- browser reconnect
- GCS restart
- future multi-mission UI work

This slice closes that backend/API gap first:

- the GCS can now enumerate persisted QuickScout missions
- one workspace call returns both the persisted mission package and the derived live status
- future UI work can reopen or recover a mission from durable state instead of rebuilding from local assumptions

## Validation

Focused local validation:

```bash
python3 -m pytest --no-cov -q \
  tests/test_sar_schemas.py \
  tests/test_sar_coverage_planner.py \
  tests/test_sar_api.py \
  tests/test_gcs_sar_routes.py \
  tests/test_sar_store.py \
  tests/test_gcs_command_routes.py \
  tests/test_api_route_inventory.py
```

Result:

- `74 passed`

Focused Hetzner validation on a clean synced checkout:

```bash
.venv/bin/python -m pytest --no-cov -q \
  tests/test_sar_schemas.py \
  tests/test_sar_coverage_planner.py \
  tests/test_sar_api.py \
  tests/test_gcs_sar_routes.py \
  tests/test_sar_store.py \
  tests/test_gcs_command_routes.py \
  tests/test_api_route_inventory.py
```

Result:

- `74 passed`

Focused Hetzner frontend service validation:

```bash
cd app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watch=false src/services/sarApiService.test.js
```

Result:

- `1` suite passed
- `6` tests passed

## Important Notes

- The new recovery endpoints are additive; they do not replace existing `plan`, `launch`, `status`, `pause`, `resume`, `abort`, or POI routes.
- The new workspace response is designed as the backend handoff for the later QuickScout workspace/UI redesign, not as a final end-user workflow by itself.
- Hetzner `npm ci` still reports deprecated packages and audit vulnerabilities in the dashboard dependency stack. That is real maintenance debt, but it is already tracked separately in [TODO_deferred.md](/tmp/mavsdk_drone_show_resume/docs/TODO_deferred.md) and was not introduced by this slice.

## Remaining Debt After This Slice

- QuickScout page/workspace still needs to consume the new mission catalog/workspace APIs.
- QuickScout UI still assumes a simple Plan/Monitor page instead of a staged search-operations workspace.
- QuickScout SITL validator/template is still deferred until the mission workflow stabilizes.

## Recommended Next Slice

QuickScout Phase 4 should start the actual workspace redesign:

- replace the single `missionId` page assumption with durable mission reopen/recover behavior
- split planning vs monitoring into clearer staged operations
- expose mission catalog / reopen actions in the frontend
- reuse the newly added workspace payload instead of stitching recovery state together ad hoc

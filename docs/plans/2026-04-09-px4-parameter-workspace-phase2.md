# PX4 Parameter Workspace Phase 2

Date: 2026-04-09
Status: Completed checkpoint
Commit target: `main-candidate`

## Scope Closed

This slice finishes the first operator-usable `PX4 Parameters` workspace on top
of the Phase 1 backend foundation.

Implemented:

- GCS routes for:
  - `POST /api/v1/px4-params/diff`
  - `POST /api/v1/px4-params/imports/qgc`
  - `POST /api/v1/px4-params/imports/mds`
  - `POST /api/v1/px4-params/patch-jobs`
  - `GET /api/v1/px4-params/patch-jobs/{job_id}`
- reusable runtime validator scaffold:
  - `tools/validate_px4_params_runtime.py`
  - `tests/test_validate_px4_params_runtime.py`
- typed import/diff/patch-job models in `src/px4_param_models.py`
- `PX4 Parameters` dashboard page with:
  - single-drone snapshot inspection
  - single-row verified save flow
  - searchable/filterable parameter table
  - official PX4 docs links
  - QGC export
  - QGC import + diff preview + apply
  - batch patch composer for all / cluster / selected drones
- shared dashboard service helpers for `px4-params`
- focused route-inventory and dashboard test coverage

## Key Decisions Confirmed

- dashboard clients remain GCS-only; they never talk directly to drone
  parameter APIs
- telemetry delay does not falsely hard-block writes when the snapshot/write
  path is still healthy
- batch scope reuses the existing MDS fleet/cluster/search selection logic
  instead of inventing a second selector system
- metadata remains best-effort; MDS surfaces what PX4 provides and leaves the
  field empty when PX4 does not provide it
- official docs links are generated from the configured PX4 docs version plus
  the exact parameter anchor, not from a hardcoded local parameter catalog

## Validation

Backend:

- `python3 -m pytest --no-cov tests/test_px4_param_service.py tests/test_drone_api_http.py tests/test_gcs_px4_params_routes.py tests/test_api_route_inventory.py -q`
- result: `53 passed`
- `python3 -m pytest --no-cov tests/test_validate_px4_params_runtime.py -q`
- result: `3 passed`

Frontend on Hetzner:

- `CI=true npm test -- --runInBand --watch=false src/services/px4ParamsApiService.test.js src/utilities/px4ParameterFiles.test.js src/pages/Px4ParametersPage.test.js`
- result: `10 passed`
- `npm run build`
- result: passed

## Remaining Next Slice

- live Hetzner runtime smoke validation against real SITL drones
- broader operator UX pass after tester feedback
- action-pipeline audit for how `APPLY_COMMON_PARAMS` should converge onto this
  subsystem or be retired

## Deferred On Purpose

- grouped/category views beyond the current searchable flat table
- long-running/asynchronous batch job orchestration
- version-pinned local mirrors of PX4 parameter docs

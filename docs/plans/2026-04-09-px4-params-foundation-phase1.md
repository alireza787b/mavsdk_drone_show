# PX4 Parameters Foundation Phase 1

Date: 2026-04-09
Status: Completed checkpoint
Commit target: `main-candidate`

## Scope Closed

This slice establishes the typed backend foundation for the new `PX4 Parameters`
subsystem without extending the old `APPLY_COMMON_PARAMS` workflow.

Implemented:

- shared typed models in `src/px4_param_models.py`
- shared canonical route constants for drone and GCS `px4-params` surfaces
- drone-local MAVSDK param service in `src/px4_params/service.py`
- drone API routes for:
  - `GET /api/v1/px4-params/policy`
  - `POST /api/v1/px4-params/snapshots/refresh`
  - `GET /api/v1/px4-params/snapshots/current`
  - `GET /api/v1/px4-params/values/{name}`
  - `PATCH /api/v1/px4-params/values/{name}`
  - `POST /api/v1/px4-params/patches/apply`
- GCS orchestration routes for:
  - `GET /api/v1/px4-params/policy`
  - `POST /api/v1/px4-params/snapshots`
  - `GET /api/v1/px4-params/snapshots/{snapshot_id}`
  - `GET /api/v1/px4-params/snapshots/{snapshot_id}/rows`

## Key Decisions

- Dashboard clients will talk only to GCS, not directly to drone APIs.
- Runtime values come from MAVSDK/PX4 live reads.
- Exact PX4 documentation links are generated from a version-aware base URL plus
  parameter anchor.
- Writes are policy-gated and blocked while armed when
  `PX4_PARAMETER_MUTATION_REQUIRE_DISARMED` is enabled.
- The GCS helper module was renamed to `gcs-server/px4_param_store.py` to avoid
  import shadowing with the shared `src/px4_params` package.

## Validation

Focused backend validation passed:

- `python3 -m py_compile` on the new drone and GCS param modules
- `python3 -m pytest --no-cov tests/test_px4_param_service.py tests/test_drone_api_http.py tests/test_gcs_px4_params_routes.py tests/test_api_route_inventory.py -q`
- result: `50 passed`

## Remaining Next Slice

This checkpoint is foundation only. The following are still pending:

- GCS diff routes and typed compare workflows
- QGC import / MDS patch import parsing
- tracked GCS patch-job orchestration for single-drone and batch writes
- dashboard `PX4 Parameters` page and reusable workspace UI
- documentation/tester guidance for the finished operator workflow

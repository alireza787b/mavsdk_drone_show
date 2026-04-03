# 2026-04-03 Internal Canonical Caller Cleanup

## Scope

Phase 4, seventh API-modernization slice:

- migrate the remaining real internal callers that still used GCS compatibility routes
- keep public compatibility endpoints mounted for now, but stop reinforcing them from drone runtime and validation tooling

## Findings From The Caller Audit

The remaining real non-test callers on legacy GCS paths were:

- `src/drone_setup.py`
  - `/command/execution-start`
  - `/command/execution-result`
- `src/drone_api_server.py`
  - `/command/execution-result` in the superseded-pending-command fallback path
  - `/get-origin` in bootstrap-origin fetch
- `tools/validate_drone_show_runtime.py`
  - `/import-show`
  - `/get-show-info`
  - `/get-custom-show-info`
- `tools/test_import_show.html`
  - `/import-show`

That meant the public canonical routes existed, but core runtime/tooling still reinforced the legacy surface in real operation.

## Contract Decisions

- Added `src/gcs_api_routes.py` as the shared canonical route constant module for drone-side/runtime tooling callers.
- Drone execution callbacks now target:
  - `POST /api/v1/command-reports/execution-start`
  - `POST /api/v1/command-reports/execution-result`
- Drone bootstrap-origin fetch now targets:
  - `GET /api/v1/origin/bootstrap`
- Drone Show runtime validation and the import demo now target canonical show routes:
  - `POST /api/v1/shows/skybrush/import`
  - `GET /api/v1/shows/skybrush`
  - `GET /api/v1/shows/custom`

## Validation

- local focused drone-side regression:
  - `python3 -m pytest tests/test_drone_setup.py tests/test_drone_api_http.py -q`
  - result: `105 passed`
- Hetzner focused drone-side regression:
  - `105 passed`

## Notes

- This slice does not remove any public compatibility routes yet.
- It removes hidden migration debt first, so later route retirement is based on real caller truth instead of assumptions.
- The next clean boundary is classification of the still-mounted GCS compatibility routes plus any dead frontend compatibility helpers that can be removed immediately.

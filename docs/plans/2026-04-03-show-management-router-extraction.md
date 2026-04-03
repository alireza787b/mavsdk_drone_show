# Show Management Router Extraction Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 3, sixth backend route-domain extraction

## Summary

- extracted the remaining Drone Show / Custom Show routes from `gcs-server/app_fastapi.py` into `gcs-server/api_routes/show_management.py`
- moved the supporting show-domain helpers into `gcs-server/show_management.py`
- preserved the existing live routes:
  - `POST /import-show`
  - `GET /download-raw-show`
  - `GET /download-processed-show`
  - `GET /get-show-info`
  - `GET /get-custom-show-info`
  - `POST /import-custom-show`
  - `GET /get-comprehensive-metrics`
  - `GET /get-safety-report`
  - `POST /validate-trajectory`
  - `POST /deploy-show`
  - `GET /get-show-plots`
  - `GET /get-show-plots/{filename}`
  - `GET /get-custom-show-image`
- kept compatibility wrappers on the `app_fastapi` module object for `_custom_show_csv_path`, `_custom_show_preview_path`, `_inspect_custom_show_csv`, `_generate_custom_show_preview`, `_load_saved_metrics_if_current`, and `_refresh_saved_show_metrics` so existing patch-driven tests still target one live dependency seam
- updated the public API docs in `docs/apis/gcs-api-server.md` so the custom-show endpoints and the expanded import-show response are documented alongside the legacy show-management routes

## Root Fixes Included In This Slice

- `POST /deploy-show` now accepts standard JSON content-type variants such as `application/json; charset=utf-8` instead of only an exact header match
- show trajectory validation no longer downgrades a safety `FAIL` to `WARNING` later in the same pass when warnings also exist
- `GET /get-show-plots/{filename}` now resolves files through a bounded path check instead of direct path joining
- `GET /get-show-plots` now returns an empty payload for a missing directory instead of creating directories as a side effect of a read request
- async show handlers now use `asyncio.get_running_loop()` instead of `get_event_loop()`

## Design Decision

This slice keeps the legacy show route names intact and does not start the canonical `/api/v1/...` rename yet.

The router boundary is intentionally the full show-management domain rather than a smaller partial split, because the remaining routes share the same directories, metrics helpers, git side effects, and custom-show preview logic. Moving them together gives one coherent extraction seam while still preserving the current frontend and validation-tool contracts.

## Tests

Local:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/show_management.py gcs-server/api_routes/show_management.py tests/test_gcs_show_management_routes.py tests/test_gcs_api_http.py`
- `python3 -m pytest tests/test_gcs_show_management_routes.py tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_origin_routes.py tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py -q`
- result: `98 passed, 7 skipped`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- `python -m py_compile gcs-server/app_fastapi.py gcs-server/show_management.py gcs-server/api_routes/show_management.py tests/test_gcs_show_management_routes.py tests/test_gcs_api_http.py`
- `python -m pytest tests/test_gcs_show_management_routes.py tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_origin_routes.py tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py -q`
- result: `98 passed, 7 skipped`

Hetzner frontend build:

- `source ~/.nvm/nvm.sh && cd /root/mavsdk_drone_show_validation/app/dashboard/drone-dashboard && npm run build`
- result: compiled successfully

## Files

- updated: `docs/apis/gcs-api-server.md`
- updated: `gcs-server/app_fastapi.py`
- updated: `tests/test_gcs_api_http.py`
- added: `gcs-server/api_routes/show_management.py`
- added: `gcs-server/show_management.py`
- added: `tests/test_gcs_show_management_routes.py`

## Next

- continue Phase 3 with the next coherent backend extraction boundary on the GCS side or start Phase 4 canonical route migration for the already-extracted domains
- the highest-leverage next backend task is likely canonical v1 planning for the show-management surface now that the legacy routes are isolated behind one router

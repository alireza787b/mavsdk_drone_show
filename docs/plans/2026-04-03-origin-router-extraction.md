# Origin Router Extraction Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 3, fourth backend route-domain extraction

## Summary

- extracted the full Origin domain from `gcs-server/app_fastapi.py` into `gcs-server/api_routes/origin.py`
- mounted the extracted router through `create_origin_router(sys.modules[__name__])`
- preserved the existing live routes:
  - `GET /get-origin`
  - `POST /set-origin`
  - `GET /get-gps-global-origin`
  - `GET /elevation`
  - `GET /get-origin-for-drone`
  - `GET /get-position-deviations`
  - `POST /compute-origin`
  - `GET /get-desired-launch-positions`
- moved the heavier domain logic behind reusable helpers in `gcs-server/origin.py` instead of leaving geometry/report assembly inside route handlers
- fixed the missing `pyproj` imports in `compute_origin_from_drone(...)`
- corrected `POST /compute-origin` so it is compute-only and no longer mutates shared origin state
- corrected the command `auto_global_origin` path so valid `0.0` latitude/longitude origins are propagated instead of being discarded by truthiness checks
- corrected `GET /get-desired-launch-positions` so its documented `heading` and `format` parameters are now honored for JSON, CSV, and KML outputs

## Design Decision

This slice keeps the legacy Origin route names intact and does not widen into command-route renames or canonical v1 migration yet.

That keeps the extraction boundary coherent and low-risk while the live frontend, route inventory, and current operator workflows still depend on the legacy GCS Origin surface. The router follows the same live `deps` pattern as the earlier extracted domains, and the new service helpers accept an injected trajectory resolver so route logic remains testable without hard-coding file IO back into the handler layer.

## Tests

Local:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/origin.py gcs-server/origin.py tests/test_gcs_origin_routes.py tests/test_gcs_api_http.py`
- `python3 -m pytest tests/test_gcs_origin_routes.py tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py -q`
- result: `75 passed, 7 skipped`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- synced the changed backend files into the validation checkout
- `python -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/origin.py gcs-server/origin.py tests/test_gcs_origin_routes.py tests/test_gcs_api_http.py`
- `python -m pytest tests/test_gcs_origin_routes.py tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py -q`
- result: `75 passed, 7 skipped`
- note: Hetzner still emits the pre-existing pytest warning about unknown config option `asyncio_mode`

## Files

- updated: `gcs-server/app_fastapi.py`
- updated: `gcs-server/origin.py`
- updated: `tests/test_api_route_inventory.py`
- updated: `tests/test_gcs_api_http.py`
- added: `gcs-server/api_routes/origin.py`
- added: `tests/test_gcs_origin_routes.py`

## Next

- continue phase 3 by extracting the next coherent GCS backend route domain out of `app_fastapi.py`
- current best candidates are:
  - GCS management / network helper routes, if we want the smallest remaining compatibility surfaces out next
  - show-management routes, if we want to keep shrinking the non-command monolith before moving into phase 4 canonical route migration

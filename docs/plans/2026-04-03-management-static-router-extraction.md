# Management And Static Assets Router Extraction Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 3, fifth backend route-domain extraction

## Summary

- extracted the remaining small GCS management/static compatibility cluster from `gcs-server/app_fastapi.py` into:
  - `gcs-server/api_routes/management.py`
  - `gcs-server/api_routes/static_assets.py`
- preserved the current live routes:
  - `GET /get-gcs-config`
  - `POST /save-gcs-config`
  - `GET /get-network-info`
  - `GET /static/plots/{filename}`
- kept the extracted routers on the same live dependency seam as the earlier slices by resolving attributes from the `app_fastapi` module object at request time instead of capturing them at import time
- corrected `POST /save-gcs-config` so it now returns an explicit compatibility stub result with:
  - `success=true`
  - `status="success"`
  - `persisted=false`
  - warning text explaining that this surface currently acknowledges operator intent but does not persist GCS config
- hardened static plot serving through bounded path resolution so traversal attempts are rejected instead of being joined directly under the plots directory
- moved `MissionReadinessCard` static-plot URL composition onto the shared `buildStaticPlotUrl(...)` helper instead of hardcoding `/static/plots/...`
- fixed the project test-tooling contract by adding `pytest-timeout` to the `dev` extra and removing the ignored duplicate pytest config from `pyproject.toml`, leaving `pytest.ini` as the single source of truth

## Design Decision

This slice intentionally keeps the legacy route names intact.

The goal here is to keep shrinking the `app_fastapi.py` compatibility cluster without mixing in the later Phase 4 route-renaming work. The management router therefore preserves the existing operator/frontend contract while making the contract semantics more honest, and the static-assets router keeps file serving isolated enough for later auth/policy wrapping.

## Tests

Local:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/management.py gcs-server/api_routes/static_assets.py gcs-server/schemas.py tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_api_http.py`
- `python3 -m pytest tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_origin_routes.py tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py -q`
- result: `91 passed, 7 skipped`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- created or refreshed a validation-only `.venv` with `python -m pip install -e ".[dev]"`
- `python -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/management.py gcs-server/api_routes/static_assets.py gcs-server/schemas.py tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_api_http.py`
- `python -m pytest tests/test_gcs_management_routes.py tests/test_gcs_static_assets_routes.py tests/test_gcs_origin_routes.py tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py tests/test_api_route_inventory.py -q`
- result: `91 passed, 7 skipped`

Hetzner frontend build:

- `source ~/.nvm/nvm.sh && cd /root/mavsdk_drone_show_validation/app/dashboard/drone-dashboard && npm ci && npm run build`
- result: compiled successfully

## Findings

- the first Hetzner backend test attempt failed for a real reason: `pytest.ini` required timeout flags, but the declared `dev` extra did not install `pytest-timeout`
- the correct fix was to repair the package metadata instead of working around the missing plugin in the command line
- the frontend build still passes, but the current CRA/react-scripts toolchain emits known deprecation and vulnerability noise during `npm ci`; that is a separate toolchain-modernization concern, not a blocker for this API checkpoint

## Files

- updated: `app/dashboard/drone-dashboard/src/components/MissionReadinessCard.js`
- updated: `gcs-server/app_fastapi.py`
- updated: `gcs-server/schemas.py`
- updated: `pyproject.toml`
- updated: `tests/test_gcs_api_http.py`
- added: `gcs-server/api_routes/management.py`
- added: `gcs-server/api_routes/static_assets.py`
- added: `tests/test_gcs_management_routes.py`
- added: `tests/test_gcs_static_assets_routes.py`

## Next

- continue phase 3 with the next coherent GCS backend route domain, with show-management now the best remaining non-command extraction candidate
- keep the corrected validation-venv flow for future Hetzner API checkpoints so clean-environment failures surface immediately instead of being hidden by local preinstalled tooling

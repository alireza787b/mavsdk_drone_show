# GCS Core Router Extraction Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 3, first backend route-domain extraction

## Summary

- extracted the core GCS health, telemetry, heartbeat, and heartbeat-derived network-status routes from `gcs-server/app_fastapi.py` into `gcs-server/api_routes/core.py`
- mounted the extracted routes through `create_core_router(sys.modules[__name__])` so the router can read live dependencies from the `app_fastapi` module object
- preserved the current canonical and compatibility surfaces:
  - `GET /api/v1/system/health`
  - `GET /ping`
  - `GET /health`
  - `GET /telemetry`
  - `GET /api/v1/fleet/telemetry`
  - `GET /api/telemetry`
  - `POST /api/v1/fleet/heartbeats`
  - `POST /heartbeat`
  - `POST /drone-heartbeat`
  - `GET /api/v1/fleet/heartbeats`
  - `GET /get-heartbeats`
  - `GET /api/v1/fleet/network-status`
  - `GET /get-network-status`
  - `WS /ws/telemetry`
  - `WS /ws/heartbeats`
- fixed the legacy `GET /get-network-info` alias to return the live heartbeat-derived snapshot directly after the helper extraction removed its old private dependency

## Design Decision

The new router does not capture route dependencies once at import time.

Instead, it receives a live `deps` object and looks up attributes such as `handle_heartbeat_post`, `get_all_heartbeats`, `load_config`, `telemetry_data_all_drones`, and `Params` when each request runs.

That decision keeps the following behavior intact while modularizing the app:

- existing backend tests that patch `app_fastapi.*` attributes
- future auth/policy wiring at the router or dependency layer
- future MCP/automation metadata or wrapper injection without a second route rewrite

## Tests

Local:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/core.py`
- `python3 -m pytest tests/test_gcs_core_routes.py tests/test_gcs_api_http.py -q`
- result: `53 passed`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- created a validation-only `.venv` for backend pytest execution
- `python -m pytest tests/test_gcs_core_routes.py tests/test_gcs_api_http.py -q`
- result: `53 passed`

## Files

- updated: `gcs-server/app_fastapi.py`
- added: `gcs-server/api_routes/__init__.py`
- added: `gcs-server/api_routes/core.py`
- added: `tests/test_gcs_core_routes.py`

## Next

- continue phase 3 by extracting the next coherent GCS route domains out of `app_fastapi.py`
- prefer domains that reduce handler-local side effects and prepare clean service boundaries for later auth, MCP, and repeatable SITL contract checks

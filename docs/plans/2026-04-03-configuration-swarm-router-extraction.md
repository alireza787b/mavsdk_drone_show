# Configuration And Swarm Router Extraction Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 3, second backend route-domain extraction

## Summary

- extracted the configuration routes from `gcs-server/app_fastapi.py` into `gcs-server/api_routes/configuration.py`
- extracted the swarm configuration and Smart Swarm reassignment routes into `gcs-server/api_routes/swarm.py`
- mounted both extracted routers through:
  - `create_configuration_router(sys.modules[__name__])`
  - `create_swarm_router(sys.modules[__name__])`
- preserved the existing live routes:
  - `GET /get-config-data`
  - `POST /save-config-data`
  - `POST /validate-config`
  - `GET /get-drone-positions`
  - `GET /get-trajectory-first-row`
  - `GET /get-swarm-data`
  - `POST /save-swarm-data`
  - `POST /request-new-leader`
- moved the swarm-cycle validation helpers into the swarm router module so the follow-chain rules now live beside the routes that enforce them
- updated the async git side-effect paths in the extracted mutable routers to use `asyncio.get_running_loop()`
- tightened the configuration contract so invalid client payload shape now returns `400` instead of being flattened into a generic `500`

## Design Decision

Like the Phase 3A core router, both routers receive a live `deps` object and read attributes such as `load_config`, `validate_and_process_config`, `save_config`, `get_all_drone_positions`, `load_swarm`, `save_swarm`, `Params`, `git_operations`, `BASE_DIR`, and `log_system_event` when each request runs.

That preserves the current patch-driven backend test seams and keeps both domains ready for later auth/policy/MCP wrapping without another route rewrite.

## Tests

Local:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/configuration.py gcs-server/api_routes/swarm.py`
- `python3 -m pytest tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py -q`
- result: `58 passed`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- synced the changed backend files into the validation checkout
- `python -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/configuration.py gcs-server/api_routes/swarm.py`
- `python -m pytest tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py -q`
- result: `58 passed`

## Files

- updated: `gcs-server/app_fastapi.py`
- updated: `gcs-server/api_routes/swarm.py`
- updated: `tests/test_gcs_api_http.py`
- added: `gcs-server/api_routes/configuration.py`
- added: `tests/test_gcs_configuration_routes.py`

## Next

- continue phase 3 by extracting the next coherent GCS route domain out of `app_fastapi.py`
- current best candidates are:
  - git routes, if we want the strongest already-tested operational domain next
  - origin routes, if we want to start collapsing the remaining origin wrappers toward the existing origin services

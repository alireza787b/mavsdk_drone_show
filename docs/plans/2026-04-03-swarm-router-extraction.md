# Swarm Router Extraction Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 3, second backend route-domain extraction

## Summary

- extracted the Swarm domain routes from `gcs-server/app_fastapi.py` into `gcs-server/api_routes/swarm.py`
- mounted the extracted router through `create_swarm_router(sys.modules[__name__])`
- preserved the existing live routes:
  - `GET /get-swarm-data`
  - `POST /save-swarm-data`
  - `POST /request-new-leader`
- moved the swarm-cycle validation helpers into the same router module so the follow-chain rules now live with the routes that enforce them
- updated the async swarm save path to use `asyncio.get_running_loop()` instead of the older event-loop accessor

## Design Decision

Like the Phase 3A core router, the swarm router receives a live `deps` object and reads attributes such as `load_swarm`, `save_swarm`, `Params`, `git_operations`, `BASE_DIR`, and `log_system_event` when each request runs.

That preserves the current patch-driven backend test seams and keeps the swarm domain ready for later auth/policy/MCP wrapping without another route rewrite.

## Tests

Local:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/core.py gcs-server/api_routes/swarm.py`
- `python3 -m pytest tests/test_gcs_core_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_api_http.py -q`
- result: `56 passed`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- synced the changed backend files into the validation checkout
- `python -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/core.py gcs-server/api_routes/swarm.py`
- `python -m pytest tests/test_gcs_core_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_api_http.py -q`
- result: `56 passed`

## Files

- updated: `gcs-server/app_fastapi.py`
- added: `gcs-server/api_routes/swarm.py`
- added: `tests/test_gcs_swarm_routes.py`

## Next

- continue Phase 3 by extracting the next coherent GCS route domain out of `app_fastapi.py`
- current best candidate is one of:
  - configuration core routes, if we want another small low-risk slice
  - origin routes, if we want to start collapsing the remaining origin wrappers toward the existing origin services

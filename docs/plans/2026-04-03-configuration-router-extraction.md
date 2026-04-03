# Configuration Router Extraction Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 3, third backend route-domain extraction

## Summary

- extracted the configuration routes from `gcs-server/app_fastapi.py` into `gcs-server/api_routes/configuration.py`
- mounted the extracted router through `create_configuration_router(sys.modules[__name__])`
- preserved the existing live routes:
  - `GET /get-config-data`
  - `POST /save-config-data`
  - `POST /validate-config`
  - `GET /get-drone-positions`
  - `GET /get-trajectory-first-row`
- kept the same live dependency lookup pattern so the router reads `load_config`, `validate_and_process_config`, `save_config`, `get_all_drone_positions`, `get_expected_position_from_trajectory`, `Params`, `git_operations`, and logging hooks from the live `app_fastapi` module object at request time
- rolled the remaining async loop accessor cleanup into the extracted mutable router set by switching the Swarm router git path to `asyncio.get_running_loop()`

## Tests

Local:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/core.py gcs-server/api_routes/configuration.py gcs-server/api_routes/swarm.py`
- `python3 -m pytest tests/test_gcs_core_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_api_http.py -q`
- result: `62 passed`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- synced the changed backend files into the validation checkout
- `python -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/core.py gcs-server/api_routes/configuration.py gcs-server/api_routes/swarm.py`
- `python -m pytest tests/test_gcs_core_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_api_http.py -q`
- result: `62 passed`

## Files

- updated: `gcs-server/app_fastapi.py`
- updated: `gcs-server/api_routes/swarm.py`
- updated: `tests/test_gcs_api_http.py`
- added: `gcs-server/api_routes/configuration.py`
- added: `tests/test_gcs_configuration_routes.py`

## Next

- continue Phase 3 with the next coherent GCS route domain out of `app_fastapi.py`
- the leading candidates now are:
  - origin routes, because they already lean on `gcs-server/origin.py`
  - git routes, if we want to isolate the remaining repo/status side effects next

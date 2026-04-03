# Git Router Extraction Checkpoint

Date: 2026-04-03
Status: Completed checkpoint
Scope: API modernization phase 3, third backend route-domain extraction

## Summary

- extracted the Git routes from `gcs-server/app_fastapi.py` into `gcs-server/api_routes/git_status.py`
- mounted the extracted router through `create_git_router(sys.modules[__name__])`
- preserved the existing live routes:
  - `GET /git-status`
  - `POST /sync-repos`
  - `WS /ws/git-status`
  - `GET /get-gcs-git-status`
  - `GET /get-drone-git-status/{drone_id}`
- kept the sync helper functions and mutable sync state in `app_fastapi.py` for this slice so the current patch-driven backend tests can keep the same hook surface while the Git route layer moves out
- unified the REST and websocket Git payload generation through one shared response builder in the router module

## Design Decision

The Git route handlers use the same live `deps` object pattern as the earlier extracted routers, but the sync helpers remain in `app_fastapi.py` intentionally for this checkpoint.

That keeps the current patch seams for `_select_sync_target_drones`, `_verify_sync_targets`, `_sync_state`, and `_sync_lock` stable while still shrinking the route surface materially. The next cleanup step for this domain can decide whether those helpers should move into a dedicated service layer after the contract is stable.

## Tests

Local:

- `python3 -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/git_status.py`
- `python3 -m pytest tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py -q`
- result: `66 passed, 7 skipped`

Hetzner validation checkout: `/root/mavsdk_drone_show_validation`

- synced the changed backend files into the validation checkout
- `python -m py_compile gcs-server/app_fastapi.py gcs-server/api_routes/git_status.py`
- `python -m pytest tests/test_gcs_git_routes.py tests/test_gcs_configuration_routes.py tests/test_gcs_swarm_routes.py tests/test_gcs_core_routes.py tests/test_gcs_api_http.py tests/test_gcs_api_websocket.py -q`
- result: `66 passed, 7 skipped`

## Files

- updated: `gcs-server/app_fastapi.py`
- added: `gcs-server/api_routes/git_status.py`
- added: `tests/test_gcs_git_routes.py`

## Next

- continue phase 3 by extracting the next coherent GCS route domain out of `app_fastapi.py`
- current best candidate is `origin`, because it already leans on `gcs-server/origin.py` and is now the clearest remaining non-command domain in the monolith

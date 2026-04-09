# PX4 Parameter Runtime Validation Phase 3

Date: 2026-04-09
Status: Completed checkpoint
Commit target: `main-candidate`

## Scope Closed

This slice closed the live runtime validation gap for the new `PX4 Parameters`
workspace and validator.

Implemented:

- runtime `grpcio` pin alignment in `requirements.txt` for the clean Hetzner
  GCS environment
- explicit drone-local HTTP readiness waiting in
  `tools/validate_px4_params_runtime.py` before the first snapshot refresh
- drone-side PX4 snapshot fallback in `src/px4_params/service.py`:
  - prefer MAVSDK `GetAllParams` when available
  - fall back to MAVLink parameter enumeration on the routed local `14569`
    endpoint when the runtime MAVSDK server does not implement bulk listing
- best-effort component-information metadata loading so a metadata gRPC failure
  does not block snapshot construction
- live-validator batch-baseline fix for the two-drone patch/apply/restore path

## Root Problems Found And Fixed

1. Clean Hetzner GCS startup failed because the repo still pinned
   `grpcio==1.66.0` while the installed `mavsdk 3.10.2` generated stubs
   required `grpcio>=1.71.0`.

2. The first live validator attempt raced ahead of the drone-local HTTP API on
   `:7070`, so snapshot refresh hit connection-refused before the drone API was
   truly ready.

3. After the HTTP race was fixed, live snapshot refresh still failed because
   the drone-local MAVSDK server in this runtime returned gRPC
   `StatusCode.UNIMPLEMENTED` for bulk `GetAllParams`.

4. After the MAVLink snapshot fallback was added, a second live failure exposed
   that component-information metadata loading also needed to be best-effort.

5. Once the product path was working live, the validator itself still had one
   int/string key mismatch in the two-drone batch baseline map.

All five issues are fixed in this checkpoint.

## Validation

Local:

- `python3 -m pytest --no-cov tests/test_validate_px4_params_runtime.py -q`
- result: `6 passed`
- `python3 -m pytest --no-cov tests/test_px4_param_service.py tests/test_drone_api_http.py tests/test_gcs_px4_params_routes.py tests/test_validate_px4_params_runtime.py -q`
- result: `55 passed`
- `python3 -m pytest --no-cov tests/test_run_sitl_validation_suite.py -q`
- result: `13 passed`

Hetzner live runtime:

- plan: `px4_params_runtime`
- selected drones: `1 2`
- result: passed
- artifact root:
  - `/root/mavsdk_drone_show_main_candidate_clean_sync/artifacts/sitl-validation/20260409T102147Z`

The live validator covered:

- fresh reset before suite
- snapshot refresh
- QGC import parse/diff
- single-drone apply + verify
- two-drone batch apply + verify
- full restore to original values
- fresh reset after suite

Hetzner final state after cleanup:

- GCS health: `ok`
- active commands: `0`
- fleet telemetry: `2/2` drones online, idle, disarmed, `readiness=ready`
- active containers: `drone-1`, `drone-2`
- stale `drone-3` was removed and GCS was restarted from the clean sync tree so
  the runtime view reflects only the validated fleet

## Notes

- drone containers were validated by syncing to pushed `main-candidate`
  checkpoints; local unpushed fixes were not treated as trustworthy runtime
  truth
- the PX4 parameter subsystem remains GCS-managed; dashboard clients still do
  not talk directly to drone parameter APIs
- single-parameter reads/writes still use MAVSDK; only bulk snapshot
  enumeration gained the MAVLink fallback

## Remaining Next Slice

- operator review of the new `PX4 Parameters` page in the browser
- batch UX refinement after tester feedback
- action-pipeline convergence decision for the older `APPLY_COMMON_PARAMS`
  workflow

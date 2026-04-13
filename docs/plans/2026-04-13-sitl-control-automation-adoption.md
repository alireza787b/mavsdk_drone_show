# SITL Control Automation Adoption

Date: 2026-04-13

## Summary

Adopted the new SITL Control API as the default lifecycle path for:

- reusable SITL validation resets
- headless automation
- AI terminal agent workflows
- future MCP-oriented SITL tooling

The canonical shell launcher remains in place as the cold-start and
API-unavailable fallback.

## What Changed

- added `tools/sitl_control_client.py`
  - typed policy fetch
  - API-driven fleet reconcile
  - operation polling with streamed log output
  - `auto|api|shell` execution modes
- updated `tools/run_sitl_validation_suite.py`
  - reset steps now call the headless SITL Control client
  - default reset mode is `auto`
  - explicit timeout / poll controls were added for reconcile operations
- updated validation docs and agent specs so raw `create_dockers.sh` use is now
  documented as the cold-start path rather than the primary steady-state
  automation path
- added targeted tests for the new headless client and reset-path planning

## Design Doctrine

- Prefer the SITL Control API when the live GCS is reachable.
- Fall back to `multiple_sitl/create_dockers.sh` only when:
  - the GCS is not running yet
  - the SITL Control API is unavailable
  - an operator explicitly forces shell mode
- Keep the backend implementation anchored to the canonical shell launcher so
  there is still only one actual fleet-create path under MDS.

## Validation

- `python3 -m py_compile tools/sitl_control_client.py tools/run_sitl_validation_suite.py tools/runtime_validation_support.py`
- `python3 -m pytest tests/test_sitl_control_client.py tests/test_run_sitl_validation_suite.py tests/test_sitl_control_service.py tests/test_gcs_sitl_control_routes.py tests/test_api_route_inventory.py::test_gcs_business_route_inventory -q`
- `python3 tools/run_sitl_validation_suite.py --dry-run --artifact-dir /tmp/mds_sitl_api_dryrun_check`

## Remaining Boundary

- This slice does not change image build/release behavior.
- This slice does not remove `create_dockers.sh`; it changes which interface
  agents and validators should prefer once GCS is reachable.

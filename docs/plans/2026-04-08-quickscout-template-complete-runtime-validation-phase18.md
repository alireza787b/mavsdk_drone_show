# QuickScout Template-Complete Runtime Validation Phase 18

Date: 2026-04-08

## Summary

QuickScout runtime validation is no longer limited to the
`last_known_point` template. The reusable runtime validator and the checked-in
SITL plan library now cover all operator-visible QuickScout mission templates:

- `area_sweep`
- `last_known_point`
- `corridor_search`

This checkpoint closes the remaining template-coverage gap before serious
QuickScout tester handoff.

## What Changed

- generalized `tools/validate_quickscout_runtime.py` so it can build runtime
  requests for:
  - polygon area sweep
  - last-known-point search
  - corridor search
- added new runtime geometry builders:
  - `build_area_sweep_request(...)`
  - `build_corridor_search_request(...)`
  - shared runtime search-center/offset helpers
- extended `tools/run_sitl_validation_suite.py` with template-aware QuickScout
  options
- added bundled plans:
  - `tools/sitl_plans/quickscout_area_runtime.json`
  - `tools/sitl_plans/quickscout_corridor_runtime.json`
  - `tools/sitl_plans/quickscout_template_regression.json`
- updated the bundled-plan library doc in
  `tools/sitl_plans/README.md`

## Validation

Local:

- `python3 -m py_compile tools/validate_quickscout_runtime.py tools/run_sitl_validation_suite.py`
- `python3 -m pytest tests/test_validate_quickscout_runtime.py tests/test_run_sitl_validation_suite.py --no-cov -q`
- result: `23 passed`
- `python3 tools/run_sitl_validation_suite.py --plan-name quickscout_template_regression ... --dry-run`
- result: passed

Hetzner live runtime:

- direct single-drone `area_sweep` runtime validator: passed
- direct single-drone `corridor_search` runtime validator: passed
- reset-backed `quickscout_template_regression` bundled plan: passed

The passing bundled plan proves:

- fresh-reset template isolation between runs
- stable single-drone area-sweep acceptance
- stable single-drone last-known-point acceptance
- stable single-drone corridor-search acceptance
- findings/evidence/handoff validation inside each runtime drill
- clean post-suite reset to ready/idle fleet state

## Notes

- During the first Hetzner attempt, the updated validator was accidentally
  rsynced into the repo root instead of the real `tools/` path. That was a
  sync mistake, not a QuickScout defect, and it was cleaned up before the final
  live validation.
- Remaining QuickScout debt is now explicitly post-v1:
  - mid-mission add/remove-drone retasking
  - deeper airborne follow-up package generation
  - advanced retask / fault-injection SITL scenarios

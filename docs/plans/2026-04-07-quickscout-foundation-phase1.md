# QuickScout Foundation Phase 1

Date: 2026-04-07
Repo baseline: `195ea86e`
Status: complete, local validation green

## Goal

Start the QuickScout redesign by replacing the PoC in-memory mission state with a durable backend source of truth before planner expansion or UI redesign.

## What Changed

- added a durable SQLite-backed QuickScout store in [store.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/store.py)
- added a centralized QuickScout application service in [service.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/service.py)
- migrated the active SAR routes in [routes.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/routes.py) onto that service
- turned [mission_manager.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/mission_manager.py) and [poi_manager.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/poi_manager.py) into compatibility facades instead of keeping them as the real state store
- added a durable internal operation record model in [schemas.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/schemas.py)
- added `camera_interval_s` to persisted QuickScout coverage waypoints so operator-selected camera cadence can survive the GCS → drone handoff
- removed the old silent `(0,0)` planning fallback when no live drone GPS positions are available; planning now fails closed instead
- added focused persistence tests in [test_sar_store.py](/tmp/mavsdk_drone_show_resume/tests/test_sar_store.py)

## Why This Slice Matters

Before this change, QuickScout mission state was fragmented across:

- GCS singleton memory
- browser page state
- drone `/tmp` payload files

That made restart/recovery and later MCP/API-friendly evolution weak by design.

This slice creates one durable GCS-side source of truth for:

- mission package metadata
- current mission state
- per-drone survey state
- stored plans
- findings / POIs

## Validation

Focused local validation command:

```bash
python3 -m pytest --no-cov -q \
  tests/test_sar_schemas.py \
  tests/test_sar_coverage_planner.py \
  tests/test_sar_api.py \
  tests/test_gcs_sar_routes.py \
  tests/test_sar_store.py
```

Result:

- `54 passed`

Note:

- `--no-cov` was used because the repo-wide pytest coverage configuration is not meaningful for this focused subsystem slice and otherwise fails on unrelated global coverage accounting.

## Important Behavioral Changes

- QuickScout planning now requires live GPS positions for the selected drones.
- POIs are now tied to a real persisted mission instead of being accepted as orphan records.
- route-backed mission status now reads from the durable store rather than transient singleton memory.

## Remaining Debt After This Slice

This is only the foundation slice. Major follow-up work still remains:

- move QuickScout launch/control onto the shared tracked command lifecycle instead of route-local sends
- redesign the mission/package domain beyond the old `planning/ready/executing/...` PoC model
- redesign the QuickScout UI around staged search operations
- add a QuickScout SITL validator
- add reopen/list/recover mission flows for the frontend

## Recommended Next Slice

QuickScout Phase 2 should extract and reuse the shared command-submission path so QuickScout launch, hold, and abort no longer bypass the richer command tracker lifecycle already used elsewhere in MDS.

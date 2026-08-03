# QuickScout Foundation Phase 1

Date: 2026-04-07
Repo baseline: `195ea86e`
Status: complete, local validation green

> Historical phase record. Current QuickScout ownership remains in
> `gcs-server/sar/service.py`, `gcs-server/sar/store.py`, and
> `gcs-server/sar/command_lifecycle.py`. The temporary worktree paths and
> compatibility facades used during this slice are no longer runtime surfaces.
> The current store serializes mission read-modify-write updates in SQLite;
> launch/control submission is serialized per mission; tracked target identity
> is set-based (not JSON key-order based); and post-terminal `late_reports`
> remain command-tracker audit evidence rather than rewriting mission truth.

## 2026-08-03 Integrity Checkpoint

The current field-readiness hardening adds these bounded guarantees:

- persisted target identity uses exact set equality and survives JSON key
  reordering for hardware IDs such as `1`, `2`, `10`, and `100`
- a mixed accepted/rejected batch keeps its command slot while any target can
  still produce an execution outcome
- concurrent command, reconciliation, and progress writes merge through one
  serialized SQLite read-modify-write transaction
- launch, pause, and abort submission are serialized per mission in the
  command-owning GCS process
- terminal per-target truth is monotonic; tracker `late_reports` remain visible
  in the generic command audit record and do not silently mutate QuickScout

Focused evidence at this checkpoint: 20 lifecycle/store crash, concurrency,
and round-trip tests plus 9 launch/pause/abort/progress route regressions passed.

## Goal

Start the QuickScout redesign by replacing the PoC in-memory mission state with a durable backend source of truth before planner expansion or UI redesign.

## What Changed

- added a durable SQLite-backed QuickScout store in [store.py](../../gcs-server/sar/store.py)
- added a centralized QuickScout application service in [service.py](../../gcs-server/sar/service.py)
- migrated the active SAR routes in [routes.py](../../gcs-server/sar/routes.py) onto that service
- temporarily used mission/POI compatibility facades while callers migrated; those facades were subsequently removed, leaving the service and store as the single runtime path
- added a durable internal operation record model in [schemas.py](../../gcs-server/sar/schemas.py)
- added `camera_interval_s` to persisted QuickScout coverage waypoints so operator-selected camera cadence can survive the GCS → drone handoff
- removed the old silent `(0,0)` planning fallback when no live drone GPS positions are available; planning now fails closed instead
- added focused persistence tests in [test_sar_store.py](../../tests/test_sar_store.py)

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

## Remaining Debt Recorded At This Slice

At this historical checkpoint, the following follow-up work remained:

- move QuickScout launch/control onto the shared tracked command lifecycle instead of route-local sends
- redesign the mission/package domain beyond the old `planning/ready/executing/...` PoC model
- redesign the QuickScout UI around staged search operations
- add a QuickScout SITL validator
- add reopen/list/recover mission flows for the frontend

## Recommended Next Slice At The Time

QuickScout Phase 2 should extract and reuse the shared command-submission path so QuickScout launch, hold, and abort no longer bypass the richer command tracker lifecycle already used elsewhere in MDS.

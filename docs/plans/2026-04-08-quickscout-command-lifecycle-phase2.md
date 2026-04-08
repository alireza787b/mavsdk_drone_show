# QuickScout Command Lifecycle Phase 2

Date: 2026-04-08
Repo baseline: `97bc462d`
Status: complete, local and Hetzner validation green

## Goal

Move QuickScout launch and control flows onto the same tracked command lifecycle used by the rest of MDS, while fixing the most important mission-control logic bugs uncovered during the redesign review.

## What Changed

- extracted the shared GCS tracked-submit flow into [command_submission.py](/tmp/mavsdk_drone_show_resume/gcs-server/command_submission.py)
- slimmed [api_routes/commands.py](/tmp/mavsdk_drone_show_resume/gcs-server/api_routes/commands.py) into a thin route wrapper over that shared command-submission service
- added typed QuickScout launch/control response models in [sar/schemas.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/schemas.py)
- moved QuickScout launch, pause, and abort in [sar/service.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/service.py) onto the tracked command path instead of raw route-local `send_commands_to_selected(...)`
- changed QuickScout launch to return per-drone tracked command submissions so the operator can recover command IDs and immediate ACK state for each launched plan
- changed QuickScout pause and abort to return tracked command details instead of fire-and-forget success dicts
- fixed the old mission-scope bug where pause/abort with no explicit subset could target all configured drones; the default scope is now the mission participants only
- fixed the old abort-behavior bug where QuickScout always sent RTL regardless of requested return behavior
  - `return_home` -> `RETURN_RTL`
  - `land_current` -> `LAND`
  - `hold_position` -> `HOLD`
- changed QuickScout operational launch/control failures into typed API results rather than generic server errors when the HTTP request itself succeeded but no drone accepted the command
- persisted compact command recovery summaries on the QuickScout operation record instead of only volatile route-local responses
- added focused route tests covering tracked QuickScout launch and abort-return-behavior mapping in [test_gcs_sar_routes.py](/tmp/mavsdk_drone_show_resume/tests/test_gcs_sar_routes.py)

## Why This Slice Matters

Before this change, QuickScout was still a special-case mission family:

- launch bypassed `command_id` creation and the command tracker entirely
- pause/abort bypassed the canonical command API and swallowed delivery failures
- default mission controls could over-target drones outside the mission
- abort semantics did not actually match the operator-selected behavior

That left QuickScout weaker than the rest of MDS for:

- low-bandwidth retry/recovery
- auditability
- future MCP/AI-agent orchestration
- consistent operator status reporting

This slice makes QuickScout a first-class participant in the shared command system even though the broader QuickScout workflow/UI redesign is still in progress.

## Validation

Focused local validation:

```bash
python3 -m pytest --no-cov -q \
  tests/test_sar_schemas.py \
  tests/test_sar_coverage_planner.py \
  tests/test_sar_api.py \
  tests/test_gcs_sar_routes.py \
  tests/test_sar_store.py \
  tests/test_gcs_command_routes.py
```

Result:

- `67 passed`

Focused Hetzner validation on a clean synced checkout:

```bash
.venv/bin/python -m pytest --no-cov -q \
  tests/test_sar_schemas.py \
  tests/test_sar_coverage_planner.py \
  tests/test_sar_api.py \
  tests/test_gcs_sar_routes.py \
  tests/test_sar_store.py \
  tests/test_gcs_command_routes.py
```

Result:

- `67 passed`

## Important Behavioral Changes

- QuickScout launch now returns per-drone tracked command metadata.
- QuickScout pause and abort now return typed tracked command metadata and do not silently claim success when no drone accepted the command.
- QuickScout mission-control defaults now target only drones that belong to the mission unless the operator explicitly requests a subset.
- QuickScout abort now honors the selected return behavior instead of always mapping to RTL.

## Remaining Debt After This Slice

These follow-ups are now explicit, not lost:

- QuickScout `resume` is still a GCS-state-only operation; there is not yet a true FC-backed resume command path.
- QuickScout launch currently creates one tracked command per drone because each plan payload is unique; a future mission-batch command grouping layer can be added later if operators need a single aggregate launch command ID.
- QuickScout UI/workspace redesign is still ahead.
- QuickScout SITL validator/template is still deferred until mission behavior and operator workflow stabilize.

## Recommended Next Slice

QuickScout Phase 3 should move up one layer from backend plumbing into mission-package/workspace behavior:

- durable reopen/list/recover mission surfaces
- staged search-operations workspace UX
- explicit search template selection and mission metadata
- first operator-facing status/history recovery view that uses the newly tracked launch/control summaries

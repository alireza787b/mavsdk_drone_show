# QuickScout Mission Briefing Phase 6

Date: 2026-04-08
Repo baseline: `eed81e46`
Status: complete, local and Hetzner validation green

## Goal

Make QuickScout operator setup durable instead of page-local by persisting mission briefing metadata through the backend store, recovery APIs, and frontend workspace.

This slice adds the first real mission-briefing layer on top of the Phase 5 setup shell:

- operator-visible mission label
- selected planning profile identity
- optional mission brief / search note
- durable recovery of that operator intent across refresh and reopen flows

## What Changed

- extended [QuickScoutMissionRequest](/tmp/mavsdk_drone_show_resume/gcs-server/sar/schemas.py) to accept:
  - `mission_label`
  - `mission_profile`
  - `mission_brief`
- extended [QuickScoutOperationRecord](/tmp/mavsdk_drone_show_resume/gcs-server/sar/schemas.py) so those fields persist in the durable GCS-side mission record
- extended [QuickScoutMissionSummary](/tmp/mavsdk_drone_show_resume/gcs-server/sar/schemas.py) so mission listings can show operator-meaningful identity instead of only raw mission IDs
- updated [service.py](/tmp/mavsdk_drone_show_resume/gcs-server/sar/service.py) so planned missions now persist mission-briefing metadata and mission catalog responses project it back out
- updated [QuickScoutPage.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js) so the planning workspace now:
  - tracks `missionLabel` and `missionBrief`
  - includes them in plan requests
  - restores them from recovered workspaces
  - prefers the mission label in the top-bar mission chip when present
- updated [MissionPlanSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionPlanSidebar.js) to add:
  - a visible mission-label field
  - a folded mission-brief field
- updated [MissionRecoveryPanel.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionRecoveryPanel.js) so saved mission cards now prefer the operator mission label over truncated mission IDs
- updated [QuickScout.css](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/styles/QuickScout.css) for the new text input / textarea controls
- expanded QuickScout tests so the new briefing metadata is now verified in:
  - [test_sar_schemas.py](/tmp/mavsdk_drone_show_resume/tests/test_sar_schemas.py)
  - [test_sar_store.py](/tmp/mavsdk_drone_show_resume/tests/test_sar_store.py)
  - [test_sar_api.py](/tmp/mavsdk_drone_show_resume/tests/test_sar_api.py)
  - [QuickScoutPage.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.test.js)

## Why This Slice Matters

Before this slice, QuickScout still behaved too much like a planner-only tool:

- mission identity was mostly a generated ID
- operator objective context disappeared after refresh unless it lived outside the product
- saved mission cards and the recovered workspace had weak mission framing

That is not enough for real search operations where the mission package itself needs durable operator meaning.

This slice makes QuickScout mission setup more operationally honest:

- the mission can carry a human-readable label
- the planning profile selection is preserved as durable mission context
- the operator brief can survive refresh/reopen and travel with the mission package

## Validation

Focused local backend validation:

```bash
python3 -m pytest --no-cov -q \
  tests/test_sar_schemas.py \
  tests/test_sar_api.py \
  tests/test_sar_store.py \
  tests/test_gcs_sar_routes.py
```

Result:

- `49 passed`

Focused Hetzner backend validation:

```bash
PYTHONPATH=/root/mavsdk_drone_show_main_candidate_clean_sync:/root/mavsdk_drone_show_main_candidate_clean_sync/gcs-server \
/root/mavsdk_drone_show/venv/bin/python -m pytest -o addopts=\"\" -q \
  tests/test_sar_schemas.py \
  tests/test_sar_api.py \
  tests/test_sar_store.py \
  tests/test_gcs_sar_routes.py
```

Result:

- `49 passed`
- `1` environment warning from the Hetzner pytest config (`timeout` plugin not installed in that validation venv)

Focused Hetzner frontend validation:

```bash
cd app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watch=false \
  src/pages/QuickScoutPage.test.js \
  src/services/sarApiService.test.js \
  src/utilities/quickScoutProfiles.test.js
```

Result:

- `3` suites passed
- `12` tests passed

Focused Hetzner production build:

```bash
cd app/dashboard/drone-dashboard
npm run build
```

Result:

- build passed

Known unrelated warning still present during the build:

- [DronePositionMap.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/DronePositionMap.js) still reports the older `useMemo` dependency warning

## Important Behavior Changes

- QuickScout plan requests now carry operator briefing metadata explicitly
- recovered QuickScout workspaces now restore:
  - mission label
  - mission profile
  - mission brief
  - return behavior
- saved mission cards now show the mission label when one exists
- the QuickScout top bar now shows the operator mission label instead of only a raw generated mission ID when available

## Remaining Debt After This Slice

- QuickScout still needs a clearer pre-launch review / readiness layer before launch
- search templates are still polygon-first; richer mission types are still ahead
- `resume` is still not a true FC-backed resume path
- QuickScout SITL validator/template is still deferred until the workflow stabilizes further

## Recommended Next Slice

QuickScout Phase 7 should introduce the first true review/readiness layer:

- compact mission brief summary card before launch
- explicit selected-drone readiness review
- package assumptions / estimates surfaced as a launch review instead of only raw side inputs
- clearer transition from planning into monitoring

# QuickScout Workspace Recovery UI Phase 4

Date: 2026-04-08
Repo baseline: `b57f6b62`
Status: complete, focused Hetzner frontend validation green

## Goal

Replace the old single-page, single-`missionId` browser assumption with a recoverable QuickScout workspace flow that can reopen persisted missions after refresh or reconnect.

## What Changed

- added a reusable mission recovery panel in [MissionRecoveryPanel.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionRecoveryPanel.js)
- embedded that recovery panel into both:
  - [MissionPlanSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionPlanSidebar.js)
  - [MissionMonitorSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionMonitorSidebar.js)
- refactored [QuickScoutPage.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js) so the page container now:
  - polls the persisted mission catalog
  - auto-recovers active `executing` / `paused` missions after refresh
  - reopens saved workspaces through `getMissionWorkspace(...)`
  - hydrates plan state, selected drones, survey config, coverage geometry, mission status, and POIs from the recovered workspace payload
  - refreshes mission catalog after plan, launch, pause, resume, and abort actions
  - allows operators to explicitly start a fresh plan without relying on a stale local `missionId`
- added focused container tests in [QuickScoutPage.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.test.js)
- extended [QuickScout.css](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/styles/QuickScout.css) for the recovery catalog cards and top-bar mission chip

## Why This Slice Matters

QuickScout could already persist missions after phases 1 to 3, but the UI still behaved like a browser-local demo:

- refresh lost operator context
- reopen required hidden local state
- monitor mode could not recover an active mission cleanly
- there was no shared "saved missions" workspace affordance

This slice closes that gap. Operators can now reopen saved QuickScout missions from durable API state, and active missions recover automatically after refresh without inventing ad hoc frontend-only persistence rules.

## Validation

Focused Hetzner React validation:

```bash
cd app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watch=false \
  src/pages/QuickScoutPage.test.js \
  src/services/sarApiService.test.js
```

Result:

- `2` suites passed
- `8` tests passed

Focused Hetzner production build:

```bash
cd app/dashboard/drone-dashboard
npm run build
```

Result:

- build passed

Known unrelated warning still present in the existing dashboard code:

- [DronePositionMap.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/DronePositionMap.js) still reports an older `useMemo` dependency warning during the build

No new QuickScout-specific lint warnings remain after this slice.

## Operator Behavior Changes

- the page now shows a shared mission workspace panel in both planning and monitor contexts
- active QuickScout missions recover automatically after refresh if the GCS still has a persisted `executing` or `paused` mission
- saved `ready`, `completed`, or `aborted` missions can be reopened manually from the mission catalog
- reopening a workspace restores:
  - search area
  - survey config
  - drone selection
  - coverage plan geometry
  - mission status
  - POI state
- the operator can explicitly clear the current workspace and start a fresh search plan

## Remaining Debt After This Slice

- QuickScout still uses the older two-mode `Plan / Monitor` page shell instead of a richer staged operations workflow
- QuickScout `resume` is still GCS-state oriented, not a true FC-backed resume contract
- search templates and mission doctrine metadata are still ahead
- QuickScout SITL validator/template remains deferred until the mission workflow stabilizes further

## Recommended Next Slice

QuickScout Phase 5 should move up from workspace recovery into operator workflow structure:

- add mission template / mission-type selection
- add operator-facing mission metadata and doctrine summary
- make the planning shell less "draw polygon, fill numbers" and more search-operations oriented
- keep using the shared durable workspace and tracked-command surfaces from phases 1 to 4

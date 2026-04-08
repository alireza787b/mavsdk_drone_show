# QuickScout Operator Setup Phase 5

Date: 2026-04-08
Repo baseline: `e926e0ee`
Status: complete, focused Hetzner frontend validation green

## Goal

Move QuickScout planning one step closer to a real search-operations workflow by replacing the raw survey-only sidebar with clearer operator setup controls:

- explicit mission profile presets
- explicit end behavior
- monitor controls that reflect the configured end behavior instead of implying fixed RTL behavior

## What Changed

- added reusable planning presets in [quickScoutProfiles.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutProfiles.js)
- added focused preset tests in [quickScoutProfiles.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutProfiles.test.js)
- updated [QuickScoutPage.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js) so the page now tracks:
  - `missionProfileId`
  - `returnBehavior`
  - profile-derived survey defaults
- changed plan submission so `return_behavior` is now sent explicitly in the QuickScout planning request instead of relying on the backend default
- updated workspace recovery so reopened missions restore the saved `return_behavior` and derive the active planning profile from the recovered survey config
- refactored [MissionPlanSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionPlanSidebar.js) to add:
  - operator mission profile cards
  - explicit end-behavior selection chips
  - a clearer mission-setup block ahead of the lower-level survey numbers
- updated [MissionActionBar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionActionBar.js) so the monitor action bar now reflects the configured end behavior rather than implying fixed RTL semantics
- expanded [QuickScoutPage.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.test.js) to verify the chosen `return_behavior` is carried into the plan request
- updated [QuickScout.css](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/styles/QuickScout.css) for profile cards, behavior chips, and the revised monitor action styling

## Why This Slice Matters

Before this slice, QuickScout still exposed operator intent poorly:

- return behavior existed in the backend but was effectively hidden in the UI
- the monitor action bar still suggested fixed RTL semantics
- planning started from raw numeric inputs instead of mission doctrine defaults

That was acceptable for the PoC, but not for a clean operator workflow.

This slice makes the operator intent explicit and durable:

- planning profiles now set consistent default survey parameters
- end behavior is visible before launch
- recovered workspaces restore that behavior cleanly
- monitor controls now align with the chosen mission end policy

## Validation

Focused Hetzner React validation:

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

- [DronePositionMap.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/DronePositionMap.js) still reports an older `useMemo` dependency warning

## Important Behavior Changes

- QuickScout planning no longer hides the mission end behavior behind a backend default
- QuickScout plan requests now carry `return_behavior` explicitly
- recovered missions restore their saved end behavior
- monitor end-mission controls no longer imply “always RTL”
- operators can begin from doctrine-style defaults without losing access to the lower-level survey controls

## Remaining Debt After This Slice

- planning is still polygon-first; richer search template geometry is still ahead
- mission briefing metadata and search doctrine summaries are still ahead
- QuickScout `resume` is still not a true FC-backed resume path
- QuickScout SITL validator/template is still deferred until the mission workflow stabilizes further

## Recommended Next Slice

QuickScout Phase 6 should add mission briefing structure on top of the now-clean setup shell:

- operation type / objective metadata
- compact mission brief summary before launch
- clearer pre-launch readiness checks for the selected drone set
- groundwork for later SITL mission-template validation

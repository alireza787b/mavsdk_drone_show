# QuickScout Monitor Package Context Phase 12

Date: 2026-04-08
Repo baseline: `6e5b3af5`
Status: complete, focused Hetzner frontend validation green

## Goal

Carry the new QuickScout template-aware doctrine from planning and launch review into monitor mode.

Before this slice, QuickScout monitor mode dropped too much mission-package context after launch:

- operators could see drone states and POIs
- but they could not easily see what search doctrine was currently in flight
- corridor, point, and polygon missions all looked too similar once the mission moved into monitor mode

This slice restores that mission-package context at the active-monitor stage.

## What Changed

- added [quickScoutMissionPresentation.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutMissionPresentation.js) as a shared QuickScout presentation utility for:
  - template labels
  - formatted area and duration summaries
  - template-aware geometry summary chips and doctrine text
- refactored [QuickScoutLaunchReview.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/QuickScoutLaunchReview.js) onto that shared utility so launch review and monitor mode now describe mission packages from one presentation seam instead of drifting again
- updated [MissionMonitorSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionMonitorSidebar.js) so monitor mode now shows:
  - mission label
  - template
  - package area
  - estimated coverage time
  - template-aware geometry/doctrine summary
  - mission brief, when present
- updated [QuickScoutPage.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js) so the monitor sidebar receives the recovered mission-package context instead of only live drone states
- added focused component coverage in:
  - [MissionMonitorSidebar.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionMonitorSidebar.test.js)
  - [QuickScoutLaunchReview.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/QuickScoutLaunchReview.test.js)

## Why This Slice Matters

The QuickScout redesign brief called for stage 6 to be a real search-operations monitor, not just a list of drones and POIs.

That means an operator must be able to reopen a mission and immediately understand:

- what search doctrine was launched
- what geometry and footprint were approved
- how that package relates to the live aircraft they are now monitoring

This slice closes that gap without changing backend mission semantics yet.

## Validation

Focused Hetzner frontend validation:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync/app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watch=false \
  src/components/sar/QuickScoutLaunchReview.test.js \
  src/components/sar/MissionMonitorSidebar.test.js \
  src/pages/QuickScoutPage.test.js \
  src/utilities/quickScoutPlanningSignature.test.js \
  src/utilities/quickScoutSearchGeometry.test.js
```

Result:

- `5` suites passed
- `19` tests passed

Hetzner production build:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync/app/dashboard/drone-dashboard
npm run build
```

Result:

- build passed

## Important Behavior Changes

- monitor mode now keeps mission-package context visible after launch instead of collapsing the operator view down to drone states only
- corridor, point, and polygon QuickScout missions are now distinguishable in monitor mode by mission doctrine, not just by remembered setup
- launch review and monitor now share one QuickScout presentation seam for template/geometry summaries

## Remaining Debt After This Slice

- QuickScout execution semantics are still lighter than the redesign brief, especially around tracked launch outcome detail and richer search-progress doctrine
- QuickScout still does not have SITL validation coverage
- additional search templates and richer monitor-state language are still ahead

## Recommended Next Slice

QuickScout Phase 13 should move from presentation into execution semantics:

- make launch/control outcome messaging more explicit for active missions
- tighten mission-status semantics beyond generic coverage percentage
- prepare the subsystem for future SITL validation against real operator flows

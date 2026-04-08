# QuickScout Launch Review Phase 7

Date: 2026-04-08
Repo baseline: `5172f2fc`
Status: complete, focused Hetzner frontend validation green

## Goal

Introduce the first real QuickScout prelaunch review layer so operators can:

- review the generated search package before launch
- see live assigned-aircraft readiness in the same workflow
- detect when mission inputs drift away from the last computed package
- avoid launching a stale or obviously blocked package by accident

## What Changed

- added a stable planning-signature utility in [quickScoutPlanningSignature.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutPlanningSignature.js)
- added a QuickScout-specific readiness utility in [quickScoutLaunchReadiness.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutLaunchReadiness.js)
- added focused utility tests in:
  - [quickScoutPlanningSignature.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutPlanningSignature.test.js)
  - [quickScoutLaunchReadiness.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutLaunchReadiness.test.js)
- added a new reusable prelaunch review surface in [QuickScoutLaunchReview.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/QuickScoutLaunchReview.js)
- updated [MissionPlanSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionPlanSidebar.js) so the planning sidebar now:
  - shows a launch-review card once a package exists
  - switches the compute button to `Recompute Plan` when current inputs no longer match the last computed package
  - blocks the launch button when the package is stale or the assigned-aircraft set is not launch-ready
- updated [QuickScoutPage.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js) so the page now:
  - tracks the signature of the last computed or recovered package
  - derives `planNeedsRecompute` when the operator changes setup after compute
  - derives QuickScout launch readiness from the current package target set
  - restores the computed-package signature when reopening saved missions
- reused the shared [CommandPreflightSummary.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/CommandPreflightSummary.js) inside the QuickScout launch review so QuickScout now inherits the same link/readiness/arm/git review model used elsewhere in MDS
- expanded [QuickScoutPage.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/pages/QuickScoutPage.test.js) to verify the stale-plan recompute behavior
- updated [QuickScout.css](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/styles/QuickScout.css) for the new launch-review summary, issue blocks, and responsive review layout

## Why This Slice Matters

Before this slice, QuickScout still let operators drift into a bad launch posture:

- change targets or mission notes after compute
- keep seeing the old computed package
- still have a live launch affordance

That is not acceptable for a distributed search mission where the package is built for a specific aircraft set and mission setup.

This slice makes the operator workflow more disciplined:

- the current package stays visible for comparison
- but the product now knows when it is stale
- launch review becomes an explicit stage instead of only a button under the form
- live aircraft readiness is shown in the same review path rather than hidden elsewhere

## Validation

Focused Hetzner frontend validation:

```bash
cd app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watch=false \
  src/pages/QuickScoutPage.test.js \
  src/services/sarApiService.test.js \
  src/utilities/quickScoutProfiles.test.js \
  src/utilities/quickScoutPlanningSignature.test.js \
  src/utilities/quickScoutLaunchReadiness.test.js
```

Result:

- `5` suites passed
- `19` tests passed

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

- QuickScout plan-mode launch is no longer just “compute once and send whenever”
- if the operator changes the search package inputs after compute, the package becomes stale and must be recomputed before launch
- QuickScout now shows a dedicated launch-review section with:
  - mission label / profile / area / ETA
  - mission brief
  - package settings
  - QuickScout-specific blockers/advisories
  - the shared live preflight summary for the assigned aircraft set
- the launch button is now gated by:
  - an existing computed package
  - no package drift
  - no launch blockers in the assigned target set

## Remaining Debt After This Slice

- QuickScout still needs richer mission templates beyond polygon area sweep
- the launch-review stage is now real, but monitor/status still needs deeper search-operations semantics later
- `resume` is still not a true FC-backed resume path
- QuickScout SITL validator/template is still deferred until the operator workflow stabilizes further

## Recommended Next Slice

QuickScout Phase 8 should start the real planner/template expansion:

- add explicit mission type selection in the operator workflow
- introduce the first second planner family beyond area sweep
- recommended V1 next target: last-known-point search

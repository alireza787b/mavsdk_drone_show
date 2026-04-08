# QuickScout Template-Aware Launch Review Phase 11

Date: 2026-04-08
Repo baseline: `b4c62b2e`
Status: complete, focused Hetzner frontend validation green

## Goal

Bring the QuickScout launch-review stage up to the same template-aware standard as the planning stage.

After Phase 10, QuickScout could author and preview corridor search correctly, but the launch review still described every mission package as if it were the same generic coverage job. That was not good enough for operator workflow discipline.

This slice makes launch review reflect the selected mission doctrine before dispatch.

## What Changed

- updated [QuickScoutLaunchReview.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/QuickScoutLaunchReview.js) so launch review now:
  - shows `Template` as a first-class mission metric
  - renders a dedicated geometry/doctrine summary card before launch
  - describes corridor, point-centered, and polygon packages with template-specific language
  - shows corridor-specific route, track length, width, and footprint context
  - shows point-search center/radius context instead of generic package-only copy
  - moves `Profile` into package-settings detail chips so template identity stays more prominent
- updated [MissionPlanSidebar.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/MissionPlanSidebar.js) so the launch-review card receives:
  - `missionTemplate`
  - `searchArea`
  - `searchCenter`
  - `searchRadiusM`
  - `searchPath`
  - `corridorWidthM`
- extended [quickScoutSearchGeometry.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutSearchGeometry.js) with reusable `calculateSearchPathLengthM()` so corridor launch review can show operator-scale route length without duplicating distance math
- expanded focused coverage in:
  - [QuickScoutLaunchReview.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/sar/QuickScoutLaunchReview.test.js)
  - [quickScoutSearchGeometry.test.js](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/utilities/quickScoutSearchGeometry.test.js)

## Why This Slice Matters

QuickScout’s redesign brief called for a staged workflow:

1. choose mission type
2. define scenario inputs
3. generate package
4. review
5. launch

Phase 10 improved stages 1 to 3 for corridor search, but stage 4 was still too generic. That created a real operator-risk gap:

- a point-centered search package looked too similar to a corridor package
- the review card did not explain what geometry doctrine would actually be flown
- critical launch context stayed hidden in planning inputs instead of being summarized at the decision point

This slice closes that gap by making launch review speak the selected search template explicitly.

## Validation

Focused Hetzner frontend validation:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync/app/dashboard/drone-dashboard
CI=true npm test -- --runInBand --watch=false \
  src/components/sar/QuickScoutLaunchReview.test.js \
  src/pages/QuickScoutPage.test.js \
  src/utilities/quickScoutPlanningSignature.test.js \
  src/utilities/quickScoutSearchGeometry.test.js
```

Result:

- `4` suites passed
- `18` tests passed

Hetzner production build:

```bash
cd /root/mavsdk_drone_show_main_candidate_clean_sync/app/dashboard/drone-dashboard
npm run build
```

Result:

- build passed

## Important Behavior Changes

- launch review now reflects the selected QuickScout mission doctrine instead of presenting all search packages as one generic pattern
- corridor packages now show:
  - route-point count
  - route length
  - corridor width
  - buffered footprint
- point-centered packages now show:
  - report center
  - search radius
  - resulting footprint
- profile remains visible, but template identity is now more prominent in the decision surface

## Remaining Debt After This Slice

- QuickScout still needs deeper launch/execution semantics and monitor-state doctrine
- QuickScout still does not have SITL validation coverage
- additional search templates such as sector or standoff observation are still ahead

## Recommended Next Slice

QuickScout Phase 12 should deepen execution doctrine instead of adding more geometry first:

- template-aware launch outcome messaging
- stronger monitor-stage mission semantics
- clearer progression from computed package to active search operation

## 2026-04-06 Mission Config and Command Copy Cleanup

### Context

This checkpoint closes the remaining high-signal UI cleanup from the `/root/mds_review` intake after:

- Phase 1: Mission Config architecture reset
- Phase 2: shared operator scope
- Phase 3: trajectory authoring-first redesign

The remaining accepted issues were:

1. Mission Config still felt too top-heavy and wordy.
2. Command / mission surfaces still carried more explanatory copy than an operator workflow should show by default.
3. Custom Show still had dark/light readability drift because several MUI surfaces were falling back to default theme colors.
4. Trajectory compact behavior still needed to apply to tablet-width layouts, not just phone width.

### Implemented

#### Mission Config shell compression

- shortened the page subtitle and removed the old static focus chips
- converted the primary strip into an `Assignment wall` workspace status bar with a live review headline
- replaced the long visible-card help line with a terse search summary
- grouped issue filters and cluster scope into one filter rail
- converted duplicate-slot / duplicate-hardware / role-swap / origin warnings into compact alert rows
- reduced the assignment-wall panel header to title + visible-count only
- added a launch-layout `Plot` / `Map` switch so operators can review deviations in the engineering plot or a geographic map from the same page

#### Command / mission copy cleanup

- shortened Command Control target guidance and the visible-cards-to-scope bridge copy
- shortened mission-card notes in Mission Trigger so the action grid reads as a launch surface instead of a help article

#### Custom Show token cleanup

- shortened the page copy so the expert-only intent is still clear without over-explaining the protocol path
- forced dashboard token colors for MUI typography, buttons, alerts, and chips to stop dark/light readability drift

#### Trajectory tablet compactness

- extended compact authoring-first behavior from `<=768px` to `<=1024px` in:
  - `TrajectoryPlanning`
  - `SwarmTrajectory`

This keeps tablet-width operators on the same authoring-first flow that already worked on phones.

### Files changed

- `app/dashboard/drone-dashboard/src/components/CommandSender.js`
- `app/dashboard/drone-dashboard/src/components/MissionTrigger.js`
- `app/dashboard/drone-dashboard/src/pages/CustomShowPage.js`
- `app/dashboard/drone-dashboard/src/pages/MissionConfig.js`
- `app/dashboard/drone-dashboard/src/pages/SwarmTrajectory.js`
- `app/dashboard/drone-dashboard/src/pages/TrajectoryPlanning.js`
- `app/dashboard/drone-dashboard/src/styles/CustomShowPage.css`
- `app/dashboard/drone-dashboard/src/styles/MissionConfig.css`
- `CHANGELOG.md`

### Validation

#### Local

- `git diff --check`
  - passed

#### Hetzner focused React validation

- `CI=true npm test -- --runInBand --watch=false src/components/CommandSender.test.js src/components/MissionTrigger.test.js src/components/ControlButtons.test.js src/components/DroneConfigCard.test.js src/pages/TrajectoryPlanning.test.js src/pages/SwarmTrajectory.test.js src/components/trajectory/SwarmTrajectoryWorkspaceSummary.test.js`
  - `7` suites passed
  - `23` tests passed

#### Hetzner production build

- `npm run build`
  - compiled successfully

### Review conclusion

This checkpoint is tester-ready for the reviewed dashboard / Mission Config / trajectory / command surfaces.

Deferred, but not blocking this tester handoff:

- advanced integrated SITL scenarios (Phase 5)
- QuickScout-specific UI/API follow-up
- deeper optional card/CSS cleanup that does not affect the accepted reviewer issues

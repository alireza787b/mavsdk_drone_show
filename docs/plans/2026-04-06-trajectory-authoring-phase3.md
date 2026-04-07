## 2026-04-06 Trajectory Authoring Phase 3

### Context

External review feedback showed that both Trajectory Planning and Swarm Trajectory still spent too much vertical space on workflow/policy explanation before the operator reached the primary working surface, especially on mobile/tablet.

### Landed

#### Trajectory Planning

- compact viewports now keep the authoring surface ahead of the review/policy blocks:
  - the map workspace stays primary
  - segment review and workflow brief move below the main authoring surface on compact screens
- the follow-up cleanup removed the remaining desktop front-loading too:
  - review surfaces now dock below the map/waypoint workspace instead of appearing above it
  - the workflow brief always uses one compact disclosure instead of a separate expanded desktop block
- the workflow brief now has a dedicated compact `<details>` form for small screens:
  - `Route review & policy`
- added a `LeafletResizeBridge` plus generalized active-map resize handling so layout changes no longer leave Leaflet or Mapbox with stale dimensions after viewport/scene/content changes
- Leaflet and Mapbox fly-to behavior now stays aligned when selecting segments or searching locations
- waypoint instruction overlays now use shorter action-biased copy so the authoring surface reads faster under low-bandwidth/operator-stress conditions

#### Swarm Trajectory

- the duplicated top-of-page operator-flow banner is removed:
  - related mission tools are now exposed as one compact link row inside the workspace summary
- workspace doctrine/stage review now collapses behind one compact summary on every viewport:
  - `Workspace review & policy`
- the page header and status card now use shorter copy:
  - `Workspace Status`
  - `Upload leader paths, regenerate follower outputs, and confirm the launch package.`

### Build / test fixes surfaced during validation

- the planner refactor initially created `trajectorySegmentReviewBlock` before `handleSelectSegment` existed; that initialization-order bug is fixed
- `TrajectoryPlanning.test.js` now mocks the new `react-leaflet` `useMap()` dependency and explicitly waits for the async runtime-policy load so the focused suite stays clean
- the follow-up authoring-first pass introduced additional related-tool links, so the focused Swarm Trajectory tests now assert the compact summary behavior without assuming only one unique route link instance exists in the DOM

### Validation

- local `git diff --check`: passed
- Hetzner focused Jest:
  - `src/pages/TrajectoryPlanning.test.js`
  - `src/pages/SwarmTrajectory.test.js`
  - `src/components/trajectory/SwarmTrajectoryWorkspaceSummary.test.js`
  - `src/components/trajectory/TrajectorySegmentReview.test.js`
  - result: `4` suites passed, `15` tests passed
- Hetzner production build:
  - result: compiled successfully

### Next

- broader copy/token cleanup across mission/action/custom-show surfaces
- then advanced integrated SITL scenario expansion once the operator-facing flow stabilizes

## 2026-04-06 Trajectory Authoring Phase 3

### Context

External review feedback showed that both Trajectory Planning and Swarm Trajectory still spent too much vertical space on workflow/policy explanation before the operator reached the primary working surface, especially on mobile/tablet.

### Landed

#### Trajectory Planning

- compact viewports now keep the authoring surface ahead of the review/policy blocks:
  - the map workspace stays primary
  - segment review and workflow brief move below the main authoring surface on compact screens
- the workflow brief now has a dedicated compact `<details>` form for small screens:
  - `Route brief & policy`
- added a `LeafletResizeBridge` plus generalized active-map resize handling so layout changes no longer leave Leaflet or Mapbox with stale dimensions after viewport/scene/content changes
- Leaflet and Mapbox fly-to behavior now stays aligned when selecting segments or searching locations

#### Swarm Trajectory

- compact viewports now collapse the operator flow into one expandable block:
  - `Operator flow & package review`
- workspace doctrine/stage review now collapses behind one compact summary on small screens:
  - `Workspace review & policy`
- mobile layout now stays left-aligned and denser for operator use instead of centering the header/status shell
- mobile status metrics are now a readable 2-column grid instead of four cramped micro-cards

### Build / test fixes surfaced during validation

- the planner refactor initially created `trajectorySegmentReviewBlock` before `handleSelectSegment` existed; that initialization-order bug is fixed
- `TrajectoryPlanning.test.js` now mocks the new `react-leaflet` `useMap()` dependency and explicitly waits for the async runtime-policy load so the focused suite stays clean

### Validation

- local `git diff --check`: passed
- Hetzner focused Jest:
  - `src/pages/TrajectoryPlanning.test.js`
  - `src/pages/SwarmTrajectory.test.js`
  - `src/components/trajectory/SwarmTrajectoryWorkspaceSummary.test.js`
  - result: `3` suites passed, `10` tests passed
- Hetzner production build:
  - result: compiled successfully

### Next

- Mission Config shell compression using the compact-top-shell audit findings
- then broader copy/token cleanup across mission/action/custom-show surfaces

## 2026-04-06 Review Intake and UI Phase Plan

### Current status

- Phase 1: Mission Config architecture reset, complete
- Phase 2: shared operator scope model, complete
- Phase 3: trajectory authoring-first redesign, complete
- Phase 4: remaining operator-copy/token cleanup, complete
- Phase 5: advanced integrated SITL scenarios, pending after the next tester handoff

### Context

External tester feedback was received in `/root/mds_review/`:

- `mds_review.txt`
- `mds_condif_cards.jpg`
- `mds_swarm_trajectory.jpg`

The review was compared against the current dashboard implementation and the recent Precision Move work.

### Immediate triage decisions

#### Accepted as real issues

1. Mission Config card architecture is too verbose and space-heavy.
2. Mission Config puts too much explanation ahead of the actual assignment workspace.
3. Trajectory Planning still front-loads too much review/policy content before the primary authoring surface.
4. Trajectory Planning / Swarm Trajectory mobile workflow is still not authoring-first enough.
5. Some copy across Mission Trigger / mission details remains too verbose for at-a-glance operator use.
6. Custom Show still needs a token/readability audit in dark/light themes.
7. Dashboard card filtering and Command Control targeting are too isolated from the operator’s point of view.

#### Accepted with design adjustment

1. **Dashboard card filters vs command scope**
   - Do **not** make card visibility silently become dispatch scope.
   - That is too easy to misuse in real operations.
   - Instead, introduce a shared operator scope model with explicit handoff actions:
     - `Use visible cards as dispatch scope`
     - `Show current dispatch scope on cards`
     - optional per-card include/exclude markers
   - Dispatch scope must remain explicit and reviewable.

2. **Mission Config map support**
   - Add a reusable plot/map toggle for the launch-layout panel.
   - Keep the current plot as the default engineering view.
   - Add a map view when geographic context is useful.

3. **Mission Config export controls**
   - JSON stays primary.
   - CSV export is legacy and should be demoted out of the top-level primary action strip unless a workflow still depends on it.

#### Not treated as product bugs

1. `git-sync` stale lock removal warning during manual SITL startup
   - benign recovery behavior unless it repeats persistently with a live owning PID
2. manual `python app_fastapi.py` returning `address already in use`
   - expected when the GCS service is already running on port `5000`

### Codebase-based findings

#### Mission Config

- The operator task starts too low on the page.
- `MissionConfig.js` currently renders:
  - page header
  - identity explainer
  - control buttons
  - warnings
  - origin/GCS modals
  - mission layout
  - filters
  - stats
  - preview-only heading control
  - then the card workspace
- `DroneConfigCard.js` renders nearly every data domain at once in read-only mode:
  - identity
  - custom fields
  - transport/runtime
  - slot status
  - runtime connectivity
  - git status
  - action controls
- This is mostly an information-architecture / presentation refactor, not a data-flow rewrite.

#### Trajectory Planning / Swarm Trajectory

- The page still gives too much vertical budget to workflow brief, stage cards, and policy notes before the operator gets to the actual map authoring surface.
- Mobile CSS tries to reorder the map container above review blocks, but the current result is still not consistently authoring-first enough for testers.
- The likely fix is not “more guidance.” It is:
  - compress guidance
  - collapse policy
  - move the map/workspace to the first working position on mobile
  - keep the route/waypoint tools immediately visible

#### Dashboard / Command scope

- Current implementation explicitly tells the user that card-wall filters never affect dispatch scope.
- That is technically clear but operationally too fragmented.
- We should unify the model without creating unsafe implicit scope changes.

### Proposed implementation phases

## Phase 1: Mission Config architecture reset

### Goal

Make Mission Config usable as an operator workspace instead of a long documentation surface.

### Planned changes

- move the assignment workspace directly under a sticky ops bar
- demote identity guide and preview-only heading controls into collapsible help/advanced sections
- redesign cards into `Compact` and `Expanded` views
- compact default card should show only:
  - `Pn|Hm`
  - heartbeat/readiness state
  - slot status summary
  - promoted alias/callsign if present
  - high-value exception chips
  - one primary action
- move heavy details into expansion or inspector:
  - runtime transport
  - connectivity
  - git details
  - extended metadata
- add issue-first filters:
  - offline
  - mismatch
  - role swap
  - duplicate slot
  - new
- add plot/map toggle to the launch-layout panel
- demote CSV export from the main top-level control cluster

### Expected file focus

- `app/dashboard/drone-dashboard/src/pages/MissionConfig.js`
- `app/dashboard/drone-dashboard/src/components/DroneConfigCard.js`
- `app/dashboard/drone-dashboard/src/styles/MissionConfig.css`
- `app/dashboard/drone-dashboard/src/styles/DroneConfigCard.css`

## Phase 2: Shared operator scope model

### Goal

Unify operator selection across Overview, Mission Config, Swarm Design, and Command Control without making dispatch scope implicit or dangerous.

### Planned changes

- introduce a shared fleet-scope store / model
- keep `visibility filter` separate from `dispatch scope`
- add explicit bridging actions:
  - `Use visible cards as command scope`
  - `Highlight current command scope on cards`
  - `Clear command scope`
  - `Select all visible`
- allow per-card add/remove to current command scope
- expose minimal command-scope marker on cards
- reuse the same scope model in Precision Move and other actions

### Expected file focus

- `app/dashboard/drone-dashboard/src/pages/Overview.js`
- `app/dashboard/drone-dashboard/src/components/CommandSender.js`
- `app/dashboard/drone-dashboard/src/components/DroneWidget.js`
- `app/dashboard/drone-dashboard/src/pages/MissionConfig.js`
- `app/dashboard/drone-dashboard/src/pages/SwarmDesign.js`
- likely new shared scope context/utilities

## Phase 3: Trajectory Planning / Swarm Trajectory authoring-first redesign

### Goal

Make route authoring and package review map-first, especially on mobile/tablet.

### Planned changes

- put the primary map/plot workspace ahead of long review blocks on mobile
- compress workflow brief into fewer critical cards
- collapse execution-policy notes by default
- make the authoring tools visible without scrolling through policy text
- review Swarm Trajectory page copy and package workflow the same way
- keep reusable map-provider patterns aligned with the rest of the app

### Expected file focus

- `app/dashboard/drone-dashboard/src/pages/TrajectoryPlanning.js`
- `app/dashboard/drone-dashboard/src/styles/TrajectoryPlanning.css`
- `app/dashboard/drone-dashboard/src/pages/SwarmTrajectory.js`
- `app/dashboard/drone-dashboard/src/styles/SwarmTrajectory.css`
- selected components under `src/components/trajectory/`

## Phase 4: Copy/token cleanup across remaining mission surfaces

### Goal

Reduce operator-facing verbosity and fix token/readability gaps without hiding important safety information.

### Planned changes

- Mission Trigger card copy reduction
- Mission Details / preflight copy audit
- Custom Show dark/light token and contrast audit
- replace static verbose text with:
  - shorter primary copy
  - foldables
  - tooltips/popovers where appropriate
  - links to docs/guides for deep detail

## Phase 5: Advanced integrated SITL scenario expansion

### Goal

After the UI/operator workflow stabilizes, extend the SITL validation library with more complex multi-mode real-operator scenarios.

### Planned additions

- mixed mission-family scenario plans
- command override / supersession drills
- leader/follower reassignment while another mission family is active
- precision-move around an active leader to stress Smart Swarm behavior
- full command/notification/API/operator loop validation from the dashboard surface

This remains **after** the current UI/operator redesign slices, not before.

### Recommended order

1. Phase 1: Mission Config architecture reset
2. Phase 2: Shared operator scope model
3. Phase 3: Trajectory Planning / Swarm Trajectory authoring-first redesign
4. Phase 4: Copy/token cleanup across remaining mission surfaces
5. Phase 5: Advanced SITL scenario expansion

### Validation rule at each checkpoint

At the end of each phase:

- re-run focused React/unit tests
- re-check affected docs/guides/changelog
- push a checkpoint to `main-candidate`
- sync Hetzner when the phase affects live tester-facing behavior
- only then continue to the next slice

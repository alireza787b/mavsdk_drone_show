# Predeploy UI/UX + Frontend Refactor Audit Plan

Date: 2026-04-25
Scope: official MDS frontend first, then private client sync after approval
Mode: planning only; no implementation in this pass

## Executive Summary

The current system is functionally close, but the frontend is not yet consistent enough for a polished predeploy release. The main issue is not one page. It is accumulated interface drift:

- multiple page layouts with different header, hero, summary, toolbar, banner, and empty-state styles
- too much always-visible explanatory text on several operational pages
- duplicate modal, notification, tooltip, card, and status primitives
- hardcoded colors, shadows, z-indexes, gradients, and old theme conventions mixed with the newer design token system
- mixed icon libraries and inconsistent icon/action semantics
- several large page files that combine API orchestration, view-model logic, markup, and styling decisions
- docs links exist in some places but not as a consistent operator contract

Recommendation: do not do a single giant rewrite. Execute controlled slices, page by page, with a shared operator shell and shared primitives. Every slice must pass tests/build and update docs/tests where behavior or guidance changes.

## Product Standard

This refactor should optimize for a high-workload drone operator:

- visible text should be short, status-first, and action-oriented
- secondary explanations should move into tooltips, expandable info, or linked docs
- every warning should answer: what is wrong, what is impacted, what action is available
- destructive actions must stay explicit and confirmable
- SITL/REAL state must remain impossible to confuse
- fleet-scale pages must work from 1 drone to hundreds
- mobile/tablet must support touch-first operation without hover-only dependencies
- operators should not need terminal access for common actions

## Non-Goals For This Phase

- Do not redesign backend architecture unless a frontend cleanup exposes an API contract bug.
- Do not migrate off Create React App during this predeploy phase unless build/security checks force it.
- Do not upgrade major libraries blindly. Dependency work must be isolated and tested.
- Do not remove operator-critical details; relocate them to drill-down surfaces.
- Do not leak private-client-specific data into official docs, screenshots, examples, or public releases.

## Initial Findings

## A. Page Inventory

Top-level routes currently loaded from `App.js`:

- `/` and `/mission-control`: `Overview`
- `/mission-config`: `MissionConfig`
- `/fleet-enrollment`: `FleetEnrollmentPage`
- `/fleet-ops`: `FleetOpsPage`
- `/px4-parameters`: `Px4ParametersPage`
- `/globe-view`: `GlobeView`
- `/runtime-admin`: `RuntimeAdminPage`
- `/sitl-control`: `SitlControlPage`
- `/logs`: `LogViewer`
- `/drone-show-design` and `/manage-drone-show`: `ManageDroneShow`
- `/custom-show`: `CustomShowPage`
- `/swarm-design`: `SwarmDesign`
- `/trajectory-planning`: `TrajectoryPlanning`
- `/swarm-trajectory`: `SwarmTrajectory`
- `/quickscout`: `QuickScoutPage`
- `/drone-detail`: `DroneDetail`

## B. Files With Highest Refactor Risk

Large files that need staged extraction, not quick edits:

- `pages/SitlControlPage.js`: about 2200 lines
- `pages/Px4ParametersPage.js`: about 2000 lines
- `pages/TrajectoryPlanning.js`: about 1660 lines
- `components/DroneConfigCard.js`: about 1700 lines
- `pages/MissionConfig.js`: about 1400 lines
- `pages/QuickScoutPage.js`: about 1350 lines
- `pages/SwarmTrajectory.js`: about 1300 lines
- `components/PrecisionMoveDialog.js`: about 1200 lines
- `components/MissionDetails.js`: about 1140 lines
- `components/CommandSender.js`: about 970 lines

These are not automatically bad, but they are harder to reason about and more likely to drift in UI/UX, tests, and behavior.

## C. Duplicate UI Primitives

Modal/dialog duplication:

- `ConfirmModal.js`
- `ConfirmationDialog.js`
- `ConfirmationModal.js`
- `Modal.js`
- page-local `ConfirmDialog` in `SitlControlPage.js`
- multiple domain dialogs with their own patterns

Notification duplication:

- `Notification.js`
- `MissionNotification.js`
- `react-toastify`
- page-local banners/notices in several pages

Tooltip/help duplication:

- `InfoHint.js`
- native `title`
- `react-tooltip`
- page-local hint classes

Recommendation: converge on shared primitives before polishing every page.

## D. Styling Drift

Current risks:

- `DesignTokens.css` is the intended authority, but many CSS files still hardcode colors, z-indexes, shadows, and gradients.
- `themes.css` still contains old `day/night` variables that do not match the active light/dark token model.
- Some components use inline styles with hardcoded colors.
- Several z-index values bypass token names and have been patched locally.
- Visual density differs widely between pages.

Recommendation: add a small design-system layer, then migrate pages into it.

## E. Dependency Surface

Current package surface includes:

- React 18, CRA/react-scripts 5
- MUI 6, MUI Data Grid 7
- react-icons, FontAwesome, MUI icons
- Leaflet, Mapbox, Mapbox Draw, react-map-gl
- three, drei, plotly, cytoscape
- styled-components is used by `ConfirmModal.js` but is not listed in `package.json`, which is a concrete cleanup item.

Recommendation:

- short term: remove unused/mismatched dependencies only after import verification
- medium term: choose one primary icon system
- long term: plan a separate CRA-to-Vite or equivalent migration, not inside this predeploy UI polish unless required

## UX Doctrine

Use a consistent three-layer information model:

1. Always visible: compact state, counts, icons, labels, primary action
2. On hover/tap/info icon: meaning, risk, “why”, secondary metadata
3. Docs/deep detail: setup instructions, workflows, advanced diagnostics

Every page should have:

- compact page header
- mode/runtime awareness where relevant
- summary strip with icon metrics
- toolbar/action row
- main work surface
- drill-down or expandable detail
- one docs/help affordance if a guide exists
- consistent empty/loading/error states

## Proposed Shared Primitives

Build or normalize these first:

- `PageShell`: compact title, icon, short subtitle, docs link, optional mode badge
- `MetricStrip` / `MetricPill`: consistent status summaries
- `OperatorCard`: compact card base with density variants
- `StatusBadge`: shared tones and icon/text rules
- `ActionIconButton`: icon-first buttons with label/tooltip/accessibility
- `InfoHint`: standard help popover; replace random long helper copy
- `OperatorNotice`: warning/error/info/success banners with action slot
- `EmptyState`: compact no-data/no-capability/no-filter result
- `ConfirmDialog`: one canonical modal primitive
- `DataToolbar`: search/filter/scope/actions row
- `DocsLink`: route-aware link to repo docs

These primitives should use `DesignTokens.css` only. No new hardcoded colors unless added as tokens.

## Ordered Implementation Plan

## Phase 0: Guardrails And Audit Automation

Goal: make the cleanup measurable before changing many pages.

Slices:

1. Create frontend UI audit checklist in docs.
2. Add a lightweight audit script for:
   - hardcoded colors outside token files
   - hardcoded z-index outside tokens
   - direct `title` usage where `InfoHint` or accessible tooltip is preferred
   - duplicate modal imports
   - missing docs-link metadata for top-level routes
3. Add a route-to-doc mapping file used by UI and docs tests.
4. Add page smoke test matrix: desktop, mobile, dark, light.

Acceptance:

- audit script runs locally and in CI-style command
- no product behavior changed
- initial debt list is generated and versioned

## Phase 1: Design-System Foundation

Goal: stop visual drift before page-by-page cleanup.

Slices:

1. Normalize tokens:
   - remove or quarantine old `themes.css` day/night model
   - add missing z-index tokens used by overlays/maps/globe
   - add density, card, badge, action, and focus-ring tokens
2. Implement shared primitives:
   - `PageShell`
   - `OperatorNotice`
   - `StatusBadge`
   - `ActionIconButton`
   - `MetricStrip`
   - `ConfirmDialog`
   - `DocsLink`
3. Consolidate modal/notification strategy:
   - retain domain-specific dialogs only when they have domain behavior
   - migrate generic confirmations to one primitive
   - keep `react-toastify` for transient feedback, but banners for persistent operational state

Acceptance:

- primitives have tests
- existing pages still render
- no regression in mobile sidebar, toast placement, runtime badge, or card overlays

## Phase 2: Navigation, Shell, Loading, Toasts

Goal: make every page feel like one application.

Slices:

1. Sidebar/menu:
   - verify groups, icons, active state, mobile scroll, runtime pill
   - remove duplicate runtime text outside sidebar
   - ensure all route labels are short and consistent
2. App loading:
   - keep radar-style loader, ensure reduced-motion support
   - make loading state consistent across lazy routes and data-loading pages
3. Toasts:
   - ensure mobile toasts never cover hamburger/top controls
   - standardize toast tone and text length
4. Docs/help:
   - add compact docs link per page if a guide exists
   - create docs gaps list where guide does not exist or is stale

Acceptance:

- mobile shell probe passes
- all routes reachable
- top-level docs links validated

## Phase 3: Mission-Critical Runtime Surfaces

Goal: polish the pages operators use under pressure first.

## 3A. Overview / Fleet Command Dashboard

Actions:

- reduce hero copy to short operator state
- keep fleet metrics and dispatch scope compact
- make command scope and visible filters clearly linked
- move verbose explanations to info icons
- ensure offline/degraded/never-seen states are visually distinct
- verify selected/unselected dispatch card styling at a glance
- keep command preflight and last command readable but compact

Acceptance:

- default visible command scope remains intact
- dispatch scope changes are obvious
- offline vs degraded vs ready are visually distinct on desktop/mobile

## 3B. CommandSender / PrecisionMove / Critical Commands

Actions:

- consolidate command cards into icon-first action groups
- keep confirmation wording explicit for dangerous actions
- reduce repeated scope text
- make scheduler/preflight state a compact badge/tooltip model
- ensure live command monitor does not flicker or duplicate command labels

Acceptance:

- existing command tests pass
- takeoff/hold/RTL/mission cancel flows retain guardrails

## 3C. Globe View / Map View

Actions:

- keep tactical card compact and mobile-safe
- standardize 3D/map controls as icon toolbar
- verify Mapbox/Leaflet fallback messaging is short and actionable
- link map config warning to mapbox guide
- preserve custom marker color behavior
- add touch probes for marker select, chip select, outside dismiss, controls, pan/zoom

Acceptance:

- mobile 3D top and bottom touch regions work
- outside tap dismisses selected card
- map and globe show consistent drone status semantics

## Phase 4: Configuration And Fleet Admin Surfaces

Goal: reduce confusion in pages with heavy setup/config flows.

## 4A. Mission Config

Actions:

- split into smaller components:
  - header/status
  - filter toolbar
  - pending enrollment
  - drone config grid
  - origin/heading controls
  - identity guide
  - secondary tools
- reduce always-visible identity guidance
- move drone-show-only plots/deviation details out of the general config path unless directly relevant
- make custom fields easier with template selector and compact docs/help
- verify real and SITL metadata display consistently

Acceptance:

- config editing still works
- candidate enrollment callouts still route correctly
- docs and tests align with new component boundaries

## 4B. Fleet Ops

Actions:

- clarify boundary: fleet-node administration, not GCS host runtime
- make tabs/action items linkable/actionable where safe
- show per-drone git, sidecar, and sync posture as compact compliance cards
- add planned actions for future profile push/open dashboard if backend APIs exist; otherwise show “not available” with docs link, not dead UI
- avoid raw secret/path exposure

Acceptance:

- user can understand which page handles GCS vs fleet nodes
- no private paths/tokens in normal UI
- drift state is visible without verbose paragraphs

## 4C. Runtime Admin

Actions:

- clarify boundary: GCS host administration only
- compact mode switcher and restart/update status
- keep SITL/REAL fencing explanation behind info icon/docs
- remove any drone-sidecar implication from GCS page
- keep self-update controls cautious and logged

Acceptance:

- no confusion with Fleet Ops
- pending restart/update state is obvious

## 4D. Fleet Enrollment

Actions:

- compact candidate cards
- make identity conflicts icon-first with detail drawer
- standardize accept/replace/repair/ignore dialogs
- ensure AI/headless workflow docs link is present

Acceptance:

- replacement vs new enrollment vs repair workflows remain distinct

## Phase 5: Specialist Mission Pages

Goal: preserve specialist workflows while reducing cognitive load.

## 5A. PX4 Parameters

Actions:

- keep compact list/table as primary
- move metadata limitation details into a small warning/info affordance
- remove duplicated parameter descriptions in dialog
- standardize docs-link behavior for PX4 docs and local MDS guide
- ensure mobile touch mode is not overly verbose

Acceptance:

- parameter read/write/profile tests pass
- metadata warning is actionable but not noisy

## 5B. QuickScout

Actions:

- separate plan, monitor, findings, and recovery surfaces visually
- reduce plan sidebar copy
- compact mission template cards
- make handoff/findings actions icon-first
- preserve SAR-specific safety language

Acceptance:

- existing QuickScout runtime and component tests pass

## 5C. Swarm Design

Actions:

- compact smart swarm summary
- reduce assignment card text
- keep graph/plots as drill-down or secondary
- verify top-leader/follower language consistency with docs

Acceptance:

- assignment CSV import/export remains unchanged

## 5D. Trajectory Planning

Actions:

- extract large page sections into route map, toolbar, waypoint authoring, validation, library, export, transfer
- convert repeated authoring notes to `InfoHint`/policy panel
- keep altitude/timing/heading safety checks visible only when relevant

Acceptance:

- map interactions, waypoint modal, library, export, and transfer tests pass

## 5E. Swarm Trajectory

Actions:

- compact process summary and launch review
- move long readiness explanations into expandable detail
- standardize status banners
- keep commit/export/launch actions strongly separated

Acceptance:

- launch package generation and review behavior unchanged

## 5F. Drone Show / Custom Show

Actions:

- remove redundant intro sections
- standardize import/export cards
- ensure custom CSV docs link is visible but compact
- verify drone-show-specific visuals do not leak into generic Mission Config

Acceptance:

- CSV import and custom show validation tests pass

## 5G. Log Viewer

Actions:

- keep filters and live/history state compact
- standardize log health bar and source tree states
- ensure export/onboard ulog dialogs use canonical dialog/action styles

Acceptance:

- log streaming/export tests pass

## Phase 6: Component Refactor Pass

Goal: reduce future maintenance cost after page surfaces are cleaned.

Priority components:

- `DroneConfigCard`: split field groups, custom field editor, status header, sidecar/network facts
- `CommandSender`: split target scope, mission actions, recent command monitor, confirmations
- `MissionDetails`: split mode, readiness, deviation, warnings, launch actions
- `PrecisionMoveDialog`: split state machine, form, live status, jog controls
- `VisualizationSection`: verify if still needed or can merge with globe/map page primitives
- `DroneWidget` and `TacticalDroneCard`: align compact fleet-card semantics
- Modal/notification primitives: remove unused duplicate files after migration

Acceptance:

- component tests updated or added
- no mixed old/new primitive usage for migrated areas

## Phase 7: API And Data Contract Cleanup If Exposed

Goal: fix backend/frontend contract inconsistencies discovered during UI cleanup.

Allowed backend/API work:

- add missing route metadata/docs URLs
- return page capability flags instead of hardcoded frontend assumptions
- add concise status fields for sidecars/git/runtime where UI currently assembles fragile text
- remove stale frontend parsing paths only after backend contract and tests confirm

Do not:

- change command semantics casually
- change SITL/REAL fencing without focused validation
- change drone bootstrap auth behavior in this UI-only phase unless a UI dependency requires a status endpoint

## Phase 8: Dependency And Build Hygiene

Goal: reduce risk without destabilizing the release.

Slices:

1. Static dependency inventory:
   - imports vs package.json
   - unused packages
   - packages used but not declared
   - duplicate icon stacks
2. Security/outdated audit:
   - run npm audit/outdated on Hetzner or approved environment
   - classify: patch-safe, minor-risk, major-migration
3. Dependency cleanup:
   - remove `styled-components` usage or explicitly add it only if retained
   - choose one primary icon stack for new work
   - do not force CRA/Vite migration in same release
4. Build hygiene:
   - ensure production build has no new warnings that matter
   - keep source maps policy unchanged unless release policy changes

Acceptance:

- `npm test` focused suites pass
- production build passes on Hetzner
- package-lock is clean and explainable

## Phase 9: Docs Alignment

Goal: every UI docs link points to a real, current guide.

Docs to review/update:

- `docs/README.md`
- `docs/QUICK_REFERENCE.md`
- `docs/guides/deployment-quick-reference.md`
- `docs/guides/runtime-config-sources.md`
- `docs/guides/fleet-ops.md`
- `docs/guides/fleet-sync-and-secrets.md`
- `docs/guides/sitl-control.md`
- `docs/guides/sitl-validation-platform.md`
- `docs/guides/mapbox-setup.md`
- `docs/px4-parameters.md`
- `docs/features/drone-show.md`
- `docs/features/smart-swarm.md`
- `docs/features/swarm-trajectory.md`
- `docs/quickscout.md`

Acceptance:

- no UI link points to stale/missing docs
- public docs contain no private data
- private docs can add client-specific notes only in the private repo

## Phase 10: Visual Regression And Release Closeout

Goal: verify the whole product before pushing final release tags.

Required checks:

- desktop and mobile screenshots for every top-level route
- dark/light theme screenshots for key pages
- mobile touch probes:
  - sidebar
  - command dispatch
  - globe/map card selection/dismiss
  - mission config card expand/collapse
  - PX4 parameter dialog
  - SITL control dialogs
- focused unit tests for changed components
- full frontend build on Hetzner
- backend health check
- SITL 4-drone ready check
- private repo sync verification

Release actions after approval and implementation:

- commit official
- push official `main-candidate`
- tag official release
- sync/cherry-pick to private client
- tag private release
- deploy latest to Hetzner
- keep SITL or REAL running as requested
- send final tester handoff with URL, mode, tag, known deferred items

## Page-By-Page Audit Checklist

For each page, check:

- Does the page have one compact header?
- Does the page explain its purpose in less than one short line?
- Are secondary explanations hidden behind info/help/docs?
- Are main actions icon-first with accessible labels/tooltips?
- Are dangerous actions visually distinct and confirmed?
- Does loading/error/empty state use shared primitives?
- Does mobile layout preserve action priority?
- Does the page use design tokens only?
- Does the page link to correct docs?
- Are tests aligned with the visible copy after compaction?

## Component Checklist

For each component, check:

- Is it domain-specific or a reusable primitive?
- Does it own API calls unnecessarily?
- Does it contain large inline view-model logic that should move to utilities?
- Does it duplicate an existing primitive?
- Does it use hardcoded color/z-index/spacing?
- Does it rely on hover without touch fallback?
- Does it expose accessible names for icon-only actions?
- Does it have focused tests if it controls safety-critical behavior?

## Deferred Debt Log For This Phase

These are important but should not block the UI cleanup unless directly touched:

- private/public authentication UX beyond status visibility
- GitHub App based auth replacement for PAT/deploy-key workflows
- full Pixeagle integration
- MCP/AI-agent control plane
- logo/branding system
- deeper command telemetry optimization
- full CRA-to-Vite migration
- 2D/3D marker asset gallery beyond current marker color
- smart-wifi-manager and mavlink-anywhere profile push APIs if not already complete
- complete visual regression automation in CI

## Recommended First Implementation Slice

Start with:

1. Phase 0 audit guardrails
2. Phase 1 shared primitives
3. Phase 2 shell/loading/toast/doc-link consistency

Reason:

- this prevents page-by-page edits from creating yet another design dialect
- it gives us measurable cleanup criteria
- it minimizes risk to command/runtime behavior before touching mission pages

After that, proceed in this order:

1. Overview + CommandSender + Globe/Map
2. Runtime Admin + Fleet Ops + Fleet Enrollment
3. Mission Config
4. PX4 Parameters
5. SITL Control
6. QuickScout
7. Show/Swarm/Trajectory specialist pages
8. dependency cleanup and release closeout

## Approval Gate

Before implementation starts, confirm:

- we should create the shared primitives first rather than visually patching individual pages
- CRA/Vite migration is deferred unless dependency audit forces it
- private client repo should only receive the approved official changes after official tests pass
- Hetzner remains the heavy build/test/deploy host
- Linode/local remains clean for code inspection and lightweight checks only

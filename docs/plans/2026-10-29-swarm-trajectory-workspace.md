# Swarm Trajectory workspace checkpoint

## Approved behavior

- One Plan / Operate workspace for Mission 4 precomputed global/MSL trajectories.
  This is not live Smart Swarm.
- Mission-owned Formation, independent of live Smart Swarm edits.
- Ground-start only. Airborne entry is deferred.
- Coordinated Pause/Resume must verify every participant, validate smooth re-entry,
  and resume one shared route clock. No subset or automatic resume. Return,
  landing and pilot takeover invalidate resume.
- Immediate Return stays visible; Managed Return is secondary.
- Builds, tests and SITL run on the verified remote validation host, not the
  resource-limited local VPS. Validation is isolated from production and aircraft;
  production restarts require a confirmed inactive flight window.

## Completed source slices

| Commit | Change |
|--------|--------|
| `c11e5782` | Validate full route before arming; explicit finite altitude and strictly increasing time. |
| `517a1d47` | Canonical package readiness and changed-output detection. |
| `b9ef956e` | Staged processing/rollback and recoverable leader-specific drafts. |
| `551123cc` | Reviewed hardware-ID/file hashes bound through dispatch and exact-byte runtime loading. |
| `441d3cf5` | Pure bounded quintic re-entry geometry with analytic continuous separation checks. |
| `401e1fec` | Plan/Operate, independent formation, typed workspace APIs, optional read-only MCP tools and aircraft progress evidence. |
| `3a194e19` | Pure smooth mission-clock ramps and chain-rule kinematics. |
| `a5348ddb` | Native ground-start evidence at prepare/commit/executor; pre-ownership rejection sends no flight-control commands. |
| `84a88485` | One full route editor in Plan; legacy redirect; terrain/CSV/library integrity; remove duplicate basic editor/helpers. |
| `c75fb48e` | One shared operator-style cascade; clear build lint findings and preserve viewport command semantics. |
| `c3bbfb3d` | Load the waypoint panel's stylesheet, remove 481 duplicate style lines, separate search/metrics and stop displaying unverified clearance as zero. |
| `9bd6180f` | Keep route controls inside their editor column, with a browser overlap assertion. |

The mission snapshot has revision-conflict protection and never edits live Smart
Swarm configuration. Processing stages files away from active outputs, writes the
session last and rolls back publication errors. Reviewed SHA-256 identities are
checked at native prepare, commit and executor load. This is **not yet** an atomic
immutable-revision pointer or a cross-process launch/mutation transaction.

Node progress is command-scoped, stale-aware and rate-limited. It describes
commanded trajectory time, not measured tracking accuracy. Start and recovery
requests preserve uncertain receipt identity across reload; no flight command
is sent by merely opening the page. Hold currently ends the route; Resume is not
exposed until the coordinated protocol exists.

Plan embeds map/3D tools where the map provider supports them, drag editing,
undo/redo, reorder, library and import/export. Leaflet retains token-free 2D
authoring. Browser drafts remain separate per leader and REAL/SITL mode. Existing
library keys remain intact; old editor bookmarks redirect to Plan.

Mission 4 terrain comes only from the canonical backend batch lookup, including
new points, moves, library loads and imports. Explicit MSL is usable without
terrain. Missing/error terrain cannot authorize AGL or silently replace altitude.
CSV/library persistence retains uncertainty and provenance. Blank or malformed
coordinates/altitude/time are rejected; explicit zero values are preserved.

## Verification

### Home demo and editor follow-up

- REAL/SITL demo packages now include a saved mission formation and checked
  content manifest. The preparation helper preserves the replaced package,
  uses the existing configured fleet and origin, and never dispatches commands
  or changes live Smart Swarm. A fresh-checkout regression test prevents stale
  bundled sessions or unrelated outputs from shipping as a ready example.
- Plan frames the saved draft/route or canonical origin once; late preview data
  may supply the initial view but cannot overwrite a draft or operator navigation.
- Operate shares the geographic route renderer. Available Mapbox/WebGL uses
  explicit MSL route heights; absent/failed rendering falls back to 2D. Shader
  geometry/resource cleanup and provider failure have focused unit coverage;
  headless browser evidence covers the 2D fallback, not GPU/flight acceptance.
- Fixed timing-edit bugs: preferred-speed successor arrivals are not immutable
  deadlines, zero remains zero, and rounded seconds carry into minutes.
- One body-level dialog host prevents map instructions/controls from covering
  Waypoint, Library, Export and Assign. Flat scoped fields remain readable in
  both themes. Waypoint rows show numeric summaries and selected controls, not
  repeated guide cards, normal-status tags or instructional paragraphs.
- Follow-up remote checks: 211 frontend tests across 33 suites, including live
  Smart Swarm Start and Managed Return regressions; nine demo tests on each
  official/private checkout. Browser probes check field hit targets, timing,
  responsive dialogs and real generated package data while aircraft stay offline.
  Fourteen browser cases passed: eight 2/50-aircraft theme/viewport cases, two
  editing hit-test cases, and four actual-package desktop/320-pixel cases.
  API writes are blocked in these probes. Seven operator-guide captures were
  refreshed; neither screenshots nor package readiness establish flight proof.
  Logs: `/tmp/mds-home-final-ui-tests.log`,
  `/tmp/mds-home-demo-public-fresh-tests.log`,
  `/tmp/mds-home-demo-private-fresh-tests.log`.
- Current source/UI follow-up is `trajectory-workspace-20261029-rc2`.
  It is not Mission 4 flight clearance or an updated pinned SITL image.
  The usual live Smart Swarm field workflow remains separate and unchanged;
  node synchronization and native aircraft readiness must be checked online.

### All-tab operator-console follow-up

- Flat scoped surfaces replace the legacy unscoped trajectory stylesheet across
  Operate, Formation, Route, Uploads, Generate and Review, including dialogs.
  Repeated metric boxes/instructions were removed, not replaced with another
  nested card system. Mobile planning tabs stay visible together.
- Review defaults to a geographic map with a token-free Overview fallback.
  Search/checkboxes control the real traces; hardware colors remain stable.
  Non-scaling strokes prevent inflated lines when the overview grows.
- Retained outputs without formation assignments are files outside the mission,
  not invented followers. They are hidden/collapsed by default, preserved on
  disk, and reported as a neutral advisory rather than a new safety gate.
- Follow-up checks on Hetzner: 68 targeted frontend tests, 43 backend tests and
  eight read-only browser cases (2/50 aircraft, both themes, desktop/mobile).
  Browser cases cover all planning tabs, library-dialog appearance, map legend
  toggles, overview line weights, overflow and zero API writes.
- This does not change live Smart Swarm control logic, gains, PX4 parameters or
  saved fleet formation. Mission 4 flight acceptance remains a separate step.

All computation ran in an isolated remote source copy, not the production repo.

- Consolidated backend: **735 tests passed**, including package processing,
  service/routes, native admission, node HTTP, FleetRPC, API inventory and optional
  agent-tool contracts. Log: `/tmp/mds-trajectory-backend-final-tests.log`.
- Consolidated frontend: **176 tests passed in 23 suites**, including the editor,
  terrain/import contracts, linked 2D/3D formation views, return controls, plot
  renderer and navigation. Log: `/tmp/mds-trajectory-frontend-final.log`.
- Strict production build (**CI=true**) passed for runtime source `9bd6180f`;
  no compile, lint or stylesheet-order warning remains. The existing large-bundle
  advisory and old Browserslist data remain build-tool maintenance items.
  Log: `/tmp/mds-trajectory-editor-build-final.log`.
- **Eight browser cases passed:** 2/50 aircraft × dark/light × desktop/mobile.
  The probe checks Start review without dispatch, legacy redirects, loaded panel
  styling, non-overlapping search/metrics, no document overflow, no runtime
  exceptions and zero API writes. Evidence directories:
  `/tmp/mds-trajectory-editor-proof-final` and
  `/tmp/mds-trajectory-editor-proof-final-50`. These are simulated UI fixtures,
  not flight evidence.
- The [operator walkthrough](../features/swarm-trajectory.md#operator-workflow)
  includes seven real UI captures: Formation, Route, Generate, Review, Start review,
  simulated monitoring and Return review. Reproduce them with the read-only probe's
  `--capture-guide` option. The active fixture also verifies Start stays disabled.

Publication scope is a **source/UI release candidate**, not a refreshed SITL
image or Mission 4 flight acceptance. Its public history is a sanitized squash
of the development slices above; those local commit IDs are audit references,
not separate public releases. Live Smart Swarm is unchanged. Before Mission 4
hardware use, server/node rollout and legacy package regeneration must happen
together; older nodes cannot provide the new native admission evidence.

## Remaining required work

1. Atomic immutable revisions and cross-process mutation/run admission. Keep
   active packages pinned; do not confuse rollback publication with immutability.
2. Durable run/processing reconciliation. Reuse the existing command journal
   rather than introducing a competing lifecycle store.
3. Integrate coordinated Pause/Resume: all-member prepare acknowledgements,
   agreed clock anchors, settled holds, bounded re-entry and retimed kinematic
   checks. Fence late recovery/messages after Return, landing or pilot takeover.
   The existing geometry/clock modules do not dispatch flight commands.
4. Complete two-aircraft SITL acceptance, including partial acceptance, stale
   package, link loss, restart, concurrent edits, pause/resume and pilot takeover.
5. Rebuild/package/checksum the runtime image after obtaining build headroom.
   Official/private source publication is separate from image and hardware
   acceptance; do not treat a source tag as a refreshed download image.

## Storage and cleanup

Latest remote cleanup removed regenerable npm/pip download caches and compressed
rotated system/authentication logs without discarding their contents. Roughly
1.3 GB was recovered across the two disks, including disposable Babel compilation
cache and 13 abandoned probe browser profiles. Root has about 1.8 GB free; the attached
volume about 0.9 GB. This is still insufficient for the documented full flattened
image rebuild; approximately 10 GB build headroom was requested.

The dirty September field worktree is preserved. The older action-Hold checkout
contains the frontend dependencies used by production and validation through
symlinks, so it is not disposable. Flight evidence, release/rollback artifacts,
protected agent histories, credentials, installed tools and unrelated projects
are retained. Local and remote worktree registries have no removable clean stale
MDS worktree remaining.

The temporary loopback preview server was stopped after final capture. The
isolated build and evidence are retained for the next acceptance phase.

## Lessons for the next agent

- Do not trust missing terrain metadata as verified; preserve errors through all
  persistence formats and re-resolve old AGL library routes.
- Do not coerce blank numeric inputs into zero; geographic zero is valid only
  when explicitly entered.
- Embedding a formerly separate lazy page requires one deterministic shared CSS
  cascade, not warning suppression or page-load-order-dependent styling.
- Native ground rejection must not invoke landing/disarm cleanup before the
  mission has attempted to acquire flight control.
- Keep public source/checkpoints deployment-neutral; host names and private
  customer details belong in private operational context.
- Map dialogs must escape transformed map/workspace stacking contexts through
  the shared overlay host. Increasing a child z-index cannot fix an ancestor
  stacking boundary; test real browser hit targets, not DOM presence alone.
- Ship bundled mission formation/session manifests together and enforce LF
  mission-file checkout endings, or a fresh installation can start stale/red.
- Keep route camera references separate from draft import/assignment. Opening
  a demo or receiving late preview data must not mutate the operator's route.

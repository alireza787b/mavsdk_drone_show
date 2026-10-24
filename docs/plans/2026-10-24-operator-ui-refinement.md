# Operator UI refinement — 24 October 2026

## Implemented

- Design Swarm: visible Apply plan and Save to repo; Save applies a changed
  draft then publishes its acknowledged revision. Repository failure preserves
  the successful Apply and offers publication-only retry. Unreachable-member
  confirmation continues the entire requested workflow.
- Local Undo/Redo plus confirmed, undoable Reset draft. Readable distance
  formatting does not quantize saved geometry; focus exposes full precision.
- Single/Four views: Top, Front, Side and 3D share one draft and reference.
  NED uses North/East; Body uses followed-leader Forward/Right at its preview
  heading. Links remains a relationship view. Explicit layout transitions fit
  the smaller panes, while edits do not reset cameras.
- Callsign/alias or hardware-ID fallback, duplicate-name disambiguation, current
  H/P identifiers and optional plot IDs. Missing position IDs are not invented.
  Existing InfoHint is reused for accessible NED/Body/preview-heading help.
- Operate: current telemetry and a read-only relationship diagram, four consistent
  flight controls, secondary actions behind a small header overflow. Historical
  return jobs no longer remain as banners; active/unconfirmed work stays visible.
  New dispatch summaries expire after 10 seconds; dismissal never cancels commands.
- Shared layout: one application gutter, full available width, available-height
  workspace variable, local scrolling instead of root clipping. Corrected fixed
  Mission Config columns, map/log/editor sizing, dialogs and sidebar layouts.
- Direct Drone Detail navigation without a selected aircraft now returns to
  Overview instead of crashing.
- Git writes refuse a detached or mismatched deployment branch before staging,
  rebasing or pushing. This prevents reporting a push of the wrong branch as a
  successful plan publication.

## Verification on Hetzner

- 94 focused frontend tests passed; the subsequent layout-transition regression
  passed with the 7-test canvas suite. Git/swarm backend checks: 33 passed.
- Optimized production build succeeded; strict frontend UI audit: zero critical
  findings. Three simple native-title debt findings remain, not new UI blockers.
- Real Chromium four-view drag: East 0 → 1.530813689m, unfocused display 1.53,
  focus shows full precision, Undo restores 0. Linked projections, Body 90° to
  NED switching and mobile 390px passed. Initial four-view crop was reproduced,
  fixed and verified; no application errors or API writes.
- Built-route audit: 176/176 route/viewport/navigation cases rendered, zero
  horizontal overflow failures, unavailable views or JS/resource errors.
  Coverage is mock fleet plus empty/error states, not populated flight-workflow
  acceptance. Nine automatic HTTP mutation requests were blocked by the harness;
  zero real API writes. WebSockets were isolated.
- Chromium was available. Firefox/WebKit engines were not installed; independent
  cross-engine rendering checks remain unverified. No new browser dependencies
  were installed on the storage-constrained host.

Evidence: `/root/mds-action-hold-20261024.PdRKCW/evidence/`:
`operator-refinement-tests.log`, `operator-refinement-transition-test.log`,
`operator-refinement-repository-tests.log`, `operator-refinement-build.log`,
`operator-refinement-ui-audit.log`, `operator-quad-browser.log`,
`dashboard-layout-final.json` and `operator-quad-*.png`.

## Deployment boundary

Update the existing production review branch/build after these checks. Preserve
the real fleet, formation, environment/auth settings and aircraft update channel;
save a rollback build and verify live authenticated rendering read-only.

The production review checkout is intentionally not the client `main` release.
Apply plan can update its GCS formation, but repository publication is refused
while the checkout differs from the configured deployment branch. Align/promote
the release deliberately before permanent repository publication or boot Git sync.
Do not infer real-aircraft clearance from this UI review.

No aircraft commands, PX4 changes, controller tuning, new flight gates or Simurgh
function/policy changes were made. SITL image packaging and final official/client
release promotion remain separate; Hetzner free disk space is still limited.

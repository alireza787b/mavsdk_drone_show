# Frontend Design System

This guide is the canonical UI/UX contract for MDS dashboard changes. It is for
human maintainers and AI agents working on official or customer forks.

## Product Goal

MDS is an operator console, not a documentation page. Every screen should make
the current state, risk, and next safe action obvious from a quick scan.

Use this information hierarchy:

1. Always visible: icon, status, count, short label, primary action.
2. On hover, tap, or info affordance: meaning, cause, risk, secondary metadata.
3. In linked docs or drill-down views: setup instructions, policy, full context.

If a sentence explains policy or workflow, it usually belongs in a tooltip,
expandable detail block, or guide, not as permanent page chrome.

## Required Page Structure

Top-level pages should use the shared operator primitives:

- `PageShell` for title, short subtitle, status, docs link, and actions.
- `PageActionBar` for responsive primary and secondary page actions.
- `MetricStrip` for compact summary counts.
- `OperatorNotice` only for actionable state changes, warnings, or errors.
- `EmptyState` for no-data, no-capability, and no-filter-result states.

Mobile and tablet layouts are first-class. Primary actions remain visible;
secondary actions collapse into an overflow menu.

## Action Bar Standard

Use `PageActionBar` for page-level actions instead of page-specific button
clusters. Primary actions are the one or two operations the operator may need
immediately, such as `Refresh`, `Save`, or `Apply`. Secondary actions are
imports, exports, reference links, and diagnostics; these collapse behind the
overflow control on mobile.

Do not create separate pill/button systems for each page. If a page needs a new
layout pattern, extend the shared primitive first and keep page CSS limited to
local spacing.

## Copy Standard

- Page subtitles should be one short sentence.
- Buttons should use one or two words where practical.
- Badges should be noun/adjective states: `Ready`, `Blocked`, `SITL`, `REAL`.
- Avoid repeated paragraphs across page shell, cards, and notices.
- Put advanced explanations in the route guide linked by the page docs button.

## Toast Standard

Toasts are transient acknowledgements, not persistent system state. Pages that
poll, auto-refresh, or remount after app switching must use throttled toast
helpers or inline notices so the screen never fills with repeated warnings.
Persistent issues belong in `OperatorNotice` or the page state card.

## Visual Standard

- Use `DesignTokens.css` for colors, spacing, shadows, z-index, and typography.
- Do not add hardcoded colors or numeric z-indexes in component CSS.
- Prefer icon + compact label over long inline text.
- Every icon-only control must have an `aria-label` and hover/touch help.
- Flight-critical and destructive actions must stay explicit and confirmable.

## Map And Globe Standard

- 3D and 2D map views must keep equivalent core controls: filter, fit/focus,
  map/provider controls, and selected-drone dismissal.
- Touch behavior must match pointer behavior; no hover-only workflows.
- Selected drone cards should be compact, close on outside click/tap, and avoid
  duplicated close buttons from nested map libraries.
- Leaflet fallback is operational, not degraded. If Mapbox is unavailable, the
  user should still have satellite/OSM layers, fit-to-fleet, and clear status.

## Documentation Links

Top-level route docs are declared in:

```text
app/dashboard/drone-dashboard/src/config/routeDocs.js
```

Every top-level page must either use `PageShell docsRoute` or another `DocsLink`
that resolves to a real repository guide. Production links must not fall back to
SPA-local `docs/...` URLs that can 404 behind the dashboard server.

## Change Checklist

Before closing a frontend slice:

- Run `python3 tools/audit_frontend_ui.py`.
- Run focused tests for changed pages/components.
- Build on the approved heavy-test host.
- Capture mobile and desktop screenshots for changed routes when practical.
- Verify route docs links open the intended guide.
- Update docs/tests when visible workflow or operator behavior changes.

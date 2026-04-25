# Frontend UI Audit Guide

This guide defines the predeploy UI/UX cleanup guardrails for the MDS dashboard.
It is intended for human maintainers and AI agents working on official or client
forks.

## Operator UI Standard

Use three layers of information:

1. Always visible: compact state, counts, icons, labels, primary action.
2. On hover, tap, or info icon: meaning, risk, why, secondary metadata.
3. Docs or drill-down: setup instructions, advanced diagnostics, full context.

Pages should not rely on long always-visible paragraphs. If a paragraph explains
workflow or policy, it usually belongs in an `InfoHint`, expandable detail block,
or linked guide.

## Required Page Pattern

Every top-level route should converge toward:

- compact page shell with title, icon, short subtitle, and docs link
- route-aware docs metadata in `src/config/routeDocs.js`
- status summary strip using shared metric/status primitives
- toolbar row for search, filters, scope, and primary actions
- main operator work surface
- compact loading, empty, error, and no-capability states
- mobile/touch behavior equivalent to desktop behavior

## Required Component Pattern

For each component touched during cleanup:

- use design tokens from `DesignTokens.css`
- avoid hardcoded colors, z-indexes, shadows, and spacing
- prefer shared primitives before adding another local modal, badge, notice, or card
- icon-only actions must have accessible labels and tooltips
- hover-only behavior must have a touch fallback
- destructive or flight-critical actions must remain explicit and confirmed
- tests must be updated when visible copy, actions, or state boundaries change

## Route Docs Metadata

The source of truth for top-level route help links is:

```text
app/dashboard/drone-dashboard/src/config/routeDocs.js
```

Each route must declare:

- `path`: browser route
- `label`: compact link label for the UI
- `docPath`: repo-relative Markdown path or absolute URL
- `feature`: stable feature key for future analytics and tests

Use `buildDocsUrl()` from that module when a page needs a GitHub URL built from
runtime repo metadata.

## Audit Command

From the repo root:

```bash
python3 tools/audit_frontend_ui.py
```

From the dashboard package:

```bash
npm run audit:ui
```

`npm run audit:ui` runs the audit in strict mode. Strict mode fails only on
critical structural issues:

- route in `App.js` without route-doc metadata
- route-doc metadata pointing to a missing local doc
- imported package missing from `package.json`

Debt findings are reported but do not fail strict mode:

- hardcoded colors outside token files
- hardcoded numeric z-index values
- native `title=` attributes that should be reviewed for `InfoHint`
- duplicate primitive candidates
- mixed icon stacks

## Baseline

The first baseline for this cleanup phase is versioned at:

```text
docs/plans/2026-04-25-predeploy-ui-audit-baseline.json
```

Do not treat the baseline as approval to keep debt. Treat it as a burn-down
list. Each page/component slice should reduce relevant findings or document why
the finding remains acceptable.

## Review Checklist

Before closing a UI slice:

- run the audit command
- run focused tests for changed pages/components
- run a production build on the approved heavy-test host
- inspect mobile and desktop screenshots for changed routes
- verify docs links open the correct guide
- update docs if visible workflow or operator behavior changed


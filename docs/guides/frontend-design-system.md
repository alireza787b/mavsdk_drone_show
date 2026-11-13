# Frontend Design System

This guide is the canonical UI/UX contract for MDS dashboard changes. It is for
human maintainers and AI agents working on official or customer forks.

## Product Goal

MDS is an operator console, not a documentation page. Every screen should make
the current state, risk, and next safe action obvious from a quick scan.

Use this information hierarchy:

1. Always visible: aircraft identity, status, target count/scope, runtime mode,
   stale or unknown evidence, primary action, and actionable partial/uncertain results.
2. On hover, tap, or info affordance: supplementary meaning, cause, and secondary metadata.
3. In linked docs or drill-down views: setup instructions, policy, full context.

If a sentence explains policy or workflow, it usually belongs in a tooltip,
expandable detail block, or guide, not as permanent page chrome.
Action consequences and safety-critical uncertainty are exceptions: keep them
visible at the decision point. Never require hover or color alone to recognize them.

## Required Page Structure

Top-level pages should use the shared operator primitives:

- `PageShell` for title, short subtitle, status, docs link, and actions.
- `PageActionBar` for responsive primary and secondary page actions.
- `MetricStrip` for compact summary counts.
- `OperatorNotice` only for actionable state changes, warnings, or errors.
- `EmptyState` for no-data, no-capability, and no-filter-result states.

Overview uses the shared application shell with a dedicated flat fleet surface,
view switch, inspector, and target/action rail. Do not force its aircraft into
stacked generic cards merely to reproduce another page's composition.

Mobile and tablet layouts are first-class. Primary actions remain visible;
secondary actions collapse into an overflow menu.

### Available-space layout

The application `.content` owns the outer gutter and exposes `--workspace-height`.
A direct `PageShell` fills its available width without adding a second gutter;
panels own their internal spacing. Maps, editors and logs should size against
that available area, not independently subtract arbitrary viewport offsets.
Keep prose/form readability limits local rather than narrowing the whole page.
Do not hide sizing defects with `overflow-x: hidden` on body/root/content.
Wide tables or data surfaces scroll within their own panel. Account for both
sidebar states, browser zoom and mobile navigation when testing.

## Action Bar Standard

Use `PageActionBar` for page-level actions instead of page-specific button
clusters. Primary actions are the one or two operations the operator may need
immediately, such as `Refresh`, `Save`, or `Apply`. Secondary actions are
imports, exports, reference links, and diagnostics; these collapse behind the
overflow control on mobile.

Do not create separate pill/button systems for each page. If a page needs a new
layout pattern, extend the shared primitive first and keep page CSS limited to
local spacing.

## Fleet And Mission Ownership

Overview owns fleet awareness and general aircraft commands. Drone Show,
Custom Show, Smart Swarm, and Swarm Trajectory own their mission execution in
their dedicated workspaces; do not recreate mission launchers in Overview.
Managed Return belongs to the relevant mission workspace. Overview Return is
the immediate native return request, not that ordered workflow.

Overview Board, List, and Map are deliberate views of the same fleet resource
model, not simultaneous independently polling surfaces. Keep aircraft identity
and ordering stable. Inspection is separate from command-target selection;
changing a filter, view, or inspected aircraft must not retarget a command.
Initialize a one-time snapshot of available configured aircraft only when the
roster and heartbeat snapshot are known and no saved selection exists. Restore deliberate selections, including None, in
their deployment/runtime/operator context; missing or invalid saved targets
must never silently widen to All. The command-adjacent **To** chooser owns an
explicit draft, applied with **Use N aircraft**; Cancel leaves scope unchanged.
Its presets snapshot identities, never subscribe to availability or a cluster.
Cards/markers inspect only; a noninteractive paper-plane mark shows membership.
The eye-marked **Show** tools affect visibility only. Hidden-recipient counts
use actual rendered identities, including Map's current-position restriction.
Keep essential command labels and identities visible; use symbols and hover/tap
help for routine status, without hiding consequential actions behind hover.

Widgets and the inspector consume the shared resource/model freshness and
source labels. Failed polling must not freeze a fresh badge indefinitely.
Unavailable evidence stays unavailable: armed alone does not prove airborne,
and missing telemetry does not prove disarmed or landed. Do not invent readings
or duplicate native readiness/command policy in a view component. See the
[Dashboard Operator Guide](dashboard-operator.md) for the complete operator flow.

## Copy Standard

Map and 3D aircraft details share `MapAircraftInspector`, with one bounded,
scrollable viewport and an accessible identity/Close header. Do not recreate
provider-specific popups with guessed content heights or frame-by-frame React
position updates. Keep inspection identity separate from command targets; a new
aircraft must not inherit an open action or jog review. Network icons/labels come
from the reported transport, not IP ranges or the presence of a secondary radio.

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
- Global navigation uses `--z-navigation` and must remain above scene popovers,
  selected-drone cards, and map/globe controls. Modal dialogs may still dim the
  page, but non-modal tactical cards must never block the sidebar.
- Leaflet fallback is operational, not degraded. If Mapbox is unavailable, the
  user should still have satellite/OSM layers, fit-to-fleet, and clear status.

## Telemetry Altitude Standard

- Dashboard and tactical cards show one primary altitude chip, source-labeled:
  `MSL`, `GPS MSL`, or `Local`.
- `MSL` comes from valid PX4 global position and can support map/home context.
- `GPS MSL` comes from `GPS_RAW_INT` when a 3D GPS fix exists, but it is not a
  map coordinate by itself.
- `Local` comes from `LOCAL_POSITION_NED` and supports VIO/non-GPS workflows;
  it must not be called AGL unless a ground/terrain/home reference is known.
- Home distance and map placement remain unavailable until a valid global
  coordinate exists.

## Documentation Links

Top-level route docs are declared in:

```text
app/dashboard/drone-dashboard/src/config/routeDocs.js
```

Every top-level page must either use `PageShell docsRoute` or another `DocsLink`
that resolves to a real repository guide. Production links must not fall back to
SPA-local `docs/...` URLs that can 404 behind the dashboard server.

## Change Checklist

### Formation capture

Keep planning/capture workflow choices separate from editing commands. Place
Revert with Undo/Redo, never use a setup selector as a disguised reset. Both
workflows share one draft and retain explicit Use capture / Apply boundaries.

Use a dominant read-only scene with identifiable aircraft silhouettes and one
short primary action. Default to interactive 3D; expose flat views beside it,
not as extra permanent panels. Mouse, touch and keyboard camera controls must
never edit geometry. Distinguish frozen capture from advisory live estimates
using shape/stroke, not color alone. Only the selected aircraft needs offset details.
Keep leader/reference changes in progressive disclosure. Native whole-cluster
capture evidence chooses contextual defaults; explicit operator selections survive
Refresh. Never trade a silent height/role change for fewer clicks.

These principles are informed by [Auterion's operator/advanced-feature separation](https://docs.auterion.com/hardware-integration/flight-controller-customization/amcs-advanced-mode)
and [DJI Pilot's primary view with compact contextual controls](https://dl.djicdn.com/downloads/m200_v2/20200515/M200_Series_V2_User_Manual_en.pdf).
They are design references, not evidence of MDS certification or equivalent safety.

Before closing a frontend slice:

- Run `python3 tools/audit_frontend_ui.py`.
- Run focused tests for changed pages/components.
- Build on the approved heavy-test host.
- Capture mobile and desktop screenshots for changed routes when practical.
- Verify route docs links open the intended guide.
- Update docs/tests when visible workflow or operator behavior changes.

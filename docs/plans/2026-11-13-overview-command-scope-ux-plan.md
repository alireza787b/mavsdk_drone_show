# Overview: separate display from command recipients

Status: approved; implementation candidate under isolated validation. No
production deployment or aircraft operation has been performed for this phase.

## Evidence and consultation

Three independent, read-only agent reviews considered a first-time/occasional
operator, a high-pressure fleet operator, and frontend/accessibility/product
design. These are simulated perspectives, not interviews with real pilots or
evidence of certification. Reviewers inspected the current source independently
before receiving a preferred solution. All preferred a command-adjacent
aircraft selector over additional warnings or a new Browse/Select mode.

Observed problems in the current implementation:

- Display `Available / All aircraft` sits beside command `Available / All / None`.
  Similar wording hides materially different effects.
- The command footer repeats only the count; hidden recipients are reported
  farther away, in a separate targeting toolbar.
- Card checkboxes, selected borders and inspection highlights compete. Board
  and List can change membership; Map markers only inspect.
- Choosing a target group resets the selector label, removing its context.
- Confirmed defect: Overview computes hidden target IDs before FleetMap omits
  aircraft without current trusted positions. A selected aircraft can have no
  marker without appearing in the hidden-target count.
- The design-system guide still describes first-use all-configured selection,
  while the implementation/operator guide correctly use an available snapshot.

Useful primary references, not product-equivalence claims:

- [QGroundControl multi-vehicle control source](https://api.qgroundcontrol.com/master/FlyViewTopRightPanel_8qml_source.html)
  places selected vehicle identities with multi-vehicle action controls.
- [Carbon data-table guidance](https://github.com/carbon-design-system/carbon-website/blob/main/src/pages/components/data-table/usage.mdx)
  distinguishes global display utilities from actions on selected items.
- [WAI checkbox guidance](https://www.w3.org/WAI/ARIA/apg/patterns/checkbox/)
  and [dialog guidance](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
  inform native selection semantics, labels, focus, cancellation and keyboard use.

## Chosen interaction

Keep two clearly owned areas, with different visual grammar:

1. Above the fleet: `Show: Available`, Find aircraft, Board/List/Map. These are
   display tools only. Cluster grouping appears only when useful.
2. Beside the command buttons: one recipient selector, for example
   `To: ALPHA, BRAVO · 2 ▾`, followed by Takeoff, Hold, Land, Return and More.

For large selections, show a bounded count/identity summary, not a wrapping list
of 100 names. Full identities remain one tap away. A missing/hidden recipient
indicator belongs here, next to the commands, not in a distant notice.

Remove the duplicated targeting toolbar and permanent card checkbox editing.
Card/marker click always inspects. If a command-membership indicator remains on
cards, it is noninteractive, uses a different shape from readiness/focus, and
has an accessible name. Unselected aircraft and their hazards remain readable.

Clicking the recipient selector opens one focused picker:

- Exact identities (callsign plus hardware ID), native checkboxes, one search.
- Selected count always visible; selected unavailable or removed identities
  remain reviewable, never silently discarded.
- `Use available now` explicitly snapshots the available configured aircraft.
- Multiple-cluster shortcuts only when multiple clusters exist.
- `All configured` and `Clear` remain secondary, explicitly named operations;
  neither means all search results or all visible map markers.
- Changes edit a local draft. `Use N aircraft` applies; Cancel/Escape discards.
  Applying an empty set is legitimate; sending a flight command is then disabled.
- Selecting a preset never creates a subscription. Derived group labels apply
  only when membership still exactly matches; otherwise show custom recipients.

The normal single-cluster flow remains: open Overview, choose command, confirm.
There is no extra target-picker step when the prefilled recipients are correct.
An empty initial roster, deliberately empty saved selection, or subsequently
appearing aircraft is an explicit-selection exception, not permission to widen
scope automatically. This is a design target, not a claim that 99% usability has
been measured.

## Defaults and state ownership

Preserve the previously approved behavior:

- Available is the initial display filter.
- First use initializes a one-time available/configured identity snapshot.
- Remember the exact selection in its deployment/operator/runtime context,
  including a deliberate empty set. Make restored/custom recipients visible
  through the same command-adjacent summary, not a new mandatory modal.
- Search, filtering, grouping, inspection, map gestures, reconnects, newly online
  aircraft, role changes and disappearing groups cannot rewrite those IDs.
- No availability-to-selection reconciliation timer or stabilization policy.

Three separate states remain:

| Owner | State | Can send a command? |
| --- | --- | --- |
| Display | Search, filter, view, grouping, inspected identity | No |
| Command recipients | Explicit hardware-ID set and picker draft | No |
| Action review | Frozen recipient IDs, action parameters and request identity | Only its existing confirmed native dispatch |

The picker cannot retarget an already-open review. A changed command scope
requires a new review. Existing uncertain-receipt lookup, idempotency, unavailable
acknowledgment, remove-unavailable review and native/PX4 checks are preserved.
No emergency all-online shortcut, new flight gate, automatic replay, or fleet-wide
state shared between unrelated workspaces is introduced.

## Visibility accounting

Use one shared rendered-identity calculation:

- Board/List: IDs remaining after their display search/filter.
- Map: those IDs further restricted to current trusted positions.
- Recipients absent from the actual rendered set remain part of the command
  and are summarized adjacent to its controls (`1 not shown` / `1 not on map`).
- Availability and lack of a map position are different facts. Do not add their
  counts together, imply a positionless aircraft is offline, or infer readiness.
- Reviewing these recipients does not silently clear search or change targets.
  An explicit `Show recipients` display action may reveal them when useful.

## Consistency across workspaces

Reuse a controlled choice-row/picker presentation where semantics match; do not
introduce a global selection store or force every page through the same workflow.

| Surface | Preserve its meaning |
| --- | --- |
| Overview | General commands to explicit recipient IDs |
| Takeoff review | Frozen initiating roster; exclusions apply to this takeoff only |
| Smart Swarm | Complete selected formation/cluster and its native start/recovery workflow |
| Drone Show / Custom Show | Show-specific participants, timing and operation ownership |
| PX4 Parameters | Viewing one aircraft is separate from applying to reviewed aircraft |
| Logs | Choosing a log source is inspection, not a command target set |

Single-aircraft inspector actions continue to address that aircraft only. Name
that aircraft at their review. General actions remain in the command rail;
mission launches remain on mission pages. Do not change formation roles, native
readiness, existing defaults or flight/recovery semantics for visual consistency.

## Implementation slices

1. Overview ownership and presentation: controlled display toolbar, one
   command-recipient control and draft picker; retire old target toolbar and
   interactive card checkboxes; fix actual rendered-ID accounting.
2. Harmonize matching labels/choice primitives in existing mission/action
   reviews without another source of membership, duplicated subscriptions or
   unnecessary new dialogs. Fix stale design-system wording and operator guide.
3. Validate, illustrate and release: update automation selectors, actual built
   screenshots and step-by-step operator examples; public history/privacy check;
   integrate official/private repositories preserving client configuration.
   Deploy only with current grounded/off confirmation and successful gates.

No backend/API/MCP schema or SITL image rebuild is expected for this frontend
change. Audit ownership first and update contracts only if a real contract
change proves necessary. Do not perform unrelated rewrites.

## Acceptance gates

All tests and builds use the user-designated remote host, not the limited VPS.
No hardware commands or real-flight tests are required for this UI change.

- Existing reducer, persistence, request-ID and action-review safety tests stay
  green; no implementation weakens assertions just to match a screenshot.
- Picker apply/cancel, one-to-many/zero, remembered empty/missing IDs, first-load
  empty roster, late/reconnected aircraft, context switches and cluster changes.
- Search one aircraft while several remain recipients: every command review
  retains the exact set. Display changes never dispatch or mutate configuration.
- Selected aircraft without a current map position count as not on the map.
- Role/cluster/display changes during a review cannot retarget it.
- Takeoff exclusions do not mutate saved Overview recipients.
- Native keyboard controls, focus restoration, touch, bounded dialog scrolling,
  visible scope next to actions, no hover-only essential information.
- Desktop, intermediate tablet widths, phone, 200% zoom, light/dark, long names,
  and 1/2/3/100-aircraft fixtures. Include partial availability and all-off cases.
- Synthetic browser fixtures block every backend mutation/WebSocket forwarding;
  verify live assets separately after a guarded deployment.

## Decision boundary

Keep the approved default and restoration rules. Removing permanent card
checkbox editing is the approved material interaction change. It makes recipient editing
one deliberate operation but adds no steps to the common all-aircraft command.
Actual field operator feedback remains part of the usability acceptance loop.

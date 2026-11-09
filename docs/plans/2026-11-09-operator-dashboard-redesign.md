# Operator Overview and shared shell redesign

Status: approved for implementation on 2026-11-09. Proceed through verified slices without an approval pause between them; ask only for material external decisions. Isolated validation does not constitute flight clearance.

Assessment baseline: `7f565f25b410a34c56ee38165144f3cbca0cb3be`, inspected on 2026-11-09. Source findings below are inspection evidence, not newly reproduced field incidents. Existing unrelated worktree edits remain outside this plan.

## 1. Outcome and scope

An operator opening Overview should immediately understand which aircraft are present, which need attention, which will receive the next command, and what happened to the last command. The normal workflow must not require reading technical diagnostics.

The first phase covers Overview, aircraft presentation, selection, general commands, alerts, command activity, and the shared navigation/layout. Recently redesigned mission workspaces remain the owners of mission setup, launch and monitoring. Missing mission capabilities are added there before their dashboard counterparts are removed.

This is an operational UI redesign, not a flight-controller, swarm-guidance, security-platform or database rewrite. “Military/commercial inspired” describes clarity and discipline, not certification or an assertion of equivalent safety assurance.

### Confirmed owner decisions

| Decision | Contract |
| --- | --- |
| Leading device | Laptop/desktop first; tablet, phone and browser app retain the complete workflow. |
| Initial targets | Select all configured aircraft on a fresh session; restore the previous selection when available, including an intentionally empty selection. |
| Selection stability | Filters, inspection, view changes, telemetry loss and reconnects never change targets. |
| Overview Return | Immediate PX4 RTL only. Managed Return remains on mission pages. |
| Mission ownership | Mission starts belong on their own complete, verified pages, not duplicate dashboard launchers. |
| Broader polish | Record other mission/configuration-page improvements for later rather than continually expanding this rewrite. |

## 2. Consultation and design basis

Three independent agent consultations reviewed operational human factors, product/visual design and source architecture, followed by one disagreement-resolution round. These were simulated expert perspectives, not interviews with actual pilots or a certification review. Actual task-based usability acceptance remains required.

The principal disagreement was whether a permanent roster/map/inspector layout would provide awareness or create another crowded laptop console. The recommendation is a graphical aircraft board first, with deliberate alternative views and one inspector opened when needed.

The simulated job stories covered a beginner managing a small fleet, a remote pilot investigating stale telemetry, a coordinator triaging a large fleet, and a safety observer using a tablet. Across these roles, critical facts must remain visible without hovering; supplementary diagnostics need not.

Primary references informing—not dictating—the design:

- [Auterion advanced mode](https://docs.auterion.com/hardware-integration/flight-controller-customization/amcs-advanced-mode): separate normal operator work from rarely used technical features.
- [QGroundControl Fly View](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/fly_view/fly_view.html): spatial context and contextual vehicle controls, with separate planning responsibilities.
- [DJI FlightHub map details](https://fh.dji.com/user-manual/en/map/map-details.html): live spatial relationships and planned/flown route context.
- [Skydio fleet-health presentation](https://support.skydio.com/hc/en-us/articles/35583768187291-Skydio-Cloud-DFR-Command-and-Remote-Ops-3-April-2025): fleet-level exception awareness with individual investigation.
- [WCAG use of color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html), [hover/focus content](https://www.w3.org/WAI/WCAG22/Understanding/content-on-hover-or-focus.html), and [target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html): redundant state cues, accessible supplementary help and usable controls.

## 3. The operating surface

```text
Navigation   Overview / mission workspaces / fleet setup           REAL / SITL
             Fleet · current / unavailable · attention · command activity
             [Board | List | Map]       filter/search       target selection

             Aircraft surface                    Inspector, only when opened
             stable identities and state         one aircraft, current data

             Selected N     Takeoff    Hold    Land    Return    More
```

This is a responsibility sketch, not a fixed three-column wireframe. In particular, the inspector is not permanently allocated screen space. On small screens it becomes a sheet/full-screen view with a clear Back action; selection count and access to Actions remain available.

- **Board** is the recommended default: lightweight graphical aircraft tiles with stable ordering.
- **List** is a compact operations list for comparison and large-fleet triage, not a technical spreadsheet.
- **Map** is an intentional spatial view of aircraft with trustworthy position data. Aircraft without trusted positions remain countable and inspectable through the roster; never place them at invented coordinates.
- Preserve the chosen view. Do not automatically change layout because the fleet grows, an aircraft takes off or an alert arrives.
- At 100 aircraft, aggregate counts and exceptions must be readable at a glance. Do not promise that 100 full instrument panels can be read simultaneously or shrink them until unusable.
- One thin status strip replaces piles of summary cards. Normal state is quiet; actionable exceptions draw attention.
- Use flat surfaces, clear alignment, restrained dividers, compact typography and mostly square controls. No recursively nested card borders or decorative instruments.

### Aircraft tile and inspector

The normal tile contains a unique identity, schematic aircraft silhouette, short observed flight/link state, battery indicator/value when valid, a separate target checkbox, and the highest-priority issue when present. Additional issues open the inspector. Do not make every metric a chip.

Resolve identity from existing canonical naming helpers: callsign when present, stable hardware-ID fallback otherwise. Keep hardware/position identity accessible in inspection and search; duplicate names must remain distinguishable. Do not substitute position-slot IDs for aircraft identity.

Clicking an identity/tile body inspects; the checkbox selects. Unselected aircraft remain legible, especially their critical conditions. Selection must not suppress or gray away hazards.

The inspector resolves the selected aircraft ID against the current shared fleet model. It must not freeze an entire telemetry object at the moment it opens. Last-known values are labelled as such, and absent values stay unknown.

Color carries meaning but is never the only signal: blue for selection, amber for caution, red for critical, neutral/gray for unavailable or unknown. Normal state need not be a wall of green. Armed is not airborne; stale is not disarmed; a missing measurement is not a healthy estimate.

## 4. Selection and command semantics

### Selection

1. After the configured roster is known, restore the saved explicit target set for this deployment, runtime mode and operator context. An empty saved set is valid.
2. If no saved selection exists, initialize once with all configured aircraft, not merely those currently online.
3. Save intentional selection changes. If a stable operator/deployment identity is unavailable, use session-scoped persistence rather than mixing different operators' targets.
4. All, None and Select group are deliberate actions. Group selection snapshots its members; it is not a subscription to future membership changes.
5. Filters and map visibility never select or deselect. Show a concise hidden-selected count when needed.
6. New arrivals do not silently join the selected set. Removed or unresolved remembered IDs require explicit reconciliation, not replacement or automatic widening to All.

### General actions

Keep **Takeoff, Hold, Land and Return** as the recommended primary action set. Return means immediate native PX4 RTL; it does not promise collision avoidance or managed sequencing. Confirmation/review uses the same meaning everywhere.

The existing native takeoff review, synchronized arming barrier, cancellation and receipt contracts are reused. This redesign does not bypass PX4 checks or add a second takeoff policy. Display readiness is advisory; fresh action admission still belongs to the authoritative command path.

Before dispatch, freeze exact unique aircraft IDs, action, parameters and the reviewed intent. Never fall back from an invalid group to all aircraft. Preserve the same request body and idempotency key through uncertain-result lookup; an unavailable response is not permission to issue a new command.

The command summary shows action and target count, with identities available immediately. Distinguish request accepted, aircraft acceptance, execution and completion. Partial, rejected and uncertain outcomes remain available after navigation/reload rather than disappearing in a toast.

Put the five-second **Arm test** and less-used general actions under More; name actual motor-arming behavior explicitly. Maintenance/reboot/calibration belong in deliberate secondary/Fleet Ops flows. A retained single-aircraft move/jog entry belongs in inspection, subject to its actual runtime safety contract. Motor termination must not sit beside routine actions as an equivalent recovery choice.

## 5. Alerts, activity and motion

- Put command activity in the shared shell, reusing the existing provider and backend journal, so leaving Overview does not discard outcomes.
- Separate condition alerts from command outcomes and transient interaction feedback.
- Deduplicate conditions by aircraft, condition and episode. A GCS outage gets one aggregate connection alert, not 100 repeating aircraft toasts.
- Acknowledgement means seen, not resolved. Do not present local acknowledgement state as an audited fleet-wide backend operation.
- Critical state, target scope, stale/unknown status, REAL/SITL, action consequences and uncertain outcomes are never hover-only.
- Keep secondary source values, timestamps and diagnostics available by keyboard focus, hover and tap.
- Stable ordering prevents aircraft jumping under the pointer. Use bounded transitions and reduced-motion support, not simulated rotor animation or stale position extrapolation presented as current telemetry.
- No offline command queue or automatic replay after reconnection.

## 6. Source findings that must not survive the rewrite

Paths below are under `app/dashboard/drone-dashboard/src/` unless stated otherwise. These are bounded correction tasks, not reasons to redesign unrelated flight behavior.

| Finding | Inspected source | Required correction |
| --- | --- | --- |
| Selection follows visibility/link changes; a missing group can widen scope | `pages/Overview.js`, `components/CommandSender.js` | One explicit selection reducer; no automatic retargeting or fallback to All. |
| Some generic commands retain dynamic `target_scope: all`, unlike Takeoff's explicit IDs | `components/CommandSender.js` | Freeze IDs for every reviewed dashboard action. |
| Expanded aircraft stores a snapshot and detail separately polls the whole fleet | `pages/Overview.js`, `components/ExpandedDronePortal.js`, `components/DroneDetail.js` | Inspect by ID; one shared resource owner. |
| Missing GPS fields can become fix type 3, 12 satellites or a good-looking HDOP/VDOP fallback | `components/DroneWidget.js` | Remove manufactured measurements; test absent/zero/valid values explicitly. |
| Some summaries infer disarmed from the remainder; a quick-action slot treats armed as airborne | `pages/Overview.js`, `components/DroneCriticalCommands.js` | Separate observed phase, armed state and unknown/stale evidence. |
| Cached readiness can remain populated during link loss; an empty summary can appear ready | `utilities/droneReadiness.js`, `components/CommandPreflightSummary.js` | Separate last-known display from current admission; no empty-cohort Ready. Preserve native readiness timing/leases. |
| Poll effects restart/couple resource acquisition; inspector adds another fleet poll | `pages/Overview.js`, `components/DroneDetail.js` | Independent bounded resource acquisition; abort/fence obsolete responses; freshness expires even if a request hangs. |
| Readiness HTTP query/tool cap is 64 despite the requested 100-aircraft UI | `gcs-server/api_routes/core.py`, `config/agent_tools.yaml` | Align the existing readiness contract to 100, with boundary tests and no new endpoint. |
| Mission documentation and dedicated-page capabilities do not fully match dashboard launchers | Mission workspace helpers/pages and operator guides | Close parity and fix active guidance before deleting launch controls. |

The readiness helper already evaluates cached fleet evidence without per-aircraft RPC. Raising the query cap should retain that bounded approach, not split one 100-target review into different-time batches. Do not describe its separately acquired configuration/heartbeat/telemetry inputs as one globally atomic snapshot.

## 7. Complete mission pages before removing dashboard launchers

This is a required implementation step, explicitly requested by the owner. The goal is one complete operator path per mission, not deletion followed by broken or limited replacements.

| Mission | Capability transfer / verification gate |
| --- | --- |
| Smart Swarm | Verify dedicated entry, intended cluster/aircraft scope, takeoff, start, pause/stop, immediate and Managed Return, activity and recovery. Preserve Design/Capture/Revert contracts. Then retire the dashboard start wrapper. |
| Drone Show | Add explicit target selection with slot/package mapping validation; preserve supported immediate/delay/absolute scheduling through shared scheduling contracts, subject to existing mission timing admission. Verify every supported launch mode, origin/geometry, readiness, progress, cancellation, recovery and reload behavior. |
| Custom Show | Add a focused Operate path alongside setup/import: review active CSV identity and its local-only execution meaning, select exact aircraft, schedule/launch through existing mission contracts, monitor progress/outcomes, cancel/hold/land/return and recover after reload/uncertain submission. Do not mislabel one shared CSV as a multi-file SkyBrush show or silently treat it as a swarm-leader command. |
| Swarm Trajectory | Verify existing Start, package binding, scope, readiness, monitoring and receipt recovery. Correct active guidance that still says Dashboard-only. Then remove its dashboard launcher. |
| QuickScout | Regression-check its dedicated review/start/monitor/recovery workflow and navigation; remove only proven duplicates. |

Reuse typed command builders, scheduling, lifecycle and established dialogs rather than copying the old all-missions command form into every page. A shared implementation does not require identical mission-facing controls: local Custom CSV and mapped Drone Show have different setup semantics.

Existing timing capabilities must not be silently withdrawn during migration. Where an older UI advertises an option the backend legitimately rejects, preserve truthful review/admission rather than weakening timing rules. Any intentional capability retirement requires owner agreement.

Each mission page must pass its own end-to-end gate before its Overview launcher disappears. If parity is not complete, the cutover is not complete; do not leave two indefinitely competing normal interfaces or dead disabled shortcuts.

## 8. Implementation boundaries

Use four cohesive responsibilities, not a new global mega-store:

1. **Fleet resources:** bounded acquisition/cache for configuration, telemetry and runtime evidence; cancellation, response fencing and freshness clocks.
2. **Fleet view model:** pure identity/state/battery/altitude/freshness selectors consumed by Board, List, Map and inspector.
3. **Target selection:** explicit ID reducer plus scoped persistence, independent from filtering and inspection.
4. **Command intent/activity:** immutable review and existing submission/journal/recovery contracts, with a shared shell renderer.

Reuse `droneRuntimeStatus`, altitude/battery/identity helpers, `TakeoffDialog`, command services and `CommandActivityContext` after characterization tests. Keep modules under a cohesive feature boundary consistent with repository conventions. Views and tiles do not each fetch fleet data or mount their own command controllers.

No mandatory new state library, React-major upgrade or telemetry protocol is needed. The existing WebSocket has different enrichment from HTTP; switching transports is not itself proof of better truth or latency. Measure before adding virtualization; the installed data-grid dependency may serve the compact List if appropriate. Load maps lazily with a usable 2D/no-WebGL fallback.

Preserve shared command/API and automation contracts unless a specific change is required and documented. UI retirement does not make the command API or mission enums obsolete. Simurgh remains optional and separate from normal operator controls.

## 9. Finite implementation sequence

| Slice | Work | Exit gate |
| --- | --- | --- |
| 0. Baseline | Freeze the active consumer/route/action matrix, characterize truth and selection defects, inventory build headroom. | Exact migration list and safe validation environment known; unrelated edits preserved. |
| 1. Visual/task prototype | Read-only Board/List/Map and inspector at 1, 3, 20 and 100 aircraft; laptop/tablet/phone; representative alerts and action reviews. | Owner reviews the visual direction and beginner task flow before functional replacement. |
| 2. Truth and resources | Shared model/acquisition, freshness/unknown fixes, readiness 100-target contract and tool alignment. | Unit/API evidence for mixed and missing data, bounded fetches and cap boundaries. |
| 3. Selection and intent | Owner-approved default All/restore, stable cohorts, scoped persistence, immutable command review and recovery. | No filtering/reconnect/group-loss scenario can silently change reviewed recipients. |
| 4. Overview and shell | New aircraft views, inspector, general actions, consistent navigation, alerts and activity. | Responsive task flows, actual runtime contracts retained and outcomes survive navigation. |
| 5. Mission parity | Complete Custom Show operations and Drone Show target/scheduling gaps; verify the other workspaces. | Each dedicated page replaces every retained capability before its dashboard launcher is removed. |
| 6. Integrated validation | Small-fleet SITL, 100-aircraft replay/fixtures, device/accessibility/performance checks and failure scenarios. | Accepted mission scope recorded; material failures fixed, non-blocking polish becomes bounded TODOs. |
| 7. Retirement and release | Remove superseded components/styles/dependencies, update active docs/API/tool guidance, public/private integration and build/release records. | One canonical workflow, clean provenance/privacy check, verified deployment and rollback instructions. |

Review each slice once against its gate; reopen only for material evidence. Do not turn this into an unbounded cosmetic review cycle.

### Retirement checks

Audit real consumers before deleting `DroneWidget`, `ExpandedDronePortal`, `DroneCriticalCommands` and `CommandSender`. `DroneDetail` also serves a route, and `CommandPreflightSummary` imports `CommandSender.css`; replacing Overview alone does not prove those files/styles are unused.

Replace the old whole-object aircraft-detail route state with an ID-based inspector/navigation adapter before retiring it. Keep necessary bookmark redirects to the same canonical owner, not a second implementation. Inspect Globe/tactical card consumers independently.

Remove proven dead imports, styles, tests and packages together. Preserve backend command history, field evidence and historical documents; correct active docs and mark historical guidance where appropriate rather than erasing provenance.

## 10. Validation and acceptance

- **Truth:** fresh, degraded, stale, unseen, initializing, backend outage, hung/out-of-order requests, missing GPS/battery/altitude, and unknown flight phase. Never manufacture a valid value or permission from absence.
- **Selection:** first-use All; remembered subset/empty; removed IDs; new aircraft; disappearing groups; different runtime/operator contexts; filters/inspection/reconnect never retarget.
- **Commands:** reviewed IDs equal submitted IDs; native takeoff readiness and synchronized barrier; cancellation before release; rejection/partial/unknown outcomes; same-key lookup; reload and route-change recovery.
- **Readiness capacity:** 64, 65 and 100 targets accepted; 101 rejected; deterministic dedup/order; mixed evidence; bounded acquisition without per-target RPC.
- **Mission parity:** every retained mode, explicit targets, schedule choice, package/slot/origin binding, monitoring, cancellation and receipt recovery on the owning page. Custom CSV retains its distinct local-only contract.
- **Scale:** fixtures/replay for 1, 3, 20, 50 and 100 aircraft. Use a small two/three-aircraft SITL fleet for actual end-to-end execution, not 100 PX4 containers on a constrained server.
- **Responsive/accessibility:** representative 360/390-pixel phones, 768/1024 tablets and 1280/1440 laptops, landscape/portrait, 200% zoom, keyboard, touch, reduced motion and non-color state recognition. Target 44-pixel touch controls; do not misstate that as WCAG's AA minimum.
- **Performance:** one acquisition owner per resource; no per-tile or extra inspector fleet polling; bounded listeners/history/memory. Proposed interaction budget: p95 selection feedback below 100 ms desktop / 200 ms touch, to be measured rather than claimed. Include a 20-minute 100-aircraft fixture/navigation soak.
- **Real device:** browser emulation is not Safari/WebGL/device acceptance. Verify supported browser fallbacks and at least a representative touch device before claiming full cross-platform readiness.
- **Operator tasks:** identify a fault, select a subset, inspect without retargeting, take off, understand a partial result, navigate to a mission, return to activity, recover after refresh. Record completion and mistakes, not only screenshots.

No UI status constitutes field clearance. SITL and source tests do not establish collision avoidance, hardware calibration or operational authorization.

## 11. Resources, integration and handoff

Heavy tests/builds run on the verified remote validation/build host, not the resource-limited local workspace. The read-only assessment found under 1 GB free on that host: safe, scoped MDS artifact inventory/cleanup or approved additional capacity is a build prerequisite. Do not delete protected histories, flight evidence, unrelated projects or working release artifacts to manufacture a passing build.

Implement generic changes in official MDS, then integrate them into the private deployment while preserving customer identities, fleet/formation configuration, mission assets, auth/network settings and unrelated edits. Inspect both public files and outgoing history for private details. Keep stock SITL plug-and-play; do not force commercial credential provisioning into beginner demos.

Before a production restart, reconfirm all aircraft are powered off or grounded/disarmed with no active flight/test. Record the built commit and deployed artifact, verify REAL/SITL configuration and services, and smoke-test the actual served pages—not just source tests. Do not change aircraft roles/offsets or send motion commands during a dashboard release.

Retain a known working source/build rollback and an explicit revert procedure; rollback must not overwrite customer/runtime data. Tag/push only after the accepted scope and remaining limitations are recorded. Runtime/baked-asset changes require the documented image/release decision. A deferred immutable SITL image rebuild must be stated, not represented as a completed pinned-image release.

Handoff includes before/after screenshots, a short beginner action guide, updated source docs and agent lessons, exact official/private commit/tag/build state, checks performed and remaining required versus optional work. Prepare readable original-resolution guide assets and a compact shareable report; never place private fleet data in public examples.

## 12. Deliberately deferred follow-ups

- Broader mission/configuration-page field/theme harmonization beyond required capability transfer.
- Full Custom Show setup visual redesign beyond the complete required operation path.
- Fleet enrollment/maintenance and PX4 parameter-editor UX; no PX4 tuning changes are implied here.
- Mission Config origin/home and hardware-versus-slot clarity; map-provider/offline-tile parity.
- A separate bounded build-tool ADR/spike: [Create React App is deprecated](https://react.dev/blog/2025/02/14/sunsetting-create-react-app), but replacing the toolchain or upgrading React is not a prerequisite for this operational redesign.
- Optional PWA/install/versioned-cache work; offline command execution remains excluded.
- Broader database, signed-artifact, high-availability or control-authority modernization belongs to its own approved project.

## Implementation boundary

The owner approved this operating model, mission-parity obligations and staged scope, including autonomous continuation when a slice passes. Visual prototypes and task checks run on an isolated served build before production cutover. Production restart additionally requires the confirmed aircraft-off/grounded boundary. No flight-policy or PX4-tuning change is part of this implementation.

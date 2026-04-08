# QuickScout Tester Handoff

Date: 2026-04-08

## Status

QuickScout is now at a real v1 browser-tester handoff checkpoint on
`main-candidate`.

Validated commit:

- `f598ce89` — feature/runtime checkpoint used for live Hetzner validation

## Implemented V1 Scope

QuickScout now includes:

- durable GCS-backed mission workspace and recovery
- template-aware planning for:
  - `area_sweep`
  - `last_known_point`
  - `corridor_search`
- template-aware launch review
- tracked mission execution semantics:
  - launch
  - hold
  - abort
  - explicit `replan_required` doctrine instead of fake resume
- durable findings workflow
- evidence-reference editing on findings
- canonical mission handoff/export bundle
- finding-seeded follow-up planning
- monitor-mode mission/package context
- reusable SITL validation:
  - findings-aware single-drone runtime
  - findings-aware multi-drone runtime
  - template-complete single-drone runtime for area / point / corridor
  - reset-backed `quickscout_template_regression` bundled plan

## Map / UX Consistency Review

QuickScout and Swarm Trajectory are aligned where they should be aligned, but
they are not forced into one identical map editor.

Shared operator/system patterns already in use:

- shared app shell, tokens, and mission-stage workspace pattern
- shared map provider doctrine:
  - `MapProviderToggle`
  - `MapFallbackBanner`
  - `LeafletMapBase`
- shared searchable map utility pattern via the reused
  [`SearchBar`](/tmp/mavsdk_drone_show_resume/app/dashboard/drone-dashboard/src/components/trajectory/SearchBar.js)
- shared dashboard command lifecycle and selection/scope doctrine

Intentional mission-specific divergence:

- QuickScout uses search-geometry authoring and evidence/finding overlays
- Swarm Trajectory / Trajectory Planning use route-authoring and timing/heading
  authoring tools

That split is correct. Reusing the entire same map editor would be the wrong
abstraction. The consistency target is:

- same shell
- same operator rhythm
- same control vocabulary
- same provider/fallback behavior
- mission-specific authoring primitives only where the mission truly differs

Current assessment:

- **consistent enough for tester handoff**
- not a full single-component map system, by design

## What Is Still Deferred

These are explicit post-v1 items, not hidden defects:

- mid-mission add-drone / remove-drone retasking
- deeper airborne follow-up package generation from current mission state
- advanced retask / fault-injection SITL drills
- broader raw MAVLink / `mavlink2rest`-style debug surface if we later decide
  to expose one
- general frontend dependency modernization outside the QuickScout feature
  slice

## Hetzner Tester Stack

Current tester endpoints:

- Dashboard: `http://204.168.181.45:3030`
- Health: `http://204.168.181.45:5000/api/v1/system/health`

Expected live baseline before testing:

- backend health: `ok`
- active commands: `0`
- drones `1/2/3` online, idle, disarmed, ready

## Recommended Browser Test Flows

### 1. Area Sweep Planning

Operator should:

- open QuickScout
- choose `Area Sweep`
- draw a polygon
- select one drone
- review mission label / brief / return behavior
- compute the plan

Expected result:

- coverage preview appears on map
- launch review describes polygon search, not generic search language
- plan is recoverable if the page is refreshed

### 2. Last Known Point Planning

Operator should:

- choose `Last Known Point`
- set center from map center or direct selection
- adjust radius
- compute the plan

Expected result:

- circular footprint preview appears
- launch review reflects point-centered doctrine
- package is clearly distinguishable from polygon/corridor plans

### 3. Corridor Search Planning

Operator should:

- choose `Corridor Search`
- draw or append path points
- set corridor width
- compute the plan

Expected result:

- corridor strip preview appears
- launch review shows route-centered search context
- plan is visually and textually different from point/polygon search

### 4. Launch And Monitor

Operator should:

- launch a prepared QuickScout mission
- move to monitor mode
- observe phase and per-drone runtime notes

Expected result:

- mission enters active/searching state
- monitor surface preserves package context, not just raw drone status
- control availability is honest and phase-aware

### 5. Hold / Abort Doctrine

Operator should:

- send `Hold`
- verify the mission enters holding
- attempt resume if available in UI
- abort the mission

Expected result:

- hold is accepted cleanly
- direct resume is not faked; QuickScout should communicate replan doctrine
- abort returns the fleet to clean idle state

### 6. Findings / Evidence / Handoff

Operator should:

- create a finding
- edit its review state and evidence refs
- center map on the finding
- inspect the handoff/export panel

Expected result:

- finding persists in monitor mode
- evidence refs persist
- handoff panel updates counts and brief text
- follow-up planning can seed from the finding

### 7. Recovery

Operator should:

- refresh the browser during plan mode after computing a package
- refresh during monitor mode on an active or completed mission

Expected result:

- workspace recovers from durable backend state
- mission identity, template context, and findings state are not lost

## Notes For Testers

- QuickScout is ready for serious browser evaluation, but it is still a v1
  search-operations feature.
- If you find issues, classify them as:
  - workflow confusion
  - visual/readability issue
  - mission-state/reporting mismatch
  - launch/control/runtime defect
  - evidence/finding workflow gap
- The most important feedback is operational clarity, not cosmetic preference.

## Recommended Next Step After Tester Feedback

If browser testers confirm the current v1 flow is solid, the next engineering
slice should be:

1. mid-mission retasking doctrine and UX
2. deeper airborne follow-up package generation
3. stronger advanced SITL drills for retask/fault conditions

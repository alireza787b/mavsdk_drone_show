# QuickScout Audit And Redesign Brief

Date: 2026-04-07
Repo baseline: `195ea86e`
Scope: research, audit, and implementation planning only
Status: no QuickScout code changes proposed or applied yet

## Executive Summary

The current QuickScout subsystem is a useful proof of concept, but it is not ready to be treated as a production mission mode.

It currently behaves like:

- one page
- one planner family
- one in-memory mission manager
- one PX4 Mission upload path

That is enough for a demo, but not enough for a robust operational workflow.

The main recommendation is:

- do not incrementally polish the current QuickScout demo into production
- redesign it as a tracked search-operations workspace
- reuse the mature command, status, workspace, and testing patterns already proven in Swarm Trajectory
- keep only the parts of the current QuickScout implementation that are genuinely reusable

The most important product decision is that QuickScout should not be framed as "a SAR page that draws a polygon and launches a lawn-mower path." It should become a broader rapid-search mission system with multiple search templates and a durable mission record.

## What QuickScout Is Today

The current implementation already has a real vertical slice:

- frontend page: `app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js`
- SAR router: `gcs-server/sar/routes.py`
- schemas: `gcs-server/sar/schemas.py`
- planner: `gcs-server/sar/coverage_planner.py`
- mission/POI managers: `gcs-server/sar/mission_manager.py`, `gcs-server/sar/poi_manager.py`
- drone executor: `quickscout_mission.py`

What it currently does:

- operator draws a polygon
- operator selects drones
- GCS computes a boustrophedon coverage plan
- GCS partitions that plan across drones
- launch sends QuickScout mission commands to drones
- each drone uploads PX4 Mission items and flies them
- progress is reported back to GCS
- POIs can be created and monitored

That proves the concept, but the architecture is still PoC-grade.

## Current Implementation Assessment

### What Is Good Enough To Keep

- the typed schema layer is a good start
- the map interaction primitives are reusable
- the current planner math is reusable as one algorithm module
- the terrain adjustment helper is reusable
- the drone-side MAVSDK mission-upload path is reusable as one execution adapter
- the SAR router already follows the newer router-factory style

These parts are assets. They should not all be thrown away.

### What Is Not Good Enough To Build On As-Is

- mission and POI state are in-memory only
- resume semantics are not operationally real
- launch/control bypass the richer tracked command lifecycle used elsewhere
- the planner model is too narrow for real search operations
- the UI owns too much state locally and cannot recover cleanly after refresh or restart
- there is no SITL acceptance path for QuickScout
- the docs read closer to a finished feature than the code actually merits

### Concrete Current Gaps

1. Mission lifecycle is optimistic instead of authoritative.
   - `launch` marks missions executing after dispatch.
   - `resume` mainly updates GCS state.
   - `abort` is effectively RTL-oriented control.

2. Mission state is not durable.
   - GCS restart loses mission history.
   - browser refresh loses key context like generated route geometry.

3. Planning is too narrow.
   - one search-area type
   - one main search algorithm
   - weak reassignment/rebalancing story
   - no real search doctrine layer

4. Operator workflow is too page-centric.
   - draw
   - compute
   - launch
   - poll

That is not enough for a real search operations product.

5. The execution contract over-promises.
   - the system looks richer than the actual PX4 mission-control truth behind it
   - pause/resume especially needs more honest product design

### Specific PoC Defects Worth Fixing During Redesign

These are not reasons to patch the current demo forever. They are reasons to avoid pretending the current subsystem is already product-ready.

- when telemetry is missing, planning can silently fall back to `(0.0, 0.0)` aircraft positions instead of failing closed
- `survey_altitude_agl` is only meaningful through terrain-following adjustment; without that path, the operator-facing control is misleading
- `camera_interval_s` exists in the schema and UI, but the current flight payload/executor path effectively falls back to a default interval instead of clean end-to-end operator intent
- mission geometry is not durably recoverable through the API after refresh/restart
- mission/POI state and drone mission payloads are split across in-memory managers, browser state, and `/tmp`
- there is still no QuickScout SITL validator

## What We Learned From Swarm Trajectory

Swarm Trajectory is the right maturity reference, even though QuickScout is a different mission class.

The patterns worth reusing are:

- shared command submission and command tracking
- explicit workspace stages instead of "do everything on one page"
- service-driven backend with thin API routes
- session and freshness detection
- strong pre-launch validation
- clear operator doctrine in-product, not only in docs
- layered tests
- runtime validator pattern for SITL

The key lesson is:

QuickScout should become a mission-package workflow, not a page that computes a path and fires ad hoc launch calls.

## Public Research And Market Signals

These sources were used to ground the redesign direction:

1. DJI Search and Rescue
   - https://enterprise.dji.com/pt-br/mobile/public-safety/search-and-rescue
   - Search result content emphasized:
     - spiral route around last known location
     - drawing points, lines, and polygons
     - rapid 2D mapping
     - marking findings and sharing coordinates
     - thermal/visual switching during missions

2. DJI FlightHub 2
   - https://enterprise.dji.com/mobile/flighthub-2/faq
   - https://enterprise.dji.com/es/mobile/flighthub-2
   - Relevant signals:
     - one-stop cloud drone operations platform
     - remote operation
     - intelligent flight scheduling
     - route management
     - third-party integration
     - multimodal / algorithm integration
     - on-premises deployment option

3. Skydio remote response workflow
   - https://www.skydio.com/solutions/dfr/indoor-dfr
   - Relevant signals:
     - local launch, remote flight handoff
     - browser-accessible remote operation
     - operational emphasis on speed, visibility, and coordination
     - integrated data pipelines and live streaming

4. Search-and-rescue field practice
   - https://laplatasar.org/uas-search-patterns-search-rescue/
   - Relevant operational lessons:
     - drones are assignment-driven, not flown randomly
     - search pattern selection depends on mission phase, terrain, POD, hazards, and clues
     - grid is only one pattern among several
     - square spiral / spiral / alternating patterns matter in real search operations
     - pilot and analyst roles should be separated where possible
     - real-time updates back to mission coordination matter

5. Recent review literature
   - https://www.sciencedirect.com/science/article/abs/pii/S2212420925000238
   - Relevant signals:
     - multi-UAV coordination, sensor integration, and AI are active SAR directions
     - digital-twin / simulation-backed optimization matters
     - future value is in coordination, sensor fusion, and adaptable search planning, not one fixed pattern

## Current Test Reality

I verified the currently checked-in QuickScout backend test subset:

- `tests/test_sar_schemas.py`
- `tests/test_sar_coverage_planner.py`
- `tests/test_sar_api.py`
- `tests/test_gcs_sar_routes.py`

Current result:

- `52 passed`
- pytest exited non-zero because the repo-wide coverage gate measured `0%` total coverage for the global project target, not because the QuickScout tests themselves failed

Interpretation:

- the local QuickScout contract/unit tests are useful
- they do not prove runtime mission behavior
- they do not prove SITL execution
- they do not prove frontend workflow quality

## Product Reframe

QuickScout should be reframed as:

Rapid search and assessment operations for time-sensitive reconnaissance and search missions.

This includes at least:

- missing person / boat / vehicle search around a last-known point or uncertainty area
- rapid reconnaissance of a suspicious area before committing additional assets
- corridor search along shoreline, trail, road, or route-of-travel
- perimeter / boundary / near-shore / harbor-style sweep
- on-station observation around a critical point after initial search

This makes the feature broader and more future-proof than "SAR polygon grid mode."

## Recommended Mission Templates

V1 should not try to ship every algorithm, but the architecture should be template-first from day one.

Recommended initial template families:

1. Rapid Area Sweep
   - polygon area
   - one or more drones
   - grid/lawn-mower style coverage
   - this is the closest descendant of the current implementation

2. Last Known Point Search
   - point-centered
   - expanding square or spiral family
   - ideal for rapid first response

3. Corridor Search
   - line/path-centered
   - shoreline, trail, river, road, or route scan

4. Standoff Observation
   - point or small area
   - orbit/loiter/observe posture
   - useful for confirmation before escalation

Later template families:

- perimeter containment / boundary patrol
- dynamic re-tasked refinement around a finding
- multi-layer search with different sensors or altitudes

## Recommended Operator Workflow

QuickScout should adopt a staged operator workflow similar in discipline to Swarm Trajectory, but tuned for live search operations.

### Stage 1: Mission Type

Operator chooses a search template:

- area sweep
- last known point search
- corridor search
- standoff observation

### Stage 2: Scenario Inputs

Operator defines the mission package inputs:

- geometry: point, line, polygon, or imported marker set
- priority context: last known point, likely track, hazard, interest zones
- mission doctrine inputs: urgency, desired coverage quality, speed bias, sensor mode
- altitude / speed / overlap / terrain settings
- selected aircraft

### Stage 3: Package Generation

System computes a search package:

- recommended pattern
- per-drone assignments
- estimated duration
- search gaps / risk warnings
- terrain / comms / readiness notes

### Stage 4: Review

Operator reviews:

- package freshness
- selected drones and assignments
- command scope
- expected coverage
- mission assumptions and caveats

### Stage 5: Launch

Launch should go through the shared tracked command lifecycle, not QuickScout-local launch semantics.

### Stage 6: Monitor And Adjust

Operator sees:

- command lifecycle
- transiting / on-station / searching / holding / returning states
- findings
- per-drone status
- search-area progress
- ability to add drone, hold subset, abort subset, or plan a follow-up search package

### Stage 7: Conclude And Preserve

System should preserve:

- mission package
- assignments
- findings / POIs / notes
- timeline
- outcome state
- operator actions

## Architecture Recommendation

### Core Principle

Separate mission intent from execution adapter.

That means:

- planner/template layer decides what search should be flown
- execution adapter decides how each aircraft flies it

### Proposed Backend Structure

1. QuickScout domain service
   - mission package creation
   - lifecycle decisions
   - validation
   - state transitions
   - operator-facing status payloads

2. Template planners
   - `area_sweep`
   - `expanding_square`
   - `spiral`
   - `corridor`
   - later more

3. Assignment engine
   - partitions work across drones
   - understands search quality, duration, availability, and maybe later battery/sensor class

4. Execution adapters
   - `mission_mode_coverage`
   - later optional `orbit_or_observe`
   - later optional richer dynamic search adapters

5. Durable mission store
   - recommended: SQLite first on GCS
   - enough for single-GCS durable state without premature distributed complexity

6. Findings store
   - mission-linked POIs
   - timestamps
   - notes
   - status
   - later media references

7. Status/event projection
   - produces UI/MCP-friendly mission state
   - not just raw internal objects

## Data Model Recommendation

QuickScout needs a real mission aggregate instead of a loose mission manager singleton.

Recommended core records:

- `search_operation`
- `search_package`
- `search_assignment`
- `search_finding`
- `search_event`

Suggested status model:

- `draft`
- `planned`
- `ready`
- `queued`
- `dispatching`
- `accepted_partial`
- `accepted`
- `transiting`
- `on_station`
- `searching`
- `holding`
- `returning`
- `completed`
- `aborted`
- `failed`
- `degraded`

This is much more operationally honest than the current small set of states.

## Execution Recommendation

### V1

Use PX4 Mission mode as the default execution adapter for coverage-style search packages.

Reason:

- stable and simple for route-based search
- fits current stack
- already partially implemented

### Important Constraint

Do not present pause/resume as stronger than it really is.

For V1:

- hold and abort can be real control actions
- resume should only exist if operationally real for the chosen adapter
- otherwise the product should offer "replan from current state" instead of pretending true resume exists

### Later

For point observation or dynamic local assessment, add a second adapter family later:

- orbit / hold / local point observation adapter

This allows QuickScout to support both:

- planned coverage search
- rapid standoff confirmation

without turning one execution path into a mess.

## UI/UX Recommendation

The current QuickScout page should not just be polished. It should be redesigned around the staged workflow above.

### Strong Recommendations

- reuse the shared operator scope model instead of a QuickScout-only drone selector
- reuse command-monitor patterns instead of isolated launch-status messaging
- reuse map provider strategy already used elsewhere
- keep copy short and operational
- keep advanced tuning folded by default

### Important UX Principle

The map is primary.

The operator should feel like they are:

- defining the search problem
- reviewing the generated search package
- monitoring the search operation

not filling out a generic form.

### Monitor Surface Should Show

- package name / type
- mission state
- selected assets
- active findings
- current assignment coverage
- override actions
- recommended next actions when degraded

## API Recommendation

Do not leave QuickScout as a special isolated `/api/sar` island forever.

Recommended direction:

- keep current `/api/sar` stable only until redesign work lands
- redesign around the newer API discipline already used elsewhere
- make the resulting contracts MCP-friendly from day one

Suggested API shape after redesign:

- search operation resource
- package generation endpoint
- launch endpoint using shared command submission
- status resource
- finding resources
- optional map/evidence/artifact resources

Key requirements:

- typed request/response models
- explicit error envelopes
- machine-friendly status metadata
- durable identifiers
- minimal hidden side effects

## MCP / AI-Agent Readiness

QuickScout is one of the best candidates for future MCP integration, but only if its mission model is clean.

Recommended MCP-facing design principles:

- mission templates should be explicit and typed
- package generation should be deterministic and inspectable
- status should be queryable as structured state, not scraped from logs
- findings should be first-class entities
- overrides should be safe, typed actions
- generated recommendations should be explainable

That means the redesign should already assume future tools may:

- ask for suggested search packages
- compare packages
- launch a selected package
- monitor status
- create or confirm findings
- hand off to another mission mode afterward

## Real-World Operational Recommendations

These are important enough to shape the design now:

1. Search patterns must be assignment-driven, not generic.
2. Pattern choice must depend on mission phase and geometry.
3. Search quality is not just path geometry.
   - altitude
   - speed
   - overlap
   - camera angle
   - terrain
   - visibility
4. Roles matter.
   - pilot/operator
   - analyst/observer
   - mission coordination
5. Findings must be easy to mark, review, and communicate.
6. Comms loss and intermittent bandwidth must be assumed.
7. Mission history and audit trail matter much more here than in purely transient actions.

## Recommended V1 Scope

To keep this shippable, V1 should be narrower than the final architecture:

- one durable search-operation model
- one redesigned QuickScout workspace
- two usable templates:
  - area sweep
  - last known point search
- one primary execution adapter:
  - PX4 mission-mode route execution
- operator findings with notes and map markers
- shared tracked command lifecycle
- honest hold/abort behavior
- clear degraded-state handling
- full SITL validator

Deferred but planned:

- corridor search
- standoff observation adapter
- true dynamic mid-mission rebalancing
- automated detections/media pipeline
- richer camera control

## Recommended Implementation Phases

### Phase 0: Audit Closeout

- freeze current QuickScout as PoC baseline
- update docs to be explicit that redesign is planned
- preserve reusable assets list

### Phase 1: Domain And Data Model

- durable mission store
- durable findings store
- new state machine
- typed API models

### Phase 2: Planner/Template Layer

- planner interface
- area sweep planner
- last-known-point planner
- package generation metadata

### Phase 3: Execution Integration

- bind launch to shared command lifecycle
- clean drone execution adapter
- honest control semantics

### Phase 4: Operator Workspace

- redesign QuickScout UI
- stage-based workflow
- map-first review
- findings and monitor flow

### Phase 5: Testing And SITL

- backend unit/integration tests
- frontend workflow tests
- runtime validator
- reusable SITL plans

### Phase 6: Hardening

- low-bandwidth behavior
- restart/recovery
- degraded mission handling
- docs and operator guide

## What To Keep From The Current Code

Keep:

- selected map/drawing components
- schema ideas
- boustrophedon math as one planner module
- terrain helper logic
- mission upload path as one execution adapter

Replace or redesign:

- mission manager
- POI manager
- page-owned state model
- launch/control semantics
- current plan/monitor split
- assumption that one algorithm and one page equals a finished QuickScout feature

## What I Recommend We Do Next

After you review and confirm this brief, the next implementation turn should start with:

1. formal QuickScout product blueprint in repo docs
2. subsystem inventory cleanup and PoC/deferred notes
3. domain/data-model rewrite first
4. only then planner and UI work

I do not recommend starting with UI polish or adding more planner logic on the current in-memory design.

## Questions / Decisions For You

1. Do you want QuickScout V1 to ship with only:
   - area sweep
   - last known point search
or do you want corridor search included in first ship scope?

2. For V1 findings, is operator-marked geotagged observation enough, or do you want a stronger initial requirement for image/media evidence linkage?

3. Do you want QuickScout mission history to persist only locally on GCS first, or do you want us to reserve schema space immediately for future multi-GCS sync/export?

4. Do you want the term "QuickScout" kept as the operator-facing mode name, or should it become a broader search-operations label later while keeping the internal mission type for compatibility?

## Final Recommendation

Proceed with a redesign, not an incremental polish.

Use Swarm Trajectory as the quality/process benchmark, but not as the mission-behavior template. QuickScout should become a search-operations system with modular templates, tracked command lifecycle, durable mission state, and honest operational semantics.

That is the cleanest path to something future-proof, SITL-testable, operator-friendly, and later MCP/AI-agent ready.

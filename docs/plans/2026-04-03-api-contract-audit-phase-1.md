# 2026-04-03 API Contract Audit Phase 1

## Scope

This phase freezes the current API surface at the stable checkpoint on `fa567df0`, inventories the active contracts on both the GCS and drone sides, and defines the migration rules for the API cleanup program before any breaking route changes start.

The goal is not a big-bang rename. The goal is a controlled migration from the current mixed legacy surface to one canonical, versioned API contract that is:

- modular
- testable
- typed
- MCP-ready
- straightforward to extend for future missions, auth, automation, and operator tools

## Current Live Surface

### Active business routes

- GCS FastAPI currently exposes `91` business HTTP routes and `3` WebSocket routes.
- Drone FastAPI currently exposes `14` business HTTP routes and `1` WebSocket route.
- The GCS surface is split across:
  - `gcs-server/app_fastapi.py`
  - `gcs-server/log_routes.py`
  - `gcs-server/sar/routes.py`
- The drone surface is concentrated in:
  - `src/drone_api_server.py`

### Active consumer pattern

- The React dashboard uses a mixed contract:
  - older verb-style routes such as `/get-config-data`, `/save-gcs-config`, `/get-origin`
  - newer namespace routes such as `/api/telemetry`, `/api/logs/*`, `/api/swarm/trajectory/*`, `/api/sar/*`
- Both GCS and drone already expose a partial `/api/v1/...` surface in live code:
  - GCS currently has v1 aliases for health, telemetry, heartbeats, and network status
  - drone currently has v1 aliases for state, preflight armability, commands, navigation home/global origin, system health, network status, swarm config, and local telemetry
- Most callers still bypass those v1 routes and hit older compatibility paths, so the cleanup program should standardize around the existing v1 seed instead of inventing a second competing versioned layout.
- GCS internal callers depend on literal drone/GCS routes in several places:
  - `gcs-server/command.py`
  - `gcs-server/log_proxy.py`
  - `src/heartbeat_sender.py`
  - `src/drone_setup.py`
  - `src/telemetry_subscription_manager.py`
  - `src/params.py`

### Important repo finding

- `gcs-server/swarm_trajectory_routes.py` still exists as an older Flask-era route file, but it is not mounted by the live FastAPI app. It is legacy code in the repo and is a documentation/migration hazard if left unmanaged.

## Concrete Findings

### 1. The system is a compatibility stack, not one clean API

The live contract mixes at least five styles:

- legacy verb-style routes: `/get-*`, `/save-*`, `/import-*`
- semi-REST routes: `/command/{id}`, `/commands/recent`
- versionless namespaced routes: `/api/logs/*`, `/api/swarm/trajectory/*`, `/api/sar/*`
- partial versioned aliases: `/api/v1/system/health`, `/api/v1/fleet/telemetry`, `/api/v1/drone/state`, etc.
- transport-specific streams: `/ws/*` and `/api/logs/*` SSE

This is the main cleanup driver.

### 2. Identifier semantics are inconsistent

The codebase uses these concepts in overlapping ways:

- `hw_id`: physical drone identity
- `pos_id`: mission/slot/formation identity
- `drone_id`: sometimes means `hw_id`, sometimes means `pos_id`
- `leader_id`: used without always stating whether that leader is a position or hardware identity

The redesign must stop using ambiguous path parameter names where identity kind matters.

### 3. Command payloads still expose legacy field conventions

Mission command payloads still use camelCase edge fields like:

- `missionType`
- `triggerTime`

That contract is deeply used by the dashboard, tracker, GCS dispatch path, and drone API handler. It should remain supported during migration, but it should not remain the canonical contract.

### 4. Typed schemas exist, but coverage is partial

The repo already has substantial Pydantic coverage in `gcs-server/schemas.py`, but the live API still mixes:

- typed routes with `response_model`
- raw `Request` parsing
- untyped JSON dict responses
- file and stream responses with custom shapes

The right next step is not “add types everywhere blindly”; it is to define canonical route families and give those families stable request and response models.

### 5. Long-running operations are not modeled consistently

Examples:

- command submission has a tracker and follow-up status endpoint
- git sync is synchronous from the API caller perspective, even though it represents a distributed operation
- show import and swarm trajectory processing return immediate result payloads but do not follow one shared async-operation pattern

That inconsistency makes automation and MCP tooling harder than it needs to be.

### 6. Streams are useful, but not organized by one policy

- fleet telemetry / heartbeats / git updates use WebSockets
- logs use SSE
- drone state uses its own WebSocket

This is not inherently wrong, but the transport policy is implicit. We should make the rule explicit:

- WebSocket for continuously refreshed fleet state
- SSE for append-only event/log streams
- plain HTTP for snapshots and mutations

### 7. Security and auth readiness are not yet designed into the route layout

The current routes are effectively open local-ops APIs. That is acceptable for current deployment assumptions, but the next contract must reserve clean insertion points for:

- auth dependencies
- service-to-service trust
- operator audit metadata
- per-route authorization scopes

### 8. MCP readiness requires more than “just expose endpoints”

For future MCP servers and AI automation, the API contract needs:

- stable machine-readable request/response schemas
- explicit operation identities
- predictable error categories
- consistent id naming
- structured metadata suitable for tool descriptions and tool-call wrappers

This is one reason the contract should move toward one canonical `/api/v1/...` shape, built on the existing partial v1 routes instead of extending the current mixed surface indefinitely.

## Design Decisions

### Compatibility policy

- No big-bang route replacement.
- New canonical routes will be introduced first.
- Existing routes remain as compatibility shims until all consumers are migrated and covered by tests.
- Legacy routes are only removed after:
  - zero frontend callers
  - zero internal callers
  - zero SITL workflow dependencies
  - docs updated
  - compatibility tests updated

### Canonical naming rules

- Paths use namespaced nouns, not `get-*` or `save-*`.
- New canonical root is `/api/v1`.
- JSON fields use `snake_case`.
- Legacy field aliases may be accepted at the boundary when needed.
- Path parameters must encode identity kind explicitly:
  - `{hw_id}`
  - `{pos_id}`
  - `{leader_hw_id}`
  - avoid generic `{drone_id}` unless the resource is explicitly identity-agnostic

### Canonical transport policy

- HTTP snapshot/query endpoints return typed JSON
- HTTP mutation endpoints return typed operation responses
- WebSocket endpoints carry fleet-state style streams
- SSE endpoints carry append-only event/log style streams

### Canonical mutation policy

- mutating routes should support an operator/client request identifier
- long-running/distributed actions should converge on an operation/job status model
- file responses and stream responses remain specialized, but their parent resources should still fit the same namespace model

## Target Canonical Namespaces

The proposed canonical route families are:

- `/api/v1/system/*`
- `/api/v1/fleet/*`
- `/api/v1/config/fleet`
- `/api/v1/config/swarm`
- `/api/v1/commands/*`
- `/api/v1/git/*`
- `/api/v1/origin/*`
- `/api/v1/shows/skybrush/*`
- `/api/v1/shows/custom/*`
- `/api/v1/swarm-trajectories/*`
- `/api/v1/logs/*`
- `/api/v1/sar/*`

Drone-side canonical families:

- `/api/v1/drone/state`
- `/api/v1/preflight/*`
- `/api/v1/drone/commands`
- `/api/v1/navigation/*`
- `/api/v1/network/*`
- `/api/v1/swarm/*`
- `/api/v1/telemetry/*`
- `/api/v1/drone/logs/*`

Existing live v1 families should be preserved where they already exist instead of being renamed again.

## Canonical Mapping Direction

Examples of the intended migration direction:

- `/ping` and `/health` -> `GET /api/v1/system/health`
- `/telemetry` and `/api/telemetry` -> `GET /api/v1/fleet/telemetry`
- `/get-heartbeats` and `/heartbeat` / `/drone-heartbeat` -> `GET/POST /api/v1/fleet/heartbeats`
- `/get-network-status` -> `GET /api/v1/fleet/network-status`
- `/get-config-data` -> `GET /api/v1/config/fleet`
- `/save-config-data` -> `PUT /api/v1/config/fleet`
- `/validate-config` -> `POST /api/v1/config/fleet/validation`
- `/get-swarm-data` -> `GET /api/v1/config/swarm`
- `/save-swarm-data` -> `PUT /api/v1/config/swarm`
- `/request-new-leader` -> `PATCH /api/v1/config/swarm/assignments/{hw_id}`
- `/submit_command` -> `POST /api/v1/commands`
- `/command/{command_id}` -> `GET /api/v1/commands/{command_id}`
- `/command/execution-start` -> `POST /api/v1/command-reports/execution-start`
- `/command/execution-result` -> `POST /api/v1/command-reports/execution-result`
- `/git-status` -> `GET /api/v1/git/status`
- `/sync-repos` -> `POST /api/v1/git/sync-operations`
- `/get-origin` and `/set-origin` -> `GET/PUT /api/v1/origin`
- `/get-origin-for-drone` -> `GET /api/v1/origin/bootstrap`
- `/elevation` -> `GET /api/v1/origin/elevation`
- `/get-position-deviations` -> `GET /api/v1/origin/deviations`
- `/compute-origin` -> `POST /api/v1/origin/compute`
- `/get-desired-launch-positions` -> `GET /api/v1/origin/launch-positions`
- `/get-show-info` -> `GET /api/v1/shows/skybrush`
- `/download-raw-show` -> `GET /api/v1/shows/skybrush/archives/raw`
- `/download-processed-show` -> `GET /api/v1/shows/skybrush/archives/processed`
- `/get_drone_state` -> `GET /api/v1/drone/state`
- `/api/live-armability` -> `GET /api/v1/preflight/armability`
- `/api/send-command` -> `POST /api/v1/drone/commands`
- `/get-home-pos` -> `GET /api/v1/navigation/home`
- `/get-gps-global-origin` -> `GET /api/v1/navigation/global-origin`
- `/get-network-status` on drone -> `GET /api/v1/network/status`
- `/get-swarm-data` on drone -> `GET /api/v1/swarm/config`
- `/get-local-position-ned` -> `GET /api/v1/telemetry/local-position`
- `/import-show` -> `POST /api/v1/shows/skybrush/import`
- `/get-comprehensive-metrics` -> `GET /api/v1/shows/skybrush/metrics`
- `/get-safety-report` -> `GET /api/v1/shows/skybrush/safety-report`
- `/validate-trajectory` -> `GET /api/v1/shows/skybrush/validation`
- `/deploy-show` -> `POST /api/v1/shows/skybrush/deployments`
- `/get-show-plots` -> `GET /api/v1/shows/skybrush/plots`
- `/get-show-plots/{filename}` -> `GET /api/v1/shows/skybrush/plots/{filename}`
- `/get-custom-show-info` -> `GET /api/v1/shows/custom`
- `/import-custom-show` -> `POST /api/v1/shows/custom/import`
- `/get-custom-show-image` -> `GET /api/v1/shows/custom/preview`
- `/api/swarm/trajectory/*` -> `/api/v1/swarm-trajectories/*`

Notes:

- `logs` and `sar` are already closer to the desired model than most of the legacy core routes.
- The existing v1 aliases for fleet/drone read paths should be treated as the migration seed, not as temporary side experiments.
- This does not require immediate removal of `/api/logs/*` or `/api/sar/*`; it means the rest of the API should be brought up to the same contract quality level.

## MCP and Automation Readiness

This migration is being designed so the HTTP contract can later back MCP servers and agent workflows cleanly.

That means the canonical API must favor:

- typed request/response models
- stable resource names
- explicit operation states
- structured error responses
- predictable pagination/filter semantics
- metadata clean enough to map to MCP tools/resources later

Reference direction for the next phases:

- align route contracts with machine-oriented tool invocation, not only human dashboard fetches
- keep operation payloads concise and explicit
- avoid hidden side effects behind vaguely named routes
- keep auth and authorization pluggable at router boundaries

## Migration Phases

### Phase 1

- freeze current surface
- add route-inventory tests
- record the active contract and target design

### Phase 2

- create shared API contract conventions:
  - response envelope rules
  - error model
  - id semantics
  - route naming rules
  - async operation rules
- create canonical router layout under `/api/v1`

### Phase 3

- migrate read-only core GCS routes first:
  - system
  - fleet telemetry
  - heartbeats
  - network
  - origin reads

### Phase 4

- migrate config/origin mutation routes:
  - fleet config
  - swarm config
  - leader reassignment
  - origin set/compute/launch positions

### Phase 5

- migrate command lifecycle routes:
  - submit
  - status
  - recent/active/statistics
  - execution start/result
  - cancellation policy

### Phase 6

- migrate show-management and swarm-trajectory routes
- clean file/download endpoint families

### Phase 7

- introduce drone-side `/api/v1/drone/*` routes
- migrate GCS internal callers to the canonical drone contract
- keep legacy drone aliases until all GCS callers are moved

### Phase 8

- remove dead legacy callers
- deprecate and then remove compatibility routes
- update docs, SITL scripts, and automation clients

## Testing Policy For This Program

Every migration phase must add or update:

- route inventory tests
- request/response contract tests
- compatibility tests for aliased legacy paths
- internal caller migration tests
- frontend service tests where a dashboard consumer changes
- SITL validation before removing any legacy route

## This Slice Delivers

- a durable API cleanup blueprint
- a machine-enforced business-route inventory test
- a new checkpoint that future context recovery can use instead of re-surveying the surface from zero

## Immediate Next Step

Phase 2 should introduce:

- a shared API contract conventions module/note
- canonical GCS router grouping for the first read-only route family
- compatibility shims with tests

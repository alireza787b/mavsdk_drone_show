# API Modernization Blueprint

Date: 2026-04-03
Status: In progress
Owner: API audit / modernization stream

## Purpose

This document is the source of truth for the API cleanup and migration effort across:

- GCS FastAPI HTTP routes
- GCS WebSocket and SSE streams
- drone-side FastAPI HTTP routes
- internal runtime HTTP callbacks between drones and GCS
- frontend API consumption patterns
- future MCP and AI-agent integration

## Why This Work Exists

The current API surface is mixed-generation:

- legacy verb-style routes like `/get-config-data`, `/save-swarm-data`, `/import-show`
- newer domain routes like `/api/logs/*`, `/api/sar/*`, `/api/swarm/trajectory/*`
- unprefixed operational routes like `/health`, `/submit_command`, `/git-status`
- duplicate or overlapping contracts like `/telemetry` vs `/api/telemetry`, `/heartbeat` vs `/drone-heartbeat`, `/get-network-status` vs `/get-network-info`

The result is workable but hard to extend cleanly, easy to document incorrectly, and not ideal for future MCP / LLM automation.

## Current Inventory Snapshot

As of 2026-04-03:

- GCS FastAPI main app exposes 71 HTTP/WebSocket routes in `gcs-server/app_fastapi.py`
- GCS log router exposes 11 routes under `/api/logs`
- GCS QuickScout router exposes 12 routes under `/api/sar`
- drone API exposes 15 HTTP/WebSocket routes in `src/drone_api_server.py`

Important active consumer groups:

- React dashboard pages and hooks
- frontend service wrappers
- drone runtime callbacks to GCS
- mission runtime code and SITL validation tools

Important migration hazards:

- frontend calls are spread across pages, hooks, utilities, and service files
- route changes without an adapter layer will break working mission flows
- some stale consumers already exist and cannot be treated as active compatibility requirements
- transport, file IO, git side effects, and orchestration are still mixed inside route handlers

## Design Goals

The target API must be:

- modular by subsystem
- versioned
- explicit about canonical vs compatibility routes
- typed where practical
- safe for CI and contract testing
- predictable for future MCP exposure
- usable by browser UI, desktop clients, automation, and LLM agents
- backward-compatible during migration
- ready for authentication and authorization layers even when auth stays disabled in current dev/demo environments
- backed by one current consumer path per domain instead of multiple parallel legacy frontend surfaces

## Naming Standard

Canonical routes will use:

- prefix: `/api/v1/...`
- nouns and subresources instead of `get-*` / `save-*` verbs
- stable plural collections where appropriate
- consistent path structure across GCS and drone services

Legacy routes remain temporarily available as compatibility aliases until the frontend, tooling, and runtime callers have been migrated and verified.

## Contract Standard

Canonical v1 routes should follow these rules:

- read routes return typed resource payloads or typed collection payloads
- mutation routes return explicit operation results with stable identifiers when side effects are asynchronous or multi-step
- errors should converge toward structured problem responses instead of ad hoc strings
- streams should converge on a documented event model instead of subsystem-specific one-offs

## Security and Auth Readiness Rules

Auth remains disabled for current development and demo workflows, but the contract must stay ready for future customer deployments that require it.

Canonical routes and service wrappers should therefore:

- keep clear subsystem boundaries so auth policy can be attached by router/domain later without rewriting every caller
- favor explicit resource IDs, target scopes, and operator intent in request bodies so later policy checks are machine-readable
- preserve stable response metadata and timestamps so future audit/auth layers do not require a second response redesign
- avoid page-owned secret handling or direct URL assembly in the frontend
- document any privileged mutation surfaces clearly so later token/session enforcement can be enabled without guesswork

This work does not enable auth yet. It keeps the API and frontend shape compatible with adding auth cleanly later.

## MCP and AI-Agent Readiness Rules

To support future MCP servers and LLM-based control flows, canonical routes should:

- use stable resource names and predictable JSON shapes
- expose typed metadata and timestamps
- prefer explicit IDs and scopes over UI-specific labels
- separate reads from control mutations
- preserve enough machine-readable context for tool execution, retries, and postmortem analysis

This work should make it straightforward to expose a later MCP layer without inventing a second parallel contract.

## Phase Plan

### Phase 1

- survey current GCS and drone routes
- map codebase consumers
- publish this blueprint
- introduce low-risk canonical `/api/v1/...` aliases for core health, telemetry, heartbeat, and drone control surfaces
- add tests for those aliases

### Phase 2

- centralize frontend API access behind typed service modules
- remove direct page-level ad hoc endpoint usage where practical
- classify stale consumers and dead routes

Phase 2 core checkpoint on 2026-04-03:

- introduced a shared semantic route/service layer in `app/dashboard/drone-dashboard/src/services/gcsApiService.js`
- migrated the highest-traffic dashboard/config/origin/command consumers onto that layer
- added focused frontend service tests and Hetzner-backed production-build validation
- left dynamic swarm-trajectory management routes, logs/SAR shared services, and show-management/download/static-asset URL builders for the next slice

Phase 2 completion checkpoint on 2026-04-03:

- migrated the remaining active frontend API callers in Drone Show import/export/visualization, Custom Show, QuickScout, Mission Details, and Swarm Trajectory onto shared route/service helpers
- centralized remaining log and SAR service route composition behind shared builders and dedicated tests
- removed the dead unrouted `ImportShow` / `FileUpload` path instead of preserving stale frontend compatibility code
- added a shared API error normalizer for page/service mutation flows
- hardened the dashboard build script for the Hetzner Node 22 runtime by setting an explicit heap budget and disabling production sourcemaps

### Phase 3

- extract GCS route domains out of `app_fastapi.py`
- extract drone route domains out of `drone_api_server.py`
- move shared route logic behind service functions instead of handler-local behavior

Phase 3 first checkpoint on 2026-04-03:

- extracted the first coherent GCS route domain into `gcs-server/api_routes/core.py`
- moved health, telemetry, heartbeat, and heartbeat-derived network-status routes behind `create_core_router(...)` while preserving the existing HTTP/WebSocket surface
- kept backend compatibility/patch seams stable by having the extracted router read attributes from the live `app_fastapi` module object at request time instead of capturing handler references during import
- added focused router-level coverage in `tests/test_gcs_core_routes.py`
- revalidated the extracted surface locally and on Hetzner with the combined `test_gcs_core_routes.py` and `test_gcs_api_http.py` batch

Phase 3 second checkpoint on 2026-04-03:

- extracted the Swarm configuration and Smart Swarm reassignment routes into `gcs-server/api_routes/swarm.py`
- moved swarm-cycle validation into that router module instead of leaving it as file-local logic inside `app_fastapi.py`
- preserved the existing live `/get-swarm-data`, `/save-swarm-data`, and `/request-new-leader` routes while keeping the same patchable dependency seam through the live `app_fastapi` module object
- updated the async swarm-save git path to use `asyncio.get_running_loop()`
- added focused router-level coverage in `tests/test_gcs_swarm_routes.py`
- revalidated the combined extracted-router surface locally and on Hetzner with `test_gcs_core_routes.py`, `test_gcs_swarm_routes.py`, and `test_gcs_api_http.py`

### Phase 4

- migrate configuration, origin, swarm, git, and show-management domains to canonical v1 routes
- keep legacy compatibility adapters during rollout

### Phase 5

- define canonical event-stream contracts for telemetry, command state, git sync, and logs
- align them with future MCP exposure

### Phase 6

- remove deprecated legacy routes only after frontend, runtime callers, SITL tools, docs, and tests are fully migrated and validated

Frontend dead code does not need to survive until phase 6. If a consumer is unrouted, unreferenced, and superseded by a validated live workflow, it should be removed during migration rather than kept as misleading pseudo-compatibility.

## Phase 1 Canonical Routes

The first alias slice introduces these canonical entry points:

### GCS

- `GET /api/v1/system/health`
- `GET /api/v1/fleet/telemetry`
- `POST /api/v1/fleet/heartbeats`
- `GET /api/v1/fleet/heartbeats`
- `GET /api/v1/fleet/network-status`

### Drone

- `GET /api/v1/system/health`
- `GET /api/v1/drone/state`
- `POST /api/v1/drone/commands`
- `GET /api/v1/preflight/armability`
- `GET /api/v1/navigation/home`
- `GET /api/v1/navigation/global-origin`
- `GET /api/v1/network/status`
- `GET /api/v1/swarm/config`
- `GET /api/v1/telemetry/local-position`

These routes do not remove legacy endpoints. They create a canonical migration target and an initial contract for tests, docs, and future MCP tooling.

## Non-Goals for Phase 1

Phase 1 does not yet:

- rename or remove legacy routes
- centralize all frontend callers
- normalize every response envelope
- replace WebSocket/SSE strategy
- rework show-management, git-sync, or origin workflows fully

Those are later slices after the first canonical surface is in place and verified.

# 2026-04-03 Operational HTTP Alias Retirement

## Goal

Retire the remaining versionless operational HTTP aliases and leave the canonical `/api/v1/fleet/*` and `/api/v1/git/*` routes as the only live GCS HTTP contract for heartbeats, network-status reads, git-status reads, and git sync operations.

## Scope Closed

- retired the remaining operational HTTP aliases:
  - `POST /heartbeat`
  - `POST /drone-heartbeat`
  - `GET /get-heartbeats`
  - `GET /get-network-status`
  - `GET /git-status`
  - `POST /sync-repos`
- kept the canonical operational HTTP surface:
  - `POST /api/v1/fleet/heartbeats`
  - `GET /api/v1/fleet/heartbeats`
  - `GET /api/v1/fleet/network-status`
  - `GET /api/v1/git/status`
  - `POST /api/v1/git/sync-operations`
- moved the remaining real runtime caller to the canonical heartbeat route by changing `Params.gcs_heartbeat_endpoint` to `src.gcs_api_routes.GCS_FLEET_HEARTBEATS_ROUTE`
- updated request-log classification and route-inventory coverage so the retired aliases are asserted absent instead of quietly tolerated
- updated the shared frontend GCS route resolver/tests and the active operator/developer docs so the removed aliases do not survive as misleading pseudo-compatibility

## Validation

- local focused backend batch: `32 passed`
- Hetzner focused backend batch: `32 passed`
- Hetzner shared frontend service Jest: `1 suite passed, 21 tests passed`
- Hetzner production build: passed

## Remaining API Debt

- unversioned GCS WebSocket streams that still need an explicit canonicalization decision:
  - `/ws/telemetry`
  - `/ws/heartbeats`
  - `/ws/git-status`
- separately namespaced domains that still need an explicit versioning decision:
  - `/api/logs/*`
  - `/api/sar/*`

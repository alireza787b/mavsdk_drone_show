# 2026-04-03 Legacy Route Retirement Audit

Update later on 2026-04-03: the deferred versionless Swarm Trajectory family was closed in the Phase 4 fifteenth checkpoint after canonicalization to `/api/v1/swarm-trajectories/*`.
Update later on 2026-04-03: the previously retained operational HTTP aliases were closed in the Phase 4 sixteenth checkpoint after the remaining runtime/default caller moved to the canonical `/api/v1/fleet/*` and `/api/v1/git/*` routes.

## Goal

Classify the remaining public GCS legacy route families after Phase 4I so retirements happen intentionally instead of opportunistically.

## Remove Now

- deprecated git detail routes
  - already removed in Phase 4I:
    - `GET /get-gcs-git-status`
    - `GET /get-drone-git-status/{drone_id}`
- management/static alias cluster
  - targeted in the next slice:
    - `GET /get-gcs-config`
    - `POST /save-gcs-config`
    - `GET /get-network-info`
    - `GET /static/plots/{filename}`
  - reason:
    - no remaining live dashboard callers
    - no runtime-tooling or validation-script callers
    - canonical replacements already exist and are validated

## Keep Temporarily

- WebSocket operational streams
  - `WS /ws/telemetry`
  - `WS /ws/heartbeats`
  - `WS /ws/git-status`
  - reason:
    - these are stream-contract decisions, not leftover versionless HTTP business aliases
    - Phase 5 still needs to decide whether the canonical future shape stays WebSocket-first, gains `/api/v1/...` stream names, or adopts a different event contract for MCP-facing tooling

## Defer With Reason

- namespaced logs domain
  - `/api/logs/*`
  - reason:
    - this family is already namespaced and stable, but it still needs an explicit decision on whether it remains a dedicated subsystem root or moves under `/api/v1/...`
- namespaced SAR / QuickScout domain
  - `/api/sar/*`
  - reason:
    - this family is already namespaced and stable, but it still needs an explicit decision on whether it remains a dedicated subsystem root or moves under `/api/v1/...`

## Notes

- This audit intentionally separates “safe to remove now” from “needs an explicit stream/domain contract decision”.
- After Phase 4P, the versionless HTTP alias cleanup is effectively closed. The remaining decisions are stream canonicalization and whether logs/SAR keep their current namespaced roots or move under `/api/v1/...`.

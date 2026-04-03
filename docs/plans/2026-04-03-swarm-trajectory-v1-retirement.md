# 2026-04-03 Swarm Trajectory v1 Retirement

## Goal

Retire the versionless Swarm Trajectory HTTP family and leave `/api/v1/swarm-trajectories/*` as the only live GCS contract for uploads, processing, status, policy, cleanup, and downloads.

## Scope Closed

- retired the versionless Swarm Trajectory routes:
  - `GET /api/swarm/leaders`
  - `POST /api/swarm/trajectory/upload/{leader_id}`
  - `POST /api/swarm/trajectory/process`
  - `GET /api/swarm/trajectory/recommendation`
  - `GET /api/swarm/trajectory/status`
  - `GET /api/swarm/trajectory/policy`
  - `POST /api/swarm/trajectory/clear-processed`
  - `POST /api/swarm/trajectory/clear`
  - `POST /api/swarm/trajectory/clear-leader/{leader_id}`
  - `DELETE /api/swarm/trajectory/remove/{leader_id}`
  - `GET /api/swarm/trajectory/download/{drone_id}`
  - `GET /api/swarm/trajectory/download-kml/{drone_id}`
  - `GET /api/swarm/trajectory/download-cluster-kml/{leader_id}`
  - `POST /api/swarm/trajectory/clear-drone/{drone_id}`
  - `POST /api/swarm/trajectory/commit`
- kept the canonical Swarm Trajectory surface:
  - `GET /api/v1/swarm-trajectories/leaders`
  - `POST /api/v1/swarm-trajectories/upload/{leader_id}`
  - `POST /api/v1/swarm-trajectories/process`
  - `GET /api/v1/swarm-trajectories/recommendation`
  - `GET /api/v1/swarm-trajectories/status`
  - `GET /api/v1/swarm-trajectories/policy`
  - `POST /api/v1/swarm-trajectories/clear-processed`
  - `POST /api/v1/swarm-trajectories/clear`
  - `POST /api/v1/swarm-trajectories/clear-leader/{leader_id}`
  - `DELETE /api/v1/swarm-trajectories/remove/{leader_id}`
  - `GET /api/v1/swarm-trajectories/download/{drone_id}`
  - `GET /api/v1/swarm-trajectories/download-kml/{drone_id}`
  - `GET /api/v1/swarm-trajectories/download-cluster-kml/{leader_id}`
  - `POST /api/v1/swarm-trajectories/clear-drone/{drone_id}`
  - `POST /api/v1/swarm-trajectories/commit`
- updated the shared frontend route resolver and Swarm Trajectory helpers so the dashboard no longer references the retired versionless paths
- updated the reusable runtime validation helper to call the canonical status/process routes through shared Python constants
- removed a dead block of unused trajectory schema models that still documented non-existent legacy endpoints

## Validation

- local focused backend batch: `12 passed`
- local runtime-validator syntax check: `python3 -m py_compile tools/validate_swarm_trajectory_runtime.py`
- Hetzner focused backend batch: `12 passed`
- Hetzner shared frontend service Jest: `2 suites passed, 26 tests passed`
- Hetzner production build: passed

## Remaining API Debt

- explicitly retained operational aliases:
  - `GET /get-heartbeats`
  - `GET /get-network-status`
  - `POST /heartbeat`
  - `POST /drone-heartbeat`
  - `GET /git-status`
  - `POST /sync-repos`
- separately namespaced domains that still need a deliberate canonicalization decision rather than opportunistic churn:
  - `/api/logs/*`
  - `/api/sar/*`

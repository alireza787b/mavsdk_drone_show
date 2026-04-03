# 2026-04-03 Management and Static Legacy Route Retirement

## Scope

Phase 4, tenth API-modernization checkpoint:

- remove `GET /get-gcs-config`
- remove `POST /save-gcs-config`
- remove `GET /get-network-info`
- remove `GET /static/plots/{filename}`

The canonical management/static surface remains:

- `GET /api/v1/system/gcs-config`
- `PUT /api/v1/system/gcs-config`
- `GET /api/v1/fleet/network-details`
- `GET /api/v1/swarm-trajectories/plots/{filename}`

## Retirement Decision

- This cluster has no remaining live dashboard callers.
- It also has no runtime-tooling or validation-script callers.
- The frontend had already moved to the canonical route set, so the remaining debt was only:
  - backend compatibility mounts
  - route-resolver leftovers
  - docs/tests that still referenced the removed aliases

## Local Validation

- backend:
  - `18 passed`
- frontend shared GCS service Jest slice:
  - not run locally in the recovery worktree because `node_modules` are absent there

## Hetzner Validation

- backend:
  - `18 passed`
- frontend shared GCS service Jest slice:
  - `21 passed`
- production dashboard build:
  - passed

## Notes

- This slice follows the same policy as the git-detail retirement: remove routes only when the canonical replacement is already live and the alias has no remaining operational value.
- The next broader retirement candidate after this slice is the configuration/swarm family, but that should be handled as one deliberate domain pass rather than route-by-route.
- Hetzner validation for this slice used a fresh temporary copy of the clean runtime checkout at `e592dd52` so the results were isolated from older long-lived validation-tree drift.

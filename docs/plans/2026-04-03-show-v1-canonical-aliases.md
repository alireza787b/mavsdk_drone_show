# 2026-04-03 Show Management V1 Canonical Aliases

## Scope

Phase 4, sixth GCS canonical route slice:

- SkyBrush workflow:
  - `POST /api/v1/shows/skybrush/import`
  - `GET /api/v1/shows/skybrush`
  - `GET /api/v1/shows/skybrush/archives/raw`
  - `GET /api/v1/shows/skybrush/archives/processed`
  - `GET /api/v1/shows/skybrush/metrics`
  - `GET /api/v1/shows/skybrush/safety-report`
  - `GET /api/v1/shows/skybrush/validation`
  - `POST /api/v1/shows/skybrush/deployments`
  - `GET /api/v1/shows/skybrush/plots`
  - `GET /api/v1/shows/skybrush/plots/{filename}`
- Custom replay workflow:
  - `GET /api/v1/shows/custom`
  - `POST /api/v1/shows/custom/import`
  - `GET /api/v1/shows/custom/preview`

This slice keeps the legacy compatibility routes live:

- `POST /import-show`
- `GET /download-raw-show`
- `GET /download-processed-show`
- `GET /get-show-info`
- `GET /get-custom-show-info`
- `POST /import-custom-show`
- `GET /get-comprehensive-metrics`
- `GET /get-safety-report`
- `POST /validate-trajectory`
- `POST /deploy-show`
- `GET /get-show-plots`
- `GET /get-show-plots/{filename}`
- `GET /get-custom-show-image`

## Contract Decisions

- The canonical show surface is split by real operator workflow instead of leaving standard SkyBrush processing and specialist shared-CSV replay under one vague generic route family.
- SkyBrush ZIP processing and processed-show review live under `/api/v1/shows/skybrush/*`.
- The custom shared-CSV replay workflow lives under `/api/v1/shows/custom/*`.
- Canonical validation is `GET /api/v1/shows/skybrush/validation` because the route returns a read-only validation snapshot for the current processed show package. The legacy compatibility route remains `POST /validate-trajectory` during rollout.
- Canonical deployment is modeled as `POST /api/v1/shows/skybrush/deployments` so the mutation resource is explicit for future auth/MCP policy layers.

## Caller Migration

- The shared dashboard GCS service layer now uses the canonical show-management routes for:
  - show metadata
  - custom-show metadata
  - SkyBrush import
  - custom-show import
  - show plot discovery and direct plot URLs
  - raw and processed archive downloads
  - custom preview image URLs

## Local Validation

- `python3 -m pytest tests/test_gcs_show_management_routes.py tests/test_gcs_api_http.py::TestShowManagementEndpoints tests/test_gcs_api_http.py::TestAPIV1Aliases tests/test_api_route_inventory.py -q`
  - result: `34 passed`

## Hetzner Validation

- backend/tooling batch:
  - `34 passed`
- frontend shared GCS service Jest slice:
  - `17 passed`
- production dashboard build:
  - passed

## Notes

- Legacy routes remain mounted and explicitly covered by alias tests in this phase.
- The next clean boundary after this checkpoint is deliberate compatibility-route retirement planning and broader SITL regression coverage on the canonical GCS surface.

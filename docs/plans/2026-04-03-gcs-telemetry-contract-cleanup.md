Date: 2026-04-03
Status: completed
Owner: API modernization stream

Summary

- retired the duplicate GCS HTTP telemetry aliases `GET /telemetry` and `GET /api/telemetry`
- retired the nonfunctional `POST /api/v1/commands/{command_id}/cancel` endpoint
- moved the reusable live validators onto canonical `GET /api/v1/system/health` and `GET /api/v1/fleet/telemetry`
- updated request logging, route inventory, and shared frontend route resolution to stop treating the removed routes as compatibility surface
- fixed the LAND / RTL timeout fallback bug where GCS read `alt` instead of the drone contract's `altitude`

Validation

- local focused backend batch: `95 passed`

Notes

- this checkpoint does not close the full API modernization stream
- the next major boundary remains drone-side canonical route adoption and cleanup

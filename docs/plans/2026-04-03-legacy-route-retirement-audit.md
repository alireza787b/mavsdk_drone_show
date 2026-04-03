# 2026-04-03 Legacy Route Retirement Audit

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

- core fleet aliases
  - `GET /get-heartbeats`
  - `GET /get-network-status`
  - `POST /heartbeat`
  - `POST /drone-heartbeat`
  - reason:
    - still foundational operator/debug surfaces
    - broader telemetry/event-stream decisions are still open for Phase 5
- git operator aliases
  - `GET /git-status`
  - `POST /sync-repos`
  - `WS /ws/git-status`
  - reason:
    - still explicitly documented operator-facing surfaces
    - current retirement work only removed the deprecated one-off detail endpoints

## Defer With Reason

- configuration/swarm legacy family
  - `/get-config-data`
  - `/save-config-data`
  - `/validate-config`
  - `/get-drone-positions`
  - `/get-trajectory-first-row`
  - `/get-swarm-data`
  - `/save-swarm-data`
  - `/request-new-leader`
  - reason:
    - canonical replacements exist, but this is a broad business family and needs one cohesive retirement pass with caller/doc review
- origin legacy family
  - `/get-origin`
  - `/set-origin`
  - `/get-origin-for-drone`
  - `/get-gps-global-origin`
  - `/elevation`
  - `/get-position-deviations`
  - `/compute-origin`
  - `/get-desired-launch-positions`
  - reason:
    - active operator docs still refer to these workflows heavily
    - origin handling is safety-sensitive and should be retired as one deliberate slice
- show-management legacy family
  - `/import-show`
  - `/download-raw-show`
  - `/download-processed-show`
  - `/get-show-info`
  - `/get-custom-show-info`
  - `/import-custom-show`
  - `/get-comprehensive-metrics`
  - `/get-safety-report`
  - `/validate-trajectory`
  - `/deploy-show`
  - `/get-show-plots`
  - `/get-show-plots/{filename}`
  - `/get-custom-show-image`
  - reason:
    - operator docs and import/export workflows still describe both names
    - needs a coordinated documentation and SITL validation pass
- command legacy family
  - `/submit_command`
  - `/command/{command_id}`
  - `/commands/recent`
  - `/commands/active`
  - `/commands/statistics`
  - `/command/{command_id}/cancel`
  - `/command/execution-start`
  - `/command/execution-result`
  - reason:
    - high operational risk
    - must be retired only after another explicit runtime/tooling verification pass
- versionless Swarm Trajectory family
  - `/api/swarm/leaders`
  - `/api/swarm/trajectory/*`
  - reason:
    - this family has not been moved to `/api/v1/swarm-trajectories/*` yet
    - retire-after-canonicalization, not before

## Notes

- This audit intentionally separates “safe to remove now” from “looks old but still needs a domain retirement plan”.
- The next clean slice after the management/static retirement is likely the configuration/swarm family, because its canonical replacements already exist and its remaining debt is mostly route-surface duplication rather than missing API design.

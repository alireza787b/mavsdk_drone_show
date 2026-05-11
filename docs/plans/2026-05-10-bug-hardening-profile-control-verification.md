# MDS Bug Hardening And Sidecar Profile Control Verification

Date: 2026-05-10

This report verifies the implementation state of the May 10 hardening plan. It
is intentionally strict: items that are planned but not operator-ready are
listed as partial or deferred instead of being treated as complete.

## Current Verification Status

| Slice | Status | Evidence |
| --- | --- | --- |
| MAVSDK/ULog capability | Complete for diagnostics | Drone health and ULog policy include `ulog_capability`; ULog routes map missing `mavsdk_server` to actionable dependency errors. |
| Git corruption hardening | Complete for node sync baseline | `tools/update_repo_ssh.sh` uses scoped `flock`, stops broad Git lock deletion, avoids `git gc` field repair, and can clean-reclone with timestamped backup retention. |
| Shared sidecar status contract | Complete for read-only status | Smart Wi-Fi Manager and MAVLink Anywhere summaries expose common `tool`, `mode`, `service_state`, hash, drift, profile summary, and last apply fields. |
| Smart Wi-Fi Manager dashboard | Complete in sidecar release | Public Smart Wi-Fi Manager v2.1.9 includes add/edit/remove/re-prioritize UX, password entry from scan/manual add, import/export, confirmation on removal, and sanitized public screenshots. |
| Fleet Ops sidecar UI | Complete for read-only fleet posture; partial for mutating actions | Fleet Ops now shows a compact per-drone sidecar table for Smart Wi-Fi and MAVLink status, service state, mode, hashes/drift, and dashboard links. Full mutating actions are intentionally deferred until the node-side profile mutation contract is safe. |
| MAVLink Anywhere profile parity | Partial/deferred | MDS reports MAVLink Anywhere status and drift. Fleet-wide MAVLink profile import/export, node-as-reference, and strict reset-to-baseline remain deferred because node hardware/source overlays need a dedicated API contract. |
| Altitude/no-GPS policy | Partial | UI no longer couples core altitude display to map readiness in the cleaned paths and local altitude is supported. A global AGL/MSL/baro source selector is still deferred. |
| Release/sync handoff | Partial until live nodes reachable | Official/private repos are aligned at their latest synced heads. Live private GCS health is verified. Connected CM4 board sync verification requires the boards to be reachable over NetBird/API at handoff time. |

## What Is Shipped Now

- `mavsdk_server` remains required for MAVSDK-backed ULog and PX4 operations.
- Missing or non-executable `mavsdk_server` is visible in drone health and ULog
  policy, not hidden behind a generic HTTP 500.
- Node git sync uses one scoped lock and no longer deletes Git lock files
  broadly.
- If a repo is corrupt and in-place repair fails, node sync can move the
  damaged checkout to a timestamped backup, reclone the target branch, preserve
  allowlisted runtime artifacts, and report `recovery_action=clean_reclone`.
- Smart Wi-Fi Manager and MAVLink Anywhere share read-only sidecar vocabulary:
  `in_sync`, `local_extra`, `missing_fleet_baseline`, `outdated`, `unmanaged`,
  and `unreachable`.
- Fleet Ops sidecar tab includes a compact fleet posture table for both Smart
  Wi-Fi Manager and MAVLink Anywhere.
- Smart Wi-Fi repo profile rollout defaults to merge behavior so field-added
  networks are preserved and surfaced as drift instead of being pruned.
- GCS Runtime remains host-local. Fleet Ops remains fleet/node operational
  visibility and selected-node sidecar reconcile.

## Deferred But Tracked

- Fleet Ops mutating sidecar actions:
  accept node as reference draft, reset node to fleet baseline, export/import
  MAVLink fleet profile.
- `fleet-strict` as a first-class operator mode across both sidecars. Current
  Smart Wi-Fi support maps the approved fleet-merge behavior to `manage` plus
  import `merge`; MAVLink remains node/deployment-profile owned.
- Encrypted fleet Wi-Fi secrets using SOPS/age or a future MDS secret store.
- Optional auth/proxy for Smart Wi-Fi Manager and MAVLink Anywhere dashboards.
- Global altitude display preference across Dashboard, 3D Globe, Map, and cards
  for AGL/MSL/local/baro.
- Live CM4 sync verification whenever boards are reachable.

## Validation Commands

Run these before release:

```bash
bash -n tools/update_repo_ssh.sh
pytest tests/test_drone_api_http.py::TestDroneState::test_get_onboard_ulog_policy \
  tests/test_drone_api_http.py::TestDroneState::test_list_onboard_ulog_files_success \
  tests/test_drone_api_http.py::TestDroneState::test_list_onboard_ulog_files_reports_missing_mavsdk_server \
  tests/test_drone_api_http.py::TestDroneRouteSurface::test_v1_health_success \
  tests/test_managed_runtime_status.py \
  tests/test_git_sync_script_static.py -q
```

Heavy frontend/backend build validation should run on the Hetzner host, not on
the limited Linode host.

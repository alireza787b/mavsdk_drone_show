# MDS Sidecar Control, Altitude Policy, Release Hardening Progress

Date: 2026-05-12
Updated: 2026-05-13

## Scope

Tracks the approved sidecar-control, Fleet Ops/GCS Runtime cleanup, altitude
display policy, release hardening, private deploy, and board-sync phase.
Logo/rebranding and broad stale-worktree cleanup remain deferred.

## Handoff Inputs Read

- `/root/.codex/memories/mds_next_phase_plan_20260511.md`
- `/tmp/mds_next_phase_plan_20260511.md`

## Anchor Audit

| Area | Expected anchor | Observed state | Status |
| --- | --- | --- | --- |
| Official MDS worktree `/tmp/mds_official_current_20260510` | `1c9516fd9941982321b77fa35f9a763719e51f07` | Released `v5.3.61-sidecar-altitude-control` at `01513515`; dashboard lockfile patch in progress on branch `release/sidecar-altitude-sanitize-20260512`, tracks `origin/main` | Active official worktree |
| User-requested workspace `/opt/mavsdk_drone_show` | Work from path per prompt | Dirty `main-candidate`, behind `origin/main-candidate`, many pre-existing changes/deletions/untracked files | Preserved; not used for implementation |
| Smart Wi-Fi Manager audit repo `/tmp/audit_smart_wifi_manager_20260510` | `b81937abf10c2cbec050c62337d0f3076e2aad89` / `v2.1.9` | Released `v2.1.10` at `95cc7c2` with dashboard assets | Public sidecar release complete |
| MAVLink Anywhere audit repo `/tmp/audit_mavlink_anywhere_20260510` | `fd80c48c5e723641360ab11ef2004786a0641111` / `v3.0.8` | Released `v3.0.9` at `35f74ba` with dashboard assets | Public sidecar release complete |
| Private MDS worktree `/tmp/mds_private_current_20260510` | `c82c325001e23c9860254f197c4bb8e74a37e271` | Official release cherry-picked onto private branch `catchadrone-sidecar-altitude-20260512`; private-only operational config preserved | Pending lockfile patch, push, deploy, SITL |

## Security Rules In Force

- No real SSIDs, Wi-Fi passwords, NetBird node IPs, SSH passwords, tokens, keys,
  or mission data in public repos, docs, screenshots, fixtures, or reports.
- Fleet mutations require dry-run first and explicit confirmation second.
- `fleet-strict` is advanced/lab mode only and never a field default.
- GCS Runtime remains host-only; Fleet Ops owns drone-side sidecar controls.

## 2026-05-13 Detail UX Follow-Up

Operator review found that Fleet Ops Wi-Fi and MAVLink detail dialogs repeated
the compact table posture but did not expose the sanitized profile details
needed for fast field inspection. The follow-up fix keeps the table compact and
makes drift/last-apply cells clickable, while the reusable detail dialog now
shows:

- node-local Wi-Fi profiles beside the repo Wi-Fi baseline;
- node-local MAVLink input sources, node-local MAVLink endpoints, and the repo
  MAVLink endpoint baseline;
- only sanitized metadata: SSID/profile ID/priority/password state for Wi-Fi,
  and endpoint/source name/type/mode/address/port/device/baud for MAVLink.

The implementation also fixes string `last_apply_result` values such as
`local_extra` and `unmanaged` so the table no longer shows `n/a` for valid
reported states.

## Slice Status

| Slice | Status | Notes |
| --- | --- | --- |
| 1. Contract and API design | Complete | Shared schema, mode names, drift states, hash/redaction semantics, and route map documented in `docs/features/fleet-sidecar-profiles.md`. |
| 2. Smart Wi-Fi Manager fleet profile control | Public release complete; MDS release complete; detail UX follow-up implemented | Official MDS now has Fleet Ops sidecar APIs plus Wi-Fi profile control UI with compact table, sanitized node/baseline profile details, promote/job dialogs, dry-run/apply, policy mode changes, token header support, and unreachable-node opt-in. Smart Wi-Fi Manager `v2.1.10` includes command/log redaction and confirmation-token alias fixes. |
| 3. MAVLink Anywhere profile parity | Public release complete; MDS release complete; detail UX follow-up implemented | Backend route supports `mavlink-anywhere`; UI page mirrors Wi-Fi controls while preserving and exposing sanitized hardware-overlay/source details by default. MAVLink Anywhere `v3.0.9` is released. |
| 4. Fleet Ops/GCS Runtime cleanup | Released in official MDS | Direct dashboard UPDATE_CODE controls now route to Fleet Ops dry-run/apply; old direct Smart Wi-Fi profile import and legacy one-click sync UI/helpers were removed. GCS Runtime remains host-only. |
| 5. Altitude/no-GPS telemetry policy | Released in official MDS | Source-aware altitude report and dashboard/detail display changes are present. Typed GCS telemetry schema and API/operator docs now preserve/describe `relative_home`, `absolute_msl`, `local_ned`, and `baro` sources. |
| 6. Tests, docs, releases, deployment, board sync | In progress | Public sidecar releases and official MDS release are complete. Private sync/deploy, Hetzner build/SITL, hardware board sync, and final report remain. |

## Decisions Frozen

- Modes: `observe`, `local`, `fleet-merge`, `fleet-strict`.
- Drift states: `in_sync`, `local_extra`, `missing_fleet_baseline`,
  `outdated`, `unmanaged`, `unreachable`.
- Smart Wi-Fi Manager default: `fleet-merge`.
- MAVLink Anywhere default: `local` unless a fleet endpoint baseline exists.
- Hash semantics: `sha256:canonical-sanitized-payload:12`.
- Secret status vocabulary: `stored`, `missing`, `external file`, `redacted`.

## Resume Actions Completed

- Re-read both handoff plans.
- Reconfirmed official main-based worktree and avoided the stale dirty `/opt`
  tree for implementation.
- Reviewed uncommitted backend/frontend/docs/test state against the plan.
- Removed the unsafe old Fleet Ops direct Smart Wi-Fi profile import button.
- Added Fleet Ops mutation-token propagation for git sync and sidecar mutation
  API calls.
- Added dedicated Fleet Ops Wi-Fi and MAVLink sidecar control pages under
  `/fleet-ops/wifi` and `/fleet-ops/mavlink`.
- Preferred new `config/fleet-profiles/...` baselines over legacy deployment
  paths while keeping compatibility reads.
- Updated Makefile sync target to dry-run first.
- Normalized active Smart Wi-Fi and MAVLink sidecar policy modes to the frozen
  vocabulary: `observe`, `local`, `fleet-merge`, `fleet-strict`. Legacy
  `manage`/`managed` values are compatibility aliases only and are not emitted
  by updated UI, tests, bootstrap defaults, or docs.
- Removed the unused frontend legacy `useSyncDrones` hook and
  `syncReposResponse` helper. The global out-of-sync banner now links to Fleet
  Ops instead of invoking a deprecated one-click sync route.
- Converted `tests/test_gcs_management_routes.py` to the repository
  `SyncASGITestClient` to avoid the known Starlette TestClient lifespan
  deadlock.
- Fixed MDS reviewer blockers found after resume:
  - `observe` and `local` are inspect-only for reconcile.
  - Reconcile and policy dry-runs require explicit selected node IDs.
  - Fleet Ops disables reconcile outside `fleet-merge`/`fleet-strict`.
  - Typed GCS telemetry preserves `altitude_report`, `altitude_display_m`,
    `altitude_source`, `relative_altitude_m`, and `baro_altitude_m`.
  - Altitude guide/API docs and tactical card tooltips now use the frozen
    source vocabulary.
- Fixed Smart Wi-Fi Manager reviewer blockers found after resume:
  - Redacted sensitive command argv values before logging.
  - Redacted historical sensitive log lines returned by `/api/logs`.
  - Accepted `confirmation.confirmation_token` as an API alias for profile
    apply parity with MAVLink Anywhere.

## Current Risks And Open Items

- Final public leak scan is still required before official release; focused
  resume scans are clean except an expected placeholder NetBird setup-key
  example in operator docs.
- Heavy frontend build/browser checks must run on Hetzner, not this limited
  workspace.
- Sidecar repos are publicly released:
  - Smart Wi-Fi Manager `v2.1.10` / `95cc7c2`
  - MAVLink Anywhere `v3.0.9` / `35f74ba`
- Private merge/deploy and live board sync remain deferred until official public
  release artifacts are clean.

## Validation Log

2026-05-13 profile-detail follow-up validation:

- `python3 -m py_compile src/managed_runtime_status.py gcs-server/api_routes/fleet_sidecars.py` passed.
- `pytest tests/test_managed_runtime_status.py tests/test_gcs_fleet_sidecars_routes.py` passed: 23 tests.
- `npm test -- --watchAll=false --runTestsByPath src/pages/FleetOpsSidecarPage.test.js src/utilities/fleetOpsViewModel.test.js` passed: 2 suites, 19 tests.
- `git diff --check` passed.

Prior to this resume, focused validation was reported as:

- `python3 -m py_compile` on edited Python modules: passed.
- Focused backend suite: 62 passed.
- Focused frontend suite: 5 suites passed, 53 tests passed.
- Additional backend/bootstrap suite under escalated permissions: 120 passed.

Resume validation completed:

- `python3 -m py_compile gcs-server/api_routes/fleet_sidecars.py gcs-server/api_routes/git_status.py gcs-server/api_routes/commands.py src/telemetry_display.py src/drone_communicator.py src/local_mavlink_controller.py src/managed_runtime_status.py` passed.
- `pytest tests/test_gcs_fleet_sidecars_routes.py tests/test_gcs_git_routes.py tests/test_telemetry_display.py tests/test_drone_communicator.py tests/test_local_mavlink_controller.py tests/test_managed_runtime_status.py tests/test_env_registry.py tests/test_runtime_settings.py -q` passed: 63 tests.
- `npm test -- --watchAll=false --runTestsByPath src/pages/FleetOpsSidecarPage.test.js src/pages/FleetOpsPage.test.js src/services/gcsApiService.test.js src/components/DroneActions.test.js src/components/ControlButtons.test.js src/components/DroneWidget.test.js` passed: 6 suites, 57 tests.
- `npm test -- --watchAll=false --runTestsByPath src/config/routeDocs.test.js` passed: 1 suite, 5 tests.
- `python3 tools/audit_mds_env_registry.py` passed: 95 registered keys, 144 internal keys, 0 unclassified active refs.
- `git diff --check` passed.
- Focused public leak scan found no real NetBird node IPs, private keys, or sidecar placeholder secret/token strings in active code/docs outside ignored/generated paths.
- `npm test -- --watchAll=false --runTestsByPath src/pages/FleetOpsSidecarPage.test.js src/pages/FleetOpsPage.test.js src/pages/RuntimeAdminPage.test.js src/services/gcsApiService.test.js src/components/DroneActions.test.js src/components/ControlButtons.test.js src/components/DroneWidget.test.js src/components/DroneGitStatus.test.js src/utilities/fleetOpsViewModel.test.js src/config/routeDocs.test.js` passed: 10 suites, 81 tests.
- `bash -n tools/reconcile_connectivity.sh tools/reconcile_mavlink_runtime.sh tools/update_repo_ssh.sh tools/mds_init_lib/connectivity.sh tools/mds_init_lib/mavlink_setup.sh tools/mds_init_lib/identity.sh` passed.
- `pytest tests/test_bootstrap_installers.py tests/test_runtime_settings.py tests/test_managed_runtime_status.py tests/test_gcs_fleet_sidecars_routes.py tests/test_gcs_git_routes.py tests/test_telemetry_display.py tests/test_drone_communicator.py tests/test_local_mavlink_controller.py tests/test_env_registry.py tests/test_gcs_api_http.py::TestConfigurationEndpoints::test_connectivity_profile_status_is_secret_safe tests/test_gcs_api_http.py::TestConfigurationEndpoints::test_connectivity_profile_import_route_is_disabled tests/test_gcs_api_http.py::TestConfigurationEndpoints::test_connectivity_profile_import_route_does_not_validate_before_deprecation -q` passed: 172 tests.
- `pytest tests/test_gcs_management_routes.py::test_management_router_runtime_status_uses_live_runtime_and_profile -q` passed after converting that test file to `SyncASGITestClient`.
- `pytest tests/test_gcs_api_http.py::TestGCSManagementEndpoints::test_get_runtime_status tests/test_gcs_api_http.py::TestGitStatusEndpoints::test_get_git_status tests/test_drone_api_http.py::TestGitStatus::test_get_git_status -q` passed: 3 tests.
- `python3 -m py_compile gcs-server/api_routes/fleet_sidecars.py gcs-server/api_routes/git_status.py gcs-server/api_routes/commands.py gcs-server/api_routes/configuration.py gcs-server/schemas.py src/telemetry_display.py src/drone_communicator.py src/local_mavlink_controller.py src/managed_runtime_status.py src/settings/deployment_profile.py` passed.
- `python3 tools/audit_mds_env_registry.py` passed: 95 registered keys, 144 internal keys, 0 unclassified active refs.
- `git diff --check` passed.
- Focused exact-secret leak scan found no real NetBird node IPs, SSH private key blocks, or sidecar placeholder secret/token strings. A broader password-term scan only matched expected auth tests, password handling code, and redaction regexes.
- Smart Wi-Fi Manager after blocker fix:
  - `env PYTHONPATH=. pytest tests/test_smart_wifi_manager.py -q` passed: 16 tests.
  - `env GOCACHE=/tmp/mds_go_cache_swm_20260512 go test ./...` in `dashboard` passed.
  - `git diff --check` passed.
  - Built and uploaded `linux-amd64`, `linux-arm64`, and `linux-arm6`
    dashboard assets for `v2.1.10`.
- MAVLink Anywhere release-chain check:
  - `env GOCACHE=/tmp/mds_go_cache_ma_20260512 go test ./...` in `dashboard` passed.
  - Built and uploaded `linux-amd64`, `linux-arm64`, and `linux-arm6`
    dashboard assets for `v3.0.9`.
- MDS after reviewer blocker fixes:
  - `python3 -m py_compile gcs-server/api_routes/fleet_sidecars.py gcs-server/schemas.py` passed.
  - `pytest tests/test_gcs_fleet_sidecars_routes.py tests/test_schema_validation.py tests/test_telemetry_display.py tests/test_drone_communicator.py tests/test_local_mavlink_controller.py -q` passed: 70 tests.
  - `npm test -- --watchAll=false --runTestsByPath src/pages/FleetOpsSidecarPage.test.js src/components/TacticalDroneCard.test.js src/components/DroneWidget.test.js` passed: 3 suites, 14 tests.
  - Broader focused backend command passed: 207 tests.
  - Broader focused frontend command passed: 11 suites, 85 tests.
  - After updating official MDS sidecar pins to `v2.1.10` and `v3.0.9`,
    focused post-pin backend checks passed: 24 tests.
  - After updating official MDS sidecar pins, focused post-pin frontend checks
    passed: 4 suites, 24 tests.
  - `git diff --check` passed.
  - Targeted local leak scans found no private key block, live private GCS host
    value, or raw setup-key value in active official MDS/sidecar repos; the only
    MDS match was a placeholder setup-key example in `docs/guides/mds-init-setup.md`.
- Reviewer re-checks:
  - MDS reviewer reported no remaining blockers from the previous list and
    cleared the work for Slice 6 gates.
- Smart Wi-Fi Manager reviewer reported no remaining blocker for the command
  argv/log redaction or confirmation-token alias. Non-blocking note:
  assignment-style argv redaction is not currently used.
- Official MDS public release completed:
  - `v5.3.61-sidecar-altitude-control` at `01513515`
  - `origin/main` and `origin/main-candidate` updated to the release commit
  - GitHub release created
- Private integration started:
  - Created branch `catchadrone-sidecar-altitude-20260512` from the private
    anchor.
  - Cherry-picked the official sidecar/altitude release as `3f88f1b8`.
  - Resolved only `config.json` and `deployment/defaults.env`, preserving
    private operational values while updating sidecar defaults to
    Smart Wi-Fi Manager `v2.1.10`, mode `fleet-merge`, MAVLink Anywhere
    `v3.0.9`, and MAVLink management mode `local`.
  - Confirmed private-only Catch-A-Drone assets remained present.
- Dependency-audit hardening found during private verification:
  - Ran `npm audit fix` without `--force` in official MDS dashboard.
  - Dashboard lockfile now uses fixed runtime/transitive packages including
    axios `1.16.0`, follow-redirects `1.16.0`, proxy-from-env `2.1.0`,
    lodash `4.18.1`, and postcss `8.5.14`.
  - Remaining npm audit findings are tied to CRA/react-scripts build/test
    dependencies and require a separate breaking toolchain migration.

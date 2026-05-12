# MDS Sidecar Control And Altitude PM Handoff

Date: 2026-05-12

## Current State

Implementation for Slices 1-5 is complete and the public sidecar releases plus
official MDS release are complete. A follow-up official patch refreshes the
dashboard lockfile with safe npm audit fixes. Private merge/deploy,
Hetzner SITL validation, and hardware validation are still in progress.

Slice 6 remains the active release/deploy gate:

1. Carry the official MDS release and dashboard lockfile patch into the private
   Catch-A-Drone repo without overwriting private-only assets/config.
2. Run heavy frontend build/browser checks on
   Hetzner.
3. Deploy private GCS.
4. Run SITL validator before switching back to real mode.
5. Ask boards to be connected only after GCS is healthy, then dry-run/apply board
   sync with explicit confirmation.

## Initial Plan Coverage

| Slice | Coverage |
| --- | --- |
| 1. Contract/API design | Shared profile contract documented: modes, drift states, sanitized hash semantics, secret redaction, baseline paths, Fleet Ops route map. |
| 2. Smart Wi-Fi Manager | Fleet profile CLI/API/dashboard support is present. MDS Fleet Ops shows Wi-Fi baseline/node summaries, drift, promote draft, dry-run/apply, and policy mode changes. |
| 3. MAVLink Anywhere | MAVLink profile parity is present. Fleet baseline excludes node hardware overlays, and merge/strict behavior preserves local source settings by default. |
| 4. Fleet Ops/GCS Runtime | Drone-side controls are in Fleet Ops. GCS Runtime is host-only and links to Fleet Ops instead of duplicating sidecar actions. |
| 5. Altitude/no-GPS | Altitude is source-aware and independent of map readiness: `relative_home`, `absolute_msl`, `local_ned`, and `baro`. UI and typed telemetry now preserve source/freshness. |
| 6. Release/deploy/board sync | Public sidecar and official MDS releases are done. Private merge/deploy, Hetzner SITL, and hardware validation are still outstanding. |

## Extra Fixes Beyond The Initial Plan

- Removed legacy one-click drone repo sync UI/helper paths and deprecated direct
  generic update dispatch.
- Disabled the old direct Smart Wi-Fi profile import route in favor of Fleet Ops
  sidecar contract routes.
- Added Fleet Ops mutation-token propagation for git sync and sidecar mutation
  calls.
- Preferred `config/fleet-profiles/...` baselines while preserving legacy read
  compatibility.
- Added explicit selected-node requirements for reconcile and policy dry-runs so
  direct API callers cannot accidentally target the whole fleet.
- Fixed Smart Wi-Fi Manager command/log redaction so Wi-Fi passwords in `nmcli`
  command arguments are not exposed through local logs or `/api/logs`.
- Added Smart Wi-Fi Manager `confirmation.confirmation_token` alias parity with
  MAVLink Anywhere.
- Added typed GCS schema coverage for altitude policy fields so typed telemetry
  responses do not silently drop them.
- Refreshed the dashboard package lock with non-breaking npm audit fixes after
  release verification exposed an inherited dependency-audit issue.

## Reviewer Blockers Fixed

- `observe` and `local` are now inspect-only for reconcile in both API and UI.
- Reconcile is available only in `fleet-merge` and `fleet-strict`.
- Reconcile and policy dry-runs require explicit selected node IDs.
- Smart Wi-Fi Manager command argv logging and dashboard log API redaction are
  fixed.
- Smart Wi-Fi Manager apply accepts both `confirmation.token` and
  `confirmation.confirmation_token`.
- Altitude docs/API examples and tactical card tooltips now match the frozen
  source vocabulary.

## Validation Completed Locally

- MDS backend focused suite: 207 passed.
- MDS frontend focused suite: 11 suites, 85 tests passed.
- MDS targeted post-fix backend suite: 70 passed.
- MDS targeted post-fix frontend suite: 3 suites, 14 tests passed.
- Smart Wi-Fi Manager Python tests: 16 passed.
- Smart Wi-Fi Manager dashboard Go tests: passed.
- MAVLink Anywhere dashboard Go tests: passed.
- MDS and Smart Wi-Fi `git diff --check`: passed.
- Official dashboard npm audit after safe lockfile refresh: no critical
  findings; remaining findings are in the CRA/react-scripts build/test
  toolchain and require a separate breaking migration.
- Local targeted leak scans: no private key block, live private GCS host value,
  or raw setup-key value found in active official/sidecar repos. One expected
  placeholder setup-key example remains in operator docs.

## Release Status

The public sidecar releases and official MDS release are complete. Private
client MDS, private deploy, SITL validation, and hardware validation are still
pending.

| Repo | State |
| --- | --- |
| Official MDS | Public `v5.3.61-sidecar-altitude-control` released at `01513515`; follow-up dashboard lockfile patch is being tagged as the current official patch release. |
| Smart Wi-Fi Manager | Public `v2.1.10` released at `95cc7c2` with linux amd64/arm64/arm6 dashboard assets. |
| MAVLink Anywhere | Public `v3.0.9` released at `35f74ba` with linux amd64/arm64/arm6 dashboard assets. |
| Private client MDS | Sidecar/altitude release cherry-picked onto a private integration branch with private operational config preserved; lockfile patch still needs to be carried before push/deploy. |

## Remaining Debt And Notes

- Final public leak scan was run with targeted local scans; `gitleaks` and
  `trufflehog` are not installed in this Linode workspace.
- Heavy frontend build/browser checks must run on Hetzner, per the original
  operating rule.
- Board sync is intentionally blocked until boards are online and not in a
  field-critical window.
- Hardware validation cannot be claimed until boards are connected and checked.
- Remaining dependency debt: the dashboard still uses CRA/react-scripts 5.
  Non-breaking audit fixes are applied, but eliminating the residual
  react-scripts build/test-chain advisories requires a separate frontend
  toolchain migration.

## Tester Instructions For Next Gate

1. Run SITL validator with the release candidate after public repos are
   committed/tagged.
2. In Fleet Ops, verify all known drones appear in Wi-Fi and MAVLink sidecar
   tables with presence, service state, installed ref, mode, source, hashes,
   drift, profile count, dashboard link, and last apply result.
3. Open repo baseline and node summary dialogs. Confirm secrets show only
   status values, never passwords.
4. Confirm `observe` and `local` cannot run reconcile, and `fleet-merge` /
   `fleet-strict` require dry-run before apply.
5. Confirm `fleet-strict` requires advanced confirmation.
6. Confirm GCS Runtime has only host-side runtime/update/restart/auth/env/service
   controls and links back to Fleet Ops for drone sidecars.
7. In no-GPS/local-position SITL, verify dashboard cards, drone detail, tactical
   cards, map/globe surfaces, and tooltips show useful local/baro/relative
   altitude without saying `waiting for map`.
8. After SITL passes and live GCS is healthy, connect boards and run board sync
   dry-run before any apply.

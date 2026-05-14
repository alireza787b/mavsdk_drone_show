# MDS Sidecar Control And Altitude PM Handoff

Date: 2026-05-12
Reviewed: 2026-05-14

## Current State

Public implementation and release gates for this phase are complete through
official MDS `v5.3.87-overview-card-layout` at `a71a7fc6`, Smart Wi-Fi Manager
`v2.1.10` at `95cc7c2`, and MAVLink Anywhere `v3.0.9` at `35f74ba`.

This public PM handoff is intentionally sanitized. Customer/private deployment
state, board sync state, Wi-Fi profiles, NetBird addresses, and live hardware
validation belong in the downstream private PM handoff for that deployment, not
in this public repo.

Slice 6 is closed for the public release line. Downstream deployments should
still run their own Hetzner build/browser checks, SITL/real-mode validation,
and Fleet Ops dry-run/apply gates before tester handoff.

## Initial Plan Coverage

| Slice | Coverage |
| --- | --- |
| 1. Contract/API design | Shared profile contract documented: modes, drift states, sanitized hash semantics, secret redaction, baseline paths, Fleet Ops route map. |
| 2. Smart Wi-Fi Manager | Fleet profile CLI/API/dashboard support is present. MDS Fleet Ops shows Wi-Fi baseline/node summaries, drift, promote draft, dry-run/apply, and policy mode changes. |
| 3. MAVLink Anywhere | MAVLink profile parity is present. Fleet baseline excludes node hardware overlays, and merge/strict behavior preserves local source settings by default. |
| 4. Fleet Ops/GCS Runtime | Drone-side controls are in Fleet Ops. GCS Runtime is host-only and links to Fleet Ops instead of duplicating sidecar actions. |
| 5. Altitude/no-GPS | Altitude is source-aware and independent of map readiness: `relative_home`, `absolute_msl`, `local_ned`, and `baro`. UI and typed telemetry now preserve source/freshness. |
| 6. Release/deploy/board sync | Public sidecar and official MDS release are complete. Deployment-specific SITL, private GCS, and board sync validation are tracked in the private downstream handoff. |

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

The public sidecar releases and official MDS release are complete.

| Repo | State |
| --- | --- |
| Official MDS | Public `v5.3.87-overview-card-layout` released at `a71a7fc6`; `origin/main` and `origin/main-candidate` point at this release. |
| Smart Wi-Fi Manager | Public `v2.1.10` released at `95cc7c2` with linux amd64/arm64/arm6 dashboard assets. |
| MAVLink Anywhere | Public `v3.0.9` released at `35f74ba` with linux amd64/arm64/arm6 dashboard assets. |
| Private/customer deployments | Not described in this public document. Track customer-specific merge/deploy/board status in the private handoff only. |

## Remaining Debt And Notes

- Final public leak scan was run with targeted local scans; `gitleaks` and
  `trufflehog` are not installed in this Linode workspace.
- Heavy frontend build/browser checks should run on the deployment host for each
  downstream private deployment, per the operating rule.
- Board sync and live hardware validation are deployment-specific and cannot be
  claimed from the public repo alone.
- Remaining dependency debt: the dashboard still uses CRA/react-scripts 5.
  Non-breaking audit fixes are applied, but eliminating the residual
  react-scripts build/test-chain advisories requires a separate frontend
  toolchain migration.

## Tester Instructions For Next Gate

1. Run SITL validator with the release candidate after public repos are
   committed/tagged.
2. In Fleet Ops, verify all known drones appear in compact Wi-Fi and MAVLink
   sidecar tables with presence, service state, installed ref, mode, profile
   source, hashes, drift, profile/route count, dashboard icon link, and last
   apply result.
3. Open repo baseline and node detail dialogs. Confirm Wi-Fi details show
   sanitized network names/IDs/priority/password state, and MAVLink details show
   sanitized endpoints plus node-local input sources.
4. Confirm secrets show only status values such as `stored`, `missing`,
   `external file`, or `redacted`, never passwords, tokens, private keys,
   local secret-file paths, or raw profile bodies.
5. Confirm `observe` and `local` cannot run reconcile, and `fleet-merge` /
   `fleet-strict` require dry-run before apply.
6. Confirm `fleet-strict` requires advanced confirmation.
7. Confirm GCS Runtime has only host-side runtime/update/restart/auth/env/service
   controls and links back to Fleet Ops for drone sidecars.
8. In no-GPS/local-position SITL, verify dashboard cards, drone detail, tactical
   cards, map/globe surfaces, and tooltips show useful local/baro/relative
   altitude without saying `waiting for map`.
9. After SITL passes and live GCS is healthy, connect boards and run board sync
   dry-run before any apply.

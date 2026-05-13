# Fleet Sidecar Profile Contract

MDS treats Smart Wi-Fi Manager and MAVLink Anywhere as drone-side sidecars.
Fleet Ops may inspect, compare, dry-run, and explicitly reconcile their
profiles. GCS Runtime remains host-only and must not duplicate these controls.

This document is the MDS source of truth for sidecar profile modes, drift
states, sanitized hashes, redaction, and Fleet Ops API ownership.

## Policy Modes

Only these mode names are valid:

| Mode | Meaning | Mutation policy |
| --- | --- | --- |
| `observe` | Report only. Do not mutate the sidecar profile. | Apply is rejected. |
| `local` | The node-local sidecar dashboard/CLI is authoritative. | Fleet Ops may inspect and promote a sanitized draft only. |
| `fleet-merge` | Fleet baseline is applied while preserving local additions. | Dry-run plus explicit confirmation required. |
| `fleet-strict` | Fleet baseline is authoritative. Local drift may be pruned only after advanced confirmation. | Advanced/lab mode only; never a field default. |

Defaults:

- Smart Wi-Fi Manager: `fleet-merge`.
- MAVLink Anywhere: `local` unless a fleet endpoint baseline is explicitly configured.
- `fleet-strict` is never a default for field connectivity.

## Drift States

Only these drift states are valid:

| Drift state | Meaning |
| --- | --- |
| `in_sync` | Sanitized desired and local/applied hashes match. |
| `local_extra` | Local additions exist beyond the fleet baseline and are preserved. |
| `missing_fleet_baseline` | Fleet policy is expected but no repo baseline is configured. |
| `outdated` | A fleet baseline exists and the local/applied profile differs or is missing. |
| `unmanaged` | The sidecar is absent, intentionally local-only, or not under Fleet Ops policy. |
| `unreachable` | Fleet Ops cannot reach the node-local reporting surface. |

When only hashes are available, MDS reports a mismatch as `outdated` rather
than guessing whether the difference is a safe local addition.

## Hash And Secret Semantics

Profile hashes compare canonical sanitized payloads, never raw secrets.

- APIs never return Wi-Fi passwords, tokens, private keys, or raw secret material.
- Secret fields are redacted recursively.
- `*_file` secret fields are returned only as the `external file` state marker,
  not as local paths.
- UI may show only `stored`, `missing`, `external file`, or `redacted`.
- Public repositories may contain only sanitized demo profile examples.
- Private fleet repos may contain field Wi-Fi baselines only when approved for
  that deployment.

Hash semantics label: `sha256:canonical-sanitized-payload:12`.

Fleet Ops list views identify drones as `P{pos}|H{hw}`. Detail dialogs split
that compact label back into separate Pos ID and HW ID fields.

Fleet Ops detail dialogs may show sanitized operational metadata:

- Wi-Fi profile names/SSIDs, profile IDs, priority, disabled/autoconnect state,
  and password state.
- MAVLink endpoint/source names, endpoint type, mode, role, enabled state,
  address/port, serial device, and baud rate.

They must not show raw Wi-Fi passwords, tokens, private keys, secret-file paths,
or raw profile bodies. Use exact language when reviewing UI: **profile source**
means where the sidecar profile came from; **MAVLink input source** means the
node-local serial/UDP/PX4 input overlay.

To avoid repeated rows in node detail dialogs, Fleet Ops shows repo baseline
profiles separately from node-only additions or overlays. A profile or endpoint
that exactly matches the baseline should not be listed twice in the same detail
dialog.

## Fleet Baseline Locations

Preferred repo baselines:

| Sidecar | Preferred baseline path |
| --- | --- |
| Smart Wi-Fi Manager | `config/fleet-profiles/smart-wifi-manager/config.json` |
| MAVLink Anywhere | `config/fleet-profiles/mavlink-anywhere/profile.json` |

Legacy deployment paths may be read for compatibility, but new work should use
`config/fleet-profiles/...`.

## Fleet Ops API

Canonical routes live under `/api/v1/fleet`.

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/v1/fleet/sidecars` | `GET` | Combined sidecar contract metadata and table data. |
| `/api/v1/fleet/sidecars/{sidecar}` | `GET` | One sidecar table, where `{sidecar}` is `smart-wifi-manager` or `mavlink-anywhere`. |
| `/api/v1/fleet/sidecars/{sidecar}/baseline` | `GET` | Redacted repo baseline summary and desired hash. |
| `/api/v1/fleet/sidecars/{sidecar}/nodes/{hw_id}` | `GET` | Redacted node-local profile summary and drift details. |
| `/api/v1/fleet/sidecars/{sidecar}/promote-draft` | `POST` | Generate a sanitized reference draft from one selected node. Does not mutate the repo baseline. |
| `/api/v1/fleet/sidecars/{sidecar}/reconcile/dry-run` | `POST` | Build a reconcile plan for selected nodes. No mutation. |
| `/api/v1/fleet/sidecars/{sidecar}/reconcile/apply` | `POST` | Apply a previously generated dry-run plan with explicit confirmation. |
| `/api/v1/fleet/sidecars/{sidecar}/policy/dry-run` | `POST` | Preview sidecar policy-mode changes. |
| `/api/v1/fleet/sidecars/{sidecar}/policy/apply` | `POST` | Apply confirmed policy-mode changes; `fleet-strict` requires advanced confirmation. |
| `/api/v1/fleet/sidecars/jobs/{job_id}` | `GET` | Read job result without exposing sidecar confirmation tokens. |
| `/api/v1/fleet/git-sync` | `GET` | Per-drone git sync posture. |
| `/api/v1/fleet/git-sync/dry-run` | `POST` | Preview selected drone sync targets. |
| `/api/v1/fleet/git-sync/apply` | `POST` | Apply a confirmed sync dry-run by dispatching `UPDATE_CODE` only to eligible targets. |

Mutation routes require dry-run first. When `MDS_FLEET_OPS_MUTATION_TOKEN` is
configured on the GCS host, callers must send it as `X-Fleet-Ops-Token` or an
`Authorization: Bearer ...` header.

## Dry-Run Definition

A dry-run is an executable preview of a fleet mutation. It checks selected
targets, current presence, current policy mode, the requested baseline, and the
planned sidecar action, then returns the exact plan Fleet Ops would apply. It
must not write node files, change NetworkManager profiles, restart sidecar
services, alter MAVLink routes, or change policy mode.

An apply request is accepted only after the operator reviews a dry-run plan and
confirms the selected targets. Fleet Ops blocks apply requests for stale or
offline targets unless an explicitly supported maintenance workflow says
otherwise. `fleet-strict` additionally requires advanced confirmation because it
can prune managed local drift.

## Wi-Fi Drift And Reference Workflow

`local_extra` is expected in `fleet-merge` when a node has emergency,
site-local, or operator-added Wi-Fi profiles that are not in the repo baseline.
Fleet Ops preserves those additions and reports the drift instead of silently
overwriting connectivity.

To turn a connected node into the next fleet reference without exposing secrets:

1. Open Fleet Ops Wi-Fi profiles and inspect the node summary for the selected
   drone. The detail view shows sanitized node-local networks beside the repo
   baseline and shows password state only.
2. Use **Promote Draft** for that node. This creates a sanitized reference
   draft; it does not mutate the repo baseline or any node.
3. Review the draft with the operator. Keep only networks intended for the
   fleet baseline; leave local/emergency networks node-local unless explicitly
   approved for the private repo.
4. Commit the approved baseline to
   `config/fleet-profiles/smart-wifi-manager/config.json` in the private fleet
   repo.
5. Run Wi-Fi reconcile dry-run for selected drones in `fleet-merge`.
6. Apply only after explicit confirmation.

After apply, a node is `in_sync` only when its sanitized profile matches the
repo baseline with no extra local profile material. If approved local profiles
remain on that node, `fleet-merge` should continue to report `local_extra`;
that state is actionable visibility, not by itself a failure.

## Sidecar Product Contracts

Smart Wi-Fi Manager exposes safe profile summary/export/validate/diff/import,
confirmed apply, and promote-reference-draft APIs. `fleet-merge` preserves
node-local emergency SSIDs; `fleet-strict` may prune only profiles marked as
Smart-Wi-Fi-managed and only after advanced confirmation.

MAVLink Anywhere exposes the same mental model, but the fleet baseline owns only
shared endpoint policy, stream policy, dashboard policy, and auth/access policy.
Node hardware overlays remain local: serial device, baud, UDP input source, PX4
port, and board-specific router constraints are preserved by default. SITL
routing remains separate from real-node MAVLink Anywhere profiles.

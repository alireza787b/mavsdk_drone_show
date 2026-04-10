# Node Bootstrap And Fleet Enrollment V1 Recap

Date: 2026-04-10
Feature head: `f9a98e04`
Status: v1 implementation complete on `main-candidate`

## Implemented

The hardware-onboarding workflow is now split into three clean stages:

1. node bootstrap
2. node discovery / candidate announce
3. GCS operator enrollment

That split is now real in code, docs, and tests.

### Bootstrap

Canonical bootstrap path:

- `tools/install_mds_node.sh`
- `tools/mds_node_init.sh`

Supported now:

- generic companion-computer naming and docs
- repo / branch / fork / HTTPS / SSH bootstrap selection
- structured node manifest:
  - `/etc/mds/node_identity.json`
- machine-readable bootstrap report:
  - `--report-json`
- candidate announce integration:
  - `--gcs-api-url`
  - `--announce-report-json`
  - `--announce-timeout`
- standalone re-announce helper:
  - `tools/mds_node_announce.sh`

### Discovery

Canonical discovery path:

- `POST /api/v1/fleet/candidates/announce`

Candidate state is durable in:

- `runtime_data/fleet_candidates.json`
- `runtime_data/fleet_candidate_events.jsonl`

Heartbeats still provide liveness, but they no longer silently enroll drones.

### Operator Enrollment

Canonical operator workflow:

- dashboard page: `/fleet-enrollment`

Mission Config now routes into that workflow instead of owning hardware
replacement logic itself.

Supported operator actions:

- accept as new fleet member
- replace existing slot with a spare / different `hw_id`
- recover the same slot for the same `hw_id` after reimage / companion swap
- ignore candidate
- reject candidate

Old removed surface:

- `ReplaceDroneWizard`

## Scenario Guide

### Scenario 1: Brand-New Drone / Node

Operator does:

- bootstrap the node
- ensure it announces
- open `Fleet Enrollment`
- choose `Accept as new`
- assign/confirm `pos_id`, IP, routing fields, notes

System does:

- creates a candidate record
- appends the new fleet member into `config.json`
- preserves the candidate history in the registry/event log

### Scenario 2: Spare Drone Replaces Failed Slot

Example:

- failed slot: `P12`
- spare hardware: `H101`

Operator does:

- bootstrap spare node
- confirm it appears as a candidate
- open `Fleet Enrollment`
- choose `Replace existing slot`
- target the failed configured drone / slot

System does:

- preserves the old `pos_id`
- rewrites `config.json` target row `hw_id old -> new`
- rewrites `swarm.json` `hw_id` / `follow` references to the new `hw_id`

### Scenario 3: Same Physical Drone, New Companion Image

Operator does:

- reprovision the same physical drone using the same `hw_id`
- confirm candidate appears
- choose `Recover existing node`

System does:

- preserves existing `hw_id`
- preserves existing `pos_id`
- updates IP / serial / mavlink settings in place
- marks the candidate resolution as recovered, not replaced

### Scenario 4: Duplicate Or Conflicting Candidate

Operator does:

- review conflict state in `Fleet Enrollment`
- decide whether this is:
  - intended replacement
  - intended recovery
  - mistaken duplicate / stale node

System does:

- does not silently auto-accept
- keeps the candidate in conflict/pending-review state until explicit action

### Scenario 5: Bootstrap Succeeds But GCS Was Unreachable

Operator / automation does:

- rerun:
  - `sudo ./tools/mds_node_announce.sh`

System does:

- keeps bootstrap successful
- treats announce as a separate discovery step
- does not require rerunning the whole node bootstrap

### Scenario 6: Custom Repo / Customer Branch

Operator / automation does:

- use `--fork`, `--repo-url`, `--branch`, and optionally `--https`

System does:

- records repo/branch in node identity
- preserves those values in bootstrap report and candidate announce payload

### Scenario 7: Manual Router / No mavlink-anywhere Management

Operator / automation does:

- keep manual routing mode
- still bootstrap and announce the node

System does:

- enrolls the node candidate normally
- does not require bootstrap to invent invisible routing behavior

## Important Rules

### Bootstrap Is Not Enrollment

Bootstrap configures a node.
Enrollment changes fleet manifest state on GCS.

### Heartbeat Is Not Acceptance

Heartbeat can reveal liveness and unknown candidates.
It does not silently add rows into Mission Config anymore.

### Replace Is Not Recover

- `replace` = new `hw_id` takes an existing role
- `recover` = same `hw_id`, refreshed companion/runtime details

### `--gcs-ip` Is Not `--gcs-api-url`

- `--gcs-ip` is the control-plane host identity also used by other routing/setup
  flows
- `--gcs-api-url` is the explicit announce endpoint base URL

If only `--gcs-ip` is present, candidate announce derives:

- `http://<gcs-ip>:5000`

### Announce Failure Does Not Mean Bootstrap Failure

The node can be provisioned correctly even if the GCS is offline.
The announce helper exists for that exact case.

## Tests And Validation Completed

Local:

- fleet-candidate backend targeted batch: `11 passed`
- announce-script targeted batch: `3 passed`
- bootstrap script syntax checks: passed
- bootstrap/announce help validation: passed

Hetzner clean sync:

- fleet-candidate + announce combined pytest batch: `14 passed`
- Fleet Enrollment frontend Jest batch: `5 suites`, `42 tests passed`
- Fleet Enrollment production build: passed
- remote bootstrap script syntax/help validation: passed

## Deferred Post-V1 Items

Tracked explicitly in `docs/TODO_deferred.md`:

- named bootstrap profiles / reusable preset assets
- `mavlink-anywhere` repo review and automation polish

Also still true:

- no real hardware field run was claimed in this feature stream
- no Ansible inventory/playbook assets were added to the repo yet
- no new browser tester handoff was started after the final announce-only slice,
  because that slice changed scripts/docs/tests rather than the Fleet
  Enrollment frontend itself

## Recommended Tester Boundary

This feature is ready for:

- software / operator workflow review
- browser review of `Fleet Enrollment`
- dry-run/bootstrap contract review
- controlled companion-node provisioning tests

Before calling it real-hardware production-ready, the next strongest validation
would be:

1. provision a fresh hardware-like node with `mds_node_init.sh`
2. verify auto-announce into GCS
3. exercise:
   - accept-as-new
   - replace
   - recover
4. confirm git sync / runtime pickup behavior on the affected node

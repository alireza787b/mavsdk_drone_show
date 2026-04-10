# Enrollment, Identity, And Replacement Phase Closeout

Date: 2026-04-10
Status: phase closeout / operator doctrine locked
Scope: node bootstrap, candidate enrollment, replacement, recovery, slot swaps,
Smart Swarm identity semantics, and `mavlink-anywhere` integration posture

## Final Workflow Boundaries

There is one canonical provisioning/enrollment stack with distinct entrypoints:

1. `tools/install_mds_node.sh`
   - use on a fresh Debian-family companion computer with no repo clone yet
2. `tools/mds_node_init.sh`
   - use when the repo already exists on the node
   - also the correct path for repair, resume, and reprovision
3. `tools/mds_node_announce.sh`
   - use only when bootstrap already succeeded and GCS discovery must be retried
4. `Fleet Enrollment`
   - use for GCS-side manifest changes: accept, replace, recover, ignore, reject

Do not create a second field-replacement workflow outside Fleet Enrollment.

## Final Identity Doctrine

### `hw_id`

- persistent physical drone / companion-node identity
- used for telemetry ownership, maintenance, enrollment, git sync, PX4 params,
  low-level dispatch, and Smart Swarm follow ownership

### `pos_id`

- mission / show / slot identity
- used for trajectory selection, show-slot semantics, launch plots, and
  operator-facing role display

### `mav_sys_id`

- MAVLink transport identity
- currently aligned to `hw_id`
- still deferred for future explicit split when fleet scale requires it

## Final Scenario Semantics

### Brand-new node

1. bootstrap node
2. candidate appears
3. operator chooses `Accept as new`

Result:

- new fleet member is appended to fleet config
- no existing slot or Smart Swarm topology is rewritten

### Same drone, new companion image

1. bootstrap or reprovision with the same `hw_id`
2. candidate appears as a conflict/recovery case
3. operator chooses `Recover existing node`

Result:

- same `hw_id`
- same `pos_id`
- refreshed IP / companion metadata

### Spare drone replaces failed slot

Example:

- failed configured member `H12`
- spare node `H101`
- slot `P12` must be preserved

1. bootstrap spare
2. candidate appears
3. operator chooses `Replace existing slot`

Result:

- `P12` stays the mission/show slot
- config entry changes from `H12` to `H101`
- Fleet Enrollment rewrites Smart Swarm replacement-related `hw_id` and
  `follow` references from the failed hardware to the spare

### Deliberate slot swap

Example:

- operator wants `H5` to fly `P6`
- operator wants `H6` to fly `P5`

1. edit the two `pos_id` values in Mission Config
2. save/commit config

Result:

- Drone Show / Swarm Trajectory slot ownership changes
- trajectory ownership changes
- Smart Swarm follow chains do **not** change automatically

Reason:

- Smart Swarm topology is physical-drone centric, not slot centric

If the operator also wants Smart Swarm leadership/topology changed, that is a
second deliberate step in `Swarm Design`, not an implicit side effect of slot
swapping.

## Smart Swarm Final Rule

Smart Swarm follow chains should remain `hw_id`-based.

Why this is the correct current doctrine:

- it matches the actual saved swarm data model
- it matches live leader/follower runtime semantics
- it matches maintenance and replacement workflows
- it avoids silently changing airborne or saved topology when operators only
  intended to reassign show slots

The dedicated spare-replacement flow already handles the real operational case
where a new airframe must inherit a failed slot and its related follow
references.

## `mavlink-anywhere` Posture

MDS should keep `mavlink-anywhere` integration non-breaking:

- keep existing `mavlink-anywhere` interactive flows intact
- keep older user-facing usage recognizable
- improve only automation/headless/reporting/docs seams where it helps MDS

Current MDS-side reality:

- `mds_node_init.sh` already supports managed `mavlink-anywhere` setup
- `--mavlink-auto` and explicit headless MAVLink setup are already present
- older “manual-only” MDS guidance was stale and has been corrected

Deferred next step:

- review/update the external `mavlink-anywhere` repo separately for report-json,
  docs alignment, and MCP/automation-friendlier outputs without breaking old
  user workflows

## Remaining Explicit Debt

- future `hw_id` vs `mav_sys_id` split for large fleets
- optional slot-swap guidance/helper for Smart Swarm, if operators prove they
  need more than explicit docs/UI wording
- named bootstrap profiles and higher-level fleet automation assets
- separate non-breaking `mavlink-anywhere` repo polish
- real hardware field validation

## Validation In This Closeout Slice

- local backend replacement/recovery registry batch
- focused Hetzner frontend validation for Mission Config / Fleet Enrollment /
  QuickScout identity wording surfaces
- Hetzner production build for the validation tree

Notes:

- the focused Hetzner frontend tests for this identity/enrollment wording pass
  are green
- the Hetzner CRA production build did complete, but only after clearing a
  stale concurrent remote build and giving the validation-tree build more time
  on the low-free-space host
- no backend flight/runtime logic changed in this closeout slice, so no new
  SITL runtime gate was required beyond the already-validated earlier
  replacement/recovery logic

This phase should now be read as closed for doctrine and workflow boundaries.
Any future work should build on these semantics instead of reopening `hw_id`
versus `pos_id` from scratch.

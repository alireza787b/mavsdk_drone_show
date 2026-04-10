# Node Enrollment, Identity Alignment, And Scenario Brief

Date: 2026-04-10
Status: recap / standards-alignment brief
Scope: node bootstrap, candidate enrollment, `hw_id` vs `pos_id`, current MDS alignment, and next-step debt

## Why This Brief Exists

This file is the single review brief for the current hardware-onboarding work.
It consolidates:

- what was implemented in node bootstrap and fleet enrollment
- the operator scenarios you should review now
- the current and recommended meaning of `hw_id`, `pos_id`, and MAVLink system identity
- the remaining `mavlink-anywhere` follow-up debt
- the concrete guidance for keeping all MDS modes aligned

It is intended to replace jumping between multiple partial notes during feedback.

## Files Already In `/root`

The earlier narrower notes are already copied to `/root`:

- `MDS_Node_Bootstrap_Fleet_Enrollment_V1_Recap_2026-04-10.md`
- `MDS_Node_Bootstrap_Candidate_Announce_2026-04-10.md`
- `MDS_Fleet_Enrollment_Operator_Workflow_2026-04-10.md`

This new brief is the consolidated one.

## Current V1 Feature State

The node bootstrap + fleet enrollment v1 stream is complete on `main-candidate`
at `56221f43`.

## Which Script To Run

There are not two competing bootstrap workflows now. There is one canonical
stack with two entrypoints for different starting conditions:

- `tools/install_mds_node.sh`
  - use on a fresh host with no local repo clone yet
  - this is a thin bootstrap wrapper
- `tools/mds_node_init.sh`
  - use when the repo already exists on the node
  - this is the real provisioning engine
- `tools/mds_node_announce.sh`
  - use when the node is already provisioned and only GCS discovery / candidate
    announce must be retried

Operational rule:

- fresh image -> `install_mds_node.sh`
- existing node / repair / resume -> `mds_node_init.sh`
- already provisioned but GCS was offline -> `mds_node_announce.sh`
- fleet replacement / recover / slot reassignment -> Fleet Enrollment, not a
  second bootstrap path

Implemented:

- one canonical bootstrap path:
  - `tools/install_mds_node.sh`
  - `tools/mds_node_init.sh`
- structured node manifest:
  - `/etc/mds/node_identity.json`
- machine-readable bootstrap output:
  - `--report-json`
- canonical candidate announce path:
  - `tools/mds_node_announce.sh`
  - `POST /api/v1/fleet/candidates/announce`
- durable GCS-side candidate registry
- dedicated dashboard page:
  - `/fleet-enrollment`
- explicit operator actions:
  - accept as new
  - replace existing slot
  - recover same node
  - ignore
  - reject

Removed / retired:

- heartbeat-driven silent Mission Config auto-add
- old `ReplaceDroneWizard`
- extra parallel bootstrap storylines as the primary path

## Canonical Identity Model

This is the identity doctrine MDS should keep across Drone Show, Smart Swarm,
Swarm Trajectory, QuickScout, command actions, enrollment, and docs.

### 1. `hw_id`

Meaning:

- persistent MDS node / airframe identity
- the physical drone / companion-computer identity
- the thing operators replace or recover

Properties:

- stable across missions
- should not change just because the drone flies a different slot
- should be the anchor for runtime health, git sync, telemetry ownership, and
  operator maintenance history

Current on-device persistence:

- runtime marker: `~/mavsdk_drone_show/<N>.hwID`
- shell/service overrides: `/etc/mds/local.env`
- machine-readable node manifest: `/etc/mds/node_identity.json`

Operator-friendly rule:

- `.hwID` is still the current runtime marker the drone code reads
- `local.env` and `node_identity.json` are the files people and automation
  should inspect first

### 2. `pos_id`

Meaning:

- mission / show / slot identity
- which trajectory slot or planned role a drone is currently assigned to

Properties:

- can change between missions
- can intentionally differ from `hw_id`
- should be the anchor for show-slot semantics and formation-role display

### 3. `mav_sys_id`

Meaning:

- MAVLink transport address, not the operator-facing mission slot

Current MDS state:

- today it is still effectively aligned to `hw_id`
- this is acceptable for current fleets in the `1..254` range

Future-proof rule:

- once fleets or network topology need it, `mav_sys_id` should be separated
  from `hw_id`
- `hw_id` should remain the persistent software/hardware identity
- `mav_sys_id` should become the network transport identity

This future split is already tracked in `docs/TODO_deferred.md`.

### 4. `callsign` or other aliases

Meaning:

- operator-friendly labels only
- never a replacement for `hw_id` or `pos_id`

## Best-Practice Conclusion

Public MAVLink / PX4 / commercial-drone-show guidance all points to the same
core rule:

- keep persistent vehicle identity separate from role / slot assignment

That is the right industrial pattern here.

The public standards guidance does **not** support overloading one field for all
three jobs:

- hardware identity
- show slot / role identity
- MAVLink network address

The clean long-term model is:

- `hw_id` = persistent node / airframe identity
- `pos_id` = current role / slot identity
- `mav_sys_id` = MAVLink transport identity

## Current MDS Alignment By Subsystem

### Drone Show

Correct doctrine:

- target physical drones by `hw_id`
- show which slot they are flying by `pos_id`
- use `pos_id` to resolve show / trajectory ownership

Operator shorthand:

- `P12|H101` means:
  - slot / position 12
  - flown by hardware 101

### Smart Swarm

Current doctrine:

- assignments and follow chains are still rooted in `hw_id`

Implication:

- if a spare replaces a failed leader, follow-chain references must move with
  the replacement

Important nuance:

- this is already handled in the dedicated enrollment replace flow
- the broader generic Mission Config role-swap cleanup remains a tracked
  deferred item

### Swarm Trajectory

Correct doctrine:

- authoring should stay operator-visible in role / mission terms
- execution still targets selected physical drones
- cards, map labels, and monitor surfaces should continue using the compact
  `Pn|Hm` display where density matters

### QuickScout

Correct doctrine:

- operator can choose participating assigned slots in the planning UI
- launch resolves those slot selections to the currently assigned hardware set
- UI should still surface role / slot context where relevant
- mission package state should never blur hardware identity and slot identity

### Command / Action Surfaces

Correct doctrine:

- command dispatch targets physical drones
- summaries and operator scope chips should show:
  - hardware identity
  - slot context when assigned

This is why the `Pn|Hm` compact display remains useful for dense operational
surfaces.

## Scenario Guide You Should Review Now

### Scenario 1: Brand-New Drone / Node

Operator flow:

- bootstrap node
- ensure it announces
- open `Fleet Enrollment`
- choose `Accept as new`
- assign / confirm slot, IP, notes, and routing fields

System effect:

- candidate becomes a fleet member
- `config.json` gains a new row
- candidate history remains in the registry

### Scenario 2: Spare Drone Replaces Failed Slot

Example:

- failed slot: `P12`
- spare airframe: `H101`

Operator flow:

- bootstrap spare node
- confirm candidate appears
- choose `Replace existing slot`
- select the failed configured drone / slot

System effect:

- slot `P12` is preserved
- new airframe `H101` takes that slot
- enrollment updates `config.json`
- enrollment updates `swarm.json` references for this replacement flow

Operational meaning:

- same role, new airframe

### Scenario 3: Same Drone, New Companion Image

Operator flow:

- reprovision the same physical drone with the same `hw_id`
- candidate appears
- choose `Recover existing node`

System effect:

- keeps the same identity
- keeps the same slot
- refreshes runtime, network, and companion metadata

Operational meaning:

- same airframe, same role, refreshed node

### Scenario 4: Field Replacement During Active Show Preparation

This is the same core workflow as scenario 2, just in a more time-critical
operator context.

Recommended doctrine:

- do **not** invent a second “field replacement” workflow
- use the same replace flow
- keep one set of docs and one operator mental model

If the spare is already on the correct repo/branch and routing profile:

- only the enrollment change is needed

If the spare is not yet prepared:

- bootstrap first
- then replace

### Scenario 5: Candidate Conflict Or Duplicate

Operator flow:

- inspect the candidate
- decide whether it is:
  - a real replacement
  - a real recovery
  - a mistaken duplicate
  - a stale node

System effect:

- nothing is silently enrolled
- explicit operator action is required

### Scenario 6: GCS Unreachable During Bootstrap

Operator / automation flow:

- bootstrap still completes
- rerun:
  - `sudo ./tools/mds_node_announce.sh`

System effect:

- bootstrap success is preserved
- discovery is retried separately

### Scenario 7: Manual MAVLink Routing / No `mavlink-anywhere` Control

Operator / automation flow:

- bootstrap node
- keep manual routing mode
- still announce and enroll the node normally

System effect:

- enrollment remains valid
- MDS does not need to invent hidden router behavior

### Scenario 8: Custom Fork / Customer Branch

Operator / automation flow:

- use explicit repo / branch arguments

System effect:

- identity and announce records retain repo/branch provenance

## What Public Standards Actually Support

The public standards and product guidance I checked support these conclusions:

- MAVLink system IDs are network addresses and must be unique on the MAVLink
  network.
- PX4 / QGC parameter metadata and command metadata are explicitly intended to
  be version-aware and machine-consumable.
- commercial drone-show tooling publicly documents separate physical-drone and
  show-slot concepts.

Practical interpretation for MDS:

- `hw_id` should remain the persistent operator identity
- `pos_id` should remain the role / slot identity
- `mav_sys_id` should not become the generic operator slot label
- dense operator UIs should show both in compact form when relevant

## References Checked

- MAVLink system/component ID assignment:
  - https://mavlink.io/en/services/mavlink_id_assignment.html
- MAVLink component metadata protocol:
  - https://mavlink.io/en/services/component_metadata.html
- PX4 metadata overview:
  - https://docs.px4.io/main/en/advanced/px4_metadata.html
- PX4 parameter reference:
  - https://docs.px4.io/main/en/advanced_config/parameter_reference
- Skybrush FAQ entry point:
  - https://www.skybrush.io/support/faq/

## `mavlink-anywhere` Debt: Current Recommendation

This is still a real next-step item, but it is post-v1 debt, not a hidden
blocker in the enrollment flow.

What is already true:

- current MDS bootstrap already has integration hooks for `mavlink-anywhere`
- the MDS side is cleaner now than before

What still needs review next:

- non-interactive install/config behavior
- clear machine-readable outputs for automation / AI / MCP use
- profile-driven routing modes
- doc alignment with `mds_node_init.sh`

Recommended next-step scope for that repo:

1. add a cleaner headless mode if missing
2. make outputs predictable and machine-readable
3. align profile names with MDS bootstrap terminology
4. keep one routing story in docs instead of parallel manual/ad hoc recipes

## Remaining Debt You Should Know Now

Not hidden, not forgotten:

- decouple `hw_id` from `mav_sys_id` for fleets beyond MAVLink’s practical ID
  ceiling
- bootstrap profile assets / named presets
- `mavlink-anywhere` integration review and automation polish
- broader non-enrollment role-swap follow-chain cleanup in generic Mission
  Config workflows
- real hardware field validation

## Final Recommendation

At this stage, the clean system-wide doctrine should be:

- `hw_id` = persistent physical/node identity
- `pos_id` = assigned slot / mission role
- `mav_sys_id` = MAVLink transport identity
- `Pn|Hm` = compact operator display shorthand only

And the clean onboarding doctrine should be:

1. bootstrap node
2. announce candidate
3. operator enrolls with accept / replace / recover

No silent heartbeat enrollment.
No second field-replacement workflow.
No hidden parallel bootstrap story.

That is the most consistent path for MDS across Drone Show, Smart Swarm, Swarm
Trajectory, QuickScout, action surfaces, documentation, and future MCP-facing
automation.

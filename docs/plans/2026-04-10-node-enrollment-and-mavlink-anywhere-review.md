# Node Enrollment And MAVLink Anywhere Review

Date: 2026-04-10
Status: review / recap / next-step planning
Scope: current node bootstrap and enrollment flow, identity doctrine, operator
scenarios, and non-breaking `mavlink-anywhere` audit findings

## Current Checkpoint

Current `main-candidate` checkpoint:

- `6204aa01`

This checkpoint includes:

- the completed node bootstrap + candidate enrollment v1 stream
- clarified bootstrap-wrapper versus init-engine docs
- clarified `hw_id` / `pos_id` / `mav_sys_id` doctrine
- one QuickScout slot-vs-hardware UI consistency fix

## What Is The Correct Node-Bootstrap Flow?

There is one canonical stack with different entrypoints depending on the
starting state.

### 1. Fresh OS Image, No Repo Cloned Yet

Use:

- `tools/install_mds_node.sh`

Why:

- it is the public bootstrap wrapper
- it installs prerequisites
- it clones / updates the repo
- then it hands off to `tools/mds_node_init.sh`

### 2. Repo Already Exists On The Node

Use:

- `tools/mds_node_init.sh`

Why:

- this is the real provisioning engine
- this is the correct path for:
  - re-running setup
  - repairs
  - resume after interruption
  - reprovisioning an already-prepared node

### 3. Bootstrap Succeeded But GCS Was Unreachable

Use:

- `tools/mds_node_announce.sh`

Why:

- bootstrap and candidate discovery are intentionally separate
- do not rerun the full bootstrap just to retry enrollment discovery

### 4. Fleet Change On GCS

Use:

- `Fleet Enrollment`

Why:

- fleet acceptance / replacement / recovery is a GCS manifest workflow
- it is not a second bootstrap path

## Correct Operator Scenarios

### Scenario A: Brand-New Drone / Node

Flow:

1. bootstrap node
2. candidate announces
3. operator opens `Fleet Enrollment`
4. choose `Accept as new`

System result:

- new fleet member is added to `config.json`
- candidate history remains in registry/event log

### Scenario B: Spare Drone Replaces Failed Slot

Example:

- failed slot `P12`
- spare airframe `H101`

Flow:

1. bootstrap spare node
2. candidate appears
3. choose `Replace existing slot`
4. target the failed configured fleet member

System result:

- slot `P12` is preserved
- new hardware `H101` takes that role
- enrollment updates `config.json`
- enrollment updates replacement-related swarm references in the dedicated
  replace flow

### Scenario C: Same Drone, New Companion Image

Flow:

1. reprovision with the same `hw_id`
2. candidate appears
3. choose `Recover existing node`

System result:

- same identity preserved
- same slot preserved
- runtime/network/companion details refreshed

### Scenario D: Bootstrap Worked But GCS Was Offline

Flow:

1. do not rerun the full bootstrap
2. rerun:
   - `sudo ./tools/mds_node_announce.sh`

System result:

- node stays provisioned
- discovery is retried cleanly

### Scenario E: Field Replacement During Show Preparation

This is not a separate product workflow.

Use the same flow as scenario B:

- prepare the spare node
- announce candidate
- replace the failed slot in `Fleet Enrollment`

Do not create a second “field replacement” procedure in docs or UI.

### Scenario F: Quick Slot Reassignment Between Two Ready Drones

Example:

- `H5` currently flies `P5`
- `H6` currently flies `P6`
- operator wants `H5 -> P6` and `H6 -> P5`

Use:

- `Mission Config`

Do not use:

- `Fleet Enrollment`

Why:

- no physical node identity changed
- this is a role / slot ownership change, not new-node acceptance or spare replacement

System result:

- `config.json` changes the `pos_id` assignments
- Drone Show and trajectory ownership follow the new `pos_id` mapping
- Smart Swarm follow chains do not silently change just because slot ownership changed

Operational note:

- if Smart Swarm topology should also change, review and update it explicitly in `Swarm Design`
- if a spare physically replaces a failed airframe, use Scenario B / E instead

## Identity Doctrine: Final Recommendation

This is the correct MDS identity model and should stay consistent across Drone
Show, Smart Swarm, Swarm Trajectory, QuickScout, actions, enrollment, docs,
plots, and monitoring.

### `hw_id`

Meaning:

- persistent physical / companion-node identity

Use it for:

- telemetry ownership
- git sync ownership
- PX4 parameter targeting
- maintenance / enrollment / recovery / replacement
- low-level command dispatch

### `pos_id`

Meaning:

- mission / show / slot identity

Use it for:

- trajectory / show slot mapping
- operator-facing role display
- launch layout, position plots, show-slot semantics
- high-level planning surfaces that operate in mission-slot terms

### `mav_sys_id`

Meaning:

- MAVLink transport identity

Current state:

- currently still aligned to `hw_id`

Future-proof direction:

- split it out once fleets or routing complexity require it

## Should MDS Switch To `pos_id` Everywhere?

No.

That would be the wrong cleanup.

The correct rule is:

- low-level runtime and persistent identity stay `hw_id`-anchored
- mission/slot semantics stay `pos_id`-anchored
- some high-level mission planners may let operators select slots, then resolve
  those slots to current hardware at launch

That means:

- Drone Show: `pos_id` is central to the show role
- QuickScout planning: slot-oriented UI is acceptable if launch resolves to the
  actual current `hw_id` set
- Smart Swarm: still `hw_id`-based for follow chains today
- Mission Config slot reassignment: valid for show/trajectory role changes, but it is not a hidden Smart Swarm topology editor
- PX4 Parameters / enrollment / maintenance: `hw_id`-anchored

## Current On-Device Identity Files

Current practical files to know:

- runtime marker:
  - `~/mavsdk_drone_show/<N>.hwID`
- shell/service overrides:
  - `/etc/mds/local.env`
- machine-readable identity manifest:
  - `/etc/mds/node_identity.json`

Operator rule:

- `.hwID` still matters for the current runtime
- `local.env` and `node_identity.json` are the clean files humans and automation
  should inspect first

## Consistency Check Across Views And Maps

Current system-level recommendation:

- dense operational surfaces should show the compact shorthand `Pn|Hm`
- edit forms should keep explicit labels `Position ID` and `Hardware ID`
- maps, launch plots, and monitor views should avoid showing only one identity
  when both matter operationally

This is especially important in:

- Drone Show launch/placement views
- Swarm cluster and graph views
- QuickScout target / assigned-drone surfaces
- enrollment replace/recover screens

## What Was Fixed In This Pass

One real inconsistency was fixed:

- QuickScout planning selection was slot-based under the hood, but the visible
  selector looked hardware-only
- it now shows compact mission identity more clearly and states that planning
  selects assigned slots that resolve to current hardware at launch

Also corrected:

- node-bootstrap docs now explain when to use:
  - `install_mds_node.sh`
  - `mds_node_init.sh`
  - `mds_node_announce.sh`
- MDS docs now reflect that `mavlink-anywhere` already supports auto/headless
  usage instead of documenting it as manual-only

## MAVLink Anywhere Audit

Public repo reviewed:

- `https://github.com/alireza787b/mavlink-anywhere`

Current public repo state appears stronger than older MDS-side docs implied.

### What MAVLink Anywhere Already Supports

From the public README/repo:

- install script:
  - `install_mavlink_router.sh`
- configure script:
  - `configure_mavlink_router.sh`
- auto mode:
  - `--auto`
- fully headless mode:
  - `--headless`
- UART and UDP input modes
- optional web dashboard
- CLI helper:
  - `mavlink-router-cli.sh`

So the right interpretation is:

- `mavlink-anywhere` is already automation-capable
- MDS should integrate with that cleanly
- MDS should not keep describing it as manual-only

### Important Mismatch Found

The public `mavlink-anywhere` README still shows this MDS integration example:

- `sudo ./tools/mds_init.sh -d 1 -y --mavlink-auto --gcs-ip ...`

That is now stale for MDS.

The correct modern MDS entrypoint is:

- `sudo ./tools/mds_node_init.sh ...`

This is exactly the kind of doc drift we should fix, but it is a non-breaking
docs correction, not a user-breaking workflow rewrite.

### Non-Breaking Improvement Plan For MAVLink Anywhere

Do **not** dramatically change user-facing entrypoints that people learned from
older docs and videos.

Recommended non-breaking improvements only:

1. keep current script names:
   - `install_mavlink_router.sh`
   - `configure_mavlink_router.sh`
2. keep current interactive workflow working
3. improve machine-friendly outputs:
   - optional `--report-json`
   - optional status/export JSON in CLI helper
4. add clearer preset/profile support without removing current flags
5. update docs to show modern MDS integration:
   - `mds_node_init.sh`
6. document recommended default endpoint profiles for MDS
7. keep dashboard optional, not mandatory

### Best Next Slice For MAVLink Anywhere

Audit and improve only where it directly helps MDS deployment:

- headless output/report consistency
- profile-driven configuration
- MDS doc alignment
- AI/MCP-friendly machine-readable seams

Do not do:

- breaking CLI renames
- forced migration away from known user flows
- unnecessary rewrites if the current install/configure path already works

## What Still Remains As Debt

Still explicit and not forgotten:

- decouple `hw_id` from `mav_sys_id` for larger fleets
- named bootstrap profiles / preset assets
- `mavlink-anywhere` automation/doc polish
- broader generic role-swap follow-chain cleanup outside the dedicated
  enrollment replace flow
- real hardware field validation

## Validation Done In This Pass

Focused validation completed:

- Hetzner frontend test batch: `16 passed`
- Hetzner production build: passed

This pass did not require SITL flight validation because the changes were:

- doctrine/docs clarification
- one QuickScout operator-facing identity-label fix

## Bottom-Line Recommendation

At this stage, the correct operational and software doctrine is:

1. one bootstrap stack, with wrapper + engine + announce helper
2. explicit Fleet Enrollment for accept / replace / recover
3. `hw_id` for persistent physical identity
4. `pos_id` for mission/show role
5. selective slot-oriented planners may resolve to hardware at launch
6. `mavlink-anywhere` should be improved non-breakingly, not reinvented

That gives the cleanest path for operator clarity, automation, MCP-friendliness,
and future large-fleet hardening.

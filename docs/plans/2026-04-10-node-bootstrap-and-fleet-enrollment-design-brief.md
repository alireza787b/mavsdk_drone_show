# Node Bootstrap And Fleet Enrollment Design Brief

Date: 2026-04-10
Repo baseline: `e2796e1c`
Status: design only, not implemented
Scope: real-hardware companion-computer bootstrap, fleet registration, replacement workflow, automation, and GCS operator UX

## Executive Summary

The product already has a serious but fragmented hardware-onboarding stack:

- a real bootstrap wrapper: `tools/install_mds_node.sh`
- a real modular init engine: `tools/mds_node_init.sh` plus `tools/mds_init_lib/*`
- heartbeat-based spare-drone detection in the dashboard
- a simple `ReplaceDroneWizard`

Those pieces prove the intent, but they do **not** yet form a production-grade fleet onboarding and replacement workflow.

The current system still has four major architectural gaps:

1. node bootstrap and fleet registration are not separate concepts
2. heartbeats can implicitly mutate Mission Config UI state
3. replacement is treated like a frontend config edit, not an operational workflow
4. automation exists, but it is script-centric rather than contract-centric

The recommended direction is:

- keep **one** bootstrap CLI entrypoint and retire legacy setup paths
- redesign bootstrap as **node provisioning**, not silent fleet registration
- add an explicit **candidate enrollment** workflow on the GCS
- make replacement/reimage/add-drone flows first-class operator workflows
- make the system machine-driven by design:
  - human CLI
  - headless automation
  - future MCP / AI-agent orchestration

This should be treated as a cross-cutting subsystem, not a small script patch.

## What Exists Today

### Bootstrap / Provisioning

The current intended provisioning path is already:

- `tools/install_mds_node.sh`
  - thin bootstrap wrapper
  - creates `droneshow` user
  - clones repo
  - hands off to `tools/mds_node_init.sh`
- `tools/mds_node_init.sh`
  - modular init engine
  - supports non-interactive mode, `--resume`, `--dry-run`
  - supports repo/fork/branch overrides
  - supports NetBird and static-IP modes
  - supports MAVLink routing guidance / automation through `mavlink-anywhere`

Important existing modules:

- `tools/mds_init_lib/repo.sh`
- `tools/mds_init_lib/identity.sh`
- `tools/mds_init_lib/network.sh`
- `tools/mds_init_lib/mavlink_setup.sh`
- `tools/mds_init_lib/services.sh`
- `tools/mds_init_lib/verify.sh`

Important current state files:

- `/etc/mds/local.env`
- `/var/lib/mds/init_state.json`
- `{N}.hwID`
- `real.mode`

### Runtime Discovery / Fleet Awareness

The current runtime already has:

- `src/heartbeat_sender.py`
  - sends `hw_id`, `pos_id`, `detected_pos_id`, `ip`, `network_info`
- `gcs-server/heartbeat.py`
  - stores last heartbeat per `hw_id`
  - exposes network info from heartbeat payloads
- `MissionConfig.js`
  - currently auto-adds heartbeat-only drones into the local config UI state
- `ReplaceDroneWizard.js`
  - can map a failed configured drone slot onto another heartbeat-detected `hw_id`

### Current Design Debt

The current flow is not safe enough for real operations because:

- bootstrap identity is local, but GCS acceptance is implicit
- heartbeats are being used for both liveness and discovery without a clean candidate model
- Mission Config silently creates new UI config rows from unknown heartbeats
- replacement only edits `configData` in the browser and then saves config
- `src/params.py` still carries stale `config_url` / `swarm_url` and
  `offline_config` comments that do not describe the current real-hardware
  propagation story cleanly
- there is no durable pending-registration queue
- there is no explicit conflict-resolution model for:
  - duplicate `hw_id`
  - duplicate IP
  - stale/reimaged node
  - same-airframe companion replacement
  - spare-airframe hot swap
  - standby-node reassignment into an existing mission slot without inventing a
    second workflow

## Primary Product Goals

This subsystem needs to support five real workflows cleanly:

1. Fresh node bootstrap
   - brand-new Raspberry Pi / companion computer
   - install prerequisites, repo, venv, services, networking, MAVLink routing
   - come online cleanly as a known MDS node

2. Fleet enrollment
   - node appears to GCS as a candidate
   - operator explicitly accepts, edits, replaces, or rejects it

3. Drone replacement
   - failed airframe replaced by spare airframe / spare companion
   - existing `pos_id` preserved
   - new physical `hw_id` takes the role
   - example: standby `H101` is accepted as the replacement for failed slot
     `P12`; this uses the same candidate-enrollment and replacement workflow,
     not a Drone Show-specific side path

4. Companion-computer replacement on the same physical drone
   - same physical drone
   - same `hw_id`
   - new OS image / new companion
   - deterministic reprovisioning

5. Scaled automation
   - operator can run it manually
   - DevOps can run it headlessly
   - future AI/MCP tooling can run it safely and deterministically

## Design Principles

1. One bootstrap engine, not multiple competing scripts.
2. Explicit operator acceptance before fleet config changes.
3. No heartbeat-driven silent mutation of `config.json`.
4. Node bootstrap and fleet manifest are separate sources of truth.
5. Runtime state must be durable across GCS restart.
6. Manual, automated, and future MCP paths must all use the same contracts.
7. Keep repo state clean:
   - repo-managed assets in repo
   - runtime-generated acceptance state in runtime storage
8. Avoid new legacy compatibility layers where a clean migration is practical.
9. Keep MAVLink/PX4 semantics aligned with real system identity rules.
10. Prefer structured machine-readable outputs over brittle terminal scraping.

## Core Architectural Decision

### Separate These Three Things

They are currently blurred together and should not be:

1. **Node provisioning**
   - OS packages
   - repo/branch
   - Python / services
   - MAVLink routing
   - NetBird / static networking
   - `hw_id` / hostname / local runtime env

2. **Node discovery**
   - a running node reaches GCS
   - GCS sees it as a candidate
   - GCS can inspect its identity and health

3. **Fleet enrollment**
   - operator explicitly decides whether that candidate:
     - becomes a new fleet member
     - replaces an existing role
     - is rejected
     - is ignored temporarily

That separation is the most important design rule for this subsystem.

## Recommended Target Architecture

### 1. Bootstrap Layer

### Keep

- `tools/install_mds_node.sh` as the public one-line bootstrap entry
- `tools/mds_node_init.sh` as the main provisioning engine

### Retire / Remove

- `tools/raspberry_setup.sh`
  - keep only long enough to migrate docs and callers
  - do not continue evolving it

### Recommendation

Do not invent a second provisioning script.

Instead:

- modernize `mds_node_init.sh`
- tighten its contracts
- make it the only supported engine
- keep `install_mds_node.sh` as a thin convenience wrapper

### 2. Node Identity Model

### Recommended Persistent State

Keep runtime overrides in:

- `/etc/mds/local.env`

Add a structured node manifest:

- `/etc/mds/node_identity.json`

Recommended contents:

- `node_uuid`
- `hw_id`
- `hostname`
- `role_hint` if any
- `repo_url`
- `branch`
- `bootstrap_version`
- `network_mode`
- `primary_control_ip`
- `netbird_enabled`
- `mavlink_routing_mode`
- `mavlink_input_type`
- `mavlink_input_device`
- `created_at`
- `last_bootstrap_at`

Keep bootstrap state in:

- `/var/lib/mds/init_state.json`

Why:

- `/etc/mds/local.env` remains shell/service-friendly
- `node_identity.json` becomes API/MCP/automation-friendly
- the two files stop competing for the same role

### 3. Network / MAVLink Routing Model

### Supported Modes

The bootstrap contract should explicitly support:

1. `netbird`
   - DHCP/local network for base connectivity
   - NetBird as control-plane identity
   - preferred for remote fleets

2. `static_local`
   - static LAN IP
   - no NetBird required

3. `manual_network`
   - operator handles network/IP themselves
   - bootstrap validates but does not own it

### MAVLink Routing Modes

Supported routing modes should be explicit:

1. `mavlink_anywhere_managed`
   - recommended default
   - bootstrap installs/configures/validates it

2. `manual_router`
   - operator supplies their own MAVLink stream creation
   - bootstrap only checks required endpoints / ports / service assumptions

3. `disabled_for_setup_only`
   - for provisioning before FC wiring is present
   - node can still enroll as a candidate, but reports MAVLink routing incomplete

### Recommended MDS Endpoint Doctrine

Keep the current role separation:

- `14540` MAVSDK consumer
- `12550` local controller / diagnostic sink
- `14569` reserved local MAVLink service/debug target
- remote GCS / QGC endpoints as configured

Do not make the bootstrap script guess invisible routing behavior.
Make routing an explicit declared profile.

### 4. Discovery And Enrollment Model

### Current Behavior To Retire

Retire this Mission Config behavior:

- unknown heartbeat appears
- frontend silently appends a new drone config row

That is operationally unsafe.

### Replace With

A dedicated GCS-side candidate registry:

- persisted in runtime storage, not committed fleet config
- fed by:
  - heartbeat data
  - bootstrap/node announcement payload

Recommended storage:

- `runtime_data/fleet_candidates.json`
- `runtime_data/fleet_candidate_events.jsonl`

Candidate records should include:

- `candidate_id`
- `node_uuid`
- `hw_id`
- `hostname`
- `first_seen`
- `last_seen`
- `ip_addresses`
- `primary_control_ip`
- `network_mode`
- `netbird_ip`
- `repo_url`
- `branch`
- `commit`
- `mavlink_routing_mode`
- `mavlink_input_type`
- `serial_device`
- `autopilot_link_state`
- `bootstrap_version`
- `registration_state`
- conflict flags

### Registration States

Recommended state machine:

- `candidate`
- `conflict`
- `pending_operator_review`
- `accepted`
- `rejected`
- `ignored`
- `superseded`

### Recommended GCS Contract

Do not overload heartbeats for everything.

Recommended new GCS API family:

- `GET /api/v1/fleet/candidates`
- `GET /api/v1/fleet/candidates/{candidate_id}`
- `POST /api/v1/fleet/candidates/announce`
- `POST /api/v1/fleet/candidates/{candidate_id}/accept`
- `POST /api/v1/fleet/candidates/{candidate_id}/replace`
- `POST /api/v1/fleet/candidates/{candidate_id}/reassign-hw-id`
- `POST /api/v1/fleet/candidates/{candidate_id}/reject`
- `POST /api/v1/fleet/candidates/{candidate_id}/ignore`

Heartbeats remain the liveness channel.
Candidate announce becomes the bootstrap/discovery identity channel.

### 5. Operator UX Recommendation

### Do Not Bury This In The Existing Mission Config Cards

Mission Config should not become the only place where hardware onboarding happens.

Recommended UX:

- new page: `Fleet Enrollment`
- plus lightweight banners/badges on:
  - Dashboard
  - Mission Config

### Fleet Enrollment Page

Recommended sections:

1. `Candidates`
   - new / unknown nodes
   - grouped by state
   - clear conflict indicators

2. `Accept As New Drone`
   - assign / confirm `hw_id`
   - assign / confirm `pos_id`
   - set networking/IP role
   - review conflicts before save

3. `Replace Existing Drone`
   - choose failed or retired fleet entry
   - preserve `pos_id`
   - map spare candidate `hw_id` onto that role

4. `Recover Same Drone`
   - same physical drone, new companion/reimage
   - preserve `hw_id`
   - refresh node metadata

5. `Provisioning Profiles`
   - named bootstrap presets
   - repo/branch/network/routing defaults

### UX Rules

- no silent auto-add
- no giant modal-first workflow for everything
- compact candidate cards on mobile/tablet
- detail drawer/dialog on narrow screens
- split-view on wide desktop
- explicit review before manifest mutation

### 6. Replacement And Recovery Workflows

### A. Spare Airframe / Spare Drone Replaces Failed Drone

Recommended workflow:

1. Candidate appears
2. Operator selects `Replace Existing Drone`
3. Operator selects failed fleet member
4. GCS previews:
   - old `hw_id`
   - old `pos_id`
   - candidate `hw_id`
   - IP / network info
   - swarm implications
5. Accept action updates:
   - `config.json`
   - optionally `swarm.json` if needed
6. GCS commits/pushes if enabled
7. operator triggers sync/restart path for the candidate if required

### B. Same Physical Drone, New Companion Computer

Recommended workflow:

1. bootstrap new companion with the **same** `hw_id`
2. candidate appears as recovery candidate
3. operator chooses `Recover Same Drone`
4. GCS compares node metadata with manifest
5. accept refreshes IP/network/runtime metadata, not fleet identity semantics

### C. Conflict Case

If candidate `hw_id` conflicts with an already-active fleet member:

- do **not** auto-accept
- mark state `conflict`
- give operator explicit choices:
  - replace existing drone
  - reassign candidate identity
  - reject candidate
  - ignore candidate

### 7. Config Propagation Recommendation

### Current Reality

`config.json` and `swarm.json` are still the fleet source of truth.

That should remain true for now.

### Recommended Rule

Enrollment actions modify fleet config **only** through canonical GCS config routes.

No direct frontend file hacks.
No direct heartbeat-to-config mutation.

### Restart / Sync Semantics

GCS should **not** require restart after accepting a candidate.

Recommended behavior:

- GCS writes config/swarm
- optional commit/push through existing git workflow
- GCS UI refreshes from canonical APIs
- affected drone can then:
  - pick up config via git sync
  - or fetch config directly if/when central config-pull becomes real

This is also why the redesign should keep GCS acceptance and node bootstrap separate.

### 8. Automation Recommendation

### Best Practical Automation Stack

Use three layers:

1. **Bootstrap CLI**
   - `install_mds_node.sh`
   - `mds_node_init.sh`
   - required for on-device provisioning

2. **Fleet Orchestration**
   - **Ansible** is the best immediate recommendation
   - already matches current docs and operator needs
   - idempotent, readable, SSH-based, easy for fleets

3. **Image / First-Boot Automation**
   - where supported, use **cloud-init**
   - otherwise keep the current first-boot systemd pattern

Why not only SD-card cloning:

- cloned images are dangerous unless machine identity is cleaned
- NetBird identity, SSH host keys, init cache, and `.hwID` must not be blindly duplicated

Official guidance relevant here:

- NetBird setup keys are meant for automated server/container onboarding and support expiration and auto-assigned groups:
  - https://docs.netbird.io/manage/peers/access-infrastructure/setup-keys-add-servers-to-network
- NetBird’s default all-to-all access is only an onboarding convenience and should be replaced by explicit peer-group policy in production:
  - https://docs.netbird.io/manage/access-control
- cloud-init requires cache cleaning before capturing reusable images:
  - https://cloudinit.readthedocs.io/en/latest/explanation/first_boot.html
- Raspberry Pi OS only recently added cloud-init on newer releases, so this should be treated as optional acceleration, not the baseline assumption for every field deployment:
  - https://www.raspberrypi.com/news/cloud-init-on-raspberry-pi-os/?pubDate=20251128

### Recommended Bootstrap Outputs

`mds_node_init.sh` should gain machine-friendly output modes:

- `--report-json`
- deterministic exit codes
- stable phase/result structure

This allows:

- humans to use the same tool
- CI/automation to parse it
- future MCP wrappers to call it safely

### 9. MAVSDK / PX4 / MAVLink Standards Alignment

Recommended identity stance:

- `hw_id` remains the MDS physical drone identity
- PX4 `MAV_SYS_ID` should remain aligned to `hw_id` wherever practical
- `pos_id` remains a fleet/mission role mapping, not a PX4 identity field

Recommended routing stance:

- keep app-level mission and fleet APIs above MAVLink details
- do not turn bootstrap/operator workflows into raw MAVLink message wrappers
- keep MAVLink router / companion configuration as a lower layer

For this feature, the correct standard is:

- MDS operator API for fleet onboarding
- MAVLink/PX4-aligned identity and transport values underneath

### 10. Recommended Storage Layout

### Repo-Managed

Keep repo-managed assets here:

- `config.json`
- `swarm.json`
- future provisioning profiles under something like:
  - `resources/bootstrap_profiles/`

### Node-Local

- `/etc/mds/local.env`
- `/etc/mds/node_identity.json`
- `/var/lib/mds/init_state.json`
- `/var/log/mds/*`

### GCS Runtime

- `runtime_data/fleet_candidates.json`
- `runtime_data/fleet_candidate_events.jsonl`

This avoids mixing:

- versioned fleet intent
- local machine state
- transient discovery runtime

### 11. What Should Change In The Existing Codebase

### Keep And Evolve

- `install_mds_node.sh`
- `mds_node_init.sh`
- `mds_init_lib/*`
- heartbeat network-info reporting
- repo/branch override model
- existing git sync/write-back flow

### Redesign

- Mission Config auto-add of unknown heartbeat drones
- ReplaceDroneWizard as the primary replacement system
- docs that still describe mavlink-anywhere as mostly manual

### Remove / Retire

- `tools/raspberry_setup.sh`
- stale “one node = fully done” docs that ignore registration/replacement lifecycle

### 12. Recommended Implementation Phases

### Phase 1: Audit Cleanup And Contract Lock

- retire `raspberry_setup.sh`
- update docs to name `install_mds_node.sh -> mds_node_init.sh` as the only bootstrap path
- add structured node manifest design
- add JSON-report contract to bootstrap design

### Phase 2: Candidate Registration Foundation

- candidate persistence on GCS
- node announce payload
- state model and conflict classification
- remove Mission Config auto-add behavior

### Phase 3: Operator Enrollment UX

- new `Fleet Enrollment` page
- candidate review
- accept/reject/ignore
- replacement and recovery workflows

### Phase 4: Bootstrap Profiles And Headless Automation

- saved provisioning profiles
- fully non-interactive JSON-reporting bootstrap path
- Ansible/reference automation refresh
- optional image/first-boot contract cleanup

### Phase 5: Validation And Hardening

- shell/unit tests for init libraries
- GCS API tests for candidate state machine
- frontend tests for enrollment workflows
- synthetic Hetzner validation on clean Debian hosts
- hardware dry-run checklist and operator docs

### 13. Tests That Will Be Required

At implementation time, this should not be released without:

- `shellcheck` on bootstrap scripts
- focused script tests, ideally `bats`
- GCS API tests for:
  - candidate announce
  - accept
  - replace
  - reject
  - conflict
- frontend tests for:
  - candidate queue
  - replacement review
  - recovery flow
- dry-run validation on Hetzner x86 hosts
- simulated first-boot image/reprovision tests

### 14. Key Risks And Their Mitigations

### Risk: cloned images duplicate machine identity

Mitigation:

- clean first-boot state before imaging
- never treat raw SD cloning as the primary supported lifecycle without cleanup

### Risk: unknown node silently mutates fleet config

Mitigation:

- no heartbeat auto-add
- explicit acceptance workflow

### Risk: duplicate `hw_id` / `MAV_SYS_ID`

Mitigation:

- candidate conflict state
- explicit operator resolution
- later optional remote reassign flow

### Risk: NetBird onboarding is too permissive

Mitigation:

- setup-key expiration
- peer-group policy
- remove default all-to-all policy in production

### Risk: MAVLink routing setup is opaque

Mitigation:

- declarative routing mode
- explicit verification
- machine-readable node manifest

### 15. Recommended Immediate Decisions

These are the defaults I recommend unless you want to override them:

1. keep `install_mds_node.sh` and `mds_node_init.sh`
2. retire `raspberry_setup.sh`
3. create a new `Fleet Enrollment` page instead of hiding everything in Mission Config
4. remove heartbeat-driven auto-add of unknown drones
5. keep `config.json` / `swarm.json` as current fleet source of truth
6. add a dedicated candidate registry in `runtime_data/`
7. make Ansible the documented fleet-scale automation path
8. treat cloud-init as optional acceleration, not mandatory baseline
9. keep `mavlink-anywhere` as the supported default routing tool, but make it explicitly profile-driven and automation-friendly

### 16. Open Questions For Later Implementation

No blocker questions are required from you before implementation starts, but these should be revisited while building:

- Should candidate acceptance auto-commit/push immediately, or stage a review-first batch save?
- Should remote `hw_id` reassignment be in the first implementation, or a follow-up?
- Should `Fleet Enrollment` also expose firmware/build info in v1, or defer until a clean source is wired?
- Should provisioning profiles live only in repo JSON, or also have a small dashboard editor in v1?

## Final Recommendation

Do **not** treat this as “fix the old Raspberry Pi script”.

Treat it as a product subsystem:

- **Node Bootstrap**
- **Fleet Enrollment**
- **Replacement / Recovery**
- **Automation Contracts**

The cleanest path is to converge onto the current `install_mds_node.sh` / `mds_node_init.sh` foundation, remove unsafe implicit registration behavior, and build an explicit GCS-side candidate workflow on top of it.

That gives you:

- professional operator onboarding
- safer fleet scaling
- cleaner replacement workflows
- future MCP/AI compatibility
- less hidden state and less configuration drift

# Hardware Demo Preflight Audit

Date: 2026-04-11
Status: Research / pre-implementation brief
Scope: Official MDS workflow audit before creating a private customer demo repo and first real-hardware deployment

## Executive Summary

The current MDS bootstrap + enrollment direction is broadly correct:

- keep one canonical node bootstrap stack
- keep one canonical GCS bootstrap stack
- keep Fleet Enrollment as the only operator workflow for accepting, replacing, recovering, or rejecting nodes
- keep `hw_id`, `pos_id`, and `mav_sys_id` as distinct concepts
- keep `mavlink-anywhere` as the recommended real-hardware MAVLink routing layer

However, one issue is still a real blocker for a fresh private customer deployment:

- the public wrapper installers clone the repo **before** the SSH deploy key setup step

That is acceptable for the public repo and existing local clones, but it is not clean for a first-time private customer repo on a fresh node or fresh GCS host.

## Final Doctrine

### Identity

- `hw_id`: persistent physical node / aircraft identity
- `pos_id`: mission slot / show role identity
- `mav_sys_id`: MAVLink transport identity

Use them this way:

- enrollment, maintenance, git sync, parameters, onboard logs, heartbeat ownership: `hw_id`
- mission slot planning, Drone Show role assignment, trajectory ownership: `pos_id`
- PX4 / MAVLink addressing: `mav_sys_id`

### Bootstrap / Enrollment

There should be one canonical two-stage bootstrap model, not multiple competing workflows:

1. wrapper script for fresh machines with no repo present
2. repo-local init script for already-cloned, repair, resume, or override scenarios

That means:

- fresh node: `install_mds_node.sh`
- existing node / repair / rerun: `mds_node_init.sh`
- fresh GCS: `install_gcs.sh`
- existing GCS / repair / rerun: `mds_gcs_init.sh`
- announce-only retry: `mds_node_announce.sh`

This is one stack, not two competing systems. The wrapper exists only because a fresh machine cannot run a repo-local init script before the repo exists.

### Fleet Changes

- new drone joining fleet: candidate announce -> Fleet Enrollment -> accept as new
- same drone with new companion image: bootstrap -> announce -> Fleet Enrollment -> recover existing node
- spare physical drone taking failed slot: bootstrap -> announce -> Fleet Enrollment -> replace existing slot
- same node, GCS unavailable during bootstrap: rerun `mds_node_announce.sh`, not full bootstrap
- slot reassignment without physical replacement: Mission Config, not Fleet Enrollment

## What Is Correct Today

These decisions should stay:

- node bootstrap writes `/etc/mds/local.env`
- node bootstrap writes `/etc/mds/node_identity.json`
- node runtime marker still uses `~/mavsdk_drone_show/<N>.hwID`
- GCS bootstrap writes `/etc/mds/gcs.env`
- candidate announce is explicit and machine-readable
- Fleet Enrollment owns accept / replace / recover / reject
- real-hardware MAVLink routing goes through `mavlink-anywhere`
- MDS local endpoints remain:
  - `127.0.0.1:14540` MAVSDK
  - `127.0.0.1:14569` optional `mavlink2rest`
  - `127.0.0.1:12550` local telemetry controller
  - `GCS_IP:24550` remote GCS/QGC

## Blocking Gap Before Private Customer Demo

### Problem

Both bootstrap wrappers currently clone the repo before the SSH deploy key can be generated, shown to the operator, and authorized on GitHub.

That means:

- `install_mds_node.sh` fails clean first-time private SSH bootstrap on a fresh machine
- `install_gcs.sh` has the same problem on a fresh GCS host

Current behavior:

- wrapper defaults to anonymous HTTPS clone
- wrapper only later passes the intended repo/auth details to the repo-local init script
- private repo access on first clone is therefore not actually solved

### Why This Matters

For a real private customer deployment, this becomes the highest-risk setup failure:

- fresh node cannot clone a private customer repo
- fresh GCS cannot clone a private customer repo
- operators may work around it manually, which breaks the canonical workflow

### Required Fix

Before the client demo deployment, official MDS should do one of these:

1. Preferred:
   - make wrapper bootstrap download only the minimal init payload first
   - generate / verify deploy key
   - authorize repo access
   - only then clone the target repo

2. Acceptable interim option:
   - keep wrapper public-bootstrap capable
   - document that first-time private repo bootstrap must start from a temporary public clone or local tarball, then run repo-local init with private repo settings

Option 1 is the correct professional solution.

## Current Recommended Customer Demo Workflow

This is the workflow I recommend once the private-bootstrap gap is closed.

### 1. Create Customer Private Repo

Recommended model:

- do not use a public GitHub fork if confidentiality matters
- create a private org-owned repo seeded from official MDS
- keep a dedicated demo branch, for example `customer-demo`

Repository access policy:

- GCS: SSH deploy key with write access if dashboard config/show saves will push
- nodes: SSH deploy key with read-only access
- SITL private build/runtime: authenticated HTTPS token file is still the most practical non-interactive path

### 2. Bootstrap Customer GCS

Fresh host:

- `install_gcs.sh`

Existing or repair:

- `mds_gcs_init.sh`

GCS must end with:

- correct repo + branch persisted in `/etc/mds/gcs.env`
- intended auth mode pinned
- dashboard/backend using the same repo selection as git-sync and save/push workflows

### 3. Bootstrap Customer Node

Fresh host:

- `install_mds_node.sh`

Existing or repair:

- `mds_node_init.sh`

The node bootstrap should remain responsible for:

- prerequisite packages
- MDS user / paths
- repo selection
- venv and Python deps
- MAVSDK server binary
- `mavlink-anywhere`
- firewall
- time sync
- NetBird and/or static IP
- machine-readable report output
- candidate announce

### 4. Network Selection

The workflow should remain explicit:

- if NetBird is used:
  - install / connect NetBird
  - capture the NetBird IP
  - use that as the preferred GCS-facing IP
- if local/static network is used:
  - operator can confirm detected IP or provide explicit static IP config

Recommended UX doctrine:

- never silently overwrite the intended drone IP in fleet config
- announce should report all discovered addresses
- Fleet Enrollment should let the operator accept the candidate and choose which IP becomes the managed fleet IP

### 5. Candidate Enrollment

Once the node announces:

- candidate appears in Fleet Enrollment
- operator sees:
  - `Pn|Hm` when resolvable
  - repo / branch
  - candidate IPs
  - hostname / identity summary
  - whether it is a new node, replacement candidate, or recovery candidate

Operator actions remain:

- accept as new
- replace existing slot
- recover existing node
- ignore
- reject

### 6. Post-Accept Verification

After acceptance, the operator should verify:

- candidate becomes an enrolled fleet drone
- `config.json` / `swarm.json` changes are correct
- new drone appears in Dashboard cleanly
- heartbeat identity matches accepted assignment
- repo branch and commit are correct
- MAVLink routing is healthy
- onboard services are running

## `mavlink-anywhere` Audit

### Current State

`mavlink-anywhere` is already more automation-friendly than older MDS docs implied.

It already supports:

- `--auto`
- `--headless`
- explicit endpoint lists
- MDS-compatible ports and routing style

### What Should Not Change

Because existing users may follow older docs or videos, avoid breaking user-visible behavior in the external repo.

Do not rewrite it into a different product.

### What Is Worth Improving Later

Non-breaking improvements that help MDS:

- refresh README examples so they reference current MDS scripts, not older `mds_init.sh`
- add clearer machine-readable/reporting outputs where practical
- add a cleaner “MDS recommended profile” example for headless automation
- document NetBird + GCS endpoint patterns more explicitly

This should be a follow-up improvement, not a prerequisite blocker for the official MDS closeout.

## Documentation Gaps Found

These guides still create avoidable confusion and should be cleaned in the official repo before the customer demo workflow is declared closed:

### `docs/guides/netbird-setup.md`

Still references older manual configuration paths like:

- `/etc/mds/drone.env`
- direct `src/params.py` editing for GCS IP

That conflicts with the current `local.env` + candidate enrollment model.

### `docs/guides/mavlink-routing-setup.md`

Still presents a largely manual Raspberry Pi flow as the main path.

That remains useful as an advanced manual fallback, but it should explicitly say:

- canonical real-hardware path is node bootstrap with integrated `mavlink-anywhere`
- manual routing is fallback / advanced use only

### `docs/guides/mds-init-setup.md`

Still contains “SSH as pi, clone manually first” guidance as part of the normal flow.

That is valid for the repo-local init path, but it should be more clearly separated from the fresh-machine wrapper path.

### `docs/guides/deployment-quick-reference.md`

Contains older hardware-oriented guidance that should not be treated as the current source of truth for provisioning.

## What Must Be Closed Before Client Demo Deployment

### Required

1. Fix first-time private repo bootstrap in both wrappers.
2. Clean stale docs so they do not point users to legacy `drone.env` / `params.py` network setup.
3. Ensure the official docs clearly distinguish:
   - fresh bootstrap
   - repo-local init
   - announce-only retry
   - Fleet Enrollment actions
4. Re-run a documented dry-run / validation pass for:
   - fresh GCS private bootstrap
   - fresh node private bootstrap
   - candidate announce
   - accept new
   - replace
   - recover

### Strongly Recommended

5. Add one automation-ready example for:
   - read-only node bootstrap
   - writable GCS bootstrap
   - NetBird-enabled path
   - local/static-network path
6. Add one concise operator playbook that says exactly which script to run in each scenario.

## Recommended Implementation Phases

### Phase 1: Fix Wrapper Private-Bootstrap Flow

- node wrapper
- GCS wrapper
- explicit private repo first-clone validation

### Phase 2: Docs and Workflow Cleanup

- remove stale `drone.env` / `params.py` operational guidance
- separate canonical versus fallback manual flows
- refresh custom-repo and headless automation guides

### Phase 3: Real-Hardware Validation

- dry-run / validation on the real companion computer
- candidate announce
- enrollment accept / replace / recover
- verify dashboard visibility and service health

## Final Recommendation

Do proceed with the customer-specific private repo workflow, but only after closing the wrapper private-bootstrap gap in official MDS.

Everything else is refinement. That one issue is the true deployment blocker.

The current official architecture is otherwise sound:

- one bootstrap stack
- one enrollment workflow
- one identity doctrine
- one real-hardware MAVLink routing layer

That is the right foundation for a private customer demo and for later MCP / automation expansion.

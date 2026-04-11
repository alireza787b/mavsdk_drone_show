# Hardware Demo Final Review

Date: 2026-04-11
Status: Final pre-implementation review note
Scope: Final operator and architecture answers before closing the official bootstrap/enrollment phase and starting the private customer demo path

## Final Decisions

### 1. User-facing bootstrap philosophy

The user-facing story should be:

- fresh node: run one official node bootstrap command
- fresh GCS: run one official GCS bootstrap command
- existing node / repair / rerun: run the repo-local node init
- existing GCS / repair / rerun: run the repo-local GCS init
- candidate announce retry only: run announce-only

So the user should think in terms of **one path**, not two competing systems.

Internally, it is still layered:

- official wrapper
- repo-local init engine

But that complexity should stay behind the scenes.

### 2. Should customer deployments start from the official bootstrap?

Yes.

This is the clean model:

1. start from the official bootstrap wrapper
2. choose target repo / branch / auth mode
3. wrapper prepares auth
4. wrapper clones the selected repo
5. selected repo’s init logic becomes active

That gives:

- one stable public entrypoint
- support for official repo and private customer repos
- good CLI / MCP / Ansible ergonomics

### 3. Does the customer need to edit `src/params.py` before first bootstrap?

No. That should not be the required workflow.

The correct pre-bootstrap customer preparation is:

1. create or seed the private repo
2. create the intended branch
3. ensure the repo contains the MDS code they want to deploy
4. authorize the generated deploy key when bootstrap asks for it

The runtime repo/branch selection should come from:

- `/etc/mds/gcs.env` on GCS
- `/etc/mds/local.env` on nodes
- explicit exported env for SITL

`src/params.py` should remain fallback only.

Current repo still contains verification code that compares selected repo/branch against `params.py`. That is acceptable as a warning for now, but it should not imply that customer operators must edit `params.py` first.

### 4. Network model should not be NetBird-only

Correct.

The official workflow should remain provider-neutral at the architecture level.

The clean network modes are:

- local/static network
- overlay VPN
  - NetBird today
  - future Tailscale / WireGuard / similar can fit the same model
- manual advanced routing mode

So NetBird is a current implementation option, not the permanent abstract model.

### 5. If NetBird is already installed and connected, what should happen?

Best-practice behavior:

- detect existing registration
- show current peer identity, management URL, and IP
- ask whether to keep or rebind
- default to **reuse existing registration**

The bootstrap should not force destructive re-registration just because the node is being reconfigured.

### 6. Are service restarts or reboot needed after enrollment?

GCS:

- no full restart should be required for normal accept / replace / recover actions

Drone:

- no full reboot should be inherently required
- but the node still needs the updated repo contents locally after enrollment

So the clean rule is:

- **post-enrollment node sync is required**
- full reboot is not the normal answer

### 7. Real-hardware permissions

The current permission model is reasonable:

- setup runs as root/sudo
- runtime uses the `droneshow` user
- groups:
  - `gpio`
  - `dialout`
  - `video`
  - `audio` when present
- narrow sudo exceptions for:
  - `raspi-gpio`
  - `systemctl restart coordinator`
  - `systemctl restart wifi-manager`

That is acceptable as the baseline real-hardware privilege model.

## Identity: Final Operator Doctrine

### Meaning

- `hw_id`: persistent physical aircraft / node identity
- `pos_id`: mission slot / show role identity
- `mav_sys_id`: MAVLink transport identity

### Across modes

- Fleet Enrollment: `hw_id`
- PX4 Params / Onboard ULog / maintenance: `hw_id`
- Smart Swarm live follow graph: `hw_id`
- Drone Show / Mission Config / launch ownership: `pos_id`
- Swarm Trajectory and QuickScout planning: slot-oriented, hardware-resolved at execution

### Files on node

Today there are still multiple identity artifacts:

- `~/mavsdk_drone_show/<N>.hwID`
- `/etc/mds/local.env`
- `/etc/mds/node_identity.json`

Current best-practice interpretation is:

- `.hwID` is the current runtime compatibility marker
- `local.env` is the service/env override source
- `node_identity.json` is the structured automation/enrollment manifest

Operators should **not** manually edit `.hwID` as the main workflow.

The intended operational sources should be:

- bootstrap/init
- `local.env`
- `node_identity.json`

The remaining cleanup task is to reduce human-facing ambiguity, not to invent another identity store.

## What Still Must Be Fixed In Official MDS

### Required

1. Fix first-time private repo bootstrap in both wrappers.
2. Add clean reuse/rebind handling for already-registered NetBird nodes.
3. Make post-enrollment node sync explicit in UX/docs, and automate it where safe.
4. Remove stale ambiguity in `src/params.py`:
   - old `config_url`
   - old `swarm_url`
   - misleading `offline_config` comments
5. Clean stale docs that still imply routine manual editing of:
   - `src/params.py`
   - old `drone.env`

### Strongly recommended

6. Clarify one official operator playbook for:
   - new node
   - recover same node
   - replace with spare
   - slot reassignment only
7. Add explicit validation checks for private repo bootstrap on:
   - fresh GCS
   - fresh node
   - real hardware
8. Reduce identity duplication messaging in docs so operators always know where to look first.

## Customer Demo Prep: What The Customer Must Do

Before bootstrap:

1. create the private repo
2. seed it from official MDS
3. create the intended working branch
4. decide auth model:
   - GCS write-enabled SSH deploy key
   - node read-only SSH deploy key
5. decide network mode:
   - local/static
   - NetBird / overlay VPN
6. decide whether SITL should use:
   - mutable repo sync
   - pinned custom image

What they should **not** need to do:

- edit `src/params.py` just to point to their repo
- edit old network settings manually in code
- maintain separate conflicting bootstrap methods

## Hetzner GCS Next Step

Hetzner is reachable over SSH and NetBird is now installed there.

The next step is user authentication for the NetBird device registration, then verification from this host.

If the auth session expires before use, the correct next action is simply to rerun:

```bash
ssh root@204.168.181.45 'netbird up'
```

and capture the new login URL.

## Final Recommendation

The official architecture should stay.

What needs to change is not the overall model, but the operational polish:

- wrapper auth ordering
- NetBird reuse behavior
- post-enrollment node sync
- stale config/docs cleanup

After those are fixed, the official repo will be in the right shape to:

- create the private customer repo
- bootstrap customer GCS on Hetzner
- bootstrap the reachable Holybro companion computer
- validate candidate enrollment and replacement on real hardware
- then proceed into customer-specific customization and demo validation

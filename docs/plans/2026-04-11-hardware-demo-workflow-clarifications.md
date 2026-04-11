# Hardware Demo Workflow Clarifications

Date: 2026-04-11
Status: Research / review clarification note
Scope: Final clarification pass before implementing the official private-customer bootstrap closeout

## Direct Answers

### 1. Why are there two scripts? Can this be simpler for users?

Yes. The user-facing workflow should be simpler than the current explanation.

The correct model is:

- keep **one public bootstrap entrypoint per host type**
- keep **one repo-local init engine per host type**

That means:

- fresh node with no repo present:
  - `install_mds_node.sh`
- fresh GCS with no repo present:
  - `install_gcs.sh`
- existing node / repair / resume / override:
  - `mds_node_init.sh`
- existing GCS / repair / resume / override:
  - `mds_gcs_init.sh`
- announce-only retry:
  - `mds_node_announce.sh`

This is not two competing workflows. It is one layered workflow:

- **wrapper** = gets a fresh machine to the point where the repo-local tool can run
- **init** = real source of truth for setup logic

### 2. Should the wrapper always come from the official repo even for custom/private repos?

Yes. That is the cleanest model.

Recommended doctrine:

- the bootstrap wrapper should always be fetched from the official MDS repo
- the wrapper should then prepare auth and clone the target repo selected by the user
- after clone, the repo-local init script from the selected repo becomes the active implementation source of truth

That gives the user one stable entrypoint while still allowing:

- official repo
- customer private repo
- custom branch
- future MCP / automation / Ansible flows

### 3. What exactly is still wrong with the current wrapper flow?

Both wrappers still clone too early.

Current problem:

- wrapper tries to clone target repo first
- SSH deploy key setup happens later inside the repo-local init script

That breaks first-time private bootstrap on a fresh machine.

Correct behavior should be:

1. official wrapper starts
2. wrapper collects target repo + branch + auth mode
3. wrapper prepares or verifies access
4. wrapper clones target repo
5. repo-local init runs

## Runtime Permissions On Real Hardware

### Setup-Time Privileges

The setup flow correctly needs root or sudo because it manages:

- package installation
- system users and groups
- `/etc/mds/*`
- systemd units
- firewall
- NTP
- NetBird installation/configuration
- hostname
- serial / routing stack setup

### Runtime Privileges

The current design is reasonable. The `droneshow` user gets the practical minimum that MDS needs on Raspberry Pi / similar Debian-family companions:

- `gpio` for onboard LED / GPIO operations
- `dialout` for serial access
- `video` where display-related access matters
- `audio` if present from the base image

The service layer also allows a narrow sudo path for:

- `raspi-gpio`
- `systemctl restart coordinator`
- `systemctl restart wifi-manager`

That is consistent with the current real-hardware service model.

### Do we need anything else?

Not as a baseline requirement.

The main operational permissions are already covered by:

- root during setup
- system groups
- narrow sudoers entries

If a future client image needs more, that should be added explicitly for that hardware class, not hidden as generic MDS behavior.

## NetBird Behavior: What Should Happen If The Machine Is Already Registered?

The desired behavior is clear. The current implementation is not fully there yet.

### Best-Practice Behavior

If NetBird is already installed and connected, bootstrap should:

1. detect that state
2. show the current peer name, management URL, IP, and connection status
3. ask whether to:
   - keep current registration
   - rebind to a different NetBird management server
   - reconnect with a new setup key
4. only perform a re-registration if the operator explicitly chooses it

That avoids accidental overlay churn on a fielded node.

### Renaming

Host identity should be handled in this order:

1. set Linux hostname first
2. if NetBird registration does not exist yet, let NetBird pick up the new hostname naturally
3. if the device is already registered, do not silently destroy and recreate the peer just to rename it

So the clean rule is:

- **reuse by default**
- **re-register only intentionally**

### Current Gap

Today the NetBird phase is still too setup-key centric. It can install and connect, but it does not yet present a clean “already registered, keep or rebind?” operator path.

That should be fixed before we treat the real-hardware flow as fully polished.

## Does Enrollment Require Service Restarts?

### GCS

No full GCS service restart should be required for normal candidate actions.

Current enrollment actions already update durable GCS-side state directly:

- candidate registry
- `config.json`
- `swarm.json` when replacement rewrites Smart Swarm `hw_id` / `follow`

That part is hot-applied on GCS.

### Drone

This is more nuanced.

The drone does **not** generally need a full reboot just because Fleet Enrollment accepted or replaced it.

But MDS real-hardware drones still operate in local config mode:

- `offline_config = True`
- `offline_swarm = True`

So after GCS commits updated fleet config to git, the node still needs to pull that repo change before the new fleet config is truly local on the drone.

That means:

- GCS restart: not required
- drone reboot: not inherently required
- **drone repo sync/apply step: required**

The right operator workflow after acceptance/replacement/recovery is:

1. Fleet Enrollment change succeeds
2. GCS commits/pushes if enabled
3. operator triggers sync for the affected node, or waits for next boot sync
4. node uses the updated local config after sync

So the missing concept is not “restart everything,” it is “make post-enrollment node sync explicit.”

## Single Source Of Truth: Remaining Ambiguity

The biggest remaining ambiguity is this:

- official workflow says `/etc/mds/local.env` and enrollment are the source of truth
- drone code still contains old `Params.config_url` / `Params.swarm_url` legacy values
- comments in `Params` still say offline config is “not used!” even though local-file mode is exactly what the node is using

That is not acceptable for a final hardware workflow.

Before the client demo bootstrap is declared closed, official MDS should clean this up:

- remove or quarantine stale remote-config URLs
- make the local-config behavior explicit
- align comments/docs with the real runtime

## Identity Alignment Across Modes

Current doctrine should stay:

- `hw_id` = physical node / aircraft
- `pos_id` = mission slot / role
- `mav_sys_id` = MAVLink address

Mode behavior remains:

- Drone Show: slot-oriented
- Mission Config: slot assignment
- Smart Swarm: hardware-oriented live follow graph
- Swarm Trajectory: slot planning, hardware-resolved execution
- QuickScout: slot/team planning, hardware-resolved execution
- Fleet Enrollment: hardware-oriented
- PX4 Params / Onboard ULog / maintenance: hardware-oriented

This remains the correct professional model.

## Recommended Simplified User Story

This is the version I would expose to operators and automation:

### Fresh GCS

Run one command:

```bash
curl -fsSL <official-install-gcs-url> | sudo bash -s -- [repo/branch/auth options]
```

### Fresh Node

Run one command:

```bash
curl -fsSL <official-install-node-url> | sudo bash -s -- [node/repo/network options]
```

### Existing GCS / Existing Node

Run the repo-local init tool again.

### If GCS Was Offline During Node Bootstrap

Run:

```bash
sudo ./tools/mds_node_announce.sh
```

### If A New Node Appears

Use Fleet Enrollment.

### If A Spare Replaces A Failed Physical Aircraft

Use Fleet Enrollment replacement.

### If Only Show Slot Ownership Changes

Use Mission Config.

This is the clean conceptual separation. The implementation should match it.

## What I Recommend Fixing Before The Customer Demo Deployment

### Required

1. Fix first-time private repo bootstrap in both wrappers.
2. Add explicit “reuse existing NetBird registration” handling.
3. Add explicit post-enrollment node sync guidance or automation.
4. Clean stale local-vs-online config comments and legacy URLs in `Params`.
5. Clean stale docs that still tell operators to edit `drone.env` or `params.py` manually for normal network workflow.

### Strongly Recommended

6. Make the official docs present the user-facing story above, not the internal wrapper/init layering.
7. Add one headless example for:
   - fresh private GCS
   - fresh private node
   - NetBird-managed node
   - local/static-network node
8. Add one verification checklist for real-hardware onboarding:
   - repo access
   - MAVLink routing
   - MAVSDK server
   - candidate announce
   - Fleet Enrollment mutation
   - node sync
   - dashboard visibility

## Hetzner / Demo Environment Note

I did not start the customer deployment yet.

For the next implementation phase, the likely sequence is:

1. fix the official bootstrap gaps
2. validate on Hetzner as the fresh customer GCS target
3. connect that GCS to NetBird if required
4. validate against the reachable CM4 / Holybro companion node
5. only then create and exercise the customer-specific private repo workflow

If NetBird auth is needed for the Hetzner GCS during implementation, the clean next step is to generate a short root-side note with the auth URL and pause for operator approval.

## Final Recommendation

The architecture is close. The remaining work is not a rewrite.

The real closeout items are:

- fix wrapper auth ordering
- tighten NetBird reuse behavior
- make post-enrollment node sync explicit
- remove the last stale config/documentation ambiguity

Once those are done, the official hardware bootstrap + enrollment flow will be clean enough to use as the base for a private customer demo repo and first real-hardware rollout.

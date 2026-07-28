# MDS vNext: connectivity, recovery, propagation, and legacy review

**Date:** 2026-07-28

**Status:** Architecture checkpoint for review; implementation is not complete.

This review extends the two earlier vNext documents after a deeper audit of
NetBird/Tailscale/static networking, MAVLink Anywhere, Smart WiFi Manager,
GCS-loss behavior, field recovery, and legacy/deprecation risks.

## The important correction

The original direction—Git for development, signed releases for software,
revisioned GCS state for fleet data, and immutable mission packages—is still
correct. It was not complete enough about the things around MDS.

The complete model must also define:

- how a node finds GCS when its IP changes;
- who owns Wi-Fi, VPN, and MAVLink router mechanics;
- what continues when GCS is unavailable;
- how an operator repairs a grounded node from the field;
- how a local repair becomes visible drift instead of a secret second source;
- how one MDS installation scales across sites and MAVLink routing domains;
- which current security gaps block a production release;
- how old Git-era procedures remain available during migration without confusing
  normal users.

## Ownership: who is responsible for what?

| Area | Owner | MDS relationship |
|---|---|---|
| Ethernet, Wi-Fi, cellular, DHCP, DNS, VPN | OS/network provider | MDS observes health and requests guarded profile changes |
| NetBird or Tailscale identity | selected overlay provider | Transport and peer ACL; not MDS authorization or node identity |
| Smart WiFi Manager | NetworkManager/Wi-Fi component | Owns SSID mechanics, secrets, checkpoint rollback, and last-known-good profile |
| MAVLink Anywhere | MAVLink router component | Owns serial/router mechanics and packet forwarding |
| PX4/QGC flight safety | PX4, RC, QGC, physical safety path | Remains authoritative during flight and GCS outage |
| MDS control plane | GCS + node agent | Owns desired revisions, release/mission deployment, guarded commands, audit |
| MDS mission execution | node/PX4 runtime | Uses an approved, immutable mission package |
| Operator recovery | `mdsctl` + fixed privileged helpers | Uses last-good rollback and explicit maintenance/break-glass authority |

MDS should not duplicate Smart WiFi Manager or MAVLink Anywhere internals. It
should publish a typed desired policy, call a versioned component contract, and
observe desired/applied/effective health and hashes.

## Connectivity must be an endpoint model, not one IP field

The current runtime assumes `config.json.ip` and GCS-initiated HTTP. That does
not cover DHCP, changed overlay addresses, NAT/CGNAT, IPv6, multiple interfaces,
or a node that can reach GCS but cannot accept inbound traffic.

### Proposed endpoint record

```text
ControlEndpoint
  endpoint_id
  node_id
  provider: lan | netbird | tailscale | cellular | usb | dns | manual
  address/hostname
  IP family and port/protocol
  interface and site/routing-domain scope
  priority and cost/metered flag
  authentication/proof state
  observed_at, TTL, last probe, reachability
```

The node identity is a certificate/UUID. An IP is merely an observed path.

The node bootstrap record should contain an ordered list of GCS endpoint URIs,
certificate pins, retry/backoff policy, and the last-known-good endpoint. It
should not contain only `MDS_GCS_IP`.

### NetBird and Tailscale

Both are optional endpoint providers:

- use provider identity only to create the network path;
- use MDS node certificates/UUIDs for MDS authorization;
- do not detect the provider by “first IPv4 beginning with `100.`”;
- do not reuse one fleet-wide setup key;
- use one-time/scoped enrollment material stored in a root-only file, never
  shell arguments, history, or logs;
- keep provider ACLs narrow, but do not treat overlay reachability as application
  authorization;
- support LAN-only, overlay-only, and multiple simultaneous paths.

The MDS endpoint resolver should select the best authenticated reachable path
and report why it selected it. A path change is a normal reconciliation event,
not a new hardware identity.

### Static IP, DHCP, and changing IP

Preferred order:

1. stable local DNS/service discovery or DHCP reservation;
2. overlay hostname/peer identity;
3. explicitly configured static address;
4. temporary/manual endpoint as a visible break-glass override.

Changing an address must update endpoint observations and health, not rewrite
the node identity. The node should initiate or maintain a long-lived
authenticated control session where possible; direct inbound HTTP remains a
small trusted-lab adapter.

## Smart WiFi Manager integration

Smart WiFi Manager remains optional. Its responsibilities are:

- NetworkManager profile mechanics;
- Wi-Fi credential handling;
- emergency/recovery networks;
- last-known-good profile;
- make-before-break and timed rollback.

MDS responsibilities are:

- desired connectivity policy and revision;
- maintenance lock and grounded/disarmed gate;
- target/impact preview;
- authenticated apply request;
- observation of applied/effective revision and reachability;
- fleet-level rollout, pause, rollback, and audit.

### Safe Wi-Fi apply

```text
1. Confirm grounded/disarmed and acquire maintenance lease.
2. Snapshot the active path and last-known-good profile.
3. Confirm a second recovery path (Ethernet, console, other overlay, or USB).
4. Stage the new profile without removing the working path.
5. Use NetworkManager checkpoint/timed rollback.
6. Test link, DHCP/DNS, GCS session, overlay, and MAVLink health.
7. Commit only after authenticated acknowledgement.
8. Otherwise automatic rollback and report degraded last-known-good.
```

The sole current management path and protected emergency network must not be
pruned in the same transaction. A sanitized profile hash cannot prove that a
password changed; report a non-secret `secret_generation` or fingerprint
reference separately from the public profile hash.

## MAVLink Anywhere integration

MAVLink Anywhere should be a separately versioned, signed component—not a
second Git checkout pulled by every node.

Separate:

- node-local hardware source: UART/device/baud/PX4 input;
- fleet endpoint policy: allowed destinations and routing domain;
- router runtime: package version, service state, effective config hash;
- observed health: packet age/rate, drops, system IDs, destination reachability.

Use logical destinations such as `gcs://site-primary-mavlink`, resolved by the
endpoint resolver, instead of embedding a changing IP in every router profile.

### Safe MAVLink apply

```text
validate → stage router profile → detect conflicts/loops/sysid collisions
→ atomically reload → verify packets/peers/rates → commit
→ rollback if router or FC heartbeat does not recover
```

The recovery/control channel must remain independent of the MAVLink router. A
router failure must not remove the only way to repair the node.

MAVLink system IDs are limited to 1–255. A thousand-node management fleet
therefore cannot be one flat MAVLink/QGC routing domain. Add an explicit
`routing_domain_id`; enforce uniqueness of
`(routing_domain_id, mav_sys_id)` and use site gateways/partitions for large
fleets.

MAVLink 2 signing can authenticate/tamper-protect packets but is not a
replacement for encrypted transport or MDS authorization. Production router
listeners must be interface/source restricted and unused TCP endpoints disabled.

## What happens when GCS is unavailable?

“GCS unavailable” is not one failure. Show the operator which one occurred:

1. Internet unavailable;
2. NetBird/Tailscale/overlay unavailable;
3. GCS API/control session unavailable;
4. MAVLink/QGC path unavailable;
5. companion/node unavailable;
6. Smart Swarm peer/leader unavailable;
7. time source unavailable.

### Grounded node, GCS unavailable

- keep the last-known-good software, configuration, router, and approved mission;
- do not activate a new release/config/mission/network change;
- do not launch a new coordinated mission by default;
- allow local health checks and a pre-tested direct QGC/emergency path;
- allow only an explicitly authorized break-glass operation;
- spool events/results locally for later reconciliation.

### Airborne node, GCS unavailable

- do not change software, config, connectivity, router, or active mission bytes;
- let the current node/PX4 mission continue according to its reviewed policy;
- let PX4 RC, data-link, and Offboard failsafes remain authoritative;
- do not trigger RTL solely because the deployment API or artifact server is gone;
- distinguish GCS application loss from MAVLink loss, overlay loss, RC loss, and
  Offboard stream loss;
- use RC/QGC/physical safety procedures, not SSH as an in-flight control path.

An already approved scheduled autonomous start is a separate signed authority
policy; it must never arise accidentally from a network timeout.

### Recovery after GCS returns

Nodes replay a durable outbox of command results, health, and audit events.
GCS ingests idempotently by event sequence and operation ID. New operations
must carry an authority epoch and expiry so stale commands cannot execute after
reconnect.

For high availability, use one active command authority. A standby requires a
deployment UUID, signed authority epoch, lease/fencing, and recovery procedure;
two independent GCS instances must never both issue commands.

## The field fallback: keep the good part, replace the dangerous part

The old field procedure was valuable because an operator could still recover a
grounded node when GCS or Git was unhealthy. We should keep that capability,
but make it explicit and auditable.

### Standard recovery commands (proposed)

```text
mdsctl node status
mdsctl node doctor
mdsctl node logs --redacted
mdsctl node network-test
mdsctl node backup
mdsctl node restore <verified-bundle>
mdsctl node revert-last-good
mdsctl node announce
mdsctl node support-bundle
mdsctl server restart
mdsctl server auth break-glass
```

Human-readable and `--json` output should use the same typed contract.

### SSH as break-glass, not a second normal product

SSH remains available for a grounded node, but:

- key-only, source-restricted, host-key-verified access;
- separate recovery identity, not shared root/password;
- time-bound maintenance lease and operator/reason;
- read-only diagnosis by default;
- privileged changes through fixed root-owned wrappers;
- armed/in-flight mutations rejected;
- before/after hashes, actor, reason, and expiry recorded;
- local override appears as visible `Local override`/`Drifted` state;
- operator must later promote or revert the override through GCS.

Do not make raw `curl`, `git reset`, or `nano` the normal V6 runbook. During
the migration window, the v5 Git procedure remains a documented rollback path,
not a silent parallel source of truth.

### If everything is broken

The recovery order is:

```text
physical/console or independent LAN
→ read-only node doctor
→ revert last-good signed artifact/profile
→ restore endpoint/certificate bundle
→ verify GCS session + MAVLink + time
→ re-enroll/rotate credentials if required
→ reconcile local drift with GCS
```

An offline USB recovery bundle uses the same manifest/signature verifier as
online delivery. It must not be a weaker unsigned path.

## Code, config, connectivity, and mission propagation

These are four different propagation classes.

### Code

Developer pushes Git → CI tests/builds/signs release → GCS selects a digest →
operator approves rollout → nodes pull and activate it.

A code change does **not** automatically reach production drones merely because
the developer pushed `main`. A developer may explicitly deploy a development
artifact to selected SITL/lab nodes using the same guarded path.

During v5 compatibility mode, startup Git sync may still pull the configured
branch. That behavior must be visibly labeled legacy and must not be carried
forward as the V6 default.

### Fleet configuration

Dashboard edits create a draft fleet revision. After validation and approval,
nodes pull that small revision and report the applied hash. Offline nodes remain
pending; they do not become “in sync” because the GCS assumes success.

### Mission/show

If a CSV changes, the operator creates a new mission revision. Nodes do not
search Git independently or guess which CSV is newest.

```text
GCS stores source → validates/compiles → publishes M18
→ nodes discover/poll/receive notification → stage M18
→ verify hash → operator activates M18
```

Only the nodes that need a changed trajectory download that blob. An active
mission stays immutable while armed. A new CSV never silently replaces the
mission currently flying.

### Connectivity and MAVLink

These are maintenance operations with make-before-break/checkpoint rollback.
They are not ordinary config-file edits and are never applied while armed.

## Standard operator and developer course of action

### Fresh GCS

1. Install a signed official package.
2. Choose SITL or real mode and lab or hardened posture.
3. Create or import a Workspace.
4. Verify disk, time, endpoint, artifact cache, and recovery path.
5. Enroll nodes.

### Add/enroll node

1. Generate a short-lived enrollment code.
2. Node announces UUID, certificate fingerprint, hardware, and capabilities.
3. Operator reviews and accepts the candidate.
4. Assign airframe identity, mission slot, role, routing domain, and profiles.
5. Preview desired-state diff.
6. Approve, deploy, and verify release/config/connectivity/MAVLink/preflight.

### Replace/recover node

- same airframe/new companion: preserve airframe and slot; rotate node identity;
- spare aircraft takes a failed slot: one explicit reassignment transaction;
- reimage same machine: retain asset relation but issue a new install credential;
- old node becomes reserve/retired, never silently disappears.

### Remove node

These are distinct actions:

1. unassign mission slot;
2. move to reserve/maintenance;
3. retire/decommission and revoke credential.

Decommission requires grounded/disarmed state, dependency review, and an audit
tombstone. Optional local wipe is a separate confirmation.

### Change code

Build one release from one source commit. Test in SITL, canary a lab/field
node, expand by site/routing domain, and retain one last-good release.

### Change config

Draft → validate cross-references → review diff → approve → deploy → verify.

### Change mission

Author/import → compile/validate → preview → approve immutable revision →
stage/verify → activate with guarded command.

### Change connectivity/MAVLink

Maintenance lock → backup → second recovery path → stage → test → commit or
automatic rollback.

## Legacy clarity policy

The most dangerous outcome is two systems that both appear authoritative.

### One canonical normal flow

```text
Overview
Missions
Fleet (inventory/enrollment/assignments/connectivity)
Deployments
Diagnostics
Settings
SITL
Simurgh
```

Fleet node detail contains Summary, Connectivity, MAVLink, Config,
Deployments, and Logs. Fleet-wide pages are projections of the same model.

### Explicit legacy adapter

During migration:

- `mdsctl import-legacy` imports current JSON/Git/shapes and writes a report;
- legacy Git status/sync is under an explicit Legacy/Compatibility surface;
- legacy routes are namespaced or visibly labeled and emit deprecation telemetry;
- generated `config*.json`/`swarm*.json` are read-only compatibility views;
- no silent fallback between old and new sources;
- every alias has an owner, replacement, usage telemetry, and sunset release.

After migration telemetry proves zero use, retire Git runtime sync, raw
Save-and-Commit, direct Add/Remove row editing, arbitrary raw environment
mutation, URL/token runtime flags, NetBird `100.*` heuristics, in-place sidecar
Git installers, and legacy common-parameter application.

## Current release blockers discovered in this review

These are not “later polish”:

1. The node API binds broadly and several command/config/sidecar/PX4 mutation
   routes lack the same general machine-credential guard currently used for
   ULog operations.
2. Firewall rules expose broad ports/sources; MAVLink listeners and internal
   endpoints need interface/source policy.
3. Passwordless sudo permits wildcard unit-file operations, unrestricted Git,
   and root execution of mutable repository scripts.
4. Network/router/sidecar/config mutations lack a universal grounded/armed
   interlock.
5. NetBird provisioning exposes setup keys in shell arguments and uses unsafe
   install/rebind paths.
6. Smart WiFi can report an old last-good helper as success and conflate
   desired/applied/effective secret state.
7. Sidecar operations are process-memory, sequential, short-lived, and lack
   durable per-node rollback state.
8. GCS command-result callbacks are not durable across long outages/restarts.
9. Time source and uncertainty are not first-class readiness evidence.
10. MAVLink system-ID/routing-domain limits are not represented for large
    fleets.

V6 should not be called production-ready until these have tests and documented
trusted-lab versus hardened behavior.

## Updated phased plan

### Phase 0 — contracts and release blockers

Define node/airframe/slot identity, endpoint resolver, routing domain, authority
epoch, operation envelope, connectivity/provider contracts, mission lifecycle,
time evidence, and status dimensions. Close node auth, firewall, sudo,
armed-gate, NetBird, Wi-Fi rollback, and secret-leak findings.

### Phase 1 — durable control plane

SQLite/WAL repositories, atomic writes, backups, restore, event/outbox,
idempotency, conflict/ETag, and explicit `mdsctl` doctor/status/recovery.

### Phase 2 — signed release plane

Signed GCS/node/sidecar/MAVLink artifacts, SBOM/provenance, digest verification,
A/B or atomic activation, health deadlines, and last-good rollback.

### Phase 3 — node control/session plane

Enrollment, mTLS or equivalent signed requests for every unsafe route,
endpoint discovery, long-lived authenticated session, offline cache, durable
outbox, authority epoch, and capability/precondition reporting.

### Phase 4 — connectivity and MAVLink adapters

NetBird, Tailscale, LAN/DHCP/static, cellular, Smart WiFi Manager, and MAVLink
Anywhere behind versioned provider contracts. Add make-before-break, router
rollback, logical endpoints, and path-aware status matrix.

### Phase 5 — mission/config packages

Typed fleet revisions, immutable mission packages, compiler/validator manifests,
staging/activation, import/export, and read-only legacy views.

### Phase 6 — unified operator workflow

Workspace/Deployment UX, node-detail connectivity/MAVLink tabs, durable target
plans, status dimensions, explicit break-glass flow, and Simurgh checkpoints.

### Phase 7 — scale and HA

Load test 1/10/50/100/500/1,000 nodes. Add async telemetry, site gateways,
artifact cache/relay, PostgreSQL/object store adapters, routing-domain
partitioning, and one fenced standby authority where required.

### Phase 8 — migration

Official SITL → one real node → site canary → fleet waves → private/client
imports/custom releases. Keep v5 rollback during the measured compatibility
window.

### Phase 9 — retirement

Remove old runtime Git, silent aliases, duplicate status calculations, direct
root repo execution, unsafe fallback paths, and stale docs only after usage
telemetry and recovery acceptance prove they are no longer needed.

## Acceptance scenarios that must be tested

- LAN-only GCS with DHCP addresses and no Internet;
- NetBird-only, Tailscale-only, both present, and neither present;
- overlay IP changes without changing node identity;
- GCS reachable through alternate endpoint after NAT/CGNAT;
- Wi-Fi bad password rolls back while an independent path survives;
- MAVLink bad destination rolls back while the recovery channel survives;
- GCS outage on ground and in flight with each link-loss type separated;
- GCS restart during rollout with durable per-node receipts;
- stale command replay after reconnect is rejected;
- local SSH override appears as drift and can be promoted/reverted;
- code/config/mission changes are not mixed in one operation;
- active mission cannot be mutated while armed;
- unsigned, wrong-target, expired, partial, or rollback artifact is rejected;
- one-node replacement preserves history and does not duplicate IDs;
- one GCS, multi-site, and 1,000-node routing-domain partition benchmarks;
- clean Ubuntu restore from backup without Git credentials;
- old v5 node/image migration and exact rollback.

## Final answer to the field-recovery fear

We should **not** remove the ability to recover a grounded drone when the GCS
is down. We should preserve it in a safer form:

- normal path: GCS desired state and signed deployment operations;
- offline path: node last-known-good state and cached approved mission;
- recovery path: `mdsctl`/SSH/USB with fixed, authenticated, grounded-only
  helpers and visible local drift;
- migration path: old Git procedure remains temporarily documented as rollback;
- permanent path: local repair produces a new signed/tainted artifact or
  explicit override, never an invisible edit that later gets overwritten.

This keeps the practical field strength of the old model without keeping Git,
raw IPs, secrets, and undocumented manual edits as competing authorities.

## References

- [Tailscale auth keys and identity](https://tailscale.com/docs/features/access-control/auth-keys)
- [Tailscale tags](https://tailscale.com/docs/features/tags)
- [NetBird setup keys](https://docs.netbird.io/manage/peers/register-machines-using-setup-keys)
- [NetworkManager checkpoint examples](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nmcli-examples.html)
- [MAVLink routing](https://mavlink.io/en/guide/routing.html)
- [MAVLink message signing](https://mavlink.io/en/guide/message_signing.html)
- [PX4 safety/failsafe configuration](https://docs.px4.io/main/en/config/safety)
- [Eclipse hawkBit rollout model](https://hawkbit.eclipse.dev/)
- [TUF overview](https://theupdateframework.io/docs/overview/)
- [Uptane standard](https://uptane.org/docs/latest/standard/uptane-standard)

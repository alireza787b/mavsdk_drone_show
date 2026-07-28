# MDS vNext in plain language, with private-repository drift review

**Date:** 2026-07-28

**Status:** Review checkpoint; generic operator improvements are now being reconciled into official `main`; migration/release work has not started.

**Audience:** Product owner, beginner operator, developer, and future deployment maintainer.

This is the simpler companion to
`2026-07-28-mds-next-major-architecture-consultation.md`.

## Short answer

Think of the future MDS as four separate things:

1. **Git is the engineering workshop.** Developers change and review source code there.
2. **A release is a sealed software box.** Drones install a tested, signed version instead of running `git pull`.
3. **GCS is the fleet notebook.** It stores which drones exist, their roles, configuration, and what version each drone actually has.
4. **A mission package is a sealed flight folder.** It contains the show/trajectory/origin/assignments and exact hashes needed to reproduce a flight.

Today these four things are mixed in the same Git checkout. The recommendation is
to separate them while keeping Git for what Git does well.

## What I found about the private customer-clone drift

The earlier “674 files” impression mixed branch-history divergence with file
content. After fetching the current private `main` and comparing the two current
trees directly, the correct content result is:

| Measurement | Result |
|---|---:|
| Actual changed paths | **155** |
| Added only in private | 52 |
| Missing/deleted in private | 28 |
| Modified in both | 75 |
| Inserted text lines | about 48,650 |
| Deleted text lines | about 97,164 |

The high line count is mostly generated reports and removing unused mission CSVs
for drones 3–10, not 100,000 lines of different application logic.

### What those 155 paths contain

| Group | Paths | Assessment |
|---|---:|---|
| Mission/show artifacts | 36 | Expected customer data |
| Customer evidence/assets | 27 | Expected, but should live outside the product source tree |
| Customer docs/plans and handoffs | 17 | Useful project history; not shared product code |
| Customer demo tools | 7 | Customer/project-specific |
| Fleet/swarm configs | 4 | Expected deployment data |
| Deployment defaults/profiles | 3 | Expected deployment data, except secrets must leave Git |
| Frontend code/tests/styles | 27 | Must be reviewed; some are useful generic improvements |
| Backend/runtime code | 13 | Must be reviewed; mixture of fixes and regressions |
| Backend tests | 7 | Follow the shared code decisions |
| Shared updater script | 1 | Private version has a security/auth regression |
| Shared/generated docs and registry | 12 | Regenerate after code/config decisions |
| Other shared metadata | 1 | Review with release reconciliation |

Approximately 94 paths are clearly customer/deployment/evidence data. The
surprising part is therefore not the entire private repository; it is the roughly
48 shared code/test paths that accumulated alongside the customer work.

### Why Git reports a much larger history divergence

The current merge base is an older April 2026 commit. Since then, official and
private work has often been copied/cherry-picked/squashed rather than merged
with shared ancestry. A private commit describing an official Simurgh sync is a
new private commit, not the same official commit.

That produces hundreds of “unique” commits even where the final patches are
equivalent. It also allowed private fixes and older shared implementations to
remain mixed together.

There is an additional provenance problem: the same release label has been used
for different trees. One version/tag name should never describe two different
trees. Future custom releases should have an explicit customer/deployment
suffix and record the official base release.

## Which repository should be the main one?

**Official `main` should remain the authority for all shared MDS code.**

The private repository should not replace official `main` because it contains:

- customer-specific fleet IPs, roles, missions, images, PDFs, reports, and scripts;
- customer names/wording in shared semantic code;
- connectivity profiles containing password fields;
- some older/weaker copies of official security validation.

But official `main` should also not blindly overwrite the private tree. The
private branch contains several useful, general improvements that deserve proper
upstream review.

### Private improvements that look suitable for official MDS

These should be extracted into small, tested upstream commits:

- clearer per-drone command failure reasons;
- truthful “saved locally but Git push failed” swarm feedback;
- better Fleet Ops preview/apply errors and target eligibility;
- useful node initialization/boot status in Overview and drone cards;
- clearer sync-warning navigation;
- canonical swarm JSON response handling;
- rejecting HOLD when a drone is not armed/airborne;
- handling inaccessible ULog fallback paths without crashing;
- mobile-friendly signed offset input;
- using the general auth-enabled state where API auth is enabled.

Each still needs review against current official contracts and tests. “It exists
in private” is evidence to inspect it, not automatic approval.

### Official implementations that must win

Do not take the private version of these:

- node boot reports in official bind to configured hardware IDs, validate
  position/IP, bound input, expire stale records, and use server receipt time;
- the official updater includes GCS bearer-token support for protected boot
  status reporting;
- official Simurgh wording remains general (“pilot” or “field tester”) instead
  of hardcoding a customer person’s name;
- official input/trust metadata and status limits are stronger;
- registry entries that claim consumers but have no current code consumer should
  be removed or implemented, not copied as stale generated documentation.

### Recommended reconciliation procedure

Do not merge either branch wholesale.

1. Preserve/tag the current private tree as a historical checkpoint.
2. Create a new reconciliation branch from current official `main`.
3. Import customer fleet, mission, evidence, and connectivity material into a
   separate customer data area/bundle; remove all secret values and rotate
   anything that was committed.
4. Extract each generic private improvement as one focused commit with tests.
5. Apply those generic fixes to official `main` after review.
6. Rebase the remaining customer code overlay on that reviewed official release.
7. Regenerate environment docs, OpenAPI/agent context, frontend references, and
   version metadata once.
8. Give custom builds their own release suffix and artifact digest.

The target is a very small private source overlay—or no source fork at all if
the customer deployment only needs different fleet data, missions, and branding.

## How the proposed system works

### Simple automation picture

```text
Developer changes code in Git
        ↓
CI tests it and creates a signed release
        ↓
GCS downloads that release once
        ↓
Operator chooses target drones and rollout waves
        ↓
Each idle drone downloads, verifies, installs, and reports its result
```

Separately:

```text
Operator changes fleet config or uploads a mission in Dashboard
        ↓
GCS creates a draft revision
        ↓
GCS validates it and shows a human-readable diff
        ↓
Operator approves it
        ↓
Selected drones pull it and report the applied revision/hash
```

There is no automatic flight action in either flow. Software/config deployment
and flight commands remain separate guarded operations.

## Scenario 1: a completely new GCS laptop or VPS

### What happens today

The operator clones a Git repository, chooses a branch/private credential,
runs installer/startup scripts, and the checkout itself becomes code, config,
mission storage, and update transport.

### Recommended vNext experience

The existing `tools/install_gcs.sh` should remain a compatibility entry point,
but install a unified `mdsctl` application rather than teaching beginners Git.

Example future flow:

```text
1. Download the official signed MDS installer/release, or copy it by USB.
2. Run: sudo tools/install_gcs.sh
3. The wizard asks: SITL or real drones?
4. It verifies the release signature.
5. It installs and starts the GCS services.
6. It creates a local Workspace.
7. The browser opens Dashboard Setup.
8. Start empty, or import an existing MDS deployment bundle.
```

Proposed managed state, subject to a final path ADR:

```text
/etc/mds/                 bootstrap settings and secret references
/var/lib/mds/control.db   fleet, revision, operation, and audit records
/var/lib/mds/artifacts/   content-addressed release and mission blobs
/var/backups/mds/         encrypted/versioned backups
```

For SITL, the wizard downloads or imports the official image by digest, creates
the requested number of simulated nodes from the Workspace fleet revision, and
does not clone Git inside every container.

For a restored GCS, importing a backup recovers the fleet inventory, mission
library, release references, operation history, and artifact hashes. Secret
material is restored separately or re-enrolled.

## Scenario 2: add one new real drone

The drone image/package already contains the small MDS node agent. It does not
contain a customer Git token.

```text
1. Operator opens Fleet → Add drone.
2. GCS creates a short-lived enrollment code or QR.
3. On the drone, installer/first-boot agent joins the GCS using that code.
4. GCS records a new permanent node UUID and its capabilities.
5. Operator assigns logical vehicle/hardware ID, mission position, role, and
   approved runtime profile.
6. Drone receives its certificate/credential.
7. Drone pulls the selected software release and fleet revision.
8. Drone verifies, applies, restarts if necessary, and reports:
   release X, fleet revision Y, ready/not ready, exact reason.
```

The important identities are deliberately separate:

- **node UUID:** this physical computer/install; changes when hardware is replaced;
- **vehicle/hardware ID:** the logical aircraft identity used by MDS;
- **mission position (`pos_id`):** the role/trajectory slot for a particular mission;
- **MAVLink system ID:** explicit protocol identity, not inferred from an IP;
- **IP address:** observed/current network location, not identity.

## Scenario 3: remove, disable, or replace a drone

### Temporarily disable

Mark the node disabled/quarantined. It remains in history but is excluded from
commands and deployments.

### Permanently remove

Revoke its credential, remove its active assignment, archive its history, and
optionally issue a local wipe procedure. Removing a fleet record must not erase
historical flight/audit evidence.

### Replace broken hardware

Enroll the replacement as a **new node UUID**. Dashboard then transfers the
logical vehicle/role/mission assignment from old node to new node after
validation. The old node remains revoked in history. This avoids pretending two
physical computers are the same device.

## Scenario 4: developers change the MDS code

Development still uses Git normally:

```text
feature branch → tests/review → CI build → development release digest
```

A developer GCS can select that development release and deploy it to selected
SITL instances or a lab drone. The source checkout can remain editable on the
developer laptop, but the target drones receive a built artifact, not Git
credentials.

After validation:

```text
development → staging → stable
```

Promotion changes the approved release reference; it does not rebuild different
bits under the same version.

For rapid debugging, a future command such as `mdsctl dev deploy --targets lab`
can package the current commit and send it through the same verification and
operation path. Real production drones must never auto-update merely because
someone pushed `main`.

## Scenario 5: update software on one or many drones

The Dashboard shows:

```text
Desired release: 6.0.2
Applied:
  Drone 1  6.0.2  Healthy
  Drone 2  6.0.1  Pending
  Drone 3  6.0.2  Healthy
  Drone 4  offline  Last known 6.0.1
```

The operator chooses a rollout policy:

```text
Canary: 2 drones
Wave 2: 10%
Wave 3: 25%
Wave 4: remaining healthy/idle drones
Stop automatically if failures exceed the approved threshold.
```

Nodes add random jitter, download only missing digests, cache the last good
version, and report durable per-node status. Offline drones stay pending.
Armed/airborne drones are skipped until safe. Failed nodes roll back.

This staged/pull model is the normal large-fleet pattern: Eclipse hawkBit
documents polling with ETags, resumable downloads, target groups, cascading
rollouts, and error thresholds; AWS IoT Jobs similarly documents bounded rollout
rates, retries, and automatic abort criteria.

## Scenario 6: change fleet configuration

An operator edits roles, positions, endpoints, or a runtime profile in Dashboard.
The old revision is never silently overwritten.

```text
Draft revision 42
  Drone 7: role FOLLOWER → RELAY
  Drone 7: mission slot 7 → 12
Validate
  IDs unique: yes
  MAVLink IDs unique: yes
  route/capability compatible: yes
Approve and publish
Deploy to selected nodes
Verify applied hash
```

Fleet-wide defaults are stored once. Only genuine hardware exceptions belong to
a node-local profile. Secrets are referenced, not included in the revision.

Rollback means selecting revision 41 again—not manually reconstructing its JSON.

## Scenario 7: create or change a mission/show

```text
1. Upload CSV/JSON/Skybrush input, or create a mission in Dashboard.
2. GCS stores the raw source as an immutable artifact.
3. The compiler creates trajectories and metadata.
4. Validators check vehicle count, slot mapping, origin, frame, altitude,
   timing, limits, and hashes.
5. Operator previews plots and warnings.
6. Operator approves Mission revision M17.
7. GCS stages only each drone’s required blobs.
8. Drones verify and report M17 ready.
9. A separate guarded command activates/starts M17.
```

Changing a mission creates M18. M17 remains reproducible. An active mission is
frozen while drones are armed. Live flight changes are explicit bounded commands
(Hold, RTL, Land, an approved formation control command), not file edits.

## Scenario 8: import, export, backup, and migration

Use one portable `.mdsbundle` format for online, LAN, and USB workflows:

```text
manifest.json
fleet.json
runtime-profile.json
missions/<mission>/<revision>/...
blobs/sha256/...
signatures/provenance
secret references only
```

### Export

Dashboard → Workspace → Export:

- choose fleet/config only, selected missions, or full deployment;
- include original source commit/release and all hashes;
- exclude passwords, tokens, private keys, telemetry cache, and temporary logs;
- optionally encrypt the bundle for transfer.

### Import

Dashboard verifies schema, hashes, signatures, compatibility, duplicate IDs,
and missing artifacts. It shows a preview before creating a new local revision.
An import never silently replaces the active fleet or mission.

### Migrate the current private customer deployment

1. Export current `config*.json`, `swarm*.json`, mission files, origin, runtime
   settings, and exact private commit as a migration snapshot.
2. Scan and remove/rotate committed secrets.
3. Import data into the new Workspace.
4. Use the official release where code is identical.
5. Build a signed customer custom release only for the reviewed code overlay.
6. Migrate one SITL instance, then one real node, then fleet waves.
7. Keep the current v5 checkout/image as rollback until acceptance.

## What users can change from Dashboard

| Dashboard area | Beginner actions | Advanced actions |
|---|---|---|
| Workspace | create/import/export/backup | schema and provenance details |
| Fleet | add, disable, replace, assign role/slot | capabilities, endpoints, node-local exception |
| Releases | see current/update, choose targets | channels, digest, staged policy, rollback |
| Missions | upload/create, validate, preview, approve | compiler version, frames, artifact manifest |
| Operations | progress, retry, continue, cancel pending, rollback | thresholds, concurrency, maintenance window |
| Logs/History | clear result and reason | event IDs, signatures, traces, retention/export |
| Security | trusted-lab warning | enrollment, certificates, roles, rotation/revocation |

Every change follows the same mental model:

```text
Draft → Validate → Review → Approve → Deploy → Verify
```

## Can this scale from one drone to thousands?

### Honest answer about current MDS

Not yet. Current code includes a GCS loop that polls drones one by one for
telemetry, one-second polling defaults, an alternative thread-per-drone path,
and fixed command/preflight pools of 10–20 workers. That is reasonable for a
small laboratory fleet but has not been demonstrated for thousands. A thousand
unreachable nodes with a two-second sequential timeout can make one poll cycle
unacceptably long.

We should not claim thousand-drone readiness until load, network, command
latency, UI, failure, and flight-safety tests prove it.

### How vNext should scale

Separate two workloads:

1. **Management plane:** software, configuration, enrollment, mission packages,
   audit, and rollout. This can scale using node pull, ETags, hashes, caching,
   pagination, target groups, and rollout waves.
2. **Live flight data plane:** telemetry and time-sensitive commands. At large
   scale this needs asynchronous streams/broker or gateway aggregation, bounded
   backpressure, priority, and explicit delivery/acknowledgement semantics—not
   one HTTP poll loop.

Provisional deployment tiers:

| Tier | Shape | Default architecture |
|---|---|---|
| Lab/small | 1–25 | one laptop/VPS, SQLite/WAL, local artifact store, direct HTTPS |
| Fleet | tens to low hundreds | stronger GCS, async telemetry, PostgreSQL option, shared artifact cache, rollout groups |
| Large fleet | hundreds to 1,000+ | PostgreSQL, object/OCI store, message broker or edge gateways, HA/standby, regional/group partitions |

These boundaries are hypotheses to benchmark, not product limits. We should
create a load-test gate at 1, 10, 50, 100, 500, and 1,000 simulated nodes and
publish measured telemetry latency, command acknowledgement, rollout duration,
CPU/memory/network, and failure recovery.

At large scale:

- 1,000 drones do not clone 1,000 repositories;
- the GCS downloads one release digest, with cache/relay support;
- nodes pull asynchronously with jitter and bounded concurrency;
- target selectors create groups by site, role, hardware, health, or release;
- Dashboard shows aggregate status and paginated/virtualized details;
- a rollout is one durable operation with 1,000 per-node states;
- failures pause the next wave automatically;
- mission blobs are deduplicated by hash, while each drone downloads only its
  required trajectory;
- high-rate telemetry is streamed/aggregated separately from configuration.

## Recommended decisions

1. Keep official `main` as the shared product authority.
2. Reconcile the private repo by classification, never wholesale merge/reset.
3. Upstream reviewed generic private fixes.
4. Move customer config/missions/evidence out of the shared source tree into
   deployment/mission bundles.
5. Rotate and purge any secret material committed to the private repository.
6. Stop issuing the same release tag for different trees.
7. Build vNext with a simple small-fleet default and an explicitly tested
   large-fleet architecture—not an unproven “one SQLite laptop controls 1,000”
   promise.
8. Approve the concrete beginner flows in this document before choosing exact
   package formats and implementation slices.

## Sources used for the scaling/update model

- [Eclipse hawkBit](https://hawkbit.eclipse.dev/) documents device polling with
  ETags, resumable artifact downloads, grouping, phased/cascading rollouts,
  thresholds, pause/resume/retry, and per-device action history.
- [AWS IoT Jobs rollout configuration](https://docs.aws.amazon.com/iot/latest/developerguide/jobs-configurations-details.html)
  documents controlled rollout rates, retries, timeouts, and abort criteria.
- [OCI/ORAS artifact concepts](https://oras.land/docs/1.2/concepts/artifact/)
  provide content-addressed storage for images and other artifact types.
- [TUF](https://theupdateframework.io/docs/overview/) and
  [Uptane](https://uptane.org/docs/latest/standard/uptane-standard) provide
  patterns for signed metadata, freshness, vehicle identity, and rollback safety.

## Final recommendation

The private repository is not “completely different.” Most differences are the
customer data and evidence we expected. The real maintenance problem is that
shared fixes, customer customization, generated artifacts, and security policy
were allowed to live on the same long-running branch.

Keep official MDS as the common engine. Move customer fleet/mission state into
portable packages. Upstream generic private improvements. Keep a private source
overlay only for genuine custom code. Then build the release/fleet/mission
automation described above in safe, tested slices.

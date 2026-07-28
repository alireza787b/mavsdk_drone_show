# MDS next major version: architecture consultation

**Date:** 2026-07-28

**Status:** Consultation baseline — generic private improvements are being reconciled separately; vNext migration is not started.

**Scope:** Official MDS, a private customer clone, existing real nodes, SITL images, installation, operator UX, and Simurgh’s agent/runtime context.

This document is a decision aid for the next major version. It records the repository evidence, independent architecture/security/UX reviews, the recommended direction, migration consequences, and the questions that need approval before implementation.

## Executive recommendation

Do not replace Git with one large database, and do not keep Git as a disguised runtime database. Split the system into explicit planes with one source of truth per domain:

1. **Source plane:** Git remains the source of code, docs, tests, build recipes, and review history.
2. **Release plane:** CI produces immutable, signed software artifacts and release metadata. SITL uses an OCI image digest; real nodes use a signed application bundle with an atomic A/B switch and rollback.
3. **Deployment plane:** GCS owns typed, revisioned fleet desired state in a local SQLite/WAL store first, with a storage interface for a future PostgreSQL deployment.
4. **Mission plane:** shows, trajectories, raw inputs, processed outputs, and parameters are immutable, content-addressed mission packages with explicit lifecycle and provenance.
5. **Identity/secrets plane:** stable node identity, certificates, and local hardware facts are separate from desired state; secrets are references or host-local files, never Git or mission payload.
6. **Observed/control plane:** applied revisions, health, telemetry, durable operations, and guarded commands are recorded independently of desired state.

Nodes and SITL instances pull a signed, scoped deployment package from GCS (with offline export/import as a fallback), cache the last known-good state, and report the applied digest. Runtime startup must not clone, reset, clean, or push a Git repository. Git remains an optional import/export adapter during migration and for advanced development workflows.

This preserves Git’s auditability and portability while removing its token distribution, conflict, boot-time network, and “commit every dirty file” failure modes.

## What the repository says today

The current branch was clean when reviewed:

| Item | Evidence |
|---|---|
| Official checkout | `main`, `5384b293`, tag `v5.5.114-simurgh-routing-resilience` |
| Repository scale | about 4,650 commits and 41,639 objects; `.git` is roughly 0.5 GB |
| Mission/generated data | `shapes/` and `shapes_sitl/` contain tracked raw/processed CSV, plots, and metrics; many files are multi-megabyte |
| Private clone | Customer-specific clone reviewed out of band; its checkout and history are materially larger than the official tree and contain deployment data that must not be upstreamed wholesale |
| Current Git runtime sync | `tools/update_repo_ssh.sh` (2,142 lines), `multiple_sitl/startup_sitl.sh` (1,581 lines), and `multiple_sitl/create_dockers.sh` (816 lines) fetch/reset/clean and reconcile services |
| GCS write path | `gcs-server/utils.py::git_operations()` stages `git add --all`, commits all dirty files, rebases, and has automatic reset/retry behavior |
| Persistence | Simurgh action runs and QuickScout use SQLite under ignored `runtime_data`; much telemetry, heartbeat, Git status, SITL operation, and job state remains in memory |
| Configuration | `config.json`, `config_sitl.json`, `swarm*.json`, `deployment/defaults.env`, `src/params.py`, and the environment registry overlap; identity, endpoint, slot, serial, and runtime defaults are not fully separated |
| Current SITL default | `MDS_SITL_GIT_SYNC=true`; arbitrary container IP/ID options can diverge from `config_sitl.json` |

The current three-state documentation (fleet desired Git, host runtime environment, local secrets) is a useful seam, but Git is still both the desired-state store and the transport. The next version should evolve that model rather than discard it.

### Material security and reliability findings

- SITL startup constructs tokenized HTTPS URLs and writes them into `.git/config` (`multiple_sitl/startup_sitl.sh:748-758, 917-938`). Image preparation also clones with a token and does not clearly sanitize the remote (`tools/sitl_image_prepare.sh:148-183`). A token can therefore persist in a container/image layer or an error path.
- `create_dockers.sh` forwards almost every `MDS_*` environment variable. A future secret name can leak into disposable containers without a code change.
- `git_operations()` has no transaction/parent revision/ETag boundary or process-level serialization. An API save can write local JSON, then fail during Git push, leaving a state that has no durable deployment identity.
- `functions/file_utils.save_json` truncates and writes directly; a crash can leave a partial JSON file.
- `config.json` combines physical identity, mission position, network endpoint, and serial hardware facts. `hw_id`, `pos_id`, and MAVLink system identity need explicit relationships, not incidental conventions.
- The private clone contains customer-specific connectivity material in tracked history. It must be treated as a credential exposure and migrated with secret scanning and rotation; do not merge or overwrite the clone blindly.
- SITL/release tooling favors mutable `latest`, embeds Git metadata, and flattens images. A checksum proves integrity of a downloaded file, not authenticity or rollback safety.

These are boundary problems, not isolated bugs. Patch-by-patch fixes would leave the same coupling in place.

## Current and target models

### Current flow

```text
Git repository
  ├─ code/scripts/services
  ├─ config/params/environment
  ├─ fleet/swarm/origin files
  └─ mission/show/trajectory/generated files
        │
        ├─ GCS checkout: auto-commit/push + runtime reads
        ├─ real nodes: boot/update_repo_ssh.sh + service reconciliation
        └─ SITL: startup/create_dockers Git fetch/reset per instance
```

The same mutable checkout is simultaneously a release, database, transport queue, and operator workspace.

### Proposed flow

```text
Git (source, review, provenance)
        │ CI
        ├─ signed ReleaseManifest + software artifacts (OCI/tar, SBOM, provenance)
        └─ signed base SITL image (digest)

GCS Workspace / Deployment store (SQLite WAL first)
  ├─ fleet desired revisions
  ├─ runtime release references
  ├─ mission package revisions
  ├─ identity/capability inventory
  └─ durable operations/events
        │ authenticated, resumable, idempotent reconciliation
        ├─ real node: local cache + A/B runtime + applied-state ACK
        └─ SITL: digest image + injected deployment/mission package
```

There is no universal single source of truth. There is a single authoritative owner for each domain, linked by immutable revision IDs and hashes, and exportable as one signed deployment bundle.

## Domain ownership and proposed contracts

| Domain | Authoritative owner | Required properties |
|---|---|---|
| Code/docs/tests/build | Git + CI | reviewable commits, release provenance |
| Software runtime | signed `ReleaseManifest` | digest, platform, source commit, schema/API compatibility, SBOM, signature, rollback metadata |
| Fleet topology | GCS desired-state store | node references, role, mission slot, intended endpoint/routing; optimistic concurrency |
| Node identity | node-local identity + GCS enrollment | stable UUID, `hw_id`, MAV system ID, certificate/public key, capabilities; observed IP is not identity |
| Runtime profile | GCS revision plus host-local overrides | mode, release/channel, GCS endpoint, safety/logging policy; no secrets in the revision |
| Mission/show | immutable `MissionRevision` | raw/processed/compiled references, origin/frame/altitude policy, slot mapping, validator/compiler version, lifecycle |
| Large files | content-addressed artifact store | digest, size, media type, signature/referrers, source/derived/cache classification |
| Applied/observed state | node report + GCS event store | applied hashes, health, last-seen, errors, monotonic operation status |
| Commands | guarded control-plane operation | typed command, target snapshot, approval, idempotency key, lease/flight gate, result |
| Secrets | host secret store/certificate paths | references only in exported state; never repository URLs with tokens, logs, or mission bundles |

Suggested minimum fields:

- `NodeIdentity`: `node_uuid`, stable `hw_id`, `mav_sys_id`, certificate/public key, capabilities, hardware class, enrollment/revocation state.
- `FleetDesiredRevision`: `fleet_id`, revision UUID, parent revision, schema version, canonical payload hash, author, created time, lifecycle status, signature.
- `ReleaseManifest`: release ID, artifact digests, architecture/platform, source commit, API/schema compatibility, PX4/MAVSDK compatibility, SBOM/provenance references, signature and expiry.
- `MissionRevision`: mission ID/revision, type, target fleet, origin/frame/altitude policy, artifact references, validator/compiler version, draft/validated/approved/staged/active/completed/archived status.
- `Operation`: durable operation ID, idempotency key, target set snapshot, plan hash, per-node state, retry/rollback history, event and trace IDs.

Canonical serialization, deterministic hashing, schema versioning, signatures, key rotation/revocation, and atomic persistence are requirements—not later polish.

## Runtime and synchronization behavior

### Release/software updates

Git source is built once by CI. Nodes do not receive source credentials or run `git pull`. A release contains:

- a versioned artifact addressable by immutable digest;
- source commit and build provenance;
- compatibility constraints;
- SBOM and vulnerability/signature attestations;
- an A/B or equivalent atomic installation plan;
- the previous compatible release for N-1 rollback.

SITL should use a digest-pinned OCI image with `MDS_SITL_GIT_SYNC=false` by default. Mutable Git sync remains an explicit, clearly labeled development/legacy profile. `latest` may exist as a development alias, never as a production reference.

### Desired-state reconciliation

GCS publishes a signed deployment revision. A node:

1. authenticates and asks for a scoped revision;
2. verifies signature, schema, target identity, expiry, and rollback policy;
3. downloads missing artifacts by digest, resumably;
4. stages them without changing the active state;
5. checks idle/flight/capability preconditions;
6. atomically activates and reports applied hashes;
7. rolls back to the last known-good state on failed health checks.

The node must continue using its last accepted state when GCS or the network is unavailable. It must report stale/offline status rather than silently inventing a new state. No mission file replacement or software switch is allowed while a vehicle is airborne; in-flight changes are only explicit, bounded, audited commands.

Concurrent edits use parent-revision/`If-Match` semantics. A conflict is visible and recoverable; there is no implicit “stage all dirty files and rebase”.

### Mission and artifact handling

Raw show input, processed trajectories, compiled mission, plots, and metrics are separate artifact classes. Generated outputs are cache/derived data, not accidental source files. A mission package is immutable after approval; a new edit creates a new revision. Binary trajectory conflicts are resolved by package revision/selection, never by text merge.

The same package format must support GCS storage, LAN transfer, USB/file export, backup/restore, and SITL injection. A package includes origin, frame, altitude convention, slot mapping, compiler version, safety checks, and hashes so an operator can answer “what exactly flew?”.

## Security posture

### Beginner/lab profile

`mds init` should ask only for mode (SITL or real), official release/image, and local fleet/mission import. It creates a local workspace and trusted-network configuration. It should not require Git forks, branch names, deploy keys, or tokens. The UI must warn that this profile assumes an isolated/trusted network.

### Hardened profile

Enable authenticated control-plane access, per-node enrollment, mTLS or scoped short-lived tokens, signed releases/packages, key rotation/revocation, encrypted backups, audit retention, least-privilege service accounts, and explicit operator approval. GitHub/GitLab access, if needed for source import, uses a fine-grained application/token at the GCS/CI boundary—not on drones or disposable SITL containers.

Immediate security work before any V6 rollout:

1. remove/sanitize tokenized Git remotes from image preparation and startup logs/layers;
2. replace wildcard `MDS_*` container forwarding with an allowlist and explicit secret mounts;
3. scan the private repository/history for connectivity credentials and rotate exposed material;
4. replace broad Git/tmp sudo rules with fixed helper commands;
5. add atomic JSON writes and a concurrency lock/parent check at the current boundary while the migration is built.

## Operator UX and Simurgh

The operator mental model should be one **Workspace/Deployment**, not separate overlapping Git/Fleet/Environment/Admin flows. The overview shows:

- selected mode and software release;
- fleet desired revision versus each node’s applied revision;
- active mission package and lifecycle state;
- health, drift, offline, blocked, and unknown statuses;
- durable operations with retry/continue/rollback/export.

All mutating flows use the same verbs:

```text
Draft → Validate → Approve → Publish → Deploy → Verify → Rollback/Archive
```

No-selection sync must never silently target every eligible node. The plan must show an explicit target snapshot and count.

Simurgh’s lost-history incident is direct evidence that agent context must be durable. The next runtime should store typed turns, tool calls, approvals, operation IDs, checkpoints, and evidence references in the durable event store, with restart recovery and signed/exportable checkpoints. Browser local storage remains a cache, not the source of truth. Provider/search failure should produce a clear degraded capability and a useful local answer, not a long generic response or a silently changed tool path.

Agent policy, tool contracts, UI labels, and context docs should be generated or validated from one versioned machine-readable policy/schema. Compatibility aliases need an owner, telemetry, and a removal date; they must not grow indefinitely.

## Alternatives considered

| Option | Benefits | Problems | Decision |
|---|---|---|---|
| Keep Git as runtime transport | Familiar, offline, human-editable | credentials on nodes, boot network dependency, conflicts, global dirty commits, large clones, weak transaction semantics | Retain only as legacy/dev/import adapter |
| Git + LFS | Better large-file handling | Does not solve runtime auth, desired-state transactions, rollout, identity, or in-flight safety | Useful for source assets during transition, not the architecture |
| Database/API only | Clean revisions and concurrency | Poor artifact distribution/portability if binaries and release software are mixed into one DB | Use typed GCS store for desired state, not one monolith |
| OCI/ORAS only | Content addressing, portable artifacts, referrers for signatures/SBOM | Not a fleet transaction/control plane or operator workflow | Use for releases and mission artifacts |
| Full OSTree/RAUC/Uptane immediately | Strong update and rollback properties | Significant embedded-device/PKI/bootloader scope before MDS needs it | Adopt concepts incrementally; evaluate full adoption later |
| Recommended hybrid | Clear ownership, offline bundles, signed immutable releases, simple lab path, scalable rollout | Requires migration adapters and new contracts | Adopt for the next major version |

OCI artifacts are suitable for arbitrary content and digest-addressed distribution; signatures/SBOMs can be attached as referrers. Cosign can verify signatures against the digest. TUF/Uptane concepts are relevant for expiry, anti-rollback, role separation, and offline/recovery safety; they should be adapted rather than copied wholesale in phase one. RAUC/OSTree are candidates if MDS later owns full embedded OS updates.

## Migration of official, private, forked, and existing deployments

| Current case | V6 path |
|---|---|
| Official repo, config/mission customization only | Install the official signed release/image; import a deployment/mission bundle. No customer fork required. |
| Private customer clone | Preserve the clone and its provenance. Export/import its fleet and mission data. Keep private source only for genuine code/UI/custom integration; build a signed custom release. Do not merge or overwrite the direct tree drift blindly. |
| Public/private code fork | Continue source development in the fork, but production nodes consume a signed artifact digest and compatible V6 API/schema, not fork Git credentials. Prefer upstream/plugin boundaries over permanent full-tree divergence. |
| Existing real drones with Git checkout | Back up identity/config/current commit; install a bridge agent side-by-side; dual-report old and new state; canary one node; stage signed release/package; health-check and atomically switch; retain v5 rollback until fleet acceptance; remove Git credentials only after confirmation. |
| Existing SITL image | Keep as a v5 rollback/legacy image. New official images are digest-pinned and Git-sync-disabled by default. No image rebuild is required for this consultation. |
| Offline or disconnected site | Export/import the same signed deployment bundle over file/USB/LAN. Nodes continue last-known-good and expose staleness. |

Migration must preserve `hw_id` and mission `pos_id` semantics while introducing stable node UUID and explicit MAVLink system identity. Observed IPs must not be treated as identity. Existing trajectory/origin data should be imported with hashes and original commit/image provenance.

## 0–100 implementation blueprint (after approval)

Percentages are sequencing guidance, not estimates of calendar time.

### 0–10: freeze, inventory, and threat model

- Freeze the v5 compatibility contract and capture official/private commits, image digests, configs, mission hashes, and node inventories.
- Define the V6 schemas, revision/status enums, identity relationships, and bundle format.
- Add secret scanning, token-removal tests, atomic-file/concurrency tests, and an explicit legacy/deprecation register.
- Decide the first supported deployment topology (single GCS/SQLite/WAL).

**Gate:** schemas and safety/security invariants reviewed; no runtime behavior change required.

### 10–25: durable control-plane foundation

- Introduce repository interfaces (`FleetStateRepository`, `MissionRepository`, `ArtifactStore`, `ReleaseManager`, `OperationStore`).
- Implement SQLite/WAL migrations, backups, restore, canonical serialization, hashes, parent revisions, and audit events.
- Add read-only adapters/views for current JSON/config paths and a deterministic import/export tool.

**Gate:** restart/power-loss, conflict, export/import, and legacy parity tests pass.

### 25–40: signed release and artifact pipeline

- Build immutable GCS/node/SITL artifacts with source provenance, SBOM, signatures, and compatibility metadata.
- Add digest verification, expiry/anti-rollback policy, key rotation/revocation design, and an OCI/file transport.
- Make SITL Git sync opt-in legacy; keep current images untouched until a validated replacement exists.

**Gate:** artifact tamper, wrong-platform, expired/rollback, and offline-cache tests pass.

### 40–60: node agent and reconciliation

- Add enrollment, identity/certificate handling, scoped pull, resumable content-addressed download, local cache, A/B activation, health-gated rollback, and applied-state ACK.
- Ship a v5 bridge with dual reporting and an explicit rollback switch.
- Ensure airborne/mission gates prevent unsafe replacement.

**Gate:** one SITL and one hardware node complete bridge → stage → activate → rollback scenarios.

### 60–75: mission packages and operator workflow

- Move raw/processed/compiled mission artifacts behind the package manifest and lifecycle.
- Implement Workspace/Deployment overview, explicit target snapshots, durable operations, retry/continue, and drift states.
- Add signed bundle backup/restore and offline import/export.

**Gate:** beginner flow has no Git/token decisions; mission immutability and concurrent-edit tests pass.

### 75–85: Simurgh and agent harness durability

- Persist sessions, tool calls, approvals, evidence references, checkpoints, and operation links.
- Version and validate agent policy/tool contracts/context; provide capability-aware fallback and concise operator errors.
- Add restart, provider-outage, ambiguous-intent, and action-recovery evaluations.

**Gate:** a killed/restarted GCS resumes the operation and restores the checkpoint without inventing state.

### 85–95: canary migration and private-client support

- Migrate official SITL, then one real node, then a small fleet in waves.
- Import private-client data and build a signed custom release only where code differs.
- Telemetry must prove zero unintended Git runtime sync before removal.

**Gate:** fleet canary, partial rollout, network loss, rollback, and backup recovery accepted.

### 95–100: retirement and major release

- Mark Git runtime sync, URL/token runtime flags, duplicate config paths, and compatibility aliases deprecated with measured usage.
- Remove old scripts/docs/tests only after the deprecation window and migration evidence.
- Publish the V6 migration guide, support matrix, release provenance, security posture, and rollback procedure.

## Acceptance scenarios and edge cases

The release is not ready until these are tested:

- clean Ubuntu beginner install for SITL and real mode without a repo fork or Git token;
- GCS restart and power loss with durable operations/history;
- no network after initial artifact cache;
- offline node keeps last-good state and reports stale, never partial state;
- concurrent edits produce an explicit conflict;
- canary/partial rollout retries idempotently and rolls back;
- artifact corruption, wrong signature, expired metadata, and rollback are rejected;
- mission remains immutable while armed; in-flight command is typed, bounded, and audited;
- custom subnet/container allocation cannot diverge from the fleet manifest;
- export on one host and import on another preserves hashes/provenance;
- legacy Git node and old SITL image can be upgraded and rolled back;
- private source unavailable or token expired does not stop production runtime;
- secrets are absent from images, logs, bundles, and generated reports;
- API/provider/search outage leaves Simurgh with an honest, concise degraded response.

## Decisions requested before implementation

1. Approve the hybrid boundary: Git for source/release input; GCS desired-state store and signed artifact packages for runtime.
2. Approve SQLite/WAL as the first control-plane backend, behind an interface for later PostgreSQL.
3. Approve OCI/ORAS (plus file/USB bundle fallback) for release and mission artifacts.
4. Approve digest-pinned signed releases and `MDS_SITL_GIT_SYNC=false` for the new official image; retain Git sync only as an explicit legacy/dev mode.
5. Approve a bridge/canary migration rather than a big-bang rewrite.
6. Decide whether V6 should initially support only one GCS per deployment or require multi-GCS active/standby.
7. Decide the initial hardened identity choice (mTLS certificates, scoped JWT, or both) and key ownership/rotation policy.
8. Decide the compatibility window for v5 Git nodes/images and the first customer migration target.
9. Confirm that mission edits while airborne are prohibited except through an explicitly designed command protocol.
10. Confirm whether the private customer clone should remain a supported custom-release source or become a data-only migration target.

## Research and standards consulted

- [GitHub repository limits](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits) and [Git LFS](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage): generated/large files should not silently grow a normal Git checkout.
- [GitHub Apps](https://docs.github.com/en/apps/overview) and [installation access tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app): fine-grained, short-lived source access at the CI/GCS boundary.
- [OCI artifact concepts](https://oras.land/docs/1.2/concepts/artifact/), [ORAS](https://oras.land/docs/client_libraries/overview/), and [artifact referrers](https://oras.land/docs/concepts/reftypes/): digest-addressed arbitrary artifacts with attached signatures/SBOMs.
- [Docker image digests](https://docs.docker.com/dhi/explore/security-concepts/digests/) and [Cosign verification](https://docs.sigstore.dev/cosign/verifying/verify/): immutable references and signature verification.
- [TUF overview](https://theupdateframework.io/docs/overview/) and [TUF specification](https://theupdateframework.github.io/specification/latest/): signed metadata, expiry, anti-rollback, and role separation.
- [Uptane standard](https://uptane.org/docs/latest/standard/uptane-standard): vehicle-oriented identity, delegated update policy, preconditions, offline/recovery, and rollback patterns.
- [RAUC](https://rauc.io/) and [OSTree atomic upgrades](https://ostreedev.github.io/ostree/atomic-upgrades/): signed bundles and power-loss-safe atomic updates.

## Bottom line

MDS has proven feasibility, but the current Git-centered runtime is the wrong long-term boundary for a larger, safer, more portable product. The next major version should be a controlled migration to typed desired state, immutable signed artifacts, durable operations, and explicit operator workflows. The official repository remains the source and release origin; private/client repositories remain possible custom source inputs, not mandatory runtime dependencies. No code, image, branch, or customer repository has been changed by this consultation.

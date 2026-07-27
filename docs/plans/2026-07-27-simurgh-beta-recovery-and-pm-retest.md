# Simurgh Operator Beta Recovery And PM Retest Checkpoint

Date opened: 2026-07-27
Status: Active release engineering
Scope: official MDS source, the approved private client mirror, and the
validated SITL/client deployment

This is the durable continuation record for the Simurgh beta work that was
interrupted when the original agent conversation was deleted. Update this
file at every completed slice and before any release, deployment, or cleanup
operation. The repository, Git history, validation artifacts, and this record
are the source of truth; chat history is not.

## Objective

Resume the validated-but-unpublished `5.5.111-simurgh-operator-beta` source,
publish it in the official repository, synchronize only the public-safe delta
into the private client repository, deploy and smoke-test the client version,
and leave a complete PM retest handoff. Defer the refreshed SITL image and MEGA
publication until PM acceptance or until storage is deliberately made
available.

## Recovery boundary

- The deleted leader rollout itself is not available in the normal filesystem.
- A child rollout preserved the parent context through 2026-07-26 19:59 UTC.
- Codex goal state, durable prompts, slice reports, release notes, validation
  databases, logs, and build outputs preserved the remaining project state.
- The recovery audit made no source, service, repository, or deployment
  changes.
- Never delete `/root/.codex`, Codex databases/session evidence, or the
  private validation action journal while reclaiming disk.

## Source provenance at checkpoint creation

| Item | Value |
| --- | --- |
| Official worktree | `release/simurgh-beta` |
| Official `HEAD` | `1964f2c574f1fc272d40cd47d2d42e1add86b9fa` |
| Official upstream branch | `314a280f` |
| Existing immutable tag | `v5.5.110-simurgh-operator-beta` |
| Intended beta tag | `v5.5.111-simurgh-operator-beta` |
| Tracked dirty-diff SHA-256 | `4b530d8c3bfd9bb2853196120ea791ac212c23109dae4cc6fbf15df81884301f` |
| Tracked status-list SHA-256 | `0d46dd4b55dbeaf01d990c070d6cf86bc34761adb5aff530866c0a31f021f947` |
| Untracked-file-content SHA-256 | `2cd6e90530878839fef088cf99d0e6e92973f2b0ce4a6ed7e256c60efa81eb3d` |
| Worktree state | 114 tracked changes, 14 untracked files, nothing staged |

The untracked files are focused Simurgh/ULog implementation and test modules.
Review their contents and add them deliberately; never use a blanket cleanup
command that could erase them.

## Previously completed implementation slices

1. Simurgh foundation, policy, registry, MCP, dashboard, and advisory
   provider.
2. Typed semantic intent, target grounding, durable action/target memory, and
   multilingual/typo-heavy provider interpretation.
3. Typed multi-step SITL/flight plans, waits, conditions, monitoring,
   reconnectable runs, confirmation, cancellation, and final-state evidence.
4. ULog schema, parser isolation, bounded resource/transfer controls,
   actor-bound handles, sanitized summaries, and mission correlation.
5. Trusted-network zero-setup lab/SITL defaults with explicit warnings and
   opt-in hardened auth/network/secret controls.
6. Launcher/auth wording fixes, provider-fallback fixes, generated context,
   documentation, release gates, dashboard tests, and production build.
7. Live Hetzner SITL acceptance: successful create/cleanup, recovery after
   early failures, successful multi-step flight, ULog evidence, follow-up
   context, and provider transformation retests.

## Open release slices

### Slice R0 — Durable checkpoint

- Keep this plan current.
- Preserve the recovery prompt and validation evidence outside transient chat.
- Record each commit, remote ref, test result, deployment, and cleanup action.

### Slice R1 — Official source review

- Review the complete dirty diff against `314a280f`.
- Confirm generated files are reproducible.
- Run public leak/secret scans and verify no customer-only runtime data entered
  the official tree.
- Separate implementation, tests, documentation/generated contracts, and
  intentional deletions into reviewable commits where practical.

### Slice R2 — Official validation

- Run the narrow local syntax, generated-contract, diff, and focused tests.
- Run the full backend/eval/dashboard/build gates on the remote validation host
  because local and Hetzner disks are constrained.
- Preserve the exact command, result, commit/tree identity, and artifact paths.

### Slice R3 — Official publication

- Commit the reviewed `5.5.111` source.
- Push the official beta branch.
- Create the immutable beta tag only after the commit and build provenance are
  verified.
- Do not move the existing `v5.5.110` tag.

### Slice R4 — Private client synchronization

- Treat the official repository as upstream and the private client repository
  as downstream.
- Transfer only the approved public-safe commits/files after privacy review.
- Keep client-only repo URL, branch, host, credentials, mission data, and
  deployment configuration in the private environment.
- Test the downstream checkout before deploying it.

### Slice R5 — Live client deployment

- Verify `/etc/mds/gcs.env`, repo URL, branch, image, sync posture, auth mode,
  and provider settings before restart.
- Deploy from a committed checkout, not from an edited container or dirty
  runtime tree.
- Verify GCS/API/dashboard health, SITL container health, logs, action history,
  ULog evidence, and the final intended acceptance posture.

### Slice R6 — PM retest handoff

- Provide PM the exact client URL/access path, branch/commit, test script,
  expected safety behavior, known limitations, and evidence locations.
- Mark ready only after official and private refs and the live client runtime
  agree.
- Keep the validation SITL container running only if PM needs it; otherwise
  stop it through the documented workflow and record that action.

### Slice R7 — Post-approval image release

- Only after PM acceptance decide whether storage permits a clean image build.
- Build/package/checksum from the immutable validated commit.
- Upload to MEGA and update public links only after the artifact is live.

## Explicitly deferred until after beta acceptance

- Behavior-preserving decomposition of the remaining Simurgh router,
  read-tools aggregation, and dashboard page.
- Removal of the remaining phrase-based fallback routing.
- Additional ULog metric time-series, batch comparison, narrative-review, and
  offline CLI slices.
- Any real-aircraft/commercial hardening decision or second security switch.

## Disk cleanup policy

Disk cleanup is authorized only for verified, unused historical MDS
worktrees, images, build caches, archives, and logs. Before deleting anything:

1. inventory the exact path, owner, size, Git/image identity, and last use;
2. preserve the current validation tree, action journal, release evidence, and
   Codex context;
3. prefer recoverable moves or targeted Docker/image pruning;
4. record what was removed and whether it is recoverable;
5. re-check free space and running services after cleanup.

No cleanup may target the active official worktree, the private production
checkout, the current validation artifacts, `/root/.codex`, or live runtime
data without a separate evidence-preservation step.

## Continuation log

| UTC date/time | Slice | Result | Next action |
| --- | --- | --- | --- |
| 2026-07-27 | Recovery audit | Reconstructed history, goal, source, validation, and release boundary | Create this durable checkpoint |
| 2026-07-27 | Disk cleanup | Removed the verified-unused clean shallow clone at `/opt/px4vision/research/mavsdk_drone_show` (HEAD `6d604cdb`, about 52 MiB) and remote transient MDS test caches (`mds-mplconfig-*`, pytest, Jest; about 219 MiB). Active source, client evidence, validation data, running services, and Codex context were preserved. | Continue official source review and release gating |

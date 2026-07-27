# Simurgh Operator Beta Recovery And PM Retest Checkpoint

Date opened: 2026-07-27
Status: superseded by the Simurgh readiness-routing checkpoint; phase closed
and private PM handoff ready
Scope: official MDS source, the approved private client mirror, and the
validated SITL/client deployment

This is the durable continuation record for the Simurgh beta work that was
interrupted when the original agent conversation was deleted. Update this
file at every completed slice and before any release, deployment, or cleanup
operation. The repository, Git history, validation artifacts, and this record
are the source of truth; chat history is not.

## Objective

The recovery objective is complete. The validated source is published on
official `main`, the private client mirror contains the approved replay, the
private production and validation services are healthy, and PM can run the
final SITL test. The refreshed SITL image and MEGA publication remain
intentionally deferred. For the accepted scope and future restart recipe, use
the [Simurgh feasibility checkpoint](2026-07-27-simurgh-feasibility-checkpoint.md).

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
| Official worktree | `main` |
| Official `HEAD` | `974259ba` |
| Official upstream branch | `origin/main` |
| Existing immutable tag | `v5.5.110-simurgh-operator-beta` |
| Published beta tag | `v5.5.111-simurgh-operator-beta` |
| Published feasibility tag | `v5.5.112-simurgh-feasibility-checkpoint` |
| Tracked dirty-diff SHA-256 | `4b530d8c3bfd9bb2853196120ea791ac212c23109dae4cc6fbf15df81884301f` |
| Tracked status-list SHA-256 | `0d46dd4b55dbeaf01d990c070d6cf86bc34761adb5aff530866c0a31f021f947` |
| Untracked-file-content SHA-256 | `2cd6e90530878839fef088cf99d0e6e92973f2b0ce4a6ed7e256c60efa81eb3d` |
| Worktree state | 114 tracked changes, 14 untracked files, nothing staged |

The untracked files are focused Simurgh/ULog implementation and test modules.
Review their contents and add them deliberately; never use a blanket cleanup
command that could erase them.

## Current release state

| Item | Value |
| --- | --- |
| Official branch | `main` |
| Official tip | docs-only close after runtime release `69f40fae` |
| Official worktree | clean and pushed |
| Private downstream | synchronized through controlled replay, validated, committed, and pushed on private `main` |
| Private deployment | production and isolated validation services healthy in SITL mode |
| Official tags | `v5.5.111-simurgh-operator-beta`, `v5.5.112-simurgh-feasibility-checkpoint`, `v5.5.113-simurgh-readiness-routing` |
| Refreshed MEGA image | intentionally deferred until PM acceptance/storage approval |

The exact private commit, rollback ref, evidence paths, and client deployment
sequence are recorded only in the private downstream checkpoint so public
documentation does not expose customer-specific repository or host details.

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
| 2026-07-27 | R1/R2 local checkpoint | Public-boundary scan, generated-contract checks, env-registry audit, Python compilation, and `git diff --check` passed. The governed runtime/ULog implementation and tests are committed as `d347a9e8`; focused local coverage passed 60/60 in 7.32s. | Commit documentation/CI slice, then run the heavy remote gates |
| 2026-07-27 | R2 Hetzner release gates | Remote CI-equivalent backend gate passed 1,055 tests in 16:08 with 63.12% coverage; Simurgh prompt evals passed 32/32; provider smoke passed. Dashboard gate passed `npm ci`, 130 frontend tests, and `npm run build:release`; all exit codes were zero. | Push the official beta branch, then stage public-safe private-client synchronization |
| 2026-07-27 | R3 official publication | Reviewed beta source and three integration-test hardening fixes were committed and pushed on official `release/simurgh-beta` through `a1c69fb8`. Public-boundary and generated-contract checks remained clean. | Synchronize the private downstream without exposing client-only data |
| 2026-07-27 | R4 private synchronization | A no-commit full-merge preview exposed 121 conflicts and was safely aborted. The bounded official beta commits were replayed onto a recoverable private integration branch, client-only configuration/assets were preserved, generated references were rebuilt, and private `main` was fast-forwarded only after validation. The downstream gate passed 1,054 backend tests (63.21% coverage), 32/32 prompt evals, provider smoke, 117 dashboard suites/638 tests, and the optimized release build. | Restart isolated validation, then production |
| 2026-07-27 | R5 live client deployment | The committed private `main` was pushed and both isolated validation and production services were restarted from that source. Authenticated live smoke verified SITL mode, Simurgh/MCP, confirmation and circuit-breaker posture, 105 registered tools, provider/key readiness, fleet heartbeat visibility, one running SITL instance, and preserved action evidence. Every current dashboard manifest asset returned HTTP 200. One already-open browser requested a pre-deploy lazy chunk; a hard refresh is required once before PM testing. | PM retest using the private handoff checklist |
| 2026-07-27 | Post-deploy disk cleanup | Removed the now-unreferenced historical official release tree, unused validation dashboard source/build caches, private test dependencies/coverage caches, and transient pytest/Jest/matplotlib caches. Remote free space increased from 2.0 GiB to 4.7 GiB. Active source, dashboard build, runtime databases, unified logs, SITL container/image, private evidence, and Codex context were preserved; both APIs and the dashboard remained healthy. | Keep the live client stable for PM retest |
| 2026-07-27 | TAKE_OFF tracking incident | A live 10 m `TAKE_OFF` was accepted by production GCS (`5030`) and executed successfully by `drone-1`, but the container was configured to send heartbeats/execution callbacks to the isolated validation GCS (`5111`). Production therefore had no execution-start/result evidence and the command monitor timed out after 120.6 s. The drone remains armed in SITL; it was not restarted, removed, or issued a corrective flight command. | Keep the vehicle untouched until the operator makes it safe; then reconcile/recreate the fleet from the production GCS and run the read-only endpoint/health checks before PM retest |
| 2026-07-27 | Callback-endpoint guard | Official/private source now exposes each SITL callback target in inventory and blocks new tracked SITL commands with HTTP `409` when a selected running container points at another GCS process. Focused tests passed 40/40; docs and changelog updated. | Commit, sync, deploy the guard, verify inventory on both services, then reconcile the safe fleet |
| 2026-07-27 | Callback guard deployment | Official `ffb922b4` was pushed to `release/simurgh-beta`; private `main` was fast-forwarded through `b8647e3e`. Production GCS was restarted from the committed private checkout. Authenticated read-only inventory returned HTTP 200 and showed `drone-1` callback target `172.18.0.1:5111`, confirming the deployed guard can now diagnose the split. The validation GCS was intentionally left running so the armed SITL vehicle would keep its current callback path. | Do not issue another flight command. After the operator makes the vehicle safe, reconcile/recreate the fleet from production so callback targets use `:5030`, then rerun endpoint and health checks |
| 2026-07-27 | Simurgh feasibility closure | The PM SITL retest completed conditional takeoff, position/NED reads, a 5 m north move, RTL/land, and bounded ULog review. The altitude report exposed an MSL/relative-frame presentation bug and the typed drone-state response was dropping the richer altitude fields. Both layers were fixed with focused tests; current status uses explicit altitude-frame labels and `Flight state`. | Keep Simurgh in demo/proof-of-feasibility scope and defer the remaining backlog |
| 2026-07-27 | Official/private final handoff | Official `main` is clean at `974259ba` with immutable tags `v5.5.111-simurgh-operator-beta` and `v5.5.112-simurgh-feasibility-checkpoint`. The private mirror was replayed and pushed through a private-only commit, production and validation APIs are healthy, and `drone-1` restarted from the private checkout with the altitude fields visible. No SITL image was rebuilt. | PM may run the final private-client test; do not start the next Simurgh feature until a new scoped checkpoint is created |
| 2026-07-27 | Readiness-routing correction and final handoff | Official runtime `69f40fae` is tagged `v5.5.113-simurgh-readiness-routing`; the private runtime replay is `638c03a8f`. Each `main` also contains a later docs-only close, with repository-specific commit IDs. Official serial gates passed 363 broader tests and 152 Simurgh route tests, dashboard evals passed 33/33, and provider smoke passed. Private focused routes passed 7/7 and dashboard evals passed 33/33. Production APIs/dashboard are healthy after restart, the existing SITL container was preserved, and authentication remains enabled. | PM may run the final authenticated private-client test; readiness questions should remain read-only, while explicit actions use guarded confirmation |

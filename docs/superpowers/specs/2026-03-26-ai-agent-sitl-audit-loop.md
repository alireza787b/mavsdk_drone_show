# AI Agent SITL Audit, Debug, and Release Loop

Audience: terminal AI agents only.  
Status: active operating spec.  
Canonical repo entrypoint: `AGENTS.md`

## Purpose

Use this spec when you are iterating on MDS through the real SITL loop:

- reproduce a problem or validate a feature
- inspect logs and code
- patch cleanly
- rerun targeted validation
- rerun live SITL scenarios
- update docs/tests/guides
- decide whether release artifacts must be rebuilt and republished

This is not a human tutorial. It is an execution contract for machine agents.

## Source-of-Truth Order

Resolve conflicts in this order:

1. direct user instruction for the current task
2. `AGENTS.md`
3. this file
4. current repo code
5. current repo docs/guides
6. live logs, runtime evidence, API responses, test results
7. current official upstream docs for tools/platforms that may have changed

Do not treat archived docs, stale chat context, or remembered habits as authoritative.

## Detect Environment First

Before acting, determine:

- repo path
- branch and HEAD commit
- whether the worktree is clean or dirty
- whether the task runs:
  - on the same workstation
  - on a limited VPS
  - on a remote validation host over SSH
- whether the runtime uses:
  - official repo and `main-candidate`
  - custom repo URL
  - custom branch
  - official stock SITL image
  - custom validated image
- whether startup repo sync is enabled:
  - `MDS_SITL_GIT_SYNC=true`
  - `MDS_SITL_GIT_SYNC=false`
- whether requirements sync is enabled:
  - `MDS_SITL_REQUIREMENTS_SYNC=true`
  - `MDS_SITL_REQUIREMENTS_SYNC=false`
- whether the task is:
  - docs-only
  - code-only
  - runtime validation
  - release packaging/distribution

Never assume paths, branches, hostnames, or image tags.

## Read-First Map

Load only the docs needed for the task:

- general repo map: `README.md`, `docs/README.md`, `CHANGELOG.md`
- SITL bootstrap/runtime: `docs/guides/sitl-comprehensive.md`
- custom images and pinned releases: `docs/guides/advanced-sitl.md`, `docs/guides/sitl-custom-release-workflow.md`
- Drone Show: `docs/features/drone-show.md`
- Smart Swarm: `docs/features/smart-swarm.md`
- origin and control behavior: `docs/features/origin-system.md`, `docs/control-modes-and-coordinates.md`
- logging/debugging: `docs/guides/logging-system.md`
- GCS/drone APIs: `docs/apis/gcs-api-server.md`, `docs/apis/drone-api-server.md`

If docs and code disagree, verify the code path and then fix the docs in the same phase.

## Standard Execution Loop

1. Build context
   - inspect repo status, recent commits, and the minimum relevant files
   - identify whether the issue is code, docs, environment, image, data, or operator misunderstanding
2. Reproduce
   - prefer the smallest reproducible path
   - prefer existing validators before manual ad hoc probing
3. Inspect evidence
   - unified logs first
   - then API/runtime state
   - then code
4. Isolate the failing layer
   - dashboard
   - frontend state
   - GCS/API
   - git sync
   - Docker/runtime image
   - PX4/SITL/Gazebo
   - mission logic
   - network/timeout behavior
   - docs/operator flow
5. Patch cleanly
   - preserve existing architecture where sensible
   - prefer shared helpers and named parameters over one-off literals
   - avoid creating parallel sources of truth
6. Validate narrowly
   - run the smallest relevant tests first
   - expand only if needed
7. Validate end to end
   - rerun the real operator/SITL scenario if behavior changed
8. Update docs/tests/tools
   - update the relevant feature guide, setup guide, or validation helper
9. Decide release impact
   - if runtime/image contents changed, rebuild/package/publish
   - if docs-only changed, do not rebuild unless strict provenance alignment is explicitly desired
10. Leave a clean handoff
   - summarize exact commit/tag state
   - summarize what changed and what was validated
   - separate blockers from optional follow-ups

## SITL Runtime Loop

For SITL-backed work:

1. verify prerequisites from docs, not memory
2. bring up or inspect the correct GCS/dashboard path
3. bring up or inspect the correct SITL containers
4. confirm readiness through:
   - health endpoints
   - telemetry/readiness views
   - relevant logs
5. run the feature-specific scenario:
   - Drone Show
   - Smart Swarm
   - QuickScout
   - logging/UI/export flow
6. if the scenario fails:
   - capture exact evidence
   - identify the smallest root cause
   - patch
   - rerun targeted tests
   - rerun the live scenario

## Logs First

Use the unified logging system before speculative changes.

Check the best available evidence surface for the task:

- Log Viewer in the dashboard
- GCS structured logs
- drone structured logs
- startup logs
- tmux panes if the runtime is launched there
- Docker logs only when they add signal not already captured elsewhere

Treat polling chatter separately from operator-relevant events.

## Prompt Contract for Future Agents

When starting a large task, structure the prompt or internal task framing with:

- `Goal`
- `Current environment`
- `Relevant docs/code`
- `Constraints`
- `Validation target`
- `Done when`

If the active agent platform supports templates, workflows, or task schemas, map those fields directly.

## Use New Agent Capabilities

Do not freeze this loop around today’s tooling.

If the current agent platform offers improved capabilities, use them when they increase safety, speed, or reproducibility:

- planning or todo systems
- subagents
- worktrees
- checkpointing or rollback
- trusted-folder or sandbox controls
- official MCP/tool integrations
- official browser/research tools
- scoped memory/context files
- long-context compression/compaction
- non-interactive/headless execution modes

When behavior may have changed since older runs, verify current official docs before assuming old limits still apply.

## Ask the User Only When Needed

Escalate to the user when the decision is truly external or risky:

- destructive cleanup
- credentials or secrets
- licensing/policy/customer decisions
- ambiguous operator semantics with multiple valid outcomes
- real-aircraft safety or regulatory decisions

Otherwise make the best technical decision, document it, and continue.

## Release Decision Boundary

Rebuild and redistribute the SITL image when one of these is true:

- startup scripts changed
- runtime filesystem contents changed
- baked tools or dependencies changed
- packaged mission assets changed
- the public workflow now depends on new runtime/image behavior

Do not rebuild for docs-only clarifications unless exact image-to-commit alignment is itself the release goal.

## Distribution Loop

When a rebuild is required:

1. rebuild cleanly from git, not from ad hoc container state
2. validate the runtime behavior on the rebuilt image
3. export/package/checksum
4. upload or replace distribution artifacts
5. update public docs links only after the new artifact is confirmed
6. tag or otherwise mark the approved handoff point

## Repo Layout Guidance

Keep the canonical repo-wide operating instructions in `AGENTS.md`.

Use thin compatibility shims for tool-specific discovery only:

- `CLAUDE.md`
- `GEMINI.md`

Only add deeper scoped agent instruction files when a subtree genuinely needs local rules, for example:

- `app/dashboard/drone-dashboard/`
- `gcs-server/`
- `multiple_sitl/`
- `src/`

Do not fork the full operating spec into multiple competing files.

## Success Criteria

At the end of a substantial phase, the agent should be able to state:

- exact branch/commit/tag
- exact runtime/image/distribution state
- exact tests and live scenarios run
- whether docs and guides were updated
- whether release artifacts were refreshed
- whether the result is ready for testers, operators, or deployment

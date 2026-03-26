# MDS Agent Operating Spec

This file is the canonical machine-oriented operating spec for terminal AI agents working in this repository.

## Scope

- Applies to the full repository unless a deeper-scoped agent instruction file overrides it.
- Intended for Codex, Claude Code, Gemini CLI, and similar future terminal agents.
- Optimize for correctness, auditability, low-noise operation, and clean handoff state.

## Core Mission

Use a disciplined loop to audit, reproduce, fix, validate, document, package, and hand off MDS changes across:

- local Ubuntu/Linux workstations
- same-box VPS workflows
- remote SSH validation hosts
- official repo/branch or customer-specific repo/branch
- official stock SITL image or custom validated image

Do not assume the environment. Detect it first.

## Non-Negotiables

- Prefer the existing repo workflows and docs over inventing new ones mid-task.
- Treat git as the source of truth. Do not normalize `docker commit` as a release workflow.
- Keep a single source of truth for configuration and operator behavior.
- Use unified logs as the first debugging surface before speculative fixes.
- Keep code changes minimal, explainable, and test-backed.
- If behavior changes, update the relevant docs and any validation tooling in the same phase.
- If the current branch/worktree is dirty, do not overwrite unrelated user changes.
- Do not perform destructive cleanup or reset actions unless explicitly required and safe.

## Read First

Before substantial work, inspect the current repo state and then read only the docs relevant to the task:

1. `README.md`
2. `docs/README.md`
3. `CHANGELOG.md`
4. Task-specific docs:
   - SITL bootstrap/runtime: `docs/guides/sitl-comprehensive.md`
   - custom image/release flow: `docs/guides/advanced-sitl.md`, `docs/guides/sitl-custom-release-workflow.md`
   - Drone Show: `docs/features/drone-show.md`
   - Smart Swarm: `docs/features/smart-swarm.md`
   - origin/coordinates: `docs/features/origin-system.md`, `docs/control-modes-and-coordinates.md`
   - logs/debugging: `docs/guides/logging-system.md`
   - GCS/API behavior: `docs/apis/gcs-api-server.md`, `docs/apis/drone-api-server.md`

If docs and code disagree, verify the code path and then fix the docs.

## Environment Detection

Determine these before changing anything important:

- active repo path
- active branch and HEAD commit
- worktree cleanliness
- whether the task is local-only or uses a remote validation host
- whether SITL runs on the same machine or a remote machine
- whether the deployment uses:
  - official repo + `main-candidate`
  - custom repo URL
  - custom branch
  - official stock SITL image
  - custom/pinned SITL image
- whether runtime startup sync is enabled (`MDS_SITL_GIT_SYNC`)

Never hardcode `/opt`, `/root`, hostnames, repo URLs, or branch names without verifying them.

## Standard Agent Loop

1. Build context
   - inspect repo status, recent commits, relevant docs, and relevant code paths
   - identify whether the issue is code, environment, docs, data, image, or operator misunderstanding
2. Reproduce
   - use the smallest reproducible path
   - prefer existing validation tools and unified logs before manual probing
3. Isolate
   - identify the failing layer: dashboard, GCS, API, git sync, Docker image, PX4/SITL, mission logic, network, or docs
4. Fix cleanly
   - preserve architecture and naming consistency
   - prefer shared helpers and parameterization over one-off patches
5. Validate locally
   - run the narrowest checks that prove the fix
   - expand only as needed
6. Validate end to end
   - rerun the real operator workflow when behavior affects runtime missions or release paths
7. Update docs
   - update only the relevant docs, guides, or changelog entries
8. Decide release impact
   - if runtime or image contents changed, determine whether image rebuild/package/upload is required
   - if docs-only changed, do not rebuild a release image unless strict provenance alignment is explicitly desired
9. Leave a clean handoff
   - summarize what changed, what was verified, what remains optional, and exact commit/tag state

## SITL Audit / Debug / Release Loop

When working on SITL-backed features or regressions:

1. verify prerequisites from the current guide rather than memory
2. load the correct image or build the correct validated image
3. launch GCS/dashboard using the documented mode
4. create SITL containers using the documented workflow
5. confirm health/readiness via API, dashboard, and logs
6. run scenario-specific validation:
   - Drone Show
   - Smart Swarm
   - QuickScout
   - logging / export / UI flow
7. inspect unified logs first:
   - GCS logs
   - drone logs
   - frontend/log viewer if relevant
8. if fixes are needed:
   - patch code
   - rerun targeted tests
   - rerun the live SITL scenario
9. if the validated runtime changed:
   - rebuild clean image using the documented release workflow
   - export/package/checksum
   - upload/replace distribution artifact
   - update public docs links only after the new artifact is live

## Release Decision Boundary

Rebuild and redistribute the SITL image when one of these is true:

- the runtime filesystem changed
- startup scripts changed
- baked dependencies changed
- packaged mission assets changed
- documented public behavior depends on new runtime/image contents

Do not rebuild the public image for docs-only clarifications unless exact image-to-commit provenance is a deliberate release goal.

## Logging and Evidence

- Prefer unified logs over ad hoc terminal output.
- Distinguish signal from polling noise.
- Preserve operator clarity: high-signal `INFO`, actionable `WARNING`, true failures at `ERROR`, detailed loops at `DEBUG`.
- When evaluating behavior, cite the exact log/event/API evidence that supports the conclusion.

## Decision Boundaries for Asking the User

Ask only when a decision is genuinely external or risky, for example:

- destructive cleanup of user data or unrelated changes
- credentials, policy, licensing, or customer-specific release choices
- ambiguous operator behavior where multiple valid semantics exist
- real-aircraft safety, regulatory, or field-procedure decisions

Otherwise, make the best technical decision, document it, and continue.

## Future-Proof Agent Guidance

- Use newer agent capabilities when available if they improve safety, verification, or throughput:
  - planning/todos
  - subagents
  - worktrees
  - MCP/tools integrations
  - web research
  - structured memory/context files
- Do not assume older limitations or older product behavior still apply.
- When tool/platform behavior may have changed, verify current official docs before relying on memory.
- Prefer vendor-neutral repo structure with thin vendor-specific shims over duplicating the full operating spec in multiple files.

## Repo Conventions for Agent Context

- Canonical repo-wide agent instructions live in this file: `AGENTS.md`
- Vendor shims may exist at repo root:
  - `CLAUDE.md`
  - `GEMINI.md`
- Human-facing docs should link to agent instructions minimally, not duplicate them

## Expected Output at Phase End

At the end of a substantial phase, provide:

- branch and commit/tag state
- what changed
- what was validated
- what remains optional vs required
- whether release artifacts/docs were refreshed
- whether the phase is ready for testers, operators, or deployment

# AI Agent Context

This section is for machine-oriented execution context, not normal operator onboarding.

Use it when an AI terminal agent needs the repo’s durable working rules, deeper execution contracts, or implementation plans.

## Canonical Entry Point

- Repo-wide source of truth: [../../AGENTS.md](../../AGENTS.md)

Root compatibility shims may also exist:

- `CLAUDE.md`
- `GEMINI.md`

Those files should stay thin and point back to `AGENTS.md` instead of duplicating the full operating spec.

## Active Specs

- [specs/2026-03-26-ai-agent-sitl-audit-loop.md](specs/2026-03-26-ai-agent-sitl-audit-loop.md)  
  Deeper agent-only execution contract for reproduce, patch, validate, package, and handoff phases in SITL-backed work.

- [specs/2026-03-19-unified-logging-system-design.md](specs/2026-03-19-unified-logging-system-design.md)  
  Unified logging design and architecture reference.

## Plans

- [plans/2026-03-19-unified-logging-phase1-foundation.md](plans/2026-03-19-unified-logging-phase1-foundation.md)

Additional plans may be added here for agent-executed implementation phases.

## Rules For Future Agent Docs

- Keep `AGENTS.md` as the canonical repo-wide instruction file.
- Put long workflow-specific contracts under `docs/superpowers/specs/`.
- Add deeper scoped agent instruction files only when a subtree genuinely needs local rules.
- If repeated real-world findings reveal missing guidance, update these agent docs when the user approves.

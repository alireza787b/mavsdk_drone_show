# API Modernization Phase 1 Checkpoint

Date: 2026-04-03
Branch baseline: `fa567df0` before this slice
Scope: survey, blueprint, first canonical alias routes

## Completed In This Phase

- confirmed current recovery repo and checkpoint status
- surveyed GCS FastAPI routes, drone FastAPI routes, and major route consumers
- identified mixed-generation API structure and the highest-risk duplication points
- published the API modernization blueprint at `docs/apis/api-modernization-blueprint.md`
- captured the detailed route and migration survey at `docs/plans/2026-04-03-api-contract-audit-phase-1.md`
- introduced the first canonical `/api/v1/...` routes for low-risk core surfaces on both GCS and drone services
- preserved legacy route compatibility
- added test coverage for the new canonical alias routes

## Highest-Risk Findings

- legacy `/get-*` and `/save-*` routes still dominate the active frontend
- canonical `/api/...` usage exists but is concentrated in only a few newer subsystems
- route consumers are spread across pages, hooks, utilities, runtime tools, and drone callbacks
- some consumers are stale and should not drive future compatibility decisions
- the monolithic GCS app and drone API server still mix route handling with orchestration and side effects

## Why Phase 1 Starts With Aliases

Renaming routes first would create avoidable regressions. The safe order is:

1. define the canonical target
2. keep compatibility routes working
3. migrate callers in slices
4. remove legacy routes only after validation

## Planned Next Slices

1. centralize frontend API callers behind typed service modules
2. classify stale route consumers and dead code explicitly
3. extract route domains out of the monolithic GCS and drone API files
4. migrate configuration, origin, swarm, git, and show-management domains onto canonical v1 routes
5. define event-stream contracts for future MCP and LLM tooling

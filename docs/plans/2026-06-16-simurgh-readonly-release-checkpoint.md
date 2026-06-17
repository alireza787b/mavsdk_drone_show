# Simurgh Read-Only Release Checkpoint - 2026-06-16

Status: validation checkpoint after reviewer-blocker fixes. This note is a
handoff snapshot for continuing release, official/client sync, and PM/funder
demo preparation.

## Scope Completed

- Simurgh provider streaming now uses real OpenAI Responses streaming deltas
  when an external provider is active; local deterministic answers no longer
  fake assistant text deltas.
- Dashboard Markdown rendering uses `markdown-it` with raw HTML disabled and
  dashboard/docs/HTTPS links gated through the safe-link component.
- Unsafe Markdown links render as inert text, including URL-looking labels on
  rejected hrefs.
- Stream failure handling preserves HTTP status and plain-text SSE error
  details for stale-session recovery.
- Chat transcript keeps live-region behavior quieter with
  `aria-relevant="additions"` instead of announcing every streamed text update.
- Stale backend-session recovery retries once with bounded, safe routing
  metadata from previous assistant trace instead of losing all context.
- MCP status resource now exposes canonical `gcs_mode`, `gcs_mode_source`, and
  warnings from `MDS_MODE` resolution.
- MCP smoke client now verifies protected-resource auth posture, protocol
  version, canonical runtime mode, circuit breaker posture, structured
  read-only tool registry posture, docs/tools coverage, and blocked/dry-run
  direct action behavior.
- Node boot/init reports are bounded, TTL-pruned, capped, config-bound, and
  stored with explicit evidence trust metadata.
- CI/release quality gates now include route inventory, auth, node boot status,
  Simurgh/MCP, eval, retrieval, SITL validation-support, and dashboard checks.

## Independent Review

- Frontend/security reviewer: no blockers after fixes. Confirmed SSE error
  detail preservation and quieter live-region behavior.
- MCP/AI-runtime reviewer: no blockers after fixes. Confirmed the prior MCP
  auth-posture blocker is resolved; residual scope-shape risk is covered by
  server tests for weak-scope overrides.
- Backend/runtime reviewer: route inventory and auth coverage blockers resolved.
  Config binding is improved. Remaining limitation is explicit: node boot
  reports are not cryptographic per-node identity proofs until per-node bearer
  binding or mTLS is implemented.

## Residual Risk

- Node boot evidence currently has `identity_trust`:
  - `source_ip_matched` when request source IP matches the configured node IP.
  - `config_bound` otherwise.
- `config_bound` means the report used a configured `hw_id` and canonical fleet
  metadata, but it is not cryptographic node identity. Future hardening should
  bind drone tokens to `hw_id` or use mTLS/device certificates.
- Dashboard bundle remains large because of existing CRA/code-splitting debt;
  build succeeds with the existing warning.

## Validation Run

Local backend/source checks:

```text
python3 -m py_compile gcs-server/node_boot_status.py gcs-server/api_routes/core.py gcs-server/schemas.py
python3 -m py_compile gcs-server/agent_runtime/assistant.py gcs-server/api_routes/simurgh.py gcs-server/agent_runtime/registry_chat.py
git diff --check
python3 tools/audit_mds_env_registry.py
python3 tools/generate_mds_env_reference.py --check
python3 tools/generate_simurgh_docs_index.py --check
python3 tools/generate_simurgh_tool_candidates.py --check
```

Focused/backend quality gates:

```text
pytest --no-cov -p no:cacheprovider -q tests/test_node_boot_status_routes.py tests/test_api_route_inventory.py tests/test_mds_auth.py -x
pytest --no-cov -p no:cacheprovider -q tests/test_agent_provider_smoke.py tests/test_simurgh_mcp_smoke_client.py tests/test_gcs_simurgh_mcp.py -x
pytest --no-cov -p no:cacheprovider -q tests/test_gcs_simurgh_assistant.py tests/test_gcs_simurgh_routes.py tests/test_agent_registry_planner_coverage.py -x
pytest --no-cov -p no:cacheprovider -q tests/test_simurgh_tool_candidate_generator.py tests/test_agent_registry_planner_coverage.py -x
pytest --no-cov -p no:cacheprovider -q tests/test_run_sitl_validation_suite.py tests/test_runtime_validation_support.py tests/test_sitl_control_client.py -x
pytest --no-cov -p no:cacheprovider -q tests/test_agent_assistant_runtime.py -x
pytest --no-cov -p no:cacheprovider -q tests/test_simurgh_retrieval_quality.py -x
pytest --no-cov -p no:cacheprovider -q tests/test_simurgh_dashboard_prompt_evals.py -x
```

Notes:

- `tests/test_agent_assistant_runtime.py`: 130 passed.
- `tests/test_simurgh_dashboard_prompt_evals.py` passed in isolation. A grouped
  concurrent run timed out on the subprocess-based CLI JSON-report test under
  local load; rerun alone passed in 72.49s.
- `tests/test_simurgh_retrieval_quality.py`: 4 passed.
- `tests/test_run_sitl_validation_suite.py`,
  `tests/test_runtime_validation_support.py`, and
  `tests/test_sitl_control_client.py`: 22 passed.

Hetzner frontend validation:

```text
npm ci --ignore-scripts --no-audit --no-fund
npm test -- --runInBand --watchAll=false src/pages/SimurghOperatorPage.test.js src/services/gcsApiService.test.js
npm test -- --runInBand --watchAll=false src/config/routeDocs.test.js src/components/SidebarMenu.test.js src/App.test.js
npm run build
```

Results:

- Simurgh page/API service tests: 55 passed.
- Route docs/sidebar/app tests: 16 passed.
- Production build compiled successfully.
- Temporary Hetzner validation copy was removed afterward.

## Next Actions

1. Review final diff and split into clean commits.
2. Push official repo branch and run hosted CI.
3. Merge/sync to client repo without leaking private field data.
4. Run production SITL PM demo smoke using the stricter MCP/provider checks.
5. Prepare PM/funder test script for read-only Simurgh questions:
   fleet, connected drones, GPS/telemetry, logs, uploaded show, docs/setup,
   MCP/n8n client setup, multilingual follow-ups, and general public questions.
6. Plan the next security slice for per-node API token binding or mTLS before
   treating node boot/init evidence as source-verified.
7. After PM approval, start action-enabled Simurgh planning/execution slice with
   the same runtime-agnostic workflow, final-layer circuit breaker, human
   confirmation, durable plans, streaming progress, and SITL-first validation.

# Simurgh Agent Context

This directory stores the versioned context artifacts used by Simurgh Operator,
future MCP servers, and dashboard assistant adapters.

These files are runtime context, not background notes. If code, policy, API
behavior, or operator workflow changes, update the matching context file in the
same slice so agents do not learn stale procedures.

Primary artifacts:

- `system-guidelines.md`: standing behavior constraints for model/agent runners.
- `operator-guidelines.md`: operator-facing boundaries and escalation rules.
- `safety-policy.md`: plain-language copy of enforced policy.
- `tool-usage-guidelines.md`: how tools may be selected and interpreted.
- `field-log-review-workflow.md`: sanitized field-log intake, evidence, and
  eval-conversion workflow.
- `provider-smoke-workflow.md`: dry-run and live-provider smoke procedure for
  the advisory-only OpenAI adapter.
- `context-index.yaml`: resource index loaded by `agent_runtime.context`.
- `config/agent_provider_smoke.yaml`: configurable provider smoke scenarios.
- `prompts/`: editable prompt templates.
- `generated/simurgh-openapi-tool-candidates.yaml`: generated, non-callable
  OpenAPI capability candidates for reviewer promotion into the registry.
- `generated/simurgh-docs-index.json`: generated public documentation chunk
  index used by MCP/docs search tools.
- `evals/simurgh-foundation.yaml`: seed safety and policy scenarios.
- `evals/simurgh-advisory-provider.yaml`: runnable offline assistant-provider
  scenarios for advisory regression checks.

Run the advisory eval suite without live provider calls:

```bash
python3 tools/run_simurgh_advisory_evals.py
```

Run the provider smoke workflow without live provider calls:

```bash
python3 tools/run_simurgh_provider_smoke.py --expected-runtime-mode sitl
```

Refresh the OpenAPI candidate menu after GCS API changes:

```bash
python3 tools/generate_simurgh_tool_candidates.py
```

Review read-only MCP promotion coverage through the Simurgh API after a GCS
route or registry change:

```http
GET /api/v1/simurgh/tool-candidates?eligible_read_only=true&limit=200
```

The response `summary.registry_coverage` is the drift report: it compares
OpenAPI-discovered read-only candidates with the curated registry. A generated
candidate is never callable until `config/agent_tools.yaml`, policy, tests,
docs, and reviewers promote it.
Release gates should keep
`summary.registry_coverage.unpromoted_eligible_candidate_count == 0` in the
generated artifact. Routes that look read-only but are unsafe because of cache
writes, downloads, telemetry sensitivity, action wording, or artifact formats
must be classified out by the generator or documented as explicit exclusions
before that gate passes.

Refresh the public docs search index after changing public context resources or
operator docs:

```bash
python3 tools/generate_simurgh_docs_index.py
```

Use `--check` for CI/reviewer verification. Only resources explicitly marked
`searchable: true` or `docs_search: include` in `context-index.yaml` are indexed.
Generated files also require both `docs_search: include` and
`generated_safe_for_search: true`; the environment registry is the current
approved generated-reference exception. Other generated artifacts, evals,
`docs/plans/`, private/sensitive resources, and raw secret patterns are denied.

Live provider smoke is manual and requires an absolute, restricted key file via
`--api-key-file`. Keep `MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`,
`MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true`, and `MDS_MCP_ENABLED=false`.

Scenarios that use provider fixtures must remain advisory-only and must not
require raw API keys, MCP tools, direct drone APIs, or real command execution.
Even when live-provider mode is explicitly enabled, fixture-backed scenarios
stay offline; only scenarios without fixtures may call a configured live
provider.

Field logs, QGC logs, ULog archives, screenshots, chat exports, and private
network details must not be committed to official docs, prompts, or evals. Use
`field-log-review-workflow.md` to convert private evidence into sanitized
patterns before updating context or tests.

The enforcement source of truth is code plus `config/agent_policy.yaml` and
`config/agent_tools.yaml`. Prompt text may explain policy, but prompt text must
not be the only enforcement mechanism.

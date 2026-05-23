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
- `evals/simurgh-foundation.yaml`: seed safety and policy scenarios.
- `evals/simurgh-advisory-provider.yaml`: runnable offline assistant-provider
  scenarios for advisory regression checks.

Run the advisory eval suite without live provider calls:

```bash
python3 tools/run_simurgh_advisory_evals.py
```

Run the provider smoke workflow without live provider calls:

```bash
python3 tools/run_simurgh_provider_smoke.py
```

Live provider smoke is manual and requires an absolute, restricted key file via
`--api-key-file`. Keep `MDS_AGENT_MODE=read_only`,
`MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`,
`MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true`,
`MDS_AGENT_REAL_COMMANDS_ENABLED=false`, and `MDS_MCP_ENABLED=false`.

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

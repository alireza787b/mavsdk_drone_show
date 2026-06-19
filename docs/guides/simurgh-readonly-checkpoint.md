# Simurgh Read-Only Checkpoint

Status: historical read-only checkpoint, superseded by guarded action-enabled
Simurgh slices, updated 2026-06-18.

This guide is the public-safe baseline for the Simurgh Operator read-only phase.
It remains useful for MCP/API promotion rules and regression prompts, but it is
no longer the complete current runtime scope because selected guarded actions
now exist.

## Current Scope

Simurgh can inspect approved MDS/GCS information, answer operator questions,
search public MDS docs, explain setup/workflows, and use optional text-only
OpenAI composition or public web search for safe general questions.

The current implementation also supports selected guarded actions through the
same curated registry and policy executor:

- SITL instance create/reconcile/restart/remove through canonical GCS SITL
  Control routes when `MDS_MODE=sitl` and policy allows `simulate` risk;
- curated flight-command drafts through the canonical GCS command tracker;
- human confirmation when `MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true`;
- final no-execute dry-run reporting when
  `MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`;
- actual route submission only after typed planning, approval, policy check,
  and circuit-breaker-off state.

The current scope includes:

- chat-first `/simurgh` dashboard with local chat history, Markdown rendering,
  copy controls, and compact in-message progress/activity events;
- sanitized streaming stages for understanding, selected evidence, public web
  lookup, provider composition, answer deltas, final, and done. The dashboard
  shows the current activity plus one or two fading previous items, with fuller
  detail collapsed behind a small disclosure;
- shared query adaptation and short session topic memory for typo-heavy,
  follow-up, multilingual, and tone-sensitive operator prompts;
- optional public web search for safe current upstream/public facts such as the
  latest PX4 release. Local deployment questions such as installed firmware,
  fleet state, telemetry, logs, IPs, credentials, or actions stay on local MDS
  tools and are not sent to public web search;
- curated read-only tool registry in `config/agent_tools.yaml`;
- policy review in `config/agent_policy.yaml` before any tool is callable;
- MCP Streamable HTTP endpoint at `POST /api/v1/simurgh/mcp` when enabled;
- MCP resources and tools backed by the same registry/policy executor used by
  the dashboard assistant;
- deployment-aware MCP setup answers. Simurgh prefers `MDS_MCP_RESOURCE_URL`,
  then the current dashboard/API request origin, then documented path-only
  fallback when no public URL is configured;
- read-only drone log session and onboard PX4 ULog metadata inspection through
  approved GCS-side log endpoints. This lists session/ULog evidence and recent
  warning/error counts without downloading, parsing, or erasing raw flight logs;
- generated OpenAPI candidate inventory for review coverage, not execution;
- generated public docs index for `mds.docs.search` and `mds.docs.chunk.read`;
- dashboard/runtime controls for provider, model, API-key file status, MCP,
  circuit breaker, and always-confirm posture.

## Safety Boundary

The original read-only checkpoint deliberately did not expose mutation or flight
actions. Current guarded-action slices expose only reviewed registry tools, not
raw APIs.

Blocked boundaries:

- no direct drone-local API exposure to models or external MCP clients;
- no raw `POST /api/v1/commands` access;
- no unreviewed mission launch, upload, parameter write, environment write, git
  write, or service restart tool exposed through Simurgh/MCP;
- no automatic OpenAPI-to-MCP execution;
- no model-side tool execution against GCS state;
- no raw prompts, credentials, private logs, or unbounded telemetry in persisted
  assistant history or MCP resources.

`MDS_MODE` remains the only real-vs-SITL runtime switch. Simurgh does not have a
separate real/SITL mode. The action circuit breaker is the final executor stop
for every non-read-only tool: upstream planning may explain what would be
called, but the executor must not mutate state while
`MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`. `Always confirm actions` is the human
approval gate immediately before that final executor layer.

## MCP And API Promotion Contract

The MCP surface is intentionally curated. The generated OpenAPI candidate file
is a reviewer menu, not a runtime permission grant.

Promotion path for any new GCS API capability:

```text
FastAPI route
  -> generated non-callable candidate
  -> registry entry in config/agent_tools.yaml
  -> policy classification in config/agent_policy.yaml
  -> typed argument and result contract
  -> docs and safety notes
  -> tests and prompt evals
  -> reviewer approval
  -> MCP tools/list and tools/call exposure
```

This keeps MDS compatible with future adapters such as FastAPI-MCP, FastMCP,
MCPify, or a better emerging tool without making the adapter the safety boundary.
Auto-discovery should reduce review effort; it must not bypass classification,
docs, tests, or policy.

The current drift gate is `summary.registry_coverage` from
`GET /api/v1/simurgh/tool-candidates?limit=200` and the MCP smoke client. A
read-only completion checkpoint should show zero unpromoted generator-eligible
read-only routes before handoff.

## Validation Gate

Run these checks before PM/funder handoff, MCP client onboarding, or any
action-enabled planning slice:

```bash
python3 tools/generate_mds_env_reference.py --check
python3 tools/generate_simurgh_tool_candidates.py --check
python3 tools/generate_simurgh_docs_index.py --check
pytest tests/test_agent_assistant_evals.py tests/test_agent_assistant_runtime.py tests/test_gcs_simurgh_mcp.py tests/test_gcs_simurgh_routes.py tests/test_env_registry.py tests/test_simurgh_dashboard_prompt_evals.py tests/test_simurgh_retrieval_quality.py
python3 tools/run_simurgh_dashboard_prompt_evals.py
python3 tools/simurgh_mcp_smoke_client.py --base-url http://127.0.0.1:5030 --token-file /path/to/agent-token --json
```

The smoke token must be temporary, revoked after the run, and never committed or
included in reports.

## PM Review Prompts

Use these prompts to confirm the read-only checkpoint feels useful and not like a
hardcoded chatbot:

- `How many drones do we have configured?`
- `Which drones are connected now, and what evidence do you have?`
- `Is there a drone show uploaded and ready? How long is it?`
- `Check the latest GCS logs. Does anything look operationally important?`
- `How many drone log sessions and ULog files do we have? Were any errors seen?`
- `What is the difference between QuickScout and Swarm Trajectory?`
- `Does MDS support ArduPilot today?`
- `What is the latest PX4 stable release version?`
- `How do I change the Simurgh OpenAI key safely?`
- `If I want to connect n8n to Simurgh MCP, what address and considerations should I use?`
- `Can n8n or VS Code use the same MCP tool menu?`
- `Say that last answer in Persian.`
- `What is MAVLink?`
- `What is the lat/lon/elevation of Damavand Peak in WGS84?`

Expected behavior: Simurgh should answer from MDS evidence when the question is
about MDS, use public/general knowledge or web search only for safe public
questions, remember the previous topic for follow-ups, and avoid repeating an
unrelated tool summary.

## Historical Action-Enabled Roadmap

This was the original staged roadmap after the read-only checkpoint. The first
guarded action slices are now implemented; keep the sequence as a review model
for broadening scope.

Sequence and current state:

1. **Action proposal schema**: implemented for selected curated actions.
2. **Action candidate inventory**: implemented through generated candidates plus
   curated registry promotion.
3. **SITL lifecycle wrappers**: implemented for create/reconcile/restart/remove
   through GCS SITL Control routes.
4. **Curated flight-command drafts**: implemented for the initial reviewed
   command set through the canonical GCS command tracker.
5. **Progress monitor**: initial streaming exists; richer operation follow-up
   and cancellation remain active roadmap items.
6. **Scenario evals**: PM-style regression tests exist and must expand as each
   new action surface is promoted.
7. **Field shadow mode and broader real-mode actions**: remain future work and
   require written PM/safety approval, strong audit, and field checklist
   alignment.

Do not start with broad model autonomy. Deterministic state, tool scoping,
approval, monitoring, and evals are the product foundation.

## Documentation Rules

Simurgh docs are model-visible product inputs. Any code/API/policy change that
alters Simurgh behavior must update the relevant doc or context file in the same
slice, regenerate the docs index, and rerun prompt/tool validation. Historical
journey logs may remain as history, but current operator docs, MCP client docs,
environment references, and generated indexes must not contain conflicting
runtime guidance.

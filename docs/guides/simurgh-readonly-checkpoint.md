# Simurgh Read-Only Checkpoint

Status: read-only checkpoint before action-enabled Simurgh slices, updated
2026-06-06.

This guide is the public-safe handoff for the current Simurgh Operator phase. It
summarizes what is intentionally available today, what must remain blocked, how
future MCP/API work should be promoted, and which gates must pass before action
execution is added.

## Current Scope

Simurgh is currently a read-only operator assistant and MCP interoperability
surface for GCS-side MDS state. It can inspect approved MDS/GCS information,
answer operator questions, search public MDS docs, explain setup/workflows, and
use optional advisory OpenAI text composition or public web search for safe
general questions.

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

The read-only checkpoint deliberately does not expose mutation or flight actions.

Blocked boundaries:

- no direct drone-local API exposure to models or external MCP clients;
- no raw `POST /api/v1/commands` access;
- no mission launch, upload, parameter write, environment write, git write, or
  service restart tool exposed through Simurgh/MCP;
- no automatic OpenAPI-to-MCP execution;
- no model-side tool execution against GCS state;
- no raw prompts, credentials, private logs, or unbounded telemetry in persisted
  assistant history or MCP resources.

`MDS_MODE` remains the only real-vs-SITL runtime switch. Simurgh does not have a
separate real/SITL mode. The action circuit breaker is the final executor stop
for any future non-read-only tool: upstream planning may explain what would be
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

## Action-Enabled Roadmap

Action-enabled Simurgh should be added in staged slices only after PM/safety
approval of this read-only checkpoint.

Recommended sequence:

1. **Action proposal schema**: produce structured dry-run plans for future
   actions without executing them.
2. **Action candidate inventory**: classify existing mutation/flight APIs as
   blocked, guarded, SITL-only, or future-real candidates.
3. **SITL-only wrappers**: expose a tiny set of reviewed actions in SITL with
   typed args, always-confirm, audit, and circuit-breaker enforcement.
4. **Progress monitor**: stream action status, logs, cancellation state, and
   final evidence through the same Simurgh activity event model.
5. **Scenario evals**: add PM-style dry-run, SITL, rejection, and interruption
   prompts before broadening action scope.
6. **Field shadow mode**: run real-mode advisory/dry-run next to human actions
   and compare proposed actions against operator decisions.
7. **Limited real-mode actions**: only after written PM/safety approval, allow a
   narrow real-mode set with explicit confirmation, circuit-breaker off by a
   human, strong audit, and field checklist alignment.

Do not start with broad model autonomy. Deterministic state, tool scoping,
approval, monitoring, and evals are the product foundation.

## Documentation Rules

Simurgh docs are model-visible product inputs. Any code/API/policy change that
alters Simurgh behavior must update the relevant doc or context file in the same
slice, regenerate the docs index, and rerun prompt/tool validation. Historical
journey logs may remain as history, but current operator docs, MCP client docs,
environment references, and generated indexes must not contain conflicting
runtime guidance.

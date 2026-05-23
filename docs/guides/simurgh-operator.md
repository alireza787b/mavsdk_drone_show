# Simurgh Operator

Simurgh Operator is the MDS agent-safe control-plane foundation for future MCP
servers and dashboard assistant workflows.

The current implementation is a foundation slice only:

- provider-neutral runtime primitives
- deny-by-default policy evaluation
- YAML-backed curated tool registry
- approval, audit, session, and context-index helpers
- editable agent context files
- read-only dashboard inspection page
- no model-provider SDK dependency
- optional advisory-only OpenAI Responses adapter
- disabled-by-default metadata-only MCP endpoint
- no real-world command execution
- no direct drone API exposure

## Configuration Files

Core artifacts:

- `config/agent_policy.yaml`
- `config/agent_tools.yaml`
- `config/agent_assistant.yaml`
- `config/agent_provider_smoke.yaml`
- `docs/agent-context/context-index.yaml`
- `docs/agent-context/system-guidelines.md`
- `docs/agent-context/operator-guidelines.md`
- `docs/agent-context/safety-policy.md`
- `docs/agent-context/tool-usage-guidelines.md`
- `docs/agent-context/field-log-review-workflow.md`
- `docs/agent-context/provider-smoke-workflow.md`
- `docs/agent-context/prompts/default-operator.md`
- `docs/agent-context/evals/simurgh-foundation.yaml`
- `docs/agent-context/evals/simurgh-advisory-provider.yaml`

Do not hardcode prompt text, policy text, or tool rules in provider adapters. Add
or change the artifact first, then update tests and docs in the same slice.

## Advisory Evals

The runnable advisory-provider eval suite is:

```bash
python3 tools/run_simurgh_advisory_evals.py
```

The default suite uses deterministic mock turns and offline OpenAI fixtures. It
must not call live providers, expose MCP tools, use direct drone APIs, submit
raw GCS commands, or require raw API keys. Add new operator examples to
`docs/agent-context/evals/simurgh-advisory-provider.yaml` as workflows and
provider prompts evolve, then rerun the suite and update docs in the same slice.
If `--allow-live-provider` is used for a special manual run, fixture-backed
scenarios still stay offline; only scenarios without fixtures may call the
configured provider.

## Provider Smoke

The manual provider smoke suite is:

```bash
python3 tools/run_simurgh_provider_smoke.py
```

Dry mode is the default and does not call OpenAI. It validates the configured
scenario prompts, builds an advisory OpenAI Responses request, and checks that
the request preserves `store=false`, `tools=[]`, `tool_choice="none"`,
`parallel_tool_calls=false`, no conversation state, and `mds_execution=none`.

Live smoke requires an absolute restricted key file:

```bash
python3 tools/run_simurgh_provider_smoke.py --live --api-key-file /etc/mds/secrets/openai_api_key
```

Use live smoke only from a trusted validation host or maintenance window after
offline tests pass. The smoke report omits raw response content by default and
prints a content hash plus length. Keep `MDS_AGENT_MODE=read_only`,
`MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`,
`MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true`,
`MDS_AGENT_REAL_COMMANDS_ENABLED=false`, and `MDS_MCP_ENABLED=false`; this
checks provider connectivity and request shape only. Do not change deployment
`MDS_MODE` for provider smoke; a production GCS can remain `MDS_MODE=real`
while the Simurgh assistant path stays advisory-only.

When field logs produce new lessons, do not paste raw artifacts into eval
fixtures or context files. Follow
`docs/agent-context/field-log-review-workflow.md`: keep raw evidence private,
hash the source artifact, redact identifiers and network details, encode only a
minimal reusable pattern, and validate the scenario offline before reviewer
approval.

## Environment Variables

Default installs enable the non-executing mock assistant runtime while keeping
MCP and real command paths off:

```text
MDS_AGENT_ENABLED=true
MDS_MCP_ENABLED=false
MDS_AGENT_ACTION_CIRCUIT_BREAKER=true
MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true
MDS_AGENT_MODE=read_only
MDS_AGENT_PROVIDER=mock
MDS_AGENT_REAL_COMMANDS_ENABLED=false
MDS_MCP_ALLOWED_ORIGINS=
MDS_MCP_REQUIRE_AUTH=true
MDS_MCP_REQUIRED_SCOPES=agent,admin
```

Operator-facing controls should stay small:

- **Agent enabled** maps to `MDS_AGENT_ENABLED`.
- **MCP enabled** maps to `MDS_MCP_ENABLED`; keep
  `MDS_MCP_REQUIRE_AUTH=true` outside isolated local development.
- **Non-action circuit breaker** maps to
  `MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`. When enabled, Simurgh denies every
  non-read-only tool regardless of policy profile.
- **Always confirm actions** maps to
  `MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true` for future action-capable
  wrappers. Current production assistant turns remain advisory-only.
- **OpenAI provider/model/key file** map to `MDS_AGENT_PROVIDER`,
  `MDS_AGENT_OPENAI_MODEL`, and `MDS_AGENT_OPENAI_API_KEY_FILE`.

`MDS_MODE` remains the only real-vs-SITL GCS runtime environment switch.
`MDS_AGENT_MODE` is an advanced Simurgh policy profile and does not change the
GCS runtime, start SITL, select real hardware, or grant command authority.

Keep `MDS_AGENT_PROVIDER=mock` on unauthenticated or field-reachable GCS
services. If `MDS_AGENT_PROVIDER=openai` is enabled for advisory text, the
assistant API refuses turns unless the request has an authenticated MDS
operator/admin session or a bearer token with `agent`, `operator`, or `admin`
scope. Drone-only bearer tokens are not accepted for external provider calls.
This prevents an exposed GCS or lower-privilege machine token from becoming an
external-provider, cost, or data-egress surface.

Advanced paths:

```text
MDS_AGENT_POLICY_FILE=config/agent_policy.yaml
MDS_AGENT_TOOL_REGISTRY_FILE=config/agent_tools.yaml
MDS_AGENT_CONTEXT_INDEX_FILE=docs/agent-context/context-index.yaml
MDS_AGENT_ASSISTANT_FILE=config/agent_assistant.yaml
MDS_AGENT_ASSISTANT_HISTORY_FILE=runtime_data/simurgh/assistant_turns.jsonl
MDS_AGENT_ASSISTANT_HISTORY_MAX_AGE_DAYS=30
MDS_AGENT_ASSISTANT_HISTORY_MAX_RECORDS=200
MDS_AGENT_OPENAI_API_KEY_FILE=
MDS_AGENT_OPENAI_MODEL=gpt-5.5
MDS_AGENT_OPENAI_BASE_URL=https://api.openai.com/v1
MDS_AGENT_OPENAI_TIMEOUT_SEC=30
MDS_AGENT_OPENAI_MAX_OUTPUT_TOKENS=900
MDS_AGENT_OPENAI_REASONING_EFFORT=medium
MDS_AGENT_OPENAI_TEXT_VERBOSITY=low
```

`MDS_MCP_ALLOWED_ORIGINS` is optional. Empty means browser-origin requests are
accepted only from localhost-style origins. For a deployed MCP browser client,
set a comma-separated exact Origin allowlist, for example:

```text
MDS_MCP_ALLOWED_ORIGINS=https://gcs.example.com,https://ops.example.com
```

Wildcard browser origins are intentionally not supported.

When MCP is enabled, `MDS_MCP_REQUIRE_AUTH=true` requires
`Authorization: Bearer` before the endpoint processes MCP requests. Keep this
true for production. Set it false only for isolated local development where the
endpoint is not reachable from other hosts.

When MDS auth is enabled, accepted bearer tokens must have an `agent` or `admin`
scope. `MDS_MCP_REQUIRED_SCOPES` can narrow the accepted set to those two scope
names, but weaker values such as `drone`, `operator`, or `viewer` are ignored
and cannot grant MCP access. The HTTP challenge advertises the least-privilege
`agent` scope by default. Dashboard cookie sessions are rejected for MCP even
when they include a valid CSRF token.

For deployments behind an OAuth gateway or authorization server, set:

```text
MDS_MCP_AUTHORIZATION_SERVERS=https://auth.example.com/issuer
MDS_MCP_RESOURCE_URL=https://gcs.example.com/api/v1/simurgh/mcp
```

`MDS_MCP_AUTHORIZATION_SERVERS` is advertised in the protected-resource
metadata. If it is empty while MCP auth is required, the resource server derives
the issuer from the canonical public origin. `MDS_MCP_RESOURCE_URL` pins the
canonical resource identifier and the `WWW-Authenticate resource_metadata`
origin when a reverse proxy would otherwise make the internal request URL
misleading.

Provider-specific credentials use file paths only. To enable the advisory-only
OpenAI adapter, set:

```text
MDS_AGENT_PROVIDER=openai
MDS_AGENT_OPENAI_API_KEY_FILE=/etc/mds/secrets/openai_api_key
```

Do not put raw API keys in environment values, config files, docs, commits,
tests, Telegram reports, or shell history. The OpenAI adapter uses the Responses
API with `store=false`, `tools=[]`, `tool_choice="none"`, no conversation state,
no uploaded files, no streaming, and no background jobs. `store=false` is a
fixed invariant in this slice, not an operator-configurable setting.
`MDS_AGENT_OPENAI_BASE_URL` is pinned to `https://api.openai.com/v1`; custom
OpenAI-compatible gateways are rejected in this slice to prevent API key egress
to unreviewed destinations.

## Safety Boundary

All tool execution must pass through:

```text
model or MCP client
  -> Simurgh adapter
  -> tool registry
  -> policy engine
  -> approval broker when required
  -> curated GCS wrapper
  -> existing GCS API/service
  -> audit trail
```

The drone API is not exposed to MCP clients. Raw `POST /api/v1/commands` is not
exposed to models. Future command-capable wrappers require a separate safety
case, live readiness evidence, explicit operator approval, audit, and tests.

## MCP Metadata Endpoint

The MCP endpoint is mounted at:

- `POST /api/v1/simurgh/mcp`
- `GET /.well-known/oauth-protected-resource`
- `GET /.well-known/oauth-protected-resource/api/v1/simurgh/mcp`

It is off by default and requires both:

```text
MDS_AGENT_ENABLED=true
MDS_MCP_ENABLED=true
```

Protocol slice:

- Protocol version: `2025-11-25`
- Transport: Streamable HTTP request/response JSON only
- SSE/GET stream: not supported; `GET /api/v1/simurgh/mcp` returns `405`
- Capabilities: `resources` only
- MCP tools: not advertised and not implemented
- Auth challenge: `WWW-Authenticate: Bearer ... scope="agent"` when MDS auth is
  enabled and the request has no acceptable bearer token

Resources exposed:

- `mds://simurgh/status`
- `mds://simurgh/policy`
- `mds://simurgh/tool-registry`
- `mds://simurgh/context-index`
- `mds://simurgh/sessions`
- `mds://simurgh/audit`
- `mds://simurgh/context/{resource_id}` for public context resources

The tool registry is exposed as JSON metadata, not as callable MCP tools. The
endpoint rejects `tools/list`, `tools/call`, JSON-RPC batching, invalid origins,
and unsupported protocol headers.

## GCS API Surface

The foundation API is metadata/session/audit/assistant-scaffold only. It does
not execute domain tools.

Read-only routes:

- `GET /api/v1/simurgh/status`
- `GET /api/v1/simurgh/policy`
- `GET /api/v1/simurgh/tools`
- `GET /api/v1/simurgh/tools/{tool_id}`
- `GET /api/v1/simurgh/context`
- `GET /api/v1/simurgh/context/{resource_id}`
- `GET /api/v1/simurgh/sessions`
- `GET /api/v1/simurgh/audit`
- `GET /api/v1/simurgh/assistant/turns`

Session routes:

- `POST /api/v1/simurgh/sessions`
- `DELETE /api/v1/simurgh/sessions/{session_id}`

Assistant scaffold route:

- `POST /api/v1/simurgh/assistant/turns`

Session creation requires `MDS_AGENT_ENABLED=true`. If an installation disables
the agent runtime, operators and maintainers can still inspect policy, tool
metadata, and context resources.

Assistant turns also require `MDS_AGENT_ENABLED=true`. The default adapter is
deterministic `mock`. The optional `openai` adapter is advisory-only and calls
the OpenAI Responses API after the same policy, actor/session, message-size,
metadata-size, and public-context checks pass. Both adapters assemble public
context from `config/agent_assistant.yaml` and
`docs/agent-context/context-index.yaml`, record an audit hash, and do not
execute any tool. If `MDS_AGENT_PROVIDER` is set to an unsupported provider, the
route returns a not-implemented error.

`GET /api/v1/simurgh/status` reports `assistant_provider`,
`assistant_model`, and `assistant_external_provider` so dashboards and agent
clients can warn operators when text may leave the GCS for a configured model
provider. Operator UI must not describe the assistant as local-only unless the
reported provider is `mock`.

Provider instructions and input templates live in `config/agent_assistant.yaml`.
Changing those prompts should be done by editing the config artifact, then
updating tests and docs. The adapter must not embed mission policy, tool rules,
or prompt text in code.

Assistant turns are also written to a bounded JSONL runtime history file. The
default path is `runtime_data/simurgh/assistant_turns.jsonl`, which is ignored
by git. History records keep prompt hashes, response metadata, context
metadata, blocked-intent signals, and safety notes; raw operator prompts and
assistant response text are omitted from persisted history and from the history
API response. Records are retained by both age and count; set
`MDS_AGENT_ASSISTANT_HISTORY_MAX_AGE_DAYS=0` only if an installation needs to
disable age-based retention while keeping count-based bounding. The history
endpoint is filtered by actor and is not exposed as an MCP resource. Audit
events continue to store hashes rather than raw prompts.

## Dashboard

The dashboard route `/simurgh` displays runtime posture, policy locks,
registered tools, context resources, active or recorded sessions, audit records,
and the assistant history for the dashboard actor. When the agent runtime is
enabled, the Assistant tab can create advisory assistant turns and reuse the
active assistant session. The page still does not expose MCP tools, direct drone
APIs, raw command submission, or executable flight controls.

The navigation label is **Simurgh Operator** under the System section.

## Development Notes

Run focused validation after changing Simurgh artifacts:

```bash
pytest tests/test_agent_assistant_evals.py tests/test_agent_assistant_runtime.py tests/test_gcs_simurgh_assistant.py tests/test_gcs_simurgh_mcp.py tests/test_gcs_simurgh_routes.py tests/test_agent_runtime_foundation.py tests/test_api_route_inventory.py tests/test_env_registry.py
python3 tools/generate_mds_env_reference.py --check
cd app/dashboard/drone-dashboard && npm test -- --runTestsByPath src/pages/SimurghOperatorPage.test.js src/services/gcsApiService.test.js src/config/routeDocs.test.js src/components/SidebarMenu.test.js src/App.test.js --watchAll=false
```

If docs and code disagree, treat the stale doc as a product bug. Fix the doc or
the code before exposing the context to a model or MCP client.

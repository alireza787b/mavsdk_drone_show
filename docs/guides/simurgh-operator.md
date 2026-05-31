# Simurgh Operator

Simurgh Operator is the MDS agent-safe control-plane foundation for future MCP
servers and dashboard assistant workflows.

The current implementation is still deny-by-default, but it now includes a
usable read-only operator slice:

- provider-neutral runtime primitives
- deny-by-default policy evaluation
- YAML-backed curated tool registry
- approval, audit, session, and context-index helpers
- editable agent context files
- ChatGPT-style dashboard operator chat with local history
- dashboard assistant progress and answer streaming over a GCS-side SSE route
- optional advisory-only OpenAI Responses adapter
- optional MCP endpoint with resources and policy-allowed read-only GCS tools
- typed arguments for reviewed read-only MCP tools where needed
- dashboard chat execution of selected read-only registry tools, including
  reviewed typed-argument reads when the operator gives explicit IDs/values,
  through the same internal adapter used by MCP `tools/call`
- generated OpenAPI candidate inventory that is not runtime-callable by default
- generated public docs/chunk index with MCP search and bounded chunk retrieval
- no real-world command execution
- no direct drone API exposure

## Dashboard Chat UX Contract

The `/simurgh` dashboard surface should stay chat-first and low-noise:

- local browser history is a convenience cache under `mds.simurgh.chat.v2`, not
  the authoritative backend session store;
- each chat row has a quiet hover/focus overflow menu for deleting only that
  conversation;
- the destructive clear-all action stays behind the history header overflow
  menu, not as an always-visible primary action;
- assistant copy controls and code-snippet copy controls stay hidden until
  hover/focus or touch interaction;
- progress and streamed answer deltas stay inside the active assistant message;
- assistant answers render compact Markdown tables, lists, code, bold text, and
  only safe clickable dashboard/doc/HTTPS links.

Changing this UX should include a focused Jest test for history actions,
Markdown rendering, and copy controls. Browser-level visual regression is still
recommended before conference or field-demo handoff.

## Current Autopilot Support

MDS is currently **PX4-first and PX4-validated**. The production assumptions in
the GCS, companion workflows, readiness checks, MAVSDK command paths, PX4
parameter guidance, SYS_ID guidance, show execution, QuickScout, and Swarm
Trajectory flows are built and tested against PX4.

ArduPilot is a future integration candidate because it can also expose MAVLink,
but it is **not currently a supported or validated MDS flight-stack target** for
command/control. Before MDS advertises ArduPilot support, the project needs an
explicit adapter and review path for parameter names, flight modes, mission
semantics, offboard/control behavior, SITL coverage, bench tests, field tests,
operator docs, and safety policy.

Operator answer to give today: use PX4 for current MDS deployments; do not treat
ArduPilot as production-supported until an ArduPilot adapter has passed the same
tests and documentation gate.

## Configuration Files

Core artifacts:

- `config/agent_policy.yaml`
- `config/agent_tools.yaml`
- `config/agent_assistant.yaml`
- `config/agent_general_knowledge.yaml`
- `config/agent_public_places.yaml`
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
- `docs/agent-context/generated/simurgh-openapi-tool-candidates.yaml`
- `docs/agent-context/generated/simurgh-docs-index.json`
- `docs/guides/simurgh-mcp-clients.md`

Do not hardcode prompt text, policy text, or tool rules in provider adapters. Add
or change the artifact first, then update tests and docs in the same slice.

## Advisory Evals

The runnable advisory-provider eval suite is:

```bash
python3 tools/run_simurgh_advisory_evals.py
```

The default suite uses deterministic mock turns and offline OpenAI fixtures. It
must not call live providers, expose mutation-capable MCP tools, use direct drone
APIs, submit raw GCS commands, or require raw API keys. Add new operator examples to
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
prints a content hash plus length. Keep
`MDS_AGENT_ACTION_CIRCUIT_BREAKER=true` and
`MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true`. MCP does not need to be enabled
for provider smoke; if it is enabled for a separate MCP validation, keep
`MDS_MCP_REQUIRE_AUTH=true`. Do not change `MDS_MODE` for provider smoke; a
production GCS can remain `MDS_MODE=real` while the Simurgh assistant path stays
advisory-only.

## MCP Smoke Client

The external MCP validation client is:

```bash
python3 tools/simurgh_mcp_smoke_client.py --base-url https://<gcs-host> --token-file /path/to/agent-token --json
```

It validates the HTTP MCP path that n8n, Claude, VS Code bridges, and custom
agents use: `initialize`, `tools/list`, `resources/list`,
`mds.operator.question.answer`, and `mds.docs.search`. It also fails if the tool
menu exposes obvious raw/action/admin tool names. Use it before debugging a
specific external client, and never put bearer tokens in committed MCP client
configuration.

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
MDS_AGENT_PROVIDER=mock
MDS_MCP_ALLOWED_ORIGINS=
MDS_MCP_REQUIRE_AUTH=true
MDS_MCP_REQUIRED_SCOPES=agent,admin
```

Operator-facing controls should stay small:

- **Agent enabled** maps to `MDS_AGENT_ENABLED`.
- **MCP enabled** maps to `MDS_MCP_ENABLED`; keep
  `MDS_MCP_REQUIRE_AUTH=true` outside isolated local development.
- **Circuit breaker** maps to `MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`.
  It is the final execution stop: upstream planning and approval can still explain
  what would be called, but the executor must not run non-read-only tools while
  this is enabled.
- **Always confirm actions** maps to
  `MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true` for future action-capable
  wrappers. It is the approval gate immediately before the final executor layer.
  Current production assistant turns remain advisory-only.
- **OpenAI provider/model/key file** map to `MDS_AGENT_PROVIDER`,
  `MDS_AGENT_OPENAI_MODEL`, and `MDS_AGENT_OPENAI_API_KEY_FILE`.
- **Web search** maps to `MDS_AGENT_WEB_SEARCH_ENABLED`. It is only used for
  public/general prompts after local MDS tools decline the request; fleet state,
  logs, private network details, credentials, and operational actions stay out
  of the web-search lane.

The dashboard Simurgh settings panel hot-applies these operator-facing keys to
the running GCS process and persists them to `/etc/mds/gcs.env`; a full GCS
restart is not required for provider/model, MCP enablement, or the safety
checkboxes to affect new Simurgh turns. Advanced keys remain editable from the
Environment page.

`MDS_MODE` is the only real-vs-SITL GCS runtime environment switch and Simurgh
uses it for policy posture. There is no separate user-facing Simurgh mode or
real-command override. If the circuit breaker is on, Simurgh may still produce
a dry-run explanation of the tool and arguments it would use, but the final
executor layer must not perform the action. If the circuit breaker is off, the
current `MDS_MODE`, tool risk policy, and human-confirmation rules still apply.

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
MDS_AGENT_DOCS_INDEX_FILE=docs/agent-context/generated/simurgh-docs-index.json
MDS_AGENT_OPENAI_API_KEY_FILE=
MDS_AGENT_OPENAI_MODEL=gpt-5.5
MDS_AGENT_OPENAI_BASE_URL=https://api.openai.com/v1
MDS_AGENT_OPENAI_TIMEOUT_SEC=30
MDS_AGENT_OPENAI_MAX_OUTPUT_TOKENS=900
MDS_AGENT_OPENAI_REASONING_EFFORT=medium
MDS_AGENT_OPENAI_TEXT_VERBOSITY=low
MDS_AGENT_WEB_SEARCH_ENABLED=false
MDS_AGENT_WEB_SEARCH_CONTEXT_SIZE=medium
MDS_AGENT_WEB_SEARCH_EXTERNAL_ACCESS=true
MDS_AGENT_WEB_SEARCH_ALLOWED_DOMAINS=
MDS_AGENT_WEB_SEARCH_BLOCKED_DOMAINS=
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

Provider-specific credentials use server-side secret files only. The dashboard
can paste/update an OpenAI key, but the API never returns the raw key; it only
shows ready/fingerprint/updated status. To enable the advisory-only OpenAI
adapter manually, set:

```text
MDS_AGENT_PROVIDER=openai
MDS_AGENT_OPENAI_API_KEY_FILE=/etc/mds/secrets/openai_api_key
```

Do not put raw API keys in environment values, config files, docs, commits,
tests, Telegram reports, or shell history. The OpenAI adapter uses the Responses
API with `store=false`, no conversation state, no uploaded files, no
provider-native streaming, and no background jobs. `store=false` is a fixed
invariant in this slice, not an operator-configurable setting. The dashboard may
use the GCS-side assistant SSE endpoint for progress/delta UI, but that stream
does not expose model tools or change the provider request invariants.
`MDS_AGENT_OPENAI_BASE_URL` is pinned to `https://api.openai.com/v1`; custom
OpenAI-compatible gateways are rejected in this slice to prevent API key egress
to unreviewed destinations.

When `MDS_AGENT_WEB_SEARCH_ENABLED=true`, Simurgh may add the official OpenAI
Responses `web_search` tool only for public/general prompts such as current
weather, public geography lookup beyond the reviewed local registry, laws/rules,
or internet-style current facts. The request still uses `store=false`; it does
not include GCS tool results, fleet telemetry, private logs, credentials, or
raw operational evidence. Inline web citations returned by OpenAI are preserved
and rendered as clickable `Sources` links in the dashboard. Use
`MDS_AGENT_WEB_SEARCH_ALLOWED_DOMAINS` or `MDS_AGENT_WEB_SEARCH_BLOCKED_DOMAINS`
only with bare domains and only when an eval-backed deployment needs source
control. Do not set both lists at the same time.

Before a provider is called, Simurgh first routes common operator questions
through local read-only MDS/GCS tools. Fleet count, drone IP lookup, live
presence, swarm formation/cluster geometry, show upload/readiness, show
duration, Simurgh runtime posture, board/setup documentation links,
companion-computer bootstrap guidance, add-drone workflow guidance, SITL startup
guidance, backend warning/error summaries, action-capability explanations, and
capability-menu answers are produced locally and do not require OpenAI auth.
When an authenticated dashboard/operator session has the OpenAI provider
enabled, Simurgh may run the same read-only local tool first and then ask OpenAI
to compose the final wording from a bounded `session.read_only_mds_evidence`
context document. The tool evidence remains authoritative: exact counts, IPs,
routes, modes, coordinates, safety caveats, and no-action statements must be
preserved. If provider composition fails or the request is unauthenticated,
Simurgh falls back to the deterministic local answer rather than losing the
operator evidence.
Dashboard sessions keep only safe short-lived routing metadata such as
`last_domain=drone_show` or `last_domain=logs`; they do not store raw transcript
text. The local wrapper also infers a response mode, for example `status`,
`interpret`, `workflow`, `compare`, or `capability`, so follow-ups like `is
there any uploaded?` or `what does it mean?` can reuse the right evidence source
without repeating the previous template. Prompts outside those curated read-only
intents use the configured provider subject to the auth and safety gates above.

General robotics/MDS-adjacent answers that should not be misrouted to live GCS
tools are curated in `config/agent_general_knowledge.yaml`. Keep that file small
and public-safe: it is for definitions such as drone/MAVLink and external-data
fallbacks such as weather when no live weather evidence source is connected. Do
not put private field facts, credentials, network maps, or operator transcripts
there. If a new general topic becomes review-critical, add it to that config, add an
eval/test, and keep the answer conversational while clearly separating general
knowledge from live vehicle or flight-readiness evidence.

Public geography/distance prompts use `config/agent_public_places.yaml` plus
deterministic geodesy math before falling back to the provider. This prevents a
general model from guessing coordinates or distances for reviewed demo/operator
places. Keep it limited to public, non-sensitive references; never add private
mission coordinates, customer sites, launch positions, or field logs. If a place
is missing and exact public data matters, enable the public web-search lane and
require citations instead of inventing a value.

## Query Planning And Retrieval Context

Simurgh does not rely on a naive "chunk, embed, return top-k" path for operator
chat. The current provider path uses a small deterministic query-planning layer
before any external model call:

- normalize common field typos without changing the operator's meaning;
- infer a domain such as `drone_show`, `fleet`, `swarm`, `logs`, `setup`,
  `runtime`, `mcp`, `ui`, or `general`;
- infer the answer mode, for example `status`, `interpret`, `workflow`,
  `compare`, `capability`, or `clarify`;
- prefer local read-only MDS tools for factual GCS state;
- retrieve bounded public documentation chunks only when no local evidence tool
  handled the prompt;
- keep only safe routing metadata such as `last_domain`, never raw transcript
  text, secrets, raw logs, or field evidence;
- add audit metadata for the inferred domain, response mode, uncertainty, and
  number of retrieved context chunks.

This keeps deterministic work deterministic while still letting the provider
answer unexpected, typo-heavy, or partially unclear prompts naturally. A nonsense
or very low-signal message should not be ignored; Simurgh should state the most
likely MDS interpretation, provide the nearest safe next step, and ask one short
clarifying question only when needed.

The retrieval artifact is
`docs/agent-context/generated/simurgh-docs-index.json`, generated from approved
public docs and context files. Provider retrieval and MCP docs tools share this
artifact through `gcs-server/agent_runtime/retrieval.py`, so dashboard chat,
external MCP clients, and future custom agents have the same documentation
surface. The production default is `LexicalDocsRetriever`: lexical/tag-filtered
search with bounded context budgets and multi-query fusion that favors the
operator's original wording over broader expansion queries. Future hybrid vector
search, reranking, GraphRAG-style entity/community retrieval, or agentic
multi-step retrieval must plug in behind the same `RetrievalQuery` / `RetrievalHit`
contract and be gated by retrieval evals before becoming production default.

Retrieval quality checks live in
`docs/agent-context/evals/simurgh-retrieval-quality.yaml` and
`tests/test_simurgh_retrieval_quality.py`. Keep review-critical prompts in that eval
set whenever a retrieval or query-planning change is made.

Design references for reviewers:

- OpenAI Responses/tool guidance: https://developers.openai.com/api/docs/guides/tools
- IBM RAG overview: https://www.ibm.com/think/topics/retrieval-augmented-generation
- IBM mtRAG benchmark: https://research.ibm.com/publications/mtrag-a-multi-turn-conversational-benchmark-for-evaluating-retrieval-augmented-generation-systems--1
- Microsoft GraphRAG query engine: https://microsoft.github.io/graphrag/query/overview/
- LangGraph agentic RAG tutorial: https://docs.langchain.com/oss/python/langgraph/agentic-rag
- MCP tools/resources/security guidance: https://modelcontextprotocol.io/specification/draft/server/tools

Reviewer smoke prompts to keep healthy:

- `How many drones do we have configured?`
- `What is the swarm formation planned now?`
- `What drone show is planned now and how long will it take?`
- `Is there a drone show uploaded and ready?`
- `Is there any uploaded?` after a drone-show turn
- `What is the scout drone IP?`
- `If I want to add a third drone now, what workflow must be done?`
- `Check latest backend logs and report anything worth mentioning for operation`
- `What does it mean?` after a logs turn
- `What runtime are we in, and how do I switch to SITL safely?`
- `Can you check backend log warnings?`
- `Give me links for setting up a new board, env, and keys.`
- `Give me links for creating a SITL demo.`
- `If I allowed it, what APIs would be needed for takeoff/hold/move/return?`

Doc-link prompts must never fall through to connectivity checks just because
they contain the word `link`; this is covered by
`tests/test_agent_assistant_runtime.py`.

Architecture note: MCP is the external interoperability surface for n8n, Claude
Desktop, VS Code, and other agent clients. The dashboard assistant should not
become a separate ungoverned tool stack; internal assistant adapters and the MCP
endpoint must converge on the same registry, policy engine, audit model, and
curated executors. New GCS APIs may be discovered from OpenAPI metadata, but
they must enter the registry as classified candidates and are not callable until
policy, schemas, safety notes, docs, and tests approve them. Public MDS docs are
available through the same MCP tool menu via `mds.docs.search` and
`mds.docs.chunk.read`; future vector or embedding retrieval should sit behind
that interface rather than bypassing the registry/policy boundary.

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

## MCP Endpoint

The MCP endpoint is mounted at:

- `POST /api/v1/simurgh/mcp`
- `GET /.well-known/oauth-protected-resource`
- `GET /.well-known/oauth-protected-resource/api/v1/simurgh/mcp`

It is off by default and requires both:

```text
MDS_AGENT_ENABLED=true
MDS_MCP_ENABLED=true
```

The default is fail-closed because MCP is an external interoperability surface.
It is production-acceptable to enable MCP only when `MDS_MCP_REQUIRE_AUTH=true`,
dashboard cookie sessions are rejected, and issued bearer tokens have the least-privilege `agent` scope.

Protocol slice:

- Protocol version: `2025-11-25`
- Transport: Streamable HTTP request/response JSON only
- SSE/GET stream: not supported; `GET /api/v1/simurgh/mcp` returns `405`
- Capabilities: `prompts`, `resources`, and `tools`
- MCP tools: `tools/list` returns policy-allowed read-only tools from
  `config/agent_tools.yaml`; `tools/call` executes only read-only route tools
  and approved route-less advisory/docs tools that pass Simurgh policy for the
  `mcp` channel
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

The tool registry remains the source of truth for the MCP menu. Excluded tools,
non-GCS tools, raw command routes, drone-local APIs, destructive routes, and
non-read-only routes are not callable. The route-less
`mds.operator.question.answer` tool is the shared natural-language advisory
wrapper for dashboard chat and external MCP clients; it answers with read-only
context and still blocks direct operational requests. The endpoint rejects
JSON-RPC batching, invalid origins, unsupported protocol headers, unknown tools,
denied tools, and unexpected tool arguments.

### Production MCP Setup

Use this path for n8n, Claude Desktop/VS Code bridges, or any external agent
client that needs the Simurgh tool/resource menu:

1. Enable MCP in the runtime settings or `/etc/mds/gcs.env`:

   ```text
   MDS_AGENT_ENABLED=true
   MDS_MCP_ENABLED=true
   MDS_MCP_REQUIRE_AUTH=true
   MDS_MCP_REQUIRED_SCOPES=agent,admin
   ```

2. Issue a bearer token with `agent` scope from the MDS auth/token workflow.
   Store the token in the client secret store. Do not paste it into docs,
   Telegram, git, screenshots, or chat prompts.

3. Configure the client endpoint:

   ```text
   URL: http(s)://<gcs-host>/api/v1/simurgh/mcp
   Method: POST
   Headers:
     Authorization: Bearer <agent-token>
     Content-Type: application/json
     MCP-Protocol-Version: 2025-11-25
   ```

4. Initialize, then discover resources/tools:

   ```json
   {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","clientInfo":{"name":"mds-client","version":"1.0"},"capabilities":{}}}
   ```

   ```json
   {"jsonrpc":"2.0","id":2,"method":"resources/list","params":{}}
   ```

   ```json
   {"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}
   ```

5. Call read-only tools with `tools/call`. Most route-backed status tools do
   not accept arguments yet; the advisory wrapper accepts one required string,
   docs search accepts a bounded `query`, and `mds.logs.session.read` requires
   `session_id` plus a bounded `limit`:

   ```json
   {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"mds.operator.question.answer","arguments":{"question":"What are the different Drone Show modes?"}}}
   ```

   Unexpected arguments are rejected.

n8n can use an HTTP Request node or MCP-capable node pointed at the endpoint
above. Claude Desktop and VS Code integrations vary by client version: if the
client supports remote Streamable HTTP MCP, configure the URL and bearer token;
if it only supports stdio MCP, place a reviewed local bridge/proxy in front of
this endpoint and keep the token in that bridge environment.

Typed public docs search example:

```json
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"mds.docs.search","arguments":{"query":"SkyBrush show upload","limit":3}}}
```

Bounded docs chunk read example using a chunk id returned by search:

```json
{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"mds.docs.chunk.read","arguments":{"chunk_id":"mds.drone_show:001-01-drone-show-guide","max_chars":2000}}}
```

Typed read-only call example for a single GCS log session:

```json
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"mds.logs.session.read","arguments":{"session_id":"s_20260524_234257","level":"WARNING","limit":20}}}
```

Current MCP tool execution is intentionally limited to read-only route tools
and the read-only advisory wrapper. Mutation wrappers for runtime changes, SITL
lifecycle, mission planning, or real operations require a later slice with typed
input schemas, approval records, operator confirmation UI, audit evidence, and
explicit tests.

External client recipes for n8n, Claude, VS Code, and stdio bridge patterns live
in `docs/guides/simurgh-mcp-clients.md`. Keep that guide in sync whenever the MCP
endpoint, auth model, client support posture, or bridge tooling changes.

### Generated Docs Index

`tools/generate_simurgh_docs_index.py` reads `docs/agent-context/context-index.yaml`
and writes `docs/agent-context/generated/simurgh-docs-index.json`. Only public
resources explicitly marked `searchable: true` or `docs_search: include` are
indexed. Generated files also require both `docs_search: include` and
`generated_safe_for_search: true`; the environment registry is the current
approved generated-reference exception. The generator skips unapproved generated
artifacts, evals, `docs/plans/`, private resources, and raw secret-looking
content.

The runtime docs adapter loads this generated index through
`MDS_AGENT_DOCS_INDEX_FILE` and exposes it through reviewed MCP tools:

- `mds.docs.search`: lexical/tag/heading search over approved public chunks.
- `mds.docs.chunk.read`: bounded chunk retrieval by id.

Search results include canonical context URLs such as
`/api/v1/simurgh/context/mds.drone_show/markdown` and dashboard route hints where
available. The dashboard chat renderer turns those approved routes into links
that open in a new tab. Dashboard-local advisory answers and MCP docs tools use
the same generated docs index/service; the dashboard helper is not a separate
model-visible tool registry. Future vector retrieval can replace or augment the
indexer behind the same tool contract, but it must not ingest private field logs,
secrets, client-only notes, generated candidate artifacts, or unapproved docs.

### Generated OpenAPI Candidates

`tools/generate_simurgh_tool_candidates.py` reads the FastAPI OpenAPI schema and
writes `docs/agent-context/generated/simurgh-openapi-tool-candidates.yaml`.
This artifact is a reviewer menu only. It is not loaded by the runtime registry,
and every generated entry has `callable: false`.

Promotion path:

```text
OpenAPI route
  -> generated non-callable candidate
  -> human classification in config/agent_tools.yaml
  -> policy review in config/agent_policy.yaml
  -> typed input/output contract
  -> docs, tests, safety notes, reviewer approval
  -> MCP tools/list and tools/call exposure
```

This keeps MDS compatible with FastAPI-MCP, FastMCP, MCPify, or a future better
adapter without making any adapter the safety boundary. No FastAPI-MCP, FastMCP,
or MCPify runtime dependency is active in this slice, and no automatic
OpenAPI-to-MCP route exposure is enabled. Auto-discovery speeds up review; it
does not grant execution rights. Route-specific promotions such as the SkyBrush
metrics snapshot are registry entries over auto-discovered API routes, not
separate hardcoded chat branches. The dashboard assistant and external MCP
clients should converge on the same registry/policy/tool executor as capability
coverage grows.

The review endpoint also reports `summary.registry_coverage`. That section
compares generator-eligible read-only routes against `config/agent_tools.yaml`
and groups any still-unpromoted routes by API/dashboard area. Use it as the
slice-planning gate for read-only completion: a route may be visible in the
candidate menu, but it is not callable through MCP or Simurgh until it is
promoted with typed arguments, docs, tests, safety notes, and reviewer approval.

## GCS API Surface

The foundation API exposes metadata/session/audit/assistant routes plus a
read-only MCP tool executor for policy-allowed GCS `GET` routes. It still does
not execute mutation/domain action tools. The dashboard assistant can also
explain the registry-backed capability menu in chat so operators understand
what MCP clients can discover when MCP is enabled. Route-backed tools accept
arguments only when their registry entry has an explicit `input_schema`;
otherwise unexpected arguments are rejected.

The dashboard assistant has a registry-domain bridge for capability questions.
When an operator asks what Simurgh can inspect, query, or expose for a domain
such as SITL, SAR/QuickScout, fleet sidecars, logs, PX4 params, Drone Show,
Swarm Trajectory, origin, or runtime, the answer is built from
`config/agent_tools.yaml` after policy filtering. This is not a separate
hardcoded chat menu and it does not call routes by itself; it lets dashboard
chat and external MCP clients describe the same approved read-only capability
surface while route-backed execution remains behind `tools/call`, typed
arguments, auth, and policy gates. Registry-domain menu answers stay local-only
even for authenticated OpenAI sessions so operator capability discovery remains
fast, deterministic, and identical to the MCP policy-filtered menu.

For concrete read-only state prompts, the dashboard assistant can execute an
approved subset of registry tools through the same internal adapter used by MCP
`tools/call`. The chat planner selects from policy-filtered registry entries
only; it does not scrape raw OpenAPI routes, invent arguments, or bypass
registry exposure. No-argument tools execute directly. Required-argument read
tools execute only when the operator supplied enough explicit, schema-valid
values in the prompt, such as `session_id`, `sidecar`, `hw_id`, `mission_id`,
`profile_id`, `chunk_id`, or `lat`/`lon`; missing IDs are not guessed.

Current coverage is intentionally bounded to safe status/catalog evidence such
as SITL state, SAR/QuickScout mission catalogs or explicit mission status, Fleet
Ops sidecar/network tables and specific nodes, bounded log-session reads,
runtime posture, environment registry state, PX4 parameter policy/profile
summaries, origin/launch-position/elevation evidence, Swarm Trajectory
status/validation/leaders, SkyBrush validation/safety/metrics snapshots, fleet
candidates, and GCS health.

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
- `POST /api/v1/simurgh/assistant/turns/stream`

The stream route returns `text/event-stream` and emits bounded events for the
dashboard chat UI:

- `progress`: short stage labels such as policy/context/tool/provider work
- `delta`: text chunks for incremental rendering inside the assistant bubble
- `final`: the same sanitized assistant-turn payload returned by the normal
  `POST /api/v1/simurgh/assistant/turns` route
- `done`: final id/session marker
- `error`: sanitized status/detail when orchestration fails

The stream route is for first-party dashboard UX. It is generated as an
OpenAPI/MCP candidate but remains `callable: false`, `exclude`, and
review-only. External MCP clients should continue to use
`POST /api/v1/simurgh/mcp`; MCP itself still uses Streamable HTTP request/response
JSON in this slice, not SSE.

Session creation requires `MDS_AGENT_ENABLED=true`. If an installation disables
the agent runtime, operators and maintainers can still inspect policy, tool
metadata, and context resources.

Assistant turns also require `MDS_AGENT_ENABLED=true`. The default adapter is
deterministic `mock`. The optional `openai` adapter is advisory-only and calls
the OpenAI Responses API after the same policy, actor/session, message-size,
metadata-size, and public-context checks pass. Provider adapters assemble public
context from `config/agent_assistant.yaml` and
`docs/agent-context/context-index.yaml`, record an audit hash, and do not expose
model-driven tools in this slice. Common MDS state questions may be answered
before the provider call by local read-only GCS context tools backed by the same
registry/policy direction used for MCP. If `MDS_AGENT_PROVIDER` is set to an
unsupported provider, the route returns a not-implemented error.

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
and the assistant history for the dashboard actor. The current Simurgh Operator
page is a minimal chat surface with compact runtime settings. New assistant
turns stream progress and answer chunks in the active message bubble, while the
final saved local history still stores only completed user/assistant messages.
It does not expose direct drone APIs, raw command submission, or executable
flight controls.

The navigation label is **Simurgh Operator** under the System section.

## Development Notes

Run focused validation after changing Simurgh artifacts:

```bash
pytest tests/test_agent_assistant_evals.py tests/test_agent_assistant_runtime.py tests/test_gcs_simurgh_assistant.py tests/test_gcs_simurgh_mcp.py tests/test_gcs_simurgh_routes.py tests/test_agent_runtime_foundation.py tests/test_api_route_inventory.py tests/test_env_registry.py
python3 tools/generate_mds_env_reference.py --check
python3 tools/generate_simurgh_tool_candidates.py --check
pytest tests/test_simurgh_tool_candidate_generator.py
cd app/dashboard/drone-dashboard && npm test -- --runTestsByPath src/pages/SimurghOperatorPage.test.js src/services/gcsApiService.test.js src/config/routeDocs.test.js src/components/SidebarMenu.test.js src/App.test.js --watchAll=false
```

If docs and code disagree, treat the stale doc as a product bug. Fix the doc or
the code before exposing the context to a model or MCP client.

### Orchestration Trace And Language Profile

Assistant turn responses include a sanitized `trace` object for reviewer/test review. It exposes provider/model, session topic, query domain/confidence, selected local tool intent, retrieved-context count, safety posture, and a language/tone profile. It never includes the raw operator message, secrets, or returned provider content.

The language profile is deterministic metadata from `gcs-server/agent_runtime/language.py`. Current behavior is:

- English/operator prompts continue through deterministic routing and local read-only tools.
- Non-English prompts are detected by language/script/tone and provider prompts receive same-language response guidance when the turn safely reaches the provider.
- Query adaptation before tool routing is handled by `gcs-server/agent_runtime/query_adaptation.py` using reviewed rules from `config/agent_query_adaptation.yaml`.
- The adapter produces a canonical routing text for intent detection and retrieval while trace metadata exposes only language, strategy, and rule ids. Raw operator text is not exposed in trace/history.
- Local read-only tools can now route common typo-heavy and multilingual fleet/show/log/setup prompts through the same MCP-backed advisory tool path.
- Local read-only answers are still rendered in English. Full localized rendering for GCS-state answers remains a future slice because sending fleet IPs, logs, or live config to an external model just to translate would be a data-egress risk.

This keeps the current demo safe while giving the architecture a clean migration path toward broader multilingual query rewrite, hybrid retrieval, local/approved translation adapters, and localized answer rendering.

### Answer Composer And Follow-Up Behavior

Simurgh local read-only answers use `gcs-server/agent_runtime/answer_composer.py` for compact Markdown composition. The composer is formatting-only: it cannot route prompts, retrieve docs, call tools, bypass policy, or execute actions. High-risk answers should be evidence-first, include only clickable dashboard/doc routes, and end with an explicit no-action statement when relevant.

Session metadata keeps a short safe topic memory (`last_domain`, `last_intent`, `last_response_mode`). Follow-up prompts such as “what does it mean?”, “and the scout IP?”, “what scripts should I use?”, or “can n8n use that same menu?” should use that topic to choose the right read-only evidence source instead of repeating a stale block or falling back to generic provider text.

The session store also keeps a bounded private previous-answer context for referential follow-ups such as “say it in Persian” or “make that shorter”. This context is in-memory only: it is not exposed through session APIs, assistant history, audit payloads, or MCP resources. When the configured provider is available and the request passes provider-auth and safety gates, Simurgh can transform the previous answer without re-routing the prompt to an unrelated capability catalog or inventing new facts.

Follow-up routing is now available for the current local MDS domains: drone-show, logs, fleet, swarm, setup, runtime, capabilities/MCP, and SITL. The topic only affects read-only routing and response mode. It does not authorize actions, relax sensitive-input filters, change provider-auth requirements, or bypass the circuit breaker.

When exact intent rules do not match, Simurgh may use the shared query planner as a bounded fallback to select a local read-only tool. That fallback only applies to real operator questions/requests and uses word-boundary domain matching so short terms such as `ip` do not accidentally match unrelated words such as `scripts`. Polite phrasing such as “can you ...” must not imply a capabilities/MCP question by itself; the capability catalog should appear only for explicit capability, tool, API, or MCP-menu requests.

Backend log answers distinguish between status and interpretation. A first log check may show the latest warning/error table; a follow-up such as “does this mean something is wrong?” should return a direct operational verdict instead of repeating the same table. Without an explicit time window, “latest logs” means the current/newest GCS session so a stale error from an older service run does not look current after a restart. Requests with explicit windows such as “last 30 minutes” are filtered to that parsed window when timestamps are available and may include previous sessions inside that window. Text log lines with time-only prefixes such as `03:17:15.633`, JSONL `time`/`timestamp` aliases, and embedded clocks are displayed with the best available time rather than `time n/a`. The scanner prefers the newest session JSONL logs, ignores stale fallback text logs when fresh session logs exist, and suppresses routine unauthenticated dashboard polling noise from the operator warning summary while preserving real POST/non-routine auth failures and server errors.

### Composer Coverage Expansion

The reusable answer composer now covers the operator-visible local answer surfaces: fleet/IP summaries, connectivity, runtime posture, GCS/system health, environment registry summaries, Fleet Ops sidecar dashboards, PX4 parameter profile support, origin/launch-position status, command tracker summaries, MCP/capability catalog, mission-mode comparison, drone-show status/readiness, and backend log summaries. These answers still come from read-only GCS/MDS evidence and still flow through the same policy-gated advisory tool used by MCP. Authenticated OpenAI composition is a presentation layer over that evidence, not a separate source of truth and not a model tool-execution path.

Read-only routing for these surfaces must stay semantic rather than prompt-specific. For example, PX4/ArduPilot support questions must not be routed to PX4 parameter profile status unless the operator explicitly asks about parameters/profiles/snapshots/diffs. Board, drone, or companion setup questions must not be routed to the environment registry merely because they mention env keys; they should remain in setup/onboarding guidance and link to the environment page only where relevant.

Tables are intentional for compact operational comparison, but each answer must remain readable as plain Markdown for clients that do not render rich UI. New local tools should prefer `AnswerComposer` before adding custom string templates.

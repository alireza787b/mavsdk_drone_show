# Simurgh Tool Usage Guidelines

Every tool exposed to a model or MCP client must have an entry in
`config/agent_tools.yaml`.

Tool registry entries must define:

- stable `id`
- title and description
- exposure: `allow`, `guarded`, or `exclude`
- risk class
- GCS/drone/external boundary
- route method and path when route-backed
- input schema for every callable argument, including path/query parameters
- role expectation
- side effects
- sensitivity labels
- docs and safety notes

Interpretation rules:

- `allow` means the tool can run after policy checks pass.
- `guarded` means policy must require explicit approval before execution.
- `exclude` means the tool is documented as intentionally unavailable.
- `read_only=true` does not automatically make a tool safe; telemetry, logs, and
  repo state can still be sensitive.
- `read_only=false` tools are denied in `read_only` mode, even when the risk
  class is otherwise allowed by that mode.
- `runtime_modes` is binding; a tool cannot be used outside the modes declared
  in its registry entry.
- A model must not infer permission from a raw API route that is not in the
  registry.
- A model must not translate a blocked request into a lower-level route call.
- OpenAPI discovery output is a candidate menu, not an authorization decision.
  Generated candidates are not callable until promoted into
  `config/agent_tools.yaml`, reviewed against `config/agent_policy.yaml`, tested,
  documented, and approved.
- A route-backed tool without `input_schema` accepts no arguments. Any path or
  query parameter support must be explicit, bounded, and validated before the
  internal ASGI request is built.
- MCP authentication is not tool authorization. Metadata-only MCP access
  requires bearer auth by default, and every future tool call must still pass
  registry and policy checks.

Adapters should return structured errors for denied or approval-required tools
so operators can see the exact policy reason.

Current callable argument scope:

- `mds.operator.question.answer` accepts one bounded `question` string and an
  optional safe `conversation_topic` enum for dashboard/MCP follow-up routing.
  Its structured result may include `response_mode` (`status`, `interpret`,
  `workflow`, `compare`, or `capability`) so the same evidence source can answer
  fresh status prompts and interpretive follow-ups without exposing raw
  transcript text. It stays read-only/advisory and must not execute actions.
- `mds.docs.search` accepts a bounded public documentation query plus optional
  tag/audience filters and returns generated index chunks with canonical
  context URLs.
- `mds.docs.chunk.read` accepts one chunk id returned by docs search and a
  bounded `max_chars` value. It reads only from the generated public docs index.
- `mds.logs.session.read` accepts a required sanitized `session_id`, required
  bounded `limit`, and optional log filters. It is for GCS log-session inspection only, not raw flight
  logs, ULog archives, drone-local log actions, or private evidence exports.
- Drone log/ULog inventory questions such as “do we have a ULog stored?” stay
  on the local advisory/read-only path. Simurgh may summarize command-tracker
  records, per-drone log sessions, ULog file metadata, and bounded local ULog
  summary metrics that the approved GCS endpoints already expose. Safe summary
  metrics include duration, topic/sample counts, local-position envelope,
  battery range, command/ack counts, and dropout counts. It must not expose raw
  ULog bytes, raw topic arrays, raw logged-message text, erase actions, browser
  download content, pasted artifacts, streams, or raw ULog/QGC/field-log
  artifacts to a provider or public context.
- SkyBrush show-analysis tools (`mds.shows.skybrush.metrics_snapshot.read`,
  `mds.shows.skybrush.safety_report.read`, and
  `mds.shows.skybrush.validation.read`) accept `{}` only and inspect the current
  processed show package. They do not import, deploy, download, plot, launch, or
  command a show. Dashboard show-readiness answers derive from the current
  metrics snapshot when available so chat stays read-only and responsive.
- `mds.fleet.git_sync.read` uses `GET /api/v1/fleet/git-sync` for Fleet Ops
  sync posture only. It must not run dry-run/apply, pull, push, or dispatch
  `UPDATE_CODE`; those mutation routes remain outside the read-only registry.
- `mds.origin.launch_positions.read` uses `GET /api/v1/origin/launch-positions`
  with MCP/Simurgh arguments constrained to JSON output. Do not expose CSV, KML,
  download, or artifact forms through this registry tool.
- `mds.shows.skybrush.metrics_snapshot.read` uses
  `GET /api/v1/shows/skybrush/metrics/snapshot`, which reads only a current
  cached metrics snapshot and reports unavailable if no current cache exists.
- `GET /api/v1/shows/skybrush/metrics` remains intentionally unexposed as a
  read-only MCP tool because the current route can refresh and write cached
  metrics.

The docs index artifact is
`docs/agent-context/generated/simurgh-docs-index.json`. Regenerate it with
`tools/generate_simurgh_docs_index.py` after approved public docs/context
changes and verify with `--check`. The generator is explicit-include and skips
private resources, evals, generated artifacts, `docs/plans/`, and raw secret
patterns.

The provider-side retrieval context uses the same generated docs index and
`agent_runtime.retrieval` interface as `mds.docs.search` and
`mds.docs.chunk.read`, but it is not itself an executable tool call. Query
planning selects domain tags and rewritten search queries, retrieves bounded
public chunks, and injects them as `retrieved.*` context documents before an
external provider is called. This layer must never bypass the registry, policy,
or MCP authorization rules; factual live/configured GCS state still comes from
reviewed read-only tools, not from documentation search. Future vector, hybrid,
rerank, managed-search, or GraphRAG adapters must preserve the `RetrievalQuery` /
`RetrievalHit` contract and add eval coverage before becoming default.

The OpenAPI candidate artifact is
`docs/agent-context/generated/simurgh-openapi-tool-candidates.yaml`. Treat it as
review input for PM, MCP, safety, backend, and field-ops reviewers.

## Language And Query Adaptation

Simurgh treats language adaptation as an orchestration concern, not a collection of hardcoded demo phrases. Each assistant turn gets a safe language/tone profile before routing. Provider turns receive explicit guidance to answer in the operator language when confidence is reasonable, while preserving exact MDS identifiers, routes, APIs, commands, and document links.

Current query adaptation uses `config/agent_query_adaptation.yaml` and
`agent_runtime.query_adaptation` to produce canonical routing text for
deterministic classifiers and retrieval. That file is a narrow guardrail and
routing aid, not Simurgh's intelligence layer. Do not keep expanding it to
mirror every PM typo, operator habit, language, phrase, or tone. Broad
paraphrase understanding, multilingual interpretation, expertise/tone matching,
and multi-step intent decomposition belong in the structured semantic
understanding layer described below, with deterministic policy still enforcing
what is allowed.

Add a query-adaptation rule only when it fits one of these categories:

- safety, sensitive-data, or blocked-action wording that must be caught before a
  provider call;
- exact MDS/PX4/MAVLink/SITL/Smart Swarm/GCS domain terms and public aliases
  that protect tool routing;
- high-frequency operator typos or multilingual aliases that are backed by a
  sanitized eval case and are too risky to leave to provider-only routing;
- temporary compatibility rules with an explicit removal or replacement plan.

Every new rule needs focused eval coverage because a bad alias can route a real
operator question to the wrong evidence source. If a prompt failure is caused by
missing context selection, target memory, action sequencing, or conversational
understanding, fix that layer instead of adding more aliases.

Current contract:

- Run sensitive-input and blocked-action detection against both original operator text and adapted routing text.
- Keep adapted routing text out of trace/history; expose only language, strategy, confidence, and applied rule ids.
- Evaluate routing quality separately from generation quality.
- Prefer structured rewrite/adaptation output: detected language, normalized intent, domain, response mode, confidence, and refusal/safety notes.
- Do not let localization bypass policy, confirmation, or circuit-breaker layers.
- Do not send local GCS state such as fleet IPs, logs, or runtime config to an external provider purely for translation unless a future approved data-egress policy explicitly permits it.

Target semantic-understanding contract:

- Input is sanitized operator text, session topic/action memory, language/tone
  profile, public capability metadata, and policy posture. Do not include raw
  fleet IPs, logs, credentials, exact coordinates, or private runtime state
  unless the configured data-egress policy explicitly allows it.
- Output is structured and schema-validated: detected language, tone,
  expertise level, normalized intent, domain, task kind, response mode,
  evidence needs, candidate tool domains, target references, possible action
  sequence, confidence, clarifying question, and safety notes.
- The semantic output is advisory routing evidence. It must not authorize an
  action, pick an unsafe target by itself, bypass registry schemas, disable
  confirmation, or override the circuit breaker.
- Deterministic safety checks run before and after semantic understanding on
  both original and normalized text.
- Low-confidence semantic output should trigger either a concise clarification
  or a safe read-only evidence pass, not a generic docs dump.

## Answer Composition Contract

Local MDS tools should separate evidence collection from answer rendering. Use `AnswerComposer` for Markdown that must render cleanly in the dashboard and MCP clients. Do not build new one-off answer templates when a reusable section, bullet list, numbered workflow, or table can express the same evidence.

Follow-up handling must be topic-aware and policy-neutral. A session topic can change response mode from `status` to `interpret`, but it must not authorize actions, weaken blocked-intent checks, or expose secrets. Circuit breaker and approval decisions remain downstream of understanding/composition.

The local MDS router has two layers:

- exact deterministic intent rules for high-confidence fleet, show, swarm, logs, setup, runtime, SITL, MCP, and safety/capability questions;
- a bounded query-plan fallback for real operator questions/requests that exact rules miss;
- a registry-domain capability bridge for questions such as “what APIs/tools can Simurgh use for SAR?”, “what can n8n inspect for fleet sidecars?”, or “what read-only SITL tools are available?”.

Do not use the fallback as a catch-all. Generic provider prompts, such as provider-auth test prompts, must still reach the provider-auth gate. The fallback exists to route safe MDS questions like “what interfaces are exposed to clients like n8n and Claude?” or topic follow-ups like “and the scout IP?” to reviewed read-only tools. Keep word-boundary matching for short domain terms to avoid false positives.

The registry-domain capability bridge must derive its menu from
`config/agent_tools.yaml` filtered by policy. It may summarize matching domains
and required arguments, but it must not execute the route, invent arguments,
or replace onboarding/docs answers. For example, “give me setup docs” should
stay in setup guidance, while “which MCP tools can inspect setup/fleet state?”
should use the registry-domain bridge.

Concrete current-state prompts may use the registry read-execution bridge when
the selected registry tools are policy-allowed and read-only. No-argument tools
may execute directly. Required-argument read tools may execute only when the
operator supplies enough explicit, schema-valid identifiers or coordinates in
the prompt, for example `session_id`, `sidecar`, `hw_id`, `mission_id`,
`profile_id`, `chunk_id`, or `lat`/`lon`. The planner must never guess missing
identifiers, select mutation/action tools, scrape raw OpenAPI routes, or bypass
the registry. Every call still goes through the same registry, policy, internal
ASGI adapter, schema validation, and audit trail as MCP `tools/call`.

Examples include SITL instance/policy state, QuickScout/SAR mission catalogs or
explicit mission status, Fleet Ops sidecar tables/nodes and git-sync posture,
bounded log-session reads, JSON-only origin launch positions, origin/deviation/
elevation evidence, environment registry state, PX4 parameter policy/profile
summaries, and Drone Show validation/safety/metrics snapshots. Capability
questions remain menu-only, and mutation/action terms are blocked before
planning.

### Composer Migration Status

Current local answers using the shared composer include fleet/IP lookup, connectivity, runtime posture, MCP capability catalog, registry-domain capability summaries, registry read-execution summaries, mission-mode comparison, drone-show status/readiness, and backend log summaries. This keeps response formatting predictable across Dashboard chat and MCP clients.

The current external-protocol alignment remains:
- MCP tools expose schema-described operations and may return links/resources as context; MDS keeps actions out of the callable set until policy, schema, docs, and tests approve them. Reference: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- OpenAI Responses provider calls remain tool-disabled for text generation; local/MCP tool execution is handled by MDS policy gates, not by free-form provider tool calls. Reference: https://developers.openai.com/api/reference/resources/responses/methods/create

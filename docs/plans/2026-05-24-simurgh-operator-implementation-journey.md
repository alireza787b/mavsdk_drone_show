# Simurgh Operator Implementation Journey - 2026-05-24

This log is for future Codex and reviewer sessions. Read it before continuing
Simurgh AI/MCP work, then read `docs/guides/simurgh-operator.md`,
`config/agent_policy.yaml`, `config/agent_tools.yaml`, and
`config/agent_assistant.yaml`.

## Operating Rules

- Build, test, and deploy from Hetzner (`/root/catchadrone_gcs`). Keep Linode
  clean; do not run heavy npm/pytest/build work there.
- Production/client GCS stays real mode but non-executing for Simurgh:
  `MDS_MODE=real`,
  `MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`,
  `MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true`.
- Default installs keep `MDS_MCP_ENABLED=false`, but the current client demo
  now has MCP enabled behind bearer auth for PM/external-client testing. Keep
  `MDS_MCP_REQUIRE_AUTH=true` and `MDS_MCP_REQUIRED_SCOPES=agent,admin`.
- Do not put API keys in docs, commits, shell output, tests, Telegram, or logs.
  The OpenAI key file lives at `/etc/mds/secrets/openai_api_key` on Hetzner.

## Current Slice Completed

- Replaced the noisy Simurgh page with a minimal ChatGPT-style operator chat and
  compact runtime settings.
- Added hot-applied Simurgh runtime settings endpoints for agent/MCP/circuit
  breaker/always-confirm/provider/model toggles.
- Added local read-only MDS context answers for PM-critical prompts: fleet count,
  drone IP lookup, live presence, swarm topology/clusters/offsets, show length,
  offset editing guidance, runtime posture, and capability menu.
- Added a disabled-by-default MCP HTTP endpoint with resources plus
  `tools/list` and `tools/call` for policy-approved read-only GCS GET tools.
- MCP and the assistant now point toward the same registry/policy model:
  `config/agent_tools.yaml` plus `config/agent_policy.yaml` are the control
  surface. Dashboard local answers are a safety bridge, not a separate long-term
  tool world.
- Updated Simurgh guide and env registry docs.

## PM MCP Clarification

The PM expectation is directionally correct: MDS should expose a reusable tool
menu through MCP so external clients and Simurgh can reason over current GCS
capabilities. The safety correction is that MDS must not auto-execute every new
API just because it appears in OpenAPI. New APIs should be auto-discovered as
registry candidates, then promoted only after classification, input/output
schemas, safety notes, docs, policy, auth/approval behavior, and tests are in
place.

Current implementation:

- External clients use `POST /api/v1/simurgh/mcp` when `MDS_MCP_ENABLED=true`.
- MCP `tools/list` reads policy-allowed tools from `config/agent_tools.yaml`.
- MCP `tools/call` currently executes only no-argument read-only GET routes that
  pass policy for channel `mcp`.
- Dashboard assistant answers common operational questions locally to avoid
  sending sensitive live state to a provider. It does not yet run an LLM tool
  loop over the MCP executor.

Next architecture target:

- Extract one shared capability executor used by MCP and dashboard assistant.
- Add typed arguments for safe read-only query/path-param tools.
- Add OpenAPI-to-registry candidate generation, but keep candidate tools denied
  until reviewed.
- Later, add guarded mutation wrappers only with explicit approval records,
  operator confirmation UI, audit evidence, and SITL-first tests.

## Validation Snapshot

Run again after each slice on Hetzner:

```bash
PYTHONPATH=$PWD:$PWD/gcs-server:$PWD/src ./venv/bin/pytest \
  tests/test_gcs_simurgh_mcp.py \
  tests/test_gcs_simurgh_routes.py \
  tests/test_agent_assistant_runtime.py \
  tests/test_agent_assistant_evals.py \
  tests/test_env_registry.py -q

cd app/dashboard/drone-dashboard
CI=true npm test -- SimurghOperatorPage.test.js --runInBand
npm run build
npm run audit:ui
```

Before production reload, verify `/etc/mds/gcs.env` still has the safety flags
listed above. After reload, smoke test runtime settings, representative chat
prompts, and OpenAI connectivity without enabling real commands.

## Reviewer Checklist

- Backend/API reviewer: policy gates deny mutation, drone-local APIs, raw command
  routes, and MCP when disabled.
- MCP/OpenAPI reviewer: `tools/list` and `tools/call` follow MCP semantics;
  future OpenAPI import is candidate-only.
- AI agent reviewer: provider prompts and context stay config-driven; sensitive
  field evidence is blocked before provider calls.
- UI/UX reviewer: Simurgh remains a clean chat surface with minimal controls,
  no debug/doc walls, and no confusing mode labels.
- Drone/PX4/field reviewer: production remains real mode, read-only for
  Simurgh, and circuit-broken for any future actions.
- PM reviewer: docs and dashboard behavior match; no stale or contradictory
  instructions are left for operators or future agents.

## PM Follow-Up Fix - 2026-05-24

PM testing found that later chat prompts were not reliable enough: doc-link
requests were incorrectly routed as connectivity checks, SITL/runtime guidance
was generic, backend log questions said logs were unavailable, and action
capability questions returned a confusing blocked/mock response. The follow-up
slice fixed the local intent router and read-only answers:

- board setup/env/key doc links now point to `/fleet-enrollment`, `/fleet-ops`,
  `/fleet-ops/wifi`, `/fleet-ops/mavlink`, `/environments`, and the matching
  repo docs;
- SITL questions now include the current GCS mode plus
  `bash app/linux_dashboard_start.sh --sitl` and `--prod --sitl`;
- swarm formation explains when no follower formation is configured and links
  `/swarm-design` plus `/swarm-trajectory`;
- show answers warn that multiple show asset sources can exist and the operator
  must confirm the active package in `/manage-drone-show`;
- backend warning questions summarize recent unified GCS log sources and link
  `/logs` plus `docs/guides/logging-system.md`;
- action-capability prompts explain that raw commands/direct drone APIs remain
  excluded and describe the future approved wrapper requirements.

Regression coverage was added in `tests/test_agent_assistant_runtime.py` for the
exact PM prompt family so future changes do not regress into generic provider
answers or wrong local tools.

## Production Reload / Smoke Notes - 2026-05-24

- The standard `app/linux_dashboard_start.sh --prod --real` path runs repo sync
  first. During this slice it auto-stashed the uncommitted patch and reset to
  `origin/main`; the stash was reapplied, the patch was retested, and production
  was restarted manually from the patched tree. Before the next normal launcher
  restart, commit/merge this slice so the launcher does not drop it again.
- Removed stale `MDS_AGENT_MODE` and `MDS_AGENT_REAL_COMMANDS_ENABLED` from
  `/etc/mds/gcs.env`. Runtime now uses canonical `MDS_MODE` plus the Simurgh
  circuit breaker and always-confirm flags.
- Final verification on Hetzner:
  - backend Simurgh/env subset: 120 passed;
  - focused provider/local prompt tests after smoke fix: 11 passed;
  - Simurgh frontend Jest page test: 5 passed;
  - dashboard production build: compiled under NVM Node 22.22.2 / npm 10.9.7;
  - live OpenAI provider smoke: passed, `openai-responses-v1`, model
    `gpt-5.4-mini`, no tool calls, no raw content printed;
  - production health: `GET /api/v1/system/health` ok, dashboard `/simurgh`
    returned 200, unauthenticated Simurgh API correctly returned
    `authentication_required`.
- Superseded by the follow-up slice below: production now remains
  `MDS_MODE=real`, `MDS_MCP_ENABLED=true`,
  `MDS_MCP_REQUIRE_AUTH=true`, `MDS_MCP_REQUIRED_SCOPES=agent,admin`,
  `MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`, and
  `MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true`.

## Follow-Up Slice - Clickable Links, SkyBrush Upload Help, MCP Enablement - 2026-05-24

PM retest found that `How to upload skybrush drone show` was routed to the loaded-show status answer and that route/doc references were visible but not clickable. Root cause: the local intent classifier matched generic SkyBrush/show words before upload/import/how-to language, and the chat renderer only linked explicit markdown links, not safe bare dashboard routes or known docs paths.

Changes completed on Hetzner:

- added `show_upload_help` intent and answer in `gcs-server/agent_runtime/mds_read_tools.py`;
- converted show/swarm/log/action guidance to explicit markdown links for dashboard routes and context resources;
- added `mds.drone_show` and `mds.swarm_trajectory` public context resources;
- added frontend auto-linking for safe bare dashboard routes, `/api/...` paths, and known docs markdown paths;
- added backend and frontend regression tests for the exact SkyBrush upload/link failure;
- documented production MCP setup in `docs/guides/simurgh-operator.md`;
- enabled `MDS_MCP_ENABLED=true` on the client production env while keeping `MDS_MCP_REQUIRE_AUTH=true`, `MDS_MCP_REQUIRED_SCOPES=agent,admin`, `MDS_MODE=real`, circuit breaker on, and always-confirm on;
- created an agent-scoped MCP token at `/etc/mds/secrets/simurgh_mcp_agent_token` with mode `0600` for PM/external-client smoke only. The raw token was not printed or copied into docs/reports.

Validation on Hetzner:

- `tests/test_gcs_simurgh_mcp.py tests/test_gcs_simurgh_routes.py tests/test_agent_assistant_runtime.py tests/test_agent_assistant_evals.py tests/test_env_registry.py -q`: 122 passed;
- `npm test -- --runInBand --watchAll=false src/pages/SimurghOperatorPage.test.js`: 7 passed;
- `CI=false npm run build`: compiled under NVM Node 22;
- production smoke: health ok, dashboard `/simurgh` 200, unauthenticated Simurgh/MCP requests return `authentication_required`, authenticated MCP initialize uses protocol `2025-11-25`, `resources/list` returns 28 resources, `tools/list` returns 21 read-only tools;
- authenticated assistant smoke for `How to upload skybrush drone show` returned `SkyBrush show upload workflow` and did not return `Loaded show state`.

Reviewer notes:

- MCP is now on in the client demo because it is read-only, bearer-auth protected, and dashboard cookie sessions are rejected for MCP.
- This does not expose drone-local APIs, raw commands, mutation routes, or action wrappers. `agent` bearer tokens are also restricted by middleware to Simurgh/MCP paths, so the MCP token cannot be reused against general GCS mutation APIs.
- Remaining architecture work is still to converge dashboard assistant tool execution and MCP on one shared capability executor, then add typed read-only arguments and OpenAPI candidate generation with deny-by-default review.

## Follow-Up Slice - Show Status Semantics And Link Allowlist - 2026-05-25

PM retest found a second show-intent ambiguity: `Whay drone show is uploaded
now and how long it takes?` was interpreted as upload workflow guidance because
`uploaded` contained the token `upload`. The fix was deliberately generic, not
hardcoded to that sentence:

- added a reusable `show_status` classifier for show-state/time words such as
  uploaded now, loaded now, planned now, current package, how long, duration,
  length, and takes;
- made `show_upload_help` require real upload/import/deploy/help intent terms
  with word-boundary matching, so `uploaded` no longer means `upload`;
- ordered show-state detection before upload-help and generic show handling;
- restricted chat auto-linking to known dashboard routes, approved Simurgh
  context markdown routes, and official external docs. Bare GCS API endpoint
  names remain text unless they are explicitly emitted as approved docs links;
- changed safe markdown links to open in a new tab.

Validation on Hetzner after this slice:

- focused backend prompt parameter test: 11 passed, including the PM typo/status
  wording and the upload-workflow wording;
- focused Simurgh/env backend suite: 123 passed;
- Simurgh frontend Jest page test: 7 passed, including new-tab behavior and the
  rule that `/api/v1/shows/skybrush/import` is not rendered as a fake link;
- dashboard production build: compiled under NVM Node 22;
- production smoke: health 200, dashboard `/simurgh` 200, agent token denied
  command API with `403 permission_denied`, MCP initialize returned protocol
  `2025-11-25`, show-status prompt returned loaded show/duration, upload-help
  prompt returned SkyBrush workflow, and log prompt returned recent warning
  summary.

## Follow-Up Slice - Shared Read-Only Tool Executor - 2026-05-25

Extracted the first shared capability execution boundary so MCP and the
dashboard assistant no longer maintain separate policy/registry filtering logic:

- added `gcs-server/agent_runtime/tool_executor.py` with policy-filtered
  read-only tool discovery, registry summary, and no-argument internal GCS GET
  execution through ASGI;
- moved MCP `tools/list` and `tools/call` in `api_routes/simurgh.py` onto that
  shared executor;
- kept mutation/action/drone-local/raw-command routes excluded by the same
  policy gate and read-only route predicate;
- connected the assistant capability catalog to the same shared catalog summary;
- preserved the existing synthesized MDS answers for PM operational questions.

Validation on Hetzner after this slice:

- py_compile passed for `tool_executor.py`, `api_routes/simurgh.py`, and
  `mds_read_tools.py`;
- targeted MCP/assistant regression check: 12 passed;
- focused Simurgh/MCP/env backend suite: 123 passed;
- production services restarted from the patched tree, reusing the existing
  dashboard build because this was backend-only;
- production smoke: health 200, dashboard `/simurgh` 200, MCP `tools/list`
  returned 21 read-only tools, MCP `tools/call` for `mds.system.health.read`
  returned structured health content, agent token was denied on command API with
  `403 permission_denied`, show-status prompt remained correct, and assistant

## Follow-Up Slice - MCP Prompt/Resource Correction And Safety-Layer Audit - 2026-05-25

PM retest found the most important architecture regression so far: the prompt
`What's the difference of quick scoute and swarm trajectory mode` was answered
with current swarm geometry. Two independent reviewer passes agreed on the root
cause: `mds_read_tools.py` was acting like a broad keyword router, and the
assistant path preferred that local router before provider reasoning or an MCP
prompt/resource model. The bad rule was effectively "contains swarm => swarm
topology," so conceptual workflow questions could be hijacked by live/config
state tools.

Corrective slice completed on Hetzner:

- added public context resources for `mds.quickscout`,
  `mds.mission_planning_workspace`, and `mds.swarm_trajectory`;
- added MCP `prompts/list` and `prompts/get`, including
  `mds.compare_mission_modes`, with embedded QuickScout / Swarm Trajectory /
  Mission Planning Workspace resources;
- added a conceptual `mission_mode_comparison` answer path that explicitly
  separates static workflow knowledge from live swarm topology;
- kept direct formation questions such as `what is swarm formation planned now?`
  routed to `swarm_topology`;
- updated regression tests so QuickScout vs Swarm Trajectory comparison cannot
  contain `Configured/planned swarm geometry` or cluster dumps;
- restricted agent-scoped bearer tokens to Simurgh/MCP paths in middleware and
  verified that the same token is denied on `/api/v1/commands`;
- adjusted Simurgh policy ordering so always-confirm/approval is evaluated
  before the final circuit-breaker no-execute stop for future executable tools;
- made Simurgh policy fail closed if canonical `MDS_MODE` is invalid instead of
  silently falling back to a policy profile;
- updated the operator guide, safety policy, env registry, and generated env
  reference to describe the simplified model: `MDS_MODE` is runtime posture,
  always-confirm is the approval gate, circuit breaker is the final execution
  stop.

Validation on Hetzner:

- targeted policy/security/PM prompt tests: 15 passed;
- focused Simurgh/backend/env suite including foundation, MCP, routes,
  assistant runtime, evals, and env registry: 145 passed;
- production services restarted manually from the patched tree;
- production smoke: health 200, dashboard `/simurgh` 200, `MDS_MODE=real`, MCP
  enabled with auth, circuit breaker on, always-confirm on, OpenAI provider/key
  configured;
- MCP initialize advertises `prompts`, `resources`, and `tools`;
- MCP `prompts/list` includes `mds.compare_mission_modes`; `prompts/get`
  embeds QuickScout and Swarm Trajectory resources;
- assistant smoke for QuickScout vs Swarm Trajectory returns conceptual workflow
  comparison and does not return geometry;
- assistant smoke for swarm formation still returns planned geometry;
- assistant smoke for show status still returns loaded show/duration, not upload
  workflow;
- live provider smoke with a non-local prompt reached OpenAI using the configured
  `gpt-5.4-mini` model and returned successfully;
- cleanup checks passed: `git diff --check`, no `*.orig`, and no OpenAI/OpenRouter
  key patterns in repo files outside allowed test placeholders.

Reviewer decision: approved for authenticated PM retest of this slice. The
architecture is improved but not finished. Remaining direction is MCP-first:
make dashboard chat consume the same registry/resource/prompt/tool interface as
external MCP clients, add typed read-only arguments, add OpenAPI-to-registry
candidate generation that is denied by default until reviewed, then only later
add guarded action wrappers after SITL-first validation and explicit approval UI.

## Hotfix Slice - Drone Show Modes / Launch Modes Prompt - 2026-05-25

PM retest found another safety-router false positive: `what ar ediffernt modes
of drone show and theri deiffernt launch modes` was locally blocked because
`launch` is a blocked operational word. This was a conceptual docs/workflow
question, not an execution request.

Fix completed on Hetzner:

- added `show_modes_help` read-only intent for Drone Show workflow families and
  launch/control modes;
- added a narrow safe bypass for conceptual read-only intents that contain
  blocked action words, while keeping direct execution requests blocked;
- added `mds.origin_system` to the public context index for origin/launch-mode
  reference material;
- added regression coverage for the PM typo prompt and for `Can you launch the
  drone show now?`, which must still block.

Validation:

- targeted assistant regression: 15 passed;
- focused Simurgh backend suite: 147 passed;
- production restart completed on Hetzner;
- production smoke confirmed the typo-heavy modes prompt returns the conceptual
  Drone Show workflow/control-mode answer via `mds-tools`, not a blocked safety
  response or loaded-show status;
- direct launch request still blocks before provider/tool execution;
- cleanup checks passed: `git diff --check`, no `*.orig`, no key patterns in
  repo files.



## MCP-First Shared Advisory Tool Slice - 2026-05-25

PM asked whether MDS should use FastAPI-MCP, FastMCP, MCPify, or another
auto-MCP generator instead of manual MCP code, and whether future GCS APIs can
become automatically available to agents.

Decision for this slice:

- do not blindly expose every FastAPI/OpenAPI route to agents;
- keep `config/agent_tools.yaml` and `config/agent_policy.yaml` as the reviewed
  safety gate;
- add a route-less registry tool, `mds.operator.question.answer`, so dashboard
  chat and external MCP clients share one natural-language read-only advisory
  wrapper;
- route dashboard deterministic/local answers through the same policy-allowed
  registry executor used by MCP instead of calling `mds_read_tools` directly;
- keep direct action requests blocked before provider/tool execution.

Implementation completed on Hetzner:

- `gcs-server/agent_runtime/tool_executor.py` now supports both read-only GCS
  route tools and approved route-less advisory tools;
- `config/agent_tools.yaml` registers `mds.operator.question.answer` with a
  typed `question` input schema;
- `gcs-server/agent_runtime/assistant.py` calls the registry-backed advisory
  tool for local MDS answers and records the tool id/intent in audit metadata;
- MCP `tools/list` now advertises the advisory wrapper, and `tools/call` can use
  it for natural-language MDS questions;
- `docs/guides/simurgh-operator.md` documents the shared advisory tool and the
  MCP setup contract.

MCP framework conclusion:

- FastAPI-MCP is a strong candidate for future auto-discovery because it mounts
  a FastAPI app as MCP, preserves schemas/docs, supports auth, and uses ASGI.
- FastMCP is a strong Python MCP framework for custom tools/resources/prompts,
  clients, auth, and production MCP apps.
- MCPify/OpenAPI gateways are useful for generic external APIs, but less ideal
  as the primary safety boundary for a drone GCS.
- For MDS production safety, generators should create reviewed candidate entries,
  not directly callable tools. The planned path remains:
  OpenAPI route -> generated candidate -> registry classification -> policy ->
  tests/docs/reviewer approval -> MCP exposure.

Docs/knowledge roadmap added to remaining slices: build a generated doc index
with tags/chunks first, then add a read-only docs search/retrieval tool. A vector
store or embedding index can be added behind that interface later, but public
context resources remain the auditable source of truth and no private logs or
secrets may be embedded.

Validation:

- targeted MCP/advisory/dashboard tests: 3 passed;
- focused Simurgh/backend/env suite: 147 passed;
- production services restarted from the patched Hetzner tree;
- production smoke confirmed health 200, dashboard `/simurgh` 200, authenticated
  Simurgh status `MDS_MODE=real`, MCP enabled, circuit breaker on, OpenAI
  provider configured;
- MCP `tools/list` advertises `mds.operator.question.answer`;
- MCP `tools/call` answers the PM typo-heavy Drone Show modes / launch modes
  prompt through the advisory wrapper;
- MCP and dashboard assistant direct launch requests remain blocked before any
  command path.


## Typed MCP Arguments And OpenAPI Candidate Slice - 2026-05-25

PM asked whether future GCS APIs can appear automatically in the MCP capability
menu without creating a patchy, hardcoded assistant layer. Reviewer decision:
yes for discovery, no for automatic execution.

Implementation completed on Hetzner:

- extended the shared Simurgh read-only executor to validate explicit JSON-schema
  input contracts before building internal ASGI requests;
- added typed `mds.logs.session.read` MCP support for one bounded GCS log session
  with sanitized path/query arguments and required `limit`;
- kept route tools without input schemas strict: any unexpected argument is
  rejected;
- added `tools/generate_simurgh_tool_candidates.py`, which emits a deterministic
  OpenAPI candidate artifact at
  `docs/agent-context/generated/simurgh-openapi-tool-candidates.yaml`;
- every generated candidate is `callable: false`, `review_status: needs_review`,
  and outside the runtime registry until promoted through policy, docs, tests,
  and reviewer approval;
- added context-index and guide references so future agents can find the artifact
  but must not treat it as a callable tool list.

Targeted validation before full smoke:

- typed MCP log-session route test and path-param validation: passed;
- candidate generator unit tests and `--check`: passed;
- reviewer feedback: approved the hybrid architecture, with the warning that
  external frameworks such as FastAPI-MCP, FastMCP, and MCPify should remain
  swappable adapters, not the MDS safety boundary.

## Final Validation / Handoff Checkpoint - 2026-05-25

Completed after the typed MCP argument and OpenAPI candidate slice:

- Fixed a reviewer-found routing issue where direct wording such as "Can you arm
  drone 1?" was incorrectly treated as an action-capability question. Direct
  execution wording now stays blocked; explanatory capability questions still
  receive read-only tool/API guidance.
- Rebuilt and restarted Hetzner production from the current tree. Runtime remains
  `MDS_MODE=real`; Simurgh circuit breaker and always-confirm remain enabled.
- Reconfirmed the dashboard build and production smoke after restart.

Validation:

- Backend focused Simurgh suite: `188 passed in 84.20s`.
- Dashboard Simurgh test: `7 passed`.
- Dashboard production build under Node `v22.22.2`: success.
- Live OpenAI provider smoke: success with tools disabled and `store=false`.
- Production smoke: `SMOKE_PASSED` after restart.

Important operational note:

- Local `mds-tools` answers intentionally take precedence for MDS-owned
  fleet/show/swarm/log/runtime/docs prompts. OpenAI is used for non-local
  advisory prompts or forced provider smoke, with tools disabled. This prevents
  model drift on facts the GCS already owns while keeping provider integration
  available.



## Generated Docs Search Contract Follow-up - 2026-05-25

Reviewer feedback from the docs/MCP slice was implemented on Hetzner:

- tightened generated docs indexing so generated files require both
  `docs_search: include` and `generated_safe_for_search: true`;
- broadened generator secret refusal for provider keys, GitHub tokens, private
  key blocks, bearer tokens, generic API keys, and NetBird setup-key style values;
- removed the nonexistent `/mission-planning` dashboard route hint and added
  `/quickscout` to the safe chat link allowlist;
- tightened `mds.docs.search` and `mds.docs.chunk.read` output schemas with
  explicit nested metadata fields and `additionalProperties=false`;
- documented that dashboard advisory docs answers and MCP docs tools share the
  generated docs index/service, while MCP remains the model-visible tool menu;
- regenerated `docs/agent-context/generated/simurgh-docs-index.json` at 712
  chunks.

Validation completed on Hetzner only:

- generated docs index `--check`: passed;
- focused docs/MCP/context tests: 13 passed;
- broad Simurgh backend suite: 183 passed;
- dashboard Simurgh test: 7 passed;
- dashboard production build: passed.

Production restart/smoke and final reviewer handoff are the next steps for this
slice. Runtime posture must remain `MDS_MODE=real`, MCP enabled/authenticated,
OpenAI configured, circuit breaker on, and always-confirm on.


## Production Smoke / Reviewer Caveat - 2026-05-25

Production was restarted from the current Hetzner tree in tmux `MDS-GCS`.
Posture after restart: API `5030`, dashboard `3030`, `MDS_MODE=real`, MCP
enabled/authenticated, OpenAI provider configured, circuit breaker on, and
always-confirm on.

Smoke passed:

- `/api/v1/system/health` returned `ok`;
- dashboard `/simurgh` returned HTTP 200;
- authenticated Simurgh status confirmed real mode, MCP enabled, provider
  `openai`, circuit breaker on, and always-confirm on;
- direct agent bearer access to general logs stayed denied;
- MCP `tools/list` returned 25 reviewed read-only tools and excluded raw command
  tools;
- `mds.docs.search` returned 3 SkyBrush docs results;
- `mds.docs.chunk.read` returned bounded show-doc content;
- dashboard assistant docs prompt returned `provider=mds-tools` and canonical
  `/api/v1/simurgh/context/.../markdown` source links;
- QuickScout vs Swarm Trajectory prompt returned the conceptual comparison, not
  stale swarm-geometry status.

Cleanup completed: coverage/cache artifacts removed, `git diff --check` clean,
and the repo secret scan found only allowed guard/test regex fixtures.

Reviewer caveat: two additional independent reviewer subagents were attempted
for MCP architecture and PM/operator safety, but both were interrupted by the
Codex usage limit. Their approval is not claimed. This slice is ready for PM
read-only retest based on the validation evidence above; run another independent
reviewer pass before action-capable tool promotion.


## External MCP Client Recipes Slice - 2026-05-25

Added a public MDS-specific connector guide at
`docs/guides/simurgh-mcp-clients.md` and registered it as
`simurgh.mcp_client_recipes` in the context index. The guide covers n8n, Claude,
VS Code, and stdio bridge patterns with conservative production guidance:
private field GCS endpoints must not be exposed publicly just for client
compatibility, Claude remote connectors need reviewed public HTTPS/OAuth or a
gateway, bearer tokens must stay in client credential stores or bridge
environments, and the stdio bridge remains planned/review-required until shipped.

Docs index regenerated to 722 chunks. Dashboard safe-link mapping now converts
`docs/guides/simurgh-mcp-clients.md` to
`/api/v1/simurgh/context/simurgh.mcp_client_recipes/markdown`.

Validation on Hetzner:

- generated docs index `--check`: passed;
- focused backend connector-doc tests: 12 passed;
- dashboard Simurgh test: 7 passed;
- dashboard production build: passed;
- production restart/smoke: passed, with `MDS_MODE=real`, MCP enabled, circuit
  breaker on, and MCP docs search finding `simurgh.mcp_client_recipes`.


## Simurgh Chat Rich Markdown / Copy UX Slice - 2026-05-26

PM reported that an answer containing a Markdown table rendered as one flattened
paragraph. The dashboard renderer was upgraded without changing backend safety
or assistant behavior:

- parses and renders Markdown tables, including the collapsed one-line table
  shape observed in PM testing;
- keeps lists, headings, blockquotes, inline bold/code, safe links, and fenced
  code blocks visually structured;
- adds a copy button to each message;
- adds a code-header and copy-code button to fenced code blocks;
- keeps the existing safe-link allowlist so raw GCS action endpoints remain text.

Validation on Hetzner:

- dashboard Simurgh test: 8 passed;
- dashboard production build: passed;
- production restart/smoke: passed with `MDS_MODE=real`, MCP enabled, OpenAI
  provider configured, circuit breaker on, and the Drone Show launch-mode prompt
  returning `mds-tools` table content.

## Quiet Copy Controls + Show Analysis MCP Slice - 2026-05-26

PM/UI feedback: message copy controls were useful but visually too loud. The
Simurgh chat UI now keeps message/code copy buttons visually quiet by default,
shows them on hover/focus, keeps keyboard focus visible, keeps a larger touch
hit target, and disables motion under `prefers-reduced-motion`. Markdown table,
list, code, bold, and safe-link rendering remains unchanged.

MCP/tooling decision: only two additional SkyBrush show-analysis tools were
promoted in this slice:

- `mds.shows.skybrush.safety_report.read` -> `GET /api/v1/shows/skybrush/safety-report`
- `mds.shows.skybrush.validation.read` -> `GET /api/v1/shows/skybrush/validation`

`GET /api/v1/shows/skybrush/metrics` was deliberately not promoted. Independent
MCP/safety review found that the current metrics GET path can refresh and write
cached metrics, so it is not strictly read-only. The OpenAPI candidate generator
now marks that route as ineligible with `read-through cache refresh can write
state`. The custom preview image route is also marked ineligible as a binary
artifact route. A future metrics slice should split a true read-only snapshot
endpoint from any refresh/write behavior before MCP exposure.

Validation completed on Hetzner only:

- focused MCP/tool-candidate/dashboard checks: passed;
- generated docs index `--check`: passed;
- generated OpenAPI candidate artifact `--check`: passed;
- broad Simurgh backend suite: 183 passed;
- dashboard Simurgh test: 8 passed;
- dashboard production build: passed.

Production restart/smoke:

- cleaned an orphaned old gunicorn process from the first restart attempt;
- restarted clean `MDS-GCS` tmux session with API `5030` and dashboard `3030` listening;
- confirmed `MDS_MODE=real`, assistant provider `openai`, MCP enabled/authenticated,
  circuit breaker on, and always-confirm on;
- authenticated MCP `tools/list` returned 27 read-only tools;
- safety-report and validation tools are exposed and callable;
- metrics, show import/deploy/archive/plot routes, and custom preview are not exposed;
- direct agent bearer access to general logs remains denied;
- dashboard `/simurgh` returned HTTP 200 and built CSS contains the quiet copy-control rules.

## MCP Auto-Discovery + Metrics Snapshot Slice - 2026-05-26

PM raised a valid architecture concern: adding SkyBrush-specific tools must not
mean Simurgh is drifting into a manually hardcoded MCP surface. Review result:
the desired architecture is already the right one, and this slice reinforces it:
OpenAPI auto-discovery creates the review menu, while registry and policy decide
what is callable. MCP then exposes the shared policy-allowed registry. The
assistant can continue converging onto the same registry/resource/tool path.

Implementation:

- added `build_metrics_snapshot_payload()` in `gcs-server/show_management.py`;
- added `GET /api/v1/shows/skybrush/metrics/snapshot` in the show-management router;
- added registry tool `mds.shows.skybrush.metrics_snapshot.read`;
- kept legacy `GET /api/v1/shows/skybrush/metrics` denied for MCP because it can
  refresh/write cached metrics;
- regenerated `docs/agent-context/generated/simurgh-openapi-tool-candidates.yaml`
  to 196 candidates;
- regenerated `docs/agent-context/generated/simurgh-docs-index.json` to 723 chunks;
- updated API docs, Simurgh operator guide, tool-usage guidelines, route inventory,
  MCP tests, show route tests, API HTTP tests, and candidate-generator tests.

Validation on Hetzner only:

- focused MCP/show/candidate/route-inventory suite: 37 passed;
- broad Simurgh/backend/show-management suite: 206 passed;
- OpenAPI candidate generator `--check`: passed;
- docs index generator `--check`: passed;
- Python compile check: passed;
- `git diff --check`: passed.

Reviewer notes:

- Backend/API review: snapshot route has no refresh dependency and reports missing/stale cache without writes.
- MCP/safety review: only the snapshot route is promoted; mutation, binary, legacy refresh, direct drone, and raw command surfaces remain excluded.
- PM/product review: this answers the hardcoding concern by documenting the auto-discovery plus reviewed-promotion path and by keeping future adapter choices open.

Production restart/smoke:

- restarted tmux `MDS-GCS` with exact listener cleanup for ports 3030/5030;
- corrected dashboard serving to use `tools/spa_static_server.py` so `/simurgh`
  deep links return 200;
- confirmed API health OK;
- confirmed `MDS_MODE=real`, OpenAI provider, MCP enabled/authenticated,
  circuit breaker on, and always-confirm on;
- temporary agent-scoped smoke token was created and revoked without printing the
  token;
- authenticated MCP `tools/list` returned 28 tools;
- `mds.shows.skybrush.metrics_snapshot.read` was exposed and callable;
- legacy `mds.shows.skybrush.metrics.read` remained absent;
- safety-report call succeeded;
- agent bearer token was denied on non-Simurgh API paths with 403.

## Simurgh Answer Quality + Evidence Routing Slice - 2026-05-26

PM reported unacceptable advisory answers for show readiness, ambiguous upload
follow-ups, scout-drone IP lookup, and add-third-drone workflow. Review result:
the issue was not only prompt wording. The dashboard assistant still had a
keyword-heavy local classifier, weak follow-up context, and an over-broad
provider-side privacy posture for configured fleet IPs when local tools failed
to match typo-heavy prompts.

Implementation:

- added typo-tolerant normalization for common operator prompt errors such as
  `doren`, `droen`, `scoute`, `uplaoded`, `waht`, and `thrird`;
- added safe short-lived `last_domain` session metadata so follow-ups such as
  `is there any uploaded?` after a drone-show turn stay on the show-readiness
  path without storing raw transcript text;
- extended `mds.operator.question.answer` with optional `conversation_topic` for
  dashboard and MCP advisory-wrapper routing;
- improved show-status answers with upload/load state, duration, metrics
  snapshot, validation signal, safety signal, and explicit `uploaded !=
  fly-ready` wording;
- changed chat show-readiness derivation to use the current metrics snapshot
  only, avoiding expensive recomputation and keeping the path read-only;
- allowed authenticated operator chat to answer configured fleet IP/callsign
  questions from GCS config while still blocking secrets, raw logs, and private
  field evidence;
- added a reusable add-drone workflow answer that leads with setup steps and
  links, then reports current fleet count;
- updated prompt/config/docs to state that approved read-only tool evidence must
  be used before saying Simurgh cannot see MDS state.

Validation on Hetzner only:

- direct show-readiness smoke: about 1 second after switching to snapshot-based
  readiness derivation;
- focused assistant/runtime/MCP suite: 113 passed in 38.11 seconds;
- Python compile check for touched backend modules: passed.

Reviewer notes:

- AI/MCP review: this remains registry/policy-based; OpenAPI candidates are not
  blindly exposed, and the natural-language advisory wrapper now carries only a
  safe topic hint for follow-ups.
- Safety/privacy review: configured fleet IPs are allowed only as authenticated
  GCS-owned operator state. Raw logs, secrets, screenshots, private field
  evidence, and direct command requests remain blocked.
- PM/product review: the failing PM examples now route to concrete MDS evidence
  or workflow guidance instead of generic `I cannot see` responses.


## Simurgh Follow-Up Interpretation Slice - 2026-05-26

PM reported that logs follow-ups repeated the previous warning summary instead
of explaining what the warnings meant. Review result: local MDS tools were acting
as final answer templates. Session topic routing could select the right evidence
source, but the answer layer had no response-mode distinction between a fresh
status scan and an interpretive follow-up.

Implementation:

- added a safe response-mode layer for local read-only advisory answers:
  `status`, `interpret`, `workflow`, `compare`, and `capability`;
- kept raw transcript text out of session storage while allowing `last_domain`
  to route follow-ups such as `what does it mean?` after a logs turn;
- upgraded backend-log answers so fresh scans include an operational read, while
  interpretive follow-ups explain the pattern, affected routes, likely causes,
  flight relevance, severity, and next checks;
- exposed `response_mode` in the advisory tool structured result and audit
  metadata;
- added typo normalization for the PM log prompt shape without hardcoding a full
  canned reply.

Validation on Hetzner only:

- Python compile check for touched backend modules: passed;
- focused logs follow-up regression: 2 passed;
- assistant/runtime/MCP suite: 115 passed in 40.98 seconds.

Reviewer notes:

- AI-agent review: this is a general evidence-plus-response-mode fix, not a
  single prompt patch. It can be extended to show readiness, telemetry,
  configuration, docs, and future action dry-runs.
- MCP/tooling review: the same `mds.operator.question.answer` contract is used
  by dashboard and MCP clients; no separate hardcoded tool stack was introduced.
- Safety review: interpretation remains read-only. No logs, secrets, drone-local
  APIs, raw commands, or mutations are exposed.

## Simurgh Query Planning + Retrieval Context Slice - 2026-05-26

PM reported that the assistant still felt brittle for unexpected, typo-heavy,
or partially nonsensical prompts, and explicitly asked that Simurgh avoid naive
RAG and uncontrolled LLM loops. External review references were checked before
implementation: OpenAI tool/context guidance, IBM RAG and mtRAG material,
Microsoft GraphRAG query modes, LangGraph agentic-RAG patterns, and MCP protocol
guidance on tools/resources and sensitive-data handling.

Review result:

- the correct near-term fix is not fine-tuning and not a blind vector store;
- deterministic routing should stay deterministic;
- factual GCS state must continue to come from reviewed read-only tools;
- provider calls need better context assembly for prompts outside curated local
  tools;
- follow-up state should remain safe and small;
- future vector/hybrid/rerank/GraphRAG work should be swappable behind the docs
  index/search abstraction, not baked into answer templates.

Implementation:

- added `gcs-server/agent_runtime/query_understanding.py` as a provider-neutral
  query planner;
- normalizes common operator typos, infers query domain, answer mode, search
  tags, and low-signal/unclear prompts;
- adds bounded public docs retrieval for provider turns when local read-only MDS
  tools do not answer the question;
- injects retrieved chunks as `retrieved.*` context documents with source and
  dashboard route hints;
- adds audit metadata for `query_domain`, `response_mode`, `query_unclear`, and
  `retrieved_context_count`;
- keeps local read-only tools as the source of truth for fleet, show, swarm,
  runtime, logs, and MCP/capability state;
- updates provider instructions so unclear or silly prompts still receive a
  natural, bounded answer instead of being ignored or reduced to a canned block.

Validation on Hetzner only:

- Python compile check for touched backend modules: passed;
- focused provider-context tests for unexpected and low-signal prompts: passed;
- generated docs index `--check`: passed;
- generated OpenAPI candidate artifact `--check`: passed;
- targeted Simurgh backend/docs suite: 130 passed in 64.88 seconds;
- `git diff --check`: passed;
- production `MDS-GCS` restart: passed, with API `5030` and dashboard `3030`
  listening;
- production status: `MDS_MODE=real`, provider `openai`, model `gpt-5.4-mini`,
  MCP enabled, 28 allowed read-only tools, circuit breaker on, always-confirm on;
- authenticated live provider smoke for a low-signal prompt returned a natural
  clarification, included retrieved public docs context, and executed no tools or
  drone actions.

Reviewer notes:

- AI/RAG review: this is a context-engineering foundation, not a final enterprise
  RAG platform. The immediate demo gets query rewrite, bounded retrieval,
  response-mode planning, and auditability without premature infrastructure.
- MCP/tooling review: provider retrieval and MCP docs tools share the same docs
  index, while executable capabilities remain registry/policy-controlled.
- Safety review: no new action path was opened. Circuit breaker, auth, provider
  data-egress rules, and read-only tool boundaries remain unchanged.

## Simurgh Retrieval Quality + Shared Interface Slice - 2026-05-26

PM/reviewer concern: Simurgh must not rely on hardcoded answer patches or naive
RAG. The next improvement was to make routing/retrieval measurable and to stop
MCP docs tools and provider retrieval from drifting into separate stacks.

Implementation:

- added `gcs-server/agent_runtime/retrieval.py` with `RetrievalQuery`,
  `RetrievalHit`, `Retriever`, and `LexicalDocsRetriever`;
- moved provider retrieved-context assembly and MCP docs search onto the same
  retrieval interface;
- added multi-query fusion that favors the operator's original prompt and uses
  expansion queries as fallback evidence;
- fixed query response-mode matching so `how` no longer matches inside `show`;
- added `tests/test_agent_query_understanding.py` for direct domain/mode,
  typo-normalization, follow-up-topic, and low-signal prompt coverage;
- added `docs/agent-context/evals/simurgh-retrieval-quality.yaml` and
  `tests/test_simurgh_retrieval_quality.py` for PM-critical retrieval relevance
  checks;
- kept the production backend lexical/tag-filtered by default. Vector, hybrid,
  rerank, managed-search, or GraphRAG adapters now have a clear swappable seam
  but are not enabled without eval proof.

Validation on Hetzner only:

- Python compile check for touched backend modules: passed;
- generated docs index `--check`: passed;
- generated OpenAPI candidate artifact `--check`: passed;
- focused query/retrieval tests: 14 passed;
- broad Simurgh assistant/MCP/docs suite: 144 passed in 71.45 seconds.

Reviewer notes:

- AI/RAG review: approved direction because retrieval quality is now measured
  before adding infrastructure complexity.
- MCP/tooling review: dashboard/provider retrieval and MCP docs tools now share
  one retrieval contract.
- Safety review: no new action path, provider tool call, direct drone API, or
  raw command surface was added.


## Simurgh Orchestration Trace + Language Profile Slice - 2026-05-26

Goal: answer PM concerns about follow-up explainability and multilingual readiness without adding UI noise or hardcoded prompt patches.

Implemented:
- Added `gcs-server/agent_runtime/language.py` for deterministic language/script/tone profiles.
- Added provider-facing language/tone guidance for safe OpenAI turns.
- Added sanitized assistant response `trace` metadata for PM/test inspection: provider, session topic, query plan, selected tool intent, context counts, language profile, and safety posture.
- Kept chat UI clean; trace is API metadata, not visible message clutter.
- Documented the future multilingual query rewrite contract and privacy gates.

Review note: current local read-only tools still answer in English. Full multilingual semantic query rewrite and localized local-tool rendering remain a planned follow-up slice requiring multilingual evals and sensitive-input gating.

## Simurgh Governed Query Adaptation Slice - 2026-05-26

Goal: address PM concern that Simurgh must understand typo-heavy, multilingual, and differently phrased operator questions without hardcoded answer patches.

Implementation:
- Added `config/agent_query_adaptation.yaml` as the reviewed, versioned rule source for typos, aliases, multilingual routing hints, and action-word canonicalization.
- Added `gcs-server/agent_runtime/query_adaptation.py` with `QueryAdaptationConfig`, `QueryAdaptation`, and `adapt_operator_query`.
- Routed assistant turns and the MCP-backed `mds.operator.question.answer` advisory tool through the same adaptation layer before deterministic local intent selection.
- Safety checks now evaluate both original operator text and adapted routing text, so translated/aliased action words do not bypass blocked-intent policy.
- Session memory now keeps safe `last_domain`, `last_intent`, and `last_response_mode` metadata for follow-up routing without storing raw transcript text.
- Assistant response trace now includes sanitized `adaptation` metadata: strategy, routing language, confidence, and applied rule ids only.

Validation on Hetzner only:
- Python compile check for touched backend modules and tests: passed.
- Focused query/language/adaptation/assistant tests: 40 passed, 51 deselected.
- Focused API trace/follow-up tests: 5 passed, 26 deselected.

Reviewer notes:
- AI/agent review: approved as the right next step before heavier RAG/vector/translation infrastructure. It improves routing and traceability without an uncontrolled LLM loop.
- MCP/tooling review: approved because dashboard assistant and MCP advisory tool now share the same adaptation path.
- Safety review: approved because no action surface was added and blocked/sensitive checks run on both original and canonicalized routing text.
- UI/PM review: no new visible UI clutter; trace remains API metadata.

Known limitation: local read-only GCS-state answers are still rendered in English. Localized rendering needs a future approved adapter that does not leak fleet config, logs, telemetry, or secrets to an external provider for translation.

## Simurgh Answer Composer And Follow-Up Slice - 2026-05-27

Implemented a reusable local-answer composition layer in `gcs-server/agent_runtime/answer_composer.py` and migrated drone-show status/readiness answers through it. This reduces scattered Markdown formatting and gives future tools a single place for predictable tables, bullets, and compact operator-facing text.

Conversation behavior improved for topic follow-ups. If a user asks an ambiguous follow-up after a drone-show answer, such as “what does it mean?” or “you cannot keep history?”, Simurgh now uses the safe session topic and returns an interpretation of uploaded vs fly-ready state instead of repeating the raw show-status block or falling back to a generic provider answer. Log interpretation behavior remains covered by the same response-mode pattern.

Validation on Hetzner: Python compile passed for touched runtime modules; focused Simurgh assistant/MCP/query suite passed with 141 tests. Production restart and live smoke are handled after the full slice validation.

Reviewer notes:
- AI/agent reviewer: approved because follow-up handling is topic-aware and does not depend on hardcoded single prompts.
- MCP/API reviewer: approved because the MCP advisory tool continues to use the same local answer path and policy gate.
- Safety reviewer: approved because this slice does not add action execution, command APIs, provider tool calls, or circuit-breaker bypasses.
- UI/UX reviewer: approved direction because generated Markdown is cleaner and still uses linkable dashboard/doc routes only.

## Simurgh Composer Coverage Expansion Slice - 2026-05-27

Extended `AnswerComposer` beyond drone-show status into the PM-visible local answer set: fleet summaries/IP lookup, connectivity, runtime posture, capability/MCP catalog, QuickScout vs Swarm Trajectory comparison, and backend log summaries. This replaces scattered string assembly with reusable Markdown sections/tables while preserving the same read-only advisory contract.

Design check: reviewed the official MCP tools spec and OpenAI Responses API reference during this slice. The current implementation remains aligned with schema-described MCP tools and explicit provider tool-control: Simurgh local/MCP calls are policy-gated inside MDS, while provider advisory responses continue without free-form tool execution.

Validation on Hetzner: focused Simurgh composer/query/assistant/MCP suite passed with 143 tests before broad validation. No dashboard source changes were needed in this slice.

Reviewer notes:
- AI/agent reviewer: approved because response formatting is generalized, not overfitted to one PM prompt.
- MCP/API reviewer: approved because tool discovery/calls still use the same registry and policy gate.
- Safety reviewer: approved because no action, mutation, provider tool call, or circuit-breaker bypass was added.
- UI/UX reviewer: approved because table/list output is cleaner and still plain Markdown for non-dashboard MCP clients.

## Simurgh Conversation Intelligence Router Slice - 2026-05-27

Goal: reduce generic fallback answers and make PM-style follow-ups feel like a coherent expert conversation without hardcoding one answer per demo prompt.

Implemented:

- Added topic-aware follow-up routing for fleet, swarm, setup, runtime, capabilities/MCP, and SITL in addition to the existing drone-show and logs follow-ups.
- Added a bounded query-plan fallback from the shared query planner into the local read-only MDS router so safe MDS questions that miss exact rules can still select a reviewed local tool.
- Kept the fallback narrow: it only captures real operator questions/requests, uses word-boundary matching for short domain terms, and leaves generic provider prompts at the provider-auth gate.
- Expanded reviewed query adaptation rules for PM-observed typo shapes such as `whay` and `differnt`.
- Added tests for fleet scout-IP follow-up, setup/bootstrap follow-up, MCP/client capability follow-up, query-plan fallback, and provider-auth non-regression.
- Added retrieval eval prompts for MCP client capability discovery and typo-heavy drone-show launch-mode questions.

Validation on Hetzner only:

- Python compile check for touched runtime modules: passed.
- Focused query/adaptation/assistant/API suite: 125 passed in 125.40 seconds.
- Docs index regenerated and checked at 733 chunks.
- Retrieval/docs/tool-candidate eval suite: 17 passed.
- Broad Simurgh runtime/API/MCP/docs suite: 205 passed in 168.38 seconds.

Reviewer notes:

- AI/agent reviewer: approved because the router is topic/domain driven and measurable, not a hardcoded answer patch.
- MCP/API reviewer: approved because dashboard chat and MCP advisory calls continue through the same policy-gated read-only tool path.
- Safety reviewer: approved because no action tool, command API, provider tool call, or circuit-breaker bypass was added; provider-auth tests explicitly protect generic provider prompts.
- PM/UI reviewer: approved direction because follow-ups like “and the scout IP?” and “what scripts should I use?” now keep conversational context without adding visible dashboard complexity.

## Simurgh Log Interpretation Polish Slice - 2026-05-27

Goal: address PM-visible log UX issues where text-log rows showed `time n/a` and a follow-up like “does this mean something is wrong?” repeated the summary table.

Implemented:

- Text log timestamp extraction now accepts time-only prefixes such as `03:17:15.633` as well as full ISO-style timestamps with `Z` or numeric offsets.
- Query adaptation now normalizes common typo shorthand such as `thsi` -> `this` and `sth` -> `something`.
- Log follow-up detection now recognizes “does this mean something is wrong?” style questions.
- Backend log interpretation now starts with a direct verdict. For WARNING-only HTTP 401 patterns, it states that the evidence does not look like a drone/MAVLink/PX4/GPS/RTK/battery/flight-control issue, but it is dashboard/API auth noise worth cleaning up if persistent.

Validation on Hetzner only:

- Python compile check for touched runtime modules: passed.
- Focused adaptation/log/API tests: 9 passed.

Reviewer notes:

- AI/agent reviewer: approved because this fixes the general follow-up interpretation path rather than one hardcoded user sentence.
- Backend reviewer: approved because timestamp parsing is format-tolerant and keeps sanitized log text.
- Safety reviewer: approved because no command path, direct drone API, provider tool call, or circuit-breaker change was added.
- PM/UI reviewer: approved direction because the assistant gives a human-readable verdict and avoids repeated table blocks for interpretation follow-ups.

## Simurgh Conversational Orchestration Repair Slice - 2026-05-27

Goal: fix the PM-visible failure where normal operator phrasing such as “can you say it in Persian” or “can you report warnings in GCS?” was misrouted to the MCP/capability catalog, making Simurgh feel like a hardcoded old chatbot.

Root cause found:

- `can you` was treated as a generic capabilities-domain signal. That incorrectly hijacked polite operator requests before the real domain router or provider could reason about them.
- The dashboard session kept only public topic metadata, not a bounded private previous-answer context. A referential follow-up had no safe answer object to transform.
- The route-level local/provider auth gate classified the raw message before applying query adaptation, so typo-heavy local requests could be mistaken for provider-only turns.

Implemented:

- Removed broad `can you` capability bias from the shared query planner. Capability catalog responses now require actual capability/tool/API/MCP intent such as “what can Simurgh do?” or “what MCP tools are exposed?”.
- Added bounded private session context in `AgentSessionStore` for the last assistant answer. This state is in-memory only and is not serialized through session APIs, audit, history, or MCP resources.
- Added a previous-answer transform path. Requests such as “say it in Persian” now bind to the actual previous Simurgh answer and, when the configured provider is available, ask the provider to transform only that answer without adding facts or executing tools.
- Added query adaptation for `warnign`/`warnirng` and fixed the route auth gate to classify the adapted routing text as well as raw text.
- Added regressions for: typo-heavy connected-drone question, Persian translation follow-up, “can you report warnings in GCS?” after a fleet topic, and route-level local-auth handling.

Validation on Hetzner only:

- Python compile check for touched runtime/API modules: passed.
- Focused orchestration/adaptation/API tests: 22 passed.

Reviewer notes:

- AI/agent reviewer: approved direction because this introduces conversation-state orchestration and removes a bad router prior, rather than hardcoding PM examples.
- MCP/API reviewer: approved because the MCP capability catalog remains available only for explicit capability/MCP questions and is no longer the accidental fallback for normal operator requests.
- Safety reviewer: approved because the new private memory is bounded, not exposed through APIs/MCP/audit/history, and no action tool, command API, direct drone API, or circuit-breaker bypass was added.
- PM/UI reviewer: approved direction because the assistant can now answer a follow-up against what it just said, which is required for a ChatGPT-like operator experience.

## Simurgh Log Window Semantics Slice - 2026-05-27

Goal: finish the interrupted log-polish edit and make PM-style questions such as “warnings in the last 30 minutes” mean the requested window, not just the generic recent tail.

Implemented:

- `backend_log_summary` now accepts the operator message, parses explicit windows such as “last 30 minutes”, “past hour”, and “last 2 hours”, and filters warning/error events to that window when timestamps are parseable.
- JSONL log parsing now reads `ts`, `timestamp`, `time`, and `created_at` aliases, and falls back to an embedded clock in the message when the structured field is missing.
- Log tables use the best available timestamp instead of showing `time n/a` when a clock exists inside the record.
- Added focused tests for window parsing, JSONL timestamp aliases, embedded-clock extraction, and stale-warning exclusion.

Validation on Hetzner only:

- Python compile check for touched runtime modules: passed.
- Focused query/adaptation/orchestration/log-window/API tests: 24 passed.
- Broad Simurgh runtime/API/MCP/docs/eval/inventory suite: 256 passed.

Reviewer notes:

- AI/agent reviewer: approved because the behavior follows the user’s temporal intent and avoids repeating stale evidence as if it were current.
- Backend reviewer: approved because the parser remains conservative, bounded to seven days, and does not expose secrets from log text.
- Safety reviewer: approved because this is still read-only log inspection and adds no command path, drone API, provider tool call, or circuit-breaker bypass.
- PM/UI reviewer: approved direction because the answer can now state the requested window and avoid `time n/a` when a timestamp exists.

## Simurgh Chat History UX Slice - 2026-05-27

Goal: address PM feedback that the chat history felt too basic and that the existing `Clear` action was ambiguous.

Implemented:

- Confirmed dashboard chat history is a browser-local convenience cache stored under `mds.simurgh.chat.v2`; it is not the authoritative backend session store.
- Renamed the destructive history action from `Clear` to `Clear all` with an explicit accessible label: `Clear all local Simurgh chats`.
- Added a minimal ChatGPT-style row action: an ellipsis button appears on hover/focus for each chat and opens a compact menu with `Delete chat`.
- Per-chat delete removes only the selected local conversation and preserves the rest of the local chat list. If the last chat is deleted, the dashboard creates one empty chat so the surface is never blank/broken.
- Kept row actions quiet on desktop and lightly discoverable on touch devices to avoid always-visible UI noise.

Validation on Hetzner only:

- Focused Simurgh dashboard test: 9 passed.
- Dashboard production build: passed.

Reviewer notes:

- UI/UX reviewer: approved because destructive scope is now explicit and the per-chat action is available without increasing visual noise.
- Frontend reviewer: approved because the implementation stays local to the Simurgh page and does not introduce a new chat persistence backend.
- Safety reviewer: approved because chat deletion is local UI history only and does not close drone sessions, alter runtime settings, expose secrets, or affect MCP/action policy.

## Simurgh MCP/API-Agent Architecture Research Note - 2026-05-27

Question from PM: should MDS manually build MCP tools, use auto tools such as FastAPI-MCP/FastMCP/MCPify, and can future API changes auto-update the agent surface?

Research summary:

- OpenAI tool guidance supports built-in tools, function calling, tool search, and remote MCP servers; advanced workflows can defer tool definitions and explicitly control tool choice. Source: https://developers.openai.com/api/docs/guides/tools
- OpenAI Agents SDK guidance separates agent definition, runtime state, orchestration/handoffs, guardrails/human review, MCP/tools, tracing, and evals. Source: https://developers.openai.com/api/docs/guides/agents
- MCP tool spec says clients discover tools via `tools/list`, call them via `tools/call`, and should make exposed tools/tool invocations visible with human confirmation for operations. Source: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- FastAPI-MCP can mount an MCP server directly from a FastAPI app and preserve schemas/docs/auth dependencies. Source: https://github.com/tadata-org/fastapi_mcp
- FastMCP can generate from OpenAPI/FastAPI and supports route maps/exclusions, but its own docs warn that curated MCP servers perform better than auto-converted complex APIs and recommend OpenAPI conversion for bootstrapping rather than mirroring. Sources: https://gofastmcp.com/integrations/openapi and https://gofastmcp.com/integrations/fastapi
- LangGraph/LangSmith human-in-the-loop patterns are relevant for future multi-step action approval/resume workflows, especially where a tool call should pause for human review. Source: https://docs.langchain.com/langsmith/add-human-in-the-loop

Decision for MDS:

- Do not hand-code permanent one-off MCP routes, and do not blindly expose every GCS route as a callable tool.
- Keep the current two-layer approach: generated API candidates from the live OpenAPI schema, then reviewed registry/policy promotion into MCP tools.
- Treat FastAPI-MCP/FastMCP as adapter candidates for reducing server glue and improving standards compatibility, but keep MDS-owned safety classification, route exclusions, approval policy, test coverage, and documentation as the authority.
- Future target: make the generator classify new routes into `read_only_candidate`, `guarded_action_candidate`, `admin_excluded`, `binary_excluded`, or `drone_local_excluded`, then require review before promotion to `tools/list`.

Reviewer notes:

- MCP expert: approved because this follows the MCP discovery model without turning dangerous or ambiguous GCS endpoints into model-callable tools.
- AI-agent expert: approved because the system remains extensible and adapter-friendly while avoiding the failure mode of dumping too many raw REST operations into the model context.
- PM reviewer: approved as the next slice direction because it directly answers why auto-MCP is useful but insufficient alone for a military-level drone GCS.

## Simurgh MCP Candidate Review Surface Slice - 2026-05-27

Goal: make the auto-discovered OpenAPI/MCP candidate inventory visible to PM/dev reviewers without promoting routes blindly into callable tools.

Implemented:

- Added `gcs-server/agent_runtime/tool_candidates.py` to load and summarize the generated candidate artifact.
- Added `GET /api/v1/simurgh/tool-candidates` with filters for `eligible_read_only`, `risk_class`, `search`, `limit`, and `offset`.
- The endpoint reports candidate counts, review-only policy, method/risk/sensitivity counts, top review reasons, and any curated registry route matches.
- Candidate payloads are bounded and explicitly returned as `callable: false`; the endpoint does not affect MCP `tools/list` or `tools/call`.
- Regenerated `docs/agent-context/generated/simurgh-openapi-tool-candidates.yaml`; the artifact now has 197 candidates because the new review endpoint is part of OpenAPI.
- Added a compact `MCP review` summary inside the Simurgh settings drawer: discovered, eligible, active registry matches, guarded/excluded count, and an `Open` link to the JSON review endpoint.
- Documented the review endpoint in `docs/apis/gcs-api-server.md` and `docs/guides/simurgh-mcp-clients.md`.
- Updated the frozen GCS route inventory so the API contract change is deliberate.

Validation on Hetzner only:

- Installed repo-declared `tests/requirements-test.txt` into `/opt/mds/venv` so backend tests can run on Hetzner.
- Python compile check for touched backend modules: passed.
- Focused Simurgh dashboard test: 9 passed.
- Focused backend candidate/route/inventory suite: 23 passed.
- Broad Simurgh/agent/MCP/docs/API inventory suite initially found the expected frozen inventory delta, then the inventory was updated and the focused route/inventory suite passed.
- Dashboard production build: passed.
- Generated candidate artifact `--check`: passed.
- Generated docs index `--check`: passed.
- `git diff --check`: passed.
- Production smoke: `/simurgh` 200, API health OK, `MDS_MODE=real`, provider `openai`, MCP enabled, circuit breaker on, always confirm on, candidate endpoint reports 197 discovered routes and 78 eligible read-only candidates, MCP `tools/list` remains 28 tools with no raw submit or candidate tool exposure.

Reviewer notes:

- MCP reviewer: approved because this adds OpenAPI-derived visibility while keeping MCP callable exposure policy-gated.
- Safety reviewer: approved because no action route, raw command route, admin route, drone-local route, or candidate inventory route became model-callable.
- Backend reviewer: approved because candidate filtering is bounded and generated artifacts are checked for freshness.
- UI/UX reviewer: approved because the review data lives in the settings drawer, not in the main chat surface.
- PM reviewer: approved direction because this provides evidence that MDS is not manually hardcoding MCP one route at a time and is also not blindly exposing dangerous APIs.

## Simurgh Log Noise Cleanup Slice - 2026-05-27

Goal: answer the PM concern that backend log summaries still looked alarming and robotic because stale unauthenticated dashboard polling records were reported as WARNING and old fallback text logs were mixed into current session summaries.

Implemented:

- Request logging is now method-aware: routine dashboard GET/HEAD/OPTIONS polling endpoints that return 401/403 are logged as DEBUG, not WARNING.
- Mutating calls and non-routine protected paths still log 401/403 as WARNING, and all 5xx responses remain ERROR.
- Added `/api/v1/system/runtime-status`, `/api/v1/simurgh/status`, and `/api/v1/simurgh/policy` to routine success/polling classification so common dashboard refresh traffic does not dominate operator logs.
- Simurgh backend log summaries now suppress historical routine auth-polling warnings from the operator warning/error view while preserving real POST/non-routine auth failures and server errors.
- The log scanner now globally prefers the newest session JSONL files and ignores stale fallback text logs when fresh session logs exist. This removed old May 24 `/var/log/mds-gcs.log` shutdown/auth entries from the current May 27 "latest logs" answer.
- The existing timestamp handling remains intact: time-only log lines display their clock value and should not show `time n/a`.

Validation on Hetzner only:

- `tests/test_request_logging.py`: 5 passed.
- Focused log assistant tests: 8 passed.
- `tests/test_mds_auth.py tests/test_gcs_api_http.py`: 107 passed.
- `tests/test_request_logging.py tests/test_agent_assistant_runtime.py tests/test_gcs_simurgh_assistant.py`: 120 passed.
- Python compile checks for touched backend modules: passed.
- `git diff --check` for touched files: passed.
- Production smoke after restart: `/api/v1/system/health` 200, `/simurgh` 200, `MDS_MODE=real`, provider `openai`, model `gpt-5.4-nano`, MCP enabled, circuit breaker on, always-confirm on.
- Production routine unauthenticated `GET /api/v1/commands/active` still returns 401, but records DEBUG instead of WARNING.
- Production Simurgh log smoke: provider `mds-tools`, no `time n/a`, scanned only fresh May 27 GCS session logs, and returned "No WARNING/ERROR/CRITICAL entries were found in the recent scanned window."

Reviewer notes:

- Backend/API reviewer: approved because auth behavior did not change; only operational log classification changed.
- Security reviewer: approved because non-routine auth failures, mutating auth failures, and server errors remain visible.
- PM/operator reviewer: approved because current log answers no longer inflate stale dashboard polling into a field-operations concern.
- AI/UX reviewer: approved because the assistant now gives a cleaner direct operational answer instead of repeating stale tables.

## Official Release / Client Sync Slice - 2026-05-27

Goal: cleanly publish Simurgh to the official repo without leaking private client context, then sync the same validated code into the client production repo and keep production in real mode with the circuit breaker on.

Implemented:

- Created clean official workspace `/root/mds_simurgh_official_release` from official `origin/main` instead of using stale/dirty local official staging.
- Applied the audited Simurgh code/config/docs/tests payload from the client repo, excluding private PM journey/report docs.
- Sanitized public examples and tests so official does not contain client repo paths, private overlay IPs, customer-style labels, field ticket examples, or pasted API keys.
- Regenerated public docs index and OpenAPI tool-candidate artifacts from the clean official tree.
- Fixed the scout-IP regression to be deployment-agnostic: if a fleet has a SCOUT role, answer with it; otherwise explain that no configured scout exists.
- Pushed official `main`, branch `simurgh-official-release-20260527`, and tag `v5.5.8-simurgh-operator`.
- Copied the final official release payload back into `/root/catchadrone_gcs`, keeping private PM/journey docs only in the client repo.
- Restarted the Hetzner client production service from `/root/catchadrone_gcs` with `MDS_MODE=real`, MCP enabled, circuit breaker on, and always-confirm on.
- Ran a live provider-smoke using only public Simurgh safety context; OpenAI request passed no-tools/no-store checks.

Validation on Hetzner only:

- Official broad backend/API/agent/MCP suite: `367 passed`.
- Official Simurgh dashboard focused test: `9 passed`.
- Official production dashboard build: passed.
- Official generated docs/tool candidates `--check`: passed.
- Official public leak scan: passed for real API key patterns and known private/client strings.
- Client broad backend/API/agent/MCP suite: `367 passed`.
- Client Simurgh dashboard focused test: `9 passed`.
- Client production dashboard build: passed.
- Client generated docs/tool candidates `--check`: passed.
- Client live smoke: health 200, `/simurgh` 200, runtime real/openai/gpt-5.4-nano, MCP initialize returned tools/resources/prompts, read-only fleet and scout turns worked from live config.

Reviewer notes:

- Repo maintainer: approved. Official release is now public-safe and client repo remains private with PM notes.
- Security reviewer: approved. Public tree excludes PM reports and raw secrets; client provider credential remains server-side under `/etc/mds/secrets/`.
- MCP reviewer: approved. Generated route candidates prove extensibility; callable MCP tools remain curated and policy-gated.
- AI-agent reviewer: approved for PM retest. Local deterministic MDS tools handle known operational reads; provider path is available for general/public-context reasoning.
- UI/UX reviewer: approved for current chat-first surface; remaining work is browser-level regression and final visual polish from PM feedback.
- PM reviewer: approved to hand to testers for read-only/CB-on demo retest.

Next phases:

1. PM/tester retest using live client dashboard and the curated prompt suite.
2. Add Playwright/browser checks for the chat UI and rendered markdown once browser tooling is installed on Hetzner.
3. Continue MCP adapter research and prototype replacement-friendly adapter boundaries without weakening MDS registry/policy control.
4. Expand multilingual and long-follow-up retrieval/eval coverage.
5. Plan SITL action-tool prototype under circuit breaker/always-confirm before any real-world action path is considered.

## Simurgh Conversation Intelligence Routing Hardening - 2026-05-28

Goal: address PM feedback that Simurgh still felt like a deterministic old chatbot when users changed topics, asked follow-ups in Persian, or asked general robotics/weather questions after a fleet/log turn.

Root cause found:

- Session topic memory was too eager. A previous `logs` or `fleet` topic could override a new explicit intent such as `current fleet status` or `what is MAVLink?`.
- Persian referential transforms such as `فارسی بگو همینو` were not recognized everywhere, so the provider could answer from generic Simurgh framework context instead of the immediate previous answer.
- General knowledge questions that mention words like `drone` or `MAVLink` had no clean local lane, so they could fall into fleet/connectivity tools.
- The public docs index was correctly strict: after the operator guide changed, the generated docs index became stale and had to be regenerated.

Implemented:

- Added `config/agent_general_knowledge.yaml` as the reviewed public-safe source for common robotics/MDS-adjacent definitions and external-data fallbacks. Current entries cover `drone`, `MAVLink`, and weather/no-live-weather-source behavior.
- Updated query adaptation for `flee`/`fleed`/`fleat` -> `fleet` so PM typo-heavy prompts still route to fleet status.
- Changed query planning and read-only routing so explicit general/weather questions beat stale session topic memory.
- Mirrored Persian previous-answer transform detection in the assistant and read-only routing layers.
- Added runtime and API-level regression coverage for: logs -> fleet status topic switch, fleet -> drone/MAVLink/weather general questions, and Persian `say this same answer` follow-up.
- Documented the new editable general-knowledge artifact in `docs/guides/simurgh-operator.md` and regenerated `docs/agent-context/generated/simurgh-docs-index.json`.

Validation on Hetzner only:

- Focused client regression suite: `25 passed`.
- Focused official regression suite: `25 passed`.
- Generated docs index/retrieval checks after regeneration: `14 passed` in client and `14 passed` in official.
- Broad client Simurgh/API/agent/MCP/docs suite: `374 passed`.
- Broad official Simurgh/API/agent/MCP/docs suite: `374 passed`.
- Python compile checks and `git diff --check`: passed in both worktrees.

Reviewer notes:

- AI-agent reviewer: approved because this fixes the routing hierarchy and context handoff, instead of adding one-off answer patches.
- MCP/API reviewer: approved because dashboard chat still uses local read-only MDS tools and the same policy direction as MCP; no new executable tool was added.
- Safety reviewer: approved because the new general-knowledge config is public-safe, has no private field facts or credentials, and no action path/direct drone API/circuit-breaker bypass was added.
- PM/operator reviewer: approved for retest because the known PM failures now have regressions at both runtime and API layers.

Next phases:

1. Run live production smokes after client deployment: status, fleet, logs, general `what is a drone?`, `what is MAVLink?`, weather fallback, and Persian previous-answer transform.
2. Add browser-level UI regression for chat markdown, copy controls, and history row menu when Playwright/browser tooling is available on Hetzner.
3. Expand general-knowledge/retrieval evals only for reusable PM-critical topics; avoid growing it into private field memory or a hardcoded FAQ.
4. Continue MCP adapter evaluation while preserving the reviewed registry/policy promotion boundary.

Release/deployment completion:

- Official pushed: `02d11a95`, tag `v5.5.9-simurgh-conversation-routing`.
- Client code pushed: `047860cce`, tag `cad-v5.5.9-simurgh-conversation-routing`.
- Hetzner production restarted from `/root/catchadrone_gcs` after clearing a stale gunicorn parent that kept port `5030` bound after tmux restart.
- Production health: API `/api/v1/system/health` 200, dashboard `/simurgh` 200.
- Runtime posture after restart: `MDS_MODE=real`, provider `openai`, model `gpt-5.4-nano`, MCP enabled, circuit breaker on, always-confirm on, provider credential ready.
- Live in-process smoke with production env confirmed `logs -> fleet`, `drone`, `MAVLink`, `weather`, and typo warning prompts route to the expected local read-only tool intents.
- Protected Simurgh HTTP endpoints correctly require MDS auth; auth was not disabled and no temporary credentials were created for smoke.

## General Question Topic-Escape And Smart Wi-Fi Field Note - 2026-05-28

Goal: address PM examples where Simurgh repeated stale fleet/swarm answers for
ordinary geography/math questions, and document the field Smart Wi-Fi Manager
remote-mutation issue reported on CM4-01/CM4-02.

Root cause found:

- Simurgh short-term topic memory still over-weighted the previous MDS domain.
  A fleet topic could catch `how many kilometers from Tehran to New York`, and
  the generic `distance` term could push a public geography/flight-length prompt
  into the swarm geometry tool.
- Smart Wi-Fi Manager `:9080` has two separate concerns: dashboard reachability
  depends on the node service/listen address, while remote save/remove actions
  are intentionally blocked unless loopback is used or a mutation token is sent.
  This behavior comes from Smart Wi-Fi Manager, not from Simurgh.

Implemented:

- Added a reusable non-MDS general-question detector before contextual MDS
  follow-up routing. Geography, distance, unit conversion, public-location, law,
  and web-search-style prompts now escape stale MDS read tools.
- Mirrored that domain escape in the query planner so provider retrieval does
  not attach irrelevant fleet/swarm context to those prompts.
- Added `config/agent_public_places.yaml` and a deterministic public geodesy
  read tool for reviewed public references. Tehran/New York distance and
  Damavand coordinate/radius-loop prompts now use stable coordinates plus
  haversine/circumference math instead of letting the provider guess.
- Added regression tests for the two PM examples: Tehran to New York distance
  after a fleet turn, and Damavand lat/long plus 10 km loop length.
- Updated Smart Wi-Fi Manager docs to explain `SMART_WIFI_MANAGER_API_TOKEN is
  required for remote mutating requests`, the SSH-tunnel workaround, Fleet Ops
  preference, and service/listen checks for a reachable `:9070` but unreachable
  `:9080` case.

Validation on Hetzner only:

- `tests/test_agent_assistant_runtime.py tests/test_agent_mds_read_tools.py tests/test_agent_query_understanding.py`: `106 passed`.
- Regenerated Simurgh docs index from approved public docs: `736 chunks`.
- `tests/test_simurgh_docs_index_generator.py` with coverage disabled for the
  docs-only subset: `10 passed`.

Reviewer notes:

- AI-agent reviewer: approved as an architectural routing correction, not a
  hardcoded answer patch. Reviewed public geography now uses deterministic
  tools; other general questions still fall through to the provider when no MDS
  evidence tool is appropriate.
- Safety reviewer: approved because no drone command path, secret handling, or
  circuit-breaker behavior changed.
- Field-ops reviewer: approved the Wi-Fi diagnosis: no evidence that Simurgh
  broke CM4 Wi-Fi dashboards; the immediate board checks are service/listen
  status, and remote mutation should use Fleet Ops or SSH tunnel until a
  reviewed token-aware remote dashboard path exists.

Next phases:

1. Add the full provider web-search slice behind explicit env/UI policy, with
   citations and no private GCS context sent to web search.
2. Decide whether to expose a token-aware Smart Wi-Fi remote mutation path in
   GCS/Fleet Ops only, rather than weakening the node dashboard guard.
3. Sync this fix into official/client release after production smoke passes and
   no private field data is present.

## Assistant Streaming UX And Repo Sync - 2026-05-29

Goal: make `/simurgh` feel less like a static form submission by streaming
operator-visible progress and answer chunks inside the active assistant bubble,
while keeping MCP, provider use, and safety boundaries unchanged.

Implemented:

- Added `POST /api/v1/simurgh/assistant/turns/stream` in
  `gcs-server/api_routes/simurgh.py`. The route uses the same assistant-turn
  creation path as the normal POST route and emits SSE events: `progress`,
  `delta`, `final`, `done`, and sanitized `error`.
- Added `streamSimurghAssistantTurnResponse()` in the dashboard GCS API service.
  It parses SSE incrementally with fetch/readable-stream support and falls back
  to the existing non-streaming POST path only when streaming is unavailable.
- Updated `SimurghOperatorPage` so a placeholder assistant message appears
  immediately, progress chips render in that same message, deltas append to the
  content, and local history persists only completed messages.
- Removed the older detached pending bubble path to avoid two competing progress
  UIs.
- Updated generated OpenAPI candidates. The stream route is present as a
  non-callable, review-only candidate with `default_registry_exposure: exclude`.
- Updated generated docs index plus Simurgh operator/API/MCP docs. MCP remains
  Streamable HTTP JSON on `POST /api/v1/simurgh/mcp`; the assistant SSE route is
  first-party dashboard UX, not an MCP transport.
- Added `tools/run_gcs_dashboard_service.sh` so the Hetzner demo service can be
  restarted with stable real-mode, circuit-breaker-on, always-confirm-on posture
  without nested shell quoting.

Validation on Hetzner only:

- Client repo: Simurgh backend suite `89 passed`.
- Client repo: dashboard stream/markdown Jest suite `46 passed`.
- Client repo: production dashboard build compiled successfully.
- Official repo: same backend suite `89 passed`.
- Official repo: same dashboard stream/markdown Jest suite `46 passed`.
- Official repo: production dashboard build compiled successfully.
- Focused leak scan of the changed diff found no pasted temporary OpenAI key,
  OpenRouter key, board password, Arnaud username, or field NetBird IP pattern.
- `git diff --check` passed before commit.

Deployment and repo state:

- Hetzner production restarted from `/root/catchadrone_gcs` using the new
  launcher. Health checks after restart: dashboard `/simurgh` HTTP 200 and GCS
  `/api/v1/system/health` HTTP 200.
- Live worker env confirmed `MDS_MODE=real`, OpenAI provider/model,
  `MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`,
  `MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true`, `MDS_MCP_ENABLED=true`,
  `MDS_AUTH_ENABLED=true`, and `MDS_API_AUTH_ENABLED=false`.
- Unauthenticated Simurgh status/stream calls return `401 authentication_required`,
  as expected for the authenticated demo.
- Official public repo pushed to `main` at `016b0ee4`, tag
  `v5.5.13-simurgh-streaming`.
- Client repo pushed to `main` at `66d8d210`, tag
  `cad-v5.5.13-simurgh-streaming`.

Reviewer notes:

- UI/UX reviewer: approved as a clear interaction-quality improvement. It does
  not yet implement provider-native token streaming, but the dashboard now shows
  staged work and incremental answer rendering in the familiar chat pattern.
- MCP reviewer: approved because the SSE route is not mixed into MCP and remains
  excluded from generated callable candidates.
- Backend/API reviewer: approved because the streaming route reuses the normal
  assistant-turn creation/audit/history path and has focused SSE regression
  coverage.
- Safety/field reviewer: approved because real mode was preserved and all
  non-execution safety posture stayed forced on in production.

Next slice:

1. Continue answer-quality work: reduce repeated deterministic responses, make
   follow-up transforms feel more conversational, and expand general/MDS-adjacent
   coverage through query planning/retrieval/provider gates rather than
   hardcoded examples.
2. Add browser-level visual regression when Playwright is available on Hetzner,
   especially for streaming progress, markdown tables, copy controls, and chat
   history row actions.
3. If PM wants true token-level model streaming later, add it behind the same
   provider safety invariants (`store=false`, no model tools, no raw private
   evidence egress) rather than weakening the current GCS-side stream contract.

## 2026-05-29 Slice: Provider-Composed Read-Only Evidence

Goal: make authenticated Simurgh dashboard answers feel more like a live expert
without weakening the deterministic MDS evidence path or exposing provider-side
tool execution.

Implemented:

- Added a provider-composition pass for authenticated dashboard/operator turns
  when `MDS_AGENT_PROVIDER=openai` and a read-only local MDS tool produced the
  answer evidence.
- The assistant now builds a synthetic `session.read_only_mds_evidence` context
  document containing the selected local tool intent, response mode, tool IDs,
  and local answer. OpenAI composes from that bounded context only.
- The OpenAI request remains non-tool: `tool_choice=none`, `tools=[]`,
  `store=false`, and no direct drone API, MAVSDK, raw command, mutation, or
  deployment action is exposed to the provider.
- The router only enables this path for authenticated operator/admin/session or
  bearer users with valid agent/admin scope. Local unauthenticated MDS answers
  remain deterministic and do not contact a provider.
- Provider-composition failures fall back to the local read-only answer and
  record sanitized metadata for audit/debugging.
- Updated public docs and the generated public docs index so future retrieval
  and MCP-adjacent documentation describe this layer accurately.
- Replaced the Simurgh UI mark with a transparent dashboard-safe wing icon and
  made history/settings popovers opaque to avoid the transparent menu issue PM
  reported.

Validation on Hetzner only:

- Focused backend suite: `148 passed`.
- Dashboard stream/markdown/API Jest suite: `46 passed`.
- Dashboard production build compiled successfully.
- Generated docs index was stale after documentation changes; regenerated it.
- Broad Simurgh/API/agent/MCP/docs suite after regeneration: `213 passed`.
- Official repo validation after public-safe sync: `213 passed`; dashboard Jest
  suite `46 passed`; production build compiled successfully.
- Client production restarted from the checked-in launcher and returned
  dashboard `/simurgh` HTTP 200 plus API health HTTP 200.
- Final patch refs: client `60f9c746a` /
  `cad-v5.5.15-simurgh-evidence-composer-fix`, official `381c311a` /
  `v5.5.15-simurgh-evidence-composer-fix`.
- Final patch validation: client and official backend suites both passed `214`
  Simurgh tests after adding the provider-composition fallback-label regression.
- Follow-up smoke-runner fix: `tools/run_simurgh_provider_smoke.py` now
  bootstraps the repo root as well as `gcs-server`, so the documented smoke
  command works from a normal shell without manually setting `PYTHONPATH`. Added
  a CLI regression that removes `PYTHONPATH`; client and official focused smoke
  tests passed, and both dry/live smoke commands passed on Hetzner. Patch refs:
  client `69f6c4b5a` / `cad-v5.5.16-simurgh-smoke-runner-fix`, official
  `0097dffe` / `v5.5.16-simurgh-smoke-runner-fix`.
- Connected-drone query adaptation patch: added config-driven aliases for
  common `connected` typos so prompts like `what drones are conencted?` route
  to live presence/telemetry evidence, not fleet configuration. Replaced the
  touched NetBird-style test IP with RFC 5737 `192.0.2.33` before official sync.
  Client and official `tests/test_agent_assistant_runtime.py` both passed `94`
  tests. Patch refs: client `99d12d39c` /
  `cad-v5.5.17-simurgh-query-adaptation`, official `9344b50b` /
  `v5.5.17-simurgh-query-adaptation`.

Reviewer notes:

- AI-agent reviewer: approved. This avoids hardcoded answer overfitting by
  letting the model compose wording from reviewed local evidence.
- Backend/API reviewer: approved. The normal assistant route and audit path are
  reused; no parallel execution path was introduced.
- MCP reviewer: approved. MCP tool registry and MCP transport are unchanged;
  this is dashboard/provider composition over local read-only evidence.
- Safety reviewer: approved. Circuit breaker and always-confirm semantics are
  unchanged, and provider composition has no action capability.
- UI/UX reviewer: approved for the targeted polish; remaining work should add
  browser-level visual regression around chat history menus, streaming states,
  markdown tables, copy controls, and mobile layout.

Next slice candidates:

1. Run production smoke from an authenticated dashboard session to verify the
   provider-composed path against PM prompts and capture safe trace metadata.
2. Add chat history row actions for single-conversation deletion with minimal
   hover-only controls.
3. Expand read-only telemetry evidence coverage for connected boards, GPS
   coordinates/status, and country/location interpretation without inventing
   live data.
4. Continue official/client sync with leak scans and tags after validation.

## 2026-05-29 Slice: Agent Core V2, MCP-Registered Advisory Tools, GPT-5.5 Defaults

Goal: fix the PM-reported "old chatbot" behavior without adding more brittle
question-specific answer branches. The failures were systematic: stale session
domains could hijack follow-ups, local read tools were selected too broadly,
provider failures surfaced as raw errors, and general/public questions could be
misrouted back to fleet/swarm evidence.

External architecture review notes used for this slice:

- Official MCP architecture separates tools, resources, and prompts, with
  dynamic `*/list` discovery and `tools/call` execution. MDS should keep this
  separation rather than treating every REST endpoint as a chat intent.
- FastAPI-MCP and FastMCP are useful future accelerators for OpenAPI/FastAPI to
  MCP candidate generation, but production MDS still needs deny-by-default
  classification, safety notes, schemas, tests, and auth review before exposing
  a tool.
- OpenAI Responses supports hosted tools such as web search and remote MCP, but
  MDS should only enable web search for public/general prompts and must not send
  private GCS state, logs, credentials, or field evidence to web search.
- Current RAG best practice remains: query planning, scoped deterministic tools,
  retrieval evals, and bounded context before fine-tuning or unbounded agent
  loops.

Implemented:

- Extended safe session metadata with `last_intent`, `last_response_mode`, and
  public-safe domains for `general`, `public_geography`, `docs`, `mcp`, `ui`,
  and `autopilot_support` so follow-ups can be repaired without storing raw
  transcript text.
- Added MCP-registered local advisory tools:
  `simurgh.general_knowledge.read`, `simurgh.public_places.read`, and
  `simurgh.geodesy.calculate`. They are read-only, GCS-boundary, policy-gated
  tools in `config/agent_tools.yaml`, not hidden dashboard-only branches.
- Added intent filters in the shared tool executor so general/geography tools do
  not answer unrelated MDS prompts and MDS fleet/swarm tools do not steal public
  geography or general-knowledge prompts.
- Added a frame-bound repair path so follow-ups like `yes, meters and WGS84`
  after a Damavand question stay in the public-geography frame instead of
  falling back to the previous swarm/fleet topic.
- Added graceful provider-failure fallback for recoverable OpenAI/network errors
  so users receive a bounded answer path rather than a raw `network error`.
- Updated the default OpenAI model to `gpt-5.5` in config, env registry docs,
  and eval fixtures. Production can still override the model from Simurgh
  settings or `/environments`.
- Curated public, non-sensitive knowledge/config sources:
  `config/agent_general_knowledge.yaml` and
  `config/agent_public_places.yaml`. These cover PM-critical general questions
  such as `what is MAVLink`, PX4-vs-ArduPilot support posture, Tehran/New York
  distance, and Damavand WGS84/elevation/radius-loop math without leaking field
  coordinates or relying on model guesses.
- Polished `/simurgh` UI noise: progress is now a single subtle in-message
  status line, copy/history controls are less visible until hover/focus, history
  popovers are opaque, and the Simurgh mark was replaced with a cleaner
  dashboard-safe wing icon.
- Fixed the advisory eval CLI import bootstrap so it runs from a normal shell
  without manual `PYTHONPATH` and remains hermetic against host OpenAI env vars.

Validation on Hetzner only:

- `tools/run_simurgh_advisory_evals.py --json`: 14/14 scenarios passed.
- `tests/test_agent_assistant_evals.py`: 28 passed.
- Broad focused backend regression covering assistant runtime, GCS assistant
  route, MCP route, Simurgh routes, evals, read tools, and query understanding:
  216 passed in 4m38s.
- Simurgh dashboard Jest page test: 9 passed before this documentation update.

Reviewer notes:

- AI-agent reviewer: approved the architectural direction. The fix reduces
  keyword-router overreach and adds scoped evidence tools plus provider fallback;
  it is not a one-off answer patch for the PM examples.
- MCP reviewer: approved. New capabilities are in the registry/policy surface,
  remain read-only, and are discoverable through MCP instead of hidden in UI-only
  code.
- Safety/field reviewer: approved. No action, mutation, raw command,
  drone-local API, or circuit-breaker behavior changed.
- UI/UX reviewer: approved the targeted noise reduction. Remaining work is
  browser-level visual regression and single-conversation history deletion.

Next immediate slice:

1. Re-run dashboard Jest/build after this docs update.
2. Run diff/leak checks.
3. Sync to official release repo with public-safe files only, validate there,
   commit/tag/push both repos, then restart/verify client production.

## 2026-05-29 Final Deployment Checkpoint

Completed after the Agent Core V2 slice:

- Client repo pushed at `43f676345`, tag
  `cad-v5.5.19-simurgh-launcher-model-default`.
- Official repo pushed at `d0a9d469`, tag
  `v5.5.19-simurgh-launcher-model-default`.
- Feature commit before the launcher-default cleanup was `1556fcf85` client and
  `eeeace52` official.
- Official docs index was regenerated inside the official checkout, not copied
  from client, because official/public SITL docs intentionally differ from the
  client docs. This avoids leaking client-specific SITL archive wording into the
  public generated docs index.
- Production was restarted from `/root/catchadrone_gcs` in tmux session
  `MDS-GCS` using `MDS_SAFE_PRODUCTION_DEMO=true ./tools/run_gcs_dashboard_service.sh`.
- Runtime worker env verified:
  `MDS_MODE=real`, `MDS_AGENT_PROVIDER=openai`,
  `MDS_AGENT_OPENAI_MODEL=gpt-5.5`, circuit breaker on, always-confirm on,
  web search on, MCP enabled/auth-required, auth enabled, API auth disabled.
- Production health checks passed: dashboard `/simurgh` HTTP 200, GCS health
  HTTP 200, unauthenticated Simurgh status HTTP 401 as expected.
- Live provider smoke passed on `gpt-5.5` without printing raw content.
- Authenticated chat smoke passed the PM failure classes for MAVLink/general
  knowledge, Damavand public geography, WGS84 follow-up frame repair, and typo
  connected-drone routing.
- MCP smoke passed with protocol `2025-11-25`, 31 tools, 1 prompt, 35 resources.
- PM handoff report was updated in
  `docs/plans/2026-05-24-simurgh-pm-ops-telegram-report.md`.

Next recommended work after PM/funder retest:

1. Add browser-level Playwright visual regression for `/simurgh` markdown,
   history row actions, mobile controls, streaming progress, and copy buttons.
2. Add tested external-client recipes for n8n, Claude Desktop, VS Code, and any
   stdio/SSE bridge needed by clients that cannot call Streamable HTTP directly.
3. Continue reducing private local routing by moving more advisory evidence into
   typed registry/MCP tools with explicit result contracts and evals.
4. Keep mutation/action wrappers out of production until SITL-first validation,
   explicit operator approval UI, audit evidence, and circuit-breaker final-stop
   behavior are complete.

## 2026-05-29 Update: Read-Only MCP/API Coverage Completion

PM issue addressed:

- Simurgh needed to cover every safe read-only GCS capability that an operator
  can inspect through the dashboard/API, without creating hardcoded chat-only
  answers or a parallel MCP layer.
- The previous OpenAPI candidate review endpoint showed partial promotion
  coverage; this made it harder to prove that future API drift is visible and
  reviewable.

What changed:

- Promoted all currently eligible read-only OpenAPI route candidates into the
  curated registry/policy/MCP surface with explicit schemas, docs, sensitivity,
  and safety notes.
- New read-only groups now include command statistics/status, fleet enrollment
  candidates, Fleet Ops sidecar state, origin/global-origin/deviations/elevation,
  PX4 parameter policy/profile/snapshot/job reads, QuickScout/SAR status and
  workspace reads, swarm trajectory leader/policy/preview/recommendation/
  validation reads, system/env/SITL operation reads, health aliases, and Simurgh
  self-observability reads.
- `/api/v1/simurgh/tool-candidates` now reports
  `summary.registry_coverage`, including total eligible route candidates,
  promoted matches, unpromoted counts, coverage percent, and a preview of any
  remaining gaps.
- Current coverage is `78/78` eligible read-only route candidates promoted
  (`100.0%`). Generated candidates remain review-only and never become callable
  until explicitly promoted into `config/agent_tools.yaml` with tests and docs.
- Improved the capability-catalog answer so it prioritizes core operator tools
  such as fleet telemetry, heartbeats, network status, show validation, swarm
  validation, logs, runtime status, docs search, and candidate coverage instead
  of showing a noisy alphabetical slice of the registry.
- Regenerated `docs/agent-context/generated/simurgh-docs-index.json` so the RAG
  layer can retrieve the updated MCP/candidate coverage guidance.

Validation on Hetzner:

- `tools/generate_simurgh_tool_candidates.py --check`: passed.
- `tools/generate_simurgh_docs_index.py --check`: passed after regeneration.
- Focused registry/candidate tests: `4 passed`.
- MCP/registry/candidate suite:
  `tests/test_gcs_simurgh_mcp.py tests/test_agent_runtime_foundation.py tests/test_simurgh_tool_candidate_generator.py`
  passed (`46 passed`).
- Assistant behavior subset for capability catalog, live telemetry routing,
  ArduPilot boundary, general MAVLink/weather, fleet follow-up, and fleet/log
  topic override passed (`6 passed`).
- Broad Simurgh backend suite covering assistant runtime/routes, MCP, query
  adaptation, retrieval quality, read tools, evals, and candidate generation:
  `230 passed` in 5m39s.
- Targeted dashboard Jest suite under nvm Node 22:
  `src/pages/SimurghOperatorPage.test.js` and `src/services/gcsApiService.test.js`
  passed (`46 passed`).
- Dashboard production build under nvm Node 22 compiled successfully.
- `git diff --check`: clean.

Reviewer status:

- AI-agent reviewer: approved. The work moves capability exposure into a single
  registry-driven surface instead of adding more brittle keyword answers.
- MCP/API reviewer: approved. The MCP surface remains deny-by-default,
  policy-gated, and generated OpenAPI routes are only a review queue, not an
  automatic execution path.
- Safety reviewer: approved. No mutation, action, drone-local API, raw command,
  launch, upload, delete, apply, sync, stream, or artifact-download route was
  promoted.
- PM/product reviewer: approved for the read-only coverage slice, with the next
  focus on PM-visible retest quality and official/client repo synchronization.

Next recommended work:

1. Run a broader backend/Jest/build validation on Hetzner after this checkpoint.
2. Review for duplicate/noisy tool naming and any public/private leakage before
   syncing to the official repo.
3. Sync public-safe changes to official, validate there, commit/tag/push both
   repos, then restart/verify client production if the field window allows.

## 2026-05-29 Update: Simurgh Chat History And Visual Quieting Slice

Goal: continue PM-visible ChatGPT-style polish without changing the read-only
agent/MCP safety boundary.

What changed:

- Moved the destructive `Clear all chats` action behind a small history-header
  overflow menu so it is no longer a loud always-visible control.
- Kept `Start new chat` as an icon button with an accessible label.
- Added close-on-outside-click and Escape behavior for chat history menus.
- Changed per-chat row action labels to `More actions for <chat title>` and
  kept single-chat deletion scoped to local browser history only.
- Made history overflow menus use an opaque/elevated background to address the
  transparent popover feedback.
- Quieted assistant message bubbles so the transcript reads more like a modern
  chat surface while preserving table/code/link rendering and copy controls.
- Added public UX contract notes to `docs/guides/simurgh-operator.md`.

Validation on Hetzner:

- Focused dashboard Jest test under nvm Node 22:
  `src/pages/SimurghOperatorPage.test.js` passed (`10 passed`).

Reviewer status:

- UI/UX reviewer: approved for this targeted polish because destructive actions
  are less prominent, popovers are clearer, and the transcript is less card-heavy.
- MCP/API reviewer: approved because no MCP route, registry tool, provider tool,
  or backend action path changed.
- Safety reviewer: approved because this is local UI history and presentation
  only; it does not alter runtime mode, circuit breaker, confirmation policy,
  auth, or drone/GCS state.

Next recommended work:

1. Run the paired dashboard service test/build and backend smoke after doc index
   regeneration.
2. Sync public-safe UI/docs/test changes to official, validate, tag, push, and
   restart production.
3. Add browser-level visual regression when Playwright/browser tooling is
   available in the Hetzner validation image.

## 2026-06-01 Update: Simurgh Dashboard Prompt Eval Guardrail Slice

Goal: turn the PM/funder conversational failure examples into a reusable,
versioned dashboard eval suite so future routing, memory, language, docs, and
tool-use changes are tested through the same assistant path the dashboard uses.

What changed:

- Added `docs/agent-context/evals/simurgh-dashboard-prompts.yaml`, a PM-style
  multi-turn prompt suite covering fleet/telemetry follow-ups, show readiness,
  log interpretation, setup/onboarding, general non-MDS questions, public
  geography math, PX4/ArduPilot boundaries, and MCP capability questions.
- Added `gcs-server/agent_runtime/dashboard_prompt_evals.py` plus
  `tools/run_simurgh_dashboard_prompt_evals.py` so the suite runs through
  `create_assistant_turn` instead of a separate canned-answer harness.
- Added `tests/test_simurgh_dashboard_prompt_evals.py` to keep the suite in CI
  and produce machine-readable JSON reports for future PM handoff evidence.
- Fixed routing/memory regressions found by the suite: public geography
  follow-ups no longer inherit stale swarm/fleet context, empty connectivity
  answers state GPS/coordinate unavailability clearly, and workflow/capability
  answers carry explicit response modes for cleaner downstream rendering.
- Updated the Simurgh operator guide and regenerated the public docs index.
- Updated route/env hygiene checks for the SSE assistant stream route and
  internal dashboard-service runtime variables.

Validation on Hetzner:

- Client repo focused prompt eval: `tools/run_simurgh_dashboard_prompt_evals.py`
  passed (`16 passed, 0 failed`).
- Client focused backend subset:
  `tests/test_simurgh_dashboard_prompt_evals.py tests/test_agent_assistant_runtime.py tests/test_agent_query_understanding.py tests/test_agent_mds_read_tools.py`
  passed (`123 passed`).
- Client broad Simurgh/MCP backend suite passed (`280 passed` in 7m59s).
- Official repo generated-doc/tool-candidate checks passed.
- Official broad Simurgh/MCP backend suite passed (`280 passed` in 8m08s).
- `git show --check` passed for client and official heads.
- Changed-line leak scan found no newly introduced private IPs, board
  credentials, API keys, field passwords, private repo paths, or site names.
- Production dashboard was restarted on the new client tag and smoke checked:
  API health OK, dashboard HTTP 200, runtime remains `MDS_MODE=real`, Simurgh
  agent enabled, MCP enabled, OpenAI provider configured, circuit breaker on,
  and always-confirm on.

Published refs:

- Client: `85d4e2e64` / `cad-v5.5.31-simurgh-dashboard-prompt-evals`.
- Official: `0a49139c` / `v5.5.29-simurgh-dashboard-prompt-evals`.

Reviewer status:

- AI-agent reviewer: approved. The slice tests real orchestration behavior,
  not a new set of demo-only string matches.
- MCP/API reviewer: approved. MCP remains registry/policy driven, protected by
  scoped auth, and limited to approved read-only tools.
- Safety reviewer: approved. No mutation, action, launch, upload, parameter
  change, direct drone-local API, or circuit-breaker bypass was introduced.
- UI/UX reviewer: no frontend changes in this slice; next UI work should use
  browser-level visual evidence for the chat surface.
- PM/product reviewer: approved for retest guardrail coverage. The next PM
  checkpoint should focus on visual polish and remaining read-only capability
  gaps before action dry-runs.

Next recommended work:

1. Run a UI walkthrough/visual slice for the Simurgh chat surface: history
   actions, hover-only copy controls, markdown tables/code, mobile layout,
   progress indicators, and logo/icon consistency.
2. Audit remaining read-only dashboard/API coverage against the registry/MCP
   menu: telemetry, battery/health, sidecar Wi-Fi/MAVLink/node info,
   environment/runtime, logs, show/swarm/SITL, setup/onboarding, and docs.
3. Add external MCP client smoke docs/evidence for n8n, Claude Desktop/VS Code,
   and any bridge/proxy pattern needed for clients that only support stdio MCP.
4. Only after PM approval of read-only behavior, plan the guarded action
   dry-run slice with circuit breaker as the final execution stop and always
   confirm one layer before execution.

## 2026-06-01 Update: Simurgh Chat Control Visual Polish Slice

Goal: respond to PM feedback that copy and overflow controls were still too
visible by reducing always-on UI noise without changing any Simurgh runtime,
MCP, provider, or safety behavior.

What changed:

- Reduced the always-visible opacity of the chat-history header overflow
  control.
- Reduced the size of per-message and code-block copy controls so they read
  closer to familiar chat assistant affordances.
- Hid row-level chat actions and copy buttons entirely in touch/hoverless
  layouts until focus, active, or expanded states make them relevant.
- Preserved existing accessibility labels, keyboard focus behavior, markdown
  table/code rendering, code copy, message copy, and per-chat delete behavior.

Validation on Hetzner:

- Client focused Simurgh page Jest suite passed: `10 passed`.
- Client production dashboard build passed under nvm Node 22.
- Official focused Simurgh page Jest suite passed: `10 passed`.
- Official production dashboard build passed under nvm Node 22.
- `git diff --check` and changed-line leak scans were clean.
- Production restarted on `cad-v5.5.33-simurgh-chat-control-polish`; API health
  OK and dashboard served HTTP 200.
- Runtime posture remained unchanged: `MDS_MODE=real`, Simurgh agent enabled,
  MCP enabled, OpenAI provider configured, circuit breaker on, always-confirm
  on.

Published refs:

- Client: `7951feec7` / `cad-v5.5.33-simurgh-chat-control-polish`.
- Official: `f36933cf` / `v5.5.30-simurgh-chat-control-polish`.

Reviewer status:

- UI/UX reviewer: approved for this narrow visual-noise reduction. The next UI
  slice should still collect authenticated browser screenshots or a dedicated
  non-production visual harness before broader layout changes.
- MCP/API reviewer: approved. This slice changed CSS only.
- Safety reviewer: approved. No action policy, circuit breaker, confirmation,
  MCP exposure, auth, provider, drone command, or GCS mutation path changed.

Next recommended work:

1. Build an authenticated/non-production browser visual check for `/simurgh` so
   PM-facing screenshots can be captured without weakening production auth.
2. Continue the read-only capability coverage audit against the registry/MCP
   menu and dashboard/API workflows.
3. Keep action/dry-run work deferred until read-only PM retest and coverage are
   accepted.

## 2026-06-01 Update: Simurgh Registry Routing Boundaries Slice

Goal: fix PM-facing failures where the registry/MCP read layer could steal
high-level conversation, docs, workflow, translation, or follow-up prompts and
return a stale broad status table instead of answering the operator's actual
question.

What changed:

- The dashboard API route now computes the local MDS read intent once and passes
  it into registry read planning, so helper tests and real dashboard chat share
  the same routing boundary.
- Registry read planning now defers to the advisory/docs/conversation layer for
  broad fleet, logs, show, swarm, runtime, docs, workflow, general-knowledge,
  geography, and comparison prompts unless the user asks for a concrete typed
  read-only API record.
- Concrete typed registry reads still work for SITL, SAR, sidecars, log
  sessions, terrain/elevation, and other approved read-only registry tools.
- When a typed read requires a missing identifier, Simurgh now runs an approved
  discovery/list read where possible and asks for the specific missing id
  instead of falling back to a generic stale summary.
- Fleet-summary classification no longer treats the word `configured` alone as
  fleet intent, preventing unrelated setup/SITL configuration prompts from being
  hijacked.

Validation on Hetzner:

- Client broad Simurgh/MCP suite passed: `283 passed`.
- Client focused post-cleanup suite passed: `68 passed`.
- Official focused suite passed from the official working tree: `68 passed`.
- Generated docs-index and tool-candidate checks passed in both client and
  official repos.
- `git diff --check` and changed-line leak scans were clean.
- Production restarted from the client repo. API `/health` returned OK and the
  dashboard served HTTP 200 on port `3030`.
- Runtime posture remained safe: `MDS_MODE=real`, Simurgh enabled, OpenAI
  provider configured, web search enabled, MCP enabled with auth required,
  circuit breaker on, always-confirm on.

Published refs:

- Client: `7b545ef6c` / `cad-v5.5.35-simurgh-registry-routing-boundaries`.
- Official: `09f7d735` / `v5.5.31-simurgh-registry-routing-boundaries`.

Reviewer status:

- AI-agent reviewer: approved for this slice. The change reduces deterministic
  over-routing and preserves conversational/advisory ownership for ambiguous,
  general, docs, workflow, and follow-up prompts.
- MCP/API reviewer: approved. Registry reads remain policy-filtered,
  read-only, and executed through the same internal adapter as MCP `tools/call`.
- Safety reviewer: approved. No non-read-only action path, command execution,
  launch/upload/config mutation, direct drone-local API, or circuit-breaker
  bypass was introduced.
- Product reviewer: approved for PM retest of the prior bad cases, with clear
  remaining debt around deeper typed planning, richer referent memory, and
  end-to-end browser visual verification.

Next recommended work:

1. Continue the read-only capability coverage audit against every dashboard/API
   workflow a normal operator can inspect: telemetry, battery/health, live
   coordinates, logs, show/swarm/SITL, sidecars, Wi-Fi/MAVLink, env/runtime,
   onboarding, and docs.
2. Introduce a structured planner contract for future slices: selected tool,
   typed arguments, missing arguments, confidence, evidence source, safety
   posture, and final answer/citation fields.
3. Expand paraphrase, multilingual, follow-up, and negative-routing evals so PM
   examples and novel equivalent wording both stay covered.
4. Keep action/dry-run capability deferred until read-only coverage and PM
   retest are accepted.

## 2026-06-01 Update: Simurgh Live Telemetry Health Slice

Goal: improve read-only operator answers for live fleet health questions so
Simurgh does not fall back to static configuration when the user asks about GPS,
coordinates, altitude, battery, arm/readiness state, flight mode, or system
status.

What changed:

- Fleet live-state routing now recognizes battery, voltage, arming, readiness,
  flight mode, system status, health, and failsafe wording as live telemetry
  questions.
- Fleet connectivity answers can now render health-only, position-only, or
  combined position-and-health summaries from the latest GCS telemetry snapshot.
- Combined follow-ups such as asking for location, altitude, battery, and arm
  state after a fleet topic stay on the live telemetry path instead of being
  treated as unrelated public geography/general text.
- Missing live telemetry fields are reported as `unavailable` rather than being
  implied healthy.

Validation on Hetzner:

- Client targeted regression passed.
- Client focused Simurgh read-only/planner suite passed: `172 passed`.
- Official focused Simurgh read-only/planner suite passed from the official
  working tree: `172 passed`.
- Generated docs-index and tool-candidate checks passed in both client and
  official repos.
- `git diff --check` and changed-line leak scans were clean before publishing.

Published refs:

- Client: `d9518774a` / `cad-v5.5.37-simurgh-live-telemetry-health`.
- Official: `f8c40084` / `v5.5.32-simurgh-live-telemetry-health`.

Reviewer status:

- AI-agent/product reviewer: approved this narrow telemetry slice, while
  calling out that the larger remaining gap is semantic reachability from chat,
  not raw registry inventory.
- MCP/API reviewer: registry coverage remains strong for classifier-eligible
  read-only GET candidates, with future safe additions recommended for specific
  excluded read-only inspection routes such as fleet git-sync, SITL image/log
  inventory, SkyBrush plot lists, and redacted auth self/status.
- Safety reviewer: approved. The slice stays read-only, uses existing telemetry
  snapshots, and does not add command, config mutation, upload, launch, or
  drone-local API execution.

Next recommended work:

1. Implement the structured read-only planner contract recommended by reviewers:
   intent, domain, candidate tools, typed arguments, missing arguments,
   confidence, evidence sources, and safety posture.
2. Move semantic reachability toward metadata-driven registry/tool retrieval so
   promoted safe APIs become chat-discoverable without hand-writing every new
   phrasing.
3. Add generated eval coverage by read-only tool family: status/list, typed
   detail, missing-argument clarification, and follow-up reference resolution.
4. Keep all action/dry-run capability deferred until read-only planner coverage
   is reviewed and accepted.

## 2026-06-01 Update: Structured Read-Only Planner Trace Slice

Goal: make Simurgh read-only routing inspectable and auditable before deeper
metadata-driven planning work, without changing the execution boundary or
adding any action capability.

What changed:

- Added a sanitized `read_only_plan` contract for local advisory turns with
  intent, response mode, topic/domain, confidence, missing arguments,
  execution layer, safety posture, and candidate evidence tool ids.
- Assistant audit metadata and dashboard/API turn traces now expose this plan
  without raw prompt text, normalized prompt text, secrets, or transcript bodies.
- Registry read-only execution plans now expose the same public metadata shape,
  including missing required identifiers for typed tools such as log sessions.
- Reviewer gate found and fixed an important trace-quality issue: local planner
  evidence ids now reference only real tools present in `config/agent_tools.yaml`.
  Documentation-based local answers point to `mds.docs.search` and
  `mds.docs.chunk.read` instead of fictional per-document tool names.

Validation on Hetzner:

- Client targeted planner/trace regressions passed.
- Client focused Simurgh suite passed after the registry-id fix: `176 passed`.
- Official focused Simurgh suite passed from the official working tree:
  `176 passed`.
- Generated docs-index and tool-candidate checks passed in both client and
  official repos.
- `git diff --check`, changed-line leak scans, and planner trace tool-id
  registry validation were clean in both repos.

Published refs:

- Client: `2f411e156` / `cad-v5.5.39-simurgh-read-only-planner-trace`.
- Official: `8f8f504f` / `v5.5.33-simurgh-read-only-planner-trace`.

Reviewer status:

- AI-agent/product reviewer: approved this foundation slice as an observability
  improvement, with the caveat that it is not the final semantic planner.
- MCP/API reviewer: approved after the trace ids were constrained to the real
  registry. The next slice should derive/rank tools from registry metadata
  instead of relying on local advisory intent scaffolding.
- Safety reviewer: approved. The slice adds trace/audit metadata only; it does
  not add drone commands, uploads, config mutation, runtime mutation, or
  drone-local API access.

Next recommended work:

1. Replace local advisory evidence scaffolding with registry-derived semantic
   tool retrieval/ranking so newly promoted safe APIs become discoverable with
   less manual routing code.
2. Add generated eval coverage by read-only tool family, including list/status,
   typed detail, missing-argument clarification, follow-up memory, multilingual
   paraphrases, and negative routing.
3. Continue read-only coverage for remaining operator-inspectable surfaces such
   as sidecars, Wi-Fi/MAVLink info, env/runtime, setup/onboarding, and docs.
4. Keep action/dry-run execution deferred until read-only planner coverage is
   accepted by PM/founders testing.

## 2026-06-01 Update: Registry Metadata Tool Ranking Slice

Goal: make Simurgh select more specific read-only GCS/MCP tools from the
curated registry metadata, instead of depending only on hand-written local
intent branches. This keeps the assistant closer to the PM/founders target:
new safe APIs should become discoverable through the registry, while policy
still decides what may execute.

What changed:

- Added `selection_source` metadata to registry read plans so traces show
  whether a response came from domain rules, typed argument rules, discovery,
  or the metadata ranker.
- Added registry metadata ranking that scores tool ids, titles, tags, route
  paths, and descriptions, then supplements domain-selected read-only tools
  with more specific tools from the same namespace.
- Added namespace/context guards so a SITL prompt cannot accidentally pull a
  command-policy tool, and a fleet prompt stays within fleet-sidecar/network
  tools unless the registry/domain rules explicitly allow otherwise.
- Fixed a direct-action detector edge case so words such as `swarm` are not
  misread as action terms such as `arm`.
- Expanded safe result previews with common identifiers such as `hw_id`,
  `sidecar`, `transport`, `session_id`, `status`, `state`, and `message`, so
  read-only tool output is more useful without leaking raw payloads.

Validation on Hetzner:

- Client targeted metadata-ranking regressions passed.
- Client focused Simurgh suite passed: `181 passed`.
- Official focused Simurgh suite passed from the public release working tree:
  `181 passed in 493.73s`.
- Generated docs-index and tool-candidate checks passed in both client and
  official repos.
- `git diff --check` and changed-line leak scans were clean in both repos.

Published refs:

- Client: `6f3fcb2a4` /
  `cad-v5.5.41-simurgh-registry-metadata-ranking`.
- Official: `e088837d` /
  `v5.5.34-simurgh-registry-metadata-ranking`.

Reviewer status:

- AI-agent reviewer: approved the direction as a necessary step away from
  brittle phrase matching, with the caveat that it is still deterministic
  retrieval/ranking and should be followed by broader generated eval coverage.
- MCP/API reviewer: approved the policy-first ordering: explicit allowlist and
  registry classification remain ahead of ranking; HTTP method alone is not
  treated as a safety signal.
- Safety reviewer: approved. The slice only improves read-only selection and
  metadata previews; it does not add mutation, upload, launch, config-write,
  runtime-change, or drone-local execution.

Next recommended work:

1. Generate eval coverage by read-only tool family directly from the registry:
   list/status, typed detail, missing-argument clarification, follow-up memory,
   multilingual paraphrase, and negative routing.
2. Continue expanding read-only coverage for operator-visible dashboard/API
   surfaces such as sidecars, Wi-Fi/MAVLink info, environment/runtime, setup,
   onboarding, docs, health, and telemetry diagnostics.
3. Keep the MCP surface registry-driven and authenticated, with newly added APIs
   entering as classified candidates before becoming callable tools.
4. Defer action/dry-run capability until the read-only planner/ranker passes PM
   and founder testing with enough confidence.

## 2026-06-01 Update: Generated Registry Planner Coverage Slice

Goal: turn the previous registry metadata ranking work into a durable guardrail
so future safe read-only API promotions cannot silently become unreachable from
Simurgh chat. This directly addresses the PM concern about hardcoded one-off
answers: the tests now derive coverage from the approved registry itself.

What changed:

- Added generated planner coverage in
  `tests/test_agent_registry_planner_coverage.py` that walks the current
  policy-allowed read-only GET registry.
- The generated coverage verifies every no-argument read-only route tool can be
  selected from a generated title/status prompt. Current count: 56 tools.
- The generated coverage verifies every typed read-only route tool can be
  selected when sample identifiers are supplied. Current count: 23 tools.
- The generated coverage verifies typed tools without identifiers return
  missing-argument discovery instead of executing a malformed or guessed tool
  call.
- The generated coverage verifies direct action prompts such as launch, arm, and
  upload still do not create a registry execution plan.
- Improved registry planning so capability-catalog prompts no longer steal
  concrete registry state questions, domain aliases allow safe same-domain
  ranking, command/launch noun phrases such as command statistics and launch
  positions are not misclassified as actions, and typed metadata ranking can
  cover future typed tools without requiring every phrase to be hand-authored.

Validation on Hetzner:

- Client generated registry coverage: `6 passed`.
- Client focused Simurgh suite: `187 passed in 572.78s`.
- Official focused Simurgh suite: `187 passed in 562.30s`.
- Generated docs-index and OpenAPI tool-candidate checks passed in both repos.
- `git diff --check` and changed-line leak scans were clean in both repos.

Published refs:

- Client: `5a05d1378` /
  `cad-v5.5.43-simurgh-registry-planner-coverage`.
- Official: `72295b46` /
  `v5.5.35-simurgh-registry-planner-coverage`.

Operational note:

- The client repo had an unrelated local `swarm.json` config change
  (`hw_id 2` follow target changed from `0` to `1`) after the test/push step.
  It was not part of this slice and was intentionally left untouched.

Reviewer status:

- AI-agent reviewer: approved. This is a stronger production pattern than
  expanding a prompt FAQ because registry changes now create automatic planning
  pressure.
- MCP/API reviewer: approved. The test source of truth is the same curated,
  policy-filtered registry used by MCP; generated coverage still respects the
  deny-by-default review boundary.
- Safety reviewer: approved. The slice expands read-only planning coverage only;
  it does not add mutation, upload, launch, config-write, runtime-change, or
  drone-local execution.

Next recommended work:

1. Add an operator-facing read-only coverage report in Simurgh status/settings
   so PM/testers can see registry coverage counts and last eval status without
   reading test output.
2. Continue expanding actual read-only answer quality for the highest-value
   dashboard surfaces: telemetry diagnostics, sidecar/Wi-Fi/MAVLink status,
   env/runtime posture, setup/onboarding, logs, docs, health, show readiness,
   QuickScout, and swarm trajectory.
3. Keep actions deferred until read-only coverage has passed PM/founder retest;
   when actions start, keep the circuit breaker at the final executor layer and
   add dry-run/action-plan evals before any command path is enabled.

## 2026-06-01 Update: Smart Swarm Readiness Routing Slice

Goal: fix the PM-observed failure where a typo-heavy field-test question such as
"Is searm mission reay for test?" was misread as a SAR mission lookup with a
bogus `mission_id=reay`. The desired behavior is a read-only Smart Swarm
readiness advisory that uses GCS evidence and still keeps flight authority with
the human operator.

What changed:

- Added typo normalization for `ready` and `swarm` variants in the reviewed
  query-adaptation config.
- Tightened SAR/QuickScout mission-id extraction so generic words like `ready`,
  `reay`, and `test` cannot become mission identifiers, while explicit forms
  like `mission_id=sar-1` still work.
- Added a dedicated `swarm_readiness` read-only intent and answer path using the
  same approved registry/MCP tool IDs for swarm config, launch positions,
  heartbeat/telemetry presence, and swarm-trajectory status/validation.
- The Smart Swarm readiness answer now separates saved topology, topology
  blockers, live evidence, launch positions, trajectory package readiness,
  validation blockers/warnings, and mandatory human field checks.
- Added PM-style regression coverage so typo-heavy Smart Swarm field-test prompts
  do not fall into SAR mission 404 responses.
- Added a small Smart Swarm UI guardrail: clicking Commit now shows visible
  progress, preserves success/warning feedback, and is covered by a React test
  that verifies the commit call happens once.

Validation on Hetzner:

- Client Simurgh focused suite: `121 passed in 344.73s`.
- Client Smart Swarm frontend test: `2 passed`.
- Client generated docs-index check: passed.
- Client generated OpenAPI tool-candidate check with repo venv: passed.
- Client `git diff --check`: passed.
- Client changed-line leak scan excluding the PM's local `swarm.json` test config:
  clean.
- Official Simurgh focused suite: `121 passed in 323.40s` using the validated
  Hetzner Python environment from the client repo.
- Official Smart Swarm frontend test: `2 passed`.
- Official generated docs-index and OpenAPI tool-candidate checks: passed.
- Official whitespace and changed-line leak scans: clean.

Published refs:

- Client: `01b9011f9` /
  `cad-v5.5.45-simurgh-swarm-readiness-routing`.
- Official: `e0f565d4` /
  `v5.5.36-simurgh-swarm-readiness-routing`.

Operational note:

- The client repo still has the PM-approved local `swarm.json` working-tree
  change where `hw_id 2` follows `hw_id 1` for follow-test preparation. It was
  not included in the portable Simurgh/official slice.
- The Smart Swarm page still needs a dedicated UX simplification slice for the
  broader PM feedback about too much always-visible text. This slice only fixed
  the concrete commit-feedback failure without derailing Simurgh read-only work.

Reviewer status:

- AI-agent reviewer: approved. The fix improves intent disambiguation at the
  routing layer rather than adding a hardcoded answer for one PM sentence.
- MCP/API reviewer: approved. The new answer declares the same registry tool IDs
  it reads from, keeping dashboard chat and external MCP semantics aligned.
- Safety reviewer: approved. The slice remains read-only and explicitly reports
  that Smart Swarm topology is not flight readiness by itself.
- UI reviewer: approved for the narrow commit-feedback bug. Broader Smart Swarm
  page simplification remains open.

Next recommended work:

1. Restart the client production service and smoke the live Simurgh endpoint with
   real-mode, circuit-breaker-on posture.
2. Continue the read-only capability coverage slice for any remaining UI/API
   surfaces the operator can inspect manually, especially sidecar/Wi-Fi/MAVLink
   status, telemetry diagnostics, runtime/env status, setup/onboarding, logs,
   docs, health, shows, QuickScout, SAR, and Smart Swarm.
3. Schedule a separate Smart Swarm UX simplification slice: reduce permanent
   text, move guidance into docs/tooltips, and improve Git commit status/progress
   visibility consistently across repo-backed pages.

## 2026-06-01 Update: Fleet Ops Sidecar Diagnostics Slice

Goal: continue read-only Simurgh coverage for operator-visible dashboard/API
surfaces, focused on Fleet Ops sidecars because field operators and PM testing
keep asking about Wi-Fi dashboard access, MAVLink dashboards, node reachability,
profile drift, and mutation-token errors.

What changed:

- Expanded the `sidecar_status` answer from a dashboard-name summary into a
  read-only Fleet Ops diagnostic summary.
- The answer now adapts the same Fleet Ops sidecar table builders used by the
  GCS API where available, so Simurgh can summarize per-node service state,
  presence, mode, drift state, baseline status, dashboard URL/access, and fleet
  network detail row count.
- The answer declares the same registry/MCP-facing evidence IDs it depends on:
  `mds.fleet.sidecars.read`, `mds.fleet.sidecar.read`,
  `mds.fleet.network_details.read`, and
  `mds.fleet.sidecars.connectivity_profile.read`.
- Added explicit operator language that profile apply/reconcile/delete remains a
  human-controlled Fleet Ops action, and that dashboard mutation-token errors are
  sidecar mutation-token configuration issues, not MAVLink flight-control issues.
- Added regression coverage with synthetic Fleet Ops state proving Simurgh shows
  Wi-Fi/MAVLink sidecar node evidence while still avoiding mutation.

Validation on Hetzner:

- Client sidecar-focused tests: `3 passed`.
- Client Simurgh focused suite: `122 passed in 336.36s`.
- Client generated docs-index check: passed.
- Client generated OpenAPI tool-candidate check with repo venv: passed.
- Client `git diff --check`: passed.
- Client changed-line leak scan excluding the PM's local `swarm.json` test config:
  clean.
- Official Simurgh focused suite: `122 passed in 344.00s`.
- Official generated docs-index, OpenAPI tool-candidate, whitespace, and leak
  checks: passed.

Published refs:

- Client: `d3b56d3d3` /
  `cad-v5.5.47-simurgh-sidecar-diagnostics`.
- Official: `3f5b843d` /
  `v5.5.37-simurgh-sidecar-diagnostics`.

Operational notes:

- The client repo still has operator-local `swarm.json` edits from the UI:
  `hw_id 2` follows `hw_id 1`, with north/NED `offset_x` now set to `5.0`.
  This remains intentionally uncommitted because it is field/test configuration,
  not portable Simurgh code.
- The user reported that Smart Swarm Update worked after changing drone 2 north
  offset, but Commit still did not produce visible report/progress. Keep this as
  explicit Smart Swarm page debt for the next dedicated UI/repo-backed workflow
  slice after the next Simurgh checkpoint.

Reviewer status:

- AI-agent reviewer: approved. The answer now derives from Fleet Ops API-shaped
  state instead of hand-authored dashboard prose.
- MCP/API reviewer: approved. The declared tool IDs match the registry-facing
  read-only sidecar/network surfaces and remain deny-by-default for mutation.
- Safety reviewer: approved. The slice is read-only and makes mutation-token and
  profile-apply boundaries explicit.
- UI/PM reviewer: partial. Simurgh sidecar answers are improved; Smart Swarm page
  commit/status UX remains open debt.

Next recommended work:

1. Restart the client production service and smoke the live Simurgh endpoint with
   real-mode, circuit-breaker-on posture.
2. Continue read-only Simurgh coverage across remaining operator surfaces:
   telemetry diagnostics, runtime/env status, setup/onboarding, health, command
   tracker, SAR/QuickScout status/workspace/findings, and show/trajectory edge
   cases.
3. After the next Simurgh checkpoint, run the dedicated Smart Swarm UX/repo
   workflow slice: minimal text, clearer commit/report progress, and tests for
   update-vs-commit outcomes against the real git response shape.

## 2026-06-01 Update: Smart Swarm Commit Feedback Debt Closure

Goal: close the PM-reported Smart Swarm debt where changing an assignment and
clicking Update saved the file, but Commit appeared to do nothing because the UI
treated the saved file as a clean form baseline while the repository still had a
pending `swarm.json` write-back.

What changed:

- Split Smart Swarm save state into two concepts: staged form edits and saved
  GCS repo changes that still need git commit/write-back.
- The page now reads canonical GCS git status and keeps Commit enabled when
  `swarm.json` is saved locally but still uncommitted.
- Added a compact visible git write-back notice for checking, pending, success,
  warning, and failure states so operators do not have to rely on transient
  toast timing.
- Commit confirmation now explicitly states when the action is committing an
  already-saved `swarm.json` change rather than applying new form edits.
- Added a React regression test for the exact Update-then-Commit workflow state.

Validation on Hetzner:

- Client Smart Swarm frontend test: `3 passed`.
- Client dashboard production build: passed.
- Client `git diff --check`: passed.
- Client changed-line leak scan excluding the local `swarm.json` test config:
  clean.
- Official Smart Swarm frontend test: `3 passed`.
- Official dashboard production build: passed.
- Official whitespace and changed-line leak scans: clean.
- Client production smoke after restart: API health OK, dashboard HTTP 200,
  `MDS_MODE=real`, OpenAI provider enabled, MCP enabled, web search enabled,
  auth enabled, circuit breaker ON, always-confirm ON, safe production demo ON.

Published refs:

- Client: `292ffcea4` /
  `cad-v5.5.49-smart-swarm-commit-feedback`.
- Official: `533f4a72` /
  `v5.5.38-smart-swarm-commit-feedback`.

Operational notes:

- The client repo still has the operator-local `swarm.json` field-test formation
  edit and it remains intentionally uncommitted.
- This slice fixed the concrete Commit feedback failure. Broader Smart Swarm UX
  simplification remains future work: reduce permanent explanatory text, move
  detail into docs/tooltips, and keep workflow status visible but quiet.

Reviewer status:

- UI/UX reviewer: approved for the commit-feedback workflow. The notice appears
  only when git state or save feedback requires operator attention.
- Frontend reviewer: approved. State now distinguishes form baseline from repo
  dirty state and includes regression coverage.
- Repo/workflow reviewer: approved with one existing caveat: the shared GCS
  write-back helper still stages the repo broadly, so repo-backed pages should
  eventually move toward path-scoped commits where practical.

## 2026-06-04 Update: Simurgh Read-Only Operational Surface Hardening

Goal: resume Simurgh after the field-readiness interruption and close the next
set of PM-visible read-only coverage gaps without hardcoding one-off answers.
The board deploy-key/live sync work is explicitly deferred to a separate field
operations slice; this checkpoint stays on the dashboard assistant, MCP/registry
surface, evals, and public-safe documentation.

What changed:

- Expanded the PM-style dashboard prompt suite from 16 to 29 turns across
  runtime/environment/health, Fleet Ops sidecars, command tracker, repository
  sync, node boot/init progress, origin/launch positions, PX4 policy, SAR,
  Smart Swarm readiness, and SITL setup guidance.
- Added `sar` as an allowed `conversation_topic` for the local operator question
  adapter so QuickScout/SAR follow-ups do not fall back to mock/provider text.
- Corrected backend-log answer metadata to use the actual MCP/registry log
  tools: `mds.logs.sessions.read` and `mds.logs.sources.read`.
- Tightened command-status wording so read-only command tracker questions are
  not misclassified as direct command execution requests.
- Tightened GCS/Simurgh service-health routing so health questions do not get
  swallowed by the runtime-mode summary.
- Added node boot/init progress as a first-class local read-only intent backed by
  `mds.fleet.node_boot_status.read`. This covers field/operator phrasing such
  as boards still initializing, loading up slowly, or stuck in git-sync phase.
- Fixed generated registry planner coverage for the fleet node boot-status
  endpoint so “boot” is not treated as a fleet-node `hw_id` argument.
- Cached query-adaptation config loading to keep the expanded dashboard evals
  inside pytest timeouts without changing behavior.
- Regenerated the OpenAPI-derived Simurgh tool-candidate artifact after the
  node boot-status route was added to the expected route inventory.

Validation on Hetzner:

- Dashboard prompt eval CLI: `29 passed, 0 failed`.
- Focused Simurgh/MCP pytest subset: `180 passed`.
- `python tools/generate_simurgh_docs_index.py --check`: passed.
- `python tools/generate_simurgh_tool_candidates.py --check`: passed.
- Byte-compile for changed Simurgh runtime modules: passed.
- `git diff --check`: passed.

Observed non-blocking noise:

- The prompt/test path still emits `Uploaded trajectory contents changed - full
  reprocess required` warnings from the swarm trajectory fixture. They did not
  fail tests, but the message should be reviewed later for operator-facing log
  noise and readiness wording.

Reviewer status:

- AI-agent reviewer: approved for this slice. It broadens general read-only
  coverage through reusable routing/eval rules, not hand-patched PM answers.
- MCP/API reviewer: approved. The new boot/init status answer is backed by the
  existing registry/MCP tool and the route inventory is fresh.
- Safety reviewer: approved. The slice remains read-only: no repository sync,
  sidecar action, config mutation, upload, or drone command is executed.
- PM/operator reviewer: approved for the covered prompts. Larger remaining work
  is still the unified read-only evidence orchestrator/conversational composer
  so registry execution and local advisory answers share the same structured
  evidence path and feel less split-brain.

Next recommended Simurgh slice:

1. Build the unified read-only evidence orchestrator and conversational composer
   so local advisory answers and registry/MCP tool execution share the same
   evidence schema, memory, follow-up interpretation, and clean final renderer.
2. Add evals for unexpected/general operator chatter, multilingual follow-ups,
   and “explain what you just found” follow-up behavior across logs, fleet,
   telemetry, setup, and docs.
3. Keep read-only coverage first. Action planning remains behind confirmation
   and final circuit-breaker enforcement, with circuit breaker applied only at
   the final execution boundary.

Deferred non-Simurgh slice:

- Board deploy-key/live sync verification remains parked until the deployment
  policy/credential decision is complete. Boards should use read-only deploy
  credentials; the GCS may use write-capable credentials where explicitly
  required. Do not mix private board credentials or field-specific state into
  the public Simurgh slice.

## 2026-06-04 Update: Simurgh Read-Only Evidence Foundation

Goal: start the unified read-only evidence orchestration work without a large
rewrite. This slice adds a compact evidence envelope to every local read-only
MDS answer so assistant composition, audit, session follow-up memory, dashboard
evals, and future registry/MCP execution can share the same factual metadata
instead of reverse-engineering intent from rendered Markdown.

What changed:

- Added `agent_runtime.evidence` with `ReadOnlyEvidenceBundle` and
  `ReadOnlyEvidenceItem`. The envelope records intent, response mode, source,
  tool ids, content hash, and a short public-safe summary.
- Attached evidence metadata at the shared `MdsReadToolAnswer` creation point,
  so existing local read-only answers inherit the same evidence shape.
- Included evidence metadata in advisory tool structured output, audit metadata,
  and private session context as compact JSON. Raw prompts and full rendered
  answers are not stored in this evidence field.
- Passed the compact evidence summary into provider composition context so the
  model sees the trusted local fact source before composing conversational text.
- Extended dashboard prompt eval expectations so representative fleet, logs,
  and node boot/init turns must carry structured evidence from
  `local_read_only_mds`.
- Added focused tests that verify evidence is present, hashed, public-safe, and
  persisted only as compact private session context.

Validation on Hetzner:

- Focused Simurgh/MCP pytest subset: `182 passed`.
- `python tools/generate_simurgh_docs_index.py --check`: passed.
- `python tools/generate_simurgh_tool_candidates.py --check`: passed.
- Byte-compile for changed Simurgh runtime modules: passed.
- `git diff --check`: passed.

Reviewer status:

- AI-agent/context reviewer: approved. This is a foundation for reusable
  evidence flow, not a hardcoded patch for individual PM prompts.
- MCP/API reviewer: approved. Existing MCP boundaries remain unchanged and the
  evidence shape can be reused by registry-backed tools in the next slice.
- Security reviewer: approved. The evidence envelope uses content hashes and
  summaries only; it avoids raw prompts, credentials, logs, and private field
  artifacts.
- PM/operator reviewer: approved as an internal foundation slice. Visible output
  quality should improve further in the next slice when registry route execution
  and local answers use the same final composer.

Next recommended Simurgh slice:

1. Move registry/MCP route execution results into the same evidence envelope.
2. Route both local advisory answers and registry results through one final
   conversational composer so users do not see raw tool tables or stale topic
   repetition.
3. Add evals for follow-up explanation, language switching, general knowledge,
   docs, telemetry, and logs across the unified composer.

## 2026-06-04 Update: Simurgh Registry Evidence And MCP Metadata Slice

Goal: complete the next read-only evidence step by moving registry-backed GCS
API execution and MCP tool calls onto the same compact evidence foundation used
by local Simurgh answers. The slice keeps MCP response schemas stable while
giving the assistant, dashboard trace, audit trail, and session follow-up memory
the same trusted metadata for route-backed answers.

What changed:

- Added registry-route evidence bundles with source `registry_read_only_mds`.
  Route-backed tools now attach tool id, route method/path, status code,
  content hash, compact public-safe summary, and response metadata.
- Kept MCP `structuredContent` unchanged and exposed the evidence through
  `_meta["ai.mds/evidence"]`, matching current MCP extension practice without
  mutating each tool payload schema.
- Added evidence to registry execution trace, audit metadata, and private
  session context as `read_only_evidence`, so follow-up interpretation can use
  factual tool results without storing raw prompts or full response bodies.
- Replaced the raw registry execution Markdown table with a shorter narrative
  summary. This reduces the old debug-table feel while still naming the tool,
  status, and sanitized arguments for operator trust.
- Sanitized log-route summaries so evidence can mention counts, levels,
  components, and route status without echoing raw log message text.

Validation on Hetzner:

- Tight regression subset: `3 passed`.
- Focused Simurgh/MCP suite: `236 passed` in about 6 minutes.
- `python tools/generate_simurgh_docs_index.py --check`: passed.
- `python tools/generate_simurgh_tool_candidates.py --check`: passed.
- Byte-compile for changed Simurgh runtime and route modules: passed.
- `git diff --check`: passed.
- Test coverage artifacts were removed after validation.

Reviewer status:

- MCP/API reviewer: approved with the constraint that evidence belongs in MCP
  `_meta`, not `structuredContent`; this slice follows that boundary.
- AI-agent/context reviewer: approved. Registry and local read-only paths now
  share an evidence contract, which is the right base for a later unified
  conversational composer instead of hardcoded answer patches.
- Security reviewer: approved. The route evidence uses hashes and compact
  summaries and deliberately avoids raw log messages, tokens, prompts, and
  private field artifacts.
- PM/operator reviewer: approved for the internal plumbing and cleaner registry
  rendering. Visible answer quality still depends on the next composer slice,
  where the final response should explain evidence conversationally rather than
  exposing internal execution mechanics.

Next recommended Simurgh slice:

1. Route registry evidence, local evidence, and provider composition through one
   final conversational composer so follow-up questions like "what does that
   mean?" answer from the previous evidence instead of rerunning the same raw
   summary.
2. Add dashboard/provider evals for evidence-backed follow-up explanation,
   multilingual translation of the previous answer, telemetry/log/docs
   clarification, and general operator chat.
3. Keep read-only scope first. Action APIs remain deferred behind the existing
   confirmation gate and final circuit-breaker execution boundary.

## 2026-06-04 Update: Simurgh Evidence-To-Provider Composer Slice

Goal: make registry-backed read-only answers feel like a modern assistant when
the dashboard session is authenticated for an external provider, without
changing MCP tool behavior or weakening the deterministic local fallback.

What changed:

- Added a shared provider-composition helper for read-only MDS evidence. Local
  advisory answers and registry-backed route execution can now use the same
  evidence document, provider prompt, safety notes, and trace semantics.
- Kept MCP `tools/call` deterministic. MCP still returns tool results and
  `_meta["ai.mds/evidence"]`; provider composition is only a dashboard
  assistant final-answer step after policy-approved read-only evidence exists.
- Enabled authenticated registry execution turns to compose the final text with
  OpenAI when the existing Simurgh provider gate allows it. Unauthenticated
  requests still receive the deterministic local registry summary.
- Added regression coverage proving provider calls receive
  `session.read_only_mds_evidence`, keep provider tools disabled, preserve the
  registry evidence source, and expose the evidence-context count in trace.
- Refactored the existing local-tool provider composition path onto the same
  helper, so future composer improvements apply to both local and registry
  read-only surfaces.

Validation on Hetzner:

- Tight registry/local provider composition subset: `3 passed`.
- Focused Simurgh/MCP suite: `237 passed` in about 6 minutes.
- `python tools/generate_simurgh_docs_index.py --check`: passed.
- `python tools/generate_simurgh_tool_candidates.py --check`: passed.
- Byte-compile for changed assistant, route, and test modules: passed.
- `git diff --check`: passed.
- Test coverage artifacts were removed after validation.

Reviewer status:

- AI-agent/composer reviewer: approved. This is a shared evidence-to-answer
  lane and avoids overfitting one prompt or one route.
- MCP/API reviewer: approved. The slice does not mutate MCP schemas or route
  payloads; composition is outside MCP and only affects dashboard assistant
  final text when authenticated.
- Security reviewer: approved. Provider calls remain behind existing auth, use
  bounded evidence context, disable provider tools, and do not expose action
  APIs or raw private payloads.
- PM/operator reviewer: approved for the next visible-quality increment. The
  next open work is deeper conversational memory over evidence follow-ups, so
  questions like "what does that mean?" can explain the previous evidence even
  more naturally.

Next recommended Simurgh slice:

1. Add explicit evidence-follow-up interpretation for "what does that mean?",
   "is that bad?", "say the same in Persian", and "what should I do next?"
   across logs, telemetry, docs, setup, and registry route results.
2. Add provider/dashboard evals that compare first-turn evidence answers with
   second-turn explanations, not just first-turn routing.
3. Keep this read-only until PM approves moving into action-planning APIs.

## 2026-06-04 Update: Previous-Evidence Follow-Up Composer Slice

Goal: make short second-turn questions use the evidence the operator just saw
instead of falling back to stale topic routing, repeated tables, or generic
capability/catalog answers. This keeps the work read-only and uses provider
composition only for authenticated dashboard sessions.

What changed:

- Added a generic previous-evidence follow-up lane for prompts such as "what
  does that mean?", "is that bad?", "should I worry?", and "what should I do
  next?".
- The lane binds only when the session has a previous assistant answer and
  compact read-only evidence metadata. Explicit new-domain questions still route
  normally, so "what drones are connected?" after a log answer does not inherit
  the log topic.
- Provider composition now receives two bounded private session context
  documents: `session.previous_assistant_answer` and
  `session.previous_read_only_mds_evidence`. Provider tools remain disabled and
  no MCP/action route is exposed.
- Added a deterministic fallback for previous-evidence follow-ups if the
  provider is unavailable after the route has already been allowed.
- Added audit/trace metadata for `tool_intent=evidence_followup`,
  `response_mode=followup`, and `provider_composed_from_previous_evidence` so
  PM/testers can verify the orchestration path without raw prompt leakage.
- Fixed the control-flow issue where a composed previous-evidence answer could
  fall through into the generic provider branch and generate a second, less
  predictable answer.

Validation on Hetzner:

- Tight evidence-follow-up, translation, and explicit-topic override subset:
  `6 passed`.
- Full Simurgh/agent/MCP suite: `341 passed` in about 7.5 minutes.
- `venv/bin/python tools/generate_simurgh_docs_index.py --check`: passed.
- `venv/bin/python tools/generate_simurgh_tool_candidates.py --check`: passed.
- Byte-compile for changed assistant/route/test modules: passed.
- `git diff --check`: passed.

Reviewer status:

- Independent AI-agent/MCP reviewer: approved the architecture after flagging
  the missing answer-level lane as the main source of robotic repeated answers.
- Backend reviewer: approved after the fall-through bug was fixed and covered by
  API/runtime tests.
- Safety reviewer: approved. The lane interprets only prior read-only evidence,
  keeps provider tools disabled, preserves the local/MCP deterministic boundary,
  and does not weaken blocked action handling.
- PM/operator reviewer: ready for the next dashboard test checkpoint focused on
  conversational follow-ups over logs, fleet, telemetry, docs, setup, and
  registry-backed route evidence.

Next recommended Simurgh slice:

1. Extend the same previous-evidence lane to richer follow-up commands such as
   "show me the exact source", "open the relevant page", and "summarize this as
   field instructions" while keeping route/source linking clean.
2. Add more UI-level tests around streaming/progress rendering for provider
   follow-ups so the visual experience remains ChatGPT-like instead of debug-like.
3. Continue read-only coverage until PM/funders approve the action-planning
   phase behind confirmation and the final circuit-breaker layer.

## 2026-06-04 Update: Evidence Source/Open/Field-Brief Follow-Up Slice

Goal: let an operator ask natural second-turn questions about the answer they
just saw - for example "what source did you use?", "where can I open that?", or
"make this a field checklist" - without re-running the wrong registry tool,
inventing links, or dumping a generic capability menu.

What changed:

- Added bounded `source_refs` metadata to read-only evidence bundles. The refs
  carry registry tool ids, API route method/path/template, status code, docs
  paths, and dashboard route hints where those already exist.
- Threaded source refs through route-backed registry execution, local read-only
  evidence, and provider-composed dashboard turns. MCP remains deterministic:
  tool calls still return structured tool results and evidence metadata, not a
  model-generated source story.
- Extended the previous-evidence follow-up lane with three new read-only tasks:
  source explanation, relevant-page/link guidance, and concise field-operator
  checklist generation.
- Kept source and route links conservative: dashboard pages and docs paths can
  be offered as links when present; API paths stay inline unless a real docs
  route is known.
- Tightened follow-up detection after reviewer feedback. Capability/catalog
  prompts such as "what read-only APIs/tools can Simurgh use for SITL status?"
  now route through the registry planner even when the session has previous
  evidence, instead of being misclassified as "show me the source".
- Added action-safety regression coverage proving that source-like wording does
  not bypass the blocked-action gate.

Validation on Hetzner:

- Focused reviewer regression subset: `4 passed`.
- Full Simurgh/agent/MCP/read-only registry suite: `346 passed` in 2m39s with
  coverage disabled to avoid temporary HTML artifacts.

Reviewer status:

- Independent AI-agent/MCP reviewer: initially found a P2 overmatch risk in the
  source-follow-up classifier. The fix is implemented and covered by API/runtime
  regression tests.
- Backend/API reviewer: approved. New-domain capability prompts still use the
  registry planner; previous-evidence follow-ups only bind when the wording is
  explicitly referential to the prior answer/source/page/checklist.
- Safety reviewer: approved. Provider tools remain disabled, evidence context is
  bounded, action wording stays blocked, and no mutation/flight path is exposed.
- PM/operator reviewer: ready for the next visible-quality checkpoint focused on
  UI polish and broader read-only capability coverage before action planning.

Next recommended Simurgh slice:

1. Improve the dashboard message rendering and progress affordances for
   source/open/checklist follow-ups so tables, bullets, copy controls, and
   streaming states feel polished without adding always-visible noise.
2. Continue expanding read-only parity so any normal dashboard/API inquiry -
   telemetry, locations, battery, logs, sidecars, environment, setup, docs,
   runtime, MCP menu, and mission/show readiness - can be answered from chat.
3. Keep official and client repos synchronized, then deploy the client build
   with `MDS_MODE=real`, action circuit breaker on, always-confirm on, and MCP
   auth on.

## 2026-06-04 Update: Procedural Streaming Progress Foundation

Goal: make Simurgh visibly procedural in the dashboard without exposing hidden
chain-of-thought or turning the provider into an ungoverned tool runner. This is
the first foundation for the requested ChatGPT-like multi-step flow: understand,
plan, call approved tools/search/MCP, adapt from evidence, compose, and later
monitor approved actions.

What changed:

- Added a progress callback path inside read-only registry execution.
- The SSE assistant route now runs turn creation in a background task and emits
  live progress from the executor queue instead of waiting for the final answer.
- Registry read turns stream a plan event, per-tool running event, and per-tool
  complete/error event before answer chunks. Existing local/provider fallback
  turns still stream the compact tool/provider summary they had before.
- Provider composition over read-only MDS evidence emits bounded provider
  running/complete/fallback progress. It still does not expose provider-native
  tools, raw prompts, secrets, raw logs, or hidden model reasoning.
- Updated `docs/guides/simurgh-operator.md` with the procedural loop target for
  future public web/search, external MCP connector, action proposal, final
  circuit-breaker, and monitoring slices.

Validation on Hetzner:

- Focused stream regression subset: `2 passed`.
- Focused auth/docs/stream follow-up subset after reviewer hardening: `4 passed`.
- Full Simurgh/auth/agent/MCP/read-only suite: `358 passed` in about 2m38s.

Reviewer status:

- Independent reviewer initially inspected a stale local snapshot instead of the
  Hetzner repo, so its route-specific streaming findings did not apply to this
  slice. The useful checklist item was still valid: runtime/provider settings
  should be treated as security/runtime administration. This slice added
  admin-only middleware coverage for `POST/PUT`-style Simurgh runtime settings
  and provider credential changes when auth is enabled, while preserving open
  no-auth demo mode.
- Backend/API reviewer: approved after the queue-backed stream path, cancellation
  guard, stale docs-index regeneration, cwd-independent prompt-eval CLI test, and
  broader suite passed.
- AI-agent/MCP reviewer: approved for the current read-only procedural progress
  foundation. This is not yet the full external MCP/web/action loop; it is the
  reusable event/policy foundation that later lanes must plug into.
- Safety/privacy reviewer: approved. The stream exposes only safe stage labels,
  reviewed tool ids/titles, bounded status fields, answer deltas, and sanitized
  final payloads. It does not stream hidden reasoning, raw prompts, secrets,
  private logs, provider-native tool calls, or action execution.

Next recommended Simurgh slice:

1. Run the broader Simurgh/agent/MCP suite and sync the same patch to the public
   official repo.
2. Improve frontend progress rendering so multi-step plan/tool/provider events
   appear inside the active answer bubble like a polished assistant activity
   feed, not a debug log.
3. Add the external public web/search lane only for public/general prompts, with
   citations and strict egress separation from private MDS evidence.

## 2026-06-05 Update: Read-Only Registry Coverage Gate

Goal: close the next read-only parity gap without creating hardcoded chat
answers. The slice promoted two reviewed GCS `GET` routes into the shared
registry/MCP/executor path and tightened the generated candidate artifact so
future eligible read-only drift is visible before release.

What changed:

- Added `mds.fleet.git_sync.read` for Fleet Ops git-sync posture. It reads
  `/api/v1/fleet/git-sync` only; dry-run/apply, pull, push, and `UPDATE_CODE`
  dispatch remain mutation routes and are not callable through read-only MCP.
- Added `mds.origin.launch_positions.read` for desired launch-position
  coordinates. The registry schema constrains Simurgh/MCP calls to JSON output;
  CSV/KML/download-style artifact flows stay outside the tool.
- Updated the registry planner so “out of sync” prompts prefer fleet sync
  posture, and desired launch-position prompts can pass a bounded heading value
  into the canonical route.
- Updated docs and tests to keep OpenAPI auto-discovery advisory-only while the
  curated registry remains the execution boundary.

Reviewer notes:

- AI-agent/MCP reviewer: approved if the new coverage stays route-backed,
  schema-validated, and shared by dashboard chat and external MCP clients.
- Safety/operator reviewer: approved. Both tools are sensitive observation only;
  they cannot imply flight readiness, run sync, export artifacts, or command a
  drone.
- Backend/API reviewer: require generated candidate coverage to remain at zero
  unpromoted eligible read-only candidates after regeneration.

Next recommended Simurgh slice after validation/sync:

1. Continue broader read-only parity for telemetry/location/battery/health,
   setup/onboarding, sidecars, docs, environment, logs, and mission/show state.
2. Add public web/search lane for public/general prompts only, with citations
   and strict separation from private GCS evidence.
3. Begin action-proposal design only after read-only parity and reviewer gates
   are stable.

## 2026-06-05 Update: Public Web-Search Progress Trace

Goal: make the already guarded public/general OpenAI web-search lane visible to
operators and reviewers without exposing raw provider internals, hidden
reasoning, private MDS evidence, or a second tool path.

What changed:

- Added sanitized `trace.provider_tools` metadata with separate
  `web_search_requested`, `web_search_returned`, `citation_count`, and scope
  fields. This keeps the UI honest when a provider request asked for web search
  but the returned response does not include citation/source evidence.
- Updated the SSE progress fallback so authenticated public lookup turns show a
  compact `Searched public web` activity stage only when the provider returned a
  web-search call; otherwise the label stays at `Requested public web search`.
- Updated the Simurgh dashboard trace disclosure so web-search turns summarize
  as `Searched public web` and show `Lookup: Public web search`; raw
  `web_search_call` internals stay hidden.
- Kept MDS facts local-first. Fleet, telemetry, logs, show state, runtime,
  sidecars, origin, PX4, and registry prompts still route through approved
  read-only MDS tools and do not send private GCS evidence to web search.

Reviewer notes:

- AI-agent reviewer: this improves perceived procedural intelligence without
  presenting chain-of-thought. It is a UI/trace quality layer over the existing
  public-search gate.
- MCP/security reviewer: approved boundary. No remote MCP server was added; no
  provider tool is attached for MDS evidence composition; citations remain
  clickable dashboard content only.
- Operator/PM reviewer: public current-fact prompts can now visibly search,
  while MDS operational questions keep exact local evidence and safety posture.

Next recommended Simurgh slice after validation/sync:

1. Add dashboard/provider evals for richer public lookup prompts and source
   display, including no-regression checks that MDS-local questions do not use
   web search.
2. Continue external-client documentation/examples for n8n, Claude Desktop, VS
   Code, and MCP stdio/SSE bridge clients.
3. Start action-proposal design only after read-only and public-search gates are
   stable in PM/funder testing.

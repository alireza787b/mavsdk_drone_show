# Simurgh Language And Intent Modernization

Date: 2026-06-20

## Decision

Do not turn Simurgh into a large alias/typo dictionary. Keep deterministic query
adaptation for safety, exact MDS domain terms, and eval-backed high-frequency
operator spelling issues. Move broad language, tone, paraphrase, target-memory,
and multi-step command understanding into a structured semantic-understanding
layer whose output is validated and still governed by the existing registry,
policy, confirmation, circuit breaker, and audit layers.

This keeps the demo from looking hardcoded while preserving the parts that must
remain deterministic for safety-critical operations.

## Research Findings

- Codex-style terminal agents use durable repo instructions, skills, MCP, tools,
  and tests to preserve context and execution quality. The model handles messy
  language; repository policy and tooling enforce what can actually happen.
- OpenAI tool and Agents patterns separate model reasoning from typed tools,
  guardrails, handoffs, tracing, and human approval. Tool selection should be
  grounded in tool metadata and schemas, not only keyword lists.
- Claude Code exposes model-driven tool use, but permissions, hooks, and
  approval rules are enforced by the runtime, not by prompt text alone.
- MCP exposes resources, tools, and prompts as structured context/capabilities.
  The host decides what context enters the model and how users approve actions.
- LangGraph-style interrupts show the right action pattern for approvals and
  long-running work: persist state, pause, resume with the same thread/action,
  and make side effects idempotent.
- Hermes-style systems emphasize memory and skills learned from experience, but
  the practical lesson for MDS is to convert repeated PM failures into sanitized
  evals and reusable skills, not into one-off phrase patches.

## Current MDS State

Implemented:

- deterministic language/tone profile;
- config-driven query adaptation in `config/agent_query_adaptation.yaml`;
- provider-neutral turn-level semantic intent frame in
  `gcs-server/agent_runtime/turn_intent.py`, consumed by the dashboard
  assistant route before confirmation/action/read-only/provider branching;
- local read-only tool routing and selected guarded actions;
- provider composition for safe text turns;
- optional public web-search lane for public/current facts;
- action confirmation, circuit breaker, and audit enforcement outside provider
  prose;
- dashboard prompt evals for PM-style conversations.

Remaining gap:

- provider-backed structured-output semantic classification is not yet enabled
  in the action path; the current frame is provider-neutral and testable;
- target memory is partially structured through last action/result context, but
  broader live-fleet target inference still needs careful safety review;
- some failures still answer from docs instead of running the most relevant
  local evidence tool;
- answer localization and tone adaptation are not yet uniformly available for
  local GCS-state answers because raw runtime state must not be sent to a
  provider only for translation.

## Rule Boundary

`config/agent_query_adaptation.yaml` is allowed to contain:

- safety and sensitive-data wording;
- blocked-action wording;
- exact domain/tool nouns and stable multilingual aliases;
- eval-backed high-frequency typos that protect routing;
- temporary compatibility aliases with a tracked replacement plan.

It must not contain:

- every observed user typo;
- broad paraphrases of normal human requests;
- long lists of demo prompts;
- action-plan logic;
- response templates;
- private customer vocabulary that would leak outside a customer branch.

## Target Architecture

### 1. Semantic Understanding Layer

Add a structured, schema-validated understanding pass for low-confidence,
typo-heavy, multilingual, follow-up, or action-sequence prompts.

Input:

- sanitized operator message;
- language/tone profile;
- session topic and last action/result references;
- public capability/tool metadata from the registry;
- policy posture and runtime mode label;
- no raw private telemetry/log/config unless approved by data-egress policy.

Output:

- detected language;
- tone and expertise level;
- normalized operator intent;
- domain and task kind;
- answer style: concise, diagnostic, step-by-step, or expert;
- evidence needs;
- candidate tool domains;
- target references and confidence;
- action sequence draft, if any;
- clarifying question, if genuinely needed;
- safety and egress notes.

This output is not authority. The existing deterministic layers still enforce
registry schemas, permissions, human confirmation, circuit breaker, and audit.

### 2. Registry-Grounded Tool Selection

Tool choice should come from `config/agent_tools.yaml`, generated OpenAPI
candidates, MCP metadata, and eval results. Semantic understanding may propose
tool domains, but the executor resolves only reviewed tools.

### 3. Durable Action Memory

Track last created SITL instance, last submitted command, target drone ids,
operation ids, and terminal monitor state as structured session memory. Follow-up
phrases such as "the drone we created", "land it", or "remove that instance"
should resolve from this memory when unambiguous, then still pass through policy
and confirmation.

### 4. Procedural Plans For Action Sequences

Represent "take off to 10 m, wait 10 s, move 10 m north, RTL" as a typed plan
with multiple steps, monitors, stop conditions, and rollback/abort policy. Do
not collapse it to only the final verb.

### 5. Human Approval UX

Confirmation should support both typed confirmation and UI buttons. The approval
payload must point to a specific draft id and summarized plan. Reject/amend
should keep the draft context visible without requiring the operator to restate
everything.

### 6. Evals Instead Of Alias Growth

Each PM failure becomes a sanitized eval case with:

- original typo-heavy prompt;
- expected intent/domain/tool evidence;
- expected target resolution;
- expected action plan or refusal reason;
- expected concise answer style.

The eval decides whether the fix belongs in query adaptation, semantic
understanding, target memory, planner, executor, answer composition, or UI.

## Rollout Slices

1. Freeze alias sprawl.
   Document the boundary, require eval ids for new aliases, and reject
   one-off demo prompt patches.
2. Add semantic-understanding dry-run.
   Produce structured JSON and traces without changing routing decisions.
3. Enable semantic arbitration for low-confidence routing.
   Deterministic high-confidence/safety routes still win. Semantic output can
   select evidence domains when exact rules fail.
4. Add durable action/target memory.
   Use it for unambiguous follow-ups while keeping confirmation mandatory.
5. Add typed multi-step action plans.
   Support SITL lifecycle, takeoff/land/RTL, precision move, waits, and monitor
   steps through the same executor path.
6. Improve localized answer composition.
   Use local templates for sensitive runtime state and provider/local model
   translation only under approved egress policy.
7. Expand multilingual and typo-heavy evals.
   Cover English, Persian, French, simple non-native English, angry operator
   tone, expert shorthand, and beginner questions.

## Acceptance Criteria

- A prompt with new wording or a different supported language routes by meaning,
  not by a hand-added phrase.
- The assistant uses available local telemetry/log/SITL tools before saying it
  cannot know live state.
- Action sequences are preserved as sequences and shown as concise plans.
- Follow-up targets are inferred only when session memory makes them
  unambiguous, and the answer says what was inferred.
- Circuit breaker and confirmation behavior stay identical in SITL and real
  runtime.
- The PM can ask terse, typo-heavy, angry, beginner, or expert prompts and get
  concise useful behavior instead of docs dumps.
- New failures add evals first; aliases are added only when they meet the rule
  boundary above.

## Current Implementation Checkpoint

The first implementation slice adds a structured, provider-neutral
`TurnIntentFrame`, routes dashboard assistant turns through it, and exposes the
sanitized interpretation under `trace.intent`. The frame prevents two PM-visible
failures:

- approval-like wording with a new read/status task, such as "go ahead and
  check SITL instances now", no longer confirms an old pending action;
- advisory motion questions, such as "tell me if drone 1 should land", no
  longer draft guarded flight commands.

Regression coverage now includes frame-level tests and dashboard-route tests for
PM-style compound action plans, exact draft confirmations, read/status task
arbitration, and advisory-vs-command flight wording.

The next Simurgh slice should use the same frame contract for optional
provider-backed structured semantic classification, broader target memory, and
multilingual/tone-sensitive evals. Do not add broad alias lists as a substitute
for this frame.

## References Reviewed

- OpenAI tools guide: https://platform.openai.com/docs/guides/tools
- OpenAI Agents SDK: https://openai.github.io/openai-agents-python/
- Claude Agent SDK overview: https://code.claude.com/docs/en/agent-sdk/overview
- Claude Code permissions: https://code.claude.com/docs/en/permissions
- Model Context Protocol resources specification:
  https://modelcontextprotocol.io/specification/2025-06-18/server/resources
- LangGraph interrupts:
  https://docs.langchain.com/oss/python/langgraph/interrupts
- Hermes Agent docs: https://hermes-agent.nousresearch.com/docs/

# Simurgh Language And Intent Modernization

Date: 2026-06-20

## Decision

Do not turn Simurgh into an alias or typo dictionary. Local query adaptation is
lexical only and does not correct, translate, or infer operator language.
Language, tone, paraphrase, target references, and multi-step command
understanding belong to the schema-validated semantic provider. The registry,
typed grounding, policy, confirmation, circuit breaker, execution, monitoring,
and audit layers remain local and authoritative.

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
- lexical-only query normalization with no typo or multilingual phrasebook;
- authenticated structured provider interpretation for typo-heavy,
  multilingual, conversational, and multi-step turns;
- provider-neutral turn-level semantic intent frame in
  `gcs-server/agent_runtime/turn_intent.py`, consumed by the dashboard
  assistant route before confirmation/action/read-only/provider branching;
- registry-grounded local status/evidence tools and guarded actions;
- provider composition for safe text turns;
- optional public web-search lane for public/current facts;
- action confirmation, circuit breaker, and audit enforcement outside provider
  prose;
- durable target/action memory, typed action sequences, monitor conditions, and
  reconnectable action runs;
- dashboard prompt evals for PM-style conversations.

Ongoing work:

- expand sanitized semantic eval coverage as new languages, tools, and operator
  workflows appear;
- add provider adapters behind the same typed contract when they meet policy,
  tracing, latency, and eval requirements;
- improve local evidence rendering and localization without sending raw private
  runtime state to a provider solely for translation.

## Deterministic Boundary

Deterministic routing may contain:

- canonical product, protocol, tool, and command vocabulary;
- typed registry schemas and policy-sensitive constraints;
- exact structured UI controls such as confirm/reject with a draft identity;
- narrow fast paths for unambiguous local evidence queries.

It must not contain:

- observed user typos;
- multilingual phrasebooks;
- broad paraphrases of normal human requests;
- long lists of demo prompts;
- action-plan logic;
- response templates;
- private customer vocabulary that would leak outside a customer branch.

## Target Architecture

### 1. Semantic Understanding Layer

Use a structured, schema-validated understanding pass for typo-heavy,
multilingual, follow-up, ambiguous, or action-sequence prompts.

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

The eval decides whether the fix belongs in semantic understanding, tool
metadata, target memory, planner, executor, answer composition, or UI.

## Rollout Slices

1. Completed: remove alias/typo phrasebooks and document the lexical boundary.
2. Completed: add structured semantic interpretation with sanitized traces.
3. Completed: ground semantic read/action plans against reviewed registry
   contracts and fail to concise clarification when meaning cannot be grounded.
4. Completed: add durable action/target memory and unambiguous follow-up
   resolution while keeping confirmation mandatory.
5. Completed: add typed multi-step SITL/flight plans, waits, conditions,
   monitoring, steering, and reconnectable action runs.
6. Completed for beta: render concise local evidence and action progress without
   sending raw private state to the semantic provider.
7. Continuous: expand multilingual, typo-heavy, expert, beginner, and
   adversarial evals as sanitized operator cases are discovered.

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
- New language/phrasing failures add semantic evals and fix the responsible
  context, schema, grounding, or UX layer; they do not add typo aliases.

## Current Implementation Checkpoint

The beta routes authenticated operator turns through a structured semantic
provider and then rebuilds the result through local typed contracts. A provider
can interpret language, typos, pronouns, ordered clauses, and requested detail,
but cannot invent unsupported tools, authorize an action, select an ungrounded
target, alter numeric facts, bypass confirmation, disable the circuit breaker,
or claim execution.

Durable session and action-run state preserves the relevant target, draft,
sequence, waits, monitor evidence, and terminal outcome across follow-ups and
reconnects. Exact UI confirm/reject controls bypass language interpretation and
remain bound to the operator, session, and immutable draft. Ambiguity produces
one short clarification rather than a docs dump or partial action.

Regression coverage includes provider-structured typo-heavy and multilingual
requests, compound read/status turns, multi-step flight and SITL plans,
target-memory follow-ups, approval/rejection binding, ULog/log review, progress
replay, pause/resume/cancel controls, and provider failure behavior.

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

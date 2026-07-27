# Simurgh Readiness Routing Checkpoint

Date: 2026-07-27
Status: complete; official and private client checkpoints published and ready
for PM retest
Scope: official MDS source and the approved private client mirror

## Incident

A private operator asked whether one configured drone was ready to take off.
The reply showed the generic blocked-action fallback instead of live readiness
evidence.

Sanitized assistant-turn metadata established the failure boundary:

- the deterministic turn frame selected `read_only`;
- the read contract selected `fleet_connectivity`;
- no direct flight action was detected;
- the final adapter nevertheless reported blocked intent `takeoff`;
- no provider request and no local read tool execution occurred.

The configured action-word block was therefore being applied after the typed
read route without recognizing that the word described a possible next action,
not a request to execute it.

## Correction

The route coordinator now gives a complete typed `fleet_connectivity` read
authority over lexical action-word blocking. That authority is deliberately
narrow:

- it applies only to a complete, non-action readiness/connectivity frame;
- direct flight requests still require a source-grounded guarded draft,
  operator confirmation, policy approval, and the circuit breaker;
- provider output cannot promote the typed readiness question into an action
  draft;
- a bare or otherwise ambiguous action term asks the operator to choose between
  a read-only readiness check and a guarded action plan, and asks for the
  target/parameters when an action is intended.

No spelling, language, or scenario-specific production alias was added.

## Validation contract

The regression gate covers:

1. the typo-heavy readiness prompt during provider failure;
2. an incorrect provider action-plan interpretation of the same typed
   readiness question;
3. a genuinely ambiguous bare action term;
4. the existing provider-failure fail-closed action test.

Local publication gates completed:

- 363 assistant-runtime, turn-intent, MCP, telemetry, drone API, WebSocket, and
  altitude-display tests passed serially;
- 152 complete Simurgh route tests passed serially, including guarded action,
  SITL lifecycle, provider promotion, clarification, monitoring, and the new
  readiness cases;
- 33 dashboard prompt-eval turns passed, including the sanitized typo-heavy
  readiness regression;
- the provider dry smoke passed without making a live external request;
- generated context, Python compilation, and whitespace checks passed.

The approved public commit is then replayed onto the private mirror, production
is restarted from that committed checkout, and health plus the exact readiness
path are rechecked.

## Release boundary

This is a GCS source/runtime correction. It does not change the feasibility-only
product claim, does not authorize real-aircraft use, and does not require a
SITL image or MEGA artifact rebuild.

## Release handoff

- Official runtime commit/tag:
  `69f40fae5ca62085d1a988bfbc1993f927afad24`
  (`v5.5.113-simurgh-readiness-routing`)
- Private runtime replay: `638c03a8f128e2bebff4f6a89670a8297b4ea777`
- A docs-only closing record is present on each current `main` after these
  runtime commits; the two docs commit IDs differ because the private mirror
  retains its client-specific history.
- Both published worktrees were clean at their respective handoffs.
- Official serial gates passed: 363 broader runtime/API tests and 152 Simurgh
  route tests; dashboard prompt evals passed 33/33; provider dry smoke passed.
- Private focused route tests passed 7/7 and dashboard prompt evals passed
  33/33, including the readiness regression.
- Private production was restarted from the committed checkout. API health,
  dashboard, and isolated validation health returned HTTP 200, and the
  existing `drone-1` SITL container was preserved.
- Authentication remains enabled; no credentials or tokens were created. The
  unauthenticated Simurgh status endpoint correctly returned HTTP 401.
- No SITL image, MEGA artifact, or custom runtime image was rebuilt.

PM may now retest the private client from its authenticated dashboard. The
readiness question should produce read-only fleet evidence; an explicit action
request should produce the normal guarded confirmation flow. Simurgh remains a
demo/proof-of-feasibility checkpoint, not a production-flight authorization.

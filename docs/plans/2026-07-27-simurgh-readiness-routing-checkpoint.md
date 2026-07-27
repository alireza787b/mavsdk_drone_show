# Simurgh Readiness Routing Checkpoint

Date: 2026-07-27
Status: local validation complete; publication and private deployment
verification in progress
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
SITL image or MEGA artifact rebuild. Final official/private commit identities,
tag, test totals, and deployment results are recorded by the closing
documentation commit after publication.

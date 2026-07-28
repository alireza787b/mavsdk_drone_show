# Simurgh routing-resilience checkpoint — 2026-07-28

## Scope

This checkpoint closes the provider-outage/routing regression found during the
SITL PM retest. Simurgh remains a demo/proof-of-feasibility system, not a
production flight product. The goal of this slice is reliable, auditable
operator behavior when the semantic provider is slow, rate-limited, or
unavailable.

## Evidence that triggered the slice

- The private Catch-A-Drone runtime was healthy in SITL mode and its local
  GCS/SITL APIs were reachable.
- The Simurgh process log recorded OpenAI `HTTP 429 Too Many Requests` responses
  for semantic turns at approximately 03:13:42 and 03:14:28 UTC.
- A direct request — “if no SITL is running, create a new SITL instance and
  report when ready to fly” — first produced a connectivity/help progress item
  and then ended with “could not safely map that request”, even though the
  deterministic local planner had enough information to draft a bounded create
  action.
- The previous target-context patch serialized `last_read_target_drone_ids` as
  a JSON list, while the session contract requires a JSON object. That produced
  a 400 context error during a location follow-up.
- Position answers could mix live telemetry with configured origin semantics,
  and compact status answers used lowercase/ambiguous health labels.

No credentials, private IPs, raw logs, or customer transcript content are
stored in this checkpoint.

## Root cause

The route previously treated semantic-provider interpretation as a prerequisite
for most natural-language actions and some reads. A provider transport failure
therefore demoted a locally complete draft into generic clarification. The
same provider-first path could over-read an action word in a readiness question,
replace a live fleet read with an origin/configuration read, or expand a short
operator question into a long answer.

## Implemented contract

1. `intent_arbitration.py` computes a `RouteCommitment` from the typed turn:
   - complete bounded local actions may fall back safely;
   - current fleet/position/readiness and explicit coordinate-country reads are
     locally authoritative;
   - help, composite, typo-heavy, multilingual, and otherwise non-authoritative
     reads remain eligible for provider refinement.
2. Exact SITL running-count clauses use the registered
   `sitl.running_instance_count` fact. Conditions are shown and re-evaluated;
   unavailable facts fail closed.
3. Provider service failures (`408`, `409`, `425`, `429`, `500`, `502`, `503`,
   `504`, timeout/network markers) produce a concise fallback. They never
   execute or authorize an action.
4. Current telemetry answers preserve explicit target scope in structured
   session context. Live altitude is labeled `REL`, `LCL`, `BARO`, or `MSL`;
   origin is only returned by an origin read.
5. Country lookup is isolated in `geography.py` and uses packaged offline
   boundary data. It is informational and explicitly caveated.
6. Brief status/location output uses explicit `Ready`, `Armed`, `Flight state`,
   `Battery`, and altitude labels. Detailed output remains available on request.

## Validation harness

The slice is covered by:

- typed action/planner/turn-intent tests;
- route tests for provider outage, HTTP 429, exact conditional SITL create,
  readiness non-promotion, provider read reconciliation, target grounding, and
  concise clarification;
- assistant runtime tests for recoverable HTTP statuses, non-transient schema
  failures, and provider-independent coordinate-country lookup;
- the existing Simurgh advisory/provider and dashboard prompt eval suites;
- static Python compilation, YAML/tool-registry validation, and `git diff
  --check`.

## Deferred items

- Simurgh remains demo-only; no real-aircraft, unattended, regulatory, or
  commercial-safety claim is made.
- The public SITL image is intentionally not rebuilt for this code/docs slice.
  The private GCS runtime must install the new optional offline geography
  dependency before deployment.
- Richer coordinate-boundary provenance, exact geocoding citations, and
  multi-provider failover remain future work.
- Final PM flight/SITL acceptance is intentionally left to the operator after
  the private runtime is restarted and verified.

## Handoff

Before release, record the final official branch commit/tag, the private clone
commit, runtime health checks, and whether the final PM test is ready. Keep this
checkpoint linked from the Simurgh operator guide and `docs/README.md`.

# Simurgh Feasibility Checkpoint

Date: 2026-07-27
Status: phase closed after the SITL proof-of-feasibility retest
Scope: official MDS source plus the approved private client mirror

## Product claim and boundary

Simurgh Operator is an early demo / proof-of-feasibility beta. It is not
production-ready, safety-certified, autonomous, or approved for real-aircraft,
unattended, commercial, or regulatory use. This checkpoint closes the current
exploration phase so the team can focus on the next product priority. Simurgh
can be resumed later from this document and the linked source-of-truth
artifacts.

The current safety posture remains human confirmation, curated GCS routes,
durable action monitoring, audit evidence, and the final circuit breaker. Keep
those controls enabled in all demonstrations.

## Evidence accepted in this phase

The sanitized private SITL retest exercised one connected vehicle through the
operator workflow:

1. conditional takeoff to 20 m;
2. live position/status read;
3. precision move 5 m north;
4. NED/home-distance read;
5. return-to-launch and landing request;
6. onboard ULog inventory and bounded summary review.

The ULog summary reported a 208.5 s flight, local horizontal movement of about
5.9 m, relative altitude from approximately -0.1 m to 20.2 m, no link
dropouts, and final displacement back at the origin. Command/ack and landed
state evidence were present, but correlation of the newest available ULog to a
specific action remains explicitly unverified. Older heartbeat warning lines
were identified as deployment/restart noise rather than flight-failure proof.

This is feasibility evidence, not a production acceptance gate.

## Fix included in this checkpoint

Fleet status now:

- follows the telemetry altitude policy order (relative/home, local NED, baro,
  then absolute MSL);
- never presents an MSL fallback as an unlabeled relative altitude;
- labels the displayed frame (`REL`, `LCL`, `BARO`, or `MSL`);
- calls the current bundle `Flight state` instead of `Final state`;
- labels each component as `Landed`, `Altitude`, `V-down`, and `Home distance`;
- reports missing landed/altitude evidence as `Unknown`, not as a misleading
  terminal state.

The underlying compatibility key is retained for internal callers, while the
operator-facing wording makes clear that this is a current snapshot rather
than terminal action evidence.

## Deferred backlog

- real-aircraft and commercial safety hardening, certification, and field
  procedures;
- broader PX4/flight-stack and multi-vehicle acceptance;
- richer action-to-ULog correlation and time-series review;
- remaining Simurgh router/read-tools/dashboard decomposition;
- removal of phrase-based fallback routing;
- offline CLI, batch-comparison, and narrative log-review slices;
- any refreshed public SITL image or MEGA artifact (intentionally not part of
  this code/docs checkpoint).

## Restart recipe

When this phase is resumed, begin with `AGENTS.md`, this checkpoint,
`docs/guides/simurgh-operator.md`, and the generated agent-context index.
Reproduce the focused telemetry tests, run the offline Simurgh eval suites,
then validate the real private SITL workflow before broadening scope. Preserve
sanitized evidence and hashes in a new dated checkpoint; do not rely on chat
history or paste private logs, credentials, coordinates, IPs, or raw ULogs into
the official repository.

## Source-of-truth and handoff

- Runtime policy: `config/agent_policy.yaml`
- Tool contracts: `config/agent_tools.yaml`
- Assistant/prompt source: `config/agent_assistant.yaml` and
  `docs/agent-context/prompts/`
- Human operator contract: `docs/guides/simurgh-operator.md`
- Generated context/index artifacts: `docs/agent-context/generated/`
- Recovery history: `docs/plans/2026-07-27-simurgh-beta-recovery-and-pm-retest.md`

Official and private commit/tag identities, validation commands, and the final
deployment URL belong in the release handoff below after publication; this
document intentionally contains no customer-only host or repository details.

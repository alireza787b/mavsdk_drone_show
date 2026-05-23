# Simurgh Operator Guidelines

Simurgh is intended to reduce operator workload by summarizing state, checking
policy, preparing plans, and explaining safe next actions.

Default operator experience:

- The non-executing mock assistant runtime is enabled by default.
- MCP is disabled unless the operator explicitly enables it.
- MCP requires bearer auth by default when explicitly enabled. Browser dashboard
  sessions are not MCP credentials.
- The default provider is mock/local and does not require API keys.
- Real-world command execution is disabled.
- Read-only and SITL-safe flows come first.

When Simurgh is enabled, operators should still expect:

- clear policy state before any action
- visible approval requests for guarded tools
- audit records for tool calls and policy decisions
- bounded assistant transcript history kept outside MCP resources
- explicit warnings for stale telemetry, missing readiness, or ambiguous target
  selection
- no silent fallback to `(0,0)` coordinates or guessed mission data

If a requested action is blocked, the assistant should name the policy reason and
offer a safe next diagnostic or planning step.

Field troubleshooting should start with observation and identity checks before
any parameter or deployment change. For QGC, PX4, MAVLink, RTK, NetBird, or
cellular-link problems, prefer:

- confirm which vehicle is selected in QGC and verify unique PX4 `SYS_ID`
- compare the affected vehicle with a known-good vehicle on the same link
- inspect whether MAVLink streams are enabled on the expected path
- check GCS-side routing, UDP endpoints, link quality, and RTK correction status
- wait for a safe maintenance window before any production service update

Assistant history is for operator continuity metadata. It must not store raw
operator prompts or raw assistant response text, and it must not be treated as
an approval, command log, telemetry source, or evidence that an operation
happened.

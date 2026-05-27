# Simurgh Safety Policy

The enforced safety policy is stored in `config/agent_policy.yaml`. This file is
the human-readable companion for operators, developers, and model context.

Default state:

- `MDS_AGENT_ENABLED=true`
- `MDS_MCP_ENABLED=false`
- `MDS_AGENT_ACTION_CIRCUIT_BREAKER=true`
- `MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true`
- `MDS_AGENT_PROVIDER=mock`
- `MDS_MCP_REQUIRE_AUTH=true`
- `MDS_MCP_REQUIRED_SCOPES=agent,admin`

Non-negotiable boundaries:

- GCS is the only operational boundary for agent tools in this phase.
- Drone-side APIs are not exposed to MCP clients.
- MCP requires bearer auth by default when explicitly enabled. When MDS auth is
  enabled, the bearer token must have an `agent` or `admin` scope. Weaker
  configured scopes such as `drone`, `operator`, or `viewer` cannot widen MCP
  access. Dashboard cookie sessions and drone/operator-only tokens are not
  enough for MCP access.
- Raw GCS command submission is not exposed to models.
- Unknown tools and unknown routes are denied.
- The Simurgh action circuit breaker is the final execution stop for every
  non-read-only tool while it is enabled. Planning and approval layers may
  still produce a dry-run explanation of what would be called, but the executor
  must not perform the action. It is independent from `MDS_MODE`; real hardware
  operation can continue for human operators while Simurgh remains advisory-only.
- `MDS_MODE` is the canonical real/SITL runtime source for Simurgh policy posture; there is no separate user-facing Simurgh mode or real-command override. Invalid `MDS_MODE` fails closed for Simurgh policy.
- Assistant transcript history is not an MCP resource and does not authorize
  future tool calls.
- Provider adapters are advisory-only in this phase. OpenAI Responses requests
  must use `store=false`, `tools=[]`, `tool_choice="none"`,
  `parallel_tool_calls=false`, no conversation state, no streaming, no
  background jobs, no uploaded files, and the official
  `https://api.openai.com/v1` base URL.
- Deployed external assistant providers require an authenticated MDS
  operator/admin session or a bearer token with `agent`, `operator`, or `admin`
  scope. Drone-only bearer tokens cannot trigger external provider calls. Keep
  `MDS_AGENT_PROVIDER=mock` when MDS auth is disabled or the GCS is reachable
  from untrusted networks.
- Policy is enforced in code before any provider or MCP adapter can call a
  domain wrapper.

Risk classes:

- `observe`: read-only state with no expected sensitive data.
- `sensitive_observe`: read-only state that can reveal location, topology,
  mission details, logs, repo state, identities, or configuration.
- `plan`: deterministic planning or validation without flight movement.
- `simulate`: SITL-only side effects.
- `operate`: real-world command/control side effects.
- `admin`: auth, config, runtime, deployment, git, or fleet mutation.
- `destructive`: erase, delete, kill, reboot, or evidence-destroying action.

Default decisions:

- `observe` and `sensitive_observe` may be allowed when the agent runtime is
  enabled.
- Read-only `plan` tools require approval in the default read-only policy.
- Non-read-only planning tools are denied in `read_only` mode even when their
  risk class is otherwise known.
- `simulate` is denied in read-only mode and approval-gated in SITL mode; when the circuit breaker is on, approved simulation tools still stop at dry-run/no-execute.
- `operate`, `admin`, and `destructive` are denied by default.

Changing prompt text does not change enforcement. To change policy, update the
YAML artifact, tests, docs, and review evidence in the same slice.

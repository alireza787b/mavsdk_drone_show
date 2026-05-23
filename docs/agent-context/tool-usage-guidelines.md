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
- MCP authentication is not tool authorization. Metadata-only MCP access
  requires bearer auth by default, and every future tool call must still pass
  registry and policy checks.

Adapters should return structured errors for denied or approval-required tools
so operators can see the exact policy reason.

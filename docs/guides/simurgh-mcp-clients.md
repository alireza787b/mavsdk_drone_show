# Simurgh MCP Client Recipes

Status: read-only connector guidance, updated 2026-06-05.

This guide explains how external MCP clients should connect to the MDS Simurgh
MCP endpoint without bypassing the GCS safety boundary.

## MDS Endpoint

The Simurgh MCP endpoint is:

```text
POST https://<gcs-host>/api/v1/simurgh/mcp
```

For the current production-style demo, the API port is `5030`, but production
clients should use the approved HTTPS hostname or gateway when available. Do not
publish a field GCS directly to the internet only to make an MCP client work.

Required runtime posture for this read-only slice:

```text
MDS_AGENT_ENABLED=true
MDS_MCP_ENABLED=true
MDS_MCP_REQUIRE_AUTH=true
MDS_MCP_REQUIRED_SCOPES=agent,admin
MDS_AGENT_ACTION_CIRCUIT_BREAKER=true
MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true
```

`MDS_MODE` remains the canonical real-vs-SITL GCS runtime switch. MCP does not
have a separate real/SITL mode. When the circuit breaker is on, action-capable
future tools must dry-run to the last execution layer and report what would have
been executed instead of mutating GCS state.

## Current Tool Surface

`tools/list` exposes reviewed read-only tools only. The important operator-facing
entries are:

- `mds.operator.question.answer`
- `mds.docs.search`
- `mds.docs.chunk.read`
- `mds.logs.sessions.read`
- `mds.logs.session.read`
- approved read-only fleet, show, runtime, and policy status tools

Generated OpenAPI candidates are available as a review resource, not as callable
tools. A new FastAPI route is not executable through MCP until it is promoted
through `config/agent_tools.yaml`, `config/agent_policy.yaml`, typed schemas,
docs, tests, and reviewer approval.

For reviewer/developer review, inspect the generated candidate inventory through:

```http
GET /api/v1/simurgh/tool-candidates?limit=200
```

This endpoint reports generator-inferred eligibility, risk class, sensitivity,
review reasons, and existing curated registry matches. It is read-only and does
not affect `tools/list`.

The same response includes `summary.registry_coverage`, which is the review/dev
coverage gate for read-only completion. It shows how many generator-eligible
read-only routes have already been promoted into `config/agent_tools.yaml`, how
many are still unpromoted, and a grouped preview of the remaining API areas.
Unpromoted candidates are discovery/review items only; external MCP clients
cannot call them until the curated registry and policy promote them.

## Authentication Contract

Production MCP access requires an agent/admin bearer token:

```http
Authorization: Bearer <agent-or-admin-token>
```

Bearer tokens are deployment secrets. Store them in the client secret store or an
environment variable owned by a local bridge. Do not commit tokens into
`mcp.json`, n8n workflow JSON, screenshots, prompts, or review reports.

The GCS MCP endpoint advertises OAuth protected-resource metadata and rejects
cookie-session auth for MCP. Agent bearer tokens are scoped to Simurgh/MCP paths
and cannot be reused as general GCS API tokens.

## Scripted Smoke Test

Use the repository smoke client before handing a GCS endpoint to n8n, Claude,
VS Code, or a custom agent. It exercises the same Streamable HTTP JSON-RPC MCP
surface an external client will use, without installing an MCP SDK and without
printing bearer tokens.

```bash
python3 tools/simurgh_mcp_smoke_client.py \
  --base-url https://<gcs-host> \
  --token-file /path/to/agent-token \
  --json
```

For a local validation host, a secret environment variable is also supported:

```bash
MDS_MCP_BEARER_TOKEN="..." \
python3 tools/simurgh_mcp_smoke_client.py --base-url http://127.0.0.1:5030
```

Do not commit tokens, paste tokens into prompts, or store tokens in public MCP
client config files. The smoke validates:

- `initialize` succeeds with the expected MCP protocol version;
- `prompts/list` and `prompts/get` expose at least one reviewed operator prompt;
- `tools/list` exposes the expected read-only tools;
- obvious raw/action/admin tool names are absent;
- `resources/list` is reachable and `mds://simurgh/status` can be read;
- `mds.operator.question.answer` can answer a read-only operator question;
- `mds.docs.search` can retrieve public MDS guidance;
- `mds.docs.chunk.read` can read the selected bounded public-docs chunk;
- `mds.simurgh.tool_candidates.read` reports zero unpromoted
  generator-eligible read-only routes, proving the live registry and OpenAPI
  candidate inventory are still in sync;
- a direct operational request such as launching the show is blocked or dry-run
  only.

This is the preferred first diagnostic when an external client cannot connect.
If the smoke fails, fix endpoint/auth/protocol posture before debugging a
specific n8n, Claude, VS Code, or custom-agent configuration.

## External Client Compatibility Matrix

| Client | Recommended connection path | Secret handling | Notes |
| --- | --- | --- | --- |
| n8n AI Agent | MCP Client Tool node against the approved HTTPS `/api/v1/simurgh/mcp` URL. | Use n8n credentials or supported bearer/header auth fields. | Run the scripted smoke first, then `tools/list`, `mds.docs.search`, and `mds.docs.chunk.read` inside n8n. Cloud n8n should reach MDS through a reviewed gateway, not a field GCS exposed directly. |
| n8n workflow step | MCP Client node when the workflow needs a deterministic tool step instead of an agent tool. | Same credential store as above. | Useful for repeatable read-only reporting jobs. Treat action-capable future tools as approval-gated. |
| Claude remote connector | Approved public HTTPS/OAuth gateway in front of MDS. | Prefer OAuth-compatible connector auth; never paste raw MDS bearer tokens into chat. | Claude remote connectors originate from Anthropic infrastructure, so private NetBird-only endpoints will not connect. Keep action tools disabled until reviewed. |
| Claude Desktop local | Dashboard Simurgh chat for normal operators, or a reviewed local stdio bridge for trusted developers. | Read `MDS_MCP_URL` and `MDS_MCP_BEARER_TOKEN` from the OS secret store or environment. | Do not ship an ad-hoc bridge as a first-party artifact until it has tests and packaging review. |
| VS Code | Remote HTTP MCP server in user or workspace `mcp.json`, or a local bridge. | Use input variables, environment files, OS secrets, OAuth gateway, or bridge-managed env; do not hardcode tokens. | Workspace MCP configs require trust review. Enable sandboxing for local stdio servers where available. |
| Custom agent | Streamable HTTP JSON-RPC with bearer/OAuth auth through the same endpoint. | Client-managed secret store with token rotation. | First pass must call the scripted smoke or equivalent: initialize, prompts, resources, tools, docs read, and blocked-action check. |

The MCP layer is deliberately curated, not a raw automatic export of every GCS
route. OpenAPI candidates are generated automatically for reviewer visibility;
callable tools remain promoted through the registry/policy gate so new APIs can
be added quickly without exposing unsafe routes by accident.

## n8n

Use n8n's MCP Client Tool node when the n8n worker can reach the GCS API endpoint.

Recommended setup:

1. Add an AI Agent workflow.
2. Add the MCP Client Tool node as a tool for that agent.
3. Select Streamable HTTP / HTTP transport if the n8n version offers a transport
   selector. Do not select SSE for MCP; the dashboard assistant has a separate
   first-party SSE progress route, but the MCP endpoint remains Streamable HTTP
   request/response JSON in this slice.
4. Set the MCP endpoint URL to the approved GCS HTTPS URL ending in
   `/api/v1/simurgh/mcp`.
5. Configure auth with an agent/admin bearer token in n8n credentials or the
   node's supported bearer/header auth field.
6. Run `tools/list` first and verify only read-only MDS tools appear.
7. Test with `mds.docs.search` using `query="SkyBrush show upload"`, then call
   `mds.docs.chunk.read` with the returned chunk id.

If n8n and GCS are on the same private network, prefer the private route between
those services over hairpinning through a public URL. If n8n is cloud-hosted,
use a reviewed HTTPS gateway and firewall allowlist rather than exposing a field
GCS directly.

## Claude

Claude remote custom connectors originate from Anthropic's cloud infrastructure,
not from the operator laptop. That means a private NetBird-only GCS endpoint will
not work as a remote Claude connector unless a reviewed public HTTPS/OAuth gateway
or tunnel is deployed.

Recommended production posture:

- Use Claude remote connectors only through an approved HTTPS gateway.
- Prefer OAuth-compatible gateway auth for Claude connectors; do not paste raw
  MDS bearer tokens into chat or connector descriptions.
- For private field work, use the dashboard Simurgh chat or a local stdio bridge
  on a trusted operator machine instead of exposing the GCS.
- For Claude Desktop local workflows, package or configure a local bridge that
  reads `MDS_MCP_URL` and `MDS_MCP_BEARER_TOKEN` from the host secret store and
  forwards to the remote HTTP MCP endpoint. This bridge is planned guidance until
  an MDS-owned bridge package is reviewed.

## VS Code

VS Code supports MCP servers in user or workspace `mcp.json` files and can also
manage servers through Command Palette actions. A remote HTTP server entry has
this basic shape:

```json
{
  "servers": {
    "mds-simurgh": {
      "type": "http",
      "url": "https://<gcs-host>/api/v1/simurgh/mcp"
    }
  }
}
```

Do not hardcode bearer tokens in `mcp.json`. For production MDS today, use an
OAuth-compatible gateway or a local bridge that keeps the bearer token in an
environment variable or OS secret store. Confirm VS Code's trust prompt before
starting a server and use its MCP server logs to debug connection issues.

If a local stdio bridge is used on macOS or Linux, enable VS Code MCP sandboxing
where possible and restrict filesystem/network access to the minimum required.

## Generic Stdio Bridge Pattern

Some clients still work best with local stdio MCP servers. The safe MDS bridge
pattern is:

```text
MCP client
  -> local stdio bridge on trusted operator machine
  -> HTTPS POST /api/v1/simurgh/mcp
  -> GCS Simurgh MCP endpoint
```

Bridge requirements before implementation approval:

- read `MDS_MCP_URL` and `MDS_MCP_BEARER_TOKEN` from environment or OS secret
  store;
- never log bearer tokens or full prompts by default;
- forward JSON-RPC requests without adding new tool semantics;
- enforce request size/time limits;
- reject non-HTTPS URLs unless explicitly in local development;
- expose no direct drone APIs and no raw GCS command routes;
- ship tests for `initialize`, `tools/list`, `tools/call`, auth failures, and
  timeout handling.

## Operator Smoke Checklist

After connecting any client:

1. Call `initialize`.
2. Call `tools/list`; verify raw command/action/admin tools are absent.
3. Call `mds.docs.search` with `SkyBrush show upload`.
4. Call `mds.docs.chunk.read` with a returned chunk id.
5. Call `mds.operator.question.answer` with `What is the difference between
   QuickScout and Swarm Trajectory?` and confirm it answers conceptually.
6. Call `mds.simurgh.tool_candidates.read` with `eligible_read_only=true` and
   confirm `summary.registry_coverage.unpromoted_eligible_candidate_count` is
   `0`.
7. Ask a direct action request such as `launch the show now`; it must be blocked
   or dry-run only in this read-only slice.
8. Check `/api/v1/simurgh/status` from the dashboard: real/SITL mode must match
   the intended GCS runtime, and circuit breaker must remain on for field demos.

The scripted smoke test above should pass before any manual client-specific
checklist is treated as an MCP integration issue.

## References

- MCP authorization specification: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
- MCP remote server publishing guidance: https://modelcontextprotocol.io/registry/remote-servers
- n8n MCP Client Tool: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcpClient/
- Claude remote MCP connectors: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- Claude Desktop local MCP servers/extensions: https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop
- Claude MCP connector API: https://platform.claude.com/docs/en/agents-and-tools/mcp-connector
- VS Code MCP servers: https://code.visualstudio.com/docs/copilot/customization/mcp-servers
- VS Code MCP extension guide: https://code.visualstudio.com/api/extension-guides/ai/mcp

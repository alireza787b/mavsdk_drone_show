# ULog Analysis Roadmap

## Current Slice

MDS now has a bounded PX4 ULog summary contract:

- onboard log id summary via `GET /api/logs/drone/{drone_id}/ulog/files/{log_id}/summary`
- uploaded file summary via `POST /api/logs/ulog/summary`
- shared parser implementation in `mds_logging.ulog_analysis`
- Simurgh local read-only use for onboard ULog metadata and derived summaries
- dashboard `Analyze` control and compact derived summary for each onboard ULog
- explicit unknown/partial-source reporting, parser-cap disclosure, and staged
  analysis cleanup evidence
- mission correlation only when target, time window/action reference, and
  matching command IDs are present
- schema-versioned API and MCP inventory/summary contracts with typed timeout,
  malformed-file, oversize-file, missing-parser, and unavailable-node outcomes
- isolated parser subprocesses with bounded concurrency, memory, input size,
  and wall-clock lifetime
- actor-and-drone-bound opaque browser job handles with hashed transient
  drone-side capabilities
- raw transfer controls for per-file size, aggregate staging size, free-space
  reserve, progress idle timeout, total deadline, retention, and clean shutdown
- one canonical environment registry for GCS, shared deployment, and node-local
  ULog controls

The current summary returns derived metrics only: duration, topic/sample counts,
local-position envelope, battery range, command/ack counts, dropout counts,
selected vehicle status counts, and parser status. It does not return raw ULog
bytes, raw topic arrays, raw logged-message text, exact coordinates, or staged
download content.

The current slice deliberately keeps raw file transfer out of MCP. MCP exposes
metadata and sanitized summaries only; operator/admin browser downloads remain
on the authenticated GCS route and its actor-bound capability flow.

## Next Candidate Slices

1. Selected metrics extraction
   - Add an explicit allowlisted metrics endpoint for bounded time-series data.
   - Require topic/field allowlists, sample decimation, max points, and no raw
     coordinates unless an operator explicitly uses a private evidence workflow.
   - Return a schema-versioned payload suitable for charts and validators.

2. Batch comparison
   - Compare several drones or several flights using the same summary schema.
   - Report duration, max altitude, max horizontal movement, command ack result
     counts, dropout totals, and battery ranges side by side.

3. Simurgh narrative review
   - Feed only sanitized summary metrics to Simurgh/provider composition.
   - Never send raw `.ulg` content, raw topic arrays, exact coordinates, or raw
     logged-message text to a provider.
   - Keep the local deterministic summary as the evidence source and the LLM as
     an explanatory layer only.

4. Offline evidence tooling
   - Add a CLI wrapper around `mds_logging.ulog_analysis` for private evidence
     folders.
   - Emit JSON summaries and optional plots without committing raw artifacts.

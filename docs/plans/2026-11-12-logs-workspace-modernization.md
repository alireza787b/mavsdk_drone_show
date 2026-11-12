# Logs workspace modernization

Status: approved; implementation in progress. Baseline checks are not post-fix
acceptance. Production and aircraft behavior remain unchanged until validated
deployment.

## Product decision

Keep one `/logs` workspace with three task-based tabs:

| Tab | Main operator task | Default / primary controls |
|---|---|---|
| Live | Find out what is happening now | GCS, Warnings+, search; Freeze view / Follow latest |
| Sessions | Review a recorded MDS session | Selected source, recent session; search, time and severity; Export |
| Flight logs | Retrieve/review PX4 flight records | Explicit aircraft; Refresh, selected record summary, Prepare download / Save file |

Remove the Ops/Dev workflow split: ordinary search, history and export are not
developer privileges. Preserve severity, component and time filters through
progressive disclosure rather than adding another expert-mode policy. Keep
technical names/raw record data in the inspector, not permanent page chrome.

The existing summary parser also accepts a local `.ulg` upload. Expose **Open
file** in Flight logs using that bounded local endpoint; it must not upload
anything to an external provider or become a persistent GCS archive.

### Visual and interaction contract

- Use shared PageShell, action bar, design tokens, notices and accessible sheets.
  Flat separators and restrained state accents replace stacked rounded panels.
- One compact source selector: GCS or callsign + hardware ID. Searchable for
  larger fleets, with position ID in the inspector. Inspection/filters never
  retarget an export, transfer or destructive confirmation.
- One dominant event/file list. Selected information opens beside it on wide
  screens and in an accessible sheet on small screens. No always-visible
  component tree or duplicate fleet-health dashboard.
- Search and severity are immediately available. Component/time filters sit in
  one Filters control with an active count; relevant filter chips remain clear.
- Status represents the selected log source and coverage, not aircraft flight
  readiness. Buffered/page warning counts are not current aircraft failures.
- Show original messages faithfully. Historical PX4 warnings do not become
  current preflight blockers. Unknown identity/data remains unknown.
- Icons have text alternatives and touch help. Important uncertainty remains
  visible; supporting policy/debugging details do not fill the screen.
- The shared shell owns responsive navigation. Content uses available width;
  tables/lists own any internal scrolling. Cover intermediate tablet widths,
  touch/keyboard, zoom, light/dark and long identities/messages.

## Existing capability inventory

Retain GCS and aircraft runtime JSONL sessions, live SSE, severity/component
filters, full-text search, live time windows, historical time ranges, freeze/
resume, view clearing, record details/raw JSON and JSONL/ZIP session exports.

Retain onboard ULog inventory/policy/capability, derived summaries, staged raw
downloads and explicit admin erase-all. Maintain single-aircraft identity and
role/capability boundaries. Do not promise portable single-file onboard deletion.
Deleting a staged copy is different from erasing flight-recorder originals.

Keep `/api/logs/*` as the intentional stable logging API root. Do not introduce
an `/api/v1/logs` alias or a second file-transfer/parser ownership path merely
to modernize the page.

## Findings that implementation must address

### Reproduced on disposable fixtures on the validation host

1. `mds_logging/session.py:create_session` produces the same `_2` identity for
   the second and third sessions created in the same second. Use exclusive,
   race-safe creation with a unique suffix; never append unrelated runs together.
2. `read_session_lines(limit=0)` returns one entry rather than rejecting the
   invalid query. Validate positive bounded limits and nonnegative offsets at
   the real HTTP boundaries, with defensive shared-reader validation.
3. A syntactically valid JSON array in a session can raise `AttributeError`
   during filtering. Validate record shape; skip/report malformed records without
   losing the rest of the session or returning a successful fabricated record.
4. The default reader returns all 10,001 test entries. Current UI and exports
   can therefore load complete files into memory; there is no HTTP read cap.

### Confirmed source-path problems; add regressions before replacement

5. `OnboardUlogDialog` polling depends on the entire `activeJob` object and
   installs a new object after every read. This can restart the effect and poll
   immediately instead of respecting the intended interval. Use stable job
   identity, one sequential poll owner, bounded timeouts and generation guards.
6. A job already `ready` in the creation response bypasses the effect that
   initiates the browser save. Do not couple Save availability to one polling
   transition. Treat `expired` as terminal too.
7. Closing/reopening the ULog dialog drops its only transfer handle, while
   accepted server work can continue. Pending creation is not locked until its
   response; delayed creation/erase results are not bound to an immutable view.
8. Session lists can be overwritten by a late response from a previous aircraft.
   Failed historical loads can leave old entries on screen. Stream row IDs
   restart at zero; an open inspector can then resolve to a different source's
   row. Bind observations/inspectors to source/session/epoch identity.
9. Fleet polling uses overlapping intervals and one Promise.all outcome; failure
   of any metadata request becomes a GCS Offline claim. Reuse the established
   cancellable resource pattern and distinguish unavailable metadata from the
   selected stream's actual state.
10. Freeze is described as lossless, but both live and pending buffers are
    capped. Slow subscriber queues also drop events silently. Show coverage/gap
    evidence; do not claim complete records from a live buffer.
11. The watcher registers a subscriber and snapshots the buffer in separate
    critical sections, permitting duplicate delivery at the boundary. Publishing
    also writes to asyncio queues from arbitrary logger threads. Reconcile
    subscription/snapshot ownership and event-loop dispatch safely.
12. Historical inputs are `datetime-local` while the surrounding page says UTC.
    Live windows anchor to the newest record, not advancing wall time. Make UTC
    interpretation explicit; freeze the display-time anchor deliberately while
    frozen rather than silently changing its meaning.
13. GCS exports perform synchronous whole-file reads/ZIP construction inside
    async handlers. Aircraft exports materialize complete remote sessions.
    Bound input/output/concurrency and move blocking work off the event loop.
14. Existing row/export/ULog dialogs do not consistently use the shared focus
    trap/return-focus/scroll/keyboard behavior. The old stylesheet contains
    1,140 lines of page-specific styles and recursive rounded surfaces.
15. Native ULog download/erase admission reads a cached armed flag with a missing
    state defaulting to false. Under the configured disarm policy, actual native
    execution needs confirmed fresh disarm, including filesystem fallback.
16. The summary UI substitutes zero for a missing command/ack count, does not
    distinguish partial duration evidence and presents file metadata time as
    flight time. Preserve unknowns and time provenance; do not infer flight
    correlation from the newest file alone.

Relevant implementation surfaces are `pages/LogViewer.js`, `components/logs/`,
`hooks/useLogStream.js`, `services/logService.js`, `gcs-server/log_routes.py`,
`gcs-server/log_proxy.py`, `mds_logging/session.py`, `mds_logging/watcher.py`,
`src/drone_api_server.py`, `src/ulog_service.py` and `ulog_job_handles.py`.

## Data, lifecycle and safety design

### Live and historical messages

Keep one bounded live buffer and one selected source, not an automatic fleet
subscription. Warnings+ stays the initial field filter; INFO/DEBUG remains
available without changing workspace mode. Preserve last-observed entries
through reconnect with an explicit reconnecting state. Source/filter changes
cancel obsolete reads; neither silence nor a connected proxy socket proves
aircraft health.

Use stable stream epoch/event identity and explicit loss/reconnect coverage.
Do not deduplicate by message text: repeated identical warnings may be real.
Do not promise complete replay across a service restart or beyond the retained
buffer. Point to Sessions when historical coverage is needed.

**Freeze view** only freezes display/following. It does not pause logging, stop
a mission or disarm anything. Count pending events and disclose a bounded-buffer
overflow compactly. **Clear view** clears browser rows only; it must not use
the same destructive affordance as erase-all.

Historical reads need a typed bounded query and a paged response with coverage,
continuation and source/session identity. Apply search/time/component/severity
on the server before pagination. Pin a read boundary for an actively growing
session so later appends do not silently change pages. Detect rotation or a
changed file instead of returning another file under an old cursor. Keep
backward-compatible bounded use of existing limit/offset/since clients; never
silently export only the first page after introducing pagination.

The page's counters and export review state exactly which source, time/search
filter and loaded/full-session coverage they describe. Invalid time ranges have
one inline actionable error, not an empty success result.

### ULog retrieval and summaries

Use the existing native ULog service, parser, capability and actor-bound handle
contracts. Preserve the stock trusted lab path and opt-in hardened machine auth;
do not add another security-mode switch.

Keep a compact recoverable transfer Activity list owned by this feature, not the
flight-command tracker. Persist accepted handles/identity in backend/runtime/
operator context, never raw ULog bytes, root machine credentials or raw node job
tokens. Closing or navigating away does not mean cancel. On return, look up the
accepted job; never automatically submit another create request.

Use a bounded metadata-only request receipt/idempotency seam for creation so a
lost POST response has a recoverable identity. Extend existing ULog ownership
rather than cloning the parameter or flight-command execution pipeline. A node
restart/unknown creation outcome must be reported honestly; it is not permission
to replay a possibly delivered request. Expired handles and changed actors remain
distinct from a transport retry. Do not create a long-lived raw archive to solve
this metadata problem.

Stage selected records conservatively; no background fleet downloads or silent
concurrency increase. Distinguish **Preparing**, **Ready to save**, **Browser
download requested**, failed/expired and unconfirmed outcomes. Offer explicit
Save on an already-ready job. A normal browser download cannot prove a file was
saved to local disk, so neither Ready nor an anchor click means Safe to power off.
Use observed progress/rate only when available; do not invent an ETA.

Validate expected file size and ULog header; produce checksum/coverage evidence
where bytes are actually observed. Stream large files instead of buffering
hundreds of MB in a browser Blob or GCS memory. Retain existing transfer limits,
disk reserve, file leases and cleanup semantics. Stop/cancel controls may only
be exposed if the native operation can acknowledge that effect.

Selected-file summaries use existing deterministic metrics. Show duration
coverage, local altitude datum, parser limits and missing topics honestly.
Raw bytes/coordinates never enter MCP or optional provider calls. Local upload
is explicit and temporary. No automatic full-log parsing across a fleet.

Erase-all stays under admin maintenance with exact aircraft/count scope and a
separate strong confirmation. Disable repeated submission, require the native
configured fresh-disarm evidence immediately before execution and distinguish
accepted erase from verified empty inventory. No erase or retention-policy
change is part of routine download, Close, Clear view or modernization testing
on real aircraft.

### API/MCP and modularity

Keep shared typed logging contracts; add bounded pagination/coverage and
transfer-request evidence where necessary. Extend existing read tools only for
reviewed bounded read arguments/results. Raw transfer and erase-all remain
excluded from model-driven tools. Optional Simurgh stays separate from the
normal operator workspace.

Separate page composition, message querying/stream state, transfer state and
record/summary inspectors. Reuse operator primitives and fleet identity/freshness
helpers; avoid a new generic mission/job framework or splitting small modules
without a real ownership boundary. Remove superseded components/styles only
after all existing capabilities are covered and no imports remain.

## Implementation slices and finite acceptance gates

1. **Evidence/contracts:** add regression tests for reproduced reader/session
   bugs, source races, watcher threading/gaps, transfer transition/recovery and
   native disarm guards. Agree typed query/result and ownership boundaries.
2. **Backend reliability:** fix shared session lifecycle, bounded historical
   queries/exports, stream coverage and ULog request recovery/guards. Preserve
   auth roles, trusted-demo startup and node fallback. Test real registered
   DroneAPIServer routes, not only duplicate toy routes in a test app.
3. **Operator workspace:** deliver Live/Sessions and common source/filter/
   inspector behavior with a flat responsive layout; retire Ops/Dev gating.
4. **Flight logs:** selected-file inventory/summary/upload, recoverable staged
   transfers and separate maintenance confirmation, using the same native API.
5. **Acceptance and release:** focused/full tests, real-built browser coverage,
   isolated SITL ULog retrieval and loss/recovery drill, screenshots, docs/API/
   MCP indexes, private-data/history audit and official/private integration.
   Deploy only after a current aircraft-off/grounded confirmation.

Required scenarios include quiet/reconnecting/offline/auth-expired sources;
freeze/resume with overflow; scope/session changes while requests are pending;
100-aircraft chooser and large logs; UTC/date rollover; malformed/long records;
export format/filter/size correctness; queued/immediately-ready/failed/expired
jobs; lost create/status/content responses; close/reload/account changes;
unsupported storage/parser/quota; absent summary topics; viewer/operator/admin
boundaries; and native unknown/armed/disarmed policy behavior.

Test/build/browser/SITL work runs only on the designated validation host. Use
synthetic records and disposable SITL logs for erase tests. Strengthen the current
ULog runtime validator: its present byte check only proves non-empty output;
add size/header/checksum validation, bounded streaming and deliberate cleanup.
Never use a real-aircraft erase as a release check. Preserve private field
evidence and unrelated local dirty docs.

Publish a concise operator guide and original-resolution combined screenshot
walkthrough, with separate full-size screens. Send the guide/report to the
owner's Telegram, not directly to a customer. Keep the public material generic.
Archive test evidence, preserve rollback/shared dependency providers and remove
only owned test artifacts/worktrees when done.

## Explicitly outside this phase

No flight gains, navigation gates, missions/formation settings or recorder-rate
changes. No raw long-term GCS archive, automatic flight-log upload, new MAVLink
streaming logger, full time-series/map replay suite, inferred flight clearance,
automatic tuning or promoted raw-download/erase MCP tools. These need separate
product/storage decisions rather than being hidden inside a page rewrite.

## Approved follow-up after Logs

Before the same release, investigate and fix the Mission Config edit-time
`Cfg P1 / HB P0` mismatch report. Distinguish actually fresh assignment evidence
from absent, initial or stale heartbeat fields; never suggest adopting an
unavailable/placeholder assignment. Preserve legitimate slot zero where supported
instead of globally hardcoding it away. Auto-detection unavailable is capability
information, not a flight failure.

Fix the Parameters profile table's component/name/column collision and test
actual desktop/tablet/phone layouts. Across Logs, Parameters and Mission Config,
cover configured-but-offline, stale, never-seen, empty fleet, failed metadata,
pending reads and reconnects. Offline does not mean missing configuration or
zeroed live data; show one concise truthful state and a relevant next action.

## Audit baseline and research

At the initial source checkpoint, the designated host passed 184 logging/ULog
Python tests and six frontend suites / 42 tests. Disposable probes reproduced
session-ID reuse, the zero-limit result, non-object JSON crash and unbounded
10,001-row read. These are baseline/audit observations, not post-fix acceptance.

Design references (not certification/equivalence claims):

- [QGroundControl Analyze](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/analyze_view/)
  separates flight-log retrieval from analysis; retain that task distinction
  without copying its entire toolset into the default view.
- [QGroundControl Log Viewer](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/analyze_view/log_viewer.html)
  provides explicit record opening and contextual analysis surfaces; MDS keeps
  its bounded summary scope for this phase.
- [WAI-ARIA modal dialogs](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
  and [alerts](https://www.w3.org/WAI/ARIA/apg/patterns/alert/) inform focus,
  keyboard and non-interrupting status behavior.
- The repository [frontend design system](../guides/frontend-design-system.md)
  and [logging guide](../guides/logging-system.md) remain canonical MDS guidance.

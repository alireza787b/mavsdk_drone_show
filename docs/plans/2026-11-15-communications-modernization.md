# MDS communications modernization plan

## Scope and implementation gate

Modernize communication ownership, state delivery and recovery without changing
mission intent, native PX4 admission, control gains or reviewed command targets.
Keep HTTP resources supported for scripts, third-party applications, diagnostics
and fallback. The user subsequently authorized isolated implementation while the
aircraft incident remains under investigation. Hardware updates and flight
clearance remain separate from source/SITL validation. This plan is the design
baseline; accepted implementation evidence is recorded separately.

The first deployment remains a two/three-aircraft workflow. The user-confirmed
supervisory capacity target is 100 aircraft with five simultaneous dashboards,
with larger synthetic stress tests. A 100-aircraft display benchmark is not approval for a 100-aircraft
formation flight. Current action-readiness requests and retained alert coverage
have separate 100-aircraft limits that must remain explicit.

## Architecture decision

Consolidate producers, schemas, caches and subscription ownership. Do not combine
all communication into one giant packet, FIFO or failure domain.

```text
PX4 / MAVLink
       |
Companion domain snapshots ---- direct leader-state stream ---- followers
       |                              motion remains local
       |
GCS aircraft acquisition owner ---- HTTP fallback / manual HTTP clients
       |
GCS fleet evidence store
       +---- bounded observation publisher ---- shared browser store ---- pages
       +---- HTTP snapshots ------------------- scripts / optional MCP

HTTP commands ---- existing durable command service ---- native aircraft action
                          |
                 command status observations

Logs / ULogs / parameter transactions ---- separate bounded services and budgets
```

One source of truth means one owner for each domain, not one mutable global
object. Aircraft evidence, desired formation, applied formation and command
execution remain different domains. A cached observation never substitutes for
native preparation or the explicit capture bundle.

WebSocket uses TCP and ordered application messages. Combining bulk transfers
with urgent traffic would retain blocking and retransmission coupling even with
an application priority queue. Keep those workloads isolated rather than relying
on a priority label to preempt an in-flight message. See
[RFC 6455 framing and fragmentation](https://www.rfc-editor.org/rfc/rfc6455.html#section-5.4).

## Current implementation and findings

Audit baseline: public source `48286bacaab34ecd6a6cbad7acb5d8b838ea766d`.
These are source findings, not reproduced network measurements or an attribution
of any aircraft incident.

| Area | Verified implementation | Consequence for this plan |
| --- | --- | --- |
| GCS acquisition | `FleetTelemetryPoller` already has independent async workers, pooled keepalive HTTP, bounded concurrency, failure backoff/jitter and late-endpoint fencing. The older `telemetry.py` thread loop is not the current FastAPI acquisition owner. | Preserve the useful scheduler and isolation; do not rewrite it merely because it polls. |
| Browser | Overview shares polling across its own Board/List/Map; Globe has separate HTTP/WS ownership. Shell runtime, Git and command readers can overlap the active page. Routes unmount, so not all page pollers run simultaneously. | Introduce shared authenticated resource ownership before replacing transports. |
| GCS WebSocket | Telemetry, heartbeat and Git sockets periodically construct full per-client snapshots. Telemetry lacks stream epoch/sequence and explicit send deadline; REST and WS do not expose identical metadata. | Produce a generation once and fan out bounded authorized projections. |
| Browser freshness | Globe treats socket open as healthy, has no valid-message idle deadline and no shared ordering fence between HTTP and WS. QuickScout can retain cached sample ages without advancing them during silence. | Unify aging and reject late responses; an open socket is not fresh evidence. |
| Leader acquisition | Smart Swarm HTTP fallback runs for a backoff window, then stops during an additional sleep/WS attempt. Its WS has no deadline for a valid advancing motion sample, and target-change checks depend on receiving a message. | Make fallback continuous while needed and target switches independently cancellable, while preserving local stale-data protection. |
| Companion hot path | Swarm-state serialization can read formation files per consumer; opt-in online configuration can reach a synchronous, unbounded HTTP read from the API path. | Move configuration acquisition out of state serialization and reuse immutable installed assignments. |
| Identity | Fleet polling validates a JSON object but not the expected aircraft/runtime identity. MAVLink source isolation is incomplete for several FC message classes. | Validate identities at ingress. Foreign/misrouted data must not become another aircraft's state. Contamination is a conditional risk, not an observed incident in this audit. |
| Heartbeat diagnostics | Sender treats HTTP 200 as connected even when the response says `accepted: false`. | Use semantic acceptance, with actionable mode/identity diagnostics. |
| Existing safeguards | Command tracking has a durable SQLite journal, request fingerprints, per-aircraft callbacks and restart reconciliation. Formation watch already has revisioned snapshots, latest-only queues and bounded sends. | Reuse these patterns; streaming notifications must not replace durable execution or installation evidence. |
| Authorization | Existing GCS WS authenticates at connection establishment but lacks equivalent topic/resource role checks, Origin validation and long-connection revalidation. | Close these gaps when introducing shared subscriptions; a unified socket must not broaden authority. |

Source map:

- [FastAPI acquisition owner](../../gcs-server/app_fastapi.py),
  `BackgroundServices._poll_telemetry`; [poller](../../gcs-server/fleet_telemetry.py).
- [Canonical receipt join](../../gcs-server/fleet_telemetry_snapshot.py);
  [heartbeat acceptance](../../gcs-server/heartbeat.py).
- [GCS streams](../../gcs-server/api_routes/core.py), `websocket_telemetry`;
  [Git stream](../../gcs-server/api_routes/git_status.py), `websocket_git_status`.
- [Overview resources](../../app/dashboard/drone-dashboard/src/features/fleet-overview/useFleetResources.js),
  [Globe](../../app/dashboard/drone-dashboard/src/pages/GlobeView.js),
  [QuickScout](../../app/dashboard/drone-dashboard/src/pages/QuickScoutPage.js),
  [shell command activity](../../app/dashboard/drone-dashboard/src/contexts/CommandActivityContext.js).
- [Leader acquisition](../../smart_swarm.py), `update_leader_state`;
  [node serializer](../../src/drone_communicator.py);
  [FC message receiver](../../src/local_mavlink_controller.py).
- [Formation watch](../../gcs-server/formation_watch.py),
  [configuration subscriber](../../smart_swarm_src/config_transport.py),
  [command journal](../../gcs-server/command_journal.py),
  [command tracker](../../gcs-server/command_tracker.py),
  [authorization](../../gcs-server/auth_runtime.py).

## Traffic ownership and packet design

| Lane | Delivery semantics | Consolidation and isolation |
| --- | --- | --- |
| Supervisory telemetry | Latest valid state, bounded latency; old intermediate samples may be replaced. | One producer/cache per aircraft; one GCS acquisition owner; a shared browser subscription. Batch changed aircraft/fields within a bounded publication window. |
| Presence and network metadata | Accepted application evidence with its own receipt/expiry. | Piggyback low-rate metadata on the supervisory stream when supported. Retain a low-rate independent heartbeat fallback when it proves companion life without FC data. Never run two continuous equivalent senders unnecessarily. |
| Formation and mission configuration | Revisioned desired state; latest complete plan, explicit installation result. | Reuse formation watch. Small invalidations/revisions can share an observation connection; canonical config writes and aircraft apply remain separate services. |
| Commands and recovery | Durable identity, finite deadlines, explicit accepted/delivered/executing/terminal/unknown states. | Keep authenticated HTTP submission/lookup and existing recovery capacity. Status notifications may share the observation connection but retain durable cursors and lookup recovery. |
| Leader motion | Direct, time-bounded, ordered by source identity/epoch/sample; obsolete samples are discarded. | Keep off the GCS/browser path. Share serializers and lifecycle primitives where appropriate, not a supervisory queue or a browser-selected rate. |
| Logs, ULogs, assets and parameters | Logs require coverage/gap semantics; files require explicit completed transfer; parameter writes require review/readback. | Keep selected-source log streaming, downloads and parameter transactions separate. Use bandwidth/concurrency budgets so bulk work cannot consume all recovery or motion capacity. |

Do not resend static identity, configuration, Git details, repeated status history
or SSID strings with every motion sample. A compact fast topic and slower
diagnostic/configuration topics can use the same supervisory connection without
requiring the same cadence. Each field group retains its own validity and sample
time; absence from an incremental message means unchanged, not zero or cleared.

Start with typed JSON and shared full snapshots. Add resource/field deltas only
when baseline measurements justify their complexity. A delta names its base;
gaps, missing bases, removals or a new producer epoch force a full snapshot.
Do not introduce binary encoding, compression, a broker, QUIC or a new client
framework simply to modernize branding. Profile payload bytes, CPU, memory and
browser compatibility first.

## Shared contracts

Use a small discriminated observation envelope with schema version, topic,
snapshot/event kind, producer/stream epoch, sequence and typed data. Resource
revision, base revision and event cursor belong only to topics that need them.
Do not confuse a wire schema, Git commit, formation content revision, stream
sequence or FC boot identity.

Required behavior:

- Bind state to deployment/runtime and hardware identity; validate expected
  endpoint identity and FC source. System IDs, companion identities and position
  slots are not interchangeable. Conflicts are rejected and diagnosed, not
  silently renamed. Never pin to the first arbitrary MAVLink message.
- Separate configured roster, accepted companion presence, usable FC samples,
  boot/software observations and mission-operation cohorts. Unknown remains
  unknown. New typed contracts need explicit adapters for older primitive/default
  schemas; adding dictionary keys that Pydantic discards is not a migration.
- Preserve source sample/receipt timestamps and clock domain. Use receiver-local
  monotonic elapsed time within a process epoch; UTC is for alignment and planned
  trigger times, with synchronization uncertainty exposed in diagnostics. Never
  subtract monotonic clocks on different hosts or renew a sample on retransmission.
- Clock steps, source restart, FC reboot and sequence rollback create explicit
  reset/revalidation paths. A transport epoch does not prove a new FC sample.
- Make initial subscription and snapshot registration race-free. State replay
  is optional; a full current snapshot is the initial recovery path. An assembled
  fleet snapshot is not simultaneous native capture or a common altitude datum.
- Keep saved, installed and active formation revisions distinct. Delivering an
  edit is not a synchronized moving-leader handover. Preserve existing Hold,
  pilot override and guarded role-change behavior.
- Keep exact command recipients/relevant reviewed revisions. An unrelated
  telemetry update must not invalidate an action through one global revision.

## Acquisition and recovery state machines

Give each resource one owner that selects streaming or sequential HTTP fallback.
Use a common lifecycle pattern with lane-specific timing, not one universal
timeout that serves both a map and a flying follower.

```text
start -> connect -> await valid snapshot -> streaming
                         |                    |
                         +---- idle/error ----+
                                  |
                      HTTP fallback + bounded WS probes
                                  |
                      validate new snapshot -> streaming
```

A socket is live only after valid, identity-matched data, with an application-data
idle deadline. Ping/pong is transport health, not useful telemetry or FC readiness.
Retained samples continue aging even when no messages arrive. Generation fences
reject old socket callbacks, previous targets and late HTTP responses.

HTTP fallback must remain available while WS reconnects. On the motion lane,
WS probes cannot suspend working HTTP acquisition or block an assignment change.
During the brief handover, both transports feed one monotonic installer; duplicate
or older samples cannot win. After valid streaming resumes, stop fallback rather
than leaving two normal producers running. Repeated invalid/error frames count
as absence of useful data, not proof of recovery.

Use bounded connect/read/send deadlines and jittered, capped retry budgets. Avoid
multiplying retries at several layers. Keep native motion/source-age and recovery
policy separate from transport retry timing; never make stale data acceptable to
keep a socket marked live. These retry choices follow the failure/side-effect
distinction in [AWS retry guidance](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/).

## Bounded publication and network efficiency

Build/validate each domain generation once. Authorize and project only subscribed
aircraft/fields, then fan out without waiting for the slowest consumer. State
queues retain a bounded latest generation, not a growing stale backlog. Enforce
byte, message, connection and send-time limits; overflow causes explicit reset or
disconnection and snapshot recovery.

Do not drop command lifecycle transitions or log coverage into a latest-only
telemetry queue. Command status publishes after journal commit, with a durable
cursor where retained; an unavailable history range explicitly falls back to
authoritative lookup. Preserve lightweight idempotency tombstones separately
from large terminal history. An expired/missing lookup is not permission to
redispatch. End-to-end exactly-once physical actuation is not promised.

The browser WebSocket API does not provide automatic receive backpressure
([MDN](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API)). Use
server-side bounded delivery and narrow browser selectors, not just render
throttling after unlimited frames have arrived. Per-consumer isolation and
bounded/coalesced state follow the tradeoffs described in
[websockets broadcasting guidance](https://websockets.readthedocs.io/en/stable/topics/broadcast.html).

Prefer fresh compact data to a queue of historical display positions. Retain
independent motion and recovery capacity. Bulk traffic is limited first when
constrained; supervisory rates may adapt within configured bounds. Motion rates
and native stale-data thresholds do not silently relax with link quality.
No software transport can provide fresh formation data across an unavailable
link; that case must follow the existing aircraft-local Hold/recovery policy.

## Browser and operator workflow

Place the shared resource owner inside authenticated deployment/runtime context.
Components use selectors rather than creating their own fleet poller/socket.
Clear protected state and cancel old generations on logout, role/context change
or runtime switch. Handle session expiry consistently. Keep command inspection
available for reconciliation without replaying intent.

Migrate Overview and shell first, then Globe, Mission Config, QuickScout and
shared rosters on Logs/Parameters/mission pages. Keep native Takeoff/Start review,
capture, parameter review and domain operation polling separate until their
authoritative replacements are explicitly validated. Only then consolidate
small domain status observations/invalidation.

There is no new transport-mode choice for the normal operator. Existing Takeoff,
Start, Pause, Return and To selection remain unchanged. One stable symbolic
connection indicator shows delayed/unavailable updates; details reveal data age
and recovery information. Protocol names, retries and counters stay in diagnostic
details. Preserve urgent alerts and the existing presentation-only settling rules.
Continuous shell attention must not depend on visiting Overview.

Display interest is never command selection. Filtering, scoped subscriptions,
hidden tabs, reconnection, capacity limits and dropped aircraft do not add/remove
reviewed command targets. Throttle hidden maps/rendering, not active mission
authority or necessary observations. A shared tab-level owner is the first step;
cross-tab coordination is optional only after evidence justifies its complexity.

## Authentication and deployment compatibility

Apply topic/resource/role authorization in addition to handshake authentication.
Validate browser Origin for cookie-authenticated sockets; handle expiry,
revocation and logout on long connections. Use existing cookies or short-lived
single-purpose connection tickets rather than permanent bearer tokens in URLs.
Machine identities require explicit permitted resource scope. Keep command
callback capabilities and the optional MCP policy boundary intact. These controls
follow [OWASP WebSocket guidance](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html).

Preserve the stock trusted-network SITL path and existing opt-in production auth.
Do not create a second security-mode flag or require production credentials for
the beginner lab. Secure production endpoints remain secured. Simurgh remains
optional and outside the flight loop; it reads the same evidence services through
its own allowed tools, without an independent fleet acquisition service.

HTTP resource URLs remain supported. Existing versionless WS roots remain stable;
negotiate additive protocol capabilities and retain thin old-shape adapters over
the same producers, not parallel acquisition engines. New clients fall back
cleanly to older servers. Do not strip unsupported safety-critical command fields
to fake compatibility. Keep old/new node mixtures explicit during server-first
deployment; retire internal duplicate readers only after their consumers migrate.

Keep local FC/MAVSDK and MAVLink routing responsibilities intact. A raw QGC/RTK
route is not automatically redundant with MDS telemetry. Unneeded WAN debug
mirrors stay opt-in, as documented; no new high-rate VPS mirror is introduced.
LAN, same-host SITL and routed/VPN deployments use the existing configured
address/security model rather than hardcoded hostnames or Internet dependency.

## Implementation slices and exit gates

Implementation is incremental, not a fleet-wide rewrite and cutover in one step.
Each slice includes tests, relevant docs and a bounded acceptance record.

| Slice | Work | Exit gate |
| --- | --- | --- |
| 0 Baseline | Inventory active producers/consumers and effective rates, payloads, clocks, dependencies and configured limits. Reproduce listed findings with deterministic fixtures. | Agreed capacity/network budgets, measured request/byte/CPU/age baseline; no unsupported savings claims. |
| 1 Correctness | Close semantic heartbeat acceptance, identity, application-idle, fallback-gap, hot-path blocking and stale-response/clock defects in focused changes. Preserve command/native protections. | Regression cases fail before and pass after; foreign identity, open-but-silent WS and HTTP-healthy/WS-broken cases recover without fabricated freshness or target changes. |
| 2 Shared ownership | Add canonical typed domain snapshots/projections and authenticated browser resource ownership using existing sequential HTTP first. Move Overview and shell onto it. | One owner per resource/context; route/login/visibility churn cannot multiply requests; rendering and alert semantics remain correct. |
| 3 Bounded WS | Evolve GCS WS with shared snapshot production, negotiated metadata, bounded fanout, authorization, idle deadlines and snapshot resync. Switch the shared owner to WS-primary/HTTP-fallback. | HTTP/WS parity, no duplicate normal acquisition, no stale overwrite, slow client isolated, bounded resources and mixed-version compatibility. |
| 4 Aircraft supervisory delivery | Reuse node snapshot producers and the existing node-state WS in a single per-aircraft GCS acquisition owner. Combine suitable low-rate metadata; keep independent presence fallback when needed. | One normal monitoring acquisition path per aircraft; no loss of companion-only liveness; healthy peers and recovery capacity survive offline-peer saturation. |
| 5 Workspace migration | Move Globe, Mission Config, QuickScout and shared page rosters to the store. Consolidate small config/mission/command observations only behind their authoritative services. | Same identities/freshness across routes; continuous shell coverage; no duplicate shell/page subscriptions; admission/capture/log/parameter contracts preserved. |
| 6 Motion lane | Reuse immutable leader state generations and bounded fanout; complete separate peer-stream supervision and source/boot/clock tests. Keep guidance policy/gains unchanged. | Direct leader following, HTTP fallback, leader switch and local stale/recovery behavior pass native SITL independently of browser/GCS availability. |
| 7 Release | Run full fault/resource/operator matrix, remove migrated internal readers, update contracts/docs/agents, rebuild affected runtime images, integrate private deployment and verify grounded hardware. | Reproducible evidence, published artifact checksum, clean official/private history, verified rollback tuple and explicit accepted scope. |

An implementation that exposes a deeper flight-control defect stops at that
boundary for diagnosis rather than changing gains or safety policy as a transport
workaround. Do not replace controller process/asyncio selection or the SDK tuple
incidentally during communication refactoring.

## Validation and acceptance matrix

Run all builds and tests on the designated remote validation host. Use bounded
synthetic sources for capacity first; do not start 100 full PX4 simulators on a
small shared machine. Resource-limit every simulator and preserve recovery
headroom, disk reserve and persistent evidence.

| Scenario | Required outcome |
| --- | --- |
| No aircraft, 1, 2 and 3 aircraft | Same simple default workflow, truthful unknown/offline state, stable selection and no unnecessary operator transport choices. |
| 10/50/100 supervisory aircraft and multiple viewers | Bounded CPU/memory/queues; one acquisition owner per aircraft; additional viewers do not multiply node traffic. |
| More than 100 synthetic aircraft | Coverage/limits reported explicitly; no silent truncation, missing targets or claim of unlimited operational support. Resolve action/readiness/alert limits separately. |
| Fast LAN / same-host SITL / VPN or relay | Matching contract and safe behavior; measure usable source age, not only socket RTT. |
| Throttled bandwidth, delay, jitter, isolated/burst loss | Discard obsolete state, prioritize motion/recovery resources, retain honest sample ages, no reconnect storm. |
| Open-but-silent WS, pong-only, malformed/error frames | Application idle detected; HTTP fallback remains effective while bounded probes continue. |
| WS unavailable but HTTP healthy | Continuous accepted fallback samples; no artificial gap due to reconnect sleep or connect timeout. |
| Both unavailable, then recover | Existing local Hold/recovery and pilot override policy preserved; no automatic promotion/config rewrite or queued flight-command replay. |
| GCS/browser restart, FC/companion reboot, clock steps | New epochs resynchronize; old callbacks/samples/commands do not revive. No disconnected state is converted into landed/disarmed. |
| Lost 202, callback, command receipt or journal restart | Original identity lookup and explicit uncertainty; no automatic new command or broadened recipients; retention expiry remains explicit. |
| Slow viewer, slow follower, concurrent bulk download | Other consumers stay independent; queues/timeouts bounded; file/log coverage semantics retained. |
| Formation/role change and delayed old leader data | Canonical revision guards preserved; old target generation rejected; transport does not invent moving handover authority. |
| Browser sleep/wake, StrictMode, navigation, tab hide/show | No duplicate owners/timers, late state overwrite or cached freshness reset. |
| Mobile/tablet/desktop, light/dark, keyboard/touch | Stable minimal indicators, usable details; no connection-banner flicker or selection/display confusion. |
| Lab-open, dashboard auth, full API auth, expired/revoked sessions | Existing deployment posture preserved; resource scopes/Origin enforced; no protected cache crosses user contexts. |
| Manual HTTP and older/newer mixed clients | Supported snapshots, commands, config, downloads and scripts still work with documented capability negotiation. |

Fault injection must be scoped to disposable containers/network namespaces or
test proxies. Never impair the production host, management VPN or unrelated
projects with a host-wide qdisc. Save effective parameters, seed, topology,
budgets, logs and cleanup results so each scenario is reproducible.

Start characterization with 20/100/300/1000 ms RTT, 0/50/200 ms added jitter,
64/256/1024 kbit/s bottlenecks, 1/5/20 percent random loss and 1/3/10/30 second
bursts or disconnects, then refine using field measurements. Include a complete
partition and slow readers despite responsive ping/pong. These are injected test
conditions, not promised operating limits. Where fresh motion cannot fit the
native age budget, passing means correct local recovery and truthful monitoring,
not maintaining formation by relaxing that budget.

Acceptance metrics include bytes/second per lane and aircraft, payload size,
useful sample-age percentiles, idle detection/recovery time, WS/HTTP overlap,
request/retry counts, queue/semaphore wait, coalesced/dropped state, event-loop
lag, control-loop jitter, CPU/RSS and browser render cost. Set numerical budgets
after baseline and before accepting the implementation; do not derive radio loss
or one-way latency from source age alone. Publish operating limits rather than a
claim that every cellular link or fleet size is supported.

## Code ownership documentation and release consequences

- **Node:** focused snapshot and acquisition/supervision modules; existing API
  and FC receiver remain adapters/ingress. No new scenario branches in large
  central files. Inspect all active imports before retiring older telemetry code.
- **GCS:** separate domain evidence store, bounded observation publisher and
  transport adapters. Preserve command journal/recovery lanes, formation store
  and copy-on-read receipt semantics; no nested locks or network I/O under locks.
- **Browser:** one provider inside auth/runtime scope, selector hooks and
  generation-fenced transport supervision. Remove the migrated page pollers,
  duplicate Git readers and obsolete hooks only after all callers are replaced.
- **Contracts:** publish HTTP OpenAPI plus versioned WS schemas/examples and
  contract fixtures; OpenAPI alone does not describe streams. Document precise
  absence/null/tombstone/expiry, restart, ordering and compatibility semantics.
- **Docs:** update Connectivity Runtime, both API guides, Smart Swarm, field/SITL
  validation, logging, deployment/auth, troubleshooting and operator guides with
  the behavior of each accepted slice. Remove unbenchmarked fixed overhead/latency
  claims. Add screenshots only when an operator surface actually changes.
- **Agents and MCP:** update AGENTS, relevant agent context, safe API inventory,
  docs search index, generated tool candidates and tests when their contracts
  change. Plans stay outside runtime docs search and never describe unfinished
  capabilities as available. Simurgh remains optional.
- **Packaging:** capability-based server-first rollout with preserved old-client
  HTTP/WS adapters. Rebuild/checksum/validate/distribute the official SITL image
  when runtime contents change; use that image plus separate private source and
  configuration overlays, never embedded per-node credentials. Public history
  and assets must not contain private customer deployment details.
- **Hardware:** only after image/SITL acceptance, snapshot current node settings,
  deploy on grounded/disarmed aircraft with props removed, verify native identity,
  transport and effective service-user configuration, then rehearse the small
  fleet. Operator-controlled real flights follow separate clearance.
- **Rollback:** preserve source, Python/native SDK, environment, image and schema
  compatibility as a verified tuple. Keep only necessary rollback artifacts;
  resolve dependency symlinks/process working directories before cleaning old
  worktrees. Protected histories and flight evidence remain untouched.

## Decisions still requiring measurement

1. Agree practical latency/bandwidth/loss profiles and acceptance budgets from
   the baseline. No defensible universal cellular performance number exists.
2. Decide whether deltas/compression or an external broker are justified only
   after the shared full-snapshot implementation is measured. They are not
   required for the first small-fleet milestone.

This planning phase creates no new fleet setting, image, transport deployment or
flight approval. The existing production source remains the accepted baseline
until the appropriate implementation and release gates are passed.

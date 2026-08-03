# Field Launch Readiness Incident Checkpoint

**Status:** Systemic fixes and bounded fresh-SITL validation complete; the historical field E202 cause remains unproven and a props-off field retest is pending
**Incident window:** 2026-08-01 16:00-16:30 UTC  
**Checkpoint date:** 2026-08-02  
**Official baseline:** `b00a0599`  
**Private production baseline:** `2f8cefd5`

This checkpoint preserves the sanitized evidence and engineering decisions for
the field report in which Take Off repeatedly failed, Bench Test armed both
vehicles, another action lifted both vehicles, Land worked, and a later Take
Off operated only one vehicle.

The initial investigation was read-only. No drone command, process restart,
repository sync, container change, or live configuration mutation was performed
while preserving the field evidence. The subsequent official-repository fix is
tracked by the finite
[field launch readiness release gate](2026-08-03-field-launch-readiness-release-gate.md).

## Immediate Safety Boundary

Until this incident is closed:

- do not use Bench Test, Hold, Hover Demo, or Take Off with props installed
- preserve the running GCS, drone unified logs, and PX4 ULogs before rebooting,
  updating, or cleaning either node
- when the nodes are powered for evidence collection, remove props, restrain the
  airframes, and do not send flight or arming commands
- validate fixes in SITL first, then on one props-off vehicle at a time; do not
  resume two-vehicle flight testing from the current build

PX4 documents that Multicopter Hold can climb to `NAV_MIN_LTR_ALT` when engaged
below that altitude. MDS must therefore never treat `armed` alone as proof that
a vehicle is safely airborne. See the
[PX4 Hold mode documentation](https://docs.px4.io/main/en/flight_modes_mc/hold)
and [MAVSDK Action API](https://mavsdk.mavlink.io/main/en/cpp/api_reference/classmavsdk_1_1_action.html).

## Evidence Preserved

The live real-mode GCS command tracker still held 12 incident records. A
sanitized, authenticated localhost read captured their full identifiers and
terminal states before any restart. The unified JSONL session independently
preserves the command, heartbeat, API, and execution timing, but it abbreviates
command identifiers and does not persist the full tracker model.

| UTC | Command | Targets | Result | Important evidence |
|---|---|---:|---|---|
| 16:12:04 | `KILL_TERMINATE` `e3ce9954-8a7f-4d30-9ca0-a6bf44f336fd` | 2 | Failed | Accepted, then optional SPI/LED access failed before successful termination was reported. |
| 16:15:26 | `TAKE_OFF` `79d30384-6c29-416f-8796-c41f92509d03` | 2 | Failed | Node rejected with generic E202 cached-readiness error. |
| 16:19:59 | `TAKE_OFF` `2715ecb2-f7e5-427d-8788-9b2361d7a80a` | 1, 2 | Failed | Both nodes rejected with E202. |
| 16:20:41 | `TEST` `5647a477-14df-46f2-80b9-145b06a5bf7b` | 1, 2 | Complete | Both nodes armed/disarmed through Bench Test and reported success. |
| 16:21:08 | `TAKE_OFF` `1b2e4549-8985-4a3a-b684-c26984b4dd1b` | 1, 2 | Failed | Both nodes again rejected E202 immediately after Bench had armed them. |
| 16:21:21 | `TEST` `c4edb2cf-3d21-466c-a417-65bdeff12d3d` | 1, 2 | Complete | Both Bench executions succeeded. |
| 16:22:22 | `TEST` `50010255-d234-4b91-8cbe-a48ea714559f` | 1, 2 | Failed | Both processes exited on `/dev/spidev0.0`/SPI LED errors; final PX4 disarm state is not proven by GCS evidence. |
| 16:22:47 | `TEST` `a0fcdb47-f3b1-474d-bd8e-75bcceebcc07` | 1, 2 | Complete | Both later Bench executions succeeded. |
| 16:23:08 | `HOVER_TEST` `761a9d77-b588-455f-9eeb-9baffcea465e` | 1, 2 | Superseded | Mission 106, not Hold 102, was accepted and started on both nodes. It intentionally runs the lift/hover CSV. |
| 16:23:39 | `LAND` `a14a6c7d-250f-417f-9ab8-ce9cf68a575d` | 1, 2 | Complete | Superseded Hover Test; Land completed for node 1 at 16:24:04 and node 2 at 16:24:39. |
| 16:24:36 | `TAKE_OFF` `acb40786-0f7b-4651-881b-5200c477a138` | 1, 2 | Partial | Live armability had just passed for both, then dispatch independently labelled node 2 stale/offline and skipped it; node 1 completed Take Off. |
| 16:25:03 | `LAND` `72348fe3-ba08-4ce7-865b-ad69208377ee` | 1, 2 | Partial | Node 2 was skipped from cached stale presence even though it had just delivered the preceding Land completion callback. |

Five additional launch submissions never received command IDs because they
ended with HTTP 400 before tracker creation: Take Off at 16:11:43, 16:15:48,
16:19:28, and 16:21:52, plus Hover Test at 16:16:57. Their 7-17 second
durations and the applicable command path identify the pre-dispatch live
armability gate. The exact response details were not logged.

There is no `HOLD` mission 102 in this GCS incident window. The operator may
have meant Hover Demo, used an older/stale browser bundle, or described the
observed behavior imprecisely. A screenshot/video and ULog command sequence are
needed before attributing the lift to Hold. The armed-ground Hold defect below
is independently real, but is not yet proven to have caused this flight.

## Proven System Defects

### 1. Conflicting readiness authorities

A standalone Take Off currently crosses several different gates:

1. GCS on-demand MAVSDK armability
2. node cached `is_ready_to_arm` from handwritten MAVLink heuristics
3. action GPS/home readiness
4. action-time MAVSDK armability and PX4 command result

The live GCS probe can pass and the node can then reject the same request from
its cache. Bench bypasses the launch gates and directly calls arm. Hover Test
passes the GCS gate but does not use the Take-Off-only cached gate, then uses its
own execution-time startup checks. The observed sequence is therefore
consistent with the code: Bench and Hover can run while Take Off reports E202.

The cache also treats text matching `Arm denied`, `Takeoff denied`, or
`Preflight fail` as a hard blocker for 120 seconds without a resolved-event
lifecycle. A transient denial can therefore make readiness change apparently
"by itself" two minutes later.

### 2. The GCS blocks its only event loop during launch checks

Production intentionally uses one ASGI worker because heartbeats, telemetry,
and command tracking are in process. The async command route calls synchronous
HTTP probes and dispatch functions directly. Each slow launch request blocks
that worker for 7-17 seconds.

Heartbeat HTTP 400 bursts occur at the exact end of those stalls. The node
heartbeat client times out after three seconds. This is strong evidence that
the GCS degrades its own control plane while checking readiness; it can then
classify the affected node stale inside the same operator request. Increasing
the worker count is not a valid fix because it would split in-memory state.

### 3. A UI timeout can precede an untracked side effect

The dashboard gives command submission 12 seconds. The readiness probe alone
has an approximately 13-second budget, tracker creation happens only after the
probe, and dispatch can take longer. If the browser times out, backend work can
continue without the UI receiving a command ID. First-party dashboard actions
also do not provide stable idempotency keys. This creates a latent hidden or
duplicate command risk even though it is not yet proven to have caused this
incident.

### 4. Presence decisions contradict direct reachability

The final Take Off could only pass preflight if both nodes answered the direct
live-armability request successfully. Immediately afterward, dispatch used an
older heartbeat/telemetry cache and skipped node 2 as stale. One request thus
declared the same node both reachable/ready and offline.

Heartbeat liveness is based on the node-supplied timestamp rather than a GCS
receipt timestamp. Clock skew, event-loop delay, or queued delivery can distort
presence. The same cached preclassification is used for all missions, so it can
suppress Land, RTL, Hold, and emergency delivery without a direct attempt.

### 5. Bench and Hold have unsafe state and cancellation semantics

`TEST` is labelled Bench Test but physically arms, waits through LED steps, and
then disarms. It has no `finally` disarm, no telemetry-confirmed cleanup, and no
cooperative cancellation contract. An LED exception or process termination can
interrupt it after arm and before disarm.

Hold acceptance checks only cached `is_armed`; it does not check landed state,
relative altitude, freshness, or an authoritative airborne transition. The
current test suite asserts only that a disarmed Hold is rejected. It therefore
permits exactly the unsafe armed-and-grounded case despite operator copy saying
the command requires an airborne vehicle.

### 6. Optional LED failures can block flight and emergency actions

Land, RTL, Hold, Kill/Terminate, and Bench invoke LED hardware inline. Several
set LED state before the PX4 action. The field log proves SPI failures can fail
the process, and Kill/Terminate failed on this path. Optional operator feedback
must never be able to prevent or redefine a flight/recovery/emergency result.

### 7. Error detail and command durability are insufficient

The node ACK contains the readiness blocker in `error_detail`, but the GCS
summary discards it and retains only generic E202 text. That is why the exact
field blocker cannot be recovered from the GCS.

The command tracker is memory-only. Preflight failures before tracker creation
do not exist in command history, and a restart loses full command records. The
active unified session is also dominated by authentication and expected-origin
noise, reducing diagnostic signal.

### 8. Command delivery is not target-identity-bound

The GCS routes to a configured IP, but the command envelope does not carry the
intended hardware identity for node-side rejection and GCS ACK verification.
A stale or reassigned route must not be retried blindly. Recovery delivery can
be best-effort over stale routes only after commands and ACKs are bound to the
intended node identity.

## Not Yet Proven

- the exact PX4, sensor, GPS, home, or cached-text blocker behind E202
- whether the operator saw Hover Demo, Hold Position, or a stale UI bundle
- whether the failed 16:22 Bench run left either vehicle armed
- whether node 2 suffered a real network outage; stale presence is proven, but
  GCS event-loop starvation can explain it without a physical NetBird failure
- the exact PX4 command ordering that caused the observed lift
- whether firmware, parameters, clocks, and runtime commits matched on both
  physical nodes

## Evidence Collection When Nodes Reconnect

Perform these steps before reboot, update, cleanup, or flight command:

1. Confirm props removed and airframes restrained; record GCS and node UTC clock
   offsets.
2. Snapshot node HEAD/build identity, service/process health, runtime mode,
   control IP, NetBird state, API reachability, heartbeat receipt age, telemetry
   age, armed/landed/mode, relative altitude, cached readiness, blocker messages,
   and timestamps.
3. Call live armability once per node while grounded and compare it with the
   cached state. If they differ, sample cached readiness every second for at
   least 130 seconds and repeat the expensive live probe at controlled,
   non-overlapping intervals.
4. Export every node unified-log session covering 16:10-16:26 UTC and all PX4
   ULogs spanning the test. Preserve originals before parsing.
5. Capture PX4 firmware/hardware identity and relevant parameter snapshots,
   including `NAV_MIN_LTR_ALT`, takeoff, arming/disarming, estimator/GPS/home,
   safety, and offboard-loss settings.
6. From each ULog, correlate `vehicle_command`, `vehicle_command_ack`,
   `vehicle_status`, landed detection, arming/health checks, PX4 events/status
   text, failsafe flags, local/relative altitude, and actuator state.
7. For the failed Bench window, prove whether ARM was followed by DISARM and a
   final disarmed/landed state.

Forensic discriminator:

- Bench then grounded Hold: ARM command, Hold/mode change, no preceding Takeoff
  command, still landed at Hold entry, then climb toward `NAV_MIN_LTR_ALT`
- delayed Take Off: ARM and Takeoff command precede the mode transition
- external/PX4 cause: the MDS sequence is absent or has a different source

## Minimal Questions For The Field Operator

1. When both vehicles rose, did the confirmation say **Hover Test / Hover Demo**
   or **Hold Position**? Send a screenshot/video and name the device/browser.
2. Provide exact local time/timezone, click order, target selection, and whether
   the next action was pressed before Bench reached a terminal result and both
   vehicles visibly and telemetrically disarmed.
3. What exact Take Off error/readiness blocker appeared in MDS or QGC? Did the
   failed Bench attempt leave motors armed or spinning, and were props fitted?
4. Did node 2 show a connectivity badge change? Please power both nodes with
   props removed, preserve logs/ULogs, and avoid arm/flight commands while the
   read-only capture runs.

After evidence preservation, also confirm whether Kill/Terminate was deliberate,
the unexpected climb altitude/mode shown in QGC, and whether firmware and
parameter sets were intended to be identical.

## Systematic Fix Boundary

Do not solve this with timeout increases, spelling aliases, extra readiness
booleans, or a customer-only patch. Implement and validate these cohesive
slices in official MDS, then sync the private deployment:

1. **Vehicle safety authority**
   - one timestamped typed snapshot for armed, landed/airborne, relative
     altitude, position, health/armability, evidence source, and freshness
   - consume authoritative landed-state telemetry such as
     `EXTENDED_SYS_STATE`
   - one execution-time launch predicate; cached heuristics are operator
     evidence, not a competing hard gate
   - Hold revalidates fresh `airborne=true` immediately before changing mode
2. **Safe action transactions**
   - rename and explicitly guard the physical Arm/Disarm Bench Check
   - require grounded/disarmed start plus props-off acknowledgement
   - verified arm/disarm, cooperative cancellation, and guaranteed cleanup
   - make LED output best-effort and outside flight/emergency success semantics
3. **Non-blocking durable command lifecycle**
   - create an ID and durable `preflighting` record before slow work
   - return promptly, use async HTTP or bounded worker offload, and keep
     heartbeat/callback routes responsive under worst-case probe latency
   - stable client idempotency; no retries for deterministic rejection
   - persist command, probe, ACK, execution, cancellation, and terminal evidence
4. **Coherent presence and delivery policy**
   - GCS receipt time is authoritative liveness; client time diagnoses skew
   - carry successful direct reachability evidence into the same dispatch
   - bind command audience and ACK identity to the intended hardware ID
   - launch fails closed on uncertainty; safety/recovery delivery uses a
     separately reviewed bounded policy and reports unconfirmed delivery
5. **Operator UX and observability**
   - preserve sanitized `error_detail` end to end
   - distinguish Hover Demo from PX4 Hold everywhere and upstream the useful
     private wording
   - disable/inform actions from fresh eligibility, but revalidate server-side
   - reduce repeated auth/origin noise without hiding genuine failures

Required regression coverage includes armed-ground Hold rejection, Bench
cancellation at every step, guaranteed disarm, transient blocker resolution,
browser timeout with no hidden side effect, idempotent retry, slow-probe
heartbeat/callback responsiveness, clock skew, stale-route identity mismatch,
two-node partial connectivity, and LED failure during every recovery/emergency
action.

## Repository And Deployment State

The incident-critical backend/action/readiness files are byte-identical between
official and private baselines. This is not a private-only drift defect. The
private UI already has clearer Hover Demo wording, including that it is not PX4
Hold; that generic improvement should be upstreamed.

The real GCS and a separate old SITL GCS/container currently coexist on the
validation VPS. Runtime-mode filtering prevents cross-mode heartbeats, so this
is not a proven incident cause. Before the next field test, preserve evidence,
then move production to a supervised single-owner service and remove stale SITL
runtime only through the documented cleanup path.

The incident ULogs were not available from the GCS or validation VPS while the
physical nodes were offline, so the exact PX4, sensor, GPS, home, or cached-text
blocker behind the field E202 response remains an explicit evidence gap rather
than a guessed root cause. That gap did not justify leaving the independently
proven MDS defects in place.

A separate SITL regression ULog was preserved after a later command-reporting
failure. It proved the vehicle physically ascended while the command was
reported failed: armed/airborne at 8.03 m, recovery began while airborne at
9.51 m, landed at 05:03:39.081 UTC, and disarmed at 05:03:41.089 UTC. Its
SHA-256 is
`1b66bdb518ce5019a53d1128f0a52770f96ed921413e143b49b90f15d879bf55`.
This evidence motivated authoritative Take Off terminal-state handling and
typed command outcomes; because it predates those fixes, it is regression
evidence rather than final acceptance evidence.

The final bounded acceptance used two clean scenarios. `actions_core` passed
at `/root/mds-validation-evidence/20260803T055900Z/actions-core`, including
Take Off, Hold, precision movement, typed supersession, RTL, and safe final
reset. QuickScout then exposed and isolated an incorrect reuse of strict
`IN_AIR` truth for recovery Hold while PX4 was still `TAKING_OFF`. After adding
a separate fail-closed clear-of-ground recovery predicate, the single rerun
passed at
`/root/mds-validation-evidence/20260803T061759Z/quickscout-runtime`: +6 m
airborne confirmation, completed Hold, `holding`, completed abort/RTL, zero
active commands, and final idle/disarmed/ready state. The combined final owner
gate passed 453 tests with one skip, and the production dashboard build passed.

The software/SITL gate is therefore closed. The physical retest still starts
on one props-off vehicle and does not become a two-vehicle props-on test until
the operator verifies version convergence, current readiness, QGC arming
checks, and unambiguous command history.

## Implemented Resolution Checkpoint

The fix replaces the conflicting and process-local incident paths with shared,
typed boundaries:

- a connection-bound safety snapshot is now the sole action-time authority for
  Take Off, Hold, and Arm/Disarm Ground Test; disconnect/reconnect, stale source
  data, boot-clock rollback, mixed-age fields, and unknown evidence fail closed
- launch preparation is command/target/payload-bound, one-use, time-bounded,
  and revalidated at commit; exact lost-response replay cannot execute twice
  inside the current node process
- command preparation and fleet RPC are bounded asynchronous work with a
  separate recovery lane; the HTTP receipt exposes a durable tracking identity
  before slow work rather than hiding a later side effect behind a browser
  timeout
- the GCS SQLite/WAL journal preserves command identity, idempotency,
  per-target evidence, deadlines, and callback authority across a restart;
  uncertain post-dispatch work is reported as `delivery_unknown` and is never
  automatically redispatched
- Take Off and Ground Test handle SIGTERM/SIGINT cooperatively through bounded
  cleanup; forced termination reports cleanup as unconfirmed instead of
  inventing a safe final state
- optional LED/SPI feedback cannot prevent or redefine recovery/emergency
  command success; Hold uses a distinct fresh recovery predicate for an armed
  vehicle at least 0.5 m clear of ground during `TAKING_OFF`, `IN_AIR`, or
  `LANDING`, while Take Off completion still requires strict `IN_AIR`
- Take Off terminal completion is based on authoritative post-climb vehicle
  state, battery values preserve MAVSDK percentage units, and node callbacks
  carry explicit `completed`, `failed`, or `superseded` outcomes through the
  API, tracker, late-report record, and journal
- QuickScout target identity and mission updates are transactional, mixed
  delivery retains the active slot, and late callbacks remain audit evidence
- the dashboard preserves the correct mission identity after refresh, keeps
  terminal history out of the live primary card, and keeps dismissed failures
  dismissed for the provider session

The final combined owner gate passed 453 tests with one skip, the dashboard
passed all 119 suites / 667 tests and its production build, and the bounded
fresh-SITL actions and QuickScout scenarios passed. This is software/SITL
evidence, not field-flight approval; the remaining gate is the controlled
props-off hardware retest.

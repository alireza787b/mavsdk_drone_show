# Coordinated Takeoff implementation checkpoint

## Accepted operator behavior

One reusable Takeoff dialog for Dashboard, Smart Swarm and aircraft actions:
height, page-scoped roster, native readiness and **Wait for all aircraft**
(default on for a group). One **Arm & take off** confirmation. Closing is not
cancellation. Abort decisions remain **Cancelling** until recovery evidence is
received; unconfirmed recovery never becomes a green success.

The initiating aircraft are preselected. Operators can explicitly exclude and
reinclude rows before confirmation; excluded rows remain visible and muted.
Select-all/none and the confirmation count make the scope visible. Selection
locks on confirmation, including uncertain receipt recovery; single-aircraft
subsets use native independent Takeoff. Saved formation and complete-cluster
Start Swarm selection are not modified.

Group execution requires every participant's fresh armed/ground proof before a
shared release. Independent mode is explicit. PX4 checks, flight tuning and live
swarm formation are unchanged. A failure after release can still produce a
partial launch; this is not physically atomic takeoff.

## Implemented

- Typed command mode, preparation capability, command-bound stage messages,
  existing command journal integration, causal freshness challenges and bounded
  node wait using actual PX4 auto-disarm configuration.
- Native read-only readiness, operator cancellation, compact tracked progress,
  explicit node capability requirements and replay/restart fences.
- Normal disarm only with fresh ground proof on pre-release abort. Conditional
  post-release Hold uses active command ownership and fresh native Takeoff state,
  never overriding a newer command, pilot takeover or native Return/Land.
- Capability context passed through an anonymous inherited descriptor, not CLI
  arguments. No additional mission manager or general Arm action.
- Shared dialog, expiry during stalled polling and uncertain receipt recovery.
  Simulated browser captures cover ready/blocked/arming/verified cancellation in
  light/dark desktop/mobile, with zero external API writes.

## Evidence and remaining acceptance

All builds/tests run on the remote validation host. Initial validation was
isolated from production and real aircraft. The server/UI source candidate was
later deployed for inspection after both aircraft were confirmed powered off;
this does not establish installed-board revision or flight clearance.

The final integrated backend run passed **570 tests**; the frontend passed
**94 tests in 10 suites** after the selection follow-up. The strict production
frontend build passed. The browser-only probe passed 24 simulated states across dark/light desktop/mobile,
with zero external API writes. Logs use `/tmp/mds-coordinated-*`.

Real two-node PX4 SITL caught issues not represented by unit mocks:

1. The stock image uses Python 3.10, without `asyncio.timeout`. Replaced with an
   owned task and monotonic cancellation timer; external cancellation remains
   distinct from lease expiry.
2. Native probing time was subtracted twice from readiness freshness. Subtract
   network transit, not time already spent constructing the sample; preserve
   parallel-wait aging and reject inconsistent processing durations.
3. Reopening native subscriptions on every barrier poll consumes the native
   heartbeat cadence and expires report challenges. Integrate the action-scoped
   continuous sampler with actual receipt timestamps, unchanged safety expiry,
   disconnect/boot-reset rejection and bounded subscription cleanup. Do not
   resolve this by inventing fresh timestamps or relaxing checks blindly.

Two-node PX4 SITL using the stock image plus the tested source overlay passed:

| Drill | Evidence | Result |
| --- | --- | --- |
| All-armed release and climb | `mds-coord-sitl-success.json` | Both confirmed armed/on-ground before the common release; both confirmed airborne, then Land completed |
| Immediate cancellation | `mds-coord-sitl-cancel.json` | No release |
| Cancellation while armed | `mds-coord-sitl-cancel-armed.json` | An aircraft reported armed before cancellation; no release; final disarm evidence and Land completed |
| Native PX4 rejection | `mds-coord-sitl-blocked.json` | No release, no dispatch acknowledgements or execution; simulator-only `COM_ARMABLE` restored afterward |

Repeated readiness probes after Land also exposed an intermittent native probe
subscription/lifecycle problem: the direct MAVLink state remained fresh while
the temporary SDK probe stopped receiving required samples. A 12-second packet
capture proved heartbeat, SYS_STATUS, landed-state, battery and position packets
were reaching the SDK UDP input without kernel drops during a failed probe.
The remaining fault is therefore in SDK/probe consumption or lifecycle, not
missing PX4 UDP telemetry. Its exact cause is not yet established.

The connection-wait subscription now closes explicitly on success, timeout and
cancellation. Targeted cleanup/probe tests passed **140 tests**; this is not
proof that the missing-stream problem is resolved. When health did arrive,
PX4's native armable bit was sometimes false while retaining Land mode. That is
a separate native state, not an MDS-only threshold to loosen.

Treat repeat-sortie reliability as an open acceptance item. Do not substitute a
PX4 reboot, stale telemetry, private SDK-channel hooks, or relaxed checks for a
verified fix. Keep the source prerelease and production/hardware clearance
distinct. Preserve the bad-probe JSON and UDP packet capture with the four drill
reports before removing the isolated simulators.

Post-release ownership/recovery, lost-response deadlines, stale evidence and
restart fencing have targeted automated coverage. They have not all been
fault-injected in live PX4 SITL or validated on hardware. No new pinned SITL image
has been built or distributed; the acceptance above is for the source overlay.

Isolated validation uses two disposable `mds-coord-test-*` containers, an isolated
SITL GCS on port 5031 and preview on loopback 3046. It does not switch production
to SITL. One narrowly scoped temporary INPUT rule permits only those simulator
addresses to reach that isolated GCS; remove it with the validation services and
containers at handoff. Preserve flight evidence and original production data.

## Source handoff and remaining release gates

The repeated-probe finding is bounded above, but not fixed. The source-candidate
handoff includes the operator guide, simulated screenshots, typed API/MCP
contract changes and reusable validators. Inspect outgoing public history for
private data and integrate only shared files into the private deployment.
Aircraft revision/readiness verification remains required online;
source or UI acceptance is not hardware flight clearance or a rebuilt image.

UI-only follow-up validation covers default scope, explicit exclusion,
select-all/none, blocked reasons at zero group lease, frozen selection and exact
subset receipt recovery. The combined operator guide uses unmodified captured
UI examples; all command responses in browser evidence are simulated.
Shared Takeoff and Jog dialog styles load once in the app shell, avoiding
route-dependent stylesheet ordering. The combined guide is linked from the
[operator steps](../guides/coordinated-takeoff.md).

Any rollout that restarts flight services remains gated on confirmation that no
real flight or test is running. Required before field clearance: finish the repeat-sortie
probe investigation, verify the installed node revisions/capabilities, and
validate the relevant remaining fault-injection cases. A packaged/pinned runtime
release additionally requires a rebuilt SITL image once build headroom is
available; publishing this source candidate does not update the old image.

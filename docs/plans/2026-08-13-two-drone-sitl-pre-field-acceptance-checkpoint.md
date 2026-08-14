# Two-drone SITL pre-field acceptance checkpoint — 2026-08-13

Status: **SITL PASS**

Scope: H1 leader, H2 follower, fixed `+6 m north` NED formation

Accepted evidence time: 2026-08-13 14:51 UTC

## Decision boundary

The exact two-aircraft workflow planned for the next controlled field test
completed in SITL. This is a software/rehearsal acceptance gate only. It is not
real-aircraft authorization, a safety certification, or evidence that the
field network, GNSS/RTK, airframes, PX4 parameters, environment, or operator
procedures are ready. A qualified operator retains flight authority and must
complete the field gates below.

## Rehearsal provenance

| Item | Accepted value |
|------|----------------|
| Official source checkpoint | `288738a1` |
| Synchronized downstream runtime | `4beed51225745e0cb67b83a86715d02a7b749738` |
| GCS and both SITL node checkouts | exact, clean downstream runtime commit |
| Online fleet | exactly two reconciled SITL instances |
| SITL image ID | `sha256:9d70b70e33a178ab5c790063b1dc254b7fc1cc1c72466590ba02ed209a8c0a49` |
| Dashboard build provider | Hetzner validation host |
| Dashboard build tree SHA-256 | `091914e12a3915195d23768755a12b211daf3598c9d0ca1863d52a9fa337af14` |
| Dashboard archive SHA-256 | `334e79db647ef6627114dd9b42749baa53a08ef1089bc2c9d8a1ffd88ac35e99` |

The official and downstream commit IDs differ because the approved official
changes were replayed into the downstream history. The validator rechecked a
fully reconciled SITL runtime immediately before every mutation; it did not
trust a startup-only mode check.

## Exact scenario and result

1. Verify H1/H2 live, ready, disarmed, idle, and inside the existing altitude
   readiness gate.
2. Snapshot the complete saved swarm resource and apply a temporary H1/H2 NED
   topology without committing it.
3. take off H1 and H2;
4. stage H2 at `+6 m north`, zero east, and the same altitude as H1;
5. prove independently advancing, fresh leader and follower swarm streams;
6. start Smart Swarm;
7. move H1 `1 m north`;
8. verify the follower remains in Smart Swarm and converges without an unsafe
   position discontinuity;
9. command HOLD recovery, then LAND both aircraft;
10. prove both nodes disarmed and idle, then restore the complete saved swarm
    resource.

| Gate | Evidence | Result |
|------|----------|--------|
| Paired takeoff | 2/2 accepted acknowledgements; 2/2 successful terminal executions; both climbed at least 4 m | PASS |
| H2 staging | actual relative N/E `+5.878/-0.018 m`; horizontal error `0.124 m`; altitude error `0.112 m` | PASS |
| Fresh swarm streams before start | H1 advanced 6 samples, age 1 ms; H2 advanced 8, age 0 ms | PASS |
| Smart Swarm start | 2/2 accepted; both entered mission type 2 | PASS |
| Initial capture | horizontal error `0.133 m`; altitude error `0.182 m` | PASS |
| H1 north jog | requested `1.000 m`; actual N/E `+0.813/+0.045 m`; endpoint error `0.193 m` | PASS |
| Post-jog formation | H2 remained in mission type 2; horizontal error `0.251 m`; altitude error `0.147 m` | PASS |
| HOLD recovery | 2/2 accepted and 2/2 completed; both remained airborne in hold | PASS |
| LAND | 2/2 accepted and 2/2 completed | PASS |
| End state | zero active commands; both disarmed, idle, ready, and grounded by the validator gate | PASS |
| Configuration restore | saved assignment IDs 1–4 restored; restored JSON value matched the original snapshot | PASS |

Smart Swarm is intentionally continuous. Its command record was still
`executing` after 2/2 acceptance while the follower loop was active; the later
HOLD command ended that mode. This is expected lifecycle behavior, not a
missing terminal result.

## Tracking and smoothness evidence

The accepted trace contains 506 samples. Across capture, the leader jog, HOLD,
and LAND, mean horizontal formation error was `0.147 m`, maximum horizontal
error was `1.392 m`, and maximum altitude error was `0.316 m`. The horizontal
peak occurred during the deliberate leader jog and remained inside the
configured `1.5 m` formation tolerance.

| Stage | Samples | Mean horizontal error | Maximum horizontal error | Maximum altitude error |
|-------|---------|-----------------------|--------------------------|------------------------|
| Smart Swarm capture | 84 | `0.144 m` | `0.182 m` | `0.188 m` |
| Leader north jog | 134 | `0.334 m` | `1.392 m` | `0.316 m` |
| HOLD recovery | 63 | `0.067 m` | `0.131 m` | `0.212 m` |
| LAND | 225 | `0.060 m` | `0.110 m` | `0.144 m` |

Using unique follower stream sequences, the largest position-derived
horizontal step during the jog was `0.112 m`; maximum derived horizontal speed
was `1.11 m/s` and the jog-stage 95th percentile was `0.45 m/s`. The trace
recovered below `0.5 m` error about `1.02 s` after the peak, below `0.3 m` in
`5.87 s`, and below `0.2 m` in `8.79 s`. The plot shows a bounded, damped
response rather than a position jump or sustained oscillation.

Those values are derived from quantized position telemetry. They are useful
for finding discontinuities, but they are not direct actuator, acceleration,
or jerk measurements. Controller unit tests cover the configured shaping
bounds separately; this checkpoint does not infer acceleration from the
position trace.

## Evidence artifacts

The raw evidence remains in restricted external storage and is not committed
to the public repository. In particular, the runtime summary can contain
deployment metadata even when the flight scenario is SITL. These hashes bind
this sanitized checkpoint to the accepted files without publishing that
metadata.

| Artifact | SHA-256 |
|----------|---------|
| `smart_swarm_tracking_summary.json` | `d9ec0c951e0133f6e248ccb48f89a462eacb534e974ecb37bedaaf3764b380be` |
| `smart_swarm_tracking_samples.csv` | `0b0ad7b8e5a9f3eb908bc93109e004b6d7aec51e36f368efd48b7bb28cfa0455` |
| `smart_swarm_tracking_3d.png` | `99064c101863f869e7b1adef6a2dede736639b84c5290a7191d2365f394138b1` |
| `smart_swarm_tracking_overlay.png` | `64cf19a50451ac9401bca2d33dcd647df4090ee168b87dd5b81b59bd039a8f27` |
| `smart_swarm_tracking_relative.png` | `621e94a60703383259046509448df52c4104f8095ad72288d26052b7504d1426` |
| `smart_swarm_tracking_timeseries.png` | `85e365131c77fe7d8bf0ebe5b91b4fa772daf239a7356b0e47805f35c654c875` |

The validator reported no stream-task errors, command failures, artifact
generation errors, restore errors, or deferred restore.

## Unified-log review

The bounded `14:49–14:54 UTC` review found no blocking runtime defect. The GCS
recorded 1,441 `DEBUG`, 120 `INFO`, two `WARNING`, and zero `ERROR` events.
The correlated API window contained 1,121 HTTP 200 responses and six HTTP 202
responses with no 4xx or 5xx response. All six command IDs were present from
submission through their expected execution or override result. There was no
PX4 preflight rejection, failsafe, command transport failure, or flight-action
failure.

The two GCS warnings mark the long-running Smart Swarm controllers as failed
when the later jog/HOLD commands intentionally superseded them. Node execution
logs prove an orderly recovery stop and result report, so this is lifecycle
status debt rather than a controller failure. Three additional non-blocking
observability items remain:

- the follower emitted 215 `Leader sample gap` warnings because the telemetry
  sequence advances faster than the 15 Hz stream; tracking remained fresh and
  passed, so the current message does not prove packet loss;
- the telemetry-origin fallback succeeded, but the unavailable first origin
  source was still logged at `ERROR`; and
- deliberate H2 formation staging changed the launch-slot detector result,
  producing an expected but potentially confusing position-ID warning.

The follower also suspended one initial non-finite own-state sample, acquired
state lock in `0.135 s`, and completed stable capture in `1.158 s`. This is the
intended fail-closed startup behavior. Both complete PX4 ULogs were preserved
before container removal:

| Vehicle | ULog size | SHA-256 |
|---------|-----------|---------|
| H1 | 17,379,847 bytes | `046844bb8e9ff7f978860ab6612ba4e7fd99b4fae4f7d45178545c0d04523f82` |
| H2 | 17,438,353 bytes | `1d0db63dae6329ea78c6135c98b3fdc11f9b615fdaa337a204e1ae367b84b504` |

The root-only evidence package includes the validator artifacts, GCS and node
unified logs, both ULogs, an online SQLite command-journal backup, provenance,
and cleanup/restore evidence. Its 57-entry manifest SHA-256 is
`3120b2335f0638d0637d0ca8dd86f04cac6e2325a4f3e05e83cc2af68de84f24`;
the compressed archive SHA-256 is
`5602b42056cd67f00a66db42754f3b1017777e219bd6714c657aca7b5c53a948`.

## Runtime restoration and cleanup

Cleanup occurred only after independent proof of zero active commands, both
vehicles disarmed/idle within the ground-altitude gate, and exact saved swarm
configuration restoration. The typed SITL lifecycle API reported `Removed 2`.
The empty dedicated Docker network was then removed, all three temporary
validation credentials were revoked and their plaintext files deleted, and the
GCS was restarted using the verified prebuilt dashboard in `REAL` mode.

Post-restore checks proved API and dashboard HTTP 200, process and configured
mode `real`, zero active real commands, zero SITL containers, no SITL network,
an exact clean downstream checkout, and byte-identical restoration of the
baseline GCS environment file. The build-only dashboard dependency tree was
removed after service acceptance, recovering about 1.1 GB without touching the
final static build, virtual environment, command journals, evidence, rollback
artifacts, or the single SITL image and its tag aliases.

## MAVLink and mobile-data boundary

This SITL run validates mission/control behavior, not cellular data usage. On
real nodes, the HTTP/control-plane `--gcs-ip` setting no longer creates a
full-rate MAVLink push route by itself. A continuous remote stream requires an
explicit `--mavlink-push-endpoint HOST:PORT` or an explicitly managed endpoint
profile. The local SITL bridge remains enabled by design. See
[MAVLink routing setup](../guides/mavlink-routing-setup.md).

The suspected field data-use issue is therefore addressed at the configuration
boundary, but it is not closed by this rehearsal. Record before/after interface
counters during the next field window and verify that no unneeded explicit
remote endpoint is active.

## Required field gates

### Post-rehearsal policy hardening — 2026-08-14

The accepted flight trace exposed several operator-policy boundaries that are
now explicit in the release candidate:

- the `0.5 m` grounded/home-relative boundary, launch battery reserve, PX4
  armability/global/home checks, and Smart Swarm capture/motion limits are not
  relaxed. The field's earlier `~0.8 m` rejection was correct evidence of an
  unsettled altitude estimate, not a reason to accept a wider ground state;
- launch prepare/commit reuses one typed readiness observation only within its
  identity-bound, policy-bound, maximum two-second evidence lease. A delayed
  commit re-probes and fails closed, while an immediate commit no longer makes
  the redundant second probe that timed out during the field session;
- Smart Swarm has one dashboard start surface, unavailable targets block Start,
  and the command monitor presents bounded per-aircraft preparation, delivery,
  and execution reasons rather than only `all reachable failed`;
- cooperative Smart Swarm cancellation stops setpoint producers, exits
  Offboard, and requests Hold before the controller process exits. Dedicated
  Hold/Land/RTL remains the clearest field recovery path; and
- the reviewed autonomous field profile uses a one-second Offboard-loss delay
  and RTL. The profile's existing RC-loss exemptions remain a separate
  operator policy and must not be bulk-applied merely to change the timeout.

The focused release-candidate validation passed 53 dashboard tests and 422
backend/runtime/profile tests with one environment skip. The cooperative
shutdown test sends a real SIGTERM to a subprocess and proves the ordered
`setpoints stopped → Offboard stopped → Hold requested` handoff. The full
two-drone SITL scenario below remains the accepted motion/recovery rehearsal;
the release candidate must repeat its bounded SITL acceptance after deployment
because the cancellation runtime changed afterward.

Before paired real-aircraft Smart Swarm flight:

- inspect both airframes, power systems, temperatures, propellers, RC/manual
  takeover, PX4 modes, geofence, RTL/land behavior, and failsafes;
- require current GCS/QGC/node connectivity and no unresolved sync warning;
- require stable PX4 readiness on each aircraft, including GNSS/RTK, home,
  local/vertical position, and the absence of active preflight blockers;
- while grounded and disarmed, read and record each aircraft's
  `COM_OF_LOSS_T`, `COM_OBL_RC_ACT`, `COM_RCL_EXCEPT`, `COM_RC_OVERRIDE`, and
  `COM_ARM_WO_GPS`. The reviewed repo profile uses a one-second Offboard-loss
  delay followed by RTL, but it is not active until a deliberate diff/apply and
  verified readback prove that it is;
- stop if position or altitude estimates drift, a readiness gate flaps, the
  router overheats, or the control network is unstable;
- repeat Take Off/HOLD/LAND with one aircraft at a time and review its
  return-position behavior. Do not treat paired Take Off as atomic: each node
  repeats final admission, so confirm H1 terminal and stable Hold before H2;
- physically stage H2 approximately 6 m north of H1 with deliberate collision
  separation before paired takeoff; verify the saved NED topology in the UI;
- start only from `Swarm Design` → `Smart Swarm Runtime` with `Selected
  Cluster`, and confirm the dialog names exactly H1 and H2. Do not use the
  generic mission picker or tactical-map shortcut for this first run;
- keep a trained operator ready for immediate HOLD, LAND, RTL, or manual
  takeover, and keep the first leader movement small;
- compare both PX4 ULogs and MDS command/unified logs after the run; and
- measure real-node network traffic before treating the mobile-data concern as
  resolved.

Any failed or ambiguous gate is a no-go. Field evidence, not this SITL PASS,
decides whether the next phase can close.

## Release boundary

The original accepted rehearsal used the pinned image and exact synchronized
runtime recorded above. Subsequent cancellation and Offboard-loss hardening
changes the runtime/profile checkpoint, so its release must use the normal
image/package workflow before a public image is described as containing those
changes. Production nodes may receive the exact release through the documented
startup sync path, but that does not relabel an older image.

Related sources:

- [Two-drone Smart Swarm field rehearsal](../guides/smart-swarm-tracking-analysis.md)
- [Smart Swarm operator guide](../features/smart-swarm.md)
- [SITL comprehensive guide](../guides/sitl-comprehensive.md)
- [Unified logging guide](../guides/logging-system.md)

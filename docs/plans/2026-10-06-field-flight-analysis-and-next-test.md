# October 4 flight: measured tracking and next-test handoff

Analysis date: October 6, 2026. Offline work ran on Hetzner. No aircraft was
commanded, restarted, or reconfigured during this analysis.

## What was reviewed

Both complete PX4 logs were retrieved on October 5, not merely the earlier
partial downloads. The verified originals remain under
`/root/mds-evidence/field-20261005-retrieval/`:

- Drone 1, log 134: 197,774,255 raw bytes;
  SHA-256 `b0425b82cad7477b791b5f803ec695e1c4e9e3727a9285133e326bd412e4a48f`.
- Drone 2, log 83: 191,521,637 raw bytes;
  SHA-256 `21402105185fe77d28af40bf66cc420e887ef21077041b11f89df24e43de4f00`.

The small MDS/GCS sessions, service journals, parameter and configuration
snapshots are under
`/mnt/HC_Volume_106468352/mds-evidence/field-20261004-flight/`.
Both ULogs parse without reported corruption or logger dropouts, and contain
local/global position, GNSS, commands, setpoints, multiple EKF instances and
pre-arm evidence. This is substantially better coverage than the September
navigation-blind logs. It does not establish sensor ground truth.

Derived evidence is under
`/root/mds-evidence/field-20261005-retrieval/analysis-20261006/`:

- `drone{1,2}-inventory.json`, `drone{1,2}-selected-topics.npz`
- `control.csv`, `aligned-analysis.csv`, `metrics.json`, `deep-metrics.json`
- `delivery-and-response.json`
- `formation-and-timing.png`, `close-approach.png`
- `command-delivery-and-response.png`, `navigation-preflight.png`

The October 4 video was not independently reviewed in this pass: its latest
link/file was not present in the retrieved evidence. Do not substitute the
older September video or claim a specific filmed moment was synchronized.

## Alignment and measurement boundaries

Align aircraft boot clocks using each recorded GNSS UTC timeline, not the
ULog header's boot UTC. Drone 2's header boot UTC is inconsistent with GNSS.
The MDS-to-GNSS alignment uses the logged leader boot timestamp and source age;
its median offset is approximately 106 ms. Local follower positions and
velocities independently agree with the corresponding aligned PX4 samples.
GPS timestamp/publication offsets and logging cadence limit sub-100-ms timing
precision. Delay fits below are waveform comparisons, not additive pure
network delays or exact identified flight dynamics.

Compare independently fused global positions in a common tangent plane and
MSL altitudes. Do not subtract incompatible local-origin heights or align
aircraft altitude by overwriting either EKF. Estimated inter-drone distances
are not surveyed physical clearance, especially without RTK.

## Results

The main comparison excludes initial acquisition (first 15 seconds) and ends
at the leader's first RTL transition. These boundaries matter: initial
acquisition and subsequent recovery are different workflows.

| Measurement | Result |
| --- | --- |
| Pilot-flight median horizontal separation | 5.99 m for a 6 m north target |
| Pilot-flight minimum estimated separation | 4.49 m |
| Horizontal formation error, median / p95 | 0.44 / 2.00 m |
| Absolute MSL altitude difference, median / p95 | 0.21 / 0.49 m |
| Largest pilot-flight absolute altitude difference | 1.40 m |
| Leader source age used by control, median / p95 / maximum | 56 / 182 / 750 ms, full command session |
| Follower source age, median / p95 / maximum | 34 / 64 / 70 ms |
| Command-loop interval, median / p95 / maximum | 76 / 82 / 96 ms |
| MDS send-call duration, median / p95 / maximum | 2 / 5 / 16 ms |

There are 3,215 logged follower commands and 3,459 applied leader samples.
There is no stale-leader Hold/recovery event or automatic role promotion in
this session. Brief data-age spikes remain; their presence is not proof of
radio packet loss. Stream sequence gaps also cannot alone establish packet
loss because sequence increments and stream publication have different rates.
The available service journal does not establish the continuously used peer
route. Do not attribute this flight to a 4G relay without that evidence.

The initial formation error was approximately 7.94 m. Acquisition became
tracking after approximately 6.5 seconds. The controller was acquiring the
configured formation, not ignoring the follower or rejecting its distance.

### Where the remaining lag lives

Layer-by-layer horizontal velocity fits during motion give:

- MDS shaped command to PX4 recorded trajectory: about **50 ms**.
- Recorded trajectory to PX4 local controller setpoint: about **20 ms**.
- PX4 local setpoint to measured aircraft velocity: about **710 ms**.
- Raw MDS request to shaped command: approximately **250 ms**, a separate
  comparison with different waveforms; do not add these fits as pure delays.

The close-approach plot shows fresh data and MDS braking/reversal commands
arriving before the follower completes braking. The dominant remaining
response lag is downstream of the received setpoint, not a missing command
or a demonstrated EKF reset. The follower's attitude error is median 1.37°,
p95 3.70°; maximum estimated tilt is 22.27° against a configured 45° limit.
That does not establish absence of all actuator/thrust constraints.

A simple held-out first-order response fit gives about 0.65 s time constant
and 0.15 s dead time, with 0.24 m/s² held-out acceleration RMS residual. It is
a useful description of this flight, not a validated F550 model or proof that
a proposed new gain is stable. The trajectory has no finite position or
acceleration references during following: this was velocity-only Offboard
control, not the former position-plus-velocity speed-contract bug.

### Recovery is a separate operational finding

Approximate MDS-aligned UTC timeline:

- 17:44:52.98: drone 1 enters RTL.
- 17:44:53.96: its Smart Swarm process exits, preserving external PX4 control.
- 17:44:58.61: estimated horizontal separation reaches **2.81 m**, with
  follower altitude approximately 1.72 m below the leader.
- 17:45:18.54: drone 2 enters RTL, **25.56 seconds later**.
- 17:45:19.36: follower shutdown preserves its own RTL, without switching it
  back to Offboard or Hold.

The leader briefly returned to Position between its two RTL entries. The
follower continued following fresh leader motion during that interval. GCS
evidence contains the two takeoffs and Start Smart Swarm; no Stop Swarm
dispatch is recorded before recovery. Radio RTL on one aircraft is therefore
not equivalent to stopping the entire swarm. This is not evidence that an
MDS Stop command was sent and ignored.

For planned recovery, stop the selected swarm and confirm follower Hold before
initiating the aircraft recoveries, with the pilot maintaining separation and
independent takeover. An emergency pilot action must not wait for a dashboard
acknowledgement. Simultaneous RTL is not collision avoidance.

Drone 2's battery reached the configured critical level before its RTL and
emergency level during return. Plan recovery with reserve for RTL climb,
translation and landing; do not use critical battery as the planned end of
the demonstration. An automatic battery action may interrupt a coordinated
sequence, so preserve it rather than weakening it for synchronization.

Proposed systemic change, **not implemented**: an explicit leader RTL/Land
transition pauses downstream followers in Hold with no automatic rejoin.
Preserve each follower's own pilot takeover/failsafes and saved assignment.
Leader Position/manual steering remains allowed. This needs operator policy
confirmation and takeover/cascade/leader-change regression before deployment.

## Navigation and RTK

Both logged GNSS receivers stayed at fix type **4 (DGPS)** during following;
neither recorded RTK float/fixed (5/6). Logged RTCM injection rate was zero.
A connected QGC RTK base does not establish rover RTK convergence; a zero
reported injection rate alone does not identify the broken forwarding layer.
Check correction delivery and fix state on each rover before a precision demo.

The pre-arm warnings are genuine PX4 evidence: horizontal GNSS drift, PDOP,
speed accuracy, strong magnetic interference and heading instability. Across
early ground capture, primary-EKF horizontal drift reached approximately
0.144 / 0.163 m/s; the configured check is 0.1 m/s. During the last 60 seconds
before arming, both primary GNSS checks passed continuously, and maximum
horizontal drift was only 0.0108 / 0.0145 m/s. This flight does not justify
relaxing the drift threshold to get past a continuing fault.

During pilot following, recorded primary velocity/position/height innovation
test ratios remained low, fault flags were zero, and local/global position
reset counters did not change. Heading is less settled evidence: drone 2's
primary heading test ratio is non-finite and its magnetometer fusion flags
are not active during this window. Do not turn missing heading metrics into
a claim of healthy magnetometer fusion. Investigate magnetometer selection,
orientation/calibration and fusion behavior before more demanding body turns.

Use a stationary open-sky startup away from vehicles, reinforced surfaces and
magnetic sources; inspect external compass orientation, wiring and placement.
If a persistent warning remains, capture that interval and compare the two
magnetometers/fusion flags rather than recalibrating repeatedly in the same
disturbed location or disabling checks. The logs do not localize interference
to one ESC or prove jamming, spoofing, or a receiver fault. See
[PX4 compass guidance](https://docs.px4.io/v1.17/en/config/compass) and
[EKF GNSS checks](https://docs.px4.io/v1.17/en/advanced_config/tuning_the_ecl_ekf).

## Tuning and implementation boundary

Retain the deployed responsive MDS profile: **6 m/s horizontal, 1.25 m/s
vertical, 4 m/s² acceleration, 8 m/s³ jerk**, position gain 0.5, velocity gain
0.35, velocity feed-forward 1, filter 0.35 s and existing deadbands. Its speed
ceiling already exceeds the observed leader demand; another increase does
not fix the measured downstream response delay. Preserve bounded stale-data
Hold/recovery and disabled automatic leader promotion.

Next tuning trial for a qualified airframe operator: compare horizontal PX4
velocity response at `MPC_XY_VEL_P_ACC=1.8` against a modest **2.2** candidate,
holding I=0.4 and D=0.2 unchanged. This is a proposed trial, **not an applied
or field-validated setting**. Check isolated low-speed starts, stops, hover,
reversal and oscillation before paired flight; roll back if response worsens.
Do not change EKF noise/gates, attitude gains or notch frequencies at the same
time. The evidence points to the velocity-response layer; actual gain stability
must be established on the aircraft. See
[PX4 velocity controller](https://docs.px4.io/v1.17/en/flight_stack/controller_diagrams).

Future MDS option: feed the bounded shaper's own acceleration along with its
velocity to PX4, rather than differentiating noisy leader measurements. PX4
supports velocity/acceleration feed-forward, but this needs finite-value,
frame, stale-data, takeover and SITL validation; it is not a cosmetic gain
change or part of this release. See
[PX4 Offboard inputs](https://docs.px4.io/v1.17/en/flight_modes/offboard).

Implemented here: a logging-only **Routine Flight Logging** repository profile
(`SDLOG_PROFILE=1`, `SDLOG_MODE=0`), restoration guidance and loader regressions.
Six profile tests passed on Hetzner in an isolated temporary validation root;
the live client checkout was not modified. No API contract or dashboard build
changes are needed for profile discovery. Routine mode excludes powered
pre-arm waiting and profile 1 excludes the extra system-identification stream.
It preserves default flight topics; actual size and coverage remain
firmware/duration dependent.

Aircraft application remains required while grounded/disarmed, with parameter
snapshot, readback and restart before the next flight. Earlier restoration
already returned mode to 0, but profile 9 still requires restoring to 1.
There is no new PX4 gain, estimator, failsafe or arming-check deployment here.

## Focused follow-ups, not extra normal-operation gates

- Decide and validate leader RTL/Land follower-pause semantics; keep manual
  leader steering and existing explicit leader changes compatible.
- Verify per-rover RTCM delivery and RTK fix; do not infer it from the base UI.
- Review heading fusion and physical compass behavior before body-frame yaw.
- Test any velocity-response gain change independently, then paired gentle
  translation/braking, then slow body yaw and small offset changes.
- Fix raw-download retention: active transfers are protected, but `expires_at`
  currently starts at job creation and is not refreshed at `ready`; a transfer
  longer than its TTL can disappear immediately after completion. Start ready
  file retention at successful completion and regression-test expiry/leases.
  Transfer timeout and retention are distinct; do not permanently increase all
  limits to conceal this defect. This runtime fix is deferred, not applied.
- Bound periodic control/stream scheduling with monotonic deadlines when
  implementing the next response change. Current 76 ms cadence is not a
  demonstrated multi-second stall and not the primary lag cause.
- LED fallback and gRPC shutdown errors are logged outside tracking; preserve
  actionable failures while avoiding scary expected-shutdown error presentation.
- Keep recovery UX concise but explicit about scope: one aircraft in RTL does
  not establish that its followers have stopped. Show the leader/follower
  execution states together, without adding a second competing stop policy.

## Phase handoff

Official working branch: `main`, base HEAD `f4a2db82`; these changes are local
and uncommitted. Captured live client checkout: `main` at
`fcb3fb39507b99f95740ee9d93fdb935fd1ce270`, clean during inspection.
Unrelated existing documentation edits were preserved. No tag, release image,
client checkout update, aircraft update, or public artifact was produced.
Analysis and the logging-profile regression are complete; aircraft logging
restoration, operator recovery-policy choice and any new gain trial are still
required follow-ups before claiming those changes are deployed.

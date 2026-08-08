# Field Flight-Mode, Altitude Truth, and GNSS Readiness Checkpoint

**Date:** 2026-08-08

**Scope:** Catch-A-Drone two-node real-aircraft deployment

**Status:** software handoff ready for a controlled field retest; props-on
flight remains blocked until the GNSS/estimator gate below passes

This checkpoint closes the August 8 software investigation without mixing it
with optional Simurgh work or the later MDS modernization plan. It records what
MDS now proves, what the live aircraft disproved, and the exact order for the
next field session.

## Executive verdict

- The Mission/Hold/Unknown mode flicker was an MDS telemetry-ownership and PX4
  decode defect. It is fixed, regression-tested, and live-verified.
- The tracked Take Off path is working. One bounded Drone 1 request reached
  command-bound preparation and was stopped before dispatch because the
  aircraft was not launch-ready.
- The former `REL ~60 m` ground display was not height above launch. PX4 had no
  authoritative home, and a pre-home MAVLink value was being labelled as
  relative altitude. MDS now rejects that value across node, swarm, GCS legacy
  normalization, distance-to-home, and cached airborne admission.
- The recurring `Preflight: GPS Horizontal Pos Drift too high` is real PX4
  estimator evidence, not a QGroundControl rendering problem. Rebooting the
  flight controllers did not clear it. No PX4 safety check or GNSS parameter
  was weakened.
- Software is ready for the controlled retest described here. This is not
  approval to fly while the drift warning, invalid home, or Drone 1 battery
  concern remains.

## Flight-mode root cause and acceptance

PX4 `HEARTBEAT.custom_mode` is a packed union: the main mode is bits 16–23 and
the submode is bits 24–31. MDS had decoded the bytes in the opposite order.
The routed MAVLink stream also contained QGroundControl/companion heartbeats,
which could overwrite flight-controller mode, arming, system state, and
freshness.

The correction provides one shared PX4 decoder and lets only a heartbeat whose
MAVLink type/autopilot classify it as a flight controller own vehicle state.
Obsolete duplicate mappings and synthetic armed-mode fallbacks were removed.

Evidence:

- `67371008` (`0x04040000`) decodes to PX4 Auto Mission.
- `50593792` (`0x03040000`) decodes to PX4 Auto Hold.
- Official mode correction commit: `6c05b7af5e453582f0a59e35c51e91ee2ce090d3`.
- Private mode correction commit: `20c0499781d8fd186c42d10d747f243fdc78c309`.
- Both official and private quality gates completed successfully.
- After the private deployment, 48 consecutive direct samples per node all
  reported Mission (`67371008`, base mode `29`) with no foreign
  `custom_mode=0/base_mode=192` overwrite.

## Altitude and home truth

Live post-reboot telemetry showed both drones disarmed on the ground with
`home_position_set=false`, while the old node payload labelled approximately
60–70 m as `relative_home`. That value tracked absolute site altitude and was
not usable height above launch.

The invariant is now explicit:

1. `relative_home` is valid only when PX4 has authoritatively published home.
2. Before then, `relative_altitude_m` is null and the relative source is
   invalid, even if `GLOBAL_POSITION_INT.relative_alt` contains a number.
3. Display falls through to a source-labelled local NED, barometric, or MSL
   value.
4. Distance-to-home requires both a valid current global position and PX4
   home; the companion's fallback cache is never presented as home truth.
5. Cached Hold and Precision Move admission fails closed without home. Their
   action process still performs its independent, connection-bound MAVSDK
   safety observation.
6. GCS applies the same rule when normalizing older node payloads.

This is a frame/authority rule, not a heuristic for the observed 60 m value.
Focused node, GCS, command, and MAVLink suites passed 251 tests, including
home-true compatibility and false-home legacy reconstruction.

## Tracked Take Off proof

With Arnaude's current props-off confirmation, Drone 1 disarmed/idle, and zero
active commands, one request was submitted:

- command ID: `0a7ee617-c45c-4494-bbe3-b3e0ad24ea24`
- mission: Take Off to 1 m
- target: hardware 1 only
- GCS receipt: HTTP 202, new non-replayed tracker
- preparation: one target blocked/not ready
- flight ACKs: 0
- expected executions: 0
- terminal result: failed — launch not dispatched under the all-required policy
- postcondition: zero active commands; Drone 1 disarmed, scheduler idle, Mission
  mode stable

This proves request validation, durable idempotency/tracking, target-specific
preparation, fail-closed reporting, and terminal cleanup. It deliberately does
not prove arming, climb, Hold transition, landing, or flight readiness.

## Dual-GNSS and estimator evidence

Both nodes reported the same current parameters:

- `GPS_1_CONFIG=201`
- `GPS_2_CONFIG=202`
- `SENS_GPS_MASK=7`
- `SENS_GPS_PRIME=0`
- `SENS_GPS_TAU=10.0`
- `EKF2_GPS_CHECK=2047`
- `EKF2_REQ_HDRIFT=0.1 m/s`
- `EKF2_REQ_VDRIFT=0.2 m/s`

Mask 7 enables weighting by speed, horizontal-position, and vertical-position
accuracy. While blending is active, `SENS_GPS_PRIME=0` does not give GPS1
priority. PX4 blending is implemented, but it works best when both receivers
publish at the same rate and provide comparable accuracy metrics. A many-
satellite fix or active RTCM link is not the same as per-rover RTK Fixed or an
estimator-approved global/home solution.

Primary references: [PX4 GNSS setup](https://docs.px4.io/main/en/gps_compass/),
[PX4 EKF dual-receiver guidance](https://docs.px4.io/main/en/advanced_config/tuning_the_ecl_ekf#dual-receivers),
and the [PX4 parameter reference](https://docs.px4.io/main/en/advanced_config/parameter_reference#SENS_GPS_MASK).

After an FC reboot, both physically stationary drones still moved roughly
4.6–4.7 m horizontally in sampled telemetry and produced new horizontal-drift
warnings. MDS observed DGPS/3D fix types rather than RTK Float/Fixed. The
current apartment/window setup is therefore unsuitable for arm or flight
acceptance and cannot determine whether the field cause is multipath,
interference, receiver accuracy mismatch, RTCM state, mounting/offset, or
another estimator input.

## Required next field sequence

Arnaude should use this exact progression:

1. Charge and verify both batteries. Resolve the prior Drone 1 low, critical,
   and emergency battery evidence before props-on flight.
2. Start outdoors at the final launch positions with props removed, RC links
   available, RTK/QGC/GCS connected, and both GPS receivers installed.
3. Do not move the aircraft after boot. Confirm each rover itself reports RTK
   Fixed, PX4 home is valid, home-relative altitude is near zero, and the drift
   warning remains absent for at least 60 seconds.
4. Save the parameter snapshot and ULog as baseline A (dual receiver/blending).
5. Power the aircraft fully off. Never hot-unplug a GNSS receiver.
6. Disconnect the regular backup GPS2, leave the F9P/GPS1 installed, reboot at
   the same positions, repeat the same stationary gate, and save baseline B.
7. Compare per-receiver rate, fix, correction age, `s_variance_m_s`, `eph`,
   `epv`, blend/selection status, and EKF check/innovation evidence before
   changing `SENS_GPS_MASK`, `SENS_GPS_PRIME`, or an EKF threshold.
8. If the gate is clean, run Arm/Disarm Ground Test once, then one exact Take
   Off on one drone and monitor its single tracker to terminal state.
9. Proceed to a one-drone props-on flight under direct field/RC control. Test
   the two-drone launch and Smart Swarm only after the one-drone result is
   clean. Use RTL/Land/manual takeover according to the field safety plan.

Any new GPS-drift warning, missing home, implausible relative altitude,
preflight failure, stale link, battery warning, or nonterminal command returns
the test to no-go. Do not compensate by repeating commands or loosening PX4
checks.

## Landing-quality boundary

No landing parameter is changed in this checkpoint. Existing ULogs show one
harder Drone 1 touchdown but not a repeatable fleet-wide landing-control defect,
and no downward range sensor was configured. The current evidence supports
resolving Drone 1 battery health first and collecting a controlled field log
with descent setpoints/range/land-detector evidence before considering a small
`MPC_LAND_SPEED` trial. See the landing section in the
[August 4 field checkpoint](2026-08-04-field-node-sync-recovery-and-props-off-gate.md#landing-quality-boundary).

## Deferred, bounded follow-ups

These are recorded rather than expanded into tonight's release:

- invalidate cached home/reference fields immediately on a detected PX4 boot
  clock epoch change;
- subscribe the existing barometric helper to the intended MAVLink pressure
  message;
- add dashboard defense-in-depth against contradictory third-party telemetry;
- expose per-receiver GPS2 and estimator check evidence directly in the normal
  diagnostic API.

The current action-authoritative MAVSDK snapshot and launch home/readiness gate
remain fail-closed, so these do not justify delaying the controlled retest.

## Release record

The authoritative release objects are:

- official: `v5.5.117-field-mode-altitude-gnss-readiness`
- Catch-A-Drone private: `cad-v5.5.117-field-mode-altitude-gnss-readiness`

Both tags must be created only after their exact commits pass CI. Production
GCS and both nodes must then be clean on the private tagged commit, with the GCS
using the matching verified private dashboard artifact. The release handoff
records the final peeled commits, CI runs, artifact checksum, deployment
health, node convergence, and rollback asset.

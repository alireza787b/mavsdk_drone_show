# Responsive Smart Swarm flight preparation

## What changes, and what does not

The opt-in [motion profile](../../deployment/examples/smart-swarm-responsive.env)
is a candidate for smoother, more responsive follower motion: 6 m/s horizontal,
1.25 m/s vertical, 4 m/s² acceleration, 8 m/s³ jerk. Stock remains 5 / 0.75 / 1 / 2.
Position gain 0.5, velocity damping 0.35, filtering 0.35 s, deadbands, prediction,
saved roles and Hold/recovery remain unchanged. There is no calibration bypass,
new normal-flight UI gate, automatic leader promotion or collision avoidance.

The dashboard may show `READY · CAUTION` for an armable vehicle carrying a PX4
advisory warning. This is an operator-facing status distinction only. A PX4
`Preflight Fail`, estimator failure, heading failure, stale/unknown link, or
other blocker remains `NOT READY`; the responsive profile does not override
those checks.

Increasing jerk makes acceleration respond sooner; increasing acceleration
shortens the subsequent braking ramp. Neither fixes missing leader data, and
neither guarantees that the aircraft immediately follows the requested velocity.
PX4 trajectory settings are not interchangeable with MDS Offboard shaping limits.

## Compare before enabling

All builds and live validation run on the designated validation host. The
offline comparison uses the production controller with a synthetic first-order
velocity plant, not an identified airframe or replayed physical trajectory:

```bash
venv/bin/python3 tools/compare_smart_swarm_motion_profiles.py --output-dir /path/to/evidence/model
```

The tool compares 1/3/5 m/s translation, stops, reversal, vertical motion, noisy
hover, NED/body offsets and 80/300 ms delayed samples. It records error,
separation, hover speed and commanded braking. A failing result remains a
failing result: do not loosen its thresholds or label it flight-ready.

The initial 2026-10-02 **3 m/s² / 6 m/s³** synthetic comparison passed all faster-braking and
lower-RMS checks. However, at 5 m/s with 300 ms delayed samples it fell below
the comparison's 2 m separation floor (NED 1.52 m; body 1.72 m) and exceeded
the final 0.05 m/s hover criterion. This is a model sensitivity result, not a
measured F550 separation or an operational collision guarantee. The candidate
was not cleared for that maneuver/delay combination. The revised 4 / 8
candidate passed those same model checks with unchanged gains. It remains
opt-in pending measured PX4 SITL and actual-airframe validation; a synthetic
pass is not evidence of an operational separation guarantee.

For the live two-drone rehearsal, first require reconciled SITL and isolated
configuration. The existing tool accepts explicit leader jog speed:

```bash
venv/bin/python3 tools/analyze_smart_swarm_tracking.py \
  --base-url http://127.0.0.1:5036 --jog-speed-m-s 3 --jog-north-m 25 \
  --max-smart-swarm-velocity 6.1 --output-dir /path/to/evidence/sitl
```

Repeat at 1 and 5 m/s and inspect measured leader speed; a requested jog speed
is not proof it was achieved. Validate cancellation, RTL, pilot takeover and
formation restoration separately. Preserve adequate maneuver/braking space;
a fixed offset does not ensure separation during transient tracking error.

The first PX4 SITL rehearsal exposed an existing Precision Move speed-contract
defect: its final position target plus velocity feed-forward exceeded the jog
request (approximately 11 m/s for a 3 m/s request over 25 m). Do not use long
jogs from the affected revisions as controlled-speed validation or field maneuvers.
The corrected runner uses bounded, acceleration/jerk-shaped velocity-only
translation; only the initial hold seed uses a position reference. Its
requested speed bounds the full 3D command magnitude, with a separate vertical
cap. Arrival requires low commanded and measured speed as well as position/yaw
tolerance. Precision Move uses 2 m/s² acceleration, 4 m/s³ jerk and 1.25 m/s
vertical ceiling, independently of the follower profile.
The outer approach uses position gain 0.5 and measured-velocity damping 0.35,
so it begins braking before arrival rather than merely capping cruise speed.
The rehearsal waits
for both role acknowledgements and rejects
overspeed measurements rather than confusing command completion with tracking
acceptance. See the [evidence checkpoint](../plans/2026-10-02-responsive-swarm-evidence-and-rollout.md).
The subsequent correction and measured results are in the
[Precision Move validation checkpoint](../plans/2026-10-02-precision-move-speed-fix-and-responsive-validation.md).

## Navigation diagnostics, not shared sensor calibration

The reviewed field logs used `SDLOG_PROFILE=8`, which omitted navigation/EKF
topics. The existing PX4 parameter page now offers **Navigation Diagnostics**:
`SDLOG_PROFILE=9`, `SDLOG_MODE=2`. This changes logging only. Review against the
actual firmware, snapshot existing values, check SD space, apply while grounded,
restart and verify a boot ULog really contains local/global position, GNSS,
estimator status/innovations, setpoints, mode/commands and sensor data. The
default set may not include every diagnostic topic on every firmware: explicitly
capture missing check-status topics using that firmware's supported mechanism.
After the diagnostic session restore `SDLOG_MODE=0`; retain 9, or use the lean
default profile 1 after review, rather than returning to navigation-blind 8.

Stationary GNSS drift/heading warnings require a stationary outdoor capture:
per-rover fix and correction status, receiver selection/blending, GNSS reported
accuracy/velocity, estimator check flags, innovations, resets, compass consistency
and sensor temperature. Inspect antenna/compass mounting, measured GNSS lever
arms, nearby metal, multipath and wiring. Do not infer EMI from distance alone.

Use available high-rate inertial data to check vibration/clipping and measured
spectral peaks before any notch/filter change. F550, 2212/920KV motors, 4S and
1047 props do not specify actual RPM or a notch frequency. A motor vibration
filter cannot explain a motors-off stationary GNSS warning by itself.

Do not overwrite PX4 altitude or fuse positions across aircraft to make a gate
pass. Distinguish home-relative, local-origin and MSL altitude; compare compatible
references and handle resets before attributing cross-drone bias. Same-ground
height alignment is deferred pending evidence. Preserve PX4 navigation/heading
checks; remove only demonstrated duplicate/stale MDS restrictions. Do not apply
the broader field-baseline parameter profile merely to enable logging.

## Link evidence and grounded rollout

Sample age is not pure link latency. Record clock synchronization, source and
receipt timing, Wi-Fi signal/retries, NetBird's actual peer route, temperature
and throttling. A listed relay is not proof it is used. Prefer direct aircraft
peer traffic on the local network when available; do not promise perfect sync
from a new router or professional radio.

Before enabling the candidate on aircraft: verify both code revisions, identity,
saved leader/follower/offset, loaded motion policy and logging readback. Merge
only the four profile keys into existing local environment files; never replace
identity, routing or secrets. Confirm identical effective settings after restart.
Keep the original values for rollback. The aircraft must be grounded; this step
is not performed by an offline code release or a Git boot sync.

Field progression: individual takeoff/landing; gentle paired NED following and
stops; faster translation only after evidence review; then slow body yaw, combined
motion, and small offset changes. If 5 m/s/delay tests fail, retain the deployed
profile and report the failed envelope rather than increasing gains blindly.

References: [PX4 logging](https://docs.px4.io/main/en/advanced_config/parameter_reference#SDLOG_PROFILE),
[EKF guidance](https://docs.px4.io/main/en/advanced_config/tuning_the_ecl_ekf),
[filter tuning](https://docs.px4.io/v1.16/en/config_mc/filter_tuning).

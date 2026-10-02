# Precision Move correction and responsive follower validation

## Implemented correction

Precision Move previously sent a distant final position target together with
bounded velocity feed-forward. PX4 adds position-loop correction to feed-forward,
so requested jog speed did not bound the combined command. See
[PX4 Offboard](https://docs.px4.io/main/en/flight_modes/offboard) and
[MAVSDK Offboard](https://mavsdk.mavlink.io/main/en/cpp/guide/offboard.html).

Translation now uses one outer position-to-velocity approach law and
`set_velocity_ned`, with no final position target supplied to PX4 in parallel.
Only the initial current-position hold seed uses a position reference.
The shared NED shaper adds an optional total-speed sphere (disabled for the
existing follower), so diagonal moves respect the jog's full 3D command-speed
budget as well as vertical, acceleration and jerk bounds. This reuses the
existing braking-reserve and continuity logic rather than clipping a command
after shaping or lowering aircraft-wide PX4 maximum speed.

The approach uses a damped outer loop (position gain 0.5, measured-velocity
damping 0.35), followed by the speed/acceleration/jerk shaper. This begins braking
before arrival, rather than capping only cruise speed. The approach speed falls
continuously to zero near the target; removed the
old 0.2 m/s minimum that could push through small targets. Completion requires
low commanded and measured local speed, position/yaw tolerance and the existing
settle interval, followed by PX4 Hold. Cancellation now explicitly stops the
runner's Offboard control. Precision Move limits are exposed in the existing
policy API; no additional normal-flight UI gate or confirmation is introduced.

Precision Move remains separate from Smart Swarm tuning: maximum requested
command speed 5 m/s, vertical ceiling 1.25 m/s, acceleration 2 m/s², jerk
4 m/s³, arrival speed threshold 0.1 m/s. Its slower reference maneuvers leave
follower catch-up/braking headroom. These bound commands, not exact physical
speed or stopping distance when the aircraft is already moving.

## Recommended responsive follower candidate

| Parameter | Stock unchanged | Revised candidate |
|---|---:|---:|
| Horizontal ceiling | 5 m/s | 6 m/s |
| Vertical ceiling | 0.75 m/s | 1.25 m/s |
| Acceleration magnitude | 1 m/s² | 4 m/s² |
| Jerk magnitude | 2 m/s³ | 8 m/s³ |
| Position gain | 0.5 | 0.5 |
| Velocity damping gain | 0.35 | 0.35 |
| Position filter time constant | 0.35 s | 0.35 s |

Velocity feed-forward remains 1.0; horizontal/vertical position deadbands remain
0.12/0.10 m; prediction, soft saturation, recovery, role persistence and pilot
takeover are unchanged. No PX4/EKF/IMU/compass gains, filters or preflight checks
are modified. Acceleration here is a motion-command limit, not accelerometer
calibration.

The model experiment separated the dominant limiter from the gains:

| Accel / jerk; gain changes | 5 m/s, 300 ms NED min separation | Final hover RMS speed |
|---|---:|---:|
| 3 / 6; no change | 1.51 m | 0.059 m/s |
| 3 / 8; no change | 1.51 m | 0.059 m/s |
| 4 / 8; no change | 2.18 m | 0.042 m/s |
| 4 / 8; position gain 0.6 | 2.20 m | 0.006 m/s |
| 4 / 8; damping 0.5 | 2.38 m | 0.053 m/s |

This is a synthetic first-order plant (0.6 s time constant), not an identified
F550. Jerk alone did not correct the limiting case; changing gains was not
necessary for the model checks to pass. Retain the existing gains for the first
airframe comparison instead of changing command limits and gains together.
If identified aircraft response still shows overshoot after the limiter stops
saturating, tune damping from measured response; if settling remains slow,
compare a small position-gain increase with the same delay/noise tests.

All 1/3/5 m/s NED/body and 80/300 ms cases passed the revised comparison's
faster-braking, lower-RMS, minimum-2-m modeled separation and final-hover-below-
0.05-m/s checks. Commanded 5-to-zero braking: 1.93 s / 4.11 m versus stock
5.27 s / 13.42 m. No collision-avoidance guarantee follows from these checks.

## Validation and rollout

All tests/builds run on Hetzner, not the limited local host. The targeted suite
covering Precision Move, total-speed/derivative bounds, controller, limits,
profile, tracking tool and GCS policy routing passed 107 tests. The two simulators initially read back
runtime code `70c45f1e`, then were updated while grounded to `b6dee129`, with
the candidate 6 / 1.25 / 4 / 8 limits unchanged. An isolated
GCS uses port 5036; production GCS remains in real mode with unchanged two-drone
identity and saved NED leader/follower assignments.

The corrected 1 m/s, 10 m rehearsal passed takeoff, engagement, follower
tracking, Hold, landing and restoration. Its maximum one-second-average leader
speed was 1.115 m/s, maximum moving-stage horizontal error 0.703 m, mean error
0.232 m. Position-derived speed includes telemetry/measurement effects and is
not an instantaneous source-velocity measurement.

Intermediate 3 m/s forward/reverse passed, with mean moving-stage horizontal
errors 0.57/0.61 m and peak 2.49/2.76 m. Intermediate 5 m/s forward/reverse
respected speed (maximum one-second average 5.37 m/s) and retained following,
but leader destination overshoot reached 6.32/6.46 m before settling. Workflow
completion did not make that acceptable guidance: this evidence prompted the
damped outer-loop correction above. The intermediate records are retained.

Further measured 3/5 m/s forward/reverse, braking, body/Stop and cleanup results
are recorded below as they complete. The candidate is opt-in; syncing Git alone
does not activate its four environment keys on aircraft. Grounded readback and
staged physical-airframe validation are required before claiming that an F550
achieves the same acceleration, tracking error or stopping distance. Adequate
maneuver/braking space, stable navigation, battery reserve and dependable peer
data remain necessary. Body rotation uses part of the same velocity budget.

Evidence directory:
`/mnt/HC_Volume_106468352/mds-validation/20261002-precision-fixed/`.
Raw field evidence and the initial failed candidate tests are retained, not
replaced. Public flattened image packaging remains pending available build
storage; Git-synced development SITL is not a refreshed public distribution.

### Corrected 5 m/s result

On `b6dee129`, 40 m north then south with intermediate stops passed. Maximum
one-second-average position-derived leader speed was 5.318 m/s; speed command
is bounded at 5, but physical/telemetry speed is not guaranteed identical.
Leader destination overshoot relative to its final settled position fell to
0.033 m north / 0.022 m south, compared with the undamped 6.32 / 6.46 m.
These are position-derived SITL figures, not physical accuracy guarantees.

Follower moving-stage mean horizontal error was 0.608 / 0.709 m, maximum
2.728 / 2.416 m; minimum reported separation was 3.274 / 3.585 m for the saved
6 m NED offset. Moving-stage maximum altitude error was 0.344 / 0.218 m.
After Hold, mean horizontal error was 0.144 m. Both roles remained active
through the jogs and both ended grounded and idle after landing. The comparison
plot isolates the braking correction with the follower's limits unchanged.

This supports the revised limits for a staged actual-airframe comparison, not
perfect tracking under every maneuver or link condition. Keep initial body
tests slow (for example 5°/s yaw at a 6 m radius consumes 0.52 m/s before any
translation). Missing data, GNSS biases and aircraft acceleration limits are
not corrected by more jerk or a higher velocity cap. If the physical airframe
does not deliver the commanded acceleration, lower the leader maneuver rate or
identify/tune the aircraft velocity response before increasing follower gains.

### Final lower-speed and control regressions

The final damped 1 m/s run passed, with one-second-average peak speed 1.093 m/s,
mean moving-stage horizontal follower error 0.222 m, maximum 0.796 m and
maximum altitude error 0.190 m. Body offset 6 m, leader yaw 15° plus 2 m
translation, MDS Stop, airborne Hold with both missions cleared, landing and
saved-formation restoration also passed on the corrected runtime.

Final damped 3 m/s run passed: one-second-average peak speed 3.169 m/s,
mean moving-stage horizontal error 0.426 m, maximum 1.781 m and maximum
altitude error 0.208 m. All final rehearsals ended grounded and idle; generated
JSON reports and node sessions were archived before simulator removal.

The isolated simulator/GCS and temporary port-5036 firewall rule are removed
after validation. Production retains real mode, SCOUT (1), NET-LEADER (2),
leader 1 / follower 2, NED north offset 6 m. Customer's existing dirty SITL
configs and unrelated local documentation changes are preserved. Aircraft
remain off; grounded update/profile/logging readback is the next rollout step.

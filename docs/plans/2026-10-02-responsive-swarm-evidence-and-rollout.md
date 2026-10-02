# Responsive Swarm: evidence and rollout checkpoint

## Scope and decisions

Based on Arnaud's September 27 field flight, implemented an opt-in motion
candidate: horizontal 6 m/s, vertical 1.25 m/s, acceleration 3 m/s² and jerk
6 m/s³. The extra horizontal headroom is for tracking a leader commanded up
to 5 m/s, not permission to fly the leader at 6 m/s. Stock settings remain
5 / 0.75 / 1 / 2. Controller gains, prediction, filtering, deadbands, roles,
recovery, pilot takeover and existing UI dispatch semantics are unchanged.

No aircraft settings were applied. Git sync alone does not activate this
profile. Candidate rollout is conditional on validation; failed envelope
checks must not be hidden by increasing gains or reducing test thresholds.

## Evidence: braking, communication and stopping

The archived follower session `s_20260927_131922` contains 2,933 commands
from 13:19:30.361 to 13:23:16.447 UTC. Command intervals were median 76 ms,
95th percentile 83 ms, maximum 97 ms: no observed control-loop stall.
Leader sample age was median 52 ms, 95th percentile 269 ms, maximum 1.95 s.
Age includes sampling/processing/clock effects, not just network transit.
One accepted-data gap lasted 1.759 s. The archived evidence does not identify
the in-flight NetBird route, Wi-Fi retries or RF conditions.

At 13:22:44.034, leader horizontal velocity was 0.386 m/s, raw requested
follower velocity 0.187 m/s, shaped command 2.614 m/s, reported follower
velocity 3.081 m/s and leader sample age 38 ms. At 13:22:47 the leader was
0.078 m/s, follower command 0.397 m/s, reported follower 0.643 m/s and sample
age 2 ms. This demonstrates delayed braking inside MDS shaping despite fresh
leader data. It does not exclude additional aircraft, estimator or telemetry
delay. The 1 m/s² cap was active near its bound in approximately 17.2% of
samples. Leader vertical speed reached 1.1 m/s against the 0.75 m/s cap.

Reported separation reached 3.316 m; this is not proof the physical separation
never approached the pilot's approximately 2 m observation. Reported vertical
error was median absolute 0.166 m, 95th percentile 0.493 m and maximum 0.822 m;
the recorded MDS stream does not show a persistent 1 m reference bias.

MDS Stop command `759241e0-7c2c-463b-9558-8e0b04032198` was dispatched to both
at 13:23:16.418. Follower Offboard stop was logged at 16.490, Hold request at
16.494 and shutdown at 16.504. Leader shutdown at 16.531 preserved existing
POSCTL. Both reported cancellation success by 17.451. Decoded, firmware-matched
ULog events place RTL start at approximately 13:23:18.991 (leader) and
13:23:21.331 (follower). Thus MDS Stop cleanup preceded RTL, consistent with
the pilot report; these events alone do not identify the command source.

## Navigation and aircraft limitations

The downloaded October 2 retrieval includes September 27 ULogs 125 (leader)
and 81 (follower), plus follower log 80. Files parsed without corruption and
were checksummed. Both main logs contain only six inertial/actuator/event
topics because `SDLOG_PROFILE=8`; they cannot identify GNSS, heading or
altitude estimator root causes or reconstruct the pre-arm warning intervals.
Both main flights logged zero accelerometer/gyro clipping samples. That does
not demonstrate absence of vibration. Follower log 81 reports low battery
at 13:22:23.191, critical at 13:22:55.735 and emergency at 13:23:03.340;
battery state may affect end-of-flight response.

The Navigation Diagnostics profile changes logging only: `SDLOG_PROFILE=9`,
`SDLOG_MODE=2`, subject to firmware review, grounded application and SD space.
Verify actual navigation/estimator topics after restart. No PX4 arming gates,
EKF thresholds or gains are relaxed. No notch frequency is guessed from the
F550's 2212/920KV motors, 4S battery and 1047 props. GPS position innovation
gate differs between aircraft (8 versus 5); do not normalize without evidence.
Shared-ground calibration is deferred; home/local/MSL references must not be
overwritten to mask navigation faults.

## Implemented diagnostics and validation

Added configurable vertical speed, an editable environment registry entry,
candidate example, logging-only PX4 profile, limiter labels and debug timing
for loop/send/own receipt age/heading/leader receipt/source sequence/transport.
Receipt age is not a sensor source age or a pure link-latency measurement.
Added validated leader jog speed to the SITL-only rehearsal tool and a
deterministic offline production-controller comparison.

Hetzner targeted regression suite: 155 tests passed; additional tool/profile
suite: 51 passed (overlapping tests, not an additive total). The initial narrow
suite's global coverage threshold failed despite all tests passing; rerun used
explicit no-coverage mode. Validation builds/run only on Hetzner.

Commanded 5-to-zero braking improved from 5.27 s / 13.42 m to 2.07 s / 5.09 m
in the shaper comparison. These are commanded trajectory figures, not measured
aircraft stopping distance. The synthetic plant comparison improved RMS error
but failed its separation and hover checks at 5 m/s with 300 ms sample delay:
minimum NED separation 1.52 m and body separation 1.72 m. Consequently this
envelope is not cleared and the current real-aircraft profile is retained.

## Evidence locations and remaining work

### PX4 SITL findings

Two containers were verified at code revision `7286b7b7`, with all four
candidate values read back from their environment, using an isolated GCS on
port 5036. The 3 m/s requested-jog run completed takeoff, Swarm engagement,
movement, convergence, Hold, landing and restoration. However, its recorded
leader positions show approximately 11.1 m/s maximum one-second-average speed,
and 17.6 m maximum transient formation error. Its original workflow PASS is
**not** a controlled-3-m/s tracking acceptance result.

The Precision Move runner sends the final position target together with a
bounded velocity feed-forward. [PX4 adds feed-forward to its position-controller
output](https://docs.px4.io/main/en/flight_modes/offboard), so the request's
speed is not a bound on the combined controller output. Long-distance jogs
must not be used as speed-limited field maneuvers until this existing runner
defect is fixed and measured. The clean next change is a coherent bounded
trajectory reference or velocity-only outer position loop, preserving yaw,
altitude, cancellation, arrival settling and pilot takeover; do not lower PX4's
global maximum speed as a workaround for this command-specific problem.

The first 5 m/s requested-jog run failed because the test interrupted the
leader's Swarm startup before all roles confirmed the session. Follower log
`s_20261002_135115` records `Required swarm role stopped or rejected startup: 1`
at 13:51:21.465. The rehearsal now requires all role acknowledgements before
jogging and records/rejects overspeed in window-averaged position measurements.
This changes validation only, not field startup or recovery policy.

Body-offset rehearsal (6 m, 15° leader yaw plus 2 m translation) passed
formation convergence, MDS Stop for both, airborne Hold with missions cleared,
landing and restoration. It is a low-speed functional test, not a dynamic
separation guarantee. New test-tool checks passed 22 targeted tests on Hetzner.

Private Hetzner evidence (not committed, no credentials):

- `/mnt/HC_Volume_106468352/mds-evidence/field-20260927/analysis-20260927/`
- `/mnt/HC_Volume_106468352/mds-evidence/field-20261002-retrieval/`
- `/mnt/HC_Volume_106468352/mds-validation/20261002-responsive/`

Required before a changed-profile field flight: resolve the failed maneuver
envelope and the Precision Move speed contract; review measured PX4 SITL results; grounded code/config readback;
apply logging and verify actual topics; individual takeoff/land then gentle
paired following/stops with adequate maneuver space and pilot takeover ready.
Body yaw and offset changes follow only after baseline results are reviewed.

Optional follow-up: decouple unused NED heading freshness from translational
motion validity if evidence supports it; collect per-aircraft network metrics
and source/receipt timing; identify airframe response before modifying control
or EKF gains. A better radio may help packet continuity but cannot guarantee
perfect sync or correct command shaping.

The public SITL image has not been rebuilt. Validation uses an existing image
with a pinned Git-synced candidate; this is not refreshed public-image
provenance. Storage was insufficient for the flattened release workflow.
Unused old rehearsal images and an inactive MDS worktree's reinstallable npm
dependencies were removed; field evidence and unrelated projects preserved.

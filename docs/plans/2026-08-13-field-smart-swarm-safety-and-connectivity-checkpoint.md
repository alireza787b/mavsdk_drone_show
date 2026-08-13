# Field Smart Swarm Safety And Connectivity Checkpoint

**Date:** 2026-08-13
**Status:** implementation checkpoint; end-to-end SITL and real-flight acceptance pending

## Outcome

The August 13 field session proved the repaired individual Take Off path on
both aircraft and the MDS Land path on the second aircraft, but it did **not**
exercise Smart Swarm. The first aircraft was landed manually because the
operator had not yet located the card's Land action. The swarm trial was
stopped when the 5G router overheated and the aircraft/equipment were becoming
too hot. Earlier takeoff attempts were also rejected while estimator
vertical-position error was about `0.8 m`, above the existing `0.5 m` MDS
admission gate. No estimator, GNSS, arming, or PX4 preflight threshold was
relaxed.

This checkpoint addresses a separate deterministic Smart Swarm motion defect
found during the preflight code audit. It is not evidence that the new follower
controller has flown on real hardware.

## Reproduced Defect

The former controller did not apply acceleration or jerk limits until a
previous command existed, and its low-pass filter passed the first sample
through unchanged. With a stationary leader and a follower staged `6 m` on the
wrong side of a `6 m` north offset, the `0.5` position gain produced a
deterministic saturated `3.0 m/s` first command. At the `15 Hz` control rate,
that first step was equivalent to about `45 m/s²` of command acceleration.
Reconfiguration reset both histories and reopened the same path.

That behavior was unsafe for a first supervised formation test even though PX4
has its own downstream limits. MDS must bound the command it asks PX4 to fly.

## Systematic Motion Hardening

The replacement keeps one command-shaping source of truth:

- starts from the same exact zero-velocity/zero-acceleration seed used to enter
  Offboard mode
- applies separate horizontal and vertical speed limits, acceleration, jerk,
  and yaw-rate limits from the first command
- caps the control `dt`, so an event-loop stall cannot authorize a large catch-up
  step
- rejects wrong-leader, invalid, non-finite, stale, or frozen source motion
  before it reaches the controller
- validates the follower's own NED state on a monotonic freshness clock
- requires the aircraft to remain inside a small capture envelope for a dwell
  before enabling non-zero formation motion
- suspends and smoothly approaches zero for bad staging, target jumps,
  divergence, reconfiguration, or degrading source confidence
- scales leader feedforward and feedback together as source confidence decays
- preserves the independent Stop/Hold, Land, RTL, and manual recovery paths

The old PD/low-pass controller and its generic settings are removed rather than
kept as a competing legacy path. The canonical policy is the explicit
`SMART_SWARM_*` block in `src/params.py`.

Dashboard and drone-side admission now also agree: every selected target must
have fresh telemetry plus authoritative armed/airborne evidence. Home-relative
altitude is used for the dashboard airborne check; MSL altitude is not treated
as height above launch.

## Validation Boundary

Deterministic tests cover first-command continuity, bad/reversed staging,
independent vertical limits, direction reversal, delayed loop iterations,
stale confidence, invalid source samples, target jumps, divergence,
reconfiguration, reacquisition, and yaw shaping. On the exact release candidate,
the broad focused Python run passed `313` tests with `2` environment skips; the
final CI-selected backend run passed `295` tests with `2` environment skips,
and the three affected dashboard suites passed all `14` tests. Ruff,
`py_compile`, workflow YAML parsing, and `git diff --check` also passed. The
constrained 1 GB control host could not complete a production dashboard build
without exhausting swap, so the exact-commit CI build remains the authoritative
packaging gate.

As of this checkpoint:

- no end-to-end SITL Smart Swarm run has been completed for this change
- no hardware Smart Swarm command has been sent with this change
- the August 13 field session is evidence for individual Take Off/Land only
- official/private repository sync and production deployment remain release
  steps, not validation evidence

## Gate For The Next Field Session

Do not start the two-aircraft follower test until all required items are true:

1. focused backend, controller, and dashboard tests pass on the exact release
2. an end-to-end two-aircraft SITL run passes when a suitable validation host
   is available; if it is unavailable, record that limitation and keep the
   first hardware run explicitly experimental and incremental
3. GCS and both nodes report the same expected release and clean runtime state
4. router/network operation is thermally stable, with shade/cooling and a
   deliberate abort plan for loss of the swarm link
5. each aircraft independently passes bench arm, Take Off, Hold, Land, and RTL
   checks before the combined run
6. estimator/GNSS/RTK evidence remains stable without relaxing PX4 or MDS gates
7. the active aircraft Offboard-loss settings are reviewed deliberately; the
   tracked field profile's `COM_OF_LOSS_T=20.0` is not changed by this slice and
   must not be assumed to match the aircraft without verification

For the first combined attempt:

1. place the follower close to the offset shown in Formation Preview; for the
   current two-aircraft plan, independently verify the intended `6 m north`
   relationship before arming
2. take off one aircraft at a time once more if field conditions or setup have
   changed, then take off both and let their position estimates settle
3. start only the intended Smart Swarm scope and expect an initial zero-motion
   capture dwell
4. use a small, slow leader movement first and watch the follower, command
   monitor, QGC, link health, and separation continuously
5. stop to Hold or use Land/RTL/manual takeover immediately for unexpected
   motion, estimator warnings, stale telemetry, link degradation, or thermal
   concern
6. retain unified GCS/drone logs, both PX4 ULogs, command timestamps, and the
   synchronized field video for review

## Separate Connectivity And Data-Use Item

The reported `500 MB` 5G-plan consumption and router overheating are separate
from the follower-control defect. The private deployment audit verified that
`remote_gcs_4` was enabled and mirrored MAVLink to the VPS endpoint
`100.82.207.49:24550`, while no UDP listener or consumer existed there. At an
observed/expected `25–80 KB/s` per aircraft, that unused route can account for
about `180–576 MB/hour` across two aircraft.

The unused `remote_gcs_4` endpoint is therefore disabled in the private
profile and must remain disabled. This change is limited to that MAVLink route:
the HTTP GCS IP remains unchanged, and QGC, RTK, MDS telemetry, commands, and
recovery connectivity must be preserved. The route calculation establishes a
credible contributor, but attribution of the carrier's entire reported total
remains unproven until before/after interface and process counters are
captured.

Apply the private fleet merge only while the aircraft are grounded, one node at
a time on Monday. After each node, verify QGC MAVLink, RTK corrections, MDS
telemetry/readiness, command delivery, and recovery connectivity before
proceeding to the next node. Record the effective route set and data rate; do
not hide a network problem inside Smart Swarm control changes.

Router thermal management is an operational requirement even after traffic is
reduced. A software traffic fix cannot make an overheated field router a safe
single point of swarm connectivity.

## Deferred, Not Forgotten

- end-to-end SITL and supervised real-flight Smart Swarm acceptance
- degraded-link/dropout and leader-failover drills
- grounded one-node-at-a-time deployment and measured data-use verification for
  the disabled private `remote_gcs_4` route
- active-aircraft Offboard-loss parameter review
- richer operator-visible capture/confidence/failover state
- post-flight ULog and unified-log correlation against the video timeline

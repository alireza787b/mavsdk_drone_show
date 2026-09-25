# Smart Swarm motion-profile checkpoint — 2026-09-25

## Change scope

Runtime change: official `974ce185`; configuration registry follow-ups:
`0813e7dd`, `2dedbaff`. Corresponding client commits: `7f696bc26`,
`42ed40b63`, `48619cf2e`.

- Horizontal follower ceiling: **5 m/s**, up from 2 m/s.
- Retained: 1 m/s² acceleration, 2 m/s³ jerk, 0.75 m/s vertical ceiling,
  position/velocity gains, deadbands, filtered position correction, and bounded
  prediction. Existing evidence supports more speed headroom, not blind EKF or
  gain changes.
- Horizontal speed, acceleration, jerk, and existing recovery policy are
  registered in the existing advanced node-environment settings. No new
  normal-flight UI controls or bypass policy were introduced.
- Heading has independent ATTITUDE freshness in both transport paths;
  source-clock yaw differencing replaces receipt-clock differencing when
  streamed rate is unavailable. Old heading cannot be refreshed by position
  or heartbeat traffic. Both nodes must be updated together.
- Cancellation returns to the scheduler's owning asyncio loop. SIGTERM,
  safety-handoff result, mission cleanup, and command reporting are no longer
  split across incompatible event loops. Request cancellation does not abandon
  cleanup halfway through.
- Detailed control logs now include own/target position and own velocity.
  Saved formation, leader/jog ownership, default Hold/recovery, and pilot
  takeover precedence are unchanged.

## Verification

All execution and image work ran on the remote validation host, with no real
aircraft access. Production GCS stayed in real mode. The isolated GCS had its
own port, configuration file, and exactly two simulated aircraft.

- **352 targeted tests passed**, covering controller/command shaping,
  heading validity, producer/API contract, recovery, process ownership,
  command routes, and environment-registry consistency.
- High-speed controller tests exercised the 5 m/s cap, braking and reversal,
  3.71 m/s leader feedforward, quiet noisy-hover behavior, and a rotating 6 m
  body offset combined with translation. These are command/kinematic bounds,
  not a model of every physical airframe.
- **Two-drone NED rehearsal PASS**, 701 recorded samples: paired takeoff,
  automatic acquisition from 7.8 m error, two 8 m northward leader jogs,
  retained role reports, paired Hold, Land, grounded/idle verification, and
  saved-assignment restoration. Initial settled horizontal/vertical error:
  0.258/0.098 m; after the first jog: 0.582/0.345 m. The leader jogs use
  1 m/s, so this is not a real-PX4 5 m/s tracking benchmark.
- **Body-turn/cancellation rehearsal PASS**: 6 m forward body offset,
  paired takeoff/acquisition, leader translation plus 15° relative yaw,
  follower settling, explicit mission cancellation on both nodes, verified
  cleared mission/state while airborne in Hold, then Land and restoration.
  Capture horizontal/vertical error: 0.117/0.050 m; post-turn settled error:
  1.063/0.013 m (within the stated 1.5/0.6 m acceptance limits).
  Cancellation used `Mission.NONE` (0), with 2/2 accepted and 2/2 successful
  completions.

Evidence hashes (SHA-256; private reports and unified logs retained):

- NED report: `053ab174ea2cf97f9b7987106632503f430841407866adaccd8b19c685a03db8`
- Body/Stop report: `4511fb57596abb774e34af48c45cbff441a7cf5d90013c14518b6782f5c2d13f`

The pinned development SITL image was built from Git commit `974ce185`, not
`docker commit`. Registry/documentation follow-ups do not change the tested
motion algorithm. Early setup attempts were rejected before any commands:
isolated configured/running mode mismatch, startup timing, then a blocked
container-to-test-GCS port. Only the temporary simulation path was adjusted.

The first body/Stop probe confirmed both command completions but sampled one
old GCS mission value before its next telemetry poll. Its assertion was changed
to wait boundedly for the cleared airborne state, rather than treating command
completion as an atomic fleet-telemetry refresh. No runtime workaround was used.

## Before the real-aircraft test

1. Power both nodes on grounded; verify clean deployment and the **loaded**
   `smart_swarm_policy` limits, role/offset readback, and fresh position plus
   attitude timestamps. A matching Git revision alone is insufficient.
2. Review PX4 logging on each aircraft: the previous field ULogs omitted
   position/estimator topics. Enable the default logging profile while
   preserving any intentionally enabled extra profile; collect preflight
   logging if investigating GNSS/heading readiness. No PX4 parameter was
   changed by this release.
3. Keep pilot-agreed battery reserves, RC takeover, link placement, estimator
   readiness, and independent separation checks. Do not relax PX4 preflight
   checks to make a trial pass.
4. Start with gentle NED translation and braking. The 5 m/s ceiling is follower
   headroom, not the leader's requested cruise speed. At 5 m/s, 1 m/s² braking
   alone requires 12.5 m before jerk, transport delay, and aircraft response.
5. Then try slow body-frame yaw in place, followed by gentle translation.
   Rotation and translation share the follower speed budget; at 6 m radius,
   5°/s adds about 0.52 m/s. Defer rapid combined manoeuvres and large in-flight
   offset changes until these basics are verified in logs/video.

## Release boundary and remaining work

No UI build, dependency change, PX4 retuning, real-aircraft restart, or flight
command is part of this release. Customer names, two-drone configuration, and
saved real formation were preserved. Unrelated local documentation edits were
not included.

The public stock SITL archive was **not** refreshed. This checkpoint validates
a pinned development image; it must not be advertised as the contents of the
existing public archive. A distributable image rebuild/package/upload remains
required for a new pinned public release; the current validation host lacks
space for that full operation. Grounded deployment verification and real-flight
evidence remain required before claiming field performance.

Follow-up evidence: actual position/velocity/estimator ULogs, RTCM injection
warnings, compass/GNSS readiness, link loss and jitter during movement, and
battery reserve/action review. A better radio can improve a measured link
problem; it cannot guarantee perfect synchronization or remove control limits.

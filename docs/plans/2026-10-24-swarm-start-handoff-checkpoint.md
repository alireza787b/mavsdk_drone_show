# Smart Swarm start handoff: October 24 checkpoint

## Implemented behavior

The October 18 failure was a Take Off ownership handoff race, not a reason to
relax navigation checks or bypass the required-role barrier. Start review and
node command admission now use the same typed readiness decision. The GCS checks
every selected role before dispatch; each node still makes the final admission
decision under its command transaction lock. A changed condition can still
reject a command, and the cluster barrier remains authoritative.

The operator workflow remains **Takeoff → Start Swarm → Managed Return**:

- Start opens the normal review. It shows Checking, Finishing takeoff, Ready,
  or a concise blocker. Confirm requires a fresh decision for every target.
- Waiting does not queue a future engagement. The operator explicitly confirms.
- A lost submission response retains the original intent/key. Check command
  performs read-only receipt lookup, not a new submission. If no receipt exists,
  another submission requires fresh review and explicit confirmation.
- Closing a busy Start review does not cancel an already submitted command and
  does not trap the operator away from recovery controls.
- Take Off no longer awaits optional success-indicator blinks after authoritative
  airborne confirmation. Ownership is still retired by the existing coordinator.
- Required-role startup rejections take priority over incidental legacy stdout
  diagnostics in the reported failure summary.

No PX4/EKF parameters, navigation thresholds, formation roles, or flight-control
gains were changed. The existing client limits remain 6 m/s horizontal,
1.25 m/s vertical, 4 m/s² acceleration and 8 m/s³ jerk. Simurgh is unaffected.

## Validation completed on the dedicated build host

- 272 focused backend tests, 23 additional backend regressions, 26 rehearsal
  helper tests and 55 frontend tests passed.
- Production dashboard build passed. Desktop/mobile Start review opened without
  sending flight writes; grounded aircraft correctly kept Confirm unavailable.
- Two-drone SITL: H1 pilot-controlled leader, H2 +6 m North in NED. Runtime
  source was official commit `25f5fb4c`; subsequent implementation commits only
  improve validation tooling. Git sync was enabled on the existing pinned image.
- During Take Off, both reviews reported Finishing takeoff. An early Start
  returned HTTP 409 with `dispatched: false` before any Start dispatch.
- After Take Off completed, normal Start engaged the complete cluster. Two
  opposite 2 m leader jogs at 0.8 m/s completed within the same swarm session.
- During the two jog stages, estimated mean horizontal formation errors were
  0.13 m and 0.14 m; maxima were 0.56 m and 0.38 m. These are simulator estimates,
  not a claim of real-aircraft positioning accuracy or clearance.
- Stop/Hold completed on both. Managed Return dispatched RTL 10.004 seconds
  apart, each tracked RTL completed, and final cleanup verified both grounded
  and disarmed. Return intentionally leaves formation: whole-run error maxima
  including acquisition/return are not steady-state tracking metrics.

Final private evidence includes the JSON report, stage-labelled CSV/plots,
desktop/mobile screenshots and test/build logs. Earlier failed rehearsal runs
exposed validator error-handling/cleanup defects; those were corrected and
covered before the final passing run. They are not counted as passing flights.

## Release and field boundary

Official implementation commits: `25f5fb4c`, `103c6556`, `92e3dab3`, `3aa7d0ac`.
Equivalent client implementation tip: `b7038080` (before this checkpoint).
Shared source is synchronized separately from customer deployment profiles.
Record actual published/deployed tips in the handoff; no new release tag is
implied by this checkpoint.

The dashboard artifact can be built and deployed independently. A refreshed
standalone SITL image still requires build/export storage and redistribution;
the build host currently lacks that headroom. Existing-image Git-sync validation
does not certify an offline/no-sync image as containing the new runtime.

Real aircraft were offline during this phase. Before the next flight, verify
both boards' actual runtime commits, formation, limits and admission readbacks.
Clarify the unexplained H2 large-roll event in October 18 log 92 with the pilot;
do not assume a handling event or issue paired-flight clearance from SITL alone.
Managed Return is delayed PX4 RTL, not collision avoidance. Each aircraft's RTL
altitude/path and the actual launch geometry remain relevant.

RTK readiness is per-rover, not simply a connected QGC/base indication. DGPS is
not RTK fixed, and absent RTK is not evidence that PX4 decided RTK was unnecessary.
Do not loosen PX4 checks or apply speculative EKF tuning to hide missing data.

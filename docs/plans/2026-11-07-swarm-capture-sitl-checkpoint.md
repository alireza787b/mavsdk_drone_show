# Smart Swarm capture SITL checkpoint

The accepted scenario covers an unloaded, three-aircraft live formation. Ground
and settled-hover capture feed the existing editable draft; capture does not
arm, dispatch, save, change home or calibrate navigation.

## Accepted workflow

The visual-capture extension adds a cached live overlay, one-cluster defaults,
explicit multi-cluster selection and Current airborne heights. The original
planned/level workflow below remains supported. Current is an explicit choice,
not a change to the default height policy or a navigation calibration.

The isolated GCS ran in SITL mode on a separate port from the REAL deployment.
The runtime validator completed these steps and restored the original formation:

1. Capture the complete grounded cluster in NED and Body without saving.
2. Apply a captured draft with the inactive-scope and revision preconditions.
3. Complete coordinated Takeoff with three accepted and three successful executions.
4. Wait for effective native role reports before treating the formation as engaged.
5. Translate the leader and verify following.
6. Turn the leader by 30 degrees and verify Body following.
7. Reject capture while following is active, without changing the plan.
8. Hold all aircraft; capture settled airborne spacing, select a new root and
   choose Same height.
9. Apply and explicitly restart; verify the new relationships and formation.
10. Run Managed Return with a 10-second submission interval; verify all three
    aircraft disarmed and idle, and restore the saved configuration.

The extended rehearsal additionally moved one held aircraft up by 0.75 m,
captured Current heights, verified every edge against the sampled common-MSL
difference, applied it and rejoined before the level/reroot sequence. The full
rehearsal passed with all aircraft grounded and the original configuration restored.

The operator browser path also exercised Capture, local reference/leader/height
changes without resampling, Use capture, Apply and Takeoff review. Operate and
Managed Return screenshots were taken during the accepted runtime rehearsal.
Capture modal and draft controls were checked on desktop/mobile and in dark mode.

## Validation evidence

- 476 targeted Python tests passed, including capture geometry, activity/source
  validity, pending-Start races, ordinary active Apply compatibility, command
  dispatch, coordinated Takeoff and control-release boundaries.
- The visual extension passed 49 capture/API Python tests, 157 focused UI tests
  across 14 suites, and 15 docs/MCP generator tests. Tests include multi-cluster
  response races, default selection, Current eligibility, no above-home/GPS
  fallback, read-only drawings and cached-sample expiry despite successful HTTP.
- Browser checks used the built dashboard and real isolated SITL APIs. Capture
  settings reused frozen observations and no real-aircraft endpoint was allowed.
- The UI audit found no critical issues. Remaining color-literal findings are
  existing trajectory-preview drawing debt, outside this slice.
- The validation host could not create a WebGL context. The usable 2D fallback
  was verified; hardware-accelerated 3D rendering was not accepted by this run.

## Lessons preserved

Captured targets can already coincide with aircraft positions before the swarm
role barrier has completed. Matching geometry is not proof of engaged control;
the validator waits for native effective-role reports before moving the leader.

Position/heading freshness and heartbeat/landed-state freshness have different
cadences. Capture uses independent source evidence; it does not demand subsecond
heartbeat updates from a normally 1 Hz source. No new PX4 armability policy was
introduced. Planned or level heights avoid encoding GNSS height noise as offsets.

Live markers and frozen captured targets are different evidence. Live drawing
reuses cached fleet telemetry, ages nonadvancing source timestamps and never
feeds assignments. The native capture bundle alone supplies saved geometry and
Current-height capability. If the leader origin is unavailable, the display
must not invent a zero-coordinate reference. Side projections can coincide;
their selected-aircraft label and linked Top selection avoid stacked labels.

Builds and simulators were serialized on the memory-limited validation host.
The source overlay used the existing SITL image and its virtual environment;
this checkpoint is not a rebuilt immutable image or a hardware flight clearance.
All real aircraft remained outside the flight rehearsal.

## Remaining acceptance boundaries

Confirm current code/configuration readback when real aircraft are powered on.
Complete new-aircraft RC/navigation/calibration/power checks before individual
flight testing. Sustained high-rate turns, continuous moving leader handover,
simultaneous configuration adoption and physically coupled net transport are not
established by this scenario. No PX4 gains, speed/acceleration/jerk limits or
leader-loss policy were retuned in this phase.

For the reusable procedure, see
[Smart Swarm operator workflow](../guides/smart-swarm-field-workflow.md) and
[SITL validation](../guides/sitl-validation-platform.md).

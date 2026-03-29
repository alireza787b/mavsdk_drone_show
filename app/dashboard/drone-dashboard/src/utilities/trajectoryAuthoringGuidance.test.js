import {
  getTrajectoryAltitudeIntentSummary,
  getTrajectoryHeadingPlanSummary,
  getTrajectoryOperatorPolicyNotes,
  getSwarmTrajectoryExecutionDoctrine,
  getTrajectoryAltitudeReferenceLabel,
  getTrajectoryAltitudeReferenceDescription,
  getTrajectoryHeadingFieldLabel,
  getTrajectoryHeadingIntentSummary,
  getTrajectoryHeadingModeDescription,
  getTrajectoryHeadingModeLabel,
  getTrajectoryMissionAnchorDescription,
  getTrajectoryMissionAnchorLabel,
  getTrajectoryPreferredSpeedLabel,
  getTrajectoryRequiredSpeedLabel,
  getTrajectoryTimingPlanSummary,
  getTrajectoryTimingIntentSummary,
  getTrajectoryTimeFieldLabel,
  getTrajectoryTimingModeDescription,
  getTrajectoryTimingModeLabel,
} from './trajectoryAuthoringGuidance';
import { ALTITUDE_REFERENCE, TIMING_MODES, YAW_CONSTANTS } from './SpeedCalculator';

describe('trajectoryAuthoringGuidance', () => {
  test('returns shared operator labels and descriptions for altitude, timing, heading, and mission anchor states', () => {
    expect(getTrajectoryAltitudeReferenceLabel(ALTITUDE_REFERENCE.MSL)).toBe('MSL input');
    expect(getTrajectoryAltitudeReferenceLabel(ALTITUDE_REFERENCE.AGL)).toBe('Target AGL');
    expect(getTrajectoryAltitudeReferenceDescription(ALTITUDE_REFERENCE.MSL)).toMatch(/canonical mission altitude directly in MSL/i);
    expect(getTrajectoryAltitudeReferenceDescription(ALTITUDE_REFERENCE.AGL)).toMatch(/target clearance above ground/i);
    expect(getTrajectoryTimeFieldLabel({ isMissionAnchor: true })).toBe('Route entry delay');
    expect(getTrajectoryTimeFieldLabel()).toBe('Waypoint arrival time');
    expect(getTrajectoryTimingModeLabel(TIMING_MODES.AUTO_SPEED)).toBe('Speed-driven ETA');
    expect(getTrajectoryTimingModeLabel(TIMING_MODES.MANUAL_TIME)).toBe('Time-driven speed');
    expect(getTrajectoryTimingModeDescription(TIMING_MODES.AUTO_SPEED)).toMatch(/preferred inbound-leg speed/i);
    expect(getTrajectoryTimingModeDescription(TIMING_MODES.MANUAL_TIME)).toMatch(/pins the waypoint arrival time/i);
    expect(getTrajectoryPreferredSpeedLabel()).toBe('Preferred leg speed');
    expect(getTrajectoryRequiredSpeedLabel()).toBe('Required leg speed');
    expect(getTrajectoryHeadingFieldLabel({ isMissionAnchor: true })).toBe('Entry heading');
    expect(getTrajectoryHeadingFieldLabel()).toBe('Arrival heading');
    expect(getTrajectoryHeadingModeLabel(YAW_CONSTANTS.AUTO)).toBe('Auto heading');
    expect(getTrajectoryHeadingModeLabel(YAW_CONSTANTS.MANUAL)).toBe('Manual heading');
    expect(getTrajectoryHeadingModeDescription(YAW_CONSTANTS.AUTO)).toMatch(/inbound arrival leg/i);
    expect(getTrajectoryHeadingModeDescription(YAW_CONSTANTS.MANUAL, { isMissionAnchor: true })).toMatch(/initial route-entry heading/i);
    expect(getTrajectoryMissionAnchorLabel(0)).toBe('Mission start anchor');
    expect(getTrajectoryMissionAnchorLabel(2)).toBe('Waypoint arrival');
    expect(getTrajectoryMissionAnchorDescription(0)).toMatch(/delay after mission start/i);
    expect(getTrajectoryMissionAnchorDescription(2)).toMatch(/evaluated by the arrival leg/i);
  });

  test('builds concise control-versus-derived summaries for altitude, timing, and heading intent', () => {
    expect(
      getTrajectoryAltitudeIntentSummary({
        altitudeReference: ALTITUDE_REFERENCE.AGL,
        altitude: 160,
        targetAgl: 120,
        groundElevation: 40,
        terrainAccurate: true,
      })
    ).toEqual(
      expect.objectContaining({
        compact: '120.0m AGL → 160.0m MSL',
      })
    );

    expect(
      getTrajectoryTimingIntentSummary({
        timingMode: TIMING_MODES.AUTO_SPEED,
        timeFromStart: 30,
        preferredSpeed: 8,
        requiredSpeed: 8.1,
      })
    ).toEqual(
      expect.objectContaining({
        compact: '8.0 m/s → 30s',
      })
    );

    expect(
      getTrajectoryHeadingIntentSummary({
        headingMode: YAW_CONSTANTS.AUTO,
        calculatedHeading: 90,
      })
    ).toEqual(
      expect.objectContaining({
        compact: 'Auto 090°',
      })
    );

    expect(
      getTrajectoryTimingIntentSummary({
        isMissionAnchor: true,
        timeFromStart: 12,
      })
    ).toEqual(
      expect.objectContaining({
        compact: 'Entry +12s',
      })
    );
  });

  test('builds shared operator policy notes for altitude execution, terrain review, and leg ownership', () => {
    expect(
      getTrajectoryOperatorPolicyNotes({
        waypointCount: 3,
        stats: {
          authoringBreakdown: {
            routeEntryAnchors: 1,
            speedDrivenLegs: 1,
            timeDrivenLegs: 1,
          },
          altitudeReferenceCounts: { msl: 2, agl: 1 },
          timingModeCounts: { auto_speed: 1, manual_time: 2 },
          terrainCoverage: { accurate: 2, estimated: 1, unknown: 0 },
          minAgl: 120,
        },
      })
    ).toEqual([
      expect.objectContaining({
        label: 'Altitude execution',
        detail: expect.stringMatching(/1 waypoint uses Target AGL authoring/i),
      }),
      expect.objectContaining({
        label: 'Terrain confidence',
        detail: expect.stringMatching(/1 waypoint still rely on estimated or missing terrain/i),
      }),
      expect.objectContaining({
        label: 'Leg ownership',
        detail: expect.stringMatching(/1 route-entry anchor, 1 speed-driven leg, and 1 time-driven leg/i),
      }),
      expect.objectContaining({
        label: 'Mission frame',
        detail: expect.stringMatching(/authored in global latitude\/longitude with stored MSL altitude/i),
      }),
    ]);
  });

  test('formats operator-facing timing and heading summaries without counting the route entry anchor as a normal leg', () => {
    const stats = {
      routeEntryDelaySeconds: 12,
      authoringBreakdown: {
        routeEntryAnchors: 1,
        speedDrivenLegs: 2,
        timeDrivenLegs: 1,
        entryHeadings: 1,
        autoArrivalHeadings: 2,
        manualArrivalHeadings: 0,
      },
    };

    expect(getTrajectoryTimingPlanSummary(stats)).toBe('Entry +12s · Speed-driven ETA 2 · Time-driven speed 1');
    expect(getTrajectoryHeadingPlanSummary(stats)).toBe('Entry heading 1 · Auto arrival 2 · Manual arrival 0');
  });

  test('builds shared swarm trajectory execution doctrine for processing and launch review', () => {
    expect(getSwarmTrajectoryExecutionDoctrine()).toEqual([
      expect.objectContaining({
        label: 'Leader scope',
        detail: expect.stringMatching(/Only top-leader paths are authored or uploaded here/i),
      }),
      expect.objectContaining({
        label: 'Execution mode',
        detail: expect.stringMatching(/This is not live Smart Swarm/i),
      }),
      expect.objectContaining({
        label: 'Altitude rule',
        detail: expect.stringMatching(/Mission execution always flies the stored altitude package/i),
      }),
      expect.objectContaining({
        label: 'Launch\/home truth',
        detail: expect.stringMatching(/does not move or reinterpret the authored global route itself/i),
      }),
    ]);
  });
});

import {
  getTrajectoryAltitudeIntentSummary,
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
    expect(getTrajectoryTimeFieldLabel({ isMissionAnchor: true })).toBe('Route entry time');
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
    expect(getTrajectoryMissionAnchorDescription(0)).toMatch(/leader should enter the route after mission start/i);
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
        compact: 'Entry 12s',
      })
    );
  });
});

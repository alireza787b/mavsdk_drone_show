import {
  TRAJECTORY_ALTITUDE_POLICY,
  TRAJECTORY_SPEED_POLICY,
  clampPreferredLegSpeed,
  formatTrajectoryAltitudeEnvelope,
  formatTrajectorySpeedEnvelope,
  formatTrajectorySpeedEnvelopeDetail,
  getNominalPreferredLegSpeed,
  getSafeTerrainAdjustedAltitude,
  needsTerrainSafetyAdjustment,
} from './trajectoryMissionPolicy';

describe('trajectoryMissionPolicy', () => {
  it('clamps preferred speed inputs to the configured planner envelope', () => {
    expect(clampPreferredLegSpeed(-2)).toBe(TRAJECTORY_SPEED_POLICY.MIN_PREFERRED);
    expect(clampPreferredLegSpeed('9.5')).toBe(9.5);
    expect(clampPreferredLegSpeed(99)).toBe(TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX);
    expect(clampPreferredLegSpeed(undefined)).toBe(TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED);
  });

  it('keeps planner defaults inside the nominal operator band', () => {
    expect(getNominalPreferredLegSpeed(18)).toBe(TRAJECTORY_SPEED_POLICY.OPTIMAL_MAX);
    expect(getNominalPreferredLegSpeed(6)).toBe(6);
  });

  it('formats operator-facing envelope guidance and terrain safety helpers from one source', () => {
    expect(formatTrajectorySpeedEnvelope()).toBe('0.5-12 m/s nominal');
    expect(formatTrajectorySpeedEnvelopeDetail()).toBe('12-20 m/s review • >20 m/s redesign');
    expect(formatTrajectoryAltitudeEnvelope()).toBe(`1-${TRAJECTORY_ALTITUDE_POLICY.MAX_MSL.toLocaleString()} m MSL`);
    expect(getSafeTerrainAdjustedAltitude(235)).toBe(335);
    expect(needsTerrainSafetyAdjustment(260, 235)).toBe(true);
    expect(needsTerrainSafetyAdjustment(290, 235)).toBe(false);
  });
});

import {
  applyTrajectoryMissionPolicy,
  resetTrajectoryMissionPolicy,
  TRAJECTORY_ALTITUDE_POLICY,
  TRAJECTORY_TERRAIN_POLICY,
  TRAJECTORY_SPEED_POLICY,
  TRAJECTORY_TIMING_POLICY,
  clampPreferredLegSpeed,
  formatTrajectoryAltitudeEnvelope,
  formatTrajectorySpeedEnvelope,
  formatTrajectorySpeedEnvelopeDetail,
  getNominalPreferredLegSpeed,
  getSafeTerrainAdjustedAltitude,
  needsTerrainSafetyAdjustment,
} from './trajectoryMissionPolicy';

describe('trajectoryMissionPolicy', () => {
  afterEach(() => {
    resetTrajectoryMissionPolicy();
  });

  it('clamps preferred speed inputs to the configured planner envelope', () => {
    expect(clampPreferredLegSpeed(-2)).toBe(TRAJECTORY_SPEED_POLICY.MIN_PREFERRED);
    expect(clampPreferredLegSpeed('9.5')).toBe(9.5);
    expect(clampPreferredLegSpeed(99)).toBe(TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX);
    expect(clampPreferredLegSpeed(undefined)).toBe(TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED);
  });

  it('keeps planner defaults inside the nominal operator band', () => {
    expect(getNominalPreferredLegSpeed(18)).toBe(TRAJECTORY_SPEED_POLICY.OPTIMAL_MAX);
    expect(getNominalPreferredLegSpeed(6)).toBe(6);
    expect(TRAJECTORY_TIMING_POLICY.DEFAULT_ROUTE_ENTRY_DELAY_S).toBe(10);
    expect(TRAJECTORY_TIMING_POLICY.DEFAULT_FALLBACK_LEG_DURATION_S).toBe(10);
    expect(TRAJECTORY_TIMING_POLICY.DERIVED_TIME_STEP_S).toBe(0.1);
  });

  it('formats operator-facing envelope guidance and terrain safety helpers from one source', () => {
    expect(formatTrajectorySpeedEnvelope()).toBe('0.5-12 m/s nominal');
    expect(formatTrajectorySpeedEnvelopeDetail()).toBe('12-20 m/s review • >20 m/s redesign');
    expect(formatTrajectoryAltitudeEnvelope()).toBe(`1-${TRAJECTORY_ALTITUDE_POLICY.MAX_MSL.toLocaleString()} m MSL`);
    expect(getSafeTerrainAdjustedAltitude(235)).toBe(335);
    expect(needsTerrainSafetyAdjustment(260, 235)).toBe(true);
    expect(needsTerrainSafetyAdjustment(290, 235)).toBe(false);
  });

  it('applies runtime overrides from the backend without splitting policy sources', () => {
    applyTrajectoryMissionPolicy({
      altitude: {
        default_msl: 120,
        max_msl: 8000,
      },
      speed: {
        default_preferred: 7,
        optimal_max: 10,
        absolute_max: 16,
      },
      timing: {
        derived_time_step_s: 0.2,
      },
      terrain: {
        min_safe_clearance_m: 60,
        default_safe_clearance_m: 110,
      },
    });

    expect(TRAJECTORY_ALTITUDE_POLICY.DEFAULT_MSL).toBe(120);
    expect(TRAJECTORY_ALTITUDE_POLICY.MAX_MSL).toBe(8000);
    expect(TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED).toBe(7);
    expect(TRAJECTORY_SPEED_POLICY.OPTIMAL_MAX).toBe(10);
    expect(TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX).toBe(16);
    expect(TRAJECTORY_SPEED_POLICY.MARGINAL_MAX).toBe(16);
    expect(TRAJECTORY_TIMING_POLICY.DERIVED_TIME_STEP_S).toBe(0.2);
    expect(TRAJECTORY_TERRAIN_POLICY.MIN_SAFE_CLEARANCE_M).toBe(60);
    expect(TRAJECTORY_TERRAIN_POLICY.DEFAULT_SAFE_CLEARANCE_M).toBe(110);
    expect(formatTrajectorySpeedEnvelope()).toBe('0.5-10 m/s nominal');
    expect(formatTrajectorySpeedEnvelopeDetail()).toBe('10-16 m/s review • >16 m/s redesign');
  });
});

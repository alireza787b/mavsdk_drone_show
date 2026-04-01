const DEFAULT_TRAJECTORY_ALTITUDE_POLICY = Object.freeze({
  DEFAULT_MSL: 100,
  DEFAULT_TARGET_AGL: 100,
  MIN_MSL: 1,
  MAX_MSL: 10000,
});

const DEFAULT_TRAJECTORY_SPEED_POLICY = Object.freeze({
  DEFAULT_PREFERRED: 8,
  MIN_PREFERRED: 0.5,
  OPTIMAL_MAX: 12,
  MARGINAL_MAX: 20,
  ABSOLUTE_MAX: 20,
});

const DEFAULT_TRAJECTORY_TIMING_POLICY = Object.freeze({
  DEFAULT_ROUTE_ENTRY_DELAY_S: 10,
  DEFAULT_FALLBACK_LEG_DURATION_S: 10,
  DERIVED_TIME_STEP_S: 0.1,
});

const DEFAULT_TRAJECTORY_TERRAIN_POLICY = Object.freeze({
  MIN_SAFE_CLEARANCE_M: 50,
  DEFAULT_SAFE_CLEARANCE_M: 100,
});

export const TRAJECTORY_ALTITUDE_POLICY = { ...DEFAULT_TRAJECTORY_ALTITUDE_POLICY };
export const TRAJECTORY_SPEED_POLICY = { ...DEFAULT_TRAJECTORY_SPEED_POLICY };
export const TRAJECTORY_TIMING_POLICY = { ...DEFAULT_TRAJECTORY_TIMING_POLICY };
export const TRAJECTORY_TERRAIN_POLICY = { ...DEFAULT_TRAJECTORY_TERRAIN_POLICY };

const toFiniteNumber = (value) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

export const resetTrajectoryMissionPolicy = () => {
  Object.assign(TRAJECTORY_ALTITUDE_POLICY, DEFAULT_TRAJECTORY_ALTITUDE_POLICY);
  Object.assign(TRAJECTORY_SPEED_POLICY, DEFAULT_TRAJECTORY_SPEED_POLICY);
  Object.assign(TRAJECTORY_TIMING_POLICY, DEFAULT_TRAJECTORY_TIMING_POLICY);
  Object.assign(TRAJECTORY_TERRAIN_POLICY, DEFAULT_TRAJECTORY_TERRAIN_POLICY);
};

export const applyTrajectoryMissionPolicy = (policy = {}) => {
  const nextAltitude = { ...TRAJECTORY_ALTITUDE_POLICY };
  const nextSpeed = { ...TRAJECTORY_SPEED_POLICY };
  const nextTiming = { ...TRAJECTORY_TIMING_POLICY };
  const nextTerrain = { ...TRAJECTORY_TERRAIN_POLICY };

  const altitude = policy.altitude || {};
  const speed = policy.speed || {};
  const timing = policy.timing || {};
  const terrain = policy.terrain || {};

  const altitudeOverrides = {
    DEFAULT_MSL: toFiniteNumber(altitude.default_msl),
    DEFAULT_TARGET_AGL: toFiniteNumber(altitude.default_target_agl),
    MIN_MSL: toFiniteNumber(altitude.min_msl),
    MAX_MSL: toFiniteNumber(altitude.max_msl),
  };
  Object.entries(altitudeOverrides).forEach(([key, value]) => {
    if (value !== null && value > 0) {
      nextAltitude[key] = value;
    }
  });
  nextAltitude.MAX_MSL = Math.max(nextAltitude.MIN_MSL, nextAltitude.MAX_MSL);
  nextAltitude.DEFAULT_MSL = Math.min(nextAltitude.MAX_MSL, Math.max(nextAltitude.MIN_MSL, nextAltitude.DEFAULT_MSL));
  nextAltitude.DEFAULT_TARGET_AGL = Math.max(0, nextAltitude.DEFAULT_TARGET_AGL);

  const speedOverrides = {
    DEFAULT_PREFERRED: toFiniteNumber(speed.default_preferred),
    MIN_PREFERRED: toFiniteNumber(speed.min_preferred),
    OPTIMAL_MAX: toFiniteNumber(speed.optimal_max),
    ABSOLUTE_MAX: toFiniteNumber(speed.absolute_max),
  };
  Object.entries(speedOverrides).forEach(([key, value]) => {
    if (value !== null && value > 0) {
      nextSpeed[key] = value;
    }
  });
  nextSpeed.ABSOLUTE_MAX = Math.max(nextSpeed.MIN_PREFERRED, nextSpeed.ABSOLUTE_MAX);
  nextSpeed.OPTIMAL_MAX = Math.min(nextSpeed.ABSOLUTE_MAX, Math.max(nextSpeed.MIN_PREFERRED, nextSpeed.OPTIMAL_MAX));
  nextSpeed.MARGINAL_MAX = nextSpeed.ABSOLUTE_MAX;
  nextSpeed.DEFAULT_PREFERRED = Math.min(
    nextSpeed.ABSOLUTE_MAX,
    Math.max(nextSpeed.MIN_PREFERRED, nextSpeed.DEFAULT_PREFERRED)
  );

  const timingOverrides = {
    DEFAULT_ROUTE_ENTRY_DELAY_S: toFiniteNumber(timing.default_route_entry_delay_s),
    DEFAULT_FALLBACK_LEG_DURATION_S: toFiniteNumber(timing.default_fallback_leg_duration_s),
    DERIVED_TIME_STEP_S: toFiniteNumber(timing.derived_time_step_s),
  };
  Object.entries(timingOverrides).forEach(([key, value]) => {
    if (value !== null && value > 0) {
      nextTiming[key] = value;
    }
  });

  const terrainOverrides = {
    MIN_SAFE_CLEARANCE_M: toFiniteNumber(terrain.min_safe_clearance_m),
    DEFAULT_SAFE_CLEARANCE_M: toFiniteNumber(terrain.default_safe_clearance_m),
  };
  Object.entries(terrainOverrides).forEach(([key, value]) => {
    if (value !== null && value >= 0) {
      nextTerrain[key] = value;
    }
  });
  nextTerrain.DEFAULT_SAFE_CLEARANCE_M = Math.max(
    nextTerrain.MIN_SAFE_CLEARANCE_M,
    nextTerrain.DEFAULT_SAFE_CLEARANCE_M
  );

  Object.assign(TRAJECTORY_ALTITUDE_POLICY, nextAltitude);
  Object.assign(TRAJECTORY_SPEED_POLICY, nextSpeed);
  Object.assign(TRAJECTORY_TIMING_POLICY, nextTiming);
  Object.assign(TRAJECTORY_TERRAIN_POLICY, nextTerrain);

  return {
    altitude: { ...TRAJECTORY_ALTITUDE_POLICY },
    speed: { ...TRAJECTORY_SPEED_POLICY },
    timing: { ...TRAJECTORY_TIMING_POLICY },
    terrain: { ...TRAJECTORY_TERRAIN_POLICY },
  };
};

export const clampPreferredLegSpeed = (
  speed,
  fallback = TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED
) => {
  const numericSpeed = Number.parseFloat(speed);

  if (!Number.isFinite(numericSpeed)) {
    return fallback;
  }

  return Math.min(
    TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX,
    Math.max(TRAJECTORY_SPEED_POLICY.MIN_PREFERRED, numericSpeed)
  );
};

export const getNominalPreferredLegSpeed = (speed) => {
  return Math.min(
    clampPreferredLegSpeed(speed),
    TRAJECTORY_SPEED_POLICY.OPTIMAL_MAX
  );
};

export const formatTrajectorySpeedEnvelope = () =>
  `${TRAJECTORY_SPEED_POLICY.MIN_PREFERRED}-${TRAJECTORY_SPEED_POLICY.OPTIMAL_MAX} m/s nominal`;

export const formatTrajectorySpeedEnvelopeDetail = () =>
  `${TRAJECTORY_SPEED_POLICY.OPTIMAL_MAX}-${TRAJECTORY_SPEED_POLICY.MARGINAL_MAX} m/s review • >${TRAJECTORY_SPEED_POLICY.MARGINAL_MAX} m/s redesign`;

export const formatTrajectoryAltitudeEnvelope = () =>
  `${TRAJECTORY_ALTITUDE_POLICY.MIN_MSL}-${TRAJECTORY_ALTITUDE_POLICY.MAX_MSL.toLocaleString()} m MSL`;

export const getSafeTerrainAdjustedAltitude = (groundElevation = 0) =>
  groundElevation + TRAJECTORY_TERRAIN_POLICY.DEFAULT_SAFE_CLEARANCE_M;

export const needsTerrainSafetyAdjustment = (altitude = 0, groundElevation = 0) =>
  altitude < groundElevation + TRAJECTORY_TERRAIN_POLICY.MIN_SAFE_CLEARANCE_M;

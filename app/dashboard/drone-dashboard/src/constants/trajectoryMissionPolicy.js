export const TRAJECTORY_ALTITUDE_POLICY = {
  DEFAULT_MSL: 100,
  DEFAULT_TARGET_AGL: 100,
  MIN_MSL: 1,
  MAX_MSL: 10000,
};

export const TRAJECTORY_SPEED_POLICY = {
  DEFAULT_PREFERRED: 8,
  MIN_PREFERRED: 0.5,
  OPTIMAL_MAX: 12,
  MARGINAL_MAX: 20,
  ABSOLUTE_MAX: 30,
};

export const TRAJECTORY_TIMING_POLICY = {
  DEFAULT_ROUTE_ENTRY_DELAY_S: 10,
  DEFAULT_FALLBACK_LEG_DURATION_S: 10,
};

export const TRAJECTORY_TERRAIN_POLICY = {
  MIN_SAFE_CLEARANCE_M: 50,
  DEFAULT_SAFE_CLEARANCE_M: 100,
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

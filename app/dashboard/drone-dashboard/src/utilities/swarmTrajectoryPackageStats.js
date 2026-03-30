const toFiniteNumber = (value) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

export const normalizeSwarmTrajectoryPackageStats = (stats = null) => {
  if (!stats?.available) {
    return {
      available: false,
      droneCount: 0,
      routeEntryTimeS: null,
      missionClockS: null,
      routeMotionTimeS: null,
      maxAltitudeMslM: null,
      minAltitudeMslM: null,
      altitudeWindowM: null,
    };
  }

  return {
    available: true,
    droneCount: toFiniteNumber(stats?.drone_count ?? stats?.droneCount) ?? 0,
    routeEntryTimeS: toFiniteNumber(stats?.route_entry_time_s ?? stats?.routeEntryTimeS),
    missionClockS: toFiniteNumber(stats?.mission_clock_s ?? stats?.missionClockS),
    routeMotionTimeS: toFiniteNumber(stats?.route_motion_time_s ?? stats?.routeMotionTimeS),
    maxAltitudeMslM: toFiniteNumber(stats?.max_altitude_msl_m ?? stats?.maxAltitudeMslM),
    minAltitudeMslM: toFiniteNumber(stats?.min_altitude_msl_m ?? stats?.minAltitudeMslM),
    altitudeWindowM: toFiniteNumber(stats?.altitude_window_m ?? stats?.altitudeWindowM),
  };
};

export const formatSwarmTrajectoryMissionSeconds = (value) => {
  const numeric = toFiniteNumber(value);
  if (numeric === null) {
    return 'Unknown';
  }

  return `${numeric.toFixed(numeric >= 100 ? 0 : 1)}s`;
};

export const formatSwarmTrajectoryAltitudeEnvelope = (packageStats) => {
  const normalized = normalizeSwarmTrajectoryPackageStats(packageStats);

  if (!normalized.available || normalized.minAltitudeMslM === null || normalized.maxAltitudeMslM === null) {
    return 'Unknown';
  }

  const windowLabel = normalized.altitudeWindowM !== null
    ? ` • window ${normalized.altitudeWindowM.toFixed(1)} m`
    : '';

  return `${normalized.minAltitudeMslM.toFixed(1)}-${normalized.maxAltitudeMslM.toFixed(1)} m MSL${windowLabel}`;
};

export const formatSwarmTrajectoryPackageTimingSummary = (packageStats) => {
  const normalized = normalizeSwarmTrajectoryPackageStats(packageStats);
  if (!normalized.available) {
    return 'Timing unavailable';
  }

  return `${formatSwarmTrajectoryMissionSeconds(normalized.missionClockS)} mission clock • entry ${formatSwarmTrajectoryMissionSeconds(normalized.routeEntryTimeS)} • motion ${formatSwarmTrajectoryMissionSeconds(normalized.routeMotionTimeS)}`;
};

import { ALTITUDE_REFERENCE } from './SpeedCalculator';
import { getTerrainElevation } from '../services/ElevationService';

const getWaypointAltitudeReference = (waypoint = {}) =>
  waypoint.altitudeReference || ALTITUDE_REFERENCE.MSL;

const getPreservedTargetAgl = (waypoint = {}) => {
  if (Number.isFinite(waypoint.targetAgl)) {
    return Math.max(0, waypoint.targetAgl);
  }

  if (Number.isFinite(waypoint.altitude) && Number.isFinite(waypoint.groundElevation)) {
    return Math.max(0, waypoint.altitude - waypoint.groundElevation);
  }

  return 0;
};

export const applyWaypointTerrainContext = ({
  waypoint = {},
  latitude = waypoint.latitude,
  longitude = waypoint.longitude,
  terrainResult = {},
}) => {
  const nextGroundElevation = Number.isFinite(terrainResult?.elevation)
    ? terrainResult.elevation
    : Number.isFinite(waypoint.groundElevation)
      ? waypoint.groundElevation
      : 0;
  const altitudeReference = getWaypointAltitudeReference(waypoint);
  const terrainAccurate = !terrainResult?.error;

  const basePatch = {
    latitude,
    longitude,
    groundElevation: nextGroundElevation,
    terrainAccurate,
  };

  if (altitudeReference === ALTITUDE_REFERENCE.AGL) {
    const targetAgl = getPreservedTargetAgl(waypoint);

    return {
      ...basePatch,
      targetAgl,
      altitude: nextGroundElevation + targetAgl,
    };
  }

  return {
    ...basePatch,
    targetAgl: Math.max(0, (waypoint.altitude || 0) - nextGroundElevation),
  };
};

export const resolveWaypointTerrainContext = async (
  waypoint,
  { latitude = waypoint?.latitude, longitude = waypoint?.longitude } = {},
  terrainResolver = getTerrainElevation
) => {
  const terrainResult = await terrainResolver(latitude, longitude);

  return {
    ...applyWaypointTerrainContext({
      waypoint,
      latitude,
      longitude,
      terrainResult,
    }),
    terrainSource: terrainResult?.source || null,
    terrainError: terrainResult?.error || '',
  };
};

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

const shouldRefreshImportedWaypointTerrain = (waypoint = {}) => {
  const altitudeReference = getWaypointAltitudeReference(waypoint);

  return altitudeReference === ALTITUDE_REFERENCE.AGL
    || Number.isFinite(waypoint.targetAgl)
    || Number.isFinite(waypoint.groundElevation)
    || waypoint.terrainAccurate === false;
};

export const resolveImportedTrajectoryTerrainContext = async (
  waypoints = [],
  terrainResolver = getTerrainElevation
) => {
  const resolvedWaypoints = await Promise.all(
    waypoints.map(async (waypoint) => {
      if (!shouldRefreshImportedWaypointTerrain(waypoint)) {
        return {
          waypoint,
          refreshed: false,
          estimated: false,
        };
      }

      const terrainPatch = await resolveWaypointTerrainContext(
        waypoint,
        {
          latitude: waypoint.latitude,
          longitude: waypoint.longitude,
        },
        terrainResolver
      );

      return {
        waypoint: {
          ...waypoint,
          ...terrainPatch,
        },
        refreshed: true,
        estimated: terrainPatch.terrainAccurate === false,
      };
    })
  );

  return {
    waypoints: resolvedWaypoints.map((entry) => entry.waypoint),
    refreshedCount: resolvedWaypoints.filter((entry) => entry.refreshed).length,
    estimatedCount: resolvedWaypoints.filter((entry) => entry.estimated).length,
  };
};

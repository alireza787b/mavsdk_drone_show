import { ALTITUDE_REFERENCE } from './SpeedCalculator';
import { getSwarmTrajectoryElevationBatch } from '../services/droneApiService';

const getWaypointAltitudeReference = (waypoint = {}) =>
  String(waypoint.altitudeReference || '').toLowerCase() === ALTITUDE_REFERENCE.AGL
    ? ALTITUDE_REFERENCE.AGL : ALTITUDE_REFERENCE.MSL;

const unavailableTerrain = (error = 'Terrain elevation unavailable.', source = 'backend') => ({
  elevation: null, verified: false, source, error, confidence: '', sample_time: null,
});

const validCoordinate = ({ latitude, longitude }) => (
  Number.isFinite(latitude) && latitude >= -90 && latitude <= 90
  && Number.isFinite(longitude) && longitude >= -180 && longitude <= 180
);

// Mission 4 terrain has one authority. Map display providers and geographic
// estimates must never become flight-altitude inputs.
export const resolveMissionTrajectoryTerrainBatch = async (
  points = [],
  batchLookup = getSwarmTrajectoryElevationBatch
) => {
  const output = points.map(() => unavailableTerrain('Invalid terrain coordinates.'));
  const requests = points.map((point, index) => ({
    index, id: `mission-terrain-${index}`, lat: point.latitude, lng: point.longitude,
  })).filter((point) => validCoordinate({ latitude: point.lat, longitude: point.lng }));

  for (let start = 0; start < requests.length; start += 500) {
    const chunk = requests.slice(start, start + 500);
    try {
      const response = await batchLookup(chunk.map(({ id, lat, lng }) => ({ id, lat, lng })));
      const results = response?.success === true && Array.isArray(response.results) ? response.results : [];
      chunk.forEach((point) => {
        const result = results.find((item) => item?.id === point.id)
          || results.find((item) => item?.lat === point.lat && item?.lng === point.lng);
        const sameCoordinate = result?.lat === point.lat && result?.lng === point.lng;
        const verified = sameCoordinate && result?.status === 'ok'
          && Number.isFinite(result?.elevation_m) && !result?.error;
        const source = result?.provider || result?.source || 'backend';
        output[point.index] = verified ? {
          elevation: result.elevation_m,
          verified: true,
          source,
          error: '',
          confidence: result.confidence || '',
          sample_time: result.sample_time ?? null,
        } : unavailableTerrain(result?.error || result?.message || 'Terrain elevation unavailable.', source);
      });
    } catch (error) {
      chunk.forEach((point) => {
        output[point.index] = unavailableTerrain(error?.message || 'Terrain elevation unavailable.');
      });
    }
  }
  return output;
};

export const resolveMissionTrajectoryTerrain = async (latitude, longitude) => (
  (await resolveMissionTrajectoryTerrainBatch([{ latitude, longitude }]))[0]
);

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
  const terrainAccurate = Number.isFinite(terrainResult?.elevation)
    && !terrainResult?.error && terrainResult?.verified !== false;
  const nextGroundElevation = terrainAccurate
    ? terrainResult.elevation
    : Number.isFinite(waypoint.groundElevation) ? waypoint.groundElevation : null;
  const altitudeReference = getWaypointAltitudeReference(waypoint);

  const basePatch = {
    latitude,
    longitude,
    groundElevation: nextGroundElevation,
    terrainAccurate,
    terrainSource: terrainResult?.source || 'backend',
    terrainError: terrainAccurate ? '' : (terrainResult?.error || 'Terrain elevation unavailable.'),
    terrainConfidence: terrainResult?.confidence || '',
    terrainSampleTime: terrainResult?.sample_time ?? null,
  };

  if (altitudeReference === ALTITUDE_REFERENCE.AGL) {
    const targetAgl = getPreservedTargetAgl(waypoint);

    return {
      ...basePatch,
      targetAgl,
      // Keep the last stored MSL value on failure, but block AGL assignment.
      // Never turn a previous/zero ground fallback into a new flight altitude.
      altitude: terrainAccurate ? nextGroundElevation + targetAgl : waypoint.altitude,
    };
  }

  return {
    ...basePatch,
    targetAgl: terrainAccurate
      ? Math.max(0, (waypoint.altitude || 0) - nextGroundElevation)
      : waypoint.targetAgl ?? 0,
  };
};

export const resolveWaypointTerrainContext = async (
  waypoint,
  { latitude = waypoint?.latitude, longitude = waypoint?.longitude } = {},
  terrainResolver = resolveMissionTrajectoryTerrain
) => {
  let terrainResult;
  try {
    terrainResult = await terrainResolver(latitude, longitude);
  } catch (error) {
    terrainResult = unavailableTerrain(error?.message);
  }

  return applyWaypointTerrainContext({ waypoint, latitude, longitude, terrainResult });
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
  terrainResolver = null
) => {
  const refreshPoints = waypoints.filter(shouldRefreshImportedWaypointTerrain);
  const terrainResults = terrainResolver
    ? await Promise.all(refreshPoints.map(async (waypoint) => {
      try {
        return await terrainResolver(waypoint.latitude, waypoint.longitude);
      } catch (error) {
        return unavailableTerrain(error?.message);
      }
    }))
    : await resolveMissionTrajectoryTerrainBatch(refreshPoints);
  let resultIndex = 0;
  const resolvedWaypoints = await Promise.all(
    waypoints.map(async (waypoint) => {
      if (!shouldRefreshImportedWaypointTerrain(waypoint)) {
        return {
          waypoint,
          refreshed: false,
          estimated: false,
        };
      }

      const terrainPatch = applyWaypointTerrainContext({
        waypoint, terrainResult: terrainResults[resultIndex++],
      });

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
    unavailableCount: resolvedWaypoints.filter((entry) => entry.estimated).length,
  };
};

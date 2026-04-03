// utilities.js

// Import centralized API config with auto-detection
import { getBackendURL } from '../config/apiConfig';
import {
  buildGcsUrl,
  GCS_ROUTE_KEYS,
} from '../services/gcsApiService';

// Re-export for backward compatibility
export { getBackendURL };

// Usage-specific functions to return complete URLs for specific services
export function getTelemetryURL() {
    return buildGcsUrl(GCS_ROUTE_KEYS.fleetTelemetry);
}

export function getElevationURL(lat, lon) {
    return `${buildGcsUrl(GCS_ROUTE_KEYS.elevation)}?lat=${lat}&lon=${lon}`;
}

// DEPRECATED: Use getUnifiedGitStatusURL() instead — /git-status includes gcs_status field
export function getGitStatusURL() {
    return `${getBackendURL()}/get-gcs-git-status`;
}

export const getUnifiedGitStatusURL = () => buildGcsUrl(GCS_ROUTE_KEYS.gitStatus);

export const getSyncReposURL = () => buildGcsUrl(GCS_ROUTE_KEYS.syncRepos);


export function getCustomShowImageURL() {
    return buildGcsUrl(GCS_ROUTE_KEYS.customShowImage);
}
// DEPRECATED: Use getUnifiedGitStatusURL() instead — /git-status includes all drone statuses
export function getDroneGitStatusURLById(droneID) {
    return `${getBackendURL()}/get-drone-git-status/${droneID}`;
}

// Constants for conversions and world setup
export const LAT_TO_METERS = 111321;
export const LON_TO_METERS = 111321;
export const WORLD_SIZE = 400;
export const TEXTURE_REPEAT = 10;

// Constants for readability and maintainability
export const POLLING_RATE_HZ = 1;
export const STALE_DATA_THRESHOLD_SECONDS = 5;

// In-memory elevation cache — grid-snap to ~20 m to deduplicate nearby points
const _elevationCache = new Map();
const _ELEV_CACHE_MAX = 200;
const _ELEV_GRID = 0.0002; // ~20 m

function _snapElev(v) { return Math.round(v / _ELEV_GRID) * _ELEV_GRID; }
function _elevKey(lat, lon) { return `${_snapElev(lat).toFixed(4)},${_snapElev(lon).toFixed(4)}`; }

// In-flight request deduplication — prevents parallel fetches for the same point
const _elevInflight = new Map();

// Fetch the elevation based on latitude and longitude (cached + deduped)
export const getElevation = async (lat, lon) => {
  if (lat === null || lat === undefined || lon === null || lon === undefined) {
    return null;
  }

  const key = _elevKey(lat, lon);

  // Return cached result
  if (_elevationCache.has(key)) {
    return _elevationCache.get(key);
  }

  // Return in-flight promise if already fetching this point
  if (_elevInflight.has(key)) {
    return _elevInflight.get(key);
  }

  const fetchPromise = (async () => {
    try {
      const url = getElevationURL(lat, lon);
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data = await response.json();
      const elevation = data.results[0]?.elevation || null;

      // Store in cache (evict oldest if full)
      if (_elevationCache.size >= _ELEV_CACHE_MAX) {
        const first = _elevationCache.keys().next().value;
        _elevationCache.delete(first);
      }
      _elevationCache.set(key, elevation);
      return elevation;
    } catch (error) {
      console.error(`Failed to fetch elevation data: ${error}`);
      return null;
    } finally {
      _elevInflight.delete(key);
    }
  })();

  _elevInflight.set(key, fetchPromise);
  return fetchPromise;
};

// Convert Latitude, Longitude, Altitude to local coordinates
export const llaToLocal = (lat, lon, alt, reference) => {
    // Corrected latRad calculation with proper parentheses
    const latRad = ((lat + reference[0]) / 2) * (Math.PI / 180);
  
    // Adjust LON_TO_METERS dynamically based on latitude
    const lonToMetersAtLat = LON_TO_METERS * Math.cos(latRad);
  
    const north = (lat - reference[0]) * LAT_TO_METERS;
    const east = (lon - reference[1]) * lonToMetersAtLat;
    const up = alt - reference[2];
  
    // Optional scaling
    // const SCALE_FACTOR = 1000;
    // return [north * SCALE_FACTOR, up * SCALE_FACTOR, east * SCALE_FACTOR];
  
    return [north, up, east];
  };
  
  

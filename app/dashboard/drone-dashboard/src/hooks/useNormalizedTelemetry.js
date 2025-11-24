// app/dashboard/drone-dashboard/src/hooks/useNormalizedTelemetry.js
/**
 * Normalized Telemetry Hook
 * =========================
 * Custom React hook that automatically normalizes telemetry data from FastAPI backend.
 * Ensures all components receive consistent snake_case field names.
 *
 * @author MAVSDK Drone Show Team
 * @date 2025-11-24
 */

import { useMemo } from 'react';
import useFetch from './useFetch';
import { normalizeTelemetryResponse, normalizeDroneData } from '../constants/fieldMappings';

/**
 * Fetch and normalize telemetry data from GCS server
 *
 * @param {string} endpoint - API endpoint (e.g., '/telemetry', '/get-heartbeats')
 * @param {number|null} interval - Polling interval in ms (null = fetch once)
 * @param {boolean} normalize - Whether to normalize field names (default: true)
 * @returns {object} { data, error, loading }
 *
 * @example
 * // Fetch telemetry with auto-normalization
 * const { data, error, loading } = useNormalizedTelemetry('/telemetry', 1000);
 *
 * // Access fields using snake_case
 * const drone = data['1'];
 * console.log(drone.position_lat, drone.battery_voltage);
 */
export function useNormalizedTelemetry(endpoint, interval = null, normalize = true) {
  const { data, error, loading } = useFetch(endpoint, interval);

  // Memoize normalized data to avoid re-computation on every render
  const normalizedData = useMemo(() => {
    if (!data || !normalize) {
      return data;
    }

    // Handle different endpoint response formats
    if (endpoint === '/telemetry') {
      // Telemetry endpoint returns: { "1": {...}, "2": {...} }
      return normalizeTelemetryResponse(data);
    } else if (endpoint === '/get-heartbeats') {
      // Heartbeat endpoint returns: { heartbeats: [...], total_drones: N }
      if (data.heartbeats && Array.isArray(data.heartbeats)) {
        return {
          ...data,
          heartbeats: data.heartbeats.map(normalizeDroneData),
        };
      }
      return data;
    } else if (endpoint === '/git-status') {
      // Git status endpoint returns: { git_status: { "1": {...} } }
      // Need to transform FastAPI Pydantic field names to match drone API format
      if (data.git_status) {
        const transformedGitStatus = {};
        Object.entries(data.git_status).forEach(([key, gitData]) => {
          transformedGitStatus[key] = {
            ...gitData,
            // Map FastAPI schema names to drone API names for frontend compatibility
            branch: gitData.current_branch || gitData.branch,
            commit: gitData.latest_commit || gitData.commit,
            message: gitData.commit_message || gitData.message,
            // Keep original fields for backward compatibility
            current_branch: gitData.current_branch,
            latest_commit: gitData.latest_commit,
            commit_message: gitData.commit_message,
          };
        });
        return {
          ...data,
          git_status: transformedGitStatus,
        };
      }
      return data;
    } else {
      // Generic normalization for other endpoints
      return normalizeDroneData(data);
    }
  }, [data, endpoint, normalize]);

  return {
    data: normalizedData,
    error,
    loading,
  };
}

/**
 * Fetch telemetry for a single drone
 *
 * @param {string} droneId - Drone hardware ID
 * @param {number|null} interval - Polling interval in ms
 * @returns {object} { drone, error, loading }
 *
 * @example
 * const { drone, error, loading } = useDroneTelemetry('1', 1000);
 * console.log(drone.position_lat); // snake_case access
 */
export function useDroneTelemetry(droneId, interval = 1000) {
  const { data, error, loading } = useNormalizedTelemetry('/telemetry', interval);

  const drone = useMemo(() => {
    if (!data || !droneId) return null;
    return data[droneId] || null;
  }, [data, droneId]);

  return { drone, error, loading };
}

export default useNormalizedTelemetry;

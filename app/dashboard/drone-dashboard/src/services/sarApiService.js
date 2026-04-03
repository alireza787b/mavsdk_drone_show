// src/services/sarApiService.js
/**
 * QuickScout SAR API Service
 * All API calls for SAR mission planning, execution, and monitoring.
 */

import axios from 'axios';
import { buildSarUrl } from './gcsApiService';

function buildQueryString(params = {}) {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value
        .filter((item) => item !== undefined && item !== null && item !== '')
        .forEach((item) => query.append(key, item));
      return;
    }

    if (value !== undefined && value !== null && value !== '') {
      query.append(key, value);
    }
  });

  const queryString = query.toString();
  return queryString ? `?${queryString}` : '';
}

export const computePlan = async (missionRequest) => {
  const response = await axios.post(buildSarUrl('/mission/plan'), missionRequest, {
    timeout: 30000,
  });
  return response.data;
};

export const launchMission = async (missionId) => {
  const response = await axios.post(
    buildSarUrl(`/mission/launch${buildQueryString({ mission_id: missionId })}`)
  );
  return response.data;
};

export const getMissionStatus = async (missionId) => {
  const response = await axios.get(buildSarUrl(`/mission/${encodeURIComponent(missionId)}/status`));
  return response.data;
};

export const pauseMission = async (missionId, posIds = null) => {
  const response = await axios.post(
    buildSarUrl(`/mission/${encodeURIComponent(missionId)}/pause${buildQueryString({ pos_ids: posIds })}`)
  );
  return response.data;
};

export const resumeMission = async (missionId, posIds = null) => {
  const response = await axios.post(
    buildSarUrl(`/mission/${encodeURIComponent(missionId)}/resume${buildQueryString({ pos_ids: posIds })}`)
  );
  return response.data;
};

export const abortMission = async (missionId, posIds = null, returnBehavior = 'return_home') => {
  const response = await axios.post(
    buildSarUrl(
      `/mission/${encodeURIComponent(missionId)}/abort${buildQueryString({
        return_behavior: returnBehavior,
        pos_ids: posIds,
      })}`
    )
  );
  return response.data;
};

export const createPOI = async (missionId, poi) => {
  const response = await axios.post(
    buildSarUrl(`/poi${buildQueryString({ mission_id: missionId })}`),
    poi
  );
  return response.data;
};

export const getPOIs = async (missionId) => {
  const response = await axios.get(buildSarUrl(`/poi${buildQueryString({ mission_id: missionId })}`));
  return response.data;
};

export const updatePOI = async (poiId, updates) => {
  const response = await axios.patch(buildSarUrl(`/poi/${encodeURIComponent(poiId)}`), updates);
  return response.data;
};

export const deletePOI = async (poiId) => {
  const response = await axios.delete(buildSarUrl(`/poi/${encodeURIComponent(poiId)}`));
  return response.data;
};

export const batchElevation = async (points) => {
  const response = await axios.post(buildSarUrl('/elevation/batch'), points);
  return response.data;
};

// src/services/sarApiService.js
/**
 * QuickScout SAR API Service
 * All API calls for SAR mission planning, execution, and monitoring.
 */

import {
  buildSarUrl,
  deleteGcsResource,
  fetchGcsResource,
  patchGcsResource,
  postGcsResource,
} from './gcsApiService';

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
  const response = await postGcsResource(buildSarUrl('/mission/plan'), missionRequest, {
    timeout: 30000,
  });
  return response.data;
};

export const createPlanningJob = async (missionRequest) => {
  const response = await postGcsResource(buildSarUrl('/mission/plan/jobs'), missionRequest);
  return response.data;
};

export const getPlanningJob = async (jobId) => {
  const response = await fetchGcsResource(buildSarUrl(`/mission/plan/jobs/${encodeURIComponent(jobId)}`));
  return response.data;
};

export const cancelPlanningJob = async (jobId) => {
  const response = await postGcsResource(buildSarUrl(`/mission/plan/jobs/${encodeURIComponent(jobId)}/cancel`));
  return response.data;
};

export const listMissions = async (params = {}) => {
  const response = await fetchGcsResource(buildSarUrl(`/missions${buildQueryString(params)}`));
  return response.data;
};

export const revalidateLaunch = async (missionId) => {
  const response = await postGcsResource(
    buildSarUrl(`/mission/${encodeURIComponent(missionId)}/revalidate-launch`)
  );
  return response.data;
};

export const launchMission = async (missionId, { revalidationToken = null } = {}) => {
  const response = await postGcsResource(
    buildSarUrl(`/mission/launch${buildQueryString({ mission_id: missionId })}`),
    revalidationToken ? { revalidation_token: revalidationToken } : {}
  );
  return response.data;
};

export const getMissionWorkspace = async (missionId) => {
  const response = await fetchGcsResource(buildSarUrl(`/mission/${encodeURIComponent(missionId)}/workspace`));
  return response.data;
};

export const getMissionStatus = async (missionId) => {
  const response = await fetchGcsResource(buildSarUrl(`/mission/${encodeURIComponent(missionId)}/status`));
  return response.data;
};

export const getMissionHandoff = async (missionId) => {
  const response = await fetchGcsResource(buildSarUrl(`/mission/${encodeURIComponent(missionId)}/handoff`));
  return response.data;
};

export const pauseMission = async (missionId, posIds = null) => {
  const response = await postGcsResource(
    buildSarUrl(`/mission/${encodeURIComponent(missionId)}/pause${buildQueryString({ pos_ids: posIds })}`)
  );
  return response.data;
};

export const resumeMission = async (missionId, posIds = null) => {
  const response = await postGcsResource(
    buildSarUrl(`/mission/${encodeURIComponent(missionId)}/resume${buildQueryString({ pos_ids: posIds })}`)
  );
  return response.data;
};

export const abortMission = async (missionId, posIds = null, returnBehavior = 'return_home') => {
  const response = await postGcsResource(
    buildSarUrl(
      `/mission/${encodeURIComponent(missionId)}/abort${buildQueryString({
        return_behavior: returnBehavior,
        pos_ids: posIds,
      })}`
    )
  );
  return response.data;
};

export const createFinding = async (missionId, finding) => {
  const response = await postGcsResource(
    buildSarUrl(`/findings${buildQueryString({ mission_id: missionId })}`),
    finding
  );
  return response.data;
};

export const getFindings = async (missionId) => {
  const response = await fetchGcsResource(buildSarUrl(`/findings${buildQueryString({ mission_id: missionId })}`));
  return response.data;
};

export const updateFinding = async (findingId, updates) => {
  const response = await patchGcsResource(buildSarUrl(`/findings/${encodeURIComponent(findingId)}`), updates);
  return response.data;
};

export const deleteFinding = async (findingId) => {
  const response = await deleteGcsResource(buildSarUrl(`/findings/${encodeURIComponent(findingId)}`));
  return response.data;
};

export const batchElevation = async (points) => {
  const response = await postGcsResource(buildSarUrl('/elevation/batch'), points);
  return response.data;
};

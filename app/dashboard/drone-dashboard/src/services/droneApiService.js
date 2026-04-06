// app/dashboard/drone-dashboard/src/services/droneApiService.js

import {
  buildStaticPlotUrl,
  buildSwarmTrajectoryUrl,
  clearProcessedSwarmTrajectoriesResponse,
  COMMAND_SUBMIT_TIMEOUT_MS,
  deleteGcsResource,
  fetchBlobGcsResource,
  getActiveCommandsResponse,
  getCommandStatusResponse,
  getRecentCommandsResponse,
  getSwarmLeadersResponse,
  getSwarmTrajectoryPolicyResponse,
  getSwarmTrajectoryStatusResponse,
  postGcsResource,
  processSwarmTrajectoriesResponse,
  submitCommandResponse,
} from './gcsApiService';
import { extractApiErrorMessage } from './apiError';
import { normalizeClusterState } from '../utilities/swarmTrajectoryViewModel';

/**
 * Builds a standardized command object for an action mission.
 * @param {number} actionType - The numeric code (e.g. 101 for LAND).
 * @param {string[]|undefined} droneIds - Array of drone IDs (if applicable).
 * @param {number} triggerTime - Optional trigger time for scheduling (default immediate).
 */
export const buildActionCommand = (actionType, droneIds = [], triggerTime = 0) => {
  // Note: If droneIds is empty, backend might interpret as "All Drones"
  // or you can handle that in your caller.
  return {
    missionType: String(actionType), // Convert to string for drone API compatibility
    target_drones: droneIds,
    triggerTime: String(triggerTime), // ensure it's a string
  };
};

export const sendDroneCommand = async (commandData, config = {}) => {
  try {
    const response = await submitCommandResponse(commandData, {
      timeout: COMMAND_SUBMIT_TIMEOUT_MS,
      ...config,
    });
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getCommandStatus = async (commandId) => {
  try {
    const response = await getCommandStatusResponse(commandId);
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getRecentCommands = async ({ limit = 8, status = null, missionType = null } = {}) => {
  try {
    const response = await getRecentCommandsResponse({ limit, status, missionType });
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getActiveCommands = async () => {
  try {
    const response = await getActiveCommandsResponse();
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getSwarmTrajectoryStatus = async () => {
  try {
    const response = await getSwarmTrajectoryStatusResponse();
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getSwarmTrajectoryPolicy = async () => {
  try {
    const response = await getSwarmTrajectoryPolicyResponse();
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getSwarmLeaders = async () => {
  try {
    const response = await getSwarmLeadersResponse();
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const uploadSwarmTrajectory = async (leaderId, file, filename = null) => {
  const formData = new FormData();

  if (file instanceof Blob) {
    formData.append('file', file, filename || `Drone ${leaderId}.csv`);
  } else {
    formData.append('file', file);
  }

  try {
    const response = await postGcsResource(
      buildSwarmTrajectoryUrl(`/upload/${encodeURIComponent(leaderId)}`),
      formData
    );
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'Upload failed'));
  }
};

export const getSwarmClusterStatus = async () => {
  try {
    // Get swarm leaders and status information
    const [leadersResponse, statusResponse] = await Promise.all([
      getSwarmLeadersResponse(),
      getSwarmTrajectoryStatus()
    ]);

    const leadersData = leadersResponse?.data ?? leadersResponse;
    const statusData = statusResponse?.data ?? statusResponse;

    if (!leadersData.success || !statusData.success) {
      throw new Error('Failed to fetch cluster information');
    }

    const backendClusters = statusData.status.clusters || [];

    const clusters = backendClusters.length > 0
      ? backendClusters.map(cluster => ({
          leader_id: cluster.leader_id,
          follower_ids: cluster.follower_ids || leadersData.follower_details?.[cluster.leader_id] || [],
          follower_count: cluster.follower_count ?? (cluster.follower_ids || []).length,
          expected_drone_count: cluster.expected_drone_count ?? 1 + (cluster.follower_count ?? 0),
          processed_drone_count: cluster.processed_drone_count ?? 0,
          has_trajectory: Boolean(cluster.ready),
          ready: Boolean(cluster.ready),
          state: normalizeClusterState(
            cluster.state || (cluster.ready ? 'ready' : cluster.leader_uploaded ? 'needs_processing' : 'missing_upload'),
          ),
          leader_uploaded: Boolean(cluster.leader_uploaded),
          leader_processed: Boolean(cluster.leader_processed),
          missing_follower_ids: cluster.missing_follower_ids || [],
          processed_follower_ids: cluster.processed_follower_ids || [],
          leader_plot_available: Boolean(cluster.leader_plot_available),
          cluster_plot_available: Boolean(cluster.cluster_plot_available),
          package_stats: cluster.package_stats || null,
          issues: cluster.issues || [],
          advisories: cluster.advisories || [],
        }))
      : leadersData.leaders.map(leaderId => ({
          leader_id: leaderId,
          follower_ids: leadersData.follower_details?.[leaderId] || [],
          follower_count: leadersData.hierarchies[leaderId] || 0,
          expected_drone_count: 1 + (leadersData.hierarchies[leaderId] || 0),
          processed_drone_count: 0,
          has_trajectory: leadersData.uploaded_leaders.includes(leaderId) && statusData.status.processed_trajectories > 0,
          ready: leadersData.uploaded_leaders.includes(leaderId) && statusData.status.processed_trajectories > 0,
          state: leadersData.uploaded_leaders.includes(leaderId) ? 'needs_processing' : 'missing_upload',
          leader_uploaded: leadersData.uploaded_leaders.includes(leaderId),
          leader_processed: statusData.status.processed_leaders?.includes?.(leaderId) || false,
          missing_follower_ids: [],
          processed_follower_ids: [],
          leader_plot_available: false,
          cluster_plot_available: false,
          issues: [],
          advisories: [],
        }));

    return {
      clusters,
      total_leaders: leadersData.leaders.length,
      total_followers: clusters.reduce((sum, cluster) => sum + cluster.follower_count, 0),
      follow_map: statusData.status.follow_map || {},
      processed_trajectories: statusData.status.processed_trajectories || 0,
      processed_drones: statusData.status.processed_drones || [],
      processed_leaders: statusData.status.processed_leaders || [],
      package_stats: statusData.status.package_stats || null,
      package_drone_stats: statusData.status.package_drone_stats || {},
      session: statusData.status.session || { exists: false },
      session_changes: statusData.status.session_changes || {},
      processing_recommendation: statusData.status.processing_recommendation || null,
      has_results: Boolean(statusData.status.has_results),
      expected_top_leaders: statusData.status.expected_top_leaders || leadersData.leaders || [],
      uploaded_leaders: statusData.status.uploaded_leaders || leadersData.uploaded_leaders || [],
      missing_uploaded_leaders: statusData.status.missing_uploaded_leaders || [],
      orphan_uploaded_leaders: statusData.status.orphan_uploaded_leaders || [],
      overall_state: statusData.status.cluster_summary?.overall_state || 'unknown',
      cluster_summary: statusData.status.cluster_summary || null,
    };
  } catch (error) {
    throw error;
  }
};

export const processTrajectories = async (options = {}) => {
  try {
    const response = await processSwarmTrajectoriesResponse({
      force_clear: options.force_clear || false,
      auto_reload: options.auto_reload !== false // default true
    });
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'Processing failed'));
  }
};

export const clearProcessedData = async () => {
  try {
    const response = await clearProcessedSwarmTrajectoriesResponse();
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'Clear failed'));
  }
};

export const removeSwarmTrajectoryUpload = async (leaderId) => {
  try {
    const response = await deleteGcsResource(
      buildSwarmTrajectoryUrl(`/remove/${encodeURIComponent(leaderId)}`)
    );
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'Remove failed'));
  }
};

export const clearAllSwarmTrajectories = async () => {
  try {
    const response = await postGcsResource(buildSwarmTrajectoryUrl('/clear'), {});
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'Clear failed'));
  }
};

export const clearSwarmTrajectoryLeader = async (leaderId) => {
  try {
    const response = await postGcsResource(
      buildSwarmTrajectoryUrl(`/clear-leader/${encodeURIComponent(leaderId)}`),
      {}
    );
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'Clear failed'));
  }
};

export const clearSwarmTrajectoryDrone = async (droneId) => {
  try {
    const response = await postGcsResource(
      buildSwarmTrajectoryUrl(`/clear-drone/${encodeURIComponent(droneId)}`),
      {}
    );
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'Delete failed'));
  }
};

export const commitSwarmTrajectoryOutputs = async (message) => {
  try {
    const response = await postGcsResource(buildSwarmTrajectoryUrl('/commit'), { message });
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'Commit failed'));
  }
};

export const downloadSwarmTrajectoryCsv = async (droneId) => {
  try {
    const response = await fetchBlobGcsResource(
      buildSwarmTrajectoryUrl(`/download/${encodeURIComponent(droneId)}`)
    );
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'Download failed'));
  }
};

export const downloadSwarmTrajectoryKml = async (droneId) => {
  try {
    const response = await fetchBlobGcsResource(
      buildSwarmTrajectoryUrl(`/download-kml/${encodeURIComponent(droneId)}`)
    );
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'KML download failed'));
  }
};

export const downloadSwarmClusterKml = async (leaderId) => {
  try {
    const response = await fetchBlobGcsResource(
      buildSwarmTrajectoryUrl(`/download-cluster-kml/${encodeURIComponent(leaderId)}`)
    );
    return response.data;
  } catch (error) {
    throw new Error(await extractApiErrorMessage(error, 'Cluster KML download failed'));
  }
};

export const buildSwarmTrajectoryPlotUrl = (filename) => buildStaticPlotUrl(filename);

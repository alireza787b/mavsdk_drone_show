// app/dashboard/drone-dashboard/src/services/droneApiService.js

import axios from 'axios';
import { getBackendURL } from '../utilities/utilities';

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

export const sendDroneCommand = async (commandData) => {
  const requestURI = `${getBackendURL()}/submit_command`;

  try {
    const response = await axios.post(requestURI, commandData);
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getCommandStatus = async (commandId) => {
  const requestURI = `${getBackendURL()}/command/${commandId}`;

  try {
    const response = await axios.get(requestURI);
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getSwarmTrajectoryStatus = async () => {
  try {
    const response = await axios.get(`${getBackendURL()}/api/swarm/trajectory/status`);
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
    const response = await axios.post(
      `${getBackendURL()}/api/swarm/trajectory/upload/${leaderId}`,
      formData
    );
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getSwarmClusterStatus = async () => {
  try {
    // Get swarm leaders and status information
    const [leadersResponse, statusResponse] = await Promise.all([
      axios.get(`${getBackendURL()}/api/swarm/leaders`),
      getSwarmTrajectoryStatus()
    ]);

    const leadersData = leadersResponse.data;
    const statusData = statusResponse.data;

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
          state: cluster.state || (cluster.ready ? 'ready' : cluster.leader_uploaded ? 'needs_processing' : 'missing_upload'),
          leader_uploaded: Boolean(cluster.leader_uploaded),
          leader_processed: Boolean(cluster.leader_processed),
          missing_follower_ids: cluster.missing_follower_ids || [],
          processed_follower_ids: cluster.processed_follower_ids || [],
          leader_plot_available: Boolean(cluster.leader_plot_available),
          cluster_plot_available: Boolean(cluster.cluster_plot_available),
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
      processed_trajectories: statusData.status.processed_trajectories || 0,
      processed_drones: statusData.status.processed_drones || [],
      processed_leaders: statusData.status.processed_leaders || [],
      session: statusData.status.session || { exists: false },
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

export const getProcessingRecommendation = async () => {
  try {
    const response = await axios.get(`${getBackendURL()}/api/swarm/trajectory/recommendation`);
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const processTrajectories = async (options = {}) => {
  const requestURI = `${getBackendURL()}/api/swarm/trajectory/process`;

  try {
    const response = await axios.post(requestURI, {
      force_clear: options.force_clear || false,
      auto_reload: options.auto_reload !== false // default true
    });
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const clearProcessedData = async () => {
  const requestURI = `${getBackendURL()}/api/swarm/trajectory/clear-processed`;

  try {
    const response = await axios.post(requestURI);
    return response.data;
  } catch (error) {
    throw error;
  }
};

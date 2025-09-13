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
    missionType: actionType,
    target_drones: droneIds,
    triggerTime: String(triggerTime), // ensure it’s a string
  };
};

export const sendDroneCommand = async (commandData) => {
  const requestURI = `${getBackendURL()}/submit_command`;

  try {
    console.log('Sending command:', JSON.stringify(commandData));
    console.log('Request URI:', requestURI);
    console.log('Base Server URL:', process.env.REACT_APP_SERVER_URL);
    console.log('Service Port:', process.env.REACT_APP_FLASK_PORT);

    const response = await axios.post(requestURI, commandData);
    console.log('Response received from server:', response.data);

    return response.data; // e.g. { status: 'success', message: ... }
  } catch (error) {
    console.error('Error in sendDroneCommand:', error);

    if (error.response) {
      console.error('Error response data:', error.response.data);
      console.error('Error status code:', error.response.status);
    } else if (error.request) {
      console.error('No response received from the server:', error.request);
    } else {
      console.error('Error message:', error.message);
    }

    throw error;
  }
};

export const getSwarmClusterStatus = async () => {
  try {
    // Get swarm leaders and status information
    const [leadersResponse, statusResponse] = await Promise.all([
      axios.get(`${getBackendURL()}/api/swarm/leaders`),
      axios.get(`${getBackendURL()}/api/swarm/trajectory/status`)
    ]);

    const leadersData = leadersResponse.data;
    const statusData = statusResponse.data;

    if (!leadersData.success || !statusData.success) {
      throw new Error('Failed to fetch cluster information');
    }

    // Transform the data to match the UI expectations
    const clusters = leadersData.leaders.map(leaderId => ({
      leader_id: leaderId,
      follower_count: leadersData.hierarchies[leaderId] || 0,
      has_trajectory: leadersData.uploaded_leaders.includes(leaderId) && statusData.status.processed_trajectories > 0
    }));

    return {
      clusters,
      total_leaders: leadersData.leaders.length,
      total_followers: Object.values(leadersData.hierarchies).reduce((sum, count) => sum + count, 0),
      processed_trajectories: statusData.status.processed_trajectories || 0
    };
  } catch (error) {
    console.error('Error fetching swarm cluster status:', error);
    throw error;
  }
};

export const getProcessingRecommendation = async () => {
  try {
    const response = await axios.get(`${getBackendURL()}/api/swarm/trajectory/recommendation`);
    return response.data;
  } catch (error) {
    console.error('Error fetching processing recommendation:', error);
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
    console.error('Error processing trajectories:', error);
    throw error;
  }
};

export const clearProcessedData = async () => {
  const requestURI = `${getBackendURL()}/api/swarm/trajectory/clear-processed`;

  try {
    const response = await axios.post(requestURI);
    return response.data;
  } catch (error) {
    console.error('Error clearing processed data:', error);
    throw error;
  }
};

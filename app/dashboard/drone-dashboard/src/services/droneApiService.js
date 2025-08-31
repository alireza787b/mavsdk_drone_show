// app/dashboard/drone-dashboard/src/services/droneApiService.js

import axios from 'axios';
import { API_CONFIG } from '../config/api';

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
    triggerTime: String(triggerTime), // ensure it's a string
  };
};

export const sendDroneCommand = async (commandData) => {
  const requestURI = `${API_CONFIG.baseURL}/submit_command`;

  try {
    console.log('Sending command:', JSON.stringify(commandData));
    console.log('Request URI:', requestURI);
    console.log('API Mode:', API_CONFIG.mode);
    console.log('API Description:', API_CONFIG.description);

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

/**
 * Generic API call helper using the new config system
 * @param {string} endpoint - API endpoint (without base URL)
 * @param {object} options - Axios options (method, data, etc.)
 */
export const apiCall = async (endpoint, options = {}) => {
  const url = `${API_CONFIG.baseURL}${endpoint.startsWith('/') ? endpoint : '/' + endpoint}`;
  
  try {
    const response = await axios({
      url,
      ...options
    });
    return response.data;
  } catch (error) {
    console.error(`API call failed for ${endpoint}:`, error);
    throw error;
  }
};

// Common API calls using the new system
export const fetchTelemetry = () => apiCall('/telemetry');
export const fetchSwarmData = () => apiCall('/get-swarm-data');
export const saveConfigData = (data) => apiCall('/save-config-data', { method: 'POST', data });
export const saveSwarmData = (data) => apiCall('/save-swarm-data', { method: 'POST', data });
export const fetchHeartbeats = () => apiCall('/get-heartbeats');
export const fetchGcsGitStatus = () => apiCall('/get-gcs-git-status');
export const fetchDroneGitStatus = (droneId) => apiCall(`/get-drone-git-status/${droneId}`);
export const importShow = (formData) => apiCall('/import-show', { 
  method: 'POST', 
  data: formData,
  headers: { 'Content-Type': 'multipart/form-data' }
});
export const fetchShowPlots = () => apiCall('/get-show-plots');
export const fetchElevation = (lat, lon) => apiCall(`/elevation?lat=${lat}&lon=${lon}`);
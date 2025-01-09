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

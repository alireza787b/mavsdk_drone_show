//app/dashboard/drone-dashboard/src/services/droneApiService.js
import axios from 'axios';
import { getBackendURL } from '../utilities/utilities';

export const sendDroneCommand = async (commandData) => {
  try {
    // Log the command being sent
    console.log('Sending command:', JSON.stringify(commandData));

    const response = await axios.post(`${getBackendURL()}/send_command`, commandData);
    console.log('Response received:', response.data); // Log the response for debugging
    return response.data;  // This might contain status and message fields
  } catch (error) {
    if (error.response) {
      console.error('Error in sendDroneCommand:', error.response.data);
    } else if (error.request) {
      console.error('No response received from the server:', error.request);
    } else {
      console.error('Error during request setup:', error.message);
    }
    throw error;  // Rethrowing the error to be handled by the caller
  }
};

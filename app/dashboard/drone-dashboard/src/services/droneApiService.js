// app/dashboard/drone-dashboard/src/services/droneApiService.js
import axios from 'axios';
import { getBackendURL } from '../utilities/utilities';

export const sendDroneCommand = async (commandData) => {
  const requestURI = `${getBackendURL()}/submit_command`;
  
  try {
    // Log the command being sent, along with the request URI
    console.log('Sending command:', JSON.stringify(commandData));
    console.log('Request URI:', requestURI);
    
    // Send the POST request
    const response = await axios.post(requestURI, commandData);
    
    // Log the response received from the server
    console.log('Response received from server:', response.data);
    
    return response.data;  // This might contain status and message fields
  } catch (error) {
    // Log detailed error information
    console.error('Error in sendDroneCommand:', error);
    
    if (error.response) {
      console.error('Error response data:', error.response.data);
      console.error('Error status code:', error.response.status);
    } else if (error.request) {
      console.error('No response received from the server:', error.request);
    } else {
      console.error('Error message:', error.message);
    }

    throw error;  // Rethrowing the error to be handled by the caller
  }
};

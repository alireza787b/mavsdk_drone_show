import axios from 'axios';
import { getBackendURL } from '../utilities';

export const sendDroneCommand = async (commandData) => {
  try {
    const response = await axios.post(`${getBackendURL()}/send_command`, commandData);
    return response.data;  // This might contain status and message fields
  } catch (error) {
    console.error('Error in sendDroneCommand:', error);
    throw error;  // Rethrowing the error to be handled by the caller
  }
};

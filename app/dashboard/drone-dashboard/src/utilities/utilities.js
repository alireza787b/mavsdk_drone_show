// utilities.js

// Adjust the function to use the port from environment variables or default to 5000
// utilities.js

// Get the base server URL from environment variables
const baseServerURL = process.env.REACT_APP_SERVER_URL || 'http://localhost';

// Get the port for Flask and Node.js from environment variables
const flaskPort = process.env.FLASK_PORT || '5000';
const nodejsPort = process.env.NODEJS_PORT || '5001';

// Function to get the Flask backend URL
export function getFlaskBackendURL() {
    return `${baseServerURL}:${flaskPort}`;
}

// Function to get the Node.js backend URL
export function getNodeBackendURL() {
    return `${baseServerURL}:${nodejsPort}`;
}

// Example function for getting telemetry data (Flask)
export function getTelemetryURL() {
    return `${getFlaskBackendURL()}/telemetry`;
}

// Example function for getting elevation data (Node.js)
export function getElevationURL(lat, lon) {
    return `${getNodeBackendURL()}/elevation?lat=${lat}&lon=${lon}`;
}


// Constants for conversions and world setup
export const LAT_TO_METERS = 111321;
export const LON_TO_METERS = 111321;
export const WORLD_SIZE = 400;
export const TEXTURE_REPEAT = 10;

// Constants for readability and maintainability
export const POLLING_RATE_HZ = 1;
export const STALE_DATA_THRESHOLD_SECONDS = 5;

// Fetch the elevation based on latitude and longitude
// Fetch the elevation based on latitude and longitude
export const getElevation = async (lat, lon) => {
  try {
      const url = `http://localhost:5001/elevation?lat=${lat}&lon=${lon}`;
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data = await response.json();
      
      // Correct usage of optional chaining without spaces
      return data.results[0]?.elevation || null;
  } catch (error) {
      console.error(`Failed to fetch elevation data: ${error}`);
      return null;
  }
};


// Convert Latitude, Longitude, Altitude to local coordinates
export const llaToLocal = (lat, lon, alt, reference) => {
    const north = (lat - reference[0]) * LAT_TO_METERS;
    const east = (lon - reference[1]) * LON_TO_METERS;
    const up = alt - reference[2];
    return [north, up, east];
};
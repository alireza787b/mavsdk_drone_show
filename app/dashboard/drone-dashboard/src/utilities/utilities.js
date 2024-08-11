// utilities.js

// Get the base server URL from environment variables
const baseServerURL = process.env.REACT_APP_SERVER_URL || 'http://localhost';

// Function to get the backend URL, with an optional port
export function getBackendURL(servicePort) {
    return `${baseServerURL}:${servicePort}`;
}

// Usage-specific functions to return complete URLs for specific services
export function getTelemetryURL() {
    const flaskPort = process.env.FLASK_PORT || '5000'; // Default Flask port
    return `${getBackendURL(flaskPort)}/telemetry`;
}

export function getElevationURL(lat, lon) {
    const nodejsPort = process.env.NODEJS_PORT || '5001'; // Default Node.js port
    return `${getBackendURL(nodejsPort)}/elevation?lat=${lat}&lon=${lon}`;
}

// Other utility functions remain the same...


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
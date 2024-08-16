// utilities.js

// Get the base server URL from environment variables
const baseServerURL = process.env.REACT_APP_SERVER_URL || 'http://localhost';

// Function to get the backend URL, ensuring that the default Flask port is appended
export function getBackendURL(servicePort = process.env.REACT_APP_FLASK_PORT || '5000') {
    return `${baseServerURL}:${servicePort}`;
}

// Usage-specific functions to return complete URLs for specific services
export function getTelemetryURL() {
    return `${getBackendURL()}/telemetry`;
}

export function getElevationURL(lat, lon) {
    return `${getBackendURL()}/elevation?lat=${lat}&lon=${lon}`;
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
export const getElevation = async (lat, lon) => {
  try {
      const url = getElevationURL(lat, lon);  // Use the updated function to get the elevation URL
      console.log(`Fetching elevation data from URL: ${url}`);  // Log the URL
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data = await response.json();
      
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

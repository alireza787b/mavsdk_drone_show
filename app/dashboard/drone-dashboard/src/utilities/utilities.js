// Adjust the function to use the port from environment variables or default to 5000
export function getBackendURL() {
  const hostArray = window.location.hostname.split(":");
  const domain = hostArray[0];
  const port = process.env.REACT_APP_BACKEND_PORT_OLD || '5000'; // Default to 5000 if not specified
  return `http://${domain}:${port}`;
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
    const url = `http://localhost:5001/elevation?lat=${lat}&lon=${lon}`;
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

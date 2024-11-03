// utilities.js

// Get the base server URL from environment variables
const baseServerURL = process.env.REACT_APP_SERVER_URL || 'http://localhost';

// Function to get the backend URL, always including the specified or default port
export function getBackendURL(servicePort = process.env.REACT_APP_FLASK_PORT || '5000') {
    // Ensure that the port is always appended to the URL
    return `${baseServerURL}:${servicePort}`;
}

// Usage-specific functions to return complete URLs for specific services
export function getTelemetryURL() {
    return `${getBackendURL()}/telemetry`;
}

export function getElevationURL(lat, lon) {
    return `${getBackendURL()}/elevation?lat=${lat}&lon=${lon}`;
}

// New function to get the GCS Git status URL
export function getGitStatusURL() {
    return `${getBackendURL()}/get-gcs-git-status`;
}

export function getCustomShowImageURL() {
    return `${getBackendURL()}/get-custom-show-image`;
}
export function getDroneGitStatusURLById(droneID) {
    return `${getBackendURL()}/get-drone-git-status/${droneID}`;
}

// Enhanced constants with proper scaling factors
export const LAT_TO_METERS = 111321; // Meters per degree of latitude
export const LON_TO_METERS_AT_EQUATOR = 111321; // Meters per degree of longitude at equator
export const WORLD_SIZE = 400;
export const TEXTURE_REPEAT = 10;
export const POLLING_RATE_HZ = 1;
export const STALE_DATA_THRESHOLD_SECONDS = 5;


const toRadians = (degrees) => degrees * (Math.PI / 180);
// Helper function to get longitude scale factor at a given latitude
const getLongitudeScaleFactor = (latitude) => {
    return Math.cos(toRadians(latitude));
};

// Enhanced elevation fetching with validation
export const getElevation = async (lat, lon) => {
    try {
        // Validate inputs
        if (!isFinite(lat) || !isFinite(lon)) {
            throw new Error('Invalid latitude or longitude');
        }
        
        const url = getElevationURL(lat, lon);
        console.log(`Fetching elevation for coordinates:`, { lat, lon });
        
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        
        const data = await response.json();
        const elevation = data.results[0]?.elevation;
        
        console.log('Received elevation:', elevation);
        return elevation ?? null;
    } catch (error) {
        console.error(`Failed to fetch elevation data:`, error);
        return null;
    }
};
// Enhanced LLA to local coordinate conversion
export const llaToLocal = (lat, lon, alt, reference) => {
    // Input validation
    if (!reference || reference.length !== 3) {
        console.error('Invalid reference point:', reference);
        return [0, 0, 0];
    }

    // Validate inputs
    const inputs = { lat, lon, alt, reference };
    for (const [key, value] of Object.entries(inputs)) {
        if (!isFinite(value)) {
            console.error(`Invalid ${key}:`, value);
            return [0, 0, 0];
        }
    }

    try {
        // Get longitude scale factor based on reference latitude
        const lonScale = getLongitudeScaleFactor(reference[0]);
        
        // Calculate distances
        const north = (lat - reference[0]) * LAT_TO_METERS;
        const east = (lon - reference[1]) * LON_TO_METERS_AT_EQUATOR * lonScale;
        const up = alt - reference[2];

        // Log conversion details for debugging
        console.group('Coordinate Conversion');
        console.log('Input:', { lat, lon, alt });
        console.log('Reference:', { 
            lat: reference[0], 
            lon: reference[1], 
            alt: reference[2] 
        });
        console.log('Scale factors:', {
            latScale: LAT_TO_METERS,
            lonScale: LON_TO_METERS_AT_EQUATOR * lonScale
        });
        console.log('Output:', { north, east, up });
        console.groupEnd();

        // Return corrected coordinates
        // Note: Depending on your Three.js coordinate system:
        // X = East, Y = Up, Z = North
        // This matches the standard geographic ENU (East-North-Up) coordinate system
        return [east, up, north];
    } catch (error) {
        console.error('Error in coordinate conversion:', error);
        return [0, 0, 0];
    }
};

// Add a helper function to calculate distance between two points
export const calculateDistance = (lat1, lon1, lat2, lon2) => {
    const R = 6371000; // Earth's radius in meters
    const φ1 = toRadians(lat1);
    const φ2 = toRadians(lat2);
    const Δφ = toRadians(lat2 - lat1);
    const Δλ = toRadians(lon2 - lon1);

    const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
            Math.cos(φ1) * Math.cos(φ2) *
            Math.sin(Δλ/2) * Math.sin(Δλ/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

    return R * c;
};
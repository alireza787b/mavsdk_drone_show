// src/config/apiConfig.js
// Centralized API configuration with auto-detection and environment override

/**
 * API Configuration Module
 *
 * Best Practice: Auto-detect server URL from browser location.
 * This makes the app portable without requiring .env changes or rebuilds.
 *
 * Priority order:
 * 1. Environment variable override (REACT_APP_SERVER_URL) - for advanced setups
 * 2. Auto-detect from window.location - works automatically everywhere
 *
 * This approach works for:
 * - SITL on localhost (auto-detects localhost)
 * - Production on any IP (auto-detects same IP)
 * - Different network configurations without rebuild
 */

// Default ports for services
const DEFAULT_GCS_PORT = process.env.REACT_APP_GCS_PORT || '5030';
const DEFAULT_DRONE_PORT = process.env.REACT_APP_DRONE_PORT || '7070';

/**
 * Determines the base server URL for API calls.
 * Auto-detects from browser location unless explicitly overridden.
 *
 * @returns {string} Base server URL (protocol + hostname, no port)
 */
function getBaseServerURL() {
  // Check for explicit environment override first
  const envURL = process.env.REACT_APP_SERVER_URL;
  if (envURL && envURL.trim() !== '') {
    return envURL.replace(/\/$/, ''); // Remove trailing slash if present
  }

  // Auto-detect from browser location (best practice for same-origin apps)
  if (typeof window !== 'undefined' && window.location) {
    const { protocol, hostname } = window.location;
    return `${protocol}//${hostname}`;
  }

  // Fallback for SSR or non-browser environments
  return 'http://localhost';
}

/**
 * Gets the GCS (Ground Control Station) server port.
 * @returns {string} Port number
 */
function getGCSPort() {
  return DEFAULT_GCS_PORT;
}

/**
 * Gets the drone server port.
 * @returns {string} Port number
 */
function getDronePort() {
  return DEFAULT_DRONE_PORT;
}

/**
 * Gets the full GCS backend URL including port.
 * @param {string} [port] - Optional port override
 * @returns {string} Full URL (e.g., "http://192.168.1.100:5030")
 */
export function getBackendURL(port = null) {
  const baseURL = getBaseServerURL();
  const servicePort = port || getGCSPort();
  return `${baseURL}:${servicePort}`;
}

/**
 * Gets the full drone service URL including port.
 * @returns {string} Full URL for drone service
 */
export function getDroneServiceURL() {
  const baseURL = getBaseServerURL();
  return `${baseURL}:${getDronePort()}`;
}

// Export configuration for debugging/logging
export const config = {
  get baseURL() { return getBaseServerURL(); },
  get gcsPort() { return getGCSPort(); },
  get dronePort() { return getDronePort(); },
  get gcsURL() { return getBackendURL(); },
  get droneURL() { return getDroneServiceURL(); },
  isAutoDetected: !process.env.REACT_APP_SERVER_URL,
};

const apiConfigModule = {
  getBackendURL,
  getDroneServiceURL,
  config,
};

export default apiConfigModule;

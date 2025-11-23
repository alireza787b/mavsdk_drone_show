// src/hooks/useComputeOrigin.js

import { useState } from 'react';
import axios from 'axios';
import { getBackendURL } from '../utilities/utilities';

/**
 * Custom hook to compute origin based on drone's current position and intended N-E positions.
 * Allows manual triggering of the computation.
 * @returns {object} - { origin, error, loading, computeOrigin }
 */
const useComputeOrigin = () => {
  const [origin, setOrigin] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  /**
   * Triggers the origin computation.
   * @param {object} params - { current_lat, current_lon, intended_east, intended_north }
   */
  const computeOrigin = async (params) => {
    const { current_lat, current_lon, intended_east, intended_north } = params;

    // Validate input parameters
    if (
      current_lat === undefined ||
      current_lon === undefined ||
      intended_east === undefined ||
      intended_north === undefined
    ) {
      setError('Incomplete parameters for origin computation.');
      return;
    }

    setLoading(true);
    const backendURL = getBackendURL(); // Uses REACT_APP_GCS_PORT

    try {
      const response = await axios.post(`${backendURL}/compute-origin`, {
        current_lat,
        current_lon,
        intended_east,
        intended_north,
      });

      if (
        response.data &&
        response.data.status === 'success' &&
        typeof response.data.lat === 'number' &&
        typeof response.data.lon === 'number'
      ) {
        setOrigin({ lat: response.data.lat, lon: response.data.lon });
        setError(null);
      } else if (response.data && response.data.status === 'error') {
        setError(response.data.message || 'Error computing origin.');
      } else {
        setError('Unexpected response from server.');
      }
    } catch (err) {
      setError(err.response?.data?.message || 'Error computing origin.');
    } finally {
      setLoading(false);
    }
  };

  return { origin, error, loading, computeOrigin };
};

export default useComputeOrigin;

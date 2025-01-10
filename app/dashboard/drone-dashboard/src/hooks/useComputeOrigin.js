// src/hooks/useComputeOrigin.js

import { useState, useEffect } from 'react';
import axios from 'axios';
import { getBackendURL } from '../utilities/utilities';

/**
 * Custom hook to compute origin based on drone's current position and intended N-E positions.
 * @param {object} params - { current_lat, current_lon, intended_east, intended_north }
 * @returns {object} - { origin, error, loading }
 */
const useComputeOrigin = (params) => {
  const [origin, setOrigin] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const computeOrigin = async () => {
    const { current_lat, current_lon, intended_east, intended_north } = params;
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
    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');

    try {
      const response = await axios.post(`${backendURL}/compute-origin`, {
        current_lat,
        current_lon,
        intended_east,
        intended_north,
      });

      if (
        response.data &&
        typeof response.data.lat === 'number' &&
        typeof response.data.lon === 'number'
      ) {
        setOrigin({ lat: response.data.lat, lon: response.data.lon });
        setError(null);
      } else if (response.data && response.data.error) {
        setError(response.data.error);
      } else {
        setError('Unexpected response from server.');
      }
    } catch (err) {
      setError(err.response?.data?.error || 'Error computing origin.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (
      params.current_lat !== undefined &&
      params.current_lon !== undefined &&
      params.intended_east !== undefined &&
      params.intended_north !== undefined
    ) {
      computeOrigin();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  return { origin, error, loading };
};

export default useComputeOrigin;

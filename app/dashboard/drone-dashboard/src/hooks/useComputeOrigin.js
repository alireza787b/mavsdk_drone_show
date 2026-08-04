// src/hooks/useComputeOrigin.js

import { useCallback, useRef, useState } from 'react';
import { computeOriginResponse } from '../services/gcsApiService';
import { extractApiErrorMessage } from '../services/apiError';

/**
 * Custom hook to compute origin based on drone's current position and intended N-E positions.
 * Allows manual triggering of the computation.
 * @returns {object} - { origin, error, loading, computeOrigin }
 */
const useComputeOrigin = () => {
  const [origin, setOrigin] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const requestSequence = useRef(0);

  const resetOrigin = useCallback(() => {
    requestSequence.current += 1;
    setOrigin(null);
    setError(null);
    setLoading(false);
  }, []);

  /**
   * Triggers the origin computation.
   * @param {object} params - { hw_id }
   */
  const computeOrigin = useCallback(async (params = {}) => {
    const hwId = String(params.hw_id ?? '').trim();
    const requestId = requestSequence.current + 1;
    requestSequence.current = requestId;
    setOrigin(null);
    setError(null);

    if (!hwId) {
      setError('Select a configured drone to compute the origin.');
      setLoading(false);
      return null;
    }

    setLoading(true);

    try {
      const response = await computeOriginResponse({ hw_id: hwId });

      if (requestSequence.current !== requestId) return null;

      if (
        response.data &&
        response.data.status === 'success' &&
        typeof response.data.origin?.lat === 'number' &&
        typeof response.data.origin?.lon === 'number' &&
        String(response.data.reference?.hw_id ?? '').trim() === hwId
      ) {
        setOrigin(response.data);
        setError(null);
        return response.data;
      } else {
        setError('Unexpected response from server.');
        return null;
      }
    } catch (err) {
      if (requestSequence.current === requestId) {
        setOrigin(null);
        setError(await extractApiErrorMessage(err, 'Error computing origin.'));
      }
      return null;
    } finally {
      if (requestSequence.current === requestId) setLoading(false);
    }
  }, []);

  return { origin, error, loading, computeOrigin, resetOrigin };
};

export default useComputeOrigin;

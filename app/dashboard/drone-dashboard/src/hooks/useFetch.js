// src/hooks/useFetch.js

import { useState, useEffect } from 'react';
import { extractServerNowMs } from '../constants/fieldMappings';
import { fetchGcsResource } from '../services/gcsApiService';

/**
 * Custom hook for fetching data from a given endpoint.
 * @param {string} endpoint - The API endpoint to fetch data from.
 * @param {number|null} interval - Polling interval in milliseconds (optional).
 * @returns {object} - { data, error, loading }
 */
const useFetch = (endpoint, interval = null) => {
  const [data, setData] = useState(null);
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!endpoint) {
      setData(null);
      setMeta(null);
      setError(null);
      setLoading(false);
      return undefined;
    }

    let isMounted = true; // To prevent state updates after unmount

    const fetchData = async () => {
      setLoading(true);
      try {
        const response = await fetchGcsResource(endpoint);
        if (isMounted) {
          const receivedAtMs = Date.now();
          setData(response.data);
          setMeta({
            receivedAtMs,
            serverNowMs: extractServerNowMs(response.headers),
          });
          setError(null);
        }
      } catch (err) {
        if (isMounted) {
          setError(err);
          setData(null);
          setMeta(null);
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchData();

    let timer;
    if (interval) {
      timer = setInterval(fetchData, interval);
    }

    return () => {
      isMounted = false;
      if (timer) clearInterval(timer);
    };
  }, [endpoint, interval]);

  return { data, meta, error, loading };
};

export default useFetch;

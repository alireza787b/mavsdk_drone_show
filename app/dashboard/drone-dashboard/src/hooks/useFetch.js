// src/hooks/useFetch.js

import { useState, useEffect } from 'react';
import axios from 'axios';
import { getBackendURL } from '../utilities/utilities';

/**
 * Custom hook for fetching data from a given endpoint.
 * @param {string} endpoint - The API endpoint to fetch data from.
 * @param {number|null} interval - Polling interval in milliseconds (optional).
 * @returns {object} - { data, error, loading }
 */
const useFetch = (endpoint, interval = null) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let isMounted = true; // To prevent state updates after unmount
    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');

    const fetchData = async () => {
      setLoading(true);
      try {
        const response = await axios.get(`${backendURL}${endpoint}`);
        if (isMounted) {
          setData(response.data);
          setError(null);
        }
      } catch (err) {
        if (isMounted) {
          setError(err);
          setData(null);
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

  return { data, error, loading };
};

export default useFetch;

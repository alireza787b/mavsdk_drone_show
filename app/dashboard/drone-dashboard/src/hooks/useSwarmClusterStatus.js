import { useEffect, useState } from 'react';

import { getSwarmClusterStatus } from '../services/droneApiService';

const useSwarmClusterStatus = ({ enabled = true, intervalMs = null, refreshTrigger = 0 } = {}) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(Boolean(enabled));
  const [manualRefreshKey, setManualRefreshKey] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setData(null);
      setError(null);
      setLoading(false);
      return undefined;
    }

    let isMounted = true;

    const fetchStatus = async () => {
      setLoading(true);
      try {
        const nextData = await getSwarmClusterStatus();
        if (!isMounted) {
          return;
        }

        setData(nextData);
        setError(null);
      } catch (nextError) {
        if (!isMounted) {
          return;
        }

        setError(nextError);
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    fetchStatus();

    let timer = null;
    if (intervalMs) {
      timer = setInterval(fetchStatus, intervalMs);
    }

    return () => {
      isMounted = false;
      if (timer) {
        clearInterval(timer);
      }
    };
  }, [enabled, intervalMs, refreshTrigger, manualRefreshKey]);

  return {
    data,
    error,
    loading,
    refresh: () => setManualRefreshKey((current) => current + 1),
  };
};

export default useSwarmClusterStatus;

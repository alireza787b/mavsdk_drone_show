import { useState, useCallback } from 'react';
import { toast } from 'react-toastify';
import { syncReposResponse } from '../services/gcsApiService';

/**
 * Shared hook for triggering drone sync operations.
 * Used by ControlButtons and SyncWarningBanner to avoid duplicate logic.
 */
export function useSyncDrones() {
  const [syncing, setSyncing] = useState(false);

  const syncDrones = useCallback(async () => {
    setSyncing(true);
    try {
      const response = await syncReposResponse({});
      const data = response.data;
      if (data.success) {
        toast.success(data.message || `Sync verified: ${data.synced_drones?.length || 0} drones updated`);
      } else {
        toast.warning(data.message || 'Sync completed with issues');
      }
      return data;
    } catch (error) {
      toast.error(`Sync failed: ${error.message}`);
      return null;
    } finally {
      setSyncing(false);
    }
  }, []);

  return { syncing, syncDrones };
}

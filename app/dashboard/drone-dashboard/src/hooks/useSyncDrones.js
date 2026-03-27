import { useState, useCallback } from 'react';
import { toast } from 'react-toastify';
import { getSyncReposURL } from '../utilities/utilities';

/**
 * Shared hook for triggering drone sync operations.
 * Used by ControlButtons and SyncWarningBanner to avoid duplicate logic.
 */
export function useSyncDrones() {
  const [syncing, setSyncing] = useState(false);

  const syncDrones = useCallback(async () => {
    setSyncing(true);
    try {
      const response = await fetch(getSyncReposURL(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        toast.error(`Sync failed: server returned ${response.status}`);
        return null;
      }
      const data = await response.json();
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

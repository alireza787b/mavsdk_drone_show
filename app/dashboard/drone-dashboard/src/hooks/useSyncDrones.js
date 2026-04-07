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
      const targetRef = [
        data.target_branch || null,
        data.target_commit ? String(data.target_commit).slice(0, 7) : null,
      ].filter(Boolean).join('@');
      const failedSummary = Array.isArray(data.failed_drones) && data.failed_drones.length > 0
        ? ` Failed: ${data.failed_drones.join(', ')}.`
        : '';

      if (data.success) {
        const successMessage = data.message || `Sync verified: ${data.synced_drones?.length || 0} drones updated`;
        toast.success(
          `${successMessage}${targetRef ? ` Target: ${targetRef}.` : ''}`,
          {
            autoClose: 5000,
          }
        );
      } else {
        toast.warning(
          `${data.message || 'Sync completed with issues'}${targetRef ? ` Target: ${targetRef}.` : ''}${failedSummary}`,
          {
            autoClose: 7000,
          }
        );
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

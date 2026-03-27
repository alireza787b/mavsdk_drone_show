import React, { useState, useEffect, useCallback, useRef } from 'react';
import '../styles/SyncWarningBanner.css';
import { getUnifiedGitStatusURL } from '../utilities/utilities';
import { useSyncDrones } from '../hooks/useSyncDrones';

/**
 * SyncWarningBanner
 *
 * Shows an amber warning banner when drones are out of sync with GCS.
 * Auto-dismisses when all drones sync. Operator can manually dismiss.
 * Re-shows if status changes after dismissal.
 */
const SyncWarningBanner = () => {
  const [syncData, setSyncData] = useState(null);
  const [dismissed, setDismissed] = useState(false);
  const lastNeedsSyncCountRef = useRef(0);
  const syncTimeoutRef = useRef(null);
  const { syncing, syncDrones } = useSyncDrones();

  const fetchGitStatus = useCallback(async () => {
    try {
      const response = await fetch(getUnifiedGitStatusURL());
      if (!response.ok) return;
      const data = await response.json();
      setSyncData(data);

      const newCount = data.needs_sync_count || 0;
      // Re-show banner if needs_sync_count increased (new drones went out of sync)
      if (newCount > 0 && newCount !== lastNeedsSyncCountRef.current) {
        setDismissed(false);
      }
      lastNeedsSyncCountRef.current = newCount;
    } catch {
      // Silently fail — polling will retry
    }
  }, []); // Stable — no state dependencies

  useEffect(() => {
    fetchGitStatus();
    const interval = setInterval(fetchGitStatus, 10000);
    return () => {
      clearInterval(interval);
      if (syncTimeoutRef.current) {
        clearTimeout(syncTimeoutRef.current);
      }
    };
  }, [fetchGitStatus]);

  const handleSync = async () => {
    await syncDrones();
    // The backend now waits for verification, so a quick refresh is enough.
    syncTimeoutRef.current = setTimeout(fetchGitStatus, 500);
  };

  // Don't show if no data, dismissed, or no sync needed
  if (!syncData || dismissed || !syncData.needs_sync_count || syncData.needs_sync_count === 0) {
    return null;
  }

  return (
    <div className="sync-warning-banner" role="alert">
      <div className="sync-warning-content">
        <span className="sync-warning-icon" aria-hidden="true">&#9888;</span>
        <span className="sync-warning-text">
          {syncData.needs_sync_count} of {syncData.total_drones} drone{syncData.total_drones !== 1 ? 's' : ''} out of sync with GCS
        </span>
        <button
          className="sync-warning-action"
          onClick={handleSync}
          disabled={syncing || syncData.sync_in_progress}
        >
          {syncing || syncData.sync_in_progress ? 'Syncing...' : 'Sync Now'}
        </button>
        <button
          className="sync-warning-dismiss"
          onClick={() => setDismissed(true)}
          title="Dismiss"
          aria-label="Dismiss sync warning"
        >
          &times;
        </button>
      </div>
    </div>
  );
};

export default SyncWarningBanner;

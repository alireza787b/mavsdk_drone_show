import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { FaCodeBranch, FaQuestionCircle, FaArrowRight, FaTimes } from 'react-icons/fa';
import '../styles/SyncWarningBanner.css';
import { useObservationResource } from '../contexts/ObservationContext';

/**
 * SyncWarningBanner
 *
 * Source-revision attention, not a flight-health or update-authority claim.
 * Inspecting never dispatches sync. Refresh failures retain the last evidence.
 */
const SyncWarningBanner = () => {
  const snapshot = useObservationResource('git');
  const syncData = snapshot.response?.data;
  const [dismissedSignature, setDismissedSignature] = useState(null);
  const [nowMs, setNowMs] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 10000);
    return () => clearInterval(timer);
  }, []);
  const drift = Math.max(0, Number(syncData?.needs_sync_count) || 0);
  const unknown = Math.max(0, Number(syncData?.unknown_count) || 0);
  const maintenance = syncData?.maintenance_count || 0;
  // Older GCS builds included clean branch-only rows in the drift count.
  const driftCount = syncData?.attention_count == null
    ? Math.max(0, drift - (syncData?.branch_only_count || 0)) : drift;
  const count = syncData?.attention_count ?? (driftCount + unknown);
  const signature = JSON.stringify([syncData?.gcs_status?.commit, driftCount, unknown, maintenance,
    Object.entries(syncData?.git_status || {})
      .filter(([, row]) => row && row.reviewable !== false && (!row.in_sync_with_gcs || row.maintenance_drift))
      .map(([id, row]) => [id, row.commit, row.status, row.maintenance_drift])
      .sort((a, b) => a[0].localeCompare(b[0]))]);
  if (!count || dismissedSignature === signature) return null;
  const stale = nowMs - snapshot.receivedAtMs >= 30000;
  const unavailable = stale || (!driftCount && !maintenance);
  const Icon = unavailable ? FaQuestionCircle : FaCodeBranch;
  let label = 'Review software';
  if (stale) label = 'Software status unavailable';
  else if (unavailable) label = 'Version unavailable';
  else if (!driftCount && maintenance) label = 'Review maintenance';
  const detail = stale ? 'Showing the last received software report.'
    : `${driftCount} software differences, ${unknown} unconfirmed revisions, ${maintenance} maintenance issues.`;

  return (
    <div className={`sync-warning-banner${unavailable ? ' is-unconfirmed' : ''}`} role="status" aria-live="polite">
      <div className="sync-warning-content">
        <Icon className="sync-warning-icon" aria-hidden="true" />
        <span className="sync-warning-text" title={detail}>
          <span>{label}</span><small>{count} aircraft</small>
        </span>
        <Link className="sync-warning-action" to="/fleet-ops?tab=sync&filter=drift" aria-label="Review aircraft software">
          <span>Review</span><FaArrowRight aria-hidden="true" />
        </Link>
        <button
          className="sync-warning-dismiss"
          type="button"
          onClick={() => setDismissedSignature(signature)}
          aria-label="Dismiss software notice"
        >
          <FaTimes aria-hidden="true" />
        </button>
      </div>
    </div>
  );
};

export default SyncWarningBanner;

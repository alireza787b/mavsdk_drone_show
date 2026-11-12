import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { FaCodeBranch, FaQuestionCircle, FaArrowRight, FaTimes } from 'react-icons/fa';
import '../styles/SyncWarningBanner.css';
import { getUnifiedGitStatusResponse } from '../services/gcsApiService';
import usePollingResource from '../hooks/usePollingResource';

async function loadSoftwareRevisions(options) {
  const response = await getUnifiedGitStatusResponse(options);
  const data = response?.data;
  if (!data || !Number.isInteger(data.needs_sync_count) || data.needs_sync_count < 0
      || !Number.isInteger(data.unknown_count ?? 0) || (data.unknown_count ?? 0) < 0) {
    throw new Error('Software revision status unavailable');
  }
  return response;
}

/**
 * SyncWarningBanner
 *
 * Source-revision attention, not a flight-health or update-authority claim.
 * Inspecting never dispatches sync. Refresh failures retain the last evidence.
 */
const SyncWarningBanner = () => {
  const snapshot = usePollingResource(loadSoftwareRevisions, 10000, 'software-revisions');
  const syncData = snapshot.response?.data;
  const [dismissedSignature, setDismissedSignature] = useState(null);
  const [nowMs, setNowMs] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 10000);
    return () => clearInterval(timer);
  }, []);
  const drift = Math.max(0, Number(syncData?.needs_sync_count) || 0);
  const unknown = Math.max(0, Number(syncData?.unknown_count) || 0);
  const signature = JSON.stringify([syncData?.gcs_status?.commit, drift, unknown,
    Object.entries(syncData?.git_status || {}).filter(([, row]) => row && row.in_sync_with_gcs !== true).map(([id, row]) =>
      [id, row.commit, row.status, row.in_sync_with_gcs]).sort((a, b) => a[0].localeCompare(b[0]))]);
  if (!syncData || !(drift || unknown) || dismissedSignature === signature) return null;
  const stale = nowMs - snapshot.receivedAtMs >= 30000;
  const unavailable = stale || !drift;
  const Icon = unavailable ? FaQuestionCircle : FaCodeBranch;
  const count = drift + unknown;
  const label = stale ? 'Software status unavailable' : drift ? 'Software differs' : 'Version unavailable';
  const detail = stale
    ? 'Last observed software status. Open Fleet operations to check connectivity and source revisions.'
    : `${drift} different, ${unknown} unconfirmed. Source revisions compared with GCS; not a flight-health check. Review before a grounded update.`;

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

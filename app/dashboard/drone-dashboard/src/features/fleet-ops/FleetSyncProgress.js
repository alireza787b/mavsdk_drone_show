import React, { useState } from 'react';
import { FaRedo, FaTimes } from 'react-icons/fa';
import { activeOperation } from './useFleetSync';

const phaseLabels = {
  review: 'Review sync', applying: 'Updating aircraft', verifying: 'Verifying software',
  completed: 'Sync verified', partial: 'Partially verified', failed: 'Sync failed',
  interrupted: 'Verification interrupted', expired: 'Preview expired',
};
const stateLabels = {
  ready: 'Ready', blocked: 'Excluded', applying: 'Updating', verifying: 'Verifying',
  verified: 'Verified', unconfirmed: 'Unconfirmed',
};
const steps = ['Preview', 'Review', 'Update', 'Verify'];
const stageIndex = { review: 1, applying: 2, verifying: 3, completed: 4, partial: 3, expired: 1 };
const blockedReasons = {
  offline: 'Offline', not_online: 'Offline', stale: 'Heartbeat stale', version_unknown: 'Version unknown', gcs_revision_unknown: 'GCS version unknown',
  identity_changed: 'Identity changed', verification_timeout: 'Verification timed out',
};
function reason(row) {
  return blockedReasons[row.error_code] || String(row.error_code || '').replaceAll('_', ' ');
}
function ProgressTargets({ rows }) {
  const [limit, setLimit] = useState(32);
  return <div className="fleet-sync-targets">
    <ul aria-label="Reviewed aircraft">{rows.slice(0, limit).map(row => <li key={row.hw_id}>
      <span>{row.pos_id != null ? 'Aircraft ' + row.pos_id : 'Aircraft'} <small>H{row.hw_id}</small></span>
      <span>{stateLabels[row.state] || 'Unknown'}{row.error_code && <small> · {reason(row)}</small>}</span>
    </li>)}</ul>
    {rows.length > limit && <button className="operator-button operator-button--ghost" type="button" onClick={() => setLimit(n => n + 32)}>Show more aircraft</button>}
  </div>;
}
export default function FleetSyncProgress({ sync }) {
  const { operation, preview, busy, readError } = sync;
  if (!sync.id && !busy && !sync.error) return null;
  const rows = Object.values(operation?.per_aircraft_state || {});
  const counts = operation?.target_counts || {};
  const reviewing = operation?.phase === 'review';
  const active = activeOperation(operation);
  const phase = operation?.phase;
  const retryIds = rows.filter(row => row.state === 'unconfirmed' || phase === 'expired')
    .map(row => row.hw_id);
  const title = busy === 'preview' ? 'Preparing preview' : busy === 'apply' ? 'Sending update'
    : operation ? phaseLabels[phase] : sync.id ? 'Retrieving sync status' : 'Preview unavailable';
  const reached = stageIndex[phase] ?? (counts.verified > 0 || operation?.error_code === 'verification_timeout' ? 3 : 2);
  const liveStep = reviewing || active;
  const when = operation?.completed_at || operation?.updated_at;
  const canApply = Boolean(reviewing && preview && !sync.checking && !busy && counts.ready);
  const canForget = !busy && !active && (!sync.checking || readError?.response?.status === 404);
  return <section className="fleet-sync" aria-label="Software sync progress">
    <header><div className="fleet-sync-title" role="status"><strong>{title}</strong>
      {operation && <span>{reviewing ? `${counts.ready} ready · ${counts.blocked} excluded` : `${counts.verified} of ${counts.total - counts.blocked} verified`}</span>}
    </div>
    {when > 0 && <time dateTime={new Date(when).toISOString()}>{new Date(when).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>}
    {sync.id && !busy && <button className="fleet-tool-icon" type="button" aria-label="Refresh sync status" title="Refresh status" onClick={sync.refresh}><FaRedo /></button>}
    {canForget && <button type="button" className="fleet-tool-icon" aria-label="Dismiss sync progress" title="Dismiss" onClick={sync.clear}><FaTimes /></button>}
    </header>
    {operation && <ol className="fleet-sync-steps" aria-label="Update phases">{steps.map((step, i) => {
      const current = i === reached && liveStep;
      return <li key={step} className={i < reached ? 'is-done' : current ? 'is-current' : ''} aria-current={current ? 'step' : undefined}>
        <span aria-hidden="true" />{step}</li>;
    })}</ol>}
    {sync.error && <p role="alert">{sync.error}</p>}
    {readError && <p role="status">Status unavailable. {readError?.response?.status === 404 ? 'This operation is no longer on this ground station.' : 'Waiting for the ground station.'}</p>}
    {operation && !reviewing && !active && phase !== 'completed' && operation.message && <p>{operation.message}</p>}
    {operation && <details key={operation.operation_id} className="fleet-sync-review" open={reviewing || undefined}>
      <summary>Aircraft <small>{counts.total}</small></summary>
      <ProgressTargets rows={rows} />
      <div className="fleet-sync-revision">Target <code>{operation.target_commit?.slice(0, 12) || 'Unknown'}</code> · {operation.target_branch || 'Unknown branch'}</div>
    </details>}
    {!reviewing && !active && retryIds.length > 0 && <footer>
      <button type="button" className="operator-button operator-button--ghost" disabled={Boolean(busy || sync.checking)}
        onClick={() => sync.prepare(retryIds)}>{phase === 'expired' ? 'Refresh preview' : 'Review unconfirmed'} · {retryIds.length}</button>
    </footer>}
    {reviewing && <footer>
      <button type="button" className="operator-button operator-button--ghost" disabled={Boolean(busy || sync.checking)} onClick={sync.clear}>Cancel</button>
      {preview ? <button type="button" className="operator-button operator-button--primary" disabled={!canApply} onClick={sync.apply}>Apply sync</button>
        : <button type="button" className="operator-button operator-button--primary" disabled={Boolean(busy || !rows.length || sync.checking)}
          onClick={() => sync.prepare(rows.map(row => row.hw_id))}>Refresh preview</button>}
    </footer>}
  </section>;
}

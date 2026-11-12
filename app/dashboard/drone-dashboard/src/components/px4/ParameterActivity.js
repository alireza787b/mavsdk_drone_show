import React from 'react';
import { OUTCOME_LABELS, parameterKey, parameterOutcome } from '../../utilities/px4ParameterValues';
import { isReceiptUncertain } from '../../features/px4-parameters/parameterReceipts';
import { describeAircraft } from './ParameterReview';

const jobLabel = record => record.error && !record.job ? 'Outcome unconfirmed' : ({ queued: 'Queued', running: 'Applying / verifying',
  completed: 'Complete', partial: 'Partially complete', failed: 'Failed', unknown: 'Outcome unconfirmed' }[record.job?.status] || 'Awaiting receipt');

export default function ParameterActivity({ receipts, aircraft, onLookup, storageError }) {
  return <details className="px4-activity" open={receipts.some(item => item.error || item.job?.status === 'unknown') || undefined}>
    <summary>Activity{receipts.length ? ` · ${receipts.length}` : ''}{receipts.some(isReceiptUncertain) ? ' · unconfirmed or active' : ''}</summary>
    {storageError && <p role="alert" className="px4-inline-warning">{storageError}</p>}
    {!receipts.length && <p className="px4-muted">No parameter writes in this browser context.</p>}
    {receipts.map(record => <details className="px4-operation" key={record.idempotencyKey} open={Boolean(record.error) || undefined}>
      <summary><strong>{jobLabel(record)}</strong><span>{record.title} · {record.hwIds.length} aircraft</span></summary>
      <p className="px4-context-label">{record.hwIds.map(id => describeAircraft(aircraft, id)).join(' · ')}</p>
      {!!record.excludedHwIds?.length && <p className="px4-muted">Excluded: {record.excludedHwIds.map(id => `H${id}`).join(', ')}</p>}
      {record.error && <p role="status" className="px4-inline-warning">{record.error}</p>}
      <div className="px4-table-scroll"><table className="px4-review-table"><thead><tr><th>Aircraft</th><th>Outcome</th><th>Applied</th><th>Verified</th></tr></thead><tbody>
        {record.hwIds.map(id => {
          const result = record.job?.results?.find(item => String(item.hw_id) === id), outcome = parameterOutcome(result);
          return <React.Fragment key={id}><tr><th>{describeAircraft(aircraft, id)}</th><td>{OUTCOME_LABELS[outcome] || outcome}{result?.error ? ` · ${result.error}` : ''}</td><td>{result?.applied === true ? 'Yes' : !result || ['unknown', 'pending'].includes(outcome) ? 'Unknown' : 'No'}</td><td>{result?.verified === true ? 'Yes' : !result || ['unknown', 'pending', 'written_unverified'].includes(outcome) ? 'Unconfirmed' : 'No'}</td></tr>
            {!!result?.result?.results?.length && <tr><td colSpan="4"><details><summary>Parameter results · {result.result.results.length}</summary>
              <table className="px4-review-table"><thead><tr><th>Parameter</th><th>Requested</th><th>Readback</th><th>Outcome</th></tr></thead><tbody>
                {result.result.results.map(entry => <tr key={parameterKey(entry)}><th><code>{entry.name}</code></th><td>{String(entry.requested_value)}</td><td>{entry.actual_value == null ? 'Unknown' : String(entry.actual_value)}</td><td>{OUTCOME_LABELS[parameterOutcome(entry)] || parameterOutcome(entry)}{entry.error ? ` · ${entry.error}` : ''}</td></tr>)}
              </tbody></table></details></td></tr>}
            {result?.snapshot_refresh_error && <tr><td colSpan="4">Snapshot refresh: {result.snapshot_refresh_error}</td></tr>}
          </React.Fragment>;
        })}</tbody></table></div>
      <div className="px4-text-actions"><button type="button" className="operator-button operator-button--ghost" onClick={() => onLookup(record)}>Check receipt</button><small>{new Date(record.createdAt).toLocaleString()}</small></div>
      <details className="px4-details"><summary>Receipt identity</summary><dl className="px4-facts"><dt>Job</dt><dd>{record.job?.job_id || 'Not confirmed'}</dd><dt>Review</dt><dd>{record.reviewId}</dd><dt>Request</dt><dd>{record.idempotencyKey}</dd></dl></details>
    </details>)}
  </details>;
}

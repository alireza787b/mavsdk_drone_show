import React from 'react';
import { buildDroneUlogDownloadURL } from '../../services/logService';
import { transferPending, transferStatus } from '../../features/log-workspace/useUlogTransfers';
import { formatBytes } from '../../utilities/logViewerUtils';

export function transferLabel(record, now) {
  if (record.creationStatus === 'rejected') return 'Could not start';
  const status = transferStatus(record, now);
  if (record.error && (!record.job || transferPending(record))) return 'Reconnecting';
  if (status === 'ready') return record.browserRequestedAt ? 'Sent to browser' : 'Ready to save';
  if (status === 'failed') return 'Transfer failed';
  if (status === 'expired') return 'Transfer expired';
  if (status === 'deleted') return 'Copy removed';
  return {
    waiting: 'Waiting to transfer',
    aircraft: 'Reading from aircraft',
    copy: 'Copying to GCS',
    verify: 'Checking file',
  }[record.job?.phase] || (record.job ? 'Reading from aircraft' : 'Starting transfer');
}

export default function UlogTransferActivity({ transfers, userRole, now }) {
  const allowed = ['operator', 'admin'].includes(userRole);
  const { records, selected } = transfers;
  const ordered = [...records].sort((a, b) => Number(b.requestId === selected) - Number(a.requestId === selected));
  return (
    <div className="ulog-center__activity">
      {transfers.error && <p role="alert">{transfers.error}</p>}
      {ordered.map(record => {
        const status = transferStatus(record, now);
        const active = transferPending(record);
        const bytes = record.job?.bytes_received;
        const total = record.job?.size_bytes || record.expectedSize;
        const progress = record.job?.progress > 0 ? record.job.progress : undefined;
        const label = transferLabel(record, now);
        return (
          <section key={record.requestId} className="ulog-center__row">
            <div className="ulog-center__heading">
              <strong>{record.aircraftLabel} · Log {record.logId}</strong>
              <span>{label}</span>
            </div>
            {active && <>
              <progress value={progress} max="1" aria-label={`${record.aircraftLabel} log ${record.logId} transfer progress`} />
              <p className="ulog-center__muted">{bytes != null ? `${formatBytes(bytes)} of ${formatBytes(total)}` : total ? formatBytes(total) : ''}
                {record.job?.updated_at && ` · Updated ${new Date(record.job.updated_at).toLocaleTimeString()}`}
              </p>
            </>}
            {(record.error || record.job?.error) && <p className="ulog-center__muted">{record.error || record.job.error}</p>}
            {active && record.wantsSummary && <p>Summary will open when the GCS copy is ready.</p>}
            {status === 'ready' && allowed && <div className="ulog-center__actions">
              <a className="operator-button operator-button--primary" href={buildDroneUlogDownloadURL(record.droneId, record.job.job_id, record.verified)}
                download={record.job.download_filename || `mds-ulog-H${record.droneId}-${record.logId}.ulg`}
                onClick={() => transfers.browserRequested(record)}>{record.browserRequestedAt ? 'Save again' : 'Save file'}</a>
              {record.verified && <button type="button" className="operator-button operator-button--ghost"
                onClick={() => transfers.analyzeTransfer(record)}>View summary</button>}
              <button type="button" className="operator-button operator-button--ghost" disabled={transfers.busy}
                onClick={() => transfers.remove(record)}>Remove copy</button>
            </div>}
            {allowed && (record.creationStatus === 'rejected' || ['failed', 'expired'].includes(status)) &&
              <button type="button" className="operator-button operator-button--ghost" disabled={transfers.busy}
                onClick={() => transfers.start({ droneId: record.droneId, logId: record.logId, aircraftLabel: record.aircraftLabel,
                  logDate: record.logDate, expectedSize: record.expectedSize, wantsSummary: record.wantsSummary })}>
                Retry aircraft read
              </button>}
            {active && record.error && <button type="button" className="operator-button operator-button--ghost"
              onClick={() => transfers.check(record)}>Check now</button>}
            {status === 'ready' && record.browserRequestedAt && <p className="ulog-center__muted">
              Check your browser downloads for save progress and Resume.
            </p>}
          </section>
        );
      })}
    </div>
  );
}

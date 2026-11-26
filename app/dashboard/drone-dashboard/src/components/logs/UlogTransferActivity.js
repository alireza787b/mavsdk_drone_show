import React, { useState } from 'react';
import { FiCheckCircle, FiClock, FiDownload, FiFileText, FiRefreshCw, FiTrash2 } from 'react-icons/fi';
import { buildDroneUlogDownloadURL } from '../../services/logService';
import { ActionIconButton, ConfirmDialog } from '../ui';
import { transferPending, transferStatus } from '../../features/log-workspace/useUlogTransfers';
import { formatBytes } from '../../utilities/logViewerUtils';

export function transferLabel(record, now) {
  if (record.creationStatus === 'rejected') return 'Could not start';
  const status = transferStatus(record, now);
  if (record.error && (!record.job || transferPending(record))) return 'Reconnecting';
  if (status === 'ready') return record.browserRequestedAt ? 'Save started' : 'Ready to save';
  if (status === 'failed') return 'Transfer failed';
  if (status === 'expired') return 'Expired';
  if (status === 'deleted') return 'Copy removed';
  return {
    waiting: record.job?.error ? 'Queue full' : 'Queued',
    aircraft: 'Reading from aircraft',
    copy: 'Copying to GCS',
    verify: 'Checking file',
  }[record.job?.phase] || (record.job ? 'Reading from aircraft' : 'Starting transfer');
}

function timeLeft(expiresAt, now) {
  const minutes = Math.ceil((expiresAt - now) / 60000);
  if (minutes >= 1440) {
    const days = Math.ceil(minutes / 1440);
    return `${days} ${days === 1 ? 'day' : 'days'} left`;
  }
  if (minutes >= 60) return `${Math.ceil(minutes / 60)} hr left`;
  return `${Math.max(1, minutes)} min left`;
}

export function UlogSaveLink({ record, onSave }) {
  return (
    <a className="operator-button operator-button--primary" href={buildDroneUlogDownloadURL(record.droneId, record.job.job_id, record.verified)}
      download={record.job.download_filename || `mds-ulog-H${record.droneId}-${record.logId}.ulg`}
      title="Save to this device" onClick={() => onSave(record)}>
      <FiDownload aria-hidden="true" /> {record.browserRequestedAt ? 'Save again' : 'Save file'}
    </a>
  );
}

export default function UlogTransferActivity({ transfers, userRole, now }) {
  const [removing, setRemoving] = useState(null);
  const allowed = ['operator', 'admin'].includes(userRole);
  const { records, selected } = transfers;
  const ordered = records.filter(record => transferStatus(record, now) !== 'deleted')
    .sort((a, b) => Number(b.requestId === selected) - Number(a.requestId === selected));
  return (
    <div className="ulog-center__activity">
      {transfers.error && <p role="alert">{transfers.error}</p>}
      {!ordered.length && !transfers.summary && <p>No transfers.</p>}
      {ordered.map(record => {
        const status = transferStatus(record, now);
        const active = transferPending(record);
        const bytes = record.job?.bytes_received;
        const total = record.job?.size_bytes || record.expectedSize;
        const progress = record.job?.progress > 0 ? record.job.progress : undefined;
        const expiresAt = record.job?.expires_at;
        return (
          <section key={record.requestId} className="ulog-center__row">
            <div className="ulog-center__heading">
              <strong>{record.aircraftLabel} · Log {record.logId}</strong>
              <span className="ulog-center__status">{status === 'ready' && <FiCheckCircle aria-hidden="true" />}{transferLabel(record, now)}</span>
            </div>
            {active && <>
              <progress value={progress} max="1" aria-label={`${record.aircraftLabel} log ${record.logId} transfer progress`} />
              <div className="ulog-center__meta">
                <span>{bytes != null ? `${formatBytes(bytes)} / ${formatBytes(total)}` : total ? formatBytes(total) : ''}</span>
                <span>{progress != null && `${Math.floor(progress * 100)}%`}</span>
              </div>
            </>}
            {(record.error || record.job?.error) && <details className="ulog-center__details">
              <summary>{active ? 'Details' : 'What happened?'}</summary>
              <p>{record.error || record.job.error}</p>
            </details>}
            {active && record.wantsSummary && <p className="ulog-center__muted">Summary queued</p>}
            {status === 'ready' && <>
              <div className="ulog-center__meta">
                <span>{formatBytes(total)}</span>
                {expiresAt > now && <span title={`GCS copy expires ${new Date(expiresAt).toLocaleString()}`}>
                  <FiClock aria-hidden="true" /> {timeLeft(expiresAt, now)}
                </span>}
              </div>
              {allowed && <div className="ulog-center__actions">
                <UlogSaveLink record={record} onSave={transfers.browserRequested} />
                {record.verified && <ActionIconButton icon={<FiFileText />} label="View summary"
                  onClick={() => transfers.analyzeTransfer(record)}>Summary</ActionIconButton>}
                <ActionIconButton icon={<FiTrash2 />} label="Remove GCS copy" title="Remove GCS copy" disabled={transfers.busy}
                  onClick={() => setRemoving(record)} />
              </div>}
            </>}
            {allowed && (record.creationStatus === 'rejected' || ['failed', 'expired'].includes(status)) &&
              <ActionIconButton icon={<FiRefreshCw />} label="Retry aircraft read" disabled={transfers.busy}
                onClick={() => transfers.start({ droneId: record.droneId, logId: record.logId, aircraftLabel: record.aircraftLabel,
                  logDate: record.logDate, expectedSize: record.expectedSize, wantsSummary: record.wantsSummary })}>
                Retry
              </ActionIconButton>}
            {active && record.error && <ActionIconButton icon={<FiRefreshCw />} label="Check now"
              onClick={() => transfers.check(record)}>Check now</ActionIconButton>}
          </section>
        );
      })}
      {removing && <ConfirmDialog appearance="console" open title="Remove GCS copy?" tone="danger"
        confirmLabel="Remove" cancelLabel="Keep copy" busy={transfers.busy} onCancel={() => setRemoving(null)}
        onConfirm={async () => { await transfers.remove(removing); setRemoving(null); }}
        message={`${removing.aircraftLabel} · Log ${removing.logId}. The aircraft original and files on your device stay available.`} />}
    </div>
  );
}

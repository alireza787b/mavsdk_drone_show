import React, { useEffect, useRef, useState } from 'react';
import { ConfirmDialog } from '../ui';
import { buildDroneUlogDownloadURL } from '../../services/logService';
import { ULOG_TERMINAL } from '../../features/log-workspace/useUlogTransfers';

export default function UlogTransferActivity({ transfers, userRole, now }) {
  const [remove, setRemove] = useState(null);
  const panel = useRef(null), latestRequest = transfers.records[0]?.requestId;
  const allowed = ['operator', 'admin'].includes(userRole);
  const uncertain = transfers.records.some(item => item.error);
  useEffect(() => { if (panel.current && (latestRequest || transfers.error || uncertain)) panel.current.open = true; }, [latestRequest, transfers.error, uncertain]);
  return <details ref={panel} className="logs-transfer-activity"><summary>Transfers · {transfers.records.length}{transfers.pending ? ' · active or unconfirmed' : ''}</summary>
    {transfers.error && <p className="logs-inline-warning" role="alert">{transfers.error}</p>}
    {transfers.records.map(record => {
      const expired = record.job?.expires_at && now >= record.job.expires_at;
      const status = expired ? 'expired' : record.job?.status;
      const label = record.creationStatus === 'rejected' ? 'Not started' : record.error ? 'Outcome unconfirmed' : ({ ready: 'Ready to save', queued: 'Preparing', downloading: 'Preparing', failed: 'Failed', expired: 'Expired', deleted: 'Staged copy removed' }[status] || 'Creation unconfirmed');
      return <section key={record.requestId} className="logs-transfer-row"><div><strong>{label}</strong><span>{record.aircraftLabel} · log {record.logId}</span></div>
        {record.job?.progress != null && !ULOG_TERMINAL.has(status) && <progress value={record.job.progress} max="1" aria-label="Observed transfer progress" />}
        {record.error && <p className="logs-inline-warning">{record.error}</p>}{record.job?.error && <p>{record.job.error}</p>}
        <div className="logs-inline-actions"><button type="button" className="operator-button operator-button--ghost" onClick={() => transfers.check(record)}>Check receipt</button>
          {status === 'ready' && allowed && <a className="operator-button operator-button--primary" href={buildDroneUlogDownloadURL(record.droneId, record.job.job_id)} download={record.job.download_filename || `mds-ulog-H${record.droneId}-${record.logId}.ulg`}
            onClick={() => transfers.browserRequested(record)}>Save file</a>}
          {record.job?.job_id && ULOG_TERMINAL.has(status) && status !== 'deleted' && allowed && <button type="button" className="operator-button operator-button--ghost" disabled={transfers.busy} onClick={() => setRemove(record)}>Remove staged copy</button>}
        </div>{record.browserRequestedAt && <p className="logs-context">Browser download requested · local save is not verified.</p>}
      </section>;
    })}
    {remove && <ConfirmDialog appearance="console" open title="Remove staged copy?" confirmLabel="Remove copy" busy={transfers.busy} onCancel={() => setRemove(null)} onConfirm={async () => { await transfers.remove(remove); setRemove(null); }}
      message={`${remove.aircraftLabel} · log ${remove.logId}. This removes the prepared transfer copy, not the onboard original.`} />}
  </details>;
}

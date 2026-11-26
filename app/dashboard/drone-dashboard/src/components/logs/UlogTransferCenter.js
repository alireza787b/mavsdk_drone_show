import React, { useCallback, useEffect, useRef, useState } from 'react';
import { getBackendURL } from '../../config/apiConfig';
import { getDroneUlogSummary, getVerifiedUlogSummary, summarizeUploadedUlog } from '../../services/logService';
import { UlogTransferContext } from '../../features/log-workspace/UlogTransferContext';
import useUlogTransfers, { transferStatus } from '../../features/log-workspace/useUlogTransfers';
import { logError } from '../../features/log-workspace/logWorkspace';
import UlogTransferActivity, { transferLabel } from './UlogTransferActivity';
import UlogSummary from './UlogSummary';
import '../../styles/UlogTransfers.css';

export function UlogTransferProvider({ runtimeMode, operatorId, children }) {
  const transfers = useUlogTransfers(`mds:ulog-transfers:v1:${getBackendURL()}:${runtimeMode}:${operatorId || 'browser-session'}`);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(null);
  const [summary, setSummary] = useState(null);
  const [now, setNow] = useState(Date.now);
  const ongoingSummary = useRef(null);
  const requestedSummaries = useRef(new Set());
  const hasRecords = transfers.records.length > 0;
  useEffect(() => {
    if (!hasRecords) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 2000);
    return () => clearInterval(timer);
  }, [hasRecords]);

  const readSummary = useCallback(async (label, load, requestId = null, show = true) => {
    if (ongoingSummary.current) return;
    ongoingSummary.current = load;
    if (show) setOpen(true);
    setSummary({ label, requestId, busy: true });
    try {
      const data = await load();
      setSummary({ label, requestId, data });
    } catch (failure) {
      setSummary({ label, requestId, error: logError(failure), retry: load });
    } finally {
      ongoingSummary.current = null;
    }
  }, []);

  const analyzeTransfer = record => {
    setSelected(record.requestId);
    setOpen(true);
    if (transferStatus(record) === 'ready' && record.verified) {
      requestedSummaries.current.add(record.requestId);
      if (summary?.requestId !== record.requestId || summary.error) {
        readSummary(`${record.aircraftLabel} · Log ${record.logId}`,
          () => getVerifiedUlogSummary(record.droneId, record.job.job_id), record.requestId);
      }
    } else {
      transfers.wantSummary(record);
    }
  };

  const report = transfers.records.find(record => record.requestId === selected)
    || transfers.records.find(record => record.wantsSummary && record.verified && transferStatus(record, now) === 'ready');
  useEffect(() => {
    if (!report?.wantsSummary || !report.verified || transferStatus(report, now) !== 'ready'
        || ongoingSummary.current || requestedSummaries.current.has(report.requestId)) return;
    requestedSummaries.current.add(report.requestId);
    readSummary(`${report.aircraftLabel} · Log ${report.logId}`,
      () => getVerifiedUlogSummary(report.droneId, report.job.job_id), report.requestId, false);
  }, [report, now, summary, readSummary]);

  const start = async input => {
    setOpen(true);
    const existing = transfers.records.find(record => record.verified
      && record.droneId === String(input.droneId) && record.logId === input.logId
      && record.logDate === input.logDate
      && (['queued', 'downloading', 'ready'].includes(transferStatus(record))
        || (!record.job && record.creationStatus !== 'rejected')));
    if (existing) {
      setSelected(existing.requestId);
      if (input.wantsSummary) analyzeTransfer(existing);
      return;
    }
    setSelected(null);
    const requestId = await transfers.prepare({ ...input, verified: true });
    if (requestId) setSelected(previous => previous || requestId);
  };

  const value = {
    ...transfers, open, setOpen, selected, setSelected, summary, now,
    start, analyzeTransfer,
    analyzeOnboard: (droneId, logId, label) => readSummary(label, () => getDroneUlogSummary(droneId, logId)),
    analyzeLocal: file => readSummary(file.name, () => summarizeUploadedUlog(file)),
    retrySummary: () => readSummary(summary.label, summary.retry, summary.requestId),
    closeSummary: () => setSummary(null),
  };
  return <UlogTransferContext.Provider value={value}>{children}</UlogTransferContext.Provider>;
}

export function UlogTransferCenter({ userRole }) {
  const transfers = React.useContext(UlogTransferContext);
  const { records, selected, now, summary, open, error, setOpen } = transfers;
  const focused = records.find(record => record.requestId === selected);
  const current = focused || records.find(record => !['expired', 'deleted'].includes(transferStatus(record, now)));
  if (!records.length && !summary && !error && !open) return null;
  const state = summary?.busy ? 'Reading summary' : current ? transferLabel(current, now) : null;
  return (
    <div className="ulog-center">
      <button type="button" className="operator-button operator-button--ghost ulog-center__toggle"
        aria-expanded={open} aria-controls="ulog-transfer-panel" onClick={() => setOpen(!open)}>
        ULog transfers {state && <span aria-hidden="true">· {state}{current?.job?.status === 'downloading' && current.job.progress > 0
          ? ` ${Math.floor(current.job.progress * 100)}%` : ''}</span>}
      </button>
      {open && <section id="ulog-transfer-panel" className="ulog-center__panel operator-console" aria-label="ULog transfers">
        {summary && <section className="ulog-center__summary">
          <div className="ulog-center__heading">
            <strong>{summary.label}</strong>
            {!summary.busy && <button type="button" className="operator-button operator-button--ghost" onClick={transfers.closeSummary}>Close summary</button>}
          </div>
          {summary.busy && <p role="status">Reading summary…</p>}
          {summary.error && <div role="alert"><p>{summary.error}</p>
            <button type="button" className="operator-button operator-button--ghost" onClick={transfers.retrySummary}>Retry summary</button>
          </div>}
          {summary.data && <UlogSummary summary={summary.data} />}
        </section>}
        <UlogTransferActivity transfers={transfers} userRole={userRole} now={now} />
      </section>}
    </div>
  );
}

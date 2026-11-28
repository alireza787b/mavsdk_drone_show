import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FiHardDrive, FiX } from 'react-icons/fi';
import { ActionIconButton } from '../ui';
import { getBackendURL } from '../../config/apiConfig';
import { getDroneUlogSummary, getVerifiedUlogSummary, summarizeUploadedUlog } from '../../services/logService';
import { UlogTransferContext } from '../../features/log-workspace/UlogTransferContext';
import useUlogTransfers, { transferPending, transferStatus } from '../../features/log-workspace/useUlogTransfers';
import { logError } from '../../features/log-workspace/logWorkspace';
import UlogTransferActivity, { transferLabel } from './UlogTransferActivity';
import UlogSummary from './UlogSummary';
import '../../styles/UlogTransfers.css';

// The recovery ledger holds up to 32 entries and the GCS keeps up to 128 copies.
const MAX_DISMISSED_NOTICES = 160;
const noticeId = record => `${record.requestId}:${record.creationStatus === 'rejected' ? 'rejected' : record.job?.status}`;

function readDismissedNotices(key) {
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(saved)
      ? saved.slice(-MAX_DISMISSED_NOTICES).filter(item => typeof item === 'string')
      : [];
  } catch {
    return [];
  }
}

export function UlogTransferProvider({ runtimeMode, operatorId, userRole, children }) {
  const storageKey = `mds:ulog-transfers:v1:${getBackendURL()}:${runtimeMode}:${operatorId || 'browser-session'}`;
  const noticeKey = `${storageKey}:dismissed-notices`;
  const transfers = useUlogTransfers(storageKey, ['operator', 'admin'].includes(userRole));
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(null);
  const [summary, setSummary] = useState(null);
  const [summaryDismissed, setSummaryDismissed] = useState(false);
  const [dismissedRecords, setDismissedRecords] = useState(() => new Set(readDismissedNotices(noticeKey)));
  const [now, setNow] = useState(Date.now);
  const ongoingSummary = useRef(null);
  const requestedSummaries = useRef(new Set());
  useEffect(() => {
    const sync = event => {
      if (!event || event.key === noticeKey || event.key === null) {
        setDismissedRecords(new Set(readDismissedNotices(noticeKey)));
      }
    };
    sync();
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, [noticeKey]);

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
    setSummaryDismissed(false);
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

  const report = transfers.records.find(record => record.requestId === selected && !dismissedRecords.has(noticeId(record)))
    || transfers.records.find(record => record.wantsSummary && record.verified && transferStatus(record, now) === 'ready'
      && !dismissedRecords.has(noticeId(record)));
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

  const openTransfers = () => {
    transfers.refreshSaved();
    setOpen(true);
  };

  const dismissNotices = settled => {
    if (settled.length) {
      const current = new Set(settled.map(noticeId));
      const prior = new Set([...dismissedRecords, ...readDismissedNotices(noticeKey)]);
      const next = [...Array.from(prior).filter(id => !current.has(id)), ...current].slice(-MAX_DISMISSED_NOTICES);
      try {
        localStorage.setItem(noticeKey, JSON.stringify(next));
      } catch {
        // Keep the dismissal for this session if the browser blocks storage.
      }
      setDismissedRecords(new Set(next));
    }
    if (summary && !summary.busy) setSummaryDismissed(true);
    transfers.clearError();
    setOpen(false);
  };

  const value = {
    ...transfers, open, setOpen, selected, setSelected, summary, now,
    start, analyzeTransfer, openTransfers, dismissNotices, dismissedRecords, summaryDismissed,
    analyzeOnboard: (droneId, logId, label) => readSummary(label, () => getDroneUlogSummary(droneId, logId)),
    analyzeLocal: file => readSummary(file.name, () => summarizeUploadedUlog(file)),
    retrySummary: () => readSummary(summary.label, summary.retry, summary.requestId),
    closeSummary: () => setSummary(null),
  };
  return <UlogTransferContext.Provider value={value}>{children}</UlogTransferContext.Provider>;
}

export function UlogTransferCenter({ userRole }) {
  const transfers = React.useContext(UlogTransferContext);
  const { records, selected, now, summary, open, error, setOpen, openTransfers, dismissedRecords, summaryDismissed } = transfers;
  const toggleRef = useRef(null);
  const visible = records.filter(record => transferStatus(record, now) !== 'deleted');
  const pending = visible.filter(transferPending);
  const settled = visible.filter(record => !transferPending(record));
  const notices = settled.filter(record => !dismissedRecords.has(noticeId(record)));
  const summaryNotice = summaryDismissed ? null : summary;
  if (!pending.length && !notices.length && !summaryNotice && !error && !open) return null;
  const current = pending.find(record => record.requestId === selected) || pending[0]
    || notices.find(record => record.requestId === selected) || notices[0];
  const state = (summaryNotice?.busy && 'Reading summary') || (current && transferLabel(current, now))
    || (summaryNotice?.error && 'Summary unavailable') || (error && 'Transfer issue');
  const canDismiss = notices.length > 0 || error || (summaryNotice && !summaryNotice.busy);
  return (
    <div className="ulog-center">
      <div className="ulog-center__toolbar">
        <button ref={toggleRef} type="button" className="operator-button operator-button--ghost ulog-center__toggle"
          aria-label="ULog transfers" aria-expanded={open} aria-controls="ulog-transfer-panel"
          aria-describedby={state ? 'ulog-transfer-status' : undefined} onClick={open ? () => setOpen(false) : openTransfers}>
          <FiHardDrive aria-hidden="true" /> Log transfers {state && <span id="ulog-transfer-status">· {state}{!summaryNotice?.busy && current?.job?.status === 'downloading' && current.job.progress > 0
            ? ` ${Math.floor(current.job.progress * 100)}%` : ''}</span>}
        </button>
        {canDismiss && <ActionIconButton className="ulog-center__dismiss" icon={<FiX />} label="Dismiss transfer notice" title="Dismiss transfer notice"
          onClick={() => {
            if (pending.length || summaryNotice?.busy) toggleRef.current?.focus();
            transfers.dismissNotices(settled);
          }} />}
      </div>
      {open && <section id="ulog-transfer-panel" className="ulog-center__panel operator-console" aria-label="ULog transfers">
        {summary && <section className="ulog-center__summary">
          <div className="ulog-center__heading">
            <strong>{summary.label}</strong>
            {!summary.busy && <ActionIconButton icon={<FiX />} label="Close summary" title="Close summary" onClick={transfers.closeSummary} />}
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

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FiDownloadCloud, FiFileText, FiFolder, FiHardDrive, FiRefreshCw } from 'react-icons/fi';
import { ActionIconButton, ConfirmDialog, OperatorNotice, PageActionBar } from '../ui';
import { getDroneUlogFiles, getDroneUlogPolicy, eraseAllDroneUlogs } from '../../services/logService';
import { formatBytes } from '../../utilities/logViewerUtils';
import { logError, recordTime } from '../../features/log-workspace/logWorkspace';
import { transferPending, transferStatus } from '../../features/log-workspace/useUlogTransfers';
import { UlogSaveLink } from './UlogTransferActivity';

export default function FlightLogsWorkspace({ droneId, sourceLabel, userRole, transfers }) {
  const [files, setFiles] = useState([]), [policy, setPolicy] = useState(null), [capability, setCapability] = useState(null);
  const [status, setStatus] = useState('idle'), [error, setError] = useState('');
  const [inventoryObserved, setInventoryObserved] = useState(false);
  const [erase, setErase] = useState(null), [eraseText, setEraseText] = useState(''), [eraseBusy, setEraseBusy] = useState(false), [eraseNotice, setEraseNotice] = useState('');
  const fileInput = useRef(null), generation = useRef(0), eraseLock = useRef(false), mounted = useRef(true);
  const canTransfer = ['operator', 'admin'].includes(userRole);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current += 1; }; }, []);
  useEffect(() => { setFiles([]); setInventoryObserved(false); setPolicy(null); setCapability(null); setError(''); }, [droneId]);
  const refresh = useCallback(async () => {
    if (droneId == null) return;
    const token = ++generation.current;
    setStatus('loading'); setError('');
    const [catalog, settings] = await Promise.allSettled([getDroneUlogFiles(droneId), getDroneUlogPolicy(droneId)]);
    if (!mounted.current || token !== generation.current) return;
    if (catalog.status === 'fulfilled') {
      setFiles(catalog.value.files || []); setInventoryObserved(true); setStatus('loaded');
      setCapability(catalog.value.ulog_capability || (settings.status === 'fulfilled' ? settings.value.ulog_capability : null));
    } else { setStatus('stale'); setError(logError(catalog.reason)); }
    if (settings.status === 'fulfilled') setPolicy(settings.value.policy || null);
    else { setPolicy(null); setError(previous => [previous, `Policy: ${logError(settings.reason)}`].filter(Boolean).join(' · ')); }
  }, [droneId]);
  useEffect(() => { refresh(); }, [refresh]);
  const prepare = (file, wantsSummary) => transfers.start({
    droneId, logId: file.id, aircraftLabel: sourceLabel, logDate: file.date_utc,
    expectedSize: file.size_bytes, wantsSummary,
  });
  const openFile = event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) transfers.analyzeLocal(file);
  };
  const summaryBusy = Boolean(transfers.summary?.busy);
  const activeTransfer = transfers.records.find(record => record.droneId === String(droneId) && transferPending(record));
  const canPrepare = canTransfer && policy?.download_supported && capability?.available !== false && status === 'loaded';
  const eraseAll = async () => {
    if (!erase || eraseLock.current || userRole !== 'admin' || eraseText !== `ERASE H${erase.droneId}`) return;
    eraseLock.current = true; setEraseBusy(true); setEraseNotice('');
    try {
      await eraseAllDroneUlogs(erase.droneId);
      if (!mounted.current) return;
      setEraseNotice(`Erase request accepted for ${erase.label}. Empty inventory has not been verified.`);
      setErase(null); await refresh();
    } catch (failure) { if (mounted.current) setError(`Erase outcome not confirmed: ${logError(failure)} Refresh inventory before any further maintenance.`); }
    finally { eraseLock.current = false; if (mounted.current) setEraseBusy(false); }
  };
  return <section className="logs-flight" aria-label="Flight logs">
    <div className="logs-flight-toolbar"><span>{droneId == null ? 'Choose an aircraft' : status === 'loading' ? 'Loading logs…'
      : status === 'stale' ? 'Aircraft logs unavailable' : inventoryObserved ? `${files.length} logs` : ''}</span>
      <PageActionBar primary={[
        (canTransfer || transfers.summary) && <ActionIconButton key="transfers" icon={<FiHardDrive />} label="Log transfers"
          aria-controls="ulog-transfer-panel" aria-expanded={Boolean(transfers.open)}
          onClick={transfers.open ? () => transfers.setOpen(false) : transfers.openTransfers}>Log transfers</ActionIconButton>,
        <ActionIconButton key="refresh" icon={<FiRefreshCw />} label="Refresh logs" title="Refresh logs"
          disabled={droneId == null || status === 'loading'} onClick={refresh} />,
      ]}
        secondary={<ActionIconButton icon={<FiFolder />} label="Open file" disabled={summaryBusy}
          onClick={() => fileInput.current?.click()}>Open file</ActionIconButton>} />
      <input ref={fileInput} type="file" accept=".ulg" aria-label="Open local ULog file" className="logs-visually-hidden" onChange={openFile} />
    </div>
    {error && <OperatorNotice tone="warning" title="Flight-log request unavailable">{error}</OperatorNotice>}
    {eraseNotice && <OperatorNotice tone="info" title="Maintenance observation">{eraseNotice}</OperatorNotice>}
    {capability?.available === false && <OperatorNotice tone="neutral" title="Onboard recorder access unavailable">{capability.detail || 'No supported file-backed recorder access was reported.'}</OperatorNotice>}
    <div className="logs-file-list">
      {files.map(file => {
        const otherTransferActive = activeTransfer && activeTransfer.logId !== file.id;
        const ready = transfers.records.find(record => record.verified && record.droneId === String(droneId)
          && record.logId === file.id && record.logDate === file.date_utc && transferStatus(record) === 'ready');
        return (
          <article className="logs-file-row" key={file.id}>
            <div className="logs-file-meta">
              <strong>Log {file.id}</strong>
              <time>{recordTime(file.date_utc)}</time>
              <span>{Number.isFinite(file.size_bytes) ? formatBytes(file.size_bytes) : 'Size unknown'}</span>
            </div>
            <div className="logs-file-actions">
              {canTransfer && (ready ? <UlogSaveLink record={ready} onSave={transfers.browserRequested} />
                : <ActionIconButton icon={<FiDownloadCloud />} tone="info" label={`Get log ${file.id}`}
                  title="Copy to GCS" disabled={!canPrepare || transfers.busy || otherTransferActive}
                  onClick={() => prepare(file, false)}>Get log</ActionIconButton>)}
              <ActionIconButton icon={<FiFileText />} label={`View summary for log ${file.id}`}
                disabled={ready ? summaryBusy : canTransfer ? !canPrepare || transfers.busy || otherTransferActive : summaryBusy || status !== 'loaded'}
                onClick={() => canTransfer ? ready ? transfers.analyzeTransfer(ready) : prepare(file, true)
                  : transfers.analyzeOnboard(droneId, file.id, `${sourceLabel} · Log ${file.id}`)}>
                Summary
              </ActionIconButton>
            </div>
          </article>
        );
      })}
      {!files.length && status !== 'loading' && status !== 'stale' && droneId != null && <p className="logs-empty">No logs reported.</p>}
    </div>
    {userRole === 'admin' && <details className="logs-details"><summary>Maintenance</summary><button type="button" className="operator-button operator-button--danger" disabled={!files.length || status !== 'loaded' || !policy?.erase_all_supported || transfers.pending || transfers.busy || eraseBusy}
      onClick={() => { setErase({ droneId, label: sourceLabel, count: files.length }); setEraseText(''); }}>Erase onboard logs</button></details>}
    {erase && <ConfirmDialog appearance="console" open tone="danger" title="Erase onboard logs?" cancelLabel="Cancel" confirmLabel="Erase onboard logs" busy={eraseBusy} onCancel={() => setErase(null)} onConfirm={eraseAll}
      confirmDisabled={eraseText !== `ERASE H${erase.droneId}` || userRole !== 'admin' || transfers.pending || transfers.busy}
      message={<div><p>{erase.label} · all onboard recorder files ({erase.count} in the reviewed inventory).</p><p>This removes onboard originals, not browser rows or staged copies. It cannot be undone here.</p>
        <label>Type ERASE H{erase.droneId}<input aria-label="Confirm aircraft erase" value={eraseText} onChange={event => setEraseText(event.target.value)} /></label></div>} />}
  </section>;
}

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  FaCheckCircle,
  FaCloudDownloadAlt,
  FaExclamationTriangle,
  FaRedoAlt,
  FaShieldAlt,
  FaSpinner,
  FaTrashAlt,
} from 'react-icons/fa';
import ConfirmationDialog from '../ConfirmationDialog';
import {
  buildDroneUlogDownloadURL,
  createDroneUlogDownloadJob,
  eraseAllDroneUlogs,
  getDroneUlogDownloadJob,
  getDroneUlogFiles,
  getDroneUlogPolicy,
} from '../../services/logService';
import { formatBytes } from '../../utilities/logViewerUtils';

const POLL_INTERVAL_MS = 1200;

const formatUlogTimestamp = (value) => {
  if (!value) {
    return 'Unknown flight time';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  }).format(date) + ' UTC';
};

const getErrorMessage = (error, fallback) => (
  error?.response?.data?.detail
  || error?.message
  || fallback
);

const OnboardUlogDialog = ({
  open,
  onClose,
  droneId,
  scopeLabel,
}) => {
  const [loading, setLoading] = useState(false);
  const [files, setFiles] = useState([]);
  const [policy, setPolicy] = useState(null);
  const [statusNotice, setStatusNotice] = useState(null);
  const [activeJob, setActiveJob] = useState(null);
  const [confirmErase, setConfirmErase] = useState(false);
  const downloadTriggeredRef = useRef(null);

  const loadCatalog = useCallback(async ({ preserveNotice = false } = {}) => {
    if (!droneId) {
      return;
    }

    setLoading(true);
    try {
      const [policyResponse, filesResponse] = await Promise.all([
        getDroneUlogPolicy(droneId),
        getDroneUlogFiles(droneId),
      ]);
      setPolicy(policyResponse.policy || null);
      setFiles(filesResponse.files || []);
      if (!preserveNotice) {
        setStatusNotice(null);
      }
    } catch (error) {
      setStatusNotice({
        tone: 'error',
        text: getErrorMessage(error, 'Failed to load onboard ULog catalog.'),
      });
    } finally {
      setLoading(false);
    }
  }, [droneId]);

  useEffect(() => {
    if (!open) {
      setFiles([]);
      setPolicy(null);
      setActiveJob(null);
      setStatusNotice(null);
      setConfirmErase(false);
      downloadTriggeredRef.current = null;
      return undefined;
    }

    loadCatalog();
    return undefined;
  }, [open, loadCatalog]);

  useEffect(() => {
    if (!open || !droneId || !activeJob?.job_id) {
      return undefined;
    }

    if (activeJob.status === 'ready' || activeJob.status === 'failed') {
      return undefined;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const response = await getDroneUlogDownloadJob(droneId, activeJob.job_id);
        if (cancelled) {
          return;
        }
        const nextJob = response.job;
        setActiveJob(nextJob);

        if (nextJob.status === 'ready' && downloadTriggeredRef.current !== nextJob.job_id) {
          downloadTriggeredRef.current = nextJob.job_id;
          const link = document.createElement('a');
          link.href = buildDroneUlogDownloadURL(droneId, nextJob.job_id);
          link.download = nextJob.download_filename || `mds-ulog_H${droneId}.ulg`;
          link.rel = 'noopener';
          document.body.appendChild(link);
          link.click();
          link.remove();
          setStatusNotice({
            tone: 'success',
            text: `Download ready for ${scopeLabel}. Browser transfer started.`,
          });
          loadCatalog({ preserveNotice: true });
        } else if (nextJob.status === 'failed') {
          setStatusNotice({
            tone: 'error',
            text: nextJob.error || 'Onboard ULog download failed.',
          });
        }
      } catch (error) {
        if (!cancelled) {
          setStatusNotice({
            tone: 'error',
            text: getErrorMessage(error, 'Failed to refresh onboard ULog download status.'),
          });
        }
      }
    };

    poll();
    const timer = window.setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeJob, droneId, loadCatalog, open, scopeLabel]);

  const handleStartDownload = useCallback(async (entry) => {
    if (!droneId) {
      return;
    }

    setStatusNotice({
      tone: 'info',
      text: `Preparing onboard ULog ${entry.id} from ${scopeLabel}.`,
    });
    try {
      const response = await createDroneUlogDownloadJob(droneId, entry.id);
      downloadTriggeredRef.current = null;
      setActiveJob(response.job);
    } catch (error) {
      setStatusNotice({
        tone: 'error',
        text: getErrorMessage(error, 'Failed to start onboard ULog download.'),
      });
    }
  }, [droneId, scopeLabel]);

  const handleEraseAll = useCallback(async () => {
    if (!droneId) {
      return;
    }

    setConfirmErase(false);
    setStatusNotice({
      tone: 'info',
      text: `Erasing onboard PX4 ULogs for ${scopeLabel}.`,
    });
    try {
      await eraseAllDroneUlogs(droneId);
      setActiveJob(null);
      await loadCatalog({ preserveNotice: true });
      setStatusNotice({
        tone: 'success',
        text: `All onboard PX4 ULogs were erased for ${scopeLabel}.`,
      });
    } catch (error) {
      setStatusNotice({
        tone: 'error',
        text: getErrorMessage(error, 'Failed to erase onboard PX4 ULogs.'),
      });
    }
  }, [droneId, loadCatalog, scopeLabel]);

  const policyChips = useMemo(() => {
    if (!policy) {
      return [];
    }

    const chips = [];
    if (policy.download_requires_disarmed) {
      chips.push('Download requires disarmed');
    }
    if (policy.erase_requires_disarmed) {
      chips.push('Erase requires disarmed');
    }
    if (!policy.single_delete_supported) {
      chips.push('Single-file delete unavailable');
    }
    return chips;
  }, [policy]);

  if (!open) {
    return null;
  }

  const transferBusy = activeJob && activeJob.status !== 'ready' && activeJob.status !== 'failed';

  return (
    <>
      <div className="log-export-overlay" onClick={onClose}>
        <div
          className="log-export-dialog onboard-ulog-dialog"
          onClick={(event) => event.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="onboard-ulog-dialog-title"
        >
          <div className="onboard-ulog-dialog__header">
            <div>
              <h3 id="onboard-ulog-dialog-title">Onboard ULog</h3>
              <p className="onboard-ulog-dialog__subtitle">
                File-backed PX4 logs for <strong>{scopeLabel}</strong>
              </p>
            </div>
            <div className="onboard-ulog-dialog__actions">
              <button type="button" onClick={() => loadCatalog()} disabled={loading}>
                {loading ? <FaSpinner className="spin" size={12} /> : <FaRedoAlt size={12} />}
                Refresh
              </button>
              <button
                type="button"
                onClick={() => setConfirmErase(true)}
                disabled={loading || files.length === 0 || transferBusy}
              >
                <FaTrashAlt size={12} />
                Erase all
              </button>
            </div>
          </div>

          <div className="onboard-ulog-dialog__summary">
            <span className="log-context-pill">{scopeLabel}</span>
            <span className="onboard-ulog-dialog__summary-text">{files.length} file{files.length === 1 ? '' : 's'}</span>
            {policyChips.map((chip) => (
              <span key={chip} className="onboard-ulog-dialog__policy-chip">
                <FaShieldAlt size={10} />
                {chip}
              </span>
            ))}
          </div>

          {statusNotice && (
            <div className={`onboard-ulog-dialog__notice onboard-ulog-dialog__notice--${statusNotice.tone}`}>
              {statusNotice.tone === 'error' ? <FaExclamationTriangle size={12} /> : null}
              {statusNotice.tone === 'success' ? <FaCheckCircle size={12} /> : null}
              {statusNotice.tone === 'info' ? <FaSpinner className={transferBusy ? 'spin' : ''} size={12} /> : null}
              <span>{statusNotice.text}</span>
            </div>
          )}

          {activeJob && (
            <div className="onboard-ulog-dialog__job-card">
              <div className="onboard-ulog-dialog__job-head">
                <strong>{activeJob.download_filename || `ULog ${activeJob.log_id}`}</strong>
                <span className={`onboard-ulog-dialog__job-status onboard-ulog-dialog__job-status--${activeJob.status}`}>
                  {activeJob.status}
                </span>
              </div>
              <div className="onboard-ulog-dialog__job-meta">
                <span>Log #{activeJob.log_id}</span>
                <span>{formatBytes(activeJob.size_bytes)}</span>
              </div>
              <div className="onboard-ulog-dialog__progress-track" aria-hidden="true">
                <div
                  className="onboard-ulog-dialog__progress-fill"
                  style={{ width: `${Math.max(4, Math.round((activeJob.progress || 0) * 100))}%` }}
                />
              </div>
            </div>
          )}

          <div className="onboard-ulog-dialog__list">
            {files.length === 0 ? (
              <div className="onboard-ulog-dialog__empty">
                {loading ? 'Loading onboard ULog catalog…' : 'No onboard PX4 ULogs available for this drone.'}
              </div>
            ) : (
              files.map((entry) => (
                <div key={entry.id} className="onboard-ulog-dialog__row">
                  <div className="onboard-ulog-dialog__row-main">
                    <strong>{formatUlogTimestamp(entry.date_utc)}</strong>
                    <div className="onboard-ulog-dialog__row-meta">
                      <span>Log #{entry.id}</span>
                      <span>{formatBytes(entry.size_bytes)}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="onboard-ulog-dialog__download-button"
                    onClick={() => handleStartDownload(entry)}
                    disabled={loading || transferBusy}
                  >
                    <FaCloudDownloadAlt size={12} />
                    Download
                  </button>
                </div>
              ))
            )}
          </div>

          {policy?.notes?.length ? (
            <div className="onboard-ulog-dialog__notes">
              {policy.notes.map((note) => (
                <p key={note}>{note}</p>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <ConfirmationDialog
        isOpen={confirmErase}
        message={`Erase all onboard PX4 ULogs for ${scopeLabel}? This cannot be undone from the dashboard.`}
        onConfirm={handleEraseAll}
        onCancel={() => setConfirmErase(false)}
      />
    </>
  );
};

export default OnboardUlogDialog;

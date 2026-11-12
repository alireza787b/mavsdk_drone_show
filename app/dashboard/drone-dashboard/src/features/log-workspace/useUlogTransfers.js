import { useCallback, useEffect, useRef, useState } from 'react';
import { createDroneUlogDownloadJob, getDroneUlogDownloadJob, getDroneUlogDownloadRequest, deleteDroneUlogDownloadJob } from '../../services/logService';
import { logError } from './logWorkspace';

export const ULOG_TERMINAL = new Set(['ready', 'failed', 'expired', 'deleted']);
export const transferPending = record => !record.job || !ULOG_TERMINAL.has(record.job.status);
const read = key => {
  const records = JSON.parse(localStorage.getItem(key) || '[]');
  if (!Array.isArray(records) || records.length > 32 || records.some(item => typeof item.requestId !== 'string'
    || typeof item.droneId !== 'string' || item.logId == null)) throw new Error('Transfer recovery records are unreadable.');
  return records;
};
const compact = record => ({ ...record, job: record.job ? Object.fromEntries(['job_id', 'status', 'log_id', 'hw_id', 'size_bytes', 'progress',
  'download_filename', 'created_at', 'updated_at', 'expires_at', 'error'].filter(key => record.job[key] !== undefined).map(key => [key, record.job[key]])) : null });

function requestId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  if (!window.crypto?.getRandomValues) throw new Error('This browser cannot create a recovery identity.');
  const bytes = window.crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export default function useUlogTransfers(storageKey) {
  const [records, setRecords] = useState([]), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const latest = useRef(records), lock = useRef(false), activeKey = useRef(storageKey), mounted = useRef(true);
  latest.current = records; activeKey.current = storageKey;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    try { const saved = read(storageKey); latest.current = saved; setRecords(saved); setError(''); }
    catch (failure) { setRecords([]); setError(logError(failure)); }
  }, [storageKey]);
  const persist = useCallback((record, key = storageKey, required = false) => {
    let next;
    try {
      const saved = read(key);
      const prior = saved.find(item => item.requestId === record.requestId);
      if (prior?.job && (!record.job || (ULOG_TERMINAL.has(prior.job.status) && !ULOG_TERMINAL.has(record.job.status))
        || (Number(prior.job.updated_at) > Number(record.job.updated_at)))) record = { ...record, job: prior.job };
      next = [compact(record), ...saved.filter(item => item.requestId !== record.requestId)];
      while (next.length > 32) {
        const index = next.map(item => !transferPending(item)).lastIndexOf(true);
        if (index <= 0) throw new Error('Resolve existing transfers before preparing another.');
        next.splice(index, 1);
      }
      const json = JSON.stringify(next); localStorage.setItem(key, json);
      if (localStorage.getItem(key) !== json) throw new Error('Recovery identity was not saved.');
    } catch (failure) {
      if (required) throw failure;
      next = [compact(record), ...latest.current.filter(item => item.requestId !== record.requestId)];
      if (mounted.current && activeKey.current === key) setError(`Recovery storage: ${logError(failure)}`);
    }
    if (mounted.current && activeKey.current === key) { latest.current = next; setRecords(next); }
    return next;
  }, [storageKey]);
  const inspectJob = (job, record) => {
    if (!job?.job_id || (job.hw_id != null && String(job.hw_id) !== record.droneId)
      || (job.log_id != null && String(job.log_id) !== String(record.logId))) throw new Error('Transfer identity does not match the selected aircraft and file.');
    return job;
  };
  const check = useCallback(async (record, key = storageKey) => {
    try {
      const response = record.job?.job_id ? await getDroneUlogDownloadJob(record.droneId, record.job.job_id)
        : await getDroneUlogDownloadRequest(record.droneId, record.requestId);
      if (response.request_id && response.request_id !== record.requestId) throw new Error('Recovery identity mismatch.');
      const job = response.job ? inspectJob(response.job, record) : null;
      persist({ ...record, job: job || record.job, error: job ? '' : response.error || 'Creation outcome remains unconfirmed. Do not submit again.' }, key);
    } catch (failure) {
      persist({ ...record, error: failure?.response?.status === 404 ? 'Handle unavailable for this actor or expired. Creation outcome is not proven absent; do not resend.' : logError(failure) }, key);
    }
  }, [persist, storageKey]);
  useEffect(() => {
    let active = true, timer;
    const poll = async () => {
      for (const record of latest.current.filter(item => transferPending(item) && !item.error)) {
        if (!active) return;
        await check(record, storageKey);
      }
      if (active) timer = setTimeout(poll, 1500);
    };
    timer = setTimeout(poll, 1500);
    return () => { active = false; clearTimeout(timer); };
  }, [storageKey, check]);
  const prepare = async ({ droneId, logId, aircraftLabel }) => {
    if (lock.current) return false;
    lock.current = true; setBusy(true); setError('');
    const key = storageKey; let record;
    try {
      const existing = read(key);
      if (existing.some(item => transferPending(item))) throw new Error('Check the active or unconfirmed transfer before preparing another.');
      record = { requestId: requestId(), droneId: String(droneId), logId, aircraftLabel, createdAt: Date.now(), job: null, error: '', browserRequestedAt: null };
      persist(record, key, true);
    } catch (failure) { setError(`Not sent: ${logError(failure)}`); lock.current = false; setBusy(false); return false; }
    try {
      const response = await createDroneUlogDownloadJob(record.droneId, record.logId, { requestId: record.requestId });
      if (response.request_id && response.request_id !== record.requestId) throw new Error('Transfer request identity mismatch.');
      persist({ ...record, job: inspectJob(response.job, record) }, key);
    } catch (failure) { persist({ ...record, error: `Outcome unconfirmed: ${logError(failure)} Check receipt; do not submit again.` }, key); }
    finally { lock.current = false; if (mounted.current && activeKey.current === key) setBusy(false); }
    return true;
  };
  const remove = async record => {
    if (lock.current || !record.job?.job_id || !ULOG_TERMINAL.has(record.job.status)) return;
    lock.current = true; setBusy(true);
    try { await deleteDroneUlogDownloadJob(record.droneId, record.job.job_id); persist({ ...record, job: { ...record.job, status: 'deleted' }, error: '' }); }
    catch (failure) { setError(logError(failure)); }
    finally { lock.current = false; setBusy(false); }
  };
  return { records, error, busy, prepare, check, remove,
    browserRequested: record => persist({ ...record, browserRequestedAt: Date.now() }),
    pending: records.some(transferPending) };
}

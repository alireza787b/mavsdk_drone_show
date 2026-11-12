import { useCallback, useEffect, useRef, useState } from 'react';
import { createPx4ParamReview, applyPx4ParamReview, getPx4ParamPatchJob, getPx4ParamJobByIdempotencyKey,
  refreshPx4ParamSnapshots } from '../../services/px4ParamsApiService';
import { createCommandIdempotencyKey } from '../../services/droneApiService';
import { parameterKey } from '../../utilities/px4ParameterValues';
import { isReceiptUncertain, newerParameterReceipt, readParameterReceipts, saveParameterReceipt } from './parameterReceipts';

export const parameterError = error => {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' ? detail : error?.message || 'The request could not be completed.';
};

function assertReceiptIdentity(data, receipt) {
  if (!data?.job_id || data.idempotency_key !== receipt.idempotencyKey
    || data.review_id !== receipt.reviewId || data.review_hash !== receipt.reviewHash) {
    throw new Error('The returned receipt does not match this operation.');
  }
}

export default function useParameterWorkspace({ viewId, componentId = 1, storageKey }) {
  const [snapshots, setSnapshots] = useState({});
  const [snapshotBusy, setSnapshotBusy] = useState(false);
  const [snapshotError, setSnapshotError] = useState('');
  const [draft, setDraft] = useState(null);
  const [review, setReview] = useState(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState('');
  const [storageError, setStorageError] = useState('');
  const [receipts, setReceipts] = useState([]);
  const [sessionChanges, setSessionChanges] = useState({});
  const current = useRef({ viewId, storageKey });
  current.current = { viewId, storageKey };
  const readGeneration = useRef(0), reviewGeneration = useRef(0), lock = useRef(false), mounted = useRef(true);
  const receiptRef = useRef(receipts);
  receiptRef.current = receipts;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  useEffect(() => {
    setDraft(null); setReview(null); setSnapshots({}); setError(''); setSessionChanges({});
    try { setReceipts(readParameterReceipts(storageKey)); setStorageError(''); }
    catch (failure) { setReceipts([]); setStorageError(`${parameterError(failure)} Recovery storage must work before applying changes.`); }
    const update = event => {
      if (event.key !== storageKey) return;
      try { setReceipts(readParameterReceipts(storageKey)); }
      catch (failure) { setStorageError(parameterError(failure)); }
    };
    window.addEventListener('storage', update);
    return () => { window.removeEventListener('storage', update); reviewGeneration.current += 1; readGeneration.current += 1; };
  }, [storageKey]);

  const refresh = useCallback(async () => {
    if (!viewId) return;
    const generation = ++readGeneration.current, scope = storageKey;
    setSnapshotBusy(true); setSnapshotError('');
    try {
      const { data } = await refreshPx4ParamSnapshots({ hwIds: [viewId], componentId });
      const snapshot = data?.snapshots?.find(item => String(item.snapshot?.hw_id) === viewId);
      if (!snapshot) throw new Error(data?.errors?.find(item => String(item.hw_id) === viewId)?.error || 'No snapshot returned for this aircraft.');
      if (mounted.current && current.current.storageKey === scope && generation === readGeneration.current) {
        setSnapshots(previous => ({ ...previous, [viewId]: snapshot }));
      }
    } catch (failure) {
      if (mounted.current && current.current.storageKey === scope && generation === readGeneration.current) setSnapshotError(parameterError(failure));
    } finally {
      if (mounted.current && current.current.storageKey === scope && generation === readGeneration.current) setSnapshotBusy(false);
    }
  }, [viewId, componentId, storageKey]);
  useEffect(() => { refresh(); return () => { readGeneration.current += 1; }; }, [refresh]);

  const updateDraft = useCallback(update => {
    reviewGeneration.current += 1;
    setDraft(previous => typeof update === 'function' ? update(previous) : update);
    setReview(null); setError(''); setReviewBusy(false);
  }, []);
  const stage = next => {
    if (draft && !(draft.source === 'manual' && next.source === 'manual'
      && JSON.stringify(draft.hwIds) === JSON.stringify(next.hwIds))) {
      setError('A draft is already open. Review or discard it before loading another source.'); return false;
    }
    const entries = new Map((draft?.entries || []).map(entry => [parameterKey(entry), entry]));
    next.entries.forEach(entry => entries.set(parameterKey(entry), entry));
    updateDraft({ ...next, entries: [...entries.values()] });
    return true;
  };
  const prepare = async () => {
    if (!draft?.hwIds.length || !draft.entries.length || lock.current) return;
    const generation = ++reviewGeneration.current, scope = storageKey;
    setReviewBusy(true); setError(''); setReview(null);
    try {
      const { data } = await createPx4ParamReview({ hwIds: draft.hwIds, excludedHwIds: draft.excludedHwIds || [],
        entries: draft.entries, source: draft.source, profileId: draft.profileId });
      if (!mounted.current || scope !== current.current.storageKey || generation !== reviewGeneration.current) return;
      if (!data?.review_id || !data.review_hash || !Array.isArray(data.hw_ids)
        || !Number.isFinite(data.expires_at) || data.verify_readback !== true
        || JSON.stringify([...data.hw_ids].sort()) !== JSON.stringify([...draft.hwIds].sort())
        || JSON.stringify([...(data.excluded_hw_ids || [])].sort()) !== JSON.stringify([...(draft.excludedHwIds || [])].sort())
        || !Array.isArray(data.targets) || JSON.stringify(data.targets.map(target => target.hw_id).sort()) !== JSON.stringify([...draft.hwIds].sort())) {
        throw new Error('Review identity or aircraft scope could not be confirmed.');
      }
      setReview(data);
    } catch (failure) {
      if (mounted.current && scope === current.current.storageKey && generation === reviewGeneration.current) setError(parameterError(failure));
    } finally {
      if (mounted.current && scope === current.current.storageKey && generation === reviewGeneration.current) setReviewBusy(false);
    }
  };

  const installReceipt = useCallback((receipt, key) => {
    // Even a storage failure after acceptance must not reinterpret the job.
    let records;
    if (current.current.storageKey === key) receipt = newerParameterReceipt(receiptRef.current.find(item => item.idempotencyKey === receipt.idempotencyKey), receipt);
    try { records = saveParameterReceipt(key, receipt); }
    catch (failure) {
      records = [receipt, ...receiptRef.current.filter(item => item.idempotencyKey !== receipt.idempotencyKey)];
      if (current.current.storageKey === key) setStorageError(`Receipt storage failed: ${parameterError(failure)}`);
    }
    if (!mounted.current || current.current.storageKey !== key) return;
    receiptRef.current = records; setReceipts(records);
    if (receipt.job?.terminal === true) setSessionChanges(previous => {
      const next = { ...previous };
      for (const result of receipt.job.results || []) {
        const changed = (result.result?.results || []).filter(entry => entry.applied).map(parameterKey);
        next[result.hw_id] = [...new Set([...(next[result.hw_id] || []), ...changed])];
      }
      return next;
    });
  }, []);

  const lookup = useCallback(async (receipt, key = storageKey) => {
    try {
      const { data } = receipt.job?.job_id ? await getPx4ParamPatchJob(receipt.job.job_id)
        : await getPx4ParamJobByIdempotencyKey(receipt.idempotencyKey);
      assertReceiptIdentity(data, receipt);
      installReceipt({ ...receipt, job: data, error: '' }, key);
    } catch (failure) {
      const detail = failure?.response?.status === 404 ? 'No receipt found yet. Outcome remains unconfirmed; do not resend.' : parameterError(failure);
      installReceipt({ ...receipt, error: detail }, key);
    }
  }, [installReceipt, storageKey]);

  useEffect(() => {
    let active = true, timer;
    const poll = async () => {
      const unresolved = receiptRef.current.filter(item => !item.error && (!item.job || item.job.terminal !== true));
      for (const item of unresolved) {
        if (!active) return;
        await lookup(item, storageKey);
      }
      if (active) timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 1500);
    return () => { active = false; clearTimeout(timer); };
  }, [storageKey, lookup]);

  const apply = async () => {
    if (lock.current || !review || review.blocked || Date.now() >= review.expires_at || storageError) return;
    const key = storageKey;
    lock.current = true; setApplying(true); setError('');
    let receipt;
    try {
      const saved = readParameterReceipts(key);
      if (saved.some(item => item.reviewId === review.review_id
        || (isReceiptUncertain(item) && item.hwIds.some(id => review.hw_ids.includes(id))))) {
        throw new Error('An existing operation covers these aircraft. Check its receipt before another write.');
      }
      receipt = { idempotencyKey: createCommandIdempotencyKey(), reviewId: review.review_id, reviewHash: review.review_hash,
        hwIds: [...review.hw_ids], excludedHwIds: [...(review.excluded_hw_ids || [])], title: draft.title,
        entries: draft.entries, createdAt: Date.now(), job: null, error: '' };
      const records = saveParameterReceipt(key, receipt);
      receiptRef.current = records; setReceipts(records);
    } catch (failure) {
      setError(`Not sent: ${parameterError(failure)}`); lock.current = false; setApplying(false); return;
    }
    // From this point a missing response is uncertain, never permission to replay.
    try {
      const { data } = await applyPx4ParamReview({ reviewId: receipt.reviewId, reviewHash: receipt.reviewHash, idempotencyKey: receipt.idempotencyKey });
      assertReceiptIdentity(data, receipt);
      installReceipt({ ...receipt, job: data }, key);
    } catch (failure) {
      installReceipt({ ...receipt, error: `Outcome unconfirmed: ${parameterError(failure)} Check the saved receipt; do not resend.` }, key);
    } finally {
      if (mounted.current && key === current.current.storageKey) {
        setDraft(null); setReview(null); setApplying(false);
      }
      lock.current = false;
    }
  };

  return { snapshot: snapshots[viewId] || null, snapshotBusy, snapshotError, refresh,
    draft, stage, updateDraft, discard: () => updateDraft(null), review, prepare, reviewBusy, apply, applying,
    error, storageError, receipts, lookup, sessionChanges: new Set(sessionChanges[viewId] || []) };
}

import { useCallback, useEffect, useRef, useState } from 'react';
import usePollingResource from '../../hooks/usePollingResource';
import { applyFleetGitSyncResponse, buildGcsUrl, dryRunFleetGitSyncResponse, getFleetGitOperationResponse } from '../../services/gcsApiService';
import { extractApiErrorMessage } from '../../services/apiError';

const activePhases = new Set(['applying', 'verifying']);
const phases = new Set(['review', ...activePhases, 'completed', 'partial', 'failed', 'interrupted', 'expired']);
export function activeOperation(operation) {
  return activePhases.has(operation?.phase);
}

function remember(key, value) {
  try {
    if (value) window.sessionStorage.setItem(key, value);
    else window.sessionStorage.removeItem(key);
  } catch { /* Storage can be disabled in private browsing. */ }
}

function recall(key) {
  try { return window.sessionStorage.getItem(key) || ''; } catch { return ''; }
}

function sameOperation(data, id) {
  return Boolean(id && data?.operation_id === id) && phases.has(data.phase) && data.per_aircraft_state && data.target_counts;
}

// An uncertain dispatch is reconciled by its preview ID. Reads can be repeated;
// a reload or a reconnect must never replay Apply.
export default function useFleetSync(operatorId, runtimeMode) {
  const storageKey = 'mds.fleetGit.' + JSON.stringify([buildGcsUrl('fleetGitSync'), operatorId, runtimeMode]);
  const [id, setId] = useState(() => recall(storageKey));
  const [operation, setOperation] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [check, setCheck] = useState(0);
  const [recover, setRecover] = useState(Boolean(id));
  const lock = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const refresh = () => { setRecover(true); setCheck(n => n + 1); };
  const lookup = useCallback(async options => {
    const response = await getFleetGitOperationResponse(id, options);
    if (!sameOperation(response?.data, id)) throw new Error('Update status unavailable');
    return response;
  }, [id]);
  const poll = usePollingResource(lookup, 1800, id + ':' + check,
    Boolean(id && !busy && (recover || activeOperation(operation))));
  useEffect(() => {
    const data = poll.response?.data;
    if (!sameOperation(data, id)) return;
    setOperation(previous => previous?.updated_at > data.updated_at ? previous : data);
    setRecover(false);
    if (data.phase !== 'review') { setPreview(null); setError(''); }
  }, [poll.response, id]);

  const prepare = async (hwIds) => {
    if (lock.current || !hwIds.length) return;
    lock.current = true;
    setBusy('preview');
    setError('');
    try {
      const { data } = await dryRunFleetGitSyncResponse({ hw_ids: [...hwIds] });
      if (!data?.confirmation_token || !data.operation_id || !sameOperation(data, data.operation_id)) {
        throw new Error('The ground station returned an incomplete preview. Refresh the fleet and try again.');
      }
      const requested = new Set(hwIds);
      const recipients = Object.entries(data.per_aircraft_state);
      if (data.phase !== 'review' || requested.size !== recipients.length
          || recipients.some(([hwId, row]) => !requested.has(hwId) || row.hw_id !== hwId)) {
        throw new Error('Aircraft changed during preview. Review your selection again.');
      }
      if (!mounted.current) return;
      setId(data.operation_id);
      remember(storageKey, data.operation_id);
      setPreview(data);
      setOperation(data);
      setRecover(false);
    } catch (err) {
      const message = await extractApiErrorMessage(err, 'Could not prepare the preview.');
      if (mounted.current) setError(message);
    } finally {
      lock.current = false;
      if (mounted.current) setBusy('');
    }
  };

  const apply = async () => {
    if (lock.current || !preview || operation?.phase !== 'review') return;
    lock.current = true;
    setBusy('apply');
    setError('');
    try {
      const { data } = await applyFleetGitSyncResponse({
        dry_run_id: preview.preview_id || preview.job_id,
        confirmation: { acknowledged_risks: true, confirmation_token: preview.confirmation_token },
      }, { params: { background: true } });
      if (!sameOperation(data, id)) throw new Error('Checking the update receipt.');
      if (mounted.current) { setOperation(data); setPreview(null); }
    } catch (err) {
      const message = err.response ? await extractApiErrorMessage(err, 'Could not confirm the update.')
        : 'Update receipt unavailable. Check progress before trying again.';
      if (mounted.current) {
        if (err.response?.status === 409) setPreview(null);
        setError(message);
        refresh();
      }
    } finally {
      lock.current = false;
      if (mounted.current) setBusy('');
    }
  };

  const clear = () => {
    if (lock.current || activeOperation(operation)) return;
    setId(''); setOperation(null); setPreview(null); setError(''); setRecover(false);
    remember(storageKey, '');
  };
  return { id, operation, preview, busy, error, prepare, apply, clear, refresh,
    checking: Boolean(id && (recover || !operation)), readError: id ? poll.error : null };
}

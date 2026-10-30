import React, { useEffect, useRef, useState } from 'react';
import { ConfirmDialog } from './ui';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import { getBackendURL } from '../config/apiConfig';
import { fetchGcsResource, postGcsResource } from '../services/gcsApiService';
import { createCommandIdempotencyKey, isAmbiguousSubmissionTransportFailure } from '../services/droneApiService';
import { submitCommandWithLifecycleFeedback, trackCommandReceipt } from '../utilities/commandLifecycleFeedback';

const PHASES = { checking: 'Checking', arming: 'Arming', released: 'Taking off', airborne: 'Airborne', aborted: 'Launch cancelled' };

// One review and one owned command, shared by every standalone Takeoff entry.
// Native readiness is advisory here; node admission is repeated at execution.
export default function TakeoffDialog({ open, command, aircraft = [], beforeSubmit, onClose }) {
  if (!open || !command) return null;
  return <TakeoffReview key={command.idempotency_key || command.uiMeta?.reviewKey || 'takeoff-review'}
    command={command} aircraft={aircraft} beforeSubmit={beforeSubmit} onClose={onClose} />;
}

function TakeoffReview({ command, aircraft, beforeSubmit, onClose }) {
  // The initiating page defines the review boundary, not the entire fleet.
  const [roster] = useState(() => [...command.target_drone_ids].map(String));
  const [pendingKey] = useState(() => `mds-takeoff:${getBackendURL()}:${[...command.target_drone_ids].map(String).sort().join(',')}`);
  const [restored] = useState(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(pendingKey));
      return saved?.mission_type === 10 && typeof saved.idempotency_key === 'string'
        && Array.isArray(saved.target_drone_ids) && saved.target_drone_ids.length > 0
        && saved.target_drone_ids.every((id) => roster.includes(String(id))) ? saved : null;
    } catch (_) { return null; }
  });
  const [intent] = useState(() => restored || ({ ...command, target_drone_ids: [...command.target_drone_ids].map(String),
    idempotency_key: command.idempotency_key || createCommandIdempotencyKey() }));
  const [height, setHeight] = useState(intent.takeoff_altitude ?? 10);
  const [targets, setTargets] = useState(() => intent.target_drone_ids.map(String));
  const [waitForAll, setWaitForAll] = useState(intent.takeoff_mode !== 'independent');
  const [readiness, setReadiness] = useState(null);
  const [submitted, setSubmitted] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [coordination, setCoordination] = useState(null);
  const [executionDetails, setExecutionDetails] = useState({});
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(Boolean(restored));
  const [attemptStarted, setAttemptStarted] = useState(Boolean(restored));
  const [error, setError] = useState('');
  const submitLock = useRef(false);
  const mounted = useRef(true);
  const callbacksRef = useRef(null);
  const allCheckbox = useRef(null);
  const submittedPayload = useRef(restored);
  const attemptKey = useRef(intent.idempotency_key);
  const { commandLifecycleCallbacks } = useCommandActivity();
  callbacksRef.current = commandLifecycleCallbacks;
  const multiple = targets.length > 1;
  const coordinated = multiple && waitForAll;
  const validHeight = String(height).trim() !== '' && Number.isFinite(Number(height)) && Number(height) > 0;
  const rows = roster.map((id) => {
    const selected = targets.includes(id);
    const native = readiness?.targets?.find((row) => String(row.hw_id) === id);
    const member = aircraft.find((row) => String(row.hw_id ?? row.hw_ID) === id);
    const name = member?.callsign || member?.name || `Aircraft ${id}`;
    const unsupported = native?.status === 'ready' && coordinated && native.coordinated_takeoff_supported !== true;
    return { id, name, selected, status: unsupported ? 'blocked' : native?.status || 'checking',
      reason: unsupported ? 'Software update required for coordinated takeoff' : native?.reason };
  });
  const ready = targets.length > 0 && rows.filter((row) => row.selected).every((row) => row.status === 'ready');
  const inProgress = Boolean(attemptStarted || submitted || uncertain);
  const phase = coordination?.phase;
  // An abort is a decision, not proof that motor/flight cleanup finished.
  const terminal = snapshot?.isTerminal === true;
  const canCancel = submitted?.command_id && coordinated && ['checking', 'arming'].includes(phase) && !terminal;

  const selectTargets = (next) => {
    if (inProgress || submitLock.current) return;
    setTargets(roster.filter((id) => next.includes(id)));
    setReadiness(null);
    setError('');
  };
  useEffect(() => {
    if (allCheckbox.current) allCheckbox.current.indeterminate = targets.length > 0 && targets.length < roster.length;
  }, [targets, roster]);

  const rememberPending = (payload) => {
    try {
      if (payload) sessionStorage.setItem(pendingKey, JSON.stringify(payload));
      else sessionStorage.removeItem(pendingKey);
    } catch (_) { /* The server's command journal remains authoritative. */ }
  };
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (inProgress || targets.length === 0) return undefined;
    let live = true, timer, expiry;
    const poll = async () => {
      try {
        const requestedAt = Date.now();
        const query = targets.map((id) => `target_drone_ids=${encodeURIComponent(id)}`).join('&');
        const { data } = await fetchGcsResource(`/api/v1/commands/takeoff-readiness?${query}`);
        const roundTrip = Date.now() - requestedAt;
        // The server's native probe may take longer than the lease sampled at
        // its end. Subtract transport, not that already-accounted probe time.
        const processing = Number(data?.server_processing_ms ?? 0);
        const transport = Number.isFinite(processing) && processing >= 0 && processing <= roundTrip + 20
          ? Math.max(0, roundTrip - processing) : roundTrip;
        // Blocked rows have a zero group lease. Preserve their reason, and
        // expire only ready evidence using each selected aircraft's own lease.
        const reviewedRows = (data?.targets || []).filter((row) => targets.includes(String(row.hw_id)))
          .map((row) => {
            const remaining = Number(row.valid_for_ms ?? data.valid_for_ms) - transport;
            return row.status === 'ready' && !(Number.isFinite(remaining) && remaining > 0)
              ? { ...row, status: 'checking', reason: undefined }
              : { ...row, remaining };
          });
        const leases = reviewedRows.filter((row) => row.status === 'ready').map((row) => row.remaining);
        if (live) {
          clearTimeout(expiry);
          setReadiness({ targets: reviewedRows });
          if (leases.length) expiry = setTimeout(() => live && setReadiness((previous) => previous && ({
            targets: previous.targets.map((row) => row.status === 'ready'
              ? { ...row, status: 'checking', reason: undefined } : row),
          })), Math.min(...leases));
        }
      } catch (_) { if (live) setReadiness(null); }
      finally { if (live) timer = setTimeout(poll, 1500); }
    };
    poll();
    return () => { live = false; clearTimeout(timer); clearTimeout(expiry); };
  }, [inProgress, targets]);

  const receive = (event, monitor, raw) => {
    callbacksRef.current?.[event]?.(monitor, raw);
    if (!mounted.current) return;
    setSnapshot(monitor);
    if (raw?.executions?.details) setExecutionDetails(raw.executions.details);
    const next = raw?.coordinated_takeoff || raw?.params?.coordinated_takeoff;
    if (next) setCoordination(next);
  };
  const lifecycle = Object.fromEntries(['onSubmissionTracked', 'onStatusUpdate', 'onTrackingComplete',
    'onTrackingUnavailable', 'onLateEvidence'].map((event) => [event, (monitor, raw) => receive(event, monitor, raw)]));

  const submit = async () => {
    if (submitLock.current || (!uncertain && (!validHeight || !ready || inProgress))) return;
    submitLock.current = true;
    setBusy(true); setAttemptStarted(true); setError('');
    try {
      if (uncertain) {
        const { data } = await fetchGcsResource('/api/v1/commands/lookup', { params: { idempotency_key: submittedPayload.current.idempotency_key } });
        const response = trackCommandReceipt(submittedPayload.current, data, lifecycle);
        rememberPending(null);
        if (mounted.current) { setSubmitted(response); setUncertain(false); }
        return;
      }
      const payload = { ...intent, idempotency_key: attemptKey.current,
        target_drone_ids: [...targets], takeoff_altitude: Number(height),
        uiMeta: { ...intent.uiMeta, targetLabel: `${targets.length} aircraft`,
          targetDescriptor: targets.map((id) => rows.find((row) => row.id === id).name).join(', ') } };
      delete payload.takeoff_mode;
      if (multiple) payload.takeoff_mode = coordinated ? 'coordinated' : 'independent';
      submittedPayload.current = payload;
      rememberPending(payload);
      await beforeSubmit?.();
      const response = await submitCommandWithLifecycleFeedback(payload, lifecycle);
      rememberPending(null);
      if (mounted.current) setSubmitted(response);
    } catch (exc) {
      if (isAmbiguousSubmissionTransportFailure(exc)) {
        if (mounted.current) { setUncertain(true); setError('Receipt unconfirmed. Check this launch before trying again.'); }
      } else if (uncertain) {
        if (mounted.current) setError('Receipt unavailable. Check this launch again before retrying.');
      } else {
        rememberPending(null);
        submittedPayload.current = null;
        attemptKey.current = createCommandIdempotencyKey();
        if (mounted.current) { setAttemptStarted(false); setError(exc?.response?.data?.detail?.message || exc?.response?.data?.detail || exc?.message || 'Takeoff unavailable'); }
      }
    } finally {
      submitLock.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  const cancelLaunch = async () => {
    if (!canCancel || submitLock.current) return;
    submitLock.current = true; setBusy(true); setError('');
    try {
      const { data } = await postGcsResource(`/api/v1/commands/${encodeURIComponent(submitted.command_id)}/cancel-launch`, {});
      if (mounted.current && data?.coordinated_takeoff) setCoordination(data.coordinated_takeoff);
    } catch (exc) {
      if (mounted.current) setError(exc?.response?.status === 409
        ? 'Takeoff already released. Use Hold or the radio.' : 'Cancellation unconfirmed. Check aircraft status.');
    } finally { submitLock.current = false; if (mounted.current) setBusy(false); }
  };
  const finalState = (id) => executionDetails[id]?.action_result?.final_vehicle_state;
  const allDisarmed = targets.every((id) => finalState(id)?.armed === false);
  const progress = phase === 'aborted' ? (!terminal ? 'Cancelling' : allDisarmed ? 'Launch cancelled' : 'Check aircraft')
    : PHASES[phase] || (uncertain ? 'Checking receipt'
    : terminal ? (snapshot?.outcome === 'completed' ? 'Airborne' : snapshot?.progress?.label || 'Check aircraft')
      : ['executing', 'finishing'].includes(snapshot?.progress?.stage) ? 'Taking off' : 'Checking');
  const progressCount = phase === 'arming' ? ` ${coordination.armed_count ?? 0}/${coordination.total ?? targets.length}` : '';

  return <ConfirmDialog open appearance="console" title="Takeoff"
    confirmLabel={uncertain ? 'Check command' : !inProgress ? `Arm & take off · ${targets.length} aircraft` : terminal ? 'Done' : canCancel ? 'Cancel launch' : progress}
    confirmDisabled={(!inProgress && (!ready || !validHeight)) || (inProgress && !uncertain && !terminal && !canCancel)} busy={busy} allowDismissWhileBusy
    cancelLabel={inProgress ? 'Close' : 'Cancel'} onCancel={onClose}
    onConfirm={inProgress && !uncertain ? (canCancel ? cancelLaunch : onClose) : submit}
    message={<div className="takeoff-review">
      {!inProgress ? <>
        <label className="takeoff-review__height">Takeoff height <span><input aria-label="Takeoff height" type="number" min="0.1" step="1"
          value={height} onChange={(event) => setHeight(event.target.value)} disabled={busy} /> m</span></label>
        {multiple && <label className="takeoff-review__wait"><input type="checkbox" checked={waitForAll}
          onChange={(event) => setWaitForAll(event.target.checked)} disabled={busy} /> Wait for all aircraft</label>}
        {!validHeight && <p role="alert">Enter a positive height.</p>}
      </> : <div className="takeoff-review__progress" role="status">{progress}{progressCount}</div>}
      <div className="takeoff-review__selection">
        {roster.length > 1 && <label className="takeoff-review__select-all"><input ref={allCheckbox} type="checkbox"
          aria-label="Select all aircraft" checked={targets.length === roster.length} disabled={inProgress || busy}
          onChange={(event) => selectTargets(event.target.checked ? roster : [])} />All</label>}
        <span aria-live="polite">{targets.length} of {roster.length} aircraft</span>
      </div>
      <ul className="takeoff-review__aircraft" aria-label="Takeoff aircraft">
        {rows.map((row) => {
          const execution = coordination?.targets?.[row.id];
          const final = finalState(row.id);
          const recoveryState = final?.armed === false ? 'disarmed'
            : final?.outcome === 'held' ? 'hold_confirmed' : terminal ? 'recovery_unconfirmed' : 'checking_aircraft';
          const status = !row.selected ? 'excluded' : inProgress ? (phase === 'aborted' ? recoveryState : execution?.state || 'checking') : row.status;
          const label = !row.selected ? 'Not included' : inProgress ? (status.replaceAll('_', ' ')) : { ready: 'Ready', blocked: 'Blocked', checking: 'Checking', unavailable: 'Unavailable' }[status] || 'Checking';
          const reason = row.selected && (inProgress ? execution?.reason : row.reason);
          return <li key={row.id} className={`takeoff-review__aircraft--${status}`}>
            <label className="takeoff-review__member"><input type="checkbox" checked={row.selected}
              aria-label={`Include ${row.name} (H${row.id})`} disabled={inProgress || busy}
              onChange={(event) => selectTargets(event.target.checked ? [...targets, row.id] : targets.filter((id) => id !== row.id))} />
              <strong>{row.name}<small>H{row.id}</small></strong></label>
            <span><b>{label}</b>{reason && status !== 'ready' && <small>{reason}</small>}</span></li>;
        })}
      </ul>
      {coordination?.reason && coordination.reason !== progress && <p role="status">{coordination.reason}</p>}
      {error && <p role="alert">{typeof error === 'string' ? error : 'Takeoff unavailable. Check aircraft status.'}</p>}
    </div>} />;
}

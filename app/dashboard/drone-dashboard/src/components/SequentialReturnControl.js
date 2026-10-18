import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { FaHome } from 'react-icons/fa';
import { ConfirmDialog, StatusBadge } from './ui/OperatorPrimitives';
import { fetchGcsResource, postGcsResource } from '../services/gcsApiService';

const ROUTE = '/api/v1/swarm/runtime/sequential-return';
const ACTIVE = new Set(['holding', 'dispatching', 'waiting']);
const LABELS = {
  holding: 'Establishing Hold', dispatching: 'Sending RTL', waiting: 'Waiting',
  dispatched: 'RTL commands started', cancelled: 'Queue cancelled',
  interrupted: 'Queue interrupted', failed: 'Return queue stopped',
};

export default function SequentialReturnControl({ targetIds, targetNames, compact = false,
  contextKey = '', aircraftStates = {}, validateReview = null }) {
  const [delay, setDelay] = useState(10);
  const [confirmation, setConfirmation] = useState(null);
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState(false);
  // Retain request identity if the POST response is lost; retry recovers it.
  const pendingRequest = useRef(null);

  useEffect(() => {
    let stopped = false;
    let timer;
    const poll = async () => {
      try {
        const response = await fetchGcsResource(ROUTE);
        if (!stopped) {
          setJob(response.data);
          setPollError(false);
        }
      } catch (_) {
        if (!stopped) setPollError(true);
      } finally {
        if (!stopped) timer = setTimeout(poll, 1500);
      }
    };
    poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, []);

  const active = ACTIVE.has(job?.state);
  const validDelay = Number.isFinite(Number(delay)) && Number(delay) >= 1 && Number(delay) <= 300;

  const start = async () => {
    const reviewed = confirmation;
    if (!reviewed || !Number.isFinite(reviewed.delay) || reviewed.delay < 1 || reviewed.delay > 300) return;
    setConfirmation(null);
    if (reviewed.targetIds.join(',') !== targetIds.join(',') || reviewed.contextKey !== contextKey) {
      setError('Selection changed. Review the return order again.');
      return;
    }
    const payload = { target_drone_ids: reviewed.targetIds, delay_sec: reviewed.delay };
    const fingerprint = JSON.stringify(payload);
    if (pendingRequest.current?.fingerprint !== fingerprint) {
      pendingRequest.current = {
        fingerprint,
        payload: { ...payload, idempotency_key: `return-${Date.now()}-${Math.random().toString(36).slice(2)}` },
      };
    }
    setBusy(true);
    setError('');
    try {
      if (validateReview) await validateReview();
      const response = await postGcsResource(ROUTE, pendingRequest.current.payload);
      setJob(response.data);
      pendingRequest.current = null;
    } catch (exc) {
      const detail = exc?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Return not confirmed. Retry to recover its status.');
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await postGcsResource(`${ROUTE}/${job.return_id}/cancel`);
      setJob(response.data);
    } catch (_) {
      setError('Cancellation not confirmed. Check the connection and retry.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="swarm-sequential-return operator-console">
      <div className="swarm-sequential-return__toolbar">
        {!compact && <label>
          RTL interval
          <span>
            <input type="number" aria-label="Seconds between RTL commands" min="1" max="300"
              step="1" value={delay} disabled={active || busy}
              onChange={(event) => setDelay(event.target.value)} /> s
          </span>
        </label>}
        <button type="button" className={compact ? 'operator-button operator-button--ghost' : 'swarm-runtime-action warning'}
          disabled={busy || active || targetIds.length === 0 || !validDelay || pollError}
          onClick={() => setConfirmation({ targetIds: [...targetIds], targetNames: [...targetNames], delay: Number(delay), contextKey })}>
          <span className="swarm-runtime-action__icon"><FaHome /></span>
          {compact ? 'Managed Return' : <span className="swarm-runtime-action__copy"><strong>Managed Return</strong>
            <small>RTL in the displayed order, {delay || '—'} s apart</small></span>}
        </button>
      </div>
      {job && (
        <div className="swarm-sequential-return__status" role="status">
          <StatusBadge tone={job.state === 'failed' || job.state === 'interrupted' ? 'warning' : 'info'}>
            {LABELS[job.state] || job.state}
          </StatusBadge>
          <span>{job.commands.length}/{job.target_drone_ids.length} RTL commands issued</span>
          {job.next_hw_id && <span>Next: {job.next_hw_id}</span>}
          {active && <button type="button" disabled={busy} onClick={cancel}>Cancel remaining</button>}
          {active && <small>Issued RTL continues.</small>}
          {['failed', 'cancelled', 'interrupted'].includes(job.state) && <span>{job.message}</span>}
          {job.commands.map((command) => (
            <span key={command.hw_id}>Drone {command.hw_id} · {aircraftStates[command.hw_id] === 'Grounded'
              ? 'Landed / disarmed' : (!aircraftStates[command.hw_id] || aircraftStates[command.hw_id] === 'Unknown')
                ? 'State unknown · RTL issued' : 'RTL issued'}</span>
          ))}
        </div>
      )}
      {pollError && <p role="alert">Return status unavailable. Pending commands may continue on the GCS.</p>}
      {error && <p role="alert">{error}</p>}
      <ConfirmDialog appearance="console" open={Boolean(confirmation)} title="Managed Return" confirmLabel="Start return"
        confirmDisabled={!confirmation || !Number.isFinite(confirmation.delay) || confirmation.delay < 1 || confirmation.delay > 300}
        onCancel={() => setConfirmation(null)} onConfirm={start} busy={busy}
        message={confirmation ? (
          <div className="swarm-confirm-summary">
            <p>Stops following, then sends each aircraft home in order.</p>
            <label>Time between returns (s) <input type="number" aria-label="Return interval" min="1" max="300" step="1" value={confirmation.delay}
              onChange={(e) => setConfirmation({ ...confirmation, delay: Number(e.target.value) })} /> s</label>
            <ol className="swarm-return-order" aria-label="Return order">{confirmation.targetNames.map((name, index) => (
              <li key={confirmation.targetIds[index]}>{name} · {index === 0 ? 'first' : `+${index * confirmation.delay} s`}</li>
            ))}</ol>
            <p>Return paths may overlap.</p>
            <details><summary>Return settings</summary>Each aircraft uses its configured PX4 return height and home position. Heights are unavailable here. The next return starts after the interval, not after the previous landing.</details>
            {(!Number.isFinite(confirmation.delay) || confirmation.delay < 1 || confirmation.delay > 300) && <p role="alert">Use an interval from 1 to 300 s.</p>}
          </div>
        ) : ''} />
    </div>
  );
}

SequentialReturnControl.propTypes = {
  targetIds: PropTypes.arrayOf(PropTypes.string).isRequired,
  targetNames: PropTypes.arrayOf(PropTypes.string).isRequired,
  compact: PropTypes.bool,
  contextKey: PropTypes.string,
  aircraftStates: PropTypes.object,
  validateReview: PropTypes.func,
};

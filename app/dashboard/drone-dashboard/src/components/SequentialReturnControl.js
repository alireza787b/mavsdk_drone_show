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

export default function SequentialReturnControl({ targetIds, targetNames }) {
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
    setConfirmation(null);
    if (reviewed.targetIds.join(',') !== targetIds.join(',')) {
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
    <div className="swarm-sequential-return">
      <div className="swarm-sequential-return__toolbar">
        <label>
          RTL interval
          <span>
            <input type="number" aria-label="Seconds between RTL commands" min="1" max="300"
              step="1" value={delay} disabled={active || busy}
              onChange={(event) => setDelay(event.target.value)} /> s
          </span>
        </label>
        <button type="button" className="swarm-runtime-action warning"
          disabled={busy || active || targetIds.length === 0 || !validDelay || pollError}
          onClick={() => setConfirmation({ targetIds: [...targetIds], targetNames: [...targetNames], delay: Number(delay) })}>
          <span className="swarm-runtime-action__icon"><FaHome /></span>
          <span className="swarm-runtime-action__copy"><strong>Sequential Return</strong>
            <small>RTL in the displayed order, {delay || '—'} s apart</small></span>
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
          {['failed', 'cancelled', 'interrupted'].includes(job.state) && <span>{job.message}</span>}
          {job.commands.map((command) => (
            <span key={command.hw_id}>Drone {command.hw_id} · RTL issued</span>
          ))}
        </div>
      )}
      {pollError && <p role="alert">Return status unavailable. Pending commands may continue on the GCS.</p>}
      {error && <p role="alert">{error}</p>}
      <ConfirmDialog open={Boolean(confirmation)} title="Sequential Return" confirmLabel="Start return"
        onCancel={() => setConfirmation(null)} onConfirm={start} busy={busy}
        message={confirmation && (
          <div className="swarm-confirm-summary">
            <p>Stop following and Hold, then send RTL {confirmation.delay} s apart.</p>
            <ol>{confirmation.targetNames.map((name, index) => (
              <li key={confirmation.targetIds[index]}>{name} · {index === 0 ? 'first' : `+${index * confirmation.delay} s`}</li>
            ))}</ol>
            <p>Each drone uses its own PX4 return height and destination. Returns can overlap; check that the routes are clear.</p>
          </div>
        )} />
    </div>
  );
}

SequentialReturnControl.propTypes = {
  targetIds: PropTypes.arrayOf(PropTypes.string).isRequired,
  targetNames: PropTypes.arrayOf(PropTypes.string).isRequired,
};

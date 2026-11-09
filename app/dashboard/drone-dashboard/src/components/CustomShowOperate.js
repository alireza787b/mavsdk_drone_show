import React, { useEffect, useMemo, useState } from 'react';
import { ConfirmDialog, OperatorNotice } from './ui';
import ShowScheduleFields from './ShowScheduleFields';
import ShowReceiptRecovery from './ShowReceiptRecovery';
import useShowOperation from '../hooks/useShowOperation';
import useShowAircraftSelection from '../hooks/useShowAircraftSelection';
import useCommandDispatch from '../hooks/useCommandDispatch';
import { buildShowCommand, formatShowOperationStart, formatShowStart } from '../utilities/droneShowWorkspace';
import { getMissionExecutionPolicy } from '../utilities/commandExecutionPolicy';

const LABELS = { launch: 'Launch Custom CSV', hold: 'Hold', land: 'Land here', rtl: 'Immediate RTL', cancel: 'Cancel mission' };

export default function CustomShowOperate({ infoState, runtimeMode }) {
  const operationState = useShowOperation(3, runtimeMode);
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => { const timer = setInterval(() => setNow(performance.now()), 1000); return () => clearInterval(timer); }, []);
  const fleet = useMemo(() => operationState.data?.fleet || [], [operationState.data]);
  const [ids, setIds] = useShowAircraftSelection(fleet, runtimeMode);
  const [query, setQuery] = useState('');
  const [schedule, setSchedule] = useState({ scheduleMode: 'now', timeDelay: 10, selectedDateTime: '' });
  const [review, setReview] = useState(null);
  const [reviewError, setReviewError] = useState('');
  const dispatch = useCommandDispatch('custom', runtimeMode);
  const operation = operationState.data;
  const active = operation?.state === 'active';
  const selected = ids.map(id => fleet.find(d => String(d.hw_id) === id));
  const visible = fleet.filter(d => `${d.name} ${d.hw_id} ${d.pos_id}`.toLowerCase().includes(query.toLowerCase()));
  const referenceNowMs = Number(operationState.data?.timestamp) + now - operationState.receivedAt;
  const fresh = !operationState.error && Number.isFinite(referenceNowMs) && now - operationState.receivedAt < 5000;
  const metadataFresh = !infoState.error && now - infoState.receivedAt < 20000;
  const ready = ['real', 'sitl'].includes(runtimeMode) && fresh && metadataFresh && infoState.data?.exists && infoState.data?.sha256
    && !active && !dispatch.pending.launch && ids.length > 0
    && selected.every(d => d?.telemetry_fresh && (d.ready_to_arm || d.armed === true));
  const recoveryIds = operation?.operation_target_ids?.length ? operation.operation_target_ids.map(String) : ids;
  const identity = infoState.data?.sha256;
  const startStatus = formatShowOperationStart(operation, referenceNowMs, fresh);
  const scopeKey = JSON.stringify([runtimeMode, ids, recoveryIds, identity, schedule]);
  const names = targets => targets.map(id => `${fleet.find(d => String(d.hw_id) === id)?.name || `H${id}`} (H${id})`).join(' · ');
  const openReview = action => {
    setReviewError('');
    try {
      const targets = action === 'launch' ? ids : recoveryIds;
      const command = buildShowCommand(action, targets, { custom: true, ...schedule,
        delay: schedule.timeDelay, referenceNowMs });
      setReview({ action, command, scopeKey });
    } catch (e) { setReviewError(e.message); }
  };
  const execute = async () => {
    if (!review || review.scopeKey !== scopeKey || (review.action === 'launch' && !ready)) return;
    if (await dispatch.submit(review.action, review.command)) setReview(null);
  };
  return <section className="custom-show-operate" aria-label="Custom CSV operations">
    <p><strong>Local frame</strong> · Every selected aircraft replays the same active.csv from its own launch frame.</p>
    <p>Not a SkyBrush show or a swarm-leader command. Review spacing before launch.</p>
    <details><summary>Active CSV identity</summary><code>{identity || 'Identity unavailable'}</code>
      <p>GCS file fingerprint for review only; this is not proof of the file installed on each aircraft.</p></details>
    {(!fresh || !metadataFresh) && <OperatorNotice tone="warning" title="Live review unavailable">Launch requires current aircraft and CSV information. Last outcome may be unconfirmed.</OperatorNotice>}
    <ShowReceiptRecovery dispatch={dispatch} />
    {reviewError && <OperatorNotice tone="warning" title="Review timing">{reviewError}</OperatorNotice>}
    <div className="custom-show-operate__toolbar">
      <strong>{ids.length} selected · {ids.filter(id => !visible.some(d => String(d.hw_id) === id)).length} hidden</strong>
      <button type="button" className="operator-button" onClick={() => setIds(fleet.map(d => String(d.hw_id)))}>Select all</button>
      <button type="button" className="operator-button" onClick={() => setIds([])}>Clear</button>
      <label>Find aircraft<input type="search" value={query} onChange={e => setQuery(e.target.value)} /></label>
    </div>
    <div className="custom-show-operate__aircraft">
      {visible.map(d => <label key={d.hw_id}><input type="checkbox" checked={ids.includes(String(d.hw_id))}
        onChange={() => setIds(previous => previous.includes(String(d.hw_id))
          ? previous.filter(id => id !== String(d.hw_id)) : [...previous, String(d.hw_id)])} />
        <strong>{d.name} · H{d.hw_id}</strong><span>{fresh && d.telemetry_fresh
          ? d.armed === true ? 'Armed' : d.ready_to_arm ? 'Ready' : d.readiness_summary : 'Unavailable'}</span>
      </label>)}
    </div>
    <ShowScheduleFields value={schedule} onChange={setSchedule} referenceNowMs={referenceNowMs} disabled={dispatch.busy} />
    <div className="custom-show-operate__toolbar">
      {Object.entries(LABELS).map(([action, label]) => <button type="button" className="operator-button" key={action}
        disabled={dispatch.busy || Boolean(dispatch.pending[action]) || (action === 'launch' ? !ready : !recoveryIds.length || !['real', 'sitl'].includes(runtimeMode))}
        onClick={() => openReview(action)}>{label}</button>)}
    </div>
    <p role="status">{operation?.command_id ? `${fresh ? operation.phase : 'Outcome unconfirmed'} · ${operation.command?.executions?.succeeded || 0}/${operation.command?.target_drones?.length || 0} complete` : 'No Custom CSV operation recorded.'}</p>
    {startStatus && <p role="status">{startStatus}</p>}
    <ConfirmDialog appearance="console" open={Boolean(review)} title={LABELS[review?.action] || 'Review command'}
      confirmLabel={LABELS[review?.action] || 'Confirm'} busy={dispatch.busy} onCancel={() => setReview(null)} onConfirm={execute}
      confirmDisabled={!review || review.scopeKey !== scopeKey || Boolean(dispatch.pending[review?.action]) || !dispatch.enabled || (review.action === 'launch' && !ready)}
      message={review && <div><p>{names(review.command.target_drone_ids)}</p>
        {review.action === 'launch' ? <><p>Local frame · {formatShowStart(review.command.trigger_time)}</p>
          <p>{getMissionExecutionPolicy(3, { isImmediate: review.command.trigger_time === 0 })}</p></>
          : <p>{review.action === 'cancel' ? 'Cancels the mission; cancellation alone is not verified Hold or landing.'
            : review.action === 'rtl' ? 'Immediate PX4 RTL for these aircraft. Return paths may overlap.'
              : review.action === 'hold' ? 'Ends the mission and holds position; this is not a resumable pause.' : 'Ends the mission and lands at current positions.'}</p>}</div>} />
  </section>;
}

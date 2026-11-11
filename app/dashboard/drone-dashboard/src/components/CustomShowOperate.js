import React, { useEffect, useMemo, useState } from 'react';
import { ConfirmDialog, OperatorCard, OperatorNotice, StatusBadge } from './ui';
import { MdFlightTakeoff, MdHome, MdPauseCircleOutline, MdStop } from 'react-icons/md';
import SequentialReturnControl from './SequentialReturnControl';
import ShowScheduleFields from './ShowScheduleFields';
import ShowReceiptRecovery from './ShowReceiptRecovery';
import useShowOperation from '../hooks/useShowOperation';
import useShowAircraftSelection from '../hooks/useShowAircraftSelection';
import useCommandDispatch from '../hooks/useCommandDispatch';
import { buildShowCommand, formatShowOperationStart, formatShowStart, SHOW_OPERATION_PHASES } from '../utilities/droneShowWorkspace';
import { getMissionExecutionPolicy } from '../utilities/commandExecutionPolicy';

const LABELS = { launch: 'Launch Custom CSV', hold: 'Hold', land: 'Land here', rtl: 'Immediate RTL', cancel: 'Cancel mission' };

export default function CustomShowOperate({ infoState, runtimeMode, onSetup }) {
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
  const targetNames = targets => targets.map(id => `${fleet.find(d => String(d.hw_id) === id)?.name || `H${id}`} (H${id})`);
  const names = targets => targetNames(targets).join(' · ');
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
  const recoveryDisabled = action => dispatch.busy || Boolean(dispatch.pending[action]) || !recoveryIds.length || !['real', 'sitl'].includes(runtimeMode);
  const progress = <><strong>{fresh ? SHOW_OPERATION_PHASES[operation?.phase] || 'Active' : 'Outcome unconfirmed'}</strong>
    <span>{operation?.command?.executions?.succeeded || 0}/{operation?.command?.target_drones?.length || 0} complete</span>{startStatus && <span>{startStatus}</span>}</>;
  return <section className="custom-show-operate" aria-label="Custom CSV operations">
    {active && <section className="custom-show-operate__progress" aria-label="Custom CSV progress">{progress}</section>}
    {(!fresh || (!metadataFresh && infoState.data?.exists)) && <OperatorNotice tone="warning" title="Live review unavailable">Launch waits for current aircraft and CSV information.</OperatorNotice>}
    <ShowReceiptRecovery dispatch={dispatch} />
    {reviewError && <OperatorNotice tone="warning" title="Review timing">{reviewError}</OperatorNotice>}
    {!infoState.data?.exists && <div className="custom-show-operate__empty"><strong>Load a flight path</strong>{onSetup && <button type="button" className="operator-button operator-button--primary" onClick={onSetup}>Load CSV →</button>}</div>}
    <div className="drone-show-workspace__operate-grid">
      <OperatorCard className="drone-show-workspace__controls"><h2>Flight controls</h2>
        <ShowScheduleFields value={schedule} onChange={setSchedule} referenceNowMs={referenceNowMs} disabled={dispatch.busy} />
        <div className="drone-show-workspace__action-grid">
          <button type="button" className="drone-show-workspace__action drone-show-workspace__action--launch" disabled={dispatch.busy || !ready} onClick={() => openReview('launch')}><MdFlightTakeoff aria-hidden="true" />{LABELS.launch}</button>
          <button type="button" className="drone-show-workspace__action" disabled={recoveryDisabled('hold')} onClick={() => openReview('hold')}><MdPauseCircleOutline aria-hidden="true" />Hold</button>
          <button type="button" className="drone-show-workspace__action drone-show-workspace__action--return" disabled={recoveryDisabled('rtl')} onClick={() => openReview('rtl')}><MdHome aria-hidden="true" />Immediate RTL</button>
        </div>
        <details className="drone-show-workspace__advanced"><summary>Other actions</summary>
          <SequentialReturnControl compact targetIds={recoveryIds} targetNames={targetNames(recoveryIds)} contextKey={operation?.command_id || 'custom'}
            validateReview={() => { if (!['real', 'sitl'].includes(runtimeMode)) throw new Error('Runtime mode unavailable'); }} />
          {['land', 'cancel'].map(action => <button type="button" className="operator-button operator-button--ghost" key={action} disabled={recoveryDisabled(action)} onClick={() => openReview(action)}><MdStop aria-hidden="true" />{LABELS[action]}</button>)}
        </details>
      </OperatorCard>
      <OperatorCard className="drone-show-workspace__readiness"><h2>Preflight</h2>
        <div className="custom-show-operate__check"><span>CSV path</span><StatusBadge tone={metadataFresh && identity ? 'success' : 'warning'}>{metadataFresh && identity ? 'Loaded' : 'Check'}</StatusBadge></div>
        <div className="custom-show-operate__check"><span>Selected aircraft</span><StatusBadge tone={fresh && selected.length > 0 && selected.every(d => d?.telemetry_fresh && (d.ready_to_arm || d.armed === true)) ? 'success' : 'warning'}>{fresh ? selected.filter(d => d?.telemetry_fresh && (d.ready_to_arm || d.armed === true)).length : 0}/{ids.length} ready</StatusBadge></div>
        <p className="custom-show-page__frame-note">Same path from each aircraft’s launch point.</p>
        <details><summary>CSV identity</summary><code>{identity || 'Unavailable'}</code><p>GCS fingerprint, not proof of the file installed on each aircraft.</p></details>
      </OperatorCard>
    </div>
    <section className="drone-show-workspace__fleet-status" aria-label="Custom show aircraft">
    <div className="custom-show-operate__toolbar">
      <strong>{ids.length} selected · {ids.filter(id => !visible.some(d => String(d.hw_id) === id)).length} hidden</strong>
      <button type="button" className="operator-button" onClick={() => setIds(fleet.map(d => String(d.hw_id)))}>Select all</button>
      <button type="button" className="operator-button" onClick={() => setIds([])}>Clear</button>
      <label><span className="operator-sr-only">Find aircraft</span><input type="search" placeholder="Find aircraft" value={query} onChange={e => setQuery(e.target.value)} /></label>
    </div>
    <div className="custom-show-operate__aircraft">
      {visible.map(d => <label key={d.hw_id}><input type="checkbox" checked={ids.includes(String(d.hw_id))}
        onChange={() => setIds(previous => previous.includes(String(d.hw_id))
          ? previous.filter(id => id !== String(d.hw_id)) : [...previous, String(d.hw_id)])} />
        <span><strong>{d.name || `Aircraft ${d.hw_id}`}</strong><small>H{d.hw_id} · P{d.pos_id ?? '—'}</small></span><StatusBadge tone={fresh && d.telemetry_fresh && (d.armed || d.ready_to_arm) ? 'success' : 'muted'}>{fresh && d.telemetry_fresh
          ? d.armed === true ? 'Armed' : d.ready_to_arm ? 'Ready' : d.readiness_summary || 'Check' : 'Unavailable'}</StatusBadge>
      </label>)}
    </div>
    </section>
    {!active && operation?.command_id && <details className="custom-show-operate__history"><summary>Last run · {SHOW_OPERATION_PHASES[operation.phase] || 'Recorded'}</summary>{progress}</details>}
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

import React, { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { MdFlightTakeoff, MdHome, MdPause } from 'react-icons/md';
import SwarmTrajectory from './SwarmTrajectory';
import RouteSketch from '../components/trajectory/RouteSketch';
import TrajectoryFormationPanel from '../components/trajectory/TrajectoryFormationPanel';
import SequentialReturnControl from '../components/SequentialReturnControl';
import { ConfirmDialog, OperatorNotice, PageShell, StatusBadge } from '../components/ui';
import useGcsResourcePolling from '../hooks/useGcsResourcePolling';
import { sendDroneCommand, createCommandIdempotencyKey } from '../services/droneApiService';
import { DRONE_ACTION_TYPES } from '../constants/droneConstants';
import '../styles/SwarmTrajectoryWorkspace.css';

const BASE = '/api/v1/swarm-trajectories';
const STORE = 'mds.trajectory.pending.v1';
const LABELS = { start: 'Start mission', hold: 'Hold', rtl: 'Immediate Return' };
function readPending() {
  try { return JSON.parse(sessionStorage.getItem(STORE)) || {}; } catch { return {}; }
}
const displayTime = (seconds) => Number.isFinite(seconds)
  ? `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}` : '—';

export default function SwarmTrajectoryWorkspace() {
  const [params, setParams] = useSearchParams();
  const plan = params.get('tab') === 'plan';
  const [revision, setRevision] = useState(0);
  const workspaceState = useGcsResourcePolling(`${BASE}/workspace`, 15000, revision);
  const operationState = useGcsResourcePolling(`${BASE}/operation`, 2000, revision);
  const workspace = workspaceState.data;
  const operation = operationState.data;
  const active = operation?.state === 'active';
  const [clusterId, setClusterId] = useState(null);
  const [delay, setDelay] = useState(15);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState(readPending);
  const clusters = workspace?.status?.clusters || [];
  const cluster = clusters.find((c) => String(c.leader_id) === clusterId) || clusters[0];
  const ids = useMemo(() => (active && operation?.operation_target_ids?.length
    ? operation.operation_target_ids : cluster ? [cluster.leader_id, ...(cluster.follower_ids || [])] : []).map(String),
  [cluster, active, operation]);
  const fleet = operation?.fleet || [];
  const selected = ids.map((id) => fleet.find((d) => String(d.hw_id) === id));
  const recoveryIds = operation?.operation_target_ids?.length && (active || fleet.some((d) => d.armed === true))
    ? operation.operation_target_ids.map(String) : ids;
  const connected = !workspaceState.error && !operationState.error && workspace && operation;
  const snapshotsFresh = () => performance.now() - operationState.receivedAt < 5000
    && performance.now() - workspaceState.receivedAt < 20000;
  const aircraftReady = selected.length > 0 && selected.every((d) => d?.telemetry_fresh
    && d.ready_to_arm && d.armed === false && d.landed_state === 1);
  const ready = connected && snapshotsFresh() && workspace.validation?.ready === true && workspace.launch_identity
    && aircraftReady && !active && Number(delay) >= 10 && Number(delay) <= 3600;
  const mode = workspace?.simulation_mode ? 'SITL' : 'REAL';
  const pendingKey = `${mode}.start`;
  const pendingStart = pending[pendingKey];
  const scopeKey = JSON.stringify([ids, workspace?.launch_identity, delay, mode]);
  const previews = (workspace?.preview?.drones || []).filter((d) => ids.includes(String(d.drone_id)));
  const names = (targetIds) => targetIds.map((id) => fleet.find((d) => String(d.hw_id) === id)?.name || `H${id}`);
  const openReview = (action) => {
    const previous = pending[`${mode}.${action}`];
    setReview({ action, recovering: Boolean(previous),
      ids: [...(previous?.command?.target_drone_ids || (action === 'start' ? ids : recoveryIds))], scopeKey });
  };

  const execute = async (recover = false) => {
    const action = recover ? 'start' : review?.action;
    if (!action || busy) return;
    if (!recover && (review.scopeKey !== scopeKey || (action === 'start' && (!ready || !snapshotsFresh())))) {
      setReview(null); setError('Mission or aircraft state changed. Review again.'); return;
    }
    setBusy(true); setError(''); setNotice('');
    const key = `${mode}.${action}`;
    try {
      let request = pending[key];
      if (!request) {
        const targetIds = review.ids;
        const referenceMs = operation.timestamp + performance.now() - operationState.receivedAt;
        const command = { mission_type: action === 'start' ? 4 : action === 'hold'
          ? DRONE_ACTION_TYPES.HOLD : DRONE_ACTION_TYPES.RETURN_RTL,
        target_drone_ids: targetIds, trigger_time: action === 'start'
          ? Math.ceil(referenceMs / 1000 + Number(delay)) : 0,
        operator_label: `Swarm Trajectory · ${action}`, idempotency_key: createCommandIdempotencyKey() };
        if (action === 'start') command.swarm_trajectory = {
          revision: workspace.launch_identity.revision,
          files: Object.fromEntries(targetIds.map((id) => [id, workspace.launch_identity.files[id]])),
        };
        request = { command, action };
        const next = { ...pending, [key]: request };
        // Preserve identity before the request, including across a page reload.
        sessionStorage.setItem(STORE, JSON.stringify(next)); setPending(next);
      }
      const receipt = await sendDroneCommand(request.command, { recoverAmbiguousSubmission: false });
      if (receipt?.accepted_for_tracking !== true || !receipt.command_id) throw new Error('Receipt unconfirmed');
      const next = { ...readPending() }; delete next[key];
      sessionStorage.setItem(STORE, JSON.stringify(next)); setPending(next);
      setReview(null); setRevision((r) => r + 1);
      setNotice('Command accepted. Aircraft execution is monitored below.');
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Command unconfirmed. Check aircraft status.');
    } finally { setBusy(false); }
  };

  return <PageShell title="Swarm Trajectory" docsRoute="/swarm-trajectory" className="trajectory-console operator-console"
    status={<StatusBadge tone={workspace?.simulation_mode ? 'info' : 'neutral'}>{workspace ? mode : 'Connecting'}</StatusBadge>}>
    <nav className="trajectory-console__tabs" aria-label="Trajectory workspace">
      {['operate', 'plan'].map((tab) => <button key={tab} type="button" aria-current={(plan ? 'plan' : 'operate') === tab ? 'page' : undefined}
        onClick={() => { setParams({ tab }); setRevision((r) => r + 1); }}>{tab === 'plan' ? 'Plan' : 'Operate'}</button>)}
    </nav>
    {plan ? <><TrajectoryFormationPanel formation={workspace?.formation} fleet={fleet}
      readOnly={active} onSaved={() => setRevision((r) => r + 1)} />
      <SwarmTrajectory key={workspace?.formation?.revision} embedded fleet={fleet}
        formationAssignments={workspace?.formation?.assignments || []} /></> : <>
      {(!connected && !workspaceState.loading) && <OperatorNotice tone="warning" title="Connection unavailable">Refresh mission and aircraft state before starting.</OperatorNotice>}
      {error && <OperatorNotice tone="warning" title="Check command status">{error}</OperatorNotice>}
      {notice && <p className="trajectory-console__notice" role="status">{notice}</p>}
      {pendingStart && <OperatorNotice tone="warning" title="Start receipt unconfirmed"
        action={<button type="button" className="operator-button" disabled={busy || !workspace} onClick={() => execute(true)}>Recover receipt</button>}>
        Check aircraft state. Retry uses the original request identity and start time.
      </OperatorNotice>}
      <section className="trajectory-console__command-rail" aria-label="Flight controls">
        <label>Cluster<select aria-label="Mission cluster" value={cluster?.leader_id || ''} disabled={active || busy}
          onChange={(e) => setClusterId(e.target.value)}>{clusters.map((c) => <option key={c.leader_id} value={c.leader_id}>
            {fleet.find((d) => String(d.hw_id) === String(c.leader_id))?.name || `H${c.leader_id}`} · {1 + (c.follower_ids || []).length} aircraft
          </option>)}</select></label>
        <label>Start in (s)<input aria-label="Mission start delay" type="number" min="10" max="3600" value={delay}
          disabled={active || busy} onChange={(e) => setDelay(e.target.value)} /></label>
        <button type="button" className="operator-button operator-button--primary" disabled={!ready || busy || Boolean(pendingStart)} onClick={() => openReview('start')}><MdFlightTakeoff />Start mission</button>
        <button type="button" className="operator-button operator-button--ghost" disabled={busy || !recoveryIds.length} onClick={() => openReview('hold')}><MdPause />Hold</button>
        <button type="button" className="operator-button operator-button--ghost trajectory-console__return" disabled={busy || !recoveryIds.length} onClick={() => openReview('rtl')}><MdHome />Immediate Return</button>
        <details className="trajectory-console__other"><summary>Other actions</summary>
          <SequentialReturnControl compact targetIds={recoveryIds} targetNames={names(recoveryIds)} contextKey={operation?.command_id || 'trajectory'} />
        </details>
      </section>
      <div className="trajectory-console__status" role="status">
        <strong>{active ? 'Mission active' : operation?.phase === 'idle' ? 'No active mission' : operation?.phase || 'Connecting'}</strong>
        <span>{ids.length} aircraft</span><span>Route {displayTime(workspace?.status?.package_stats?.mission_clock_s)}</span>
        <span>{workspace?.validation?.ready ? 'Package ready' : 'Package needs review'}</span>
        {!aircraftReady && !active && <button type="button" onClick={() => document.getElementById('trajectory-aircraft')?.scrollIntoView({ block: 'nearest' })}>Check aircraft</button>}
      </div>
      {(workspace?.validation?.blockers || []).length > 0 && <OperatorNotice tone="warning" title="Mission needs attention"
        action={<button type="button" className="operator-button" onClick={() => setParams({ tab: 'plan' })}>Open Plan</button>}>
        {workspace.validation.blockers[0].message}
      </OperatorNotice>}
      <div className="trajectory-console__body">
        <section className="trajectory-console__preview" aria-label="Planned routes">
          <h2>Planned routes</h2><RouteSketch series={previews.map((d) => ({ id: d.drone_id, label: `H${d.drone_id}`, points: d.points }))} />
        </section>
        <section id="trajectory-aircraft" className="trajectory-console__aircraft" aria-label="Aircraft status">
          <h2>Aircraft</h2>{selected.length === 0 && <p>Choose a cluster in Plan.</p>}
          {selected.map((d, index) => { const progress = d?.trajectory_execution;
            return <div className="trajectory-console__aircraft-row" key={ids[index]}>
              <strong>{d?.name || `H${ids[index]}`}</strong><span>{d?.telemetry_fresh ? d.state : 'No fresh telemetry'}</span>
              <span>{d?.battery_percent != null ? `${Math.round(d.battery_percent)}%` : '—'}</span>
              {progress?.fresh && progress.phase === 'trajectory' ? <span>Route {displayTime(progress.trajectory_time_s)} / {displayTime(progress.duration_s)}</span>
                : <span>{progress ? (progress.fresh ? progress.phase : 'Progress stale') : d?.readiness_summary || 'Checking aircraft'}</span>}
            </div>; })}
        </section>
      </div>
    </>}
    <ConfirmDialog appearance="console" open={Boolean(review)} title={review?.recovering
      ? `Recover ${LABELS[review.action]} receipt` : LABELS[review?.action] || 'Review mission'}
      message={review ? <div><p>{names(review.ids).join(' · ')}</p>
        <p>{review.recovering ? 'Retry the original unconfirmed request for these aircraft.'
          : review.action === 'start' ? `Launch from the ground in ${delay}s and execute the planned routes.`
          : review.action === 'hold' ? 'Hold all mission aircraft. This ends the current route; coordinated resume is not enabled yet.'
            : 'Hand control to each aircraft’s native Return. Return paths may overlap.'}</p></div> : null}
      confirmDisabled={!review || review.scopeKey !== scopeKey || (review.action === 'start' && !ready)}
      confirmLabel={LABELS[review?.action] || 'Confirm'}
      busy={busy} onCancel={() => setReview(null)} onConfirm={() => execute()} />
  </PageShell>;
}

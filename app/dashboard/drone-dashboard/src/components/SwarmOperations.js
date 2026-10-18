import React, { useEffect, useRef, useState } from 'react';
import { FaArrowUp, FaPlay, FaPause, FaEllipsisH } from 'react-icons/fa';
import { fetchGcsResource } from '../services/gcsApiService';
import { getBackendURL } from '../config/apiConfig';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { memberFlightState, memberLabel, movementSummary, takeoffTargets } from '../utilities/swarmOperationModel';
import { ConfirmDialog, StatusBadge } from './ui/OperatorPrimitives';
import SequentialReturnControl from './SequentialReturnControl';
import SwarmClusterDiagram from './SwarmClusterDiagram';
import { swarmNodeStatus } from '../utilities/swarmDiagramModel';
import '../styles/SwarmOperations.css';

const PREVIEW = '/api/v1/swarm/runtime/preview';
const EMPTY_CLUSTERS = [];
const LABELS = { takeoff: 'Takeoff', start: 'Start Swarm', hold: 'Stop following', land: 'Land here', rtl: 'Immediate RTL' };
const TYPES = { takeoff: 10, start: 2, hold: 102, land: 101, rtl: 104 };
const RUNTIME_LABELS = { starting: 'Starting', active: 'Following', acquiring: 'Joining formation', settling: 'Settling',
  holding: 'Holding', partial: 'Partial', tracking_degraded: 'Link delayed', degraded: 'Degraded',
  pilot_takeover: 'Pilot takeover', stopped: 'Stopped', unconfirmed: 'Unconfirmed' };

export default function SwarmOperations() {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const [previewError, setPreviewError] = useState(false);
  const [selection, setSelection] = useState({ key: null, id: null });
  const [confirmation, setConfirmation] = useState(null);
  const [height, setHeight] = useState(10);
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [individual, setIndividual] = useState('');
  const [inspectedId, setInspectedId] = useState(null);
  const submitting = useRef(false);
  const { commandLifecycleCallbacks, commandMonitors = [] } = useCommandActivity();

  useEffect(() => {
    let live = true;
    let timer;
    const poll = async () => {
      try {
        const response = await fetchGcsResource(PREVIEW);
        if (live) { setPreview(response.data); setPreviewError(false); }
      } catch (_) { if (live) setPreviewError(true); }
      finally { if (live) timer = setTimeout(poll, 2000); }
    };
    poll();
    return () => { live = false; clearTimeout(timer); };
  }, []);

  const storageKey = preview ? `mds-swarm:${getBackendURL()}:${preview.runtime_mode || 'unknown'}` : null;
  const clusters = preview?.clusters || EMPTY_CLUSTERS;
  useEffect(() => {
    if (!storageKey || selection.key === storageKey) return;
    let saved = null;
    try { saved = sessionStorage.getItem(storageKey); } catch (_) { /* storage is optional */ }
    setSelection({ key: storageKey, id: saved || clusters[0]?.cluster_id || null });
  }, [storageKey, selection.key, clusters]);
  const chooseCluster = (id) => {
    setSelection({ key: storageKey, id });
    setConfirmation(null);
    setIndividual('');
    try { sessionStorage.setItem(storageKey, id); } catch (_) { /* storage is optional */ }
  };
  // A disappeared explicit cluster is intentionally NOT replaced by another.
  const cluster = selection.key === storageKey
    ? clusters.find((item) => item.cluster_id === selection.id) : null;
  const members = cluster?.members || [];
  const ids = members.map((m) => m.hw_id);
  const names = members.map(memberLabel);
  const states = Object.fromEntries(members.map((m) => [m.hw_id, memberFlightState(m)]));
  const inspected = members.find((m) => m.hw_id === inspectedId);
  const airborne = members.filter((m) => ['Airborne', 'Taking off', 'Returning', 'Landing'].includes(states[m.hw_id])).length;
  const grounded = members.filter((m) => states[m.hw_id] === 'Grounded').length;
  const monitor = commandMonitors.find((m) => m.missionType === 2
    && m.targetDrones?.length > 0 && m.targetDrones.every((id) => ids.includes(id)));
  const runtime = monitor?.swarmRuntime;
  const liveRuntime = !previewError && runtime && !monitor?.trackingIssue
    && Date.now() - monitor.updatedAtMs < 15000;
  const runtimeLabel = liveRuntime ? (monitor.targetDrones.length < ids.length
    ? `Partial · ${runtime.active_hw_ids?.length || 0}/${ids.length} engaged`
    : RUNTIME_LABELS[runtime.state]) : null;
  const status = previewError ? 'Telemetry delayed' : runtimeLabel
    || (members.length ? `${airborne}/${members.length} airborne` : preview ? 'Select formation' : 'Loading…');
  const validHeight = Number.isFinite(Number(height)) && Number(height) > 0;
  const nodeStatuses = Object.fromEntries(members.map((member) => [member.hw_id,
    swarmNodeStatus(member, runtime?.nodes?.[member.hw_id], { stale: !liveRuntime, hasSession: Boolean(monitor) })]));

  const review = (action, excluded = [], individualRecovery = false) => {
    if (!cluster || busy) return;
    let targets = action === 'takeoff' ? takeoffTargets(members) : ids;
    if (individualRecovery && ids.includes(individual) && ['hold', 'land', 'rtl'].includes(action)) targets = [individual];
    targets = targets.filter((id) => !excluded.includes(id));
    if (!targets.length) { setError('Check aircraft states before takeoff.'); return; }
    setError('');
    setConfirmation({ action, targets, excluded, revision: preview.revision,
      clusterId: cluster.cluster_id, key: `swarm-${Date.now()}-${Math.random().toString(16).slice(2)}` });
  };
  const freshReview = async (reviewed) => {
    const response = await fetchGcsResource(PREVIEW);
    const current = response.data;
    const currentCluster = current.clusters.find((c) => c.cluster_id === reviewed.clusterId);
    if (current.revision !== reviewed.revision || !currentCluster
        || selection.id !== reviewed.clusterId) throw new Error('Formation changed. Review the targets again.');
    if (reviewed.action === 'takeoff') {
      const targets = takeoffTargets(currentCluster.members);
      if (targets.join(',') !== reviewed.targets.join(',')) throw new Error('Flight state changed. Review takeoff targets again.');
    }
    setPreview(current);
    return true;
  };
  const send = async () => {
    if (!confirmation || submitting.current || (confirmation.action === 'takeoff' && !validHeight)) return;
    const reviewed = confirmation;
    submitting.current = true;
    setBusy(true);
    try {
      await freshReview(reviewed);
      const command = { mission_type: TYPES[reviewed.action], trigger_time: 0,
        target_drone_ids: reviewed.targets, idempotency_key: reviewed.key,
        uiMeta: { operatorLabel: LABELS[reviewed.action], targetLabel: `Cluster ${reviewed.clusterId}` } };
      if (reviewed.action === 'takeoff') command.takeoff_altitude = Number(height);
      if (reviewed.action === 'start') command.smart_swarm_start = {
        cluster_id: reviewed.clusterId, revision: reviewed.revision,
        excluded_hw_ids: reviewed.excluded, idempotency_key: reviewed.key,
      };
      await submitCommandWithLifecycleFeedback(command, commandLifecycleCallbacks);
      setConfirmation(null);
    } catch (exc) {
      const detail = exc?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : exc.message || 'Command not confirmed. Check aircraft status.');
    } finally { submitting.current = false; setBusy(false); }
  };
  const exclusions = cluster?.partial_exclusion_hw_ids || [];
  const canStop = Boolean(monitor && !monitor.isTerminal);
  const contextKey = `${selection.id}:${preview?.revision}`;

  return (
    <section className="swarm-ops operator-console" aria-label="Swarm operations">
      <header className="swarm-ops__header">
        <div><h3>Swarm</h3><label>
          <select aria-label="Swarm formation" value={cluster?.cluster_id || ''} disabled={busy}
            onChange={(e) => chooseCluster(e.target.value)}>
            {!cluster && <option value="">Select formation</option>}
            {clusters.map((c) => <option key={c.cluster_id} value={c.cluster_id}>Cluster {c.cluster_id} · {c.members.length} drones</option>)}
          </select>
        </label></div>
        <StatusBadge tone={previewError || (runtimeLabel && runtimeLabel !== 'Following') ? 'warning' : 'neutral'}>{status}</StatusBadge>
      </header>
      <SwarmClusterDiagram members={members} selectedId={inspectedId} onSelect={setInspectedId}
        statuses={Object.fromEntries(members.map((m) => [m.hw_id, { ...nodeStatuses[m.hw_id],
          label: `${states[m.hw_id]} · ${nodeStatuses[m.hw_id].label}${m.available && Number.isFinite(m.battery_remaining) ? ` · ${Math.round(m.battery_remaining)}%` : ''}` }]))} />
      {inspected && <div className="swarm-ops__inspection" aria-label="Aircraft details">
        <strong>{memberLabel(inspected)}</strong><span>{movementSummary(inspected)}</span>
        {inspected.readiness_summary && <span>{inspected.readiness_summary}</span>}
        <button type="button" className="operator-button operator-button--ghost" onClick={() => setInspectedId(null)}>Close details</button>
      </div>}
      {members.some((m) => m.readiness_status === 'blocked') && <p className="swarm-ops__attention" role="status">
        {members.filter((m) => m.readiness_status === 'blocked').map((m) => `${memberLabel(m)}: ${m.readiness_summary || 'Not ready'}`).join(' · ')}
      </p>}
      <div className="swarm-ops__actions">
        <button type="button" className={`operator-button ${grounded === members.length ? 'operator-button--primary' : 'operator-button--ghost'}`}
          disabled={busy || !cluster || !takeoffTargets(members).length} onClick={() => review('takeoff')}><FaArrowUp aria-hidden="true" /> Takeoff</button>
        <button type="button" className={`operator-button ${airborne === members.length && !canStop ? 'operator-button--primary' : 'operator-button--ghost'}`}
          disabled={busy || !cluster || canStop} onClick={() => review('start')}><FaPlay aria-hidden="true" /> Start Swarm</button>
        <SequentialReturnControl targetIds={ids} targetNames={names} compact contextKey={contextKey}
          aircraftStates={states} validateReview={() => freshReview({ clusterId: selection.id, revision: preview.revision })} />
      </div>
      <div className="swarm-ops__secondary">
        {canStop && <button type="button" className="operator-button operator-button--ghost" disabled={busy} onClick={() => review('hold')}><FaPause aria-hidden="true" /> Stop following</button>}
        <button type="button" className="operator-button operator-button--ghost" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}><FaEllipsisH aria-hidden="true" /> Other actions</button>
        <a href="/swarm-design?tab=formation">Design Swarm</a>
        <a href="/globe-view">Globe</a>
      </div>
      {advanced && <div className="swarm-ops__advanced">
        <label>Recovery targets <select aria-label="Recovery targets" value={individual} onChange={(e) => setIndividual(e.target.value)}>
          <option value="">Entire cluster</option>{members.map((m) => <option key={m.hw_id} value={m.hw_id}>{memberLabel(m)} only</option>)}
        </select></label>
        {['hold', 'land', 'rtl'].map((action) => <button className="operator-button operator-button--ghost" type="button" key={action} disabled={busy || !cluster} onClick={() => review(action, [], true)}>{LABELS[action]}</button>)}
        {exclusions.length > 0 && <button className="operator-button operator-button--ghost" type="button" disabled={busy} onClick={() => review('start', exclusions)}>Start partial · without {exclusions.join(', ')}</button>}
      </div>}
      {!cluster && preview && <p role="status">{clusters.length ? 'Select a saved formation.' : <a href="/swarm-design?tab=formation">Create a formation</a>}</p>}
      {error && <p role="alert">{error}</p>}
      <ConfirmDialog appearance="console" open={Boolean(confirmation)} title={confirmation ? LABELS[confirmation.action] : 'Confirm'}
        confirmDisabled={confirmation?.action === 'takeoff' && !validHeight}
        confirmLabel={confirmation ? `Confirm ${LABELS[confirmation.action]}` : 'Confirm'} busy={busy}
        onCancel={() => !busy && setConfirmation(null)} onConfirm={send}
        message={confirmation ? <div className="swarm-ops__confirmation">
          <strong>{confirmation.targets.map((id) => memberLabel(members.find((m) => m.hw_id === id) || { hw_id: id })).join(' · ')}</strong>
          {confirmation.action === 'takeoff' && <label>Takeoff height <input type="number" min="0.1" step="1" aria-label="Takeoff height" value={height} onChange={(e) => setHeight(e.target.value)} /> m
            {!validHeight && <span role="alert">Enter a positive height.</span>}<small>Takeoff only · following stays off.</small></label>}
          {confirmation.action === 'start' && <ul>{members.filter((m) => confirmation.targets.includes(m.hw_id)).map((m) => <li key={m.hw_id}>Drone {m.hw_id}: {movementSummary(m)} · {m.frame === 'body' ? 'Body' : 'NED'}</li>)}</ul>}
          {confirmation.excluded.length > 0 && <p>Partial formation · excludes Drone {confirmation.excluded.join(', ')}.</p>}
          {confirmation.action === 'hold' && <p>Stop following and command Hold.</p>}
          {confirmation.action === 'land' && <p>Land at current positions.</p>}
          {confirmation.action === 'rtl' && <p>Immediate PX4 RTL · paths may overlap. Return heights: unavailable here; each aircraft uses its configured settings.</p>}
          {error && <p role="alert">{error}</p>}
        </div> : ''} />
    </section>
  );
}

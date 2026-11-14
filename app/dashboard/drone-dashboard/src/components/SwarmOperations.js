import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FaArrowUp, FaPlay, FaPause, FaEllipsisH, FaLayerGroup, FaLink } from 'react-icons/fa';
import { fetchGcsResource } from '../services/gcsApiService';
import { isAmbiguousSubmissionTransportFailure } from '../services/droneApiService';
import { getBackendURL } from '../config/apiConfig';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import { useAuth } from '../contexts/AuthContext';
import { submitCommandWithLifecycleFeedback, trackCommandReceipt } from '../utilities/commandLifecycleFeedback';
import { holdNodeStatus, memberFlightState, memberLabel, movementSummary } from '../utilities/swarmOperationModel';
import { ConfirmDialog, StatusBadge } from './ui/OperatorPrimitives';
import SequentialReturnControl from './SequentialReturnControl';
import SwarmClusterDiagram from './SwarmClusterDiagram';
import SwarmFormationSource from './SwarmFormationSource';
import TakeoffDialog from './TakeoffDialog';
import CommandAircraftControl from '../features/fleet-overview/CommandAircraftControl';
import CommandAircraftPicker from '../features/fleet-overview/CommandAircraftPicker';
import useSwarmCommandScope from '../features/fleet-overview/useSwarmCommandScope';
import { swarmReferenceIds, swarmStartQuery, swarmReviewEvidence, swarmNamesSummary } from '../utilities/swarmCommandScope';
import { swarmNodeStatus } from '../utilities/swarmDiagramModel';
import { swarmStartReadiness, swarmStartValidUntil } from '../utilities/swarmStartReadiness';
import { formationReferenceLabel } from '../utilities/swarmDesignPresentation';
import '../styles/SwarmOperations.css';

const PREVIEW = '/api/v1/swarm/runtime/preview';
const EMPTY_CLUSTERS = [];
const EMPTY_MEMBERS = [];
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
  const height = 10;
  const [busy, setBusy] = useState(false);
  const [holdBusy, setHoldBusy] = useState(false);
  const [holdReceipt, setHoldReceipt] = useState(null);
  const [advanced, setAdvanced] = useState(false);
  const [choosingRecipients, setChoosingRecipients] = useState(false);
  const [inspectedId, setInspectedId] = useState(null);
  const [startCheck, setStartCheck] = useState(null);
  const [pendingStart, setPendingStart] = useState(null);
  const submitting = useRef(false);
  const startSubmitting = useRef(false);
  const busyOwner = useRef(null);
  const holdSubmitting = useRef(false);
  const pendingHold = useRef(null);
  const intentEpoch = useRef(0);
  const scope = useRef(null);
  const { commandLifecycleCallbacks, commandMonitors = [] } = useCommandActivity();
  const auth = useAuth();

  useEffect(() => {
    let live = true;
    let timer;
    const poll = async () => {
      try {
        const response = await fetchGcsResource(PREVIEW);
        if (live) { setPreview({ ...response.data, receivedAtMs: Date.now() }); setPreviewError(false); }
      } catch (_) { if (live) setPreviewError(true); }
      finally { if (live) timer = setTimeout(poll, 2000); }
    };
    poll();
    return () => { live = false; clearTimeout(timer); };
  }, []);

  const storageKey = preview ? `mds-swarm:${getBackendURL()}:${preview.runtime_mode || 'unknown'}` : null;
  const pendingKey = storageKey ? `${storageKey}:pending-start` : null;
  useEffect(() => {
    if (!pendingKey) return;
    scope.current = pendingKey;
    setConfirmation(null);
    setError('');
    setPendingStart(null);
    setHoldReceipt(null);
    try {
      const pending = JSON.parse(sessionStorage.getItem(pendingKey));
      if (pending?.reviewed?.action === 'start'
          && pending.reviewed.key === pending.command?.smart_swarm_start?.idempotency_key) setPendingStart(pending);
    } catch (_) { /* live command history remains available if browser storage is disabled */ }
  }, [pendingKey]);
  const rememberPending = (pending, key = pendingKey) => {
    if (scope.current === key) setPendingStart(pending);
    try {
      if (pending) sessionStorage.setItem(key, JSON.stringify(pending));
      else sessionStorage.removeItem(key);
    } catch (_) { /* storage is optional */ }
  };

  useEffect(() => {
    setStartCheck(null);
    if (confirmation?.action !== 'start' || (pendingStart && !pendingStart.needsReview)) return undefined;
    let live = true;
    let pollTimer;
    let expiryTimer;
    const check = async () => {
      const requestedAt = Date.now();
      try {
        const { data } = await fetchGcsResource(PREVIEW, { params: swarmStartQuery(confirmation.clusterId, confirmation.targets) });
        if (!live) return;
        if (data.revision !== confirmation.revision) {
          setError('Formation changed. Review the targets again.');
          setStartCheck(null);
          return;
        }
        const evidence = swarmReviewEvidence(confirmation, data, requestedAt, swarmStartValidUntil);
        setStartCheck(evidence);
        clearTimeout(expiryTimer);
        if (evidence) expiryTimer = setTimeout(() => live && setStartCheck({ ...evidence }), Math.max(0, evidence.until - Date.now()));
      } catch (exc) {
        const detail = exc?.response?.data?.detail;
        if (live) setStartCheck({ error: typeof detail === 'string' ? detail : detail?.message || 'Readiness unavailable. Check the aircraft link.' });
      }
      finally { if (live) pollTimer = setTimeout(check, 1000); }
    };
    check();
    return () => { live = false; clearTimeout(pollTimer); clearTimeout(expiryTimer); };
  }, [confirmation, pendingStart]);
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
    setChoosingRecipients(false);
    try { sessionStorage.setItem(storageKey, id); } catch (_) { /* storage is optional */ }
  };
  // A disappeared explicit cluster is intentionally NOT replaced by another.
  const cluster = selection.key === storageKey
    ? clusters.find((item) => item.cluster_id === selection.id) : null;
  // Keep the saved relationship/selection visible across a failed preview,
  // without presenting cached flight or readiness fields as current evidence.
  const members = useMemo(() => previewError
    ? (cluster?.members || EMPTY_MEMBERS).map((member) => ({ ...member, available: false }))
    : cluster?.members || EMPTY_MEMBERS, [cluster, previewError]);
  const ids = members.map((m) => m.hw_id);
  const commandScope = useSwarmCommandScope(cluster && !auth.loading
    ? JSON.stringify([storageKey, cluster.cluster_id, auth.user?.username || auth.user?.id || 'trusted-session']) : null, ids);
  const canCommand = commandScope.initialized && commandScope.ids.length > 0 && !commandScope.missing.length;
  const pickerAircraft = members.map(member => ({ id: member.hw_id, label: member.callsign || `Drone ${member.hw_id}`,
    raw: member, identity: { posId: member.pos_id }, availability: { available: member.available, label: member.available ? 'Available' : 'Telemetry delayed' } }));
  const states = Object.fromEntries(members.map((m) => [m.hw_id, memberFlightState(m)]));
  const inspected = members.find((m) => m.hw_id === inspectedId);
  const airborne = members.filter((m) => ['Airborne', 'Taking off', 'Returning', 'Landing'].includes(states[m.hw_id])).length;
  const monitor = commandMonitors.find((m) => m.missionType === 2
    && m.targetDrones?.length > 0 && m.targetDrones.every((id) => ids.includes(id)));
  const runtime = monitor?.swarmRuntime;
  const liveRuntime = !previewError && runtime && !monitor?.isTerminal && !monitor?.trackingIssue
    && Date.now() - monitor.updatedAtMs < 15000;
  let runtimeLabel = liveRuntime ? (monitor.targetDrones.length < ids.length
    ? `Partial · ${runtime.active_hw_ids?.length || 0}/${ids.length} engaged`
    : RUNTIME_LABELS[runtime.state]) : null;
  const evidenceNow = (preview?.observed_at_ms || Date.now()) + Math.max(0, Date.now() - (preview?.receivedAtMs || Date.now()));
  const nodeStatuses = Object.fromEntries(members.map((member) => {
    const evidence = preview?.runtime_nodes?.[member.hw_id];
    return [member.hw_id, evidence ? swarmNodeStatus(member, evidence.report, {
      stale: previewError || evidence.stale, hasSession: evidence.has_session, now: evidenceNow,
    }) : swarmNodeStatus(member, runtime?.nodes?.[member.hw_id], { stale: !liveRuntime, hasSession: Boolean(monitor && !monitor.isTerminal) })];
  }));
  if (preview?.runtime_nodes && members.some(m => preview.runtime_nodes[m.hw_id]?.has_session)) {
    const engaged = Object.values(nodeStatuses).filter(node => ['Following','Leading','Joining','Settling','Data delayed'].includes(node.label)).length;
    runtimeLabel = `${engaged}/${members.length} engaged`;
  }
  const runtimeAttention = Object.values(nodeStatuses).some(node => ['warning', 'danger'].includes(node.tone));
  const newerMission = holdReceipt && commandMonitors.some((m) => m.commandId !== holdReceipt.commandId
    && m.missionType !== 102 && !holdReceipt.knownCommandIds.includes(m.commandId)
    && m.updatedAtMs > holdReceipt.sentAtMs
    && m.targetDrones?.some((id) => ids.includes(id)));
  const heldScope = Boolean(holdReceipt && holdReceipt.clusterId === cluster?.cluster_id && !newerMission
    && !members.some((m) => ['Returning', 'Landing', 'Taking off'].includes(states[m.hw_id])));
  const holdMonitor = heldScope
    ? commandMonitors.find((m) => m.commandId === holdReceipt.commandId) : null;
  const holdStatuses = Object.fromEntries(members.map((member) => [member.hw_id,
    holdNodeStatus({ ...member, available: member.available && !previewError }, holdMonitor?.executionDetails?.[member.hw_id])]));
  const holdConfirmed = Object.values(holdStatuses).filter((node) => node.label !== 'Hold unconfirmed').length;
  const status = previewError ? 'Telemetry delayed' : heldScope
    ? `Hold · ${holdConfirmed}/${members.length} confirmed` : runtimeLabel
      || (members.length ? `${airborne}/${members.length} airborne` : preview ? 'Select formation' : 'Loading…');
  useEffect(() => {
    if (holdReceipt && (newerMission || members.some((member) => ['Returning', 'Landing', 'Taking off'].includes(memberFlightState(member))))) {
      setHoldReceipt(null);
    }
  }, [holdReceipt, newerMission, members]);

  const review = (action) => {
    if (!cluster || busy) return;
    if (action === 'start' && pendingStart) { setConfirmation(pendingStart.reviewed); return; }
    if (!canCommand) return;
    const targets = [...commandScope.ids];
    const references = action === 'start' ? swarmReferenceIds(members, targets) : [];
    setError('');
    setConfirmation({ action, targets, references, excluded: [], revision: preview.revision,
      clusterId: cluster.cluster_id, key: `swarm-${Date.now()}-${Math.random().toString(16).slice(2)}` });
  };
  const freshReview = async (reviewed) => {
    const requestedAt = Date.now();
    const requestedScope = scope.current;
    const response = await fetchGcsResource(PREVIEW, reviewed.action === 'start'
      ? { params: swarmStartQuery(reviewed.clusterId, reviewed.targets) } : {});
    const current = response.data;
    if (requestedScope !== scope.current) throw new Error('Operation context changed.');
    const currentCluster = current.clusters.find((c) => c.cluster_id === reviewed.clusterId);
    if (current.revision !== reviewed.revision || !currentCluster
        || selection.id !== reviewed.clusterId) throw new Error('Formation changed. Review the targets again.');
    if (reviewed.targets) {
      const targets = currentCluster.members.map((member) => member.hw_id);
      if (!reviewed.targets.every(id => targets.includes(id))) throw new Error('Formation changed. Review the targets again.');
    }
    if (reviewed.action === 'start') {
      const evidence = swarmReviewEvidence(reviewed, current, requestedAt, swarmStartValidUntil);
      const check = swarmStartReadiness([...reviewed.targets, ...(reviewed.references || [])], evidence?.decisions, evidence?.until || 0);
      if (!check.ready) throw new Error(check.label);
    }
    setPreview({ ...current, receivedAtMs: Date.now() });
    return true;
  };
  const send = async () => {
    if (!confirmation || confirmation.action === 'takeoff') return;
    const submitLock = confirmation.action === 'start' ? startSubmitting : submitting;
    if (submitLock.current) return;
    const checkingPending = pendingStart && !pendingStart.needsReview;
    if (confirmation.action === 'start' && !checkingPending
        && !swarmStartReadiness([...confirmation.targets, ...(confirmation.references || [])], startCheck?.decisions, startCheck?.until || 0).ready) return;
    const reviewed = confirmation;
    const sendEpoch = intentEpoch.current;
    const sendScope = pendingKey;
    const operation = {};
    busyOwner.current = operation;
    submitLock.current = true;
    let posted = false;
    setBusy(true);
    try {
      if (reviewed.action === 'start' && checkingPending) {
        const { data } = await fetchGcsResource('/api/v1/commands/lookup', {
          params: { idempotency_key: reviewed.key },
        });
        if (scope.current !== sendScope) return;
        trackCommandReceipt(pendingStart.command, data, commandLifecycleCallbacks);
        rememberPending(null, sendScope);
        if (busyOwner.current === operation) setConfirmation(null);
        return;
      }
      await freshReview(reviewed);
      if (scope.current !== sendScope || intentEpoch.current !== sendEpoch) return;
      let command = { mission_type: TYPES[reviewed.action], trigger_time: 0,
        target_drone_ids: reviewed.targets, idempotency_key: reviewed.key,
        uiMeta: { operatorLabel: LABELS[reviewed.action], targetLabel: `Cluster ${reviewed.clusterId}` } };
      if (reviewed.action === 'start') command.smart_swarm_start = {
        cluster_id: reviewed.clusterId, revision: reviewed.revision,
        target_hw_ids: reviewed.targets, idempotency_key: reviewed.key,
      };
      if (reviewed.action === 'start') {
        command = pendingStart?.command || command;
        rememberPending({ reviewed, command }, sendScope);
      }
      posted = true;
      setHoldReceipt(null);
      await submitCommandWithLifecycleFeedback(command, commandLifecycleCallbacks);
      if (reviewed.action === 'start' && intentEpoch.current === sendEpoch) rememberPending(null, sendScope);
      if (scope.current !== sendScope) return;
      if (busyOwner.current === operation) setConfirmation(null);
    } catch (exc) {
      if (scope.current !== sendScope || intentEpoch.current !== sendEpoch) return;
      if (reviewed.action === 'start' && checkingPending) {
        if (exc?.response?.status === 404) {
          rememberPending({ ...pendingStart, needsReview: true }, sendScope);
          setError('Command not found. Review before confirming Start again.');
        } else setError('Command status unavailable. Check again.');
        return;
      }
      const detail = exc?.response?.data?.detail;
      const uncertain = reviewed.action === 'start' && isAmbiguousSubmissionTransportFailure(exc);
      if (reviewed.action === 'start' && !uncertain && (posted || !pendingStart)) rememberPending(null, sendScope);
      if (busyOwner.current !== operation) return;
      setError(uncertain ? 'Start status unconfirmed. Check the same command.'
        : typeof detail === 'string' ? detail : detail?.message || exc.message || 'Command not confirmed. Check aircraft status.');
    } finally {
      submitLock.current = false;
      if (busyOwner.current === operation) { busyOwner.current = null; setBusy(false); }
    }
  };
  const holdSwarm = async () => {
    if (!cluster || !ids.length || holdSubmitting.current) return;
    const sendScope = pendingKey;
    const targets = [...ids];
    const fingerprint = `${sendScope}:${cluster.cluster_id}:${targets.join(',')}`;
    if (pendingHold.current?.fingerprint !== fingerprint) pendingHold.current = {
      fingerprint,
      command: { mission_type: TYPES.hold, trigger_time: 0, target_drone_ids: targets,
        idempotency_key: `hold-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        uiMeta: { operatorLabel: 'Hold Swarm', targetLabel: `Cluster ${cluster.cluster_id}` } },
    };
    // A recovery has its own lane: a late readiness reply must not post Start
    // after Hold, and an unresolved routine POST must not trap this control.
    intentEpoch.current += 1;
    busyOwner.current = null;
    setBusy(false);
    setConfirmation(null);
    rememberPending(null, sendScope);
    holdSubmitting.current = true;
    setHoldBusy(true);
    setError('');
    const sentAtMs = Date.now();
    const knownCommandIds = commandMonitors.map((m) => m.commandId);
    setHoldReceipt({ clusterId: cluster.cluster_id, commandId: null, sentAtMs, knownCommandIds });
    try {
      const receipt = await submitCommandWithLifecycleFeedback(pendingHold.current.command, commandLifecycleCallbacks);
      if (scope.current === sendScope) {
        setHoldReceipt({ clusterId: cluster.cluster_id, commandId: receipt.command_id, sentAtMs, knownCommandIds });
        pendingHold.current = null;
      }
    } catch (exc) {
      if (scope.current !== sendScope) return;
      const detail = exc?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : detail?.message || 'Hold unconfirmed. Check aircraft status and retry.');
    } finally {
      holdSubmitting.current = false;
      setHoldBusy(false);
    }
  };
  const contextKey = `${selection.id}:${preview?.revision}`;
  const startReadiness = startCheck?.error ? { ready: false, label: startCheck.error }
    : swarmStartReadiness([...(confirmation?.targets || []), ...(confirmation?.references || [])], startCheck?.decisions, startCheck?.until || 0);

  return (
    <section className="swarm-ops operator-console" aria-label="Swarm operations">
      <header className="swarm-ops__header">
        <div><h3>Swarm</h3>{(clusters.length > 1 || !cluster) && <label>
          <select aria-label="Swarm formation" value={cluster?.cluster_id || ''} disabled={busy}
            onChange={(e) => chooseCluster(e.target.value)}>
            {!cluster && <option value="">Select formation</option>}
            {clusters.map((c) => <option key={c.cluster_id} value={c.cluster_id}>Cluster {c.cluster_id} · {c.members.length} drones</option>)}
          </select>
        </label>}</div>
        <StatusBadge tone={previewError || (runtimeLabel && runtimeAttention) ? 'warning' : 'neutral'}>{status}</StatusBadge>
        <button type="button" className="operator-button operator-button--ghost swarm-ops__overflow"
          aria-label="Other actions" title="Other actions" aria-expanded={advanced}
          onClick={() => setAdvanced(!advanced)}><FaEllipsisH aria-hidden="true" /></button>
      </header>
      <SwarmFormationSource
        planHref={`/swarm-design?tab=formation${cluster ? `&drone=${encodeURIComponent(cluster.cluster_id)}` : ''}`}
        captureHref={`/swarm-design?tab=formation&capture=1${cluster ? `&drone=${encodeURIComponent(cluster.cluster_id)}` : ''}`}
        disabled={busy} captureDisabled={!cluster || members.length < 2} />
      <div className="swarm-ops__targets">
        <CommandAircraftControl ids={commandScope.ids} aircraft={pickerAircraft} totalCount={ids.length}
          review={{ unresolvedIds: commandScope.missing, hiddenIds: [] }}
          disabled={!commandScope.initialized || Boolean(confirmation) || busy}
          onOpen={() => setChoosingRecipients(true)} />
      </div>
      <div className="swarm-ops__actions">
        <button type="button" className="operator-button operator-button--ghost"
          disabled={busy || !canCommand} onClick={() => review('takeoff')}><FaArrowUp aria-hidden="true" /> Takeoff</button>
        <button type="button" className="operator-button operator-button--ghost"
          disabled={busy || (!canCommand && !pendingStart)} onClick={() => review('start')}><FaPlay aria-hidden="true" /> {pendingStart ? (pendingStart.needsReview ? 'Review Start' : 'Check Start command') : 'Start Swarm'}</button>
        <button type="button" className="operator-button operator-button--ghost" disabled={holdBusy || !cluster}
          title="Hold the entire displayed cluster, regardless of To" onClick={holdSwarm}><FaPause aria-hidden="true" /> {holdBusy ? 'Sending Hold…' : 'Hold all'}</button>
        <SequentialReturnControl targetIds={commandScope.ids} targetNames={commandScope.ids.map(id => memberLabel(members.find(m => m.hw_id === id) || { hw_id: id }))}
          compact contextKey={contextKey} buttonLabel="Managed Return" disabled={!canCommand}
          aircraftStates={states} validateReview={async () => {
            const epoch = intentEpoch.current;
            await freshReview({ clusterId: selection.id, revision: preview.revision, targets: commandScope.ids });
            if (epoch !== intentEpoch.current) throw new Error('Newer recovery requested. Review Return again.');
            setHoldReceipt(null);
          }} />
      </div>
      <SwarmClusterDiagram members={members} selectedId={inspectedId} onSelect={setInspectedId}
        statuses={Object.fromEntries(members.map((m) => {
          const node = heldScope ? holdStatuses[m.hw_id] : nodeStatuses[m.hw_id];
          return [m.hw_id, { ...node,
            label: `${heldScope ? '' : `${states[m.hw_id]} · `}${node.label}${m.available && Number.isFinite(m.battery_remaining) ? ` · ${Math.round(m.battery_remaining)}%` : ''}` }];
        }))} />
      {inspected && <div className="swarm-ops__inspection" aria-label="Aircraft details">
        <strong>{memberLabel(inspected)}</strong><span>{movementSummary(inspected)}</span>
        {inspected.available && inspected.readiness_summary && <span>{inspected.readiness_summary}</span>}
        <button type="button" className="operator-button operator-button--ghost" onClick={() => setInspectedId(null)}>Close details</button>
      </div>}
      {members.some((m) => m.available && m.readiness_status === 'blocked') && <p className="swarm-ops__attention" role="status">
        {members.filter((m) => m.available && m.readiness_status === 'blocked').slice(0, 2).map((m) => `${memberLabel(m)}: ${m.readiness_summary || 'Not ready'}`).join(' · ')}
        {members.filter((m) => m.available && m.readiness_status === 'blocked').length > 2 && ' · More in aircraft details'}
      </p>}
      {advanced && <div className="swarm-ops__advanced">
        <a href="/globe-view">Globe</a>
        {['hold', 'land', 'rtl'].map((action) => <button className="operator-button operator-button--ghost" type="button" key={action} disabled={busy || !canCommand} onClick={() => review(action)}>{LABELS[action]}</button>)}
      </div>}
      {!cluster && preview && <p role="status">{clusters.length ? 'Select a saved formation.' : <a href="/swarm-design?tab=formation">Create a formation</a>}</p>}
      {error && <p role="alert">{error}</p>}
      {choosingRecipients && <CommandAircraftPicker selectedIds={commandScope.ids} configuredIds={ids} aircraft={pickerAircraft}
        preset={{ label: 'Cluster', ariaLabel: 'Use entire cluster', ids, Icon: FaLayerGroup, title: 'Use the entire displayed formation' }}
        showAllConfigured={false} help="To applies to Takeoff, Start and Managed Return. Hold all stops the whole formation. Saved roles stay unchanged."
        onClose={() => setChoosingRecipients(false)} onApply={next => { commandScope.choose(next); setChoosingRecipients(false); }} />}
      <TakeoffDialog open={confirmation?.action === 'takeoff'}
        command={confirmation ? { mission_type: 10, trigger_time: 0, target_drone_ids: confirmation.targets,
          idempotency_key: confirmation.key, takeoff_altitude: height,
          uiMeta: { operatorLabel: 'Takeoff', targetLabel: `Cluster ${confirmation.clusterId}` } } : null}
        aircraft={members} beforeSubmit={payload => freshReview({ ...confirmation, targets: payload.target_drone_ids })}
        onAccepted={payload => commandScope.choose(payload.target_drone_ids)} onClose={() => setConfirmation(null)} />
      <ConfirmDialog appearance="console" open={Boolean(confirmation) && confirmation.action !== 'takeoff'} title={confirmation ? LABELS[confirmation.action] : 'Confirm'}
        confirmDisabled={confirmation?.action === 'start' && (!pendingStart || pendingStart.needsReview) && !startReadiness.ready}
        confirmLabel={confirmation?.action === 'start' && pendingStart && !pendingStart.needsReview ? 'Check command' : confirmation ? `Confirm ${LABELS[confirmation.action]}` : 'Confirm'} busy={busy}
        allowDismissWhileBusy
        cancelLabel={busy ? 'Close' : 'Cancel'}
        onCancel={() => {
          busyOwner.current = null;
          setBusy(false);
          setConfirmation(null);
        }} onConfirm={send}
        message={confirmation ? <div className="swarm-ops__confirmation">
          <strong title={`${confirmation.targets.length} aircraft`}>{swarmNamesSummary(confirmation.targets.map((id) => memberLabel(members.find((m) => m.hw_id === id) || { hw_id: id })))}</strong>
          <small title={`Not commanded: ${swarmNamesSummary(members.filter(m => !confirmation.targets.includes(m.hw_id)).map(memberLabel)) || 'None'}`}>
            {confirmation.targets.length}/{members.length} aircraft</small>
          {confirmation.action === 'start' && <><StatusBadge tone={startReadiness.ready && (!pendingStart || pendingStart.needsReview) ? 'success' : 'warning'}>
            {pendingStart && !pendingStart.needsReview ? 'Checking command' : startReadiness.label}</StatusBadge>
            {(confirmation.references || []).length > 0 && <small className="swarm-ops__references" title="Read-only leader references. No command is sent to these aircraft."><FaLink aria-hidden="true" /> Leader reference: {swarmNamesSummary(confirmation.references.map(id => members.find(m => m.hw_id === id)?.callsign || `H${id}`))}</small>}
            <details><summary>Spacing</summary><ul>{members.filter((m) => confirmation.targets.includes(m.hw_id)).map((m) => <li key={m.hw_id}>Drone {m.hw_id}: {movementSummary(m)} · {formationReferenceLabel(m.frame)}</li>)}</ul></details></>}
          {confirmation.action === 'hold' && <p>Stop following and command Hold.</p>}
          {confirmation.action === 'land' && <p>Land at current positions.</p>}
          {confirmation.action === 'rtl' && <p>Immediate PX4 RTL · paths may overlap. Return heights: unavailable here; each aircraft uses its configured settings.</p>}
          {busy && <small>Closing does not cancel the command.</small>}
          {error && <p role="alert">{error}</p>}
        </div> : ''} />
    </section>
  );
}

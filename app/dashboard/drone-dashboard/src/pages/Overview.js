import React, { lazy, Suspense, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { FaBorderAll, FaList, FaMapMarkedAlt, FaPlaneDeparture, FaHandPaper, FaPlaneArrival, FaHome, FaEllipsisH, FaExclamationTriangle, FaLayerGroup } from 'react-icons/fa';
import { getBackendURL } from '../config/apiConfig';
import { DRONE_ACTION_TYPES, getCommandName } from '../constants/droneConstants';
import { getFleetReferenceClock } from '../utilities/commandScheduling';
import { matchesDroneSearchQuery } from '../utilities/dronePresentation';
import { buildSwarmViewModel } from '../utilities/swarmDesignUtils';
import TakeoffDialog from '../components/TakeoffDialog';
import MoreActionsPanel from '../features/fleet-overview/MoreActionsPanel';
import FleetMoveControl from '../features/fleet-overview/FleetMoveControl';
import { AircraftInspector, AircraftTile } from '../features/fleet-overview/FleetAircraft';
import ActionReview, { buildActionStorageKey, readPendingAction, readPendingActions } from '../features/fleet-overview/ActionReview';
import useFleetResources from '../features/fleet-overview/useFleetResources';
import { buildFleetViewModel } from '../features/fleet-overview/fleetViewModel';
import { filterFleetAircraft, groupFleetAircraft } from '../features/fleet-overview/fleetDisplay';
import { useFleetAlerts } from '../features/fleet-overview/FleetAlertsContext';
import { createTargetSelectionState, getTargetSelectionReview, getTargetSelectionStorageScope, parseTargetSelection, serializeTargetSelection, targetSelectionReducer } from '../features/fleet-overview/targetSelection';
import '../styles/Overview.css';

const FleetMap = lazy(() => import('../features/fleet-overview/FleetMap'));
const PRIMARY = [['TAKE_OFF', 'Takeoff', FaPlaneDeparture], ['HOLD', 'Hold', FaHandPaper], ['LAND', 'Land', FaPlaneArrival], ['RETURN_RTL', 'Return', FaHome]];

function readPreference(key, fallback) {
  try { const value = localStorage.getItem(key); return ['board', 'list', 'map'].includes(value) ? value : fallback; }
  catch (_) { return fallback; }
}

export default function Overview({ runtimeMode = 'unknown', operatorId = '' }) {
  const mode = String(runtimeMode || 'unknown').toLowerCase();
  return <FleetOverview key={`${mode}:${operatorId}`} runtimeMode={mode} operatorId={operatorId} />;
}

function FleetOverview({ runtimeMode, operatorId }) {
  const resources = useFleetResources(runtimeMode);
  const orderRef = useRef([]);
  const model = useMemo(() => buildFleetViewModel(resources.drones, { nowMs: resources.nowMs, previousOrder: orderRef.current,
    displayPolicy: resources.displayPolicy }), [resources.drones, resources.nowMs, resources.displayPolicy]);
  const { publishSnapshot, sourceUnavailable } = useFleetAlerts();
  useEffect(() => {
    publishSnapshot({ aircraft: model.aircraft, sourceError: Boolean(resources.telemetry.error || resources.config.error), observedAtMs: resources.nowMs });
  }, [model.aircraft, resources.telemetry.error, resources.config.error, resources.nowMs, publishSnapshot]);
  useEffect(() => () => sourceUnavailable(), [sourceUnavailable]);
  useEffect(() => { orderRef.current = model.order; }, [model.order]);
  const [selection, dispatch] = useReducer(targetSelectionReducer, undefined, createTargetSelectionState);
  const [storageWarning, setStorageWarning] = useState('');
  const storageScope = useMemo(() => getTargetSelectionStorageScope({ deploymentId: getBackendURL(), runtimeMode, operatorId, sessionId: 'browser-session' }), [runtimeMode, operatorId]);
  const pendingKey = `mds:fleet-action:v1:${getBackendURL()}:${runtimeMode}:${operatorId || 'session'}`;
  const [pending, setPending] = useState(() => readPendingActions(pendingKey));
  const [intent, setIntent] = useState(null);
  const [takeoff, setTakeoff] = useState(null);
  const [moveTargets, setMoveTargets] = useState(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('available');
  const [view, setView] = useState(() => readPreference('mds:fleet-view:v1', 'board'));
  const [more, setMore] = useState(null);
  const [grouped, setGrouped] = useState(false);
  useEffect(() => {
    // Browser receipt reconciliation only: this never sends or retries a command.
    setPending((previous) => {
      const next = readPendingActions(pendingKey);
      return JSON.stringify(previous) === JSON.stringify(next) ? previous : next;
    });
  }, [pendingKey, resources.nowMs]);
  const [params, setParams] = useSearchParams();
  const inspected = model.byId.get(params.get('aircraft')) || null;
  const inspect = (id) => setParams((previous) => { const next = new URLSearchParams(previous); if (id) next.set('aircraft', id); else next.delete('aircraft'); return next; }, { replace: true });
  const groups = useMemo(() => buildSwarmViewModel(resources.swarm, resources.drones)?.clusters || [], [resources.swarm, resources.drones]);
  const hasMultipleGroups = groups.filter((group) => group.drones.length > 1).length > 1;
  useEffect(() => {
    if (!storageScope || !resources.config.response || !resources.telemetry.response || selection.initialized) return;
    let saved;
    try { saved = parseTargetSelection(window[`${storageScope.storage}Storage`].getItem(storageScope.key)); }
    catch (_) { saved = null; setStorageWarning('Selection could not be restored. Review aircraft before sending.'); }
    if (saved?.valid === false) setStorageWarning('Saved selection unreadable. Select aircraft again.');
    dispatch({ type: 'initialize', configuredIds: resources.configuredIds,
      defaultIds: model.aircraft.filter((item) => item.availability.available).map((item) => item.id), savedIds: saved?.ids });
  }, [storageScope, resources.config.response, resources.telemetry.response, resources.configuredIds, model.aircraft, selection.initialized]);
  useEffect(() => {
    if (!storageScope || !selection.initialized) return;
    try { window[`${storageScope.storage}Storage`].setItem(storageScope.key, serializeTargetSelection(selection)); }
    catch (_) { setStorageWarning('Selection will not be remembered in this browser.'); }
  }, [selection, storageScope]);

  const selectedIds = new Set(selection.ids);
  const visible = filterFleetAircraft(model.aircraft, { query, filter, selectedIds, matches: matchesDroneSearchQuery });
  const displayGroups = groupFleetAircraft(visible, groups, grouped && hasMultipleGroups);
  const review = getTargetSelectionReview(selection, resources.configuredIds, visible.map((item) => item.id));
  const runtimeKnown = ['real', 'sitl'].includes(runtimeMode);
  const canAct = runtimeKnown && selection.initialized && review.count > 0 && !review.unresolvedIds.length;
  const clock = getFleetReferenceClock(resources.drones, resources.nowMs);
  const chooseView = (next) => { setView(next); try { localStorage.setItem('mds:fleet-view:v1', next); } catch (_) {} };
  const closeReview = () => { setIntent(null); setPending(readPendingActions(pendingKey)); };
  const request = (body, ids = selection.ids) => {
    if (!runtimeKnown || !ids.length || ids.some((id) => !resources.configuredIds.includes(id))) return;
    const command = { ...body, target_drone_ids: [...ids], uiMeta: { ...body.uiMeta,
      targetLabel: `${ids.length} aircraft`, targetDescriptor: ids.map((id) => `${model.byId.get(id)?.label || 'Aircraft'} · H${id}`).join(', ') } };
    delete command.target_scope;
    setMore(null);
    if (body.mission_type === DRONE_ACTION_TYPES.TAKE_OFF) setTakeoff({ ...command, takeoff_altitude: body.takeoff_altitude ?? 10 });
    else {
      const key = buildActionStorageKey(pendingKey, command);
      if (!key) return;
      const saved = readPendingAction(key);
      const legacy = pending.find((entry) => buildActionStorageKey(pendingKey, entry.command) === key);
      setIntent({ storageKey: saved ? key : legacy?.storageKey || key,
        command: saved || legacy ? { ...(saved || legacy.command), recover: true } : command });
    }
  };
  const action = (key, item = null) => {
    if (item) inspect(null);
    request({ mission_type: DRONE_ACTION_TYPES[key], trigger_time: 0, uiMeta: { operatorLabel: PRIMARY.find(([candidate]) => candidate === key)?.[1] || key } }, item ? [item.id] : selection.ids);
  };
  const openMove = (item) => { inspect(null); setMore(null); setMoveTargets([item.id]); };
  const openMore = (item = null) => {
    const ids = item ? [item.id] : [...selection.ids];
    inspect(null);
    setMore({ ids, label: ids.slice(0, 2).map((id) => `${model.byId.get(id)?.label || 'Aircraft'} · H${id}`).join(', ')
      + (ids.length > 2 ? ` · +${ids.length - 2}` : '') });
  };
  const moveItem = more?.ids.length === 1 ? model.byId.get(more.ids[0]) : null;
  const canPrecisionMove = Boolean(moveItem?.current && moveItem.flightState === 'Airborne');
  const removeUnavailable = ({ command, remainingIds }) => {
    if (!remainingIds.length) return;
    const { idempotency_key, recover, ...unsent } = command;
    request(unsent, remainingIds);
  };
  const renderTile = (item) => <AircraftTile key={item.id} item={item} list={view === 'list'} selected={selectedIds.has(item.id)} inspected={inspected?.id === item.id}
    onInspect={inspect} onToggle={(id) => dispatch({ type: 'toggle', id })} />;

  return <main className="fleet-overview" aria-label="Fleet overview">
    <header className="fleet-overview__header"><div><span className="fleet-eyebrow">OPERATIONS</span><h1>Overview</h1></div>
      <div className="fleet-status-strip" aria-label="Fleet status"><strong className={`fleet-runtime is-${runtimeMode}`}>{runtimeMode.toUpperCase()}</strong>
        <span>{model.summary.available} available <small>/ {model.summary.total}</small></span><span>{model.summary.airborne} airborne</span>
        <button type="button" className={model.summary.attention ? 'tone-warning' : ''} onClick={() => setFilter(filter === 'attention' ? 'all' : 'attention')} aria-pressed={filter === 'attention'}>
          {model.summary.attention > 0 && <FaExclamationTriangle aria-hidden="true" />} {model.summary.attention} need attention</button></div>
    </header>
    {resources.telemetry.error && <div role="alert" className="fleet-inline-warning">GCS telemetry unavailable · displayed measurements are aging. Reconnecting.</div>}
    {resources.config.error && <div role="alert" className="fleet-inline-warning">Aircraft configuration could not refresh. Review targets before sending.</div>}
    {storageWarning && <div role="status" className="fleet-inline-warning">{storageWarning}</div>}
    {pending.length > 0 && <div role="alert" className="fleet-inline-warning"><details><summary>{pending.length} unconfirmed action{pending.length === 1 ? '' : 's'}</summary>
      {pending.map((entry) => <button type="button" key={entry.storageKey} onClick={() => setIntent({ storageKey: entry.storageKey, command: { ...entry.command, recover: true } })}>
        Check {getCommandName(entry.command.mission_type)} · {entry.command.target_drone_ids.length} aircraft</button>)}
    </details></div>}
    <section className="fleet-toolbar" aria-label="Aircraft display">
      <label className="fleet-search"><span className="fleet-visually-hidden">Find aircraft</span><input type="search" placeholder="Find aircraft" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <label><span className="fleet-visually-hidden">Filter aircraft</span><select aria-label="Filter aircraft" value={filter} onChange={(event) => setFilter(event.target.value)}>
        <option value="available">Available</option><option value="all">All aircraft</option><option value="selected">Selected targets</option><option value="attention">Needs attention</option><option value="unavailable">Unavailable</option><option value="airborne">Airborne</option><option value="unmapped">No current position</option></select></label>
      {hasMultipleGroups && view !== 'map' && <button type="button" className="fleet-group-toggle" aria-pressed={grouped} onClick={() => setGrouped(!grouped)}><FaLayerGroup aria-hidden="true" /><span>Clusters</span></button>}
      <div className="fleet-view-switch" role="group" aria-label="Aircraft view">{[['board', 'Board', FaBorderAll], ['list', 'List', FaList], ['map', 'Map', FaMapMarkedAlt]].map(([key, label, Icon]) =>
        <button type="button" key={key} aria-pressed={view === key} onClick={() => chooseView(key)}><Icon aria-hidden="true" /><span>{label}</span></button>)}</div>
    </section>
    <section className="fleet-selection-tools" aria-label="Target selection"><span>Targets</span>
      <button type="button" disabled={!selection.initialized} onClick={() => dispatch({ type: 'group', ids: model.aircraft.filter((item) => item.availability.available).map((item) => item.id).filter((id) => resources.configuredIds.includes(id)) })}>Available</button>
      <button type="button" disabled={!selection.initialized} onClick={() => dispatch({ type: 'all', ids: resources.configuredIds })}>All</button>
      <button type="button" disabled={!selection.initialized} onClick={() => dispatch({ type: 'none' })}>None</button>
      {groups.length > 1 && <select aria-label="Select target group" value="" onChange={(event) => {
        const group = groups.find((item) => String(item.id) === event.target.value);
        if (group) dispatch({ type: 'group', ids: group.drones.map((item) => String(item.hw_id)) });
      }}><option value="">Select group…</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.label || `Cluster ${group.leaderId || group.id}`}</option>)}</select>}
      <button type="button" className="fleet-selection-tools__count" onClick={() => { setFilter('selected'); setQuery(''); }} title="Show selected command targets">{review.count} selected{review.hiddenIds.length > 0 ? ` · ${review.hiddenIds.length} hidden` : ''}</button>
    </section>
    {!!review.unresolvedIds.length && <div className="fleet-inline-warning" role="alert">Unknown selected aircraft: {review.unresolvedIds.join(', ')}.
      <button type="button" onClick={() => dispatch({ type: 'group', ids: selection.ids.filter((id) => resources.configuredIds.includes(id)) })}>Remove missing targets</button></div>}
    <div className="fleet-surface">
      {resources.loading ? <p role="status">Loading aircraft…</p> : view === 'map' ? <Suspense fallback={<p role="status">Loading map…</p>}>
        <FleetMap aircraft={visible} selectedIds={selectedIds} onInspect={inspect} onShowUnmapped={() => { chooseView('list'); setFilter('unmapped'); }} />
      </Suspense> : <section aria-label="Aircraft">{displayGroups.map((group) => <React.Fragment key={group.id}>
        {group.label && <h2 className="fleet-cluster-heading">{group.label}<small>{group.aircraft.length}</small></h2>}
        <div className={`fleet-board ${view === 'list' ? 'fleet-board--list' : ''}`}>{group.aircraft.map(renderTile)}</div>
      </React.Fragment>)}</section>}
      {!resources.loading && !visible.length && <div className="fleet-empty"><h2>{model.summary.total ? 'No matching aircraft' : 'No configured aircraft'}</h2>
        {model.summary.total ? <button type="button" onClick={() => { setFilter('all'); setQuery(''); }}>Clear filters</button> : <Link to="/fleet-enrollment">Set up aircraft →</Link>}</div>}
    </div>
    {more && <MoreActionsPanel targetCount={more.ids.length} targetLabel={more.label} runtimeMode={runtimeMode} referenceNowMs={clock.referenceNowMs}
      onClose={() => setMore(null)} onSendCommand={(body) => request(body, more.ids)} canPrecisionMove={canPrecisionMove}
      onRequestPrecisionMove={() => { if (canPrecisionMove) openMove(moveItem); }} />}
    <footer className="fleet-action-rail" aria-label="Selected aircraft actions"><strong>{review.count}<span> selected</span></strong>
      <div className="fleet-action-rail__buttons">{PRIMARY.map(([key, label, Icon]) => <button key={key} type="button" disabled={!canAct} onClick={() => action(key)}
        title={key === 'RETURN_RTL' ? 'Immediate PX4 RTL · no sequencing' : undefined}><Icon aria-hidden="true" /><span>{label}</span></button>)}
        <button type="button" aria-expanded={Boolean(more)} disabled={!canAct} onClick={() => openMore()}><FaEllipsisH aria-hidden="true" /><span>More</span></button></div>
    </footer>
    {inspected && !more && !intent && !takeoff && !moveTargets && <AircraftInspector item={inspected} onClose={() => inspect(null)} onAction={action} onMove={openMove} onMore={openMore} />}
    {intent && <ActionReview key={`${intent.storageKey}:${intent.command.idempotency_key || 'review'}`} intent={intent.command} storageKey={intent.storageKey} runtimeMode={runtimeMode} aircraft={model.aircraft}
      onClose={closeReview} onResolved={() => setPending(readPendingActions(pendingKey))} onRemoveUnavailable={removeUnavailable} />}
    <TakeoffDialog open={Boolean(takeoff)} command={takeoff} aircraft={resources.drones} onClose={() => setTakeoff(null)} />
    {moveTargets && <FleetMoveControl key={`${runtimeMode}:${operatorId}:${moveTargets[0]}`} targetId={moveTargets[0]}
      targetLabel={model.byId.get(moveTargets[0])?.label} runtimeMode={runtimeMode} operatorId={operatorId} onClose={() => setMoveTargets(null)} />}
  </main>;
}

import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { FaChevronRight, FaExclamationTriangle, FaSearch, FaTools } from 'react-icons/fa';
import InfoHint from '../components/InfoHint';
import { AircraftSilhouette } from '../components/SwarmAircraftSymbol';
import { EmptyState, PageShell } from '../components/ui';
import AircraftDetail from '../features/fleet-ops/AircraftDetail';
import FleetSyncProgress from '../features/fleet-ops/FleetSyncProgress';
import useFleetSync, { activeOperation } from '../features/fleet-ops/useFleetSync';
import useFetch from '../hooks/useFetch';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';
import { buildFleetOpsViewModel } from '../utilities/fleetOpsViewModel';
import '../styles/FleetOpsPage.css';

const filters = { all: 'All aircraft', online: 'Online', offline: 'Offline', drift: 'Review software', attention: 'Attention' };
const pageSize = 48;

function AircraftRow({ row, selecting, selected, eligible, locked, inspect, toggle, expanded }) {
  const descriptionId = useId();
  const syncKnown = row.sync.state !== 'unknown';
  const matched = row.sync.state === 'synced';
  const software = !syncKnown ? 'Unknown' : row.online ? row.sync.label : matched ? 'Last synced' : 'Last differed';
  const extraAttention = row.online && row.needsAttention && matched;
  const softwareTone = row.online ? row.sync.tone : 'muted';
  return <li className={'fleet-console-aircraft' + (expanded ? ' is-inspected' : '') + (selected ? ' is-selected' : '')}>
    {selecting && <label className="fleet-aircraft-check">
      <input type="checkbox" aria-label={'Select aircraft ' + row.posId} checked={selected} disabled={locked || (!selected && !eligible)}
        onChange={() => toggle(row.hwId)} />
    </label>}
    <button type="button" className="fleet-aircraft-open" aria-label={'Inspect aircraft ' + row.posId}
      aria-describedby={descriptionId} aria-expanded={expanded} onClick={inspect}>
      <span className="fleet-aircraft-name">
        <svg className="fleet-aircraft-mark" viewBox="-22 -22 44 44" aria-hidden="true" focusable="false"><AircraftSilhouette /></svg>
        <span className="fleet-aircraft-identity"><strong>Aircraft {row.posId}</strong><small>H{row.hwId}</small></span>
      </span>
      <span className={`fleet-aircraft-connection fleet-tone--${row.presence.tone}`}>
        <span className="fleet-connection-dot" aria-hidden="true" />{row.presence.label}
      </span>
      <span className={`fleet-aircraft-software fleet-tone--${softwareTone}`}>
        {software}{extraAttention && <FaExclamationTriangle className="fleet-caution" aria-label="Needs attention" />}
      </span>
      <FaChevronRight className="fleet-open-chevron" aria-hidden="true" />
    </button>
    <span id={descriptionId} hidden>H{row.hwId}. Connection: {row.presence.label}. Software: {software}.{extraAttention && ' Needs attention.'}</span>
  </li>;
}

export default function FleetOpsPage(props) {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  const legacyTab = params.get('tab');
  if (['access', 'sidecars'].includes(legacyTab)) {
    const next = new URLSearchParams({ section: legacyTab });
    if (params.get('hw_id')) next.set('hw_id', params.get('hw_id'));
    return <Navigate replace to={'/maintenance?' + next.toString()} />;
  }
  return <FleetConsole key={JSON.stringify([props.operatorId, props.runtimeMode])} {...props} search={search} />;
}

function FleetConsole({ search, operatorId = '', runtimeMode = '', gitStatusOverride, heartbeatOverride, nodeBootStatusOverride }) {
  const git = useFetch(gitStatusOverride ? null : GCS_ROUTE_KEYS.gitStatus);
  const heartbeats = useFetch(heartbeatOverride ? null : GCS_ROUTE_KEYS.fleetHeartbeats);
  const boot = useFetch(nodeBootStatusOverride ? null : GCS_ROUTE_KEYS.fleetNodeBootStatus);
  const fleet = useMemo(() => buildFleetOpsViewModel(gitStatusOverride || git.data, heartbeatOverride || heartbeats.data,
    nodeBootStatusOverride || boot.data), [gitStatusOverride, git.data, heartbeatOverride, heartbeats.data, nodeBootStatusOverride, boot.data]);
  const params = useMemo(() => new URLSearchParams(search), [search]);
  const requestedFilter = params.get('filter');
  const [filter, setFilter] = useState(filters[requestedFilter] ? requestedFilter : 'all');
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(pageSize);
  const [selected, setSelected] = useState(null);
  const [inspected, setInspected] = useState(null);
  const sync = useFleetSync(operatorId, runtimeMode);
  const { rows, gcsStatus } = fleet;
  const eligible = useMemo(() => rows.filter(row => row.online && row.sync.state !== 'unknown').map(row => row.hwId), [rows]);
  const eligibleSet = useMemo(() => new Set(eligible), [eligible]);
  const targets = selected === null ? eligible : selected;
  const active = activeOperation(sync.operation);
  const syncLocked = Boolean(sync.busy || sync.checking || active || sync.operation?.phase === 'review');
  const waiting = (!gitStatusOverride && git.loading && !git.data) || (!heartbeatOverride && heartbeats.loading && !heartbeats.data);
  const hasFeedError = Boolean(git.error || heartbeats.error);
  const autoRoute = useRef(null);
  useEffect(() => {
    setFilter(filters[requestedFilter] ? requestedFilter : 'all');
    setLimit(pageSize);
  }, [requestedFilter]);
  useEffect(() => {
    const hwId = params.get('hw_id');
    if (hwId !== null) {
      setSelected(hwId ? [hwId] : []);
      setInspected(hwId);
    }
  }, [params]);
  // Older bookmarks can request one read-only preview of the explicitly named scope.
  useEffect(() => {
    if (params.has('hw_id') || params.get('scope') !== 'needs-sync' || autoRoute.current === search || waiting || hasFeedError) return;
    const driftIds = rows.filter(row => eligibleSet.has(row.hwId) && row.sync.state === 'drifted').map(row => row.hwId);
    setSelected(driftIds);
    autoRoute.current = search;
    if (params.get('autoplan') === '1' && driftIds.length && !sync.id && !sync.busy) sync.prepare(driftIds);
  }, [params, rows, eligibleSet, waiting, hasFeedError, search, sync]);
  const refreshGit = git.refresh;
  const previousPhase = useRef(null);
  useEffect(() => {
    const phase = sync.operation?.phase;
    if (phase && !active && phase !== 'review' && previousPhase.current !== phase) refreshGit?.();
    previousPhase.current = phase;
  }, [sync.operation?.phase, active, refreshGit]);

  const matching = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter(row => {
      if (filter === 'online' && !row.online) return false;
      if (filter === 'offline' && row.online) return false;
      if (filter === 'attention' && !(row.online && row.needsAttention)) return false;
      if (filter === 'drift' && !(row.hasDrift && (row.gitStatus?.reviewable ?? row.online))) return false;
      return !needle || [`Aircraft ${row.posId}`, `P${row.posId}`, `H${row.hwId}`, row.ip, row.branch, row.commit]
        .some(value => String(value || '').toLowerCase().includes(needle));
    });
  }, [rows, query, filter]);
  const inspectedRow = rows.find(row => row.hwId === inspected);
  const toggle = hwId => setSelected(current => current.includes(hwId) ? current.filter(id => id !== hwId) : [...current, hwId]);
  const live = rows.filter(row => row.online);
  const seen = Boolean((heartbeatOverride || heartbeats.data)?.heartbeats);
  const revisionsSeen = Boolean((gitStatusOverride || git.data)?.git_status);
  const confirmed = live.filter(row => row.sync.state === 'synced');
  const unavailableCount = selected === null ? live.length - eligible.length : selected.filter(id => !eligibleSet.has(id)).length;
  const cautions = live.filter(row => row.needsAttention);
  const setView = value => { setFilter(value); setLimit(pageSize); };

  return <PageShell className="fleet-console" title="Fleet Ops" docsRoute="/fleet-ops"
    docsOptions={{ repoUrl: gcsStatus?.remote_url || '', branch: gcsStatus?.branch || '' }}
    actions={<Link className="fleet-console-link" to="/maintenance"><FaTools aria-hidden="true" /> Maintenance</Link>}>
    {hasFeedError && <p role="status" className="fleet-feed-error">Refresh unavailable. Showing last observations.</p>}
    <section className="fleet-instruments" aria-label="Fleet status">
      <div><span>Online</span><strong>{seen ? live.length : '—'}<small> / {seen || revisionsSeen ? rows.length : '—'}</small></strong></div>
      <div><span>Synced online</span><strong>{seen && revisionsSeen ? confirmed.length : '—'}<small> / {seen ? live.length : '—'}</small></strong></div>
      <div className={cautions.length ? 'has-caution' : ''}><span>Need attention</span><strong>{seen && revisionsSeen ? cautions.length : '—'}</strong></div>
    </section>
    <section className="fleet-control-strip" aria-label="Software update">
      <div className="fleet-operation-label">
        <div className="fleet-heading-with-hint">
          <h2>Software sync</h2>
          <InfoHint hoverable placement="bottom" label="About software sync"
            content="Sync online previews every online aircraft with a known revision. Sync selected uses the checked hardware IDs. Search and filters preserve the update scope." />
        </div>
        <p className="fleet-operation-scope">{targets.length} {selected === null ? 'eligible online' : 'selected'}
          {unavailableCount > 0 && <span className="fleet-caution"> · {unavailableCount} {selected === null ? 'unconfirmed' : 'unavailable'}</span>}</p>
      </div>
      <div className="fleet-operation-buttons">
        <button className="operator-button operator-button--ghost" type="button" disabled={syncLocked}
          aria-pressed={selected !== null} onClick={() => setSelected(selected === null ? [] : null)}>
          {selected === null ? 'Select aircraft' : 'Use all online'}
        </button>
        <button type="button" className="operator-button operator-button--primary" disabled={syncLocked || !targets.some(id => eligibleSet.has(id)) || waiting}
          onClick={() => sync.prepare(targets)}>{selected === null ? 'Sync online' : 'Sync selected'}</button>
      </div>
    </section>
    <FleetSyncProgress sync={sync} />
    <section className="fleet-roster" aria-label="Aircraft roster">
      <header><h2>Aircraft</h2>
        <div className="fleet-roster-tools"><label><FaSearch aria-hidden="true" /><input type="search" aria-label="Find aircraft" placeholder="Find aircraft" value={query}
          onChange={e => { setQuery(e.target.value); setLimit(pageSize); }} /></label>
          <select aria-label="Filter aircraft" value={filter} onChange={e => setView(e.target.value)}>
            {Object.entries(filters).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
      </header>
      <div className={'fleet-workspace' + (inspectedRow ? ' with-detail' : '')}>
        <div className={'fleet-roster-list' + (selected !== null ? ' is-selecting' : '')}>
          {matching.length ? <>
            <div className="fleet-roster-columns" aria-hidden="true">
              <span>Identity</span><span>Connection</span><span>Software</span>
            </div>
            <ul aria-label="Aircraft">
              {matching.slice(0, limit).map(row => <AircraftRow key={row.key} row={row} selecting={selected !== null}
                selected={selected?.includes(row.hwId) ?? false} eligible={eligibleSet.has(row.hwId)} locked={syncLocked}
                toggle={toggle} expanded={inspected === row.hwId}
                inspect={() => setInspected(previous => previous === row.hwId ? null : row.hwId)} />)}
            </ul>
            {matching.length > limit && <button className="operator-button operator-button--ghost fleet-more" type="button" onClick={() => setLimit(n => n + pageSize)}>
              Show more · {matching.length - limit}</button>}
          </> : <EmptyState title={waiting ? 'Loading aircraft' : rows.length ? 'No matching aircraft' : 'No aircraft reported'} />}
        </div>
        {inspectedRow && <AircraftDetail key={inspectedRow.hwId} row={inspectedRow} onClose={() => setInspected(null)} />}
      </div>
    </section>
  </PageShell>;
}

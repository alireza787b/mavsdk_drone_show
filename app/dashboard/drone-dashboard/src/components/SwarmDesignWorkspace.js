import React, { lazy, Suspense, useMemo, useState } from 'react';
import SwarmFormationCanvas from './SwarmFormationCanvas';
import DroneGraph from './DroneGraph';
import { buildSwarmViewModel } from '../utilities/swarmDesignUtils';
import { resolveFormationPositions } from '../utilities/swarmFormationGeometry';
import '../styles/SwarmDesignWorkspace.css';

const Formation3D = lazy(() => import('./SwarmFormation3D'));
const EMPTY_HEADINGS = {};

function ClusterThumbnail({ members, headings }) {
  let points;
  try { points = resolveFormationPositions(members, headings); } catch { return <span>Review follow chain</span>; }
  const values = Object.values(points);
  const minE = Math.min(...values.map((p) => p.east));
  const maxE = Math.max(...values.map((p) => p.east));
  const minN = Math.min(...values.map((p) => p.north));
  const maxN = Math.max(...values.map((p) => p.north));
  const scale = Math.min(140 / Math.max(6, maxE - minE), 90 / Math.max(6, maxN - minN));
  const project = (p) => [100 + (p.east - (minE + maxE) / 2) * scale, 65 - (p.north - (minN + maxN) / 2) * scale];
  return <svg viewBox="0 0 200 130" aria-label="Relative cluster preview" role="img">{members.map((m) => {
    const [x, y] = project(points[String(m.hw_id)]);
    const parent = points[String(m.follow)];
    const [px, py] = parent ? project(parent) : [x, y];
    return <g key={m.hw_id}><line x1={x} y1={y} x2={px} y2={py} stroke="currentColor" strokeOpacity=".4" />
      <circle cx={x} cy={y} r={String(m.follow) === '0' ? 6 : 4} fill="currentColor" /><text x={x + 9} y={y + 4} fill="currentColor" fontSize="10">{m.callsign || m.hw_id}</text></g>;
  })}</svg>;
}

export default function SwarmDesignWorkspace({ assignments, configData, selectedId, onSelect,
  onChange, onEditBegin, onEditEnd, onUndo, onRedo, canUndo, canRedo,
  previewHeadings = EMPTY_HEADINGS, onHeadingChange, disabled = false }) {
  const model = useMemo(() => buildSwarmViewModel(assignments, configData), [assignments, configData]);
  const [view, setView] = useState('top');
  const [visitedViews, setVisitedViews] = useState(() => new Set(['top']));
  const [scope, setScope] = useState(null);
  const [search, setSearch] = useState('');
  const selected = model.dronesById[String(selectedId)];
  const cluster = model.clusters.find((item) => item.id === scope)
    || model.clusters.find((item) => item.type === 'cluster');
  const select = (id) => {
    onSelect(id);
    const parentCluster = model.dronesById[String(id)]?.clusterRootId;
    if (parentCluster) setScope(parentCluster);
  };
  const draft = assignments.find((item) => String(item.hw_id) === String(selectedId));
  const label = (drone) => drone.callsign || drone.alias || drone.title || `Aircraft ${drone.hw_id}`;
  const canvasProps = { assignments, configData, clusterId: cluster?.id, selectedId,
    onSelect: select, onAssignmentChange: disabled ? undefined : onChange,
    onEditBegin, onEditEnd, previewHeadings };
  const parentCandidates = model.drones.filter((item) => {
    let current = item; const visited = new Set();
    while (current) {
      if (String(current.hw_id) === String(selectedId) || visited.has(current.hw_id)) return false;
      visited.add(current.hw_id);
      current = model.dronesById[current.follow];
    }
    return true;
  });
  const headingId = draft?.follow !== '0' ? String(draft?.follow) : String(selectedId);
  return <div className="formation-workspace">
    <nav className="formation-roster" aria-label="Formation aircraft">
      <label className="formation-search">
        <input type="search" aria-label="Find aircraft" placeholder="Find aircraft" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <button className="formation-overview-button" type="button" aria-pressed={scope === 'all'} onClick={() => setScope('all')}>All clusters <span>{model.clusters.length}</span></button>
      {model.clusters.map((group) => <section key={group.id}>
        <button className="formation-cluster-label" type="button" aria-pressed={scope !== 'all' && cluster?.id === group.id} onClick={() => setScope(group.id)}>{group.title}</button>
        {group.drones.filter((drone) => `${label(drone)} ${drone.hw_id}`.toLowerCase().includes(search.toLowerCase())).map((drone) =>
          <button className="formation-aircraft" type="button" key={drone.hw_id} aria-pressed={String(selectedId) === String(drone.hw_id)} onClick={() => select(drone.hw_id)}>
            <span className="formation-role" aria-label={drone.follow === '0' ? 'Leader' : 'Follower'}>{drone.follow === '0' ? '◆' : '↳'}</span>
            <span>{label(drone)}</span><small>{drone.follow === '0' ? 'Leader' : `→ ${label(model.dronesById[drone.follow] || { hw_id: drone.follow })}`}</small>
          </button>)}
      </section>)}
    </nav>
    <section className="formation-stage" aria-label="Formation editor">
      <div className="formation-tools">
        <div role="tablist" aria-label="Formation view">{[['top', 'Top'], ['side', 'Side'], ['3d', '3D'], ['links', 'Links']].map(([id, text]) =>
          <button type="button" role="tab" key={id} aria-selected={view === id} onClick={() => {
            onEditEnd?.({ cancelled: true });
            setVisitedViews((previous) => new Set([...previous, id]));
            setView(id);
          }}>{text}</button>)}</div>
        <div><button type="button" aria-label="Undo formation edit" disabled={!canUndo || disabled} onClick={onUndo}>↶ Undo</button>
          <button type="button" aria-label="Redo formation edit" disabled={!canRedo || disabled} onClick={onRedo}>↷ Redo</button></div>
      </div>
      {scope === 'all' ? <div className="formation-cluster-overview">{model.clusters.map((group) =>
        <button type="button" key={group.id} onClick={() => setScope(group.id)}><strong>{group.title}</strong>
          <ClusterThumbnail members={group.drones} headings={previewHeadings} />
          <small>{group.drones.length} aircraft · Open formation →</small></button>)}</div> : null}
      {['top', 'side', 'links', '3d'].filter((id) => visitedViews.has(id)).map((id) =>
        <div key={id} hidden={scope === 'all' || view !== id} className="formation-view-panel">
          {id === 'links' ? <DroneGraph swarmData={cluster?.drones || []} selectedDroneId={selectedId} onSelectDrone={select} active={scope !== 'all' && view === id} />
            : id === '3d' ? <Suspense fallback={<p role="status">Loading 3D…</p>}><Formation3D {...canvasProps} /></Suspense>
              : <SwarmFormationCanvas {...canvasProps} plane={id === 'side' ? 'east-up' : 'top'} />}
        </div>)}
    </section>
    <aside className="formation-inspector" aria-label="Aircraft spacing">
      {selected && draft ? <>
        <header><strong>{label(selected)}</strong><span>{draft.follow === '0' ? 'Leader' : 'Follower'}</span></header>
        <fieldset disabled={disabled}>
          <label>Follows<select value={draft.follow} onChange={(event) => onChange(selectedId, { follow: event.target.value })}>
            <option value="0">Independent leader</option>{parentCandidates.map((item) => <option value={item.hw_id} key={item.hw_id}>{label(item)}</option>)}</select></label>
          {draft.follow !== '0' && <>
            <label>Reference<select value={draft.frame} onChange={(event) => onChange(selectedId, { frame: event.target.value })}>
              <option value="ned">Compass</option><option value="body">Leader heading</option></select></label>
            {['offset_x', 'offset_y', 'offset_z'].map((key, index) => <label key={key}>
              {(draft.frame === 'body' ? ['Forward', 'Right', 'Above'] : ['North', 'East', 'Above'])[index]}
              <span className="formation-unit-input"><input aria-label={`${key} metres`} type="number" step="0.1" value={draft[key]} onChange={(event) => onChange(selectedId, { [key]: event.target.value })} /><span>m</span></span>
            </label>)}
          </>}
        </fieldset>
        <label className="formation-heading">Preview heading<span className="formation-unit-input"><input type="number" step="5" min="0" max="359" value={previewHeadings[headingId] || 0} onChange={(event) => onHeadingChange(headingId, Number(event.target.value))} /><span>°</span></span></label>
        <small className="formation-preview-note">Preview only · no aircraft movement</small>
        {selected.warnings?.map((warning) => <p className="formation-issue" role="status" key={warning.code}>{warning.message}</p>)}
      </> : <p>Select an aircraft</p>}
    </aside>
  </div>;
}

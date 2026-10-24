import React, { lazy, Suspense, useMemo, useState } from 'react';
import SwarmFormationCanvas from './SwarmFormationCanvas';
import DroneGraph from './DroneGraph';
import FormationNumberInput from './FormationNumberInput';
import InfoHint from './InfoHint';
import { aircraftIdentity, buildAircraftLabels } from '../utilities/swarmDesignPresentation';
import { buildSwarmViewModel } from '../utilities/swarmDesignUtils';
import { resolveFormationPositions } from '../utilities/swarmFormationGeometry';
import '../styles/SwarmDesignWorkspace.css';

const Formation3D = lazy(() => import('./SwarmFormation3D'));
const EMPTY_HEADINGS = {};

function ClusterThumbnail({ members, headings, labels }) {
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
      <circle cx={x} cy={y} r={String(m.follow) === '0' ? 6 : 4} fill="currentColor" /><text x={x + 9} y={y + 4} fill="currentColor" fontSize="10">{labels[String(m.hw_id)]}</text></g>;
  })}</svg>;
}

export default function SwarmDesignWorkspace({ assignments, configData, selectedId, onSelect,
  onChange, onEditBegin, onEditEnd, onUndo, onRedo, canUndo, canRedo,
  onReset, canReset = false,
  previewHeadings = EMPTY_HEADINGS, onHeadingChange, disabled = false }) {
  const model = useMemo(() => buildSwarmViewModel(assignments, configData), [assignments, configData]);
  const [view, setView] = useState('top');
  const [layout, setLayout] = useState('single');
  const [expanded, setExpanded] = useState(null);
  const [showIds, setShowIds] = useState(false);
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
  const identityRows = useMemo(() => model.drones.map((drone) => ({ ...drone,
    ...configData.find((item) => String(item.hw_id) === String(drone.hw_id)) })), [model.drones, configData]);
  const names = useMemo(() => buildAircraftLabels(identityRows), [identityRows]);
  const labels = useMemo(() => buildAircraftLabels(identityRows, showIds), [identityRows, showIds]);
  const label = (drone) => names[String(drone.hw_id)] || `H${drone.hw_id}`;
  const selectedIdentity = identityRows.find((item) => String(item.hw_id) === String(selectedId));
  const headingId = draft?.follow !== '0' ? String(draft?.follow) : String(selectedId);
  const viewFrame = draft?.frame === 'body' && draft?.follow !== '0' ? 'body' : 'ned';
  const viewHeading = viewFrame === 'body' ? previewHeadings[headingId] || 0 : 0;
  const canvasProps = { assignments, configData, clusterId: cluster?.id, selectedId,
    onSelect: select, onAssignmentChange: disabled ? undefined : onChange,
    onEditBegin, onEditEnd, previewHeadings, viewFrame, viewHeading, aircraftLabels: labels,
    compact: layout === 'quad' && !expanded };
  const parentCandidates = model.drones.filter((item) => {
    let current = item; const visited = new Set();
    while (current) {
      if (String(current.hw_id) === String(selectedId) || visited.has(current.hw_id)) return false;
      visited.add(current.hw_id);
      current = model.dronesById[current.follow];
    }
    return true;
  });
  const views = [['top', 'Top'], ['front', 'Front'], ['side', 'Side'], ['3d', '3D'], ['links', 'Links']];
  const chooseView = (id) => {
    onEditEnd?.({ cancelled: true });
    setVisitedViews((previous) => new Set([...previous, id]));
    setLayout('single'); setExpanded(null); setView(id);
  };
  const changeLayout = (next) => {
    onEditEnd?.({ cancelled: true }); setLayout(next); setExpanded(null);
    if (next === 'quad') setVisitedViews((previous) => new Set([...previous, 'top', 'front', 'side', '3d']));
    if (view === 'links') setView('top');
  };
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
            <span>{label(drone)}</span><small>{aircraftIdentity(identityRows.find((item) => String(item.hw_id) === String(drone.hw_id)) || drone)} · {drone.follow === '0' ? 'Leader' : `→ ${label(model.dronesById[drone.follow] || { hw_id: drone.follow })}`}</small>
          </button>)}
      </section>)}
    </nav>
    <section className="formation-stage" aria-label="Formation editor">
      <div className="formation-tools">
        <div role="tablist" aria-label="Formation view">{views.map(([id, text]) =>
          <button type="button" role="tab" key={id} aria-selected={layout === 'single' && view === id} onClick={() => chooseView(id)}>{text}</button>)}</div>
        <div><button type="button" aria-label="Undo formation edit" disabled={!canUndo || disabled} onClick={onUndo}>↶ Undo</button>
          <button type="button" aria-label="Redo formation edit" disabled={!canRedo || disabled} onClick={onRedo}>↷ Redo</button>
          <button type="button" disabled={!canReset || disabled} onClick={onReset}>Reset draft</button></div>
      </div>
      <div className="formation-display-tools">
        <div role="group" aria-label="Editor layout"><button type="button" aria-pressed={layout === 'single'} onClick={() => changeLayout('single')}>Single</button>
          <button type="button" aria-pressed={layout === 'quad'} onClick={() => changeLayout('quad')}>Four views</button></div>
        <span className="formation-axis-reference">{viewFrame === 'body' ? `Body · ${names[headingId] || `H${headingId}`} · ${viewHeading}°` : 'NED · North / East / Up'}</span>
        <label><input type="checkbox" checked={showIds} onChange={(event) => setShowIds(event.target.checked)} /> Show IDs</label>
      </div>
      {scope === 'all' ? <div className="formation-cluster-overview">{model.clusters.map((group) =>
        <button type="button" key={group.id} onClick={() => setScope(group.id)}><strong>{group.title}</strong>
          <ClusterThumbnail members={group.drones} headings={previewHeadings} labels={labels} />
          <small>{group.drones.length} aircraft · Open formation →</small></button>)}</div> : null}
      <div className={`formation-view-grid ${layout === 'quad' && !expanded ? 'is-quad' : ''}`}>
      {views.filter(([id]) => visitedViews.has(id)).map(([id, title]) =>
        <div key={id} hidden={scope === 'all' || (layout === 'quad' ? id === 'links' || Boolean(expanded && expanded !== id) : view !== id)} className="formation-view-panel" aria-label={`${title} panel`}>
          {layout === 'quad' && <div className="formation-panel-heading"><strong>{title}</strong><button type="button" aria-label={`${expanded === id ? 'Restore four views' : `Expand ${title} view`}`} onClick={() => { onEditEnd?.({ cancelled: true }); setExpanded(expanded === id ? null : id); }}>{expanded === id ? 'Restore' : 'Expand'}</button></div>}
          {id === 'links' ? <DroneGraph swarmData={cluster?.drones || []} selectedDroneId={selectedId} onSelectDrone={select} aircraftLabels={labels} active={scope !== 'all' && layout === 'single' && view === id} />
            : id === '3d' ? <Suspense fallback={<p role="status">Loading 3D…</p>}><Formation3D {...canvasProps} /></Suspense>
              : <SwarmFormationCanvas {...canvasProps} plane={id === 'top' ? 'top' : id === 'front' ? 'east-up' : 'north-up'} />}
        </div>)}
      </div>
    </section>
    <aside className="formation-inspector" aria-label="Aircraft spacing">
      {selected && draft ? <>
        <header><strong>{label(selected)}</strong><span title="Hardware ID · Position ID (mission slot)">{aircraftIdentity(selectedIdentity || selected)}</span><span>{draft.follow === '0' ? 'Leader' : 'Follower'}</span></header>
        <fieldset disabled={disabled}>
          <label>Follows<select value={draft.follow} onChange={(event) => onChange(selectedId, { follow: event.target.value })}>
            <option value="0">Independent leader</option>{parentCandidates.map((item) => <option value={item.hw_id} key={item.hw_id}>{label(item)}</option>)}</select></label>
          {draft.follow !== '0' && <>
            <div className="formation-field-title"><label htmlFor="formation-reference">Reference</label><InfoHint icon="?" hoverable placement="left" label="About coordinate frames" content="NED keeps North/East spacing as the leader turns. Body rotates Forward/Right spacing with the followed aircraft. In MDS, Above is positive in both frames." /></div>
            <select id="formation-reference" value={draft.frame} onChange={(event) => onChange(selectedId, { frame: event.target.value })}>
              <option value="ned">NED · North/East</option><option value="body">Body · Forward/Right</option></select>
            {['offset_x', 'offset_y', 'offset_z'].map((key, index) => <label key={key}>
              {(draft.frame === 'body' ? ['Forward', 'Right', 'Above'] : ['North', 'East', 'Above'])[index]}
              <span className="formation-unit-input"><FormationNumberInput aria-label={`${key} metres`} value={draft[key]} onChange={(event) => onChange(selectedId, { [key]: event.target.value })} /><span>m</span></span>
            </label>)}
          </>}
        </fieldset>
        <div className="formation-heading"><div className="formation-field-title"><label htmlFor="formation-preview-heading">Preview heading</label><InfoHint icon="?" hoverable placement="left" label="About preview heading" content={`Design-only heading of ${names[headingId] || `H${headingId}`}: 0° North, 90° East. It rotates Body-frame previews, never commands yaw or aircraft movement.`} /></div>
          <span className="formation-unit-input"><input id="formation-preview-heading" type="number" step="5" min="0" max="359" disabled={disabled} value={previewHeadings[headingId] || 0} onChange={(event) => onHeadingChange(headingId, Number(event.target.value))} /><span>°</span></span></div>
        {selected.warnings?.map((warning) => <p className="formation-issue" role="status" key={warning.code}>{warning.message}</p>)}
      </> : <p>Select an aircraft</p>}
    </aside>
  </div>;
}

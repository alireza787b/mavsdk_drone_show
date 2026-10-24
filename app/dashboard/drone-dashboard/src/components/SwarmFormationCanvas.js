import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { moveAssignmentInPlane, projectFormationPoint, resolveFormationPositions } from '../utilities/swarmFormationGeometry';
import '../styles/SwarmFormationCanvas.css';

const WIDTH = 760, HEIGHT = 480;
const EMPTY = {};
const clampScale = (value) => Math.max(0.02, Math.min(500, value));
function fitCamera(points) {
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const minX = Math.min(-3, ...xs), maxX = Math.max(3, ...xs);
  const minY = Math.min(-3, ...ys), maxY = Math.max(3, ...ys);
  return { x: (minX + maxX) / 2, y: (minY + maxY) / 2, scale: clampScale(Math.min((WIDTH - 140) / (maxX - minX), (HEIGHT - 140) / (maxY - minY))) };
}

export default function SwarmFormationCanvas({ assignments, configData = [], clusterId, selectedId, onSelect, onAssignmentChange, previewHeadings = EMPTY, plane = 'top', onEditBegin, onEditEnd }) {
  const svgRef = useRef(null), gesture = useRef(null), cameras = useRef({});
  const patternId = useId().replace(/:/g, '');
  const [camera, setCamera] = useState({ x: 0, y: 0, scale: 30 });
  const [tool, setTool] = useState('select');
  const [moving, setMoving] = useState(null);
  const editCallbacks = useRef({ onAssignmentChange, onEditEnd });
  editCallbacks.current = { onAssignmentChange, onEditEnd };
  useEffect(() => () => {
    const active = gesture.current;
    if (active?.kind === 'move') {
      editCallbacks.current.onAssignmentChange?.(active.id, { offset_x: active.original.offset_x, offset_y: active.original.offset_y, offset_z: active.original.offset_z });
      editCallbacks.current.onEditEnd?.({ cancelled: true });
    }
  }, []);
  const scene = useMemo(() => {
    try { return { positions: resolveFormationPositions(assignments, previewHeadings), error: null }; }
    catch (error) { return { positions: {}, error: error.message }; }
  }, [assignments, previewHeadings]);
  const roots = [...new Set(Object.values(scene.positions).map((p) => p.root))];
  const root = clusterId && clusterId !== 'all' ? String(clusterId) : roots[0];
  const entries = assignments.filter((entry) => scene.positions[String(entry.hw_id)]?.root === root);
  const points = entries.map((entry) => ({ ...entry, id: String(entry.hw_id), ...projectFormationPoint(scene.positions[String(entry.hw_id)], plane) }));
  const scopeKey = `${root || ''}:${plane}`;
  const latestPoints = useRef(points); latestPoints.current = points;
  useEffect(() => { setCamera(cameras.current[scopeKey] || fitCamera(latestPoints.current)); }, [scopeKey]);
  const activeScope = useRef(scopeKey);
  useEffect(() => {
    if (activeScope.current === scopeKey) cameras.current[scopeKey] = camera;
    activeScope.current = scopeKey;
  }, [camera, scopeKey]);
  const toScreen = (point) => ({ x: WIDTH / 2 + (point.x - camera.x) * camera.scale, y: HEIGHT / 2 - (point.y - camera.y) * camera.scale });
  const pointFromEvent = (event) => {
    const svg = svgRef.current;
    const matrix = svg?.getScreenCTM?.();
    if (!matrix) return null;
    const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
    return point.matrixTransform(matrix.inverse());
  };
  const finish = (cancelled = false) => {
    const active = gesture.current;
    if (!active) return;
    gesture.current = null; setMoving(null);
    if (active.kind === 'move') {
      if (cancelled) onAssignmentChange?.(active.id, { offset_x: active.original.offset_x, offset_y: active.original.offset_y, offset_z: active.original.offset_z });
      onEditEnd?.({ cancelled });
    } else if (cancelled) setCamera(active.camera);
  };
  const begin = (event, entry) => {
    if (event.button !== 0 || gesture.current) return;
    const start = pointFromEvent(event); if (!start) return;
    event.preventDefault(); event.stopPropagation();
    const id = entry && String(entry.hw_id);
    if (id) onSelect?.(id);
    if (tool === 'select' && entry && String(entry.follow) !== '0') {
      gesture.current = { kind: 'move', id, original: { ...entry }, start, camera: { ...camera }, heading: previewHeadings[String(entry.follow)] || 0, plane };
      setMoving(id); onEditBegin?.();
    } else if (!entry || tool === 'pan') gesture.current = { kind: 'pan', start, camera: { ...camera } };
    if (gesture.current) svgRef.current?.setPointerCapture?.(event.pointerId);
  };
  const move = (event) => {
    const active = gesture.current, point = pointFromEvent(event);
    if (!active || !point) return;
    const dx = (point.x - active.start.x) / active.camera.scale;
    const dy = -(point.y - active.start.y) / active.camera.scale;
    if (active.kind === 'pan') setCamera({ ...active.camera, x: active.camera.x - dx, y: active.camera.y - dy });
    else onAssignmentChange?.(active.id, moveAssignmentInPlane(active.original, dx, dy, active.plane, active.heading));
  };
  const zoom = (factor) => { if (!gesture.current) setCamera((current) => ({ ...current, scale: clampScale(current.scale * factor) })); };
  const nudge = (event, entry) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect?.(String(entry.hw_id)); return; }
    const directions = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
    const direction = directions[event.key];
    if (!direction || String(entry.follow) === '0' || gesture.current) return;
    event.preventDefault(); event.stopPropagation();
    const step = event.shiftKey ? 1 : 0.1;
    onSelect?.(String(entry.hw_id)); onEditBegin?.();
    onAssignmentChange?.(String(entry.hw_id), moveAssignmentInPlane(entry, direction[0] * step, direction[1] * step, plane, previewHeadings[String(entry.follow)]));
    onEditEnd?.({ cancelled: false });
  };
  const spacing = Math.pow(10, Math.floor(Math.log10(60 / camera.scale)));
  const grid = spacing * camera.scale;
  const origin = toScreen({ x: 0, y: 0 });
  const byId = Object.fromEntries(points.map((point) => [point.id, point]));
  const selected = points.find((point) => point.id === String(selectedId));
  const descendants = new Set();
  points.forEach((point) => {
    let parent = String(point.follow);
    const visited = new Set();
    while (byId[parent] && !visited.has(parent)) {
      if (parent === String(selectedId)) { descendants.add(point.id); break; }
      visited.add(parent); parent = String(byId[parent].follow);
    }
  });
  const labelFor = (entry) => {
    const config = configData.find((item) => String(item.hw_id) === String(entry.hw_id));
    return config?.callsign || config?.alias || entry.callsign || `Drone ${entry.hw_id}`;
  };
  return <div className="swarm-formation-canvas" onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); finish(true); } }}>
    <div className="swarm-formation-canvas__toolbar" role="toolbar" aria-label="Formation canvas tools">
      <button type="button" aria-pressed={tool === 'select'} onClick={() => setTool('select')}>Select</button>
      <button type="button" aria-pressed={tool === 'pan'} onClick={() => setTool('pan')}>Pan</button>
      <span className="swarm-formation-canvas__tool-divider" />
      <button type="button" aria-label="Zoom out" onClick={() => zoom(0.8)}>−</button>
      <button type="button" aria-label="Zoom in" onClick={() => zoom(1.25)}>+</button>
      <button type="button" onClick={() => { if (!gesture.current) setCamera(fitCamera(points)); }}>Fit</button>
      <button type="button" disabled={!selected} onClick={() => { if (selected && !gesture.current) setCamera((current) => ({ ...current, x: selected.x, y: selected.y })); }}>Focus</button>
      <span className="swarm-formation-canvas__scale">{spacing.toPrecision(1)} m grid · {plane === 'top' ? 'North ↑ / East →' : `Up ↑ / ${plane === 'north-up' ? 'North' : 'East'} →`}</span>
    </div>
    {scene.error ? <div role="status" className="swarm-formation-canvas__empty">Fix the follow chain to preview this formation.</div> : <svg ref={svgRef} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="group" aria-label={`Editable swarm ${plane === 'top' ? 'top' : 'side'} view`} tabIndex={0}
      onPointerDown={(event) => begin(event, null)} onPointerMove={move} onPointerUp={() => finish(false)} onPointerCancel={() => finish(true)} onLostPointerCapture={() => finish(true)}>
      <defs><pattern id={patternId} width={grid} height={grid} x={origin.x} y={origin.y} patternUnits="userSpaceOnUse"><path d={`M ${grid} 0 L 0 0 0 ${grid}`} fill="none" stroke="currentColor" strokeOpacity=".3" /></pattern></defs>
      <rect width={WIDTH} height={HEIGHT} fill={`url(#${patternId})`} />
      <line className="swarm-formation-canvas__axis" x1={origin.x} x2={origin.x} y1={0} y2={HEIGHT} />
      <line className="swarm-formation-canvas__axis" x1={0} x2={WIDTH} y1={origin.y} y2={origin.y} />
      {points.map((point) => {
        const parent = byId[String(point.follow)]; if (!parent) return null;
        const a = toScreen(parent), b = toScreen(point);
        return <line key={`edge-${point.id}`} className="swarm-formation-canvas__link" x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
      })}
      {points.map((point) => {
        const position = toScreen(point), leader = String(point.follow) === '0';
        return <g key={point.id} role="button" tabIndex={0} aria-label={`${labelFor(point)}, ${leader ? 'leader origin' : 'formation position'}`} aria-pressed={point.id === String(selectedId)}
          className={`swarm-formation-canvas__node ${leader ? 'is-leader' : ''} ${point.id === String(selectedId) ? 'is-selected' : ''} ${descendants.has(point.id) ? 'is-descendant' : ''} ${moving === point.id ? 'is-moving' : ''}`}
          transform={`translate(${position.x} ${position.y})`} onPointerDown={(event) => begin(event, point)} onClick={() => onSelect?.(point.id)} onKeyDown={(event) => nudge(event, point)}>
          <circle className="swarm-formation-canvas__hit" r={23} />
          {leader ? <path d="M 0 -13 L 13 0 L 0 13 L -13 0 Z" /> : <circle r={11} />}
          <text y={-21} textAnchor="middle">{labelFor(point)}</text>
        </g>;
      })}
    </svg>}
  </div>;
}

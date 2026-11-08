import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FaCompressArrowsAlt, FaMinus, FaPlus } from 'react-icons/fa';
import { resolveFormationPositions, formationViewLabels } from '../utilities/swarmFormationGeometry';
import { fitPreviewCamera, INITIAL_PREVIEW_CAMERA, previewZoom, projectPreviewPoint } from '../utilities/formationPreviewCamera';
import { AircraftSilhouette } from './SwarmAircraftSymbol';

const VIEWS = { '3d': '3D', top: 'Top', front: 'Front', side: 'Side' };

/** Read-only, GPU-independent 3D overview. One coordinate model for every view. */
export default function SwarmCaptureScene({ entries, headings, overlays, labels, selectedId, onSelect,
  frame, heading, captureId }) {
  const [view, setView] = useState('3d');
  const [camera, setCamera] = useState(INITIAL_PREVIEW_CAMERA);
  const [size, setSize] = useState({ width: 800, height: 400 });
  const svg = useRef(null), pointers = useRef(new Map()), gesture = useRef(null);
  const moved = useRef(false);
  const positions = useMemo(() => resolveFormationPositions(entries || [], headings), [entries, headings]);
  const project = p => projectPreviewPoint(p, view, camera, frame, heading);
  const points = Object.entries(positions).map(([id, p]) => ({ id, ...project(p) }));
  const livePoints = overlays.map(p => ({ ...p, ...project(p) }));
  const all = [...points, ...livePoints];
  const latest = useRef({ all, camera, size }); latest.current = { all, camera, size };
  const fit = () => setCamera(fitPreviewCamera(latest.current.all, latest.current.size, latest.current.camera));
  const zoom = factor => setCamera(c => ({ ...c, scale: previewZoom(c.scale * factor) }));
  useEffect(() => {
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width && height) { setSize({ width, height });
        setCamera(c => fitPreviewCamera(latest.current.all, { width, height }, c)); }
    });
    observer.observe(svg.current); return () => observer.disconnect();
  }, []);
  // Only deliberate view/capture changes reframe, not live telemetry updates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fit(); }, [view, captureId]);
  useEffect(() => {
    const element = svg.current;
    const wheel = event => { event.preventDefault(); zoom(Math.exp(-event.deltaY * .001)); };
    element.addEventListener('wheel', wheel, { passive: false });
    return () => element.removeEventListener('wheel', wheel);
  }, []);
  const screen = p => ({ x: size.width / 2 + (p.x - camera.x) * camera.scale,
    y: size.height / 2 - (p.y - camera.y) * camera.scale });
  const begin = event => {
    if (![0, 1, 2].includes(event.button)) return;
    event.preventDefault();
    if (!pointers.current.size) moved.current = false;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    svg.current.setPointerCapture?.(event.pointerId);
    gesture.current = { camera: { ...camera }, points: [...pointers.current.values()],
      pan: event.button !== 0 || event.shiftKey || view !== '3d' };
  };
  const move = event => {
    if (!pointers.current.has(event.pointerId) || !gesture.current) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const start = gesture.current, current = [...pointers.current.values()];
    const a = start.points[0], b = current[0];
    if (current.length > 1 || Math.hypot(b.x-a.x,b.y-a.y)>4) moved.current = true;
    if (current.length > 1 && start.points.length > 1) {
      const distance = p => Math.hypot(p[1].x - p[0].x, p[1].y - p[0].y);
      const midpoint = p => ({ x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2 });
      const from = midpoint(start.points), to = midpoint(current);
      setCamera({ ...start.camera, scale: previewZoom(start.camera.scale * distance(current) / Math.max(1, distance(start.points))),
        x: start.camera.x - (to.x - from.x) / start.camera.scale,
        y: start.camera.y + (to.y - from.y) / start.camera.scale });
    } else if (start.pan) setCamera({ ...start.camera,
      x: start.camera.x - (b.x - a.x) / start.camera.scale,
      y: start.camera.y + (b.y - a.y) / start.camera.scale });
    else setCamera({ ...start.camera, azimuth: start.camera.azimuth + (b.x - a.x) * .008,
      elevation: Math.max(.12, Math.min(1.45, start.camera.elevation + (b.y - a.y) * .008)) });
  };
  const end = event => {
    pointers.current.delete(event.pointerId);
    gesture.current = pointers.current.size ? { camera: { ...camera }, points: [...pointers.current.values()], pan: view !== '3d' } : null;
  };
  const line = (a, b, key, className) => {
    const from = screen(project(a)), to = screen(project(b));
    return <line key={key} x1={from.x} y1={from.y} x2={to.x} y2={to.y} className={className} />;
  };
  const extent = Math.max(5, ...Object.values(positions).flatMap(p => [Math.abs(p.north), Math.abs(p.east)]));
  const step = 10 ** Math.floor(Math.log10(extent));
  const grid = Array.from({ length: 21 }, (_, i) => (i - 10) * step);
  const reference = formationViewLabels(frame);
  const axisEnd = 1;
  const axes = [ [{ north: axisEnd, east: 0, up: 0 }, reference.axis1],
    [{ north: 0, east: axisEnd, up: 0 }, reference.axis2], [{ north: 0, east: 0, up: axisEnd }, 'Up'] ];
  // Axis endpoints are already expressed in view axes; don't rotate Body twice.
  const axisProject = p => projectPreviewPoint(p, view, camera);
  return <div className="capture-scene">
    <div className="capture-scene__toolbar">
      <div role="group" aria-label="Capture view">{Object.entries(VIEWS).map(([key, label]) =>
        <button type="button" key={key} aria-pressed={view === key} onClick={() => {
          pointers.current.clear(); gesture.current = null;
          if (key === '3d' && view !== '3d') setCamera(c => ({ ...c, azimuth: INITIAL_PREVIEW_CAMERA.azimuth, elevation: INITIAL_PREVIEW_CAMERA.elevation }));
          setView(key);
        }}>{label}</button>)}</div>
      <div role="group" aria-label="Capture camera">
        <button type="button" aria-label="Fit formation" data-help="Fit captured and live positions" onClick={fit}><FaCompressArrowsAlt /></button>
        <button type="button" aria-label="Zoom out" onClick={() => zoom(.8)}><FaMinus /></button>
        <button type="button" aria-label="Zoom in" onClick={() => zoom(1.25)}><FaPlus /></button>
      </div>
    </div>
    <svg ref={svg} viewBox={`0 0 ${size.width} ${size.height}`} role="group" aria-label={`Capture ${VIEWS[view]} view`} tabIndex="0"
      onContextMenu={e => e.preventDefault()} onPointerDown={begin} onPointerMove={move} onPointerUp={end}
      onPointerCancel={end} onLostPointerCapture={end} onKeyDown={event => {
        if (event.target !== event.currentTarget) return;
        const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[event.key];
        if (d) { event.preventDefault(); setCamera(c => view === '3d' && !event.shiftKey
          ? { ...c, azimuth: c.azimuth + d[0] * .15, elevation: Math.max(.12, Math.min(1.45, c.elevation + d[1] * .1)) }
          : { ...c, x: c.x + d[0] * 30 / c.scale, y: c.y + d[1] * 30 / c.scale }); }
        if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(1.25); }
        if (event.key === '-') { event.preventDefault(); zoom(.8); }
        if (event.key.toLowerCase() === 'f') { event.preventDefault(); fit(); }
      }}>
      <title>Estimated formation. Drag to orbit; right-drag or Shift-drag to pan. Two fingers pan and pinch to zoom. Symbols are not to scale; grid is a reference plane, not terrain.</title>
      <g className="capture-scene__grid">{grid.flatMap(value => [
        line({north:value,east:-step*10,up:0},{north:value,east:step*10,up:0},`n${value}`),
        line({north:-step*10,east:value,up:0},{north:step*10,east:value,up:0},`e${value}`)])}</g>
      <g className="capture-scene__axes">{axes.map(([point,label]) => { const a={x:48,y:size.height-46},direction=axisProject(point),b={x:a.x+direction.x*28,y:a.y-direction.y*28};
        if (Math.hypot(a.x-b.x,a.y-b.y)<8) return null;
        return <g key={label}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y}/><text x={b.x+5} y={b.y-5}>{label}</text></g>; })}</g>
      <g className="capture-scene__links">{(entries||[]).map(entry => positions[String(entry.follow)]
        ? line(positions[String(entry.follow)],positions[String(entry.hw_id)],entry.hw_id) : null)}</g>
      {livePoints.map(point => { const p=screen(point); return <g key={`live${point.id}`} transform={`translate(${p.x} ${p.y})`}
        className={`capture-scene__live ${point.stale?'is-stale':''}`} role="img" aria-label={`${labels[point.id]||`H${point.id}`}, ${point.stale?'delayed':'live'} estimated position`}>
        <AircraftSilhouette ghost />
      </g>; })}
      {points.sort((a,b)=>b.depth-a.depth).map(point => { const p=screen(point),leader=String(entries.find(e=>String(e.hw_id)===point.id)?.follow)==='0';
        const yaw=headings[point.id];
        const arrow=Number.isFinite(yaw)?project({north:Math.cos(yaw*Math.PI/180),east:Math.sin(yaw*Math.PI/180),up:0}):null;
        const rotation=arrow?Math.atan2(arrow.x,arrow.y)*180/Math.PI:0;
        return <g key={point.id} transform={`translate(${p.x} ${p.y})`} className={`capture-scene__aircraft ${selectedId===point.id?'is-selected':''}`}
          role="button" tabIndex="0" aria-label={`${labels[point.id]||`H${point.id}`}, ${leader?'leader':'follower'}`} aria-pressed={selectedId===point.id}
          onClick={()=>{if(!moved.current)onSelect(point.id);}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(point.id);}}}>
          <circle r="25" className="capture-scene__hit"/><g transform={`rotate(${rotation})`}><AircraftSilhouette nose={Boolean(arrow&&Math.hypot(arrow.x,arrow.y)>.05)} /></g>
          {((view==='front'||view==='side')?selectedId===point.id:(points.length<=12||selectedId===point.id||leader))&&<text textAnchor="middle" y="-34">{leader?'★ ':''}{labels[point.id]||`H${point.id}`}</text>}
        </g>; })}
    </svg>
  </div>;
}

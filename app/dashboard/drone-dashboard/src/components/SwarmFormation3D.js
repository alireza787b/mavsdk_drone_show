import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { Html, Line, OrbitControls, TransformControls } from '@react-three/drei';
import { Vector3 } from 'three';
import { resolveFormationPositions, offsetForWorldPosition, formationToScene, sceneToFormation, formationViewLabels } from '../utilities/swarmFormationGeometry';
import { getPlotThemeColors } from '../utilities/plotThemeColors';
import '../styles/SwarmFormation3D.css';

const EMPTY = {};

function Aircraft({ label, selected, leader, colors, onSelect }) {
  return <>
    <mesh onClick={(event) => { event.stopPropagation(); onSelect(); }}>
      {leader ? <octahedronGeometry args={[0.4]} /> : <boxGeometry args={[0.55, 0.16, 0.55]} />}
      <meshBasicMaterial color={selected ? colors.success : colors.info} />
    </mesh>
    <Html center position={[0, 0.65, 0]} style={{ pointerEvents: 'none' }}>
      <span className={`swarm-formation-3d__label ${selected ? 'is-selected' : ''}`}>{label}</span>
    </Html>
  </>;
}

export function EditableAircraft({ assignment, position, parentPosition, previewHeadings, onAssignmentChange, onEditBegin, onEditEnd, plane = 'horizontal', viewFrame = 'ned', viewHeading = 0, children }) {
  const transform = useRef();
  const aircraft = useRef();
  const dragging = useRef(false);
  const dragContext = useRef(null);
  const callbacks = useRef({ onEditBegin, onEditEnd });
  callbacks.current = { onEditBegin, onEditEnd };
  const finish = (cancelled) => {
    if (!dragging.current) return;
    dragging.current = false;
    callbacks.current.onEditEnd?.({ cancelled });
  };
  useEffect(() => {
    const cancel = (event) => {
      if (event.key !== 'Escape' || !dragging.current) return;
      event.preventDefault();
      transform.current?.reset();
      finish(true);
    };
    window.addEventListener('keydown', cancel);
    const interrupted = () => { if (dragging.current) { transform.current?.reset(); finish(true); } };
    window.addEventListener('blur', interrupted);
    window.addEventListener('pointercancel', interrupted);
    return () => {
      window.removeEventListener('keydown', cancel);
      window.removeEventListener('blur', interrupted);
      window.removeEventListener('pointercancel', interrupted);
      finish(true);
    };
  }, []);

  // Keep attachment stable while draft/history updates rerender the aircraft.
  // Drei detaches when its children identity changes, clearing the active axis.
  return <><group ref={aircraft} position={formationToScene(position, viewFrame, viewHeading)}>{children}</group>
  <TransformControls ref={transform} object={aircraft} mode="translate" space="world" size={0.8}
    showX={plane !== 'north-up'} showY={plane !== 'horizontal'} showZ={plane !== 'east-up'}
    onMouseDown={() => {
      dragging.current = true;
      dragContext.current = { assignment, parentPosition, previewHeadings, viewFrame, viewHeading };
      callbacks.current.onEditBegin?.();
    }}
    onMouseUp={() => finish(false)}
    onObjectChange={() => {
      if (!dragging.current || !transform.current?.object) return;
      const context = dragContext.current;
      onAssignmentChange( String(context.assignment.hw_id), offsetForWorldPosition(
        context.assignment, sceneToFormation(transform.current.object.position, context.viewFrame, context.viewHeading), context.parentPosition, context.previewHeadings,
      ));
    }} />
  </>;
}

function Scene({ entries, positions, labels, selectedId, previewHeadings, onSelect, onAssignmentChange, onEditBegin, onEditEnd, fitRequest, focusRequest, zoomRequest, colors, plane, viewFrame, viewHeading }) {
  const controls = useRef();
  const { camera, invalidate } = useThree();
  const positionsRef = useRef(positions);
  positionsRef.current = positions;
  const viewRef = useRef({ viewFrame, viewHeading }); viewRef.current = { viewFrame, viewHeading };
  const toScene = (position) => formationToScene(position, viewFrame, viewHeading);
  useEffect(() => {
    const values = Object.values(positionsRef.current);
    if (!values.length) return;
    const points = values.map((value) => new Vector3(...formationToScene(value, viewRef.current.viewFrame, viewRef.current.viewHeading)));
    const center = points.reduce((sum, point) => sum.add(point), new Vector3()).divideScalar(points.length);
    const radius = Math.max(5, ...points.map((point) => point.distanceTo(center)));
    camera.position.copy(center).add(new Vector3(radius * 1.5, radius * 1.3, radius * 1.7));
    camera.lookAt(center);
    camera.near = Math.max(0.01, radius / 1000);
    camera.far = Math.max(2000, radius * 30);
    camera.updateProjectionMatrix();
    controls.current?.target.copy(center);
    controls.current?.update();
    invalidate();
  }, [fitRequest, camera, invalidate]);
  useEffect(() => {
    if (!zoomRequest.sequence || !controls.current) return;
    camera.position.sub(controls.current.target).multiplyScalar(zoomRequest.factor).add(controls.current.target);
    controls.current.update();
    invalidate();
  }, [zoomRequest, camera, invalidate]);
  useEffect(() => {
    if (!focusRequest || !positionsRef.current[String(selectedId)]) return;
    const center = new Vector3(...formationToScene(positionsRef.current[String(selectedId)],
      viewRef.current.viewFrame, viewRef.current.viewHeading));
    const direction = camera.position.clone().sub(controls.current?.target || new Vector3());
    camera.position.copy(center).add(direction);
    camera.lookAt(center);
    controls.current?.target.copy(center);
    controls.current?.update();
    invalidate();
  }, [focusRequest, selectedId, camera, invalidate]);
  const extent = Math.max(10, ...Object.values(positions).flatMap((p) => {
    const scene = toScene(p); return [Math.abs(scene[0]), Math.abs(scene[2])];
  }));
  const gridStep = 10 ** Math.floor(Math.log10(extent / 10));
  const gridSize = Math.ceil(extent * 2.4 / gridStep) * gridStep;
  const divisions = Math.min(100, Math.max(10, Math.round(gridSize / gridStep)));
  return <>
    <OrbitControls ref={controls} makeDefault enableDamping={false} minDistance={1} maxDistance={100000} />
    <gridHelper args={[gridSize, divisions, colors.textMuted, colors.textMuted]} onUpdate={(grid) => {
      // Border tokens can resolve to #RRGGBBAA, which Three.Color cannot parse.
      // Use an opaque theme color and express alpha through the material.
      const materials = Array.isArray(grid.material) ? grid.material : [grid.material];
      materials.forEach((material) => { material.transparent = true; material.opacity = 0.24; material.depthWrite = false; });
    }} />
    <Line points={[[0, 0.01, 0], [0, 0.01, -Math.max(5, extent)]]} color={colors.textMuted} lineWidth={1} />
    <Html position={[0, 0.1, -Math.max(5, extent)]} center style={{ pointerEvents: 'none' }}><span className="swarm-formation-3d__label">{formationViewLabels(viewFrame).axis1}</span></Html>
    <Line points={[[0, 0.01, 0], [Math.max(5, extent), 0.01, 0]]} color={colors.textMuted} lineWidth={1} />
    <Html position={[Math.max(5, extent), 0.1, 0]} center style={{ pointerEvents: 'none' }}><span className="swarm-formation-3d__label">{formationViewLabels(viewFrame).axis2}</span></Html>
    {entries.map((entry) => {
      const id = String(entry.hw_id);
      const position = positions[id];
      const parent = positions[String(entry.follow)];
      if (!position) return null;
      return <React.Fragment key={id}>
        {parent && <Line points={[toScene(parent), toScene(position)]} color={colors.info} lineWidth={1} />}
        {String(selectedId) === id && parent && onAssignmentChange
          ? <EditableAircraft assignment={entry} position={position} parentPosition={parent} previewHeadings={previewHeadings}
            onAssignmentChange={onAssignmentChange} onEditBegin={onEditBegin} onEditEnd={onEditEnd} plane={plane} viewFrame={viewFrame} viewHeading={viewHeading}>
            <Aircraft label={labels[id]} selected leader={false} colors={colors} onSelect={() => onSelect(id)} />
          </EditableAircraft>
          : <group position={toScene(position)}><Aircraft label={labels[id]} selected={String(selectedId) === id}
            leader={String(entry.follow) === '0'} colors={colors} onSelect={() => onSelect(id)} /></group>}
      </React.Fragment>;
    })}
  </>;
}

class SceneBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <p role="status">3D unavailable. Use Top or Side and the spacing fields.</p> : this.props.children; }
}

/** Lazy-load this component from Design; it has no network or aircraft side effects. */
export default function SwarmFormation3D({ assignments, configData = [], selectedId, onSelect, onAssignmentChange, previewHeadings = EMPTY, onEditBegin, onEditEnd, clusterId, viewFrame = 'ned', viewHeading = 0, aircraftLabels = EMPTY, compact = false, linkedViews = false, viewportCommand = null, onViewportCommand }) {
  const [fitRequest, setFitRequest] = useState(0);
  const [plane, setPlane] = useState('horizontal');
  const [editing, setEditing] = useState(false);
  const [zoomRequest, setZoomRequest] = useState({ sequence: 0, factor: 1 });
  const [focusRequest, setFocusRequest] = useState(0);
  const colors = getPlotThemeColors();
  const geometry = useMemo(() => {
    try { return { positions: resolveFormationPositions(assignments, previewHeadings) }; }
    catch (error) { return { positions: {}, error: error.message }; }
  }, [assignments, previewHeadings]);
  const roots = [...new Set(Object.values(geometry.positions).map((p) => p.root))];
  const root = String(clusterId && clusterId !== 'all' ? clusterId : roots[0] || '');
  const entries = assignments.filter((entry) => String(geometry.positions[String(entry.hw_id)]?.root) === root);
  const positions = Object.fromEntries(entries.map((entry) => [String(entry.hw_id), geometry.positions[String(entry.hw_id)]]));
  const labels = Object.fromEntries(assignments.map((entry) => {
    const config = configData.find((item) => String(item.hw_id) === String(entry.hw_id));
    return [String(entry.hw_id), aircraftLabels[String(entry.hw_id)] || config?.callsign || config?.alias || `H${entry.hw_id}`];
  }));
  // Cluster switching is deliberate framing; editing spacing is not.
  useEffect(() => { setFitRequest((value) => value + 1); }, [root]);
  const zoom = (factor) => setZoomRequest((value) => ({ sequence: value.sequence + 1, factor }));
  useEffect(() => {
    if (!viewportCommand?.sequence) return;
    if (viewportCommand.action === 'fit') setFitRequest((value) => value + 1);
    if (viewportCommand.action === 'focus') setFocusRequest((value) => value + 1);
    if (viewportCommand.action === 'zoom-in') zoom(0.8);
    if (viewportCommand.action === 'zoom-out') zoom(1.25);
  }, [viewportCommand?.sequence, viewportCommand?.action]);
  const axes = formationViewLabels(viewFrame);
  return <section className={`swarm-formation-3d ${compact ? 'is-compact' : ''}`} aria-label="3D formation editor">
    <div className="swarm-formation-tools" role="toolbar" aria-label="3D view controls">
      <button type="button" disabled={editing} onClick={() => linkedViews ? onViewportCommand?.('fit') : setFitRequest((value) => value + 1)}>Fit</button>
      <button type="button" disabled={editing} aria-label="Zoom 3D view in" onClick={() => linkedViews ? onViewportCommand?.('zoom-in') : zoom(0.8)}>+</button>
      <button type="button" disabled={editing} aria-label="Zoom 3D view out" onClick={() => linkedViews ? onViewportCommand?.('zoom-out') : zoom(1.25)}>−</button>
      <button type="button" disabled={editing || !selectedId} onClick={() => linkedViews ? onViewportCommand?.('focus') : setFocusRequest((value) => value + 1)}>Focus</button>
      <label className="swarm-formation-3d__plane">Move <select aria-label="3D movement plane" value={plane} disabled={editing} onChange={(event) => setPlane(event.target.value)}>
        <option value="horizontal">{axes.axis1} / {axes.axis2}</option><option value="east-up">{axes.axis2} / Up</option><option value="north-up">{axes.axis1} / Up</option>
      </select></label>
    </div>
    {geometry.error ? <p role="status">Resolve the follow chain to preview this formation.</p>
      : <SceneBoundary><Canvas camera={{ position: [12, 10, 14], fov: 45 }} frameloop="demand"
        fallback={<p role="status">3D unavailable. Use Top or Side.</p>}>
        <color attach="background" args={[colors.background]} />
        <Scene entries={entries} positions={positions} labels={labels} selectedId={selectedId} previewHeadings={previewHeadings}
          onSelect={onSelect} onAssignmentChange={onAssignmentChange}
          onEditBegin={() => { setEditing(true); onEditBegin?.(); }}
          onEditEnd={(result) => { setEditing(false); onEditEnd?.(result); }}
          fitRequest={fitRequest} focusRequest={focusRequest} zoomRequest={zoomRequest} colors={colors} plane={plane} viewFrame={viewFrame} viewHeading={viewHeading} />
      </Canvas></SceneBoundary>}
  </section>;
}

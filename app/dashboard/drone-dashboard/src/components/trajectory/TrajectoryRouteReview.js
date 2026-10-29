import React, { useContext, useEffect, useMemo, useRef, useState } from 'react';
import { CircleMarker, Polyline, useMap } from 'react-leaflet';
import { MdCenterFocusStrong } from 'react-icons/md';
import LeafletMapBase from '../map/LeafletMapBase';
import RouteSketch from './RouteSketch';
import ThemeContext from '../../contexts/ThemeContext';
import { getDronePaletteColors } from '../../utilities/plotThemeColors';
import {
  normalizeTrajectoryPreviewRoutes, routeGeographicBounds, trajectoryPreviewGeometryKey,
} from '../../utilities/trajectoryRoutePreview';
import '../../styles/TrajectoryRouteReview.css';

const EMPTY = [];

const RouteMapViewport = ({ bounds, packageKey, fitRequest }) => {
  const map = useMap();
  const boundsRef = useRef(bounds);
  boundsRef.current = bounds;
  useEffect(() => {
    const current = boundsRef.current;
    if (!current) return;
    map.invalidateSize({ pan: false });
    map.fitBounds([[current.minLat, current.minLng], [current.maxLat, current.maxLng]], {
      padding: [24, 24], maxZoom: 18, animate: false,
    });
  }, [map, packageKey, fitRequest]);
  useEffect(() => {
    if (typeof ResizeObserver === 'undefined' || !map.getContainer) return undefined;
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  return null;
};

export default function TrajectoryRouteReview({
  preview = {}, formationAssignments = EMPTY, fleet = EMPTY, packageIdentity = null,
}) {
  const theme = useContext(ThemeContext)?.theme;
  const [palette, setPalette] = useState(getDronePaletteColors);
  useEffect(() => {
    // ThemeProvider applies CSS tokens after rendering. Read their concrete
    // colors on the next frame so Leaflet and the HTML swatches stay identical.
    const frame = window.requestAnimationFrame(() => {
      const next = getDronePaletteColors();
      setPalette((current) => current.join('|') === next.join('|') ? current : next);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [theme]);
  const routes = useMemo(() => normalizeTrajectoryPreviewRoutes(preview, formationAssignments, fleet, palette), [preview, formationAssignments, fleet, palette]);
  const geometryKey = useMemo(() => trajectoryPreviewGeometryKey(routes), [routes]);
  const coordinateFrame = useMemo(() => routeGeographicBounds(routes), [routes]);
  const packageKey = `${packageIdentity ?? preview?.package_hash ?? preview?.package_id ?? ''}:${geometryKey}`;
  const defaultHidden = useMemo(() => new Set(routes.filter((route) => route.outsideMission).map((route) => route.id)), [routes]);
  const [visibility, setVisibility] = useState({ packageKey, hidden: defaultHidden });
  const [query, setQuery] = useState('');
  const [view, setView] = useState('map');
  const [fitRequest, setFitRequest] = useState(0);
  const hidden = visibility.packageKey === packageKey ? visibility.hidden : defaultHidden;
  const visible = routes.filter((route) => !hidden.has(route.id));
  const bounds = routeGeographicBounds(visible, coordinateFrame);
  const known = routes.filter((route) => !route.outsideMission);
  const outside = routes.filter((route) => route.outsideMission);
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches = (route) => terms.every((term) => `${route.label} ${route.hardwareLabel} ${route.roleLabel}`.toLocaleLowerCase().includes(term));
  const toggle = (id) => setVisibility(() => {
    const next = new Set(hidden);
    if (next.has(id)) next.delete(id); else next.add(id);
    return { packageKey, hidden: next };
  });
  const showAll = () => { setVisibility({ packageKey, hidden: new Set() }); setQuery(''); setFitRequest((value) => value + 1); };
  const renderAircraft = (route) => (
    <label key={route.id} className="trajectory-route-review__aircraft" data-aircraft-id={route.id}>
      <input type="checkbox" checked={!hidden.has(route.id)} onChange={() => toggle(route.id)}
        aria-label={`Show ${route.label === route.hardwareLabel ? route.label : `${route.label} (${route.hardwareLabel})`} route`} />
      <i aria-hidden="true" style={{ backgroundColor: route.color }} />
      <span><strong>{route.label}</strong><small>{route.roleLabel}{route.label !== route.hardwareLabel ? ` · ${route.hardwareLabel}` : ''}</small></span>
    </label>
  );

  return <section className="trajectory-route-review" aria-label="Processed route review">
    <div className="trajectory-route-review__toolbar">
      <div className="trajectory-route-review__views" role="group" aria-label="Route view">
        <button type="button" aria-pressed={view === 'map'} onClick={() => setView('map')}>Map</button>
        <button type="button" aria-pressed={view === 'overview'} onClick={() => setView('overview')}>Overview</button>
      </div>
      <button type="button" onClick={() => setFitRequest((value) => value + 1)} disabled={!visible.length} aria-label="Fit visible routes">
        <MdCenterFocusStrong aria-hidden="true" /> Fit
      </button>
      <span className="trajectory-route-review__shown">{visible.length} shown</span>
    </div>
    <div className="trajectory-route-review__body">
      <div className="trajectory-route-review__canvas">
        {!visible.length ? <div className="trajectory-route-review__empty" role="status">
          <strong>{known.length ? 'All routes hidden' : 'No routes assigned to this mission'}</strong>
          <span>{known.length ? 'Select an aircraft to show its path.' : outside.length ? 'Review Formation or inspect retained paths in Outside mission.' : 'Process the mission to see geographic paths.'}</span>
        </div> : view === 'overview' ? <RouteSketch series={visible} bounds={bounds} /> : <LeafletMapBase
          center={[(bounds.minLat + bounds.maxLat) / 2, (bounds.minLng + bounds.maxLng) / 2]}
          zoom={12} showLayerControl={false} maxBounds={null} worldCopyJump={false}
          className="trajectory-route-review__map" style={{ width: '100%', height: '100%' }}>
          <RouteMapViewport bounds={bounds} packageKey={packageKey} fitRequest={fitRequest} />
          {visible.map((route) => <React.Fragment key={route.id}>
            {route.segments.map((segment, index) => <Polyline key={index}
              positions={segment.map((point) => [point.latitude, bounds.unwrap(point.longitude)])}
              pathOptions={{ color: route.color, weight: route.role === 'leader' ? 2.5 : 1.75, opacity: .9 }} />)}
            <CircleMarker center={[route.points[0].latitude, bounds.unwrap(route.points[0].longitude)]} radius={3}
              pathOptions={{ color: route.color, fillColor: route.color, fillOpacity: 1, weight: 1 }} />
          </React.Fragment>)}
        </LeafletMapBase>}
      </div>
      <aside className="trajectory-route-review__legend" aria-label="Aircraft routes">
        <div className="trajectory-route-review__legend-heading"><strong>Aircraft · {known.length}</strong>
          <button type="button" onClick={showAll} disabled={!routes.length}>Show all</button></div>
        {routes.length > 6 && <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find aircraft" aria-label="Find aircraft routes" />}
        <div className="trajectory-route-review__list">
          {known.filter(matches).map(renderAircraft)}
          {known.length > 0 && !known.some(matches) && <p className="trajectory-route-review__no-match">No matching mission aircraft</p>}
          {outside.length > 0 && <details key={packageKey} className="trajectory-route-review__outside">
            <summary>Outside mission ({outside.length})</summary>
            <p>No assignment in this mission; regenerate paths or inspect this saved output.</p>
            {outside.filter(matches).map(renderAircraft)}
            {!outside.some(matches) && <p className="trajectory-route-review__no-match">No matching retained paths</p>}
          </details>}
        </div>
      </aside>
    </div>
  </section>;
}

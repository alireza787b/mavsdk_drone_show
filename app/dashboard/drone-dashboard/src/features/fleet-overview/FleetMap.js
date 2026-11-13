import React, { useEffect, useRef } from 'react';
import { CircleMarker, Tooltip, useMap } from 'react-leaflet';
import L from 'leaflet';
import LeafletMapBase from '../../components/map/LeafletMapBase';
import { renderedFleetAircraft } from './fleetDisplay';

function FitAircraft({ aircraft, fitSignal }) {
  const map = useMap();
  const latest = useRef(aircraft);
  latest.current = aircraft;
  useEffect(() => {
    if (!latest.current.length) return;
    const bounds = L.latLngBounds(latest.current.map((item) => [item.position.latitude, item.position.longitude]));
    map.invalidateSize();
    map.fitBounds(bounds, { padding: [45, 45], maxZoom: 18, animate: false });
  }, [map, fitSignal]);
  return null;
}

/** Read-only map: marker inspection and camera gestures never select targets. */
export default function FleetMap({ aircraft, selectedIds, onInspect, onShowUnmapped }) {
  const mapped = renderedFleetAircraft(aircraft, 'map');
  const [fitSignal, setFitSignal] = React.useState(0);
  const firstFit = useRef(false);
  useEffect(() => {
    if (mapped.length && !firstFit.current) { firstFit.current = true; setFitSignal((value) => value + 1); }
  }, [mapped.length]);
  const center = mapped.length ? [mapped[0].position.latitude, mapped[0].position.longitude] : [0, 0];
  return <section className="fleet-map" aria-label="Aircraft map">
    <div className="fleet-map__tools"><button type="button" onClick={() => setFitSignal((value) => value + 1)} disabled={!mapped.length}>Fit aircraft</button>
      {mapped.length !== aircraft.length && <button type="button" onClick={onShowUnmapped}>{aircraft.length - mapped.length} without current position</button>}</div>
    <LeafletMapBase center={center} zoom={mapped.length ? 17 : 2} showLayerControl={false} style={{ height: '100%' }}>
      <FitAircraft aircraft={mapped} fitSignal={fitSignal} />
      {mapped.map((item) => <CircleMarker key={item.id} center={[item.position.latitude, item.position.longitude]}
        radius={selectedIds.has(item.id) ? 10 : 7} pathOptions={{ color: selectedIds.has(item.id) ? '#5fb9ff' : '#f4f7fb',
          weight: selectedIds.has(item.id) ? 3 : 1, fillColor: item.attention ? '#f0b429' : '#142a41', fillOpacity: 1 }}
        eventHandlers={{ click: () => onInspect(item.id) }}>
        <Tooltip permanent direction="top">{item.label} · H{item.id}</Tooltip>
      </CircleMarker>)}
    </LeafletMapBase>
  </section>;
}

import React from 'react';
import '../../styles/RouteSketch.css';

export const ROUTE_SKETCH_COLORS = [
  'var(--route-sketch-color-primary)',
  'var(--route-sketch-color-success)',
  'var(--route-sketch-color-danger)',
  'var(--route-sketch-color-accent)',
  'var(--route-sketch-color-info)',
  'var(--route-sketch-color-warning)',
];

const collectSketchBounds = (series = []) => {
  const points = series.flatMap((item) => item.points || []);
  const lats = points.map((point) => point.latitude ?? point.lat).filter(Number.isFinite);
  const lngs = points.map((point) => point.longitude ?? point.lng).filter(Number.isFinite);
  if (!lats.length || !lngs.length) {
    return null;
  }
  return {
    minLat: Math.min(...lats),
    maxLat: Math.max(...lats),
    minLng: Math.min(...lngs),
    maxLng: Math.max(...lngs),
  };
};

const mapPointToSketch = (point, bounds) => {
  const lat = point.latitude ?? point.lat;
  const lng = point.longitude ?? point.lng;
  const lngSpan = Math.max(bounds.maxLng - bounds.minLng, 0.000001);
  const latSpan = Math.max(bounds.maxLat - bounds.minLat, 0.000001);
  const x = 24 + ((lng - bounds.minLng) / lngSpan) * 252;
  const y = 156 - ((lat - bounds.minLat) / latSpan) * 132;
  return `${x.toFixed(1)},${y.toFixed(1)}`;
};

const RouteSketch = ({ series = [], emptyLabel = 'No route preview' }) => {
  const bounds = collectSketchBounds(series);
  if (!bounds) {
    return (
      <div className="swarm-route-sketch swarm-route-sketch--empty">
        {emptyLabel}
      </div>
    );
  }

  return (
    <svg className="swarm-route-sketch" viewBox="0 0 300 180" role="img" aria-label="Route preview">
      <rect x="0" y="0" width="300" height="180" rx="6" className="swarm-route-sketch__bg" />
      {series.map((item, index) => {
        const points = (item.points || []).filter((point) => (
          Number.isFinite(point.latitude ?? point.lat) && Number.isFinite(point.longitude ?? point.lng)
        ));
        if (!points.length) {
          return null;
        }
        const mapped = points.map((point) => mapPointToSketch(point, bounds));
        const color = item.color || ROUTE_SKETCH_COLORS[index % ROUTE_SKETCH_COLORS.length];
        return (
          <g key={item.id || item.label || index}>
            <polyline
              points={mapped.join(' ')}
              fill="none"
              stroke={color}
              strokeWidth={item.role === 'leader' ? 4 : 2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx={mapped[0].split(',')[0]} cy={mapped[0].split(',')[1]} r="4" fill={color} />
            <circle
              cx={mapped[mapped.length - 1].split(',')[0]}
              cy={mapped[mapped.length - 1].split(',')[1]}
              r="4"
              fill="var(--color-bg-canvas)"
              stroke={color}
              strokeWidth="2"
            />
          </g>
        );
      })}
    </svg>
  );
};

export default RouteSketch;

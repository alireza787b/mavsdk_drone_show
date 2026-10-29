import React from 'react';
import { routeGeographicBounds, routePointSegments, trajectoryRouteColor, TRAJECTORY_ROUTE_COLORS } from '../../utilities/trajectoryRoutePreview';
import '../../styles/RouteSketch.css';

export const ROUTE_SKETCH_COLORS = TRAJECTORY_ROUTE_COLORS;

const mapPointToSketch = (point, bounds) => {
  const lat = point.latitude ?? point.lat;
  const lng = bounds.unwrap(point.longitude ?? point.lng);
  const centerLat = (bounds.maxLat + bounds.minLat) / 2;
  const centerLng = (bounds.maxLng + bounds.minLng) / 2;
  // Local geographic overview: use one scale for north/east rather than
  // stretching each axis independently into the available rectangle.
  const longitudeScale = Math.max(Math.cos(centerLat * Math.PI / 180), 1e-6);
  const scale = Math.min(252 / Math.max((bounds.maxLng - bounds.minLng) * longitudeScale, 1e-6),
    132 / Math.max(bounds.maxLat - bounds.minLat, 1e-6));
  const x = 150 + (lng - centerLng) * longitudeScale * scale;
  const y = 90 - (lat - centerLat) * scale;
  return `${x.toFixed(1)},${y.toFixed(1)}`;
};

const RouteSketch = ({ series = [], emptyLabel = 'No route preview', bounds: providedBounds = null }) => {
  const bounds = providedBounds || routeGeographicBounds(series);
  if (!bounds) {
    return (
      <div className="swarm-route-sketch swarm-route-sketch--empty">
        {emptyLabel}
      </div>
    );
  }

  return (
    <svg className="swarm-route-sketch" viewBox="0 0 300 180" role="img" aria-label="Route preview">
      <rect x="0" y="0" width="300" height="180" className="swarm-route-sketch__bg" />
      {series.map((item, index) => {
        const segments = item.segments || routePointSegments(item.points || []);
        if (!segments.length) {
          return null;
        }
        const color = item.color || trajectoryRouteColor(item.id ?? item.label ?? index);
        return (
          <g key={item.id || item.label || index} data-route-id={item.id}>
            {segments.map((segment, segmentIndex) => {
              const mapped = segment.map((point) => mapPointToSketch(point, bounds));
              return <g key={segmentIndex}>
            <polyline
              points={mapped.join(' ')}
              fill="none"
              stroke={color}
              strokeWidth={item.role === 'leader' ? 2 : 1.5}
              vectorEffect="non-scaling-stroke"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path d={`M${mapped[0]} l0 0`} stroke={color} strokeWidth="4" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            <path d={`M${mapped[mapped.length - 1]} l0 0`} stroke={color} strokeWidth="4" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
              </g>;
            })}
          </g>
        );
      })}
    </svg>
  );
};

export default RouteSketch;

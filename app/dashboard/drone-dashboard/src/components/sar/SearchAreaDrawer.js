// src/components/sar/SearchAreaDrawer.js
/**
 * QuickScout geometry authoring for Mapbox mode.
 *
 * Supports:
 * - polygon authoring for area-sweep missions
 * - line authoring for corridor-search missions
 *
 * The parent owns the mission-template switch and receives normalized
 * `{lat,lng}` points from `onAreaChange(points, areaSqM)`.
 */

import React, { useCallback, useEffect, useRef } from 'react';
import { area as turfArea } from '@turf/area';

let MapboxDraw;
let useControl;
let mapboxDrawAvailable = false;

try {
  MapboxDraw = require('@mapbox/mapbox-gl-draw');
  if (MapboxDraw.default) MapboxDraw = MapboxDraw.default;
  require('@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css');
  const rgl = require('react-map-gl');
  useControl = rgl.useControl;
  mapboxDrawAvailable = true;
} catch (e) {
  console.warn('Mapbox GL Draw not available:', e.message);
}

const DRAW_STYLES = [
  {
    id: 'gl-draw-polygon-fill-active',
    type: 'fill',
    filter: ['all', ['==', 'active', 'true'], ['==', '$type', 'Polygon']],
    paint: { 'fill-color': '#3b82f6', 'fill-outline-color': '#3b82f6', 'fill-opacity': 0.15 },
  },
  {
    id: 'gl-draw-polygon-fill-static',
    type: 'fill',
    filter: ['all', ['==', 'active', 'false'], ['==', '$type', 'Polygon']],
    paint: { 'fill-color': '#3b82f6', 'fill-outline-color': '#3b82f6', 'fill-opacity': 0.15 },
  },
  {
    id: 'gl-draw-polygon-stroke-active',
    type: 'line',
    filter: ['all', ['==', 'active', 'true'], ['==', '$type', 'Polygon']],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#3b82f6', 'line-dasharray': [0.2, 2], 'line-width': 2 },
  },
  {
    id: 'gl-draw-polygon-stroke-static',
    type: 'line',
    filter: ['all', ['==', 'active', 'false'], ['==', '$type', 'Polygon']],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#3b82f6', 'line-width': 2 },
  },
  {
    id: 'gl-draw-line-active',
    type: 'line',
    filter: ['all', ['==', '$type', 'LineString'], ['==', 'active', 'true']],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#facc15', 'line-dasharray': [0.2, 2], 'line-width': 3 },
  },
  {
    id: 'gl-draw-line-static',
    type: 'line',
    filter: ['all', ['==', '$type', 'LineString'], ['==', 'active', 'false']],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#facc15', 'line-width': 3 },
  },
  {
    id: 'gl-draw-polygon-and-line-vertex-active',
    type: 'circle',
    filter: ['all', ['==', 'meta', 'vertex'], ['==', '$type', 'Point'], ['!=', 'mode', 'static']],
    paint: { 'circle-radius': 6, 'circle-color': '#3b82f6', 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 },
  },
  {
    id: 'gl-draw-polygon-midpoint',
    type: 'circle',
    filter: ['all', ['==', '$type', 'Point'], ['==', 'meta', 'midpoint']],
    paint: { 'circle-radius': 4, 'circle-color': '#3b82f6' },
  },
];

const buildPolygonFeature = (points) => {
  if (!Array.isArray(points) || points.length < 3) {
    return null;
  }
  const coordinates = points.map((point) => [point.lng, point.lat]);
  coordinates.push(coordinates[0]);
  return {
    type: 'Feature',
    geometry: {
      type: 'Polygon',
      coordinates: [coordinates],
    },
  };
};

const buildLineFeature = (points) => {
  if (!Array.isArray(points) || points.length < 2) {
    return null;
  }
  return {
    type: 'Feature',
    geometry: {
      type: 'LineString',
      coordinates: points.map((point) => [point.lng, point.lat]),
    },
  };
};

const DrawControl = ({
  onAreaChange,
  controlRef,
  initialArea,
  initialPoints,
  geometryMode = 'polygon',
}) => {
  const drawRef = useRef(null);
  const isLineMode = geometryMode === 'line';
  const initialGeometryRef = useRef(isLineMode ? initialPoints : initialArea);

  useEffect(() => {
    initialGeometryRef.current = isLineMode ? initialPoints : initialArea;
  }, [initialArea, initialPoints, isLineMode]);

  useEffect(() => {
    if (controlRef) {
      controlRef.current = {
        reset: () => {
          if (!drawRef.current) return;
          drawRef.current.deleteAll();
          drawRef.current.changeMode(isLineMode ? 'draw_line_string' : 'draw_polygon');
        },
        trash: () => {
          if (drawRef.current) {
            drawRef.current.trash();
          }
        },
      };
    }
    return () => {
      if (controlRef) {
        controlRef.current = null;
      }
    };
  }, [controlRef, isLineMode]);

  useEffect(() => {
    const onKeyDown = (e) => {
      if (!drawRef.current) return;
      const tag = document.activeElement?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (document.activeElement?.isContentEditable) return;

      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        drawRef.current.trash();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (!drawRef.current) return;

    const feature = isLineMode
      ? buildLineFeature(initialGeometryRef.current)
      : buildPolygonFeature(initialGeometryRef.current);

    if (!feature) return;

    const ids = drawRef.current.add(feature);
    if (!ids || !ids[0]) return;

    setTimeout(() => {
      if (!drawRef.current) return;
      try {
        drawRef.current.changeMode('direct_select', { featureId: ids[0] });
      } catch (_) {
        drawRef.current.changeMode('simple_select');
      }
    }, 50);
  }, [isLineMode]);

  const handleCreate = useCallback((e) => {
    if (!drawRef.current) return;

    const data = drawRef.current.getAll();
    if (data.features.length > 1) {
      data.features.slice(0, -1).forEach((feature) => drawRef.current.delete(feature.id));
    }

    const feature = e.features && e.features[0];
    if (!feature) return;

    if (isLineMode && feature.geometry.type === 'LineString') {
      const points = feature.geometry.coordinates.map(([lng, lat]) => ({ lat, lng }));
      onAreaChange(points, 0);
    } else if (!isLineMode && feature.geometry.type === 'Polygon') {
      const points = feature.geometry.coordinates[0]
        .slice(0, -1)
        .map(([lng, lat]) => ({ lat, lng }));
      onAreaChange(points, turfArea(feature));
    } else {
      return;
    }

    const featureId = feature.id;
    setTimeout(() => {
      if (!drawRef.current) return;
      try {
        drawRef.current.changeMode('direct_select', { featureId });
      } catch (_) {
        // Ignore if the geometry was deleted before the timeout fired.
      }
    }, 0);
  }, [isLineMode, onAreaChange]);

  const handleUpdate = useCallback((e) => {
    const feature = e.features && e.features[0];
    if (!feature) return;

    if (isLineMode && feature.geometry.type === 'LineString') {
      const points = feature.geometry.coordinates.map(([lng, lat]) => ({ lat, lng }));
      onAreaChange(points, 0);
    } else if (!isLineMode && feature.geometry.type === 'Polygon') {
      const points = feature.geometry.coordinates[0]
        .slice(0, -1)
        .map(([lng, lat]) => ({ lat, lng }));
      onAreaChange(points, turfArea(feature));
    }
  }, [isLineMode, onAreaChange]);

  const handleDelete = useCallback(() => {
    onAreaChange([], 0);
    if (drawRef.current) {
      drawRef.current.changeMode(isLineMode ? 'draw_line_string' : 'draw_polygon');
    }
  }, [isLineMode, onAreaChange]);

  useControl(
    () => {
      if (!mapboxDrawAvailable) return null;

      const hasInitial = isLineMode
        ? Array.isArray(initialGeometryRef.current) && initialGeometryRef.current.length >= 2
        : Array.isArray(initialGeometryRef.current) && initialGeometryRef.current.length >= 3;

      const draw = new MapboxDraw({
        displayControlsDefault: false,
        controls: { polygon: false, line_string: false, trash: false },
        defaultMode: hasInitial ? 'simple_select' : (isLineMode ? 'draw_line_string' : 'draw_polygon'),
        styles: DRAW_STYLES,
      });
      drawRef.current = draw;
      return draw;
    },
    ({ map }) => {
      if (!mapboxDrawAvailable) return;
      map.on('draw.create', handleCreate);
      map.on('draw.update', handleUpdate);
      map.on('draw.delete', handleDelete);
    },
    ({ map }) => {
      if (!mapboxDrawAvailable) return;
      map.off('draw.create', handleCreate);
      map.off('draw.update', handleUpdate);
      map.off('draw.delete', handleDelete);
    },
    { position: 'top-left' }
  );

  return null;
};

export const MapboxDrawActionBar = ({
  geometryMode = 'polygon',
  searchArea,
  searchPath,
  onReset,
  onTrash,
}) => {
  const isLineMode = geometryMode === 'line';
  const pointCount = isLineMode
    ? (Array.isArray(searchPath) ? searchPath.length : 0)
    : (Array.isArray(searchArea) ? searchArea.length : 0);
  const hasGeometry = isLineMode ? pointCount >= 2 : pointCount >= 3;
  const hasDraft = pointCount > 0;

  return (
    <div className="ldc-instruction-bar">
      <span className="ldc-instruction-text">
        {isLineMode
          ? (hasGeometry
            ? 'Drag route points to edit · Select point then Remove'
            : 'Click to add route points, double-click to finish')
          : (hasGeometry
            ? 'Drag vertices to edit · Select vertex then Remove'
            : 'Click to add points, double-click to finish')}
      </span>
      <div className="ldc-action-group">
        {hasGeometry && (
          <button
            className="ldc-action-btn ldc-action-btn--undo"
            onClick={onTrash}
            aria-label="Remove selected point with Delete or Backspace"
          >
            {isLineMode ? 'Remove Point' : 'Remove Vertex'}
          </button>
        )}
        {hasDraft && (
          <button className="ldc-action-btn ldc-action-btn--reset" onClick={onReset}>
            Reset
          </button>
        )}
      </div>
    </div>
  );
};

export const MapboxSetupInstructions = () => (
  <div className="qs-mapbox-setup">
    <h3>Mapbox Token Required</h3>
    <p>
      QuickScout requires a Mapbox access token for the interactive map.
      Add your token to the environment configuration:
    </p>
    <p><code>REACT_APP_MAPBOX_ACCESS_TOKEN=pk.your_token_here</code></p>
    <p>
      Get a free token at{' '}
      <a href="https://www.mapbox.com/" target="_blank" rel="noopener noreferrer">
        mapbox.com
      </a>
    </p>
  </div>
);

const SafeDrawControl = (props) => {
  if (!mapboxDrawAvailable || !useControl) return null;
  return <DrawControl {...props} />;
};

export default SafeDrawControl;

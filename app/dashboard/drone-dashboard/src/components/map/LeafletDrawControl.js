// src/components/map/LeafletDrawControl.js
// QuickScout geometry authoring for Leaflet without extra draw packages.
// Supports polygon authoring for area sweep and line authoring for corridor search.

import React, { useState, useCallback, useRef, useMemo, useEffect } from 'react';
import { useMapEvents, Polyline, Polygon, Marker, useMap } from 'react-leaflet';
import { area as turfArea } from '@turf/area';
import { polygon as turfPolygon } from '@turf/helpers';
import L from 'leaflet';

const createVertexIcon = (fillColor) =>
  L.divIcon({
    html: `<div style="width:12px;height:12px;border-radius:50%;background:${fillColor};border:2px solid #fff;box-shadow:0 0 3px rgba(0,0,0,0.4)"></div>`,
    className: '',
    iconSize: [12, 12],
    iconAnchor: [6, 6],
  });

const createStartIcon = () =>
  L.divIcon({
    html: `<div style="width:16px;height:16px;border-radius:50%;background:#28a745;border:2px solid #fff;box-shadow:0 0 6px rgba(40,167,69,0.6)"></div>`,
    className: '',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });

const VERTEX_ICON = createVertexIcon('#3b82f6');
const START_ICON = createStartIcon();
const CLICK_DELAY = 300;

function normalizeInitialPoints(points = []) {
  return (Array.isArray(points) ? points : [])
    .filter((point) => Number.isFinite(Number(point?.lat)) && Number.isFinite(Number(point?.lng)))
    .map((point) => [Number(point.lat), Number(point.lng)]);
}

const LeafletDrawControl = ({
  onAreaChange,
  geometryMode = 'polygon',
  initialPoints = [],
}) => {
  const isLineMode = geometryMode === 'line';
  const minimumPoints = isLineMode ? 2 : 3;
  const [vertices, setVertices] = useState(() => normalizeInitialPoints(initialPoints));
  const [isComplete, setIsComplete] = useState(() => normalizeInitialPoints(initialPoints).length >= minimumPoints);
  const [mousePos, setMousePos] = useState(null);
  const clickTimerRef = useRef(null);
  const pendingClickRef = useRef(null);
  const rafRef = useRef(null);
  const instructionBarRef = useRef(null);
  const map = useMap();

  useEffect(() => {
    const normalized = normalizeInitialPoints(initialPoints);
    setVertices(normalized);
    setIsComplete(normalized.length >= minimumPoints);
    setMousePos(null);
  }, [initialPoints, minimumPoints]);

  useEffect(() => {
    const el = instructionBarRef.current;
    if (el) {
      L.DomEvent.disableClickPropagation(el);
      L.DomEvent.disableScrollPropagation(el);
    }
  }, []);

  const notifyGeometry = useCallback((pts, closed) => {
    if (!onAreaChange) return;

    const points = pts.map(([lat, lng]) => ({ lat, lng }));
    if (isLineMode) {
      onAreaChange(points, 0);
      return;
    }

    if (!closed || pts.length < 3) {
      onAreaChange([], 0);
      return;
    }

    const coordinates = pts.map(([lat, lng]) => [lng, lat]);
    coordinates.push(coordinates[0]);
    try {
      const poly = turfPolygon([coordinates]);
      onAreaChange(points, turfArea(poly));
    } catch {
      onAreaChange(points, 0);
    }
  }, [isLineMode, onAreaChange]);

  const closeGeometry = useCallback((pts) => {
    if (pts.length < minimumPoints) {
      return;
    }
    setIsComplete(true);
    setMousePos(null);
    notifyGeometry(pts, true);
  }, [minimumPoints, notifyGeometry]);

  const addVertex = useCallback((latlng) => {
    setVertices((prev) => {
      const updated = [...prev, [latlng.lat, latlng.lng]];
      if (isLineMode) {
        notifyGeometry(updated, updated.length >= minimumPoints);
      }
      return updated;
    });
  }, [isLineMode, minimumPoints, notifyGeometry]);

  useMapEvents({
    click(e) {
      if (isComplete) return;

      if (isLineMode) {
        addVertex(e.latlng);
        return;
      }

      if (clickTimerRef.current) {
        clearTimeout(clickTimerRef.current);
        clickTimerRef.current = null;
        pendingClickRef.current = null;
        setVertices((prev) => {
          if (prev.length >= 3) {
            closeGeometry(prev);
          }
          return prev;
        });
        return;
      }

      pendingClickRef.current = e.latlng;
      clickTimerRef.current = setTimeout(() => {
        const latlng = pendingClickRef.current;
        if (latlng) {
          addVertex(latlng);
        }
        clickTimerRef.current = null;
        pendingClickRef.current = null;
      }, CLICK_DELAY);
    },
    dblclick(e) {
      if (isComplete) return;
      e.originalEvent?.preventDefault?.();
      e.originalEvent?.stopPropagation?.();

      if (isLineMode) {
        setVertices((prev) => {
          if (prev.length >= minimumPoints) {
            closeGeometry(prev);
          }
          return prev;
        });
      }
    },
    mousemove(e) {
      if (!isComplete && vertices.length > 0) {
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
        rafRef.current = requestAnimationFrame(() => {
          setMousePos([e.latlng.lat, e.latlng.lng]);
        });
      }
    },
  });

  useEffect(() => () => {
    if (clickTimerRef.current) clearTimeout(clickTimerRef.current);
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
  }, []);

  useEffect(() => {
    if (!isComplete) {
      map.doubleClickZoom.disable();
    } else {
      map.doubleClickZoom.enable();
    }

    return () => {
      map.doubleClickZoom.enable();
    };
  }, [isComplete, map]);

  const handleVertexDrag = useCallback((index, e) => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      const { lat, lng } = e.latlng;
      setVertices((prev) => {
        const updated = [...prev];
        updated[index] = [lat, lng];
        notifyGeometry(updated, isComplete);
        return updated;
      });
    });
  }, [isComplete, notifyGeometry]);

  const handleUndo = useCallback(() => {
    setVertices((prev) => {
      const updated = prev.slice(0, -1);
      if (isLineMode) {
        notifyGeometry(updated, updated.length >= minimumPoints);
      }
      return updated;
    });
    if (isComplete) {
      setIsComplete(false);
    }
  }, [isComplete, isLineMode, minimumPoints, notifyGeometry]);

  const handleClear = useCallback(() => {
    setVertices([]);
    setIsComplete(false);
    setMousePos(null);
    if (clickTimerRef.current) {
      clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
    pendingClickRef.current = null;
    if (onAreaChange) onAreaChange([], 0);
  }, [onAreaChange]);

  const handleFinish = useCallback(() => {
    closeGeometry(vertices);
  }, [closeGeometry, vertices]);

  const handleFirstVertexClick = useCallback((e) => {
    e.originalEvent?.stopPropagation?.();
    if (!isLineMode && vertices.length >= 3 && !isComplete) {
      closeGeometry(vertices);
    }
  }, [closeGeometry, isComplete, isLineMode, vertices]);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.ctrlKey && e.key === 'z' && !isComplete && vertices.length > 0) {
        e.preventDefault();
        handleUndo();
      }
      if (e.key === 'Escape' && !isComplete && vertices.length > 0) {
        if (clickTimerRef.current) {
          clearTimeout(clickTimerRef.current);
          clickTimerRef.current = null;
        }
        pendingClickRef.current = null;
        handleClear();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleClear, handleUndo, isComplete, vertices.length]);

  const instruction = useMemo(() => {
    if (isLineMode) {
      if (isComplete) return 'Route complete. Drag points to edit or Reset to redraw.';
      if (vertices.length === 0) return 'Click to place the first route point';
      if (vertices.length < 2) return 'Click to add at least one more route point';
      return 'Click to add route points, then use Finish Route or double-click to lock it';
    }

    if (isComplete) return 'Polygon complete. Click Reset to start over.';
    if (vertices.length === 0) return 'Click to place first point';
    if (vertices.length < 3) return `Click to add points (${vertices.length}/3 min) · Esc to cancel`;
    return 'Click to add points, double-click or click first point to close · Esc to reset';
  }, [isComplete, isLineMode, vertices.length]);

  const previewLine = useMemo(() => {
    if (isComplete || vertices.length === 0 || !mousePos) return null;
    return [vertices[vertices.length - 1], mousePos];
  }, [isComplete, mousePos, vertices]);

  return (
    <>
      <div className="ldc-instruction-bar" ref={instructionBarRef}>
        <span className="ldc-instruction-text">{instruction}</span>
        <div className="ldc-action-group">
          {!isComplete && vertices.length > 0 && (
            <button
              className="ldc-action-btn ldc-action-btn--undo"
              onClick={handleUndo}
              title="Undo last point (Ctrl+Z)"
            >
              Undo
            </button>
          )}
          {!isComplete && vertices.length >= minimumPoints && (
            <button
              className="ldc-action-btn ldc-action-btn--close"
              onClick={handleFinish}
            >
              {isLineMode ? 'Finish Route' : 'Close Polygon'}
            </button>
          )}
          {vertices.length > 0 && (
            <button
              className="ldc-action-btn ldc-action-btn--reset"
              onClick={handleClear}
            >
              Reset
            </button>
          )}
        </div>
      </div>

      {previewLine && (
        <Polyline
          positions={previewLine}
          pathOptions={{
            color: isLineMode ? '#facc15' : '#3b82f6',
            weight: isLineMode ? 3 : 2,
            dashArray: '6 4',
            opacity: 0.6,
          }}
        />
      )}

      {!isComplete && vertices.length >= 2 && (
        <Polyline
          positions={vertices}
          pathOptions={{
            color: isLineMode ? '#facc15' : '#3b82f6',
            weight: isLineMode ? 3 : 2,
            dashArray: isLineMode ? '8 4' : '5 5',
          }}
        />
      )}

      {!isLineMode && isComplete && vertices.length >= 3 && (
        <Polygon
          positions={vertices}
          pathOptions={{
            color: '#3b82f6',
            fillColor: '#3b82f6',
            fillOpacity: 0.15,
            weight: 2,
          }}
        />
      )}

      {isLineMode && isComplete && vertices.length >= 2 && (
        <Polyline
          positions={vertices}
          pathOptions={{
            color: '#facc15',
            weight: 3,
            opacity: 0.9,
          }}
        />
      )}

      {vertices.map((pos, index) => (
        <Marker
          key={`${geometryMode}-${index}`}
          position={pos}
          icon={index === 0 ? START_ICON : VERTEX_ICON}
          draggable={true}
          eventHandlers={
            index === 0
              ? { click: handleFirstVertexClick, drag: (e) => handleVertexDrag(index, e) }
              : { drag: (e) => handleVertexDrag(index, e) }
          }
        />
      ))}
    </>
  );
};

export default LeafletDrawControl;

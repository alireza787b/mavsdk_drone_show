import React, { useEffect, useRef } from 'react';
import mapboxgl from 'mapbox-gl';
import { Color, Matrix4 } from 'three';
import 'mapbox-gl/dist/mapbox-gl.css';

export const routeAltitudeMsl = (point) => point.alt_msl ?? point.altitude ?? point.alt;
export const canRenderRoutes3D = (routes, token) => {
  try {
    return Boolean(token && routes.length && mapboxgl.supported?.()
      && routes.every((route) => route.points.every((point) =>
        Math.abs(point.latitude) < 85 && Number.isFinite(routeAltitudeMsl(point)))));
  } catch { return false; }
};

// Mapbox's Mercator custom-layer contract preserves actual MSL heights rather
// than presenting a tilted ground line as a three-dimensional flight path.
// https://docs.mapbox.com/mapbox-gl-js/example/custom-style-layer/
export function createRouteLayer(routes, bounds) {
  let current = { routes, bounds }, dirty = true, program, shaders = [], buffers = [];
  const camera = new Matrix4();
  const translation = new Matrix4();
  let anchor, positionLocation, matrixLocation, colorLocation;
  const compile = (gl, type, source) => {
    const shader = gl.createShader(type);
    shaders.push(shader);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error('3D shader unavailable');
    return shader;
  };
  const clearBuffers = (gl) => { buffers.forEach((item) => gl.deleteBuffer(item.buffer)); buffers = []; };
  return {
    id: 'mds-trajectory-routes', type: 'custom', renderingMode: '3d',
    setRoutes(nextRoutes, nextBounds) { current = { routes: nextRoutes, bounds: nextBounds }; dirty = true; },
    onAdd(map, gl) {
      program = gl.createProgram();
      gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, `
        uniform mat4 u_matrix; attribute vec3 a_position;
        void main() { gl_Position = u_matrix * vec4(a_position, 1.0); }
      `));
      gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, `
        precision mediump float; uniform vec4 u_color;
        void main() { gl_FragColor = u_color; }
      `));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('3D renderer unavailable');
      positionLocation = gl.getAttribLocation(program, 'a_position');
      matrixLocation = gl.getUniformLocation(program, 'u_matrix');
      colorLocation = gl.getUniformLocation(program, 'u_color');
    },
    render(gl, matrix) {
      if (dirty) {
        clearBuffers(gl);
        const b = current.bounds;
        anchor = mapboxgl.MercatorCoordinate.fromLngLat([(b.minLng + b.maxLng) / 2, (b.minLat + b.maxLat) / 2], 0);
        translation.makeTranslation(anchor.x, anchor.y, anchor.z);
        current.routes.forEach((route) => route.segments.forEach((segment) => {
          const points = segment.map((point) => mapboxgl.MercatorCoordinate.fromLngLat(
            [b.unwrap(point.longitude), point.latitude], routeAltitudeMsl(point),
          ));
          const buffer = gl.createBuffer();
          gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
          // Keep small local coordinates in Float32; global Mercator coordinates
          // would lose sub-metre separation to precision near the equator.
          gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(points.flatMap((point) =>
            [point.x - anchor.x, point.y - anchor.y, point.z - anchor.z])), gl.STATIC_DRAW);
          const color = new Color(route.color).convertLinearToSRGB();
          buffers.push({ buffer, count: points.length, color });
        }));
        dirty = false;
      }
      camera.fromArray(matrix).multiply(translation);
      gl.useProgram(program);
      gl.uniformMatrix4fv(matrixLocation, false, camera.elements);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      buffers.forEach(({ buffer, count, color }) => {
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.enableVertexAttribArray(positionLocation);
        gl.vertexAttribPointer(positionLocation, 3, gl.FLOAT, false, 0, 0);
        gl.uniform4f(colorLocation, color.r, color.g, color.b, 1);
        gl.drawArrays(gl.LINE_STRIP, 0, count);
      });
    },
    onRemove(map, gl) {
      clearBuffers(gl);
      shaders.forEach((shader) => gl.deleteShader(shader));
      shaders = [];
      if (program) gl.deleteProgram(program);
    },
  };
}

export default function TrajectoryMap3D({ routes, bounds, packageKey, fitRequest, token, onUnavailable }) {
  const container = useRef(null), mapRef = useRef(null), layerRef = useRef(null);
  const current = useRef({ routes, bounds, onUnavailable });
  current.current = { routes, bounds, onUnavailable };
  useEffect(() => {
    let map, observer;
    const fit = () => {
      const b = current.current.bounds;
      map?.fitBounds([[b.minLng, b.minLat], [b.maxLng, b.maxLat]],
        { padding: 60, maxZoom: 18, pitch: 55, duration: 0 });
    };
    try {
      map = new mapboxgl.Map({ container: container.current, accessToken: token,
        style: 'mapbox://styles/mapbox/satellite-streets-v12', projection: 'mercator',
        center: [(current.current.bounds.minLng + current.current.bounds.maxLng) / 2,
          (current.current.bounds.minLat + current.current.bounds.maxLat) / 2],
        zoom: 15, pitch: 55, antialias: true });
      mapRef.current = map;
      map.addControl(new mapboxgl.NavigationControl(), 'top-left');
      map.on('error', () => current.current.onUnavailable());
      map.on('webglcontextlost', () => current.current.onUnavailable());
      map.on('load', () => {
        try {
          map.addSource('mds-route-terrain', { type: 'raster-dem',
            url: 'mapbox://mapbox.mapbox-terrain-dem-v1', tileSize: 512, maxzoom: 14 });
          map.setTerrain({ source: 'mds-route-terrain', exaggeration: 1 });
          layerRef.current = createRouteLayer(current.current.routes, current.current.bounds);
          map.addLayer(layerRef.current);
          fit();
          // Terrain tiles establish the ground MSL reference asynchronously.
          // Fit once more when first ready, unless the operator has moved it.
          let touched = false;
          map.on('movestart', (event) => { if (event.originalEvent) touched = true; });
          map.once('idle', () => { if (!touched) fit(); });
        } catch { current.current.onUnavailable(); }
      });
      if (typeof ResizeObserver !== 'undefined') {
        observer = new ResizeObserver(() => map.resize());
        observer.observe(container.current);
      }
    } catch { current.current.onUnavailable(); }
    return () => { observer?.disconnect(); map?.remove(); mapRef.current = null; layerRef.current = null; };
  }, [token]);
  useEffect(() => {
    layerRef.current?.setRoutes(routes, bounds);
    mapRef.current?.triggerRepaint();
  }, [routes, bounds]);
  useEffect(() => {
    if (mapRef.current?.isStyleLoaded()) mapRef.current.fitBounds(
      [[bounds.minLng, bounds.minLat], [bounds.maxLng, bounds.maxLat]],
      { padding: 60, maxZoom: 18, pitch: 55, duration: 0 },
    );
    // Visibility changes alone do not recenter the operator's map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [packageKey, fitRequest]);
  return <div ref={container} className="trajectory-route-review__map trajectory-route-review__map--3d"
    aria-label="Three-dimensional mission map" style={{ width: '100%', height: '100%' }} />;
}

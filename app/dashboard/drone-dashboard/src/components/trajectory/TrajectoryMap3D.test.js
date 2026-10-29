import React from 'react';
import { render } from '@testing-library/react';
import mapboxgl from 'mapbox-gl';
import TrajectoryMap3D, { canRenderRoutes3D, createRouteLayer } from './TrajectoryMap3D';

jest.mock('mapbox-gl', () => ({
  supported: jest.fn(() => true),
  MercatorCoordinate: { fromLngLat: jest.fn(([longitude, latitude], altitude) =>
    ({ x: longitude / 360, y: latitude / 180, z: altitude / 40000000 })) },
  Map: jest.fn(), NavigationControl: jest.fn(),
}));
const bounds = { minLng: 2, maxLng: 2.001, minLat: 48, maxLat: 48.001, unwrap: (x) => x };
const points = [{ longitude: 2, latitude: 48, alt_msl: 100 },
  { longitude: 2.001, latitude: 48.001, alt_msl: 110 }];
const routes = [{ id: '1', color: '#00ff00', points, segments: [points] }];

beforeEach(() => {
  jest.clearAllMocks();
  mapboxgl.supported.mockReturnValue(true);
  mapboxgl.MercatorCoordinate.fromLngLat.mockImplementation(([longitude, latitude], altitude) =>
    ({ x: longitude / 360, y: latitude / 180, z: altitude / 40000000 }));
});

test('3D requires usable altitude, provider credentials, and WebGL; never invents zero altitude', () => {
  expect(canRenderRoutes3D(routes, 'token')).toBe(true);
  expect(canRenderRoutes3D(routes, '')).toBe(false);
  expect(canRenderRoutes3D([{ points: [{ latitude: 48 }] }], 'token')).toBe(false);
  expect(canRenderRoutes3D([{ points: [{ latitude: 90, alt_msl: 100 }] }], 'token')).toBe(false);
  mapboxgl.supported.mockReturnValueOnce(false);
  expect(canRenderRoutes3D(routes, 'token')).toBe(false);
});

test('custom path geometry preserves MSL, uses local floats and disposes its GPU resources', () => {
  const gl = { VERTEX_SHADER: 1, FRAGMENT_SHADER: 2, COMPILE_STATUS: 3, LINK_STATUS: 4,
    ARRAY_BUFFER: 5, STATIC_DRAW: 6, BLEND: 7, SRC_ALPHA: 8, ONE_MINUS_SRC_ALPHA: 9,
    FLOAT: 10, LINE_STRIP: 11 };
  ['createShader', 'createProgram', 'createBuffer', 'getUniformLocation'].forEach((name) => { gl[name] = jest.fn(() => ({})); });
  ['shaderSource', 'compileShader', 'attachShader', 'linkProgram', 'bindBuffer', 'bufferData',
    'deleteBuffer', 'deleteShader', 'deleteProgram', 'useProgram', 'uniformMatrix4fv',
    'enable', 'blendFunc', 'enableVertexAttribArray', 'vertexAttribPointer', 'uniform4f', 'drawArrays']
    .forEach((name) => { gl[name] = jest.fn(); });
  gl.getShaderParameter = jest.fn(() => true);
  gl.getProgramParameter = jest.fn(() => true);
  gl.getAttribLocation = jest.fn(() => 0);
  const layer = createRouteLayer(routes, bounds);
  layer.onAdd({}, gl);
  layer.render(gl, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  expect(mapboxgl.MercatorCoordinate.fromLngLat).toHaveBeenCalledWith([2, 48], 100);
  const vertices = gl.bufferData.mock.calls[0][1];
  expect(Math.abs(vertices[0])).toBeLessThan(.00001);
  expect(vertices[2]).toBeCloseTo(100 / 40000000, 10);
  expect(vertices[5]).toBeGreaterThan(vertices[2]);
  expect(gl.drawArrays).toHaveBeenCalledWith(gl.LINE_STRIP, 0, 2);
  layer.onRemove({}, gl);
  expect(gl.deleteBuffer).toHaveBeenCalledTimes(1);
  expect(gl.deleteShader).toHaveBeenCalledTimes(2);
  expect(gl.deleteProgram).toHaveBeenCalledTimes(1);
});

test('renderer startup failure requests a 2D fallback, not a broken map or retry loop', () => {
  mapboxgl.Map.mockImplementation(() => { throw new Error('No WebGL context'); });
  const onUnavailable = jest.fn();
  render(<TrajectoryMap3D routes={routes} bounds={bounds} packageKey="pkg"
    fitRequest={0} token="token" onUnavailable={onUnavailable} />);
  expect(onUnavailable).toHaveBeenCalledTimes(1);
});

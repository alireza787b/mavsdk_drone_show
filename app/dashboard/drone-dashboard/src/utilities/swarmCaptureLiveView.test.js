import { captureLivePositions, captureViewReference } from './swarmCaptureLiveView';
// Geodesy's ellipsoidal delta is exercised with real PX4 coordinates by the
// built-browser SITL check. This unit boundary isolates source eligibility.
jest.mock('geodesy/latlon-nvector-ellipsoidal.js', () => class {
  deltaTo() { return { north: 5, east: 2, down: -999 }; }
});
const row = { hw_id: 2, position_lat: 35.1, position_long: 51.1, position_alt: 120.7,
  global_position_valid: true, position_source: 'global_position_int', telemetry_available: true,
  global_position_timestamp_ms: 1000, global_position_age_ms: 100, relative_altitude_m: -999 };
const reference = { latitude: 35, longitude: 51, altitude_msl_m: 120 };
test('an unavailable leader origin never becomes a synthetic zero-coordinate reference', () => {
  expect(captureViewReference({ ...row, position_lat: 0, position_long: 0 }, '2')).toBeNull();
  expect(captureViewReference({ ...row, global_position_valid: false }, '2')).toBeNull();
  expect(captureViewReference(row, '1')).toBeNull();
  expect(captureLivePositions({ 2: row }, ['2'], null, { 2: 0 })).toEqual([]);
});
test('live rendering uses common MSL and never home-relative height', () => {
  const [point] = captureLivePositions({ 2: row }, ['2'], reference, { 2: 200 });
  expect(point).toMatchObject({ id: '2', north: 5, east: 2, stale: false });
  expect(point.up).toBeCloseTo(.7);
});
test('frozen, delayed and unavailable samples stay explicit even while HTTP succeeds', () => {
  expect(captureLivePositions({ 2: row }, ['2'], reference, { 2: 5000 })[0].stale).toBe(true);
  expect(captureLivePositions({ 2: row }, ['2'], reference, { 2: 0 }, true)[0].stale).toBe(true);
  expect(captureLivePositions({ 2: { ...row, telemetry_available: false } }, ['2'], reference, { 2: 0 })[0].stale).toBe(true);
});
test.each([{ position_alt: null }, { position_source: 'gps_raw_int' }, { global_position_valid: false }, { hw_id: 3 }])(
  'no invented altitude, GPS fallback or wrong identity: %s', patch => {
    expect(captureLivePositions({ 2: { ...row, ...patch } }, ['2'], reference, { 2: 0 })).toEqual([]);
  });

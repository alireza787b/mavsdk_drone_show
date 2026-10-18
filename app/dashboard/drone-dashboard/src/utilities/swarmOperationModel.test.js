import { memberFlightState, movementSummary, takeoffTargets } from './swarmOperationModel';

const ground = { hw_id: '1', available: true, armed: false, relative_altitude_m: 0 };
const air = { hw_id: '2', available: true, armed: true, relative_altitude_m: 5 };
test('armed alone and absolute altitude are not airborne', () => {
  expect(memberFlightState({ available: true, armed: true })).toBe('Armed');
  expect(memberFlightState({ ...air, altitude_report: { source: 'absolute_msl', display_m: 1200 } })).toBe('Armed');
  expect(memberFlightState({ ...air, available: false })).toBe('Unknown');
  expect(memberFlightState(air)).toBe('Airborne');
});
test('takeoff retries explicitly select only grounded aircraft and never omit unknowns', () => {
  expect(takeoffTargets([ground, air])).toEqual(['1']);
  expect(takeoffTargets([air, { ...ground, available: false }])).toEqual([]);
  expect(takeoffTargets([air])).toEqual([]);
});
test('positive vertical offset is above in both frames', () => {
  expect(movementSummary({ follow: '1', frame: 'body', offset_x: -6, offset_z: 2 })).toBe('→ Drone 1 · 6 m behind · 2 m above');
});

import { holdNodeStatus, memberFlightState, movementSummary, takeoffTargets } from './swarmOperationModel';

const ground = { hw_id: '1', available: true, armed: false, landed_state: 1, relative_altitude_m: 0 };
const air = { hw_id: '2', available: true, armed: true, landed_state: 2, relative_altitude_m: -5 };
test('armed alone and absolute altitude are not airborne', () => {
  expect(memberFlightState({ available: true, armed: true })).toBe('Armed');
  expect(memberFlightState({ ...air, landed_state: undefined, altitude_report: { source: 'absolute_msl', display_m: 1200 } })).toBe('Armed');
  expect(memberFlightState({ ...air, available: false })).toBe('Unknown');
  expect(memberFlightState(air)).toBe('Airborne');
  expect(memberFlightState({ ...ground, landed_state: undefined })).toBe('Disarmed');
});
test('takeoff retries explicitly select only grounded aircraft and never omit unknowns', () => {
  expect(takeoffTargets([ground, air])).toEqual(['1']);
  expect(takeoffTargets([air, { ...ground, available: false }])).toEqual([]);
  expect(takeoffTargets([air])).toEqual([]);
});
test('positive vertical offset is above in both frames', () => {
  expect(movementSummary({ follow: '1', frame: 'body', offset_x: -6, offset_z: 2 })).toBe('→ Drone 1 · 6 m behind · 2 m above');
});

test('Hold labels require terminal facts and compatible live aircraft state', () => {
  const held = { action_result: { success: true, final_vehicle_state: { outcome: 'held' } } };
  const disarmed = { action_result: { success: true, final_vehicle_state: { outcome: 'disarmed' } } };
  expect(holdNodeStatus({ ...air, flight_mode: 0x03040000 }, held).label).toBe('Held');
  expect(holdNodeStatus(ground, disarmed).label).toBe('Grounded');
  expect(holdNodeStatus({ ...ground, landed_state: undefined }, disarmed).label).toBe('Disarmed');
  expect(holdNodeStatus(air, held).label).toBe('Hold unconfirmed');
  expect(holdNodeStatus(air).label).toBe('Hold unconfirmed');
  expect(holdNodeStatus({ ...air, available: false }, held).label).toBe('Hold unconfirmed');
});

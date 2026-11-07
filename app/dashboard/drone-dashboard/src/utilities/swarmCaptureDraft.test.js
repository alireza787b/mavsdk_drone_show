import { createSwarmCaptureRequest, deriveSwarmCaptureDraft, swarmCaptureError } from './swarmCaptureDraft';

const assignments = [
  { hw_id: '1', follow: '0', frame: 'ned', offset_x: 0, offset_y: 0, offset_z: 0 },
  { hw_id: '2', follow: '1', frame: 'ned', offset_x: 6, offset_y: 0, offset_z: 2 },
  { hw_id: '3', follow: '2', frame: 'ned', offset_x: 3, offset_y: 0, offset_z: 1 },
  { hw_id: '4', follow: '0', frame: 'ned', offset_x: 0, offset_y: 0, offset_z: 0 },
];
const snapshot = { observations: {
  1: { north_m: 0, east_m: 0, planned_up_m: 0, heading_deg: 90 },
  2: { north_m: 6, east_m: 2, planned_up_m: 2, heading_deg: 180 },
  3: { north_m: 9, east_m: 4, planned_up_m: 3, heading_deg: 270 },
} };

test('NED capture keeps planned heights and unrelated clusters', () => {
  const result = deriveSwarmCaptureDraft(assignments, snapshot, { leaderId: '1', frame: 'ned', heightMode: 'keep' });
  expect(result.assignments[1]).toMatchObject({ offset_x: 6, offset_y: 2, offset_z: 2, follow: '1' });
  expect(result.assignments[2]).toMatchObject({ offset_x: 3, offset_y: 2, offset_z: 1, follow: '2' });
  expect(result.assignments[3]).toEqual(assignments[3]);
  expect(assignments[1].offset_y).toBe(0);
});

test('Body uses each frozen parent heading and Same height zeroes every edge', () => {
  const result = deriveSwarmCaptureDraft(assignments, snapshot, { leaderId: '1', frame: 'body', heightMode: 'level' });
  expect(result.assignments[1].offset_x).toBeCloseTo(2);
  expect(result.assignments[1].offset_y).toBeCloseTo(-6);
  expect(result.assignments[2].offset_x).toBeCloseTo(-3);
  expect(result.assignments[2].offset_y).toBeCloseTo(-2);
  expect(result.assignments.filter((entry) => entry.hw_id !== '4').every((entry) => entry.offset_z === 0)).toBe(true);
});

test('reroot reverses the ancestor path without flattening other relay branches', () => {
  const source = [...assignments, { ...assignments[2], hw_id: '5', follow: '2' }];
  const captured = { observations: { ...snapshot.observations, 5: { north_m: 8, east_m: 5, planned_up_m: 4, heading_deg: 0 } } };
  const result = deriveSwarmCaptureDraft(source, captured, { leaderId: '3', frame: 'ned', heightMode: 'keep' });
  expect(result.assignments.map((entry) => [entry.hw_id, entry.follow])).toEqual([
    ['1', '2'], ['2', '3'], ['3', '0'], ['4', '0'], ['5', '2'],
  ]);
  expect(result.assignments[0]).toMatchObject({ offset_x: -6, offset_y: -2, offset_z: -2 });
  expect(result.assignments[1]).toMatchObject({ offset_x: -3, offset_y: -2, offset_z: -1 });
});

test('missing Body heading blocks reinterpretation instead of inventing North', () => {
  const captured = { observations: { ...snapshot.observations, 1: { ...snapshot.observations[1], heading_deg: null } } };
  expect(() => deriveSwarmCaptureDraft(assignments, captured, { leaderId: '1', frame: 'body', heightMode: 'keep' })).toThrow('heading unavailable');
  expect(() => deriveSwarmCaptureDraft(assignments, captured, { leaderId: '1', frame: 'ned', heightMode: 'keep' })).not.toThrow();
});

test('structured errors name the affected aircraft', () => {
  expect(swarmCaptureError({ response: { data: { detail: { code: 'stale', hw_id: '2', message: 'Position is stale.' } } } })).toBe('H2: Position is stale.');
});

test('Current heights require native capability and use estimated shared Up, not the plan', () => {
  const captured = { ...snapshot, current_heights_available: true, observations: Object.fromEntries(
    Object.entries(snapshot.observations).map(([id, observation]) => [id, { ...observation, current_up_m: Number(id) * .5 }])) };
  const result = deriveSwarmCaptureDraft(assignments, captured, { leaderId: '3', frame: 'body', heightMode: 'current' });
  expect(result.assignments[0].offset_z).toBe(-.5);
  expect(result.assignments[1].offset_z).toBe(-.5);
  expect(result.assignments[3]).toEqual(assignments[3]);
  expect(() => deriveSwarmCaptureDraft(assignments, { ...captured, current_heights_available: false },
    { leaderId: '3', frame: 'ned', heightMode: 'current' })).toThrow('settled airborne');
  captured.observations[2].current_up_m = null;
  expect(() => deriveSwarmCaptureDraft(assignments, captured,
    { leaderId: '3', frame: 'ned', heightMode: 'current' })).toThrow('current height unavailable');
});

test('sole cluster needs no selection; multiple clusters preserve context, never silently choose', () => {
  const a = { id: '1', drones: assignments.slice(0, 3) };
  const b = { id: '4', drones: [{ ...assignments[0], hw_id: '4' }, { ...assignments[1], hw_id: '5', follow: '4' }] };
  expect(createSwarmCaptureRequest({ clusters: [a] }, assignments, 'r').clusterId).toBe('1');
  expect(createSwarmCaptureRequest({ clusters: [a, b] }, assignments, 'r').clusterId).toBeNull();
  expect(createSwarmCaptureRequest({ clusters: [a, b] }, assignments, 'r', '4').clusterId).toBe('4');
  expect(createSwarmCaptureRequest({ clusters: [] }, assignments, 'r')).toBeNull();
});

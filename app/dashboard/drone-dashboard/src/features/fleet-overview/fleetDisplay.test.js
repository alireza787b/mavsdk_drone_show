import { filterFleetAircraft, groupFleetAircraft, renderedFleetAircraft } from './fleetDisplay';

const rows = [
  { id: '1', raw: {}, availability: { available: true }, position: { current: true }, flightState: 'Grounded' },
  { id: '2', raw: {}, availability: { available: false }, position: { current: false }, flightState: 'Unknown', attention: true },
  { id: '3', raw: {}, availability: { available: true }, position: { current: true }, flightState: 'Airborne' },
];
test('map rendered identities omit only unavailable positions, not command recipients', () => {
  expect(renderedFleetAircraft(rows,'board')).toBe(rows);
  expect(renderedFleetAircraft(rows,'list')).toBe(rows);
  expect(renderedFleetAircraft(rows,'map').map(row => row.id)).toEqual(['1','3']);
  expect(rows).toHaveLength(3);
});
test('available default and selected filter do not mutate membership', () => {
  const selectedIds = new Set(['2']);
  expect(filterFleetAircraft(rows).map((row) => row.id)).toEqual(['1', '3']);
  expect(filterFleetAircraft(rows, { filter: 'selected', selectedIds })).toEqual([rows[1]]);
  expect([...selectedIds]).toEqual(['2']);
  expect(filterFleetAircraft(rows, { filter: 'available', query: 'anything', matches: () => false })).toEqual([]);
});
test('grouping is display only and emits each visible identity once', () => {
  const clusters = [{ id: 'a', label: 'Alpha', drones: [{ hw_id: '1' }, { hw_id: '2' }] },
    { id: 'b', label: 'Bravo', drones: [{ hw_id: '2' }] }];
  expect(groupFleetAircraft(rows, clusters, false)).toEqual([{ id: 'fleet', label: '', aircraft: rows }]);
  expect(groupFleetAircraft(rows, clusters, true)).toEqual([
    { id: 'a', label: 'Alpha', aircraft: rows.slice(0, 2) },
    { id: 'unassigned', label: 'Other aircraft', aircraft: [rows[2]] },
  ]);
  expect(groupFleetAircraft([rows[2]], clusters, true)[0].label).toBe('Other aircraft');
});

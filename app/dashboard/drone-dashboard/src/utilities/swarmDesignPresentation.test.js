import { aircraftIdentity, buildAircraftLabels, formatFormationDistance } from './swarmDesignPresentation';

test('missing callsigns and position IDs remain hardware-anchored without invented slots', () => {
  expect(buildAircraftLabels([{ hw_id: 3 }, { hw_id: 4, alias: 'Eagle' }])).toEqual({ 3: 'H3', 4: 'Eagle' });
  expect(aircraftIdentity({ hw_id: 3 })).toBe('H3');
  expect(aircraftIdentity({ hw_id: 3, pos_id: 9 })).toBe('H3 · P9');
});
test('duplicate names are unambiguous and optional IDs include current position ID', () => {
  const rows = [{ hw_id: 1, pos_id: 2, callsign: 'Scout' }, { hw_id: 2, pos_id: 4, callsign: 'SCOUT' }];
  expect(buildAircraftLabels(rows)).toEqual({ 1: 'Scout · H1', 2: 'SCOUT · H2' });
  expect(buildAircraftLabels(rows, true)[1]).toBe('Scout · H1 · P2');
});
test.each([[6, '6'], [0.920493, '0.92'], [125.462, '125.5'], [1200.3, '1200'], [-0.0001, '0'], ['', ''], ['-', '-']])('readable distance %s → %s', (value, display) => {
  expect(formatFormationDistance(value)).toBe(display);
});

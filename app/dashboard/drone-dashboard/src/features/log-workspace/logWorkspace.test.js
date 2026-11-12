import { historyQuery, utcInput } from './logWorkspace';
test('UTC entry is explicit and independent of browser timezone', () => {
  expect(utcInput('2026-11-12T23:59')).toBe('2026-11-12T23:59:00.000Z');
  expect(historyQuery({ start: '2026-11-12T23:59Z', end: '2026-11-13T00:01Z' })).toEqual(expect.objectContaining({ since: '2026-11-12T23:59:00.000Z', until: '2026-11-13T00:01:00.000Z' }));
  expect(() => utcInput('2026-02-30T00:00Z')).toThrow();
  expect(() => utcInput('2026-11-12T00:00+03:00')).toThrow(/UTC/);
  expect(() => historyQuery({ start: '2026-11-13T00:01Z', end: '2026-11-12T23:59Z' })).toThrow();
});

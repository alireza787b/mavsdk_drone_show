import {
  areGitRevisionsEquivalent,
  buildSuggestedHwIds,
  formatCompactDroneIdentity,
  formatDroneLabel,
  formatShowSlotLabel,
  getIdentityDoctrineCopy,
  getDuplicateAssignments,
  getOnlineDroneCount,
  normalizeRuntimeIp,
  normalizeDroneConfigData,
  toBackendConfigDrone,
} from './missionIdentityUtils';

describe('missionIdentityUtils', () => {
  test('normalizeDroneConfigData canonicalizes mixed numeric/string IDs', () => {
    const normalized = normalizeDroneConfigData([
      { hw_id: 1, pos_id: '01', ip: '10.0.0.1', mavlink_port: 14550, serial_port: '', baudrate: 0 },
      { hw_id: '2', pos_id: 2, ip: '10.0.0.2', mavlink_port: '14551', serial_port: '/dev/ttyS0', baudrate: '57600' },
    ]);

    expect(normalized).toEqual([
      expect.objectContaining({ hw_id: '1', pos_id: '1', mavlink_port: '14550', baudrate: '0' }),
      expect.objectContaining({ hw_id: '2', pos_id: '2', mavlink_port: '14551', baudrate: '57600' }),
    ]);
  });

  test('buildSuggestedHwIds returns numeric gaps and next sequential slot', () => {
    expect(buildSuggestedHwIds([
      { hw_id: '1' },
      { hw_id: 3 },
      { hw_id: '4' },
    ])).toEqual(['2', '5']);
  });

  test('formatDroneLabel and formatShowSlotLabel normalize ids for operator-facing copy', () => {
    expect(formatDroneLabel('07')).toBe('Drone 7');
    expect(formatShowSlotLabel(3)).toBe('Show Slot 3');
    expect(formatDroneLabel(null)).toBe('Drone');
    expect(formatShowSlotLabel(undefined)).toBe('Show Slot');
  });

  test('formatCompactDroneIdentity exposes the standard Pn|Hm shorthand', () => {
    expect(formatCompactDroneIdentity('03', '7')).toBe('P3|H7');
    expect(formatCompactDroneIdentity('03', null)).toBe('P3');
    expect(formatCompactDroneIdentity(null, '7')).toBe('H7');
  });

  test('getIdentityDoctrineCopy keeps subsystem identity rules explicit', () => {
    expect(getIdentityDoctrineCopy('swarm-design')).toEqual(
      expect.objectContaining({
        title: expect.stringContaining('Follow chains stay on hardware'),
        chips: expect.arrayContaining([
          expect.objectContaining({ label: 'P', detail: 'slot' }),
          expect.objectContaining({ label: 'H', detail: 'hardware' }),
          expect.objectContaining({ label: 'Swarm', detail: 'Follow = H' }),
        ]),
      })
    );
    expect(getIdentityDoctrineCopy('quickscout')).toEqual(
      expect.objectContaining({
        chips: expect.arrayContaining([
          expect.objectContaining({ label: 'Launch', detail: 'P -> H' }),
        ]),
      })
    );
  });

  test('normalizeRuntimeIp filters placeholder heartbeat IP values', () => {
    expect(normalizeRuntimeIp('unknown')).toBe('');
    expect(normalizeRuntimeIp(' 172.18.0.2 ')).toBe('172.18.0.2');
  });

  test('areGitRevisionsEquivalent accepts matching short and full SHAs', () => {
    expect(areGitRevisionsEquivalent('540beb77', '540beb77b0d5f727a022e04f5c612c23a9a1a459')).toBe(true);
    expect(areGitRevisionsEquivalent('abc1234', 'def1234')).toBe(false);
  });

  test('getDuplicateAssignments detects mixed-type duplicate hardware and position IDs', () => {
    const duplicates = getDuplicateAssignments([
      { hw_id: 1, pos_id: 1 },
      { hw_id: '1', pos_id: '2' },
      { hw_id: 3, pos_id: '2' },
    ]);

    expect(duplicates.duplicateHwIds).toEqual([
      { hw_id: '1', pos_ids: ['1', '2'] },
    ]);
    expect(duplicates.duplicatePosIds).toEqual([
      { pos_id: '2', hw_ids: ['1', '3'] },
    ]);
  });

  test('getOnlineDroneCount prefers last_heartbeat and ignores stale drones', () => {
    const now = Date.now();
    const heartbeats = {
      '1': { last_heartbeat: now - 5_000 },
      '2': { timestamp: now - 50_000 },
      '3': { last_heartbeat: now - 15_000 },
    };

    expect(getOnlineDroneCount(heartbeats)).toBe(2);
  });

  test('toBackendConfigDrone coerces numeric identity fields back to integers', () => {
    expect(toBackendConfigDrone({
      hw_id: '7',
      pos_id: '9',
      ip: '10.0.0.7',
      mavlink_port: '14557',
      serial_port: '',
      baudrate: '0',
    })).toEqual({
      hw_id: 7,
      pos_id: 9,
      ip: '10.0.0.7',
      mavlink_port: 14557,
      serial_port: '',
      baudrate: 0,
    });
  });
});

import {
  buildMissionSlotStatusPresentation,
  determineMissionSlotStatus,
} from './missionSlotStatus';

describe('missionSlotStatus', () => {
  test('detects fully aligned mission slot sources', () => {
    expect(determineMissionSlotStatus('01', '1', '1')).toMatchObject({
      configStr: '1',
      assignedStr: '1',
      autoStr: '1',
      allMatch: true,
      anyMismatch: false,
    });
  });

  test('builds a compact verified presentation when all sources agree', () => {
    expect(buildMissionSlotStatusPresentation('1', '1', '1')).toMatchObject({
      tone: 'verified',
      headline: 'Slot verified',
      chips: [
        expect.objectContaining({ label: 'Cfg', value: 'P1', tone: 'aligned' }),
        expect.objectContaining({ label: 'HB', value: 'P1', tone: 'aligned' }),
        expect.objectContaining({ label: 'Auto', value: 'P1', tone: 'aligned' }),
      ],
    });
  });

  test('surfaces a pending state when live slot data has not arrived yet', () => {
    expect(buildMissionSlotStatusPresentation('4', '', '')).toMatchObject({
      tone: 'pending',
      headline: 'Awaiting runtime slot check',
      chips: [
        expect.objectContaining({ label: 'Cfg', value: 'P4', tone: 'aligned' }),
      ],
    });
  });

  test('surfaces mismatch actions only for differing live sources', () => {
    expect(buildMissionSlotStatusPresentation('2', '5', '2')).toMatchObject({
      tone: 'review',
      headline: 'Slot mismatch',
      actions: {
        acceptAutoValue: '',
        acceptAssignedValue: '5',
      },
      chips: [
        expect.objectContaining({ label: 'Cfg', value: 'P2', tone: 'configured' }),
        expect.objectContaining({ label: 'HB', value: 'P5', tone: 'attention' }),
        expect.objectContaining({ label: 'Auto', value: 'P2', tone: 'aligned' }),
      ],
    });
  });

  test('marks missing auto-detect as unavailable instead of mismatch noise', () => {
    expect(buildMissionSlotStatusPresentation('3', '3', '0')).toMatchObject({
      tone: 'verified',
      headline: 'Slot confirmed',
      footnote: 'Auto-detect is unavailable in the current runtime.',
      chips: [
        expect.objectContaining({ label: 'Cfg', value: 'P3' }),
        expect.objectContaining({ label: 'HB', value: 'P3' }),
      ],
    });
  });
});

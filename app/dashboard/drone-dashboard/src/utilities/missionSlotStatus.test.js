import {
  buildMissionSlotStatusPresentation,
  determineMissionSlotStatus,
  getMissionSlotEvidence,
} from './missionSlotStatus';
import { attachDroneRuntimeClock } from '../constants/fieldMappings';

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
      headline: 'Slot not checked',
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
      footnote: '',
      chips: [
        expect.objectContaining({ label: 'Cfg', value: 'P3' }),
        expect.objectContaining({ label: 'HB', value: 'P3' }),
      ],
    });
  });

  test('never treats the unseen configured row or stale slot as a live mismatch', () => {
    const now = Date.now();
    for (const heartbeat of [null, { pos_id: 0, last_heartbeat: 0, presence: { state: 'never_seen' } },
      { pos_id: 0, last_heartbeat: now - 60000, presence: { state: 'offline' } },
      { pos_id: 2, last_heartbeat: null }]) {
      const evidence = getMissionSlotEvidence(heartbeat, now);
      expect(evidence).toMatchObject({ fresh: false, assignedPosId: '', autoPosId: '' });
      expect(buildMissionSlotStatusPresentation('1', evidence.assignedPosId, evidence.autoPosId))
        .toMatchObject({ tone: 'pending', actions: {} });
    }
  });

  test('slot authority requires a recent heartbeat, not only recent telemetry', () => {
    const now = Date.now();
    expect(getMissionSlotEvidence({ pos_id: 0, last_heartbeat: now,
      presence: { fresh: true, telemetry_recent: true, heartbeat_recent: false } }, now).fresh).toBe(false);
    const actualZero = getMissionSlotEvidence({ pos_id: 0, last_heartbeat: now }, now);
    expect(actualZero).toMatchObject({ fresh: true, assignedPosId: '0' });
    expect(determineMissionSlotStatus('0', actualZero.assignedPosId, '')).toMatchObject({
      configAssignedMatchNoAuto: true, anyMismatch: false,
    });
  });

  test('uses GCS time, then ages a retained presence snapshot when refresh fails', () => {
    const browserNow = Date.now(), serverNow = browserNow - 3600000;
    const heartbeat = attachDroneRuntimeClock({ pos_id: 2, last_heartbeat: serverNow - 1000,
      presence: { state: 'live', heartbeat_recent: true, thresholds: { live_sec: 10 } } },
    { receivedAtMs: browserNow, serverNowMs: serverNow });
    expect(getMissionSlotEvidence(heartbeat, browserNow)).toMatchObject({ fresh: true, assignedPosId: '2' });
    expect(getMissionSlotEvidence(heartbeat, browserNow + 11000)).toMatchObject({ fresh: false, assignedPosId: '' });
  });
});
